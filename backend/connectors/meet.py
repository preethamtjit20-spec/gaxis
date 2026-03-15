"""Google Meet connector — start, join, and schedule video meetings.

Provides precise, step-by-step browser instructions for:
- Start an instant meeting (create and get link)
- Join an existing meeting by code or link
- Schedule a meeting via Google Calendar with Meet conferencing

Each skill maps the exact Google Meet / Calendar UI layout so the
navigator never clicks the wrong element or types into the wrong field.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


# ─── MEET UI LAYOUT REFERENCE ──────────────────────────────────────
# Google Meet landing page (https://meet.google.com):
#
# ┌────────────────────────────────────────────────────────────────┐
# │  Google Meet              [Sign in] / [Account avatar]         │
# │                                                                │
# │  ┌──────────────────┐   ┌──────────────────────────────────┐  │
# │  │  [New meeting ▼]  │   │  Enter a code or link  [Join →]  │  │
# │  └──────────────────┘   └──────────────────────────────────┘  │
# │                                                                │
# │  "New meeting" dropdown options:                               │
# │    • Create a meeting for later  (generates link only)        │
# │    • Start an instant meeting    (enters meeting immediately) │
# │    • Schedule in Google Calendar (opens calendar edit form)   │
# └────────────────────────────────────────────────────────────────┘
#
# Pre-join screen (meet.google.com/xxx-xxxx-xxx before joining):
#
# ┌────────────────────────────────────────────────────────────────┐
# │                    Ready to join?                              │
# │  ┌──────────────────────────────┐                             │
# │  │      Camera preview          │   Your meeting is ready     │
# │  │      (self-view)             │                             │
# │  │  [🎤 mic] [📷 camera]       │   [Join now]  [Present]     │
# │  └──────────────────────────────┘                             │
# └────────────────────────────────────────────────────────────────┘
#
# In-meeting bottom bar:
#
# ┌────────────────────────────────────────────────────────────────┐
# │  [🎤 Mic] [📷 Camera] [CC] [👋 Raise] [😀 React]            │
# │  [📤 Present] [💬 Chat] [👥 People] [📋 Activities]          │
# │  [🔴 Leave call]                                              │
# └────────────────────────────────────────────────────────────────┘
#
# Meeting link format: meet.google.com/abc-defg-hij


class GoogleMeetConnector(BaseConnector):
    name = "google_meet"
    description = "Google Meet — start, join, and schedule video meetings"
    icon = "meet"
    category = "communication"

    def _setup(self) -> None:
        self._register_start_meeting()
        self._register_join_meeting()
        self._register_schedule_meeting()

    # ────────────────────────────────────────────────
    #  START MEETING
    # ────────────────────────────────────────────────

    def _register_start_meeting(self) -> None:
        self.register_skill(Skill(
            name="start_meeting",
            description="Start a new instant Google Meet video call and get the meeting link",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://meet.google.com",
            browser_template=(
                "Navigate to https://meet.google.com\n\n"

                "PAGE LAYOUT — memorize before acting:\n"
                "  LEFT SIDE:   'New meeting' button (white, with dropdown arrow ▼)\n"
                "  RIGHT SIDE:  'Enter a code or link' text input with 'Join' button\n"
                "  The 'New meeting' button opens a dropdown with 3 options:\n"
                "    1. 'Create a meeting for later'  — generates link without entering\n"
                "    2. 'Start an instant meeting'    — enters meeting immediately\n"
                "    3. 'Schedule in Google Calendar'  — opens calendar form\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — CLICK 'NEW MEETING':\n"
                "  Click the 'New meeting' button on the left side of the page.\n"
                "  A dropdown menu will appear with three options.\n\n"

                "Step 2 — SELECT MEETING TYPE:\n"
                "  {meeting_type_step}\n\n"

                "Step 3 — HANDLE 'CREATE FOR LATER' PATH:\n"
                "  If you chose 'Create a meeting for later':\n"
                "    A dialog/popup will appear showing the meeting link (meet.google.com/xxx-xxxx-xxx).\n"
                "    Use extract_data to capture the meeting link text.\n"
                "    Click the copy icon (📋) next to the link if available.\n"
                "    Call task_complete with the meeting link.\n\n"

                "Step 4 — HANDLE 'START INSTANT' PATH:\n"
                "  If you chose 'Start an instant meeting':\n"
                "    You will be taken directly into the meeting room.\n"
                "    wait(seconds=3, reason='Waiting for meeting room to fully load')\n"
                "    Look at the bottom bar or the meeting info. The meeting link is shown\n"
                "    in the top-left (meeting code) or by clicking the 'i' info icon in bottom-left.\n"
                "    Use extract_data to capture the meeting link from the URL bar or meeting info.\n"
                "    Call task_complete with the meeting link.\n\n"

                "Step 5 — EXTRACT LINK FROM URL:\n"
                "  The current page URL will contain the meeting link (meet.google.com/xxx-xxxx-xxx).\n"
                "  Use extract_data to capture the full URL.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- The meeting link format is always: meet.google.com/abc-defg-hij\n"
                "- ALWAYS extract and return the meeting link before calling task_complete.\n"
                "- If a 'Got it' or permission dialog appears, dismiss it by clicking 'Got it' or 'Dismiss'."
            ),
            params=[
                SkillParam(
                    name="meeting_type_step",
                    description=(
                        "'Click Create a meeting for later to get a link without joining.' "
                        "or 'Click Start an instant meeting to join immediately.'"
                    ),
                    required=False,
                    default="Click 'Create a meeting for later' to generate a shareable link without entering the call.",
                ),
            ],
            tags=["meet", "video", "call", "meeting", "start", "create", "instant", "link"],
            examples=[
                "Start a Google Meet call",
                "Create a new video meeting",
                "Get me a Meet link",
                "Start an instant meeting",
            ],
        ))

    # ────────────────────────────────────────────────
    #  JOIN MEETING
    # ────────────────────────────────────────────────

    def _register_join_meeting(self) -> None:
        self.register_skill(Skill(
            name="join_meeting",
            description="Join a Google Meet call by meeting link or code",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://meet.google.com",
            browser_template=(
                "Navigate to https://meet.google.com\n\n"

                "PAGE LAYOUT — memorize before acting:\n"
                "  LEFT SIDE:   'New meeting' button\n"
                "  RIGHT SIDE:  'Enter a code or link' text input with 'Join' arrow button\n"
                "  The input field accepts:\n"
                "    - Full link: meet.google.com/abc-defg-hij\n"
                "    - Code only: abc-defg-hij\n"
                "    - Nickname links (for Workspace users)\n\n"

                "PRE-JOIN SCREEN LAYOUT (after navigating to meeting):\n"
                "  LEFT:   Camera preview with mic/camera toggle buttons below it\n"
                "  RIGHT:  'Your meeting is ready' text, 'Join now' button, 'Present' option\n"
                "  The mic/camera toggles on the preview let you mute/unmute before joining.\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — ENTER MEETING CODE:\n"
                "  Click the 'Enter a code or link' text input (right side of the page).\n"
                "  type_text(x, y, text='{meeting_code}', press_enter=false, clear_first=true)\n\n"

                "Step 2 — CLICK JOIN:\n"
                "  Click the 'Join' button (arrow icon → to the right of the input field).\n"
                "  wait(seconds=3, reason='Waiting for pre-join screen to load')\n\n"

                "Step 3 — PRE-JOIN SCREEN SETUP:\n"
                "  {mic_step}\n"
                "  {camera_step}\n\n"

                "Step 4 — JOIN THE MEETING:\n"
                "  Click the 'Join now' button (blue button, right side of pre-join screen).\n"
                "  If you see 'Ask to join' instead (for meetings you are not the host of),\n"
                "  click 'Ask to join' and wait for the host to admit you.\n\n"

                "Step 5 — WAIT FOR MEETING:\n"
                "  wait(seconds=3, reason='Waiting for meeting room to fully load')\n"
                "  Verify you are in the meeting — you should see the bottom bar with\n"
                "  mic, camera, and leave call controls.\n\n"

                "Step 6 — CONFIRM:\n"
                "  Call task_complete with confirmation: 'Joined meeting {meeting_code} successfully.'\n"
                "  If stuck on 'Asking to join...' screen, report that you are waiting for host admission.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If a 'Got it' or permissions dialog appears, dismiss it first.\n"
                "- If the meeting code is a full URL (https://meet.google.com/xxx), enter just the code part (xxx-xxxx-xxx).\n"
                "- If the page says 'Check your meeting code' the code is invalid — report the error.\n"
                "- If the page says 'This meeting has ended', report that the meeting is no longer active.\n"
                "- NEVER click 'Present' unless specifically asked to present screen."
            ),
            params=[
                SkillParam(
                    name="meeting_code",
                    description="Meeting code (abc-defg-hij) or full link (meet.google.com/abc-defg-hij)",
                ),
                SkillParam(
                    name="mic_step",
                    description="'Click the microphone toggle to mute before joining.' or 'Leave microphone on (default).'",
                    required=False,
                    default="Leave microphone on (default).",
                ),
                SkillParam(
                    name="camera_step",
                    description="'Click the camera toggle to turn off camera before joining.' or 'Leave camera on (default).'",
                    required=False,
                    default="Leave camera on (default).",
                ),
            ],
            tags=["meet", "video", "call", "join", "meeting", "enter", "connect"],
            examples=[
                "Join the standup meeting",
                "Join meet.google.com/abc-defg-hij",
                "Join the meeting with code abc-defg-hij",
                "Join the meeting with camera off",
            ],
        ))

    # ────────────────────────────────────────────────
    #  SCHEDULE MEETING
    # ────────────────────────────────────────────────

    def _register_schedule_meeting(self) -> None:
        self.register_skill(Skill(
            name="schedule_meeting",
            description="Schedule a Google Meet with calendar invite via Google Calendar",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://calendar.google.com/calendar/u/0/r/eventedit",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r/eventedit\n\n"

                "ACTUAL PAGE LAYOUT (match this to what you see):\n"
                "  ┌───────────────────────────────────────────────────────────┐\n"
                "  │ [X]  'Add title' (large text input)           [Save]     │\n"
                "  ├───────────────────────────────────────────────────────────┤\n"
                "  │ [Mar 11, 2026] [4:30pm] to [5:30pm] [Mar 11, 2026]      │\n"
                "  │ [ ] All day   [Does not repeat ▼]                        │\n"
                "  ├─────────────────────────┬─────────────────────────────────┤\n"
                "  │ Event details tab       │ Guests tab                      │\n"
                "  │ 📹 Add Google Meet...   │ [Add guests] input              │\n"
                "  │ 📍 Add location         │ Guest permissions               │\n"
                "  │ 🔔 Notification [30min] │                                 │\n"
                "  │ ≡  Add description      │                                 │\n"
                "  └─────────────────────────┴─────────────────────────────────┘\n\n"

                "EXECUTE EVERY STEP IN ORDER. DO NOT SKIP ANY.\n\n"

                "Step 1 — TITLE (most important!):\n"
                "  The 'Add title' field is at the VERY TOP, above the date row.\n"
                "  Click it and type: '{title}'\n"
                "  type_text(x, y, text='{title}', press_enter=false)\n\n"

                "Step 2 — START DATE:\n"
                "  Click the start date CHIP (rounded button showing current date, e.g. 'Mar 11, 2026').\n"
                "  It becomes editable or shows a date picker calendar.\n"
                "  Type the new date with clear_first=true: '{date}'\n"
                "  Click outside the picker or press Tab to confirm.\n\n"

                "Step 3 — START TIME:\n"
                "  Click the start time CHIP (e.g. '4:30pm'). A dropdown of times appears.\n"
                "  Type: '{start_time}' with clear_first=true, OR click the correct time from dropdown.\n"
                "  Click outside or press Tab to confirm.\n\n"

                "Step 4 — END TIME:\n"
                "  Click the end time CHIP (after 'to'). Same dropdown appears.\n"
                "  Type: '{end_time}' with clear_first=true, OR click from dropdown.\n"
                "  Click outside or press Tab to confirm.\n\n"

                "Step 5 — ADD GOOGLE MEET:\n"
                "  In the Event details panel (left side), find 'Add Google Meet video conferencing'.\n"
                "  Click that text link (it has a 📹 Google Meet icon to its left).\n"
                "  wait(seconds=2, reason='Generating Meet link')\n"
                "  A 'Join with Google Meet' link with URL will appear. Note the URL.\n\n"

                "Step 6 — GUESTS:\n"
                "  {guests_step}\n\n"

                "Step 7 — DESCRIPTION:\n"
                "  {description_step}\n\n"

                "Step 8 — SAVE:\n"
                "  Click the blue 'Save' button at the top-right of the page.\n"
                "  If a dialog asks 'Send invitation emails to guests?' → click 'Send'.\n"
                "  If it asks 'Discard changes?' → do NOT discard, something went wrong.\n\n"

                "Step 9 — WAIT & VERIFY:\n"
                "  wait(seconds=3, reason='Waiting for calendar to load')\n"
                "  The calendar grid should now show the event '{title}'.\n"
                "  ONLY call task_complete if the event is visible on the calendar.\n"
                "  Include the Google Meet link in the task_complete summary.\n\n"

                "RULES:\n"
                "- Title is at the VERY TOP of the page. Date/time chips are BELOW it.\n"
                "- Date/time are CHIP BUTTONS (rounded), not regular text fields.\n"
                "  Click a chip → it becomes editable or shows a picker.\n"
                "- Date format as displayed: 'Mar 12, 2026'. Time format: '10:00am' (12hr, no space).\n"
                "- Use clear_first=true for ALL date/time fields.\n"
                "- ONE action per turn. Check screenshot after each.\n"
                "- NEVER type dates into the title. NEVER type title into guests.\n"
                "- The Meet link MUST be added — this is the point of this skill.\n"
                "- ALWAYS include the Meet link in task_complete."
            ),
            params=[
                SkillParam(name="title", description="Meeting title text"),
                SkillParam(name="date", description="Meeting date in MM/DD/YYYY format (e.g. '03/15/2026')"),
                SkillParam(name="start_time", description="Start time in 12hr format no space (e.g. '10:00am')"),
                SkillParam(name="end_time", description="End time in 12hr format no space (e.g. '11:00am')"),
                SkillParam(
                    name="end_date",
                    description="End date MM/DD/YYYY (usually same as date for single-day meetings)",
                    required=False,
                    default="",
                ),
                SkillParam(
                    name="guests_step",
                    description=(
                        "'Click the Add guests field (RIGHT PANEL). "
                        "Type <email> and press Enter. Repeat for each guest.' "
                        "or 'Skip — no guests to invite.'"
                    ),
                    required=False,
                    default="Skip — no guests to invite.",
                ),
                SkillParam(
                    name="description_step",
                    description=(
                        "'Click Add description (LEFT PANEL, bottom). "
                        "Type: <description text>.' "
                        "or 'Skip — no description needed.'"
                    ),
                    required=False,
                    default="Skip — no description needed.",
                ),
            ],
            tags=["meet", "schedule", "calendar", "invite", "video", "call", "conference"],
            examples=[
                "Schedule a team sync with Meet for Friday at 10am",
                "Set up a video meeting with john@example.com tomorrow at 2pm",
                "Schedule a 1-on-1 meeting with Google Meet next Monday 3-4pm",
            ],
        ))
