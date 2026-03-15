"""Google Docs connector — create, edit, and summarize documents.

Provides precise, step-by-step browser instructions for:
- Create document (new blank doc with title and content)
- Edit document (find and modify an existing doc)
- Summarize document (read and extract structured summary)

Each skill maps the exact Google Docs UI layout so the navigator
never types into the wrong field.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


# --- UI LAYOUT REFERENCE (shared across skills) -------------------------
# Google Docs editor (https://docs.google.com/document/...):
#
# +---------------------------------------------------------------------+
# | [Docs icon] [Untitled document ___________]  [Star] [Move] [Status] |
# | File  Edit  View  Insert  Format  Tools  Extensions  Help           |
# | [B] [I] [U] [Color] | [Font ▼] [Size ▼] | [Normal text ▼] | ...   |
# | ------------------------------------------------------------------- |
# |                                                                     |
# |  +---------------------------------------------------------------+  |
# |  |                                                               |  |
# |  |              (Main document body / canvas)                    |  |
# |  |         Click anywhere to place cursor, type to add text      |  |
# |  |                                                               |  |
# |  +---------------------------------------------------------------+  |
# |                                                                     |
# +---------------------------------------------------------------------+
# |                                          [Share 🔵] button top-right |
# +---------------------------------------------------------------------+
#
# Key UI elements:
#   Title bar:    "Untitled document" text at top-left — click to rename
#   Menu bar:     File, Edit, View, Insert, Format, Tools, Extensions, Help
#   Toolbar:      Bold, Italic, Underline, font picker, size, heading styles
#   Body:         Large white page area — rich text editor canvas
#   Share button: Blue "Share" button at top-right corner
#
# Google Drive search (https://drive.google.com/drive/u/0/):
#   Search bar at top: "Search in Drive" input
#   File list below: click a doc name to open it


class GoogleDocsConnector(BaseConnector):
    name = "google_docs"
    description = "Google Docs — create, edit, and summarize documents"
    icon = "docs"
    category = "productivity"

    def _setup(self) -> None:
        self._register_create_document()
        self._register_edit_document()
        self._register_summarize_document()

    # ────────────────────────────────────────────────
    #  CREATE DOCUMENT
    # ────────────────────────────────────────────────

    def _register_create_document(self) -> None:
        self.register_skill(Skill(
            name="create_document",
            description="Create a new Google Docs document with a title and content",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://docs.google.com/document/create",
            browser_template=(
                "Navigate to https://docs.google.com/document/create (NOT docs.new — it shows a template popup).\n"
                "If a popover/template chooser appears, press Escape to dismiss it FIRST.\n\n"

                "PAGE LAYOUT — memorize this before acting:\n"
                "  TOP-LEFT:    Title field showing 'Untitled document' — click to rename\n"
                "  MENU BAR:    File, Edit, View, Insert, Format, Tools, Extensions, Help\n"
                "  TOOLBAR:     Bold, Italic, Underline, font, size, heading styles, alignment\n"
                "  BODY:        Large white page area — the main rich text editing canvas\n"
                "  TOP-RIGHT:   Blue 'Share' button\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — WAIT FOR PAGE LOAD:\n"
                "  wait(seconds=3, reason='Waiting for new document to fully load')\n"
                "  Confirm you see 'Untitled document' in the title area at top-left.\n"
                "  If the page is still loading, wait another 2 seconds.\n\n"

                "Step 2 — SET TITLE:\n"
                "  Click the 'Untitled document' text at the top-left of the page.\n"
                "  This is ABOVE the menu bar (File, Edit, View...), in the title area.\n"
                "  type_text(x, y, text='{title}', press_enter=false, clear_first=true)\n"
                "  press_key('Tab')\n"
                "  wait(seconds=1, reason='Waiting for title to be applied')\n\n"

                "Step 3 — VERIFY TITLE:\n"
                "  Check that the title area now shows '{title}' instead of 'Untitled document'.\n"
                "  If it still says 'Untitled document', click it again and retype.\n\n"

                "Step 4 — CLICK INTO DOCUMENT BODY:\n"
                "  Click the large white page area below the toolbar.\n"
                "  The cursor should appear as a blinking text cursor in the body.\n"
                "  Do NOT click the title area, menu bar, or toolbar.\n\n"

                "Step 5 — TYPE CONTENT:\n"
                "  {content_step}\n\n"

                "Step 6 — WAIT FOR AUTO-SAVE:\n"
                "  wait(seconds=3, reason='Waiting for Google Docs auto-save')\n"
                "  Look at the top of the page near the title — it should say\n"
                "  'Saving...' then change to a timestamp like 'Last edit was seconds ago'\n"
                "  or show a cloud/check icon indicating the document is saved.\n\n"

                "Step 7 — VERIFY:\n"
                "  Confirm the document title shows '{title}'.\n"
                "  Confirm the body contains the text you just typed.\n"
                "  ONLY call task_complete if BOTH the title and content are visible.\n"
                "  If something is missing, fix it before completing.\n\n"

                "RULES:\n"
                "- Title is at TOP-LEFT, above the menu bar. Body is the large white area below the toolbar.\n"
                "- NEVER type content into the title field or vice versa.\n"
                "- Google Docs auto-saves — there is NO save button. Just wait for auto-save.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If the page redirects or shows an error, wait and retry."
            ),
            params=[
                SkillParam(name="title", description="Document title (replaces 'Untitled document')"),
                SkillParam(
                    name="content_step",
                    description=(
                        "Instructions for typing content into the body. Example: "
                        "'Type the following text into the document body: <your text here>. "
                        "Press Enter for new paragraphs.' "
                        "For headings use: 'Type the heading text, select it, then click "
                        "the Normal text dropdown in the toolbar and choose Heading 1.'"
                    ),
                ),
            ],
            tags=["docs", "document", "create", "write", "new"],
            examples=[
                "Create a meeting notes document",
                "Write a project proposal in Google Docs",
                "Create a new doc called Weekly Report with bullet points",
            ],
        ))

    # ────────────────────────────────────────────────
    #  EDIT DOCUMENT
    # ────────────────────────────────────────────────

    def _register_edit_document(self) -> None:
        self.register_skill(Skill(
            name="edit_document",
            description="Open and edit an existing Google Docs document by searching in Drive",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com/drive/u/0/",
            browser_template=(
                "Navigate to https://drive.google.com/drive/u/0/\n\n"

                "PAGE LAYOUT — Google Drive:\n"
                "  TOP:         'Search in Drive' input bar\n"
                "  LEFT PANEL:  My Drive, Shared with me, Recent, Starred, Trash\n"
                "  MAIN AREA:   File and folder list\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — WAIT FOR DRIVE TO LOAD:\n"
                "  wait(seconds=3, reason='Waiting for Google Drive to load')\n"
                "  Confirm you see the 'Search in Drive' bar at the top.\n\n"

                "Step 2 — SEARCH FOR DOCUMENT:\n"
                "  Click the 'Search in Drive' input at the top of the page.\n"
                "  type_text(x, y, text='{name}', press_enter=true)\n"
                "  wait(seconds=3, reason='Waiting for search results to appear')\n\n"

                "Step 3 — OPEN THE DOCUMENT:\n"
                "  Look through the search results for a Google Docs file matching '{name}'.\n"
                "  Google Docs files have a blue document icon.\n"
                "  Double-click the matching document to open it.\n"
                "  If multiple results appear, choose the most recently modified one.\n"
                "  If no results found, call task_complete with an error message.\n\n"

                "Step 4 — WAIT FOR DOCUMENT TO LOAD:\n"
                "  wait(seconds=3, reason='Waiting for Google Docs editor to load')\n"
                "  Confirm you see the Google Docs editor with the menu bar\n"
                "  (File, Edit, View, Insert, Format, Tools, Extensions, Help)\n"
                "  and the document body below the toolbar.\n\n"

                "Step 5 — MAKE EDITS:\n"
                "  {edit_instruction}\n\n"

                "  EDITING REFERENCE — use these techniques as needed:\n"
                "  - To append text: click at the END of the document body, then type.\n"
                "  - To prepend text: click at the BEGINNING of the document body, then type.\n"
                "  - To find specific text: press Ctrl+F (or Cmd+F on Mac) to open Find bar,\n"
                "    type the search text, press Enter to locate it, press Escape to close Find.\n"
                "  - To replace text: press Ctrl+H (or Cmd+H on Mac) to open Find & Replace,\n"
                "    type the old text in 'Find', new text in 'Replace with', click 'Replace' or 'Replace all'.\n"
                "  - To select text: click at start position, hold Shift, click at end position.\n"
                "  - To select all: press Ctrl+A (or Cmd+A on Mac).\n"
                "  - To delete selected text: press Backspace or Delete after selecting.\n"
                "  - To apply heading: select text, click 'Normal text' dropdown in toolbar,\n"
                "    choose Heading 1, Heading 2, etc.\n"
                "  - To bold/italic/underline: select text, then click B/I/U in toolbar\n"
                "    or press Ctrl+B / Ctrl+I / Ctrl+U.\n"
                "  - To add a comment: select text, press Ctrl+Alt+M, type comment, click 'Comment'.\n"
                "  - To insert a link: select text, press Ctrl+K, paste URL, press Enter.\n\n"

                "Step 6 — WAIT FOR AUTO-SAVE:\n"
                "  wait(seconds=3, reason='Waiting for Google Docs auto-save')\n"
                "  Look near the title for 'Saving...' to change to a saved state.\n\n"

                "Step 7 — VERIFY:\n"
                "  Confirm the edits are visible in the document body.\n"
                "  ONLY call task_complete if you can SEE the changes in the document.\n"
                "  If changes are not visible, retry the edit.\n\n"

                "RULES:\n"
                "- Google Docs auto-saves — there is NO save button. Just wait for auto-save.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- NEVER click the title area unless you are renaming the document.\n"
                "- Use clear_first=true only when replacing an entire field, not for body edits.\n"
                "- If the document is read-only, look for 'Request edit access' or notify the user."
            ),
            params=[
                SkillParam(name="name", description="Document name to search for in Google Drive"),
                SkillParam(
                    name="edit_instruction",
                    description=(
                        "Detailed editing instructions. Examples: "
                        "'Append the following paragraph at the end of the document: <text>.' "
                        "'Find the sentence starting with X and replace it with Y.' "
                        "'Add a new Heading 2 section called Results at the bottom.'"
                    ),
                ),
            ],
            tags=["docs", "document", "edit", "update", "modify", "change", "write"],
            examples=[
                "Update the project plan document with new deadlines",
                "Add a new section to the meeting notes document",
                "Replace the introduction paragraph in my proposal",
                "Add a comment to the budget report",
            ],
        ))

    # ────────────────────────────────────────────────
    #  SUMMARIZE DOCUMENT
    # ────────────────────────────────────────────────

    def _register_summarize_document(self) -> None:
        self.register_skill(Skill(
            name="summarize_document",
            description="Open a Google Doc and summarize its contents with structured extraction",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com/drive/u/0/",
            browser_template=(
                "Navigate to https://drive.google.com/drive/u/0/\n\n"

                "PAGE LAYOUT — Google Drive:\n"
                "  TOP:         'Search in Drive' input bar\n"
                "  LEFT PANEL:  My Drive, Shared with me, Recent, Starred, Trash\n"
                "  MAIN AREA:   File and folder list\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — WAIT FOR DRIVE TO LOAD:\n"
                "  wait(seconds=3, reason='Waiting for Google Drive to load')\n"
                "  Confirm you see the 'Search in Drive' bar at the top.\n\n"

                "Step 2 — SEARCH FOR DOCUMENT:\n"
                "  Click the 'Search in Drive' input at the top of the page.\n"
                "  type_text(x, y, text='{name}', press_enter=true)\n"
                "  wait(seconds=3, reason='Waiting for search results to appear')\n\n"

                "Step 3 — OPEN THE DOCUMENT:\n"
                "  Look through the search results for a Google Docs file matching '{name}'.\n"
                "  Google Docs files have a blue document icon.\n"
                "  Double-click the matching document to open it.\n"
                "  If multiple results appear, choose the most recently modified one.\n"
                "  If no results found, call task_complete with an error message.\n\n"

                "Step 4 — WAIT FOR DOCUMENT TO LOAD:\n"
                "  wait(seconds=3, reason='Waiting for Google Docs editor to load')\n"
                "  Confirm you see the Google Docs editor with the document content.\n\n"

                "Step 5 — GET WORD COUNT (optional context):\n"
                "  Click the 'Tools' menu in the menu bar.\n"
                "  Click 'Word count' in the dropdown.\n"
                "  Note the page count, word count, and character count.\n"
                "  Click 'OK' or press Escape to close the dialog.\n\n"

                "Step 6 — READ THE FULL DOCUMENT:\n"
                "  Scroll through the ENTIRE document from top to bottom.\n"
                "  For long documents, use Page Down or scroll repeatedly.\n"
                "  For each section/page, read and note:\n"
                "  - Document title (shown in the title bar at top-left)\n"
                "  - Headings and subheadings (larger/bold text)\n"
                "  - Key paragraphs and bullet points\n"
                "  - Tables, images, or embedded content (note their presence)\n"
                "  - Any action items, decisions, or important dates\n"
                "  Continue scrolling until you reach the very end of the document.\n\n"

                "Step 7 — EXTRACT STRUCTURED DATA:\n"
                "  Use extract_data to capture:\n"
                "  - title: document title\n"
                "  - word_count: from Step 5 (if obtained)\n"
                "  - sections: list of section headings with brief descriptions\n"
                "  - key_points: the most important facts, decisions, or takeaways\n"
                "  - action_items: any tasks or follow-ups mentioned\n"
                "  - people_mentioned: names of people referenced in the doc\n"
                "  - dates_mentioned: any dates or deadlines noted\n\n"

                "Step 8 — COMPLETE:\n"
                "  Call task_complete with a structured summary like:\n"
                "  'Document: {name} (~1,200 words, 3 pages)\n"
                "   Sections: Introduction, Analysis, Recommendations\n"
                "   Key points: 1) ... 2) ... 3) ...\n"
                "   Action items: - Task A (owner) - Task B (owner)\n"
                "   Dates: March 15 deadline for X, April 1 review for Y'\n\n"

                "RULES:\n"
                "- Scroll through the ENTIRE document. Do not summarize after reading only the first page.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT edit the document. This is read-only.\n"
                "- If the document is very long (10+ pages), focus on headings, first/last\n"
                "  paragraphs of each section, and any bold/highlighted text.\n"
                "- If the document is empty, call task_complete noting it is blank."
            ),
            params=[
                SkillParam(name="name", description="Document name to search for in Google Drive"),
            ],
            tags=["docs", "document", "read", "summarize", "extract", "summary", "review"],
            examples=[
                "Summarize the meeting notes from last week",
                "What does the project proposal document say?",
                "Give me a summary of the Q1 report",
                "Read the design doc and list the key decisions",
            ],
        ))
