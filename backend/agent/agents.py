"""Specialist agents for G-Axis multi-agent system.

Each agent has a focused role, system prompt, and tool set:
- Perceiver: Screenshot → structured page understanding
- Orchestrator: Task decomposition and agent delegation
- Navigator: Page navigation (click, scroll, navigate, etc.)
- FormFiller: Form interaction (type, select, submit)
- DataExtractor: Structured data extraction from pages
- Verifier: Task completion validation
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from google import genai
from google.genai import types

from backend.agent.base import BaseAgent, AGENT_MODEL, VISION_MODEL
from backend.agent.state import AgentState, SubTask
from backend.tools.definitions import (
    PLANNER_TOOLS, ORCHESTRATOR_TOOLS, NAVIGATOR_TOOLS, FORM_FILLER_TOOLS,
    DATA_EXTRACTOR_TOOLS, VERIFIER_TOOLS,
)
from backend.tools.executor import ToolExecutor
from backend.observability.logger import obs

logger = logging.getLogger("gaxis.agents")


# ─── PERCEIVER ─────────────────────────────────────────────────

PERCEIVER_SYSTEM = """You are the Perceiver for G-Axis, an AI browser agent.

Your job: analyze a browser screenshot and identify ALL interactive elements on the page.

For each element provide:
- "id": short unique identifier (e.g., "search_input", "login_btn", "nav_home")
- "type": one of "button", "link", "input", "dropdown", "checkbox", "tab", "menu_item", "icon_button", "other"
- "text": visible text on/near the element
- "description": what this element does
- "x": center x coordinate (pixels from left)
- "y": center y coordinate (pixels from top)
- "width": approximate width
- "height": approximate height
- "interactable": true if clickable/typeable
- "is_sensitive": true if password/payment/PII field

Also provide:
- "page_summary": 1-2 sentence summary of the page
- "current_state": what state the page is in

The viewport size varies. Use the DOM element coordinates when available for precise positions.

Return ONLY valid JSON:
{"page_summary": "...", "current_state": "...", "elements": [...]}"""


class PerceiverAgent(BaseAgent):
    """Analyzes screenshots to build page understanding.

    Does NOT use tools — just vision analysis via structured JSON output.
    """
    _model_override = VISION_MODEL  # Pro for accurate screenshot analysis

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="perceiver",
            client=client,
            tool_executor=tool_executor,
            tools=[],  # No tools — pure perception
            system_prompt=PERCEIVER_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        """Analyze the current screenshot and update page context."""
        state.status = "perceiving"

        if not state.page.screenshot_b64:
            logger.warning("Perceiver: no screenshot available")
            return state

        image_bytes = base64.b64decode(state.page.screenshot_b64)

        prompt = f"Analyze this browser screenshot. URL: {state.page.url}, Title: {state.page.title}"

        # Add DOM elements as additional context for more accurate coordinates
        if state.page.dom_elements:
            dom_hint = "\n\nDOM HINTS (use these for precise coordinates):\n"
            for el in state.page.dom_elements[:30]:
                dom_hint += (
                    f"  {el.get('tag', '?')} \"{(el.get('text', '') or '')[:50]}\" "
                    f"at ({el.get('x', 0)},{el.get('y', 0)}) "
                    f"{el.get('width', 0)}x{el.get('height', 0)}\n"
                )
            prompt += dom_hint

        contents = [
            types.Content(parts=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                types.Part.from_text(text=prompt),
            ])
        ]

        # Retry on rate limit
        for attempt in range(4):
            try:
                response = await self.client.aio.models.generate_content(
                    model=VISION_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=0.1,
                        max_output_tokens=4096,
                        response_mime_type="application/json",
                    ),
                )
                break
            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < 3:
                    wait = min(2 ** attempt * 5, 30)
                    logger.warning(f"Perceiver rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                else:
                    raise

        parsed = _parse_json(response.text or "{}")

        state.page.page_summary = parsed.get("page_summary", "")
        state.page.current_state = parsed.get("current_state", "")
        state.page.elements = parsed.get("elements", [])
        state.page.timestamp = time.time()

        obs.action("perceiver", "analyze",
                   target=state.page.url[:50],
                   reason=state.page.page_summary[:60],
                   success=True,
                   elements=len(state.page.elements))
        return state


# ─── PLANNER AGENT ─────────────────────────────────────────────

PLANNER_SYSTEM = """You are the Planner for G-Axis — an AI that decomposes user tasks into subtasks.

