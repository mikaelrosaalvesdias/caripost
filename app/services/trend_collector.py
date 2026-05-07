"""
Trend collector: scrapes trending data from platforms and stores in trends_raw table.
Includes reference-channel scraping per creator.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..db_agency import trend_raw_insert

logger = logging.getLogger(__name__)


# ── Platform detection ────────────────────────────────────────────────────────

def _detect_platform(url: str) -> str:
    """Return 'xvideos' | 'pornhub' | 'xhamster' | 'xnxx' | 'unknown'."""
    u = url.lower()
    if "xvideos" in u:
        return "xvideos"
    if "pornhub" in u:
        return "pornhub"
    if "xhamster" in u:
        return "xhamster"
    if "xnxx" in u:
        return "xnxx"
    return "unknown"


def _xvideos_channel_name_from_url(url: str) -> Optional[str]:
    """Extract channel/pornstar name from an XVideos URL.
    Handles: /channels/name, /profiles/name, /pornstars/name, /model/name
    Falls back to the bare input if it's not a URL.
    """
    url = url.strip()
    if not url.startswith("http"):
        # Treat raw string as channel name
        return url
    patterns = [
        r"xvideos\.com/(?:channels|profiles|pornstars?|model)/([^/?#]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url, re.IGNORECASE)
        if m:
            return m.group(1)
    # Last segment
    path = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return path if path else None


def _pornhub_model_name_from_url(url: str) -> Optional[str]:
    """Extract model/channel name from a Pornhub URL."""
    url = url.strip()
    if not url.startswith("http"):
        return url
    m = re.search(r"pornhub\.com/(?:model|pornstar|channels)/([^/?#]+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    path = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return path if path else None


# ── XVideos channel scraper ──────────────────────────────────────────────────

async def scrape_xvideos_channel(channel_ref: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Scrape top videos from an XVideos channel/pornstar.
    channel_ref can be a full URL or a channel name/slug.
    Returns list of video dicts: {title, url, views, duration, tags}.
    """
    try:
        from ..xvideos_source import fetch_channel_videos, fetch_pornstar_videos
        loop = asyncio.get_event_loop()

        name = _xvideos_channel_name_from_url(channel_ref) or channel_ref

        # Try channel first, then pornstar
        result = await loop.run_in_executor(None, lambda: fetch_channel_videos(name, limit=limit))
        videos = result.get("videos") or result.get("items") or []

        if not videos:
            result2 = await loop.run_in_executor(None, lambda: fetch_pornstar_videos(name, limit=limit))
            videos = result2.get("videos") or result2.get("items") or []

        # Normalise fields
        out = []
        for v in videos:
            if not v:
                continue
            out.append({
                "title": str(v.get("title") or v.get("name") or ""),
                "url": str(v.get("url") or v.get("link") or ""),
                "views": int(v.get("views") or v.get("nb_visits") or 0),
                "duration": int(v.get("duration") or 0),
                "tags": list(v.get("tags") or []),
                "thumbnail": str(v.get("thumb") or v.get("thumbnail") or ""),
            })
        return out
    except Exception as exc:
        logger.error("XVideos channel scrape failed for %r: %s", channel_ref, exc)
        return []


