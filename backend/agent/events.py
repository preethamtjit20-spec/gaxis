"""Global Event Bus — decoupled agent communication.

Instead of agents directly mutating state.current_agent or calling
agent.reset(), they emit typed events. The orchestration layer
(AgentGraph / FastLoop) subscribes to events and reacts.

This removes tight coupling between agents:
  BEFORE: navigator sets state.current_agent = "verifier"  (knows about verifier)
  AFTER:  navigator emits TASK_COMPLETED → bus routes to verifier  (knows nothing)

Event types are organized by domain:
  - Navigation events (PAGE_NAVIGATED, NAVIGATION_FAILED)
  - Agent lifecycle events (AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED)
  - Form events (FORM_SUBMITTED, FORM_FILL_FAILED)
  - Verification events (VERIFICATION_PASSED, VERIFICATION_FAILED)
  - Task events (TASK_COMPLETED, TASK_FAILED, TASK_NEEDS_INPUT)

Usage:
    bus = EventBus()
    bus.on(EventType.NAVIGATION_COMPLETED, handle_nav)
    bus.on(EventType.AGENT_COMPLETED, handle_agent_done)
    await bus.emit(AgentEvent(EventType.AGENT_COMPLETED, agent="navigator", ...))
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger("gaxis.events")


# ─── EVENT TYPES ─────────────────────────────────────────────────

class EventType(str, Enum):
    """All event types in the G-Axis agent system."""

    # Navigation
    PAGE_NAVIGATED = "page_navigated"
    NAVIGATION_FAILED = "navigation_failed"
    PAGE_CHANGED = "page_changed"         # URL or content changed

    # Agent lifecycle
    AGENT_STARTED = "agent_started"       # Agent began processing
    AGENT_COMPLETED = "agent_completed"   # Agent finished its subtask
    AGENT_FAILED = "agent_failed"         # Agent encountered an error
    AGENT_STUCK = "agent_stuck"           # Agent is repeating itself

    # Form interactions
    FORM_FILLED = "form_filled"           # Batch fill completed
    FORM_FILL_FAILED = "form_fill_failed"
    FORM_SUBMITTED = "form_submitted"     # Submit button clicked

    # Verification
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_PARTIAL = "verification_partial"
    VERIFICATION_FAILED = "verification_failed"

    # Task-level
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_NEEDS_INPUT = "task_needs_input"  # Agent needs user clarification
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"

    # Orchestration
    SUBTASK_COMPLETED = "subtask_completed"
    SUBTASK_FAILED = "subtask_failed"
    DELEGATION_REQUESTED = "delegation_requested"

    # Data
    DATA_EXTRACTED = "data_extracted"

    # Skill execution
    SKILL_STARTED = "skill_started"
    SKILL_COMPLETED = "skill_completed"
    SKILL_FAILED = "skill_failed"


# ─── EVENT DATA ──────────────────────────────────────────────────

@dataclass
class AgentEvent:
    """A typed event emitted by any agent or system component.

    Unlike TaskEvent (which is for frontend display), AgentEvent
    drives internal orchestration logic.
    """
    type: EventType
    source: str = ""              # Who emitted: "navigator", "verifier", "graph", etc.
    task_id: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    # Convenience fields (avoid digging into data dict)
    agent: str = ""               # Target or source agent name
    subtask_index: int = -1       # Which subtask this relates to
    summary: str = ""             # Human-readable summary
    error: str = ""               # Error message if failed

    def __repr__(self) -> str:
        extra = f" agent={self.agent}" if self.agent else ""
        extra += f" error={self.error[:40]}" if self.error else ""
        extra += f" summary={self.summary[:40]}" if self.summary else ""
        return f"<AgentEvent {self.type.value}{extra}>"


# Type alias for event handlers
EventHandler = Callable[[AgentEvent], Awaitable[None]]


# ─── EVENT BUS ───────────────────────────────────────────────────

class EventBus:
    """Async pub/sub event bus for agent orchestration.

    Supports:
      - Type-specific handlers: bus.on(EventType.PAGE_NAVIGATED, handler)
      - Wildcard handlers: bus.on_all(handler)  — receives every event
      - One-shot handlers: bus.once(EventType.TASK_COMPLETED, handler)
      - Event history: bus.history[-10:]
    """

    def __init__(self, max_history: int = 200):
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._wildcard_handlers: list[EventHandler] = []
        self._once_handlers: dict[EventType, list[EventHandler]] = {}
        self._history: list[AgentEvent] = []
        self._max_history = max_history

    # ── Subscribe ──

    def on(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def on_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (wildcard)."""
        self._wildcard_handlers.append(handler)

    def once(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to the next occurrence of an event type, then auto-unsubscribe."""
        if event_type not in self._once_handlers:
            self._once_handlers[event_type] = []
        self._once_handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe a handler."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    # ── Emit ──

    async def emit(self, event: AgentEvent) -> None:
        """Emit an event to all matching handlers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.debug(f"Event: {event}")

        # Type-specific handlers
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Event handler error ({event.type}): {e}", exc_info=True)

        # One-shot handlers
        once_list = self._once_handlers.pop(event.type, [])
        for handler in once_list:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Once handler error ({event.type}): {e}", exc_info=True)

        # Wildcard handlers
        for handler in self._wildcard_handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Wildcard handler error ({event.type}): {e}", exc_info=True)

    # ── Query ──

    @property
    def history(self) -> list[AgentEvent]:
        """Recent event history."""
        return self._history

    def last_of(self, event_type: EventType) -> AgentEvent | None:
        """Get the most recent event of a given type."""
        for event in reversed(self._history):
            if event.type == event_type:
                return event
        return None

    def count(self, event_type: EventType) -> int:
        """Count occurrences of an event type in history."""
        return sum(1 for e in self._history if e.type == event_type)

    def reset(self) -> None:
        """Clear all handlers and history (new task)."""
        self._handlers.clear()
        self._wildcard_handlers.clear()
        self._once_handlers.clear()
        self._history.clear()

    # ── Wait ──

    async def wait_for(
        self, event_type: EventType, timeout: float = 30.0,
    ) -> AgentEvent | None:
        """Block until an event of the given type is emitted, or timeout."""
        result: list[AgentEvent] = []
        received = asyncio.Event()

        async def _capture(event: AgentEvent) -> None:
            result.append(event)
            received.set()

        self.once(event_type, _capture)
        try:
            await asyncio.wait_for(received.wait(), timeout=timeout)
            return result[0] if result else None
        except asyncio.TimeoutError:
            return None
