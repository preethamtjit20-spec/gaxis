"""Conversation analytics store.

Stores voice session data and generates insights.
Uses local JSON files (no Firebase needed).
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

ANALYTICS_DIR = Path(".analytics")
SESSIONS_FILE = ANALYTICS_DIR / "sessions.json"
STATS_FILE = ANALYTICS_DIR / "stats.json"


@dataclass
class SessionRecord:
    session_id: str
    persona: str
    started_at: str
    ended_at: str
    duration_secs: int
    message_count: int
    user_word_count: int
    agent_word_count: int
    topics: list = field(default_factory=list)
    intent: str = "casual"
    summary: str = ""
    skills: dict = field(default_factory=dict)  # confidence, clarity, engagement, etc.
    action_items: list = field(default_factory=list)


@dataclass
class UserStats:
    total_sessions: int = 0
    total_duration_mins: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    xp: int = 0
    level: int = 1
    last_session_date: str = ""
    persona_usage: dict = field(default_factory=dict)
    daily_activity: list = field(default_factory=list)  # last 7 days
    skill_scores: dict = field(default_factory=lambda: {
        "confidence": 50, "clarity": 50, "engagement": 50,
        "listening": 50, "pacing": 50,
    })


def _ensure_dir():
    ANALYTICS_DIR.mkdir(exist_ok=True)


def _load_sessions() -> list[dict]:
    _ensure_dir()
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text())
    return []


def _save_sessions(sessions: list[dict]):
    _ensure_dir()
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def _load_stats() -> dict:
    _ensure_dir()
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text())
    return asdict(UserStats())


def _save_stats(stats: dict):
    _ensure_dir()
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def save_session(record: SessionRecord) -> dict:
    """Save a completed voice session and update stats."""
    sessions = _load_sessions()
    sessions.append(asdict(record))
    # Keep last 100 sessions
    if len(sessions) > 100:
        sessions = sessions[-100:]
    _save_sessions(sessions)

    # Update stats
    stats = _load_stats()
    stats["total_sessions"] += 1
    stats["total_duration_mins"] += record.duration_secs // 60

    # XP: 10 per minute + 50 per session + bonus for skills
    xp_earned = (record.duration_secs // 60) * 10 + 50
    if record.skills:
        avg_skill = sum(record.skills.values()) / len(record.skills)
        xp_earned += int(avg_skill * 0.5)
    stats["xp"] = stats.get("xp", 0) + xp_earned
    stats["level"] = 1 + stats["xp"] // 500

    # Streak
    today = datetime.now().strftime("%Y-%m-%d")
    last_date = stats.get("last_session_date", "")
    if last_date == today:
        pass  # Same day, streak unchanged
    elif last_date == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"):
        stats["current_streak"] = stats.get("current_streak", 0) + 1
    else:
        stats["current_streak"] = 1
    stats["longest_streak"] = max(stats.get("longest_streak", 0), stats.get("current_streak", 1))
    stats["last_session_date"] = today

    # Persona usage
    persona_usage = stats.get("persona_usage", {})
    persona_usage[record.persona] = persona_usage.get(record.persona, 0) + 1
    stats["persona_usage"] = persona_usage

    # Update skill scores (rolling average with new session)
    if record.skills:
        existing = stats.get("skill_scores", {})
        for k, v in record.skills.items():
            old = existing.get(k, 50)
            existing[k] = int(old * 0.7 + v * 0.3)  # Weighted average
        stats["skill_scores"] = existing

    # Daily activity (last 7 days)
    daily = stats.get("daily_activity", [])
    if daily and daily[-1].get("date") == today:
        daily[-1]["sessions"] += 1
        daily[-1]["minutes"] += record.duration_secs // 60
    else:
        daily.append({"date": today, "sessions": 1, "minutes": record.duration_secs // 60})
    stats["daily_activity"] = daily[-7:]

    _save_stats(stats)
    return {"xp_earned": xp_earned, "level": stats["level"], "streak": stats["current_streak"]}


def get_stats() -> dict:
    """Get current user stats for dashboard."""
    return _load_stats()


def get_recent_sessions(limit: int = 10) -> list[dict]:
    """Get recent session records."""
    sessions = _load_sessions()
    return sessions[-limit:]


def get_insights() -> dict:
    """Generate insights from recent sessions."""
    sessions = _load_sessions()
    if not sessions:
        return {"message": "No sessions yet. Start a voice conversation to see insights!"}

    recent = sessions[-10:]
    total_mins = sum(s.get("duration_secs", 0) for s in recent) // 60
    avg_duration = total_mins // len(recent) if recent else 0
    all_topics = []
    for s in recent:
        all_topics.extend(s.get("topics", []))
    top_topics = sorted(set(all_topics), key=all_topics.count, reverse=True)[:5]

    personas_used = {}
    for s in recent:
        p = s.get("persona", "friend")
        personas_used[p] = personas_used.get(p, 0) + 1
    fav_persona = max(personas_used, key=personas_used.get) if personas_used else "friend"

    return {
        "recent_sessions": len(recent),
        "total_minutes": total_mins,
        "avg_duration_mins": avg_duration,
        "top_topics": top_topics,
        "favorite_persona": fav_persona,
        "personas_used": personas_used,
    }
