"""One-time Google login helper for G-Axis demo.

Opens a visible Chrome browser with a persistent profile so you can log into
Google manually. After login, close the browser — the session (cookies,
localStorage) is saved to the profile directory and reused by the agent.

Usage:
    CHROME_PROFILE_DIR=.chrome-profile python -m backend.browser.login

Then start the server with the same profile:
    CHROME_PROFILE_DIR=.chrome-profile python run.py
"""

import asyncio
import os
import sys

from playwright.async_api import async_playwright


async def main():
    profile_dir = os.environ.get("CHROME_PROFILE_DIR", ".chrome-profile")
    os.makedirs(profile_dir, exist_ok=True)

    print(f"\n  G-Axis Login Setup")
    print(f"  Profile: {os.path.abspath(profile_dir)}")
    print(f"  Browser will open — log into Google, then close it.\n")

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--window-size=1280,800",
        ],
    )

    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://accounts.google.com")

    print("  Waiting for you to log in...")
    print("  Close the browser window when done.\n")

    # Wait until all pages are closed (user closes the window)
    while context.pages:
        await asyncio.sleep(1)

    await context.close()
    await pw.stop()

    print(f"  Login saved to {os.path.abspath(profile_dir)}")
    print(f"  Start the server with: CHROME_PROFILE_DIR={profile_dir} python run.py\n")


if __name__ == "__main__":
    asyncio.run(main())
