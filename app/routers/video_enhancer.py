from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

from ..db import async_job_get, async_job_list, async_job_put
from ..services.video_enhancer import (
    ASYNC_KIND,
    _ALLOWED_EXTENSIONS,
    _MAX_SIZE_BYTES_DEFAULT,
    _ensure_dirs,
    check_video2x,
    run_enhance_job,
    validate_input,
)

router = APIRouter(prefix="/api/video-enhancer", tags=["video-enhancer"])

_VALID_RESOLUTIONS = {"720p", "1080p"}


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


# ── POST /enhance ───────────────────────────────────────────────────────────
@router.post("/enhance")
async def enhance_video(
    request: Request,
    file: UploadFile = File(default=None),
):
    """
    Melhora a qualidade de um vídeo usando Video2X.

    Aceita:
      - multipart upload (campo 'file') — para upload direto
      - JSON body com 'video_object_key' (local: ref) — para vídeo já armazenado

    Parâmetros opcionais (query string ou JSON):
      - resolution: 720p | 1080p (padrão: 720p)
    """
    err = _auth(request)
    if err:
        return err

    resolution = (request.query_params.get("resolution") or "720p").lower()
    if resolution not in _VALID_RESOLUTIONS:
        return JSONResponse({"error": "invalid_resolution", "detail": f"Use: {', '.join(sorted(_VALID_RESOLUTIONS))}"}, status_code=400)

    dirs = _ensure_dirs()
    job_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # ── Determinar arquivo de entrada ───────────────────────────────────────
    input_path: str | None = None
    original_filename = "video"

    if file and file.filename:
        # Upload direto via multipart
        ext = Path(file.filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return JSONResponse({"error": "invalid_format", "detail": f"Formatos permitidos: {', '.join(_ALLOWED_EXTENSIONS)}"}, status_code=400)

        dest = os.path.join(dirs["original"], f"{job_id}{ext}")
        try:
            with open(dest, "wb") as f_out:
                while chunk := await file.read(1024 * 1024):
                    f_out.write(chunk)
        except Exception as exc:
            return JSONResponse({"error": "upload_failed", "detail": str(exc)}, status_code=500)

        size = os.path.getsize(dest)
        if size > _MAX_SIZE_BYTES_DEFAULT:
            os.remove(dest)
            max_mb = _MAX_SIZE_BYTES_DEFAULT // (1024 * 1024)
            return JSONResponse({"error": "file_too_large", "detail": f"Máximo {max_mb}MB"}, status_code=413)

        input_path = dest
        original_filename = file.filename

    else:
        # Referência a vídeo já armazenado (video_object_key ou input_path)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "missing_input", "detail": "Envie um arquivo via multipart ou {'video_object_key': 'local:...'} no body JSON."}, status_code=400)

        resolution = body.get("resolution", resolution).lower()
        if resolution not in _VALID_RESOLUTIONS:
            return JSONResponse({"error": "invalid_resolution", "detail": f"Use: {', '.join(sorted(_VALID_RESOLUTIONS))}"}, status_code=400)

        obj_key = str(body.get("video_object_key") or body.get("input_path") or "").strip()
        if not obj_key:
            return JSONResponse({"error": "missing_input", "detail": "Informe 'video_object_key' ou faça upload via multipart."}, status_code=400)

        # Resolve local: ref
        if obj_key.startswith("local:"):
            media_root = os.environ.get("LOCAL_MEDIA_ROOT", "/media")
            rel = obj_key[len("local:"):]
            input_path = os.path.join(media_root, rel)
        else:
            input_path = obj_key

        original_filename = os.path.basename(input_path)

        err_msg = validate_input(input_path)
        if err_msg:
            return JSONResponse({"error": "invalid_input", "detail": err_msg}, status_code=400)

    # ── Saída ───────────────────────────────────────────────────────────────
    ext_out = Path(original_filename).suffix.lower() or ".mp4"
    output_filename = f"{Path(original_filename).stem}_{resolution}_{job_id[:8]}{ext_out}"
    output_path = os.path.join(dirs["processed"], output_filename)

    # ── Criar job e disparar em background ─────────────────────────────────
    async_job_put(
        kind=ASYNC_KIND,
        job_id=job_id,
        payload={
            "status": "queued",
            "detail": "Na fila…",
            "progress_pct": 0,
            "input_path": input_path,
            "output_path": output_path,
            "resolution": resolution,
            "original_filename": original_filename,
            "created_at": now,
        },
        created_at=now,
    )

    asyncio.create_task(run_enhance_job(job_id))

    return {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "resolution": resolution,
        "input_path": input_path,
        "output_path": output_path,
        "status_url": f"/api/video-enhancer/status/{job_id}",
    }


# ── GET /status/{job_id} ────────────────────────────────────────────────────
@router.get("/status/{job_id}")
def status(job_id: str, request: Request):
    err = _auth(request)
    if err:
        return err

    job = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not job:
        return JSONResponse({"detail": "Job não encontrado"}, status_code=404)
    return job


# ── GET /jobs ───────────────────────────────────────────────────────────────
@router.get("/jobs")
def list_jobs(request: Request, limit: int = 20):
    err = _auth(request)
    if err:
        return err

    jobs = async_job_list(kind=ASYNC_KIND, limit=max(1, min(limit, 100)))
    jobs.sort(key=lambda j: str(j.get("created_at") or ""), reverse=True)
    return {"jobs": jobs, "total": len(jobs)}


# ── GET /check ──────────────────────────────────────────────────────────────
@router.get("/check")
def check_installation(request: Request):
    """Verifica se o Video2X está instalado e acessível."""
    err = _auth(request)
    if err:
        return err

    available, msg = check_video2x()
    if available:
        return {"ok": True, "video2x": msg}
    return JSONResponse({"ok": False, "error": msg, "install": "pip install video2x"}, status_code=503)
