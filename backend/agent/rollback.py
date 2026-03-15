"""Execution Rollback — undo browser actions when things go wrong.

Every successful browser action gets a RollbackEntry with an undo strategy.
When the agent is stuck (typed wrong field, navigated wrong page, etc.),
the RollbackManager can undo the last N actions and retry.

Undo strategies per action type:
  type_text  → click same (x, y), Ctrl+A, Delete  (clear the field)
  fill_form  → for each field, select all + delete  (clear all filled fields)
  navigate   → navigate back to previous URL
  click      → press Escape  (closes dropdowns, dialogs, popovers)
  scroll     → reverse scroll
  press_key  → best-effort reverse (Tab→Shift+Tab, etc.)

Usage:
  manager = RollbackManager(tool_executor)

  # After each action, record it
  manager.record(fn_name, fn_args, result, url_before)

  # When stuck, rollback last N actions
  undone = await manager.rollback(n=2, mode="extension", emit_fn=..., task_id=...)

  # Or rollback to a specific step
  undone = await manager.rollback_to(step=3, ...)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.observability.logger import obs

if TYPE_CHECKING:
    from backend.tools.executor import ToolExecutor

logger = logging.getLogger("gaxis.rollback")


# ─── UNDO STRATEGY ──────────────────────────────────────────

@dataclass
class UndoAction:
    """A single browser action that reverses a previous action."""
    function_name: str
    function_args: dict
    description: str


@dataclass
class RollbackEntry:
    """A recorded action with its undo strategy."""
    step: int
    function_name: str
    function_args: dict
    url_before: str             # URL before this action executed
    url_after: str              # URL after this action executed
    timestamp: float
    undo_actions: list[UndoAction] = field(default_factory=list)
    reversible: bool = True     # Some actions can't be undone (Enter on submit)


# Actions that cannot be meaningfully undone
IRREVERSIBLE_ACTIONS = {"task_complete", "task_failed", "task_partial",
                        "delegate", "extract_data", "plan_task", "wait"}

# Actions that are risky to undo (submission, destructive)
RISKY_UNDO_PATTERNS = {"submit", "send", "delete", "remove", "purchase", "buy"}


def _build_undo(fn_name: str, fn_args: dict, url_before: str) -> list[UndoAction]:
    """Build undo actions for a given browser action."""

    if fn_name == "type_text":
        x = fn_args.get("x", 0)
        y = fn_args.get("y", 0)
        return [
            UndoAction("click", {"x": x, "y": y, "element_description": "Rollback: re-focus field"},
                       f"Click field at ({x},{y})"),
            UndoAction("press_key", {"key": "Control+a"}, "Select all text"),
            UndoAction("press_key", {"key": "Backspace"}, "Delete selected text"),
        ]

    if fn_name == "fill_form":
        # Undo each filled field in reverse order
        undos: list[UndoAction] = []
        fields = fn_args.get("fields", [])
        for f in reversed(fields):
            action = f.get("action", "type")
            if action in ("type", "select_all_and_type"):
                hints = f.get("hints", {})
                desc = hints.get("aria") or hints.get("placeholder") or hints.get("text") or "field"
                # Clear via fill_form with empty value
                undos.append(UndoAction(
                    "fill_form",
                    {"fields": [{
                        "hints": hints,
                        "value": "",
                        "action": "select_all_and_type",
                        "clear_first": True,
                    }]},
                    f"Clear field: {desc}",
                ))
        return undos

    if fn_name == "navigate":
        if url_before and url_before not in ("about:blank", "chrome://newtab/"):
            return [
                UndoAction("navigate", {"url": url_before},
                           f"Navigate back to {url_before[:60]}"),
            ]
        return []

    if fn_name == "click":
        desc = (fn_args.get("element_description", "") or "").lower()
        # Check if this was a risky/irreversible click
        if any(w in desc for w in RISKY_UNDO_PATTERNS):
            return []  # Can't undo submit/send/delete
        # Generic: press Escape to close whatever opened
        return [
            UndoAction("press_key", {"key": "Escape"},
                       "Press Escape to close dropdown/dialog"),
        ]

    if fn_name == "scroll":
        direction = fn_args.get("direction", "down")
        pixels = fn_args.get("pixels", 400)
        reverse = "up" if direction == "down" else "down"
        return [
            UndoAction("scroll", {"direction": reverse, "pixels": pixels},
                       f"Scroll {reverse} {pixels}px"),
        ]

    if fn_name == "press_key":
        key = fn_args.get("key", "")
        reverse_keys = {
            "Tab": "Shift+Tab",
            "ArrowDown": "ArrowUp",
            "ArrowUp": "ArrowDown",
            "ArrowLeft": "ArrowRight",
            "ArrowRight": "ArrowLeft",
        }
        if key in reverse_keys:
            return [
                UndoAction("press_key", {"key": reverse_keys[key]},
                           f"Reverse key: {reverse_keys[key]}"),
            ]
        return []

    return []


def _is_reversible(fn_name: str, fn_args: dict) -> bool:
    """Check if an action can be undone."""
    if fn_name in IRREVERSIBLE_ACTIONS:
        return False
    if fn_name == "click":
        desc = (fn_args.get("element_description", "") or "").lower()
        if any(w in desc for w in RISKY_UNDO_PATTERNS):
            return False
    if fn_name == "press_key":
        key = fn_args.get("key", "")
        if key == "Enter":
            return False  # Enter may have submitted something
    return True


# ─── ROLLBACK MANAGER ───────────────────────────────────────

class RollbackManager:
    """Tracks executed actions and can undo them in reverse order.

    Integrated into ToolExecutor — records after every successful action.
    Called by FastAgentLoop/AgentGraph when stuck detection triggers.
    """

    def __init__(self, tool_executor: ToolExecutor):
        self._executor = tool_executor
        self._stack: list[RollbackEntry] = []
        self._rollback_count = 0   # Total rollbacks performed
        self._max_stack = 50       # Don't track forever

    def reset(self) -> None:
        """Clear rollback stack for a new task."""
        self._stack.clear()
        self._rollback_count = 0

    def record(
        self,
        fn_name: str,
        fn_args: dict,
        success: bool,
        url_before: str = "",
        url_after: str = "",
        step: int = 0,
    ) -> None:
        """Record a successfully executed action onto the rollback stack."""
        if not success:
            return  # Only record successful actions — failed ones need no undo
        if fn_name in IRREVERSIBLE_ACTIONS:
            return  # Don't bother recording non-browser actions

        entry = RollbackEntry(
            step=step,
            function_name=fn_name,
            function_args=fn_args,
            url_before=url_before,
            url_after=url_after,
            timestamp=time.time(),
            undo_actions=_build_undo(fn_name, fn_args, url_before),
            reversible=_is_reversible(fn_name, fn_args),
        )

        self._stack.append(entry)
        if len(self._stack) > self._max_stack:
            self._stack = self._stack[-self._max_stack:]

    async def rollback(
        self,
        n: int = 1,
        mode: str = "extension",
        emit_fn=None,
        task_id: str = "",
    ) -> list[dict]:
        """Undo the last N actions in reverse order.

        Returns list of undo results: [{action, success, error}]
        """
        results = []
        undone = 0

        while undone < n and self._stack:
            entry = self._stack.pop()

            if not entry.reversible or not entry.undo_actions:
                obs.rollback("rollback", "skip_irreversible",
                             reason=f"{entry.function_name} not reversible",
                             step=entry.step)
                results.append({
                    "action": entry.function_name,
                    "step": entry.step,
                    "success": False,
                    "error": "Not reversible",
                    "skipped": True,
                })
                continue

            obs.rollback("rollback", f"undo_{entry.function_name}",
                         reason=_summarize_args(entry.function_args),
                         step=entry.step)

            # Execute each undo action
            entry_success = True
            for undo in entry.undo_actions:
                try:
                    result = await self._executor.execute(
                        function_name=undo.function_name,
                        function_args=undo.function_args,
                        mode=mode,
                        emit_fn=emit_fn,
                        task_id=task_id,
                    )
                    if not result.success:
                        logger.warning(
                            f"Rollback undo failed: {undo.description} — {result.error}"
                        )
                        entry_success = False
                except Exception as e:
                    logger.error(f"Rollback undo error: {undo.description} — {e}")
                    entry_success = False

            results.append({
                "action": entry.function_name,
                "step": entry.step,
                "success": entry_success,
                "description": f"Undid {entry.function_name} from step {entry.step}",
            })
            undone += 1

        self._rollback_count += undone
        obs.rollback("rollback", "complete", reason=f"{undone}/{n} actions undone",
                     undone=undone, requested=n)

        if emit_fn:
            from backend.agent.core import TaskEvent
            await emit_fn(TaskEvent("rollback_executed", task_id, {
                "undone": undone,
                "requested": n,
                "results": results,
            }))

        return results

    async def rollback_to(
        self,
        step: int,
        mode: str = "extension",
        emit_fn=None,
        task_id: str = "",
    ) -> list[dict]:
        """Rollback all actions after the given step index."""
        count = sum(1 for e in self._stack if e.step > step)
        if count == 0:
            logger.info(f"Rollback: nothing to undo after step {step}")
            return []
        return await self.rollback(n=count, mode=mode, emit_fn=emit_fn, task_id=task_id)

    @property
    def depth(self) -> int:
        """How many reversible actions are on the stack."""
        return len(self._stack)

    @property
    def can_rollback(self) -> bool:
        """Check if there are any reversible actions to undo."""
        return any(e.reversible and e.undo_actions for e in self._stack)

    @property
    def last_entry(self) -> RollbackEntry | None:
        """Get the most recent entry."""
        return self._stack[-1] if self._stack else None

    @property
    def stats(self) -> dict:
        return {
            "stack_depth": len(self._stack),
            "reversible": sum(1 for e in self._stack if e.reversible),
            "total_rollbacks": self._rollback_count,
        }

    def to_prompt(self, max_items: int = 5) -> str:
        """Render rollback state for LLM context."""
        if not self._stack:
            return ""
        lines = [f"ROLLBACK AVAILABLE ({len(self._stack)} actions can be undone):"]
        for entry in self._stack[-max_items:]:
            rev = "✓" if entry.reversible else "✗"
            lines.append(
                f"  {rev} Step {entry.step}: {entry.function_name}"
                f"({_summarize_args(entry.function_args)})"
            )
        if self._rollback_count > 0:
            lines.append(f"  (Already rolled back {self._rollback_count} actions this task)")
        return "\n".join(lines)


def _summarize_args(args: dict) -> str:
    """Short summary of action args for logging."""
    if "url" in args:
        return args["url"][:50]
    if "text" in args:
        return f'"{args["text"][:30]}"'
    if "element_description" in args:
        return args["element_description"][:40]
    if "fields" in args:
        return f"{len(args['fields'])} fields"
    if "key" in args:
        return args["key"]
    if "direction" in args:
        return f"{args['direction']} {args.get('pixels', 400)}px"
    return str(args)[:40]
