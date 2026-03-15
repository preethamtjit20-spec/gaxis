"""Gmail Inbox — semantic UI graph.

Built from the Gmail inbox/search page layout:
  mail.google.com/mail/u/0/#inbox
"""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gmail_inbox",
        name="Gmail — Inbox & Search",
        url_pattern=r"mail\.google\.com/mail",
        entry_node="compose_btn",
        terminal_nodes=["compose_btn"],
        layout_description=(
            "TOP BAR:     [☰ Menu]  [🔍 Search mail ________________________]\n"
            "SIDEBAR:     [+ Compose] | Inbox | Starred | Sent | Drafts | Labels\n"
            "MAIN AREA:   Email list — each row:\n"
            "             ☐  ☆  Sender     Subject — snippet              3pm\n"
            "             ☐  ☆  Sender     Subject — snippet              2pm\n"
            "             Bold rows = unread, normal = read"
        ),
        interaction_sequence=[
            "search_bar",
            "compose_btn",
        ],
    )

    # ── NODES ──────────────────────────────────────────────

    graph.nodes["search_bar"] = UINode(
        id="search_bar",
        label="Search mail",
        node_type=NodeType.INPUT,
        selector_hints={
            "placeholder": "Search mail",
            "aria": "Search mail",
            "tag": "input",
            "region": "top_center",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the 'Search mail' input at the top"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": True},
                     "Type search query and press Enter"),
        ],
        order=1,
        notes=(
            "Large search input spanning the top center. Supports Gmail operators: "
            "from:, to:, subject:, has:attachment, is:unread, before:, after:, label:."
        ),
    )

    graph.nodes["compose_btn"] = UINode(
        id="compose_btn",
        label="Compose",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Compose",
            "tag": "div",
            "region": "sidebar_top",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the Compose button in the sidebar"),
        ],
        order=2,
        notes=(
            "Large button at the top of the left sidebar with '+' icon. "
            "Opens the floating compose window at the bottom-right."
        ),
    )

    graph.nodes["email_row"] = UINode(
        id="email_row",
        label="Email row",
        node_type=NodeType.LINK,
        selector_hints={
            "tag": "tr",
            "region": "main_area",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click an email row to open the full email"),
        ],
        order=3,
        notes=(
            "Each email is a clickable row: checkbox, star, sender, subject — snippet, time. "
            "Bold = unread. Click to open full email view."
        ),
    )

    # ── EDGES ──────────────────────────────────────────────

    graph.edges = [
        UIEdge(
            source="search_bar",
            target="email_row",
            action=ActionType.PRESS_KEY,
            description="After searching, results appear as email rows",
        ),
    ]

    return graph
