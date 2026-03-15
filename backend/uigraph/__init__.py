"""Semantic UI Graph — structured maps of known app UIs.

Instead of pixel-guessing, the agent reasons over a graph:
  intent → node → action → next state
"""

from backend.uigraph.model import UIGraph, UINode, UIEdge, UIAction, NodeType, ActionType
from backend.uigraph.registry import UIGraphRegistry
from backend.uigraph.prompt import serialize_graph_for_prompt

__all__ = [
    "UIGraph", "UINode", "UIEdge", "UIAction", "NodeType", "ActionType",
    "UIGraphRegistry", "serialize_graph_for_prompt",
]
