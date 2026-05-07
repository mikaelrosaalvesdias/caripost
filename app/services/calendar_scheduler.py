"""
Calendar scheduler: processes due calendar entries and triggers publishing.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from ..db_agency import calendar_due, calendar_update, publish_job_create
from .publish_pipeline import run_publish_pipeline

logger = logging.getLogger(__name__)


async def process_scheduled_publications() -> Dict[str, Any]:
    """
    Check for calendar entries due for publishing and kick them off.
    Called by cron every 5 minutes.
    """
    now = datetime.now(timezone.utc).isoformat()
    due_entries = calendar_due(now)
    triggered = 0

    for entry in due_entries:
        entry_id = entry["entry_id"]
        creator_id = entry["creator_id"]
        platforms = entry.get("publish_platforms", [])

        if not platforms:
            calendar_update(entry_id, {"status": "error", "publish_results": {"error": "No platforms specified"}})
            continue

        # Mark as publishing
        calendar_update(entry_id, {"status": "publishing"})

        # Create and run publish job
        job_id = str(uuid.uuid4())
        now_ts = datetime.now(timezone.utc).isoformat()
        publish_job_create({
            "job_id": job_id,
            "creator_id": creator_id,
            "video_object_key": entry["video_object_key"],
            "thumbnail_object_key": None,
            "platforms": platforms,
            "metadata": {
                "title": entry.get("title", ""),
                "description": entry.get("description", ""),
                "tags": entry.get("tags", []),
                "category": entry.get("category", "Amateur"),
                "is_premium": False,
            },
            "status": "pending",
            "created_at": now_ts,
            "updated_at": now_ts,
        })

        # Run pipeline as background task
        asyncio.create_task(_run_and_update_calendar(job_id, entry_id))
        triggered += 1

    return {"triggered": triggered, "checked_at": now}


async def _run_and_update_calendar(job_id: str, entry_id: str) -> None:
    """Run publish pipeline and update calendar entry status on completion."""
    try:
        await run_publish_pipeline(job_id)
        from ..db_agency import publish_job_get, publications_by_job
        job = publish_job_get(job_id)
        pubs = publications_by_job(job_id)
        results = {p["platform"]: {"status": p["status"], "video_url": p.get("video_url")} for p in pubs}
        final_status = "done" if job and job.get("status") == "done" else "error"
        calendar_update(entry_id, {
            "status": final_status,
            "published": final_status == "done",
            "publish_results": results,
        })
    except Exception as exc:
        logger.error("Calendar entry %s publish pipeline failed: %s", entry_id, exc)
        calendar_update(entry_id, {"status": "error", "publish_results": {"error": str(exc)}})


async def auto_schedule(
    creator_id: str,
    video_object_keys: list,
    platforms: list,
    period_days: int = 7,
    timezone_str: str = "America/Sao_Paulo",
) -> Dict[str, Any]:
    """
    Use Grok to generate an optimal publishing schedule and create calendar entries.
    """
    from ..db_agency import creator_get, calendar_create
    from ..llm import ProviderSpec, run_providers_to_completion
    from ..db import settings_get
    import json as _json
    from datetime import timedelta

    creator = creator_get(creator_id)
    if not creator:
        return {"error": "creator_not_found"}

    now = datetime.now(timezone.utc)
    prompt = f"""
Você é um estrategista de publicação de conteúdo adulto.

Criador: {creator["name"]}
Plataformas: {", ".join(platforms)}
Vídeos para agendar: {len(video_object_keys)}
Período: {period_days} dias a partir de agora
Fuso horário: {timezone_str}

Regras:
1. Máximo 2 vídeos por dia
2. Mínimo 8 horas entre publicações
3. Publicar nos horários de pico: 21h-23h (horário de Brasília)
4. Distribuir uniformemente pelo período

Gere um cronograma com exatamente {len(video_object_keys)} entradas.
Retorne SOMENTE JSON array:
[{{"publish_at": "ISO datetime UTC", "video_index": 0}}]
"""

    # Generate schedule via LLM (best-effort, fallback to even distribution)
    schedule = []
    try:
        raw = settings_get("tokens")
        tokens = _json.loads(raw) if raw else []
        provider = None
        for t in (tokens if isinstance(tokens, list) else []):
            if str(t.get("name", "")).lower() in ("grok", "openai"):
                provider = ProviderSpec(name=t["name"], model=t.get("model", "grok-3"), api_key=t.get("api_key", ""))
                break
        if provider:
            _results = await run_providers_to_completion(
                providers=[provider],
                prompt=prompt,
                params={"temperature": 0.4, "max_tokens": 2000},
            )
            result_text = _results[0]["text"] if _results and _results[0].get("ok") else ""
            text = (result_text or "").strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()
            schedule = _json.loads(text)
    except Exception as exc:
        logger.warning("Auto-schedule LLM failed, using even distribution: %s", exc)

    # Fallback: even distribution, peak hour (22:00 BRT = 01:00 UTC)
    if not schedule or len(schedule) < len(video_object_keys):
        schedule = []
        hours_between = max(8, (period_days * 24) // max(len(video_object_keys), 1))
        for i, _ in enumerate(video_object_keys):
            dt = now + timedelta(hours=hours_between * i + 1)
            # Set to 01:00 UTC (22:00 BRT)
            dt = dt.replace(hour=1, minute=0, second=0, microsecond=0)
            schedule.append({"publish_at": dt.isoformat(), "video_index": i})

    # Create calendar entries
    created_entries = []
    for item in schedule:
        idx = item.get("video_index", 0)
        if idx >= len(video_object_keys):
            continue
        entry_id = str(uuid.uuid4())
        now_ts = datetime.now(timezone.utc).isoformat()
        calendar_create({
            "entry_id": entry_id,
            "creator_id": creator_id,
            "video_object_key": video_object_keys[idx],
            "publish_platforms": platforms,
            "publish_at": item["publish_at"],
            "cross_promote": True,
            "cross_channels": ["telegram"],
            "status": "scheduled",
            "created_at": now_ts,
            "updated_at": now_ts,
        })
        created_entries.append(entry_id)

    return {"created": len(created_entries), "entry_ids": created_entries}
