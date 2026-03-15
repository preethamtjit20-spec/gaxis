"""Google Docs Editor — semantic UI graph.

Built from the actual Google Docs editor page layout:
  docs.google.com/document/.../edit
  docs.google.com/document/create
"""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gdocs_editor",
        name="Google Docs — Document Editor",
        url_pattern=r"docs\.google\.com/document/.*/edit|docs\.google\.com/document/create",
        entry_node="title",
        terminal_nodes=["auto_save"],
        layout_description=(
            "TOP BAR:  [☰] [Document title ___________] [☆ Star] [📁 Move] [☁️ Saved]\n"
            "MENU BAR: File  Edit  View  Insert  Format  Tools  Extensions  Help\n"
            "TOOLBAR:  [B] [I] [U] [Color] | [Font ▼] [Size ▼] | [Normal text ▼] | align | ...\n"
            "──────────────────────────────────────────────────────────────────────\n"
            "           ┌─────────────────────────────────────────────┐\n"
            "           │                                             │\n"
            "           │    (Main document body / canvas)            │\n"
            "           │    Click anywhere to type                   │\n"
            "           │                                             │\n"
            "           └─────────────────────────────────────────────┘\n"
            "TOP-RIGHT: [Share 🔵] button"
        ),
        interaction_sequence=[
            "title",
            "body",
            "auto_save",
        ],
    )

    # ── NODES ──────────────────────────────────────────────

    graph.nodes["title"] = UINode(
        id="title",
        label="Document title",
        node_type=NodeType.INPUT,
        selector_hints={
            "tag": "input",
            "placeholder": "Untitled document",
            "aria": "Rename",
            "class": "docs-title-input",
            "region": "top_bar",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the 'Untitled document' text at the top-left"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type the document title"),
            UIAction(ActionType.PRESS_KEY, {"key": "Tab"},
                     "Press Tab to confirm the title and move to body"),
        ],
        required=True,
        order=1,
        notes=(
            "At the VERY TOP-LEFT of the page, above the menu bar (File, Edit, View...). "
            "Shows 'Untitled document' for new docs. Click it to make it editable. "
            "Type the new title with clear_first=true. Press Tab to confirm. "
            "NEVER type content here — this is ONLY for the document name."
        ),
    )

    graph.nodes["body"] = UINode(
        id="body",
        label="Document body",
        node_type=NodeType.INPUT,
        selector_hints={
            "tag": "div",
            "contenteditable": "true",
            "aria": "Document content",
            "class": "kix-appview-editor",
            "region": "center",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the large white page area below the toolbar"),
            UIAction(ActionType.TYPE, {"press_enter": False},
                     "Type the document content"),
        ],
        required=True,
        order=2,
        notes=(
            "Large white page area below the formatting toolbar. This is the main "
            "rich text editing canvas. Click anywhere in it to place cursor, then type. "
            "For headings: type text, select it, use Ctrl+Alt+1 for H1, Ctrl+Alt+2 for H2. "
            "For bold: Ctrl+B. For bullet lists: type '- ' at line start. "
            "Google Docs auto-saves — there is NO save button."
        ),
    )

    graph.nodes["auto_save"] = UINode(
        id="auto_save",
        label="Auto-save indicator",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Saving...",
            "region": "top_bar",
        },
        actions=[
            UIAction(ActionType.WAIT, {"seconds": 3},
                     "Wait for auto-save to complete"),
        ],
        required=True,
        order=3,
        notes=(
            "Google Docs auto-saves. Look near the title for 'Saving...' to change "
            "to a saved state (timestamp or cloud icon). Wait 3 seconds after typing "
            "to ensure content is saved. There is NO explicit save button."
        ),
    )

    graph.nodes["heading_style"] = UINode(
        id="heading_style",
        label="Normal text (style dropdown)",
        node_type=NodeType.DROPDOWN,
        selector_hints={
            "text": "Normal text",
            "aria": "Styles",
            "region": "toolbar",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the 'Normal text' dropdown in toolbar"),
            UIAction(ActionType.CLICK, {}, "Select Heading 1, Heading 2, etc."),
        ],
        order=4,
        notes=(
            "Dropdown in the toolbar showing 'Normal text'. Click to see options: "
            "Title, Subtitle, Heading 1-6, Normal text. "
            "Shortcut: Ctrl+Alt+1 for H1, Ctrl+Alt+2 for H2."
        ),
    )

    graph.nodes["share_btn"] = UINode(
        id="share_btn",
        label="Share",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Share",
            "tag": "button",
            "region": "top_right",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the blue Share button at top-right"),
        ],
        order=5,
        notes=(
            "Blue button at the top-right corner. Opens the Share dialog where you "
            "can add people, change permissions, and copy the link."
        ),
    )

    # ── EDGES ──────────────────────────────────────────────

    graph.edges = [
        UIEdge(
            source="title",
            target="body",
            action=ActionType.PRESS_KEY,
            description="After setting title, Tab moves focus to body",
        ),
        UIEdge(
            source="body",
            target="auto_save",
            action=ActionType.WAIT,
            description="After typing content, wait for auto-save",
        ),
    ]

    return graph
