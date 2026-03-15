"""G-Axis Agent Core — multi-agent orchestration with Gemini tool calling.

Coordinates the agent graph:
  Perceiver → Orchestrator → Navigator/FormFiller/DataExtractor/Verifier

Supports two execution modes:
  - API mode: Playwright captures screenshots and executes actions
  - Extension mode: Chrome extension sends screenshots, backend plans, extension executes
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from google import genai

from backend.agent.state import AgentState
from backend.agent.graph import AgentGraph
from backend.agent.fast_loop import FastAgentLoop
from backend.agent.research_loop import ResearchLoop
from backend.agent.planner import ConversationPlanner
from backend.agent.agents import (
    PlannerAgent, PerceiverAgent, OrchestratorAgent, NavigatorAgent,
    FormFillerAgent, DataExtractorAgent, VerifierAgent,
)
from backend.browser.runtime import BrowserRuntime
from backend.tools.executor import ToolExecutor
from backend.policy.engine import PolicyEngine
from backend.audit.store import AuditStore, create_event
from backend.memory.store import MemoryStore, EpisodicEntry
from backend.connectors.registry import ConnectorRegistry
from backend.connectors.gmail import GmailConnector
from backend.connectors.drive import GoogleDriveConnector
from backend.connectors.sheets import GoogleSheetsConnector
from backend.connectors.docs import GoogleDocsConnector
from backend.connectors.meet import GoogleMeetConnector
from backend.connectors.general import GeneralSkillsConnector

logger = logging.getLogger("gaxis")


@dataclass
class TaskEvent:
    """Event emitted during task execution for the frontend."""
    type: str
    task_id: str
    data: dict
    timestamp: float = field(default_factory=time.time)


class GAxisAgent:
    """Main G-Axis agent — multi-agent graph with Gemini tool calling."""

    def __init__(
        self,
        api_key: str | None = None,
        firestore_project: str | None = None,
        headless: bool = True,
    ):
        # Gemini client (shared across all agents) — must be first
        self.genai_client = genai.Client(api_key=api_key)

        # Core components
        self.browser = BrowserRuntime()
        self.policy = PolicyEngine()
        self.audit = AuditStore(project_id=firestore_project)
        self.memory = MemoryStore(project_id=firestore_project, genai_client=self.genai_client)
        self._headless = headless
        self._api_key = api_key

        # Tool executor
        self.tool_executor = ToolExecutor(self.browser)

        # Safety guard — pre-execution gate for sensitive actions
        from backend.policy.safety import SafetyGuard
        self._safety_guard = SafetyGuard()
        self.tool_executor.safety_guard = self._safety_guard

        # Rollback manager — undo browser actions when things go wrong
        from backend.agent.rollback import RollbackManager
        self._rollback_manager = RollbackManager(self.tool_executor)
        self.tool_executor.rollback_manager = self._rollback_manager

        # UI Graph registry (semantic maps of known apps)
        from backend.uigraph.registry import UIGraphRegistry
        self.ui_graph_registry = UIGraphRegistry()

        # Specialist agents
        self._agents: dict[str, object] = {}
        self._graph: AgentGraph | None = None
        self._fast_loop: FastAgentLoop | None = None

        # Event system
        self._event_callbacks: list = []

        # Extension mode state
        self._ext_screenshot: str | None = None
        self._ext_screenshot_event: asyncio.Event | None = None
        self._ext_url: str = ""
        self._ext_title: str = ""
        self._ext_dom_elements: list[dict] = []

        # Approval gate
        self._approval_event: asyncio.Event | None = None
        self._approval_result: bool = False
        self._user_edits: dict | None = None  # Edits from confirmation card
        self._steering_queue: list[str] = []  # Mid-task steering messages
        self._blocker_queue: list[dict] = []  # DOM blocker events from content script

        # User input gate (graceful handover)
        self._user_input_event: asyncio.Event | None = None
        self._user_input_text: str = ""

        # Pause/resume control
        self.pause_event: bool = False

        # User preferences (persisted across tasks)
        self._user_preferences: dict = {}

        # Connector registry
        self.connectors = ConnectorRegistry()
        self.connectors.register(GmailConnector())
        self.connectors.register(GoogleDriveConnector())
        self.connectors.register(GoogleSheetsConnector())
        self.connectors.register(GoogleDocsConnector())
        self.connectors.register(GoogleMeetConnector())

        from backend.connectors.calendar import GoogleCalendarConnector
        from backend.connectors.research import ResearchConnector
        from backend.connectors.youtube import YouTubeConnector
        self.connectors.register(GoogleCalendarConnector())
        self.connectors.register(GeneralSkillsConnector())
        self.connectors.register(ResearchConnector())
        self.connectors.register(YouTubeConnector())

        # Execution Replay (records actions for timeline/debugging)
        from backend.browser.replay import ExecutionReplay
        self.replay = ExecutionReplay()

        # Conversation planner (pre-execution chat)
        self._planner = ConversationPlanner(self.genai_client)
        skills_prompt = self.connectors.get_orchestrator_prompt()
        if skills_prompt:
            self._planner.set_skills_context(skills_prompt)

        # Current task tracking
        self._current_task_id: str = ""

    async def start(self) -> None:
        """Initialize the agent — launch browser and create agent graph."""
        # Don't launch Playwright on startup — it opens a blank Chrome window.
        # Playwright is only needed for API mode tasks and will be launched on-demand.
        self._playwright_launched = False

        # Create specialist agents
        self._agents = {
            "planner": PlannerAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "perceiver": PerceiverAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "orchestrator": OrchestratorAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "navigator": NavigatorAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "form_filler": FormFillerAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "data_extractor": DataExtractorAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
            "verifier": VerifierAgent(
                client=self.genai_client,
                tool_executor=self.tool_executor,
                emit_fn=self._emit,
            ),
        }

        # Create agent graph
        self._graph = AgentGraph(
            agents=self._agents,
            policy=self.policy,
            emit_fn=self._emit,
            get_screenshot_fn=self._get_screenshot_from_extension,
            get_browser_state_fn=self._get_browser_state,
            get_dom_fn=self._get_dom_elements,
            approval_fn=self._wait_for_approval,
            user_input_fn=self._wait_for_user_input,
            connector_registry=self.connectors,
            is_paused_fn=lambda: self.pause_event,
            ui_graph_registry=self.ui_graph_registry,
            genai_client=self.genai_client,
        )

        # Fast single-agent loop (used by default — 5x faster)
        self._fast_loop = FastAgentLoop(
            client=self.genai_client,
            tool_executor=self.tool_executor,
            emit_fn=self._emit,
            get_screenshot_fn=self._get_screenshot_from_extension,
            get_browser_state_fn=self._get_browser_state,
            get_dom_fn=self._get_dom_elements,
            approval_fn=self._wait_for_approval,
            is_paused_fn=lambda: self.pause_event,
            ui_graph_registry=self.ui_graph_registry,
            get_edits_fn=self.get_and_clear_user_edits,
            get_steering_fn=self.get_steering_messages,
            get_blockers_fn=self.get_blockers,
            replay=self.replay,
            user_input_fn=self._wait_for_user_input,
            connector_registry=self.connectors,
        )

        # Research loop (Gemini + Google Search grounding — no browser for research)
        self._research_loop = ResearchLoop(
            client=self.genai_client,
            tool_executor=self.tool_executor,
            emit_fn=self._emit,
            get_screenshot_fn=self._get_screenshot_from_extension,
            get_browser_state_fn=self._get_browser_state,
            get_dom_fn=self._get_dom_elements,
            is_paused_fn=lambda: self.pause_event,
            replay=self.replay,
            ui_graph_registry=self.ui_graph_registry,
        )

        # Inject connector registry into orchestrator
        orchestrator = self._agents.get("orchestrator")
        if orchestrator and hasattr(orchestrator, "connector_registry"):
            orchestrator.connector_registry = self.connectors

        # Wire safety guard approval gate
        self._safety_guard.emit_fn = self._emit
        self._safety_guard.approval_fn = self._wait_for_approval

        skills_count = len(self.connectors.all_skills())
        logger.info(
            f"G-Axis agent started with fast loop + {len(self._agents)} "
            f"specialist agents + {skills_count} connector skills"
        )

    async def stop(self) -> None:
        try:
            await self.browser.shutdown()
        except Exception as e:
            logger.warning(f"Browser shutdown error: {e}")
        logger.info("G-Axis agent stopped")

    # ─── EVENT SYSTEM ──────────────────────────────────────────

    def on_event(self, callback) -> None:
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    async def _emit(self, event: TaskEvent) -> None:
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.warning(f"Event callback error ({event.type}): {e}")

    # ─── EXTENSION INTERFACE ───────────────────────────────────

    def receive_screenshot(self, screenshot_b64: str, url: str, title: str) -> None:
        """Called when extension sends a screenshot."""
        logger.info(f"Received screenshot from extension: url={url[:60] if url else 'empty'}, b64_len={len(screenshot_b64) if screenshot_b64 else 0}")
        self._ext_screenshot = screenshot_b64
        self._ext_url = url
        self._ext_title = title
        # Keep safety guard aware of current page
        self.tool_executor._current_url = url
        if self._ext_screenshot_event:
            self._ext_screenshot_event.set()

    def receive_dom_snapshot(self, elements: list[dict]) -> None:
        """Called when extension sends a DOM snapshot."""
        self._ext_dom_elements = elements

    def _get_dom_elements(self) -> list[dict]:
        """Return latest DOM snapshot from extension."""
        return self._ext_dom_elements

    async def _get_screenshot_from_extension(self, timeout: float = 15.0) -> tuple[str, str, str]:
        """Request and wait for screenshot from Chrome extension."""
        self._ext_screenshot_event = asyncio.Event()
        self._ext_screenshot = None

        # Request screenshot from extension
        await self._emit(TaskEvent("request_screenshot", self._current_task_id, {}))

        try:
            await asyncio.wait_for(self._ext_screenshot_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError("Timed out waiting for screenshot from extension")

        return self._ext_screenshot, self._ext_url, self._ext_title

    async def _get_browser_state(self):
        """Get browser state from Playwright (API mode)."""
        return await self.browser.get_state()

    # ─── APPROVAL GATE ─────────────────────────────────────────

    async def _wait_for_approval(self, timeout: float = 120.0) -> bool:
        self._approval_event = asyncio.Event()
        self._approval_result = False
        try:
            await asyncio.wait_for(self._approval_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return self._approval_result

    def respond_approval(self, approved: bool) -> None:
        self._approval_result = approved
        if self._approval_event:
            self._approval_event.set()

    def receive_user_edits(self, edits: dict) -> None:
        """Receive field edits from the confirmation card."""
        self._user_edits = edits
        logger.info(f"User edits received: {edits}")

    def get_and_clear_user_edits(self) -> dict | None:
        """Get user edits and clear them."""
        edits = self._user_edits
        self._user_edits = None
        return edits

    def receive_steering(self, text: str) -> None:
        """Queue a mid-task steering message from the user."""
        self._steering_queue.append(text)
        logger.info(f"Steering queued: {text[:80]}")

    def get_steering_messages(self) -> list[str]:
        """Drain and return all queued steering messages."""
        msgs = self._steering_queue[:]
        self._steering_queue.clear()
        return msgs

    def receive_blocker(self, blocker_data: dict) -> None:
        """Queue a DOM blocker event from the content script."""
        self._blocker_queue.append(blocker_data)
        logger.info(f"Blocker queued: {blocker_data.get('element', '?')}")

    def get_blockers(self) -> list[dict]:
        """Drain and return all queued blocker events."""
        blockers = self._blocker_queue[:]
        self._blocker_queue.clear()
        return blockers

    # ─── USER INPUT GATE (GRACEFUL HANDOVER) ──────────────────

    async def _wait_for_user_input(self, timeout: float = 300.0) -> str:
        """Wait for user to provide input when agent is stuck."""
        self._user_input_event = asyncio.Event()
        self._user_input_text = ""
        try:
            await asyncio.wait_for(self._user_input_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return ""
        return self._user_input_text

    def respond_user_input(self, text: str) -> None:
        """Called when user provides input via side panel."""
        self._user_input_text = text
        if self._user_input_event:
            self._user_input_event.set()

    # ─── CONVERSATION PLANNER ─────────────────────────────────

    async def plan_chat(self, user_message: str) -> dict:
        """Chat with the planner before execution. Returns planner response.

        The planner collects slots through conversation. When ready_to_execute=true,
        the plan contains all collected slots and a refined_instruction.
        These are stored so run_task() can pass them to the state machine,
        avoiding redundant LLM extraction.
        """
        result = await self._planner.chat(
            user_message=user_message,
            user_preferences=self._user_preferences,
            current_url=self._ext_url,
        )

        # Learn any new preferences
        if result.get("preferences_learned"):
            self._user_preferences.update(result["preferences_learned"])
            logger.info(f"Learned preferences: {result['preferences_learned']}")

        # If ready to execute, store collected slots for the state machine
        if result.get("ready_to_execute") and result.get("plan"):
            plan = result["plan"]
            result["refined_instruction"] = plan.get(
                "refined_instruction",
                plan.get("action", user_message),
            )
            # Store planner's collected slots — state machine will use these
            # instead of re-extracting from instruction
            self._planner_slots = plan.get("slots", {})
            self._planner_intent = result.get("intent", "")
            logger.info(f"Planner slots stored: {self._planner_slots}")

        return result

    def get_user_preferences(self) -> dict:
        return self._user_preferences

    def set_user_preferences(self, prefs: dict) -> None:
        self._user_preferences.update(prefs)

    # ─── TASK EXECUTION ────────────────────────────────────────

    async def run_task(self, instruction: str, mode: str = "api") -> AgentState:
        """Execute a web task using the multi-agent graph."""
        # Create initial state
        state = AgentState(mode=mode)
        state.instruction = instruction
        self._current_task_id = state.task_id
        self.policy.reset()
        self._safety_guard.reset()
        self._rollback_manager.reset()
        # Reset planner for next conversation (slots persist within task via state)
        self._planner.reset()

        # Determine domain for memory
        if mode == "api":
            try:
                current_url = self.browser.page.url
            except RuntimeError:
                current_url = ""
        else:
            current_url = self._ext_url
        domain = self._extract_domain(current_url)

        # Log task start
        await self.audit.append(create_event(
            state.task_id, "task_started",
            {"instruction": instruction, "mode": mode, "agents": list(self._agents.keys())},
        ))
        await self._emit(TaskEvent("task_started", state.task_id, {
            "instruction": instruction, "mode": mode,
        }))

        try:
            # Load memory context
            memory_context = await self.memory.build_context(domain, instruction)

            # Add retrieval-based similar experiences
            try:
                similar = await self.memory.retrieve_similar(instruction, limit=3)
                memory_context["similar_experiences"] = similar
            except Exception as e:
                logger.debug(f"Retrieval memory unavailable: {e}")
                memory_context["similar_experiences"] = []

            state.memory_context = memory_context

            if memory_context.get("has_visited_before"):
                logger.info(f"Memory: visited {domain} before, {len(memory_context.get('past_episodes', []))} episodes")
                await self._emit(TaskEvent("memory_loaded", state.task_id, {
                    "domain": domain,
                    "episodes": len(memory_context.get("past_episodes", [])),
                    "patterns": len(memory_context.get("known_patterns", [])),
                    "similar": len(memory_context.get("similar_experiences", [])),
                }))

            # Navigate to starting point (API mode only — launch Playwright on demand)
            if mode == "api":
                if not self._playwright_launched:
                    try:
                        await self.browser.launch(headless=self._headless)
                        self._playwright_launched = True
                        logger.info("Playwright browser launched on demand (API mode)")
                    except Exception as e:
                        logger.error(f"Playwright launch failed: {e}")
                try:
                    page_url = self.browser.page.url
                    if page_url in ("about:blank", "chrome://newtab/"):
                        await self.browser.execute("navigate", url="https://www.google.com")
                except Exception as e:
                    logger.debug(f"Initial page navigation skipped: {e}")

            # Inject extension DOM snapshot into initial state
            if mode == "extension" and self._ext_dom_elements:
                state.page.dom_elements = self._ext_dom_elements

            # Pass planner-collected slots to state (avoids re-extraction)
            if hasattr(self, '_planner_slots') and self._planner_slots:
                state.planner_slots = self._planner_slots
                state.planner_intent = getattr(self, '_planner_intent', '')
                logger.info(f"Passing planner slots to executor: {self._planner_slots}")
                # Clear after use
                self._planner_slots = {}
                self._planner_intent = ''

            # ── Choose execution path ──
            # 1. Research → ResearchLoop (Gemini + Google Search, no browser)
            # 2. Known apps (Calendar, Gmail, Docs, Sheets) → FastAgentLoop
            #    (has UI Graph, LLM extraction, state machine, confirmation cards)
            # 3. Unknown pages → AgentGraph (specialist agents: Perceiver,
            #    Orchestrator, Navigator, FormFiller, DataExtractor, Verifier)
            if ResearchLoop.is_research_task(instruction):
                logger.info(f"Routing to ResearchLoop for: {instruction[:60]}")
                state = await self._research_loop.run(state)
            elif self._fast_loop and self._is_known_app(self._ext_url):
                # Known app — FastAgentLoop has specialized UI Graph + state machine
                logger.info(f"Routing to FastAgentLoop (known app) for: {instruction[:60]}")
                state = await self._fast_loop.run(state)
            elif self._fast_loop:
                # Unknown page — still use FastAgentLoop (single agent is more reliable)
                # but with specialist agent events for UI visibility
                logger.info(f"Routing to FastAgentLoop for: {instruction[:60]}")
                state = await self._fast_loop.run(state)
            else:
                # Fallback: multi-agent graph
                logger.info(f"Routing to AgentGraph for: {instruction[:60]}")
                if hasattr(self, 'cancel_event') and self.cancel_event:
                    self._graph.cancel_event = self.cancel_event
                state = await self._graph.run(state)

        except Exception as e:
            state.status = "failed"
            state.error = str(e)
            logger.error(f"Task {state.task_id} failed: {e}", exc_info=True)

        # ── Post-task: audit + memory ──
        if state.status == "done":
            await self.audit.append(create_event(
                state.task_id, "task_completed",
                {"summary": state.result_summary, "total_steps": state.step_index},
            ))
            await self._emit(TaskEvent("task_completed", state.task_id, {
                "summary": state.result_summary,
                "total_steps": state.step_index,
                "extracted_data": state.extracted_data,
            }))
        else:
            await self.audit.append(create_event(
                state.task_id, "task_failed", {"error": state.error},
            ))
            await self._emit(TaskEvent("task_failed", state.task_id, {
                "error": state.error,
            }))

        # Save episodic memory
        obstacles = [
            a.get("error", "") for a in state.action_history
            if not a.get("success") and a.get("error")
        ]
        await self.memory.save_episode_with_embedding(EpisodicEntry(
            domain=domain,
            task_type=self._infer_task_type(instruction),
            instruction=instruction,
            success=state.status == "done",
            steps_taken=state.step_index,
            duration_ms=state.elapsed_ms,
            obstacles=obstacles,
        ))

        logger.info(
            f"Task {state.task_id} finished: status={state.status}, "
            f"steps={state.step_index}, duration={state.elapsed_ms}ms"
        )

        return state

    # ─── HELPERS ────────────────────────────────────────────────

    def _is_known_app(self, url: str) -> bool:
        """Check if the current URL is a known app with UI Graph support."""
        if not url:
            return False
        known_patterns = [
            "calendar.google.com",
            "mail.google.com",
            "docs.google.com",
            "sheets.google.com",
            "meet.google.com",
            "youtube.com",
        ]
        return any(p in url for p in known_patterns)

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).hostname or "unknown"
        except Exception:
            return "unknown"

    def _infer_task_type(self, instruction: str) -> str:
        instruction_lower = instruction.lower()
        if any(w in instruction_lower for w in ["search", "find", "look for", "google"]):
            return "search"
        if any(w in instruction_lower for w in ["book", "reserve", "buy", "purchase"]):
            return "transaction"
        if any(w in instruction_lower for w in ["login", "sign in", "log in"]):
            return "authentication"
        if any(w in instruction_lower for w in ["fill", "form", "submit"]):
            return "form_fill"
        if any(w in instruction_lower for w in ["navigate", "go to", "open"]):
            return "navigation"
        if any(w in instruction_lower for w in ["extract", "get", "read", "scrape"]):
            return "extraction"
        if any(w in instruction_lower for w in ["play", "watch", "listen", "youtube", "video", "music", "song"]):
            return "media"
        return "general"
