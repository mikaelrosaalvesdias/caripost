"""
Module 4: Trend Radar
Collect trending data and generate AI briefings for creators.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import (
    trend_raw_list, briefing_list, briefing_get, briefing_mark_sent, creator_list, creator_get, creator_update,
)
from ..models.trend import BriefingGenerateRequest, BriefingSendRequest, TrendScheduleUpdateRequest

router = APIRouter(prefix="/api/trends", tags=["trends"])

_TREND_JOB_KIND = "trend_ops"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _trend_job_put(job_id: str, payload: dict) -> None:
    from ..db import async_job_put
    async_job_put(kind=_TREND_JOB_KIND, job_id=job_id, payload=payload)

def _trend_job_get(job_id: str) -> Optional[dict]:
    from ..db import async_job_get
    return async_job_get(kind=_TREND_JOB_KIND, job_id=job_id)

def _trend_job_update(job_id: str, updates: dict) -> None:
    from ..db import async_job_get, async_job_put
    job = async_job_get(kind=_TREND_JOB_KIND, job_id=job_id) or {}
    job.update(updates)
    job["updated_at"] = _now()
    async_job_put(kind=_TREND_JOB_KIND, job_id=job_id, payload=job)

def _step_done(job_id: str, label: str) -> None:
    from ..db import async_job_get, async_job_put
    job = async_job_get(kind=_TREND_JOB_KIND, job_id=job_id) or {}
    steps = job.get("steps", [])
    # mark last running step done
    for s in reversed(steps):
        if s.get("status") == "running":
            s["status"] = "done"
            break
    steps.append({"label": label, "status": "running", "ts": _now()})
    job["steps"] = steps
    job["updated_at"] = _now()
    async_job_put(kind=_TREND_JOB_KIND, job_id=job_id, payload=job)

def _step_finish(job_id: str, label: str, status: str = "done") -> None:
    from ..db import async_job_get, async_job_put
    job = async_job_get(kind=_TREND_JOB_KIND, job_id=job_id) or {}
    steps = job.get("steps", [])
    for s in reversed(steps):
        if s.get("status") == "running":
            s["status"] = "done"
            break
    steps.append({"label": label, "status": status, "ts": _now()})
    job["steps"] = steps
    job["status"] = status
    job["updated_at"] = _now()
    async_job_put(kind=_TREND_JOB_KIND, job_id=job_id, payload=job)


async def _run_collect_job(job_id: str, creator: dict, channels: list) -> None:
    """Background task: scrape each channel and report progress."""
    creator_id = creator["creator_id"]
    total = len(channels)
    videos_found = 0
    try:
        from ..services.trend_collector import (
            scrape_xvideos_channel, scrape_pornhub_channel, _detect_platform,
        )
        from ..db_agency import trend_raw_insert
        now = datetime.now(timezone.utc).isoformat()
        for i, channel_url in enumerate(channels, 1):
            channel_url = str(channel_url or "").strip()
            if not channel_url:
                continue
            short = channel_url.split("/")[-1] or channel_url
            _step_done(job_id, f"Coletando canal {i}/{total}: {short}…")
            _trend_job_update(job_id, {"channels_done": i - 1})

            platform = _detect_platform(channel_url)
            try:
                if platform == "pornhub":
                    videos = await scrape_pornhub_channel(channel_url, limit=20)
                    db_platform = "pornhub_channel"
                else:
                    videos = await scrape_xvideos_channel(channel_url, limit=20)
                    db_platform = "xvideos_channel"

                videos.sort(key=lambda v: v.get("views", 0), reverse=True)
                for v in videos[:20]:
                    try:
                        trend_raw_insert({
                            "id": str(uuid.uuid4()),
                            "platform": db_platform,
                            "collected_at": now,
                            "data_type": "channel_video",
                            "data": {**v, "creator_id": creator_id, "channel_url": channel_url},
                        })
                        videos_found += 1
                    except Exception:
                        pass
                _trend_job_update(job_id, {"channels_done": i, "videos_found": videos_found})
            except Exception as exc:
                logger.error("[collect-job] channel %s failed: %s", channel_url, exc)

        _step_finish(job_id, f"✅ Coleta concluída — {videos_found} vídeos de {total} canal(is)", "done")
        _trend_job_update(job_id, {"channels_done": total, "videos_found": videos_found})
    except Exception as exc:
        logger.error("[collect-job] failed: %s", exc)
        _step_finish(job_id, f"❌ Erro: {exc}", "error")


async def _run_briefing_job(job_id: str, creator_id: str) -> None:
    """Background task: generate briefing with Grok and report progress."""
    try:
        _step_done(job_id, "Buscando vídeos dos canais de referência…")
        from ..db_agency import trend_channel_videos_for_creator
        channel_rows = trend_channel_videos_for_creator(creator_id, limit=200)
        n_videos = len(channel_rows)

        _step_done(job_id, f"Dados prontos: {n_videos} vídeos dos canais de referência. Enviando para Grok…")
        from ..services.trend_briefing import generate_briefing_for_creator
        briefing = await generate_briefing_for_creator(creator_id)

        if not briefing:
            _step_finish(job_id, "❌ Grok não respondeu ou não há chave de API configurada.", "error")
            return

        n_suggestions = len((briefing.get("content") or {}).get("suggestions") or [])
        _step_finish(job_id, f"✅ Briefing gerado com {n_suggestions} sugestões — aguardando aprovação", "awaiting_approval")
        _trend_job_update(job_id, {
            "briefing_id": briefing.get("briefing_id"),
            "briefing": briefing,
        })
    except Exception as exc:
        logger.error("[briefing-job] failed: %s", exc)
        _step_finish(job_id, f"❌ Erro: {exc}", "error")


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


@router.post("/collect")
async def collect_trends(request: Request):
    """Manually trigger global trend data collection."""
    err = _auth(request)
    if err:
        return err
    from ..services.trend_collector import collect_trending_data
    asyncio.create_task(collect_trending_data())
    return {"ok": True, "message": "Trend collection started in background"}


@router.post("/collect-channels/{creator_id}")
async def collect_creator_channels(creator_id: str, request: Request):
    """Start channel collection job with progress tracking."""
    err = _auth(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    channels = creator.get("reference_channels") or []
    if not channels:
        return JSONResponse({"detail": "Este criador não tem canais de referência configurados."}, status_code=422)

    job_id = str(uuid.uuid4())
    _trend_job_put(job_id, {
        "job_id": job_id, "creator_id": creator_id,
        "creator_name": creator.get("name", ""),
        "type": "collect_channels",
        "status": "running",
        "steps": [{"label": f"Iniciando coleta de {len(channels)} canal(is)…", "status": "running", "ts": _now()}],
        "channels_total": len(channels), "channels_done": 0, "videos_found": 0,
        "created_at": _now(), "updated_at": _now(),
    })
    asyncio.create_task(_run_collect_job(job_id, creator, channels))
    return {"ok": True, "job_id": job_id, "channels": len(channels)}


@router.post("/generate-briefing-job/{creator_id}")
async def generate_briefing_job(creator_id: str, request: Request):
    """Start briefing generation job with progress tracking."""
    err = _auth(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    job_id = str(uuid.uuid4())
    _trend_job_put(job_id, {
        "job_id": job_id, "creator_id": creator_id,
        "creator_name": creator.get("name", ""),
        "type": "generate_briefing",
        "status": "running",
        "steps": [{"label": "Preparando dados para o Grok…", "status": "running", "ts": _now()}],
        "briefing_id": None, "briefing": None,
        "created_at": _now(), "updated_at": _now(),
    })
    asyncio.create_task(_run_briefing_job(job_id, creator_id))
    return {"ok": True, "job_id": job_id}


@router.get("/job/{job_id}")
def get_trend_job(job_id: str, request: Request):
    """Poll status of a trend collection or briefing generation job."""
    err = _auth(request)
    if err:
        return err
    job = _trend_job_get(job_id)
    if not job:
        return JSONResponse({"detail": "Job not found"}, status_code=404)
    return job


@router.post("/approve-briefing/{briefing_id}")
async def approve_briefing(briefing_id: str, request: Request):
    """Approve a briefing and optionally notify the creator."""
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    notify = bool(body.get("notify", True))

    b = briefing_get(briefing_id)
    if not b:
        return JSONResponse({"detail": "Briefing not found"}, status_code=404)

    creator = creator_get(b["creator_id"])
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    results = {}
    if notify and creator.get("notification_email") and creator.get("email"):
        from ..services.email_sender import send_briefing_email
        result = await send_briefing_email(creator, b)
        results["email"] = result
        if result.get("success"):
            briefing_mark_sent(briefing_id, "email")

    return {"ok": True, "briefing_id": briefing_id, "notified": notify, "results": results}


@router.get("/latest")
def get_latest_trends(request: Request, platform: Optional[str] = None,
                       data_type: Optional[str] = None, limit: int = 50):
    err = _auth(request)
    if err:
        return err
    trends = trend_raw_list(platform=platform, data_type=data_type, limit=limit)
    return {"trends": trends, "total": len(trends)}


@router.post("/generate-briefing")
async def generate_briefing(body: BriefingGenerateRequest, request: Request):
    """Generate a trend briefing for a specific creator."""
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    creator_id = body.get("creator_id")
    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    from ..services.trend_briefing import generate_briefing_for_creator
    briefing = await generate_briefing_for_creator(creator_id)
    if not briefing:
        return JSONResponse(
            {"detail": "Failed to generate briefing. Check LLM provider configuration."},
            status_code=500,
        )
    return briefing


@router.get("/briefings")
def list_briefings(request: Request, creator_id: Optional[str] = None, limit: int = 50):
    err = _auth(request)
    if err:
        return err
    briefings = briefing_list(creator_id=creator_id, limit=limit)
    return {"briefings": briefings, "total": len(briefings)}


@router.get("/briefings/{briefing_id}")
def get_briefing(briefing_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    b = briefing_get(briefing_id)
    if not b:
        return JSONResponse({"detail": "Briefing not found"}, status_code=404)
    return b


@router.post("/send-briefing")
async def send_briefing(body: BriefingSendRequest, request: Request):
    """Send a briefing to the creator via email and/or WhatsApp."""
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    briefing_id = body.get("briefing_id")
    channels = body.get("channels", ["email"])
    if not briefing_id:
        return JSONResponse({"detail": "briefing_id is required"}, status_code=422)

    b = briefing_get(briefing_id)
    if not b:
        return JSONResponse({"detail": "Briefing not found"}, status_code=404)

    from ..db_agency import creator_get
    creator = creator_get(b["creator_id"])
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    results = {}
    if "email" in channels and creator.get("notification_email") and creator.get("email"):
        from ..services.email_sender import send_briefing_email
        result = await send_briefing_email(creator, b)
        results["email"] = result
        if result.get("success"):
            briefing_mark_sent(briefing_id, "email")

    if "whatsapp" in channels and creator.get("notification_whatsapp") and creator.get("whatsapp"):
        # WhatsApp via Evolution API / n8n webhook — future implementation
        results["whatsapp"] = {"success": False, "error": "WhatsApp not yet configured"}

    return {"ok": True, "briefing_id": briefing_id, "results": results}


@router.post("/generate-all-briefings")
async def generate_all_briefings(request: Request):
    """Generate briefings for all active creators (admin trigger)."""
    err = _auth(request)
    if err:
        return err
    from ..services.trend_briefing import generate_briefings_for_all_creators
    asyncio.create_task(generate_briefings_for_all_creators())
    return {"ok": True, "message": "Briefing generation started for all active creators"}


@router.get("/schedule")
def get_briefing_schedule(request: Request):
    err = _auth(request)
    if err:
        return err
    creators = creator_list(limit=500)
    return {
        "schedule": [
            {
                "creator_id": c.get("creator_id"),
                "name": c.get("name"),
                "status": c.get("status"),
                "trend_report_frequency": c.get("trend_report_frequency", "weekly"),
                "notification_email": bool(c.get("notification_email")),
                "notification_whatsapp": bool(c.get("notification_whatsapp")),
            }
            for c in creators
        ]
    }


@router.put("/schedule")
async def update_briefing_schedule(body: TrendScheduleUpdateRequest, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    creator_id = body.get("creator_id")
    frequency = str(body.get("trend_report_frequency") or "").strip().lower()
    valid = {"daily", "weekly", "biweekly", "monthly"}
    if frequency not in valid:
        return JSONResponse({"detail": f"trend_report_frequency must be one of {sorted(valid)}"}, status_code=422)
    if not creator_get(creator_id):
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    creator_update(creator_id, {"trend_report_frequency": frequency})
    return {"ok": True, "creator_id": creator_id, "trend_report_frequency": frequency}
