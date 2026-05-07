"""
Cross-promoter: posts teasers / promotional content to Telegram and other channels
after a video is published on the main platforms.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db_agency import calendar_list, calendar_update, creator_get
from ..db import settings_get

logger = logging.getLogger(__name__)


async def _post_to_telegram(
    creator_id: str,
    title: str,
    description: str,
    video_url: str,
    teaser_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Post cross-promotion to Telegram via n8n webhook (existing integration)."""
    import httpx
    import json

    webhook_url = settings_get("telegram:n8n_webhook_url")
    if not webhook_url:
        return {"success": False, "error": "Telegram webhook not configured"}

    message = f"🎬 *{title}*\n\n{description[:200]}\n\n▶️ {video_url}"
    payload = {
        "source": "cross_promote",
        "creator_id": creator_id,
        "message": message,
        "video_url": video_url,
        "teaser_url": teaser_url,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(webhook_url, json=payload)
            return {"success": resp.status_code < 300, "status_code": resp.status_code}
    except Exception as exc:
        logger.error("Telegram cross-promote failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def process_pending_cross_promotions() -> Dict[str, Any]:
    """
    Check calendar for entries that need cross-promotion and haven't been promoted yet.
    Called by cron every 10 minutes.
    """
    now = datetime.now(timezone.utc).isoformat()
    # Find entries: published=True, cross_promote=True, cross_promote_at <= now, status='done'
    entries = calendar_list(status="done")
    processed = 0

    for entry in entries:
        if not entry.get("cross_promote"):
            continue
        cross_results = entry.get("cross_results", {})
        if cross_results.get("done"):
            continue  # already promoted

        cross_at = entry.get("cross_promote_at")
        if cross_at and cross_at > now:
            continue  # not yet time

        channels: List[str] = entry.get("cross_channels", [])
        creator_id = entry["creator_id"]
        title = entry.get("title", "")
        description = entry.get("description", "")
        pub_results = entry.get("publish_results", {})

        # Get best video URL from publish results
        video_url = ""
        for platform_result in pub_results.values():
            if isinstance(platform_result, dict) and platform_result.get("video_url"):
                video_url = platform_result["video_url"]
                break

        if not video_url:
            continue

        new_results: Dict[str, Any] = {}
        for channel in channels:
            if channel == "telegram":
                result = await _post_to_telegram(creator_id, title, description, video_url)
                new_results["telegram"] = result
                await asyncio.sleep(2)

        new_results["done"] = True
        calendar_update(entry["entry_id"], {"cross_results": new_results})
        processed += 1

    return {"processed": processed, "checked_at": now}
