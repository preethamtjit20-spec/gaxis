"""Serialize UIGraph into compact prompt text for the LLM."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from backend.uigraph.model import UIGraph, NodeType

logger = logging.getLogger("gaxis.uigraph")


def serialize_graph_for_prompt(
    graph: UIGraph,
    task_values: dict[str, str] | None = None,
) -> str:
    """Convert a UIGraph into a compact prompt block.

    Args:
        graph: The UI graph to serialize.
        task_values: Optional mapping of node_id → value to fill.
            e.g. {"title": "Team Sync", "start_time": "10:00am"}
    """
    lines = [
        f"═══ UI GRAPH: {graph.name} ═══",
        graph.layout_description,
        "",
        "SEQUENCE (follow this order, skip nodes already correct):",
    ]

    for i, node_id in enumerate(graph.interaction_sequence, 1):
        node = graph.get_node(node_id)
        if not node:
            continue

        # Type badge
        type_badge = {
            NodeType.INPUT: "INPUT",
            NodeType.CHIP: "CHIP",
            NodeType.BUTTON: "BTN",
            NodeType.LINK: "LINK",
            NodeType.DROPDOWN: "DROP",
            NodeType.CHECKBOX: "CHECK",
            NodeType.DIALOG: "DIALOG",
        }.get(node.node_type, "?")

        # Match hints
        hints = []
        if node.selector_hints.get("placeholder"):
            hints.append(f'placeholder="{node.selector_hints["placeholder"]}"')
        if node.selector_hints.get("aria"):
            hints.append(f'aria="{node.selector_hints["aria"]}"')
        if node.selector_hints.get("text"):
            hints.append(f'text="{node.selector_hints["text"]}"')
        hint_str = f"  match: {', '.join(hints)}" if hints else ""

        # Value to fill
        value_str = ""
        if task_values and node_id in task_values:
            value_str = f'  → FILL: "{task_values[node_id]}"'

        # Format hint
        fmt_str = f"  format: {node.format_hint}" if node.format_hint else ""

        # Required marker
        req = " *" if node.required else ""

        # Action sequence
        action_seq = " → ".join(a.description for a in node.actions)

        line = f"  {i}. [{type_badge}] {node.label}{req}{fmt_str}{value_str}"
        if hint_str:
            line += f"\n    {hint_str}"
        line += f"\n     do: {action_seq}"
        if node.notes:
            # Keep notes to first sentence for brevity
            short_note = node.notes.split(". ")[0] + "."
            line += f"\n     note: {short_note}"

        lines.append(line)

    # Conditional transitions
    conditionals = [e for e in graph.edges if e.condition]
    if conditionals:
        lines.append("")
        lines.append("CONDITIONAL:")
        for edge in conditionals:
            lines.append(f"  {edge.source} → {edge.target} (if {edge.condition}): {edge.description}")

    return "\n".join(lines)


# ── Intent classification ──────────────────────────────────────

# Calendar intents — classified before field extraction
CALENDAR_INTENTS = {
    "CREATE_EVENT": "Create a new calendar event or meeting",
    "UPDATE_EVENT": "Modify an existing event (change time, title, etc.)",
    "DELETE_EVENT": "Cancel or delete an existing event",
    "ADD_PARTICIPANT": "Add a guest/participant to an existing event",
    "FIND_SLOT": "Find a free time slot in the calendar",
    "CHECK_AVAILABILITY": "Check if a specific time is free",
    "RESCHEDULE": "Move an event to a different time",
    "CREATE_RECURRING": "Create a recurring/repeating event",
}

# Required fields per intent — if missing, must clarify before confirming
REQUIRED_FIELDS: dict[str, dict[str, list[str]]] = {
    "gcal_event_editor": {
        "CREATE_EVENT": ["title", "start_date", "start_time"],
        "CREATE_RECURRING": ["title", "start_date", "start_time"],
        "UPDATE_EVENT": ["title"],  # Need to identify which event
        "DELETE_EVENT": ["title"],
        "ADD_PARTICIPANT": ["title", "guests"],
        "RESCHEDULE": ["title", "start_time"],
        "FIND_SLOT": ["start_date"],
        "CHECK_AVAILABILITY": ["start_date", "start_time"],
    },
    "gmail_compose": {
        "SEND_EMAIL": ["to_field", "subject"],
    },
}


def classify_intent(instruction: str, app_id: str) -> str:
    """Quick keyword-based intent classification (no LLM needed).

    Returns the most likely intent string.
    """
    lower = instruction.lower()

    if app_id == "gcal_event_editor":
        # Deletion
        if any(w in lower for w in ("cancel", "delete", "remove event")):
            return "DELETE_EVENT"
        # Reschedule
        if any(w in lower for w in ("reschedule", "move the", "push the", "change the time")):
            return "RESCHEDULE"
        # Update
        if any(w in lower for w in ("update", "modify", "change", "edit event", "rename")):
            return "UPDATE_EVENT"
        # Add participant
        if any(w in lower for w in ("add guest", "invite", "add participant", "add to meeting")):
            return "ADD_PARTICIPANT"
        # Check availability
        if any(w in lower for w in ("am i free", "available", "check schedule")):
            return "CHECK_AVAILABILITY"
        # Find slot
        if any(w in lower for w in ("find time", "find slot", "free slot", "when can")):
            return "FIND_SLOT"
        # Recurring
        if any(w in lower for w in ("every", "weekly", "daily", "monthly", "recurring", "repeat")):
            return "CREATE_RECURRING"
        # Default — create
        return "CREATE_EVENT"

    if app_id == "gmail_compose":
        return "SEND_EMAIL"

    return "CREATE"


def get_missing_required_fields(
    intent: str,
    app_id: str,
    values: dict[str, str],
) -> list[str]:
    """Check which required fields are missing for the given intent.

    Returns list of missing field names. Empty = all required fields present.
    """
    required = REQUIRED_FIELDS.get(app_id, {}).get(intent, [])
    missing = []
    for field in required:
        val = values.get(field, "").strip()
        if not val:
            missing.append(field)
    return missing


# Human-friendly labels for missing field prompts
_FIELD_LABELS = {
    "title": "event title",
    "start_date": "date",
    "start_time": "start time",
    "end_time": "end time",
    "guests": "guest email addresses",
    "description": "description",
    "to_field": "recipient email",
    "subject": "email subject",
}


def build_clarification_message(missing_fields: list[str]) -> str:
    """Build a natural clarification question for missing fields.

    Asks about ONE field at a time (most important first).
    """
    if not missing_fields:
        return ""

    # Ask about the most important missing field first
    field = missing_fields[0]
    label = _FIELD_LABELS.get(field, field)

    prompts = {
        "title": "What should the event be called?",
        "start_date": "Which date should this be on?",
        "start_time": "What time should it start?",
        "end_time": "What time should it end?",
        "guests": "Who should I invite? (email addresses)",
        "to_field": "Who should I send this to? (email address)",
        "subject": "What should the subject line be?",
    }

    question = prompts.get(field, f"What should the {label} be?")

    if len(missing_fields) > 1:
        others = [_FIELD_LABELS.get(f, f) for f in missing_fields[1:]]
        question += f"\n(I'll also need: {', '.join(others)})"

    return question


# ── LLM-based task value extraction ────────────────────────────

# Schema for each known app — tells the LLM what fields to extract
_EXTRACTION_SCHEMAS: dict[str, dict] = {
    "gcal_event_editor": {
        "system": (
            "Extract calendar event details from the user's message. "
            "Return a JSON object with the fields below PLUS '_intent' and '_ambiguities'. "
            "INTENT must be one of: CREATE_EVENT, UPDATE_EVENT, DELETE_EVENT, ADD_PARTICIPANT, "
            "FIND_SLOT, CHECK_AVAILABILITY, RESCHEDULE, CREATE_RECURRING. "
            "If ANY field is ambiguous, unclear, or you had to GUESS, add it to _ambiguities. "
            "IMPORTANT: A bare number for time like 'at 3' or 'at 7' is AMBIGUOUS (AM vs PM). "
            "A name without an email address means guests CANNOT be filled — that's ambiguous. "
            "If a required field (title, date, time) is NOT mentioned at all, leave it as empty string. "
            "Do NOT invent values for fields the user didn't mention. "
            "No explanation, just JSON."
        ),
        "fields": {
            "_intent": "The calendar intent: CREATE_EVENT, UPDATE_EVENT, DELETE_EVENT, ADD_PARTICIPANT, FIND_SLOT, CHECK_AVAILABILITY, RESCHEDULE, or CREATE_RECURRING.",
            "title": "Event title/name. Use EXACTLY what the user said — do NOT invent or embellish. 'schedule meeting' → 'Meeting'. 'team sync' → 'Team Sync'. Capitalize words. Empty string if not mentioned.",
            "start_date": "Date in 'Mon DD, YYYY' format (e.g. 'Mar 12, 2026'). Resolve 'tomorrow', 'next Monday', etc. Empty string if not mentioned.",
            "end_date": "End date, usually same as start_date for single-day events.",
            "start_time": "Start time in '10:00am' format (12hr, no space before am/pm). Empty string if not mentioned.",
            "end_time": "End time in '10:00am' format. If duration given (e.g. '15 minutes'), calculate from start_time. Default: 1 hour after start_time if start_time is known. Empty string if start_time is not known.",
            "guests": "Comma-separated email addresses. Empty string if none. A NAME without email is NOT a valid guest — mark as ambiguous.",
            "description": "Event description if mentioned. Empty string if none.",
            "recurrence": "Recurrence rule if mentioned (e.g. 'weekly', 'daily', 'every Monday'). Empty string if not recurring.",
            "_ambiguities": "Array of {field, issue, assumed} objects. E.g. [{\"field\": \"start_time\", \"issue\": \"'at 3' — is that 3 AM or 3 PM?\", \"assumed\": \"3:00pm\"}, {\"field\": \"guests\", \"issue\": \"Rahul mentioned but no email address provided\", \"assumed\": \"\"}]. Empty array if everything is clear.",
        },
    },
    "gmail_compose": {
        "system": (
            "Extract email composition details from the user's message. "
            "Return a JSON object with the fields below PLUS an '_ambiguities' array. "
            "If ANY field is ambiguous or missing, add it to _ambiguities. "
            "A name without email is ambiguous. No explanation, just JSON."
        ),
        "fields": {
            "to_field": "Recipient email address(es). A NAME without email is NOT valid — mark as ambiguous.",
            "subject": "Email subject line. Infer from context.",
            "body": "Email body text. Compose appropriately if not explicit.",
            "_ambiguities": "Array of {field, issue, assumed} objects. Empty array if everything is clear.",
        },
    },
    "gdocs_editor": {
        "system": (
            "Extract Google Docs document details from the user's message. "
            "Return ONLY a JSON object. No explanation."
        ),
        "fields": {
            "title": "Document title. Infer from context — capitalize appropriately. Never leave blank.",
            "body": "Document content to type into the body. If the user asks for research/itinerary/report, describe the high-level outline here. For long content, include section headings separated by newlines.",
        },
    },
    "gsheets_editor": {
        "system": (
            "Extract Google Sheets spreadsheet details from the user's message. "
            "Return ONLY a JSON object. No explanation."
        ),
        "fields": {
            "title": "Spreadsheet title. Infer from context — capitalize appropriately. Never leave blank.",
            "headers": "Comma-separated column headers for the first row (e.g. 'Date, Description, Amount, Category'). Infer from context.",
            "data": "Comma-separated rows of data, each row separated by a semicolon. Empty string if no initial data.",
        },
    },
}


async def extract_task_values_llm(
    instruction: str,
    graph: UIGraph,
    client,
    today: datetime | None = None,
    memory_hint: str = "",
) -> dict[str, str]:
    """Use a fast LLM call to extract structured task values from ANY wording.

    This replaces brittle regex extraction. One lightweight Gemini call parses
    natural language into the exact field values needed for the form.

    Returns a dict of field → value. Special keys:
      "_ambiguities": JSON string of ambiguity objects
      "_intent": detected intent (e.g. CREATE_EVENT, UPDATE_EVENT)
    """
    from google.genai import types
    from backend.agent.base import AGENT_MODEL

    schema = _EXTRACTION_SCHEMAS.get(graph.app_id)
    if not schema:
        # Unknown app — fall back to basic extraction
        return _extract_basic(instruction, graph)

    now = today or datetime.now()
    tomorrow = now + timedelta(days=1)

    # Build a tight extraction prompt
    field_desc = "\n".join(f'  "{k}": "{v}"' for k, v in schema["fields"].items())
    prompt = (
        f"{schema['system']}\n\n"
        f"Today is {now.strftime('%A, %B %d, %Y')}. "
        f"Tomorrow is {tomorrow.strftime('%A, %B %d, %Y')}.\n\n"
        f"Fields to extract:\n{field_desc}\n\n"
        f"User message: \"{instruction}\"\n\n"
        + (f"{memory_hint}\n\n" if memory_hint else "")
        + "JSON:"
    )

    try:
        response = await client.aio.models.generate_content(
            model=AGENT_MODEL,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=512,
            ),
        )

        if response.candidates and response.candidates[0].content:
            text = response.candidates[0].content.parts[0].text.strip()
            # Clean markdown code fences if present
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            values = json.loads(text)

            # Extract special keys before filtering
            ambiguities = values.pop("_ambiguities", [])
            intent = values.pop("_intent", "")

            # Filter out empty values and non-string values
            result = {k: str(v) for k, v in values.items() if v and str(v).strip()}

            # Store intent as a special key
            if intent:
                result["_intent"] = str(intent)
                logger.info(f"LLM detected intent: {intent}")

            # Store ambiguities as a special key if present
            if ambiguities and isinstance(ambiguities, list) and len(ambiguities) > 0:
                result["_ambiguities"] = json.dumps(ambiguities)
                logger.info(f"LLM detected ambiguities: {ambiguities}")

            return result

    except Exception as e:
        logger.warning(f"LLM extraction failed, falling back to basic: {e}")

    return _extract_basic(instruction, graph)


def extract_task_values(instruction: str, graph: UIGraph) -> dict[str, str]:
    """Synchronous fallback extractor — basic patterns only.

    Used when LLM extraction isn't available (e.g. during prompt serialization).
    The real extraction happens via extract_task_values_llm in the fast loop.
    """
    return _extract_basic(instruction, graph)


def _extract_basic(instruction: str, graph: UIGraph) -> dict[str, str]:
    """Lightweight pattern-based extraction — handles common cases.

    Not meant to be comprehensive. The LLM extraction handles edge cases.
    """
    lower = instruction.lower()
    values: dict[str, str] = {}

    if graph.app_id == "gcal_event_editor":
        # Date: tomorrow, today
        now = datetime.now()
        if "tomorrow" in lower:
            tmrw = now + timedelta(days=1)
            values["start_date"] = tmrw.strftime("%b %d, %Y")
            values["end_date"] = values["start_date"]
        elif "today" in lower:
            values["start_date"] = now.strftime("%b %d, %Y")
            values["end_date"] = values["start_date"]

        # Time: look for patterns like "at 10am", "at 3:30pm", "@ 2pm"
        time_match = re.search(
            r"(?:at|@)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            lower,
        )
        if time_match:
            raw_time = time_match.group(1).strip().replace(" ", "")
            if ":" not in raw_time:
                if "am" in raw_time:
                    raw_time = raw_time.replace("am", ":00am")
                elif "pm" in raw_time:
                    raw_time = raw_time.replace("pm", ":00pm")
            values["start_time"] = raw_time
            # Default end time: +1 hour
            try:
                st = datetime.strptime(raw_time, "%I:%M%p")
                et = st + timedelta(hours=1)
                values["end_time"] = et.strftime("%-I:%M%p").lower()
            except ValueError:
                pass

        # Emails
        emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", instruction)
        if emails:
            values["guests"] = ", ".join(emails)

    elif graph.app_id == "gmail_compose":
        emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", instruction)
        if emails:
            values["to_field"] = emails[0]

    return values
