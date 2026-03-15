"""Base agent class — foundation for all specialist agents.

Handles Gemini API calls with function/tool calling, conversation
management, and the step() interface used by the graph runner.

Conversation history follows the OpenManus pattern:
  user → model(function_call) → user(function_response) → model → ...
A fresh user message is ALWAYS injected before every LLM call so
Gemini never sees two model turns in a row or an orphan function_call.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from google import genai
from google.genai import types

from backend.agent.state import AgentState, PageContext
from backend.tools.executor import ToolExecutor, ToolResult
from backend.observability.logger import obs

logger = logging.getLogger("gaxis.agent")

# Fast model for structured extraction, planning, verification (no vision needed)
AGENT_MODEL = "gemini-3.1-flash-lite-preview"

# Pro model for screenshot analysis, coordinate picking, and tool calling
VISION_MODEL = "gemini-3.1-pro-preview"

# Max conversation messages to keep (sliding window)
MAX_HISTORY = 40

# Duplicate response threshold for stuck detection
STUCK_THRESHOLD = 2


class BaseAgent(ABC):
    """Abstract base for all G-Axis agents."""

    def __init__(
        self,
        name: str,
        client: genai.Client,
        tool_executor: ToolExecutor,
        tools: list[types.FunctionDeclaration],
        system_prompt: str,
        emit_fn: Callable[[object], Awaitable[None]] | None = None,
    ):
        self.name = name
        self.client = client
        self.tool_executor = tool_executor
        self.tools = tools
        self.system_prompt = system_prompt
        self.emit_fn = emit_fn
        self.event_bus = None  # Injected by AgentGraph
        self._memory: list[types.Content] = []

    # ── Backwards compat alias ──
    @property
    def _conversation_history(self):
        return self._memory

    @_conversation_history.setter
    def _conversation_history(self, value):
        self._memory = value

    def reset(self) -> None:
        """Clear conversation history for a new task."""
        self._memory = []

    async def emit_event(
        self, event_type, task_id: str = "", **kwargs,
    ) -> None:
        """Emit a typed event on the bus (if available)."""
        if self.event_bus is None:
            return
        from backend.agent.events import AgentEvent
        event = AgentEvent(
            type=event_type,
            source=self.name,
            task_id=task_id,
            agent=kwargs.pop("agent", self.name),
            summary=kwargs.pop("summary", ""),
            error=kwargs.pop("error", ""),
            subtask_index=kwargs.pop("subtask_index", -1),
            data=kwargs,
        )
        await self.event_bus.emit(event)

    # ────────────────────────────────────────────────────────
    #  Memory helpers (OpenManus-inspired)
    # ────────────────────────────────────────────────────────

    def _add_to_memory(self, content: types.Content) -> None:
        """Append a message and enforce sliding window."""
        self._memory.append(content)
        if len(self._memory) > MAX_HISTORY:
            self._memory = self._memory[-MAX_HISTORY:]

    def _safe_memory_for_api(self) -> list[types.Content]:
        """Return a copy of memory guaranteed to satisfy Gemini ordering.

        Rules enforced:
        1. Starts with a user turn
        2. Strict user/model alternation
        3. Every model function_call is immediately followed by a
           user function_response
        4. No orphan function_responses
        5. Must not end with model turn
        """
        # ── Pass 1: pair function_call/response, drop orphans ──
        paired: list[types.Content] = []
        i = 0
        history = self._memory

        while i < len(history):
            msg = history[i]
            if not msg.parts:
                i += 1
                continue

            has_fc = any(
                hasattr(p, "function_call") and p.function_call
                for p in msg.parts
            )
            has_fr = any(
                hasattr(p, "function_response") and p.function_response
                for p in msg.parts
            )

            if has_fc:
                # Must be followed by function_response — keep pair or skip both
                if i + 1 < len(history) and history[i + 1].parts:
                    next_has_fr = any(
                        hasattr(p, "function_response") and p.function_response
                        for p in history[i + 1].parts
                    )
                    if next_has_fr:
                        paired.append(msg)
                        paired.append(history[i + 1])
                        i += 2
                        continue
                # No matching response — drop the function_call turn
                i += 1
                continue

            if has_fr:
                # Orphan function_response — skip
                i += 1
                continue

            paired.append(msg)
            i += 1

        # ── Pass 2: enforce strict user/model alternation ──
        cleaned: list[types.Content] = []
        for msg in paired:
            role = getattr(msg, "role", None)
            if not cleaned:
                if role == "user":
                    cleaned.append(msg)
                continue

            prev_role = getattr(cleaned[-1], "role", None)
            if role != prev_role:
                cleaned.append(msg)
            else:
                # Consecutive same-role — merge user turns, skip duplicate model turns
                if role == "user":
                    # Merge: keep function_response parts separate, combine text
                    prev_has_fr = any(
                        hasattr(p, "function_response") and p.function_response
                        for p in (cleaned[-1].parts or [])
                    )
                    curr_has_fr = any(
                        hasattr(p, "function_response") and p.function_response
                        for p in (msg.parts or [])
                    )
                    if prev_has_fr:
                        # Previous is function_response — merge new parts into it
                        merged_parts = list(cleaned[-1].parts or []) + list(msg.parts or [])
                        cleaned[-1] = types.Content(role="user", parts=merged_parts)
                    elif curr_has_fr:
                        # Current is function_response but previous is plain — keep current
                        # (this shouldn't happen after pass 1, but be safe)
                        merged_parts = list(cleaned[-1].parts or []) + list(msg.parts or [])
                        cleaned[-1] = types.Content(role="user", parts=merged_parts)
                    else:
                        # Both plain user turns — keep the latest
                        cleaned[-1] = msg
                # else: consecutive model turns — drop the duplicate

        # Must start with user turn
        while cleaned and getattr(cleaned[0], "role", None) == "model":
            cleaned.pop(0)

        # Must not end with model turn
        while cleaned and getattr(cleaned[-1], "role", None) == "model":
            cleaned.pop()

        return cleaned

    def _is_stuck(self) -> bool:
        """Detect repeated identical model responses (stuck agent)."""
        model_msgs = [
            m for m in self._memory
            if getattr(m, "role", None) == "model" and m.parts
        ]
        if len(model_msgs) < STUCK_THRESHOLD + 1:
            return False
        last_text = self._extract_text(model_msgs[-1])
        if not last_text:
            return False
        dup_count = sum(
            1 for m in model_msgs[-(STUCK_THRESHOLD + 1):-1]
            if self._extract_text(m) == last_text
        )
        return dup_count >= STUCK_THRESHOLD

    @staticmethod
    def _extract_text(content: types.Content) -> str | None:
        for p in (content.parts or []):
            if hasattr(p, "text") and p.text:
                return p.text
        return None

    # ────────────────────────────────────────────────────────
    #  Abstract interface
    # ────────────────────────────────────────────────────────

    @abstractmethod
    async def step(self, state: AgentState) -> AgentState:
        """Process one step in the agent graph."""
        ...

    # ────────────────────────────────────────────────────────
    #  Gemini API call with retry
    # ────────────────────────────────────────────────────────

    async def _call_with_retry(
        self,
        contents: list[types.Content],
        gemini_tools,
        max_retries: int = 3,
    ) -> types.GenerateContentResponse:
        """Call Gemini with exponential backoff on 429 / RESOURCE_EXHAUSTED."""
        # Use VISION_MODEL for agents that analyze screenshots + pick coordinates
        model = getattr(self, '_model_override', None) or AGENT_MODEL
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self.client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=0.2,
                        max_output_tokens=4096,
                        tools=gemini_tools,
                    ),
                )
            except Exception as e:
                last_err = e
                err_str = str(e)
                retryable = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                if retryable and attempt < max_retries:
                    wait = min(2 ** attempt * 5, 60)
                    logger.warning(
                        f"[{self.name}] Rate limited, waiting {wait}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    # ────────────────────────────────────────────────────────
    #  call_gemini — single LLM turn
    # ────────────────────────────────────────────────────────

    async def call_gemini(
        self,
        state: AgentState,
        user_prompt: str,
        include_screenshot: bool = True,
        include_dom: bool = True,
    ) -> types.GenerateContentResponse:
        """Call Gemini with a fresh user message (OpenManus pattern).

        Always injects a user turn so Gemini never sees consecutive
        model turns or a model turn after a function_response gap.
        """
        # ── Build user content ──
        parts: list[types.Part] = []

        if include_screenshot and state.page.screenshot_b64:
            image_bytes = base64.b64decode(state.page.screenshot_b64)
            parts.append(
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            )

        if include_dom and state.page.dom_elements:
            dom_text = self._format_dom_elements(state.page.dom_elements)
            parts.append(
                types.Part.from_text(
                    text=f"\nDOM ELEMENTS (precise coordinates):\n{dom_text}"
                )
            )

        parts.append(types.Part.from_text(text=user_prompt))
        user_content = types.Content(role="user", parts=parts)

        # ── Add user message to memory FIRST (OpenManus pattern) ──
        self._add_to_memory(user_content)

        # ── Build API payload from sanitised memory ──
        contents = self._safe_memory_for_api()

        gemini_tools = (
            [types.Tool(function_declarations=self.tools)] if self.tools else None
        )

        response = await self._call_with_retry(contents, gemini_tools)

        # ── Save model response to memory ──
        if response.candidates and response.candidates[0].content:
            self._add_to_memory(response.candidates[0].content)

        return response

    # ────────────────────────────────────────────────────────
    #  call_gemini_with_tool_loop — full function-calling cycle
    # ────────────────────────────────────────────────────────

    async def call_gemini_with_tool_loop(
        self,
        state: AgentState,
        user_prompt: str,
        max_tool_calls: int = 5,
        include_screenshot: bool = True,
    ) -> tuple[AgentState, str | None]:
        """Call Gemini and execute tool calls in a loop.

        Conversation flow per iteration:
          user(prompt) → model(function_call) → user(function_response) → model …
        """
        response = await self.call_gemini(
            state, user_prompt, include_screenshot=include_screenshot
        )
        text_response = None
        tool_calls_made = 0

        while tool_calls_made < max_tool_calls:
            if not response.candidates or not response.candidates[0].content:
                break

            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                break

            has_function_call = False

            for part in candidate.content.parts:
                if part.text:
                    text_response = part.text

                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}

                    obs.tool_call(
                        self.name, fn_name, args=fn_args,
                        step=state.step_index, task_id=state.task_id,
                    )

                    # ── Control-flow tools (no browser execution) ──
                    if fn_name == "task_complete":
                        # Only verifier can truly complete a task.
                        # Other agents can claim completion but graph will route to verifier.
                        if self.name == "orchestrator":
                            logger.warning(f"[orchestrator] Tried to call task_complete directly — blocked. Must delegate to verifier.")
                            # Inject nudge to delegate to verifier instead
                            nudge = types.Content(
                                role="user",
                                parts=[types.Part.from_function_response(
                                    name="task_complete",
                                    response={"error": "You cannot call task_complete. You must delegate to verifier first. Use delegate(agent='verifier', instruction='Verify that...')"},
                                )],
                            )
                            self._add_to_memory(nudge)
                            tool_calls_made += 1
                            # Continue the loop — Gemini will see the error and delegate
                            gemini_tools = (
                                [types.Tool(function_declarations=self.tools)]
                                if self.tools else None
                            )
                            contents = self._safe_memory_for_api()
                            response = await self._call_with_retry(contents, gemini_tools)
                            if response.candidates and response.candidates[0].content:
                                self._add_to_memory(response.candidates[0].content)
                            break  # break inner for-loop, continue outer while
                        state.result_summary = fn_args.get("summary", "")
                        if fn_args.get("data"):
                            state.extracted_data.update(fn_args["data"])
                        # Emit event for decoupled routing
                        from backend.agent.events import EventType
                        await self.emit_event(
                            EventType.AGENT_COMPLETED,
                            task_id=state.task_id,
                            summary=fn_args.get("summary", ""),
                        )
                        return state, fn_args.get("summary")

                    if fn_name == "task_failed":
                        state.error = fn_args.get("reason", "Task failed")
                        state.status = "failed"
                        from backend.agent.events import EventType
                        await self.emit_event(
                            EventType.AGENT_FAILED,
                            task_id=state.task_id,
                            error=fn_args.get("reason", "Task failed"),
                        )
                        return state, fn_args.get("reason")

                    if fn_name == "task_partial":
                        # Task partially complete — store missing items for fix routing
                        summary = fn_args.get("summary", "")
                        missing = fn_args.get("missing", [])
                        state.runtime.partial_result = {
                            "summary": summary,
                            "missing": missing,
                        }
                        logger.info(
                            f"[{self.name}] Task partial: {summary} "
                            f"({len(missing)} missing items)"
                        )
                        from backend.agent.events import EventType
                        await self.emit_event(
                            EventType.VERIFICATION_PARTIAL,
                            task_id=state.task_id,
                            summary=summary,
                            missing_count=len(missing),
                            missing=missing,
                        )
                        return state, summary

                    if fn_name == "rollback":
                        steps = min(fn_args.get("steps", 1), 5)
                        reason = fn_args.get("reason", "")
                        obs.rollback(self.name, "requested", reason=reason,
                                     requested=steps, step=state.step_index,
                                     task_id=state.task_id)
                        rollback_mgr = self.tool_executor.rollback_manager
                        if rollback_mgr and rollback_mgr.can_rollback:
                            results = await rollback_mgr.rollback(
                                n=steps, mode=state.mode,
                                emit_fn=self.emit_fn, task_id=state.task_id,
                            )
                            undone = sum(1 for r in results if r.get("success"))
                            fn_response = types.Content(
                                role="user",
                                parts=[types.Part.from_function_response(
                                    name="rollback",
                                    response={
                                        "success": True,
                                        "undone": undone,
                                        "requested": steps,
                                        "results": results,
                                        "message": f"Rolled back {undone} action(s). Retry your action now.",
                                    },
                                )],
                            )
                        else:
                            fn_response = types.Content(
                                role="user",
                                parts=[types.Part.from_function_response(
                                    name="rollback",
                                    response={
                                        "success": False,
                                        "error": "No actions available to rollback",
                                    },
                                )],
                            )
                        self._add_to_memory(fn_response)
                        tool_calls_made += 1
                        # Continue loop so agent can retry
                        gemini_tools = (
                            [types.Tool(function_declarations=self.tools)]
                            if self.tools else None
                        )
                        contents = self._safe_memory_for_api()
                        response = await self._call_with_retry(contents, gemini_tools)
                        if response.candidates and response.candidates[0].content:
                            self._add_to_memory(response.candidates[0].content)
                        break  # break inner for-loop, continue outer while

                    if fn_name == "confirm_action":
                        # Show confirmation card to user and wait
                        logger.info(f"[{self.name}] Showing confirmation card: {fn_args.get('card_title', '')}")
                        if self.emit_fn:
                            from backend.agent.core import TaskEvent
                            await self.emit_fn(TaskEvent("confirm_action", state.task_id, {
                                "action_type": fn_args.get("action_type", "default"),
                                "title": fn_args.get("card_title", "Confirm Action"),
                                "icon": fn_args.get("action_type", "default"),
                                "button_label": fn_args.get("button_label", "Create"),
                                "fields": fn_args.get("fields", []),
                            }))
                        # Wait for user confirmation (reuses approval gate)
                        from backend.agent.core import GAxisAgent
                        # The approval gate is on the main agent — find it via the graph
                        # For now, we record the action and let the graph handle it
                        state.status = "awaiting_approval"
                        state.record_action({
                            "agent": self.name,
                            "action_type": "confirm_action",
                            "args": fn_args,
                            "success": True,
                        })
                        # Return a function response so conversation stays valid
                        fn_response = types.Content(
                            role="user",
                            parts=[types.Part.from_function_response(
                                name="confirm_action",
                                response={"status": "waiting_for_user_confirmation"},
                            )],
                        )
                        self._add_to_memory(fn_response)
                        return state, "Waiting for user confirmation"

                    if fn_name == "plan_task":
                        # Planner decomposed the task — create SubTask entries
                        from backend.agent.state import SubTask
                        subtasks_data = fn_args.get("subtasks", [])
                        strategy = fn_args.get("strategy", "")
                        logger.info(f"[{self.name}] Plan created: {strategy} ({len(subtasks_data)} subtasks)")
                        state.subtasks = []
                        for i, st_data in enumerate(subtasks_data):
                            state.subtasks.append(SubTask(
                                index=i,
                                instruction=st_data.get("instruction", ""),
                                agent=st_data.get("agent", "navigator"),
                                status="pending",
                            ))
                        state.current_subtask_index = 0
                        # Mark first subtask as in_progress
                        if state.subtasks:
                            state.subtasks[0].status = "in_progress"
                        # Route to orchestrator to start executing subtasks
                        state.current_agent = "orchestrator"
                        # Record plan in action history
                        state.record_action({
                            "agent": self.name,
                            "action_type": "plan_task",
                            "args": {"strategy": strategy, "subtask_count": len(subtasks_data)},
                            "success": True,
                            "duration_ms": 0,
                        })
                        from backend.agent.events import EventType as _ET
                        await self.emit_event(
                            _ET.AGENT_COMPLETED,
                            task_id=state.task_id,
                            summary=f"Plan: {strategy}",
                            subtask_count=len(subtasks_data),
                        )
                        return state, strategy

                    if fn_name == "delegate":
                        target_agent = fn_args.get("agent", "navigator")
                        state.current_agent = target_agent
                        if (
                            state.current_subtask
                            and state.current_subtask.status == "in_progress"
                        ):
                            state.current_subtask.status = "done"
                        from backend.agent.state import SubTask

                        subtask = SubTask(
                            index=len(state.subtasks),
                            instruction=fn_args.get("instruction", ""),
                            agent=target_agent,
                            status="pending",
                        )
                        state.subtasks.append(subtask)
                        state.current_subtask_index = len(state.subtasks) - 1
                        from backend.agent.events import EventType as _ET
                        await self.emit_event(
                            _ET.DELEGATION_REQUESTED,
                            task_id=state.task_id,
                            agent=target_agent,
                            summary=fn_args.get("instruction", ""),
                        )
                        return state, fn_args.get("instruction")

                    # ── Execute the tool ──
                    if fn_name == "extract_data":
                        state.extracted_data.update(fn_args.get("data", {}))
                        tool_result = ToolResult(
                            name=fn_name,
                            success=True,
                            result={"extracted": fn_args.get("data", {})},
                            duration_ms=0,
                        )
                    else:
                        try:
                            tool_result = await self.tool_executor.execute(
                                function_name=fn_name,
                                function_args=fn_args,
                                mode=state.mode,
                                emit_fn=self.emit_fn,
                                task_id=state.task_id,
                            )
                        except Exception as e:
                            # Tool errors → result, never crash the loop
                            logger.error(f"[{self.name}] Tool exec error: {e}")
                            tool_result = ToolResult(
                                name=fn_name,
                                success=False,
                                result={},
                                error=str(e),
                                duration_ms=0,
                            )

                    # Record action
                    state.record_action(
                        {
                            "agent": self.name,
                            "action_type": fn_name,
                            "args": fn_args,
                            "success": tool_result.success,
                            "error": tool_result.error,
                            "duration_ms": tool_result.duration_ms,
                        }
                    )

                    # Structured observability log
                    obs.tool_result(
                        self.name, fn_name,
                        success=tool_result.success,
                        error=tool_result.error or "",
                        latency_ms=tool_result.duration_ms,
                        target=fn_args.get("element_description", "")
                               or fn_args.get("url", "")
                               or fn_args.get("text", "")[:40] if fn_args.get("text") else "",
                        step=state.step_index,
                        task_id=state.task_id,
                    )

                    # Emit typed events for key actions
                    if self.event_bus:
                        from backend.agent.events import EventType as _ET
                        if fn_name == "navigate":
                            etype = _ET.PAGE_NAVIGATED if tool_result.success else _ET.NAVIGATION_FAILED
                            await self.emit_event(
                                etype, task_id=state.task_id,
                                url=fn_args.get("url", ""),
                                error=tool_result.error or "",
                            )
                        elif fn_name == "fill_form":
                            etype = _ET.FORM_FILLED if tool_result.success else _ET.FORM_FILL_FAILED
                            await self.emit_event(
                                etype, task_id=state.task_id,
                                field_count=len(fn_args.get("fields", [])),
                                error=tool_result.error or "",
                            )
                        elif fn_name == "extract_data":
                            await self.emit_event(
                                _ET.DATA_EXTRACTED, task_id=state.task_id,
                                description=fn_args.get("description", ""),
                            )

                    tool_calls_made += 1

                    # ── Append function_response to memory ──
                    fn_response = types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=fn_name,
                                response={
                                    "success": tool_result.success,
                                    "result": tool_result.result or {},
                                    "error": tool_result.error,
                                },
                            )
                        ],
                    )
                    self._add_to_memory(fn_response)

                    if not tool_result.success:
                        state.retries += 1
                        if state.retries > state.max_retries:
                            state.error = (
                                f"Max retries exceeded: {tool_result.error}"
                            )
                            state.status = "failed"
                            return state, None
                    else:
                        state.retries = 0

                    # ── Next Gemini call uses clean memory ──
                    gemini_tools = (
                        [types.Tool(function_declarations=self.tools)]
                        if self.tools
                        else None
                    )
                    contents = self._safe_memory_for_api()
                    response = await self._call_with_retry(contents, gemini_tools)

                    if response.candidates and response.candidates[0].content:
                        self._add_to_memory(response.candidates[0].content)

                    # Stuck detection — nudge the agent
                    if self._is_stuck():
                        obs.error(self.name, "stuck_detected",
                                  error="Agent repeating itself",
                                  step=state.step_index, task_id=state.task_id)
                        nudge = types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(
                                    text=(
                                        "You are repeating yourself. Try a different "
                                        "strategy — avoid actions already attempted."
                                    )
                                )
                            ],
                        )
                        self._add_to_memory(nudge)

                    break  # break inner for-loop, continue outer while

            if not has_function_call:
                break

        return state, text_response

    # ────────────────────────────────────────────────────────
    #  Formatting helpers
    # ────────────────────────────────────────────────────────

    def _format_dom_elements(
        self, elements: list[dict], max_elements: int = 40
    ) -> str:
        """Format DOM elements for the prompt."""
        lines = []
        for el in elements[:max_elements]:
            tag = el.get("tag", "?")
            text = (el.get("text", "") or "")[:60]
            placeholder = el.get("placeholder", "")
            aria = el.get("ariaLabel", "")
            x, y = el.get("x", 0), el.get("y", 0)
            w, h = el.get("width", 0), el.get("height", 0)
            el_id = el.get("id", "")
            name = el.get("name", "")
            href = (el.get("href", "") or "")[:80]

            desc_parts = []
            if el_id:
                desc_parts.append(f"id={el_id}")
            if name:
                desc_parts.append(f"name={name}")
            if placeholder:
                desc_parts.append(f'placeholder="{placeholder}"')
            if aria:
                desc_parts.append(f'aria="{aria}"')
            if href:
                desc_parts.append(f"href={href}")
            desc = " ".join(desc_parts)

            lines.append(f'  [{tag}] "{text}" at ({x},{y}) {w}x{h} {desc}')
        return "\n".join(lines) or "  (no interactive elements detected)"

    def _build_page_context_prompt(self, state: AgentState) -> str:
        """Build a standardized page context section for prompts."""
        parts = [
            f"PAGE URL: {state.page.url}",
            f"PAGE TITLE: {state.page.title}",
        ]
        if state.page.page_summary:
            parts.append(f"PAGE SUMMARY: {state.page.page_summary}")
        if state.page.current_state:
            parts.append(f"PAGE STATE: {state.page.current_state}")

        if state.page.elements:
            elements_text = "\n".join(
                f"  - [{el.get('id', '?')}] {el.get('type', '?')}: "
                f"\"{el.get('text', '')}\" "
                f"at ({el.get('x', 0)},{el.get('y', 0)}) "
                f"{'SENSITIVE' if el.get('is_sensitive') else ''}"
                for el in state.page.elements[:30]
                if el.get("interactable", True)
            )
            parts.append(f"VISION-DETECTED ELEMENTS:\n{elements_text}")

        if state.action_history:
            recent = state.action_history[-8:]
            history_text = "\n".join(
                f"  {i+1}. [{a.get('agent', '?')}] {a.get('action_type', '?')} "
                f"{'OK' if a.get('success') else 'FAIL ' + (a.get('error', '') or '')}"
                for i, a in enumerate(recent)
            )
            parts.append(f"RECENT ACTIONS:\n{history_text}")

        return "\n".join(parts)
