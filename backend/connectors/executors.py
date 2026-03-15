"""Deterministic skill executors — direct browser actions, no LLM.

Each executor is an async function that takes:
  (params, tool_executor, emit_fn, task_id, mode) → SkillResult

Executors call ToolExecutor.execute() directly to run browser actions
(navigate, fill_form, wait, press_key). They use fill_form with
findByHint for DOM-based element discovery — no pixel coordinates
needed.

Benefits over LLM-driven execution:
  - 100x faster (no LLM round-trips)
  - Zero hallucination (predetermined action sequences)
  - Fully reliable (same actions every time)
  - Cheap (no API costs for execution)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.connectors.base import SkillResult

logger = logging.getLogger("gaxis.executors")


# ─── HELPERS ──────────────────────────────────────────────────────

_replay_ref = None  # Set by fast_loop before deterministic execution
_replay_task_id = ""
_replay_step_counter = 0
_screenshot_fn = None  # Function to get latest screenshot


async def _exec(
    tool_executor, fn_name: str, fn_args: dict,
    mode: str, emit_fn: Any, task_id: str,
) -> dict:
    """Execute a single browser action and return the result dict."""
    global _replay_step_counter

    result = await tool_executor.execute(
        function_name=fn_name,
        function_args=fn_args,
        mode=mode,
        emit_fn=emit_fn,
        task_id=task_id,
    )

    # Record to replay with screenshot
    if _replay_ref and _replay_task_id == task_id:
        _replay_step_counter += 1
        screenshot = None
        if _screenshot_fn:
            try:
                screenshot = await _screenshot_fn()
            except Exception:
                pass
        _replay_ref.record_step(
            task_id=task_id,
            step_index=_replay_step_counter,
            action_type=fn_name,
            args=fn_args,
            success=result.success,
            error=result.error,
            duration_ms=result.duration_ms,
            url_before="",
            url_after="",
            screenshot_b64=screenshot,
        )

    return {
        "success": result.success,
        "error": result.error,
        "result": result.result,
    }


async def _navigate(
    tool_executor, url: str, mode: str, emit_fn, task_id: str,
    wait_seconds: float = 2.0,
) -> dict:
    """Navigate to a URL and wait for page load."""
    r = await _exec(
        tool_executor, "navigate", {"url": url},
        mode, emit_fn, task_id,
    )
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
    return r


async def _fill_form(
    tool_executor, fields: list[dict],
    mode: str, emit_fn, task_id: str,
    wait_after: float = 0.5,
) -> dict:
    """Batch-fill form fields using findByHint (DOM text matching)."""
    r = await _exec(
        tool_executor, "fill_form", {"fields": fields},
        mode, emit_fn, task_id,
    )
    if wait_after > 0:
        await asyncio.sleep(wait_after)
    return r


async def _click_hint(
    tool_executor, hints: dict,
    mode: str, emit_fn, task_id: str,
    wait_after: float = 0.5,
) -> dict:
    """Click an element by DOM hints (no coordinates needed)."""
    return await _fill_form(
        tool_executor,
        [{"hints": hints, "action": "click", "wait_after": 100}],
        mode, emit_fn, task_id,
        wait_after=wait_after,
    )


async def _wait(
    tool_executor, seconds: float, reason: str,
    mode: str, emit_fn, task_id: str,
) -> dict:
    """Wait for a specified duration."""
    return await _exec(
        tool_executor, "wait", {"seconds": seconds, "reason": reason},
        mode, emit_fn, task_id,
    )


async def _press_key(
    tool_executor, key: str,
    mode: str, emit_fn, task_id: str,
) -> dict:
    """Press a keyboard key."""
    return await _exec(
        tool_executor, "press_key", {"key": key},
        mode, emit_fn, task_id,
    )


# ─── GOOGLE CALENDAR: CREATE EVENT ───────────────────────────────

async def calendar_create_event(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Deterministically create a Google Calendar event.

    Uses fill_form with findByHint for all form interactions.
    Zero LLM calls — entire event creation in ~3 seconds.
    """
    title = params.get("title", "")
    start_date = params.get("start_date", "")
    end_date = params.get("end_date", start_date)
    start_time = params.get("start_time", "")
    end_time = params.get("end_time", "")
    location = params.get("location", "")
    description = params.get("description", "")
    guests = params.get("guests", [])
    add_meet = params.get("add_meet", False)

    if isinstance(guests, str):
        guests = [g.strip() for g in guests.split(",") if g.strip()]

    logger.info(
        f"[calendar_create_event] Deterministic exec: "
        f"title={title}, date={start_date}, time={start_time}"
    )

    # Phase 1: Navigate to event editor
    nav = await _navigate(
        tool_executor,
        "https://calendar.google.com/calendar/u/0/r/eventedit",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )
    if not nav["success"]:
        return SkillResult(success=False, error=f"Navigation failed: {nav['error']}")

    # Phase 2: Fill title
    if title:
        title_result = await _fill_form(
            tool_executor,
            [{"hints": {"placeholder": "Add title", "aria": "Add title"}, "value": title, "action": "type", "clear_first": True}],
            mode, emit_fn, task_id,
            wait_after=0.3,
        )
        if not title_result["success"]:
            logger.warning(f"Title fill failed: {title_result.get('error')}")

    # Phase 3: Fill date/time chips (each needs click → type → Tab)
    # These are chip buttons, not regular inputs — use select_all_and_type
    date_time_fields = []
    if start_date:
        date_time_fields.append({
            "hints": {"aria": "Start date", "text": start_date},
            "value": start_date,
            "action": "select_all_and_type",
            "clear_first": True,
            "wait_after": 400,
        })
    if start_time:
        date_time_fields.append({
            "hints": {"aria": "Start time"},
            "value": start_time,
            "action": "select_all_and_type",
            "clear_first": True,
            "wait_after": 400,
        })
    if end_time:
        date_time_fields.append({
            "hints": {"aria": "End time"},
            "value": end_time,
            "action": "select_all_and_type",
            "clear_first": True,
            "wait_after": 400,
        })
    if end_date and end_date != start_date:
        date_time_fields.append({
            "hints": {"aria": "End date"},
            "value": end_date,
            "action": "select_all_and_type",
            "clear_first": True,
            "wait_after": 400,
        })

    if date_time_fields:
        dt_result = await _fill_form(
            tool_executor, date_time_fields,
            mode, emit_fn, task_id,
            wait_after=0.5,
        )
        if not dt_result["success"]:
            logger.warning(f"Date/time fill partial: {dt_result.get('error')}")

    # Press Tab to dismiss any open picker
    await _press_key(tool_executor, "Tab", mode, emit_fn, task_id)
    await asyncio.sleep(0.3)

    # Phase 4: Optional fields
    if add_meet:
        await _click_hint(
            tool_executor,
            {"text": "Add Google Meet video conferencing", "tag": "span"},
            mode, emit_fn, task_id,
            wait_after=2.0,  # Meet link takes time to generate
        )

    if location:
        await _fill_form(
            tool_executor,
            [{"hints": {"text": "Add location", "aria": "Add location"}, "value": location, "action": "type", "clear_first": True}],
            mode, emit_fn, task_id,
            wait_after=0.5,
        )
        await _press_key(tool_executor, "Tab", mode, emit_fn, task_id)

    if description:
        await _fill_form(
            tool_executor,
            [{
                "hints": {"text": "Add description", "aria": "Description", "tag": "div", "contenteditable": "true"},
                "value": description,
                "action": "type",
                "clear_first": True,
            }],
            mode, emit_fn, task_id,
            wait_after=0.3,
        )

    # Phase 5: Guests (each guest needs type + Enter to create chip)
    for guest_email in guests:
        await _fill_form(
            tool_executor,
            [{
                "hints": {"placeholder": "Add guests", "aria": "Add guests"},
                "value": guest_email,
                "action": "type",
                "press_enter": True,
                "clear_first": False,
                "wait_after": 500,
            }],
            mode, emit_fn, task_id,
            wait_after=0.5,
        )

    # Phase 6: Click Save
    save_result = await _click_hint(
        tool_executor,
        {"aria": "Save", "tag": "button"},
        mode, emit_fn, task_id,
        wait_after=1.0,
    )

    # Handle "Send invitations?" dialog if guests were added
    if guests:
        await asyncio.sleep(1.0)
        # Try to click "Send" in the dialog
        await _click_hint(
            tool_executor,
            {"text": "Send", "tag": "button"},
            mode, emit_fn, task_id,
            wait_after=1.0,
        )

    # Wait for calendar to reload
    await asyncio.sleep(2.0)

    return SkillResult(
        success=True,
        data={
            "title": title,
            "start_date": start_date,
            "start_time": start_time,
            "end_time": end_time,
            "end_date": end_date,
            "location": location,
            "guests": guests,
            "has_meet": add_meet,
        },
    )


