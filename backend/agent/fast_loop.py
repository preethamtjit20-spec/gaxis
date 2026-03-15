"""Fast single-agent loop — Manus-style one-LLM-call-per-action.

Replaces the multi-agent graph (perceiver → orchestrator → specialist)
with a single unified agent that sees screenshot + DOM and directly
executes actions. ~5x faster than the multi-agent approach.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Callable

from google import genai
from google.genai import types

from backend.agent.state import AgentState
from backend.agent.base import AGENT_MODEL, VISION_MODEL
from backend.tools.definitions import ALL_TOOLS
from backend.tools.executor import ToolExecutor
from backend.observability.logger import obs

logger = logging.getLogger("gaxis.fast")


def has_fc_in_last_model(cleaned: list) -> bool:
    """Check if the last model turn in cleaned has a function_call."""
    for msg in reversed(cleaned):
        if getattr(msg, 'role', None) == "model":
            return any(
                hasattr(p, 'function_call') and p.function_call
                for p in (msg.parts or [])
            )
    return False

UNIFIED_SYSTEM = """You are G-Axis — an advanced browser automation agent. You interact with webpages
accurately, safely, and deterministically using structured UI navigation.

You see a screenshot + DOM elements with precise coordinates. Execute ONE action per turn.

TOOLS:
- navigate(url): Go to a URL. Use for well-known sites.
- click(x, y, element_description): Click at coordinates.
- type_text(x, y, text, press_enter): Type text. ALWAYS press_enter=true for search boxes.
- scroll(direction, pixels): Scroll up or down.
- press_key(key): Press a key (Tab, Escape, ArrowDown, etc).
- hover(x, y): Hover to reveal menus/tooltips.
- wait(seconds, reason): Wait for page load.
- extract_data(description, data): Extract structured data from the page.
- fill_form(fields): BATCH fill multiple form fields at once. 10x faster than one-by-one.
  Use when UI GRAPH provides FILL values. Each field: {hints: {placeholder, aria, text}, value, action, press_enter}.
  Example: fill_form(fields=[
    {hints: {placeholder: "Add title"}, value: "Team Sync", action: "type"},
    {hints: {aria: "Start date"}, value: "Mar 12, 2026", action: "select_all_and_type", press_enter: true},
    {hints: {aria: "Start time"}, value: "10:00am", action: "select_all_and_type", press_enter: true},
    {hints: {aria: "End time"}, value: "11:00am", action: "select_all_and_type", press_enter: true},
  ])
- task_complete(summary): Done. Write a warm, clear summary of what was accomplished.
- task_failed(reason): Cannot complete. Explain why clearly.

═══════════════════════════════════════════════════════════════
STEP 0 — PARSE THE TASK (do this mentally before your first action):
═══════════════════════════════════════════════════════════════
Before acting, extract ALL structured details from the user's instruction:
- Calendar: title (the event name), date, time, guests, description
- Email: to, subject, body
- Doc: title, content outline
- Search: query terms

Examples:
  "Schedule a team sync tomorrow at 10am with john@example.com"
  → title="Team Sync", date=tomorrow, start_time=10:00am, guest=john@example.com

  "Block a scrum meeting tomorrow at 10 AM"
  → title="Scrum Meeting", date=tomorrow, start_time=10:00am

CRITICAL: The event/email/doc title comes FROM the user's instruction. NEVER leave title fields blank.
If user says "team sync" → title is "Team Sync". If they say "scrum meeting" → title is "Scrum Meeting".

═══════════════════════════════════════════════════════════════
STRUCTURED UI NAVIGATION — CORE PRINCIPLE
═══════════════════════════════════════════════════════════════
Always process the page from TOP → BOTTOM using the visible UI hierarchy.
Never jump randomly across the interface.

SCAN STRATEGY:
1. Identify the ordered list of visible UI elements from DOM.
2. Scan from the top of the page downward.
3. For each element: identify its type → check current state → decide if interaction is needed.

FIELD STATE DETECTION — before typing or clicking:
  IF current_value == desired_value → SKIP (do not overwrite correct values)
  ELSE → update the field (use clear_first=true to replace existing values)
  Never assume fields are empty. ALWAYS check the current value first.

FORM COMPLETION SEQUENCE:
1. Start at the FIRST input field (usually title/subject — fill this FIRST, never skip it).
2. Move sequentially DOWNWARD through the form.
3. Fill missing or incorrect fields. Skip fields already correct.
4. Continue until all required fields are complete.
5. For date/time formats: "Mar 12, 2026" for dates, "10:00am" for times (12hr, no space).
6. Default meeting duration: 1 hour (e.g. 10:00am → 11:00am).

CONTROLLED BACKTRACKING:
Sometimes required actions exist ABOVE current position (e.g., Save button at top).
If this occurs:
1. Finish scanning all required fields below.
2. Navigate/scroll back to the control element.
3. Execute the action (Save, Submit, etc.).

POSITION AWARENESS:
Track which fields you have already processed. Do not restart scanning unless the page
refreshes or changes significantly. Maintain awareness of your current position.

═══════════════════════════════════════════════════════════════
KNOWN APP UI GRAPHS
═══════════════════════════════════════════════════════════════
When a "UI GRAPH" block appears in the context, it provides a semantic map of the page.
Follow its SEQUENCE exactly — it defines the top-to-bottom field order.

ELEMENT INTERACTION RULES:
- INPUT nodes: click the field → type_text(x, y, text, press_enter=false).
  Use clear_first=true if pre-filled.
- CHIP nodes (date/time pickers): These are ROUNDED BUTTONS, not text inputs.
  1. CLICK the chip button to activate it (it becomes an editable text input).
  2. type_text with clear_first=true to replace the existing value.
  3. Press Enter or Tab to confirm.
  Date chips show like "Thu Mar 12" — click to edit, type "Mar 12, 2026", press Enter.
  Time chips show like "10:00am" — click to edit, type new time, press Enter.
- LINK nodes: click the visible text.
- BTN nodes: click.
- DROPDOWN nodes: click to open → select the option.
- CHECKBOX nodes: click to toggle.

MATCHING NODES TO DOM:
- Use placeholder, aria-label, or visible text from the graph's selector hints.
- Use DOM coordinates as fallback — text matching (placeholder/aria) is MORE RELIABLE.
- The FILL values are pre-extracted from the task — use them EXACTLY as shown.

SPEED OPTIMIZATION — AUTO-FILL HANDLES TEXT INPUTS:
When a UI GRAPH with FILL values is present, text INPUT fields (title, guests, description)
are automatically batch-filled. You handle the rest:
1. After auto-fill, check the screenshot — text inputs should be filled.
2. Fill DATE/TIME CHIP fields yourself: click chip → type_text(clear_first=true, press_enter=true).
3. Click action buttons (Add Google Meet, Save).
4. Handle any dialogs (Send invitations).
CHIP fields need visual interaction — click to open picker, type value, Enter to confirm.

AUTOCOMPLETE HANDLING:
Some fields trigger suggestion dropdowns (guests, location, etc.).
- fill_form automatically dismisses autocomplete after each field.
- If using type_text manually: after typing, check for dropdown. If visible:
  wait briefly → press Escape to dismiss OR select the first suggestion.
- Never type into the next field while a dropdown is visible.
- For guest fields: type email + press Enter to add (press_enter: true in fill_form).

═══════════════════════════════════════════════════════════════
ACTION EXECUTION
═══════════════════════════════════════════════════════════════
Execute only ONE action per turn. After each action:
1. Observe the updated screenshot + DOM.
2. Confirm the expected change occurred (field filled, page navigated, etc.).
3. Continue scanning from the current position.

If an action didn't work → try an alternative approach. Don't repeat failed actions.
If a popover/dialog blocks the page → press Escape first.
If a field cannot be located → scroll to search, re-scan the UI hierarchy.

═══════════════════════════════════════════════════════════════
ERROR HANDLING & ROLLBACK
═══════════════════════════════════════════════════════════════
If a field cannot be located:
1. Scroll the page to search for it.
2. Re-scan the DOM elements.
3. Look for labels or placeholder text related to the target.
If the page structure changes unexpectedly → pause and re-analyze.
Never guess element locations — use DOM coordinates.

ROLLBACK — use when you made a MISTAKE:
- Typed text into the WRONG field → call rollback(steps=1, reason="typed into wrong field")
  This clears the field so you can type in the correct one.
