"""Google Calendar connector — dedicated CRUD skills for calendar events.

Provides precise, step-by-step browser instructions for:
- Create event
- Read/check schedule
- Update event
- Delete event
- Find free time

Each skill maps the exact Google Calendar UI layout so the navigator
never types into the wrong field.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode
from backend.connectors.executors import (
    calendar_create_event,
    calendar_check_schedule,
    calendar_delete_event,
)


# ─── FORM LAYOUT REFERENCE (shared across skills) ────────────────
# Google Calendar event edit form (https://calendar.google.com/calendar/u/0/r/eventedit):
#
# ┌────────────────────────────────────────────────────────────────┐
# │  [✕]  [Add title ___________________________]       [Save 🔵] │
# │  [StartDate] [StartTime] to [EndTime] [EndDate] (timezone)   │
# │  [ ] All day    [Does not repeat ▼]                           │
# │  ─────────────────────────────────────────────────────────────│
# │  [Event details]  [Find a time]         │  Guests             │
# │  📹 Add Google Meet video conferencing  │  [Add guests ___]   │
# │  📍 Add location                        │  Guest permissions  │
# │  🔔 Notification [30] [minutes ▼]  [✕]  │                     │
# │  👤 Preetham  [● ▼]                     │                     │
# │  📅 Busy  [Default visibility ▼]        │                     │
# │  📝 Add description                     │                     │
# └────────────────────────────────────────────────────────────────┘
#
# Field formats:
#   Date: MM/DD/YYYY  (e.g. 03/15/2026)
#   Time: 12hr no space (e.g. 3:00pm, 10:30am)


class GoogleCalendarConnector(BaseConnector):
    name = "google_calendar"
    description = "Google Calendar — create, read, update, delete events and find free time"
    icon = "calendar"
    category = "productivity"

    def _setup(self) -> None:
        self._register_create()
        self._register_read()
        self._register_update()
        self._register_delete()
        self._register_find_free_time()

    # ────────────────────────────────────────────────
    #  CREATE EVENT
    # ────────────────────────────────────────────────

    def _register_create(self) -> None:
        self.register_skill(Skill(
            name="create_event",
            description="Create a new Google Calendar event with all details",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            start_url="https://calendar.google.com/calendar/u/0/r/eventedit",
            executor=calendar_create_event,
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r/eventedit\n\n"
                "Fill: title={title}, date={start_date}, time={start_time}-{end_time}\n"
                "Optional: location={location}, description={description}, guests={guests}\n"
                "Click Save. Verify event appears on calendar."
            ),
            params=[
                SkillParam(name="title", description="Event title text"),
                SkillParam(name="start_date", description="Start date MM/DD/YYYY (e.g. '03/15/2026')"),
                SkillParam(name="end_date", description="End date MM/DD/YYYY (usually same as start_date)", required=False),
                SkillParam(name="start_time", description="Start time 12hr (e.g. '3:00pm')"),
                SkillParam(name="end_time", description="End time 12hr (e.g. '4:00pm')", required=False),
                SkillParam(name="location", description="Event location", required=False, default=""),
                SkillParam(name="description", description="Event description", required=False, default=""),
                SkillParam(name="guests", description="Comma-separated guest emails", required=False, default=""),
                SkillParam(name="add_meet", description="Add Google Meet link", type="boolean", required=False, default=False),
            ],
            tags=["calendar", "event", "create", "schedule", "meeting", "appointment", "calendar_event"],
            examples=[
                "Create a calendar event for team standup tomorrow at 10am",
                "Schedule a dentist appointment on March 20 at 2pm",
                "Create a meeting with john@example.com on Friday 3-4pm with Google Meet",
            ],
        ))

    # ────────────────────────────────────────────────
    #  READ / CHECK SCHEDULE
    # ────────────────────────────────────────────────

    def _register_read(self) -> None:
        self.register_skill(Skill(
            name="check_schedule",
            description="Check Google Calendar for events on a specific day or range",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            executor=calendar_check_schedule,
            start_url="https://calendar.google.com/calendar/u/0/r",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r\n\n"

                "Step 1: Look at the current calendar view.\n"
                "  If you need a different day: click on that date in the mini calendar (left sidebar).\n"
                "  To go to a specific date: click the date number in the mini calendar.\n"
                "  Target: {time_range}\n\n"

                "Step 2: Switch to Day or Schedule view if needed for detailed reading.\n"
                "  Click the view dropdown (top-right, shows 'Week'/'Day'/'Month') and select 'Day' or 'Schedule'.\n\n"

                "Step 3: Read ALL visible events. For each event extract:\n"
                "  - Title\n"
                "  - Time (start → end)\n"
                "  - Location (if visible)\n"
                "  - Color/calendar name\n\n"

                "Step 4: Use extract_data to return the structured event list.\n\n"

                "Step 5: Call task_complete with a summary like:\n"
                "  'Found 3 events on March 12: Team Standup (10-10:30am), Lunch (12-1pm), 1:1 with Manager (3-3:30pm)'"
            ),
            params=[
                SkillParam(name="time_range", description="What to check: 'today', 'tomorrow', 'March 15', 'this week'"),
            ],
            tags=["calendar", "schedule", "check", "read", "events", "agenda", "today", "upcoming"],
            examples=[
                "What's on my calendar today?",
                "Check my schedule for tomorrow",
                "What meetings do I have this week?",
            ],
        ))

        self.register_skill(Skill(
            name="get_event_details",
            description="Open a specific calendar event to see its full details",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://calendar.google.com/calendar/u/0/r",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r\n\n"

                "Step 1: Find the event '{event_name}' on the calendar.\n"
                "  If not visible, navigate to the correct date first.\n\n"

                "Step 2: Click on the event to open its detail popup.\n\n"

                "Step 3: Read all details:\n"
                "  - Title, Date, Time\n"
                "  - Location, Description\n"
                "  - Guests and their RSVP status\n"
                "  - Google Meet link (if any)\n"
                "  - Organizer, Calendar\n\n"

                "Step 4: Use extract_data to capture the details.\n\n"

                "Step 5: Call task_complete with all the event details."
            ),
            params=[
                SkillParam(name="event_name", description="Name/title of the event to look up"),
            ],
            tags=["calendar", "event", "details", "read", "info", "view"],
            examples=[
                "What are the details of my team standup?",
                "Show me the Sprint Planning meeting details",
            ],
        ))

    # ────────────────────────────────────────────────
    #  UPDATE EVENT
    # ────────────────────────────────────────────────

    def _register_update(self) -> None:
        self.register_skill(Skill(
            name="update_event",
            description="Edit an existing Google Calendar event (change title, time, add guests, etc.)",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://calendar.google.com/calendar/u/0/r",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r\n\n"

                "Step 1 — FIND THE EVENT:\n"
                "  Navigate to the date of the event '{event_name}'.\n"
                "  Click on the event '{event_name}' in the calendar grid.\n\n"

                "Step 2 — OPEN EDIT:\n"
                "  In the event popup, click the pencil/edit icon (✏️) to open the full edit form.\n"
                "  This will open the same form as create but pre-filled.\n\n"

                "Step 3 — MAKE CHANGES:\n"
                "  {changes}\n\n"

                "  For each field you change:\n"
                "  - Click the field\n"
                "  - Use clear_first=true to replace existing value\n"
                "  - Type the new value\n"
                "  - Press Tab to confirm\n\n"

                "  Field formats:\n"
                "  - Title: click 'Add title' area, type new title\n"
                "  - Date: click date chip, type MM/DD/YYYY with clear_first=true\n"
                "  - Time: click time chip, type 12hr (e.g. '3:00pm') with clear_first=true\n"
                "  - Location: click location field, type new location\n"
                "  - Description: click description area, type new text\n"
                "  - Guests: click 'Add guests', type email and press Enter\n\n"

                "Step 4 — SAVE:\n"
                "  Click the blue 'Save' button at top-right.\n"
                "  If asked 'Edit recurring event?' → select '{recurrence_choice}'.\n"
                "  If asked 'Send updated invitations?' → click 'Send'.\n\n"

                "Step 5 — VERIFY:\n"
                "  Wait 3 seconds. Check the calendar shows the updated event.\n"
                "  Call task_complete with what was changed."
            ),
            params=[
                SkillParam(name="event_name", description="Current name of the event to edit"),
                SkillParam(name="changes", description="Step-by-step changes to make, e.g. 'Click title, clear, type New Title. Click start time, clear, type 4:00pm.'"),
                SkillParam(
                    name="recurrence_choice",
                    description="For recurring events: 'This event' or 'All events' or 'This and following events'",
                    required=False,
                    default="This event",
                ),
            ],
            tags=["calendar", "event", "update", "edit", "change", "modify", "reschedule", "move"],
            examples=[
                "Move my 3pm meeting to 4pm",
                "Change the team standup title to Daily Sync",
                "Add john@example.com to tomorrow's meeting",
                "Reschedule the dentist appointment to next Monday",
            ],
        ))

    # ────────────────────────────────────────────────
    #  DELETE EVENT
    # ────────────────────────────────────────────────

    def _register_delete(self) -> None:
        self.register_skill(Skill(
            name="delete_event",
            description="Delete/cancel a Google Calendar event",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            executor=calendar_delete_event,
            start_url="https://calendar.google.com/calendar/u/0/r",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r\n\n"

                "Step 1 — FIND THE EVENT:\n"
                "  Navigate to the date of '{event_name}'.\n"
                "  Click on the event '{event_name}' in the calendar grid.\n\n"

                "Step 2 — DELETE:\n"
                "  In the event popup, click the trash/delete icon (🗑️).\n"
                "  It's usually in the top-right of the popup, looks like a trash can.\n\n"

                "Step 3 — CONFIRM:\n"
                "  If asked 'Delete recurring event?' → select '{recurrence_choice}'.\n"
                "  If asked 'Send cancellation?' → click 'Send'.\n\n"

                "Step 4 — VERIFY:\n"
                "  Wait 2 seconds. The event '{event_name}' should NO LONGER be visible on the calendar.\n"
                "  Call task_complete confirming the event was deleted.\n"
                "  If the event is still visible → deletion failed, try again."
            ),
            params=[
                SkillParam(name="event_name", description="Name of the event to delete"),
                SkillParam(
                    name="recurrence_choice",
                    description="For recurring: 'This event' or 'All events' or 'This and following events'",
                    required=False,
                    default="This event",
                ),
            ],
            tags=["calendar", "event", "delete", "remove", "cancel"],
            examples=[
                "Delete tomorrow's team meeting",
                "Cancel the dentist appointment",
                "Remove the Sprint Planning event",
            ],
        ))

    # ────────────────────────────────────────────────
    #  FIND FREE TIME
    # ────────────────────────────────────────────────

    def _register_find_free_time(self) -> None:
        self.register_skill(Skill(
            name="find_free_time",
            description="Find available time slots on Google Calendar",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://calendar.google.com/calendar/u/0/r",
            browser_template=(
                "Navigate to https://calendar.google.com/calendar/u/0/r\n\n"

                "Step 1: Navigate to the target date range: {date_range}\n"
                "  Use the mini calendar on the left or arrow buttons to navigate.\n\n"

                "Step 2: Switch to 'Day' or 'Schedule' view for precise reading.\n"
                "  Click view selector top-right and choose 'Day' or 'Schedule'.\n\n"

                "Step 3: For each day in the range, identify:\n"
                "  - Existing events (blocked time)\n"
                "  - Gaps between events that are ≥ {min_duration}\n"
                "  - Consider typical working hours (9am-6pm) unless told otherwise\n\n"

                "Step 4: Use extract_data to capture available slots:\n"
                "  List each free slot with: date, start time, end time, duration.\n\n"

                "Step 5: Call task_complete with formatted free time slots.\n"
                "  Example: 'Free slots on March 12: 9:00am-10:00am (1hr), 2:00pm-5:00pm (3hrs)'"
            ),
            params=[
                SkillParam(name="date_range", description="Date range to check (e.g. 'tomorrow', 'March 15-17', 'this week')"),
                SkillParam(name="min_duration", description="Minimum slot duration (e.g. '30 minutes', '1 hour')", required=False, default="30 minutes"),
            ],
            tags=["calendar", "free", "available", "slot", "schedule", "busy", "open"],
            examples=[
                "When am I free tomorrow?",
                "Find a 1-hour slot this week for a meeting",
                "What times are available on Friday?",
            ],
        ))
