"""XVideos upload driver (Playwright)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import PlatformDriver

logger = logging.getLogger(__name__)


class XVideosDriver(PlatformDriver):
    PLATFORM_NAME = "xvideos"
    UPLOAD_URL = "https://www.xvideos.com/account/uploads/new"
    LOGIN_URL = "https://www.xvideos.com/account"

    async def _is_logged_in(self) -> bool:
        url = self.page.url
        logged_in_sel = self._sel("logged_in_indicator", ".user-menu, .account-nav, #user-dropdown")
        el = await self.page.query_selector(logged_in_sel)
        return el is not None or "/account/uploads" in url

    async def login(self, username: str, password: str) -> bool:
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await self._human_delay()
        try:
            u_sel = self._sel("login_username", "#signin-form_login, input[name='login']")
            p_sel = self._sel("login_password", "#signin-form_password, input[name='password']")
            s_sel = self._sel("login_submit", "#signin-form input[type='submit']")
            await self._type_human(u_sel, username)
            await self._type_human(p_sel, password)
            await self._human_delay(500, 1000)
            await self.page.click(s_sel)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            return await self._is_logged_in()
        except Exception as exc:
            logger.error("XVideos login failed: %s", exc)
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

            # 1. Upload file
            file_sel = self._sel("file_input", "input[type='file'][accept*='video'], input[type='file']")
            file_input = await self.page.query_selector(file_sel)
            if not file_input:
                raise RuntimeError(f"File input not found with selector: {file_sel}")
            await file_input.set_input_files(video_path)

            # 2. Wait for upload to complete (up to 10 min)
            complete_sel = self._sel("upload_complete", ".upload-complete, .progress-100, .upload-success")
            logger.info("XVideos: waiting for upload to complete...")
            await self.page.wait_for_selector(complete_sel, timeout=600_000)
            logger.info("XVideos: upload complete, filling metadata")

            await self._human_delay(1000, 2000)

            # 3. Fill title
            title_sel = self._sel("title", "#title, input[name='title']")
            await self._type_human(title_sel, title[:100])

            # 4. Fill description
            desc_sel = self._sel("description", "#description, textarea[name='description']")
            desc_el = await self.page.query_selector(desc_sel)
            if desc_el:
                await desc_el.fill(description[:2000])

            # 5. Tags
            tag_sel = self._sel("tags", "#tags, input[name='tags'], .tag-input input")
            for tag in tags[:20]:
                tag_el = await self.page.query_selector(tag_sel)
                if tag_el:
                    await tag_el.type(tag, delay=50)
                    await self.page.keyboard.press("Enter")
                    await self._human_delay(150, 300)

            # 6. Category
            cat_sel = self._sel("category", "select[name='category'], select[name='cat']")
            cat_el = await self.page.query_selector(cat_sel)
            if cat_el:
                try:
                    await self.page.select_option(cat_sel, label=category)
                except Exception:
                    # Try by value
                    try:
                        await self.page.select_option(cat_sel, value=category.lower())
                    except Exception:
                        pass

            # 7. Thumbnail
            if thumbnail_path:
                thumb_sel = self._sel("thumbnail", "input[name='thumb'], .thumb-upload input[type='file']")
                thumb_input = await self.page.query_selector(thumb_sel)
                if thumb_input:
                    await thumb_input.set_input_files(thumbnail_path)

            # 8. Premium
            if is_premium:
                prem_sel = self._sel("premium", "#premium, input[name='red']")
                prem_el = await self.page.query_selector(prem_sel)
                if prem_el:
                    await prem_el.check()

            # 9. Submit
            await self._human_delay(1000, 2000)
            submit_sel = self._sel("submit", "button[type='submit'], .submit-btn, #publish, #submit")
            await self.page.click(submit_sel)
            await self.page.wait_for_load_state("networkidle", timeout=60_000)

            video_url = self.page.url
            video_id = video_url.split("/")[-1].split(".")[1] if "." in video_url.split("/")[-1] else ""

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
            logger.error("XVideos upload_video failed: %s", exc)
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
            url = f"https://www.xvideos.com/video.{video_id}/"
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._human_delay(500, 1500)

            views_sel = self._sel("video_views", ".views-count, .nb-views, .label-nb-views")
            likes_sel = self._sel("video_likes", ".likes-count, .vote-action-good .value, .nb-votes-total")
            comments_sel = self._sel("video_comments", ".comments-count, #tabComments .nb-comments")
            rating_sel = self._sel("video_rating", ".rating-value, .percent")

            views_text = await self._el_text(views_sel)
            likes_text = await self._el_text(likes_sel)
            comments_text = await self._el_text(comments_sel)
            rating_text = await self._el_text(rating_sel)

            return {
                "views": self._parse_count(views_text),
                "likes": self._parse_count(likes_text),
                "dislikes": 0,
                "comments": self._parse_count(comments_text),
                "rating": float((rating_text or "0").replace("%", "").strip() or "0"),
            }
        except Exception as exc:
            logger.error("XVideos scrape_video_stats failed for %s: %s", video_id, exc)
            return {"views": 0, "likes": 0, "dislikes": 0, "comments": 0, "rating": 0.0}

    async def scrape_channel_stats(self) -> Dict[str, Any]:
        try:
            await self.page.goto("https://www.xvideos.com/account/stats", wait_until="domcontentloaded", timeout=30_000)
            await self._human_delay()

            # These selectors are platform-specific and may need updating
            total_views = await self._el_text(".total-views, .stat-total-views") or "0"
            subscribers = await self._el_text(".subscribers-count, .stat-subscribers") or "0"
            total_videos = await self._el_text(".videos-count, .stat-total-videos") or "0"

            return {
                "total_views": self._parse_count(total_views),
                "subscribers": self._parse_count(subscribers),
                "total_videos": self._parse_count(total_videos),
                "earnings": 0.0,  # requires partner dashboard access
            }
        except Exception as exc:
            logger.error("XVideos scrape_channel_stats failed: %s", exc)
            return {"total_views": 0, "subscribers": 0, "total_videos": 0, "earnings": 0.0}
