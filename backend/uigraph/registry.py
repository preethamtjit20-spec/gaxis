"""UIGraph registry — loads and caches pre-built graphs."""

from __future__ import annotations

import logging

from backend.uigraph.model import UIGraph
from backend.uigraph.detector import detect_app

logger = logging.getLogger("gaxis.uigraph")


class UIGraphRegistry:
    """Loads all pre-built UI graphs and provides lookup by URL."""

    def __init__(self) -> None:
        self._graphs: dict[str, UIGraph] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        from backend.uigraph.graphs import (
            calendar_event_editor,
            gmail_compose,
            gdocs_editor,
            gsheets_editor,
            gmeet_home,
            gmail_inbox,
        )

        for builder_mod in [
            calendar_event_editor,
            gmail_compose,
            gdocs_editor,
            gsheets_editor,
            gmeet_home,
            gmail_inbox,
        ]:
            g = builder_mod.build()
            self._graphs[g.app_id] = g
            logger.info(f"Loaded UI graph: {g.app_id} ({len(g.nodes)} nodes)")

    def get(self, app_id: str) -> UIGraph | None:
        return self._graphs.get(app_id)

    def detect_and_get(self, url: str, title: str = "") -> UIGraph | None:
        """Detect app from URL and return its graph, or None."""
        app_id = detect_app(url, title)
        if app_id:
            return self.get(app_id)
        return None
