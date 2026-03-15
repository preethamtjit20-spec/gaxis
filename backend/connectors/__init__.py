"""G-Axis Connector System — extensible skill-based integrations.

Connectors register skills that the agent can discover and use.
Each skill maps to either a direct API call or a browser-based workflow.
"""

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillResult
from backend.connectors.registry import ConnectorRegistry
from backend.connectors.calendar import GoogleCalendarConnector
from backend.connectors.general import GeneralSkillsConnector
from backend.connectors.gmail import GmailConnector
from backend.connectors.drive import GoogleDriveConnector
from backend.connectors.sheets import GoogleSheetsConnector
from backend.connectors.docs import GoogleDocsConnector
from backend.connectors.meet import GoogleMeetConnector
from backend.connectors.research import ResearchConnector
from backend.connectors.youtube import YouTubeConnector

__all__ = [
    "BaseConnector",
    "Skill",
    "SkillParam",
    "SkillResult",
    "ConnectorRegistry",
    "GoogleCalendarConnector",
    "GeneralSkillsConnector",
    "GmailConnector",
    "GoogleDriveConnector",
    "GoogleSheetsConnector",
    "GoogleDocsConnector",
    "GoogleMeetConnector",
    "ResearchConnector",
    "YouTubeConnector",
]