YOUR ONLY JOB: Break a task into an ordered sequence of subtasks, each assigned to a specialist.

SPECIALISTS:
- navigator: clicks, types, navigates pages, fills forms
- data_extractor: reads and extracts structured data from pages
- verifier: confirms task completed successfully

TASK TYPES AND STRATEGIES:

1. SIMPLE ACTION (calendar, email, form):
   → navigator handles everything (1-2 subtasks + verifier)

2. RESEARCH (itinerary, comparison, analysis):
   → navigator: search → navigate to sources (1 per source)
   → data_extractor: extract key information
   → navigator: create document with synthesized content
   → verifier: confirm deliverable

3. MULTI-STEP WORKFLOW:
   → Break into sequential subtasks, one per phase

RULES:
- Return subtasks via plan_task() tool
- Each subtask = one focused action for one specialist
- Include a verifier subtask at the end
- Navigator handles both navigation AND form filling
- Keep instructions specific: exact URLs, field names, values
- For research: read AT LEAST 3 sources before synthesizing
"""


class PlannerAgent(BaseAgent):
    """Task decomposition — breaks complex tasks into ordered subtasks.

    Responsibilities: strategy, subtask planning, sequencing
    Does NOT: delegate, supervise, recover from errors
    """

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="planner",
            client=client,
            tool_executor=tool_executor,
            tools=PLANNER_TOOLS,
            system_prompt=PLANNER_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        """Decompose the task into subtasks. Runs ONCE at the start."""
        state.status = "orchestrating"

        from datetime import datetime
        today = datetime.now().strftime("%A, %B %d, %Y")

        context = self._build_page_context_prompt(state)

        # Memory hints for better planning
        memory_text = ""
        if state.memory_context:
            if state.memory_context.get("similar_experiences"):
                memory_text = "\nSIMILAR PAST TASKS:\n"
                for exp in state.memory_context["similar_experiences"][:3]:
                    memory_text += f"  - \"{exp.get('instruction', '?')}\" → {exp.get('result', '?')}\n"

        prompt = (
            f"TASK: {state.instruction}\n"
            f"TODAY: {today}\n\n"
            f"{context}\n"
            f"{memory_text}\n"
            f"Decompose this task into subtasks using plan_task()."
        )

        state, _ = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=1, include_screenshot=True,
        )

        return state


# ─── ORCHESTRATOR ──────────────────────────────────────────────

ORCHESTRATOR_SYSTEM = """You are the Orchestrator for G-Axis — you execute subtasks by delegating to specialists.

YOUR ONLY JOB: Take the NEXT pending subtask and delegate it to the right specialist.

TOOLS: delegate() to assign work, task_failed() if stuck.

FLOW:
1. Look at SUBTASK PROGRESS to find the next pending subtask.
2. Delegate it to the specialist with clear, specific instructions.
3. After it completes, the system advances to the next subtask automatically.

