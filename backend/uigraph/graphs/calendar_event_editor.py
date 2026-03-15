"""Google Calendar Event Editor — semantic UI graph.

Built from the actual Google Calendar event creation page layout:
  calendar.google.com/calendar/u/0/r/eventedit
"""

from backend.uigraph.model import (
    UIGraph, UINode, UIEdge, UIAction,
    NodeType, ActionType,
)


def build() -> UIGraph:
    graph = UIGraph(
        app_id="gcal_event_editor",
        name="Google Calendar — New Event",
        url_pattern=r"calendar\.google\.com/calendar/u/\d+/r/eventedit",
        entry_node="title",
        terminal_nodes=["save_btn"],
        layout_description=(
            "TOP BAR:   [X close] [__Add title__] .................. [Save btn]\n"
            "ROW 2:     [StartDate chip] [StartTime chip] to [EndTime chip] [EndDate chip]  Time zone\n"
            "ROW 3:     [ ] All day   [Does not repeat ▼]\n"
            "─── TABS:  [Event details]  |  [Find a time] ───────── [Guests] ───\n"
            "LEFT:  📹 Add Google Meet video conferencing\n"
            "       📍 Add location\n"
            "       🔔 Notification [dropdown] [30] [minutes] [×]  + Add notification\n"
            "       📅 Calendar selector   [● color ▼]\n"
            "       📋 Busy ▼   Default visibility ▼\n"
            "       ≡  Add description (rich text area)\n"
            "RIGHT: [Add guests] input\n"
            "       Guest permissions (checkboxes)"
        ),
        interaction_sequence=[
            "title",
            "start_date",
            "start_time",
            "end_time",
            "meet_link",
            "guests",
            "description",
            "save_btn",
        ],
    )

    # ── NODES ──────────────────────────────────────────────

    graph.nodes["title"] = UINode(
        id="title",
        label="Add title",
        node_type=NodeType.INPUT,
        selector_hints={
            "tag": "input",
            "placeholder": "Add title",
            "aria": "Title",
            "region": "top_bar",
        },
        actions=[
            UIAction(ActionType.TYPE, {"press_enter": False},
                     "Click the title input at the top → type event name"),
        ],
        required=True,
        order=1,
        notes=(
            "Largest input at the VERY TOP of the page, left of the Save button. "
            "MUST be filled first. Extract the event name from the user's instruction. "
            "E.g. 'schedule a team sync' → type 'Team Sync'."
        ),
    )

    graph.nodes["start_date"] = UINode(
        id="start_date",
        label="Start date",
        node_type=NodeType.CHIP,
        selector_hints={
            "aria": "Start date",
            "text_pattern": r"[A-Z][a-z]{2} \d{1,2}, \d{4}",
            "region": "row2_left",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the date chip to activate it"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type date in the chip's text input"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"}, "Confirm date"),
        ],
        format_hint="Mar 12, 2026",
        required=True,
        order=2,
        notes=(
            "Rounded chip button below the title. Shows date like 'Mar 11, 2026'. "
            "Click it → it becomes editable OR a calendar picker appears. "
            "Type the new date with clear_first=true. Press Enter or Tab to confirm. "
            "For 'tomorrow': calculate the actual date."
        ),
    )

    graph.nodes["start_time"] = UINode(
        id="start_time",
        label="Start time",
        node_type=NodeType.CHIP,
        selector_hints={
            "aria": "Start time",
            "text_pattern": r"\d{1,2}:\d{2}[ap]m",
            "region": "row2",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the time chip"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type time value"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"}, "Confirm time"),
        ],
        format_hint="10:00am (12hr, no space before am/pm)",
        required=True,
        order=3,
        notes=(
            "Chip to the RIGHT of start date. Shows time like '4:30pm'. "
            "Click → dropdown of time slots appears. Type the time with clear_first=true "
            "or click the correct slot from the dropdown. Press Enter to confirm."
        ),
    )

    graph.nodes["end_time"] = UINode(
        id="end_time",
        label="End time",
        node_type=NodeType.CHIP,
        selector_hints={
            "aria": "End time",
            "text_pattern": r"\d{1,2}:\d{2}[ap]m",
            "region": "row2_after_to",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the end time chip"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False},
                     "Type end time"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"}, "Confirm"),
        ],
        format_hint="11:00am",
        required=True,
        order=4,
        notes="After the 'to' text. Default: 1 hour after start time.",
    )

    graph.nodes["end_date"] = UINode(
        id="end_date",
        label="End date",
        node_type=NodeType.CHIP,
        selector_hints={
            "aria": "End date",
            "region": "row2_right",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click"),
            UIAction(ActionType.TYPE, {"clear_first": True, "press_enter": False}, "Type date"),
            UIAction(ActionType.PRESS_KEY, {"key": "Enter"}, "Confirm"),
        ],
        format_hint="Mar 12, 2026",
        order=5,
        notes="Usually same as start date. Only change for multi-day events.",
    )

    graph.nodes["all_day"] = UINode(
        id="all_day",
        label="All day",
        node_type=NodeType.CHECKBOX,
        selector_hints={"text": "All day", "region": "row3"},
        actions=[UIAction(ActionType.CLICK, {}, "Toggle all-day on/off")],
        order=6,
        notes="Below the date/time row. Only check if user says 'all day'.",
    )

    graph.nodes["repeat"] = UINode(
        id="repeat",
        label="Does not repeat",
        node_type=NodeType.DROPDOWN,
        selector_hints={"text": "Does not repeat", "region": "row3"},
        actions=[
            UIAction(ActionType.CLICK, {}, "Open repeat dropdown"),
            UIAction(ActionType.CLICK, {}, "Select repeat option"),
        ],
        order=7,
        notes=(
            "Dropdown next to 'All day'. Options: Does not repeat, Daily, "
            "Weekly on [day], Monthly on the [nth] [day], Annually on [date], "
            "Every weekday (Mon-Fri), Custom. Leave default unless user specifies."
        ),
    )

    graph.nodes["meet_link"] = UINode(
        id="meet_link",
        label="Add Google Meet video conferencing",
        node_type=NodeType.LINK,
        selector_hints={
            "text": "Add Google Meet video conferencing",
            "tag": "span",
            "region": "left_panel",
        },
        actions=[
            UIAction(ActionType.CLICK, {},
                     "Click the 'Add Google Meet video conferencing' text"),
            UIAction(ActionType.WAIT, {"seconds": 2},
                     "Wait for Meet link to generate"),
            UIAction(ActionType.EXTRACT, {},
                     "Extract the generated meet.google.com/xxx-xxxx-xxx link"),
        ],
        order=8,
        notes=(
            "In the left Event details panel. Has a 📹 Google Meet icon. "
            "After clicking, a 'Join with Google Meet' link appears with the URL. "
            "Extract and remember this URL for the completion summary."
        ),
    )

    graph.nodes["location"] = UINode(
        id="location",
        label="Add location",
        node_type=NodeType.INPUT,
        selector_hints={
            "placeholder": "Add location",
            "tag": "input",
            "region": "left_panel",
        },
        actions=[UIAction(ActionType.TYPE, {"press_enter": False}, "Type location")],
        notes="Only fill if user specifies a location.",
    )

    graph.nodes["notification"] = UINode(
        id="notification",
        label="Notification",
        node_type=NodeType.DROPDOWN,
        selector_hints={"text": "Notification", "region": "left_panel"},
        actions=[
            UIAction(ActionType.CLICK, {}, "Change notification type (Notification/Email)"),
        ],
        default_value="30 minutes",
        notes=(
            "Default: Notification 30 minutes before. Options: Notification or Email. "
            "Can change the time value. Click '+Add notification' to add more. "
            "Leave default unless user specifies."
        ),
    )

    graph.nodes["description"] = UINode(
        id="description",
        label="Add description",
        node_type=NodeType.INPUT,
        selector_hints={
            "placeholder": "Add description",
            "aria": "Description",
            "text": "Add description",
            "tag": "div",
            "contenteditable": "true",
            "region": "left_panel_bottom",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the description area"),
            UIAction(ActionType.TYPE, {"press_enter": False}, "Type description"),
        ],
        notes=(
            "Rich text editor at the bottom of the left panel. Has formatting toolbar "
            "(bold, italic, underline, lists, links). Only fill if user specifies."
        ),
    )

    graph.nodes["guests"] = UINode(
        id="guests",
        label="Add guests",
        node_type=NodeType.INPUT,
        selector_hints={
            "placeholder": "Add guests",
            "tag": "input",
            "region": "right_panel",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the Add guests input"),
            UIAction(ActionType.TYPE, {"press_enter": True},
                     "Type email address, press Enter to add. Repeat per guest."),
        ],
        order=9,
        notes=(
            "On the RIGHT panel, separate from Event details. "
            "Type each email and press Enter after each. "
            "Guest permissions (Modify event, Invite others, See guest list) are below."
        ),
    )

    graph.nodes["save_btn"] = UINode(
        id="save_btn",
        label="Save",
        node_type=NodeType.BUTTON,
        selector_hints={
            "text": "Save",
            "tag": "button",
            "region": "top_right",
        },
        actions=[
            UIAction(ActionType.CLICK, {}, "Click the blue Save button at top-right"),
        ],
        required=True,
        order=10,
        notes=(
            "Blue button at the top-right corner. After clicking: "
            "if guests were added → 'Send invitation emails?' dialog appears. "
            "If no guests → goes directly to calendar view."
        ),
    )

    graph.nodes["send_dialog"] = UINode(
        id="send_dialog",
        label="Send invitation emails?",
        node_type=NodeType.DIALOG,
        selector_hints={"text": "Send", "tag": "button"},
        actions=[
            UIAction(ActionType.CLICK, {}, "Click 'Send' to send invitations"),
        ],
        notes="Only appears after Save if guests were added. Click 'Send' to confirm.",
    )

    # ── EDGES ──────────────────────────────────────────────

    graph.edges = [
        UIEdge(
            source="save_btn",
            target="send_dialog",
            action=ActionType.CLICK,
            condition="guests_added",
            description="If guests were added, Send Invitations dialog appears",
        ),
        UIEdge(
            source="save_btn",
            target="CALENDAR_VIEW",
            action=ActionType.CLICK,
            condition="no_guests",
            description="Saves and returns to calendar grid",
        ),
        UIEdge(
            source="send_dialog",
            target="CALENDAR_VIEW",
            action=ActionType.CLICK,
            description="After clicking Send, returns to calendar view",
        ),
    ]

    return graph
