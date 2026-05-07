"""
Module 3: Creator Portal API
JWT-authenticated endpoints for the creator-facing dashboard.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..db_agency import (
    creator_get, creator_get_by_slug, creator_list, creator_update, publications_by_creator,
    briefing_list, calendar_list, earnings_list, earnings_report,
    creator_stats_latest,
)
from ..models.creator import CreatorPortalBrandingPublic

router = APIRouter(prefix="/api/portal", tags=["portal"])

_JWT_SECRET = os.environ.get("PORTAL_JWT_SECRET", os.environ.get("ADULT_META_API_KEY", "metaporn-portal-secret"))
_JWT_EXPIRE_HOURS = 24


def _make_jwt(creator_id: str) -> str:
    """Minimal JWT-like token (HS256-signed). For full JWT use python-jose."""
    import base64, hmac as _hmac, hashlib as _hashlib, time
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = {
        "sub": creator_id,
        "exp": int(time.time()) + _JWT_EXPIRE_HOURS * 3600,
        "iat": int(time.time()),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    msg = f"{header}.{payload_b64}"
    sig = _hmac.new(
        _JWT_SECRET.encode(), msg.encode(), _hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{msg}.{sig_b64}"


def _verify_jwt(token: str) -> Optional[str]:
    """Returns creator_id if token is valid, else None."""
    import base64, hmac as _hmac, hashlib as _hashlib, time
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_payload = f"{parts[0]}.{parts[1]}"
        expected_sig = base64.urlsafe_b64encode(
            _hmac.new(_JWT_SECRET.encode(), header_payload.encode(), _hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if not _hmac.compare_digest(parts[2], expected_sig):
            return None
        # Decode payload
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("sub")
    except Exception:
        return None


def _portal_auth(request: Request) -> Optional[str]:
    """Returns creator_id from JWT or None if unauthorized."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return _verify_jwt(token)
    return None


def _creator_password_hash(password: str, creator_id: str) -> str:
    """Simple password hash. In production, use bcrypt."""
    return hashlib.sha256(f"{creator_id}:{password}:{_JWT_SECRET}".encode()).hexdigest()


def _public_creator_portal_payload(creator: dict) -> dict:
    return {
        "creator_id": creator["creator_id"],
        "slug": str(creator.get("slug") or "").strip(),
        "name": creator.get("name") or "",
        "status": creator.get("status") or "trial",
        "portal_branding": creator.get("portal_branding") or {},
    }


# ─────────────────────────────────────────────────────────────────────────────

