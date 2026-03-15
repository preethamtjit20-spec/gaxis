"""Conversation Planner — slot-filling dialogue agent for calendar/email tasks.

Architecture:
  User input → Intent detection → Slot extraction → Missing slot check
  → Ask targeted question (ONE at a time) → Repeat until complete
  → Show confirmation → Delegate to UI navigator

Three layers:
  1. Intent understanding
  2. Slot filling through conversation
  3. Action confirmation → execution

The planner NEVER executes UI actions itself. It only collects information
through natural dialogue and delegates when all slots are filled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from google import genai
from google.genai import types

from backend.agent.base import AGENT_MODEL

logger = logging.getLogger("gaxis.planner")


# ─── SLOT DEFINITIONS ────────────────────────────────────────

# Required slots per intent (must be filled before confirmation)
REQUIRED_SLOTS = {
    "CREATE_EVENT": ["title", "date", "start_time"],
    "CREATE_RECURRING": ["title", "date", "start_time", "recurrence"],
    "UPDATE_EVENT": ["title"],
    "DELETE_EVENT": ["title"],
    "ADD_PARTICIPANT": ["title", "participants"],
    "RESCHEDULE": ["title", "start_time"],
    "FIND_SLOT": ["date"],
    "CHECK_AVAILABILITY": ["date", "start_time"],
    "SEND_EMAIL": ["to", "subject"],
    "PLAY_VIDEO": ["query"],
    "PLAY_MUSIC": ["query"],
    "SEARCH_VIDEO": ["query"],
    "GENERAL": [],
    "RESEARCH": [],
    "BROWSE": [],
}

# Priority order for asking (ask highest priority missing slot first)
SLOT_PRIORITY = [
    "query",
    "title", "date", "start_time", "duration", "end_time",
    "participants", "recurrence", "location", "description",
    "to", "subject", "body",
]

# Human-friendly questions for each slot
SLOT_QUESTIONS = {
    "title": "What should the event be called?",
    "date": "Which date should this be on?",
    "start_time": "What time should it start?",
    "duration": "How long should it be?",
    "end_time": "What time should it end?",
    "participants": "Who should I invite? (email addresses work best)",
    "recurrence": "How often should this repeat? (daily, weekly, etc.)",
    "location": "Where will this take place?",
    "description": "Any description or notes to add?",
    "to": "Who should I send this to? (email address)",
    "subject": "What should the subject line be?",
    "body": "What should the email say?",
    "query": "What would you like me to play or search for?",
}


PLANNER_SYSTEM = """You are G-Axis — a conversational assistant that helps users schedule events, send emails, and manage tasks through natural dialogue.

═══ YOUR ROLE ═══

You collect information through conversation, then delegate to a UI automation agent.
You NEVER execute browser actions. You only chat, collect slots, and confirm.

═══ CONVERSATION RULES ═══

1. DETECT INTENT from the first message:
   Calendar: CREATE_EVENT, UPDATE_EVENT, DELETE_EVENT, ADD_PARTICIPANT, FIND_SLOT, CHECK_AVAILABILITY, RESCHEDULE, CREATE_RECURRING
   Email: SEND_EMAIL, REPLY_EMAIL
   Media: PLAY_VIDEO, PLAY_MUSIC, SEARCH_VIDEO
   General: GENERAL, RESEARCH, BROWSE

   MEDIA INTENT RULES:
   - "play X" / "put on X" / "listen to X" → PLAY_MUSIC if X is a song/artist, PLAY_VIDEO otherwise
   - "watch X" → PLAY_VIDEO
   - "search youtube for X" / "find videos about X" → SEARCH_VIDEO
   - For PLAY_VIDEO/PLAY_MUSIC: the query IS the content — "play dance monkey" → query="Dance Monkey"
   - Media intents should set ready_to_execute=true IMMEDIATELY (query slot is always in the first message)
   - platform is always "youtube" for media intents

   GENERAL/RESEARCH/BROWSE INTENT RULES:
   - "research X" / "plan X" / "compare X" / "find X" / "look up X" → RESEARCH or BROWSE
   - These tasks do NOT need slot-filling — set ready_to_execute=true IMMEDIATELY
   - Use the full user message as the refined_instruction
   - platform is "browser"
   - Do NOT ask "What would you like me to play or search for?" — these are NOT media tasks

2. EXTRACT all available slots from the user's message immediately.
   Slots: title, date, start_time, end_time, duration, participants, location, description, recurrence