RULES:
- ONE delegation per turn. Never skip subtasks.
- Include specific details: URLs, field names, values, step-by-step instructions.
- If a subtask failed, try an alternative approach before calling task_failed.
- If AVAILABLE SKILLS provide step-by-step browser instructions, copy them VERBATIM.
- The planner already decomposed the task — do NOT re-plan. Just execute in order.
"""


class OrchestratorAgent(BaseAgent):
    """Executes subtasks by delegating to specialists.

    Responsibilities: delegation, execution supervision, error recovery
    Does NOT: plan, decompose tasks, confirm actions (state machine handles that)
    """

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="orchestrator",
            client=client,
            tool_executor=tool_executor,
            tools=ORCHESTRATOR_TOOLS,
            system_prompt=ORCHESTRATOR_SYSTEM,
            emit_fn=emit_fn,
        )
        # Connector registry — injected by core after creation
        self.connector_registry = None

    async def step(self, state: AgentState) -> AgentState:
        state.status = "orchestrating"

        context = self._build_page_context_prompt(state)

        # Current subtask progress
        subtask_text = ""
        if state.subtasks:
            subtask_text = "\nSUBTASK PROGRESS:\n"
            for st in state.subtasks:
                marker = "✓" if st.status == "done" else "→" if st.status == "in_progress" else "○"
                subtask_text += f"  {marker} [{st.agent}] {st.instruction} ({st.status})\n"
                if st.result:
                    subtask_text += f"    Result: {st.result}\n"

        # Connector skills context
        connector_text = ""
        if self.connector_registry:
            routing = self.connector_registry.get_skill_routing_hints(state.instruction)
            if routing.get("has_skills"):
                relevant_skills = self.connector_registry.find_skills(state.instruction)
                connector_text = "\n\nAVAILABLE SKILLS:\n"
                for skill_obj in relevant_skills[:3]:
                    connector_text += f"\n--- {skill_obj.full_name} ---\n"
                    if skill_obj.browser_template:
                        connector_text += f"INSTRUCTIONS:\n{skill_obj.browser_template}\n"

        # If navigator claimed completion
        navigator_claim = getattr(state, '_navigator_claim', '')
        claim_text = ""
        if navigator_claim:
            claim_text = f"\n⚠️ NAVIGATOR CLAIMS DONE: \"{navigator_claim}\"\nDelegate to verifier to confirm.\n"
            state._navigator_claim = ""

        # UI Graph context for known apps
        ui_graph_context = ""
        ui_graph_text = getattr(state, '_ui_graph_text', '')
        if ui_graph_text:
            ui_graph_context = f"\n\n{ui_graph_text}\n"

        prompt = (
            f"TASK: {state.instruction}\n\n"
            f"{context}\n"
            f"{subtask_text}\n"
            f"{claim_text}\n"
            f"{ui_graph_context}\n"
            f"{connector_text}\n"
            f"Step {state.step_index}/{state.max_steps}. "
            f"Delegate the next pending subtask."
        )

        state, _ = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=3, include_screenshot=True,
        )

        return state


# ─── NAVIGATOR ─────────────────────────────────────────────────

NAVIGATOR_SYSTEM = """You are the Navigator for G-Axis, a browser agent.

TOOLS:
- navigate(url): Go to a URL. USE THIS FIRST for any site.
- click(x, y, element_description): Click at coordinates.
- type_text(x, y, text, press_enter): Type text. Set press_enter=true to submit.
- scroll(direction, pixels): Scroll the page.
- press_key(key): Press a key (Tab, Escape, etc).
- hover(x, y): Hover over element.
- wait(seconds, reason): Wait for page load.

RULES:
1. navigate(url) FIRST when told to go to a URL. Always.
2. ONE action per turn. You get a new screenshot after each action.
3. Use DOM coordinates when available — more precise than guessing.
4. For search: navigate to site → type_text with press_enter=true.
5. Verify your action worked by checking the next screenshot.
6. Don't overwrite existing content (templates, headers) unless asked.
7. If stuck after 2 tries, try a different approach.
8. CHECK ACTION MEMORY before every action. If a field is already filled, SKIP IT.
   If a button was already clicked, don't click it again unless the screenshot shows it didn't work.

SPEED TIPS — avoid slow date/time pickers:
- For DATE fields: click the date input, use clear_first=true, and TYPE the date in MM/DD/YYYY format (e.g. "03/21/2026"). Press Tab to move to next field.
- For TIME fields: click the time input, clear it, and TYPE the time in 12-hour format without spaces (e.g. "5:30pm", "10:00am"). Press Tab to confirm.
- NEVER click through month/day arrows on a date picker — always type dates directly.
- For Google Calendar: use the URL format https://calendar.google.com/calendar/u/0/r/eventedit to create events. Type into each field directly.

