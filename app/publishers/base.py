"""
Base class for all platform drivers (Playwright-based).

Each driver handles: login, upload_video, scrape_video_stats, scrape_channel_stats.
Selectors are loaded from JSON maps to allow hotfixes without code changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SELECTOR_MAPS_DIR = Path(__file__).parent / "selector_maps"


def load_selector_map(platform: str) -> Dict[str, str]:
    """Load selector map from JSON file (falls back to empty dict)."""
    path = SELECTOR_MAPS_DIR / f"{platform}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("selectors", {})
        except Exception as exc:
            logger.warning("Failed to load selector map for %s: %s", platform, exc)
    return {}


class PlatformDriver(ABC):
    """
    Abstract base for all platform upload drivers.

    Usage (async context manager):
        async with XVideosDriver(cookies_json="...") as driver:
            result = await driver.upload_video(...)
    """

    PLATFORM_NAME: str = ""
    UPLOAD_URL: str = ""
    LOGIN_URL: str = ""

    def __init__(self, cookies_json: Optional[str] = None, headless: bool = True):
        self.cookies: List[Dict] = []
        if cookies_json:
            try:
                self.cookies = json.loads(cookies_json)
            except Exception:
                logger.warning("Invalid cookies_json for %s", self.PLATFORM_NAME)
        self.headless = headless
        self._selectors = load_selector_map(self.PLATFORM_NAME)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _sel(self, key: str, fallback: str = "") -> str:
        """Return selector from map or fallback."""
        return self._selectors.get(key, fallback)

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            ignore_https_errors=True,
        )
        if self.cookies:
            try:
                await self.context.add_cookies(self.cookies)
            except Exception as exc:
                logger.warning("Could not restore cookies for %s: %s", self.PLATFORM_NAME, exc)
        self.page = await self.context.new_page()
        # Stealth: hide webdriver property
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return self

    async def __aexit__(self, *args):
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def save_cookies(self) -> str:
        """Export current cookies for storage."""
        cookies = await self.context.cookies()
        return json.dumps(cookies)

    async def check_login(self) -> bool:
        """Navigate to upload page and check if still logged in."""
        try:
            await self.page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=30_000)
            return await self._is_logged_in()
        except Exception as exc:
            logger.warning("check_login failed for %s: %s", self.PLATFORM_NAME, exc)
            return False

    async def _screenshot(self, prefix: str = "error") -> str:
        """Capture a debug screenshot and return path."""
        path = f"/tmp/{self.PLATFORM_NAME}_{prefix}_{int(time.time())}.png"
        try:
            if self.page:
                await self.page.screenshot(path=path, full_page=False)
        except Exception:
            pass
        return path

    async def _human_delay(self, min_ms: int = 500, max_ms: int = 2000) -> None:
        await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)

    async def _type_human(self, selector: str, text: str) -> None:
        """Type with randomised per-keystroke delay to mimic a human."""
        await self.page.click(selector)
        await self._human_delay(200, 500)
        await self.page.fill(selector, "")
        for char in text:
            await self.page.keyboard.type(char, delay=50 + random.randint(0, 80))

    async def _wait_for_any(self, selectors: List[str], timeout: int = 30_000) -> Optional[Any]:
        """Wait for the first matching selector from a list."""
        if not selectors:
            return None
        combined = ", ".join(selectors)
        try:
            return await self.page.wait_for_selector(combined, timeout=timeout)
        except Exception:
            return None

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def _is_logged_in(self) -> bool:
        pass

    @abstractmethod
    async def login(self, username: str, password: str) -> bool:
        pass

    @abstractmethod
    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        category: str,
        thumbnail_path: Optional[str] = None,
        is_premium: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns:
            {"success": bool, "video_url": str|None, "video_id": str|None,
             "platform": str, "error": str|None, "screenshot": str|None}
        """
        pass

    @abstractmethod
    async def scrape_video_stats(self, video_id: str) -> Dict[str, Any]:
        """Returns: {"views": int, "likes": int, "dislikes": int, "comments": int, "rating": float}"""
        pass

    @abstractmethod
    async def scrape_channel_stats(self) -> Dict[str, Any]:
        """Returns: {"total_views": int, "subscribers": int, "total_videos": int, "earnings": float}"""
        pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_count(text: Optional[str]) -> int:
        if not text:
            return 0
        # Remove commas, dots, K/M suffixes
        text = text.strip().upper().replace(",", "").replace(".", "")
        multiplier = 1
        if text.endswith("K"):
            text = text[:-1]
            multiplier = 1_000
        elif text.endswith("M"):
            text = text[:-1]
            multiplier = 1_000_000
        digits = "".join(c for c in text if c.isdigit())
        return int(digits or "0") * multiplier

    async def _el_text(self, selector: str) -> Optional[str]:
        el = await self.page.query_selector(selector)
        if el:
            return (await el.inner_text()).strip()
        return None
