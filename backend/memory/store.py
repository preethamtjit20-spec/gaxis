"""G-Axis Memory System.

Four-tier memory for context-aware agent behavior:

1. Working Memory   — current task state (in-process, dies with task)
2. Episodic Memory  — per-site task history (what worked before)
3. Semantic Memory  — cross-site learned patterns (cookie banners, login flows, etc.)
4. Retrieval Memory — embedding-based similarity search across all experiences
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gaxis.memory")


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
    """Four-tier memory system with Firestore backend and local fallback.

    Includes embedding-based retrieval for finding similar past experiences
    across all domains using Gemini's text-embedding model.
    """

    def __init__(self, project_id: str | None = None, genai_client=None):
        self._firestore = None
        self._local_dir = Path("memory-store")
        self._genai_client = genai_client  # For embedding generation
        self._embedding_cache: dict[str, list[float]] = {}  # text -> embedding

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

    # ─── RETRIEVAL MEMORY (EMBEDDING-BASED) ──────────────────

    async def _get_embedding(self, text: str) -> list[float] | None:
        """Generate embedding for text using Gemini's embedding model."""
        if not self._genai_client:
            return None

        # Check cache
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        try:
            response = await self._genai_client.aio.models.embed_content(
                model="text-embedding-004",
                contents=text,
            )
            embedding = list(response.embeddings[0].values)
            self._embedding_cache[text] = embedding
            return embedding
        except Exception as e:
            logger.debug(f"Embedding generation failed: {e}")
            return None

    async def save_episode_with_embedding(self, entry: EpisodicEntry) -> None:
        """Save an episode with its embedding for similarity search."""
        # First save the episode normally
        await self.save_episode(entry)

        # Then compute and store embedding
        text = f"{entry.instruction} | {entry.domain} | {'success' if entry.success else 'failed'}"
        if entry.obstacles:
            text += f" | obstacles: {', '.join(entry.obstacles[:3])}"

        embedding = await self._get_embedding(text)
        if embedding is None:
            return

        embedding_data = {
            "text": text,
            "embedding": embedding,
            "domain": entry.domain,
            "instruction": entry.instruction,
            "success": entry.success,
            "steps_taken": entry.steps_taken,
            "obstacles": entry.obstacles[:5],
            "timestamp": entry.timestamp,
        }

        if self._firestore:
            try:
                doc_id = f"emb_{entry.domain}_{int(entry.timestamp)}"
                await self._firestore.collection("gaxis_embeddings").document(doc_id).set(embedding_data)
                return
            except Exception:
                pass

        # Local fallback
        self._save_local("embeddings", "all.jsonl", embedding_data)

    async def retrieve_similar(self, query: str, limit: int = 5) -> list[dict]:
        """Find similar past experiences using embedding cosine similarity.

        Searches across ALL domains — not just the current one.
        This is the retrieval-based memory strategy.
        """
        query_embedding = await self._get_embedding(query)
        if query_embedding is None:
            return []

        candidates = []

        # Load all embeddings
        if self._firestore:
            try:
                docs = self._firestore.collection("gaxis_embeddings").stream()
                async for doc in docs:
                    data = doc.to_dict()
                    if "embedding" in data:
                        candidates.append(data)
            except Exception:
                pass

        if not candidates:
            # Local fallback
            candidates = self._load_local_embeddings()

        if not candidates:
            return []

        # Compute cosine similarity and rank
        scored = []
        for c in candidates:
            stored_embedding = c.get("embedding", [])
            if not stored_embedding:
                continue
            similarity = self._cosine_similarity(query_embedding, stored_embedding)
            scored.append({
                "instruction": c.get("instruction", ""),
                "domain": c.get("domain", ""),
                "success": c.get("success", False),
                "steps": c.get("steps_taken", 0),
                "obstacles": c.get("obstacles", []),
                "similarity": round(similarity, 3),
                "result": "succeeded" if c.get("success") else "failed",
            })

        # Sort by similarity (highest first) and return top results
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def _load_local_embeddings(self) -> list[dict]:
        """Load all stored embeddings from local storage."""
        file_path = self._local_dir / "embeddings" / "all.jsonl"
        if not file_path.exists():
            return []
        entries = []
        for line in file_path.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

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
