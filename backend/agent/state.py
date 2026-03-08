"""Shared agent state — the single source of truth flowing through the agent graph.

Every agent reads what it needs and writes its output fields.
Inspired by LangGraph's shared state pattern.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal


TaskStatus = Literal[
    "idle", "perceiving", "orchestrating", "navigating",
    "filling_form", "extracting", "verifying",
    "awaiting_approval", "done", "failed",
]


@dataclass
class SubTask:
    """A decomposed piece of the main task."""
    index: int
    instruction: str
    agent: str  # "navigator", "form_filler", "data_extractor", "verifier"
    status: Literal["pending", "in_progress", "done", "failed"] = "pending"
    result: str = ""


@dataclass
class PageContext:
    """Everything we know about the current page."""
    url: str = ""
    title: str = ""
    screenshot_b64: str = ""
    page_summary: str = ""
    current_state: str = ""
    elements: list[dict] = field(default_factory=list)       # from Gemini vision
    dom_elements: list[dict] = field(default_factory=list)    # from extension DOM snapshot
    dom_mutations: list[dict] = field(default_factory=list)   # recent DOM changes
    cookies: list[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentState:
    """The shared mutable state that flows through the agent graph."""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    instruction: str = ""
    status: TaskStatus = "idle"
    mode: str = "api"  # "api" or "extension"

    # Which agent is currently active
    current_agent: str = "orchestrator"

    # Page context (set by Perceiver)
    page: PageContext = field(default_factory=PageContext)

    # Task decomposition (set by Orchestrator)
    subtasks: list[SubTask] = field(default_factory=list)
    current_subtask_index: int = 0

    # Execution history
    action_history: list[dict] = field(default_factory=list)
    step_index: int = 0
    max_steps: int = 30

    # Memory context (set before graph starts)
    memory_context: dict = field(default_factory=dict)

    # Extracted data (set by DataExtractor)
    extracted_data: dict = field(default_factory=dict)

    # Verification (set by Verifier)
    verification: dict = field(default_factory=dict)

    # Result
    result_summary: str = ""
    error: str | None = None
    retries: int = 0
    max_retries: int = 2

    # Timing
    start_time: float = field(default_factory=time.time)

    @property
    def current_subtask(self) -> SubTask | None:
        if 0 <= self.current_subtask_index < len(self.subtasks):
            return self.subtasks[self.current_subtask_index]
        return None

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("done", "failed")

    def record_action(self, action: dict) -> None:
        self.action_history.append({
            **action,
            "step": self.step_index,
            "timestamp": time.time(),
        })
        self.step_index += 1

    def advance_subtask(self) -> bool:
        """Move to next subtask. Returns False if no more subtasks."""
        if self.current_subtask:
            self.current_subtask.status = "done"
        self.current_subtask_index += 1
        if self.current_subtask_index >= len(self.subtasks):
            return False
        return True