POPUPS: Click "Accept"/"Allow"/"Use my location". If permission needed, call task_failed asking user to grant it.
LOGIN: If login required, call task_failed asking user to sign in.
CAPTCHA: call task_failed asking user to solve it."""


class NavigatorAgent(BaseAgent):
    """Handles page navigation — clicking, scrolling, navigating to URLs."""
    _model_override = VISION_MODEL  # Pro for precise coordinate picking + tool calls

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="navigator",
            client=client,
            tool_executor=tool_executor,
            tools=NAVIGATOR_TOOLS,
            system_prompt=NAVIGATOR_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        state.status = "navigating"

        context = self._build_page_context_prompt(state)
        current_subtask = state.current_subtask

        instruction = current_subtask.instruction if current_subtask else state.instruction

        from datetime import datetime
        today = datetime.now().strftime("%A, %B %d, %Y")

        # Inject UI Graph context for known apps (Calendar, Gmail, etc.)
        ui_graph_hint = ""
        ui_graph_text = getattr(state, '_ui_graph_text', '')
        if ui_graph_text:
            ui_graph_hint = (
                f"\n\n{ui_graph_text}\n\n"
                f"IMPORTANT: Follow the UI GRAPH above for field locations and interaction order.\n"
                f"- TITLE is the large input at the VERY TOP (placeholder='Add title').\n"
                f"- DATE/TIME are CHIP buttons in ROW 2 below the title.\n"
                f"- For CHIP fields: click the chip → type with clear_first=true → press Tab or Enter.\n"
                f"- Do NOT type dates or times into the title field.\n"
            )

        # Navigator action memory — what's already done
        nav_memory_text = ""
        memory_prompt = state.navigator_memory.to_prompt()
        if memory_prompt:
            nav_memory_text = f"\n\n── ACTION MEMORY ──\n{memory_prompt}\n"

        prompt = (
            f"TASK: {instruction}\n\n"
            f"TODAY'S DATE: {today}\n\n"
            f"{context}\n"
            f"{ui_graph_hint}\n"
            f"{nav_memory_text}\n"
            f"Take the SINGLE best next action. Do NOT repeat actions listed in ACTION MEMORY.\n"
            f"If a field is already FILLED, skip it. If a button was already CLICKED, don't click it again.\n"
            f"For date fields: TYPE in MM/DD/YYYY format (e.g. '03/15/2026') with clear_first=true. For time fields: TYPE in 12hr format (e.g. '5:30pm'). NEVER use date picker arrows."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=5, include_screenshot=True,
        )

        # If the agent completed, mark subtask done and go DIRECTLY to verifier
        if state.result_summary and current_subtask:
            current_subtask.status = "done"
            current_subtask.result = state.result_summary
            # Route directly to verifier — skip orchestrator to avoid loops
            state._pending_verification = state.result_summary
            state.result_summary = ""
            state.current_agent = "verifier"
            obs.transition("navigator", to_agent="verifier",
                           reason="subtask completed", task_id=state.task_id,
                           step=state.step_index)
            # Emit event for decoupled routing
            from backend.agent.events import EventType
            await self.emit_event(
                EventType.SUBTASK_COMPLETED,
                task_id=state.task_id,
                summary=current_subtask.result,
                subtask_index=current_subtask.index,
            )

        return state


# ─── FORM FILLER ───────────────────────────────────────────────

FORM_FILLER_SYSTEM = """You are the FormFiller for G-Axis, an AI browser agent.

Your role: Fill out forms by typing text, selecting options, checking boxes, and submitting.

Available tools:
- type_text(x, y, text, clear_first): Type text into an input field. Set clear_first=true to replace existing text.
- click(x, y): Click checkboxes, radio buttons, dropdowns, or submit buttons.
- press_key(key): Press Enter to submit, Tab to move between fields.
- scroll(direction): Scroll to reveal more form fields.
- wait(seconds, reason): Wait for form validation or page updates.

STRATEGY:
- OBSERVE FIRST: Read the screenshot carefully. What fields exist? What's already filled in? Don't overwrite existing valid data.
- Use DOM elements for precise field locations.
- For each field: click to focus → type the text.
- Use clear_first=true when the field already has text you need to replace.
- After filling all required fields, click the submit/search/go button.
- Watch for validation errors after submission.
- Call task_complete() when the form is submitted successfully.

