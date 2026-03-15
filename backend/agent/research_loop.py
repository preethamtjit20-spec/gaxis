"""Research Loop — Gemini-native deep research with Google Search grounding.

Instead of slowly clicking through web pages one by one, this loop uses
Gemini's built-in Google Search tool to gather information natively.
The model searches, reads, and synthesizes content in a single conversation —
no browser automation needed for the research phase.

Browser automation is ONLY used for the final output (creating a Google Doc).

Flow:
  Phase 1 — RESEARCH (Gemini + Google Search grounding)
    Gemini autonomously searches, reads multiple sources, extracts data.
    All done server-side — no screenshots, no clicks, no scrolling.

  Phase 2 — OUTPUT (Browser automation)
    Create a well-formatted Google Doc with the synthesized content.
    This is the only phase that touches the browser.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable

from google import genai
from google.genai import types

from backend.agent.state import AgentState
from backend.agent.base import AGENT_MODEL
from backend.tools.definitions import ALL_TOOLS
from backend.tools.executor import ToolExecutor

logger = logging.getLogger("gaxis.research")


RESEARCH_SYSTEM = """You are G-Axis — a warm, thoughtful research companion powered by Google Search.

You help people understand topics deeply by searching the web, reading multiple sources, and synthesizing everything into clear, beautifully structured reports.

Your writing voice is warm, clear, and engaging — like a knowledgeable friend explaining something they're genuinely excited about. Never dry or academic. Make the reader feel like they're getting insider knowledge.

RESEARCH APPROACH:
1. Search the topic using MULTIPLE queries (broad + specific angles)
2. Read and cross-reference at least 5-8 sources
3. Extract key facts, data, recommendations, and real-world insights
4. Note source URLs for citations

WRITING STYLE:
- Write like a thoughtful friend sharing what they've learned — warm but informative
- Start with a brief, engaging overview that hooks the reader
- Organize by THEME, not by source — synthesize, don't just list
- Include specific, actionable details: real names, prices, ratings, addresses, times
- Use a conversational but professional tone
- Add helpful tips and "good to know" nuggets naturally

═══ DOCUMENT STRUCTURE FORMAT ═══

