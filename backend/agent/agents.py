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

import base64
import json
import logging
import time

from google import genai
from google.genai import types

from backend.agent.base import BaseAgent, AGENT_MODEL
from backend.agent.state import AgentState, SubTask
from backend.tools.definitions import (
    ORCHESTRATOR_TOOLS, NAVIGATOR_TOOLS, FORM_FILLER_TOOLS,
    DATA_EXTRACTOR_TOOLS, VERIFIER_TOOLS,
)
from backend.tools.executor import ToolExecutor

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

The viewport is 1280x720 pixels.

Return ONLY valid JSON:
{"page_summary": "...", "current_state": "...", "elements": [...]}"""


class PerceiverAgent(BaseAgent):
    """Analyzes screenshots to build page understanding.

    Does NOT use tools — just vision analysis via structured JSON output.
    """

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

        response = await self.client.aio.models.generate_content(
            model=AGENT_MODEL,
            contents=[
                types.Content(parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(text=prompt),
                ])
            ],
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )

        parsed = _parse_json(response.text or "{}")

        state.page.page_summary = parsed.get("page_summary", "")
        state.page.current_state = parsed.get("current_state", "")
        state.page.elements = parsed.get("elements", [])
        state.page.timestamp = time.time()

        logger.info(
            f"Perceiver: {state.page.page_summary} | "
            f"{len(state.page.elements)} elements detected"
        )
        return state


# ─── ORCHESTRATOR ──────────────────────────────────────────────

ORCHESTRATOR_SYSTEM = """You are the Orchestrator for G-Axis, an AI browser agent with supervised autonomy.

Your role: Break down user tasks into subtasks and delegate to specialist agents.

AVAILABLE SPECIALISTS:
- navigator: Page navigation — clicking links, buttons, scrolling, going to URLs. Use for any page traversal.
- form_filler: Form interaction — typing into fields, selecting options, submitting forms. Use when data needs to be entered.
- data_extractor: Data extraction — reading and structuring data from pages. Use when the user wants information gathered.
- verifier: Verification — checking if a task was completed correctly. Use at the end to confirm success.

STRATEGY:
1. Look at the current page and the user's task.
2. Determine what needs to happen NEXT (one step at a time).
3. Delegate to the most appropriate specialist using the delegate() tool.
4. If the page already shows the desired result, call task_complete().

RULES:
- Delegate ONE subtask at a time. You'll be called again after it completes.
- Always consider the current page state — don't repeat completed work.
- If the task requires searching, delegate to navigator first.
- If a form needs filling, delegate to form_filler.
- For reading/comparing data, delegate to data_extractor.
- Use verifier at the end to confirm the task is truly done.
- If previous actions show errors, adjust your strategy.
- If you see the task is already complete from the page content, call task_complete() directly.

MEMORY CONTEXT (if available) will be provided. Use it to avoid past mistakes."""


class OrchestratorAgent(BaseAgent):
    """Decomposes tasks and delegates to specialist agents."""

    def __init__(self, client: genai.Client, tool_executor: ToolExecutor, emit_fn=None):
        super().__init__(
            name="orchestrator",
            client=client,
            tool_executor=tool_executor,
            tools=ORCHESTRATOR_TOOLS,
            system_prompt=ORCHESTRATOR_SYSTEM,
            emit_fn=emit_fn,
        )

    async def step(self, state: AgentState) -> AgentState:
        state.status = "orchestrating"

        # Build context for the orchestrator
        context = self._build_page_context_prompt(state)

        # Include memory context
        memory_text = ""
        if state.memory_context:
            if state.memory_context.get("past_episodes"):
                memory_text += "\nMEMORY (past experiences):\n"
                for ep in state.memory_context["past_episodes"][:3]:
                    status = "succeeded" if ep.get("success") else "failed"
                    memory_text += f"  - \"{ep.get('instruction', '?')}\" {status} in {ep.get('steps', '?')} steps\n"
                    if ep.get("obstacles"):
                        memory_text += f"    Obstacles: {', '.join(ep['obstacles'][:2])}\n"

            if state.memory_context.get("known_patterns"):
                memory_text += "\nKNOWN PATTERNS:\n"
                for p in state.memory_context["known_patterns"][:5]:
                    memory_text += f"  - {p.get('name', '?')}: {p.get('description', '?')}\n"

            if state.memory_context.get("similar_experiences"):
                memory_text += "\nSIMILAR PAST TASKS:\n"
                for exp in state.memory_context["similar_experiences"][:3]:
                    memory_text += f"  - \"{exp.get('instruction', '?')}\" → {exp.get('result', '?')}\n"

        # Current subtask progress
        subtask_text = ""
        if state.subtasks:
            subtask_text = "\nSUBTASK PROGRESS:\n"
            for st in state.subtasks:
                marker = "✓" if st.status == "done" else "→" if st.status == "in_progress" else "○"
                subtask_text += f"  {marker} [{st.agent}] {st.instruction} ({st.status})\n"
                if st.result:
                    subtask_text += f"    Result: {st.result}\n"

        prompt = (
            f"TASK: {state.instruction}\n\n"
            f"{context}\n"
            f"{memory_text}\n"
            f"{subtask_text}\n"
            f"Step {state.step_index} of {state.max_steps}. "
            f"What should happen NEXT? Delegate to a specialist or complete the task."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=3, include_screenshot=True,
        )

        return state


# ─── NAVIGATOR ─────────────────────────────────────────────────

NAVIGATOR_SYSTEM = """You are the Navigator for G-Axis, an AI browser agent.

