"""Research connector — deep, multi-phase browser research skills.

Provides production-quality skills for:
- Deep multi-source research with Google Doc output
- Side-by-side comparison research
- Quick topic summaries

Each skill uses a multi-phase browser workflow: search the web, open and
read multiple sources in depth, synthesize findings, and produce a
structured Google Doc deliverable.
"""

from __future__ import annotations

from backend.connectors.base import BaseConnector, Skill, SkillParam, SkillMode


class ResearchConnector(BaseConnector):
    name = "research"
    description = "Deep research — multi-source investigation, comparison, and summarization with Google Doc output"
    icon = "magnifying_glass"
    category = "research"

    def _setup(self) -> None:
        self._register_deep_research()
        self._register_compare_options()
        self._register_summarize_topic()

    # ────────────────────────────────────────────────
    #  DEEP RESEARCH
    # ────────────────────────────────────────────────

    def _register_deep_research(self) -> None:
        self.register_skill(Skill(
            name="deep_research",
            description=(
                "Conduct thorough multi-source research on any topic. "
                "Searches the web, reads multiple full articles in depth, "
                "synthesizes findings, and produces a structured Google Doc report."
            ),
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://www.google.com",
            browser_template=(
                "You are conducting a DEEP RESEARCH task. This is a multi-phase workflow.\n"
                "You MUST complete ALL four phases. Do NOT stop after searching — you must\n"
                "open, read, and synthesize multiple sources.\n\n"

                "TOPIC: {topic}\n"
                "NUMBER OF SOURCES TO READ: {num_sources}\n"
                "OUTPUT FORMAT: {output_format}\n"
                "DETAIL LEVEL: {detail_level}\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 1: SEARCH — Find the best sources\n"
                "══════════════════════════════════════════════\n\n"

                "Step 1 — NAVIGATE TO GOOGLE:\n"
                "  Go to https://www.google.com\n"
                "  wait(seconds=2, reason='Waiting for Google homepage to load')\n"
                "  Verify you see the Google logo and search input.\n"
                "  If a cookie consent banner appears, click 'Accept all' first.\n\n"

                "Step 2 — SEARCH:\n"
                "  Click the search input/textarea in the center of the page.\n"
                "  type_text(x, y, text='{topic}', press_enter=false)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n"
                "  Verify search results appear (blue title links and snippets).\n\n"

                "Step 3 — EXTRACT SEARCH RESULTS:\n"
                "  Read the search results page carefully.\n"
                "  Identify the top {num_sources} organic results (skip ads marked 'Sponsored').\n"
                "  For each result, note:\n"
                "    a) Title — the blue clickable heading.\n"
                "    b) URL — the green/gray URL line.\n"
                "    c) Snippet — the preview text.\n"
                "  REMEMBER these URLs and titles — you will visit each one.\n"
                "  If fewer than {num_sources} results exist, note all available.\n\n"

                "Step 4 — VERIFY PHASE 1:\n"
                "  Confirm you have identified {num_sources} source URLs to visit.\n"
                "  List them mentally before proceeding.\n"
                "  DO NOT call task_complete — you are only 25% done.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 2: DEEP READ — Read each source fully\n"
                "══════════════════════════════════════════════\n\n"

                "For EACH of the {num_sources} sources identified in Phase 1, perform\n"
                "Steps 5-9. You MUST visit every source, not just one.\n\n"

                "Step 5 — OPEN SOURCE [N]:\n"
                "  Click on the blue title link of the next source in the search results.\n"
                "  wait(seconds=3, reason='Waiting for source page to fully load')\n"
                "  If the page shows a paywall or login wall, note it and go back.\n"
                "  If a cookie banner appears, dismiss it first.\n\n"

                "Step 6 — READ FULL CONTENT:\n"
                "  Read the visible content on the page: headings, paragraphs, lists, data.\n"
                "  scroll_down(pixels=600)\n"
                "  wait(seconds=1, reason='Loading more content')\n"
                "  Read the newly visible content.\n"
                "  scroll_down(pixels=600)\n"
                "  wait(seconds=1, reason='Loading more content')\n"
                "  Read more content.\n"
                "  scroll_down(pixels=600)\n"
                "  wait(seconds=1, reason='Loading more content')\n"
                "  Read any remaining content.\n"
                "  Continue scrolling if the page has substantial content (up to 5 scrolls total).\n\n"

                "Step 7 — EXTRACT KEY INFORMATION:\n"
                "  From this source, extract and remember:\n"
                "    a) Key facts, statistics, and data points.\n"
                "    b) Expert opinions and direct quotes.\n"
                "    c) Recommendations, tips, or advice.\n"
                "    d) Pros/cons or comparisons mentioned.\n"
                "    e) Unique insights not found in other sources.\n"
                "    f) The article's publication date and author (if visible).\n"
                "  Use extract_data to capture the structured information.\n\n"

                "Step 8 — GO BACK TO SEARCH RESULTS:\n"
                "  Click the browser back button or navigate back to the search results page.\n"
                "  wait(seconds=2, reason='Waiting for search results page to reload')\n"
                "  Verify you are back on the Google search results page.\n"
                "  If you are not on the search results, navigate to Google and re-search.\n\n"

                "Step 9 — REPEAT FOR NEXT SOURCE:\n"
                "  Repeat Steps 5-8 for the next source in your list.\n"
                "  Continue until you have read ALL {num_sources} sources.\n"
                "  Track which sources you have visited vs. which remain.\n"
                "  DO NOT skip any source. DO NOT call task_complete yet.\n\n"

                "Step 10 — VERIFY PHASE 2:\n"
                "  Confirm you have visited and read ALL {num_sources} sources.\n"
                "  You should now have detailed notes from each source.\n"
                "  If you missed any source, go back and read it now.\n"
                "  DO NOT proceed until all sources are read.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 3: SYNTHESIZE — Create the Google Doc\n"
                "══════════════════════════════════════════════\n\n"

                "Step 11 — CREATE A NEW GOOGLE DOC:\n"
                "  Navigate to https://docs.google.com/document/create (NOT docs.new — it shows a template popup). If a popover appears, press Escape first.\n"
                "  wait(seconds=4, reason='Waiting for new Google Doc to load')\n"
                "  Verify a blank Google Doc has opened with the cursor in the document.\n"
                "  If prompted to sign in, wait for auto-redirect after sign-in.\n\n"

                "Step 12 — SET THE DOCUMENT TITLE:\n"
                "  Click on 'Untitled document' at the top-left of the Google Docs interface.\n"
                "  type_text(x, y, text='Research: {topic}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter') or click into the document body to confirm the title.\n"
                "  wait(seconds=1, reason='Waiting for title to save')\n\n"

                "Step 13 — WRITE THE DOCUMENT HEADING:\n"
                "  Click in the document body area.\n"
                "  The content should be organized by THEME, not by source.\n"
                "  First, type the main title. To make it a Heading 1:\n"
                "    Type the title text for the research topic.\n"
                "    Select the text you just typed (Ctrl+A or click-drag).\n"
                "    Use the Styles dropdown (shows 'Normal text') in the toolbar and select 'Heading 1'.\n"
                "    Or use keyboard shortcut: Ctrl+Alt+1 (Cmd+Option+1 on Mac).\n"
                "  press_key('Enter') to move to a new line.\n\n"

                "Step 14 — WRITE OVERVIEW SECTION:\n"
                "  Type 'Overview' and format it as Heading 2 (Ctrl+Alt+2 / Cmd+Option+2).\n"
                "  press_key('Enter')\n"
                "  Type a 2-4 sentence overview paragraph summarizing the research topic\n"
                "  and what this document covers. Draw from ALL sources read.\n"
                "  press_key('Enter')\n"
                "  press_key('Enter')\n\n"

                "Step 15 — WRITE TABLE OF CONTENTS:\n"
                "  Type 'Table of Contents' and format as Heading 2.\n"
                "  press_key('Enter')\n"
                "  Type a numbered list of the major sections you will cover.\n"
                "  Organize sections by THEME (e.g., 'Key Features', 'Pricing', 'Recommendations')\n"
                "  NOT by source (do NOT write 'Source 1 says...', 'Source 2 says...').\n"
                "  press_key('Enter')\n"
                "  press_key('Enter')\n\n"

                "Step 16 — WRITE THEMATIC SECTIONS:\n"
                "  For each theme/topic area identified in your table of contents:\n"
                "    a) Type the section heading and format as Heading 2.\n"
                "    b) press_key('Enter')\n"
                "    c) Write detailed paragraphs synthesizing information from MULTIPLE sources.\n"
                "       - If {detail_level} is 'brief': 2-3 sentences per section.\n"
                "       - If {detail_level} is 'detailed': 1-2 paragraphs per section with specifics.\n"
                "       - If {detail_level} is 'comprehensive': 2-4 paragraphs per section with\n"
                "         data points, quotes, examples, and nuanced analysis.\n"
                "    d) Use bold text (Ctrl+B / Cmd+B) for key terms and important findings.\n"
                "    e) Use bullet points for lists of items, tips, or recommendations.\n"
                "       To create a bullet list: click the bulleted list icon in the toolbar,\n"
                "       or type '- ' at the start of a line (Google Docs auto-formats).\n"
                "    f) Include specific data: numbers, percentages, prices, dates.\n"
                "    g) press_key('Enter') twice after each section.\n"
                "  Write at least 3-5 thematic sections depending on the topic.\n\n"

                "Step 17 — WRITE KEY FINDINGS / RECOMMENDATIONS:\n"
                "  Type 'Key Findings and Recommendations' and format as Heading 2.\n"
                "  press_key('Enter')\n"
                "  Write a bulleted list of the top 5-10 actionable takeaways.\n"
                "  These should be the most valuable insights distilled from all sources.\n"
                "  Use bold for the key point, followed by a brief explanation.\n"
                "  press_key('Enter')\n"
                "  press_key('Enter')\n\n"

                "Step 18 — WRITE SOURCES / REFERENCES:\n"
                "  Type 'Sources' and format as Heading 2.\n"
                "  press_key('Enter')\n"
                "  List each source you read as a numbered list:\n"
                "    1. [Article Title] — [URL] (accessed today)\n"
                "    2. [Article Title] — [URL] (accessed today)\n"
                "    ... and so on for all {num_sources} sources.\n"
                "  press_key('Enter')\n\n"

                "Step 19 — VERIFY THE DOCUMENT:\n"
                "  Scroll up to the top of the document.\n"
                "  Review the document structure: title, overview, TOC, thematic sections,\n"
                "  recommendations, and sources should all be present.\n"
                "  Check that headings are properly formatted (larger text, bold).\n"
                "  Verify the document has substantive content, not just placeholders.\n"
                "  If any section is missing or empty, add content now.\n\n"

                "Step 20 — COPY THE DOCUMENT URL:\n"
                "  Look at the browser address bar and note the full Google Docs URL.\n"
                "  The URL format is: https://docs.google.com/document/d/XXXXX/edit\n"
                "  Remember this URL to share with the user.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 4: DELIVER — Report back to user\n"
                "══════════════════════════════════════════════\n\n"

                "Step 21 — FINAL DELIVERY:\n"
                "  If {output_format} is 'google_doc':\n"
                "    Call task_complete with:\n"
                "      - The Google Doc URL.\n"
                "      - A brief note: 'Research complete. Document created with N sections from N sources.'\n\n"
                "  If {output_format} is 'summary':\n"
                "    Call task_complete with:\n"
                "      - A detailed text summary of ALL findings (do NOT skip content).\n"
                "      - Organized by theme with key findings and recommendations.\n"
                "      - Sources listed at the end.\n\n"
                "  If {output_format} is 'both':\n"
                "    Call task_complete with:\n"
                "      - The Google Doc URL.\n"
                "      - PLUS a concise executive summary (5-10 bullet points of key findings).\n"
                "      - List of sources consulted.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- You MUST visit and read ALL {num_sources} sources. Do NOT stop at search results.\n"
                "- Scroll down MULTIPLE times on each source page to read the FULL content.\n"
                "- Organize the document by THEME, not by source.\n"
                "- Use Google Docs formatting: Headings, bold, bullet lists.\n"
                "- If a source is behind a paywall, skip it and find a replacement from search results.\n"
                "- If Google Docs fails to load, retry once. If it fails again, deliver as summary only.\n"
                "- Do NOT call task_complete until you have completed ALL four phases.\n"
                "- If CAPTCHA appears on Google, report it and call task_complete with an error."
            ),
            params=[
                SkillParam(
                    name="topic",
                    description="The research topic or question to investigate in depth",
                ),
                SkillParam(
                    name="num_sources",
                    description="Number of sources to read and synthesize",
                    type="integer",
                    required=False,
                    default=5,
                ),
                SkillParam(
                    name="output_format",
                    description="How to deliver the research results",
                    required=False,
                    enum=["google_doc", "summary", "both"],
                    default="both",
                ),
                SkillParam(
                    name="detail_level",
                    description="How detailed the research output should be",
                    required=False,
                    enum=["brief", "detailed", "comprehensive"],
                    default="detailed",
                ),
            ],
            tags=[
                "research", "deep search", "investigate", "report", "analyze",
                "study", "explore", "learn about", "itinerary", "plan", "guide",
            ],
            examples=[
                "Research a 5-day Japan itinerary with top attractions and travel tips",
                "Deep dive into React vs Vue comparison for a new project",
                "Research the best laptops under $1000 in 2026",
                "Investigate the current state of renewable energy adoption worldwide",
            ],
        ))

    # ────────────────────────────────────────────────
    #  COMPARE OPTIONS
    # ────────────────────────────────────────────────

    def _register_compare_options(self) -> None:
        self.register_skill(Skill(
            name="compare_options",
            description=(
                "Research and compare multiple items side-by-side. "
                "Searches for each option, reads reviews and articles, "
                "and produces a structured comparison in a Google Doc with a table."
            ),
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://www.google.com",
            browser_template=(
                "You are conducting a COMPARISON RESEARCH task. This is a multi-phase workflow.\n"
                "You MUST search for and read sources about EACH item being compared,\n"
                "then create a comparison document.\n\n"

                "ITEMS TO COMPARE: {items}\n"
                "COMPARISON CRITERIA: {criteria}\n"
                "SOURCES PER ITEM: {num_sources}\n"
                "OUTPUT FORMAT: {output_format}\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 1: SEARCH — Find sources for each item\n"
                "══════════════════════════════════════════════\n\n"

                "You will research EACH item separately. Parse the items from: {items}\n"
                "Identify each distinct option/product/thing to compare.\n\n"

                "FOR EACH ITEM, perform Steps 1-4:\n\n"

                "Step 1 — SEARCH FOR ITEM [N]:\n"
                "  Navigate to https://www.google.com\n"
                "  wait(seconds=2, reason='Waiting for Google to load')\n"
                "  Click the search input.\n"
                "  type_text(x, y, text='<item name> review {criteria}', press_enter=false)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results')\n"
                "  Skip ads (marked 'Sponsored').\n\n"

                "Step 2 — IDENTIFY TOP SOURCES:\n"
                "  Read the search results page.\n"
                "  Identify {num_sources} organic results that look like reviews, comparisons,\n"
                "  or detailed analysis articles. Prefer:\n"
                "    - Professional review sites\n"
                "    - Comparison articles\n"
                "    - Expert analysis\n"
                "  Note the title, URL, and snippet for each.\n\n"

                "Step 3 — READ EACH SOURCE:\n"
                "  For each of the {num_sources} sources:\n"
                "    a) Click the blue title link to open the source.\n"
                "    b) wait(seconds=3, reason='Waiting for page to load')\n"
                "    c) Read the visible content on the page.\n"
                "    d) scroll_down(pixels=600)\n"
                "       wait(seconds=1, reason='Loading more content')\n"
                "       Read the newly visible content.\n"
                "    e) scroll_down(pixels=600)\n"
                "       wait(seconds=1, reason='Loading more content')\n"
                "       Read more content.\n"
                "    f) scroll_down(pixels=600)\n"
                "       wait(seconds=1, reason='Loading more content')\n"
                "       Read any remaining content.\n"
                "    g) Extract key information for this item:\n"
                "       - Features, specs, capabilities\n"
                "       - Pros and cons\n"
                "       - Pricing and value\n"
                "       - Expert ratings or scores\n"
                "       - User feedback or consensus\n"
                "    h) Use extract_data to capture the information.\n"
                "    i) Click the back button to return to search results.\n"
                "       wait(seconds=2, reason='Returning to search results')\n\n"

                "Step 4 — MOVE TO NEXT ITEM:\n"
                "  After reading all sources for this item, proceed to search for the next item.\n"
                "  Repeat Steps 1-3 for every item in the comparison.\n\n"

                "Step 5 — VERIFY PHASE 1:\n"
                "  Confirm you have researched ALL items and read {num_sources} sources per item.\n"
                "  You should have detailed notes on each item. DO NOT call task_complete.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 2: SYNTHESIZE — Build the comparison doc\n"
                "══════════════════════════════════════════════\n\n"

                "Step 6 — CREATE A NEW GOOGLE DOC:\n"
                "  Navigate to https://docs.google.com/document/create (NOT docs.new — it shows a template popup). If a popover appears, press Escape first.\n"
                "  wait(seconds=4, reason='Waiting for new Google Doc to load')\n"
                "  Verify a blank document has opened.\n\n"

                "Step 7 — SET DOCUMENT TITLE:\n"
                "  Click 'Untitled document' at the top-left.\n"
                "  type_text(x, y, text='Comparison: {items}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter') or click into the document body.\n"
                "  wait(seconds=1, reason='Waiting for title to save')\n\n"

                "Step 8 — WRITE INTRODUCTION:\n"
                "  Click in the document body.\n"
                "  Type the main title and format as Heading 1 (Ctrl+Alt+1 / Cmd+Option+1).\n"
                "  press_key('Enter')\n"
                "  Type a brief introduction explaining what is being compared and why.\n"
                "  If {criteria} was provided, mention the criteria being evaluated.\n"
                "  press_key('Enter')\n"
                "  press_key('Enter')\n\n"

                "Step 9 — WRITE COMPARISON TABLE:\n"
                "  Type 'Comparison Table' and format as Heading 2 (Ctrl+Alt+2 / Cmd+Option+2).\n"
                "  press_key('Enter')\n"
                "  Create a comparison table using Google Docs table:\n"
                "    a) Go to Insert menu > Table > select the appropriate grid size.\n"
                "       Rows = number of criteria + 1 (for header).\n"
                "       Columns = number of items + 1 (for criteria labels).\n"
                "    b) Fill the header row: first cell = 'Criteria', then each item name.\n"
                "    c) Fill each row with a criterion and the corresponding value for each item.\n"
                "    d) Use Tab to move between cells.\n"
                "  Key criteria to include (plus any from {criteria}):\n"
                "    - Price / Cost\n"
                "    - Key features / Specs\n"
                "    - Pros\n"
                "    - Cons\n"
                "    - Expert rating (if available)\n"
                "    - Best for (use case)\n"
                "  press_key('Enter') after the table.\n"
                "  press_key('Enter')\n\n"

                "Step 10 — WRITE DETAILED ANALYSIS PER ITEM:\n"
                "  For each item being compared:\n"
                "    a) Type the item name and format as Heading 2.\n"
                "    b) press_key('Enter')\n"
                "    c) Write a detailed analysis covering strengths, weaknesses, and best use cases.\n"
                "    d) Use bold (Ctrl+B / Cmd+B) for key highlights.\n"
                "    e) Use bullet points for pros and cons lists.\n"
                "    f) press_key('Enter') twice after each item section.\n\n"

                "Step 11 — WRITE VERDICT / RECOMMENDATION:\n"
                "  Type 'Verdict and Recommendation' and format as Heading 2.\n"
                "  press_key('Enter')\n"
                "  Write a clear recommendation:\n"
                "    - Which item wins overall and why.\n"
                "    - Which item is best for specific use cases or user types.\n"
                "    - Any caveats or considerations.\n"
                "  Use bold for the final recommendation.\n"
                "  press_key('Enter')\n"
                "  press_key('Enter')\n\n"

                "Step 12 — WRITE SOURCES:\n"
                "  Type 'Sources' and format as Heading 2.\n"
                "  press_key('Enter')\n"
                "  List all sources consulted as a numbered list:\n"
                "    1. [Article Title] — [URL]\n"
                "    2. [Article Title] — [URL]\n"
                "  press_key('Enter')\n\n"

                "Step 13 — VERIFY THE DOCUMENT:\n"
                "  Scroll to the top and review the entire document.\n"
                "  Verify: title, introduction, comparison table, per-item analysis,\n"
                "  verdict, and sources are all present and substantive.\n"
                "  Note the Google Docs URL from the address bar.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 3: DELIVER — Report back to user\n"
                "══════════════════════════════════════════════\n\n"

                "Step 14 — FINAL DELIVERY:\n"
                "  If {output_format} is 'google_doc':\n"
                "    Call task_complete with the Google Doc URL and a brief note.\n\n"
                "  If {output_format} is 'summary':\n"
                "    Call task_complete with a text summary including the comparison table\n"
                "    (formatted as text), key differences, and your recommendation.\n\n"
                "  If {output_format} is 'both':\n"
                "    Call task_complete with the Google Doc URL PLUS a concise summary:\n"
                "      - Quick comparison highlights (3-5 bullets).\n"
                "      - The winner/recommendation.\n"
                "      - Link to the full document.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- You MUST research EVERY item being compared. Do NOT skip any.\n"
                "- Read {num_sources} sources per item — visit each page, scroll, and extract.\n"
                "- The comparison table is MANDATORY — do not skip it.\n"
                "- Organize analysis by item, but the verdict should compare across items.\n"
                "- Be objective: present genuine pros and cons for each option.\n"
                "- If a source is paywalled, go back and find a replacement.\n"
                "- Do NOT call task_complete until all phases are complete."
            ),
            params=[
                SkillParam(
                    name="items",
                    description="The items to compare (e.g. 'iPhone 16 vs Samsung Galaxy S26 vs Pixel 10')",
                ),
                SkillParam(
                    name="criteria",
                    description="Specific criteria to evaluate (e.g. 'camera quality, battery life, price')",
                    required=False,
                    default="general features, price, pros, cons, best use case",
                ),
                SkillParam(
                    name="num_sources",
                    description="Number of sources to read per item",
                    type="integer",
                    required=False,
                    default=3,
                ),
                SkillParam(
                    name="output_format",
                    description="How to deliver the comparison results",
                    required=False,
                    enum=["google_doc", "summary", "both"],
                    default="both",
                ),
            ],
            tags=[
                "compare", "versus", "vs", "which is better", "pros cons", "review",
            ],
            examples=[
                "Compare React vs Vue vs Svelte for a new frontend project",
                "iPhone 16 Pro vs Samsung Galaxy S26 Ultra — which should I buy?",
                "Compare AWS vs GCP vs Azure for a startup",
                "Which is better: Notion vs Obsidian vs Roam Research?",
            ],
        ))

    # ────────────────────────────────────────────────
    #  SUMMARIZE TOPIC
    # ────────────────────────────────────────────────

    def _register_summarize_topic(self) -> None:
        self.register_skill(Skill(
            name="summarize_topic",
            description=(
                "Quick research summary on any topic. Searches the web, reads the "
                "top 3 results, and creates a concise summary in a Google Doc. "
                "Lighter and faster than deep_research."
            ),
            connector=self.name,
            mode=SkillMode.BROWSER,
            start_url="https://www.google.com",
            browser_template=(
                "You are conducting a QUICK RESEARCH SUMMARY. This is a multi-phase workflow\n"
                "but lighter than a deep research task. You will read 3 sources and produce\n"
                "a concise summary.\n\n"

                "TOPIC: {topic}\n"
                "LENGTH: {length}\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 1: SEARCH — Find top sources\n"
                "══════════════════════════════════════════════\n\n"

                "Step 1 — NAVIGATE AND SEARCH:\n"
                "  Go to https://www.google.com\n"
                "  wait(seconds=2, reason='Waiting for Google homepage to load')\n"
                "  Click the search input.\n"
                "  type_text(x, y, text='{topic}', press_enter=false)\n"
                "  press_key('Enter')\n"
                "  wait(seconds=3, reason='Waiting for search results to load')\n"
                "  Verify search results appear.\n\n"

                "Step 2 — IDENTIFY TOP 3 RESULTS:\n"
                "  Read the search results page.\n"
                "  Identify the top 3 organic results (skip ads).\n"
                "  Note title, URL, and snippet for each.\n"
                "  If a featured snippet exists, include that information.\n"
                "  DO NOT call task_complete — you must read the actual sources.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 2: READ — Open and read each source\n"
                "══════════════════════════════════════════════\n\n"

                "For EACH of the 3 sources, perform Steps 3-5:\n\n"

                "Step 3 — OPEN SOURCE [N]:\n"
                "  Click the blue title link of the next result.\n"
                "  wait(seconds=3, reason='Waiting for page to load')\n"
                "  If paywalled, note it and go back to try the next result.\n\n"

                "Step 4 — READ CONTENT:\n"
                "  Read the visible content: headings, first few paragraphs, key data.\n"
                "  scroll_down(pixels=600)\n"
                "  wait(seconds=1, reason='Loading more content')\n"
                "  Read the next section of content.\n"
                "  scroll_down(pixels=600)\n"
                "  wait(seconds=1, reason='Loading more content')\n"
                "  Read any additional key content.\n"
                "  Extract the most important facts, definitions, and takeaways.\n"
                "  Use extract_data to capture information from this source.\n\n"

                "Step 5 — GO BACK:\n"
                "  Click the browser back button.\n"
                "  wait(seconds=2, reason='Returning to search results')\n"
                "  Verify you are on the search results page.\n"
                "  Repeat Steps 3-5 for the next source.\n\n"

                "Step 6 — VERIFY PHASE 2:\n"
                "  Confirm you have read all 3 sources.\n"
                "  You should have key information from each. DO NOT call task_complete.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 3: SYNTHESIZE — Create summary doc\n"
                "══════════════════════════════════════════════\n\n"

                "Step 7 — CREATE GOOGLE DOC:\n"
                "  Navigate to https://docs.google.com/document/create (NOT docs.new — it shows a template popup). If a popover appears, press Escape first.\n"
                "  wait(seconds=4, reason='Waiting for new Google Doc to load')\n"
                "  Verify a blank document has opened.\n\n"

                "Step 8 — SET TITLE:\n"
                "  Click 'Untitled document' at the top-left.\n"
                "  type_text(x, y, text='Summary: {topic}', press_enter=false, clear_first=true)\n"
                "  press_key('Enter') or click into the document body.\n"
                "  wait(seconds=1, reason='Waiting for title to save')\n\n"

                "Step 9 — WRITE THE SUMMARY:\n"
                "  Click in the document body.\n\n"

                "  a) Type the topic as a title and format as Heading 1 (Ctrl+Alt+1 / Cmd+Option+1).\n"
                "     press_key('Enter')\n\n"

                "  b) Type 'Overview' and format as Heading 2 (Ctrl+Alt+2 / Cmd+Option+2).\n"
                "     press_key('Enter')\n"
                "     Write a clear overview paragraph explaining what this topic is about.\n"
                "     press_key('Enter')\n"
                "     press_key('Enter')\n\n"

                "  c) Type 'Key Points' and format as Heading 2.\n"
                "     press_key('Enter')\n"
                "     Write the main points as a bulleted list:\n"
                "     - If {length} is 'short': 3-5 bullet points, 1 sentence each.\n"
                "     - If {length} is 'medium': 5-8 bullet points, 1-2 sentences each.\n"
                "     - If {length} is 'long': 8-12 bullet points with detailed explanations.\n"
                "     Use bold (Ctrl+B / Cmd+B) for the key term in each bullet.\n"
                "     press_key('Enter')\n"
                "     press_key('Enter')\n\n"

                "  d) Type 'Quick Takeaway' and format as Heading 2.\n"
                "     press_key('Enter')\n"
                "     Write 1-2 sentences with the single most important thing to know.\n"
                "     Use bold for emphasis.\n"
                "     press_key('Enter')\n"
                "     press_key('Enter')\n\n"

                "  e) Type 'Sources' and format as Heading 2.\n"
                "     press_key('Enter')\n"
                "     List the 3 sources as a numbered list:\n"
                "       1. [Title] — [URL]\n"
                "       2. [Title] — [URL]\n"
                "       3. [Title] — [URL]\n\n"

                "Step 10 — VERIFY:\n"
                "  Scroll to the top and review the document.\n"
                "  Verify it has: title, overview, key points, takeaway, and sources.\n"
                "  Note the Google Docs URL from the address bar.\n\n"

                "══════════════════════════════════════════════\n"
                "  PHASE 4: DELIVER — Report to user\n"
                "══════════════════════════════════════════════\n\n"

                "Step 11 — FINAL DELIVERY:\n"
                "  Call task_complete with:\n"
                "    - The Google Doc URL.\n"
                "    - A brief executive summary (3-5 bullet points of the key findings).\n"
                "    - The quick takeaway sentence.\n\n"

                "RULES:\n"
                "- ONE action per turn. Check screenshot after each action.\n"
                "- You MUST open and read all 3 sources. Do NOT stop at search results.\n"
                "- Scroll down on each source page to read beyond the fold.\n"
                "- Keep the summary concise — this is NOT a deep research task.\n"
                "- Use Google Docs formatting: Headings, bold, bullet lists.\n"
                "- If a source is paywalled, skip it and use the next search result instead.\n"
                "- Do NOT call task_complete until the Google Doc is created and verified."
            ),
            params=[
                SkillParam(
                    name="topic",
                    description="The topic to summarize (e.g. 'What is quantum computing?')",
                ),
                SkillParam(
                    name="length",
                    description="How long the summary should be",
                    required=False,
                    enum=["short", "medium", "long"],
                    default="medium",
                ),
            ],
            tags=[
                "summarize", "brief", "overview", "quick research", "explain", "what is",
            ],
            examples=[
                "Give me a quick summary of what blockchain technology is",
                "Summarize the latest developments in AI regulation",
                "What is CRISPR? Quick overview please",
                "Brief me on the current housing market trends",
            ],
        ))
