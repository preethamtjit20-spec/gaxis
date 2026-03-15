"""Detect which known app the agent is on from URL."""

from __future__ import annotations

import re


# (regex_pattern, app_id)
_URL_PATTERNS: list[tuple[str, str]] = [
    (r"calendar\.google\.com/calendar(?:/u/\d+)?/r/eventedit", "gcal_event_editor"),
    (r"calendar\.google\.com/calendar", "gcal_view"),
    (r"mail\.google\.com/mail.*#.*compose", "gmail_compose"),
    (r"mail\.google\.com/mail", "gmail_inbox"),
    (r"docs\.google\.com/document/.*/edit", "gdocs_editor"),
    (r"docs\.google\.com/document/create", "gdocs_editor"),
    (r"docs\.google\.com/spreadsheets/.*/edit", "gsheets_editor"),
    (r"meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", "gmeet_call"),
    (r"meet\.google\.com", "gmeet_home"),
]


def detect_app(url: str, title: str = "") -> str | None:
    """Return app_id or None if URL doesn't match any known app."""
    if not url:
        return None
    for pattern, app_id in _URL_PATTERNS:
        if re.search(pattern, url):
            return app_id
    return None