Your role: Navigate web pages by clicking links, buttons, scrolling, and going to URLs.

You can see the page screenshot and DOM element positions. Use the tools to interact:
- click(x, y): Click at coordinates
- navigate(url): Go to a URL
- scroll(direction, pixels): Scroll up or down
- press_key(key): Press Enter, Tab, Escape, etc.
- hover(x, y): Hover over an element
- wait(seconds, reason): Wait for page to load

STRATEGY:
- Use DOM element coordinates when available — they're more precise than visual estimation.
- If you see the target element in DOM ELEMENTS, use its exact (x, y) coordinates.
- Click search buttons, links, and navigation elements to reach the desired page.
- After clicking, the page may need time to load — use wait() if needed.
- Call task_complete() when you've reached the target page or completed the navigation.

RULES:
- Execute ONE action at a time. You'll get a new screenshot after each action.
- Don't navigate to URLs you can't see on the page or that aren't well-known.
- If an element isn't visible, scroll to find it.
- If a click doesn't work, try a slightly different approach (hover first, or use keyboard).
- Mark password/payment actions as needing care."""


class NavigatorAgent(BaseAgent):
    """Handles page navigation — clicking, scrolling, navigating to URLs."""

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

        prompt = (
            f"NAVIGATION TASK: {instruction}\n\n"
            f"{context}\n\n"
            f"Take the next action to navigate toward the goal. "
            f"If you've reached the target, call task_complete()."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=3, include_screenshot=True,
        )

        # If the agent completed, mark subtask done
        if state.result_summary and current_subtask:
            current_subtask.status = "done"
            current_subtask.result = state.result_summary
            state.result_summary = ""  # Reset — only orchestrator sets final summary
            state.current_agent = "orchestrator"

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
- If a dropdown needs to be opened first, click it, wait for options, then click the right option."""


class FormFillerAgent(BaseAgent):
    """Handles form interactions — typing, selecting, submitting."""

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

        prompt = (
            f"FORM TASK: {instruction}\n\n"
            f"{context}\n\n"
            f"Fill the form fields as needed. Call task_complete() when done."
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

Your role: Check if a task was completed correctly by examining the current page state.

Available tools:
- scroll(direction): Scroll to see more of the page.
- click(x, y): Click to reveal details for verification.
- extract_data(description, data): Extract data for comparison.
- task_complete(summary): Confirm the task is done with a final summary.
- task_failed(reason): Report that the task was NOT completed.

STRATEGY:
- Compare the current page state to what the original task asked for.
- Check if the expected result is visible on the page.
- Scroll down if needed to see the full result.
- If the task asked for data, verify the extracted data is correct and complete.
- Provide a clear summary of the verification result.

RULES:
- Be honest — if the task isn't actually done, report it.
- Include specific details in your summary (what was found, numbers, names).
- Don't just rubber-stamp — actually verify by looking at the page."""


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

        prompt = (
            f"ORIGINAL TASK: {state.instruction}\n\n"
            f"{context}\n"
            f"{subtask_summary}\n"
            f"{extracted}\n"
            f"VERIFY: Is this task complete? Check the page carefully.\n"
            f"If done, call task_complete() with a detailed summary.\n"
            f"If NOT done, call task_failed() explaining what's missing."
        )

        state, response_text = await self.call_gemini_with_tool_loop(
            state, prompt, max_tool_calls=3, include_screenshot=True,
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
