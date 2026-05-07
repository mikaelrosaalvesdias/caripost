from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db import async_job_get, async_job_list, async_job_put, settings_get, settings_set
from ..db_agency import creator_get
from ..models.auto_editor import AutoEditorRequest, AutoEditorStartResponse, AutoEditorStatus
from ..services.auto_editor_pipeline import ASYNC_KIND, run_auto_editor_job, run_recut_job, _model_dump

router = APIRouter(prefix="/api/auto-editor", tags=["auto-editor"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


@router.post("/start", response_model=AutoEditorStartResponse)
async def start_auto_editor(body: AutoEditorRequest, request: Request):
    err = _auth(request)
    if err:
        return err

    payload = _model_dump(body)
    raw_keys = payload.get("video_object_keys") or []
    source_keys = [str(k or "").strip() for k in raw_keys if str(k or "").strip()]
    primary_key = str(payload.get("video_object_key") or "").strip()
    if primary_key and primary_key not in source_keys:
        source_keys.insert(0, primary_key)
    if not source_keys:
        return JSONResponse({"detail": "Selecione ao menos um vídeo"}, status_code=400)
    payload["video_object_key"] = source_keys[0]
    payload["video_object_keys"] = source_keys
    creator_id = str(payload.get("creator_id") or "").strip()
    if creator_id and not creator_get(creator_id):
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    job_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async_job_put(
        kind=ASYNC_KIND,
        job_id=job_id,
        payload={
            "kind": ASYNC_KIND,
            "job_id": job_id,
            "status": "pending",
            "detail": "Na fila do AutoEditor…",
            "progress_pct": 0,
            "creator_id": creator_id,
            "source_video_key": source_keys[0],
            "source_video_keys": source_keys,
            "request": payload,
            "created_at": now,
            "updated_at": now,
        },
    )
    asyncio.create_task(run_auto_editor_job(job_id))
    return {"job_id": job_id, "status": "pending"}


@router.get("/status/{job_id}", response_model=AutoEditorStatus)
def get_auto_editor_status(job_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    status = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not status:
        return JSONResponse({"detail": "Job not found"}, status_code=404)
    return status


@router.post("/recut/{job_id}", response_model=AutoEditorStartResponse)
async def recut_auto_editor(job_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    original = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not original:
        return JSONResponse({"detail": "Job not found"}, status_code=404)
    if original.get("status") not in ("done", "error"):
        return JSONResponse({"detail": "Job not finished yet"}, status_code=400)

    new_job_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async_job_put(
        kind=ASYNC_KIND,
        job_id=new_job_id,
        payload={
            "kind": ASYNC_KIND,
            "job_id": new_job_id,
            "status": "pending",
            "detail": "Re-cut na fila…",
            "progress_pct": 0,
            "creator_id": original.get("creator_id", ""),
            "source_video_key": original.get("source_video_key", ""),
            "source_video_keys": original.get("source_video_keys", []),
            "recut_of": job_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    asyncio.create_task(run_recut_job(job_id, new_job_id))
    return {"job_id": new_job_id, "status": "pending"}


@router.get("/config")
def get_ae_config(request: Request):
    err = _auth(request)
    if err:
        return err
    from ..services.auto_editor_pipeline import _default_narrative_rules
    _row = settings_get(key="ae_narrative_rules")
    saved = (_row or {}).get("value") or None
    return {
        "narrative_rules": saved if saved else _default_narrative_rules(),
        "is_custom": bool(saved),
    }


@router.put("/config")
async def put_ae_config(request: Request):
    err = _auth(request)
    if err:
        return err
    body = await request.json()
    rules = str(body.get("narrative_rules") or "").strip()
    if not rules:
        return JSONResponse({"detail": "narrative_rules não pode ser vazio"}, status_code=400)
    settings_set(key="ae_narrative_rules", value=rules, updated_at=datetime.now(timezone.utc).isoformat())
    return {"ok": True}


@router.delete("/config")
def reset_ae_config(request: Request):
    err = _auth(request)
    if err:
        return err
    settings_set(key="ae_narrative_rules", value="", updated_at=datetime.now(timezone.utc).isoformat())
    from ..services.auto_editor_pipeline import _default_narrative_rules
    return {"ok": True, "narrative_rules": _default_narrative_rules()}


@router.get("/jobs")
def list_auto_editor_jobs(request: Request, status: str = "", limit: int = 30):
    err = _auth(request)
    if err:
        return err
    statuses = [s.strip() for s in status.split(",") if s.strip()] or None
    jobs = async_job_list(kind=ASYNC_KIND, statuses=statuses, limit=max(1, min(limit, 200)))
    jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"jobs": jobs, "total": len(jobs)}
