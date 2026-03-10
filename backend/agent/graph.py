"""Agent Graph — LangGraph-style state machine for multi-agent orchestration.

The graph runs a loop:
  1. Perceive (screenshot → page understanding)
  2. Orchestrate (pick next specialist)
  3. Run specialist (execute actions)
  4. Policy check (approval gates)
  5. Loop until done/failed/max_steps

Each node is an agent that reads/writes shared AgentState.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from backend.agent.state import AgentState
from backend.agent.base import BaseAgent
from backend.policy.engine import PolicyEngine

logger = logging.getLogger("gaxis.graph")


class AgentGraph:
    """State machine that orchestrates multiple agents."""

    def __init__(
        self,
        agents: dict[str, BaseAgent],
        policy: PolicyEngine,
        emit_fn: Callable | None = None,
        get_screenshot_fn: Callable | None = None,
        get_browser_state_fn: Callable | None = None,
        approval_fn: Callable | None = None,
    ):
        self.agents = agents
        self.policy = policy
        self.emit_fn = emit_fn
        self.get_screenshot_fn = get_screenshot_fn      # extension mode
        self.get_browser_state_fn = get_browser_state_fn  # API mode
        self.approval_fn = approval_fn

    async def run(self, state: AgentState) -> AgentState:
        """Execute the agent graph until terminal state or max steps."""
        logger.info(f"Graph starting: task={state.task_id}, instruction={state.instruction[:80]}")

        # Reset all agents for the new task
        for agent in self.agents.values():
            agent.reset()

        while not state.is_terminal and state.step_index < state.max_steps:
            try:
                # ── Step 1: Get fresh screenshot ──
                state = await self._capture_page(state)

                # ── Step 2: Perceive ──
                if "perceiver" in self.agents:
                    await self._emit_event(state, "perceiving", {
                        "step": state.step_index,
                        "url": state.page.url,
                        "title": state.page.title,
                        "agent": "perceiver",
                    })

                    state = await self.agents["perceiver"].step(state)

                    await self._emit_event(state, "perception", {
                        "step": state.step_index,
                        "page_summary": state.page.page_summary,
                        "current_state": state.page.current_state,
                        "element_count": len(state.page.elements),
                        "screenshot": state.page.screenshot_b64,
                    })

                if state.is_terminal:
                    break

                # ── Step 3: Orchestrate or run current agent ──
                current = state.current_agent or "orchestrator"

                # If no subtasks yet or all done, go to orchestrator
                if current == "orchestrator" or not state.subtasks or all(
                    s.status in ("done", "failed") for s in state.subtasks
                ):
                    current = "orchestrator"
                    state.current_agent = "orchestrator"

                if current not in self.agents:
                    logger.error(f"Unknown agent: {current}, falling back to orchestrator")
                    current = "orchestrator"

                await self._emit_event(state, "agent_active", {
                    "agent": current,
                    "step": state.step_index,
                    "subtask": state.current_subtask.instruction if state.current_subtask else None,
                })

                # Save step index before agent runs (agent may execute multiple tool calls)
                pre_step = state.step_index

                # ── Run the agent ──
                state = await self.agents[current].step(state)

                # ── Step 4: Policy check on actions taken ──
                new_actions = state.action_history[pre_step:]
                for action in new_actions:
                    if action.get("action_type") in ("task_complete", "task_failed", "delegate", "extract_data"):
                        continue  # Control flow, no policy check needed

                    decision = self.policy.evaluate(
                        action_type=action.get("action_type", ""),
                        risk_level=self._estimate_risk(action),
                        confidence=0.7,  # Default — agents don't report confidence individually
                        element_id=action.get("args", {}).get("element_description", ""),
                        is_sensitive=self._is_sensitive_action(action),
                    )

                    if decision.verdict == "require_approval":
                        # In API mode, auto-approve non-critical actions (no human operator)
                        if state.mode == "api" and decision.risk_level not in ("critical",):
                            logger.info(f"Auto-approved {action.get('action_type')} in API mode (risk: {decision.risk_level})")
                            self.policy.record_approval(action.get("action_type", ""))
                        else:
                            state.status = "awaiting_approval"
                            await self._emit_event(state, "approval_needed", {
                                "step": state.step_index,
                                "action_type": action.get("action_type"),
                                "reason": decision.reason,
                                "risk_level": decision.risk_level,
                            })

                            if self.approval_fn:
                                approved = await self.approval_fn()
                                if not approved:
                                    state.status = "failed"
                                    state.error = "Operator denied action"
                                    break
                                self.policy.record_approval(action.get("action_type", ""))

                    elif decision.verdict == "deny":
                        state.status = "failed"
                        state.error = f"Policy denied: {decision.reason}"
                        break

                # ── Step 5: Emit progress ──
                if not state.is_terminal:
                    for action in new_actions:
                        if action.get("success"):
                            await self._emit_event(state, "action_succeeded", {
                                "step": action.get("step", state.step_index),
                                "action_type": action.get("action_type"),
                                "agent": action.get("agent"),
                                "duration_ms": action.get("duration_ms", 0),
                            })
                        elif action.get("error"):
                            await self._emit_event(state, "action_failed", {
                                "step": action.get("step", state.step_index),
                                "error": action.get("error"),
                            })

                # ── Check if orchestrator completed the task ──
                if state.result_summary and current == "orchestrator":
                    state.status = "done"
                    break

                # ── If a specialist completed, go back to orchestrator ──
                if state.current_agent == "orchestrator" and current != "orchestrator":
                    logger.info(f"Agent {current} completed, returning to orchestrator")

                # Brief pause between steps
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"Graph step error: {e}", exc_info=True)
                state.retries += 1
                if state.retries > state.max_retries:
                    state.status = "failed"
                    state.error = f"Max retries exceeded: {e}"
                    break
                logger.warning(f"Retrying after error (attempt {state.retries})")
                await asyncio.sleep(1.0)

        # ── Final state ──
        if not state.is_terminal:
            if state.step_index >= state.max_steps:
                state.status = "failed"
                state.error = f"Exceeded maximum steps ({state.max_steps})"
            elif not state.result_summary:
                state.status = "failed"
                state.error = "Graph ended without result"

        logger.info(
            f"Graph completed: status={state.status}, "
            f"steps={state.step_index}, elapsed={state.elapsed_ms}ms"
        )

        return state

    async def _capture_page(self, state: AgentState) -> AgentState:
        """Capture screenshot (and optionally DOM) based on mode."""
        if state.mode == "extension":
            if self.get_screenshot_fn:
                screenshot_b64, url, title = await self.get_screenshot_fn()
                state.page.screenshot_b64 = screenshot_b64
                state.page.url = url
                state.page.title = title
        else:
            if self.get_browser_state_fn:
                browser_state = await self.get_browser_state_fn()
                state.page.screenshot_b64 = browser_state.screenshot_b64
                state.page.url = browser_state.url
                state.page.title = browser_state.title
        return state

    async def _emit_event(self, state: AgentState, event_type: str, data: dict) -> None:
        """Emit a task event to connected clients."""
        if self.emit_fn:
            from backend.agent.core import TaskEvent
            await self.emit_fn(TaskEvent(event_type, state.task_id, data))

    def _estimate_risk(self, action: dict) -> str:
        """Estimate risk level from action data."""
        args = action.get("args", {})
        action_type = action.get("action_type", "")

        # Navigation to external sites
        if action_type == "navigate":
            return "medium"

        # Typing in fields
        if action_type == "type_text":
            text = args.get("text", "").lower()
            if any(w in text for w in ["password", "card", "ssn", "credit"]):
                return "critical"
            return "low"

        # Clicking
        desc = args.get("element_description", "").lower()
        if any(w in desc for w in ["buy", "purchase", "pay", "submit", "delete", "remove"]):
            return "high"
        if any(w in desc for w in ["confirm", "agree", "accept"]):
            return "medium"

        return "low"

    def _is_sensitive_action(self, action: dict) -> bool:
        """Check if action involves sensitive elements."""
        args = action.get("args", {})
        desc = (args.get("element_description", "") or "").lower()
        text = (args.get("text", "") or "").lower()

        sensitive_words = ["password", "payment", "credit", "ssn", "social security", "bank"]
        return any(w in desc or w in text for w in sensitive_words)
