"""General-purpose browser skills connector.

Provides fundamental browser interaction skills that work on any website:
search the web, navigate to URLs, read page content, fill forms,
take screenshots, click elements, and extract tabular data.

Each skill includes precise, step-by-step browser instructions so the
navigator knows exactly which UI elements to target and how to verify
success.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


class GeneralSkillsConnector(BaseConnector):
    name = "general"
    description = "General-purpose browser skills — search, navigate, read, interact"
    icon = "globe"
    category = "general"

    def _setup(self) -> None:
        self._register_web_search()
        self._register_open_url()
        self._register_read_page()
        self._register_fill_form()
        self._register_take_screenshot()
        self._register_click_element()
        self._register_extract_table()

    # ────────────────────────────────────────────────
    #  WEB SEARCH
    # ────────────────────────────────────────────────

    def _register_web_search(self) -> None:
        self.register_skill(Skill(
            name="web_search",
            description="Search Google for a query and return the top results",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://www.google.com",
            browser_template=(
                "Navigate to https://www.google.com\n\n"

                "PAGE LAYOUT — Google Search home:\n"
                "  CENTER:  Google logo above a large search input (textarea).\n"
                "  BELOW INPUT:  'Google Search' and 'I'm Feeling Lucky' buttons.\n"
                "  After submitting, the results page has:\n"
                "    TOP:  Search bar with query text.\n"
                "    BELOW: ~10 organic results, each with:\n"
                "      - Blue title link (clickable)\n"
                "      - Green/gray URL line\n"
                "      - Snippet paragraph (1-3 lines of text)\n"
                "    RIGHT SIDEBAR: Possible knowledge panel.\n"
                "    BOTTOM: 'Next' pagination link.\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — NAVIGATE:\n"
                "  Go to https://www.google.com .\n"
                "  wait(seconds=2, reason='Waiting for Google homepage to load')\n"
                "  Verify you see the Google logo and search input.\n"
                "  If a cookie consent banner appears, click 'Accept all' or dismiss it first.\n\n"

                "Step 2 — CLICK SEARCH BOX:\n"
                "  Click the large search input/textarea in the center of the page.\n"
                "  The input should now be focused (blinking cursor visible).\n"
                "  If an autocomplete dropdown is already showing, ignore it.\n\n"

                "Step 3 — TYPE QUERY:\n"
                "  type_text(x, y, text='{query}', press_enter=false)\n"
                "  Verify the query text appears in the search box.\n"
                "  Do NOT click any autocomplete suggestion — we want the exact query.\n\n"

                "Step 4 — SUBMIT SEARCH:\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results page to load')\n"
                "  Verify the results page loaded: look for the blue title links and snippets.\n"
                "  If you see 'No results found', report that and call task_complete.\n\n"

                "Step 5 — HANDLE SPECIAL RESULTS:\n"
                "  Check if Google shows a featured snippet, knowledge panel, or 'People also ask' box.\n"
                "  If a featured snippet exists at the top, include it as the first result.\n"
                "  If a 'Did you mean...' suggestion appears, note it but proceed with current results.\n\n"

                "Step 6 — EXTRACT RESULTS:\n"
                "  Read the top {num_results} organic search results on the page.\n"
                "  For EACH result, extract exactly:\n"
                "    a) Title — the blue clickable heading text.\n"
                "    b) URL — the green/gray URL shown below the title.\n"
                "    c) Snippet — the descriptive text paragraph below the URL.\n"
                "  Skip ads (marked 'Sponsored' or 'Ad'). Only extract organic results.\n"
                "  If fewer than {num_results} results exist on the page, extract all available.\n\n"

                "Step 7 — REPORT:\n"
                "  Use extract_data to return the structured results list.\n"
                "  Format each result as: [rank] Title | URL | Snippet\n"
                "  Call task_complete with the formatted results.\n"
                "  Include the total count: 'Found N results for: {query}'\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT click on any search result link — only read and extract.\n"
                "- Skip Sponsored/Ad results entirely.\n"
                "- If CAPTCHA appears, report it and call task_complete with an error."
            ),
            params=[
                SkillParam(name="query", description="The search query to type into Google"),
                SkillParam(
                    name="num_results",
                    description="Number of top results to return",
                    type="integer",
                    required=False,
                    default=5,
                ),
            ],
            tags=["search", "google", "web", "find", "lookup", "query"],
            examples=[
                "Search Google for 'best restaurants in San Francisco'",
                "Look up the latest news about AI",
            ],
        ))

    # ────────────────────────────────────────────────
    #  OPEN URL
    # ────────────────────────────────────────────────

    def _register_open_url(self) -> None:
        self.register_skill(Skill(
            name="open_url",
            description="Navigate the browser to any URL and verify it loaded",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Navigate to the target URL: {url}\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — NAVIGATE:\n"
                "  Open the URL: {url}\n"
                "  Use the browser's address bar or direct navigation.\n"
                "  If the URL does not start with http:// or https://, prepend https://.\n\n"

                "Step 2 — WAIT FOR LOAD:\n"
                "  wait(seconds=3, reason='Waiting for page to fully load')\n"
                "  Watch for the page title to appear in the browser tab.\n"
                "  Watch for the main content area to render (not just a blank page).\n"
                "  If the page is still loading (spinner visible), wait an additional 3 seconds.\n\n"

                "Step 3 — CHECK FOR ERRORS:\n"
                "  Look for common error indicators:\n"
                "    - 'This site can't be reached' or 'ERR_CONNECTION_REFUSED'\n"
                "    - '404 Not Found' or '403 Forbidden' or '500 Internal Server Error'\n"
                "    - 'Your connection is not private' (SSL error)\n"
                "    - Blank white page with no content\n"
                "  If any error is detected, report the specific error.\n\n"

                "Step 4 — HANDLE INTERSTITIALS:\n"
                "  If a cookie consent banner, age verification, or paywall modal appears:\n"
                "    - Cookie banner: click 'Accept', 'Accept All', or 'Got it'\n"
                "    - Age gate: click 'I am over 18' or appropriate confirmation\n"
                "    - Paywall/login wall: report that the page requires authentication\n"
                "  wait(seconds=1, reason='Waiting after dismissing interstitial')\n\n"

                "Step 5 — VERIFY AND REPORT:\n"
                "  Confirm the page loaded by identifying:\n"
                "    a) Page title — read from the browser tab or <title> element.\n"
                "    b) Current URL — note if there was a redirect (final URL differs from {url}).\n"
                "    c) Main content — describe what type of page this is (article, homepage, app, etc.).\n"
                "    d) Key visible elements — navigation bar, hero section, login form, etc.\n"
                "  Call task_complete with:\n"
                "    - Status: 'loaded successfully' or specific error\n"
                "    - Page title\n"
                "    - Final URL (if redirected)\n"
                "    - Brief 1-2 sentence description of the page content\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT interact with the page beyond dismissing interstitials.\n"
                "- If the page requires login, report that — do NOT attempt to log in."
            ),
            params=[
                SkillParam(name="url", description="The full URL to navigate to (e.g. https://example.com)"),
            ],
            tags=["navigate", "url", "open", "go", "visit", "browse", "link"],
            examples=[
                "Go to https://github.com",
                "Open the Wikipedia page for Python programming",
            ],
        ))

    # ────────────────────────────────────────────────
    #  READ PAGE
    # ────────────────────────────────────────────────

    def _register_read_page(self) -> None:
        self.register_skill(Skill(
            name="read_page",
            description="Extract and summarize the visible content of the current page",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Read and extract the content of the current page.\n\n"

                "CONTENT STRUCTURE — look for these elements in order:\n"
                "  HEADER AREA:  Site logo, navigation links, search bar, user menu\n"
                "  HERO/BANNER:  Large heading, subtitle, CTA buttons, hero image\n"
                "  MAIN CONTENT: Article text, product info, dashboard data, feed items\n"
                "  SIDEBAR:      Related links, ads, filters, table of contents\n"
                "  FOOTER:       Copyright, legal links, social media links\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — IDENTIFY PAGE TYPE:\n"
                "  Determine what kind of page this is:\n"
                "    - Article/blog post (headline, author, date, body text)\n"
                "    - Product page (name, price, images, description, reviews)\n"
                "    - Landing/home page (hero, features, CTAs)\n"
                "    - Dashboard/app (data widgets, charts, tables)\n"
                "    - Search results (list of results with links)\n"
                "    - Form page (input fields, submit button)\n"
                "    - Directory/listing (grid or list of items)\n"
                "  Note the page title from the browser tab.\n\n"

                "Step 2 — READ HEADINGS AND STRUCTURE:\n"
                "  Scan the page top-to-bottom and identify:\n"
                "    a) Main heading (H1) — the largest/most prominent title.\n"
                "    b) Section headings (H2, H3) — subheadings that organize content.\n"
                "    c) Navigation structure — what sections/tabs are available.\n"
                "  This gives the page's information architecture.\n\n"

                "Step 3 — EXTRACT MAIN CONTENT:\n"
                "  {focus_instruction}\n"
                "  Read the primary content area carefully:\n"
                "    - For articles: extract full text of each paragraph, author, date, key quotes.\n"
                "    - For products: name, price, availability, rating, key specs.\n"
                "    - For listings: first 10-15 items with their key details.\n"
                "    - For dashboards: key metrics, numbers, status indicators.\n"
                "  Preserve important formatting: bullet points, numbered lists, bold text.\n\n"

                "Step 4 — EXTRACT SUPPORTING CONTENT:\n"
                "  Look for additional valuable information:\n"
                "    a) Data points — dates, prices, statistics, ratings, counts.\n"
                "    b) Links — important outbound links with their anchor text.\n"
                "    c) Images — describe key images and what they show (charts, photos, diagrams).\n"
                "    d) Tables — if tables exist, note their presence and basic structure.\n"
                "    e) Embedded media — videos, audio players, maps.\n\n"

                "Step 5 — CHECK FOR MORE CONTENT:\n"
                "  Determine if there is content below the fold (not visible without scrolling).\n"
                "  Look for indicators: scroll bar, 'Show more' buttons, pagination, 'Load more'.\n"
                "  If important content is below the fold:\n"
                "    scroll_down(pixels=500)\n"
                "    wait(seconds=1, reason='Waiting for scrolled content to render')\n"
                "    Read any newly visible content.\n"
                "  Repeat scrolling up to 3 times if the page has substantial content.\n\n"

                "Step 6 — SUMMARIZE AND REPORT:\n"
                "  Use extract_data to return the structured content.\n"
                "  Organize the output as:\n"
                "    - Page title and URL\n"
                "    - Page type (article, product, etc.)\n"
                "    - Key information summary (3-5 bullet points)\n"
                "    - Full extracted text (organized by section heading)\n"
                "    - Notable data points, links, or media\n"
                "  Call task_complete with the complete extracted content.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT click any links — only read and extract.\n"
                "- If the page is behind a login wall, report what is visible without logging in.\n"
                "- If the page content is primarily images/video with little text, describe the visual content.\n"
                "- Prioritize accuracy over completeness — do not guess at obscured text."
            ),
            params=[
                SkillParam(
                    name="focus_instruction",
                    description="Optional focus area, e.g. 'Focus on the pricing section' or 'Read the main article'",
                    required=False,
                    default="Read all visible content on the page.",
                ),
            ],
            tags=["read", "extract", "content", "summarize", "text", "page", "scrape"],
            examples=[
                "Read the content of this page",
                "Summarize the article on the current page",
                "What does this page say about pricing?",
            ],
        ))

    # ────────────────────────────────────────────────
    #  FILL FORM
    # ────────────────────────────────────────────────

    def _register_fill_form(self) -> None:
        self.register_skill(Skill(
            name="fill_form",
            description="Fill a form on the current page with given field-value pairs",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Fill the form on the current page with the provided values.\n\n"

                "FORM ELEMENT TYPES — recognize and handle each:\n"
                "  TEXT INPUT:    Single-line field (<input type='text/email/tel/password/number'>)\n"
                "  TEXTAREA:     Multi-line text box (<textarea>)\n"
                "  SELECT/DROP:  Dropdown menu (<select> or custom dropdown with arrow icon)\n"
                "  CHECKBOX:     Square toggle (☐/☑) — click to check/uncheck\n"
                "  RADIO:        Circle toggle (○/●) — click the desired option\n"
                "  DATE PICKER:  Date input — may open a calendar widget when clicked\n"
                "  FILE UPLOAD:  'Choose File' or 'Browse' button\n"
                "  TOGGLE/SWITCH: On/off slider\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — SURVEY THE FORM:\n"
                "  Look at the current page and identify the form to fill.\n"
                "  Scan all visible form fields top-to-bottom and note:\n"
                "    a) Each field's label text (to the left, above, or as placeholder).\n"
                "    b) Each field's type (text input, dropdown, checkbox, radio, textarea, date).\n"
                "    c) Which fields are required (marked with *, 'required', or red border).\n"
                "    d) Which fields already have values pre-filled.\n"
                "    e) The submit button text and location.\n"
                "  If the form has multiple sections/pages, note that.\n\n"

                "Step 2 — PARSE FIELD VALUES:\n"
                "  Parse the field-value pairs from: {fields}\n"
                "  Match each provided field name to the form labels found in Step 1.\n"
                "  If a provided field name does not exactly match a label, use fuzzy matching:\n"
                "    - 'email' matches 'Email Address', 'E-mail', 'Your email'\n"
                "    - 'name' matches 'Full Name', 'Your Name', 'Name'\n"
                "  If a field cannot be matched to any form element, note it as unmatched.\n\n"

                "Step 3 — FILL EACH FIELD (top to bottom order):\n"
                "  For each field-value pair, follow the appropriate procedure:\n\n"
                "  TEXT INPUT or TEXTAREA:\n"
                "    a) Click on the field to focus it (cursor should appear).\n"
                "    b) Clear any existing content: press Ctrl+A (or Cmd+A on Mac), then Delete.\n"
                "    c) type_text(x, y, text='<value>', press_enter=false, clear_first=true)\n"
                "    d) press_key('Tab') to move to next field.\n"
                "    e) Verify the value appears correctly in the field.\n\n"
                "  DROPDOWN / SELECT:\n"
                "    a) Click the dropdown to open it.\n"
                "    b) wait(seconds=1, reason='Waiting for dropdown options to appear')\n"
                "    c) Look through the visible options for the matching value.\n"
                "    d) If the option is visible, click it directly.\n"
                "    e) If the dropdown has a search/filter input, type the value to filter.\n"
                "    f) If the option is not visible, scroll within the dropdown list.\n"
                "    g) Verify the selected value now shows in the dropdown field.\n\n"
                "  CHECKBOX:\n"
                "    a) Find the checkbox associated with the label.\n"
                "    b) Check its current state (checked ☑ or unchecked ☐).\n"
                "    c) If the desired state differs from current, click the checkbox.\n"
                "    d) Verify the checkbox toggled to the correct state.\n\n"
                "  RADIO BUTTON:\n"
                "    a) Find the radio button group for the field.\n"
                "    b) Locate the option matching the desired value.\n"
                "    c) Click that radio button option.\n"
                "    d) Verify the correct option is now selected (● filled).\n\n"
                "  DATE PICKER:\n"
                "    a) Click the date input field.\n"
                "    b) If a calendar widget opens:\n"
                "       - Navigate to the correct month/year using arrow buttons.\n"
                "       - Click the target day number.\n"
                "    c) If it is a plain text input, type the date in the displayed format.\n"
                "    d) press_key('Escape') to close any open calendar popup.\n"
                "    e) Verify the correct date appears in the field.\n\n"

                "Step 4 — REVIEW ALL FIELDS:\n"
                "  After filling all fields, scroll through the entire form.\n"
                "  Verify each field shows the correct value.\n"
                "  If any field was not filled correctly, click it and re-enter the value.\n"
                "  Note any required fields that were NOT provided values — report these.\n\n"

                "Step 5 — SUBMIT OR HOLD:\n"
                "  {submit_instruction}\n"
                "  If submitting:\n"
                "    a) Locate the submit button (usually labeled 'Submit', 'Save', 'Send', 'Next', 'Continue').\n"
                "    b) Click the submit button.\n"
                "    c) wait(seconds=3, reason='Waiting for form submission response')\n"
                "    d) Check for validation errors (red text, highlighted fields, error banners).\n"
                "    e) If validation errors appear, report which fields failed and why.\n"
                "    f) If submission succeeded, report the success message or new page state.\n\n"

                "Step 6 — REPORT:\n"
                "  Call task_complete with:\n"
                "    - List of fields filled: field label → value entered\n"
                "    - Any fields that could not be matched or filled\n"
                "    - Whether the form was submitted and the outcome\n"
                "    - Any validation errors encountered\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Fill fields in top-to-bottom order to avoid triggering premature validation.\n"
                "- Always use clear_first=true for text inputs to avoid appending to existing text.\n"
                "- For password fields, type the value but note that it will appear as dots/asterisks.\n"
                "- Do NOT submit the form unless explicitly instructed via submit_instruction."
            ),
            params=[
                SkillParam(
                    name="fields",
                    description="Field-value pairs to fill, as a JSON object or comma-separated 'label: value' pairs (e.g. 'Name: John, Email: john@test.com')",
                ),
                SkillParam(
                    name="submit_instruction",
                    description="Whether and how to submit the form",
                    required=False,
                    default="Do NOT submit the form — just fill the fields and report back.",
                ),
            ],
            tags=["form", "fill", "input", "type", "field", "submit", "enter"],
            examples=[
                "Fill the registration form with name John Doe and email john@example.com",
                "Fill the search form with the query 'machine learning'",
            ],
        ))

    # ────────────────────────────────────────────────
    #  TAKE SCREENSHOT
    # ────────────────────────────────────────────────

    def _register_take_screenshot(self) -> None:
        self.register_skill(Skill(
            name="take_screenshot",
            description="Describe what is currently visible on the screen in detail",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Observe and describe everything visible on the current browser screen.\n\n"

                "OBSERVATION FRAMEWORK — analyze each zone:\n"
                "  BROWSER CHROME: Address bar URL, tab title, bookmarks bar\n"
                "  PAGE HEADER:    Logo, navigation menu, search bar, user avatar, notifications\n"
                "  MAIN CONTENT:   Primary content area (the largest section of the page)\n"
                "  SIDEBAR(S):     Left or right panels, filters, menus, ads\n"
                "  FOOTER:         Bottom navigation, copyright, links\n"
                "  OVERLAYS:       Modals, popups, tooltips, banners, cookie notices\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — PAGE IDENTITY:\n"
                "  Read the browser tab title and the URL from the address bar.\n"
                "  Identify the website/application name.\n"
                "  Note the current state: is this a loaded page, loading spinner, error page, or blank?\n\n"

                "Step 2 — LAYOUT ANALYSIS:\n"
                "  Describe the overall page layout:\n"
                "    a) Header/navigation bar — what links/buttons are in the top area?\n"
                "    b) Is there a sidebar? Left, right, or both? What does it contain?\n"
                "    c) Main content area — what is the dominant content? Text, images, form, table, list?\n"
                "    d) Footer — is it visible? What does it contain?\n"
                "    e) Overall color scheme and visual style.\n\n"

                "Step 3 — INTERACTIVE ELEMENTS:\n"
                "  Identify all clickable/interactive elements visible:\n"
                "    a) Buttons — text, color, position (e.g. 'blue Submit button, bottom-right').\n"
                "    b) Links — anchor text and approximate position.\n"
                "    c) Form fields — input boxes, dropdowns, checkboxes with their labels.\n"
                "    d) Tabs or toggles — which tab/option is currently active.\n"
                "    e) Menus — any open dropdown menus or context menus.\n\n"

                "Step 4 — CONTENT DETAILS:\n"
                "  Read the key textual content:\n"
                "    a) Main heading and subheadings.\n"
                "    b) Important paragraphs, bullet points, or data.\n"
                "    c) Numbers, prices, dates, or statistics visible.\n"
                "    d) Image descriptions — what do visible images/icons depict?\n\n"

                "Step 5 — STATE AND NOTIFICATIONS:\n"
                "  Look for dynamic state indicators:\n"
                "    a) Error messages — red text, error banners, validation messages.\n"
                "    b) Success messages — green banners, confirmation text, checkmarks.\n"
                "    c) Loading indicators — spinners, skeleton screens, progress bars.\n"
                "    d) Notifications — badge counts, toast messages, alert banners.\n"
                "    e) Modal dialogs — any overlay covering the main content.\n"
                "    f) Tooltips — any tooltip or popover currently visible.\n"
                "  {extra_focus}\n\n"

                "Step 6 — REPORT:\n"
                "  Compile a structured description organized by page section.\n"
                "  Call task_complete with the full description.\n"
                "  Format:\n"
                "    URL: <current url>\n"
                "    Title: <page title>\n"
                "    Layout: <brief layout description>\n"
                "    Header: <header details>\n"
                "    Main Content: <main content details>\n"
                "    Sidebar: <sidebar details or 'None'>\n"
                "    Overlays/Modals: <any overlays or 'None'>\n"
                "    Notifications/Errors: <any alerts or 'None'>\n"
                "    Interactive Elements: <key buttons, links, forms>\n\n"

                "RULES:\n"
                "- Do NOT click anything or interact with the page — observation only.\n"
                "- Do NOT scroll — only describe what is currently visible in the viewport.\n"
                "- Be specific about positions (top-left, center, bottom-right).\n"
                "- If text is partially cut off, note that it is truncated.\n"
                "- Describe colors when they convey meaning (red error, green success, blue link)."
            ),
            params=[
                SkillParam(
                    name="extra_focus",
                    description="Optional area to focus description on, e.g. 'Pay special attention to the navigation bar' or 'Focus on any error messages'",
                    required=False,
                    default="",
                ),
            ],
            tags=["screenshot", "screen", "describe", "view", "see", "visible", "current", "observe"],
            examples=[
                "What's on the screen right now?",
                "Describe the current page",
                "Take a screenshot and tell me what you see",
            ],
        ))

    # ────────────────────────────────────────────────
    #  CLICK ELEMENT
    # ────────────────────────────────────────────────

    def _register_click_element(self) -> None:
        self.register_skill(Skill(
            name="click_element",
            description="Click a described element on the current page and report what changed",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Locate and click the specified element on the current page.\n\n"

                "ELEMENT IDENTIFICATION STRATEGIES (try in this order):\n"
                "  1. Visible text content — exact text match on buttons, links, menu items.\n"
                "  2. Aria labels — accessibility labels on icons, icon-buttons, images.\n"
                "  3. Placeholder text — 'Search...', 'Type here', etc.\n"
                "  4. Visual description — position, color, icon shape, relative location.\n"
                "  5. Class/role — button, link, tab, checkbox, input by visual style.\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — LOCATE THE ELEMENT:\n"
                "  Scan the visible viewport for the element described as: {element_description}\n"
                "  Search methodically:\n"
                "    a) Look for exact text match first (case-insensitive).\n"
                "    b) If not found by text, look for matching icons, positions, or visual cues.\n"
                "    c) If multiple elements match, prefer the most prominent/visible one.\n"
                "  Note the element's exact position (coordinates on screen).\n"
                "  If the element is NOT found in the visible viewport, proceed to Step 2.\n\n"

                "Step 2 — SCROLL INTO VIEW (if needed):\n"
                "  If the element was not found in the current viewport:\n"
                "    a) scroll_down(pixels=400)\n"
                "    b) wait(seconds=1, reason='Waiting for scrolled content to render')\n"
                "    c) Search the viewport again for the element.\n"
                "    d) Repeat scrolling up to 5 times (total ~2000px down).\n"
                "  If still not found, try scrolling up from the original position.\n"
                "  If the element cannot be found after scrolling, report failure and call task_complete.\n\n"

                "Step 3 — PREPARE TO CLICK:\n"
                "  Before clicking, note the current page state for comparison:\n"
                "    a) Current URL.\n"
                "    b) Visible content/layout.\n"
                "    c) Any open menus, modals, or dropdowns.\n"
                "  This baseline lets us detect what changed after the click.\n\n"

                "Step 4 — CLICK:\n"
                "  Click on the identified element at its center coordinates.\n"
                "  click(x, y)\n"
                "  wait(seconds=2, reason='Waiting for click response — page load, animation, or UI change')\n\n"

                "Step 5 — OBSERVE CHANGES:\n"
                "  Compare the screen to the baseline from Step 3. Identify what happened:\n"
                "    a) PAGE NAVIGATION — URL changed, new page loaded.\n"
                "       Report: new URL, new page title, what the new page shows.\n"
                "    b) DROPDOWN/MENU — a menu or dropdown list appeared.\n"
                "       Report: what options are visible in the menu.\n"
                "    c) MODAL/DIALOG — a popup or overlay appeared.\n"
                "       Report: modal title, content, and available buttons.\n"
                "    d) CONTENT CHANGE — part of the page updated (accordion, tab switch, dynamic load).\n"
                "       Report: which section changed and what it now shows.\n"
                "    e) FORM STATE — a field was toggled, selected, or focused.\n"
                "       Report: the new state of the form element.\n"
                "    f) DOWNLOAD — a file download started.\n"
                "       Report: filename if visible.\n"
                "    g) NO VISIBLE CHANGE — nothing appeared to happen.\n"
                "       Report: element may be disabled, or action may be background-only.\n\n"

                "Step 6 — REPORT:\n"
                "  Call task_complete with:\n"
                "    - Element clicked: description and position.\n"
                "    - Result: what changed (from Step 5 categories).\n"
                "    - Current state: brief description of the page now.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT double-click unless the element_description specifically says to.\n"
                "- If the element appears disabled (grayed out), report that instead of clicking.\n"
                "- If a confirmation dialog appears after clicking, do NOT auto-confirm — report it.\n"
                "- Right-click is NOT supported — only left-click."
            ),
            params=[
                SkillParam(
                    name="element_description",
                    description="Natural language description of the element to click (e.g. 'the blue Submit button', 'the Login link in the top right')",
                ),
            ],
            tags=["click", "press", "tap", "button", "link", "element", "interact"],
            examples=[
                "Click the 'Sign In' button",
                "Click the first search result",
                "Press the Submit button at the bottom of the form",
            ],
        ))

    # ────────────────────────────────────────────────
    #  EXTRACT TABLE
    # ────────────────────────────────────────────────

    def _register_extract_table(self) -> None:
        self.register_skill(Skill(
            name="extract_table",
            description="Extract structured tabular data from the current page",
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="",
            browser_template=(
                "Extract tabular data from the current page into structured rows and columns.\n\n"

                "TABLE RECOGNITION — tables may appear as:\n"
                "  HTML TABLE:    <table> with <thead>/<tbody>, <tr>/<th>/<td> elements.\n"
                "                 Has visible grid lines or alternating row colors.\n"
                "  CSS GRID/FLEX: Div-based layout that looks like a table but uses CSS grid.\n"
                "                 Rows are visually aligned but not in <table> tags.\n"
                "  LIST FORMAT:   Repeated card or row patterns with consistent columns.\n"
                "                 Common in dashboards and admin panels.\n\n"

                "EXECUTE EVERY STEP. DO NOT SKIP ANY.\n\n"

                "Step 1 — FIND THE TABLE:\n"
                "  {table_hint}\n"
                "  Scan the page for tabular data structures.\n"
                "  If multiple tables exist, identify each by:\n"
                "    a) Position on the page (top, middle, bottom).\n"
                "    b) Nearby heading or label text.\n"
                "    c) Number of columns and approximate row count.\n"
                "  Select the target table based on the hint, or the most prominent one.\n"
                "  If no table is found, check if data is in a list or card format instead.\n\n"

                "Step 2 — READ COLUMN HEADERS:\n"
                "  Identify the header row (usually the first row, often bold or with a background color).\n"
                "  Read each column header text from left to right.\n"
                "  Note the number of columns.\n"
                "  If headers are not obvious, use the first row of data to infer column meanings.\n"
                "  Common header patterns: Name, Date, Status, Amount, Actions, ID, Type, Description.\n\n"

                "Step 3 — EXTRACT VISIBLE ROWS:\n"
                "  Starting from the first data row (below headers), read each row:\n"
                "    a) Read each cell value in the row from left to right.\n"
                "    b) Associate each cell value with its column header by position.\n"
                "    c) Handle special cell types:\n"
                "       - Links: extract both the link text and the URL if visible.\n"
                "       - Status badges: read the text and note the color (green=active, red=error).\n"
                "       - Checkboxes: note checked (☑) or unchecked (☐).\n"
                "       - Icons: describe what the icon represents (edit, delete, view, etc.).\n"
                "       - Images/avatars: note 'image' and any alt text.\n"
                "       - Empty cells: record as empty/null.\n"
                "    d) Stop after {max_rows} rows or when the visible table ends.\n"
                "  Count the total rows extracted vs. visible.\n\n"

                "Step 4 — CHECK FOR MORE DATA (pagination/scrolling):\n"
                "  Look below the table for pagination controls:\n"
                "    a) Page numbers (1, 2, 3...) or 'Next' / '>' button.\n"
                "    b) 'Showing X-Y of Z' text — note the total count Z.\n"
                "    c) 'Load more' or infinite scroll indicator.\n"
                "  If pagination exists and more rows are needed (under {max_rows}):\n"
                "    a) Click 'Next' or the next page number.\n"
                "    b) wait(seconds=2, reason='Waiting for next page of table data')\n"
                "    c) Read the new rows and append to results.\n"
                "    d) Repeat until {max_rows} rows are collected or no more pages.\n"
                "  If the table is inside a scrollable container:\n"
                "    a) Scroll within the table container (not the whole page).\n"
                "    b) Read newly visible rows.\n\n"

                "Step 5 — HANDLE SORTING AND FILTERS (observation only):\n"
                "  Note any active sort indicators (▲/▼ arrows on column headers).\n"
                "  Note any active filters (filter chips, search boxes above the table).\n"
                "  Report these so the user knows the data ordering/filtering.\n\n"

                "Step 6 — REPORT:\n"
                "  Use extract_data to return the structured table data.\n"
                "  Format the output as:\n"
                "    - Table name/location on page.\n"
                "    - Column headers as the first row.\n"
                "    - Each data row as an ordered list of cell values.\n"
                "    - Row count: 'Extracted X of Y total rows'\n"
                "    - Pagination: 'Page 1 of N' or 'No pagination'\n"
                "    - Sort/filter status if applicable.\n"
                "  Call task_complete with the formatted table data.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- Do NOT click sort headers or filter controls — extract data as-is.\n"
                "- Read cells exactly as displayed — do not reformat numbers or dates.\n"
                "- If a cell contains a long text that is truncated (ending in '...'), note that.\n"
                "- If the table has an 'Actions' column with buttons, list the action names but do not click them.\n"
                "- Preserve row order as displayed on the page."
            ),
            params=[
                SkillParam(
                    name="table_hint",
                    description="Optional hint to identify which table to extract, e.g. 'the pricing table' or 'the table under Results'",
                    required=False,
                    default="Find the most prominent table on the page.",
                ),
                SkillParam(
                    name="max_rows",
                    description="Maximum number of rows to extract",
                    type="integer",
                    required=False,
                    default=50,
                ),
            ],
            tags=["table", "extract", "data", "rows", "columns", "grid", "spreadsheet", "csv"],
            examples=[
                "Extract the data table from this page",
                "Get the pricing table as structured data",
                "Read the results table and give me the data",
            ],
        ))
