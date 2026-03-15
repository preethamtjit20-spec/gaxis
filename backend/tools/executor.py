"""Tool executor — dispatches Gemini function calls to browser actions.

Bridges the gap between Gemini's function_call responses and
actual browser execution (Playwright or Chrome extension).

Extension mode uses a confirmation loop:
  1. Emit execute_action event → service worker → content script
  2. Content script executes and sends result back via WebSocket
  3. Executor waits for the result before returning
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from backend.browser.runtime import BrowserRuntime, ActionResult
from backend.observability.logger import obs

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
        self.safety_guard = None       # Injected by GAxisAgent after creation
        self.rollback_manager = None   # Injected by GAxisAgent after creation
        self._current_url: str = ""    # Updated by callers for safety context
        # Action confirmation for extension mode — persistent Event + queue
        # Event is created ONCE (not per-call) to prevent race where extension
        # responds before _wait_for_action_result is called.
        self._action_queue: asyncio.Queue = asyncio.Queue()

    def receive_action_result(self, result: dict) -> None:
        """Called when extension sends back action execution result."""
        try:
            self._action_queue.put_nowait(result)
        except asyncio.QueueFull:
            logger.warning("Action result queue full — dropping oldest result")
            try:
                self._action_queue.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
            self._action_queue.put_nowait(result)

    async def _wait_for_action_result(self, timeout: float = 10.0) -> dict:
        """Wait for action result from extension.

        Uses a queue instead of Event so results that arrive before this
        method is called are not lost (fixes race condition).
        """
        try:
            result = await asyncio.wait_for(self._action_queue.get(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Timed out waiting for action result from extension ({timeout}s)")
            return {"success": False, "error": "Action execution timed out — extension did not respond"}

    def drain_stale_results(self) -> None:
        """Drain any leftover results from a previous action (e.g. after cancel/timeout)."""
        drained = 0
        while not self._action_queue.empty():
            try:
                self._action_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.debug(f"Drained {drained} stale action result(s)")

    async def execute(
        self,
        function_name: str,
        function_args: dict,
        mode: str = "api",
        emit_fn=None,
        task_id: str = "",
    ) -> ToolResult:
        """Execute a function call from Gemini."""
        start = time.time()

        # ── Pre-execution safety check ──
        if self.safety_guard is not None:
            from backend.policy.safety import SafetyLevel
            verdict = self.safety_guard.check(
                function_name, function_args, self._current_url,
            )
            if verdict.level == SafetyLevel.BLOCK:
                self.safety_guard._block_count += 1
                obs.safety("executor", function_name, verdict="block",
                           reason=verdict.reason, category=verdict.category,
                           task_id=task_id)
                return ToolResult(
                    name=function_name, success=False,
                    result={"safety_blocked": True, "category": verdict.category},
                    duration_ms=0,
                    error=f"Safety blocked: {verdict.reason}",
                )
            if verdict.level == SafetyLevel.CONFIRM:
                self.safety_guard._confirm_count += 1
                obs.safety("executor", function_name, verdict="confirm",
                           reason=verdict.reason, category=verdict.category,
                           task_id=task_id)
                # Show confirmation to user via emit_fn
                if emit_fn:
                    from backend.agent.core import TaskEvent
                    await emit_fn(TaskEvent("safety_confirmation", task_id, {
                        "action": function_name,
                        "reason": verdict.reason,
                        "category": verdict.category,
                        "details": verdict.details,
                    }))
                # Wait for user approval if available
                if self.safety_guard.approval_fn:
                    approved = await self.safety_guard.approval_fn()
                    if not approved:
                        obs.safety("executor", function_name, verdict="denied",
                                   reason=verdict.reason, task_id=task_id)
                        return ToolResult(
                            name=function_name, success=False,
                            result={"safety_denied": True, "category": verdict.category},
                            duration_ms=0,
                            error=f"User denied: {verdict.reason}",
                        )
                    # User approved — mark URL as confirmed so we don't ask again
                    if self._current_url:
                        self.safety_guard.mark_url_confirmed(self._current_url)
                    obs.safety("executor", function_name, verdict="approved",
                               reason=verdict.reason, task_id=task_id)

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

            if function_name == "fill_form":
                # Batch form fill — send directly to extension
                if mode == "extension":
                    # Get raw extension result to pass per-field results
                    self.drain_stale_results()
                    action_data = {
                        "action_type": "fill_form",
                        "fields": function_args.get("fields", []),
                    }
                    if emit_fn:
                        from backend.agent.core import TaskEvent
                        await emit_fn(TaskEvent("execute_action", task_id, action_data))
                    ext_result = await self._wait_for_action_result(timeout=20.0)
                    success = ext_result.get("success", False)
                    error = ext_result.get("error")
                    per_field_results = ext_result.get("results", [])
                    filled = ext_result.get("filled", 0)
                    total = ext_result.get("total", 0)
                    if not success and not error and per_field_results:
                        failed = [r for r in per_field_results if not r.get("success")]
                        error = f"{len(failed)}/{total} fields failed: " + ", ".join(
                            f"{r.get('field', '?')}: {r.get('error', 'unknown')}" for r in failed
                        )
                    if not success:
                        logger.warning(f"Extension fill_form: {error}")
                    duration_ms = int((time.time() - start) * 1000)
                    # Record for rollback
                    if self.rollback_manager and success:
                        self.rollback_manager.record(
                            function_name, function_args, success,
                            url_before=self._current_url,
                            url_after=self._current_url,
                        )
                    return ToolResult(
                        name=function_name, success=success,
                        result={"action": "fill_form", "details": error or "batch fill complete",
                                "results": per_field_results, "filled": filled, "total": total},
                        duration_ms=duration_ms, error=error if not success else None,
                    )
                else:
                    return ToolResult(
                        name=function_name, success=False,
                        result={}, duration_ms=0,
                        error="fill_form only supported in extension mode",
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
            # Record for rollback
            if self.rollback_manager and result.success:
                url_after = result.resulting_url or self._current_url
                self.rollback_manager.record(
                    function_name, function_args, result.success,
                    url_before=self._current_url,
                    url_after=url_after,
                )
            return ToolResult(
                name=function_name, success=result.success,
                result={"url": result.resulting_url, "action": function_name, "details": result.error or ""},
                duration_ms=duration_ms, error=result.error if not result.success else None,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            obs.error("executor", function_name, error=str(e), task_id=task_id)
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
                result = await self.browser.execute("select_all_and_type", x=x, y=y, text=text)
            else:
                result = await self.browser.execute("type", x=x, y=y, text=text)
            if args.get("press_enter"):
                await asyncio.sleep(0.2)
                await self.browser.execute("press_key", key="Enter")
            return result

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
        """Execute action via Chrome extension with confirmation.

        1. Emit execute_action event → service worker → content script
        2. Wait for action_result from extension (up to 10s)
        3. Return actual result (success/failure)
        """
        start = time.time()
        # Clear any stale results from previous timed-out actions
        self.drain_stale_results()

        # Build action data for content script
        if name == "fill_form":
            action_data = {
                "action_type": "fill_form",
                "fields": args.get("fields", []),
            }
        else:
            action_data = {
                "action_type": name if name != "type_text" else ("select_all_and_type" if args.get("clear_first") else "type"),
                "x": args.get("x"),
                "y": args.get("y"),
                "text": args.get("text", ""),
                "url": args.get("url", ""),
                "direction": args.get("direction", "down"),
                "key": args.get("key", ""),
                "pixels": args.get("pixels", 400),
                "element_description": args.get("element_description", ""),
                "press_enter": args.get("press_enter", False),
            }

        if emit_fn:
            from backend.agent.core import TaskEvent
            await emit_fn(TaskEvent("execute_action", task_id, action_data))

        # Wait for the extension to confirm execution
        # Generous timeouts — hackathon WiFi can be slow
        timeout = 20.0 if name in ("fill_form", "navigate") else 8.0
        ext_result = await self._wait_for_action_result(timeout=timeout)

        success = ext_result.get("success", False)
        error = ext_result.get("error")

        # Retry navigate once on timeout — network can be flaky
        if not success and name == "navigate" and error and "timed out" in error.lower():
            logger.warning(f"Navigate timed out, retrying once: {args.get('url', '')[:60]}")
            if emit_fn:
                from backend.agent.core import TaskEvent
                await emit_fn(TaskEvent("execute_action", task_id, action_data))
            ext_result = await self._wait_for_action_result(timeout=25.0)
            success = ext_result.get("success", False)
            error = ext_result.get("error")

        if not success:
            obs.tool_result("executor", name, success=False, error=error or "",
                            latency_ms=int((time.time() - start) * 1000),
                            target=args.get("element_description", ""),
                            task_id=task_id)

        return ActionResult(
            success=success,
            action_type=name,
            duration_ms=int((time.time() - start) * 1000),
            resulting_url=ext_result.get("url", ""),
            error=error,
        )
