"""xHamster upload driver (Playwright)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import PlatformDriver

logger = logging.getLogger(__name__)


class XhamsterDriver(PlatformDriver):
    PLATFORM_NAME = "xhamster"
    UPLOAD_URL = "https://xhamster.com/upload"
    LOGIN_URL = "https://xhamster.com/login"

    async def _is_logged_in(self) -> bool:
        logged_sel = self._sel("logged_in_indicator", ".user-menu, .user-nav, .header-user-name")
        el = await self.page.query_selector(logged_sel)
        return el is not None

    async def login(self, username: str, password: str) -> bool:
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await self._human_delay()
        try:
            u_sel = self._sel("login_username", "input[name='username'], input[type='text']")
            p_sel = self._sel("login_password", "input[name='password'], input[type='password']")
            await self._type_human(u_sel, username)
            await self._type_human(p_sel, password)
            await self._human_delay(400, 900)
            submit_sel = self._sel("login_submit", "button[type='submit'], .login-button")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            return await self._is_logged_in()
        except Exception as exc:
            logger.error("xHamster login failed: %s", exc)
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

            file_sel = self._sel("file_input", "input[type='file']")
            file_input = await self.page.query_selector(file_sel)
            if not file_input:
                raise RuntimeError(f"File input not found: {file_sel}")
            await file_input.set_input_files(video_path)

            complete_sel = self._sel("upload_complete", ".upload-complete, .progress-complete, .done")
            await self.page.wait_for_selector(complete_sel, timeout=600_000)
            await self._human_delay(1000, 2000)

            title_sel = self._sel("title", "input[name='title'], #title, .title-input")
            await self._type_human(title_sel, title[:150])

            desc_sel = self._sel("description", "textarea[name='description'], .description-input")
            desc_el = await self.page.query_selector(desc_sel)
            if desc_el:
                await desc_el.fill(description[:2000])

            tag_sel = self._sel("tags", ".tags-input input, input[name='tags']")
            for tag in tags[:20]:
                tag_el = await self.page.query_selector(tag_sel)
                if tag_el:
                    await tag_el.type(tag, delay=60)
                    await self.page.keyboard.press("Enter")
                    await self._human_delay(150, 350)

            if thumbnail_path:
                thumb_sel = self._sel("thumbnail", "input[name='thumb'], .thumbnail-upload input[type='file']")
                thumb_el = await self.page.query_selector(thumb_sel)
                if thumb_el:
                    await thumb_el.set_input_files(thumbnail_path)

            await self._human_delay(800, 1600)
            submit_sel = self._sel("submit", "button[type='submit'], .upload-btn, .submit-btn")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=60_000)

            video_url = self.page.url
            video_id = video_url.rstrip("/").split("/")[-1].replace("videos/", "")

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
            logger.error("xHamster upload_video failed: %s", exc)
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
            await self.page.goto(f"https://xhamster.com/videos/{video_id}", wait_until="domcontentloaded")
            await self._human_delay()
            views = await self._el_text(".views-block .entity-info-views, .label-icon-views") or "0"
            likes = await self._el_text(".entity-buttons-item-primary .entity-buttons-item-count") or "0"
            return {"views": self._parse_count(views), "likes": self._parse_count(likes),
                    "dislikes": 0, "comments": 0, "rating": 0.0}
        except Exception as exc:
            logger.error("xHamster scrape_video_stats failed: %s", exc)
            return {"views": 0, "likes": 0, "dislikes": 0, "comments": 0, "rating": 0.0}

    async def scrape_channel_stats(self) -> Dict[str, Any]:
        return {"total_views": 0, "subscribers": 0, "total_videos": 0, "earnings": 0.0}
