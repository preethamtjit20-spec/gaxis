"""Gmail Compose — semantic UI graph."""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gmail_compose",
        name="Gmail — Compose Email",
        url_pattern=r"mail\.google\.com/mail.*#.*compose",
        entry_node="to_field",
        terminal_nodes=["send_btn"],
        layout_description=(
            "FLOATING COMPOSE WINDOW (bottom-right):\n"
            "  HEADER: 'New Message' title bar  [minimize] [expand] [X close]\n"
            "  [To ___________]  (recipient input)\n"
            "  [Subject _______]  (subject input)\n"
            "  [Body area — large text editor]\n"
            "  BOTTOM: [Send btn] [Format] [Attach 📎] [Link] [Emoji] [Drive] [🗑️]"
        ),
        interaction_sequence=["to_field", "subject", "body", "send_btn"],
    )

    graph.nodes["to_field"] = UINode(
        id="to_field", label="To",
        node_type=NodeType.INPUT,
        selector_hints={"placeholder": "Recipients", "aria": "To recipients", "tag": "input"},
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the To field"),
            UIAction(ActionType.TYPE, {"press_enter": True},
                     "Type email, press Enter. Repeat per recipient."),
        ],
        required=True, order=1,
        notes="Top of compose window. Type email and press Enter/Tab to add.",
    )

    graph.nodes["subject"] = UINode(
        id="subject", label="Subject",
        node_type=NodeType.INPUT,
        selector_hints={"placeholder": "Subject", "tag": "input", "aria": "Subject"},
        actions=[UIAction(ActionType.TYPE, {"press_enter": False}, "Type subject line")],
        required=True, order=2,
        notes="Below the To field. Extract subject from user instruction.",
    )

    graph.nodes["body"] = UINode(
        id="body", label="Body",
        node_type=NodeType.INPUT,
        selector_hints={"aria": "Message Body", "tag": "div", "contenteditable": "true"},
        actions=[
            UIAction(ActionType.CLICK, {}, "Click body area"),
            UIAction(ActionType.TYPE, {"press_enter": False}, "Type email body"),
        ],
        order=3,
        notes="Large text area below subject. Rich text editor.",
    )

    graph.nodes["send_btn"] = UINode(
        id="send_btn", label="Send",
        node_type=NodeType.BUTTON,
        selector_hints={"text": "Send", "tag": "div", "aria": "Send"},
        actions=[UIAction(ActionType.CLICK, {}, "Click Send button")],
        required=True, order=4,
        notes="Blue button at bottom-left of compose window. Verify 'Message sent' toast appears.",
    )

    return graph
