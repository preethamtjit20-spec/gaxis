"""Google Meet Home — semantic UI graph.

Built from the Google Meet landing page layout:
  meet.google.com
"""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gmeet_home",
        name="Google Meet — Home",
        url_pattern=r"meet\.google\.com(?!/[a-z]{3}-[a-z]{4}-[a-z]{3})",
        entry_node="new_meeting_btn",
        terminal_nodes=["meeting_link_display"],
        layout_description=(
            "CENTER-LEFT:  [New meeting ▼] button (white, with dropdown arrow)\n"
            "CENTER-RIGHT: [Enter a code or link ___________] [Join →]\n"
            "\n"
            "'New meeting' dropdown options:\n"
            "  • Create a meeting for later  (generates link only)\n"
            "  • Start an instant meeting    (enters meeting immediately)\n"
            "  • Schedule in Google Calendar  (opens calendar edit form)"
        ),
        interaction_sequence=[
            "new_meeting_btn",
            "join_code_input",
        ],
    )

    # ── NODES ──────────────────────────────────────────────

    graph.nodes["new_meeting_btn"] = UINode(
        id="new_meeting_btn",
        label="New meeting",
        node_type=NodeType.DROPDOWN,
        selector_hints={
            "text": "New meeting",
            "tag": "button",
            "region": "center_left",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the 'New meeting' button to open dropdown"),
        ],
        order=1,
        notes=(
            "White button with dropdown arrow on the left side. Clicking opens "
            "3 options: Create a meeting for later, Start an instant meeting, "
            "Schedule in Google Calendar."
        ),
    )

    graph.nodes["join_code_input"] = UINode(
        id="join_code_input",
        label="Enter a code or link",
        node_type=NodeType.INPUT,
        selector_hints={
            "placeholder": "Enter a code or link",
            "tag": "input",
            "region": "center_right",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the 'Enter a code or link' input"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type meeting code (abc-defg-hij)"),
        ],
        order=2,
        notes=(
            "Input field on the right side. Accepts full links "
            "(meet.google.com/abc-defg-hij) or just codes (abc-defg-hij)."
        ),
    )

    graph.nodes["join_btn"] = UINode(
        id="join_btn",
        label="Join",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Join",
            "tag": "button",
            "region": "center_right",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the Join button to enter the meeting"),
        ],
        order=3,
        notes="Arrow button to the right of the code input. Navigates to the meeting.",
    )

    graph.nodes["meeting_link_display"] = UINode(
        id="meeting_link_display",
        label="Meeting link dialog",
        node_type=NodeType.DIALOG,
        selector_hints={
            "text": "meet.google.com",
            "region": "center",
        },
        actions=[
            UIAction(ActionType.EXTRACT, {},
                     "Extract the meeting link from the dialog"),
        ],
        order=4,
        notes=(
            "Dialog that appears after clicking 'Create a meeting for later'. "
            "Shows the meeting link (meet.google.com/xxx-xxxx-xxx). "
            "Has a copy button to copy the link."
        ),
    )

    # ── EDGES ──────────────────────────────────────────────

    graph.edges = [
        UIEdge(
            source="new_meeting_btn",
            target="meeting_link_display",
            action=ActionType.CLICK,
            condition="create_for_later",
            description="After clicking 'Create for later', link dialog appears",
        ),
        UIEdge(
            source="join_code_input",
            target="join_btn",
            action=ActionType.TYPE,
            description="After entering code, click Join",
        ),
    ]

    return graph
