"""Google Sheets Editor — semantic UI graph.

Built from the actual Google Sheets editor page layout:
  docs.google.com/spreadsheets/.../edit
"""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gsheets_editor",
        name="Google Sheets — Spreadsheet Editor",
        url_pattern=r"docs\.google\.com/spreadsheets/.*/edit",
        entry_node="title",
        terminal_nodes=["auto_save"],
        layout_description=(
            "TOP BAR:    [☰] [Spreadsheet title ___________] [☆] [📁] [☁️ Saved]\n"
            "MENU BAR:   File  Edit  View  Insert  Format  Data  Tools  Extensions  Help\n"
            "TOOLBAR:    [Undo][Redo] | font | size | B I S | color | fill | borders | merge\n"
            "NAME BOX:   [A1 ▼]  fx  [ Formula Bar _________________________________ ]\n"
            "──────────────────────────────────────────────────────────────────────\n"
            "     A          B          C          D          E      ...\n"
            "  1  [        ] [        ] [        ] [        ] [        ]\n"
            "  2  [        ] [        ] [        ] [        ] [        ]\n"
            "  3  [        ] [        ] [        ] [        ] [        ]\n"
            "  ...\n"
            "──────────────────────────────────────────────────────────────────────\n"
            "BOTTOM: [Sheet1 ▼] [Sheet2 ▼] [+]                      ◄ ► scrollbar"
        ),
        interaction_sequence=[
            "title",
            "cell_grid",
            "auto_save",
        ],
    )

    # ── NODES ──────────────────────────────────────────────

    graph.nodes["title"] = UINode(
        id="title",
        label="Spreadsheet title",
        node_type=NodeType.INPUT,
        selector_hints={
            "tag": "input",
            "placeholder": "Untitled spreadsheet",
            "aria": "Rename",
            "region": "top_bar",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click 'Untitled spreadsheet' at the top-left"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type the spreadsheet title"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"},
                     "Press Enter to confirm the title"),
        ],
        required=True,
        order=1,
        notes=(
            "At the VERY TOP-LEFT, above the menu bar. Shows 'Untitled spreadsheet' "
            "for new sheets. Click to make editable, type new name, press Enter. "
            "NEVER type data here — this is ONLY for the spreadsheet name."
        ),
    )

    graph.nodes["name_box"] = UINode(
        id="name_box",
        label="Name Box (cell reference)",
        node_type=NodeType.INPUT,
        selector_hints={
            "text": "A1",
            "aria": "Name Box",
            "region": "below_toolbar",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the Name Box (shows cell ref like 'A1')"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type target cell reference (e.g. 'A1', 'B5')"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"},
                     "Press Enter to navigate to the cell"),
        ],
        order=2,
        notes=(
            "Small box at the left of the formula bar, showing the current cell "
            "reference (e.g. 'A1'). Click it, type a cell reference, press Enter "
            "to jump to that cell. Useful for navigating to specific cells."
        ),
    )

    graph.nodes["formula_bar"] = UINode(
        id="formula_bar",
        label="Formula Bar",
        node_type=NodeType.INPUT,
        selector_hints={
            "aria": "Formula Bar",
            "tag": "div",
            "region": "below_toolbar",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the formula bar (to the right of 'fx')"),
            UIAction(ActionType.TYPE, {"press_enter": False},
                     "Type cell value or formula"),
        ],
        order=3,
        notes=(
            "Long input area to the right of the Name Box, marked with 'fx'. "
            "Shows the content of the selected cell. Can type formulas here "
            "(starting with '='). Press Enter to confirm."
        ),
    )

    graph.nodes["cell_grid"] = UINode(
        id="cell_grid",
        label="Cell grid",
        node_type=NodeType.INPUT,
        selector_hints={
            "tag": "div",
            "class": "grid",
            "region": "center",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click a cell in the grid to select it"),
            UIAction(ActionType.TYPE, {"press_enter": False},
                     "Type cell value"),
            UIAction(ActionType.PRESS_KEY, {"key": "Tab"},
                     "Press Tab to move right, Enter to move down"),
        ],
        required=True,
        order=4,
        notes=(
            "Main grid area with columns A, B, C... and rows 1, 2, 3... "
            "Click a cell to select it, then type. Tab moves right to next column. "
            "Enter moves down to next row. For headers: click A1, type first header, "
            "press Tab, type next header. After last header, press Enter to go to row 2."
        ),
    )

    graph.nodes["auto_save"] = UINode(
        id="auto_save",
        label="Auto-save indicator",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "All changes saved",
            "region": "top_bar",
        },
        actions=[
            UIAction(ActionType.WAIT, {"seconds": 2},
                     "Wait for auto-save to complete"),
        ],
        required=True,
        order=5,
        notes=(
            "Google Sheets auto-saves. Check for '☁️ All changes saved in Drive' "
            "or similar status near the title. Wait 2 seconds after typing to ensure "
            "content is saved. There is NO explicit save button."
        ),
    )

    graph.nodes["sheet_tab"] = UINode(
        id="sheet_tab",
        label="Sheet tabs",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Sheet1",
            "region": "bottom_bar",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click a sheet tab to switch sheets"),
        ],
        order=6,
        notes=(
            "Tab buttons at the bottom of the page: Sheet1, Sheet2, etc. "
            "Click to switch between sheets. [+] button adds a new sheet. "
            "Right-click a tab for rename, delete, duplicate options."
        ),
    )

    # ── EDGES ──────────────────────────────────────────────

    graph.edges = [
        UIEdge(
            source="title",
            target="cell_grid",
            action=ActionType.PRESS_KEY,
            description="After setting title, Enter confirms and focus moves to grid",
        ),
        UIEdge(
            source="cell_grid",
            target="auto_save",
            action=ActionType.WAIT,
            description="After entering data, wait for auto-save",
        ),
        UIEdge(
            source="name_box",
            target="cell_grid",
            action=ActionType.PRESS_KEY,
            description="Typing cell ref and pressing Enter navigates to that cell",
        ),
    ]

    return graph
