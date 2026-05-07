"""XNXX upload driver (Playwright)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import PlatformDriver

logger = logging.getLogger(__name__)


class XnxxDriver(PlatformDriver):
    PLATFORM_NAME = "xnxx"
    UPLOAD_URL = "https://www.xnxx.com/upload"
    LOGIN_URL = "https://www.xnxx.com/account"

    async def _is_logged_in(self) -> bool:
        logged_sel = self._sel("logged_in_indicator", ".user-menu, .account-menu, #user-nav")
        el = await self.page.query_selector(logged_sel)
        return el is not None or "/upload" in self.page.url

    async def login(self, username: str, password: str) -> bool:
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await self._human_delay()
        try:
            u_sel = self._sel("login_username", "input[name='login'], #login")
            p_sel = self._sel("login_password", "input[name='password'], #password")
            await self._type_human(u_sel, username)
            await self._type_human(p_sel, password)
            await self._human_delay(400, 800)
            submit_sel = self._sel("login_submit", "input[type='submit'], button[type='submit']")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=15_000)
            return await self._is_logged_in()
        except Exception as exc:
            logger.error("XNXX login failed: %s", exc)
            return False

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
        try:
            await self.page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._human_delay()

            file_sel = self._sel("file_input", "input[type='file'][accept*='video'], input[type='file']")
            file_input = await self.page.query_selector(file_sel)
            if not file_input:
                raise RuntimeError(f"File input not found: {file_sel}")
            await file_input.set_input_files(video_path)

            complete_sel = self._sel("upload_complete", ".upload-complete, .progress-done")
            await self.page.wait_for_selector(complete_sel, timeout=600_000)
            await self._human_delay(1000, 2000)

            title_sel = self._sel("title", "input[name='title'], #title")
            await self._type_human(title_sel, title[:100])

            desc_sel = self._sel("description", "textarea[name='description'], #description")
            desc_el = await self.page.query_selector(desc_sel)
            if desc_el:
                await desc_el.fill(description[:2000])

            tag_sel = self._sel("tags", "input[name='tags'], #tags")
            for tag in tags[:15]:
                tag_el = await self.page.query_selector(tag_sel)
                if tag_el:
                    await tag_el.type(tag + " ", delay=60)
                    await self._human_delay(100, 250)

            if thumbnail_path:
                thumb_sel = self._sel("thumbnail", "input[name='thumb'], input[type='file'][accept*='image']")
                thumb_el = await self.page.query_selector(thumb_sel)
                if thumb_el:
                    await thumb_el.set_input_files(thumbnail_path)

            await self._human_delay(800, 1500)
            submit_sel = self._sel("submit", "button[type='submit'], input[type='submit'], .submit-btn")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=60_000)

            video_url = self.page.url
            video_id = video_url.rstrip("/").split("/")[-1]

            return {
                "success": True,
                "video_url": video_url,
                "video_id": video_id,
                "platform": self.PLATFORM_NAME,
                "error": None,
                "screenshot": None,
            }
        except Exception as exc:
            screenshot = await self._screenshot("upload_error")
            logger.error("XNXX upload_video failed: %s", exc)
            return {
                "success": False,
                "video_url": None,
                "video_id": None,
                "platform": self.PLATFORM_NAME,
                "error": str(exc),
                "screenshot": screenshot,
            }

    async def scrape_video_stats(self, video_id: str) -> Dict[str, Any]:
        try:
            await self.page.goto(f"https://www.xnxx.com/video-{video_id}/", wait_until="domcontentloaded")
            await self._human_delay()
            views = await self._el_text(".nb-views-number, .video-views") or "0"
            likes = await self._el_text(".vote-action-good .nb, .thumbs-up-count") or "0"
            return {"views": self._parse_count(views), "likes": self._parse_count(likes),
                    "dislikes": 0, "comments": 0, "rating": 0.0}
        except Exception as exc:
            logger.error("XNXX scrape_video_stats failed: %s", exc)
            return {"views": 0, "likes": 0, "dislikes": 0, "comments": 0, "rating": 0.0}

    async def scrape_channel_stats(self) -> Dict[str, Any]:
        return {"total_views": 0, "subscribers": 0, "total_videos": 0, "earnings": 0.0}
