"""Playwright browser runtime for G-Axis.

Manages a headless Chrome instance and executes browser actions
(click, type, scroll, navigate) based on coordinates from Gemini vision.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
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
    """Controls a Playwright browser instance for the agent."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.session_id: str = uuid.uuid4().hex[:8]

    async def launch(self, headless: bool = True) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
        )
        self._page = await self._context.new_page()

    async def shutdown(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    async def get_state(self) -> BrowserState:
        """Capture current browser state with screenshot."""
        screenshot_bytes = await self.page.screenshot(type="jpeg", quality=75)
        return BrowserState(
            url=self.page.url,
            title=await self.page.title(),
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
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)

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
