"""Structured observability logger for G-Axis.

Replaces scattered f-string logging with typed, structured log entries.
Each entry has consistent fields: agent, action, target, reason, latency, etc.

Two output modes:
  - PRETTY (default): Human-readable aligned columns for terminal debugging
  - JSON: Machine-readable JSONL for log aggregation and querying

Usage:
    from backend.observability.logger import obs

    obs.action("navigator", "click", target="Add title",
               reason="filling event title", latency_ms=210, step=3)

    obs.tool_call("gaxis", "type_text", args={"x": 100, "y": 50, "text": "Meeting"},
                  latency_ms=85, success=True)

    obs.transition("graph", from_agent="navigator", to_agent="verifier",
                   reason="subtask completed")

    obs.error("executor", "navigate", error="Timed out", url="https://...")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

# Dedicated logger — separate from module loggers so it can be
# independently configured (file handler, JSON formatter, etc.)
_logger = logging.getLogger("gaxis.obs")


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    """A single structured log entry."""
    # Required
    level: str
    category: str               # action, tool_call, transition, lifecycle, error, metric, safety, rollback
    agent: str                  # navigator, verifier, gaxis, graph, executor, etc.

    # Action context
    action: str = ""            # click, type_text, navigate, fill_form, etc.
    target: str = ""            # Element description or URL
    reason: str = ""            # Why this action was taken

    # Result
    success: bool | None = None
    error: str = ""
    latency_ms: int = 0

    # Task context
    task_id: str = ""
    step: int = -1
    url: str = ""

    # Transition context
    from_agent: str = ""
    to_agent: str = ""

    # Extra data (for anything that doesn't fit above)
    data: dict = field(default_factory=dict)

    # Timing
    timestamp: float = field(default_factory=time.time)


def _format_pretty(entry: LogEntry) -> str:
    """Format a log entry as a readable, aligned string.

    Example output:
      [Navigator] click | Target: "Add title" | Reason: filling event title | 210ms OK
      [Graph] transition | navigator → verifier | Reason: subtask completed
      [Executor] SAFETY BLOCK | navigate | payment page detected | critical
      [Gaxis] ERROR type_text | Timed out | Step 5 | https://calendar.google.com
    """
    parts = [f"[{entry.agent.capitalize()}]"]

    if entry.category == "error":
        parts.append(f"ERROR {entry.action}" if entry.action else "ERROR")
        if entry.error:
            parts.append(f"| {entry.error[:80]}")
        if entry.step >= 0:
            parts.append(f"| Step {entry.step}")
        if entry.url:
            parts.append(f"| {entry.url[:60]}")
        return " ".join(parts)

    if entry.category == "transition":
        parts.append("transition")
        if entry.from_agent and entry.to_agent:
            parts.append(f"| {entry.from_agent} → {entry.to_agent}")
        elif entry.to_agent:
            parts.append(f"| → {entry.to_agent}")
        if entry.reason:
            parts.append(f"| Reason: {entry.reason[:60]}")
        return " ".join(parts)

    if entry.category == "lifecycle":
        parts.append(entry.action)
        if entry.reason:
            parts.append(f"| {entry.reason[:80]}")
        if entry.latency_ms > 0:
            parts.append(f"| {entry.latency_ms}ms")
        if entry.data:
            extras = " ".join(f"{k}={v}" for k, v in entry.data.items()
                              if v is not None and v != "")
            if extras:
                parts.append(f"| {extras[:80]}")
        return " ".join(parts)

    if entry.category == "safety":
        verdict = entry.data.get("verdict", "").upper()
        parts.append(f"SAFETY {verdict}")
        if entry.action:
            parts.append(f"| {entry.action}")
        if entry.reason:
            parts.append(f"| {entry.reason[:60]}")
        cat = entry.data.get("category", "")
        if cat:
            parts.append(f"| {cat}")
        return " ".join(parts)

    if entry.category == "rollback":
        parts.append(f"rollback {entry.action}")
        if entry.reason:
            parts.append(f"| {entry.reason[:60]}")
        if entry.data:
            if "undone" in entry.data:
                parts.append(f"| undone={entry.data['undone']}")
            if "step" in entry.data:
                parts.append(f"| from_step={entry.data['step']}")
        return " ".join(parts)

    if entry.category == "metric":
        parts.append(entry.action)
        if entry.data:
            extras = " ".join(f"{k}={v}" for k, v in entry.data.items())
            parts.append(f"| {extras}")
        if entry.latency_ms > 0:
            parts.append(f"| {entry.latency_ms}ms")
        return " ".join(parts)

    # Default: action / tool_call
    parts.append(entry.action or entry.category)

    if entry.target:
        parts.append(f'| Target: "{entry.target[:50]}"')

    if entry.reason:
        parts.append(f"| Reason: {entry.reason[:50]}")

    # Args summary for tool_call
    if entry.category == "tool_call" and entry.data:
        args_str = _summarize_data(entry.data, max_len=60)
        if args_str:
            parts.append(f"| Args: {args_str}")

    if entry.latency_ms > 0:
        parts.append(f"| {entry.latency_ms}ms")

    if entry.success is not None:
        parts.append("OK" if entry.success else f"FAIL")
        if not entry.success and entry.error:
            parts.append(f"({entry.error[:40]})")

    if entry.step >= 0:
        parts.append(f"[step {entry.step}]")

    return " ".join(parts)


def _format_json(entry: LogEntry) -> str:
    """Format a log entry as a JSON line."""
    d = asdict(entry)
    # Remove empty/default fields for cleaner output
    return json.dumps(
        {k: v for k, v in d.items()
         if v is not None and v != "" and v != -1 and v != 0 and v != {} and v is not False},
        default=str,
    )


def _summarize_data(data: dict, max_len: int = 60) -> str:
    """Compact summary of data dict."""
    parts = []
    for k, v in data.items():
        if k in ("fields",) and isinstance(v, list):
            parts.append(f"{k}=[{len(v)} items]")
        elif isinstance(v, str) and len(v) > 30:
            parts.append(f'{k}="{v[:27]}..."')
        elif isinstance(v, str):
            parts.append(f'{k}="{v}"')
        else:
            parts.append(f"{k}={v}")
    result = ", ".join(parts)
    return result[:max_len] if len(result) > max_len else result


# ─── STRUCTURED LOGGER ───────────────────────────────────────

class StructuredLogger:
    """High-level structured logger with typed methods.

    Call obs.action(), obs.tool_call(), obs.transition(), etc.
    Each call emits a LogEntry to the gaxis.obs Python logger.
    """

    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode
        self._format = _format_json if json_mode else _format_pretty

    def _emit(self, entry: LogEntry) -> None:
        """Emit a log entry."""
        msg = self._format(entry)
        level = getattr(logging, entry.level, logging.INFO)
        _logger.log(level, msg)

    # ── Action: a browser action was executed ──

    def action(
        self,
        agent: str,
        action: str,
        *,
        target: str = "",
        reason: str = "",
        success: bool | None = None,
        error: str = "",
        latency_ms: int = 0,
        step: int = -1,
        task_id: str = "",
        url: str = "",
        **extra,
    ) -> None:
        """Log a browser action (click, type, navigate, scroll, etc.)."""
        self._emit(LogEntry(
            level="INFO" if success is not False else "WARN",
            category="action",
            agent=agent, action=action, target=target, reason=reason,
            success=success, error=error, latency_ms=latency_ms,
            step=step, task_id=task_id, url=url, data=extra,
        ))

    # ── Tool call: Gemini requested a function call ──

    def tool_call(
        self,
        agent: str,
        function_name: str,
        *,
        args: dict | None = None,
        success: bool | None = None,
        error: str = "",
        latency_ms: int = 0,
        step: int = -1,
        task_id: str = "",
        **extra,
    ) -> None:
        """Log a Gemini tool/function call."""
        self._emit(LogEntry(
            level="INFO",
            category="tool_call",
            agent=agent, action=function_name,
            success=success, error=error, latency_ms=latency_ms,
            step=step, task_id=task_id, data=args or extra,
        ))

    # ── Tool result: the result after executing a tool call ──

    def tool_result(
        self,
        agent: str,
        function_name: str,
        *,
        success: bool,
        error: str = "",
        latency_ms: int = 0,
        step: int = -1,
        task_id: str = "",
        target: str = "",
        **extra,
    ) -> None:
        """Log the result of a tool execution."""
        self._emit(LogEntry(
            level="INFO" if success else "WARN",
            category="action",
            agent=agent, action=function_name, target=target,
            success=success, error=error, latency_ms=latency_ms,
            step=step, task_id=task_id, data=extra,
        ))

    # ── Transition: agent routing change ──

    def transition(
        self,
        source: str,
        *,
        from_agent: str = "",
        to_agent: str = "",
        reason: str = "",
        task_id: str = "",
        step: int = -1,
        **extra,
    ) -> None:
        """Log an agent-to-agent transition."""
        self._emit(LogEntry(
            level="INFO",
            category="transition",
            agent=source, from_agent=from_agent, to_agent=to_agent,
            reason=reason, task_id=task_id, step=step, data=extra,
        ))

    # ── Lifecycle: agent/task/graph start/stop ──

    def lifecycle(
        self,
        agent: str,
        event: str,
        *,
        reason: str = "",
        latency_ms: int = 0,
        task_id: str = "",
        step: int = -1,
        **extra,
    ) -> None:
        """Log a lifecycle event (task_start, task_end, agent_reset, etc.)."""
        self._emit(LogEntry(
            level="INFO",
            category="lifecycle",
            agent=agent, action=event, reason=reason,
            latency_ms=latency_ms, task_id=task_id, step=step,
            data=extra,
        ))

    # ── Error: something went wrong ──

    def error(
        self,
        agent: str,
        action: str = "",
        *,
        error: str = "",
        step: int = -1,
        task_id: str = "",
        url: str = "",
        **extra,
    ) -> None:
        """Log an error."""
        self._emit(LogEntry(
            level="ERROR",
            category="error",
            agent=agent, action=action, error=error,
            step=step, task_id=task_id, url=url, data=extra,
        ))

    # ── Safety: safety guard verdict ──

    def safety(
        self,
        agent: str,
        action: str,
        *,
        verdict: str,
        reason: str = "",
        category: str = "",
        task_id: str = "",
        **extra,
    ) -> None:
        """Log a safety guard decision (allow/confirm/block)."""
        level = "WARN" if verdict in ("block", "confirm") else "DEBUG"
        self._emit(LogEntry(
            level=level,
            category="safety",
            agent=agent, action=action, reason=reason,
            task_id=task_id,
            data={"verdict": verdict, "category": category, **extra},
        ))

    # ── Rollback: undo actions ──

    def rollback(
        self,
        agent: str,
        action: str = "",
        *,
        reason: str = "",
        undone: int = 0,
        requested: int = 0,
        step: int = -1,
        task_id: str = "",
        **extra,
    ) -> None:
        """Log a rollback event."""
        self._emit(LogEntry(
            level="WARN",
            category="rollback",
            agent=agent, action=action, reason=reason,
            step=step, task_id=task_id,
            data={"undone": undone, "requested": requested, **extra},
        ))

    # ── Metric: performance/stats ──

    def metric(
        self,
        agent: str,
        name: str,
        *,
        latency_ms: int = 0,
        task_id: str = "",
        **values,
    ) -> None:
        """Log a metric (latency, counts, etc.)."""
        self._emit(LogEntry(
            level="INFO",
            category="metric",
            agent=agent, action=name,
            latency_ms=latency_ms, task_id=task_id,
            data=values,
        ))


# ─── GLOBAL INSTANCE ─────────────────────────────────────────

obs = StructuredLogger(json_mode=False)
