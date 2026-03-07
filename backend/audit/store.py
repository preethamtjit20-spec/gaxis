"""Audit store for G-Axis.

Logs all agent events to Firestore for compliance, replay, and debugging.
Falls back to local JSON files if Firestore is unavailable.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal


AuditEventType = Literal[
    "task_started", "task_completed", "task_failed",
    "screenshot_captured", "perception_completed",
    "action_planned", "action_executing", "action_succeeded", "action_failed",
    "approval_requested", "approval_granted", "approval_denied",
    "policy_evaluated",
]


@dataclass
class AuditEvent:
    id: str
    timestamp: float
    task_id: str
    event_type: AuditEventType
    payload: dict
    step_index: int | None = None
    screenshot_ref: str | None = None


class AuditStore:
    """Audit event store — Firestore with local file fallback."""

    def __init__(self, project_id: str | None = None, collection: str = "gaxis-audit"):
        self._firestore = None
        self._collection_name = collection
        self._local_dir = Path("audit-logs")

        # Try to initialize Firestore
        if project_id or os.environ.get("GOOGLE_CLOUD_PROJECT"):
            try:
                from google.cloud import firestore
                self._firestore = firestore.AsyncClient(
                    project=project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
                )
            except Exception:
                pass

    async def append(self, event: AuditEvent) -> None:
        event_dict = asdict(event)

        # Try Firestore first
        if self._firestore:
            try:
                collection = self._firestore.collection(self._collection_name)
                doc_ref = collection.document(event.id)
                await doc_ref.set(event_dict)
                return
            except Exception:
                pass

        # Fallback to local file
        self._local_dir.mkdir(exist_ok=True)
        file_path = self._local_dir / f"{event.task_id}.jsonl"
        line = json.dumps(event_dict) + "\n"
        with open(file_path, "a") as f:
            f.write(line)

    async def get_task_events(self, task_id: str) -> list[AuditEvent]:
        # Try Firestore
        if self._firestore:
            try:
                collection = self._firestore.collection(self._collection_name)
                query = collection.where("task_id", "==", task_id).order_by("timestamp")
                docs = query.stream()
                events = []
                async for doc in docs:
                    data = doc.to_dict()
                    events.append(AuditEvent(**data))
                return events
            except Exception:
                pass

        # Fallback to local
        file_path = self._local_dir / f"{task_id}.jsonl"
        if not file_path.exists():
            return []
        events = []
        for line in file_path.read_text().strip().split("\n"):
            if line:
                data = json.loads(line)
                events.append(AuditEvent(**data))
        return events


def create_event(
    task_id: str,
    event_type: AuditEventType,
    payload: dict,
    step_index: int | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=f"evt_{uuid.uuid4().hex[:12]}",
        timestamp=time.time(),
        task_id=task_id,
        event_type=event_type,
        payload=payload,
        step_index=step_index,
    )
