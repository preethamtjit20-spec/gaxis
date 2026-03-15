"""Shared agent state — the single source of truth flowing through the agent graph.

Every agent reads what it needs and writes its output fields.
State is split into explicit sub-states to prevent mutation collisions:

  AgentState
   ├── task      — instruction, intent, slots (immutable after planning)
   ├── execution — step tracking, subtasks, action history
   ├── page      — current page context (screenshot, DOM, URL)
   ├── memory    — episodic memory context (set once before execution)
   └── runtime   — current agent, verification, result, error

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
    "awaiting_approval", "awaiting_clarification",
    "needs_input", "done", "failed",
]


@dataclass
class SubTask:
    """A decomposed piece of the main task."""
    index: int
    instruction: str
    agent: str  # "navigator", "form_filler", "data_extractor", "verifier"
    status: Literal["pending", "in_progress", "done", "failed"] = "pending"
    result: str = ""


# ─── SUB-STATE: Page Context ─────────────────────────────────

@dataclass
class PageContext:
    """Everything we know about the current page.

    Written by: Perceiver, Navigator, FastLoop, core (DOM injection)
    Read by: all agents that need page awareness
    """
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


# ─── SUB-STATE: Task Context ─────────────────────────────────

@dataclass
class TaskContext:
    """What the user wants done — set during planning, stable during execution.

    Written by: ConversationPlanner → StateMachine PLANNING state
    Read by: all agents
    """
    instruction: str = ""
    intent: str = ""                           # CREATE_EVENT, SEND_EMAIL, etc.
    slots: dict = field(default_factory=dict)   # planner-collected slot values
    planner_slots: dict = field(default_factory=dict)  # raw planner output
    planner_intent: str = ""


# ─── SUB-STATE: Navigator Memory ────────────────────────────

@dataclass
class NavigatorMemory:
    """Short-term action memory for the navigator.

    Tracks what was accomplished (not just attempted) so the navigator:
      - Never re-fills a field that already has the right value
      - Never re-clicks a button it already clicked
      - Knows which form fields are done vs pending
      - Can detect when it's stuck repeating the same action

    Written by: NavigatorAgent, FormFillerAgent, FastAgentLoop
    Read by: NavigatorAgent (prompt injection), FastAgentLoop (prompt)
    """
    # Structured field memory: field_name → {value, status, step}
    filled_fields: dict[str, dict] = field(default_factory=dict)
    # Clicked elements: element_description → {step, count, success}
    clicked_elements: dict[str, dict] = field(default_factory=dict)
    # URLs visited during this task
    visited_urls: list[str] = field(default_factory=list)
    # Ordered list of successful actions: [(step, action_type, description)]
    completed_actions: list[tuple[int, str, str]] = field(default_factory=list)
    # Failed actions for retry avoidance: [(step, action_type, error)]
    failed_actions: list[tuple[int, str, str]] = field(default_factory=list)

    def record_fill(self, field_name: str, value: str, step: int, success: bool = True) -> None:
        """Record a field fill attempt."""
        if success:
            self.filled_fields[field_name] = {
                "value": value, "step": step, "status": "filled",
            }
            self.completed_actions.append((step, "fill", f"{field_name}={value}"))
        else:
            self.failed_actions.append((step, "fill", f"{field_name} failed"))

    def record_click(self, element: str, step: int, success: bool = True) -> None:
        """Record a click on an element."""
        key = element[:80]  # Normalize length
        if key in self.clicked_elements:
            self.clicked_elements[key]["count"] += 1
            self.clicked_elements[key]["step"] = step
        else:
            self.clicked_elements[key] = {"step": step, "count": 1, "success": success}
        if success:
            self.completed_actions.append((step, "click", key))
        else:
            self.failed_actions.append((step, "click", f"{key} failed"))

    def record_navigate(self, url: str, step: int) -> None:
        """Record a navigation."""
        if url not in self.visited_urls:
            self.visited_urls.append(url)
        self.completed_actions.append((step, "navigate", url[:60]))

    def is_field_filled(self, field_name: str) -> bool:
        """Check if a field was already successfully filled."""
        return field_name in self.filled_fields and self.filled_fields[field_name]["status"] == "filled"

    def is_element_clicked(self, element: str, max_times: int = 1) -> bool:
        """Check if an element was already clicked enough times."""
        key = element[:80]
        info = self.clicked_elements.get(key)
        return info is not None and info["count"] >= max_times

    def click_count(self, element: str) -> int:
        """How many times was this element clicked?"""
        return self.clicked_elements.get(element[:80], {}).get("count", 0)

    def to_prompt(self, max_items: int = 15) -> str:
        """Render action memory as a prompt section for the LLM.

        Shows: what's done, what failed, what to avoid repeating.
        """
        lines = []

        # Completed fields
        if self.filled_fields:
            lines.append("FILLED FIELDS (do NOT re-type these):")
            for name, info in self.filled_fields.items():
                lines.append(f"  ✓ {name} = \"{info['value']}\"")

        # Recent successful actions
        if self.completed_actions:
            recent = self.completed_actions[-max_items:]
            lines.append("COMPLETED ACTIONS (already done — skip these):")
            for step, action_type, desc in recent:
                lines.append(f"  {step}. [{action_type}] {desc}")

        # Failed actions (avoid repeating)
        if self.failed_actions:
            recent_fails = self.failed_actions[-5:]
            lines.append("FAILED ACTIONS (try a different approach):")
            for step, action_type, desc in recent_fails:
                lines.append(f"  ✗ {step}. [{action_type}] {desc}")

        # Duplicate click warnings
        repeated = [
            (el, info) for el, info in self.clicked_elements.items()
            if info["count"] >= 2
        ]
        if repeated:
            lines.append("REPEATED CLICKS (likely stuck — try something else):")
            for el, info in repeated:
                lines.append(f"  ⚠ Clicked \"{el}\" {info['count']}x")

        return "\n".join(lines)


# ─── SUB-STATE: Execution Context ────────────────────────────

@dataclass
class ExecutionContext:
    """Execution tracking — step counts, subtasks, action history.

    Written by: Orchestrator (subtasks), all agents (action_history)
    Read by: Orchestrator (routing), core (progress tracking)
    """
    subtasks: list[SubTask] = field(default_factory=list)
    current_subtask_index: int = 0
    action_history: list[dict] = field(default_factory=list)
    step_index: int = 0
    max_steps: int = 30
    retries: int = 0
    max_retries: int = 3
    graph_retries: int = 0
    max_graph_retries: int = 3

    @property
    def current_subtask(self) -> SubTask | None:
        if 0 <= self.current_subtask_index < len(self.subtasks):
            return self.subtasks[self.current_subtask_index]
        return None

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
        return self.current_subtask_index < len(self.subtasks)


# ─── SUB-STATE: Runtime Context ──────────────────────────────

@dataclass
class RuntimeContext:
    """Mutable runtime state — current agent, results, errors.

    Written by: active agent
    Read by: orchestrator, core
    """
    current_agent: str = "orchestrator"
    extracted_data: dict = field(default_factory=dict)      # DataExtractor output
    verification: dict = field(default_factory=dict)        # Verifier output
    partial_result: dict = field(default_factory=dict)      # task_partial output: {summary, missing}
    result_summary: str = ""
    error: str | None = None


# ─── MAIN STATE ──────────────────────────────────────────────

@dataclass
class AgentState:
    """The shared mutable state that flows through the agent graph.

    Sub-states provide clear ownership boundaries:
      - task: set once during planning → read-only during execution
      - execution: tracking counters, modified by execution engine
      - page: volatile, updated on every page load/navigation
      - runtime: current agent output, results, errors
    """
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    status: TaskStatus = "idle"
    mode: str = "api"  # "api" or "extension"

    # Sub-states
    task: TaskContext = field(default_factory=TaskContext)
    page: PageContext = field(default_factory=PageContext)
    execution: ExecutionContext = field(default_factory=ExecutionContext)
    runtime: RuntimeContext = field(default_factory=RuntimeContext)
    navigator_memory: NavigatorMemory = field(default_factory=NavigatorMemory)

    # Memory context (set once before graph starts, read-only during execution)
    memory_context: dict = field(default_factory=dict)

    # Timing
    start_time: float = field(default_factory=time.time)

    # ── Backward compatibility properties ──
    # These proxy to sub-states so existing code continues to work
    # without a mass refactor. New code should use sub-states directly.

    @property
    def instruction(self) -> str:
        return self.task.instruction

    @instruction.setter
    def instruction(self, val: str):
        self.task.instruction = val

    @property
    def planner_slots(self) -> dict:
        return self.task.planner_slots

    @planner_slots.setter
    def planner_slots(self, val: dict):
        self.task.planner_slots = val

    @property
    def planner_intent(self) -> str:
        return self.task.planner_intent

    @planner_intent.setter
    def planner_intent(self, val: str):
        self.task.planner_intent = val

    @property
    def current_agent(self) -> str:
        return self.runtime.current_agent

    @current_agent.setter
    def current_agent(self, val: str):
        self.runtime.current_agent = val

    @property
    def extracted_data(self) -> dict:
        return self.runtime.extracted_data

    @extracted_data.setter
    def extracted_data(self, val: dict):
        self.runtime.extracted_data = val

    @property
    def verification(self) -> dict:
        return self.runtime.verification

    @verification.setter
    def verification(self, val: dict):
        self.runtime.verification = val

    @property
    def result_summary(self) -> str:
        return self.runtime.result_summary

    @result_summary.setter
    def result_summary(self, val: str):
        self.runtime.result_summary = val

    @property
    def error(self) -> str | None:
        return self.runtime.error

    @error.setter
    def error(self, val: str | None):
        self.runtime.error = val

    @property
    def subtasks(self) -> list[SubTask]:
        return self.execution.subtasks

    @subtasks.setter
    def subtasks(self, val: list[SubTask]):
        self.execution.subtasks = val

    @property
    def current_subtask_index(self) -> int:
        return self.execution.current_subtask_index

    @current_subtask_index.setter
    def current_subtask_index(self, val: int):
        self.execution.current_subtask_index = val

    @property
    def action_history(self) -> list[dict]:
        return self.execution.action_history

    @action_history.setter
    def action_history(self, val: list[dict]):
        self.execution.action_history = val

    @property
    def step_index(self) -> int:
        return self.execution.step_index

    @step_index.setter
    def step_index(self, val: int):
        self.execution.step_index = val

    @property
    def max_steps(self) -> int:
        return self.execution.max_steps

    @max_steps.setter
    def max_steps(self, val: int):
        self.execution.max_steps = val

    @property
    def retries(self) -> int:
        return self.execution.retries

    @retries.setter
    def retries(self, val: int):
        self.execution.retries = val

    @property
    def max_retries(self) -> int:
        return self.execution.max_retries

    @max_retries.setter
    def max_retries(self, val: int):
        self.execution.max_retries = val

    @property
    def graph_retries(self) -> int:
        return self.execution.graph_retries

    @graph_retries.setter
    def graph_retries(self, val: int):
        self.execution.graph_retries = val

    @property
    def max_graph_retries(self) -> int:
        return self.execution.max_graph_retries

    @max_graph_retries.setter
    def max_graph_retries(self, val: int):
        self.execution.max_graph_retries = val

    # ── Convenience methods ──

    @property
    def current_subtask(self) -> SubTask | None:
        return self.execution.current_subtask

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("done", "failed")

    def record_action(self, action: dict) -> None:
        self.execution.record_action(action)
        # Auto-populate navigator memory from every action
        self._update_navigator_memory(action)

    def _update_navigator_memory(self, action: dict) -> None:
        """Extract structured info from an action and record it."""
        action_type = action.get("action_type", "")
        args = action.get("args", {})
        success = action.get("success", False)
        step = action.get("step", self.execution.step_index)

        if action_type == "navigate":
            url = args.get("url", "")
            if url and success:
                self.navigator_memory.record_navigate(url, step)

        elif action_type == "type_text":
            # Determine field name from element description or coordinates
            desc = args.get("element_description", "")
            text = args.get("text", "")
            field_name = desc or f"field@({args.get('x', '?')},{args.get('y', '?')})"
            self.navigator_memory.record_fill(field_name, text, step, success)

        elif action_type == "click":
            desc = args.get("element_description", "")
            if desc:
                self.navigator_memory.record_click(desc, step, success)

        elif action_type == "fill_form":
            # Batch fill — record each field individually
            fields = args.get("fields", [])
            for i, f in enumerate(fields):
                hints = f.get("hints", {})
                field_name = (
                    hints.get("aria")
                    or hints.get("placeholder")
                    or hints.get("text")
                    or f"field_{i}"
                )
                value = f.get("value", "")
                action_name = f.get("action", "type")
                if action_name == "click":
                    self.navigator_memory.record_click(field_name, step, success)
                elif value:
                    self.navigator_memory.record_fill(field_name, value, step, success)

    def advance_subtask(self) -> bool:
        return self.execution.advance_subtask()