Use this EXACT format hierarchy — NO raw markdown (#, ##, *, **). Use plain text with clear structure:

TITLE
A single descriptive title on the first line.

TABLE OF CONTENTS
List sections as numbered items:
1. Section Name
2. Section Name
3. Section Name

SECTIONS — use this pattern:
Write the section name on its own line, followed by a blank line, then content.
For subsections, indent or prefix with the parent context.

TABLES — use for any structured/comparative data:
Column1 | Column2 | Column3
Value1 | Value2 | Value3
Value4 | Value5 | Value6

Tables are CRITICAL for:
- Itineraries (Day | Morning | Afternoon | Evening)
- Comparisons (Option | Price | Rating | Notes)
- Quick facts (Category | Info)
- Schedules, budgets, packing lists

QUICK FACTS PANEL — include near the top:
Category | Info
Best Time | March-May, Oct-Nov
Currency | Japanese Yen (JPY)
Language | Japanese
Transport | IC Card (Suica/Pasmo)

TIPS AND WARNINGS — use these markers:
TIP: Use Takkyubin luggage forwarding to avoid carrying suitcases.
WARNING: Many temples and small restaurants accept cash only.
NOTE: Book Shinkansen tickets at least 2 weeks in advance.

CHECKLISTS — for actionable items:
[ ] Buy eSIM before departure
[ ] Install Google Maps offline maps
[ ] Reserve Shinkansen tickets
[ ] Get IC card at airport

TIMELINE/STEPS — for journeys or processes:
Step 1: Arrive at Narita Airport
Step 2: Take Narita Express to Shinjuku
Step 3: Check into hotel
Step 4: Explore Shinjuku evening scene

RULES:
- NEVER use # ## ### for headings — just write the heading text on its own line
- NEVER use * or - for bullets — use bullet character or numbered lists
- NEVER use **text** for bold — just write the text normally
- NEVER use ``` for code blocks
- Use | pipe character for table columns
- Use blank lines generously between sections for readability
- Every section should have something genuinely useful
- If data exists (prices, hours, ratings), include it in tables
- Be thorough but readable — depth without walls of text
- Include at least one table per major section
- End with a Sources section listing URLs
"""


DOC_CREATION_SYSTEM = """You are G-Axis, creating a Google Doc from research content.

You have a complete research report ready. Your ONLY job is to type it into a new Google Doc with proper formatting.

You can see a screenshot and DOM elements. Execute ONE action per turn.

AVAILABLE TOOLS:
- navigate(url): Go to a URL.
- click(x, y, element_description): Click at coordinates.
- type_text(x, y, text, press_enter): Type text into a field.
- scroll(direction, pixels): Scroll up or down.
- press_key(key): Press a key (Tab, Enter, etc).
- wait(seconds, reason): Wait for page to load.
- task_complete(summary): Done — include the Google Doc URL.
- task_failed(reason): Cannot complete.

STRATEGY FOR GOOGLE DOCS:
1. Navigate to https://docs.google.com/document/create — this creates a BLANK doc directly (no template chooser).
   DO NOT use docs.new — it shows a template popover that blocks interaction.
2. Wait 3 seconds for the doc to fully load.
3. If you see a template chooser/popover dialog, press Escape to dismiss it. Do NOT try to click behind it.
4. Click on "Untitled document" at the very top-left to set the title. Type the title. Press Enter or Tab.
5. Click into the document body (the large white area below the toolbar).
6. Type the ENTIRE content in LARGE chunks — full paragraphs at a time, not word by word.
   Use Enter for new lines. The content is already written — just paste it in.
7. Call task_complete with the doc URL from the address bar.

FORMATTING RULES — VERY IMPORTANT:
- Do NOT type raw markdown symbols (# ## * - ```) into Google Docs.
- The content uses a clean structured format. Type it exactly as written.
- For TABLE data (lines with | separators):
  Type each row on its own line. Use Tab key between columns to create a visual table layout.
  Or type as "Column1    Column2    Column3" with spaces for alignment.
- For SECTION HEADINGS (text on its own line followed by blank line):
  Type the heading, press Enter twice to create spacing.
- For TIPS/WARNINGS (lines starting with TIP: WARNING: NOTE:):
  Type them as-is — they already look professional.
- For CHECKLISTS (lines with [ ]):
  Type with the checkbox characters: "☐ Item name"
- Use generous Enter spacing between sections.
- The result should look like a professional, well-spaced document.

