"""
Publish pipeline: orchestrates multi-platform video publishing via Playwright drivers.

Flow:
1. Receive PublishRequest → create publish_job record + per-platform publication records
2. Download video from S3 to /tmp
3. For each platform: instantiate driver, decrypt cookies, upload video
4. Update publication record with result
5. Mark job done/error
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config

from ..db_agency import (
    creator_get, platform_account_get_with_cookies,
    publish_job_create, publish_job_get, publish_job_update_status,
    publication_create, publication_update, publications_by_job,
    selector_map_get,
)
from ..publishers.registry import get_driver
from ..security.encryption import decrypt

logger = logging.getLogger(__name__)

# S3 client (same config as main.py)
_S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "https://s3.n8nmikael.com.br")
_S3_KEY = os.environ.get("S3_ACCESS_KEY_ID")
_S3_SECRET = os.environ.get("S3_SECRET_ACCESS_KEY")
_S3_BUCKET = os.environ.get("S3_BUCKET", "metaporn")
_S3_REGION = os.environ.get("S3_REGION", "us-east-1")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=_S3_KEY,
        aws_secret_access_key=_S3_SECRET,
        region_name=_S3_REGION,
        config=Config(signature_version="s3v4"),
    )


async def _download_s3(object_key: str, dest_path: str) -> bool:
    """Download S3 object to local path. Returns True on success."""
    try:
        loop = asyncio.get_event_loop()
        client = _s3_client()
        await loop.run_in_executor(
            None,
            lambda: client.download_file(_S3_BUCKET, object_key, dest_path)
        )
        return True
    except Exception as exc:
        logger.error("S3 download failed for %s: %s", object_key, exc)
        return False


async def run_publish_pipeline(job_id: str) -> None:
    """Main pipeline coroutine — called as background task."""
    job = publish_job_get(job_id)
    if not job:
        logger.error("Publish job %s not found", job_id)
        return

    publish_job_update_status(job_id, "processing", detail="Iniciando publicação…", progress_pct=5)

    creator_id = job["creator_id"]
    video_key = job["video_object_key"]
    thumb_key = job.get("thumbnail_object_key")
    platforms: list[str] = job.get("platforms", [])
    metadata: dict = job.get("metadata", {})

    # Create per-platform publication records
    now = datetime.now(timezone.utc).isoformat()
    pub_map: Dict[str, str] = {}  # platform → pub_id
    for platform in platforms:
        pub_id = str(uuid.uuid4())
        pub_map[platform] = pub_id
        publication_create({
            "pub_id": pub_id,
            "job_id": job_id,
            "creator_id": creator_id,
            "platform": platform,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        })

    n_platforms = max(1, len(platforms))

    # Download video to temp file
    with tempfile.TemporaryDirectory(prefix="metaporn_pub_") as tmpdir:
        video_ext = Path(video_key).suffix or ".mp4"
        video_local = os.path.join(tmpdir, f"video{video_ext}")

        logger.info("Publishing job %s: downloading %s", job_id, video_key)
        publish_job_update_status(job_id, "processing", detail="Baixando vídeo do storage…", progress_pct=10)
        if not await _download_s3(video_key, video_local):
            publish_job_update_status(job_id, "error", detail="Falha ao baixar vídeo do storage.", progress_pct=0)
            for pub_id in pub_map.values():
                publication_update(pub_id, {"status": "error", "error_msg": "S3 download failed"})
            return

        # Download thumbnail if provided
        thumb_local: Optional[str] = None
        if thumb_key:
            thumb_ext = Path(thumb_key).suffix or ".jpg"
            thumb_local = os.path.join(tmpdir, f"thumb{thumb_ext}")
            if not await _download_s3(thumb_key, thumb_local):
                logger.warning("Thumbnail download failed — continuing without thumbnail")
                thumb_local = None

        # Process each platform sequentially (avoid rate limits)
        any_success = False
        for plat_idx, platform in enumerate(platforms):
            pub_id = pub_map[platform]
            pub_pct = 20 + int((plat_idx / n_platforms) * 70)
            publish_job_update_status(
                job_id, "processing",
                detail=f"Publicando em {platform}… ({plat_idx + 1}/{n_platforms})",
                progress_pct=pub_pct,
            )
            publication_update(pub_id, {"status": "uploading"})

            DriverClass = get_driver(platform)
            if not DriverClass:
                publication_update(pub_id, {
                    "status": "error",
                    "error_msg": f"Unsupported platform: {platform}",
                })
                continue

            # Load cookies (encrypted)
            account = platform_account_get_with_cookies(creator_id, platform)
            cookies_json: Optional[str] = None
            if account and account.get("cookies_json"):
                try:
                    cookies_json = decrypt(account["cookies_json"])
                except Exception as exc:
                    logger.warning("Cookie decrypt failed for %s/%s: %s", creator_id, platform, exc)

            # Load selector map from DB (may override JSON file)
            db_map = selector_map_get(platform)
            if db_map:
                # Merge into driver's selector map on instantiation is done at class level,
                # so we do it by patching after init
                pass

            logger.info("Publishing job %s to %s...", job_id, platform)
            try:
                async with DriverClass(cookies_json=cookies_json, headless=True) as driver:
                    # Override selectors from DB if available
                    if db_map:
                        driver._selectors.update(db_map.get("selectors", {}))

                    result = await driver.upload_video(
                        video_path=video_local,
                        title=metadata.get("title", ""),
                        description=metadata.get("description", ""),
                        tags=metadata.get("tags", []),
                        category=metadata.get("category", "Amateur"),
                        thumbnail_path=thumb_local,
                        is_premium=metadata.get("is_premium", False),
                    )

                if result.get("success"):
                    any_success = True
                    publication_update(pub_id, {
                        "status": "done",
                        "video_url": result.get("video_url"),
                        "video_id_platform": result.get("video_id"),
                    })
                    logger.info("Published to %s: %s", platform, result.get("video_url"))
                else:
                    publication_update(pub_id, {
                        "status": "error",
                        "error_msg": result.get("error", "Unknown error"),
                        "screenshot_path": result.get("screenshot"),
                    })
                    logger.warning("Failed to publish to %s: %s", platform, result.get("error"))

            except Exception as exc:
                logger.error("Exception publishing to %s: %s", platform, exc)
                publication_update(pub_id, {"status": "error", "error_msg": str(exc)})

            # Small delay between platforms
            await asyncio.sleep(5)

    final_status = "done" if any_success else "error"
    final_detail = "✓ Publicação concluída com sucesso." if any_success else "✗ Falha em todas as plataformas."
    publish_job_update_status(job_id, final_status, detail=final_detail, progress_pct=100 if any_success else 0)
    logger.info("Publish job %s finished with status: %s", job_id, final_status)


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Build a status response for the given job_id."""
    job = publish_job_get(job_id)
    if not job:
        return None
    pubs = publications_by_job(job_id)
    platforms_status: Dict[str, Any] = {}
    for p in pubs:
        platforms_status[p["platform"]] = {
            "status": p["status"],
            "video_url": p.get("video_url"),
            "video_id": p.get("video_id_platform"),
            "error": p.get("error_msg"),
        }
    return {
        "job_id": job_id,
        "status": job["status"],
        "detail": job.get("detail") or "",
        "progress_pct": int(job.get("progress_pct") or 0),
        "creator_id": job["creator_id"],
        "video_object_key": job["video_object_key"],
        "platforms": platforms_status,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