RULES:
- Fill fields one at a time. You'll get a new screenshot after each action.
- Password and payment fields are SENSITIVE — flag high risk.
- Don't guess form values — use what the task specifies.
- If a dropdown needs to be opened first, click it, wait for options, then click the right option.
- NEVER overwrite template content (headers, formulas, charts) unless explicitly asked."""


class FormFillerAgent(BaseAgent):
    """Handles form interactions — typing, selecting, submitting."""
    _model_override = VISION_MODEL  # Pro for accurate form field targeting

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="form_filler",
            client=client,
            tool_executor=tool_executor,
            tools=FORM_FILLER_TOOLS,
            system_prompt=FORM_FILLER_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        state.status = "filling_form"

        context = self._build_page_context_prompt(state)
        current_subtask = state.current_subtask

        instruction = current_subtask.instruction if current_subtask else state.instruction

        from datetime import datetime
        today = datetime.now().strftime("%A, %B %d, %Y")

        # Inject UI Graph context for known apps
        ui_graph_hint = ""
        ui_graph_text = getattr(state, '_ui_graph_text', '')
        if ui_graph_text:
            ui_graph_hint = (
                f"\n\n{ui_graph_text}\n\n"
                f"IMPORTANT: Follow the UI GRAPH above for field locations and interaction order.\n"
                f"- For CHIP fields (date/time): click the chip → type with clear_first=true → press Tab or Enter.\n"
                f"- Fill fields in the SEQUENCE specified in the graph.\n"
            )

        # Action memory — what fields are already filled
        nav_memory_text = ""
        memory_prompt = state.navigator_memory.to_prompt()
        if memory_prompt:
            nav_memory_text = f"\n\n── ACTION MEMORY ──\n{memory_prompt}\n"

        prompt = (
            f"FORM TASK: {instruction}\n\n"
            f"TODAY'S DATE: {today}\n\n"
            f"{context}\n"
            f"{ui_graph_hint}\n"
            f"{nav_memory_text}\n"
            f"Fill ONLY fields NOT listed in ACTION MEMORY. Call task_complete() when done."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=5, include_screenshot=True,
        )

        if state.result_summary and current_subtask:
            current_subtask.status = "done"
            current_subtask.result = state.result_summary
            state._pending_verification = state.result_summary
            state.result_summary = ""
            state.current_agent = "verifier"
            obs.transition("form_filler", to_agent="verifier",
                           reason="form submitted", task_id=state.task_id,
                           step=state.step_index)
            from backend.agent.events import EventType
            await self.emit_event(
                EventType.FORM_SUBMITTED,
                task_id=state.task_id,
                summary=current_subtask.result,
                subtask_index=current_subtask.index,
            )

        return state


# ─── DATA EXTRACTOR ────────────────────────────────────────────

DATA_EXTRACTOR_SYSTEM = """You are the DataExtractor for G-Axis, an AI browser agent.

Your role: Extract structured data from web pages.

Available tools:
- extract_data(description, data): Extract and structure data from the current page into a JSON object.
- scroll(direction): Scroll to reveal more content.
- click(x, y): Click to expand details or load more items.
- wait(seconds, reason): Wait for content to load.

STRATEGY:
- Read the page carefully and identify the data the user wants.
- Structure the data logically (lists, key-value pairs, tables).
- If data spans multiple sections, scroll to see all of it.
- Use extract_data() to capture the structured result.
- Call task_complete() with a summary of what was extracted.

RULES:
- Be thorough — don't miss data that's visible on the page.
- Format data clearly in the JSON output.
- If the page has multiple items (search results, products, flights), extract all visible ones.
- Include relevant metadata (prices, dates, ratings, URLs)."""


class DataExtractorAgent(BaseAgent):
    """Extracts structured data from web pages."""

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="data_extractor",
            client=client,
            tool_executor=tool_executor,
            tools=DATA_EXTRACTOR_TOOLS,
            system_prompt=DATA_EXTRACTOR_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        state.status = "extracting"

        context = self._build_page_context_prompt(state)
        current_subtask = state.current_subtask

        instruction = current_subtask.instruction if current_subtask else state.instruction

        prompt = (
            f"EXTRACTION TASK: {instruction}\n\n"
            f"{context}\n\n"
            f"Extract the requested data from this page. "
            f"Use extract_data() to capture structured results, then call task_complete()."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=5, include_screenshot=True,
        )

        if state.result_summary and current_subtask:
            current_subtask.status = "done"
            current_subtask.result = state.result_summary
            state.result_summary = ""
            state.current_agent = "orchestrator"

        return state


# ─── VERIFIER ──────────────────────────────────────────────────

VERIFIER_SYSTEM = """You are the Verifier for G-Axis, an AI browser agent.

Your role: CRITICALLY check if a task was completed correctly by examining the current page screenshot.

Available tools:
- scroll(direction): Scroll to see more of the page.
- click(x, y): Click to reveal details for verification.
- extract_data(description, data): Extract data for comparison.
- task_complete(summary): Confirm the task is FULLY done with a final summary.
- task_partial(summary, missing): The task is PARTIALLY done — core action succeeded but specific details are wrong or missing.
- task_failed(reason): The task was NOT completed at all.

