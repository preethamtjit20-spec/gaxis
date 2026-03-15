"""Gmail connector — send, read, search, and reply to emails.

Browser-based skills that work with a logged-in Chrome session.

Provides precise, step-by-step browser instructions for:
- Send email
- Read emails
- Search email
- Reply to email

Each skill maps the exact Gmail UI layout so the navigator
never clicks the wrong element.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode
from backend.connectors.executors import gmail_send_email, gmail_search_email


# ─── GMAIL UI LAYOUT REFERENCE (shared across skills) ─────────────
# Gmail inbox view (https://mail.google.com/mail/u/0/#inbox):
#
# ┌────────────────────────────────────────────────────────────────┐
# │  [☰ Menu]   [🔍 Search mail ____________________________]     │
# │                                                                │
# │  ┌─────────────┐  ┌──────────────────────────────────────────┐│
# │  │ [+ Compose] │  │  ☐  ☆  Sender     Subject — snippet  3pm ││
# │  │             │  │  ☐  ☆  Sender     Subject — snippet  2pm ││
# │  │  Inbox      │  │  ☐  ☆  Sender     Subject — snippet  1pm ││
# │  │  Starred    │  │  ...                                      ││
# │  │  Sent       │  │                                           ││
# │  │  Drafts     │  │                                           ││
# │  │  Labels ▼   │  │                                           ││
# │  └─────────────┘  └──────────────────────────────────────────┘│
# └────────────────────────────────────────────────────────────────┘
#
# Compose window (appears bottom-right after clicking Compose):
#
# ┌──────────────────────────────────────┐
# │  New Message                    — □ ✕│
# │  To: [________________________]      │
# │  Subject: [___________________]      │
# │  ┌────────────────────────────┐      │
# │  │  (body text area)          │      │
# │  │                            │      │
# │  └────────────────────────────┘      │
# │  [Send 🔵]  [A] [📎] [🔗] [...] [🗑]│
# └──────────────────────────────────────┘
#
# CC/BCC: click "Cc" or "Bcc" links next to the To field to reveal them.
# Search: supports Gmail operators (from:, to:, subject:, has:attachment, etc.)


class GmailConnector(BaseConnector):
    name = "gmail"
    description = "Gmail — send, read, search, and reply to emails"
    icon = "mail"
    category = "communication"

    def _setup(self) -> None:
        self._register_send_email()
        self._register_read_emails()
        self._register_search_email()
        self._register_reply_email()

    # ────────────────────────────────────────────────
    #  SEND EMAIL
    # ────────────────────────────────────────────────

    def _register_send_email(self) -> None:
        self.register_skill(Skill(
            name="send_email",
            description="Compose and send an email via Gmail",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            executor=gmail_send_email,
            start_url="https://mail.google.com/mail/u/0/#inbox",
            browser_template=(
                "Navigate to https://mail.google.com/mail/u/0/#inbox\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  TOP-LEFT SIDEBAR:  'Compose' button (large, with '+' icon)\n"
                "  COMPOSE WINDOW:    appears bottom-right of screen after clicking Compose\n"
                "  COMPOSE FIELDS:    To (first field), Subject (below To), Body (large area below Subject)\n"
                "  CC/BCC:            revealed by clicking 'Cc' or 'Bcc' links right of the To field\n"
                "  SEND BUTTON:       blue 'Send' button at bottom-left of compose window\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — OPEN COMPOSE:\n"
                "  Click the 'Compose' button in the top-left sidebar area.\n"
                "  wait(seconds=2, reason='Waiting for compose window to appear')\n"
                "  VERIFY: A 'New Message' compose window must appear at the bottom-right of the screen.\n"
                "  If no compose window appears, click 'Compose' again.\n\n"

                "Step 2 — TO FIELD:\n"
                "  Click the 'To' field (first input field in the compose window, at the top).\n"
                "  type_text(x, y, text='{to}', press_enter=false)\n"
                "  press_key('Tab')\n"
                "  wait(seconds=1, reason='Waiting for autocomplete to resolve')\n"
                "  VERIFY: The recipient '{to}' should appear as a chip/tag in the To field.\n"
                "  If autocomplete dropdown appears, press Tab or Enter to accept the correct match.\n\n"

                "Step 3 — CC/BCC (optional):\n"
                "  {cc_bcc_step}\n\n"

                "Step 4 — SUBJECT:\n"
                "  Click the 'Subject' field (below the To field, labeled 'Subject').\n"
                "  type_text(x, y, text='{subject}', press_enter=false)\n"
                "  press_key('Tab')\n\n"

                "Step 5 — BODY:\n"
                "  Click the large body text area (below the Subject field).\n"
                "  type_text(x, y, text='{body}', press_enter=false)\n\n"

                "Step 6 — SEND:\n"
                "  Click the blue 'Send' button at the bottom-left of the compose window.\n"
                "  wait(seconds=3, reason='Waiting for email to send')\n\n"

                "Step 7 — VERIFY:\n"
                "  The compose window MUST be gone (closed automatically after send).\n"
                "  Look for a 'Message sent' notification bar at the bottom-left of the screen.\n"
                "  ONLY call task_complete if the compose window has closed AND/OR 'Message sent' is visible.\n"
                "  If the compose window is still open:\n"
                "    - Check for red error text (e.g. invalid email address).\n"
                "    - Fix the error and click 'Send' again.\n"
                "    - If no visible error, try clicking 'Send' once more.\n\n"

                "RULES:\n"
                "- To field is TOP of compose. Subject is BELOW To. Body is BELOW Subject. NEVER mix them.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- After typing in To field, ALWAYS press Tab to confirm the recipient before moving on.\n"
                "- If recipient autocomplete shows multiple matches, verify the correct one is selected.\n"
                "- Do NOT press Enter in the body field — it adds newlines, not send."
            ),
            params=[
                SkillParam(name="to", description="Recipient email address (e.g. 'john@example.com')"),
                SkillParam(name="subject", description="Email subject line"),
                SkillParam(name="body", description="Email body text"),
                SkillParam(
                    name="cc_bcc_step",
                    description=(
                        "'Click Cc link next to To field, type <email>, press Tab. "
                        "Click Bcc link, type <email>, press Tab.' or 'Skip — no CC/BCC needed.'"
                    ),
                    required=False,
                    default="Skip — no CC/BCC needed.",
                ),
            ],
            tags=["email", "gmail", "send", "compose", "mail", "message"],
            examples=[
                "Send an email to john@example.com about the meeting",
                "Email the report to the team",
                "Send a message to alice@company.com with subject 'Q1 Report' and attach the summary",
            ],
        ))

    # ────────────────────────────────────────────────
    #  READ EMAILS
    # ────────────────────────────────────────────────

    def _register_read_emails(self) -> None:
        self.register_skill(Skill(
            name="read_emails",
            description="Read and summarize recent emails from Gmail inbox",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://mail.google.com/mail/u/0/#inbox",
            browser_template=(
                "Navigate to https://mail.google.com/mail/u/0/#inbox\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  INBOX LIST:     each row shows: checkbox, star, sender name, subject — snippet, time/date\n"
                "  UNREAD EMAILS:  displayed in BOLD text in the inbox list\n"
                "  EMAIL VIEW:     click any row to open the full email (sender, to, date, full body)\n"
                "  BACK TO INBOX:  click the left arrow (←) at top-left of email view\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — NAVIGATE TO INBOX:\n"
                "  Confirm you are on the inbox view (URL ends with #inbox).\n"
                "  If not, click 'Inbox' in the left sidebar.\n"
                "  wait(seconds=2, reason='Waiting for inbox to load')\n\n"

                "Step 2 — SCAN INBOX LIST:\n"
                "  Read the first {count} email rows visible in the inbox.\n"
                "  For EACH email row, extract:\n"
                "    - Sender name (leftmost text after checkbox/star)\n"
                "    - Subject line (bold text after sender)\n"
                "    - Snippet/preview (gray text after subject, separated by ' — ')\n"
                "    - Time or date (rightmost text in the row)\n"
                "    - Read/unread status (bold = unread, normal weight = read)\n\n"

                "Step 3 — APPLY FILTER (if any):\n"
                "  {filter_instruction}\n"
                "  If filter is provided, only include emails matching the filter criteria.\n"
                "  If filter mentions 'unread only', skip read (non-bold) emails.\n\n"

                "Step 4 — OPEN EMAILS FOR DETAIL (if needed):\n"
                "  If the user needs full email content (not just subject/snippet):\n"
                "    - Click on each email row to open it.\n"
                "    - Read the full body text, all recipients (To, CC), and date.\n"
                "    - Click the back arrow (←) at top-left to return to inbox.\n"
                "    - Repeat for each of the {count} emails.\n"
                "  If only a summary/list is needed, the inbox view is sufficient.\n\n"

                "Step 5 — EXTRACT DATA:\n"
                "  Use extract_data to capture the structured email list.\n"
                "  For each email include: sender, subject, snippet, time, read/unread.\n\n"

                "Step 6 — COMPLETE:\n"
                "  Call task_complete with a summary like:\n"
                "  'Found 5 emails. 2 unread. Most recent: [Sender] — [Subject] (time).'\n\n"

                "RULES:\n"
                "- Count emails from the TOP of the inbox (most recent first).\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- If fewer than {count} emails exist, report however many are visible.\n"
                "- Bold text in inbox = unread. Normal weight = already read."
            ),
            params=[
                SkillParam(name="count", description="Number of emails to read (e.g. 5)", type="integer", default=5),
                SkillParam(
                    name="filter_instruction",
                    description=(
                        "Optional filter instruction, e.g. 'Only include unread emails', "
                        "'Only emails from boss@company.com', 'Only emails from today'. "
                        "Or 'No filter — include all emails.'"
                    ),
                    required=False,
                    default="No filter — include all emails.",
                ),
            ],
            tags=["email", "gmail", "read", "inbox", "check", "mail"],
            examples=[
                "Check my latest emails",
                "Read unread emails from today",
                "Show me my 10 most recent emails",
            ],
        ))

    # ────────────────────────────────────────────────
    #  SEARCH EMAIL
    # ────────────────────────────────────────────────

    def _register_search_email(self) -> None:
        self.register_skill(Skill(
            name="search_email",
            description="Search Gmail for specific emails using search queries",
            connector=self.name,
            mode=SkillMode.DETERMINISTIC,
            executor=gmail_search_email,
            start_url="https://mail.google.com/mail/u/0/#inbox",
            browser_template=(
                "Navigate to https://mail.google.com/mail/u/0/#inbox\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  SEARCH BAR:      large input at the top center of Gmail, labeled 'Search mail'\n"
                "  SEARCH RESULTS:  displayed as email list below search bar after pressing Enter\n"
                "  SEARCH OPERATORS: from:, to:, subject:, has:attachment, before:, after:, is:unread, label:\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — CLICK SEARCH BAR:\n"
                "  Click the search bar at the top of Gmail (labeled 'Search mail').\n"
                "  The search bar is the large input field spanning the top center of the page.\n\n"

                "Step 2 — ENTER SEARCH QUERY:\n"
                "  type_text(x, y, text='{query}', press_enter=false, clear_first=true)\n"
                "  VERIFY: The query text '{query}' is visible in the search bar.\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n\n"

                "Step 3 — VERIFY SEARCH EXECUTED:\n"
                "  The URL should change to contain '#search/' indicating search mode.\n"
                "  Search results should appear as an email list below the search bar.\n"
                "  If 'No results' message appears, report that to the user.\n\n"

                "Step 4 — READ SEARCH RESULTS:\n"
                "  Read up to {max_results} result rows. For EACH result extract:\n"
                "    - Sender name\n"
                "    - Subject line\n"
                "    - Snippet/preview text\n"
                "    - Date/time\n"
                "    - Read/unread status (bold = unread)\n\n"

                "Step 5 — OPEN RESULTS FOR DETAIL (if needed):\n"
                "  If the user needs full email content:\n"
                "    - Click on a result row to open the full email.\n"
                "    - Read the complete body, all recipients, attachments, date.\n"
                "    - Click the back arrow (←) at top-left to return to search results.\n"
                "    - Repeat for each relevant result.\n\n"

                "Step 6 — EXTRACT DATA:\n"
                "  Use extract_data to capture the structured results.\n\n"

                "Step 7 — COMPLETE:\n"
                "  Call task_complete with a summary like:\n"
                "  'Found 8 results for \"{query}\". Top results: [Sender] — [Subject] (date).'\n"
                "  If no results found: 'No emails found matching \"{query}\".'\n\n"

                "RULES:\n"
                "- ALWAYS clear the search bar before typing (clear_first=true) to avoid appending to old queries.\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Gmail search operators are case-insensitive: from:, to:, subject: all work.\n"
                "- Common operators: from:alice, to:bob, subject:report, has:attachment,\n"
                "  is:unread, is:starred, before:2026/03/01, after:2026/01/01, label:important.\n"
                "- If results page shows 'No messages matched your search', report zero results."
            ),
            params=[
                SkillParam(
                    name="query",
                    description=(
                        "Gmail search query. Plain text or Gmail operators "
                        "(e.g. 'from:boss subject:report', 'has:attachment budget', 'is:unread from:hr')"
                    ),
                ),
                SkillParam(
                    name="max_results",
                    description="Maximum number of search results to read",
                    type="integer",
                    required=False,
                    default=10,
                ),
            ],
            tags=["email", "gmail", "search_email", "find_email", "mail"],
            examples=[
                "Find emails about the project deadline",
                "Search for emails from HR",
                "Find all unread emails with attachments from last week",
            ],
        ))

    # ────────────────────────────────────────────────
    #  REPLY EMAIL
    # ────────────────────────────────────────────────

    def _register_reply_email(self) -> None:
        self.register_skill(Skill(
            name="reply_email",
            description="Reply to a specific email in Gmail",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://mail.google.com/mail/u/0/#inbox",
            browser_template=(
                "Navigate to https://mail.google.com/mail/u/0/#inbox\n\n"

                "UI LAYOUT — memorize before acting:\n"
                "  INBOX LIST:       rows of emails with sender, subject, snippet, time\n"
                "  OPENED EMAIL:     shows full message with sender, recipients, date, body\n"
                "  REPLY BUTTON:     at the bottom of an opened email, labeled 'Reply'\n"
                "  REPLY ARROW:      curved arrow icon (↩) in the top-right of the email header\n"
                "  REPLY COMPOSE:    inline reply area appears below the email body after clicking Reply\n"
                "  REPLY SEND:       blue 'Send' button at bottom-left of the reply compose area\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — FIND THE EMAIL:\n"
                "  Scan the inbox for an email from '{sender}' with subject containing '{subject}'.\n"
                "  Look for a row where:\n"
                "    - Sender column matches or contains '{sender}'\n"
                "    - Subject/snippet text matches or contains '{subject}'\n"
                "  If the email is not visible in the current inbox view:\n"
                "    - Use the search bar: click it, type 'from:{sender} subject:{subject}', press Enter.\n"
                "    - wait(seconds=2, reason='Waiting for search results')\n\n"

                "Step 2 — OPEN THE EMAIL:\n"
                "  Click on the matching email row to open the full email view.\n"
                "  wait(seconds=2, reason='Waiting for email to load')\n"
                "  VERIFY: The email is now open. You should see:\n"
                "    - Sender name and email at the top\n"
                "    - Subject line in the header\n"
                "    - Full email body text\n"
                "    - Reply button at the bottom\n"
                "  If the wrong email opened, click the back arrow (←) and try again.\n\n"

                "Step 3 — CLICK REPLY:\n"
                "  Scroll to the bottom of the email if needed.\n"
                "  Click the 'Reply' button at the bottom of the email.\n"
                "  (Alternatively, click the reply arrow icon ↩ in the email header area.)\n"
                "  wait(seconds=1, reason='Waiting for reply compose area to appear')\n"
                "  VERIFY: An inline reply compose area should appear below the email body.\n"
                "  The reply area has a text input field and a blue 'Send' button.\n"
                "  If 'Reply' is not visible, scroll down — it may be below the fold.\n\n"

                "Step 4 — TYPE REPLY:\n"
                "  Click inside the reply text area (the blank area in the reply compose section).\n"
                "  type_text(x, y, text='{reply_body}', press_enter=false)\n"
                "  VERIFY: Your reply text '{reply_body}' is visible in the compose area.\n\n"

                "Step 5 — SEND REPLY:\n"
                "  Click the blue 'Send' button at the bottom-left of the reply compose area.\n"
                "  wait(seconds=3, reason='Waiting for reply to send')\n\n"

                "Step 6 — VERIFY:\n"
                "  After clicking Send, the reply compose area should close.\n"
                "  Look for either:\n"
                "    - A 'Message sent' notification at the bottom-left of the screen, OR\n"
                "    - The reply now appears as a new message in the email thread\n"
                "  ONLY call task_complete if one of these confirmations is visible.\n"
                "  If the reply compose area is still open:\n"
                "    - Check for red error messages (invalid recipient, etc.).\n"
                "    - Fix any errors and click 'Send' again.\n\n"

                "RULES:\n"
                "- FIND the correct email FIRST. Never reply to the wrong email.\n"
                "- If multiple emails match, prefer the most recent one (top of list).\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- The reply 'Send' button is inside the reply compose area, NOT the main Gmail toolbar.\n"
                "- Do NOT press Enter in the reply body — it adds newlines, not send.\n"
                "- If the email thread has multiple messages, Reply applies to the LAST message in the thread."
            ),
            params=[
                SkillParam(name="sender", description="Sender name or email to find the email (e.g. 'John' or 'john@example.com')"),
                SkillParam(name="subject", description="Subject line (or partial match) of the email to reply to"),
                SkillParam(name="reply_body", description="Reply message text to type"),
            ],
            tags=["email", "gmail", "reply", "respond", "mail"],
            examples=[
                "Reply to John's email about the meeting",
                "Respond to the HR email about benefits enrollment",
                "Reply to the latest email from alice@company.com saying 'Sounds good, thanks!'",
            ],
        ))
