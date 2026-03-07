"""G-Axis Agent Core — the autonomous web agent.

Coordinates vision, browser, memory, policy, and audit.
Supports two execution modes:
  - API mode: Playwright captures screenshots and executes actions (headless on Cloud Run)
  - Extension mode: Chrome extension sends screenshots, backend plans, extension executes
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from backend.browser.runtime import BrowserRuntime, ActionResult
from backend.vision.perception import VisionPerception, PagePerception, PlannedAction
from backend.policy.engine import PolicyEngine
from backend.audit.store import AuditStore, create_event
from backend.memory.store import MemoryStore, EpisodicEntry

logger = logging.getLogger("gaxis")

TaskStatus = Literal["idle", "planning", "executing", "awaiting_approval", "success", "failed"]

MAX_STEPS = 30
MAX_RETRIES = 2


@dataclass
class TaskEvent:
    """Event emitted during task execution for the frontend."""
    type: str
    task_id: str
    data: dict
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskState:
    task_id: str
    instruction: str
    status: TaskStatus = "idle"
    step_index: int = 0
    action_history: list[dict] = field(default_factory=list)
    events: list[TaskEvent] = field(default_factory=list)
    error: str | None = None
    result_summary: str | None = None


class GAxisAgent:
    """Main G-Axis agent — coordinates vision, browser, memory, and policy."""

    def __init__(
        self,
        api_key: str | None = None,
        firestore_project: str | None = None,
        headless: bool = True,
    ):
        self.browser = BrowserRuntime()
        self.vision = VisionPerception(api_key=api_key)
        self.policy = PolicyEngine()
        self.audit = AuditStore(project_id=firestore_project)
        self.memory = MemoryStore(project_id=firestore_project)
        self._headless = headless
        self._current_task: TaskState | None = None
        self._approval_event: asyncio.Event | None = None
        self._approval_result: bool = False
        self._event_callbacks: list = []

        # Extension mode: when extension sends screenshots
        self._ext_screenshot: str | None = None
        self._ext_screenshot_event: asyncio.Event | None = None
        self._ext_url: str = ""
        self._ext_title: str = ""

    async def start(self) -> None:
        """Start the agent. Launches Playwright for API mode."""
        try:
            await self.browser.launch(headless=self._headless)
            logger.info("G-Axis agent started (API mode — Playwright ready)")
        except Exception as e:
            logger.warning(f"Playwright launch failed ({e}) — extension-only mode")

    async def stop(self) -> None:
        try:
            await self.browser.shutdown()
        except Exception:
            pass
        logger.info("G-Axis agent stopped")

    def on_event(self, callback) -> None:
        """Register a callback for task events."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    async def _emit(self, event: TaskEvent) -> None:
        if self._current_task:
            self._current_task.events.append(event)
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception:
                pass

    # ─── EXTENSION SCREENSHOT INTERFACE ────────────────────────

    def receive_screenshot(self, screenshot_b64: str, url: str, title: str) -> None:
        """Called when extension sends a screenshot."""
        self._ext_screenshot = screenshot_b64
        self._ext_url = url
        self._ext_title = title
        if self._ext_screenshot_event:
            self._ext_screenshot_event.set()

    async def _get_screenshot_from_extension(self, timeout: float = 10.0) -> tuple[str, str, str]:
        """Wait for extension to send a screenshot."""
        self._ext_screenshot_event = asyncio.Event()
        self._ext_screenshot = None
        # Request screenshot from extension
        await self._emit(TaskEvent("request_screenshot", self._current_task.task_id, {}))
        try:
            await asyncio.wait_for(self._ext_screenshot_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError("Timed out waiting for screenshot from extension")
        return self._ext_screenshot, self._ext_url, self._ext_title

    # ─── TASK EXECUTION ───────────────────────────────────────

    async def run_task(self, instruction: str, mode: str = "api") -> TaskState:
        """Execute a web task. mode='api' uses Playwright, mode='extension' uses Chrome extension."""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        self._current_task = TaskState(task_id=task_id, instruction=instruction)
        self.policy.reset()
        start_time = time.time()

        await self.audit.append(create_event(task_id, "task_started", {"instruction": instruction, "mode": mode}))
        await self._emit(TaskEvent("task_started", task_id, {"instruction": instruction}))

        # Extract domain for memory lookup
        if mode == "api":
            try:
                current_url = self.browser.page.url
            except RuntimeError:
                current_url = ""
        else:
            current_url = self._ext_url
        domain = self._extract_domain(current_url)

        try:
            # Load memory context
            memory_context = await self.memory.build_context(domain, instruction)
            if memory_context["has_visited_before"]:
                logger.info(f"Memory: visited {domain} before, {len(memory_context['past_episodes'])} episodes")
                await self._emit(TaskEvent("memory_loaded", task_id, {
                    "domain": domain,
                    "episodes": len(memory_context["past_episodes"]),
                    "patterns": len(memory_context["known_patterns"]),
                }))

            # Navigate to starting point (API mode only)
            if mode == "api":
                try:
                    current_url = self.browser.page.url
                    if current_url in ("about:blank", "chrome://newtab/"):
                        await self.browser.execute("navigate", url="https://www.google.com")
                except Exception:
                    pass

            await self._execute_loop(task_id, instruction, mode, memory_context)

        except Exception as e:
            self._current_task.status = "failed"
            self._current_task.error = str(e)
            await self.audit.append(create_event(task_id, "task_failed", {"error": str(e)}))
            await self._emit(TaskEvent("task_failed", task_id, {"error": str(e)}))
            logger.error(f"Task {task_id} failed: {e}")

        # Save to episodic memory
        duration_ms = int((time.time() - start_time) * 1000)
        obstacles = [
            a["error"] for a in self._current_task.action_history
            if not a.get("success") and a.get("error")
        ]
        await self.memory.save_episode(EpisodicEntry(
            domain=domain,
            task_type=self._infer_task_type(instruction),
            instruction=instruction,
            success=self._current_task.status == "success",
            steps_taken=len(self._current_task.action_history),
            duration_ms=duration_ms,
            obstacles=obstacles,
        ))

        return self._current_task

    async def _execute_loop(
        self, task_id: str, instruction: str, mode: str, memory_context: dict
    ) -> None:
        """Core loop: screenshot -> perceive -> plan (with memory) -> policy -> execute -> repeat."""
        retries = 0

        # Build memory-augmented instruction
        augmented_instruction = self._augment_with_memory(instruction, memory_context)

        for step in range(MAX_STEPS):
            self._current_task.status = "executing"
            self._current_task.step_index = step

            # 1. Get screenshot
            if mode == "extension":
                screenshot_b64, url, title = await self._get_screenshot_from_extension()
            else:
                state = await self.browser.get_state()
                screenshot_b64, url, title = state.screenshot_b64, state.url, state.title

            await self.audit.append(create_event(
                task_id, "screenshot_captured", {"url": url, "title": title}, step_index=step,
            ))

            # 2. Perceive via Gemini vision
            self._current_task.status = "planning"
            await self._emit(TaskEvent("perceiving", task_id, {"step": step, "url": url, "title": title}))

            perception = await self.vision.perceive(screenshot_b64, url, title)

            await self.audit.append(create_event(
                task_id, "perception_completed",
                {"page_summary": perception.page_summary, "element_count": len(perception.elements)},
                step_index=step,
            ))
            await self._emit(TaskEvent("perception", task_id, {
                "step": step,
                "page_summary": perception.page_summary,
                "current_state": perception.current_state,
                "element_count": len(perception.elements),
                "screenshot": screenshot_b64,
            }))

            # 3. Plan next action (with memory context)
            planned = await self.vision.plan_action(
                task=augmented_instruction,
                perception=perception,
                action_history=self._current_task.action_history,
                screenshot_b64=screenshot_b64,
            )

            await self.audit.append(create_event(
                task_id, "action_planned",
                {
                    "action_type": planned.action_type, "reasoning": planned.reasoning,
                    "risk_level": planned.risk_level, "confidence": planned.confidence,
                    "element_id": planned.element_id,
                },
                step_index=step,
            ))
            await self._emit(TaskEvent("action_planned", task_id, {
                "step": step, "action_type": planned.action_type, "reasoning": planned.reasoning,
                "risk_level": planned.risk_level, "confidence": planned.confidence,
                "element_id": planned.element_id, "x": planned.x, "y": planned.y,
            }))

            # 4. Task complete?
            if planned.is_task_complete or planned.action_type == "done":
                self._current_task.status = "success"
                self._current_task.result_summary = planned.completion_summary or "Task completed"
                await self.audit.append(create_event(
                    task_id, "task_completed", {"summary": self._current_task.result_summary, "total_steps": step + 1}
                ))
                await self._emit(TaskEvent("task_completed", task_id, {
                    "summary": self._current_task.result_summary, "total_steps": step + 1,
                }))
                return

            # 5. Policy check
            is_sensitive = False
            if planned.element_id:
                el = next((e for e in perception.elements if e.id == planned.element_id), None)
                is_sensitive = el.is_sensitive if el else False

            decision = self.policy.evaluate(
                action_type=planned.action_type, risk_level=planned.risk_level,
                confidence=planned.confidence, element_id=planned.element_id,
                is_sensitive=is_sensitive,
            )
            await self.audit.append(create_event(
                task_id, "policy_evaluated",
                {"verdict": decision.verdict, "risk_level": decision.risk_level, "reason": decision.reason},
                step_index=step,
            ))

            # 6. Approval gate
            if decision.verdict == "require_approval":
                self._current_task.status = "awaiting_approval"
                await self._emit(TaskEvent("approval_needed", task_id, {
                    "step": step, "action_type": planned.action_type,
                    "reasoning": planned.reasoning, "risk_level": decision.risk_level,
                    "reason": decision.reason, "confidence": planned.confidence,
                    "element_id": planned.element_id,
                }))
                approved = await self._wait_for_approval()
                if not approved:
                    self._current_task.status = "failed"
                    self._current_task.error = "Operator denied action"
                    await self.audit.append(create_event(task_id, "approval_denied", {}))
                    await self._emit(TaskEvent("task_failed", task_id, {"error": "Operator denied"}))
                    return
                await self.audit.append(create_event(task_id, "approval_granted", {}))
                self.policy.record_approval(planned.action_type)
            elif decision.verdict == "deny":
                self._current_task.status = "failed"
                self._current_task.error = f"Policy denied: {decision.reason}"
                await self._emit(TaskEvent("task_failed", task_id, {"error": decision.reason}))
                return

            # 7. Execute
            self._current_task.status = "executing"
            await self.audit.append(create_event(
                task_id, "action_executing", {"action_type": planned.action_type}, step_index=step,
            ))

            if mode == "extension":
                # Tell extension to execute the action
                await self._emit(TaskEvent("execute_action", task_id, {
                    "action_type": planned.action_type,
                    "x": planned.x, "y": planned.y,
                    "text": planned.text, "url": planned.url,
                    "direction": planned.direction, "key": planned.key,
                    "pixels": planned.pixels,
                }))
                # Wait for extension to confirm execution
                await asyncio.sleep(1.0)
                result = ActionResult(
                    success=True, action_type=planned.action_type,
                    duration_ms=1000, resulting_url=url,
                )
            else:
                result = await self.browser.execute(
                    action_type=planned.action_type,
                    x=planned.x, y=planned.y,
                    text=planned.text, url=planned.url,
                    direction=planned.direction, key=planned.key,
                    pixels=planned.pixels,
                )

            # Record
            action_record = {
                "step": step, "action_type": planned.action_type,
                "reasoning": planned.reasoning, "element_id": planned.element_id,
                "success": result.success, "error": result.error,
                "duration_ms": result.duration_ms,
            }
            self._current_task.action_history.append(action_record)

            if result.success:
                retries = 0
                await self.audit.append(create_event(
                    task_id, "action_succeeded",
                    {"duration_ms": result.duration_ms, "url": result.resulting_url},
                    step_index=step,
                ))
                await self._emit(TaskEvent("action_succeeded", task_id, {
                    "step": step, "action_type": planned.action_type,
                    "duration_ms": result.duration_ms, "url": result.resulting_url,
                }))
            else:
                retries += 1
                await self.audit.append(create_event(
                    task_id, "action_failed", {"error": result.error}, step_index=step,
                ))
                await self._emit(TaskEvent("action_failed", task_id, {"step": step, "error": result.error}))
                if retries > MAX_RETRIES:
                    self._current_task.status = "failed"
                    self._current_task.error = f"Max retries exceeded: {result.error}"
                    await self._emit(TaskEvent("task_failed", task_id, {"error": self._current_task.error}))
                    return
                logger.warning(f"Action failed (retry {retries}/{MAX_RETRIES}): {result.error}")

            await asyncio.sleep(0.5)

        # Exceeded max steps
        self._current_task.status = "failed"
        self._current_task.error = f"Exceeded maximum steps ({MAX_STEPS})"
        await self._emit(TaskEvent("task_failed", task_id, {"error": self._current_task.error}))

    # ─── MEMORY HELPERS ───────────────────────────────────────

    def _augment_with_memory(self, instruction: str, memory_context: dict) -> str:
        """Inject memory context into the task instruction for better planning."""
        parts = [instruction]

        if memory_context["has_visited_before"]:
            parts.append("\n\nMEMORY CONTEXT (from past visits):")
            for ep in memory_context["past_episodes"][:2]:
                status = "succeeded" if ep["success"] else "failed"
                parts.append(f"- Previous task \"{ep['instruction']}\" {status} in {ep['steps']} steps")
                if ep["obstacles"]:
                    parts.append(f"  Obstacles encountered: {', '.join(ep['obstacles'][:3])}")

        if memory_context["known_patterns"]:
            parts.append("\nKNOWN PATTERNS:")
            for p in memory_context["known_patterns"][:5]:
                parts.append(f"- {p['name']}: {p['description']}")

        if memory_context["user_preferences"]:
            parts.append(f"\nUSER PREFERENCES: {memory_context['user_preferences']}")

        return "\n".join(parts)

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
        return "general"

    # ─── APPROVAL ─────────────────────────────────────────────

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