3. MAINTAIN SLOT STATE — track what you know and what's missing.
   The SLOT_STATE in context shows what's been collected. NEVER re-ask for filled slots.

4. ASK ONE QUESTION AT A TIME for missing required slots.
   Priority: title → date → start_time → duration → participants
   Be natural: "What time should it start?" not "Please provide the start_time parameter."

5. NEVER assume missing required fields. If time is not mentioned, ASK.
   Exception: title can be inferred ("schedule meeting" → "Meeting")

6. HANDLE FOLLOW-UPS naturally.
   "3pm" → update start_time = "3:00pm"
   "actually make it 4pm" → update start_time = "4:00pm"
   "with Alice too" → add to participants

7. NORMALIZE TIME intelligently:
   "tomorrow afternoon" → date=tomorrow, but ASK for specific time
   "at 3" → AMBIGUOUS (AM/PM?) — ask
   "at 3pm" → start_time = "3:00pm" — clear
   "for 30 minutes" → duration = "30 minutes" → compute end_time

8. When ALL required slots are filled → set ready_to_execute=true AND include a confirmation summary.
   Show the user what will happen: "I'll create 'Sprint Planning' on Thursday at 2 PM – 3 PM."

9. PERSONALITY: Warm, concise, natural.
   - 1-2 sentences max per response
   - "Got it!", "Sure thing!", "Quick question —"
   - Mirror user's energy

═══ RESPONSE FORMAT — always JSON ═══

{
  "message": "Your response to the user",
  "intent": "CREATE_EVENT",
  "slots": {
    "title": "extracted or null",
    "date": "extracted or null",
    "start_time": "extracted or null",
    "end_time": "extracted or null",
    "duration": "extracted or null",
    "participants": "extracted or null",
    "location": "extracted or null",
    "description": "extracted or null",
    "recurrence": "extracted or null"
  },
  "ready_to_execute": false,
  "plan": null,
  "questions": ["the question you asked"],
  "recommendations": [],
  "preferences_learned": {}
}

When ready_to_execute=true, include plan:
{
  "message": "I'll create 'Team Sync' tomorrow at 3 PM – 4 PM on Google Calendar.",
  "intent": "CREATE_EVENT",
  "slots": { ... all filled ... },
  "ready_to_execute": true,
  "plan": {
    "action": "Create calendar event",
    "platform": "google_calendar",
    "refined_instruction": "Create a Google Calendar event titled 'Team Sync' on Mar 14, 2026 from 3:00pm to 4:00pm.",
    "slots": { ... all filled ... }
  },
  "questions": [],
  "recommendations": [],
  "preferences_learned": {}
}