@router.post("/login")
async def portal_login(request: Request):
    """Creator login — returns JWT."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))

    if not email or not password:
        return JSONResponse({"detail": "email and password are required"}, status_code=422)

    # Find creator by email
    creators = creator_list()
    creator = next((c for c in creators if c.get("email", "").lower() == email), None)
    if not creator:
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    # Check password (stored hash in settings key portal:pass:{creator_id})
    from ..db import settings_get
    stored_row = settings_get(key=f"portal:pass:{creator['creator_id']}")
    if not stored_row:
        return JSONResponse({"detail": "Password not set. Contact agency admin."}, status_code=401)
    stored_hash = str(stored_row.get("value") or "")
    if not stored_hash:
        return JSONResponse({"detail": "Password not set. Contact agency admin."}, status_code=401)

    expected = _creator_password_hash(password, creator["creator_id"])
    if stored_hash != expected:
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    token = _make_jwt(creator["creator_id"])
    return {
        "token": token,
        "creator": {
            "creator_id": creator["creator_id"],
            "slug": creator.get("slug"),
            "name": creator["name"],
            "email": creator["email"],
            "status": creator["status"],
            "portal_branding": creator.get("portal_branding") or {},
        },
    }


@router.get("/brand/{slug}", response_model=CreatorPortalBrandingPublic)
def portal_branding_by_slug(slug: str):
    creator = creator_get_by_slug(slug)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    return _public_creator_portal_payload(creator)


@router.post("/set-password")
async def portal_set_password(request: Request):
    """Admin endpoint to set a creator's portal password."""
    from ..main_utils import require_api_key
    err = require_api_key(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    creator_id = body.get("creator_id")
    password = body.get("password")
    if not creator_id or not password:
        return JSONResponse({"detail": "creator_id and password are required"}, status_code=422)

    from ..db import settings_set
    hashed = _creator_password_hash(password, creator_id)
    settings_set(
        key=f"portal:pass:{creator_id}",
        value=hashed,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    return {"ok": True, "creator_id": creator_id}


@router.get("/me")
def portal_me(request: Request):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    # Remove sensitive fields
    creator.pop("real_name", None)
    creator.pop("logo_b64", None)
    return creator


@router.put("/profile")
async def portal_update_profile(request: Request):
    """Creator updates their own production profile."""
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=422)

    # Only allow safe production profile fields — no status, commission, etc.
    allowed = {
        "filming_setups", "performer_description", "location_types",
        "production_level", "production_constraints",
        "preferred_categories", "preferred_tags",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return JSONResponse({"detail": "No valid fields to update"}, status_code=422)

    creator_update(creator_id, updates)
    return {"ok": True, "updated": list(updates.keys())}


@router.get("/my-videos")
def portal_my_videos(request: Request, page: int = 1, limit: int = 20, sort: str = "date"):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    pubs = publications_by_creator(creator_id, limit=limit * page)
    # Simple pagination
    start = (page - 1) * limit
    return {"videos": pubs[start:start + limit], "page": page, "total": len(pubs)}


@router.get("/my-videos/{video_id}/stats")
def portal_video_stats(video_id: str, request: Request):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    from ..db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM video_stats
            WHERE creator_id=? AND video_id=?
            ORDER BY scraped_at DESC
            """,
            (creator_id, video_id),
        ).fetchall()
    stats = [dict(r) for r in rows]
    latest_by_platform = {}
    for item in stats:
        latest_by_platform.setdefault(item.get("platform"), item)
    return {
        "video_id": video_id,
        "latest_by_platform": latest_by_platform,
        "history": stats[:50],
    }


@router.get("/my-stats/overview")
def portal_stats_overview(request: Request, period: str = "30d"):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    stats = creator_stats_latest(creator_id)
    total_views = sum(s.get("total_views", 0) for s in stats)
    total_videos = max((s.get("total_videos", 0) for s in stats), default=0)

    # Financial summary
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    creator = creator_get(creator_id)
    commission_pct = float(creator.get("commission_pct", 25.0)) if creator else 25.0
    report = earnings_report(creator_id, month, commission_pct)

    return {
        "total_views": total_views,
        "total_videos": total_videos,
        "estimated_earnings_this_month": report.get("total_creator_payout", 0.0),
        "platform_stats": stats,
        "period": period,
    }


@router.get("/my-stats/chart")
def portal_stats_chart(
    request: Request,
    metric: str = "views",
    period: str = "30d",
    granularity: str = "day",
):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    days_map = {"7d": 7, "30d": 30, "90d": 90}
    start_dt = None
    if period in days_map:
        start_dt = datetime.now(timezone.utc) - timedelta(days=days_map[period])

    from ..db import get_conn
    bucket_expr = "substr(scraped_at, 1, 10)" if granularity == "day" else "substr(scraped_at, 1, 7)"
    data = []
    with get_conn() as conn:
        if metric == "earnings":
            if granularity == "day":
                period_expr = "period || '-01'"
            else:
                period_expr = "period"
            sql = f"""
                SELECT {period_expr} AS bucket, SUM(creator_payout) AS value
                FROM earning_records
                WHERE creator_id=?
            """
            params = [creator_id]
            if start_dt:
                sql += " AND period>=?"
                params.append(start_dt.strftime("%Y-%m"))
            sql += " GROUP BY bucket ORDER BY bucket ASC"
            rows = conn.execute(sql, params).fetchall()
            data = [{"bucket": r["bucket"], "value": round(float(r["value"] or 0.0), 2)} for r in rows]
        else:
            sql = f"""
                SELECT {bucket_expr} AS bucket, SUM(total_views) AS value
                FROM creator_stats
                WHERE creator_id=?
            """
            params = [creator_id]
            if start_dt:
                sql += " AND scraped_at>=?"
                params.append(start_dt.isoformat())
            sql += " GROUP BY bucket ORDER BY bucket ASC"
            rows = conn.execute(sql, params).fetchall()
            data = [{"bucket": r["bucket"], "value": int(r["value"] or 0)} for r in rows]

    return {
        "metric": metric,
        "period": period,
        "granularity": granularity,
        "points": data,
    }


@router.get("/my-earnings")
def portal_earnings(request: Request, month: Optional[str] = None):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    creator = creator_get(creator_id)
    commission_pct = float(creator.get("commission_pct", 25.0)) if creator else 25.0
    return earnings_report(creator_id, month, commission_pct)


@router.get("/my-trends")
def portal_trends(request: Request, limit: int = 20, offset: int = 0):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    all_briefings = briefing_list(creator_id=creator_id, limit=limit + offset)
    page = all_briefings[offset:offset + limit]
    # Flatten content fields to top level for convenience
    out = []
    for b in page:
        content = b.get("content") or {}
        out.append({
            "briefing_id": b["briefing_id"],
            "creator_id": b["creator_id"],
            "generated_at": b.get("generated_at", ""),
            "sent_email": bool(b.get("sent_email")),
            "sent_whatsapp": bool(b.get("sent_whatsapp")),
            "market_summary": content.get("market_summary", ""),
            "top_channel_insights": content.get("top_channel_insights") or [],
            "suggestions": content.get("suggestions") or [],
            "avoid": content.get("avoid") or [],
        })
    return {"briefings": out, "total": len(all_briefings), "limit": limit, "offset": offset}


@router.get("/my-schedule")
def portal_schedule(request: Request):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    entries = calendar_list(creator_id=creator_id, limit=50)
    return {"entries": entries}


@router.post("/upload-raw")
async def portal_upload_raw(
    request: Request,
    file: UploadFile = File(...),
    title_hint: str = Form(""),
    target_duration_minutes: int = Form(40),
):
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    from .. import main as main_mod
    from ..db import async_job_put
    from ..services.auto_editor_pipeline import ASYNC_KIND, run_auto_editor_job

    if not file.filename:
        return JSONResponse({"detail": "Missing file name"}, status_code=422)

    with tempfile.TemporaryDirectory(prefix="portal-upload-", dir=main_mod._preferred_tmpdir_root("portal")) as td:
        tmp_path = os.path.join(td, file.filename)
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        stored = await asyncio.to_thread(
            main_mod._store_local_path,
            src_path=tmp_path,
            prefix=f"uploads/portal/{creator_id}",
            filename=file.filename,
            content_type=file.content_type or "video/mp4",
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async_job_put(
        kind=ASYNC_KIND,
        job_id=job_id,
        payload={
            "kind": ASYNC_KIND,
            "job_id": job_id,
            "status": "pending",
            "detail": "Upload concluído; AutoEditor na fila…",
            "progress_pct": 0,
            "creator_id": creator_id,
            "source_video_key": stored.get("object_key", ""),
            "request": {
                "creator_id": creator_id,
                "video_object_key": stored.get("object_key", ""),
                "title_hint": title_hint or file.filename,
                "target_duration_minutes": max(1, min(int(target_duration_minutes or 40), 240)),
            },
            "created_at": now,
            "updated_at": now,
        },
    )
    asyncio.create_task(run_auto_editor_job(job_id))
    return {
        "ok": True,
        "creator_id": creator_id,
        "upload": stored,
        "job_id": job_id,
    }


@router.get("/upload-job/{job_id}")
def portal_upload_job_status(job_id: str, request: Request):
    """Poll status of an upload/autoeditor job."""
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    from ..db import async_job_get
    from ..services.auto_editor_pipeline import ASYNC_KIND
    job = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not job or job.get("creator_id") != creator_id:
        return JSONResponse({"detail": "Job not found"}, status_code=404)
    return {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "detail": job.get("detail", ""),
        "progress_pct": job.get("progress_pct", 0),
        "output_key": job.get("output_object_key", ""),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
    }


@router.get("/drive-status")
def portal_drive_status(request: Request):
    """Check if creator has Google Drive configured."""
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    folder_id = str(creator.get("drive_folder_id") or "").strip()
    has_creds = bool(str(creator.get("drive_service_account") or "").strip())
    # Fall back to global config
    from ..db import settings_get
    if not folder_id:
        row = settings_get(key="google_drive:folder_id")
        folder_id = str((row or {}).get("value") or "").strip()
    if not has_creds:
        row = settings_get(key="google_drive:service_account_json")
        has_creds = bool(str((row or {}).get("value") or "").strip())
    configured = bool(folder_id and has_creds)
    return {
        "configured": configured,
        "folder_id": folder_id if configured else "",
        "detail": "Google Drive pronto." if configured else "Google Drive não configurado para este criador.",
    }


@router.get("/drive-files")
async def portal_drive_files(request: Request):
    """List files in creator's Google Drive intake folder."""
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        from .. import main as main_mod
        cfg = await asyncio.to_thread(main_mod._google_drive_creator_config, creator_id)
        if not cfg.get("configured"):
            return JSONResponse({"detail": cfg.get("detail", "Drive não configurado"), "files": []}, status_code=400)
        raw_creds = cfg["_raw_service_account"]
        folder_id = cfg["folder_id"]
        payload = await asyncio.to_thread(
            main_mod._google_drive_list_folder_sync,
            folder_id=folder_id,
            raw_creds=raw_creds,
            page_size=50,
        )
        return {"files": payload.get("files", []), "total": payload.get("total", 0)}
    except Exception as exc:
        return JSONResponse({"detail": str(exc), "files": []}, status_code=502)


@router.post("/drive-import")
async def portal_drive_import(request: Request):
    """Import a file from creator's Google Drive into AutoEditor queue."""
    creator_id = _portal_auth(request)
    if not creator_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    drive_file_id = str(body.get("drive_file_id") or "").strip()
    filename = str(body.get("filename") or "video.mp4").strip()
    title_hint = str(body.get("title_hint") or filename).strip()
    target_duration_minutes = max(1, min(int(body.get("target_duration_minutes") or 40), 240))

    if not drive_file_id:
        return JSONResponse({"detail": "drive_file_id is required"}, status_code=422)

    try:
        from .. import main as main_mod
        from ..db import async_job_put
        from ..services.auto_editor_pipeline import ASYNC_KIND, run_auto_editor_job

        cfg = await asyncio.to_thread(main_mod._google_drive_creator_config, creator_id)
        if not cfg.get("configured"):
            return JSONResponse({"detail": cfg.get("detail", "Drive não configurado")}, status_code=400)

        raw_creds = cfg["_raw_service_account"]

        # Download file from Drive to temp, then store
        with tempfile.TemporaryDirectory(prefix="portal-drive-", dir=main_mod._preferred_tmpdir_root("portal")) as td:
            tmp_path = os.path.join(td, filename)
            await asyncio.to_thread(
                main_mod._google_drive_download_file_sync,
                file_id=drive_file_id,
                dest_path=tmp_path,
                raw_creds=raw_creds,
            )
            stored = await asyncio.to_thread(
                main_mod._store_local_path,
                src_path=tmp_path,
                prefix=f"uploads/portal/{creator_id}",
                filename=filename,
                content_type="video/mp4",
            )

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async_job_put(
            kind=ASYNC_KIND,
            job_id=job_id,
            payload={
                "kind": ASYNC_KIND,
                "job_id": job_id,
                "status": "pending",
                "detail": "Importado do Google Drive; AutoEditor na fila…",
                "progress_pct": 0,
                "creator_id": creator_id,
                "source_video_key": stored.get("object_key", ""),
                "request": {
                    "creator_id": creator_id,
                    "video_object_key": stored.get("object_key", ""),
                    "title_hint": title_hint,
                    "target_duration_minutes": target_duration_minutes,
                },
                "created_at": now,
                "updated_at": now,
            },
        )
        asyncio.create_task(run_auto_editor_job(job_id))
        return {"ok": True, "job_id": job_id, "filename": filename}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)
