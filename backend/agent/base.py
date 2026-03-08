"""Base agent class — foundation for all specialist agents.

Handles Gemini API calls with function/tool calling, conversation
management, and the step() interface used by the graph runner.
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from google import genai
from google.genai import types

from backend.agent.state import AgentState, PageContext
from backend.tools.executor import ToolExecutor, ToolResult

logger = logging.getLogger("gaxis.agent")

# Vision model for agents that need screenshot understanding
AGENT_MODEL = "gemini-2.5-pro-preview-06-05"


class BaseAgent(ABC):
    """Abstract base for all G-Axis agents.

    Each agent has:
    - A system prompt defining its role
    - A set of tools it can call
    - A step() method that processes one turn of the agent graph
    """

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
        self._conversation_history: list[types.Content] = []

    def reset(self) -> None:
        """Clear conversation history for a new task."""
        self._conversation_history = []

    @abstractmethod
    async def step(self, state: AgentState) -> AgentState:
        """Process one step in the agent graph. Must be implemented by subclasses."""
        ...

    async def call_gemini(
        self,
        state: AgentState,
        user_prompt: str,
        include_screenshot: bool = True,
        include_dom: bool = True,
    ) -> types.GenerateContentResponse:
        """Call Gemini with tools, screenshot, and conversation context.

        Returns the raw response. Caller handles function calls.
        """
        # Build the user message parts
        parts = []

        # Add screenshot if available
        if include_screenshot and state.page.screenshot_b64:
            image_bytes = base64.b64decode(state.page.screenshot_b64)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        # Add DOM snapshot context if available
        if include_dom and state.page.dom_elements:
            dom_text = self._format_dom_elements(state.page.dom_elements)
            parts.append(types.Part.from_text(text=f"\nDOM ELEMENTS (precise coordinates):\n{dom_text}"))

        # Add the main prompt
        parts.append(types.Part.from_text(text=user_prompt))

        user_content = types.Content(role="user", parts=parts)

        # Build full contents: system + history + current
        contents = list(self._conversation_history) + [user_content]

        # Tool config
        tool_config = None
        gemini_tools = None
        if self.tools:
            gemini_tools = [types.Tool(function_declarations=self.tools)]

        response = await self.client.aio.models.generate_content(
            model=AGENT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.2,
                max_output_tokens=4096,
                tools=gemini_tools,
            ),
        )

        # Save to conversation history
        self._conversation_history.append(user_content)
        if response.candidates and response.candidates[0].content:
            self._conversation_history.append(response.candidates[0].content)

        return response

    async def call_gemini_with_tool_loop(
        self,
        state: AgentState,
        user_prompt: str,
        max_tool_calls: int = 5,
        include_screenshot: bool = True,
    ) -> tuple[AgentState, str | None]:
        """Call Gemini and automatically execute any tool calls in a loop.

        Returns (updated_state, text_response_or_none).
        Handles the full function calling cycle:
        1. Call Gemini
        2. If Gemini returns function_call, execute it
        3. Send function_response back to Gemini
        4. Repeat until Gemini returns text or max calls reached
        """
        response = await self.call_gemini(state, user_prompt, include_screenshot=include_screenshot)
        text_response = None
        tool_calls_made = 0

        while tool_calls_made < max_tool_calls:
            # Check if response has function calls
            if not response.candidates or not response.candidates[0].content:
                break

            candidate = response.candidates[0]
            has_function_call = False

            for part in candidate.content.parts:
                # Text response
                if part.text:
                    text_response = part.text

                # Function call
                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}

                    logger.info(f"[{self.name}] Tool call: {fn_name}({fn_args})")

                    # Check for control flow tools — don't execute via browser
                    if fn_name == "task_complete":
                        state.result_summary = fn_args.get("summary", "")
                        if fn_args.get("data"):
                            state.extracted_data.update(fn_args["data"])
                        return state, fn_args.get("summary")

                    if fn_name == "task_failed":
                        state.error = fn_args.get("reason", "Task failed")
                        state.status = "failed"
                        return state, fn_args.get("reason")

                    if fn_name == "delegate":
                        # Orchestrator delegating — set next agent
                        state.current_agent = fn_args.get("agent", "navigator")
                        # Add as subtask if not already tracked
                        from backend.agent.state import SubTask
                        subtask = SubTask(
                            index=len(state.subtasks),
                            instruction=fn_args.get("instruction", ""),
                            agent=fn_args.get("agent", "navigator"),
                            status="pending",
                        )
                        state.subtasks.append(subtask)
                        return state, fn_args.get("instruction")

                    if fn_name == "extract_data":
                        state.extracted_data.update(fn_args.get("data", {}))
                        # Send function response back
                        tool_result = ToolResult(
                            name=fn_name, success=True,
                            result={"extracted": fn_args.get("data", {})},
                            duration_ms=0,
                        )
                    else:
                        # Execute browser action
                        tool_result = await self.tool_executor.execute(
                            function_name=fn_name,
                            function_args=fn_args,
                            mode=state.mode,
                            emit_fn=self.emit_fn,
                            task_id=state.task_id,
                        )

                    # Record the action
                    state.record_action({
                        "agent": self.name,
                        "action_type": fn_name,
                        "args": fn_args,
                        "success": tool_result.success,
                        "error": tool_result.error,
                        "duration_ms": tool_result.duration_ms,
                    })

                    tool_calls_made += 1

                    # Send function response back to Gemini for next turn
                    function_response = types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(
                            name=fn_name,
                            response={
                                "success": tool_result.success,
                                "result": tool_result.result,
                                "error": tool_result.error,
                            },
                        )],
                    )
                    self._conversation_history.append(function_response)

                    if not tool_result.success:
                        state.retries += 1
                        if state.retries > state.max_retries:
                            state.error = f"Max retries exceeded: {tool_result.error}"
                            state.status = "failed"
                            return state, None
                    else:
                        state.retries = 0

                    # Call Gemini again with the function response
                    response = await self.client.aio.models.generate_content(
                        model=AGENT_MODEL,
                        contents=self._conversation_history,
                        config=types.GenerateContentConfig(
                            system_instruction=self.system_prompt,
                            temperature=0.2,
                            max_output_tokens=4096,
                            tools=[types.Tool(function_declarations=self.tools)] if self.tools else None,
                        ),
                    )

                    if response.candidates and response.candidates[0].content:
                        self._conversation_history.append(response.candidates[0].content)

                    break  # break inner loop, continue outer while loop

            if not has_function_call:
                break

        return state, text_response

    def _format_dom_elements(self, elements: list[dict], max_elements: int = 40) -> str:
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
                desc_parts.append(f"placeholder=\"{placeholder}\"")
            if aria:
                desc_parts.append(f"aria=\"{aria}\"")
            if href:
                desc_parts.append(f"href={href}")
            desc = " ".join(desc_parts)

            lines.append(
                f"  [{tag}] \"{text}\" at ({x},{y}) {w}x{h} {desc}"
            )
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

        # Vision-detected elements
        if state.page.elements:
            elements_text = "\n".join(
                f"  - [{el.get('id', '?')}] {el.get('type', '?')}: \"{el.get('text', '')}\" "
                f"at ({el.get('x', 0)},{el.get('y', 0)}) "
                f"{'SENSITIVE' if el.get('is_sensitive') else ''}"
                for el in state.page.elements[:30]
                if el.get("interactable", True)
            )
            parts.append(f"VISION-DETECTED ELEMENTS:\n{elements_text}")

        # Recent actions
        if state.action_history:
            recent = state.action_history[-8:]
            history_text = "\n".join(
                f"  {i+1}. [{a.get('agent', '?')}] {a.get('action_type', '?')} "
                f"{'✓' if a.get('success') else '✗ ' + (a.get('error', '') or '')}"
                for i, a in enumerate(recent)
            )
            parts.append(f"RECENT ACTIONS:\n{history_text}")

        return "\n".join(parts)