═══ CRITICAL RULES ═══
- NEVER set ready_to_execute=true if ANY required slot is missing
- NEVER ask more than 1 question per response
- NEVER re-ask for a slot that's already in SLOT_STATE
- If user says "yes", "go ahead", "do it" → confirm execution with current slots
- If user corrects a value, update it and confirm the change
"""


class ConversationPlanner:
    """Slot-filling conversation agent.

    Maintains slot state across turns so the user never has to repeat info.
    Only delegates when all required slots are filled and user confirms.
    """

    def __init__(self, client: genai.Client):
        self.client = client
        self._history: list[types.Content] = []
        self._skills_prompt: str = ""
        # Slot state — persists across conversation turns
        self._slots: dict[str, str | None] = {}
        self._intent: str | None = None
        # Short-term context: parameters collected across turns
        self._session_context: dict[str, str] = {}

    def set_skills_context(self, skills_prompt: str) -> None:
        """Inject connector skills context so planner can suggest GWS workflows."""
        self._skills_prompt = skills_prompt

    def reset(self):
        """Reset conversation history and slot state."""
        self._history = []
        self._slots = {}
        self._intent = None
        self._session_context = {}

    def update_context(self, key: str, value: str) -> None:
        """Store a parameter in short-term context (persists within session)."""
        self._session_context[key] = value

    def _get_slot_state_text(self) -> str:
        """Build slot state context for the LLM."""
        if not self._slots and not self._intent:
            return ""

        now = datetime.now()
        tomorrow = now + timedelta(days=1)

        lines = [
            f"\n\nSLOT_STATE (what you already know — DO NOT re-ask these):",
            f"  Today: {now.strftime('%A, %B %d, %Y')}",
            f"  Tomorrow: {tomorrow.strftime('%A, %B %d, %Y')}",
        ]
        if self._intent:
            lines.append(f"  Intent: {self._intent}")

        filled = {k: v for k, v in self._slots.items() if v}
        missing_keys = []

        if filled:
            lines.append("  Filled slots:")
            for k, v in filled.items():
                lines.append(f"    {k}: {v}")

        # Show what's still needed
        if self._intent:
            required = REQUIRED_SLOTS.get(self._intent, [])
            missing_keys = [s for s in required if not self._slots.get(s)]
            if missing_keys:
                lines.append(f"  MISSING required: {', '.join(missing_keys)}")
                lines.append(f"  → Ask about: {missing_keys[0]}")
            else:
                lines.append("  ALL required slots filled → set ready_to_execute=true")

        return "\n".join(lines)

    def _merge_slots(self, new_slots: dict) -> None:
        """Merge new slot values into state. Only overwrite if non-null."""
        if not new_slots or not isinstance(new_slots, dict):
            return
        for key, val in new_slots.items():
            if val and str(val).strip() and str(val).lower() not in ("null", "none", ""):
                old = self._slots.get(key)
                self._slots[key] = str(val).strip()
                if old != self._slots[key]:
                    logger.info(f"Slot updated: {key}: {old!r} → {self._slots[key]!r}")

    def _compute_end_time(self) -> None:
        """Auto-compute end_time from start_time + duration if possible."""
        start = self._slots.get("start_time")
        duration = self._slots.get("duration")
        end = self._slots.get("end_time")

        if start and not end:
            if duration:
                # Parse duration like "30 minutes", "1 hour", "1.5 hours"
                mins = 60  # default 1 hour
                dur_lower = duration.lower()
                m = re.search(r"(\d+)\s*min", dur_lower)
                if m:
                    mins = int(m.group(1))
                else:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*hour", dur_lower)
                    if m:
                        mins = int(float(m.group(1)) * 60)
                # Compute end time
                try:
                    st = datetime.strptime(start.lower().replace(" ", ""), "%I:%M%p")
                    et = st + timedelta(minutes=mins)
                    self._slots["end_time"] = et.strftime("%-I:%M%p").lower()
                except ValueError:
                    pass
            else:
                # Default: 1 hour
                try:
                    st = datetime.strptime(start.lower().replace(" ", ""), "%I:%M%p")
                    et = st + timedelta(hours=1)
                    self._slots["end_time"] = et.strftime("%-I:%M%p").lower()
                except ValueError:
                    pass

    def _build_refined_instruction(self) -> str:
        """Build a complete, unambiguous instruction for the executor."""
        intent = self._intent or "CREATE_EVENT"
        slots = self._slots

        if intent in ("CREATE_EVENT", "CREATE_RECURRING"):
            parts = [f"Create a Google Calendar event titled '{slots.get('title', 'Untitled')}'"]
            if slots.get("date"):
                parts.append(f"on {slots['date']}")
            if slots.get("start_time"):
                time_str = slots["start_time"]
                if slots.get("end_time"):
                    time_str += f" to {slots['end_time']}"
                parts.append(f"from {time_str}")
            if slots.get("participants"):
                parts.append(f". Add {slots['participants']} as guest(s)")
            if slots.get("location"):
                parts.append(f". Location: {slots['location']}")
            if slots.get("description"):
                parts.append(f". Description: {slots['description']}")
            if slots.get("recurrence"):
                parts.append(f". Repeat: {slots['recurrence']}")
            return " ".join(parts) + "."

        if intent == "SEND_EMAIL":
            parts = [f"Send an email to {slots.get('to', '')}"]
            if slots.get("subject"):
                parts.append(f"with subject '{slots['subject']}'")
            if slots.get("body"):
                parts.append(f". Body: {slots['body']}")
            return " ".join(parts) + "."

        if intent in ("PLAY_VIDEO", "PLAY_MUSIC"):
            return f"Play '{slots.get('query', '')}' on YouTube."

        if intent == "SEARCH_VIDEO":
            return f"Search YouTube for '{slots.get('query', '')}'."

        # Fallback
        return f"{intent}: " + ", ".join(f"{k}={v}" for k, v in slots.items() if v)

    async def chat(
        self,
        user_message: str,
        user_preferences: dict | None = None,
        current_url: str = "",
    ) -> dict:
        """Send a message and get the planner's response.

        Maintains slot state: each turn extracts new slots and checks
        if all required slots are filled. Only then sets ready_to_execute.

        Returns dict with: message, questions, ready_to_execute, plan,
        recommendations, preferences_learned
        """
        # Build user prompt with slot state context
        parts = [types.Part.from_text(text=user_message)]

        # Add slot state (what's already collected)
        slot_state = self._get_slot_state_text()
        if slot_state:
            parts.append(types.Part.from_text(text=slot_state))

        # Add short-term session context
        if self._session_context:
            ctx_text = "\n\nSESSION CONTEXT (parameters already provided):\n"
            for k, v in self._session_context.items():
                ctx_text += f"  - {k}: {v}\n"
            parts.append(types.Part.from_text(text=ctx_text))

        # Add user preferences
        if user_preferences:
            pref_text = "\n\nUSER PREFERENCES (from past interactions):\n"
            for k, v in user_preferences.items():
                pref_text += f"  - {k}: {v}\n"
            parts.append(types.Part.from_text(text=pref_text))

        if current_url:
            parts.append(types.Part.from_text(
                text=f"\nUser is currently on: {current_url}"
            ))

        if self._skills_prompt:
            parts.append(types.Part.from_text(
                text=f"\n{self._skills_prompt}"
            ))

        user_content = types.Content(role="user", parts=parts)
        self._history.append(user_content)

        # Trim history (keep recent context)
        if len(self._history) > 20:
            self._history = self._history[-20:]

        for attempt in range(3):
            try:
                response = await self.client.aio.models.generate_content(
                    model=AGENT_MODEL,
                    contents=self._history,
                    config=types.GenerateContentConfig(
                        system_instruction=PLANNER_SYSTEM,
                        temperature=0.7,
                        max_output_tokens=1024,
                        response_mime_type="application/json",
                    ),
                )
                break
            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < 2:
                    await asyncio.sleep(2 ** attempt * 3)
                else:
                    raise

        # Parse response
        text = response.text or "{}"
        if response.candidates and response.candidates[0].content:
            self._history.append(response.candidates[0].content)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    result = {
                        "message": text,
                        "questions": [],
                        "ready_to_execute": False,
                        "plan": None,
                    }
            else:
                result = {
                    "message": text,
                    "questions": [],
                    "ready_to_execute": False,
                    "plan": None,
                }

        # ── Update slot state from LLM response ──

        # Intent
        if result.get("intent"):
            self._intent = result["intent"]
            logger.info(f"Planner intent: {self._intent}")

        # Merge slots from response
        if result.get("slots"):
            self._merge_slots(result["slots"])

        # Merge slots from plan if available
        plan = result.get("plan")
        if plan and isinstance(plan, dict):
            if plan.get("slots"):
                self._merge_slots(plan["slots"])
            for key in ("platform", "action"):
                val = plan.get(key)
                if val:
                    self._session_context[key] = val

        # Auto-compute end_time from start_time + duration
        self._compute_end_time()

        # ── Validate ready_to_execute against actual slot state ──
        ready = result.get("ready_to_execute", False)
        if ready and self._intent:
            required = REQUIRED_SLOTS.get(self._intent, [])
            missing = [s for s in required if not self._slots.get(s)]
            if missing:
                # LLM said ready but slots are missing — override
                logger.warning(f"Planner override: LLM said ready but missing {missing}")
                ready = False
                # Ask about the first missing slot
                slot = missing[0]
                question = SLOT_QUESTIONS.get(slot, f"What should the {slot} be?")
                result["message"] = result.get("message", "") + f"\n\nQuick question — {question}"
                result["questions"] = [question]

        # Build refined instruction when ready
        if ready:
            refined = self._build_refined_instruction()
            if not plan:
                plan = {}
            plan["refined_instruction"] = refined
            plan["slots"] = {k: v for k, v in self._slots.items() if v}
            plan["intent"] = self._intent
            result["plan"] = plan
            logger.info(f"Planner ready: {refined[:100]}")

        logger.info(f"Planner slots: {self._slots}")

        # Extract preferences
        preferences_learned = result.get("preferences_learned", {})

        return {
            "message": result.get("message", ""),
            "questions": result.get("questions", []),
            "ready_to_execute": ready,
            "plan": plan,
            "recommendations": result.get("recommendations", []),
            "preferences_learned": preferences_learned,
            "intent": self._intent,
            "slots": {k: v for k, v in self._slots.items() if v},
        }
