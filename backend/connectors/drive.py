"""Google Drive connector — search files, create folders, and share.

Provides precise, step-by-step browser instructions for:
- Search files
- Create folder
- Share file

Each skill maps the exact Google Drive UI layout so the navigator
never clicks the wrong element.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


# ─── UI LAYOUT REFERENCE (shared across skills) ──────────────────
# Google Drive (https://drive.google.com):
#
# ┌────────────────────────────────────────────────────────────────┐
# │  [≡]  Drive   [🔍 Search in Drive ________________________]   │
# │                                                                │
# │  SIDEBAR (left)          │  FILE LIST (center/right)          │
# │  ┌──────────────────┐    │  ┌──────────────────────────────┐  │
# │  │ [+ New] button   │    │  │ Name | Owner | Modified | Size│  │
# │  │ My Drive         │    │  │ file1.pdf   me   Mar 10  2MB │  │
# │  │ Shared with me   │    │  │ folder1/    me   Mar 9   —   │  │
# │  │ Recent           │    │  │ doc2.docx   me   Mar 8   1MB │  │
# │  │ Starred          │    │  └──────────────────────────────┘  │
# │  │ Trash            │    │                                     │
# │  └──────────────────┘    │                                     │
# └────────────────────────────────────────────────────────────────┘
#
# "+ New" dropdown menu items:
#   New folder | File upload | Folder upload | ─── |
#   Google Docs | Google Sheets | Google Slides | Google Forms
#
# Right-click context menu on a file:
#   Open with | Share | Get link | Move to | Add shortcut |
#   Rename | Make a copy | Download | Organize | Remove
#
# Share dialog:
#   ┌────────────────────────────────────────────────┐
#   │  Share "filename"                               │
#   │  [Add people, groups, and calendar events ___]  │
#   │  [Permission dropdown: Viewer ▼]                │
#   │  [Send]  [Copy link]                            │
#   └────────────────────────────────────────────────┘


class GoogleDriveConnector(BaseConnector):
    name = "google_drive"
    description = "Google Drive — search files, create folders, and share"
    icon = "drive"
    category = "productivity"

    def _setup(self) -> None:
        self._register_search_files()
        self._register_create_folder()
        self._register_share_file()

    # ────────────────────────────────────────────────
    #  SEARCH FILES
    # ────────────────────────────────────────────────

    def _register_search_files(self) -> None:
        self.register_skill(Skill(
            name="search_files",
            description="Search for files in Google Drive by name, type, or content",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com/drive/u/0/my-drive",
            browser_template=(
                "Navigate to https://drive.google.com/drive/u/0/my-drive\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  TOP BAR:     Search bar at top center ('Search in Drive')\n"
                "  SIDEBAR:     My Drive, Shared with me, Recent, Starred, Trash\n"
                "  FILE LIST:   Center area with columns: Name, Owner, Last modified, File size\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — CLICK SEARCH BAR:\n"
                "  Click the search bar at the top center of the page.\n"
                "  It contains placeholder text 'Search in Drive'.\n"
                "  The search bar is in the top navigation area, NOT the sidebar.\n\n"

                "Step 2 — TYPE QUERY:\n"
                "  type_text(x, y, text='{query}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter')\n\n"

                "Step 3 — WAIT FOR RESULTS:\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n\n"

                "Step 4 — READ RESULTS:\n"
                "  Examine the file list area. For EACH file found, extract:\n"
                "  - File name (with extension)\n"
                "  - File type (document, spreadsheet, folder, PDF, etc.)\n"
                "  - Owner\n"
                "  - Last modified date\n"
                "  - File size (if shown)\n"
                "  If no results appear, note 'No files found for this query.'\n\n"

                "Step 5 — EXTRACT DATA:\n"
                "  Use extract_data to capture the structured file list.\n\n"

                "Step 6 — COMPLETE:\n"
                "  Call task_complete with a summary like:\n"
                "  'Found 4 files matching \"{query}\": Q4 Report.pdf (2MB, modified Mar 10), "
                "Budget 2026.xlsx (500KB, modified Mar 8), ...'\n"
                "  If no files were found, say: 'No files found matching \"{query}\" in Google Drive.'\n\n"

                "RULES:\n"
                "- The search bar is at the TOP CENTER, not in the sidebar.\n"
                "- Always use clear_first=true in the search bar to replace any existing query.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If the page shows a CAPTCHA or login screen, report it and stop."
            ),
            params=[
                SkillParam(name="query", description="File search query (e.g. 'Q4 report', 'budget spreadsheet', 'type:pdf')"),
            ],
            tags=["drive", "files", "search", "find", "documents"],
            examples=[
                "Find the Q4 report in Drive",
                "Search for presentation files",
                "Look for files shared with me recently",
            ],
        ))

    # ────────────────────────────────────────────────
    #  CREATE FOLDER
    # ────────────────────────────────────────────────

    def _register_create_folder(self) -> None:
        self.register_skill(Skill(
            name="create_folder",
            description="Create a new folder in Google Drive",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com/drive/u/0/my-drive",
            browser_template=(
                "Navigate to https://drive.google.com/drive/u/0/my-drive\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  SIDEBAR:     '+ New' button at top-left of sidebar\n"
                "  DROPDOWN:    Clicking '+ New' opens a menu with: New folder, File upload,\n"
                "               Folder upload, Google Docs, Google Sheets, Google Slides, Google Forms\n"
                "  DIALOG:      'New folder' opens a dialog with a text input and 'Create' button\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — CLICK '+ New' BUTTON:\n"
                "  Click the '+ New' button in the top-left area of the sidebar.\n"
                "  It is a prominent button with a '+' icon, usually with colored background.\n"
                "  DO NOT right-click in the file list — use the '+ New' button.\n\n"

                "Step 2 — SELECT 'New folder':\n"
                "  A dropdown menu appears. Click 'New folder' — it is the FIRST item in the dropdown.\n"
                "  Do NOT click 'File upload' or 'Folder upload' or any Google Docs option.\n\n"

                "Step 3 — WAIT FOR DIALOG:\n"
                "  wait(seconds=1, reason='Waiting for New folder dialog to appear')\n"
                "  A dialog box should appear with a text input field pre-filled with 'Untitled folder'.\n\n"

                "Step 4 — TYPE FOLDER NAME:\n"
                "  Click the text input field in the dialog.\n"
                "  The field should contain 'Untitled folder' — it may already be selected.\n"
                "  type_text(x, y, text='{folder_name}', press_enter=false, clear_first=true)\n\n"

                "Step 5 — CLICK 'Create':\n"
                "  Click the 'Create' button in the dialog.\n"
                "  Do NOT press Enter — click the 'Create' button explicitly.\n\n"

                "Step 6 — WAIT FOR CREATION:\n"
                "  wait(seconds=3, reason='Waiting for folder to be created and appear in file list')\n\n"

                "Step 7 — VERIFY:\n"
                "  Check the file list. The folder '{folder_name}' MUST be visible.\n"
                "  ONLY call task_complete if you SEE the folder in the file list.\n"
                "  If the dialog is still open, click 'Create' again.\n"
                "  If you see an error message, report it.\n\n"

                "Step 8 — COMPLETE:\n"
                "  Call task_complete with confirmation:\n"
                "  'Created folder \"{folder_name}\" in My Drive.'\n\n"

                "RULES:\n"
                "- Use the '+ New' BUTTON in the sidebar, not right-click context menu.\n"
                "- The folder name field has 'Untitled folder' by default — always use clear_first=true.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If the dialog does not appear after clicking '+ New', try clicking it again.\n"
                "- If the '+ New' button is not visible, scroll the sidebar up."
            ),
            params=[
                SkillParam(name="folder_name", description="Name for the new folder"),
            ],
            tags=["drive", "folder", "create", "organize", "new"],
            examples=[
                "Create a folder called Project Files",
                "Make a new folder named Q1 Reports in Drive",
            ],
        ))

    # ────────────────────────────────────────────────
    #  SHARE FILE
    # ────────────────────────────────────────────────

    def _register_share_file(self) -> None:
        self.register_skill(Skill(
            name="share_file",
            description="Share a file or folder from Google Drive with another person",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://drive.google.com/drive/u/0/my-drive",
            browser_template=(
                "Navigate to https://drive.google.com/drive/u/0/my-drive\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  SEARCH BAR:       Top center ('Search in Drive')\n"
                "  FILE LIST:        Center area — right-click any file for context menu\n"
                "  CONTEXT MENU:     Right-click → 'Share' opens the share dialog\n"
                "  SHARE DIALOG:\n"
                "    - Title: 'Share \"filename\"'\n"
                "    - Input: 'Add people, groups, and calendar events' text field\n"
                "    - Permission dropdown: 'Viewer' / 'Commenter' / 'Editor' (appears after adding email)\n"
                "    - Buttons: 'Send' (bottom-right), 'Copy link'\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — SEARCH FOR THE FILE:\n"
                "  Click the search bar at the top center of the page.\n"
                "  type_text(x, y, text='{file_name}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter')\n\n"

                "Step 2 — WAIT FOR RESULTS:\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n\n"

                "Step 3 — FIND THE FILE:\n"
                "  Look through the search results for a file matching '{file_name}'.\n"
                "  If multiple results appear, choose the closest match by name.\n"
                "  If no results found, call task_complete with error:\n"
                "  'Could not find file \"{file_name}\" in Google Drive.'\n\n"

                "Step 4 — RIGHT-CLICK THE FILE:\n"
                "  Right-click on the file row matching '{file_name}'.\n"
                "  A context menu will appear with options like: Open with, Share, Get link, etc.\n\n"

                "Step 5 — CLICK 'Share':\n"
                "  Click 'Share' in the context menu. It opens a submenu — click the first 'Share' option.\n"
                "  This opens the Share dialog.\n\n"

                "Step 6 — WAIT FOR SHARE DIALOG:\n"
                "  wait(seconds=2, reason='Waiting for Share dialog to load')\n"
                "  You should see a dialog titled 'Share \"filename\"' with an input field.\n\n"

                "Step 7 — ADD RECIPIENT:\n"
                "  Click the 'Add people, groups, and calendar events' input field.\n"
                "  type_text(x, y, text='{share_with}', press_enter=false)\n"
                "  wait(seconds=2, reason='Waiting for email suggestion to appear')\n"
                "  Press Enter or click the matching suggestion to confirm the recipient.\n"
                "  press_key('Enter')\n\n"

                "Step 8 — SET PERMISSION LEVEL:\n"
                "  After adding the recipient, a permission dropdown appears next to their name.\n"
                "  The dropdown defaults to 'Editor' — check the current value.\n"
                "  If the current value is NOT '{permission}':\n"
                "    Click the permission dropdown (shows 'Viewer'/'Commenter'/'Editor').\n"
                "    Select '{permission}' from the dropdown options.\n"
                "  If already set to '{permission}', skip this step.\n\n"

                "Step 9 — CLICK 'Send':\n"
                "  Click the 'Send' button at the bottom-right of the Share dialog.\n"
                "  Do NOT click 'Copy link' — click 'Send'.\n\n"

                "Step 10 — WAIT AND VERIFY:\n"
                "  wait(seconds=2, reason='Waiting for share to complete')\n"
                "  The Share dialog should close. If a confirmation toast appears, note it.\n"
                "  If the dialog is still open with an error, report the error.\n\n"

                "Step 11 — COMPLETE:\n"
                "  Call task_complete with confirmation:\n"
                "  'Shared \"{file_name}\" with {share_with} as {permission}.'\n\n"

                "RULES:\n"
                "- Search for the file FIRST, then right-click to share. Do not try to share from sidebar.\n"
                "- The 'Add people' field is inside the Share dialog, not the main search bar.\n"
                "- Permission dropdown appears AFTER adding a recipient, not before.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If the share dialog does not open, try right-clicking the file again.\n"
                "- If the email is invalid, a red error will appear — report it and stop."
            ),
            params=[
                SkillParam(name="file_name", description="Name of the file or folder to share"),
                SkillParam(name="share_with", description="Email address of the person to share with"),
                SkillParam(
                    name="permission",
                    description="Access level to grant",
                    enum=["Viewer", "Commenter", "Editor"],
                    default="Viewer",
                ),
            ],
            tags=["drive", "share", "collaborate", "permission", "access"],
            examples=[
                "Share the budget spreadsheet with team@company.com",
                "Give editor access to the project folder for alice@example.com",
                "Share Q4 Report with my manager as a viewer",
            ],
        ))
