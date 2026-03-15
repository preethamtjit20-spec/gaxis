"""Playwright browser runtime for G-Axis.

Manages a headless Chrome instance and executes browser actions
(click, type, scroll, navigate) based on coordinates from Gemini vision.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid

logger = logging.getLogger("gaxis.browser")
from dataclasses import dataclass, field
from typing import Literal

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


@dataclass
class ActionResult:
    success: bool
    action_type: str
    duration_ms: int
    resulting_url: str
    error: str | None = None
    screenshot_b64: str | None = None


@dataclass
class BrowserState:
    url: str
    title: str
    screenshot_b64: str
    timestamp: float = field(default_factory=time.time)


class BrowserRuntime:
    """Controls a Playwright browser instance for the agent.

    Supports a persistent Chrome profile via CHROME_PROFILE_DIR env var.
    When set, Playwright uses launch_persistent_context so Google login,
    cookies, and extensions survive across restarts.

    Setup once:
        CHROME_PROFILE_DIR=.chrome-profile HEADLESS=false python -m backend.browser.login
    Then all future runs reuse that logged-in session.

    The .operator property provides a high-level PlaywrightOperator
    (like OpenAI's CUA pattern) for reliable, app-aware browser actions.
    """

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._persistent: bool = False
        self.session_id: str = uuid.uuid4().hex[:8]
        self._operator = None

    async def launch(self, headless: bool = True) -> None:
        import os
        self._playwright = await async_playwright().start()

        profile_dir = os.environ.get("CHROME_PROFILE_DIR")

        if profile_dir:
            # Persistent context — keeps Google login, cookies, localStorage
            from pathlib import Path
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"Launching with persistent profile: {profile_dir}")
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--window-size=1280,800",
                ],
            )
            self._persistent = True
            # Persistent context opens a default page
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            # Ephemeral context — fresh browser, no login
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--window-size=1280,800",
                ],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            self._page = await self._context.new_page()

    async def shutdown(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser and not self._persistent:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    @property
    def operator(self):
        """Get the high-level PlaywrightOperator for this runtime.

        The operator provides reliable, retryable, app-aware browser actions
        similar to OpenAI's CUA/Operator pattern.
        """
        if self._operator is None:
            from backend.browser.operator import PlaywrightOperator
            self._operator = PlaywrightOperator(page_fn=lambda: self.page)
        return self._operator

    async def ensure_page(self) -> Page:
        """Ensure we have a live page, recreating if closed."""
        try:
            if self._page and not self._page.is_closed():
                return self._page
        except Exception as e:
            logger.debug(f"Page check failed, recreating: {e}")
        # Page was closed — open a new one
        if self._context:
            self._page = await self._context.new_page()
            await self._page.goto("about:blank")
        return self._page

    async def get_state(self) -> BrowserState:
        """Capture current browser state with screenshot."""
        page = await self.ensure_page()
        screenshot_bytes = await page.screenshot(type="jpeg", quality=75)
        return BrowserState(
            url=page.url,
            title=await page.title(),
            screenshot_b64=base64.b64encode(screenshot_bytes).decode("utf-8"),
        )

    async def execute(
        self,
        action_type: str,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        url: str | None = None,
        direction: Literal["up", "down"] | None = None,
        pixels: int = 300,
        key: str | None = None,
    ) -> ActionResult:
        """Execute a browser action and return the result."""
        start = time.time()
        # Ensure page is alive before executing
        await self.ensure_page()

        try:
            match action_type:
                case "click":
                    if x is not None and y is not None:
                        await self.page.mouse.click(x, y)
                    else:
                        raise ValueError("click requires x, y coordinates")

                case "type":
                    if x is not None and y is not None:
                        await self.page.mouse.click(x, y)
                        await asyncio.sleep(0.1)
                    if text:
                        await self.page.keyboard.type(text, delay=30)

                case "scroll":
                    delta = pixels if direction == "down" else -pixels
                    await self.page.mouse.wheel(0, delta)

                case "navigate":
                    if not url:
                        raise ValueError("navigate requires a url")
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)

                case "press_key":
                    if key:
                        await self.page.keyboard.press(key)

                case "wait":
                    await asyncio.sleep(1.0)

                case "select_all_and_type":
                    if x is not None and y is not None:
                        await self.page.mouse.click(x, y)
                        await asyncio.sleep(0.1)
                    import platform
                    mod = "Meta+a" if platform.system() == "Darwin" else "Control+a"
                    await self.page.keyboard.press(mod)
                    await asyncio.sleep(0.05)
                    if text:
                        await self.page.keyboard.type(text, delay=30)

                case _:
                    raise ValueError(f"Unknown action: {action_type}")

            # Brief pause for page to react
            await asyncio.sleep(0.3)

            duration_ms = int((time.time() - start) * 1000)
            return ActionResult(
                success=True,
                action_type=action_type,
                duration_ms=duration_ms,
                resulting_url=self.page.url,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ActionResult(
                success=False,
                action_type=action_type,
                duration_ms=duration_ms,
                resulting_url=self.page.url,
                error=str(e),
            )
