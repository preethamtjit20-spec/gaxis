"""UIGraph data model — nodes, edges, actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    INPUT = "input"          # text input, textarea
    BUTTON = "button"        # clickable button
    CHIP = "chip"            # date/time chip (click → editable or picker)
    LINK = "link"            # clickable text link
    DROPDOWN = "dropdown"    # select / dropdown trigger
    CHECKBOX = "checkbox"    # toggle checkbox
    DIALOG = "dialog"        # modal/popup that may appear conditionally


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type_text"
    PRESS_KEY = "press_key"
    WAIT = "wait"
    EXTRACT = "extract_data"


@dataclass
class UIAction:
    """A concrete action the agent can take on a node."""
    action: ActionType
    params: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class UINode:
    """A single interactable UI element."""
    id: str
    label: str
    node_type: NodeType
    # Hints to match against live DOM elements (tag, placeholder, ariaLabel, text)
    selector_hints: dict = field(default_factory=dict)
    actions: list[UIAction] = field(default_factory=list)
    format_hint: str = ""       # e.g. "10:00am", "Mar 12, 2026"
    required: bool = False
    default_value: str = ""
    notes: str = ""
    order: int = 0              # recommended fill order


@dataclass
class UIEdge:
    """A state transition: action on source → target appears."""
    source: str
    target: str
    action: ActionType
    condition: str = ""
    description: str = ""


@dataclass
class UIGraph:
    """Semantic map of a known application screen."""
    app_id: str
    name: str
    url_pattern: str               # regex to match URL
    nodes: dict[str, UINode] = field(default_factory=dict)
    edges: list[UIEdge] = field(default_factory=list)
    entry_node: str = ""
    terminal_nodes: list[str] = field(default_factory=list)
    layout_description: str = ""
    interaction_sequence: list[str] = field(default_factory=list)

    def get_node(self, node_id: str) -> UINode | None:
        return self.nodes.get(node_id)

    def get_edges_from(self, node_id: str) -> list[UIEdge]:
        return [e for e in self.edges if e.source == node_id]

    def get_required_nodes(self) -> list[UINode]:
        return [n for n in self.nodes.values() if n.required]