- Navigated to the WRONG page → call rollback(steps=1, reason="wrong page")
  This navigates back to where you were.
- Filled form with WRONG values → call rollback(steps=1, reason="wrong values")
  This clears the filled fields.
- Do NOT use rollback for actions that simply failed — only for actions that SUCCEEDED
  but put the page in a wrong state.
- After rollback, you get a fresh screenshot — use it to retry correctly.

═══════════════════════════════════════════════════════════════
VERIFICATION & COMPLETION
═══════════════════════════════════════════════════════════════
Before calling task_complete:
- Verify ALL required fields were filled correctly.
- Verify the submission action succeeded (event on calendar, message sent, etc.).
- Verify confirmation is visible on page (toast message, redirect, etc.).

AFTER SAVE/SUBMIT — BE FAST:
- Once you click Save/Send/Submit and it succeeds (page redirects or toast appears):
  call task_complete IMMEDIATELY. Do NOT waste steps clicking around to "verify."
- If the page redirected to the calendar grid / inbox → it worked. Call task_complete.
- If a "Send invitations?" dialog appeared → click Send → then task_complete.
- Do NOT click outside popups, do NOT scroll around, do NOT re-open the event.
  One screenshot showing the redirect/toast is enough proof.

COMPLETION STYLE — write as a warm, helpful personal assistant:
- BAD: "Task completed. Calendar event created."
- GOOD: "Your Team Sync is scheduled for 10 AM tomorrow. I've added john@example.com and included a Google Meet link."
Include specific details: what was done, key results, links or data found.

═══════════════════════════════════════════════════════════════
SAFETY RULES
═══════════════════════════════════════════════════════════════
- Never type into fields without verifying their purpose.
- Never enter credentials or passwords unless explicitly instructed.
- Never click destructive actions (Delete, Remove) unless required by the task.
- Never leave title/subject fields blank.
- Do NOT call task_complete until the goal is actually achieved.

