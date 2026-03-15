"""Execution Replay — records and replays browser action sequences.

Records every action the operator/agent takes for:
  - Debugging failed tasks (see exactly what happened)
  - Replaying successful sequences on similar tasks
  - Execution audit trail for the hackathon demo

Each replay is a timestamped sequence of actions with screenshots,
stored as JSON for easy inspection and visualization.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger("gaxis.replay")


@dataclass
class ReplayStep:
    """A single recorded action in the replay."""
    step_index: int
    timestamp: float
    action_type: str
    args: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None
    duration_ms: int = 0
    url_before: str = ""
    url_after: str = ""
    screenshot_b64: str | None = None  # Only stored if capture_screenshots=True
    dom_snapshot: list | None = None     # Trimmed DOM at time of action


@dataclass
class ReplaySession:
    """A complete recorded session for one task."""
    task_id: str
    instruction: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    status: str = "running"  # running, done, failed
    steps: list[ReplayStep] = field(default_factory=list)
    result_summary: str = ""
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        if self.end_time:
            return int((self.end_time - self.start_time) * 1000)
        return int((time.time() - self.start_time) * 1000)


class ExecutionReplay:
    """Records and manages execution replays.

    Usage:
        replay = ExecutionReplay()
        session = replay.start_session(task_id, instruction)
        replay.record_step(task_id, step_index, "click", {"x": 100, "y": 200}, success=True)
        replay.record_step(task_id, step_index, "type_text", {"text": "hello"}, success=True)
        replay.end_session(task_id, status="done", summary="Created event")
        replay.save(task_id)  # Saves to .replays/ directory
    """

    def __init__(self, replay_dir: str = ".replays", capture_screenshots: bool = True):
        self._sessions: dict[str, ReplaySession] = {}
        self._replay_dir = Path(replay_dir)
        self._capture_screenshots = capture_screenshots

    def start_session(self, task_id: str, instruction: str,
                      metadata: dict | None = None) -> ReplaySession:
        """Start recording a new session."""
        session = ReplaySession(
            task_id=task_id,
            instruction=instruction,
            metadata=metadata or {},
        )
        self._sessions[task_id] = session
        logger.info(f"Replay session started: {task_id}")
        return session

    def record_step(
        self,
        task_id: str,
        step_index: int,
        action_type: str,
        args: dict | None = None,
        success: bool = True,
        error: str | None = None,
        duration_ms: int = 0,
        url_before: str = "",
        url_after: str = "",
        screenshot_b64: str | None = None,
        dom_snapshot: list | None = None,
    ) -> ReplayStep | None:
        """Record a single action step."""
        session = self._sessions.get(task_id)
        if not session:
            return None

        step = ReplayStep(
            step_index=step_index,
            timestamp=time.time(),
            action_type=action_type,
            args=args or {},
            success=success,
            error=error,
            duration_ms=duration_ms,
            url_before=url_before,
            url_after=url_after,
            screenshot_b64=screenshot_b64 if self._capture_screenshots else None,
            dom_snapshot=dom_snapshot[:10] if dom_snapshot else None,  # Trim DOM
        )
        session.steps.append(step)
        return step

    def end_session(self, task_id: str, status: str = "done",
                    summary: str = "", error: str | None = None) -> None:
        """End a recording session."""
        session = self._sessions.get(task_id)
        if not session:
            return

        session.end_time = time.time()
        session.status = status
        session.result_summary = summary
        session.error = error
        logger.info(
            f"Replay session ended: {task_id} — {status}, "
            f"{len(session.steps)} steps, {session.duration_ms}ms"
        )

    def save(self, task_id: str) -> str | None:
        """Save a session to disk as JSON. Returns the file path."""
        session = self._sessions.get(task_id)
        if not session:
            return None

        self._replay_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{task_id}_{int(session.start_time)}.json"
        filepath = self._replay_dir / filename

        # Convert to dict, stripping large screenshots for disk storage
        data = asdict(session)
        for step in data.get("steps", []):
            step.pop("screenshot_b64", None)  # Don't save screenshots to disk
            step.pop("dom_snapshot", None)     # Don't save DOM snapshots

        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Replay saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to save replay: {e}")
            return None

    def get_session(self, task_id: str) -> ReplaySession | None:
        """Get a session by task ID."""
        return self._sessions.get(task_id)

    def get_session_summary(self, task_id: str) -> dict | None:
        """Get a compact summary of a session (for API/UI display)."""
        session = self._sessions.get(task_id)
        if not session:
            return None

        actions = [
            {
                "step": s.step_index,
                "action": s.action_type,
                "success": s.success,
                "error": s.error,
                "duration_ms": s.duration_ms,
            }
            for s in session.steps
        ]

        return {
            "task_id": session.task_id,
            "instruction": session.instruction,
            "status": session.status,
            "duration_ms": session.duration_ms,
            "total_steps": len(session.steps),
            "failed_steps": sum(1 for s in session.steps if not s.success),
            "actions": actions,
            "result": session.result_summary,
            "error": session.error,
        }

    def get_player_data(self, task_id: str) -> dict | None:
        """Get rich replay data for the interactive player UI."""
        session = self._sessions.get(task_id)
        if not session:
            return None

        steps = []
        for s in session.steps:
            step_data = {
                "step": s.step_index,
                "action": s.action_type,
                "args": s.args,
                "success": s.success,
                "error": s.error,
                "duration_ms": s.duration_ms,
                "url_before": s.url_before,
                "url_after": s.url_after,
                "timestamp": s.timestamp,
                "screenshot": s.screenshot_b64,
                "description": s.args.get("element_description", "")
                    or s.args.get("text", "")
                    or s.args.get("url", "")
                    or s.args.get("key", ""),
            }
            steps.append(step_data)

        return {
            "task_id": session.task_id,
            "instruction": session.instruction,
            "status": session.status,
            "duration_ms": session.duration_ms,
            "total_steps": len(session.steps),
            "result": session.result_summary,
            "error": session.error,
            "steps": steps,
        }

    def load_replay(self, filepath: str) -> ReplaySession | None:
        """Load a saved replay from disk."""
        try:
            with open(filepath) as f:
                data = json.load(f)
            steps = [ReplayStep(**s) for s in data.pop("steps", [])]
            session = ReplaySession(**data)
            session.steps = steps
            return session
        except Exception as e:
            logger.warning(f"Failed to load replay: {e}")
            return None

    def list_replays(self, limit: int = 20) -> list[dict]:
        """List saved replays from disk."""
        if not self._replay_dir.exists():
            return []

        replays = []
        for f in sorted(self._replay_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                with open(f) as fh:
                    data = json.load(fh)
                replays.append({
                    "file": str(f),
                    "task_id": data.get("task_id", ""),
                    "instruction": data.get("instruction", "")[:80],
                    "status": data.get("status", ""),
                    "steps": len(data.get("steps", [])),
                    "duration_ms": data.get("duration_ms", 0),
                })
            except Exception:
                continue
        return replays

    def cleanup(self, task_id: str) -> None:
        """Remove a session from memory."""
        self._sessions.pop(task_id, None)