# ─── GMAIL: SEND EMAIL ──────────────────────────────────────────

async def gmail_send_email(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Deterministically compose and send an email via Gmail.

    Uses fill_form with findByHint. Zero LLM calls.
    """
    to = params.get("to", "")
    subject = params.get("subject", "")
    body = params.get("body", "")
    cc = params.get("cc", "")
    bcc = params.get("bcc", "")

    logger.info(
        f"[gmail_send_email] Deterministic exec: "
        f"to={to}, subject={subject[:30]}"
    )

    # Phase 1: Navigate to Gmail
    nav = await _navigate(
        tool_executor,
        "https://mail.google.com/mail/u/0/#inbox",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )
    if not nav["success"]:
        return SkillResult(success=False, error=f"Navigation failed: {nav['error']}")

    # Phase 2: Click Compose
    compose_result = await _click_hint(
        tool_executor,
        {"text": "Compose", "aria": "Compose"},
        mode, emit_fn, task_id,
        wait_after=2.0,  # Wait for compose window to animate open
    )
    if not compose_result["success"]:
        return SkillResult(success=False, error="Could not open Compose window")

    # Phase 3: Fill compose fields
    compose_fields = []

    # To field
    if to:
        compose_fields.append({
            "hints": {"aria": "To recipients", "placeholder": "Recipients", "tag": "input"},
            "value": to,
            "action": "type",
            "press_enter": False,
            "clear_first": True,
            "wait_after": 500,
        })

    # Fill To first, then Tab to dismiss autocomplete
    if compose_fields:
        await _fill_form(
            tool_executor, compose_fields,
            mode, emit_fn, task_id,
            wait_after=0.3,
        )
        await _press_key(tool_executor, "Tab", mode, emit_fn, task_id)
        await asyncio.sleep(0.5)

    # CC/BCC if needed
    if cc:
        # Click Cc link to reveal field
        await _click_hint(
            tool_executor,
            {"text": "Cc", "aria": "Add Cc recipients", "tag": "span"},
            mode, emit_fn, task_id,
            wait_after=0.5,
        )
        await _fill_form(
            tool_executor,
            [{"hints": {"aria": "Cc recipients", "tag": "input"}, "value": cc, "action": "type", "clear_first": True}],
            mode, emit_fn, task_id,
        )
        await _press_key(tool_executor, "Tab", mode, emit_fn, task_id)

    if bcc:
        await _click_hint(
            tool_executor,
            {"text": "Bcc", "aria": "Add Bcc recipients", "tag": "span"},
            mode, emit_fn, task_id,
            wait_after=0.5,
        )
        await _fill_form(
            tool_executor,
            [{"hints": {"aria": "Bcc recipients", "tag": "input"}, "value": bcc, "action": "type", "clear_first": True}],
            mode, emit_fn, task_id,
        )
        await _press_key(tool_executor, "Tab", mode, emit_fn, task_id)

    # Subject and body
    remaining_fields = []
    if subject:
        remaining_fields.append({
            "hints": {"placeholder": "Subject", "aria": "Subject", "tag": "input"},
            "value": subject,
            "action": "type",
            "clear_first": True,
            "wait_after": 200,
        })
    if body:
        remaining_fields.append({
            "hints": {"aria": "Message Body", "tag": "div", "contenteditable": "true"},
            "value": body,
            "action": "type",
            "clear_first": True,
            "wait_after": 200,
        })

    if remaining_fields:
        await _fill_form(
            tool_executor, remaining_fields,
            mode, emit_fn, task_id,
            wait_after=0.5,
        )

    # Phase 4: Click Send
    send_result = await _click_hint(
        tool_executor,
        {"aria": "Send", "text": "Send", "tag": "div"},
        mode, emit_fn, task_id,
        wait_after=2.0,
    )

    # Wait for send confirmation
    await asyncio.sleep(1.0)

    return SkillResult(
        success=True,
        data={
            "to": to,
            "subject": subject,
            "cc": cc,
            "bcc": bcc,
        },
    )


# ─── GMAIL: SEARCH EMAIL ────────────────────────────────────────

async def gmail_search_email(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Deterministically search Gmail. Navigates and types query."""
    query = params.get("query", "")

    logger.info(f"[gmail_search_email] Deterministic exec: query={query}")

    # Navigate to Gmail
    await _navigate(
        tool_executor,
        "https://mail.google.com/mail/u/0/#inbox",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )

    # Click search bar and type query
    await _fill_form(
        tool_executor,
        [{
            "hints": {"placeholder": "Search mail", "aria": "Search mail", "tag": "input"},
            "value": query,
            "action": "type",
            "clear_first": True,
            "press_enter": True,
            "wait_after": 500,
        }],
        mode, emit_fn, task_id,
        wait_after=2.0,
    )

    # Search submitted — results will be visible on next screenshot
    return SkillResult(
        success=True,
        data={"query": query, "action": "search_submitted"},
    )


# ─── GOOGLE CALENDAR: CHECK SCHEDULE ────────────────────────────

async def calendar_check_schedule(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Navigate to calendar view for schedule checking.

    This is semi-deterministic — navigates to the right view,
    but reading events still requires vision (LLM fallback).
    """
    time_range = params.get("time_range", "today")

    logger.info(f"[calendar_check_schedule] Deterministic nav: {time_range}")

    # Navigate to calendar
    await _navigate(
        tool_executor,
        "https://calendar.google.com/calendar/u/0/r",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )

    # Switch to Schedule view for easier reading
    await _click_hint(
        tool_executor,
        {"aria": "Schedule", "text": "Schedule"},
        mode, emit_fn, task_id,
        wait_after=1.5,
    )

    return SkillResult(
        success=True,
        data={"view": "schedule", "time_range": time_range},
        # Partial — still needs LLM to read the schedule
        browser_instruction=(
            f"Read all visible events for {time_range}. "
            f"Extract each event's title, time, and location. "
            f"Call task_complete with a summary."
        ),
    )


# ─── GOOGLE CALENDAR: DELETE EVENT ──────────────────────────────

async def calendar_delete_event(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Navigate to calendar for event deletion.

    Semi-deterministic — navigates, but finding the specific event
    requires vision (LLM fallback).
    """
    event_name = params.get("event_name", "")

    logger.info(f"[calendar_delete_event] Nav for delete: {event_name}")

    await _navigate(
        tool_executor,
        "https://calendar.google.com/calendar/u/0/r",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )

    return SkillResult(
        success=True,
        data={"event_name": event_name},
        browser_instruction=(
            f"Find the event '{event_name}' on the calendar. "
            f"Click on it to open the popup. "
            f"Click the trash/delete icon. "
            f"If asked about recurring events, select 'This event'. "
            f"If asked to send cancellation, click 'Send'. "
            f"Verify the event is gone."
        ),
    )


# ─── YOUTUBE: PLAY VIDEO ──────────────────────────────────────

async def youtube_play_video(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Deterministically play a video on YouTube.

    Flow: navigate → search → click first result → handle ads → verify.
    Zero LLM calls.
    """
    query = params.get("query", "")
    if not query:
        return SkillResult(success=False, error="No query provided")

    logger.info(f"[youtube_play_video] Deterministic exec: query={query}")

    # Phase 1: Navigate to YouTube
    nav = await _navigate(
        tool_executor,
        "https://www.youtube.com",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )
    if not nav["success"]:
        return SkillResult(success=False, error=f"Navigation failed: {nav['error']}")

    # Phase 2: Search for the query
    search_result = await _fill_form(
        tool_executor,
        [{
            "hints": {"placeholder": "Search", "aria": "Search", "tag": "input"},
            "value": query,
            "action": "type",
            "clear_first": True,
            "press_enter": True,
            "wait_after": 500,
        }],
        mode, emit_fn, task_id,
        wait_after=2.5,  # Wait for search results to load
    )
    if not search_result["success"]:
        return SkillResult(success=False, error=f"Search failed: {search_result.get('error')}")

    # Phase 3: Click the first video result
    # YouTube search results have video titles as links inside #contents
    # Use fill_form click action with broad hints to find first video
    click_result = await _fill_form(
        tool_executor,
        [{
            "hints": {"tag": "a", "id": "video-title", "index": 0},
            "action": "click",
            "wait_after": 500,
        }],
        mode, emit_fn, task_id,
        wait_after=3.0,  # Wait for video page to load
    )

    if not click_result["success"]:
        # Fallback: try clicking by aria
        click_result = await _fill_form(
            tool_executor,
            [{
                "hints": {"aria": "video-title", "tag": "a", "index": 0},
                "action": "click",
                "wait_after": 500,
            }],
            mode, emit_fn, task_id,
            wait_after=3.0,
        )

    if not click_result["success"]:
        # Second fallback: the LLM will handle finding the video
        return SkillResult(
            success=True,
            data={"query": query, "action": "search_completed"},
            browser_instruction=(
                f"YouTube search results for '{query}' are now visible. "
                f"Click the first video result (preferably official or music video). "
                f"If a 'Skip Ad' or 'Skip Ads' button appears, click it. "
                f"Verify the video is playing."
            ),
        )

    # Phase 4: Handle ads — try to click Skip Ad button
    # Wait a moment for ad to start (if any)
    await asyncio.sleep(2.0)

    # Try clicking Skip Ad (may not exist — that's OK)
    for skip_text in ["Skip Ad", "Skip Ads", "Skip ad", "Skip ads"]:
        try:
            skip_result = await _fill_form(
                tool_executor,
                [{
                    "hints": {"text": skip_text, "tag": "button"},
                    "action": "click",
                    "wait_after": 200,
                }],
                mode, emit_fn, task_id,
                wait_after=0.5,
            )
            if skip_result["success"]:
                logger.info("[youtube_play_video] Skipped ad")
                break
        except Exception:
            pass  # No ad to skip — that's fine

    # Phase 5: Second ad check (some videos have double ads)
    await asyncio.sleep(2.0)
    for skip_text in ["Skip Ad", "Skip Ads"]:
        try:
            await _fill_form(
                tool_executor,
                [{
                    "hints": {"text": skip_text, "tag": "button"},
                    "action": "click",
                    "wait_after": 200,
                }],
                mode, emit_fn, task_id,
                wait_after=0.5,
            )
        except Exception:
            pass

    return SkillResult(
        success=True,
        data={
            "query": query,
            "action": "video_playing",
        },
        # LLM will verify on next screenshot that video is actually playing
        browser_instruction=(
            f"Verify the YouTube video is playing for '{query}'. "
            f"If a 'Skip Ad' button is visible, click it. "
            f"If the video is playing, call task_complete. "
            f"If it's not playing, click the play button."
        ),
    )


# ─── YOUTUBE: SEARCH ──────────────────────────────────────────

async def youtube_search(
    params: dict,
    tool_executor: Any,
    emit_fn: Any,
    task_id: str,
    mode: str,
) -> SkillResult:
    """Deterministically search YouTube. Navigates and types query."""
    query = params.get("query", "")
    if not query:
        return SkillResult(success=False, error="No query provided")

    logger.info(f"[youtube_search] Deterministic exec: query={query}")

    # Navigate to YouTube
    await _navigate(
        tool_executor,
        "https://www.youtube.com",
        mode, emit_fn, task_id,
        wait_seconds=2.5,
    )

    # Search
    await _fill_form(
        tool_executor,
        [{
            "hints": {"placeholder": "Search", "aria": "Search", "tag": "input"},
            "value": query,
            "action": "type",
            "clear_first": True,
            "press_enter": True,
            "wait_after": 500,
        }],
        mode, emit_fn, task_id,
        wait_after=2.0,
    )

    # Search submitted — results visible on next screenshot
    return SkillResult(
        success=True,
        data={"query": query, "action": "search_submitted"},
        browser_instruction=(
            f"YouTube search results for '{query}' are now visible. "
            f"Read the top results and report what you find."
        ),
    )