QUICK REFERENCE:
- Google search: navigate("https://www.google.com") → type_text(x, y, "query", press_enter=true).
- Google Calendar: navigate("https://calendar.google.com/calendar/u/0/r/eventedit").
- One action per turn. Use DOM coordinates. Check before typing. Top-to-bottom scanning.
- CHECK ACTION MEMORY: If a field shows as FILLED, skip it. If a button shows as CLICKED, don't click again.
  Repeating the same action wastes steps and may cause errors."""


class FastAgentLoop:
    """Single unified agent — one LLM call per action, like Manus."""

    def __init__(
        self,
        client: genai.Client,
        tool_executor: ToolExecutor,
        emit_fn: Callable | None = None,
        get_screenshot_fn: Callable | None = None,
        get_browser_state_fn: Callable | None = None,
        get_dom_fn: Callable | None = None,
        approval_fn: Callable | None = None,
        is_paused_fn: Callable | None = None,
        ui_graph_registry=None,
        get_edits_fn: Callable | None = None,
        get_steering_fn: Callable | None = None,
        get_blockers_fn: Callable | None = None,
        replay=None,
        user_input_fn: Callable | None = None,
        connector_registry=None,
    ):
        self.client = client
        self.tool_executor = tool_executor
        self.emit_fn = emit_fn
        self.get_screenshot_fn = get_screenshot_fn
        self.get_browser_state_fn = get_browser_state_fn
        self.get_dom_fn = get_dom_fn
        self.approval_fn = approval_fn
        self._is_paused_fn = is_paused_fn
        self._ui_graph_registry = ui_graph_registry
        self._get_user_edits = get_edits_fn
        self._get_steering = get_steering_fn
        self._get_blockers = get_blockers_fn
        self._replay = replay  # ExecutionReplay instance for recording actions
        self._user_input_fn = user_input_fn  # For clarification questions
        self._connector_registry = connector_registry  # For deterministic skill execution
        self._conversation: list[types.Content] = []

    def _is_paused(self) -> bool:
        """Check if the agent is paused (human takeover)."""
        if self._is_paused_fn:
            return self._is_paused_fn()
        return False

    async def run(self, state: AgentState) -> AgentState:
        """Run the fast single-agent loop."""
        obs.lifecycle("gaxis", "task_start", task_id=state.task_id,
                      reason=state.instruction[:80],
                      mode=state.mode, max_steps=state.max_steps)
        self._conversation = []
        self._graph_filled = False  # Track if we've already batch-filled the form
        self._cached_task_values: dict[str, str] | None = None  # LLM-extracted values, cached

        # Start replay recording
        if self._replay:
            self._replay.start_session(state.task_id, state.instruction, {
                "mode": state.mode,
                "max_steps": state.max_steps,
            })

        # ── FASTEST PATH: Deterministic skill execution ──
        # If a connector skill has an executor, run it directly.
        # No LLM, no state machine — direct browser actions.
        if self._connector_registry and state.mode == "extension":
            from backend.connectors.base import SkillResult as _SR
            match = self._connector_registry.find_deterministic_skill(state.instruction)
            if match:
                skill, conn_name, skill_name = match
                # Use planner-collected slots if available, otherwise empty
                params = dict(state.task.planner_slots) if state.task.planner_slots else {}
                # Merge slot names → executor param names
                # Planner slots use: title, start_date, start_time, end_time, etc.
                # Executor params match these directly.
                logger.info(
                    f"⚡ Deterministic skill: {conn_name}.{skill_name} "
                    f"(params={list(params.keys())})"
                )
                await self._emit_event(state, "agent_active", {
                    "agent": "executor",
                    "step": 0,
                    "subtask": f"Deterministic: {conn_name}.{skill_name}",
                })
                # Set up replay recording for deterministic executor
                if self._replay:
                    from backend.connectors import executors as _execs
                    _execs._replay_ref = self._replay
                    _execs._replay_task_id = state.task_id
                    _execs._replay_step_counter = 0
                    _execs._screenshot_fn = lambda: self._get_latest_screenshot(state)

                result = await self._connector_registry.execute_deterministic(
                    instruction=state.instruction,
                    params=params,
                    tool_executor=self.tool_executor,
                    emit_fn=self.emit_fn,
                    task_id=state.task_id,
                    mode=state.mode,
                )
                if result is not None and result.success:
                    # Clean up replay recording refs
                    if self._replay:
                        from backend.connectors import executors as _execs
                        _execs._replay_ref = None
                        _execs._screenshot_fn = None

                    # Check if the executor returned a browser_instruction
                    # (semi-deterministic: nav done, LLM finishes the rest)
                    if result.browser_instruction:
                        logger.info(
                            f"Semi-deterministic done — LLM finishes: "
                            f"{result.browser_instruction[:60]}"
                        )
                        # Update instruction for the LLM phase
                        state.instruction = result.browser_instruction
                        # Fall through to state machine / LLM loop
                    else:
                        # Fully deterministic — done!
                        state.status = "done"
                        state.result_summary = self._friendly_summary(
                            conn_name, skill_name, result.data,
                        )
                        logger.info(f"⚡ Deterministic complete: {state.result_summary[:80]}")
                        # Navigate to the scheduled date so user can see the event
                        await self._navigate_to_calendar_date(state)
                        # End replay session and get player data
                        if self._replay:
                            self._replay.end_session(state.task_id, "done", state.result_summary)
                        player_data = self._replay.get_player_data(state.task_id) if self._replay else None
                        await self._emit_event(state, "task_completed", {
                            "summary": state.result_summary,
                            "total_steps": 1,
                            "deterministic": True,
                            "replay": player_data,
                        })
                        return state
                elif result is not None:
                    # Clean up replay recording refs on failure too
                    if self._replay:
                        from backend.connectors import executors as _execs
                        _execs._replay_ref = None
                        _execs._screenshot_fn = None
                    logger.warning(
                        f"Deterministic execution failed: {result.error} "
                        f"— falling back to state machine"
                    )

        # ── FAST PATH: State machine execution for known apps ──
        # Confirmation card → user edits → deterministic execution
        if self._ui_graph_registry and state.mode == "extension":
            from backend.agent.state_machine import StateMachineExecutor
            sm = StateMachineExecutor(
                client=self.client,
                tool_executor=self.tool_executor,
                emit_fn=self.emit_fn,
                get_dom_fn=self.get_dom_fn,
                get_screenshot_fn=self.get_screenshot_fn,
                ui_graph_registry=self._ui_graph_registry,
                approval_fn=self.approval_fn,
                get_edits_fn=self._get_user_edits,
                get_steering_fn=self._get_steering,
                get_blockers_fn=self._get_blockers,
                user_input_fn=self._user_input_fn,
            )
            sm_result = await sm.execute(state)
            if sm_result is not None:
                return sm_result

        gemini_tools = [types.Tool(function_declarations=ALL_TOOLS)]

        while not state.is_terminal and state.step_index < state.max_steps:
            try:
                # ── 0. Check if paused (human takeover) ──
                if self._is_paused():
                    logger.info("Agent paused — waiting for resume...")
                    while self._is_paused():
                        await asyncio.sleep(0.5)
                    logger.info("Agent resumed — continuing task")

                # ── 1. Capture page state ──
                state = await self._capture_page(state)

                # ── 1.5. AUTO-FILL: If we detect a known app with fill values,
                # execute fill_form DIRECTLY without LLM — skip 15+ LLM calls ──
                if (
                    not self._graph_filled
                    and self._ui_graph_registry
                    and state.page.url
                    and state.step_index > 0  # Skip step 0 (navigation)
                ):
                    auto_result = await self._try_auto_fill(state)
                    if auto_result:
                        self._graph_filled = True
                        state.record_action({
                            "action_type": "fill_form",
                            "args": {"auto_fill": True},
                            "success": auto_result.success,
                            "error": auto_result.error,
                            "duration_ms": auto_result.duration_ms,
                            "agent": "gaxis",
                        })
                        if auto_result.success:
                            logger.info("Auto-fill complete — skipping to post-fill actions")
                            await self._emit_event(state, "action_succeeded", {
                                "action_type": "fill_form",
                                "step": state.step_index,
                                "duration_ms": auto_result.duration_ms,
                            })
                            state.step_index += 1
                            # Brief pause for UI to settle after batch fill
                            await asyncio.sleep(0.3)
                            # Re-capture page so LLM sees the filled form
                            state = await self._capture_page(state)
                        else:
                            logger.warning(f"Auto-fill failed: {auto_result.error} — falling back to LLM")

                # ── 2. Build prompt with screenshot + DOM ──
                parts = []

                if state.page.screenshot_b64:
                    image_bytes = base64.b64decode(state.page.screenshot_b64)
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

                if state.page.dom_elements:
                    dom_text = self._format_dom(state.page.dom_elements[:80])
                    parts.append(types.Part.from_text(text=f"\nDOM ELEMENTS:\n{dom_text}"))

                # Context about the task and current state
                context = (
                    f"TASK: {state.instruction}\n"
                    f"URL: {state.page.url}\n"
                    f"PAGE TITLE: {state.page.title}\n"
                    f"Step {state.step_index + 1} of {state.max_steps}.\n"
                )

                # Inject retrieval memory context (past experiences, patterns)
                if state.memory_context and state.step_index == 0:
                    mem = state.memory_context
                    mem_lines = []
                    if mem.get("past_episodes"):
                        mem_lines.append("PAST EXPERIENCES ON THIS SITE:")
                        for ep in mem["past_episodes"][:3]:
                            result = "succeeded" if ep.get("success") else "failed"
                            mem_lines.append(f"  - \"{ep.get('instruction', '?')}\" {result} in {ep.get('steps', '?')} steps")
                            if ep.get("obstacles"):
                                mem_lines.append(f"    Obstacles: {', '.join(ep['obstacles'][:2])}")
                    if mem.get("similar_experiences"):
                        mem_lines.append("SIMILAR TASKS (cross-site):")
                        for exp in mem["similar_experiences"][:3]:
                            mem_lines.append(f"  - \"{exp.get('instruction', '?')}\" → {exp.get('result', '?')} (similarity: {exp.get('similarity', '?')})")
                    if mem.get("known_patterns"):
                        mem_lines.append("KNOWN PATTERNS:")
                        for p in mem["known_patterns"][:5]:
                            mem_lines.append(f"  - {p.get('name', '?')}: {p.get('description', '?')}")
                    if mem_lines:
                        context += "\n" + "\n".join(mem_lines) + "\n"

                # Inject UI Graph if we recognize the current app
                if self._ui_graph_registry and state.page.url:
                    graph = self._ui_graph_registry.detect_and_get(
                        state.page.url, state.page.title
                    )
                    if graph:
                        from backend.uigraph.prompt import serialize_graph_for_prompt
                        # Use cached LLM-extracted values, or basic fallback for prompt
                        task_values = self._cached_task_values
                        if not task_values:
                            from backend.uigraph.prompt import extract_task_values
                            task_values = extract_task_values(state.instruction, graph)
                        graph_text = serialize_graph_for_prompt(graph, task_values)
                        context += f"\n{graph_text}\n"
                        logger.info(f"UI Graph loaded: {graph.app_id} values={task_values}")

                        # Tell LLM what was already auto-filled
                        if self._graph_filled:
                            context += (
                                "\nAUTO-FILLED: Text input fields (title, guests, description) were "
                                "already batch-filled. Check the screenshot to verify they look correct.\n"
                                "YOU STILL NEED TO: Fill date/time CHIP fields (click each chip → type → Enter), "
                                "click 'Add Google Meet', then click 'Save'.\n"
                                "For CHIPS: click the chip button first, then type_text with clear_first=true, press_enter=true.\n"
                            )

                # On first step, remind the agent to parse structured details
                if state.step_index == 0:
                    context += (
                        "\nREMINDER: Parse ALL details from the TASK before acting.\n"
                        "Extract: title/subject, date, time, recipients, description.\n"
                        "NEVER leave form fields (especially title) blank.\n"
                    )

                # Navigator action memory — structured view of what's done
                nav_memory = state.navigator_memory.to_prompt()
                if nav_memory:
                    context += f"\n\n── ACTION MEMORY ──\n{nav_memory}\n"
                elif state.action_history:
                    # Fallback to raw recent actions if memory is empty
                    recent = state.action_history[-5:]
                    history = "\n".join(
                        f"  [{a.get('action_type', '?')}] {'✓' if a.get('success') else '✗'} {a.get('args', {}).get('element_description', '')}"
                        for a in recent
                    )
                    context += f"\nRECENT ACTIONS:\n{history}\n"

                # Rollback context — let LLM know it can undo mistakes
                if self.tool_executor.rollback_manager:
                    rb_prompt = self.tool_executor.rollback_manager.to_prompt()
                    if rb_prompt:
                        context += f"\n\n{rb_prompt}\n"

                context += "\nWhat is the SINGLE best next action? Do NOT repeat actions from ACTION MEMORY."
                parts.append(types.Part.from_text(text=context))

                user_content = types.Content(role="user", parts=parts)

                # ── OpenManus pattern: add user message FIRST, then clean ──
                self._conversation.append(user_content)

                # Trim + clean for Gemini ordering rules
                if len(self._conversation) > 20:
                    self._conversation = self._trim_conversation(self._conversation, 20)
                contents = self._clean_conversation(self._conversation)

                # Safety: if cleaning emptied everything, build a safe fresh user turn
                if not contents:
                    logger.warning("Conversation cleaned to empty — rebuilding with fresh user turn")
                    # Build a clean user turn with only text parts (no function_response)
                    safe_parts = [
                        p for p in user_content.parts
                        if not (hasattr(p, 'function_response') and p.function_response)
                    ]
                    if not safe_parts:
                        safe_parts = [types.Part.from_text(
                            text=f"TASK: {state.instruction}\nContinue with the next action."
                        )]
                    safe_user = types.Content(role="user", parts=safe_parts)
                    contents = [safe_user]
                    # Reset conversation to avoid accumulating bad state
                    self._conversation = [safe_user]

                # VALIDATE: Ensure strict alternation before calling Gemini
                contents = self._validate_conversation(contents, user_content)

                # ── 3. Call Gemini (ONE call) ──
                await self._emit_event(state, "agent_active", {
                    "agent": "gaxis",
                    "step": state.step_index,
                })

                response = await self._call_gemini(contents, gemini_tools)

                # Save model response to conversation
                if response.candidates and response.candidates[0].content:
                    self._conversation.append(response.candidates[0].content)

                # ── 4. Process response ──
                if not response.candidates or not response.candidates[0].content:
                    logger.warning("Empty response from Gemini")
                    state.retries += 1
                    if state.retries > state.max_retries:
                        state.status = "failed"
                        state.error = "No response from model"
                    continue

                candidate = response.candidates[0]
                handled = False

                for part in candidate.content.parts:
                    if part.function_call:
                        fc = part.function_call
                        fn_name = fc.name
                        fn_args = dict(fc.args) if fc.args else {}

                        obs.tool_call("gaxis", fn_name, args=fn_args,
                                     step=state.step_index, task_id=state.task_id)

                        # Handle task_complete — VERIFICATION AGENT checks before accepting
                        if fn_name == "task_complete":
                            claimed_summary = fn_args.get("summary", "")
                            state.extracted_data = fn_args.get("data", {})

                            # Announce verification is starting
                            await self._emit_event(state, "agent_active", {
                                "agent": "verifier",
                                "subtask": "Checking the result visually...",
                            })

                            # Verify: take a screenshot and confirm with Gemini vision
                            verified = await self._verify_with_screenshot(
                                state, claimed_summary,
                            )
                            if verified:
                                state.result_summary = claimed_summary
                                state.status = "done"
                                # Navigate to the scheduled date so user can see the event
                                await self._navigate_to_calendar_date(state)
                            else:
                                # Verification failed — tell agent to keep going
                                logger.warning("Verification failed — agent claimed done but page doesn't confirm")
                                state.retries += 1
                                if state.retries > state.max_retries:
                                    # Accept anyway after max retries to avoid infinite loop
                                    state.result_summary = claimed_summary
                                    state.status = "done"

                            # Append function response so conversation stays paired
                            self._conversation.append(types.Content(role="user", parts=[
                                types.Part.from_function_response(
                                    name=fn_name,
                                    response={"result": "Task completed" if state.status == "done" else "Verification failed — task does NOT appear done. Check the page and continue."},
                                )
                            ]))
                            handled = True
                            break

                        # Handle task_failed
                        if fn_name == "task_failed":
                            state.error = fn_args.get("reason", "Task failed")
                            state.status = "failed"
                            # Append function response so conversation stays paired
                            self._conversation.append(types.Content(role="user", parts=[
                                types.Part.from_function_response(
                                    name=fn_name,
                                    response={"result": "Task failed"},
                                )
                            ]))
                            handled = True
                            break

                        # Handle rollback
                        if fn_name == "rollback":
                            steps = min(fn_args.get("steps", 1), 5)
                            reason = fn_args.get("reason", "")
                            obs.rollback("gaxis", "requested", reason=reason,
                                         requested=steps, step=state.step_index,
                                         task_id=state.task_id)
                            rollback_mgr = self.tool_executor.rollback_manager
                            if rollback_mgr and rollback_mgr.can_rollback:
                                results = await rollback_mgr.rollback(
                                    n=steps, mode=state.mode,
                                    emit_fn=self.emit_fn, task_id=state.task_id,
                                )
                                undone = sum(1 for r in results if r.get("success"))
                                response_data = {
                                    "result": f"Rolled back {undone} action(s). Retry now.",
                                    "undone": undone,
                                }
                            else:
                                response_data = {
                                    "result": "No actions available to rollback. Try a different approach.",
                                }
                            self._conversation.append(types.Content(role="user", parts=[
                                types.Part.from_function_response(
                                    name="rollback", response=response_data,
                                )
                            ]))
                            # Re-capture page after rollback so LLM sees current state
                            state = await self._capture_page(state)
                            handled = True
                            break

                        # Handle extract_data
                        if fn_name == "extract_data":
                            state.extracted_data.update(fn_args.get("data", {}))
                            state.record_action({
                                "action_type": fn_name, "args": fn_args,
                                "success": True, "agent": "gaxis",
                            })
                            handled = True

                            # Send function response back
                            fn_response = types.Content(role="user", parts=[
                                types.Part.from_function_response(
                                    name=fn_name,
                                    response={"result": "Data extracted successfully"},
                                )
                            ])
                            self._conversation.append(fn_response)
                            break

                        # Emit action planned
                        await self._emit_event(state, "action_planned", {
                            "action_type": fn_name, **fn_args,
                            "step": state.step_index,
                        })

                        # Execute the action (errors → result, never crash)
                        try:
                            result = await self.tool_executor.execute(
                                fn_name, fn_args,
                                mode=state.mode,
                                emit_fn=self.emit_fn,
                                task_id=state.task_id,
                            )
                        except Exception as exec_err:
                            obs.error("gaxis", fn_name, error=str(exec_err),
                                      step=state.step_index, task_id=state.task_id)
                            result = type('R', (), {
                                'success': False, 'error': str(exec_err),
                                'result': {}, 'duration_ms': 0
                            })()

                        # Record action
                        state.record_action({
                            "action_type": fn_name, "args": fn_args,
                            "success": result.success, "error": result.error,
                            "duration_ms": result.duration_ms, "agent": "gaxis",
                        })

                        # Structured observability
                        obs.tool_result(
                            "gaxis", fn_name,
                            success=result.success,
                            error=result.error or "",
                            latency_ms=result.duration_ms,
                            target=fn_args.get("element_description", "")
                                   or fn_args.get("url", "")[:50] if fn_args.get("url") else
                                   fn_args.get("text", "")[:30] if fn_args.get("text") else "",
                            step=state.step_index,
                            task_id=state.task_id,
                        )

                        # Record to replay timeline (with screenshot for player)
                        if self._replay:
                            self._replay.record_step(
                                task_id=state.task_id,
                                step_index=state.step_index,
                                action_type=fn_name,
                                args=fn_args,
                                success=result.success,
                                error=result.error,
                                duration_ms=result.duration_ms,
                                url_before=state.page.url or "",
                                url_after=state.page.url or "",
                                screenshot_b64=state.page.screenshot_b64,
                            )

                        if result.success:
                            await self._emit_event(state, "action_succeeded", {
                                "action_type": fn_name,
                                "step": state.step_index,
                                "duration_ms": result.duration_ms,
                            })
                            state.retries = 0
                        else:
                            await self._emit_event(state, "action_failed", {
                                "error": result.error,
                                "step": state.step_index,
                            })
                            state.retries += 1
                            # Auto-rollback on 2nd consecutive failure — undo last
                            # action before the LLM retries, so it starts from a clean state
                            if state.retries == 2:
                                rollback_mgr = self.tool_executor.rollback_manager
                                if rollback_mgr and rollback_mgr.can_rollback:
                                    obs.rollback("gaxis", "auto",
                                                 reason="2 consecutive failures",
                                                 requested=1, step=state.step_index,
                                                 task_id=state.task_id)
                                    await rollback_mgr.rollback(
                                        n=1, mode=state.mode,
                                        emit_fn=self.emit_fn,
                                        task_id=state.task_id,
                                    )
                            if state.retries > state.max_retries:
                                state.status = "failed"
                                state.error = f"Max retries: {result.error}"

                        # Send function response back to Gemini conversation
                        response_msg = "success" if result.success else result.error
                        # Include rollback hint when failing
                        if not result.success and self.tool_executor.rollback_manager:
                            mgr = self.tool_executor.rollback_manager
                            if mgr.can_rollback:
                                response_msg += (
                                    " | HINT: If you typed in the wrong field or navigated "
                                    "to the wrong page, call rollback(steps=1, reason='...') "
                                    "to undo and retry."
                                )
                        fn_response = types.Content(role="user", parts=[
                            types.Part.from_function_response(
                                name=fn_name,
                                response={"result": response_msg},
                            )
                        ])
                        self._conversation.append(fn_response)

                        handled = True
                        break

                    elif part.text:
                        # Text response — agent is thinking, log and continue
                        logger.info(f"[gaxis] Text: {part.text[:100]}")

                if not handled:
                    # No function call — nudge the agent
                    state.retries += 1
                    if state.retries > state.max_retries:
                        state.status = "failed"
                        state.error = "Agent did not produce an action"

                # Brief pause between turns
                await asyncio.sleep(0.05)  # Reduced from 0.2

            except Exception as e:
                logger.error(f"FastLoop error: {e}", exc_info=True)
                state.graph_retries += 1
                if state.graph_retries > state.max_graph_retries:
                    state.status = "failed"
                    state.error = f"Max retries: {e}"
                    break
                await asyncio.sleep(0.5)

        # Final state
        if not state.is_terminal:
            if state.step_index >= state.max_steps:
                state.status = "failed"
                state.error = f"Exceeded max steps ({state.max_steps})"
            else:
                state.status = "failed"
                state.error = "Loop ended without result"

        # End replay recording
        if self._replay:
            self._replay.end_session(
                task_id=state.task_id,
                status=state.status,
                summary=state.result_summary or "",
                error=state.error,
            )
            self._replay.save(state.task_id)

        obs.lifecycle("gaxis", "task_end", task_id=state.task_id,
                      reason=state.result_summary[:60] if state.result_summary else state.error or "",
                      latency_ms=state.elapsed_ms,
                      status=state.status, steps=state.step_index)
        return state

    async def _REMOVED_deterministic_execution(self, state):
        """REMOVED — replaced by StateMachineExecutor in state_machine.py.
        Kept as dead code marker. The old methods below are also unused.

        Flow:
        1. Detect known app from instruction (calendar, gmail, etc.)
        2. ONE LLM call to extract structured values
        3. Navigate to app URL (direct extension call)
        4. Wait for page load
        5. Batch fill all form fields (direct extension call)
        6. Execute remaining graph nodes (click Meet, Save, etc.) via findByHint
        7. ONE LLM call to generate friendly summary
        """
        from backend.uigraph.model import NodeType, ActionType
        from backend.uigraph.detector import detect_app

        # Detect app from instruction keywords (before we even have a URL)
        graph = self._detect_graph_from_instruction(state.instruction)
        if not graph:
            # Check current URL if we already have one
            if state.page.url:
                graph = self._ui_graph_registry.detect_and_get(
                    state.page.url, state.page.title,
                )
            if not graph:
                return None  # Not a known app → fall through to LLM loop

        logger.info(f"⚡ Deterministic execution: {graph.app_id}")
        t_start = time.time()

        # ── Step 1: Extract task values with ONE LLM call ──
        await self._emit_event(state, "agent_active", {
            "agent": "gaxis", "step": 0, "phase": "parsing",
        })

        try:
            from backend.uigraph.prompt import extract_task_values_llm
            task_values = await extract_task_values_llm(
                state.instruction, graph, self.client,
            )
            logger.info(f"⚡ Extracted values ({int((time.time()-t_start)*1000)}ms): {task_values}")
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e} — falling back to LLM loop")
            return None

        if not task_values:
            logger.warning("No task values extracted — falling back to LLM loop")
            return None

        self._cached_task_values = task_values

        # ── Step 2: Navigate to app URL ──
        entry_url = self._get_entry_url(graph)
        if entry_url:
            await self._emit_event(state, "action_planned", {
                "action_type": "navigate", "url": entry_url,
                "step": state.step_index,
            })
            nav_result = await self.tool_executor.execute(
                "navigate", {"url": entry_url},
                mode=state.mode, emit_fn=self.emit_fn, task_id=state.task_id,
            )
            state.record_action({
                "action_type": "navigate", "args": {"url": entry_url},
                "success": nav_result.success, "error": nav_result.error,
                "duration_ms": nav_result.duration_ms, "agent": "gaxis-det",
            })
            if nav_result.success:
                await self._emit_event(state, "action_succeeded", {
                    "action_type": "navigate", "step": state.step_index,
                    "duration_ms": nav_result.duration_ms,
                })
            else:
                logger.warning(f"Navigate failed: {nav_result.error} — falling back")
                return None

            # Wait for page load
            await asyncio.sleep(1.5)

        # ── Step 3: Capture page to confirm we're on the right page ──
        state = await self._capture_page(state)

        # Verify URL matches expected pattern
        if state.page.url:
            detected_app = detect_app(state.page.url)
            if detected_app != graph.app_id:
                logger.warning(
                    f"URL mismatch: expected {graph.app_id}, got {detected_app} "
                    f"({state.page.url}) — falling back"
                )
                return None

        # ── Step 4: Batch fill form fields ──
        fill_fields = self._build_fill_fields(graph, task_values)
        if fill_fields:
            await self._emit_event(state, "action_planned", {
                "action_type": "fill_form",
                "step": state.step_index,
                "element_description": f"Filling {len(fill_fields)} fields",
            })
            fill_result = await self.tool_executor.execute(
                "fill_form", {"fields": fill_fields},
                mode=state.mode, emit_fn=self.emit_fn, task_id=state.task_id,
            )
            state.record_action({
                "action_type": "fill_form",
                "args": {"fields_count": len(fill_fields)},
                "success": fill_result.success, "error": fill_result.error,
                "duration_ms": fill_result.duration_ms, "agent": "gaxis-det",
            })
            if fill_result.success:
                await self._emit_event(state, "action_succeeded", {
                    "action_type": "fill_form", "step": state.step_index,
                    "duration_ms": fill_result.duration_ms,
                })
                logger.info(f"⚡ Batch fill done ({fill_result.duration_ms}ms)")
            else:
                logger.warning(f"Batch fill failed: {fill_result.error}")
                # Don't abort — some fields may have filled, continue with remaining nodes

            await asyncio.sleep(0.3)  # Let UI settle

        # ── Step 5: Execute remaining non-fill nodes (click Meet, Save, etc.) ──
        for node_id in graph.interaction_sequence:
            if state.is_terminal:
                break

            node = graph.get_node(node_id)
            if not node:
                continue

            # Skip nodes that were batch-filled
            if node_id in task_values and node.node_type in (NodeType.INPUT, NodeType.CHIP):
                continue

            # Skip optional nodes that have no task value
            if not node.required and node_id not in task_values:
                # Special case: meet_link is optional but we always click it
                if node_id != "meet_link":
                    continue

            # Execute this node's actions via findByHint
            await self._execute_graph_node(state, node, graph, task_values)

        # ── Step 6: Handle conditional edges (Send dialog after Save) ──
        if "guests" in task_values and task_values.get("guests"):
            # Wait for "Send invitations?" dialog
            await asyncio.sleep(1.0)
            send_dialog = graph.get_node("send_dialog")
            if send_dialog:
                await self._execute_graph_node(state, send_dialog, graph, task_values)
                await asyncio.sleep(0.5)

        # ── Step 7: Generate friendly summary with ONE LLM call ──
        elapsed_ms = int((time.time() - t_start) * 1000)
        summary = await self._generate_completion_summary(
            state.instruction, graph, task_values, elapsed_ms,
        )

        state.result_summary = summary
        state.status = "done"

        logger.info(
            f"⚡ Deterministic execution complete: {graph.app_id} "
            f"in {elapsed_ms}ms ({state.step_index} steps)"
        )

        # Navigate to the scheduled date so user can see the event
        await self._navigate_to_calendar_date(state)

        await self._emit_event(state, "task_done", {
            "summary": summary,
            "elapsed_ms": elapsed_ms,
            "mode": "deterministic",
        })

        return state

    def _detect_graph_from_instruction(self, instruction: str) -> "UIGraph | None":
        """Detect which known app to use from instruction keywords."""
        lower = instruction.lower()

        # Calendar keywords
        cal_keywords = [
            "schedule", "calendar", "event", "meeting", "appointment",
            "block", "sync", "standup", "scrum", "call",
        ]
        if any(kw in lower for kw in cal_keywords):
            graph = self._ui_graph_registry.get("gcal_event_editor")
            if graph:
                return graph

        # Gmail keywords
        mail_keywords = ["email", "mail", "send", "compose", "write to", "message"]
        if any(kw in lower for kw in mail_keywords):
            graph = self._ui_graph_registry.get("gmail_compose")
            if graph:
                return graph

        return None

    def _get_entry_url(self, graph) -> str | None:
        """Get the URL to navigate to for a known app."""
        urls = {
            "gcal_event_editor": "https://calendar.google.com/calendar/u/0/r/eventedit",
            "gmail_compose": "https://mail.google.com/mail/u/0/#inbox?compose=new",
        }
        return urls.get(graph.app_id)

    def _build_fill_fields(self, graph, task_values: dict) -> list[dict]:
        """Build fill_form fields from graph nodes and task values."""
        from backend.uigraph.model import NodeType

        fields = []
        for node_id in graph.interaction_sequence:
            node = graph.get_node(node_id)
            if not node or node_id not in task_values:
                continue

            value = task_values[node_id]
            if not value:
                continue

            # Only fill INPUT and CHIP nodes via batch fill
            if node.node_type not in (NodeType.INPUT, NodeType.CHIP):
                continue

            hints = {}
            if node.selector_hints.get("placeholder"):
                hints["placeholder"] = node.selector_hints["placeholder"]
            if node.selector_hints.get("aria"):
                hints["aria"] = node.selector_hints["aria"]
            if node.selector_hints.get("text"):
                hints["text"] = node.selector_hints["text"]
            if node.selector_hints.get("tag"):
                hints["tag"] = node.selector_hints["tag"]

            if node.node_type == NodeType.CHIP:
                action = "select_all_and_type"
                press_enter = True
                wait_after = 350
            elif node.node_type == NodeType.INPUT:
                action = "type"
                press_enter = node_id in ("guests", "to_field")
                wait_after = 50
            else:
                action = "click"
                press_enter = False
                wait_after = 50

            fields.append({
                "hints": hints,
                "value": value,
                "action": action,
                "press_enter": press_enter,
                "clear_first": True,
                "wait_after": wait_after,
            })

        return fields

    async def _execute_graph_node(self, state, node, graph, task_values):
        """Execute a single graph node via direct extension calls (no LLM)."""
        from backend.uigraph.model import NodeType, ActionType

        hints = {}
        if node.selector_hints.get("text"):
            hints["text"] = node.selector_hints["text"]
        if node.selector_hints.get("aria"):
            hints["aria"] = node.selector_hints["aria"]
        if node.selector_hints.get("placeholder"):
            hints["placeholder"] = node.selector_hints["placeholder"]
        if node.selector_hints.get("tag"):
            hints["tag"] = node.selector_hints["tag"]

        if node.node_type in (NodeType.BUTTON, NodeType.LINK, NodeType.DIALOG):
            # Click via findByHint — send as fill_form with a click action
            await self._emit_event(state, "action_planned", {
                "action_type": "click",
                "step": state.step_index,
                "element_description": f"Click '{node.label}'",
            })

            # Use fill_form with click action — it uses findByHint internally
            result = await self.tool_executor.execute(
                "fill_form",
                {"fields": [{"hints": hints, "action": "click", "wait_after": 200}]},
                mode=state.mode, emit_fn=self.emit_fn, task_id=state.task_id,
            )

            state.record_action({
                "action_type": "click",
                "args": {"element": node.label, "hints": hints},
                "success": result.success, "error": result.error,
                "duration_ms": result.duration_ms, "agent": "gaxis-det",
            })

            if result.success:
                await self._emit_event(state, "action_succeeded", {
                    "action_type": "click", "step": state.step_index,
                    "duration_ms": result.duration_ms,
                })
                logger.info(f"⚡ Clicked '{node.label}' ({result.duration_ms}ms)")
            else:
                logger.warning(f"⚡ Click failed '{node.label}': {result.error}")

            # Wait after certain actions
            if node.id == "meet_link":
                await asyncio.sleep(2.0)  # Wait for Meet link to generate
            elif node.id == "save_btn":
                await asyncio.sleep(1.0)  # Wait for save to process

        elif node.node_type == NodeType.CHECKBOX:
            # Toggle via click
            result = await self.tool_executor.execute(
                "fill_form",
                {"fields": [{"hints": hints, "action": "click"}]},
                mode=state.mode, emit_fn=self.emit_fn, task_id=state.task_id,
            )
            state.record_action({
                "action_type": "click",
                "args": {"element": node.label},
                "success": result.success, "error": result.error,
                "duration_ms": result.duration_ms, "agent": "gaxis-det",
            })

    async def _generate_completion_summary(
        self, instruction: str, graph, task_values: dict, elapsed_ms: int,
    ) -> str:
        """Generate a friendly completion summary with ONE fast LLM call."""
        from google.genai import types as gtypes

        fields_summary = "\n".join(f"  {k}: {v}" for k, v in task_values.items() if v)
        prompt = (
            f"Write a warm, helpful 1-2 sentence summary of what was accomplished. "
            f"Be specific with details. Do NOT mention technical steps.\n\n"
            f"Task: \"{instruction}\"\n"
            f"App: {graph.name}\n"
            f"Fields filled:\n{fields_summary}\n"
            f"Completed in {elapsed_ms}ms.\n\n"
            f"Summary:"
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=AGENT_MODEL,
                contents=[gtypes.Content(role="user", parts=[
                    gtypes.Part.from_text(text=prompt),
                ])],
                config=gtypes.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200,
                ),
            )
            if response.candidates and response.candidates[0].content:
                return response.candidates[0].content.parts[0].text.strip()
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")

        # Fallback summary
        title = task_values.get("title", "your event")
        date = task_values.get("start_date", "")
        time_val = task_values.get("start_time", "")
        return f"Done! {title} has been scheduled{' for ' + date if date else ''}{' at ' + time_val if time_val else ''}."

    async def _try_auto_fill(self, state: AgentState):
        """Auto-fill form fields using UI graph — bypasses per-field LLM calls.

        Returns ToolResult if auto-fill was attempted, None if not applicable.
        This is the key speed optimization: 15+ LLM calls → 1 LLM parse + 1 batch fill.
        """
        from backend.uigraph.model import NodeType

        graph = self._ui_graph_registry.detect_and_get(
            state.page.url, state.page.title
        )
        if not graph:
            return None

        # Use LLM to extract task values (handles ANY wording)
        # This is ONE fast LLM call that replaces 15+ action-planning calls
        if not self._cached_task_values:
            try:
                from backend.uigraph.prompt import extract_task_values_llm
                self._cached_task_values = await extract_task_values_llm(
                    state.instruction, graph, self.client,
                )
                logger.info(f"LLM extracted values: {self._cached_task_values}")
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}")
                from backend.uigraph.prompt import extract_task_values
                self._cached_task_values = extract_task_values(state.instruction, graph)

        task_values = self._cached_task_values
        if not task_values:
            return None

        # Build fill_form fields from graph nodes + task values
        fields = []
        for node_id in graph.interaction_sequence:
            node = graph.get_node(node_id)
            if not node:
                continue

            # Skip nodes without fill values (Meet link, Save button, etc.)
            if node_id not in task_values:
                continue

            value = task_values[node_id]
            if not value:
                continue

            # Build hints from selector_hints
            hints = {}
            if node.selector_hints.get("placeholder"):
                hints["placeholder"] = node.selector_hints["placeholder"]
            if node.selector_hints.get("aria"):
                hints["aria"] = node.selector_hints["aria"]
            if node.selector_hints.get("text"):
                hints["text"] = node.selector_hints["text"]
            if node.selector_hints.get("tag"):
                hints["tag"] = node.selector_hints["tag"]

            # Only batch-fill INPUT fields — CHIP fields (date/time) need
            # sequential visual interaction (click→wait→type→Enter) which the
            # LLM loop handles via screenshot-driven one-action-per-step.
            if node.node_type != NodeType.INPUT:
                continue

            action = "type"
            # Guests need Enter to add each email
            press_enter = node_id in ("guests", "to_field")
            wait_after = 100

            fields.append({
                "hints": hints,
                "value": value,
                "action": action,
                "press_enter": press_enter,
                "clear_first": True,
                "wait_after": wait_after,
            })

        if not fields:
            return None

        logger.info(f"Auto-fill: {len(fields)} fields from graph {graph.app_id}")
        for f in fields:
            logger.info(f"  → {f['hints']} = {f['value']!r} ({f['action']})")

        # Execute fill_form directly
        await self._emit_event(state, "action_planned", {
            "action_type": "fill_form",
            "step": state.step_index,
            "element_description": f"Auto-filling {len(fields)} fields",
        })

        result = await self.tool_executor.execute(
            "fill_form",
            {"fields": fields},
            mode=state.mode,
            emit_fn=self.emit_fn,
            task_id=state.task_id,
        )

        return result

    async def _capture_page(self, state: AgentState) -> AgentState:
        """Get screenshot + DOM from extension or Playwright."""
        if state.mode == "extension":
            if self.get_screenshot_fn:
                screenshot_b64, url, title = await self.get_screenshot_fn()
                state.page.screenshot_b64 = screenshot_b64
                state.page.url = url
                state.page.title = title
            if self.emit_fn:
                from backend.agent.core import TaskEvent
                await self.emit_fn(TaskEvent("request_dom_snapshot", state.task_id, {}))
                await asyncio.sleep(0.15)  # Reduced from 0.3 — DOM snapshots are fast
            if self.get_dom_fn:
                state.page.dom_elements = self.get_dom_fn()
        else:
            if self.get_browser_state_fn:
                browser_state = await self.get_browser_state_fn()
                state.page.screenshot_b64 = browser_state.screenshot_b64
                state.page.url = browser_state.url
                state.page.title = browser_state.title
        return state

    def _clean_conversation(self, history: list[types.Content]) -> list[types.Content]:
        """Sanitize conversation for Gemini's strict turn ordering.

        Gemini rules:
        1. Must start with user turn
        2. Strict alternation: user → model → user → model
        3. A model turn with function_call MUST be followed by user turn with function_response
        4. A user turn with function_response must ONLY contain function_response parts
        5. No orphan function_calls or function_responses

        Strategy: Build a clean sequence by walking through history and only
        keeping well-formed (user, model-fc, user-fr) triplets and plain user/model turns.
        Drop everything after the last properly paired turn if it doesn't fit.
        """
        if not history:
            return []

        cleaned = []
        i = 0

        while i < len(history):
            msg = history[i]
            if not msg.parts:
                i += 1
                continue

            role = getattr(msg, 'role', None)
            has_fc = any(hasattr(p, 'function_call') and p.function_call for p in msg.parts)
            has_fr = any(hasattr(p, 'function_response') and p.function_response for p in msg.parts)

            # Skip orphan function_responses
            if has_fr and not (cleaned and has_fc_in_last_model(cleaned)):
                i += 1
                continue

            if role == "model" and has_fc:
                # Model with function_call — need the next message to be user with function_response
                if i + 1 < len(history):
                    next_msg = history[i + 1]
                    next_has_fr = any(
                        hasattr(p, 'function_response') and p.function_response
                        for p in (next_msg.parts or [])
                    )
                    if next_has_fr and getattr(next_msg, 'role', None) == "user":
                        # Valid fc → fr pair. But check alternation.
                        if not cleaned or getattr(cleaned[-1], 'role', None) == "user":
                            cleaned.append(msg)
                            # Only keep function_response parts in the fr turn
                            fr_parts = [
                                p for p in next_msg.parts
                                if hasattr(p, 'function_response') and p.function_response
                            ]
                            cleaned.append(types.Content(role="user", parts=fr_parts))
                            i += 2
                            continue
                # Can't pair it — drop
                i += 1
                continue

            if role == "model" and not has_fc:
                # Plain model turn — check alternation
                if not cleaned or getattr(cleaned[-1], 'role', None) == "user":
                    cleaned.append(msg)
                # else: consecutive model turns — skip
                i += 1
                continue

            if role == "user" and has_fr:
                # User with function_response — should only appear after model fc
                # If it's orphaned here, skip
                if cleaned and has_fc_in_last_model(cleaned):
                    fr_parts = [
                        p for p in msg.parts
                        if hasattr(p, 'function_response') and p.function_response
                    ]
                    cleaned.append(types.Content(role="user", parts=fr_parts))
                i += 1
                continue

            if role == "user":
                # Plain user turn
                if not cleaned or getattr(cleaned[-1], 'role', None) != "user":
                    cleaned.append(msg)
                else:
                    # Consecutive user turns — but DON'T replace a function_response turn!
                    prev = cleaned[-1]
                    prev_has_fr = any(
                        hasattr(p, 'function_response') and p.function_response
                        for p in (prev.parts or [])
                    )
                    if prev_has_fr:
                        # Previous is function_response — merge new parts into it
                        merged_parts = list(prev.parts or []) + list(msg.parts or [])
                        cleaned[-1] = types.Content(role="user", parts=merged_parts)
                    else:
                        # Both are plain user turns — keep latest
                        cleaned[-1] = msg
                i += 1
                continue

            i += 1

        # Must start with user turn
        while cleaned and getattr(cleaned[0], 'role', None) != "user":
            cleaned.pop(0)

        # Must end with user turn (Gemini expects user turn last for generate)
        while cleaned and getattr(cleaned[-1], 'role', None) == "model":
            last = cleaned[-1]
            last_has_fc = any(hasattr(p, 'function_call') and p.function_call for p in (last.parts or []))
            if last_has_fc:
                # Drop orphan fc + its preceding user if that would leave a dangling model
                cleaned.pop()
            else:
                cleaned.pop()

        return cleaned

    def _trim_conversation(self, history: list[types.Content], max_len: int) -> list[types.Content]:
        """Trim conversation to max_len without splitting function_call/response pairs."""
        if len(history) <= max_len:
            return history

        # Work backwards from end, keeping pairs together
        trimmed = history[-max_len:]

        # If we start with a function_response (orphan), drop it
        if trimmed and trimmed[0].parts:
            first_has_fr = any(
                hasattr(p, 'function_response') and p.function_response
                for p in trimmed[0].parts
            )
            if first_has_fr:
                trimmed = trimmed[1:]

        # If we start with a model turn (not user), drop it
        if trimmed and getattr(trimmed[0], 'role', None) == "model":
            trimmed = trimmed[1:]

        return trimmed

    def _validate_conversation(
        self, contents: list[types.Content], fallback_user: types.Content,
    ) -> list[types.Content]:
        """Final safety check — guarantee Gemini's ordering rules are met.

        If anything is wrong, nuke the conversation and use only the latest user turn.
        This is the last line of defense against 400 INVALID_ARGUMENT.
        """
        def _safe_fallback() -> list[types.Content]:
            """Build a fallback that's guaranteed to be a valid user turn with text."""
            safe_parts = [
                p for p in fallback_user.parts
                if not (hasattr(p, 'function_response') and p.function_response)
            ]
            if safe_parts:
                return [types.Content(role="user", parts=safe_parts)]
            # Absolute last resort — plain text turn
            return [types.Content(role="user", parts=[
                types.Part.from_text(text="Continue with the next action.")
            ])]

        if not contents:
            return _safe_fallback()

        # Rule 1: Must start with user
        if getattr(contents[0], 'role', None) != "user":
            logger.warning("Validate: doesn't start with user — resetting")
            return _safe_fallback()

        # Rule 2: Check strict alternation (user, model, user, model...)
        # Exception: user with function_response after model with function_call is OK
        for i in range(1, len(contents)):
            prev_role = getattr(contents[i - 1], 'role', None)
            curr_role = getattr(contents[i], 'role', None)

            if curr_role == prev_role:
                # Same role back-to-back — this should have been caught by _clean
                logger.warning(
                    f"Validate: consecutive {curr_role} at [{i-1},{i}] — resetting"
                )
                return _safe_fallback()

        # Rule 3: Every model turn with function_call must be followed by user with function_response
        for i, msg in enumerate(contents):
            if getattr(msg, 'role', None) != "model":
                continue
            has_fc = any(
                hasattr(p, 'function_call') and p.function_call
                for p in (msg.parts or [])
            )
            if not has_fc:
                continue
            # Must have a next message that's user with function_response
            if i + 1 >= len(contents):
                logger.warning(f"Validate: trailing function_call at [{i}] — dropping it")
                return self._validate_conversation(contents[:i], fallback_user)
            next_msg = contents[i + 1]
            if getattr(next_msg, 'role', None) != "user":
                logger.warning(f"Validate: fc at [{i}] not followed by user — resetting")
                return _safe_fallback()
            has_fr = any(
                hasattr(p, 'function_response') and p.function_response
                for p in (next_msg.parts or [])
            )
            if not has_fr:
                logger.warning(f"Validate: fc at [{i}] followed by user without fr — resetting")
                return _safe_fallback()

        # Rule 4: Must NOT end with model (Gemini expects user turn last)
        if getattr(contents[-1], 'role', None) == "model":
            logger.warning("Validate: ends with model — dropping last")
            return self._validate_conversation(contents[:-1], fallback_user)

        return contents

    async def _call_gemini(self, contents, tools, max_retries=3):
        """Call Gemini with retry on 429 (rate limit) only.

        Uses VISION_MODEL (Pro) for accurate screenshot analysis,
        coordinate picking, and tool call reasoning.
        """
        for attempt in range(max_retries + 1):
            try:
                return await self.client.aio.models.generate_content(
                    model=VISION_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=UNIFIED_SYSTEM,
                        temperature=0.2,
                        max_output_tokens=4096,
                        tools=tools,
                    ),
                )
            except Exception as e:
                err_str = str(e)
                retryable = ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str)
                # 400 INVALID_ARGUMENT — conversation is malformed
                if "400" in err_str and "INVALID_ARGUMENT" in err_str:
                    logger.error(f"Gemini 400: {err_str[:200]}")
                    # Log conversation structure for debugging
                    for idx, c in enumerate(contents):
                        role = getattr(c, 'role', '?')
                        has_fc = any(hasattr(p, 'function_call') and p.function_call for p in (c.parts or []))
                        has_fr = any(hasattr(p, 'function_response') and p.function_response for p in (c.parts or []))
                        logger.error(f"  [{idx}] role={role} fc={has_fc} fr={has_fr} parts={len(c.parts or [])}")
                    # Nuclear recovery: wipe conversation, use ONLY the last user content
                    # Find last user content that has text (screenshot + DOM), not function_response
                    fresh_user = None
                    for c in reversed(contents):
                        if getattr(c, 'role', None) != 'user':
                            continue
                        has_fr = any(hasattr(p, 'function_response') and p.function_response for p in (c.parts or []))
                        has_text = any(hasattr(p, 'text') and p.text for p in (c.parts or []))
                        if has_text and not has_fr:
                            fresh_user = c
                            break
                    if not fresh_user:
                        # Build a minimal user message
                        fresh_user = types.Content(role="user", parts=[
                            types.Part.from_text(text="Continue with the task. What is the next action?")
                        ])
                    self._conversation = [fresh_user]
                    logger.info("400 recovery: reset to single user message")
                    return await self.client.aio.models.generate_content(
                        model=VISION_MODEL,
                        contents=[fresh_user],
                        config=types.GenerateContentConfig(
                            system_instruction=UNIFIED_SYSTEM,
                            temperature=0.2,
                            max_output_tokens=4096,
                            tools=tools,
                        ),
                    )
                if retryable and attempt < max_retries:
                    wait = min(2 ** attempt * 3, 20)
                    logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def _emit_event(self, state, event_type, data):
        if self.emit_fn:
            from backend.agent.core import TaskEvent
            await self.emit_fn(TaskEvent(event_type, state.task_id, data))

    async def _verify_with_screenshot(self, state: AgentState, claimed_summary: str) -> bool:
        """Take a screenshot and ask Gemini vision if the task actually completed.

        This is the verification step that runs across ALL execution paths
        (fast loop, research loop, state machine) before accepting task_complete.
        """
        try:
            # Capture fresh screenshot
            state = await self._capture_page(state)
            if not state.page.screenshot_b64:
                logger.warning("Verify: no screenshot available — accepting claim")
                return True

            image_bytes = base64.b64decode(state.page.screenshot_b64)
            parts = [
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                types.Part.from_text(text=(
                    f"TASK: {state.instruction}\n"
                    f"AGENT CLAIMS: \"{claimed_summary}\"\n"
                    f"URL: {state.page.url}\n\n"
                    f"Look at the screenshot. Did the task ACTUALLY complete?\n"
                    f"Signs of success: page redirected (calendar grid, inbox, doc content visible), "
                    f"toast notification, form no longer visible, confirmation dialog.\n"
                    f"Signs of FAILURE: still on the form, error message, empty doc, login page.\n\n"
                    f"Return ONLY JSON: {{\"verified\": true/false, \"evidence\": \"what you see\"}}"
                )),
            ]

            response = await self.client.aio.models.generate_content(
                model=VISION_MODEL,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    temperature=0.0, max_output_tokens=200,
                ),
            )

            if response.candidates and response.candidates[0].content:
                import re as _re
                text = response.candidates[0].content.parts[0].text.strip()
                text = _re.sub(r"^```(?:json)?\s*", "", text)
                text = _re.sub(r"\s*```$", "", text)
                import json as _json
                data = _json.loads(text)
                verified = data.get("verified", False)
                evidence = data.get("evidence", "")
                logger.info(f"Verify: {'PASS' if verified else 'FAIL'} — {evidence[:80]}")
                await self._emit_event(state, "verification", {
                    "verified": verified, "evidence": evidence,
                })
                return verified

        except Exception as e:
            logger.warning(f"Verify: error ({e}) — accepting claim")

        return True  # On error, accept to avoid blocking

    def _friendly_summary(self, conn_name: str, skill_name: str, data: dict) -> str:
        """Generate a human-friendly summary for deterministic skill completions."""
        title = data.get("title", "")
        date = data.get("start_date", data.get("date", ""))
        time_str = data.get("start_time", "")

        if "calendar" in conn_name and "create" in skill_name:
            parts = [f'Created calendar event "{title}"' if title else "Created a calendar event"]
            if date:
                parts.append(f"on {date}")
            if time_str:
                parts.append(f"at {time_str}")
            return " ".join(parts) + "."
        elif "gmail" in conn_name and "send" in skill_name:
            to = data.get("to", "")
            return f'Sent email to {to}.' if to else "Email sent successfully."
        elif "gmail" in conn_name and "compose" in skill_name:
            return f'Composed email "{title}".' if title else "Email composed."
        elif "docs" in conn_name:
            return f'Created Google Doc "{title}".' if title else "Google Doc created."
        elif "sheets" in conn_name:
            return f'Updated Google Sheet "{title}".' if title else "Google Sheet updated."
        elif "meet" in conn_name:
            return "Google Meet session set up."
        elif "drive" in conn_name:
            return f'Opened "{title}" in Drive.' if title else "Google Drive action completed."
        else:
            # Fallback: still human-readable
            return f"Completed {skill_name.replace('_', ' ')} successfully."

    async def _get_latest_screenshot(self, state: AgentState) -> str | None:
        """Get the latest screenshot, requesting a fresh one if needed."""
        # Small delay to let extension send the post-action screenshot
        await asyncio.sleep(0.5)
        state = await self._capture_page(state)
        return state.page.screenshot_b64

    async def _navigate_to_calendar_date(self, state: AgentState):
        """After a calendar task completes, navigate to the scheduled date so the user can see the event."""
        import re as _re
        from datetime import datetime, timedelta

        # Only for calendar-related tasks
        cal_keywords = ["schedule", "calendar", "event", "meeting", "appointment"]
        if not any(kw in state.instruction.lower() for kw in cal_keywords):
            return

        # Try to extract date from planner slots, extracted data, or cached task values
        date_str = None
        sources = [
            state.task.planner_slots if state.task and state.task.planner_slots else {},
            state.extracted_data or {},
            self._cached_task_values or {},
        ]
        for src in sources:
            for key in ("start_date", "date", "event_date"):
                if key in src and src[key]:
                    date_str = src[key]
                    break
            if date_str:
                break

        if not date_str:
            return

        # Parse date — try multiple formats
        target_date = None
        formats = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"]
        for fmt in formats:
            try:
                target_date = datetime.strptime(date_str.strip(), fmt)
                break
            except ValueError:
                continue
        if not target_date:
            # Try month-day only (no year)
            for fmt in ["%B %d", "%b %d"]:
                try:
                    target_date = datetime.strptime(date_str.strip(), fmt)
                    target_date = target_date.replace(year=datetime.now().year)
                    break
                except ValueError:
                    continue
        if not target_date:
            if "tomorrow" in date_str.lower():
                target_date = datetime.now() + timedelta(days=1)
            elif "today" in date_str.lower():
                target_date = datetime.now()

        if not target_date:
            return

        # Navigate to calendar day view for that date
        cal_url = (
            f"https://calendar.google.com/calendar/u/0/r/day/"
            f"{target_date.year}/{target_date.month}/{target_date.day}"
        )
        logger.info(f"Navigating to calendar date: {cal_url}")
        try:
            await self.tool_executor.execute(
                "navigate", {"url": cal_url},
                mode=state.mode, emit_fn=self.emit_fn, task_id=state.task_id,
            )
            await asyncio.sleep(1.5)  # Let the page load
        except Exception as e:
            logger.warning(f"Calendar date navigation failed: {e}")

    def _format_dom(self, elements: list[dict]) -> str:
        lines = []
        for el in elements:
            tag = el.get("tag", "?")
            text = (el.get("text", "") or "")[:60]
            x, y = el.get("x", 0), el.get("y", 0)
            w, h = el.get("width", 0), el.get("height", 0)
            placeholder = el.get("placeholder", "") or ""
            aria = el.get("ariaLabel", "") or ""
            el_id = el.get("id", "") or ""
            href = (el.get("href", "") or "")[:60]

            desc = ""
            if el_id:
                desc += f" id={el_id}"
            if placeholder:
                desc += f' placeholder="{placeholder}"'
            if aria:
                desc += f' aria="{aria}"'
            if href:
                desc += f" href={href}"

            lines.append(f"  [{tag}] \"{text}\" at ({x},{y}) {w}x{h}{desc}")
        return "\n".join(lines) or "  (no elements)"
