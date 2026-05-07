"""Pornhub upload driver (Playwright)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import PlatformDriver

logger = logging.getLogger(__name__)


class PornhubDriver(PlatformDriver):
    PLATFORM_NAME = "pornhub"
    UPLOAD_URL = "https://www.pornhub.com/uploadvideo"
    LOGIN_URL = "https://www.pornhub.com/login"

    async def _is_logged_in(self) -> bool:
        logged_sel = self._sel("logged_in_indicator", ".usernameWrap, .user-avatar, .topUserbarName")
        el = await self.page.query_selector(logged_sel)
        return el is not None

    async def login(self, username: str, password: str) -> bool:
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await self._human_delay()
        try:
            u_sel = self._sel("login_username", "#username, input[name='username']")
            p_sel = self._sel("login_password", "#password, input[name='password']")
            await self._type_human(u_sel, username)
            await self._type_human(p_sel, password)
            await self._human_delay(500, 1000)
            submit_sel = self._sel("login_submit", "button[type='submit'], .loginButton, input[type='submit']")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            return await self._is_logged_in()
        except Exception as exc:
            logger.error("Pornhub login failed: %s", exc)
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

            file_sel = self._sel("file_input", "#uploadVideoFile, input[type='file']")
            file_input = await self.page.query_selector(file_sel)
            if not file_input:
                raise RuntimeError(f"File input not found: {file_sel}")
            await file_input.set_input_files(video_path)

            # Wait for upload bar to finish
            complete_sel = self._sel("upload_complete", ".upload-complete, .uploadCompleted, .js-progressBar")
            await self.page.wait_for_function(
                """() => {
                    const bar = document.querySelector('.js-progressBar, .progress-bar');
                    if (!bar) return false;
                    const w = bar.style.width || bar.getAttribute('aria-valuenow') || '0';
                    return parseInt(w) >= 100;
                }""",
                timeout=600_000,
            )

            await self._human_delay(1500, 3000)

            title_sel = self._sel("title", "#videoTitle, input[name='title']")
            await self._type_human(title_sel, title[:150])

            desc_sel = self._sel("description", "#videoDescription, textarea[name='description']")
            desc_el = await self.page.query_selector(desc_sel)
            if desc_el:
                await desc_el.fill(description[:3000])

            tag_sel = self._sel("tags", "#videoTags, input[name='tags']")
            for tag in tags[:20]:
                tag_el = await self.page.query_selector(tag_sel)
                if tag_el:
                    await tag_el.type(tag + " ", delay=60)
                    await self._human_delay(100, 300)

            cat_sel = self._sel("category", "#videoCategory, select[name='category']")
            cat_el = await self.page.query_selector(cat_sel)
            if cat_el:
                try:
                    await self.page.select_option(cat_sel, label=category)
                except Exception:
                    pass

            await self._human_delay(1000, 2000)
            submit_sel = self._sel("submit", "#submitVideo, .upload-submit, button[type='submit']")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=60_000)

            video_url = self.page.url
            # Extract Pornhub viewkey from URL
            video_id = ""
            if "viewkey=" in video_url:
                video_id = video_url.split("viewkey=")[1].split("&")[0]

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
            logger.error("Pornhub upload_video failed: %s", exc)
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
            await self.page.goto(
                f"https://www.pornhub.com/view_video.php?viewkey={video_id}",
                wait_until="domcontentloaded", timeout=30_000,
            )
            await self._human_delay()

            views = await self._el_text(".count, .viewsWrapper .count, span[data-id='views']") or "0"
            likes = await self._el_text(".votesUp, .ratingPositive .number") or "0"
            rating = await self._el_text(".percent, .ratingPercent") or "0"
            comments = await self._el_text(".numComments, .commentsCount") or "0"

            return {
                "views": self._parse_count(views),
                "likes": self._parse_count(likes),
                "dislikes": 0,
                "comments": self._parse_count(comments),
                "rating": float((rating or "0").replace("%", "").strip() or "0"),
            }
        except Exception as exc:
            logger.error("Pornhub scrape_video_stats failed: %s", exc)
            return {"views": 0, "likes": 0, "dislikes": 0, "comments": 0, "rating": 0.0}

    async def scrape_channel_stats(self) -> Dict[str, Any]:
        try:
            await self.page.goto("https://www.pornhub.com/user/profile/info", wait_until="domcontentloaded")
            await self._human_delay()
            subscribers = await self._el_text(".subscribersWrapper .count, .subscribeCount") or "0"
            total_videos = await self._el_text(".videosCount, .totalVideos") or "0"
            return {
                "total_views": 0,
                "subscribers": self._parse_count(subscribers),
                "total_videos": self._parse_count(total_videos),
                "earnings": 0.0,
            }
        except Exception as exc:
            logger.error("Pornhub scrape_channel_stats failed: %s", exc)
            return {"total_views": 0, "subscribers": 0, "total_videos": 0, "earnings": 0.0}
