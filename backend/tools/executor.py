"""Tool executor — dispatches Gemini function calls to browser actions.

Bridges the gap between Gemini's function_call responses and
actual browser execution (Playwright or Chrome extension).
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from dataclasses import dataclass

from backend.browser.runtime import BrowserRuntime, ActionResult

logger = logging.getLogger("gaxis.tools")


@dataclass
class ToolResult:
    """Result of executing a tool."""
    name: str
    success: bool
    result: dict
    duration_ms: int
    error: str | None = None


class ToolExecutor:
    """Executes Gemini function calls against the browser."""

    def __init__(self, browser: BrowserRuntime):
        self.browser = browser

    async def execute(
        self,
        function_name: str,
        function_args: dict,
        mode: str = "api",
        emit_fn=None,
        task_id: str = "",
    ) -> ToolResult:
        """Execute a function call from Gemini.

        In API mode: uses Playwright directly.
        In extension mode: emits an event for the extension to execute.
        """
        start = time.time()

        try:
            if function_name == "task_complete":
                return ToolResult(
                    name=function_name, success=True,
                    result={"summary": function_args.get("summary", ""), "data": function_args.get("data", {})},
                    duration_ms=0,
                )

            if function_name == "task_failed":
                return ToolResult(
                    name=function_name, success=False,
                    result={"reason": function_args.get("reason", "Unknown")},
                    duration_ms=0, error=function_args.get("reason", "Task failed"),
                )

            if function_name == "delegate":
                return ToolResult(
                    name=function_name, success=True,
                    result={"agent": function_args.get("agent"), "instruction": function_args.get("instruction")},
                    duration_ms=0,
                )

            if function_name == "extract_data":
                return ToolResult(
                    name=function_name, success=True,
                    result={"description": function_args.get("description", ""), "data": function_args.get("data", {})},
                    duration_ms=0,
                )

            if function_name == "wait":
                seconds = min(function_args.get("seconds", 1), 5)
                await asyncio.sleep(seconds)
                return ToolResult(
                    name=function_name, success=True,
                    result={"waited": seconds, "reason": function_args.get("reason", "")},
                    duration_ms=int(seconds * 1000),
                )

            # Browser actions — dispatch based on mode
            if mode == "extension":
                result = await self._execute_extension(
                    function_name, function_args, emit_fn, task_id,
                )
            else:
                result = await self._execute_playwright(function_name, function_args)

            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                name=function_name, success=result.success,
                result={"url": result.resulting_url, "action": function_name},
                duration_ms=duration_ms, error=result.error,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Tool execution failed: {function_name} — {e}")
            return ToolResult(
                name=function_name, success=False,
                result={}, duration_ms=duration_ms, error=str(e),
            )

    async def _execute_playwright(self, name: str, args: dict) -> ActionResult:
        """Execute action via Playwright (API mode)."""
        x = args.get("x")
        y = args.get("y")
        text = args.get("text", "")
        clear_first = args.get("clear_first", False)

        if name == "click":
            return await self.browser.execute("click", x=x, y=y)

        elif name == "type_text":
            if clear_first:
                return await self.browser.execute("select_all_and_type", x=x, y=y, text=text)
            else:
                return await self.browser.execute("type", x=x, y=y, text=text)

        elif name == "navigate":
            return await self.browser.execute("navigate", url=args.get("url", ""))

        elif name == "scroll":
            return await self.browser.execute(
                "scroll",
                direction=args.get("direction", "down"),
                pixels=args.get("pixels", 400),
            )

        elif name == "press_key":
            return await self.browser.execute("press_key", key=args.get("key", "Enter"))

        elif name == "hover":
            # Playwright hover via mouse move
            page = self.browser.page
            await page.mouse.move(x or 0, y or 0)
            await asyncio.sleep(0.3)
            return ActionResult(
                success=True, action_type="hover",
                duration_ms=300, resulting_url=page.url,
            )

        else:
            raise ValueError(f"Unknown browser action: {name}")

    async def _execute_extension(
        self, name: str, args: dict, emit_fn, task_id: str,
    ) -> ActionResult:
        """Execute action via Chrome extension (extension mode).

        Emits an event that the service worker routes to the content script.
        """
        from backend.agent.state import AgentState  # avoid circular

        action_data = {
            "action_type": name if name != "type_text" else ("select_all_and_type" if args.get("clear_first") else "type"),
            "x": args.get("x"),
            "y": args.get("y"),
            "text": args.get("text", ""),
            "url": args.get("url", ""),
            "direction": args.get("direction", "down"),
            "key": args.get("key", ""),
            "pixels": args.get("pixels", 400),
        }

        if emit_fn:
            # This triggers the service worker to send execute_action to content script
            from backend.agent.core import TaskEvent
            await emit_fn(TaskEvent("execute_action", task_id, action_data))

        # Wait for extension to execute the action
        await asyncio.sleep(1.2)

        return ActionResult(
            success=True, action_type=name,
            duration_ms=1200, resulting_url="",
        )
