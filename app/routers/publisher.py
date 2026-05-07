"""
Module 2: AutoPublisher
Publish videos to platforms via Playwright drivers.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import (
    publish_job_create, creator_get,
    selector_map_get, selector_map_upsert,
)
from ..models.publication import PublishJobStatus, PublishRequest
from ..services.publish_pipeline import run_publish_pipeline, get_job_status
from ..publishers.registry import SUPPORTED_PLATFORMS

router = APIRouter(prefix="/api/publisher", tags=["publisher"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


@router.post("/publish")
async def publish_video(body: PublishRequest, request: Request):
    """Start a publish job for one or more platforms."""
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)

    creator_id = body.get("creator_id")
    video_key = body.get("video_object_key")
    platforms: List[str] = body.get("platforms", [])

    if not creator_id or not video_key:
        return JSONResponse({"detail": "creator_id and video_object_key are required"}, status_code=422)
    if not platforms:
        return JSONResponse({"detail": "At least one platform is required"}, status_code=422)

    # Validate creator exists
    if not creator_get(creator_id):
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    # Validate platforms
    invalid = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if invalid:
        return JSONResponse(
            {"detail": f"Unsupported platforms: {invalid}. Supported: {SUPPORTED_PLATFORMS}"},
            status_code=422,
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    schedule_at = body.get("schedule_at")

    publish_job_create({
        "job_id": job_id,
        "creator_id": creator_id,
        "video_object_key": video_key,
        "thumbnail_object_key": body.get("thumbnail_object_key"),
        "platforms": platforms,
        "metadata": body.get("metadata", {}),
        "schedule_at": schedule_at,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    })

    if not schedule_at:
        # Publish immediately in background
        asyncio.create_task(run_publish_pipeline(job_id))

    return {"job_id": job_id, "status": "pending"}


@router.get("/status/{job_id}", response_model=PublishJobStatus)
def get_publish_status(job_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    status = get_job_status(job_id)
    if not status:
        return JSONResponse({"detail": "Job not found"}, status_code=404)
    return status


@router.post("/scrape-stats")
async def scrape_stats(request: Request):
    """Trigger stats collection for all platforms of a creator."""
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    creator_id = body.get("creator_id")
    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    from ..routers.creators import _scrape_stats_task
    asyncio.create_task(_scrape_stats_task(creator_id))
    return {"ok": True, "creator_id": creator_id}


@router.get("/selector-map/{platform}")
def get_selector_map(platform: str, request: Request):
    err = _auth(request)
    if err:
        return err
    smap = selector_map_get(platform)
    if not smap:
        # Try loading from file
        from ..publishers.base import load_selector_map
        selectors = load_selector_map(platform)
        if selectors:
            return {"platform": platform, "source": "file", "selectors": selectors}
        return JSONResponse({"detail": "Platform not found"}, status_code=404)
    return smap


@router.put("/selector-map/{platform}")
async def update_selector_map(platform: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    version = body.get("version", datetime.now(timezone.utc).strftime("%Y-%m"))
    selectors = body.get("selectors", {})
    if not isinstance(selectors, dict):
        return JSONResponse({"detail": "selectors must be an object"}, status_code=422)

    selector_map_upsert(platform, version, selectors)
    return {"ok": True, "platform": platform, "version": version}


@router.get("/supported-platforms")
def supported_platforms(request: Request):
    err = _auth(request)
    if err:
        return err
    return {"platforms": SUPPORTED_PLATFORMS}
