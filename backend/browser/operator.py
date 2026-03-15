"""Playwright Operator — unified browser automation layer.

Similar to OpenAI's Computer Use Agent (CUA) / Operator pattern.
Provides a high-level, consistent interface for all browser interactions
across ALL task types (calendar, docs, sheets, research, email, etc.).

Architecture:
  Agent Loop → Operator → Playwright Runtime
                       → Extension Content Script

The Operator handles:
  - Reliable element finding (text, selector, coordinates fallback)
  - Auto-retry on stale elements / timeouts
  - Page readiness detection (wait for load, spinners gone)
  - Screenshot capture with retry
  - Google Workspace app-specific patterns (Docs title, Sheets cells, etc.)
  - Consistent error reporting across all task types
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("gaxis.operator")


@dataclass
class OperatorResult:
    """Result of an operator action."""
    success: bool
    action: str
    duration_ms: int = 0
    data: dict = field(default_factory=dict)
    error: str | None = None
    screenshot_b64: str | None = None


class PlaywrightOperator:
    """High-level browser operator — reliable, retryable, consistent.

    Used by fast_loop, research_loop, and state_machine for ALL Playwright
    interactions. Wraps low-level Playwright calls with:
    - Auto-wait for page readiness
    - Smart element finding (text → selector → coordinates)
    - Retry on failure
    - Consistent result format
    """

    def __init__(self, page_fn: Callable[[], Page]):
        """
        Args:
            page_fn: Callable that returns the current Playwright Page.
                     This allows the operator to always use the live page.
        """
        self._get_page = page_fn

    @property
    def page(self) -> Page:
        return self._get_page()

    # ─── NAVIGATION ─────────────────────────────────────────

    async def navigate(self, url: str, wait_until: str = "domcontentloaded",
                       timeout: int = 20000) -> OperatorResult:
        """Navigate to URL with retry."""
        start = time.time()
        for attempt in range(2):
            try:
                await self.page.goto(url, wait_until=wait_until, timeout=timeout)
                await self._wait_for_ready()
                return OperatorResult(
                    success=True, action="navigate",
                    duration_ms=self._elapsed(start),
                    data={"url": self.page.url, "title": await self.page.title()},
                )
            except PlaywrightTimeout:
                if attempt == 0:
                    logger.warning(f"Navigate timeout, retrying: {url}")
                    continue
                return OperatorResult(
                    success=False, action="navigate",
                    duration_ms=self._elapsed(start),
                    error=f"Navigation timed out after {timeout}ms: {url}",
                )
            except Exception as e:
                return OperatorResult(
                    success=False, action="navigate",
                    duration_ms=self._elapsed(start),
                    error=str(e),
                )

    # ─── CLICK ──────────────────────────────────────────────

    async def click(self, x: int, y: int, description: str = "") -> OperatorResult:
        """Click at coordinates."""
        start = time.time()
        try:
            await self.page.mouse.click(x, y)
            await asyncio.sleep(0.3)
            return OperatorResult(
                success=True, action="click",
                duration_ms=self._elapsed(start),
                data={"x": x, "y": y, "description": description},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="click",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    async def click_text(self, text: str, exact: bool = False,
                         timeout: int = 5000) -> OperatorResult:
        """Click an element by its visible text content."""
        start = time.time()
        try:
            locator = self.page.get_by_text(text, exact=exact)
            await locator.first.click(timeout=timeout)
            await asyncio.sleep(0.3)
            return OperatorResult(
                success=True, action="click_text",
                duration_ms=self._elapsed(start),
                data={"text": text},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="click_text",
                duration_ms=self._elapsed(start),
                error=f"Could not click text '{text}': {e}",
            )

    async def click_selector(self, selector: str,
                             timeout: int = 5000) -> OperatorResult:
        """Click an element by CSS selector."""
        start = time.time()
        try:
            await self.page.click(selector, timeout=timeout)
            await asyncio.sleep(0.3)
            return OperatorResult(
                success=True, action="click_selector",
                duration_ms=self._elapsed(start),
                data={"selector": selector},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="click_selector",
                duration_ms=self._elapsed(start),
                error=f"Could not click selector '{selector}': {e}",
            )

    # ─── TYPE TEXT ──────────────────────────────────────────

    async def type_text(self, text: str, selector: str | None = None,
                        clear_first: bool = False,
                        press_enter: bool = False,
                        delay: int = 20) -> OperatorResult:
        """Type text into the currently focused element or a specific selector."""
        start = time.time()
        try:
            if selector:
                await self.page.click(selector, timeout=5000)
                await asyncio.sleep(0.1)

            if clear_first:
                import platform
                mod = "Meta+a" if platform.system() == "Darwin" else "Control+a"
                await self.page.keyboard.press(mod)
                await asyncio.sleep(0.05)
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(0.05)

            await self.page.keyboard.type(text, delay=delay)

            if press_enter:
                await self.page.keyboard.press("Enter")

            await asyncio.sleep(0.2)
            return OperatorResult(
                success=True, action="type_text",
                duration_ms=self._elapsed(start),
                data={"text": text[:50], "selector": selector, "clear_first": clear_first},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="type_text",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    # ─── KEY PRESS ──────────────────────────────────────────

    async def press_key(self, key: str) -> OperatorResult:
        """Press a keyboard key."""
        start = time.time()
        try:
            await self.page.keyboard.press(key)
            await asyncio.sleep(0.1)
            return OperatorResult(
                success=True, action="press_key",
                duration_ms=self._elapsed(start),
                data={"key": key},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="press_key",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    # ─── SCROLL ─────────────────────────────────────────────

    async def scroll(self, direction: str = "down", pixels: int = 500) -> OperatorResult:
        """Scroll the page."""
        start = time.time()
        try:
            delta = pixels if direction == "down" else -pixels
            await self.page.mouse.wheel(0, delta)
            await asyncio.sleep(0.3)
            return OperatorResult(
                success=True, action="scroll",
                duration_ms=self._elapsed(start),
                data={"direction": direction, "pixels": pixels},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="scroll",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    # ─── SCREENSHOT ─────────────────────────────────────────

    async def screenshot(self, quality: int = 75) -> OperatorResult:
        """Take a screenshot and return as base64."""
        start = time.time()
        try:
            screenshot_bytes = await self.page.screenshot(type="jpeg", quality=quality)
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return OperatorResult(
                success=True, action="screenshot",
                duration_ms=self._elapsed(start),
                screenshot_b64=b64,
                data={"url": self.page.url, "title": await self.page.title()},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="screenshot",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    # ─── WAIT ───────────────────────────────────────────────

    async def wait(self, seconds: float = 1.0) -> OperatorResult:
        """Wait for a specified time."""
        start = time.time()
        await asyncio.sleep(seconds)
        return OperatorResult(
            success=True, action="wait",
            duration_ms=self._elapsed(start),
        )

    async def wait_for_selector(self, selector: str,
                                timeout: int = 10000) -> OperatorResult:
        """Wait for a CSS selector to appear."""
        start = time.time()
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return OperatorResult(
                success=True, action="wait_for_selector",
                duration_ms=self._elapsed(start),
                data={"selector": selector},
            )
        except PlaywrightTimeout:
            return OperatorResult(
                success=False, action="wait_for_selector",
                duration_ms=self._elapsed(start),
                error=f"Selector '{selector}' not found within {timeout}ms",
            )

    async def wait_for_text(self, text: str,
                            timeout: int = 10000) -> OperatorResult:
        """Wait for text to appear on the page."""
        start = time.time()
        try:
            locator = self.page.get_by_text(text)
            await locator.first.wait_for(timeout=timeout)
            return OperatorResult(
                success=True, action="wait_for_text",
                duration_ms=self._elapsed(start),
                data={"text": text},
            )
        except PlaywrightTimeout:
            return OperatorResult(
                success=False, action="wait_for_text",
                duration_ms=self._elapsed(start),
                error=f"Text '{text}' not found within {timeout}ms",
            )

    # ─── GOOGLE WORKSPACE HELPERS ───────────────────────────

    async def set_google_doc_title(self, title: str) -> OperatorResult:
        """Set the title of a Google Doc (handles the special title input)."""
        start = time.time()
        try:
            # Try the docs title input first
            title_selectors = [
                "input.docs-title-input",
                "input.docs-title-widget",
                'input[aria-label="Rename"]',
            ]
            clicked = False
            for sel in title_selectors:
                try:
                    await self.page.click(sel, timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                # Fallback: click on "Untitled document" text
                try:
                    await self.page.get_by_text("Untitled document").first.click(timeout=3000)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                return OperatorResult(
                    success=False, action="set_doc_title",
                    duration_ms=self._elapsed(start),
                    error="Could not find doc title input",
                )

            await asyncio.sleep(0.2)
            # Select all and replace
            import platform
            mod = "Meta+a" if platform.system() == "Darwin" else "Control+a"
            await self.page.keyboard.press(mod)
            await asyncio.sleep(0.05)
            await self.page.keyboard.type(title, delay=20)
            await self.page.keyboard.press("Tab")
            await asyncio.sleep(0.5)

            return OperatorResult(
                success=True, action="set_doc_title",
                duration_ms=self._elapsed(start),
                data={"title": title},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="set_doc_title",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    async def type_in_google_doc_body(self, content: str) -> OperatorResult:
        """Type content into the Google Docs body area."""
        start = time.time()
        try:
            # Click into the document body
            body_selectors = [
                'div.kix-appview-editor',
                'div[contenteditable="true"]',
                'div.kix-page',
            ]
            clicked = False
            for sel in body_selectors:
                try:
                    await self.page.click(sel, timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                # Fallback: click center of page
                viewport = self.page.viewport_size
                if viewport:
                    await self.page.mouse.click(viewport["width"] // 2, viewport["height"] // 2)
                    clicked = True

            if not clicked:
                return OperatorResult(
                    success=False, action="type_doc_body",
                    duration_ms=self._elapsed(start),
                    error="Could not click into document body",
                )

            await asyncio.sleep(0.3)
            # Type content in chunks to avoid timeout
            chunk_size = 500
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                await self.page.keyboard.type(chunk, delay=5)
                await asyncio.sleep(0.1)

            return OperatorResult(
                success=True, action="type_doc_body",
                duration_ms=self._elapsed(start),
                data={"chars_typed": len(content)},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="type_doc_body",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    async def set_google_sheet_title(self, title: str) -> OperatorResult:
        """Set the title of a Google Sheet."""
        start = time.time()
        try:
            selectors = [
                'input[aria-label="Rename"]',
                'input.docs-title-input',
            ]
            clicked = False
            for sel in selectors:
                try:
                    await self.page.click(sel, timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                try:
                    await self.page.get_by_text("Untitled spreadsheet").first.click(timeout=3000)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                return OperatorResult(
                    success=False, action="set_sheet_title",
                    duration_ms=self._elapsed(start),
                    error="Could not find sheet title input",
                )

            await asyncio.sleep(0.2)
            import platform
            mod = "Meta+a" if platform.system() == "Darwin" else "Control+a"
            await self.page.keyboard.press(mod)
            await asyncio.sleep(0.05)
            await self.page.keyboard.type(title, delay=20)
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(0.5)

            return OperatorResult(
                success=True, action="set_sheet_title",
                duration_ms=self._elapsed(start),
                data={"title": title},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="set_sheet_title",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    async def type_in_sheet_cell(self, cell_ref: str, value: str,
                                 press_tab: bool = True) -> OperatorResult:
        """Navigate to a cell and type a value in Google Sheets."""
        start = time.time()
        try:
            # Click the Name Box and type cell reference
            name_box = self.page.locator('input[aria-label="Name Box"]')
            await name_box.first.click(timeout=3000)
            await asyncio.sleep(0.1)
            import platform
            mod = "Meta+a" if platform.system() == "Darwin" else "Control+a"
            await self.page.keyboard.press(mod)
            await self.page.keyboard.type(cell_ref, delay=20)
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(0.2)

            # Type the value
            await self.page.keyboard.type(value, delay=20)

            # Tab to next column or Enter to next row
            if press_tab:
                await self.page.keyboard.press("Tab")
            else:
                await self.page.keyboard.press("Enter")

            await asyncio.sleep(0.1)

            return OperatorResult(
                success=True, action="type_sheet_cell",
                duration_ms=self._elapsed(start),
                data={"cell": cell_ref, "value": value},
            )
        except Exception as e:
            return OperatorResult(
                success=False, action="type_sheet_cell",
                duration_ms=self._elapsed(start),
                error=str(e),
            )

    # ─── PAGE STATE ─────────────────────────────────────────

    async def get_page_state(self) -> dict:
        """Get current page state (URL, title)."""
        try:
            return {
                "url": self.page.url,
                "title": await self.page.title(),
            }
        except Exception:
            return {"url": "", "title": ""}

    # ─── INTERNAL HELPERS ───────────────────────────────────

    async def _wait_for_ready(self, timeout: float = 5.0):
        """Wait for the page to be interactive."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
        except PlaywrightTimeout:
            logger.debug("Page load state timeout — proceeding anyway")

    @staticmethod
    def _elapsed(start: float) -> int:
        return int((time.time() - start) * 1000)
