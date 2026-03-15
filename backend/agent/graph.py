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
from backend.agent.events import EventBus, EventType, AgentEvent
from backend.policy.engine import PolicyEngine
from backend.observability.logger import obs

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
        get_dom_fn: Callable | None = None,
        approval_fn: Callable | None = None,
        user_input_fn: Callable | None = None,
        connector_registry=None,
        is_paused_fn: Callable | None = None,
        ui_graph_registry=None,
        genai_client=None,
    ):
        self.agents = agents
        self.policy = policy
        self.emit_fn = emit_fn
        self.get_screenshot_fn = get_screenshot_fn      # extension mode
        self.get_browser_state_fn = get_browser_state_fn  # API mode
        self.get_dom_fn = get_dom_fn                    # extension DOM snapshot
        self.approval_fn = approval_fn
        self.user_input_fn = user_input_fn              # graceful handover
        self.connector_registry = connector_registry     # connector skills
        self.cancel_event: asyncio.Event | None = None  # set by main.py for stop
        self._is_paused_fn = is_paused_fn               # pause/takeover gate
        self.ui_graph_registry = ui_graph_registry       # semantic UI graphs
        self.genai_client = genai_client                 # for LLM extraction
        self.event_bus = EventBus()                     # global event bus

    def _is_cancelled(self) -> bool:
        """Check if the task has been cancelled by the user."""
        return self.cancel_event is not None and self.cancel_event.is_set()

    async def _bus_emit(self, event_type: EventType, state: AgentState, **kwargs) -> None:
        """Emit an event on the bus AND forward to frontend emit_fn."""
        event = AgentEvent(
            type=event_type,
            source=kwargs.pop("source", "graph"),
            task_id=state.task_id,
            agent=kwargs.pop("agent", ""),
            summary=kwargs.pop("summary", ""),
            error=kwargs.pop("error", ""),
            subtask_index=kwargs.pop("subtask_index", -1),
            data=kwargs,
        )
        await self.event_bus.emit(event)

    async def run(self, state: AgentState) -> AgentState:
        """Execute the agent graph until terminal state or max steps."""
        obs.lifecycle("graph", "task_start", task_id=state.task_id,
                      reason=state.instruction[:80])

        # Reset event bus and all agents for the new task
        self.event_bus.reset()

        # Forward all bus events to the frontend emit_fn
        if self.emit_fn:
            async def _forward_to_frontend(event: AgentEvent) -> None:
                from backend.agent.core import TaskEvent
                await self.emit_fn(TaskEvent(
                    type=event.type.value,
                    task_id=event.task_id,
                    data={
                        "source": event.source,
                        "agent": event.agent,
                        "summary": event.summary,
                        "error": event.error,
                        **event.data,
                    },
                ))
            self.event_bus.on_all(_forward_to_frontend)

        # Inject event bus into agents
        for agent in self.agents.values():
            agent.event_bus = self.event_bus

        # Reset all agents for the new task
        for agent in self.agents.values():
            agent.reset()

        last_url = ""
        perceiver_run_count = 0
        last_agent = ""
        last_delegation = ""
        delegation_repeat_count = 0
        handover_count = 0  # Track how many times we've asked user for input

        # ── Step 0: Run Planner to decompose task into subtasks ──
        if "planner" in self.agents and not state.subtasks:
            try:
                await self._emit_event(state, "agent_active", {
                    "agent": "planner",
                    "step": state.step_index,
                    "subtask": "Decomposing task into subtasks...",
                })
                # Capture page first so planner has context
                state = await self._capture_page(state)
                state = self._inject_ui_graph(state)
                state = await self.agents["planner"].step(state)
                logger.info(
                    f"Planner created {len(state.subtasks)} subtasks: "
                    + ", ".join(f"[{s.agent}] {s.instruction[:40]}" for s in state.subtasks)
                )
            except Exception as e:
                logger.warning(f"Planner failed ({e}), falling back to orchestrator")
                # Planner failure is non-fatal — orchestrator will handle it

        while not state.is_terminal and state.step_index < state.max_steps:
            try:
                # ── Check cancellation ──
                if self._is_cancelled():
                    state.status = "failed"
                    state.error = "Task stopped by user"
                    logger.info("Task cancelled by user — stopping graph")
                    break

                # ── Check pause/takeover ──
                if self._is_paused_fn and self._is_paused_fn():
                    logger.info("Agent paused — waiting for resume...")
                    while self._is_paused_fn and self._is_paused_fn():
                        if self._is_cancelled():
                            state.status = "failed"
                            state.error = "Task stopped by user"
                            break
                        await asyncio.sleep(0.5)
                    if state.is_terminal:
                        break
                    logger.info("Agent resumed — continuing graph")

                # ── Step 1: Get fresh screenshot ──
                state = await self._capture_page(state)

                # ── Step 1.5: Inject UI Graph for known apps ──
                state = self._inject_ui_graph(state)

                # ── Step 2: Perceiver — analyze page on URL change ──
                if (
                    "perceiver" in self.agents
                    and state.page.url
                    and state.page.url != last_url
                    and perceiver_run_count < 20
                ):
                    # Emit PAGE_CHANGED event
                    await self._bus_emit(
                        EventType.PAGE_CHANGED, state,
                        source="graph",
                        url=state.page.url,
                        previous_url=last_url,
                    )
                    await self._emit_event(state, "agent_active", {
                        "agent": "perceiver",
                        "step": state.step_index,
                        "subtask": "Analyzing page...",
                    })
                    state = await self.agents["perceiver"].step(state)
                    perceiver_run_count += 1
                    last_url = state.page.url
                    await self._emit_event(state, "perception", {
                        "step": state.step_index,
                        "page_summary": state.page.page_summary,
                        "current_state": state.page.current_state,
                        "element_count": len(state.page.elements),
                    })
                elif state.page.url:
                    last_url = state.page.url

                if state.is_terminal:
                    break

                # ── Step 3: Orchestrate or run current agent ──
                current = state.current_agent or "orchestrator"

                # If planner created subtasks, route directly to the specialist
                # for the next pending subtask (skip orchestrator overhead)
                if current != "verifier" and state.subtasks:
                    pending = [s for s in state.subtasks if s.status == "pending"]
                    all_done = all(s.status in ("done", "failed") for s in state.subtasks)
                    if all_done:
                        # All subtasks done — route to verifier for final check
                        current = "verifier"
                        state.current_agent = "verifier"
                    elif pending and current == "orchestrator":
                        # Route directly to the next pending subtask's specialist
                        next_sub = pending[0]
                        next_sub.status = "in_progress"
                        state.current_subtask_index = next_sub.index
                        target_agent = next_sub.agent
                        if target_agent in self.agents:
                            current = target_agent
                            state.current_agent = target_agent
                            logger.info(
                                f"Planner subtask {next_sub.index}: "
                                f"routing to {target_agent} for '{next_sub.instruction[:50]}'"
                            )
                        else:
                            # Unknown agent — let orchestrator handle it
                            current = "orchestrator"
                elif current != "verifier" and (
                    current == "orchestrator" or not state.subtasks or all(
                        s.status in ("done", "failed") for s in state.subtasks
                    )
                ):
                    current = "orchestrator"
                    state.current_agent = "orchestrator"

                if current not in self.agents:
                    logger.error(f"Unknown agent: {current}, falling back to orchestrator")
                    current = "orchestrator"

                # Reset agent conversation when switching agents to prevent
                # stale context from previous subtask confusing Gemini
                if current != last_agent and current in self.agents:
                    self.agents[current].reset()
                    obs.transition("graph", from_agent=last_agent, to_agent=current,
                                   reason="agent switch", task_id=state.task_id,
                                   step=state.step_index)
                last_agent = current

                # Detect infinite delegation loops
                if current == "orchestrator" and state.subtasks:
                    latest_sub = state.subtasks[-1]
                    delegation_key = f"{latest_sub.agent}:{latest_sub.instruction[:50]}"
                    if delegation_key == last_delegation:
                        delegation_repeat_count += 1
                        if delegation_repeat_count >= 3:
                            logger.warning(f"Delegation loop detected ({delegation_repeat_count}x): {delegation_key}")
                            state = await self._request_user_input(
                                state,
                                "I seem to be going in circles on this task. "
                                "Can you give me more specific guidance or take over?",
                            )
                            if state.is_terminal:
                                break
                            delegation_repeat_count = 0  # Reset after user input
                    else:
                        delegation_repeat_count = 0
                        last_delegation = delegation_key

                await self._emit_event(state, "agent_active", {
                    "agent": current,
                    "step": state.step_index,
                    "subtask": state.current_subtask.instruction if state.current_subtask else None,
                })

                # Save step index before agent runs (agent may execute multiple tool calls)
                pre_step = state.step_index

                # ── Run the agent ──
                state = await self.agents[current].step(state)

                # ── Step 3.5: Handle confirm_action — wait for user ──
                if state.status == "awaiting_approval":
                    # confirm_action was called — wait for user to click Create/Cancel
                    logger.info("Waiting for user confirmation on action card...")
                    if self.approval_fn:
                        approved = await self.approval_fn()
                        if approved:
                            logger.info("User confirmed the action")
                            state.status = "navigating"
                            # The agent should continue with the confirmed action
                            # Reset the current agent so it can proceed
                        else:
                            logger.info("User cancelled the action")
                            state.status = "failed"
                            state.error = "Action cancelled by user"
                            break

                # ── Step 4: Policy check on actions taken ──
                new_actions = state.action_history[pre_step:]
                for action in new_actions:
                    if action.get("action_type") in ("task_complete", "task_failed", "delegate", "extract_data", "confirm_action"):
                        continue  # Control flow, no policy check needed

                    decision = self.policy.evaluate(
                        action_type=action.get("action_type", ""),
                        risk_level=self._estimate_risk(action),
                        confidence=0.7,  # Default — agents don't report confidence individually
                        element_id=action.get("args", {}).get("element_description", ""),
                        is_sensitive=self._is_sensitive_action(action),
                        url=state.page.url if state.page else None,
                    )

                    if decision.verdict == "require_approval":
                        # Auto-approve non-critical actions — only ask for truly sensitive ones
                        if decision.risk_level not in ("critical", "high"):
                            logger.info(f"Auto-approved {action.get('action_type')} (risk: {decision.risk_level})")
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
                                state.status = "navigating"  # Reset from awaiting_approval

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

                # ── Check if verifier returned partial result ──
                if current == "verifier" and state.runtime.partial_result:
                    partial = state.runtime.partial_result
                    missing = partial.get("missing", [])
                    partial_summary = partial.get("summary", "")
                    logger.info(
                        f"Verifier: PARTIAL — {partial_summary}. "
                        f"{len(missing)} items to fix."
                    )
                    # Create fix subtasks from missing items
                    from backend.agent.state import SubTask
                    for item in missing:
                        fix_instruction = item.get("fix_instruction", "")
                        field_name = item.get("field", "unknown")
                        expected = item.get("expected", "")
                        if not fix_instruction:
                            fix_instruction = f"Set {field_name} to {expected}"
                        fix_sub = SubTask(
                            index=len(state.subtasks),
                            instruction=fix_instruction,
                            agent="navigator",
                            status="pending",
                        )
                        state.subtasks.append(fix_sub)
                        logger.info(f"Fix subtask added: {fix_instruction[:60]}")
                    # Clear partial result and route to next fix subtask
                    state.runtime.partial_result = {}
                    state.result_summary = ""
                    state.current_agent = "orchestrator"
                    await self._bus_emit(
                        EventType.VERIFICATION_PARTIAL, state,
                        source="graph",
                        summary=partial_summary,
                        missing_count=len(missing),
                    )
                    continue

                # ── Check if verifier confirmed subtask/task completion ──
                if state.result_summary and current == "verifier":
                    # Check if there are more subtasks to execute
                    remaining = [s for s in state.subtasks if s.status == "pending"]
                    if remaining:
                        # Subtask verified — advance to next one
                        if state.current_subtask:
                            state.current_subtask.status = "done"
                            state.current_subtask.result = state.result_summary
                            await self._bus_emit(
                                EventType.SUBTASK_COMPLETED, state,
                                source="graph",
                                summary=state.result_summary,
                                subtask_index=state.current_subtask.index,
                                remaining=len(remaining),
                            )
                        logger.info(
                            f"Verifier confirmed subtask — {len(remaining)} remaining: "
                            f"{state.result_summary[:60]}"
                        )
                        state.result_summary = ""  # Clear so graph continues
                        state.current_agent = "orchestrator"  # Route back for next subtask
                    else:
                        # All subtasks done — task complete
                        state.status = "done"
                        logger.info(f"Verifier confirmed task complete: {state.result_summary[:80]}")
                        await self._bus_emit(
                            EventType.TASK_COMPLETED, state,
                            source="graph",
                            summary=state.result_summary,
                        )
                        break

                # ── If verifier REJECTED (task_failed), rollback + retry ──
                if state.status == "failed" and current == "verifier":
                    verifier_reject_count = getattr(state, '_verifier_reject_count', 0) + 1
                    state._verifier_reject_count = verifier_reject_count
                    if verifier_reject_count >= 2:
                        logger.warning(f"Verifier rejected {verifier_reject_count}x — stopping to avoid loop.")
                        break  # Keep status as failed
                    # Auto-rollback last few actions before retrying
                    executor = self.agents.get("navigator", self.agents.get("orchestrator"))
                    if executor and hasattr(executor, "tool_executor"):
                        rb_mgr = executor.tool_executor.rollback_manager
                        if rb_mgr and rb_mgr.can_rollback:
                            logger.info("Verifier rejected — auto-rolling back last 2 actions")
                            await rb_mgr.rollback(
                                n=2, mode=state.mode,
                                emit_fn=self.emit_fn, task_id=state.task_id,
                            )
                    logger.warning(f"Verifier rejected: {state.error}. Returning to orchestrator to retry.")
                    state.status = "orchestrating"
                    state.current_agent = "orchestrator"
                    if "orchestrator" in self.agents:
                        self.agents["orchestrator"].reset()
                    continue

                # ── If navigator/specialist claims complete, route directly to verifier ──
                if state.current_agent == "verifier" and current in ("navigator", "form_filler", "data_extractor"):
                    logger.info(f"Agent {current} claims complete — routing directly to verifier")

                # ── If a specialist completed, go back to orchestrator ──
                if state.current_agent == "orchestrator" and current != "orchestrator":
                    logger.info(f"Agent {current} completed, returning to orchestrator")

                # Track URL changes for perceiver gating
                if state.page.url:
                    last_url = state.page.url

                # Brief pause between steps
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"Graph step error: {e}", exc_info=True)
                state.graph_retries += 1
                if state.graph_retries > state.max_graph_retries:
                    state.status = "failed"
                    state.error = f"Max retries exceeded: {e}"
                    break
                logger.warning(f"Retrying after error (attempt {state.graph_retries})")
                await asyncio.sleep(1.0)

        # ── Graceful handover — ask user instead of hard fail ──
        if (
            not state.is_terminal
            and state.step_index >= state.max_steps
            and handover_count < 3
        ):
            handover_count += 1
            state = await self._request_user_input(
                state,
                f"I've taken {state.step_index} steps but haven't completed the task yet. "
                f"Would you like me to continue, try a different approach, or take over manually?",
            )
            if not state.is_terminal:
                # User wants to continue — extend and go back to main loop
                state.max_steps += 15
                delegation_repeat_count = 0
                logger.info(f"User extended task, new max_steps={state.max_steps}")
                # Jump back to the main while loop (reuses full logic with policy checks)
                # We use a simple goto-like pattern: call run() again but skip agent reset
                return await self._continue_run(
                    state, last_url, perceiver_run_count,
                    last_agent, last_delegation, delegation_repeat_count,
                    handover_count,
                )

        if not state.is_terminal and not state.result_summary:
            state.status = "failed"
            state.error = "Graph ended without result"

        obs.lifecycle("graph", "task_end", task_id=state.task_id,
                      reason=state.result_summary[:60] if state.result_summary else state.error or "",
                      latency_ms=state.elapsed_ms,
                      status=state.status, steps=state.step_index)

        return state

    async def _continue_run(
        self, state, last_url, perceiver_run_count,
        last_agent, last_delegation, delegation_repeat_count,
        handover_count,
    ) -> AgentState:
        """Continue the graph run after user extends the task. Reuses the full main loop."""
        # This is identical to run() but skips agent reset
        while not state.is_terminal and state.step_index < state.max_steps:
            try:
                state = await self._capture_page(state)
                current = state.current_agent or "orchestrator"
                url_changed = state.page.url != last_url
                needs_perception = (
                    "perceiver" in self.agents
                    and url_changed
                    and current == "orchestrator"
                )
                if needs_perception:
                    await self._emit_event(state, "perceiving", {
                        "step": state.step_index, "url": state.page.url,
                        "title": state.page.title, "agent": "perceiver",
                    })
                    state = await self.agents["perceiver"].step(state)
                    perceiver_run_count += 1
                    last_url = state.page.url
                    await self._emit_event(state, "perception", {
                        "step": state.step_index,
                        "page_summary": state.page.page_summary,
                        "current_state": state.page.current_state,
                        "element_count": len(state.page.elements),
                        "screenshot": state.page.screenshot_b64,
                    })

                if state.is_terminal:
                    break

                current = state.current_agent or "orchestrator"
                if not state.subtasks or all(s.status in ("done", "failed") for s in state.subtasks):
                    current = "orchestrator"
                    state.current_agent = "orchestrator"
                if current not in self.agents:
                    current = "orchestrator"
                if current != last_agent and current in self.agents:
                    self.agents[current].reset()
                last_agent = current

                await self._emit_event(state, "agent_active", {
                    "agent": current, "step": state.step_index,
                    "subtask": state.current_subtask.instruction if state.current_subtask else None,
                })

                pre_step = state.step_index
                state = await self.agents[current].step(state)

                # Policy check (same as main loop)
                new_actions = state.action_history[pre_step:]
                for action in new_actions:
                    if action.get("action_type") in ("task_complete", "task_failed", "delegate", "extract_data"):
                        continue
                    decision = self.policy.evaluate(
                        action_type=action.get("action_type", ""),
                        risk_level=self._estimate_risk(action),
                        confidence=0.7,
                        element_id=action.get("args", {}).get("element_description", ""),
                        is_sensitive=self._is_sensitive_action(action),
                        url=state.page.url if state.page else None,
                    )
                    if decision.verdict == "require_approval" and decision.risk_level in ("critical", "high"):
                        state.status = "awaiting_approval"
                        await self._emit_event(state, "approval_needed", {
                            "step": state.step_index,
                            "action_type": action.get("action_type"),
                            "reason": decision.reason, "risk_level": decision.risk_level,
                        })
                        if self.approval_fn:
                            approved = await self.approval_fn()
                            if not approved:
                                state.status = "failed"
                                state.error = "Operator denied action"
                                break
                            self.policy.record_approval(action.get("action_type", ""))
                            state.status = "navigating"
                    elif decision.verdict == "deny":
                        state.status = "failed"
                        state.error = f"Policy denied: {decision.reason}"
                        break

                if not state.is_terminal:
                    for action in new_actions:
                        if action.get("success"):
                            await self._emit_event(state, "action_succeeded", {
                                "step": action.get("step", state.step_index),
                                "action_type": action.get("action_type"),
                                "agent": action.get("agent"),
                                "duration_ms": action.get("duration_ms", 0),
                            })

                # Same completion logic as main run loop
                if state.result_summary and current == "verifier":
                    state.status = "done"
                    break
                if state.result_summary and current in ("navigator", "form_filler", "data_extractor"):
                    state.current_agent = "orchestrator"

                if state.page.url:
                    last_url = state.page.url
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"Extended graph step error: {e}", exc_info=True)
                state.graph_retries += 1
                if state.graph_retries > state.max_graph_retries:
                    state.status = "failed"
                    state.error = f"Max retries exceeded: {e}"
                    break
                await asyncio.sleep(1.0)

        # Can ask user again if still not done
        if (
            not state.is_terminal
            and state.step_index >= state.max_steps
            and handover_count < 3
        ):
            handover_count += 1
            state = await self._request_user_input(
                state,
                f"Still working on it after {state.step_index} steps. Continue or stop?",
            )
            if not state.is_terminal:
                state.max_steps += 15
                return await self._continue_run(
                    state, last_url, perceiver_run_count,
                    last_agent, last_delegation, delegation_repeat_count,
                    handover_count,
                )

        if not state.is_terminal and not state.result_summary:
            state.status = "failed"
            state.error = "Graph ended without result"

        logger.info(f"Extended run completed: status={state.status}, steps={state.step_index}")
        return state

    async def _request_user_input(self, state: AgentState, message: str) -> AgentState:
        """Ask user for input — graceful handover instead of hard fail."""
        state.status = "needs_input"
        await self._emit_event(state, "needs_input", {
            "message": message,
            "step": state.step_index,
            "current_agent": state.current_agent,
            "page_url": state.page.url,
        })

        if self.user_input_fn:
            user_response = await self.user_input_fn()
            if user_response:
                if user_response.lower() in ("stop", "cancel", "quit"):
                    state.status = "failed"
                    state.error = "Stopped by user"
                elif user_response.lower() in ("continue", "yes", "go"):
                    state.status = "navigating"  # Resume
                else:
                    # User gave new instructions — update task
                    state.instruction = f"{state.instruction}. Additional guidance: {user_response}"
                    state.status = "orchestrating"
                    state.current_agent = "orchestrator"
                    # Reset orchestrator conversation for fresh context
                    if "orchestrator" in self.agents:
                        self.agents["orchestrator"].reset()
            else:
                state.status = "failed"
                state.error = "No response from user"
        else:
            # No input function — just fail gracefully
            state.status = "failed"
            state.error = f"Task incomplete after {state.step_index} steps — user input needed"

        return state

    def _inject_ui_graph(self, state: AgentState) -> AgentState:
        """Detect known apps and inject UI Graph context into state."""
        if not self.ui_graph_registry or not state.page.url:
            state._ui_graph_text = ""
            return state

        graph = self.ui_graph_registry.detect_and_get(
            state.page.url, state.page.title
        )
        if graph:
            from backend.uigraph.prompt import serialize_graph_for_prompt
            state._ui_graph_text = serialize_graph_for_prompt(graph)
            state._ui_graph = graph
            logger.info(f"UI Graph injected: {graph.app_id}")
        else:
            state._ui_graph_text = ""
            state._ui_graph = None

        return state

    async def _capture_page(self, state: AgentState) -> AgentState:
        """Capture screenshot (and optionally DOM) based on mode."""
        if state.mode == "extension":
            if self.get_screenshot_fn:
                screenshot_b64, url, title = await self.get_screenshot_fn()
                state.page.screenshot_b64 = screenshot_b64
                state.page.url = url
                state.page.title = title
            # Also request a fresh DOM snapshot from the extension
            if self.emit_fn:
                from backend.agent.core import TaskEvent
                await self.emit_fn(TaskEvent("request_dom_snapshot", state.task_id, {}))
                await asyncio.sleep(0.3)  # Brief wait for DOM to arrive
            # Pull in latest DOM elements
            if self.get_dom_fn:
                state.page.dom_elements = self.get_dom_fn()
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
        from backend.policy.engine import SENSITIVE_URL_PATTERNS
        args = action.get("args", {})
        action_type = action.get("action_type", "")

        # Navigation — check if target URL is sensitive
        if action_type == "navigate":
            url = (args.get("url", "") or "").lower()
            if any(p in url for p in SENSITIVE_URL_PATTERNS):
                return "critical"
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