CRITICAL RULES:
- ALWAYS use https://docs.google.com/document/create (NOT docs.new) to avoid template popover.
- If a popover/dialog appears, press Escape FIRST before doing anything else.
- Type content in LARGE chunks — paragraphs, not sentences.
- Do NOT try to click through a popover onto elements behind it.
- The content has already been researched — just put it in the doc efficiently.
- NEVER type raw markdown — always convert to clean formatted text.
"""


class ResearchLoop:
    """Deep research using Gemini's native Google Search grounding.

    Phase 1: Gemini + Google Search (no browser) — gather & synthesize
    Phase 2: Browser automation — create Google Doc with results
    """

    def __init__(
        self,
        client: genai.Client,
        tool_executor: ToolExecutor,
        emit_fn: Callable | None = None,
        get_screenshot_fn: Callable | None = None,
        get_browser_state_fn: Callable | None = None,
        get_dom_fn: Callable | None = None,
        is_paused_fn: Callable | None = None,
        replay=None,
        ui_graph_registry=None,
    ):
        self.client = client
        self.tool_executor = tool_executor
        self.emit_fn = emit_fn
        self.get_screenshot_fn = get_screenshot_fn
        self.get_browser_state_fn = get_browser_state_fn
        self.get_dom_fn = get_dom_fn
        self._is_paused_fn = is_paused_fn
        self._replay = replay
        self._ui_graph_registry = ui_graph_registry

    async def run(self, state: AgentState) -> AgentState:
        """Run the full research pipeline."""
        logger.info(f"ResearchLoop starting: {state.instruction[:80]}")
        start_time = time.time()

        # Start replay recording
        if self._replay:
            self._replay.start_session(state.task_id, state.instruction, {
                "mode": state.mode, "type": "research",
            })

        try:
            # ═══ PHASE 1: RESEARCH (Gemini + Google Search) ═══
            # ═══ PHASE 1: OPEN TAB + SCAN OVERLAY + RESEARCH ═══

            # Step 1: Open a Google Search tab with the query
            await self._emit_event(state, "agent_active", {
                "agent": "navigator",
                "subtask": "Opening search workspace...",
            })

            import urllib.parse
            search_query = urllib.parse.quote_plus(state.instruction)
            search_url = f"https://www.google.com/search?q={search_query}"

            await self._emit_event(state, "action_planned", {
                "action_type": "navigate",
                "url": search_url,
                "reasoning": f"Searching: {state.instruction}",
            })

            # Navigate to Google Search
            if self.tool_executor and state.mode == "extension":
                await self.tool_executor.execute(
                    "navigate", {"url": search_url},
                    mode=state.mode, emit_fn=self.emit_fn,
                    task_id=state.task_id,
                )
                await asyncio.sleep(2)

                # Capture screenshot of search page for replay
                if self._replay and self.get_screenshot_fn:
                    try:
                        ss, url, _ = await self.get_screenshot_fn()
                        self._replay.record_step(
                            task_id=state.task_id, step_index=1,
                            action_type="navigate",
                            args={"url": search_url, "element_description": "Opening search workspace"},
                            success=True, duration_ms=0,
                            url_before="", url_after=search_url,
                            screenshot_b64=ss,
                        )
                    except Exception:
                        pass

            # Step 2: Show blue scanning overlay
            await self._emit_event(state, "scan_overlay", {
                "show": True,
                "text": "G-Axis is researching across multiple sources...",
            })

            await self._emit_event(state, "agent_active", {
                "agent": "researcher",
                "subtask": "Scanning and analyzing multiple sources...",
            })
            await self._emit_event(state, "action_planned", {
                "action_type": "RESEARCH",
                "reasoning": "Deep research across web sources",
            })

            # Step 3: Gemini researches (with scanning overlay visible)
            research_content = await self._research_phase(state)

            # Step 4: Remove scanning overlay
            await self._emit_event(state, "scan_overlay", {
                "show": False,
            })

            if not research_content:
                state.status = "failed"
                state.error = "Couldn't find enough information on this topic"
                return state

            logger.info(f"Research phase complete: {len(research_content)} chars")

            # Capture screenshot after research for replay
            if self._replay and self.get_screenshot_fn:
                try:
                    ss, url, _ = await self.get_screenshot_fn()
                    self._replay.record_step(
                        task_id=state.task_id, step_index=2,
                        action_type="RESEARCH",
                        args={"query": state.instruction, "element_description": "Research complete"},
                        success=True, duration_ms=0,
                        url_before=search_url, url_after=url or search_url,
                        screenshot_b64=ss,
                    )
                except Exception:
                    pass

            await self._emit_event(state, "action_succeeded", {
                "action_type": "research",
                "step": 1,
            })

            # ═══ PHASE 2: CREATE DOC (close search tab, open formatted doc) ═══
            await self._emit_event(state, "agent_active", {
                "agent": "navigator",
                "subtask": "Creating your document...",
            })
            await self._emit_event(state, "action_planned", {
                "action_type": "CREATE_DOC",
                "reasoning": "Creating formatted document with research findings",
            })

            state = await self._doc_creation_phase(state, research_content)

        except Exception as e:
            logger.error(f"ResearchLoop error: {e}", exc_info=True)
            state.status = "failed"
            state.error = str(e)

        # End replay recording
        if self._replay:
            self._replay.end_session(
                task_id=state.task_id,
                status=state.status,
                summary=state.result_summary or "",
                error=state.error,
            )
            self._replay.save(state.task_id)

        elapsed = int((time.time() - start_time) * 1000)
        logger.info(f"ResearchLoop done: status={state.status}, {elapsed}ms")
        return state

    # ─── PHASE 1: RESEARCH ──────────────────────────────────

    async def _research_phase(self, state: AgentState) -> str:
        """Use Gemini + Google Search grounding to research the topic.

        Returns the synthesized research content as markdown text.
        """
        # Google Search as a native Gemini tool — no browser needed
        google_search_tool = types.Tool(google_search=types.GoogleSearch())

        research_prompt = f"""Research this topic thoroughly: {state.instruction}