VERIFICATION PROCESS:
1. READ the original task carefully — what EXACTLY was asked?
2. EXAMINE the screenshot — what is ACTUALLY on the page right now?
3. COMPARE: Does the page state match what the task required?
4. CHECK for damage: Was any existing content accidentally overwritten or corrupted?
5. Scroll if needed to see the full result.

WHAT TO CHECK:
- If task was "create X": Is X actually created and visible? Is it properly structured?
- If task was "fill form with Y": Are the fields actually filled with the correct values?
- If task was "search for Z": Are search results for Z visible?
- If task was "open template": Is the template intact? Were headers/formatting preserved?
- If existing content was present: Was it accidentally overwritten or damaged?

WHEN TO USE EACH:
- task_complete: Everything matches — all required fields are correct, all actions succeeded.
- task_partial: The CORE action was done but specific items are missing or wrong.
  Example: Calendar event created with correct title/date BUT guest was not added.
  Example: Email sent BUT CC recipient was missing.
  For each missing item, provide: field (what's missing), expected (what it should be),
  actual (what's shown, or empty string), fix_instruction (how to fix it).
- task_failed: The core action was NOT done at all. Wrong page, nothing created, total failure.

RULES:
- Be SKEPTICAL — assume the task is NOT done until you prove it IS.
- Actually READ text on the screen — don't just accept that actions were taken.
- If a specialist claimed to type "Amount" into C1, CHECK if C1 actually says "Amount" AND if that was the right thing to do.
- If a template was opened, verify its original structure is intact.
- Include specific details in your summary (cell values, visible text, page state).
- If the task was done but existing content was damaged, report task_failed with what went wrong.
- PREFER task_partial over task_failed when the main action succeeded but details are off."""


class VerifierAgent(BaseAgent):
    """Validates that a task was completed correctly."""

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="verifier",
            client=client,
            tool_executor=tool_executor,
            tools=VERIFIER_TOOLS,
            system_prompt=VERIFIER_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        state.status = "verifying"

        context = self._build_page_context_prompt(state)

        # Summarize what's been done
        subtask_summary = ""
        if state.subtasks:
            subtask_summary = "\nCOMPLETED SUBTASKS:\n"
            for st in state.subtasks:
                if st.status == "done":
                    subtask_summary += f"  ✓ [{st.agent}] {st.instruction}\n"
                    if st.result:
                        subtask_summary += f"    Result: {st.result}\n"

        extracted = ""
        if state.extracted_data:
            extracted = f"\nEXTRACTED DATA:\n{json.dumps(state.extracted_data, indent=2)}\n"

        pending = getattr(state, '_pending_verification', '')
        claim_text = ""
        if pending:
            claim_text = f"\nNAVIGATOR CLAIMS: \"{pending}\"\n"
            state._pending_verification = ""

        prompt = (
            f"ORIGINAL TASK: {state.instruction}\n\n"
            f"{context}\n"
            f"{subtask_summary}\n"
            f"{claim_text}\n"
            f"{extracted}\n"
            f"VERIFY by examining the screenshot. You MUST call task_complete() or task_failed() — do NOT scroll or click unless absolutely needed.\n"
            f"1. What EXACTLY does the page show right now?\n"
            f"2. Does it match what the original task asked for?\n"
            f"If done correctly: call task_complete(summary='...')\n"
            f"If NOT done: call task_failed(reason='...')"
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=3, include_screenshot=True,
        )

        # Emit verification result events
        from backend.agent.events import EventType
        if state.runtime.partial_result:
            await self.emit_event(
                EventType.VERIFICATION_PARTIAL,
                task_id=state.task_id,
                summary=state.runtime.partial_result.get("summary", ""),
                missing=state.runtime.partial_result.get("missing", []),
            )
        elif state.result_summary:
            await self.emit_event(
                EventType.VERIFICATION_PASSED,
                task_id=state.task_id,
                summary=state.result_summary,
            )
        elif state.status == "failed":
            await self.emit_event(
                EventType.VERIFICATION_FAILED,
                task_id=state.task_id,
                error=state.error or "Verification failed",
            )

        return state


# ─── HELPERS ───────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Parse JSON from model output, handling markdown fences."""
    import re
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON: {cleaned[:200]}")
        return {}
