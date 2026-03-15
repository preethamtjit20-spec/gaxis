"""Google Sheets connector — create, read, and update spreadsheets.

Provides precise, step-by-step browser instructions for:
- Create spreadsheet
- Read spreadsheet
- Update spreadsheet

Each skill maps the exact Google Sheets UI layout so the navigator
never types into the wrong field or clicks the wrong element.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


# ─── UI LAYOUT REFERENCE (shared across skills) ───────────────────
# Google Sheets layout (https://sheets.new or docs.google.com/spreadsheets):
#
# ┌────────────────────────────────────────────────────────────────────┐
# │  ☰  [Untitled spreadsheet]   ☆   📁  ☁️ Saved                     │
# │  File  Edit  View  Insert  Format  Data  Tools  Extensions  Help  │
# │  🔧 Toolbar: [Undo][Redo] | font | size | B I S | color | fill | │
# │         borders | merge | align | wrap | more...                   │
# │  ─────────────────────────────────────────────────────────────────│
# │  Name Box [A1▼]  fx  [ Formula Bar __________________________ ]   │
# │  ─────────────────────────────────────────────────────────────────│
# │     A          B          C          D          E      ...        │
# │  1  [        ] [        ] [        ] [        ] [        ]        │
# │  2  [        ] [        ] [        ] [        ] [        ]        │
# │  3  [        ] [        ] [        ] [        ] [        ]        │
# │  ...                                                               │
# │  ─────────────────────────────────────────────────────────────────│
# │  [Sheet1 ▼] [Sheet2 ▼]  [+]                          ◄ ► scrollbar│
# └────────────────────────────────────────────────────────────────────┘
#
# Key UI elements:
#   Title:       "Untitled spreadsheet" text at top-left, click to rename
#   Name Box:    Shows current cell reference (e.g. "A1"), left of formula bar
#   Formula Bar: Shows/edits content of selected cell, marked with "fx"
#   Cell Grid:   Columns A-Z+ across top, rows 1-999+ down left side
#   Sheet Tabs:  Bottom bar — Sheet1, Sheet2, etc.; [+] adds new sheet
#   Cell entry:  Click cell → type → Tab (move right) or Enter (move down)
#   Navigation:  Click Name Box, type cell ref (e.g. "B5"), press Enter to jump


class GoogleSheetsConnector(BaseConnector):
    name = "google_sheets"
    description = "Google Sheets — create, read, and update spreadsheets"
    icon = "sheets"
    category = "productivity"

    def _setup(self) -> None:
        self._register_create_spreadsheet()
        self._register_read_spreadsheet()
        self._register_update_spreadsheet()

    # ────────────────────────────────────────────────
    #  CREATE SPREADSHEET
    # ────────────────────────────────────────────────

    def _register_create_spreadsheet(self) -> None:
        self.register_skill(Skill(
            name="create_spreadsheet",
            description="Create a new Google Sheets spreadsheet with optional headers and data",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://sheets.new",
            browser_template=(
                "Navigate to https://sheets.new\n\n"

                "PAGE LAYOUT — memorize this before acting:\n"
                "  TOP-LEFT:       'Untitled spreadsheet' title — click to rename\n"
                "  MENU BAR:       File, Edit, View, Insert, Format, Data, Tools, Extensions, Help\n"
                "  TOOLBAR:        Formatting buttons (bold, italic, font, size, color, etc.)\n"
                "  NAME BOX:       Shows current cell (e.g. 'A1'), left of formula bar\n"
                "  FORMULA BAR:    Labeled 'fx', shows selected cell content\n"
                "  CELL GRID:      Columns A, B, C... across top; rows 1, 2, 3... down left\n"
                "  SHEET TABS:     Bottom bar — 'Sheet1', [+] button to add sheets\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — WAIT FOR LOAD:\n"
                "  wait(seconds=3, reason='Waiting for new spreadsheet to fully load')\n"
                "  Confirm you see 'Untitled spreadsheet' at the top-left and an empty grid.\n\n"

                "Step 2 — RENAME TITLE:\n"
                "  Click on the text 'Untitled spreadsheet' at the top-left of the page.\n"
                "  It will become an editable text input.\n"
                "  type_text(x, y, text='{title}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=1, reason='Waiting for title to save')\n\n"

                "Step 3 — VERIFY TITLE:\n"
                "  Confirm the title now shows '{title}' at the top-left (not 'Untitled spreadsheet').\n"
                "  If it still says 'Untitled spreadsheet', click it again and retype.\n\n"

                "Step 4 — SET UP CONTENT:\n"
                "  {setup_instruction}\n\n"

                "  DATA ENTRY RULES:\n"
                "  - To select a specific cell: click the Name Box (shows e.g. 'A1'), type the cell\n"
                "    reference (e.g. 'A1'), press Enter. Then type the cell value.\n"
                "  - Alternative: click directly on the target cell in the grid.\n"
                "  - After typing a cell value, press Tab to move right to the next column,\n"
                "    or press Enter to move down to the next row.\n"
                "  - For headers: click cell A1, type first header, press Tab, type second header,\n"
                "    press Tab, and so on. Press Enter after the last header to drop to the next row.\n"
                "  - For data rows: after headers, click cell A2 (first data row). Type value, Tab\n"
                "    to next column. After last column, press Enter to start next row.\n"
                "  - For formulas: type the formula starting with '=' (e.g. '=SUM(A2:A10)').\n"
                "  - To bold headers: select the header row (click row number '1' on the left),\n"
                "    then press Ctrl+B (or Cmd+B on Mac).\n\n"

                "Step 5 — WAIT FOR AUTO-SAVE:\n"
                "  wait(seconds=2, reason='Waiting for Google Sheets to auto-save')\n"
                "  Check for '☁️ All changes saved in Drive' or similar status near the title.\n\n"

                "Step 6 — VERIFY:\n"
                "  Confirm the title reads '{title}'.\n"
                "  Confirm any headers/data from Step 4 are visible in the cells.\n"
                "  ONLY call task_complete if BOTH the title and content are correct.\n"
                "  If the title is wrong, click it and rename. If data is missing, enter it.\n\n"

                "RULES:\n"
                "- Title is at the TOP-LEFT above the menu bar. NEVER type the title into a cell.\n"
                "- Cell A1 is the top-left cell of the GRID (below the formula bar).\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Use Tab to move right between columns, Enter to move down between rows.\n"
                "- Google Sheets auto-saves — do NOT look for a Save button."
            ),
            params=[
                SkillParam(name="title", description="Spreadsheet title"),
                SkillParam(
                    name="setup_instruction",
                    description=(
                        "What to put in the spreadsheet — be specific about cell locations. "
                        "E.g. 'Click cell A1, type \"Date\", press Tab. Type \"Description\", press Tab. "
                        "Type \"Amount\", press Enter. Click A2, type \"03/11/2026\", Tab, "
                        "type \"Groceries\", Tab, type \"52.30\", Enter.'"
                    ),
                    required=False,
                    default="Leave the spreadsheet empty — no data to enter.",
                ),
            ],
            tags=["sheets", "spreadsheet", "create", "new", "table", "data"],
            examples=[
                "Create a budget spreadsheet with columns for Date, Description, and Amount",
                "Make a new tracking sheet for expenses",
                "Create a blank spreadsheet called Q1 Report",
            ],
        ))

    # ────────────────────────────────────────────────
    #  READ SPREADSHEET
    # ────────────────────────────────────────────────

    def _register_read_spreadsheet(self) -> None:
        self.register_skill(Skill(
            name="read_spreadsheet",
            description="Find and read data from an existing Google Sheets spreadsheet",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com",
            browser_template=(
                "Navigate to https://drive.google.com\n\n"

                "PAGE LAYOUT — Google Drive:\n"
                "  TOP:            Search bar ('Search in Drive')\n"
                "  LEFT SIDEBAR:   My Drive, Shared with me, Recent, Starred, Trash\n"
                "  MAIN AREA:      File list / grid of documents\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — SEARCH FOR SPREADSHEET:\n"
                "  Click the search bar at the top of Google Drive ('Search in Drive').\n"
                "  type_text(x, y, text='{name}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n\n"

                "Step 2 — OPEN THE SPREADSHEET:\n"
                "  Look for a file named '{name}' in the search results.\n"
                "  It should have the green Google Sheets icon (grid/table icon).\n"
                "  Double-click on the file to open it.\n"
                "  wait(seconds=3, reason='Waiting for spreadsheet to load')\n\n"

                "Step 3 — CONFIRM SPREADSHEET LOADED:\n"
                "  Verify you are now in Google Sheets:\n"
                "  - The title '{name}' (or similar) should appear at the top-left.\n"
                "  - You should see the cell grid with column headers (A, B, C...) and row numbers.\n"
                "  - The formula bar ('fx') should be visible.\n"
                "  If the spreadsheet did not open, go back and try double-clicking again.\n\n"

                "Step 4 — NAVIGATE TO TARGET RANGE:\n"
                "  Target data: {range_description}\n\n"
                "  NAVIGATION TECHNIQUES:\n"
                "  - To jump to a cell: click the Name Box (shows e.g. 'A1' at top-left of grid),\n"
                "    type the target cell reference (e.g. 'A1' or 'D15'), press Enter.\n"
                "  - To see all data: press Ctrl+Home (Cmd+Home on Mac) to go to A1, then\n"
                "    press Ctrl+End (Cmd+End on Mac) to find the last cell with data.\n"
                "  - To view a different sheet tab: click the sheet tab name at the bottom\n"
                "    (e.g. 'Sheet1', 'Sheet2').\n"
                "  - Scroll down/right if the data extends beyond the visible area.\n\n"

                "Step 5 — READ THE DATA:\n"
                "  Carefully read all visible cell values in the target range.\n"
                "  For each row, read left-to-right across all columns with data.\n"
                "  Note the column headers (usually row 1) to understand what each column means.\n"
                "  If data extends below the visible area, scroll down to read all rows.\n\n"

                "Step 6 — EXTRACT DATA:\n"
                "  Use extract_data to capture the spreadsheet content as structured data.\n"
                "  Include:\n"
                "  - Column headers\n"
                "  - All data rows within the target range\n"
                "  - Any totals, formulas, or summary rows\n"
                "  - The sheet tab name if relevant\n\n"

                "Step 7 — COMPLETE:\n"
                "  Call task_complete with a summary of what was found.\n"
                "  Example: 'Read 15 rows from Budget sheet. Columns: Date, Description, Amount, Category.\n"
                "  Total rows with data: 15. Last entry: 03/10/2026 Groceries $52.30.'\n\n"

                "RULES:\n"
                "- Start from Google Drive to find the spreadsheet by name.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If the file is not found, try searching with partial name or check 'Recent' in sidebar.\n"
                "- If multiple files match, choose the one with the Google Sheets icon.\n"
                "- Read data visually from the grid — do NOT try to use keyboard shortcuts to select all."
            ),
            params=[
                SkillParam(name="name", description="Spreadsheet name to search for and open"),
                SkillParam(
                    name="range_description",
                    description=(
                        "What part of the spreadsheet to read. "
                        "E.g. 'all data', 'first 10 rows', 'columns A through C', "
                        "'the Summary sheet tab', 'cells A1:D20'"
                    ),
                    required=False,
                    default="all visible data starting from cell A1",
                ),
            ],
            tags=["sheets", "spreadsheet", "read", "data", "table", "view", "open", "find"],
            examples=[
                "Read the expense data from the budget sheet",
                "What's in my Q1 Report spreadsheet?",
                "Show me the first 10 rows of the inventory tracker",
            ],
        ))

    # ────────────────────────────────────────────────
    #  UPDATE SPREADSHEET
    # ────────────────────────────────────────────────

    def _register_update_spreadsheet(self) -> None:
        self.register_skill(Skill(
            name="update_spreadsheet",
            description="Find and update data in an existing Google Sheets spreadsheet",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com",
            browser_template=(
                "Navigate to https://drive.google.com\n\n"

                "PAGE LAYOUT — Google Sheets (once opened):\n"
                "  TITLE:          Spreadsheet name at top-left\n"
                "  NAME BOX:       Shows current cell (e.g. 'A1'), click to type a cell reference\n"
                "  FORMULA BAR:    'fx' label, shows/edits selected cell content\n"
                "  CELL GRID:      Columns A, B, C... ; Rows 1, 2, 3...\n"
                "  SHEET TABS:     Bottom — Sheet1, Sheet2, [+] to add\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — SEARCH FOR SPREADSHEET:\n"
                "  Click the search bar at the top of Google Drive ('Search in Drive').\n"
                "  type_text(x, y, text='{name}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n\n"

                "Step 2 — OPEN THE SPREADSHEET:\n"
                "  Find the file '{name}' with the green Google Sheets icon.\n"
                "  Double-click on the file to open it.\n"
                "  wait(seconds=3, reason='Waiting for spreadsheet to load')\n\n"

                "Step 3 — CONFIRM SPREADSHEET LOADED:\n"
                "  Verify the title '{name}' (or similar) at top-left.\n"
                "  Verify you see the cell grid, formula bar, and column/row headers.\n"
                "  If it did not open, go back and try again.\n\n"

                "Step 4 — ORIENT YOURSELF:\n"
                "  Before making changes, scan the current data:\n"
                "  - Read the column headers (row 1) to understand the structure.\n"
                "  - Identify the last row with data (scroll down or press Ctrl+End / Cmd+End).\n"
                "  - Note which sheet tab you are on.\n"
                "  This prevents overwriting existing data.\n\n"

                "Step 5 — MAKE CHANGES:\n"
                "  {update_instruction}\n\n"

                "  CELL EDITING RULES:\n"
                "  - To jump to a cell: click the Name Box (top-left, shows e.g. 'A1'),\n"
                "    type the target cell reference (e.g. 'A5'), press Enter.\n"
                "  - To replace cell content: click the cell, then type the new value.\n"
                "    The old content is replaced when you start typing.\n"
                "  - To edit existing content (append/modify): double-click the cell or press F2\n"
                "    to enter edit mode, then use arrow keys to position cursor.\n"
                "  - To clear a cell: click the cell, press Delete.\n"
                "  - After typing, press Tab to move right or Enter to move down.\n"
                "  - To add a new row at the end: click the first empty cell in column A\n"
                "    below the last data row, then type values using Tab between columns.\n"
                "  - For formulas: type starting with '=' (e.g. '=SUM(C2:C50)').\n"
                "  - To insert a row: right-click a row number → 'Insert 1 row above/below'.\n"
                "  - To insert a column: right-click a column letter → 'Insert 1 column left/right'.\n"
                "  - To delete a row: right-click the row number → 'Delete row'.\n\n"

                "Step 6 — WAIT FOR AUTO-SAVE:\n"
                "  wait(seconds=2, reason='Waiting for Google Sheets to auto-save')\n"
                "  Check for save confirmation near the title (cloud icon or 'All changes saved').\n\n"

                "Step 7 — VERIFY:\n"
                "  Review the cells you changed to confirm the values are correct.\n"
                "  Click on each modified cell and check the formula bar shows the expected value.\n"
                "  ONLY call task_complete if all changes are visually confirmed.\n"
                "  If any value is wrong, click the cell and retype it.\n\n"

                "RULES:\n"
                "- Start from Google Drive to find the spreadsheet by name.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- ALWAYS orient yourself (Step 4) before editing to avoid overwriting data.\n"
                "- Google Sheets auto-saves — do NOT look for a Save button.\n"
                "- If the file is not found, try partial name search or check 'Recent'.\n"
                "- When adding rows, always append BELOW existing data, not on top of it."
            ),
            params=[
                SkillParam(name="name", description="Spreadsheet name to search for and open"),
                SkillParam(
                    name="update_instruction",
                    description=(
                        "Step-by-step changes to make — be specific about cell locations. "
                        "E.g. 'Find the last row with data. Click the next empty cell in column A. "
                        "Type \"03/11/2026\", press Tab. Type \"Coffee\", press Tab. "
                        "Type \"4.50\", press Enter.' or 'Click cell C2, type \"=B2*1.1\", press Enter.'"
                    ),
                ),
            ],
            tags=["sheets", "spreadsheet", "update", "edit", "write", "data", "add", "modify", "append"],
            examples=[
                "Add today's expenses to the budget sheet",
                "Update the price in cell C5 of the inventory tracker to $29.99",
                "Add a new row with today's date and sales figures to the Q1 Report",
            ],
        ))