async def scrape_pornhub_channel(channel_ref: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Scrape top videos from a Pornhub model/channel using Playwright."""
    try:
        from playwright.async_api import async_playwright
        name = _pornhub_model_name_from_url(channel_ref) or channel_ref
        url = f"https://www.pornhub.com/model/{name}/videos?o=mv"

        results = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector("li.pcVideoListItem", timeout=15_000)
            items = await page.query_selector_all("li.pcVideoListItem")
            for item in items[:limit]:
                try:
                    title_el = await item.query_selector(".title a")
                    views_el = await item.query_selector(".videosViewsDesktop span")
                    title = await title_el.inner_text() if title_el else ""
                    href = await title_el.get_attribute("href") if title_el else ""
                    views_txt = await views_el.inner_text() if views_el else "0"
                    # Parse views string like "1.2M views" → int
                    views_clean = re.sub(r"[^\d.]", "", views_txt.replace("K", "e3").replace("M", "e6"))
                    try:
                        views_int = int(float(views_clean))
                    except Exception:
                        views_int = 0
                    results.append({
                        "title": title.strip(),
                        "url": href,
                        "views": views_int,
                        "duration": 0,
                        "tags": [],
                        "thumbnail": "",
                    })
                except Exception:
                    pass
            await browser.close()
        return results
    except Exception as exc:
        logger.warning("Pornhub channel scrape failed for %r: %s", channel_ref, exc)
        return []


# ── Reference channel collection per creator ─────────────────────────────────

async def collect_reference_channels_for_creator(
    creator: Dict[str, Any],
    videos_per_channel: int = 20,
) -> Dict[str, Any]:
    """Scrape each reference channel of a creator and store in trends_raw.

    Stores records with:
      platform  = "xvideos_channel" | "pornhub_channel"
      data_type = "channel_video"
      data_json includes creator_id, channel_url, and all video fields.
    """
    creator_id = creator["creator_id"]
    channels: List[str] = list(creator.get("reference_channels") or [])
    if not channels:
        return {"creator_id": creator_id, "channels": 0, "videos": 0}

    now = datetime.now(timezone.utc).isoformat()
    total_videos = 0

    for channel_url in channels:
        channel_url = str(channel_url or "").strip()
        if not channel_url:
            continue

        platform = _detect_platform(channel_url)
        scrape_platform = platform if platform in ("xvideos", "pornhub") else "xvideos"

        if scrape_platform == "xvideos":
            videos = await scrape_xvideos_channel(channel_url, limit=videos_per_channel)
            db_platform = "xvideos_channel"
        else:
            videos = await scrape_pornhub_channel(channel_url, limit=videos_per_channel)
            db_platform = "pornhub_channel"

        # Sort by views descending, keep top N
        videos.sort(key=lambda v: v.get("views", 0), reverse=True)
        videos = videos[:videos_per_channel]

        for v in videos:
            try:
                trend_raw_insert({
                    "id": str(uuid.uuid4()),
                    "platform": db_platform,
                    "collected_at": now,
                    "data_type": "channel_video",
                    "data": {
                        **v,
                        "creator_id": creator_id,
                        "channel_url": channel_url,
                    },
                })
                total_videos += 1
            except Exception as exc:
                logger.warning("Failed to insert channel video: %s", exc)

        logger.info(
            "[channel-collect] %s → %s: %d videos stored for creator %s",
            channel_url, db_platform, len(videos), creator_id,
        )

    return {
        "creator_id": creator_id,
        "channels": len(channels),
        "videos": total_videos,
    }


async def collect_all_reference_channels(videos_per_channel: int = 20) -> Dict[str, Any]:
    """Collect reference channel data for all active creators."""
    from ..db_agency import creator_list
    creators = creator_list(status="active")
    total_videos = 0
    processed = 0
    for creator in creators:
        if not creator.get("reference_channels"):
            continue
        try:
            result = await collect_reference_channels_for_creator(
                creator, videos_per_channel=videos_per_channel
            )
            total_videos += result.get("videos", 0)
            processed += 1
        except Exception as exc:
            logger.error("Channel collection failed for %s: %s", creator.get("creator_id"), exc)
    return {"creators_processed": processed, "total_videos": total_videos}


# ── Global trending scrapers ─────────────────────────────────────────────────

async def collect_xvideos_trends() -> List[Dict[str, Any]]:
    """Collect trending videos from XVideos using the existing xvideos_source module."""
    try:
        from ..xvideos_source import fetch_top_videos
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, lambda: fetch_top_videos(limit=50))
        return videos or []
    except Exception as exc:
        logger.error("XVideos trend collection failed: %s", exc)
        return []


async def collect_pornhub_trending_playwright() -> List[Dict[str, Any]]:
    """Scrape Pornhub trending page (no auth needed)."""
    try:
        from playwright.async_api import async_playwright
        results = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            await page.goto("https://www.pornhub.com/video?o=mv&t=w", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector("li.pcVideoListItem", timeout=15_000)
            items = await page.query_selector_all("li.pcVideoListItem")
            for item in items[:50]:
                try:
                    title_el = await item.query_selector(".title a")
                    views_el = await item.query_selector(".videosViewsDesktop span")
                    title = await title_el.inner_text() if title_el else ""
                    href = await title_el.get_attribute("href") if title_el else ""
                    views_txt = await views_el.inner_text() if views_el else "0"
                    results.append({"title": title.strip(), "url": href, "views": views_txt.strip()})
                except Exception:
                    pass
            await browser.close()
        return results
    except Exception as exc:
        logger.warning("Pornhub Playwright collection failed: %s", exc)
        return []


async def collect_trending_data() -> Dict[str, Any]:
    """Main collection function — called by cron. Collects global trends + all reference channels."""
    now = datetime.now(timezone.utc).isoformat()
    collected = 0

    xv_videos = await collect_xvideos_trends()
    for v in xv_videos:
        try:
            trend_raw_insert({
                "id": str(uuid.uuid4()),
                "platform": "xvideos",
                "collected_at": now,
                "data_type": "video",
                "data": v,
            })
            collected += 1
        except Exception as exc:
            logger.warning("Failed to insert xvideos trend: %s", exc)

    ph_videos = await collect_pornhub_trending_playwright()
    for v in ph_videos:
        try:
            trend_raw_insert({
                "id": str(uuid.uuid4()),
                "platform": "pornhub",
                "collected_at": now,
                "data_type": "video",
                "data": v,
            })
            collected += 1
        except Exception as exc:
            logger.warning("Failed to insert pornhub trend: %s", exc)

    # Also collect all reference channels
    channel_result = await collect_all_reference_channels()

    logger.info(
        "Trend collection complete: %d global records + %d channel videos from %d creators",
        collected, channel_result["total_videos"], channel_result["creators_processed"],
    )
    return {
        "collected_at": now,
        "platforms": ["xvideos", "pornhub"],
        "record_count": collected,
        "channel_videos": channel_result["total_videos"],
        "creators_with_channels": channel_result["creators_processed"],
    }
