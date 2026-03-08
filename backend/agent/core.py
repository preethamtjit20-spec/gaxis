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
from backend.agent.agents import (
    PerceiverAgent, OrchestratorAgent, NavigatorAgent,
    FormFillerAgent, DataExtractorAgent, VerifierAgent,
)
from backend.browser.runtime import BrowserRuntime
from backend.tools.executor import ToolExecutor
from backend.policy.engine import PolicyEngine
from backend.audit.store import AuditStore, create_event
from backend.memory.store import MemoryStore, EpisodicEntry

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

        # Specialist agents
        self._agents: dict[str, object] = {}
        self._graph: AgentGraph | None = None

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

        # Current task tracking
        self._current_task_id: str = ""

    async def start(self) -> None:
        """Initialize the agent — launch browser and create agent graph."""
        # Try to launch Playwright (may fail in extension-only mode)
        try:
            await self.browser.launch(headless=self._headless)
            logger.info("Playwright browser launched (API mode ready)")
        except Exception as e:
            logger.warning(f"Playwright launch failed ({e}) — extension-only mode")

        # Create specialist agents
        self._agents = {
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
            approval_fn=self._wait_for_approval,
        )

        logger.info(f"G-Axis agent started with {len(self._agents)} specialist agents")

    async def stop(self) -> None:
        try:
            await self.browser.shutdown()
        except Exception:
            pass
        logger.info("G-Axis agent stopped")

    # ─── EVENT SYSTEM ──────────────────────────────────────────

    def on_event(self, callback) -> None:
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    async def _emit(self, event: TaskEvent) -> None:
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception:
                pass

    # ─── EXTENSION INTERFACE ───────────────────────────────────

    def receive_screenshot(self, screenshot_b64: str, url: str, title: str) -> None:
        """Called when extension sends a screenshot."""
        self._ext_screenshot = screenshot_b64
        self._ext_url = url
        self._ext_title = title
        if self._ext_screenshot_event:
            self._ext_screenshot_event.set()

    def receive_dom_snapshot(self, elements: list[dict]) -> None:
        """Called when extension sends a DOM snapshot."""
        self._ext_dom_elements = elements

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

    # ─── TASK EXECUTION ────────────────────────────────────────

    async def run_task(self, instruction: str, mode: str = "api") -> AgentState:
        """Execute a web task using the multi-agent graph."""
        # Create initial state
        state = AgentState(instruction=instruction, mode=mode)
        self._current_task_id = state.task_id
        self.policy.reset()

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

            # Navigate to starting point (API mode only)
            if mode == "api":
                try:
                    page_url = self.browser.page.url
                    if page_url in ("about:blank", "chrome://newtab/"):
                        await self.browser.execute("navigate", url="https://www.google.com")
                except Exception:
                    pass

            # Inject extension DOM snapshot into initial state
            if mode == "extension" and self._ext_dom_elements:
                state.page.dom_elements = self._ext_dom_elements

            # ── Run the agent graph ──
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
        return "general"
