"""Google Workspace connector — thin wrapper that re-exports sub-connectors.

Individual services have been split into dedicated modules:
  - gmail.py      → GmailConnector
  - drive.py      → GoogleDriveConnector
  - sheets.py     → GoogleSheetsConnector
  - docs.py       → GoogleDocsConnector
  - meet.py       → GoogleMeetConnector
  - calendar.py   → GoogleCalendarConnector

This module is kept for backward compatibility. New code should import
from the individual connector modules directly.
"""

from __future__ import annotations

from backend.connectors.gmail import GmailConnector
from backend.connectors.drive import GoogleDriveConnector
from backend.connectors.sheets import GoogleSheetsConnector
from backend.connectors.docs import GoogleDocsConnector
from backend.connectors.meet import GoogleMeetConnector
from backend.connectors.calendar import GoogleCalendarConnector

__all__ = [
    "GmailConnector",
    "GoogleDriveConnector",
    "GoogleSheetsConnector",
    "GoogleDocsConnector",
    "GoogleMeetConnector",
    "GoogleCalendarConnector",
]
