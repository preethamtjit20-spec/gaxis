"""G-Axis Memory System.

Three-tier memory for context-aware agent behavior:

1. Working Memory  — current task state (in-process, dies with task)
2. Episodic Memory — per-site task history (what worked before)
3. Semantic Memory — cross-site learned patterns (cookie banners, login flows, etc.)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class EpisodicEntry:
    """Memory of a past task on a specific domain."""
    domain: str
    task_type: str
    instruction: str
    success: bool
    steps_taken: int
    duration_ms: int
    obstacles: list[str] = field(default_factory=list)
    successful_actions: list[dict] = field(default_factory=list)
    user_preferences: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SemanticPattern:
    """A learned pattern that applies across websites."""
    pattern_id: str
    name: str
    description: str
    action_template: dict | None = None
    trigger_conditions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    seen_count: int = 0
    last_updated: float = field(default_factory=time.time)


# Built-in patterns the agent knows from day 1
BUILTIN_PATTERNS: list[dict] = [
    {
        "pattern_id": "cookie_consent",
        "name": "Cookie Consent Banner",
        "description": "Most sites show a cookie consent popup. Look for 'Accept', 'Accept All', 'OK', or 'Got it' button.",
        "action_template": {"type": "click", "target_hint": "text contains 'Accept' or 'Accept All' or 'OK'"},
        "trigger_conditions": ["page_load", "overlay_detected"],
        "confidence": 0.90,
        "seen_count": 100,
    },
    {
        "pattern_id": "search_input",
        "name": "Search Input Pattern",
        "description": "Search boxes are typically input[type=search], input with magnifying glass icon, or elements with placeholder containing 'Search'.",
        "trigger_conditions": ["looking_for_search"],
        "confidence": 0.85,
        "seen_count": 100,
    },
    {
        "pattern_id": "login_flow",
        "name": "Login Flow",
        "description": "Login typically: email/username field -> next/continue button -> password field -> submit. Always HIGH risk.",
        "trigger_conditions": ["task_requires_login"],
        "confidence": 0.80,
        "seen_count": 50,
    },
    {
        "pattern_id": "pagination",
        "name": "Pagination Pattern",
        "description": "Results often span multiple pages. Look for 'Next', '>', page numbers at the bottom.",
        "trigger_conditions": ["need_more_results", "scroll_exhausted"],
        "confidence": 0.85,
        "seen_count": 80,
    },
    {
        "pattern_id": "popup_close",
        "name": "Popup/Modal Close",
        "description": "Popups usually have an X button in the top-right corner, or a 'Close' button.",
        "action_template": {"type": "click", "target_hint": "close button, X icon, or 'Close' text"},
        "trigger_conditions": ["modal_detected", "overlay_blocking"],
        "confidence": 0.88,
        "seen_count": 90,
    },
]


class MemoryStore:
    """Three-tier memory system with Firestore backend and local fallback."""

    def __init__(self, project_id: str | None = None):
        self._firestore = None
        self._local_dir = Path("memory-store")

        if project_id or os.environ.get("GOOGLE_CLOUD_PROJECT"):
            try:
                from google.cloud import firestore
                self._firestore = firestore.AsyncClient(
                    project=project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
                )
            except Exception:
                pass

    # ─── EPISODIC MEMORY ──────────────────────────────────────

    async def save_episode(self, entry: EpisodicEntry) -> None:
        data = asdict(entry)
        if self._firestore:
            try:
                doc_id = f"{entry.domain}_{int(entry.timestamp)}"
                await self._firestore.collection("gaxis_episodic").document(doc_id).set(data)
                return
            except Exception:
                pass
        self._save_local("episodic", f"{entry.domain}.jsonl", data)

    async def recall_episodes(self, domain: str, limit: int = 5) -> list[EpisodicEntry]:
        if self._firestore:
            try:
                query = (
                    self._firestore.collection("gaxis_episodic")
                    .where("domain", "==", domain)
                    .order_by("timestamp", direction="DESCENDING")
                    .limit(limit)
                )
                entries = []
                async for doc in query.stream():
                    entries.append(EpisodicEntry(**doc.to_dict()))
                return entries
            except Exception:
                pass
        return self._load_local_episodes(domain, limit)

    # ─── SEMANTIC MEMORY ──────────────────────────────────────

    async def get_patterns(self) -> list[SemanticPattern]:
        """Get all known patterns (built-in + learned)."""
        patterns = [SemanticPattern(**p) for p in BUILTIN_PATTERNS]

        # Load learned patterns
        if self._firestore:
            try:
                docs = self._firestore.collection("gaxis_semantic").stream()
                async for doc in docs:
                    data = doc.to_dict()
                    patterns.append(SemanticPattern(**data))
            except Exception:
                pass
        else:
            learned = self._load_local_patterns()
            patterns.extend(learned)

        return patterns

    async def learn_pattern(self, pattern: SemanticPattern) -> None:
        data = asdict(pattern)
        if self._firestore:
            try:
                await self._firestore.collection("gaxis_semantic").document(pattern.pattern_id).set(data)
                return
            except Exception:
                pass
        self._save_local("semantic", "patterns.jsonl", data)

    async def update_pattern_confidence(self, pattern_id: str, success: bool) -> None:
        """Update a pattern's confidence based on whether it worked."""
        patterns = await self.get_patterns()
        for p in patterns:
            if p.pattern_id == pattern_id:
                p.seen_count += 1
                # Simple exponential moving average
                alpha = 0.1
                outcome = 1.0 if success else 0.0
                p.confidence = p.confidence * (1 - alpha) + outcome * alpha
                p.last_updated = time.time()
                await self.learn_pattern(p)
                break

    # ─── CONTEXT BUILDER ──────────────────────────────────────

    async def build_context(self, domain: str, task_instruction: str) -> dict:
        """Build memory context to inject into the agent's planning prompt."""
        episodes = await self.recall_episodes(domain)
        patterns = await self.get_patterns()

        context = {
            "has_visited_before": len(episodes) > 0,
            "past_episodes": [],
            "known_patterns": [],
            "user_preferences": {},
        }

        # Relevant past episodes
        for ep in episodes[:3]:
            context["past_episodes"].append({
                "instruction": ep.instruction,
                "success": ep.success,
                "steps": ep.steps_taken,
                "obstacles": ep.obstacles,
            })

        # Merge user preferences from past episodes
        for ep in episodes:
            context["user_preferences"].update(ep.user_preferences)

        # Relevant patterns
        for p in patterns:
            if p.confidence >= 0.5:
                context["known_patterns"].append({
                    "name": p.name,
                    "description": p.description,
                    "confidence": p.confidence,
                })

        return context

    # ─── LOCAL FALLBACK ───────────────────────────────────────

    def _save_local(self, category: str, filename: str, data: dict) -> None:
        dir_path = self._local_dir / category
        dir_path.mkdir(parents=True, exist_ok=True)
        with open(dir_path / filename, "a") as f:
            f.write(json.dumps(data) + "\n")

    def _load_local_episodes(self, domain: str, limit: int) -> list[EpisodicEntry]:
        file_path = self._local_dir / "episodic" / f"{domain}.jsonl"
        if not file_path.exists():
            return []
        entries = []
        for line in file_path.read_text().strip().split("\n"):
            if line:
                entries.append(EpisodicEntry(**json.loads(line)))
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def _load_local_patterns(self) -> list[SemanticPattern]:
        file_path = self._local_dir / "semantic" / "patterns.jsonl"
        if not file_path.exists():
            return []
        patterns = []
        seen_ids = set()
        for line in reversed(file_path.read_text().strip().split("\n")):
            if line:
                data = json.loads(line)
                pid = data.get("pattern_id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    patterns.append(SemanticPattern(**data))
        return patterns