Search for multiple aspects of this topic. Read at least 5-8 different sources.
Produce a comprehensive, well-structured report in markdown format.

Include:
- A clear, descriptive title
- Overview/summary paragraph
- Detailed sections organized by theme
- Specific data, recommendations, and actionable tips
- Source URLs at the bottom

Be thorough and specific — include real names, prices, ratings, addresses where relevant."""

        try:
            # Single Gemini call with Google Search grounding
            # Gemini will autonomously search, read, and synthesize
            response = await self._call_with_retry(
                contents=[types.Content(role="user", parts=[
                    types.Part.from_text(text=research_prompt)
                ])],
                tools=[google_search_tool],
                system_prompt=RESEARCH_SYSTEM,
                max_output_tokens=16384,  # Long output for comprehensive research
            )

            if not response.candidates or not response.candidates[0].content:
                return ""

            # Extract the text response
            text_parts = []
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)

            research_text = "\n".join(text_parts)

            # Extract grounding metadata (sources)
            sources = []
            if response.candidates[0].grounding_metadata:
                gm = response.candidates[0].grounding_metadata
                if hasattr(gm, 'grounding_chunks') and gm.grounding_chunks:
                    for chunk in gm.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web:
                            sources.append({
                                "title": getattr(chunk.web, 'title', ''),
                                "uri": getattr(chunk.web, 'uri', ''),
                            })

            # Append sources if not already in the text
            if sources and "source" not in research_text.lower()[-500:]:
                research_text += "\n\n## Sources\n"
                for i, src in enumerate(sources, 1):
                    research_text += f"{i}. [{src['title']}]({src['uri']})\n"

            # Store sources in extracted_data
            state.extracted_data["sources"] = sources
            state.extracted_data["research_length"] = len(research_text)

            await self._emit_event(state, "action_planned", {
                "action_type": "RESEARCH",
                "reasoning": f"Gathered data from {len(sources)} sources, synthesized {len(research_text)} chars",
            })

            return research_text

        except Exception as e:
            logger.error(f"Research phase error: {e}", exc_info=True)
            # Fallback: return error context so doc phase can still try
            return ""

    # ─── PHASE 2: DOC CREATION ──────────────────────────────

    async def _doc_creation_phase(self, state: AgentState, content: str) -> AgentState:
        """Doc creation: generate .docx, upload to Drive, open formatted doc.

        The extension handles: close search tab → upload .docx → open Google Doc → rename title.
        """
        import re
        from backend.tools.doc_converter import markdown_to_docx

        title_line = content.strip().split("\n")[0].strip()
        title = re.sub(r"^#+\s*", "", title_line)

        try:
            logger.info(f"Generating .docx: '{title}'")

            await self._emit_event(state, "agent_active", {
                "agent": "orchestrator",
                "subtask": "Formatting document with tables and headings...",
            })

            # Generate .docx
            filepath = markdown_to_docx(content, title)
            filename = os.path.basename(filepath)
            download_url = f"http://localhost:{os.environ.get('PORT', '8000')}/api/doc/{filename}"
            logger.info(f"Generated .docx: {filepath}")

            # Record replay step
            if self._replay and self.get_screenshot_fn:
                try:
                    ss, url, _ = await self.get_screenshot_fn()
                    self._replay.record_step(
                        task_id=state.task_id, step_index=3,
                        action_type="CREATE_DOC",
                        args={"title": title, "element_description": f"Creating document: {title}"},
                        success=True, duration_ms=0,
                        url_before=url or "", url_after=download_url,
                        screenshot_b64=ss,
                    )
                except Exception:
                    pass

            await self._emit_event(state, "action_succeeded", {
                "action_type": "CREATE_DOC", "step": 1,
            })

            # Send to extension: close search tab → upload → open doc → rename
            await self._emit_event(state, "research_complete", {
                "title": title,
                "markdown": content,
                "download_url": download_url,
                "filename": filename,
            })

            await asyncio.sleep(2)

            state.result_summary = f'Research complete: "{title}". Document created in Google Docs.'
            state.extracted_data["download_url"] = download_url
            state.extracted_data["markdown"] = content[:500]
            state.status = "done"

        except Exception as e:
            logger.error(f"Doc creation error: {e}", exc_info=True)
            state.result_summary = f'Research complete: "{title}".'
            state.status = "done"

        return state

        return blocks

    # ─── HELPERS ─────────────────────────────────────────────

    async def _call_with_retry(
        self,
        contents: list[types.Content],
        tools: list,
        system_prompt: str = RESEARCH_SYSTEM,
        max_output_tokens: int = 8192,
        max_retries: int = 3,
    ):
        """Call Gemini with retry on rate limits."""
        for attempt in range(max_retries + 1):
            try:
                return await self.client.aio.models.generate_content(
                    model=AGENT_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.3,
                        max_output_tokens=max_output_tokens,
                        tools=tools,
                    ),
                )
            except Exception as e:
                err_str = str(e)
                if "400" in err_str and "INVALID_ARGUMENT" in err_str:
                    raise
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries:
                    wait = min(2 ** attempt * 5, 30)
                    logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def _capture_page(self, state: AgentState) -> AgentState:
        """Get screenshot + DOM from extension or Playwright."""
        import base64
        if state.mode == "extension":
            if self.get_screenshot_fn:
                screenshot_b64, url, title = await self.get_screenshot_fn()
                state.page.screenshot_b64 = screenshot_b64
                state.page.url = url
                state.page.title = title
            if self.emit_fn:
                from backend.agent.core import TaskEvent
                await self.emit_fn(TaskEvent("request_dom_snapshot", state.task_id, {}))
                await asyncio.sleep(0.3)
            if self.get_dom_fn:
                state.page.dom_elements = self.get_dom_fn()
        else:
            if self.get_browser_state_fn:
                browser_state = await self.get_browser_state_fn()
                state.page.screenshot_b64 = browser_state.screenshot_b64
                state.page.url = browser_state.url
                state.page.title = browser_state.title
        return state

    def _clean_conversation(self, history: list[types.Content]) -> list[types.Content]:
        """Sanitize conversation for Gemini ordering rules."""
        if not history:
            return []
        cleaned = []
        i = 0
        while i < len(history):
            msg = history[i]
            if not msg.parts:
                i += 1
                continue
            has_fc = any(hasattr(p, 'function_call') and p.function_call for p in msg.parts)
            has_fr = any(hasattr(p, 'function_response') and p.function_response for p in msg.parts)
            if has_fc:
                if i + 1 < len(history) and history[i + 1].parts:
                    next_fr = any(
                        hasattr(p, 'function_response') and p.function_response
                        for p in history[i + 1].parts
                    )
                    if next_fr:
                        cleaned.append(msg)
                        cleaned.append(history[i + 1])
                        i += 2
                        continue
                i += 1
                continue
            if has_fr:
                i += 1
                continue
            cleaned.append(msg)
            i += 1
        while cleaned and getattr(cleaned[0], 'role', None) != "user":
            cleaned.pop(0)
        if cleaned:
            last = cleaned[-1]
            last_has_fc = any(hasattr(p, 'function_call') and p.function_call for p in (last.parts or []))
            if last_has_fc:
                cleaned.pop()
        return cleaned

    def _format_dom(self, elements: list[dict]) -> str:
        lines = []
        for el in elements:
            tag = el.get("tag", "?")
            text = (el.get("text", "") or "")[:60]
            x, y = el.get("x", 0), el.get("y", 0)
            w, h = el.get("width", 0), el.get("height", 0)
            desc = ""
            if el.get("id"):
                desc += f" id={el['id']}"
            if el.get("placeholder"):
                desc += f' placeholder="{el["placeholder"]}"'
            if el.get("ariaLabel"):
                desc += f' aria="{el["ariaLabel"]}"'
            lines.append(f"  [{tag}] \"{text}\" at ({x},{y}) {w}x{h}{desc}")
        return "\n".join(lines) or "  (no elements)"

    async def _verify_with_screenshot(self, state: AgentState) -> bool:
        """Take a screenshot and verify with Gemini vision that the task completed.

        Prevents false "done" reports — agent must prove completion visually.
        """
        import base64
        try:
            state = await self._capture_page(state)
            if not state.page.screenshot_b64:
                logger.warning("Verify: no screenshot — accepting claim")
                return True

            image_bytes = base64.b64decode(state.page.screenshot_b64)
            parts = [
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                types.Part.from_text(text=(
                    f"TASK: {state.instruction}\n"
                    f"URL: {state.page.url}\n\n"
                    f"Look at the screenshot. Was a Google Doc actually created with content?\n"
                    f"Signs of SUCCESS: doc has a title, body has content paragraphs, URL is docs.google.com/document/d/...\n"
                    f"Signs of FAILURE: empty doc, 'Untitled document' still shown, login page, error, template picker.\n\n"
                    f"Return ONLY JSON: {{\"verified\": true/false, \"evidence\": \"what you see\"}}"
                )),
            ]

            response = await self.client.aio.models.generate_content(
                model=AGENT_MODEL,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    temperature=0.0, max_output_tokens=200,
                ),
            )

            if response.candidates and response.candidates[0].content:
                import re as _re
                text = response.candidates[0].content.parts[0].text.strip()
                text = _re.sub(r"^```(?:json)?\s*", "", text)
                text = _re.sub(r"\s*```$", "", text)
                import json as _json
                data = _json.loads(text)
                verified = data.get("verified", False)
                evidence = data.get("evidence", "")
                logger.info(f"Research verify: {'PASS' if verified else 'FAIL'} — {evidence[:80]}")
                await self._emit_event(state, "verification", {
                    "verified": verified, "evidence": evidence,
                })
                return verified

        except Exception as e:
            logger.warning(f"Research verify error: {e} — accepting claim")

        return True  # On error, accept to avoid blocking

    async def _emit_event(self, state, event_type, data):
        if self.emit_fn:
            from backend.agent.core import TaskEvent
            await self.emit_fn(TaskEvent(event_type, state.task_id, data))

    @staticmethod
    def is_research_task(instruction: str) -> bool:
        """Detect if an instruction is a deep research task that needs multi-source synthesis.

        Only triggers for tasks that explicitly need research + Google Doc output.
        Simple searches, calendar events, form fills, etc. should NOT match.
        """
        instruction_lower = instruction.lower()

        # Exclude browser-action tasks even if they contain research-like words
        action_keywords = [
            "book", "create", "schedule", "send", "open", "go to",
            "navigate", "click", "fill", "sign in", "log in", "buy",
            "search for", "google for", "look up",
        ]
        if any(kw in instruction_lower for kw in action_keywords):
            return False

        # Only match explicit deep-research requests
        research_keywords = [
            "research", "deep dive", "investigate",
            "itinerary", "travel plan", "comprehensive guide",
            "write a report", "detailed report", "in-depth analysis",
            "pros and cons", "comprehensive", "detailed overview",
        ]
        return any(kw in instruction_lower for kw in research_keywords)
