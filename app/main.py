from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import textwrap
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import httpx
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .db import (
    init_db, insert_run, list_runs, get_run, delete_run, settings_get, settings_list, settings_set,
    insert_scheduled_post, list_scheduled_posts, update_scheduled_post_status,
    update_scheduled_post_sent, delete_scheduled_post, list_scheduled_posts_for_run,
    delete_scheduled_posts_for_run, list_scheduled_posts_due,
    update_run_request_field, update_run_result_sources, replace_media_ref_in_runs,
    multipart_create, multipart_get, multipart_add_part, multipart_delete, multipart_purge_old,
    async_job_get, async_job_put, async_job_merge, async_job_list, async_jobs_fail_incomplete,
    list_async_jobs_for_run, delete_async_jobs_for_run,
    upload_meta_set, upload_meta_get, upload_meta_get_many, upload_meta_delete_many,
    media_ref_used_by_other_runs,
)
from .xvideos_source import fetch_top_videos, fetch_search_videos, fetch_pornstar_videos, fetch_channel_videos
from .llm import ProviderSpec, merge_streams, run_providers_to_completion, _OLLAMA_BASE_URL

# ── Agency modules ─────────────────────────────────────────────────────────
from .db_agency import init_agency_db, creator_get
from .db_companies import init_companies_db
from .routers.creators import router as creators_router
from .routers.auto_editor import router as auto_editor_router
from .routers.publisher import router as publisher_router
from .routers.portal import router as portal_router
from .routers.trends import router as trends_router
from .routers.dmca import router as dmca_router
from .routers.calendar_router import router as calendar_router
from .routers.financial import router as financial_router
from .routers.auth import router as auth_router, verify_session_token
from .routers.video_enhancer import router as video_enhancer_router
from .routers.companies import router as companies_router
from .routers.posts import router as posts_router
from .routers.ai_settings import router as ai_settings_router
from .routers.social import router as social_router
from .routers.notify import router as notify_router
from .routers.billing import router as billing_router
from .routers.template_video import router as template_video_router

from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect

app = FastAPI(title="Adult Meta (internal)", version="1.27.103")


@app.middleware("http")
async def _tenant_scope_guard(request, call_next):
    """TENANCY (Marco A): usuário amarrado a uma empresa só acessa a própria empresa e nunca
    os recursos administrativos da agência. Super-admin/staff (sem company_id no token) = sem restrição."""
    try:
        from .main_utils import scoped_company_ids
        _scids = scoped_company_ids(request)
    except Exception:
        _scids = None
    if _scids is not None:
        import re as _re
        p = request.url.path
        m = _re.match(r"^/api/companies/([^/]+)", p)
        if m and m.group(1) not in _scids:
            from fastapi.responses import JSONResponse as _JR
            return _JR({"detail": "Acesso negado a esta empresa.", "error": "company_scope"}, status_code=403)
        _BLOCKED = ("/auth/users", "/auth/logs", "/api/creators", "/api/dmca", "/api/trends",
                    "/api/financial", "/settings/tokens", "/api/ai-settings", "/api/billing/credits",
                    "/api/billing/features", "/runs", "/analyze", "/api/autoeditor", "/api/enhancer")
        if any(p == b or p.startswith(b + "/") or p.startswith(b + "?") for b in _BLOCKED):
            from fastapi.responses import JSONResponse as _JR
            return _JR({"detail": "Recurso restrito ao administrador.", "error": "admin_only"}, status_code=403)
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheHtmlMiddleware:
    """Force no-cache on UI assets without wrapping request upload streams."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""

        async def send_with_no_cache(message):
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                ct = headers.get("content-type", "")
                if "text/html" in ct or path.startswith("/ui/"):
                    headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
            await send(message)

        await self.app(scope, receive, send_with_no_cache)


app.add_middleware(NoCacheHtmlMiddleware)

# ── Agency routers ─────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(creators_router)
app.include_router(auto_editor_router)
app.include_router(publisher_router)
app.include_router(portal_router)
app.include_router(trends_router)
app.include_router(dmca_router)
app.include_router(calendar_router)
app.include_router(financial_router)
app.include_router(video_enhancer_router)
app.include_router(companies_router)
app.include_router(posts_router)
app.include_router(ai_settings_router)
app.include_router(social_router)
app.include_router(notify_router)
app.include_router(billing_router)
app.include_router(template_video_router)

API_KEY = os.environ.get("ADULT_META_API_KEY")
# Fail-closed: if the API key is ever absent (e.g. a stack redeploy that omits
# the env), do NOT silently reopen the API. Open access requires an explicit
# opt-in for local dev. Valid browser sessions always pass regardless of this.
ALLOW_OPEN_ACCESS = os.environ.get("ALLOW_OPEN_ACCESS", "").strip().lower() in ("1", "true", "yes", "on")

# MinIO / S3-compatible storage (for direct browser uploads)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "https://s3.n8nmikael.com.br")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
S3_BUCKET = os.environ.get("S3_BUCKET", "metaporn")
S3_PUBLIC_BASE_URL = os.environ.get("S3_PUBLIC_BASE_URL", "https://s3.n8nmikael.com.br")
S3_SINGLE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024 * 1024

SUPPORTED_PROVIDER_NAMES = {"openai", "deepseek", "ollama", "openrouter", "grok", "gemini"}
OBJECT_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/\-]{0,511}$")
LOCAL_MEDIA_ROOT = (
    os.environ.get("ADULT_META_MEDIA_ROOT", "").strip()
    or ("/media" if os.path.isdir("/media") else os.path.join(os.path.dirname(os.environ.get("ADULT_META_DB_PATH", "/data/runs.db")), "media"))
)
LOCAL_MEDIA_TMP_ROOT = (
    os.environ.get("ADULT_META_MEDIA_TMP_ROOT", "").strip()
    or os.path.join(LOCAL_MEDIA_ROOT, "_tmp")
)
try:
    TMP_CLEANUP_MAX_AGE_HOURS = max(1, min(int(os.environ.get("ADULT_META_TMP_CLEANUP_MAX_AGE_HOURS", "18").strip()), 24 * 30))
except Exception:
    TMP_CLEANUP_MAX_AGE_HOURS = 18
LOCAL_MEDIA_PREFIX = "local:"
LOCAL_MEDIA_REL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/\-]{0,1023}$")
LOGO_PROFILE_SETTINGS_KEY = "wizard:logo_profiles"
LOGO_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
MAX_LOGO_OVERLAYS = 6
GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY = "google_drive:service_account_json"
GOOGLE_DRIVE_FOLDER_SETTINGS_KEY = "google_drive:folder_id"
LOCAL_MEDIA_URL_SECRET = (
    os.environ.get("ADULT_META_MEDIA_URL_SECRET", "").strip()
    or API_KEY
    or "adult-meta-local-media"
)

# In-memory store for background burn-subtitles jobs (keyed by job_id)
_burn_jobs: Dict[str, Dict] = {}
_burn_max_parallel_raw = os.environ.get("BURN_MAX_PARALLEL", "1").strip()
try:
    _burn_max_parallel = max(1, int(_burn_max_parallel_raw))
except Exception:
    _burn_max_parallel = 1
_burn_worker_semaphore = asyncio.Semaphore(_burn_max_parallel)
_burn_queue_order: List[str] = []
_burn_controls: Dict[str, Dict[str, Any]] = {}
_burn_state_lock = threading.Lock()
_preview_locks: Dict[str, asyncio.Lock] = {}
_preview_state_lock = threading.Lock()
_media_probe_cache: Dict[str, Dict[str, Any]] = {}
_media_probe_cache_lock = threading.Lock()
_ASYNC_JOB_KIND_BURN = "burn"
_ASYNC_JOB_KIND_TEASER = "teaser"
_ASYNC_JOB_KIND_DRIVE_UPLOAD = "drive_upload"
_ASYNC_JOB_KIND_DRIVE_IMPORT = "drive_import"
_ASYNC_JOB_KIND_ANALYZE = "analyze"
TEASER_MAX_NUM_CLIPS = 20

_analyze_job_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_analyze_job", default=None)


def _emit_analyze_progress(pct: int, detail: str) -> None:
    job_id = _analyze_job_ctx.get()
    if not job_id:
        return
    async_job_merge(kind=_ASYNC_JOB_KIND_ANALYZE, job_id=job_id, patch={
        "status": "running", "progress_pct": pct, "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
TEASER_MAX_SCENE_DURATION_SEC = 720.0
TEASER_MAX_TOTAL_DURATION_SEC = 1800.0


def _burn_enqueue(job_id: str) -> None:
    with _burn_state_lock:
        if job_id not in _burn_queue_order:
            _burn_queue_order.append(job_id)


def _preferred_tmpdir_root(kind: str = "") -> Optional[str]:
    base = LOCAL_MEDIA_TMP_ROOT.strip() if isinstance(LOCAL_MEDIA_TMP_ROOT, str) else ""
    if not base:
        return None
    target = os.path.join(base, kind) if kind else base
    try:
        os.makedirs(target, exist_ok=True)
        return target
    except Exception:
        return None


def _configure_process_tmpdir() -> Optional[str]:
    target = _preferred_tmpdir_root("system")
    if not target:
        return None
    try:
        os.makedirs(target, exist_ok=True)
        for env_name in ("TMPDIR", "TEMP", "TMP"):
            os.environ[env_name] = target
        tempfile.tempdir = target
        return target
    except Exception:
        return None


def _cleanup_stale_tmp_entries(
    max_age_hours: int = TMP_CLEANUP_MAX_AGE_HOURS,
    *,
    remove_all: bool = False,
) -> int:
    root = _preferred_tmpdir_root()
    if not root or not os.path.isdir(root):
        return 0
    cutoff_ts = time.time() - (max(1, int(max_age_hours or TMP_CLEANUP_MAX_AGE_HOURS)) * 3600)

    def _purge_if_stale(path: str) -> int:
        try:
            st = os.stat(path)
        except Exception:
            return 0
        if not remove_all and st.st_mtime >= cutoff_ts:
            return 0
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return 1
        except Exception:
            return 0

    removed = 0
    try:
        first_level = os.listdir(root)
    except Exception:
        return 0
    for name in first_level:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            removed += _purge_if_stale(path)
            continue
        try:
            for child in os.listdir(path):
                removed += _purge_if_stale(os.path.join(path, child))
        except Exception:
            removed += _purge_if_stale(path)
    return removed


_RUNTIME_TMPDIR = _configure_process_tmpdir()


def _burn_dequeue(job_id: str) -> None:
    with _burn_state_lock:
        try:
            _burn_queue_order.remove(job_id)
        except ValueError:
            pass


def _burn_queue_info(job_id: str) -> tuple[Optional[int], int]:
    with _burn_state_lock:
        total = len(_burn_queue_order)
        if job_id not in _burn_queue_order:
            return None, total
        return _burn_queue_order.index(job_id) + 1, total


def _burn_queue_snapshot() -> List[str]:
    with _burn_state_lock:
        return list(_burn_queue_order)


def _burn_control(job_id: str) -> Dict[str, Any]:
    with _burn_state_lock:
        c = _burn_controls.get(job_id)
        if c is None:
            c = {"cancel_requested": False, "proc": None}
            _burn_controls[job_id] = c
        return c


def _burn_set_proc(job_id: str, proc: Any) -> None:
    with _burn_state_lock:
        c = _burn_controls.get(job_id)
        if c is None:
            c = {"cancel_requested": False, "proc": None}
            _burn_controls[job_id] = c
        c["proc"] = proc


def _burn_get_proc(job_id: str) -> Any:
    with _burn_state_lock:
        c = _burn_controls.get(job_id) or {}
        return c.get("proc")


def _burn_request_cancel(job_id: str) -> Any:
    with _burn_state_lock:
        c = _burn_controls.get(job_id)
        if c is None:
            c = {"cancel_requested": False, "proc": None}
            _burn_controls[job_id] = c
        c["cancel_requested"] = True
        proc = c.get("proc")
    try:
        async_job_merge(kind=_ASYNC_JOB_KIND_BURN, job_id=job_id, patch={"cancel_requested": True})
    except Exception:
        pass
    return proc


def _burn_cancel_requested(job_id: str) -> bool:
    with _burn_state_lock:
        c = _burn_controls.get(job_id) or {}
        if bool(c.get("cancel_requested")):
            return True
    try:
        remote = async_job_get(kind=_ASYNC_JOB_KIND_BURN, job_id=job_id) or {}
    except Exception:
        remote = {}
    return bool(remote.get("cancel_requested"))


def _shared_job_get(kind: str, job_id: str, *, local_store: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    local = None
    if local_store is not None:
        raw_local = local_store.get(job_id)
        if isinstance(raw_local, dict):
            local = dict(raw_local)
    try:
        remote = async_job_get(kind=kind, job_id=job_id)
    except Exception:
        remote = None

    if remote:
        remote_status = str(remote.get("status") or "").lower()
        local_status = str((local or {}).get("status") or "").lower()
        remote_updated = str(remote.get("updated_at") or "")
        local_updated = str((local or {}).get("updated_at") or "")
        if (
            not local
            or (remote_status in {"done", "error", "cancelled"} and local_status not in {"done", "error", "cancelled"})
            or (remote_updated and local_updated and remote_updated > local_updated)
        ):
            if local_store is not None:
                local_store[job_id] = dict(remote)
            return dict(remote)
    if local:
        return local
    if remote:
        return dict(remote)
    return None


def _shared_job_put(
    kind: str,
    job_id: str,
    payload: Dict[str, Any],
    *,
    local_store: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    stored = async_job_put(kind=kind, job_id=job_id, payload=payload)
    if local_store is not None:
        local_store[job_id] = dict(stored)
    return stored


def _shared_job_patch(
    kind: str,
    job_id: str,
    patch: Dict[str, Any],
    *,
    local_store: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    stored = async_job_merge(kind=kind, job_id=job_id, patch=patch)
    if local_store is not None:
        local_store[job_id] = dict(stored)
    return stored


def _burn_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    return _shared_job_get(_ASYNC_JOB_KIND_BURN, job_id, local_store=_burn_jobs)


def _burn_job_put(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_put(_ASYNC_JOB_KIND_BURN, job_id, payload, local_store=_burn_jobs)


def _burn_job_patch(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_patch(_ASYNC_JOB_KIND_BURN, job_id, patch, local_store=_burn_jobs)


def _teaser_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    return _shared_job_get(_ASYNC_JOB_KIND_TEASER, job_id, local_store=_teaser_jobs)


def _teaser_job_put(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_put(_ASYNC_JOB_KIND_TEASER, job_id, payload, local_store=_teaser_jobs)


def _teaser_job_patch(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_patch(_ASYNC_JOB_KIND_TEASER, job_id, patch, local_store=_teaser_jobs)


def _drive_upload_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    return _shared_job_get(_ASYNC_JOB_KIND_DRIVE_UPLOAD, job_id, local_store=_drive_upload_jobs)


def _drive_upload_job_put(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_put(_ASYNC_JOB_KIND_DRIVE_UPLOAD, job_id, payload, local_store=_drive_upload_jobs)


def _drive_upload_job_patch(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_patch(_ASYNC_JOB_KIND_DRIVE_UPLOAD, job_id, patch, local_store=_drive_upload_jobs)


def _drive_import_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    return _shared_job_get(_ASYNC_JOB_KIND_DRIVE_IMPORT, job_id, local_store=_drive_import_jobs)


def _drive_import_job_put(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_put(_ASYNC_JOB_KIND_DRIVE_IMPORT, job_id, payload, local_store=_drive_import_jobs)


def _drive_import_job_patch(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return _shared_job_patch(_ASYNC_JOB_KIND_DRIVE_IMPORT, job_id, patch, local_store=_drive_import_jobs)


def _safe_json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _media_manager_category(value: str) -> str:
    rel = _media_ref_relative_path(value)
    top = rel.split("/", 1)[0].lower()
    if top == "burns":
        return "burns"
    if top == "teasers":
        return "teasers"
    return "uploads"


def _parse_google_drive_service_account(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("service_account_json_invalid")
    required = {"client_email", "private_key", "token_uri"}
    missing = [key for key in required if not str(parsed.get(key) or "").strip()]
    if missing:
        raise ValueError(f"service_account_missing_fields:{','.join(missing)}")
    return parsed


def _google_drive_config_status() -> Dict[str, Any]:
    folder_value = (settings_get(key=GOOGLE_DRIVE_FOLDER_SETTINGS_KEY) or {}).get("value") or ""
    creds_value = (settings_get(key=GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY) or {}).get("value") or ""
    folder_id = str(folder_value or "").strip()
    service_account = {}
    parse_error = ""
    if str(creds_value or "").strip():
        try:
            service_account = _parse_google_drive_service_account(str(creds_value or ""))
        except Exception as exc:
            parse_error = _safe_error_detail(exc, "google_drive_service_account_invalid")
    return {
        "ok": True,
        "folder_id": folder_id,
        "has_credentials": bool(str(creds_value or "").strip()),
        "configured": bool(folder_id and service_account),
        "service_account_email": str(service_account.get("client_email") or "").strip(),
        "detail": parse_error or ("Google Drive configurado." if folder_id and service_account else "Configure pasta e credenciais do Google Drive."),
    }


def _google_drive_creator_config(creator_id: str = "") -> Dict[str, Any]:
    safe_creator_id = str(creator_id or "").strip()
    global_folder = str((settings_get(key=GOOGLE_DRIVE_FOLDER_SETTINGS_KEY) or {}).get("value") or "").strip()
    global_creds = str((settings_get(key=GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY) or {}).get("value") or "")
    creator = creator_get(safe_creator_id) if safe_creator_id else None
    creator_folder = str((creator or {}).get("drive_folder_id") or "").strip()
    creator_creds = str((creator or {}).get("drive_service_account") or "")

    folder_id = creator_folder or global_folder
    raw_creds = creator_creds or global_creds
    folder_source = "creator" if creator_folder else ("global" if global_folder else "")
    credentials_source = "creator" if creator_creds else ("global" if global_creds else "")
    service_account = {}
    parse_error = ""
    if str(raw_creds or "").strip():
        try:
            service_account = _parse_google_drive_service_account(str(raw_creds or ""))
        except Exception as exc:
            parse_error = _safe_error_detail(exc, "google_drive_service_account_invalid")
    if safe_creator_id and not creator:
        detail = "Criador não encontrado."
    elif parse_error:
        detail = parse_error
    elif folder_id and service_account:
        detail = "Google Drive pronto para recebimento."
    elif not folder_id:
        detail = "Defina a pasta do Google Drive do criador ou a pasta global."
    else:
        detail = "Defina as credenciais do Google Drive do criador ou a service account global."

    return {
        "ok": True,
        "creator_id": safe_creator_id,
        "creator_name": str((creator or {}).get("name") or "").strip(),
        "folder_id": folder_id,
        "folder_source": folder_source,
        "credentials_source": credentials_source,
        "has_credentials": bool(str(raw_creds or "").strip()),
        "configured": bool(folder_id and service_account),
        "service_account_email": str(service_account.get("client_email") or "").strip(),
        "detail": detail,
        "_raw_service_account": raw_creds,
    }


def _google_drive_service_from_raw(raw_creds: str):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds_info = _parse_google_drive_service_account(str(raw_creds or ""))
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _google_drive_list_folder_sync(
    *,
    folder_id: str,
    raw_creds: str,
    page_size: int = 100,
) -> Dict[str, Any]:
    service = _google_drive_service_from_raw(raw_creds)
    safe_folder_id = str(folder_id or "").strip()
    safe_page_size = max(1, min(int(page_size or 100), 200))
    query = f"'{safe_folder_id}' in parents and trashed = false"
    files: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        payload = service.files().list(
            q=query,
            orderBy="modifiedTime desc,name",
            pageSize=min(safe_page_size, max(1, safe_page_size - len(files))),
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields=(
                "nextPageToken,"
                "files(id,name,size,mimeType,modifiedTime,createdTime,webViewLink,webContentLink,"
                "md5Checksum,parents,videoMediaMetadata(durationMillis,width,height))"
            ),
        ).execute()
        for item in payload.get("files", []) or []:
            mime_type = str(item.get("mimeType") or "").strip()
            files.append({
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "size_bytes": int(item.get("size") or 0),
                "size_mb": round((int(item.get("size") or 0) / 1024 / 1024), 1) if item.get("size") else 0,
                "mime_type": mime_type,
                "modified_time": str(item.get("modifiedTime") or "").strip(),
                "created_time": str(item.get("createdTime") or "").strip(),
                "web_view_link": str(item.get("webViewLink") or "").strip(),
                "download_link": str(item.get("webContentLink") or "").strip(),
                "md5_checksum": str(item.get("md5Checksum") or "").strip(),
                "is_folder": mime_type == "application/vnd.google-apps.folder",
                "video_meta": item.get("videoMediaMetadata") or {},
            })
            if len(files) >= safe_page_size:
                break
        if len(files) >= safe_page_size:
            break
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return {
        "ok": True,
        "items": files[:safe_page_size],
        "count": len(files[:safe_page_size]),
    }


def _google_drive_file_metadata_sync(*, file_id: str, raw_creds: str) -> Dict[str, Any]:
    service = _google_drive_service_from_raw(raw_creds)
    payload = service.files().get(
        fileId=str(file_id or "").strip(),
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="id,name,size,mimeType,modifiedTime,createdTime,webViewLink,webContentLink,md5Checksum",
    ).execute()
    return {
        "id": str(payload.get("id") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "size_bytes": int(payload.get("size") or 0),
        "mime_type": str(payload.get("mimeType") or "").strip(),
        "modified_time": str(payload.get("modifiedTime") or "").strip(),
        "created_time": str(payload.get("createdTime") or "").strip(),
        "web_view_link": str(payload.get("webViewLink") or "").strip(),
        "download_link": str(payload.get("webContentLink") or "").strip(),
        "md5_checksum": str(payload.get("md5Checksum") or "").strip(),
    }


def _google_drive_download_file_sync(
    *,
    file_id: str,
    out_path: str,
    raw_creds: str,
    progress_cb: Optional[Any] = None,
) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    service = _google_drive_service_from_raw(raw_creds)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    request = service.files().get_media(fileId=str(file_id or "").strip(), supportsAllDrives=True)
    with open(out_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status is not None and callable(progress_cb):
                try:
                    progress_cb(max(0.0, min(float(status.progress() or 0.0), 1.0)))
                except Exception:
                    pass


def _parse_data_url(raw: str) -> tuple[str, str]:
    """Return (mime, base64_payload). Accepts raw base64 as fallback."""
    txt = str(raw or "").strip()
    if not txt:
        return "", ""
    if txt.startswith("data:"):
        try:
            head, payload = txt.split(",", 1)
        except ValueError:
            return "", ""
        mime = ""
        m = re.match(r"^data:([^;]+);base64$", head.strip(), flags=re.IGNORECASE)
        if m:
            mime = (m.group(1) or "").strip().lower()
        return mime, payload.strip()
    return "", txt


def _logo_ext_from_mime(mime: str) -> str:
    mm = (mime or "").strip().lower()
    if mm in {"image/png"}:
        return ".png"
    if mm in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if mm in {"image/webp"}:
        return ".webp"
    if mm in {"image/gif"}:
        return ".gif"
    if mm in {"image/svg+xml"}:
        return ".svg"
    return ".png"


def _normalize_hex_color(value: str, default: str = "#ffffff") -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if raw.startswith("#"):
        raw = raw[1:]
    if re.fullmatch(r"[0-9a-f]{6}", raw):
        return f"#{raw}"
    return default


def _merge_run_wizard_state(run_id: str, patch: Dict[str, Any]) -> bool:
    """Merge `patch` into request_json.wizard_state for the given run."""
    if not run_id or not isinstance(patch, dict):
        return False
    row = get_run(run_id)
    if not row:
        return False
    req_data = _safe_json_obj(row.get("request_json"))
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    ws_profile_id = str(wizard_state.get("logo_profile_id") or "").strip()
    ws_profile_name = str(wizard_state.get("logo_profile_name") or "").strip()
    ws_layout_linked = _coerce_optional_bool(wizard_state.get("logo_profile_layout_linked"))
    if ws_layout_linked is None and (ws_profile_id or ws_profile_name):
        linked_profile = _find_logo_profile(profile_id=ws_profile_id, company_name=ws_profile_name)
        if linked_profile:
            _merge_run_wizard_state(
                run_id,
                {
                    "logo_x": float(linked_profile.get("logo_x") or 97.0),
                    "logo_y": float(linked_profile.get("logo_y") or 97.0),
                    "logo_scale_pct": float(linked_profile.get("logo_scale_pct") or 20.0),
                    "logo_opacity": float(linked_profile.get("logo_opacity") or 85.0),
                    "logo_profile_layout_linked": True,
                },
            )
            req_data = _safe_json_obj(get_run(run_id).get("request_json"))
    wizard_state = req_data.get("wizard_state")
    if not isinstance(wizard_state, dict):
        wizard_state = {}

    for k, v in patch.items():
        if v is None:
            wizard_state.pop(k, None)
        else:
            wizard_state[k] = v
    wizard_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    return update_run_request_field(run_id=run_id, field="wizard_state", value=wizard_state)


def _default_logo_preset() -> Dict[str, Any]:
    return {
        "name": "Padrao salvo",
        "logo_x": 97.0,
        "logo_y": 97.0,
        "logo_scale_pct": 20.0,
        "logo_opacity": 85.0,
    }


def _normalize_logo_preset(value: Dict[str, Any]) -> Dict[str, Any]:
    base = _default_logo_preset()
    src = value if isinstance(value, dict) else {}

    def _num(key: str, default: float, min_v: float, max_v: float) -> float:
        try:
            v = float(src.get(key, default))
        except Exception:
            v = default
        return max(min_v, min(max_v, v))

    name = str(src.get("name") or base["name"]).strip()[:64] or base["name"]
    return {
        "name": name,
        "logo_x": _num("logo_x", float(base["logo_x"]), 0.0, 100.0),
        "logo_y": _num("logo_y", float(base["logo_y"]), 0.0, 100.0),
        "logo_scale_pct": _num("logo_scale_pct", float(base["logo_scale_pct"]), 5.0, 100.0),
        "logo_opacity": _num("logo_opacity", float(base["logo_opacity"]), 5.0, 100.0),
    }


def _slugify_logo_profile_id(value: str, fallback: str = "empresa") -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    raw = raw.strip("-._")
    raw = raw[:80]
    if raw and LOGO_PROFILE_ID_RE.fullmatch(raw):
        return raw
    seed = re.sub(r"[^a-z0-9]+", "-", str(fallback or "").strip().lower()).strip("-._")[:48]
    if not seed:
        seed = "empresa"
    return f"{seed}-{uuid.uuid4().hex[:8]}"


def _normalize_logo_profile_id(value: Any, fallback_name: str) -> str:
    raw = str(value or "").strip().lower()
    if raw and LOGO_PROFILE_ID_RE.fullmatch(raw):
        return raw
    return _slugify_logo_profile_id(fallback_name, fallback="empresa")


def _logo_profile_name_key(value: str) -> str:
    return _slugify_logo_profile_id(value, fallback="empresa")


def _normalize_logo_profile_logo_entry(value: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    fb = fallback if isinstance(fallback, dict) else {}
    logo_ref = str(value.get("logo_object_key") or value.get("object_key") or fb.get("logo_object_key") or "").strip()
    if not logo_ref:
        return None
    logo_name = _safe_storage_filename(
        str(value.get("logo_name") or value.get("name") or fb.get("logo_name") or "logo.png").strip(),
        "logo.png",
    )
    try:
        x = max(0.0, min(float(value.get("x", value.get("logo_x", fb.get("logo_x", 97.0)))), 100.0))
    except Exception:
        x = 97.0
    try:
        y = max(0.0, min(float(value.get("y", value.get("logo_y", fb.get("logo_y", 97.0)))), 100.0))
    except Exception:
        y = 97.0
    try:
        scale_pct = max(5.0, min(float(value.get("scale_pct", value.get("logo_scale_pct", fb.get("logo_scale_pct", 20.0)))), 100.0))
    except Exception:
        scale_pct = 20.0
    try:
        opacity = max(5.0, min(float(value.get("opacity", value.get("logo_opacity", fb.get("logo_opacity", 85.0)))), 100.0))
    except Exception:
        opacity = 85.0
    return {
        "id": str(value.get("id") or fb.get("id") or uuid.uuid4()).strip(),
        "logo_name": logo_name,
        "logo_object_key": logo_ref,
        "x": x,
        "y": y,
        "scale_pct": scale_pct,
        "opacity": opacity,
        "enabled": value.get("enabled", fb.get("enabled", True)) is not False,
    }


def _normalize_logo_profile_entry(value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    company_name = str(value.get("company_name") or value.get("name") or "").strip()[:80]
    if not company_name:
        return None
    preset = _normalize_logo_preset(value)
    logo_object_key = str(value.get("logo_object_key") or "").strip()
    logo_name = _safe_storage_filename(str(value.get("logo_name") or f"{company_name}.png").strip(), "logo.png")
    created_at = str(value.get("created_at") or "").strip()
    updated_at = str(value.get("updated_at") or "").strip()
    logos: List[Dict[str, Any]] = []
    raw_logos = value.get("logos")
    if isinstance(raw_logos, list):
        for raw_logo in raw_logos[:MAX_LOGO_OVERLAYS]:
            normalized_logo = _normalize_logo_profile_logo_entry(raw_logo)
            if normalized_logo:
                logos.append(normalized_logo)
    if not logos and logo_object_key:
        legacy_logo = _normalize_logo_profile_logo_entry({
            "id": "primary",
            "logo_name": logo_name,
            "logo_object_key": logo_object_key,
            "x": preset["logo_x"],
            "y": preset["logo_y"],
            "scale_pct": preset["logo_scale_pct"],
            "opacity": preset["logo_opacity"],
            "enabled": True,
        })
        if legacy_logo:
            logos.append(legacy_logo)
    if logos:
        first_logo = logos[0]
        logo_object_key = str(first_logo.get("logo_object_key") or logo_object_key)
        logo_name = str(first_logo.get("logo_name") or logo_name)
        preset["logo_x"] = float(first_logo.get("x") or preset["logo_x"])
        preset["logo_y"] = float(first_logo.get("y") or preset["logo_y"])
        preset["logo_scale_pct"] = float(first_logo.get("scale_pct") or preset["logo_scale_pct"])
        preset["logo_opacity"] = float(first_logo.get("opacity") or preset["logo_opacity"])
    return {
        "id": _normalize_logo_profile_id(value.get("id"), company_name),
        "company_name": company_name,
        "logo_name": logo_name,
        "logo_object_key": logo_object_key,
        "logos": logos[:MAX_LOGO_OVERLAYS],
        "logo_x": preset["logo_x"],
        "logo_y": preset["logo_y"],
        "logo_scale_pct": preset["logo_scale_pct"],
        "logo_opacity": preset["logo_opacity"],
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _load_logo_profiles_state() -> tuple[List[Dict[str, Any]], Optional[str]]:
    saved = settings_get(key=LOGO_PROFILE_SETTINGS_KEY)
    updated_at = saved.get("updated_at") if saved else None
    if not saved:
        return [], updated_at
    try:
        raw = json.loads(saved.get("value") or "[]")
    except Exception:
        raw = []
    profiles: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        normalized = _normalize_logo_profile_entry(item)
        if not normalized:
            continue
        pid = normalized["id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        profiles.append(normalized)
    profiles.sort(key=lambda p: (str(p.get("company_name") or "").lower(), str(p.get("id") or "")))
    return profiles, updated_at


def _save_logo_profiles_state(profiles: List[Dict[str, Any]], updated_at: Optional[str] = None) -> str:
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    normalized_items: List[Dict[str, Any]] = []
    for item in profiles or []:
        normalized = _normalize_logo_profile_entry(item)
        if not normalized:
            continue
        normalized["updated_at"] = str(item.get("updated_at") or normalized.get("updated_at") or now)
        normalized["created_at"] = str(item.get("created_at") or normalized.get("created_at") or now)
        normalized_items.append(normalized)
    normalized_items.sort(key=lambda p: (str(p.get("company_name") or "").lower(), str(p.get("id") or "")))
    settings_set(
        key=LOGO_PROFILE_SETTINGS_KEY,
        value=json.dumps(normalized_items, ensure_ascii=False),
        updated_at=now,
    )
    return now


def _media_ref_to_data_url(media_ref: str) -> str:
    if not media_ref or not _is_valid_object_key(media_ref):
        return ""
    if not _media_ref_exists(media_ref=media_ref, s3=_s3_client()):
        return ""
    rel = _media_ref_relative_path(media_ref)
    mime = _normalize_content_type(mimetypes.guess_type(rel)[0]) or "application/octet-stream"
    if _is_local_media_ref(media_ref):
        abs_path = _local_media_abs_path_from_ref(media_ref)
        return f"data:{mime};base64,{_file_to_base64(abs_path)}"
    with tempfile.TemporaryDirectory(prefix="logo-profile-read-", dir=_preferred_tmpdir_root("logo")) as tmpdir:
        ext = os.path.splitext(rel)[1] or ".bin"
        tmp_path = os.path.join(tmpdir, f"logo{ext}")
        _download_media_ref_to_file(media_ref=media_ref, out_path=tmp_path, s3=_s3_client())
        return f"data:{mime};base64,{_file_to_base64(tmp_path)}"


def _serialize_logo_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_logo_profile_entry(profile) or {}
    if not normalized:
        return {}
    logo_ref = str(normalized.get("logo_object_key") or "").strip()
    logo_available = bool(logo_ref and _is_valid_object_key(logo_ref) and _media_ref_exists(media_ref=logo_ref, s3=_s3_client()))
    out = dict(normalized)
    serialized_logos: List[Dict[str, Any]] = []
    for item in (normalized.get("logos") or [])[:MAX_LOGO_OVERLAYS]:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("logo_object_key") or "").strip()
        available = bool(ref and _is_valid_object_key(ref) and _media_ref_exists(media_ref=ref, s3=_s3_client()))
        payload = dict(item)
        payload["logo_available"] = available
        payload["logo_stream_url"] = _build_local_media_url(ref) if (available and _is_local_media_ref(ref)) else ""
        payload["logo_b64"] = _media_ref_to_data_url(ref) if available else ""
        payload["name"] = payload.get("logo_name") or "logo.png"
        serialized_logos.append(payload)
    out["logos"] = serialized_logos
    out["logo_available"] = logo_available
    out["logo_stream_url"] = _build_local_media_url(logo_ref) if (logo_available and _is_local_media_ref(logo_ref)) else ""
    out["logo_b64"] = _media_ref_to_data_url(logo_ref) if logo_available else ""
    return out


def _logo_profile_to_payload_logos(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = _normalize_logo_profile_entry(profile) or {}
    out: List[Dict[str, Any]] = []
    for item in (normalized.get("logos") or [])[:MAX_LOGO_OVERLAYS]:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        ref = str(item.get("logo_object_key") or "").strip()
        b64 = _media_ref_to_data_url(ref) if ref else ""
        if not b64:
            continue
        out.append({
            "b64": b64,
            "name": str(item.get("logo_name") or "logo.png"),
            "x": float(item.get("x") or 97.0),
            "y": float(item.get("y") or 97.0),
            "scale_pct": float(item.get("scale_pct") or 20.0),
            "opacity": float(item.get("opacity") or 85.0),
            "enabled": item.get("enabled", True) is not False,
        })
    return out[:MAX_LOGO_OVERLAYS]


def _logo_wide_scale_boost(width: int, height: int) -> float:
    # Width is the user's explicit size control. Do not auto-expand it for
    # ultra-wide logos, otherwise preview and burn stop matching.
    return 1.0


def _logo_wide_height_scale(width: int, height: int) -> float:
    # Never distort the logo artwork. Earlier versions tried to compensate
    # ultra-wide logos by stretching their height, but that made real burns
    # diverge from the saved logo design.
    return 1.0


def _prepare_logo_overlay_image(
    path: str,
    *,
    is_gif: bool = False,
    requested_scale_pct: float = 20.0,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "width": 0,
        "height": 0,
        "trimmed": False,
        "layout_canvas": False,
        "scale_boost": 1.0,
        "height_scale": 1.0,
    }
    if is_gif:
        return meta
    try:
        from PIL import Image

        with Image.open(path) as im:
            rgba = im.convert("RGBA")
            w, h = rgba.size
            bbox = rgba.getchannel("A").getbbox()
            if bbox:
                x0, y0, x1, y1 = bbox
                bw = max(1, x1 - x0)
                bh = max(1, y1 - y0)
                aspect = (float(w) / float(h)) if h else 0.0
                # Some company watermarks are intentionally authored as a full
                # 16:9 video canvas (for example 3840x2160 with a lower-third
                # logo already positioned inside it). Preserve those only when
                # the saved size also says "use it like a canvas" (near full
                # width). If a 3840x2160 PNG is saved at 15%-45%, treating the
                # whole transparent canvas as the logo makes the visible mark
                # almost disappear, which looks like "logo did not burn".
                try:
                    scale_hint = max(5.0, min(float(requested_scale_pct or 20.0), 100.0))
                except Exception:
                    scale_hint = 20.0
                preserve_layout_canvas = (
                    scale_hint >= 80.0
                    and
                    w >= 1280
                    and h >= 720
                    and 1.60 <= aspect <= 1.90
                    and bw >= 1
                    and bh >= 1
                    and (
                        x0 <= int(w * 0.08)
                        or y0 >= int(h * 0.35)
                        or x1 >= int(w * 0.92)
                        or y1 >= int(h * 0.92)
                    )
                )
                if preserve_layout_canvas:
                    meta["layout_canvas"] = True
                    meta["width"] = int(w)
                    meta["height"] = int(h)
                    meta["scale_boost"] = _logo_wide_scale_boost(int(w), int(h))
                    meta["height_scale"] = _logo_wide_height_scale(int(w), int(h))
                    return meta
                pad = max(2, int(max(bw, bh) * 0.015))
                crop = (
                    max(0, x0 - pad),
                    max(0, y0 - pad),
                    min(w, x1 + pad),
                    min(h, y1 + pad),
                )
                cw = max(1, crop[2] - crop[0])
                ch = max(1, crop[3] - crop[1])
                should_trim = cw < int(w * 0.97) or ch < int(h * 0.97)
                if should_trim:
                    rgba = rgba.crop(crop)
                    rgba.save(path)
                    w, h = rgba.size
                    meta["trimmed"] = True
            meta["width"] = int(w)
            meta["height"] = int(h)
            meta["scale_boost"] = _logo_wide_scale_boost(int(w), int(h))
            meta["height_scale"] = _logo_wide_height_scale(int(w), int(h))
    except Exception:
        pass
    return meta


def _write_logo_overlay_specs(
    *,
    raw_logos: Optional[List[Dict[str, Any]]],
    legacy_logo_b64: str,
    tmpdir: str,
    legacy_x: float = 97.0,
    legacy_y: float = 97.0,
    legacy_scale_pct: float = 20.0,
    legacy_opacity: float = 85.0,
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    candidates = raw_logos if isinstance(raw_logos, list) else []
    for raw_logo in candidates[:MAX_LOGO_OVERLAYS]:
        if not isinstance(raw_logo, dict):
            continue
        if raw_logo.get("enabled") is False:
            continue
        b64_raw = str(raw_logo.get("b64") or raw_logo.get("logo_b64") or raw_logo.get("src") or "").strip()
        if not b64_raw:
            continue
        try:
            mime, payload = _parse_data_url(b64_raw)
            if not payload:
                continue
            ext = _logo_ext_from_mime(mime)
            path = os.path.join(tmpdir, f"logo_{len(specs)}{ext}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(payload))
            is_gif = bool(mime == "image/gif" or path.lower().endswith(".gif"))
            scale_pct = max(5.0, min(float(raw_logo.get("scale_pct", raw_logo.get("logo_scale_pct", 20.0))), 100.0))
            logo_meta = _prepare_logo_overlay_image(path, is_gif=is_gif, requested_scale_pct=scale_pct)
            specs.append({
                "path": path,
                "is_gif": is_gif,
                "x": max(0.0, min(float(raw_logo.get("x", raw_logo.get("logo_x", 97.0))), 100.0)),
                "y": max(0.0, min(float(raw_logo.get("y", raw_logo.get("logo_y", 97.0))), 100.0)),
                "scale_pct": scale_pct,
                "opacity": max(5.0, min(float(raw_logo.get("opacity", raw_logo.get("logo_opacity", 85.0))), 100.0)),
                "width": int(logo_meta.get("width") or 0),
                "height": int(logo_meta.get("height") or 0),
                "trimmed": bool(logo_meta.get("trimmed")),
                "layout_canvas": bool(logo_meta.get("layout_canvas")),
                "scale_boost": max(1.0, min(float(logo_meta.get("scale_boost") or 1.0), 1.6)),
                "height_scale": max(1.0, min(float(logo_meta.get("height_scale") or 1.0), 1.6)),
                "remove_bg": bool(raw_logo.get("remove_bg")),
                "bg_key_color": _normalize_hex_color(raw_logo.get("bg_key_color") or "#ffffff", "#ffffff"),
                "bg_similarity": max(0.01, min(float(raw_logo.get("bg_similarity", 0.18)), 0.60)),
                "bg_blend": max(0.0, min(float(raw_logo.get("bg_blend", 0.08)), 0.40)),
            })
        except Exception:
            continue

    if not specs and legacy_logo_b64:
        try:
            mime, payload = _parse_data_url(legacy_logo_b64)
            if payload:
                ext = _logo_ext_from_mime(mime)
                path = os.path.join(tmpdir, f"logo_legacy{ext}")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(payload))
                is_gif = bool(mime == "image/gif" or path.lower().endswith(".gif"))
                legacy_scale = max(5.0, min(float(legacy_scale_pct or 20.0), 100.0))
                logo_meta = _prepare_logo_overlay_image(path, is_gif=is_gif, requested_scale_pct=legacy_scale)
                specs.append({
                    "path": path,
                    "is_gif": is_gif,
                    "x": max(0.0, min(float(legacy_x or 97.0), 100.0)),
                    "y": max(0.0, min(float(legacy_y or 97.0), 100.0)),
                    "scale_pct": legacy_scale,
                    "opacity": max(5.0, min(float(legacy_opacity or 85.0), 100.0)),
                    "width": int(logo_meta.get("width") or 0),
                    "height": int(logo_meta.get("height") or 0),
                    "trimmed": bool(logo_meta.get("trimmed")),
                    "layout_canvas": bool(logo_meta.get("layout_canvas")),
                    "scale_boost": max(1.0, min(float(logo_meta.get("scale_boost") or 1.0), 1.6)),
                    "height_scale": max(1.0, min(float(logo_meta.get("height_scale") or 1.0), 1.6)),
                    "remove_bg": False,
                    "bg_key_color": "#ffffff",
                    "bg_similarity": 0.18,
                    "bg_blend": 0.08,
                })
        except Exception:
            pass
    return specs[:MAX_LOGO_OVERLAYS]


def _probe_video_sar(in_path: str) -> float:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=sample_aspect_ratio",
             "-of", "default=noprint_wrappers=1:nokey=1", in_path],
            capture_output=True, text=True, timeout=15,
        )
        raw = proc.stdout.strip()
        if raw and ":" in raw:
            num, den = raw.split(":")
            return float(num) / float(den) if float(den) != 0 else 1.0
        return 1.0
    except Exception:
        return 1.0


def _append_logo_aspect_locked_scale(
    parts: List[str],
    *,
    input_idx: int,
    base_ref: str,
    logo_scaled_label: str,
    base_label: str,
    scale_ratio: float,
    tag: str,
    height_scale: float = 1.0,
    video_sar: float = 1.0,
) -> None:
    """Scale a logo by width while explicitly preserving its source aspect ratio."""
    safe_ratio = max(0.01, min(float(scale_ratio or 0.20), 1.0))
    safe_tag = re.sub(r"[^A-Za-z0-9_]", "_", str(tag or "logo"))
    norm_label = f"{safe_tag}_norm"
    width_expr = f"ref_w*{safe_ratio:.4f}"
    # In FFmpeg 7 scale2ref, ref_w/ref_h refer to the second input (the
    # video/base), while main_w/main_h refer to the first input (the logo).
    # Keep the user's width as a percent of the video, but derive height from
    # the logo's own aspect ratio. Using ih/iw here resolves to the video in
    # this filter and flattens wide logos into 16:9.
    safe_height_scale = max(0.2, min(float(height_scale or 1.0), 2.0))
    height_expr = f"{width_expr}*main_h/main_w"
    if abs(safe_height_scale - 1.0) > 0.001:
        height_expr = f"{height_expr}*{safe_height_scale:.6f}"
    parts.append(f"[{input_idx}:v]format=rgba,setsar=1[{norm_label}]")
    parts.append(
        f"[{norm_label}]{base_ref}"
        f"scale2ref=w={width_expr}:h={height_expr}:flags=lanczos"
        f"[{logo_scaled_label}][{base_label}]"
    )


def _logo_overlay_y_expr(y_pct: float, **kwargs) -> str:
    return f"(H-h)*{max(0.0, min(float(y_pct or 0.0), 100.0)):.4f}/100"


def _has_logo_layout_payload(body: Dict[str, Any]) -> bool:
    # Distinguish "user sent explicit layout" from backend defaults. Without
    # this, a request that only references a saved company profile can look
    # like a custom layout of 97/97/20 and accidentally shrink canvas logos.
    if not isinstance(body, dict):
        return False
    for key in ("logo_x", "logo_y", "logo_scale_pct", "logo_opacity"):
        if key in body and body.get(key) not in (None, ""):
            return True
    return False


def _find_logo_profile(*, profile_id: str = "", company_name: str = "") -> Optional[Dict[str, Any]]:
    safe_profile_id = str(profile_id or "").strip().lower()
    safe_company_key = _logo_profile_name_key(company_name) if str(company_name or "").strip() else ""
    profiles, _ = _load_logo_profiles_state()
    for item in profiles:
        item_id = str(item.get("id") or "").strip().lower()
        item_company = str(item.get("company_name") or "").strip()
        if safe_profile_id and item_id == safe_profile_id:
            return dict(item)
        if safe_company_key and _logo_profile_name_key(item_company) == safe_company_key:
            return dict(item)
    return None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "sim"}:
        return True
    if raw in {"0", "false", "no", "off", "nao", "não"}:
        return False
    return None


def _int_with_default(value: Any, default: int) -> int:
    if value is None:
        return int(default)
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _clamp_teaser_scene_duration(value: Any, default: float = 6.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = float(default)
    return max(1.0, min(n, TEASER_MAX_SCENE_DURATION_SEC))


def _estimate_requested_teaser_duration(
    num_clips: int,
    clip_duration: float,
    selected_frame_indexes: Optional[List[int]] = None,
    scene_durations_by_frame: Optional[Dict[int, float]] = None,
    ordered_scene_durations: Optional[List[float]] = None,
) -> float:
    safe_num_clips = max(0, int(num_clips or 0))
    safe_clip_duration = max(2.0, _clamp_teaser_scene_duration(clip_duration, 6.0))
    ordered = []
    if isinstance(ordered_scene_durations, list):
        for raw_v in ordered_scene_durations[: safe_num_clips or 0]:
            ordered.append(_clamp_teaser_scene_duration(raw_v, safe_clip_duration))
    if ordered:
        if len(ordered) < safe_num_clips:
            ordered.extend([safe_clip_duration] * (safe_num_clips - len(ordered)))
        return float(sum(ordered[:safe_num_clips]))
    remaining = safe_num_clips
    total = 0.0
    seen: set[int] = set()
    durations_map = scene_durations_by_frame if isinstance(scene_durations_by_frame, dict) else {}

    for raw_idx in (selected_frame_indexes or []):
        if remaining <= 0:
            break
        try:
            idx = int(raw_idx)
        except Exception:
            continue
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        total += _clamp_teaser_scene_duration(durations_map.get(idx, safe_clip_duration), safe_clip_duration)
        remaining -= 1

    if remaining > 0:
        total += remaining * safe_clip_duration
    return total

# Cache do modelo faster-whisper (carregado uma única vez na memória)
_local_whisper_model = None
_LOCAL_WHISPER_MODEL_SIZE = "small"  # 465MB, bom custo-benefício no CPU

# Modelo premium — cache separado, carregado sob demanda
_premium_whisper_model = None
_premium_whisper_model_name = ""
_LOCAL_WHISPER_PREMIUM_MODEL = os.environ.get("ADULT_META_PREMIUM_WHISPER_MODEL", "large-v3").strip() or "large-v3"

def _get_local_whisper():
    global _local_whisper_model
    if _local_whisper_model is None:
        from faster_whisper import WhisperModel
        db_path = os.environ.get("ADULT_META_DB_PATH", "/data/runs.db")
        model_dir = os.path.join(os.path.dirname(db_path), "models", "faster-whisper")
        os.makedirs(model_dir, exist_ok=True)
        _local_whisper_model = WhisperModel(
            _LOCAL_WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            download_root=model_dir,
        )
    return _local_whisper_model

def _transcribe_local(
    audio_path: str,
    language: str = "",
    *,
    strict: bool = True,
    include_vocalizations: bool = False,
    vad_filter: bool = True,
) -> Dict[str, Any]:
    model = _get_local_whisper()
    if strict:
        vad_parameters = {
            "min_speech_duration_ms": 300,
            "min_silence_duration_ms": 700,
            "speech_pad_ms": 160,
        }
    else:
        vad_parameters = {
            "min_speech_duration_ms": 150,
            "min_silence_duration_ms": 900,
            "speech_pad_ms": 350,
        }
    kwargs: Dict[str, Any] = {
        "beam_size": 1 if strict else 5,
        "temperature": 0.0,
        "task": "transcribe",
        "vad_filter": bool(vad_filter),
        "vad_parameters": vad_parameters,
        # Modo estrito: melhor retornar vazio do que transformar ruído em fala.
        "no_speech_threshold": 0.72 if strict else 0.86,
        "log_prob_threshold": -0.95 if strict else -1.25,
        "compression_ratio_threshold": 2.25 if strict else 2.8,
        "condition_on_previous_text": False,
        "initial_prompt": PORN_BR_WHISPER_INITIAL_PROMPT,
    }
    kwargs["language"] = _norm_lang_code(language) or "pt"
    if not vad_filter:
        kwargs.pop("vad_parameters", None)
        kwargs["no_speech_threshold"] = 0.92
        kwargs["log_prob_threshold"] = -1.85
        kwargs["compression_ratio_threshold"] = 3.25
    segments_gen, info = model.transcribe(audio_path, **kwargs)
    segments = []
    for s in segments_gen:
        text = s.text.strip()
        if not text:
            continue
        no_speech_prob = getattr(s, "no_speech_prob", None)
        avg_logprob = getattr(s, "avg_logprob", None)
        compression_ratio = getattr(s, "compression_ratio", None)
        if strict and vad_filter and no_speech_prob is not None and no_speech_prob > 0.82:
            continue
        if not strict and vad_filter and no_speech_prob is not None and no_speech_prob > 0.94:
            continue
        if strict and avg_logprob is not None and avg_logprob < -1.45:
            continue
        if not strict and avg_logprob is not None and avg_logprob < -2.35:
            continue
        if strict and compression_ratio is not None and compression_ratio > 3.00:
            continue
        norm_text = re.sub(r"[^\w\s]", "", text.lower(), flags=re.UNICODE).strip()
        if strict and not include_vocalizations and norm_text in {"ah", "ahh", "ai", "hmm", "hum", "hm", "uh", "uhm", "um", "oh", "oooh"}:
            continue
        segments.append({
            "start": s.start,
            "end": s.end,
            "text": text,
            "avg_logprob": float(avg_logprob) if avg_logprob is not None else None,
            "no_speech_prob": float(no_speech_prob) if no_speech_prob is not None else None,
            "compression_ratio": float(compression_ratio) if compression_ratio is not None else None,
        })
    text = " ".join(s["text"] for s in segments if s["text"])
    return {"language": info.language, "text": text, "segments": segments}


def _get_premium_whisper():
    global _premium_whisper_model, _premium_whisper_model_name
    if _premium_whisper_model is None:
        from faster_whisper import WhisperModel
        db_path = os.environ.get("ADULT_META_DB_PATH", "/data/runs.db")
        model_dir = os.path.join(os.path.dirname(db_path), "models", "faster-whisper")
        os.makedirs(model_dir, exist_ok=True)
        requested = _LOCAL_WHISPER_PREMIUM_MODEL
        last_exc: Optional[Exception] = None
        for model_name in [requested, "large-v3"]:
            if not model_name:
                continue
            try:
                _premium_whisper_model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=model_dir,
                )
                _premium_whisper_model_name = model_name
                break
            except Exception as exc:
                last_exc = exc
                print(f"[transcribe] premium model load failed ({model_name}): {exc}", flush=True)
        if _premium_whisper_model is None and last_exc:
            raise last_exc
    return _premium_whisper_model


PORN_BR_WHISPER_INITIAL_PROMPT = (
    "Português brasileiro de putaria raiz, cena de sexo real amador ou profissional. "
    "Fala suja, gemidos altos e baixos, respiração pesada, tapa, repetições constantes "
    "e dirty talk explícito. Vocabulário esperado: ai ai ai, ahhh, aah, ah, hum hum hum, "
    "hmm, ui, oi, vai vai vai, isso isso isso, mete, mete forte, mete devagar, entra, "
    "mais fundo, goza, goza pra mim, me enche de leite, porra, caralho, buceta molhada, "
    "pau, pica grossa, cu, chupa gostoso, delícia, gostosa, safada, filha da puta, "
    "tesão, que delícia, que gostoso, me fode, squirt, creampie. "
    "Mantenha repetições reais, gemidos e fala baixa; não invente inglês, nomes ou spam."
)


def _premium_vad_attempts() -> List[tuple[str, Dict[str, Any]]]:
    """Tentativas CPU-friendly para fala baixa em conteúdo adulto PT-BR.

    A ordem importa:
    - balanced: primeira escolha, preserva fala real sem abrir demais.
    - low_speech: captura fala/gemido vocalizado mais curto.
    - noise_guard: mais conservador quando a tentativa anterior parece inglesa/lixo.
    """
    return [
        (
            "porn_br_balanced",
            {
                "beam_size": 5,
                "temperature": 0.0,
                "task": "transcribe",
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.38,
                    "min_speech_duration_ms": 160,
                    "min_silence_duration_ms": 650,
                    "speech_pad_ms": 320,
                },
                "no_speech_threshold": 0.72,
                "log_prob_threshold": -1.35,
                "compression_ratio_threshold": 2.65,
                "condition_on_previous_text": False,
                "word_timestamps": True,
                "initial_prompt": PORN_BR_WHISPER_INITIAL_PROMPT,
            },
        ),
        (
            "porn_br_low_speech",
            {
                "beam_size": 5,
                "temperature": 0.0,
                "task": "transcribe",
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.35,
                    "min_speech_duration_ms": 80,
                    "min_silence_duration_ms": 420,
                    "speech_pad_ms": 420,
                },
                "no_speech_threshold": 0.80,
                "log_prob_threshold": -1.70,
                "compression_ratio_threshold": 3.05,
                "condition_on_previous_text": False,
                "word_timestamps": True,
                "initial_prompt": PORN_BR_WHISPER_INITIAL_PROMPT,
            },
        ),
        (
            "porn_br_noise_guard",
            {
                "beam_size": 3,
                "temperature": 0.0,
                "task": "transcribe",
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.40,
                    "min_speech_duration_ms": 240,
                    "min_silence_duration_ms": 900,
                    "speech_pad_ms": 220,
                },
                "no_speech_threshold": 0.62,
                "log_prob_threshold": -1.10,
                "compression_ratio_threshold": 2.35,
                "condition_on_previous_text": False,
                "word_timestamps": True,
                "initial_prompt": PORN_BR_WHISPER_INITIAL_PROMPT,
            },
        ),
    ]


def _whisper_words_payload(segment: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for w in getattr(segment, "words", None) or []:
        word = str(getattr(w, "word", "") or "").strip()
        if not word:
            continue
        out.append({
            "start": float(getattr(w, "start", getattr(segment, "start", 0.0)) or 0.0),
            "end": float(getattr(w, "end", getattr(segment, "end", 0.0)) or 0.0),
            "word": word,
            "probability": float(getattr(w, "probability", 0.0) or 0.0),
        })
    return out


def _segments_from_word_timestamps(
    segments: List[Dict[str, Any]],
    *,
    max_words: int = 8,
    max_duration: float = 4.8,
    gap_threshold: float = 0.75,
) -> List[Dict[str, Any]]:
    """Reconstrói legendas curtas usando word_timestamps do Whisper.

    O faster-whisper pode devolver um segmento enorme com centenas de segundos,
    mesmo tendo timestamps por palavra corretos. Para burn, o que importa é o
    tempo das palavras, então reagrupamos em cues curtos.
    """
    out: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(str(w.get("word") or "").strip() for w in current).strip()
        if text:
            out.append({
                "start": float(current[0].get("start") or 0.0),
                "end": float(current[-1].get("end") or current[-1].get("start") or 0.0),
                "text": _transcript_clean_text(text),
                "confidence": min(float(w.get("probability") or 0.0) for w in current),
            })
        current = []

    for seg in segments or []:
        words = seg.get("words") or []
        if not words:
            fallback.append(seg)
            continue
        for raw in words:
            word = str(raw.get("word") or "").strip()
            if not word:
                continue
            try:
                start = float(raw.get("start") or 0.0)
                end = float(raw.get("end") or start)
            except Exception:
                continue
            item = {
                "word": word,
                "start": max(0.0, start),
                "end": max(0.0, end),
                "probability": float(raw.get("probability") or 0.0),
            }
            if current:
                gap = item["start"] - float(current[-1].get("end") or current[-1].get("start") or 0.0)
                duration = float(current[-1].get("end") or current[0].get("start") or 0.0) - float(current[0].get("start") or 0.0)
                text_len = len(" ".join(str(w.get("word") or "") for w in current))
                if gap > gap_threshold or duration >= max_duration or len(current) >= max_words or text_len >= 58:
                    flush_current()
            current.append(item)
    flush_current()

    if out:
        return out
    return fallback


def _premium_hard_filter_segment(
    segment: Any,
    *,
    include_vocalizations: bool,
    mode: str,
) -> tuple[bool, str]:
    text = str(getattr(segment, "text", "") or "").strip()
    if not text:
        return False, "empty"
    no_speech_prob = getattr(segment, "no_speech_prob", None)
    avg_logprob = getattr(segment, "avg_logprob", None)
    compression_ratio = getattr(segment, "compression_ratio", None)

    # Filtros duros apenas para lixo óbvio. A limpeza semântica vem depois.
    if no_speech_prob is not None and float(no_speech_prob) > 0.97:
        return False, "no_speech_prob"
    if avg_logprob is not None and float(avg_logprob) < -2.65:
        return False, "avg_logprob"
    if compression_ratio is not None and float(compression_ratio) > 4.40:
        return False, "compression_ratio"
    if not include_vocalizations:
        norm_text = re.sub(r"[^\w\s]", "", text.lower(), flags=re.UNICODE).strip()
        if norm_text in {"ah", "ahh", "ai", "hmm", "hum", "hm", "uh", "uhm", "um", "oh", "oooh"}:
            return False, "vocalization_disabled"
    return True, ""


def _score_transcript_quality(
    segments: List[Dict[str, Any]],
    *,
    expected_lang: str = "pt",
    duration_seconds: float = 0.0,
) -> Dict[str, Any]:
    text = " ".join((s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip())
    total_tokens, pt_hits, foreign_hits = _pt_transcript_signal_counts(text) if _norm_lang_code(expected_lang) == "pt" else (0, 0, 0)
    hallucination_hits = 0
    for seg in segments:
        if _transcript_segment_hallucination_reason(seg.get("text") or "", expected_lang, expected_lang):
            hallucination_hits += 1
    avg_no_speech_vals = [float(s["no_speech_prob"]) for s in segments if s.get("no_speech_prob") is not None]
    avg_logprob_vals = [float(s["avg_logprob"]) for s in segments if s.get("avg_logprob") is not None]
    avg_no_speech = sum(avg_no_speech_vals) / len(avg_no_speech_vals) if avg_no_speech_vals else 0.0
    avg_logprob = sum(avg_logprob_vals) / len(avg_logprob_vals) if avg_logprob_vals else 0.0
    chars = len(text)
    span_seconds = sum(max(0.0, float(s.get("end", 0.0) or 0.0) - float(s.get("start", 0.0) or 0.0)) for s in segments)
    foreign_ratio = foreign_hits / max(1, total_tokens)
    hallucination_ratio = hallucination_hits / max(1, len(segments))

    score = 100.0
    score -= min(45.0, foreign_ratio * 130.0)
    score -= min(35.0, hallucination_ratio * 100.0)
    score -= min(20.0, max(0.0, avg_no_speech - 0.55) * 55.0)
    if avg_logprob and avg_logprob < -1.0:
        score -= min(20.0, abs(avg_logprob + 1.0) * 12.0)
    if chars < 18 and duration_seconds >= 45:
        score -= 15.0
    if chars > 0 and pt_hits == 0 and _norm_lang_code(expected_lang) == "pt":
        score -= 18.0
    if span_seconds <= 0 and chars:
        score -= 10.0
    score = max(0.0, min(100.0, score))

    reasons: List[str] = []
    if chars < 18 and duration_seconds >= 45:
        reasons.append("too_short")
    if foreign_ratio >= 0.24:
        reasons.append("foreign_ratio_high")
    if hallucination_ratio >= 0.18:
        reasons.append("hallucination_ratio_high")
    if avg_no_speech >= 0.82:
        reasons.append("no_speech_high")
    if chars > 0 and pt_hits == 0 and _norm_lang_code(expected_lang) == "pt":
        reasons.append("no_pt_signal")

    return {
        "score": round(score, 2),
        "chars": chars,
        "segments": len(segments),
        "span_seconds": round(span_seconds, 3),
        "tokens": total_tokens,
        "pt_hits": pt_hits,
        "foreign_hits": foreign_hits,
        "foreign_ratio": round(foreign_ratio, 4),
        "hallucination_hits": hallucination_hits,
        "hallucination_ratio": round(hallucination_ratio, 4),
        "avg_no_speech_prob": round(avg_no_speech, 4),
        "avg_logprob": round(avg_logprob, 4),
        "retry_reasons": reasons,
        "should_retry": bool(reasons and score < 78.0),
    }


def _transcribe_premium(
    audio_path: str,
    language: str = "",
    *,
    include_vocalizations: bool = False,
) -> Dict[str, Any]:
    model = _get_premium_whisper()
    expected_lang = _norm_lang_code(language) or "pt"
    attempts = _premium_vad_attempts()
    if str(os.environ.get("ADULT_META_PREMIUM_NO_VAD_RESCUE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        attempts.append((
            "no_vad_rescue",
            {
                "beam_size": 5,
                "temperature": 0.0,
                "task": "transcribe",
                "vad_filter": False,
                "no_speech_threshold": 0.92,
                "log_prob_threshold": -2.20,
                "compression_ratio_threshold": 3.60,
                "condition_on_previous_text": False,
                "word_timestamps": True,
                "initial_prompt": PORN_BR_WHISPER_INITIAL_PROMPT,
            },
        ))
    try:
        duration_seconds = float((_probe_metadata(audio_path) or {}).get("duration_seconds") or 0.0)
    except Exception:
        duration_seconds = 0.0

    best_result: Dict[str, Any] = {"language": expected_lang, "text": "", "segments": [], "premium_mode": "", "quality": {"score": 0.0}}
    attempt_meta: List[Dict[str, Any]] = []
    for mode, kwargs in attempts:
        run_kwargs = dict(kwargs)
        run_kwargs["language"] = expected_lang
        segments_gen, info = model.transcribe(audio_path, **run_kwargs)
        segments = []
        dropped: Dict[str, int] = {}
        for s in segments_gen:
            keep, reason = _premium_hard_filter_segment(s, include_vocalizations=include_vocalizations, mode=mode)
            if not keep:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            text = str(getattr(s, "text", "") or "").strip()
            no_speech_prob = getattr(s, "no_speech_prob", None)
            avg_logprob = getattr(s, "avg_logprob", None)
            compression_ratio = getattr(s, "compression_ratio", None)
            segments.append({
                "start": float(getattr(s, "start", 0.0) or 0.0),
                "end": float(getattr(s, "end", 0.0) or 0.0),
                "text": text,
                "avg_logprob": float(avg_logprob) if avg_logprob is not None else None,
                "no_speech_prob": float(no_speech_prob) if no_speech_prob is not None else None,
                "compression_ratio": float(compression_ratio) if compression_ratio is not None else None,
                "premium_mode": mode,
                "words": _whisper_words_payload(s),
            })
        quality = _score_transcript_quality(segments, expected_lang=expected_lang, duration_seconds=duration_seconds)
        attempt_meta.append({
            "mode": mode,
            "quality": quality,
            "dropped": dropped,
            "segment_count": len(segments),
        })
        text = " ".join(s["text"] for s in segments if s["text"]).strip()
        candidate = {
            "language": getattr(info, "language", "") or expected_lang,
            "text": text,
            "segments": segments,
            "premium_mode": mode,
            "quality": quality,
            "attempts": attempt_meta[:],
            "model": _premium_whisper_model_name or _LOCAL_WHISPER_PREMIUM_MODEL,
        }
        if quality.get("score", 0.0) > float((best_result.get("quality") or {}).get("score") or 0.0):
            best_result = candidate
        if segments and not quality.get("should_retry"):
            return candidate
    return best_result


def _norm_lang_code(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return ""
    if v == "auto":
        return ""
    # Keep common two-letter language code used by our UI selectors.
    return v.replace("-", "_").split("_")[0]


_TRANSCRIBE_NON_LATIN_LANGS = {"ar", "he", "ja", "ko", "ru", "th", "uk", "zh"}
_TRANSCRIBE_LANG_NAMES = {
    "pt": "Portuguese",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "th": "Thai",
    "ru": "Russian",
}

_PT_TRANSCRIPT_KEEP_WORDS = {
    "a", "ai", "ah", "aham", "ahem", "assim", "ate", "bem", "bom", "bora", "cada", "cade",
    "caralho", "caramba", "ce", "ceu", "chupa", "com", "como", "da", "de", "deixa",
    "delicia", "delicioso", "denise", "deus", "do", "doce", "ela", "ele", "em", "enche",
    "entra", "essa", "esse", "esta", "eu", "fazer", "filha", "foi", "foda", "fode",
    "fundo", "gosa", "goza", "gozar", "gostosa", "gostoso", "gostosa", "gostou",
    "gustoso", "hmm", "hum", "isso", "leite", "macia", "mais", "mano", "me", "mete",
    "meu", "mim", "muito", "nao", "no", "nossa", "oh", "oi", "olha", "para", "pai",
    "pode", "porra", "puta", "que", "querido", "sim", "so", "sua", "ta", "tava",
    "tchau", "te", "tesao", "tesao", "toma", "um", "uma", "vai", "vem", "voce",
}
_PT_TRANSCRIPT_FOREIGN_WORDS = {
    "air", "all", "aye", "bitch", "boy", "delicious", "dog", "doing", "fine", "got",
    "good", "goodness", "guts", "happening", "harder", "he", "hey", "hi", "is", "it",
    "its", "jika", "magic", "mister", "mom", "my", "nice", "ohyeah", "password",
    "please", "right", "sadamsakumesama", "see", "shh", "support", "thank", "thanks",
    "this", "tommy", "well", "what", "whats", "whoa", "why", "yeah", "yes", "you",
    "your", "youre",
}
_PT_TRANSCRIPT_HALLUCINATION_PHRASES = (
    "as a language model",
    "como dog",
    "doing so well",
    "eu nao sei o que fazer",
    "i got it",
    "is this",
    "it is fine",
    "its all right",
    "its delicious",
    "its fine",
    "magiccao",
    "my goodness",
    "my god",
    "oh my",
    "please support",
    "sadamsakumesama",
    "thank you",
    "thank you tommy",
    "hi hi hi",
    "this is",
    "t es un",
    "what a delicious",
    "whats your password",
    "why is this happening",
    "you are doing so well",
    "youre doing so well",
    "your password",
)

# Whitelist forte para pornografia BR. Ela existe para preservar dirty talk,
# gemidos escritos e repetições reais, sem moralizar nem "corrigir" o conteúdo.
_PT_TRANSCRIPT_KEEP_WORDS.update({
    "abaixa", "abre", "abriu", "agacha", "agora", "aguenta", "ainda", "anal",
    "aperta", "arromba", "arrombada", "assim", "babando", "bater", "bate",
    "beija", "boca", "boquete", "bota", "botando", "brava", "bravo", "buceta",
    "bundinha", "bunda", "cabeca", "cacete", "cadela", "cachorra", "cara",
    "cavala", "cavalgando", "cavalga", "chupando", "chupar", "chupa", "cima",
    "comer", "come", "comigo", "continua", "cu", "dedo", "dentro", "desce",
    "devagar", "dilicia", "diz", "duro", "empina", "empurra", "enfia", "enfiando",
    "engole", "entao", "entrando", "esporra", "fazer", "fazendo",
    "fode", "fodendo", "foder", "fodeu", "forte", "fraco", "fundinho", "fundo",
    "gemendo", "geme", "gozada", "gozando", "gozei", "gozou", "grita", "grosso", "grossa", "gulosinha",
    "leite", "linda", "louca", "mamada", "mamar", "mamando", "maozinha", "mete",
    "metendo", "meter", "molhada", "molhadinha", "novinha", "pau", "pica", "piroca",
    "piranha", "porra", "profundo", "quero", "rabao", "rabuda", "rebola", "rebolando",
    "rola", "senta", "sentando", "senta", "tesuda", "tesudo", "tirar", "tira",
    "todinha", "tudo", "vem", "vindo", "xota",
    "arrombado", "creampie", "pauzao", "putinha", "safada", "squirt",
    "ahhh", "aaah", "aah", "humm", "huum", "mmm", "mmmm", "uhh", "ui", "aaa",
})
_PT_TRANSCRIPT_FOREIGN_WORDS.update({
    "hi", "hello", "bye", "goodbye", "password", "tommy", "thanks", "thankyou",
    "support", "subscribe", "channel", "dog", "mister", "goodness", "delicious",
    "happening", "doing", "fine", "alright", "right", "japanese", "subtitle",
})


def _fold_transcript_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    folded = folded.lower().replace("’", "'").replace("`", "'")
    folded = re.sub(r"[^a-z0-9'\s]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _transcript_word_tokens_folded(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", _fold_transcript_text(text))


def _pt_transcript_signal_counts(text: str) -> tuple[int, int, int]:
    tokens = _transcript_word_tokens_folded(text)
    normalized_tokens = [t.replace("'", "") for t in tokens]
    pt_hits = sum(1 for t in normalized_tokens if t in _PT_TRANSCRIPT_KEEP_WORDS)
    foreign_hits = sum(1 for t in normalized_tokens if t in _PT_TRANSCRIPT_FOREIGN_WORDS)
    return len(normalized_tokens), pt_hits, foreign_hits


def _pt_transcript_language_reason(text: str) -> str:
    folded = _fold_transcript_text(text)
    if not folded:
        return ""
    if folded in {"musica", "music", "legend", "legenda", "subtitles"}:
        return "pt_asr_music_or_caption"
    if folded in {"amem", "amen"}:
        return "pt_known_asr_hallucination"
    if any(phrase in folded for phrase in _PT_TRANSCRIPT_HALLUCINATION_PHRASES):
        return "pt_known_asr_hallucination"
    total, pt_hits, foreign_hits = _pt_transcript_signal_counts(folded)
    if total == 0:
        return ""
    if foreign_hits >= 2 and pt_hits == 0:
        return "pt_wrong_language"
    if total >= 5 and foreign_hits / max(1, total) >= 0.34 and pt_hits < 2:
        return "pt_wrong_language"
    if total >= 3 and pt_hits == 0 and foreign_hits >= 1:
        return "pt_wrong_language"
    # Garbage-like long tokens appear often when ASR tries to interpret moans
    # as Japanese/English names. Keep real Portuguese/adult words even repeated.
    for token in _transcript_word_tokens_folded(folded):
        compact = token.replace("'", "")
        if len(compact) >= 12 and compact not in _PT_TRANSCRIPT_KEEP_WORDS:
            vowels = sum(1 for ch in compact if ch in "aeiou")
            if vowels <= 2 or compact in _PT_TRANSCRIPT_FOREIGN_WORDS:
                return "pt_gibberish"
    return ""


def _default_transcribe_prompt(
    language: str = "",
    *,
    adult_mode: bool = True,
    include_vocalizations: bool = True,
) -> str:
    # Intentionally empty: Whisper prompt fields are previous-transcript context,
    # not instructions. Long instructions leak into subtitles.
    return ""


def _transcript_clean_text(text: str) -> str:
    txt = str(text or "")
    txt = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


def _transcript_script_counts(text: str) -> Dict[str, int]:
    return {
        "cjk": sum(1 for ch in text if "\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff"),
        "hangul": sum(1 for ch in text if "\uac00" <= ch <= "\ud7af"),
        "thai": sum(1 for ch in text if "\u0e00" <= ch <= "\u0e7f"),
        "cyrillic": sum(1 for ch in text if "\u0400" <= ch <= "\u052f"),
        "arabic": sum(1 for ch in text if "\u0600" <= ch <= "\u06ff"),
        "hebrew": sum(1 for ch in text if "\u0590" <= ch <= "\u05ff"),
    }


def _transcript_repetition_reason(text: str) -> str:
    # Adult content naturally contains repeated words/phrases/vocalizations.
    # Never classify repetition alone as hallucination; only explicit spam,
    # prompt leaks and unexpected scripts are filtered elsewhere.
    return ""


def _transcript_segment_hallucination_reason(text: str, expected_lang: str = "", detected_lang: str = "") -> str:
    txt = _transcript_clean_text(text)
    if not txt:
        return "empty"
    expected = _norm_lang_code(expected_lang)
    detected = _norm_lang_code(detected_lang)
    # Se o usuário não escolheu explicitamente um idioma não-latino, não aceitamos
    # surtos de script inesperado gerados pelo Whisper em trechos sem fala clara.
    allows_non_latin = expected in _TRANSCRIBE_NON_LATIN_LANGS
    counts = _transcript_script_counts(txt)
    unexpected = counts["cjk"] + counts["hangul"] + counts["thai"] + counts["cyrillic"] + counts["arabic"] + counts["hebrew"]
    letters = sum(1 for ch in txt if ch.isalpha())
    if not allows_non_latin and unexpected >= 4 and unexpected / max(1, letters) >= 0.18:
        return f"unexpected_script:{detected or 'auto'}"
    rep = _transcript_repetition_reason(txt)
    if rep:
        return rep
    lower = txt.lower()
    spam_bits = (
        "subscribe", "subtitles by", "amara.org",
        "se inscreva", "inscreva-se", "inscreva no canal", "ative o sininho", "deixe seu like",
        "suscríbete", "suscribete", "subtítulos", "subtitulado por",
        "字幕", "訂閱", "подпис",
    )
    if any(bit in lower for bit in spam_bits):
        return "known_spam"
    prompt_leak_bits = (
        "capture low-volume speech",
        "transcribe real spoken dialogue",
        "transcribe only real spoken dialogue",
        "do not invent subtitles",
        "do not translate",
        "without censorship or moralizing",
        "adult/pornographic content",
        "if speech is unclear",
        "prefer portuguese, english or spanish",
    )
    if any(bit in lower for bit in prompt_leak_bits):
        return "prompt_leak"
    if expected == "pt":
        pt_reason = _pt_transcript_language_reason(txt)
        if pt_reason:
            return pt_reason
    return ""


def _clean_transcript_segments(
    segments: List[Dict[str, Any]],
    expected_lang: str = "",
    detected_lang: str = "",
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    reason_counts: Dict[str, int] = {}
    for seg in segments or []:
        text = _transcript_clean_text(seg.get("text") or "")
        reason = _transcript_segment_hallucination_reason(text, expected_lang, detected_lang)
        if not reason and _norm_lang_code(expected_lang) == "pt":
            try:
                confidence = float(seg.get("confidence")) if seg.get("confidence") is not None else 1.0
            except Exception:
                confidence = 1.0
            total, pt_hits, foreign_hits = _pt_transcript_signal_counts(text)
            if confidence < 0.12 and total >= 2 and pt_hits == 0:
                reason = "pt_low_confidence_no_signal"
            elif confidence < 0.20 and foreign_hits > pt_hits:
                reason = "pt_low_confidence_foreign"
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue
        cleaned.append({
            "start": float(seg.get("start", 0.0) or 0.0),
            "end": float(seg.get("end", 0.0) or 0.0),
            "text": text,
        })
    return cleaned, {
        "removed_count": max(0, len(segments or []) - len(cleaned)),
        "kept_count": len(cleaned),
        "reason_counts": reason_counts,
        "expected_lang": _norm_lang_code(expected_lang) or "auto",
        "detected_lang": _norm_lang_code(detected_lang) or "auto",
    }


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty_json")
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start:end + 1])
    raise ValueError("json_object_not_found")


def _chunk_segments_for_llm(segments: List[Dict[str, Any]], size: int = 60) -> List[List[Dict[str, Any]]]:
    return [segments[i:i + size] for i in range(0, len(segments), max(1, size))]


async def _post_process_with_llm(
    segments: List[Dict[str, Any]],
    *,
    expected_lang: str = "pt",
    include_vocalizations: bool = True,
    quality_meta: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Correção final com Grok-3 sem traduzir nem reescrever dirty talk.

    O LLM atua como uma peneira conservadora:
    - remove apenas alucinações claras de ASR;
    - preserva repetições, palavrões, dirty talk e vocalizações;
    - mantém timestamps e quantidade de blocos por lote.

    Se qualquer resposta vier inválida, a função falha em modo seguro e devolve
    os segmentos originais.
    """
    if not segments:
        return segments, {"status": "skipped", "reason": "no_segments"}
    if str(os.environ.get("ADULT_META_TRANSCRIPT_LLM_POST", "1")).strip().lower() in {"0", "false", "no", "off"}:
        return segments, {"status": "skipped", "reason": "disabled"}
    if _norm_lang_code(expected_lang) != "pt":
        return segments, {"status": "skipped", "reason": "non_pt_language"}

    grok_key = ((settings_get(key="token:grok") or {}).get("value") or os.environ.get("GROK_API_KEY") or "").strip()
    openrouter_key = ((settings_get(key="token:openrouter") or {}).get("value") or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not grok_key and not openrouter_key:
        return segments, {"status": "skipped", "reason": "missing_token:grok_or_openrouter"}

    xai_model_candidates = [
        os.environ.get("GROK_TRANSCRIPT_POST_MODEL", "grok-3-latest").strip() or "grok-3-latest",
        "grok-4.3",
        "grok-4",
        "grok-3-fast",
    ]
    openrouter_model_candidates = [
        os.environ.get("OPENROUTER_TRANSCRIPT_POST_MODEL", "x-ai/grok-4.3").strip() or "x-ai/grok-4.3",
        "x-ai/grok-4.3",
        "x-ai/grok-3-fast",
    ]
    system_msg = (
        "Você é revisor técnico de transcrição ASR para pornografia adulta explícita em português brasileiro. "
        "Sua única missão é limpar a transcrição mantendo o máximo possível de fala real, gemidos, repetições "
        "e dirty talk pesado. Remova SOMENTE alucinações claras do ASR: inglês inventado, spam de legenda, "
        "nomes aleatórios, frases impossíveis em silêncio/gemidos e lixo tipo 'Thank you Tommy', "
        "'What's your password?', 'Hi Hi Hi', 'sadamsakumesama'. "
        "Mantenha TODO dirty talk, palavrão, termo sexual explícito, gemido escrito e repetição real como "
        "'ai ai ai', 'vai vai vai', 'hum hum hum', 'isso isso', 'me enche de leite porra'. "
        "Não censure, não traduza, não suavize, não melhore gramática e não deixe linguagem corporativa. "
        "Se estiver em dúvida se é alucinação ou fala real de sexo, mantenha o texto original. "
        "Retorne somente JSON válido no formato {\"segments\":[{\"index\":0,\"text\":\"...\"}]}."
    )

    output: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {
        "status": "ok",
        "provider": "grok",
        "model": "",
        "batches": 0,
        "removed_count": 0,
        "changed_count": 0,
        "fallback": False,
    }

    timeout = httpx.Timeout(90.0, connect=20.0, read=90.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for batch in _chunk_segments_for_llm(segments, 60):
            indexed = [
                {
                    "index": i,
                    "start": round(float(seg.get("start", 0.0) or 0.0), 3),
                    "end": round(float(seg.get("end", 0.0) or 0.0), 3),
                    "text": str(seg.get("text") or ""),
                }
                for i, seg in enumerate(batch)
            ]
            user_msg = json.dumps({
                "language": "pt-BR",
                "adult_mode": True,
                "porn_context": True,
                "include_vocalizations": bool(include_vocalizations),
                "quality": quality_meta or {},
                "segments": indexed,
                "rules": [
                    "Mantenha exatamente o mesmo número de segmentos e índices.",
                    "Para remover alucinação clara, retorne text vazio.",
                    "Nunca altere timestamps.",
                    "Remova apenas alucinações claras em inglês ou frases impossíveis.",
                    "Mantenha toda putaria, repetições, gemidos e dirty talk original.",
                    "Não traduza inglês real caso o trecho seja obviamente fala inglesa; mas se for frase clássica inventada em meio a PT-BR, remova.",
                    "Se tiver dúvida, mantenha o texto original.",
                ],
            }, ensure_ascii=False)

            last_error = ""
            parsed: Optional[Dict[str, Any]] = None
            used_model = ""
            attempts: List[tuple[str, str, str]] = []
            if grok_key:
                attempts.extend(("xai", "https://api.x.ai/v1/chat/completions", m) for m in dict.fromkeys(xai_model_candidates))
            if openrouter_key:
                attempts.extend(("openrouter", "https://openrouter.ai/api/v1/chat/completions", m) for m in dict.fromkeys(openrouter_model_candidates))
            for provider_name, url, model in attempts:
                try:
                    token = grok_key if provider_name == "xai" else openrouter_key
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system_msg},
                                {"role": "user", "content": user_msg},
                            ],
                            "temperature": 0.0,
                            "max_tokens": 4096,
                        },
                    )
                    if response.status_code >= 400:
                        last_error = f"{provider_name}/{model}:http_{response.status_code}:{(response.text or '')[:220]}"
                        continue
                    content = (((response.json().get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""
                    parsed = _extract_json_object(content)
                    used_model = f"{provider_name}:{model}"
                    break
                except Exception as exc:
                    last_error = f"{provider_name}/{model}:{_safe_error_detail(exc, 'grok_postprocess_failed')}"
                    continue
            if not parsed:
                return segments, {"status": "skipped", "reason": "llm_failed", "detail": last_error[:300], "fallback": True}

            returned = parsed.get("segments")
            if not isinstance(returned, list) or len(returned) != len(batch):
                return segments, {
                    "status": "skipped",
                    "reason": "invalid_segment_count",
                    "expected": len(batch),
                    "received": len(returned) if isinstance(returned, list) else None,
                    "fallback": True,
                }

            meta["model"] = used_model or meta.get("model") or ""
            meta["batches"] = int(meta.get("batches") or 0) + 1
            for original, item in zip(batch, returned):
                if not isinstance(item, dict):
                    return segments, {"status": "skipped", "reason": "invalid_item", "fallback": True}
                new_text = _transcript_clean_text(item.get("text") if item.get("text") is not None else original.get("text") or "")
                old_text = _transcript_clean_text(original.get("text") or "")
                if not new_text:
                    meta["removed_count"] = int(meta.get("removed_count") or 0) + 1
                    continue
                if new_text != old_text:
                    meta["changed_count"] = int(meta.get("changed_count") or 0) + 1
                updated = dict(original)
                updated["text"] = new_text
                output.append(updated)

    if not output:
        return segments, {"status": "skipped", "reason": "llm_removed_all", "fallback": True}
    return output, meta


async def _translate_text_google(text: str, target_lang: str, source_lang: str = "") -> str:
    src = _norm_lang_code(source_lang) or "auto"
    tgt = _norm_lang_code(target_lang)
    if not tgt:
        return text
    if _norm_lang_code(source_lang) == tgt:
        return text
    timeout = httpx.Timeout(25.0, connect=10.0, read=25.0)
    params = {
        "client": "gtx",
        "sl": src,
        "tl": tgt,
        "dt": "t",
        "q": text,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get("https://translate.googleapis.com/translate_a/single", params=params)
        r.raise_for_status()
        data = r.json()
    parts = data[0] if isinstance(data, list) and data else []
    out = "".join((p[0] or "") for p in parts if isinstance(p, list) and p)
    return out.strip() or text


async def _translate_segments_google(segments: List[Dict[str, Any]], target_lang: str, source_lang: str = "") -> List[Dict[str, Any]]:
    if not segments:
        return []
    out: List[Dict[str, Any]] = []
    sem = asyncio.Semaphore(6)
    timeout = httpx.Timeout(25.0, connect=10.0, read=25.0)
    src = _norm_lang_code(source_lang) or "auto"
    tgt = _norm_lang_code(target_lang)
    if not tgt or _norm_lang_code(source_lang) == tgt:
        return segments

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def _translate_one(seg: Dict[str, Any]) -> Dict[str, Any]:
            txt = (seg.get("text") or "").strip()
            if not txt:
                return {
                    "start": float(seg.get("start", 0.0) or 0.0),
                    "end": float(seg.get("end", 0.0) or 0.0),
                    "text": "",
                }
            async with sem:
                params = {
                    "client": "gtx",
                    "sl": src,
                    "tl": tgt,
                    "dt": "t",
                    "q": txt,
                }
                r = await client.get("https://translate.googleapis.com/translate_a/single", params=params)
                r.raise_for_status()
                data = r.json()
                parts = data[0] if isinstance(data, list) and data else []
                translated = "".join((p[0] or "") for p in parts if isinstance(p, list) and p).strip() or txt
                return {
                    "start": float(seg.get("start", 0.0) or 0.0),
                    "end": float(seg.get("end", 0.0) or 0.0),
                    "text": translated,
                }

        translated_items = await asyncio.gather(*[_translate_one(s) for s in segments])
    out.extend(translated_items)
    return out


_TRANSLATION_THINK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)
_TRANSLATION_CODE_FENCE_RE = re.compile(r'```[\w]*\n|```\n?')

def _clean_llm_translation_response(raw: str) -> str:
    """Remove thinking blocks, markdown fences, and trailing delimiters from LLM response."""
    raw = _TRANSLATION_THINK_RE.sub('', raw)
    raw = _TRANSLATION_CODE_FENCE_RE.sub('', raw)
    raw = raw.strip()
    if raw.endswith('|||SEG|||'):
        raw = raw[:-len('|||SEG|||')].strip()
    return raw


def _map_translated_texts(
    segments: List[Dict[str, Any]],
    texts: List[str],
    translated_texts: List[str],
) -> Optional[List[Dict[str, Any]]]:
    """Mapeia textos traduzidos de volta aos segmentos originais.
    Retorna None se a contagem não bater após limpeza.
    """
    cleaned = [t.strip() for t in translated_texts]
    # Remove trailing empty entry caused by trailing delimiter
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    # Remove leading empty entry
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    if len(cleaned) != len(texts):
        return None
    return [
        {
            "start": float(s.get("start", 0) or 0),
            "end": float(s.get("end", 0) or 0),
            "text": t or texts[i],
        }
        for i, (s, t) in enumerate(zip(segments, cleaned))
    ]


async def _translate_segments_llm(
    segments: List[Dict[str, Any]],
    target_lang: str,
    source_lang: str = "",
) -> List[Dict[str, Any]]:
    """Traduz segmentos via LLM: Grok (xAI) → modelos via OpenRouter → OpenAI.
    Fallback para Google Translate se todos os LLMs falharem.
    """
    if not segments:
        return []
    tgt = _norm_lang_code(target_lang)
    if not tgt:
        return segments
    if _norm_lang_code(source_lang) == tgt:
        return segments

    sep = "\n|||SEG|||\n"
    texts = [((s.get("text") or "").strip()) for s in segments]
    combined = sep.join(texts)

    lang_map = {
        "pt": "Portuguese", "en": "English", "es": "Spanish",
        "fr": "French", "de": "German", "it": "Italian",
        "ja": "Japanese", "zh": "Chinese",
    }
    lang_name = lang_map.get(tgt, tgt.upper())
    src_label = (lang_map.get(_norm_lang_code(source_lang) or "", source_lang or "auto")).capitalize()

    system_msg = (
        "Você é tradutor especialista em legendas de pornografia adulta explícita. "
        "Você receberá segmentos separados pelo delimitador '|||SEG|||'. "
        "Traduza cada segmento de " + src_label + " para " + lang_name + ", mantendo tom safado, natural, "
        "palavrões, gemidos, repetições e dirty talk. Não suavize, não censure e não use linguagem corporativa. "
        "Retorne APENAS os segmentos traduzidos separados pelo mesmo delimitador '|||SEG|||', "
        "na mesma ordem e quantidade exata. Sem explicação, sem bloco de código, sem tags de raciocínio."
    )
    user_msg = combined

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    last_error: str = "no_provider_available"

    async def _try_provider(url: str, headers: dict, json_data: dict) -> Optional[List[Dict[str, Any]]]:
        nonlocal last_error
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=json_data)
            if r.status_code < 400:
                raw = (((r.json().get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""
                cleaned = _clean_llm_translation_response(raw)
                translated_texts = cleaned.split("|||SEG|||")
                result = _map_translated_texts(segments, texts, translated_texts)
                if result is not None:
                    return result
                last_error = f"bad_seg_count_{r.status_code}"
            else:
                last_error = f"error_{r.status_code}"
        except Exception as ex:
            last_error = f"exception: {ex}"
        return None

    # 1. Grok (xAI)
    grok_key = (settings_get(key="token:grok") or {}).get("value")
    if grok_key:
        result = await _try_provider(
            "https://api.x.ai/v1/chat/completions",
            {"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
            {"model": "grok-3-fast", "messages": messages, "max_tokens": 4096},
        )
        if result is not None:
            return result

    # 2. Modelos via OpenRouter (apenas modelos não-reasoning)
    openrouter_key = (settings_get(key="token:openrouter") or {}).get("value")
    if openrouter_key:
        or_models = ["x-ai/grok-3-fast", "x-ai/grok-3-mini-fast", "openai/gpt-4o-mini"]
        or_headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://caripost.n8nmikael.com.br",
            "X-Title": "MetaPorn Translation",
        }
        for or_model in or_models:
            result = await _try_provider(
                "https://openrouter.ai/api/v1/chat/completions",
                or_headers,
                {"model": or_model, "messages": messages, "max_tokens": 4096},
            )
            if result is not None:
                return result

    # 3. OpenAI
    openai_key = (settings_get(key="token:openai") or {}).get("value")
    if openai_key:
        result = await _try_provider(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            {"model": "gpt-4o-mini", "messages": messages, "max_tokens": 4096},
        )
        if result is not None:
            return result

    # 4. Fallback: Google Translate
    fallback = await _translate_segments_google(segments, target_lang, source_lang)
    if fallback:
        return fallback

    raise RuntimeError(f"translation_llm_failed: {last_error}")


def _normalize_content_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    out = value.strip()
    if not out:
        return None
    # Keep the value minimal and deterministic to avoid signature/header mismatch.
    if ";" in out:
        out = out.split(";", 1)[0].strip()
    return out.lower() or None


_UUID_FNAME_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-',
    re.IGNORECASE,
)
_CODE_PREFIX_RE = re.compile(r'^.*?_-(?=_)')


def _clean_upload_filename(fname: str) -> str:
    """Strip local: prefix, UUID and leading code from filename.

    Example: local:uploads/.../uuid-0414_03_-_Cena_-_Slave.mp4 → _Cena_-_Slave.mp4
    """
    raw = str(fname or '')
    if raw.startswith('local:'):
        raw = raw[6:]
    base = raw.split('/')[-1] if '/' in raw else raw
    cleaned = _UUID_FNAME_RE.sub('', base)
    cleaned = _CODE_PREFIX_RE.sub('', cleaned)
    return cleaned or base


def _safe_storage_filename(filename: str, fallback: str = "upload.bin") -> str:
    safe = re.sub(r"[^a-zA-Z0-9._\-]", "_", str(filename or "").strip())
    safe = safe.strip("._-")
    return safe or fallback


def _sanitize_storage_prefix(prefix: str, default: str = "uploads") -> str:
    raw = str(prefix or "").strip().strip("/")
    if not raw:
        return default
    if ".." in raw:
        return default
    if not OBJECT_KEY_RE.fullmatch(raw):
        return default
    return raw


def _is_local_media_ref(value: str) -> bool:
    return str(value or "").startswith(LOCAL_MEDIA_PREFIX)


def _local_media_rel_path_from_ref(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.startswith(LOCAL_MEDIA_PREFIX):
        raise ValueError("invalid_local_media_ref")
    rel = raw[len(LOCAL_MEDIA_PREFIX):].lstrip("/")
    if not rel or ".." in rel or not LOCAL_MEDIA_REL_RE.fullmatch(rel):
        raise ValueError("invalid_local_media_rel_path")
    return rel


def _local_media_abs_path_from_rel(rel_path: str) -> str:
    rel = str(rel_path or "").strip().lstrip("/")
    if not rel or ".." in rel or not LOCAL_MEDIA_REL_RE.fullmatch(rel):
        raise ValueError("invalid_local_media_rel_path")
    root_abs = os.path.abspath(LOCAL_MEDIA_ROOT)
    abs_path = os.path.abspath(os.path.join(root_abs, rel))
    if os.path.commonpath([root_abs, abs_path]) != root_abs:
        raise ValueError("invalid_local_media_abs_path")
    return abs_path


def _local_media_abs_path_from_ref(value: str) -> str:
    return _local_media_abs_path_from_rel(_local_media_rel_path_from_ref(value))


def _local_media_ref(rel_path: str) -> str:
    rel = str(rel_path or "").strip().lstrip("/")
    _local_media_abs_path_from_rel(rel)
    return f"{LOCAL_MEDIA_PREFIX}{rel}"


def _media_ref_relative_path(value: str) -> str:
    raw = str(value or "").strip()
    if _is_local_media_ref(raw):
        return _local_media_rel_path_from_ref(raw)
    return raw.lstrip("/")


def _media_ref_has_prefix(value: str, *prefixes: str) -> bool:
    try:
        rel = _media_ref_relative_path(value)
    except Exception:
        return False
    for prefix in prefixes:
        safe_prefix = str(prefix or "").strip().strip("/")
        if not safe_prefix:
            continue
        if rel == safe_prefix or rel.startswith(f"{safe_prefix}/"):
            return True
    return False


def _local_media_signature(ref: str, expires_ts: int, disposition: str, filename: str = "") -> str:
    payload = f"{ref}\n{int(expires_ts)}\n{disposition}\n{filename}".encode("utf-8")
    return hmac.new(LOCAL_MEDIA_URL_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _build_local_media_url(ref: str, *, disposition: str = "inline", filename: str = "", expires_in: int = 3600) -> str:
    safe_ref = str(ref or "").strip()
    if not _is_local_media_ref(safe_ref):
        raise ValueError("local_media_ref_required")
    safe_name = _safe_storage_filename(filename, os.path.basename(_media_ref_relative_path(safe_ref) or "media.bin"))
    safe_disposition = "attachment" if disposition == "attachment" else "inline"
    expires_ts = int(time.time()) + max(60, int(expires_in or 3600))
    params = {
        "ref": safe_ref,
        "expires": str(expires_ts),
        "sig": _local_media_signature(safe_ref, expires_ts, safe_disposition, safe_name if safe_disposition == "attachment" else ""),
    }
    if safe_disposition == "attachment":
        params["filename"] = safe_name
        return f"/api/local-media/download?{urlencode(params)}"
    return f"/api/local-media/stream?{urlencode(params)}"


def _authorize_local_media_request(request: Request, ref: str, disposition: str, filename: str = "") -> Optional[Dict[str, str]]:
    auth_err = _require_api_key(request)
    if auth_err is None:
        return None
    try:
        expires_ts = int(str(request.query_params.get("expires") or "0"))
    except Exception:
        return {"error": "unauthorized", "detail": "invalid_or_missing_media_signature"}
    sig = str(request.query_params.get("sig") or "").strip().lower()
    if not sig:
        return {"error": "unauthorized", "detail": "invalid_or_missing_media_signature"}
    if expires_ts < int(time.time()):
        return {"error": "unauthorized", "detail": "expired_media_signature"}
    safe_name = _safe_storage_filename(filename, os.path.basename(_media_ref_relative_path(ref) or "media.bin"))
    expected = _local_media_signature(ref, expires_ts, disposition, safe_name if disposition == "attachment" else "")
    if not hmac.compare_digest(sig, expected):
        return {"error": "unauthorized", "detail": "invalid_or_missing_media_signature"}
    return None


def _is_valid_object_key(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if _is_local_media_ref(raw):
        try:
            _local_media_abs_path_from_ref(raw)
            return True
        except Exception:
            return False
    if ".." in raw:
        return False
    return bool(OBJECT_KEY_RE.fullmatch(raw))


def _safe_error_detail(err: Exception, fallback: str) -> str:
    text = str(err).strip()
    if not text:
        return fallback
    return text[:800]


def _build_provider_specs(items: List[Dict[str, Any]]) -> List[ProviderSpec]:
    specs: List[ProviderSpec] = []
    for p in items[:2]:
        name = (p.get("name") or "").strip().lower()
        if name not in SUPPORTED_PROVIDER_NAMES:
            raise ValueError(f"unsupported_provider:{name or 'empty'}")

        model = (p.get("model") or "").strip()
        if not model:
            raise ValueError(f"missing_model:{name}")

        api_key = p.get("api_key")
        if not api_key and name in ("openai", "deepseek", "openrouter", "grok", "gemini"):
            saved = settings_get(key=f"token:{name}")
            api_key = saved["value"] if saved else None

        specs.append(
            ProviderSpec(
                name=name,
                model=model,
                base_url=p.get("base_url"),
                api_key=api_key,
            )
        )
    return specs


def _build_smart_search_query(
    *,
    vision_analysis: Optional[Dict],
    transcript_lang: Optional[str],
    transcript_text: str,
) -> str:
    """Build a targeted xvideos search query using all available analysis data.

    Priority order:
    1. Language/nationality from Whisper lang tag
    2. Categories from Vision (specific ones, not generic)
    3. Performer ethnicity from Vision
    4. Specific acts from Vision scenes
    5. Body type (distinctive: bbw, petite, curvy, busty, thick)
    6. Fallback: words from transcript
    """
    parts: List[str] = []

    # 1. Language → nationality keyword (strongest signal for xvideos)
    lang = (transcript_lang or "").lower().replace("-", "_").split("_")[0]
    lang_kw: Dict[str, str] = {
        "pt": "brasileira",
        "es": "latina",
        "ja": "japanese",
        "ko": "korean",
        "zh": "chinese",
        "fr": "french",
        "it": "italian",
        "de": "german",
        "ru": "russian",
        "ar": "arab",
        "th": "thai",
    }
    if lang in lang_kw:
        parts.append(lang_kw[lang])

    if vision_analysis and isinstance(vision_analysis, dict):
        # 2. Specific categories (exclude generic noise words)
        _generic_cats = {
            "sex", "porn", "video", "xxx", "adult", "hardcore",
            "amateur", "homemade", "porno", "erotic",
        }
        categories = [
            c.lower().strip() for c in (vision_analysis.get("categories") or [])
            if c and c.lower().strip() not in _generic_cats
        ]
        parts.extend(categories[:3])

        # 3. Performer ethnicity (skip white/caucasian — too generic)
        performers = vision_analysis.get("performers") or {}
        ethnicities = performers.get("ethnicities_visible") or []
        if isinstance(ethnicities, str):
            ethnicities = [ethnicities]
        for eth in ethnicities:
            eth_l = str(eth).lower().strip()
            if eth_l and eth_l not in ("white", "caucasian", "unknown", ""):
                parts.append(eth_l)
                break  # one ethnicity is enough

        # 4. Specific body type (only truly distinctive ones)
        body_types = performers.get("body_types") or []
        if isinstance(body_types, str):
            body_types = [body_types]
        distinctive = [
            b.lower() for b in body_types
            if b.lower() in ("bbw", "petite", "curvy", "busty", "thick", "chubby")
        ]
        if distinctive:
            parts.append(distinctive[0])

        # 5. Most specific act from scenes
        for scene in (vision_analysis.get("scenes") or [])[:3]:
            acts = scene.get("acts") or []
            if isinstance(acts, str):
                acts = [acts]
            for act in acts:
                act_l = str(act).lower().strip()
                if act_l and len(act_l) > 3 and act_l not in ("sex", "porn", "fuck"):
                    parts.append(act_l)
                    break
            else:
                continue
            break

    # 6. Fallback: first meaningful words from transcript
    if not parts and transcript_text:
        words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", transcript_text)
        parts = [w.lower() for w in words[:6]]

    if not parts:
        return ""

    # Deduplicate preserving order
    seen: set = set()
    unique: List[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            unique.append(p)

    return " ".join(unique[:8])[:120]


def _download_object_to_file(*, s3, object_key: str, out_path: str) -> None:
    with open(out_path, "wb") as f:
        s3.download_fileobj(S3_BUCKET, object_key, f)


def _s3_object_exists(*, s3, object_key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=object_key)
        return True
    except Exception:
        return False


def _measure_fileobj_size(file_obj: Any) -> int:
    current_pos = None
    try:
        current_pos = file_obj.tell()
    except Exception:
        current_pos = None
    try:
        file_obj.seek(0, os.SEEK_END)
        size = int(file_obj.tell() or 0)
    finally:
        try:
            if current_pos is None:
                file_obj.seek(0)
            else:
                file_obj.seek(current_pos)
        except Exception:
            pass
    return max(0, size)


def _write_fileobj_to_path(*, file_obj: Any, out_path: str) -> int:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    total = 0
    try:
        file_obj.seek(0)
    except Exception:
        pass
    with open(out_path, "wb") as f:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    try:
        file_obj.seek(0)
    except Exception:
        pass
    return total


def _persist_local_ref_from_path(*, src_path: str, media_ref: str) -> Dict[str, Any]:
    abs_path = _local_media_abs_path_from_ref(media_ref)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    shutil.copyfile(src_path, abs_path)
    size_bytes = max(0, int(os.path.getsize(abs_path) or 0))
    return {
        "object_key": media_ref,
        "public_url": _build_local_media_url(media_ref),
        "size_bytes": size_bytes,
        "storage_kind": "local",
        "storage_path": abs_path,
    }


def _persist_local_ref_by_move(*, src_path: str, media_ref: str) -> Dict[str, Any]:
    abs_path = _local_media_abs_path_from_ref(media_ref)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        os.replace(src_path, abs_path)
    except OSError:
        shutil.copyfile(src_path, abs_path)
        try:
            os.remove(src_path)
        except FileNotFoundError:
            pass
    size_bytes = max(0, int(os.path.getsize(abs_path) or 0))
    return {
        "object_key": media_ref,
        "public_url": _build_local_media_url(media_ref),
        "size_bytes": size_bytes,
        "storage_kind": "local",
        "storage_path": abs_path,
    }


def _store_local_path(*, src_path: str, prefix: str, filename: str, content_type: str = "application/octet-stream") -> Dict[str, Any]:
    safe_prefix = _sanitize_storage_prefix(prefix, "uploads")
    safe_name = _safe_storage_filename(filename, "upload.bin")
    rel_path = f"{safe_prefix}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}-{safe_name}"
    return _persist_local_ref_from_path(src_path=src_path, media_ref=_local_media_ref(rel_path))


def _store_local_path_by_move(*, src_path: str, prefix: str, filename: str, content_type: str = "application/octet-stream") -> Dict[str, Any]:
    safe_prefix = _sanitize_storage_prefix(prefix, "uploads")
    safe_name = _safe_storage_filename(filename, "upload.bin")
    rel_path = f"{safe_prefix}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}-{safe_name}"
    return _persist_local_ref_by_move(src_path=src_path, media_ref=_local_media_ref(rel_path))


def _store_teaser_with_name(*, src_path: str, run_id: str, burned_object_key: str = "") -> Dict[str, Any]:
    """Armazena o teaser com um nome baseado no vídeo queimado de origem."""
    run_prefix = run_id[:8] if run_id else "teaser"
    
    burned_name = ""
    if burned_object_key:
        parts = burned_object_key.split("/")
        if parts:
            filename = parts[-1]
            if filename.endswith(".mp4"):
                filename = filename[:-4]
            burned_name = filename
    
    if burned_name:
        safe_name = _safe_storage_filename(f"teaser_{run_prefix}_{burned_name}.mp4", "teaser.mp4")
    else:
        safe_name = _safe_storage_filename(f"teaser_{run_prefix}.mp4", "teaser.mp4")
    
    rel_path = f"teasers/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}-{safe_name}"
    return _persist_local_ref_from_path(src_path=src_path, media_ref=_local_media_ref(rel_path))


def _media_ref_exists(*, media_ref: str, s3: Any = None) -> bool:
    if _is_local_media_ref(media_ref):
        try:
            return os.path.exists(_local_media_abs_path_from_ref(media_ref))
        except Exception:
            return False
    if not s3:
        s3 = _s3_client()
    if not s3:
        return False
    return _s3_object_exists(s3=s3, object_key=media_ref)


def _download_media_ref_to_file(*, media_ref: str, out_path: str, s3: Any = None) -> None:
    if _is_local_media_ref(media_ref):
        src_path = _local_media_abs_path_from_ref(media_ref)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.copyfile(src_path, out_path)
        return
    if not s3:
        s3 = _s3_client()
    if not s3:
        raise RuntimeError("s3_not_configured")
    _download_object_to_file(s3=s3, object_key=media_ref, out_path=out_path)


def _delete_media_ref(*, media_ref: str, s3: Any = None) -> None:
    if _is_local_media_ref(media_ref):
        abs_path = _local_media_abs_path_from_ref(media_ref)
        if os.path.exists(abs_path):
            os.remove(abs_path)
        return
    if not s3:
        s3 = _s3_client()
    if not s3:
        raise RuntimeError("s3_not_configured")
    s3.delete_object(Bucket=S3_BUCKET, Key=media_ref)


_RUN_CLEANUP_MEDIA_PREFIXES = (
    "uploads",
    "burns",
    "teasers",
    "combined",
    "previews",
    "narrations-manual",
    "teasers-openers",
)
_CREATION_CLEANUP_MEDIA_PREFIXES = ("burns", "teasers", "combined", "previews")
_CREATION_WIZARD_MEDIA_KEYS = (
    "burned_object_key",
    "teaser_object_key",
    "teaser_logo_object_key",
    "teaser_combined_object_key",
)


def _normalize_media_refish(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("data:", "blob:")):
        return ""
    if _is_valid_object_key(raw):
        return raw
    if raw.lower().startswith("s3://"):
        s3_path = raw[5:]
        slash = s3_path.find("/")
        candidate = s3_path[slash + 1:] if slash >= 0 else ""
        return candidate if _is_valid_object_key(candidate) else ""

    parsed = None
    if raw.startswith("/") or re.match(r"^https?://", raw, re.I):
        try:
            parsed = urlparse(raw)
        except Exception:
            parsed = None
    if parsed:
        query = parse_qs(parsed.query or "")
        for key in ("ref", "object_key"):
            for item in query.get(key, []):
                candidate = unquote(str(item or "").strip())
                if _is_valid_object_key(candidate):
                    return candidate
        path = unquote(parsed.path or "").strip("/")
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] == S3_BUCKET and len(parts) > 1:
            candidate = "/".join(parts[1:])
            if _is_valid_object_key(candidate):
                return candidate
        for idx, part in enumerate(parts):
            if part in _RUN_CLEANUP_MEDIA_PREFIXES:
                candidate = "/".join(parts[idx:])
                if _is_valid_object_key(candidate):
                    return candidate
    return ""


def _is_cleanup_media_ref(media_ref: str, prefixes: tuple[str, ...]) -> bool:
    ref = str(media_ref or "").strip()
    if not ref or not _is_valid_object_key(ref):
        return False
    return _media_ref_has_prefix(ref, *prefixes)


def _collect_media_refs_from_value(
    value: Any,
    *,
    prefixes: tuple[str, ...] = _RUN_CLEANUP_MEDIA_PREFIXES,
    out: Optional[set[str]] = None,
) -> set[str]:
    refs = out if out is not None else set()
    if isinstance(value, dict):
        for child in value.values():
            _collect_media_refs_from_value(child, prefixes=prefixes, out=refs)
        return refs
    if isinstance(value, list):
        for child in value:
            _collect_media_refs_from_value(child, prefixes=prefixes, out=refs)
        return refs
    if isinstance(value, str):
        ref = _normalize_media_refish(value)
        if ref and _is_cleanup_media_ref(ref, prefixes):
            refs.add(ref)
    return refs


def _collect_creation_media_refs(req_data: Dict[str, Any]) -> List[str]:
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    refs: set[str] = set()
    for key in _CREATION_WIZARD_MEDIA_KEYS:
        _collect_media_refs_from_value(
            wizard_state.get(key),
            prefixes=_CREATION_CLEANUP_MEDIA_PREFIXES,
            out=refs,
        )
    return sorted(refs)


def _collect_run_media_refs(
    *,
    run_row: Dict[str, Any],
    scheduled_posts: Optional[List[Dict[str, Any]]] = None,
    async_jobs: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    refs: set[str] = set()
    req_data = _safe_json_obj(run_row.get("request_json"))
    result_data = _safe_json_obj(run_row.get("result_json"))
    _collect_media_refs_from_value(req_data, out=refs)
    _collect_media_refs_from_value(result_data, out=refs)
    for post in scheduled_posts or []:
        _collect_media_refs_from_value(post, out=refs)
    for job in async_jobs or []:
        _collect_media_refs_from_value(job, out=refs)
    return sorted(refs)


async def _delete_media_refs_for_run(run_id: str, refs: List[str]) -> Dict[str, Any]:
    deleted: List[str] = []
    skipped: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    s3 = _s3_client()
    for ref in sorted({str(r or "").strip() for r in refs if str(r or "").strip()}):
        if not _is_cleanup_media_ref(ref, _RUN_CLEANUP_MEDIA_PREFIXES):
            skipped.append({"object_key": ref, "reason": "not_cleanup_candidate"})
            continue
        try:
            used_elsewhere = await asyncio.to_thread(
                media_ref_used_by_other_runs,
                media_ref=ref,
                exclude_run_id=run_id,
            )
            if used_elsewhere:
                skipped.append({"object_key": ref, "reason": "referenced_by_other_run"})
                continue
            exists = await asyncio.to_thread(_media_ref_exists, media_ref=ref, s3=s3)
            if not exists:
                skipped.append({"object_key": ref, "reason": "not_found"})
                continue
            await asyncio.to_thread(_delete_media_ref, media_ref=ref, s3=s3)
            deleted.append(ref)
        except Exception as exc:
            errors.append({"object_key": ref, "error": _safe_error_detail(exc, "delete_failed")})
    if deleted:
        try:
            await asyncio.to_thread(upload_meta_delete_many, deleted)
        except Exception as exc:
            errors.append({"object_key": "upload_metadata", "error": _safe_error_detail(exc, "metadata_delete_failed")})
    return {"deleted_media": deleted, "skipped_media": skipped, "media_errors": errors}


def _active_jobs_for_run(run_id: str, *, kinds: Optional[List[str]] = None) -> List[Dict[str, str]]:
    safe_kinds = kinds or [_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER, _ASYNC_JOB_KIND_ANALYZE]
    active: List[Dict[str, str]] = []
    try:
        jobs = list_async_jobs_for_run(run_id=run_id, kinds=safe_kinds)
    except Exception:
        jobs = []
    for job in jobs:
        status = str(job.get("status") or "").lower()
        if status in {"pending", "running"}:
            active.append({
                "kind": str(job.get("kind") or ""),
                "job_id": str(job.get("job_id") or ""),
                "status": status,
            })
    return active


def _job_payload_matches_run_id(value: Any, run_id: str) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"run_id", "video_id"} and str(child or "") == run_id:
                return True
            if _job_payload_matches_run_id(child, run_id):
                return True
        return False
    if isinstance(value, list):
        return any(_job_payload_matches_run_id(child, run_id) for child in value)
    return False


def _drop_runtime_jobs_for_run(run_id: str, *, kinds: Optional[List[str]] = None) -> int:
    safe_kinds = set(kinds or [_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER, _ASYNC_JOB_KIND_DRIVE_UPLOAD, _ASYNC_JOB_KIND_DRIVE_IMPORT])
    stores = {
        _ASYNC_JOB_KIND_BURN: _burn_jobs,
        _ASYNC_JOB_KIND_TEASER: _teaser_jobs,
        _ASYNC_JOB_KIND_DRIVE_UPLOAD: _drive_upload_jobs,
        _ASYNC_JOB_KIND_DRIVE_IMPORT: _drive_import_jobs,
    }
    dropped = 0
    for kind, store in stores.items():
        if kind not in safe_kinds:
            continue
        for job_id, payload in list(store.items()):
            if not _job_payload_matches_run_id(payload, run_id):
                continue
            store.pop(job_id, None)
            _burn_dequeue(job_id)
            dropped += 1
    return dropped


def _google_drive_upload_path_sync(
    *,
    src_path: str,
    filename: str,
    folder_id: str,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    cfg = _google_drive_config_status()
    raw_creds = (settings_get(key=GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY) or {}).get("value") or ""
    if not str(folder_id or "").strip():
        raise RuntimeError("google_drive_folder_not_configured")
    if not str(raw_creds or "").strip():
        raise RuntimeError("google_drive_credentials_not_configured")
    if not cfg.get("has_credentials"):
        raise RuntimeError("google_drive_credentials_not_configured")
    creds_info = _parse_google_drive_service_account(str(raw_creds or ""))
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    mime_type = mimetypes.guess_type(filename or src_path)[0] or "application/octet-stream"
    media = MediaFileUpload(src_path, mimetype=mime_type, resumable=True, chunksize=8 * 1024 * 1024)
    body = {
        "name": filename,
        "parents": [str(folder_id).strip()],
    }
    request = service.files().create(
        body=body,
        media_body=media,
        fields="id,name,webViewLink,webContentLink,size,mimeType,parents",
        supportsAllDrives=True,
    )
    uploaded = None
    while uploaded is None:
        status, uploaded = request.next_chunk()
        if status is not None and callable(progress_cb):
            try:
                progress_cb(max(0.0, min(float(status.progress() or 0.0), 1.0)))
            except Exception:
                pass
    return uploaded or {}


def _upload_fileobj_singlepart(
    *,
    s3,
    file_obj: Any,
    object_key: str,
    content_type: str,
    expected_size: int,
) -> None:
    if expected_size <= 0:
        raise ValueError("empty_upload")
    if expected_size > S3_SINGLE_UPLOAD_MAX_BYTES:
        raise ValueError(
            "single_upload_too_large:"
            f"{expected_size}>{S3_SINGLE_UPLOAD_MAX_BYTES}"
        )
    try:
        file_obj.seek(0)
    except Exception:
        pass
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=object_key,
        Body=file_obj,
        ContentLength=int(expected_size),
        ContentType=content_type,
    )
    head = s3.head_object(Bucket=S3_BUCKET, Key=object_key)
    stored_size = int(head.get("ContentLength") or 0)
    if stored_size != int(expected_size):
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=object_key)
        except Exception:
            pass
        raise RuntimeError(
            "uploaded_object_size_mismatch:"
            f"expected={expected_size}:stored={stored_size}"
        )


def _upload_path_singlepart(*, s3, src_path: str, object_key: str, content_type: str) -> None:
    expected_size = max(0, int(os.path.getsize(src_path) or 0))
    with open(src_path, "rb") as f:
        _upload_fileobj_singlepart(
            s3=s3,
            file_obj=f,
            object_key=object_key,
            content_type=content_type,
            expected_size=expected_size,
        )


def _looks_like_video_upload(*, filename: str, content_type: str) -> bool:
    safe_name = str(filename or "").lower()
    safe_type = str(content_type or "").lower()
    if safe_type.startswith("video/"):
        return True
    return safe_name.endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"))


def _declared_media_size_shortfall_check(*, meta: Dict[str, Any], actual_size: int) -> Optional[Dict[str, Any]]:
    """Catch MP4s whose moov atom declares a full movie but media data is missing."""
    actual_size = max(0, int(actual_size or 0))
    if actual_size <= 0:
        return None
    duration = max(
        0.0,
        float(meta.get("video_duration_seconds") or 0.0),
        float(meta.get("duration_seconds") or 0.0),
    )
    declared_bitrate = max(
        0,
        int(meta.get("declared_media_bit_rate") or 0),
        int(meta.get("video_bit_rate") or 0) + int(meta.get("audio_bit_rate") or 0),
    )
    if duration < 300 or declared_bitrate < 1_000_000 or actual_size < 100 * 1024 * 1024:
        return None

    expected_payload_bytes = int(duration * declared_bitrate / 8)
    if expected_payload_bytes <= 0:
        return None

    ratio = actual_size / max(1, expected_payload_bytes)
    missing_bytes = expected_payload_bytes - actual_size
    if ratio < 0.12 and missing_bytes > 512 * 1024 * 1024:
        return {
            "expected_payload_bytes": expected_payload_bytes,
            "actual_size": actual_size,
            "ratio": ratio,
            "declared_bitrate": declared_bitrate,
            "detail": (
                "O MP4 declara uma duração/bitrate incompatível com o tamanho real do arquivo. "
                f"Ele tem {round(actual_size / 1024 / 1024, 1)} MB, mas pelo próprio índice do vídeo "
                f"deveria estar perto de {round(expected_payload_bytes / 1024 / 1024, 1)} MB. "
                "Isso é típico de upload interrompido/truncado."
            ),
        }
    return None


def _validate_video_path_sync(*, in_path: str, size_bytes: Optional[int] = None, storage_path: Optional[str] = None) -> Dict[str, Any]:
    downloaded_size = max(0, int(os.path.getsize(in_path) or 0))
    effective_size = downloaded_size if size_bytes is None else max(0, int(size_bytes or 0))
    meta = _probe_metadata(in_path)
    duration = max(0.0, float(meta.get("duration_seconds") or 0.0))
    width = max(0, int(meta.get("width") or 0))
    height = max(0, int(meta.get("height") or 0))
    if effective_size <= 0 or downloaded_size <= 0:
        return {
            "ok": False,
            "error": "empty_media",
            "detail": "O arquivo recebido está vazio.",
            "size_bytes": effective_size,
            "downloaded_size": downloaded_size,
            "metadata": meta,
            "storage_path": storage_path,
        }
    if size_bytes is not None and downloaded_size != effective_size:
        return {
            "ok": False,
            "error": "download_size_mismatch",
            "detail": (
                "O arquivo não bate com o tamanho esperado. "
                f"Esperado: {effective_size} bytes; lido: {downloaded_size} bytes."
            ),
            "size_bytes": effective_size,
            "downloaded_size": downloaded_size,
            "metadata": meta,
            "storage_path": storage_path,
        }
    if duration <= 0 or width <= 0 or height <= 0:
        return {
            "ok": False,
            "error": "invalid_video_metadata",
            "detail": "Não foi possível extrair metadados válidos do vídeo.",
            "size_bytes": effective_size,
            "downloaded_size": downloaded_size,
            "metadata": meta,
            "storage_path": storage_path,
        }
    size_shortfall = _declared_media_size_shortfall_check(meta=meta, actual_size=effective_size)
    if size_shortfall:
        return {
            "ok": False,
            "error": "source_media_truncated",
            "detail": size_shortfall["detail"],
            "size_bytes": effective_size,
            "downloaded_size": downloaded_size,
            "metadata": meta,
            "size_shortfall": size_shortfall,
            "storage_path": storage_path,
        }
    quick_check = _quick_media_integrity_check(in_path=in_path, expected_duration=duration)
    if quick_check:
        checkpoint = max(0.0, float(quick_check.get("checkpoint_seconds") or 0.0))
        detail = str(quick_check.get("detail") or "").strip() or "Falha na validação rápida da mídia."
        return {
            "ok": False,
            "error": "source_media_corrupt",
            "detail": (
                "Detectei falhas no vídeo armazenado durante a validação prévia "
                f"perto de {_format_media_clock(checkpoint)}.\n\n{detail}"
            ),
            "size_bytes": effective_size,
            "downloaded_size": downloaded_size,
            "metadata": meta,
            "checkpoint_seconds": checkpoint,
            "storage_path": storage_path,
        }
    return {
        "ok": True,
        "size_bytes": effective_size,
        "downloaded_size": downloaded_size,
        "metadata": meta,
        "storage_path": storage_path,
        "detail": (
            f"Vídeo válido: {width}x{height}, {_format_media_clock(duration)}, "
            f"{round(effective_size / 1024 / 1024, 1)} MB."
        ),
    }


def _validate_video_object_sync(*, s3, object_key: str) -> Dict[str, Any]:
    if _is_local_media_ref(object_key):
        abs_path = _local_media_abs_path_from_ref(object_key)
        if not os.path.exists(abs_path):
            return {
                "ok": False,
                "error": "object_not_found",
                "detail": "Arquivo local não encontrado.",
                "storage_path": abs_path,
            }
        size_bytes = max(0, int(os.path.getsize(abs_path) or 0))
        return _validate_video_path_sync(in_path=abs_path, size_bytes=size_bytes, storage_path=abs_path)
    if not s3:
        raise RuntimeError("s3_not_configured")
    try:
        head = s3.head_object(Bucket=S3_BUCKET, Key=object_key)
    except ClientError as e:
        err = (getattr(e, "response", {}) or {}).get("Error", {}) or {}
        meta = (getattr(e, "response", {}) or {}).get("ResponseMetadata", {}) or {}
        err_code = str(err.get("Code") or "").strip()
        http_status = int(meta.get("HTTPStatusCode") or 0)
        if err_code in {"404", "NotFound", "NoSuchKey"} or http_status == 404:
            return {
                "ok": False,
                "error": "object_not_found",
                "detail": "Objeto não encontrado no storage.",
                "storage_path": None,
                "object_key": object_key,
            }
        raise
    size_bytes = max(0, int(head.get("ContentLength") or 0))
    with tempfile.TemporaryDirectory(prefix="validate-video-", dir=_preferred_tmpdir_root("validate")) as tmpdir:
        in_path = os.path.join(tmpdir, "input_media")
        try:
            _download_object_to_file(s3=s3, object_key=object_key, out_path=in_path)
        except ClientError as e:
            err = (getattr(e, "response", {}) or {}).get("Error", {}) or {}
            meta = (getattr(e, "response", {}) or {}).get("ResponseMetadata", {}) or {}
            err_code = str(err.get("Code") or "").strip()
            http_status = int(meta.get("HTTPStatusCode") or 0)
            if err_code in {"404", "NotFound", "NoSuchKey"} or http_status == 404:
                return {
                    "ok": False,
                    "error": "object_not_found",
                    "detail": "Objeto não encontrado no storage.",
                    "storage_path": None,
                    "object_key": object_key,
                }
            raise
        return _validate_video_path_sync(in_path=in_path, size_bytes=size_bytes)


async def _preview_lock_for(key: str) -> asyncio.Lock:
    with _preview_state_lock:
        lock = _preview_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _preview_locks[key] = lock
        return lock


def _guess_response_content_type(object_key: str) -> str:
    rel_key = _media_ref_relative_path(object_key).lower()
    guessed, _ = mimetypes.guess_type(rel_key)
    if guessed:
        return guessed
    low_key = rel_key
    if low_key.endswith(".mp3"):
        return "audio/mpeg"
    if low_key.endswith(".m4a"):
        return "audio/mp4"
    if low_key.endswith(".wav"):
        return "audio/wav"
    if low_key.endswith(".ogg"):
        return "audio/ogg"
    return "video/mp4"


def _encode_params_for_height(max_height: int) -> tuple[str, str, str]:
    safe_h = max(360, min(int(max_height or 1080), 2160))
    if safe_h <= 720:
        return "2800k", "5600k", "3.1"
    if safe_h <= 1080:
        return "4500k", "9000k", "4.1"
    return "9000k", "18000k", "5.1"


def _preview_variant_key(object_key: str, max_height: int, max_fps: int, output_crf: int) -> str:
    digest = hashlib.sha1(
        f"v1|{object_key}|h{max_height}|f{max_fps}|crf{output_crf}".encode("utf-8")
    ).hexdigest()
    return f"previews/{digest[:32]}.mp4"


def _create_preview_variant_sync(
    *,
    source_key: str,
    preview_key: str,
    max_height: int,
    max_fps: int,
    output_crf: int,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="preview-", dir=_preferred_tmpdir_root("preview")) as tmpdir:
        in_path = os.path.join(tmpdir, "input_video")
        out_path = os.path.join(tmpdir, "preview.mp4")
        _download_media_ref_to_file(media_ref=source_key, out_path=in_path)
        meta = _probe_metadata(in_path)
        src_h = int(meta.get("height") or 0)
        src_fps = float(meta.get("fps") or 0.0)
        duration = max(0.0, float(meta.get("duration_seconds") or 0.0))

        # Se já está em perfil leve, evita transcode desnecessário.
        if src_h and src_h <= max_height and (not src_fps or src_fps <= (max_fps + 0.15)):
            return source_key, "source_already_light"

        safe_h = max(360, min(int(max_height or 1080), 2160))
        safe_fps = max(24, min(int(max_fps or 30), 60))
        safe_crf = max(22, min(int(output_crf or 28), 35))
        maxrate, bufsize, level = _encode_params_for_height(safe_h)
        vf = f"scale=-2:min(ih\\,{safe_h}):flags=lanczos"
        if src_fps and src_fps > (safe_fps + 0.15):
            vf += f",fps={safe_fps}"

        cmd = [
            "ffmpeg", "-y",
            "-i", in_path,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", str(safe_crf),
            "-maxrate", maxrate,
            "-bufsize", bufsize,
            "-profile:v", "high",
            "-level:v", level,
            "-pix_fmt", "yuv420p",
            "-g", str(max(48, safe_fps * 2)),
            "-keyint_min", str(max(24, safe_fps)),
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-b:a", "96k",
            "-ac", "2",
            "-ar", "48000",
            "-movflags", "+faststart",
            out_path,
        ]
        timeout_s = max(240, int(max(30.0, duration) * 10))
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            err_text = (proc.stderr or b"").decode("utf-8", errors="replace")[-300:]
            raise RuntimeError(f"preview_ffmpeg_failed: {err_text or proc.returncode}")

        preview_ref = _local_media_ref(preview_key)
        _persist_local_ref_from_path(src_path=out_path, media_ref=preview_ref)
        return preview_ref, "preview_transcoded"


def _local_media_item_from_abs(abs_path: str) -> Dict[str, Any]:
    rel_path = os.path.relpath(abs_path, LOCAL_MEDIA_ROOT).replace(os.sep, "/")
    stat = os.stat(abs_path)
    media_ref = _local_media_ref(rel_path)
    size_bytes = max(0, int(stat.st_size or 0))
    return {
        "object_key": media_ref,
        "filename": os.path.basename(abs_path),
        "public_url": _build_local_media_url(media_ref),
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 1),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "storage_kind": "local",
        "storage_path": abs_path,
    }


def _media_ref_signature(media_ref: str) -> tuple[str, Optional[str], int, float]:
    """Stable cache signature for local media. Remote refs fall back to the ref only."""
    if _is_local_media_ref(media_ref):
        abs_path = _local_media_abs_path_from_ref(media_ref)
        stat = os.stat(abs_path)
        return (
            f"{media_ref}|{int(stat.st_size or 0)}|{stat.st_mtime_ns}",
            abs_path,
            int(stat.st_size or 0),
            float(stat.st_mtime or 0.0),
        )
    return (media_ref, None, 0, 0.0)


def _probe_media_ref_metadata_cached(media_ref: str) -> Dict[str, Any]:
    if not _is_valid_object_key(media_ref):
        raise ValueError("invalid_object_key")
    sig, abs_path, size_bytes, mtime = _media_ref_signature(media_ref)
    cache_key = hashlib.sha1(sig.encode("utf-8")).hexdigest()
    with _media_probe_cache_lock:
        hit = _media_probe_cache.get(cache_key)
        if hit:
            return dict(hit)

    if not abs_path:
        # Avoid downloading multi-GB S3 objects just to decorate the file grid.
        raise ValueError("metadata_available_for_local_media_only")
    meta = _probe_metadata(abs_path)
    out = {
        **meta,
        "object_key": media_ref,
        "size_bytes": size_bytes,
        "last_modified_ts": mtime,
        "duration_clock": _format_media_clock(float(meta.get("duration_seconds") or 0.0)),
    }
    with _media_probe_cache_lock:
        _media_probe_cache[cache_key] = dict(out)
    return out


def _media_manager_thumbnail_cache_ref(media_ref: str, *, width: int, seek_seconds: float) -> str:
    sig, _, size_bytes, mtime = _media_ref_signature(media_ref)
    payload = f"thumb-v2|{sig}|w{int(width)}|t{float(seek_seconds):.2f}|s{size_bytes}|m{mtime}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return _local_media_ref(f"thumbs/cache/{digest[:2]}/{digest}.jpg")


def _media_manager_thumbnail_sync(media_ref: str, *, width: int = 480, seek_seconds: float = 8.0) -> Dict[str, Any]:
    if not _is_valid_object_key(media_ref):
        raise ValueError("invalid_object_key")
    if not _is_local_media_ref(media_ref):
        # Thumbnails for remote S3 objects would require downloading whole videos.
        raise ValueError("thumbnail_available_for_local_media_only")
    abs_path = _local_media_abs_path_from_ref(media_ref)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(media_ref)

    safe_w = max(220, min(int(width or 480), 960))
    meta = _probe_media_ref_metadata_cached(media_ref)
    duration = max(0.0, float(meta.get("duration_seconds") or 0.0))
    if duration > 0:
        safe_seek = max(0.1, min(float(seek_seconds or 8.0), max(0.1, duration - 0.2)))
    else:
        safe_seek = max(0.1, float(seek_seconds or 2.0))

    thumb_ref = _media_manager_thumbnail_cache_ref(media_ref, width=safe_w, seek_seconds=safe_seek)
    thumb_abs = _local_media_abs_path_from_ref(thumb_ref)
    if os.path.exists(thumb_abs) and os.path.getsize(thumb_abs) > 1024:
        return {"object_key": thumb_ref, "url": _build_local_media_url(thumb_ref), "metadata": meta}

    os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)

    def _extract_at(seek: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "ffmpeg", "-y",
                "-hide_banner", "-loglevel", "error",
                "-ss", f"{seek:.3f}",
                "-i", abs_path,
                "-frames:v", "1",
                "-vf", f"scale=min({safe_w}\\,iw):-2:flags=lanczos",
                "-q:v", "5",
                thumb_abs,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=25,
        )

    proc = _extract_at(safe_seek)
    if proc.returncode != 0 or not os.path.exists(thumb_abs) or os.path.getsize(thumb_abs) <= 1024:
        try:
            if os.path.exists(thumb_abs):
                os.remove(thumb_abs)
        except Exception:
            pass
        proc = _extract_at(0.25)

    if proc.returncode != 0 or not os.path.exists(thumb_abs) or os.path.getsize(thumb_abs) <= 1024:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(err or "thumbnail_extract_failed")

    return {"object_key": thumb_ref, "url": _build_local_media_url(thumb_ref), "metadata": meta}


def _list_local_media_items(prefix: str, max_keys: int = 100) -> List[Dict[str, Any]]:
    safe_prefix = _sanitize_storage_prefix(prefix, "uploads")
    base_dir = _local_media_abs_path_from_rel(safe_prefix)
    if not os.path.isdir(base_dir):
        return []
    items: List[Dict[str, Any]] = []
    for root_dir, _, filenames in os.walk(base_dir):
        for filename in filenames:
            abs_path = os.path.join(root_dir, filename)
            try:
                items.append(_local_media_item_from_abs(abs_path))
            except Exception:
                continue
    items.sort(key=lambda item: item.get("last_modified") or "", reverse=True)
    return items[: max(1, min(int(max_keys or 100), 1000))]


def _media_item_from_media_ref(media_ref: str, *, s3: Any = None) -> Dict[str, Any]:
    if _is_local_media_ref(media_ref):
        abs_path = _local_media_abs_path_from_ref(media_ref)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(media_ref)
        item = _local_media_item_from_abs(abs_path)
    else:
        if not s3:
            s3 = _s3_client()
        if not s3:
            raise RuntimeError("s3_not_configured")
        head = s3.head_object(Bucket=S3_BUCKET, Key=media_ref)
        size_bytes = int(head.get("ContentLength") or 0)
        item = {
            "object_key": media_ref,
            "filename": os.path.basename(media_ref),
            "public_url": S3_PUBLIC_BASE_URL.rstrip("/") + f"/{S3_BUCKET}/{media_ref}",
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 1),
            "last_modified": (head.get("LastModified").isoformat() if head.get("LastModified") else ""),
            "storage_kind": "s3",
            "storage_path": None,
        }
    item["category"] = _media_manager_category(media_ref)
    return item


def _target_filename_for_rename(old_name: str, requested_name: str) -> str:
    base_old = os.path.basename(str(old_name or "").strip()) or "arquivo.mp4"
    safe_new = _safe_storage_filename(str(requested_name or "").strip(), base_old)
    old_ext = os.path.splitext(base_old)[1]
    stem = os.path.splitext(safe_new)[0] or os.path.splitext(base_old)[0] or "arquivo"
    return f"{stem}{old_ext}" if old_ext else safe_new


def _rename_media_ref(*, media_ref: str, new_filename: str, s3: Any = None) -> Dict[str, Any]:
    if not _media_ref_exists(media_ref=media_ref, s3=s3):
        raise FileNotFoundError(media_ref)
    rel = _media_ref_relative_path(media_ref)
    if "/" in rel:
        parent_prefix = rel.rsplit("/", 1)[0]
    else:
        parent_prefix = ""
    old_name = os.path.basename(rel)
    target_name = _target_filename_for_rename(old_name, new_filename)
    if target_name == old_name:
        item = _media_item_from_media_ref(media_ref, s3=s3)
        item["renamed"] = False
        return item
    target_rel = f"{parent_prefix}/{target_name}" if parent_prefix else target_name
    target_ref = _local_media_ref(target_rel) if _is_local_media_ref(media_ref) else target_rel
    if _media_ref_exists(media_ref=target_ref, s3=s3):
        raise FileExistsError("target_already_exists")

    if _is_local_media_ref(media_ref):
        src_abs = _local_media_abs_path_from_ref(media_ref)
        dst_abs = _local_media_abs_path_from_ref(target_ref)
        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
        os.replace(src_abs, dst_abs)
    else:
        if not s3:
            s3 = _s3_client()
        if not s3:
            raise RuntimeError("s3_not_configured")
        s3.copy_object(
            Bucket=S3_BUCKET,
            CopySource={"Bucket": S3_BUCKET, "Key": media_ref},
            Key=target_ref,
            MetadataDirective="COPY",
        )
        s3.delete_object(Bucket=S3_BUCKET, Key=media_ref)

    try:
        replace_media_ref_in_runs(old_ref=media_ref, new_ref=target_ref)
    except Exception as exc:
        print(f"[media-rename] reference update failed ({media_ref} -> {target_ref}): {exc}", flush=True)

    item = _media_item_from_media_ref(target_ref, s3=s3)
    item["old_object_key"] = media_ref
    item["renamed"] = True
    return item


def _probe_metadata(in_path: str) -> Dict[str, Any]:
    """Return video metadata dict using ffprobe. Returns empty dict on failure."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                in_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        raw = json.loads(proc.stdout)
        fmt = raw.get("format", {})
        duration = float(fmt.get("duration") or 0)
        width = height = fps = avg_fps = 0
        codec = ""
        has_audio = False
        video_duration = 0.0
        video_bit_rate = 0
        audio_bit_rate = 0
        nb_frames = 0
        color_primaries = color_transfer = color_space = pix_fmt = ""
        for s in raw.get("streams", []):
            stype = s.get("codec_type")
            try:
                stream_bit_rate = int(float(s.get("bit_rate") or 0))
            except Exception:
                stream_bit_rate = 0
            if stype == "audio":
                has_audio = True
                audio_bit_rate += max(0, stream_bit_rate)
                continue
            if stype == "video" and width == 0 and height == 0:
                width = int(s.get("width") or 0)
                height = int(s.get("height") or 0)
                codec = s.get("codec_name", "")
                video_bit_rate = max(0, stream_bit_rate)
                r = s.get("r_frame_rate") or "0/1"
                avg = s.get("avg_frame_rate") or "0/1"
                try:
                    num, den = r.split("/")
                    fps = round(int(num) / int(den), 2) if int(den) else 0
                except Exception:
                    fps = 0
                try:
                    num, den = avg.split("/")
                    avg_fps = round(int(num) / int(den), 2) if int(den) else 0
                except Exception:
                    avg_fps = 0
                try:
                    video_duration = float(s.get("duration") or 0)
                except Exception:
                    video_duration = 0.0
                try:
                    nb_frames = int(s.get("nb_frames") or 0)
                except Exception:
                    nb_frames = 0
                color_primaries = s.get("color_primaries", "")
                color_transfer = s.get("color_transfer", "")
                color_space = s.get("color_space", "")
                pix_fmt = s.get("pix_fmt", "")
        return {
            "duration_seconds": duration,
            "video_duration_seconds": video_duration,
            "width": width,
            "height": height,
            "fps": fps,
            "avg_fps": avg_fps,
            "nb_frames": nb_frames,
            "codec": codec,
            "has_audio": has_audio,
            "video_bit_rate": video_bit_rate,
            "audio_bit_rate": audio_bit_rate,
            "declared_media_bit_rate": video_bit_rate + audio_bit_rate,
            "color_primaries": color_primaries,
            "color_transfer": color_transfer,
            "color_space": color_space,
            "pix_fmt": pix_fmt,
        }
    except Exception:
        return {}


_HDR_TRANSFERS = {"arib-std-b67", "smpte2084", "slog", "slog2", "slog3", "bt2020-10", "bt2020-12"}
_HDR_PRIMARIES = {"bt2020"}


def _is_hdr_source(probe: Dict[str, Any]) -> bool:
    """Return True if the probe indicates an HDR or 10-bit wide-gamut source."""
    transfer = str(probe.get("color_transfer") or "").lower()
    primaries = str(probe.get("color_primaries") or "").lower()
    pix_fmt = str(probe.get("pix_fmt") or "").lower()
    return (
        transfer in _HDR_TRANSFERS
        or primaries in _HDR_PRIMARIES
        or "10le" in pix_fmt or "10be" in pix_fmt
        or "12le" in pix_fmt or "12be" in pix_fmt
    )


def _build_hdr_to_sdr_filter(probe: Dict[str, Any]) -> str:
    """Return an ffmpeg vf filter chain to tone-map HDR/10-bit input to SDR BT.709 8-bit.

    Uses zscale (libzimg) for high-quality conversion. The chain always ends with
    format=yuv420p so callers don't need to add -pix_fmt yuv420p separately.
    """
    transfer = str(probe.get("color_transfer") or "").lower()
    # HLG (Hybrid Log-Gamma) — used by Sony HLG, Panasonic HLG, broadcast cameras
    if "arib" in transfer or "hlg" in transfer:
        return (
            "zscale=transfer=linear:npl=100,"
            "format=gbrpf32le,"
            "zscale=primaries=bt709,"
            "tonemap=tonemap=hable:desat=0,"
            "zscale=transfer=bt709:matrix=bt709:range=limited,"
            "format=yuv420p"
        )
    # PQ / HDR10 (SMPTE ST 2084)
    if "smpte2084" in transfer or transfer == "pq":
        return (
            "zscale=transfer=linear:npl=1000,"
            "format=gbrpf32le,"
            "zscale=primaries=bt709,"
            "tonemap=tonemap=hable:desat=0,"
            "zscale=transfer=bt709:matrix=bt709:range=limited,"
            "format=yuv420p"
        )
    # S-Log2 / S-Log3 (Sony cinema cameras) and generic BT.2020 wide-gamut
    return (
        "colorspace=all=bt709:iall=bt2020:fast=1,"
        "format=yuv420p"
    )


def _teaser_concat_needs_reencode(meta: Dict[str, Any], expected_duration: float) -> tuple[bool, str]:
    expected_duration = max(0.0, float(expected_duration or 0.0))
    if not isinstance(meta, dict) or expected_duration <= 0:
        return False, ""

    format_duration = max(0.0, float(meta.get("duration_seconds") or 0.0))
    video_duration = max(0.0, float(meta.get("video_duration_seconds") or 0.0))
    fps = max(float(meta.get("avg_fps") or 0.0), float(meta.get("fps") or 0.0))
    try:
        nb_frames = int(meta.get("nb_frames") or 0)
    except Exception:
        nb_frames = 0
    derived_fps = 0.0
    ref_duration = max(video_duration, format_duration)
    if nb_frames > 0 and ref_duration > 0:
        derived_fps = nb_frames / ref_duration
    effective_fps = max(fps, derived_fps)

    if expected_duration >= 60.0:
        if effective_fps > 0 and effective_fps < 10.0:
            return True, f"fps_medio_baixo:{effective_fps:.2f}"
        if nb_frames > 0 and nb_frames < max(30, int(expected_duration * 10.0)):
            return True, f"quadros_insuficientes:{nb_frames}"

    if format_duration > 0 and video_duration > 0:
        tolerance = max(2.0, format_duration * 0.05)
        if video_duration + tolerance < format_duration:
            return True, (
                "video_mais_curto_que_container:"
                f"{video_duration:.3f}s<{format_duration:.3f}s"
            )

    expected_tolerance = _duration_shortfall_tolerance(expected_duration)
    if format_duration > 0 and (format_duration + expected_tolerance) < expected_duration:
        return True, (
            "container_curto_para_planejado:"
            f"{format_duration:.3f}s<{expected_duration:.3f}s"
        )
    if video_duration > 0 and (video_duration + expected_tolerance) < expected_duration:
        return True, (
            "video_curto_para_planejado:"
            f"{video_duration:.3f}s<{expected_duration:.3f}s"
        )
    return False, ""


def _probe_duration(in_path: str) -> float:
    """Return video duration in seconds using ffprobe. Returns 0.0 on failure."""
    m = _probe_metadata(in_path)
    return float(m.get("duration_seconds") or 0)


def _probe_has_audio_stream(in_path: str) -> bool:
    m = _probe_metadata(in_path)
    return bool(m.get("has_audio"))


def _format_media_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    whole = int(seconds)
    hrs = whole // 3600
    mins = (whole % 3600) // 60
    secs = whole % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def _duration_shortfall_tolerance(expected_seconds: float) -> float:
    expected_seconds = max(0.0, float(expected_seconds or 0.0))
    if expected_seconds <= 0:
        return 0.0
    # Aceita pequenas diferenças de arredondamento/VFR no final, mas não truncamentos reais.
    return max(5.0, min(expected_seconds * 0.01, 20.0))


def _is_nearly_full_duration(*, expected_seconds: float, actual_seconds: float) -> bool:
    expected_seconds = max(0.0, float(expected_seconds or 0.0))
    actual_seconds = max(0.0, float(actual_seconds or 0.0))
    if expected_seconds <= 0 or actual_seconds <= 0:
        return False
    return (expected_seconds - actual_seconds) <= _duration_shortfall_tolerance(expected_seconds)


def _is_duration_close(*, expected_seconds: float, actual_seconds: float) -> bool:
    expected_seconds = max(0.0, float(expected_seconds or 0.0))
    actual_seconds = max(0.0, float(actual_seconds or 0.0))
    if expected_seconds <= 0 or actual_seconds <= 0:
        return False
    return abs(actual_seconds - expected_seconds) <= _duration_shortfall_tolerance(expected_seconds)


_MEDIA_CORRUPTION_MARKERS = (
    "partial file",
    "invalid nal unit size",
    "error while decoding",
    "corrupt",
    "packet corrupt",
    "reserved bit set",
    "number of bands exceeds limit",
    "moov atom not found",
    "invalid data found when processing input",
    "input/output error",
    "truncated",
    "corrupt input packet",
    "missing picture",
    # NOTE: "output file is empty" / "nothing was encoded" are intentionally excluded —
    # they are false positives on VBR files where ffmpeg can't seek to a specific timestamp.
)


def _looks_like_media_corruption(stderr_text: str) -> bool:
    lowered = (stderr_text or "").lower()
    return any(marker in lowered for marker in _MEDIA_CORRUPTION_MARKERS)


def _summarize_ffmpeg_stderr(stderr_text: str, *, max_lines: int = 12, max_chars: int = 3500) -> str:
    stderr_text = (stderr_text or "").replace("\r", "\n")
    lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
    if not lines:
        return ""

    interesting_lines: List[str] = []
    seen: set[str] = set()
    error_markers = (
        "error", "invalid", "failed", "partial file", "corrupt", "malformed",
        "trunc", "end of file", "could not", "no such file", "not found",
        "moov atom", "unable", "conversion failed", "non-monoton", "aac",
        "nal unit", "decoder", "muxer", "broken",
    )
    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in error_markers):
            if line not in seen:
                seen.add(line)
                interesting_lines.append(line)

    picked = interesting_lines[-max_lines:] if interesting_lines else lines[-max_lines:]
    summary = "\n".join(picked).strip()
    if len(summary) > max_chars:
        summary = summary[-max_chars:]
    return summary


def _classify_burn_failure(*, stderr_text: str, input_duration: float, output_duration: float) -> Dict[str, str]:
    summary = _summarize_ffmpeg_stderr(stderr_text) or "Conversion failed!"
    lowered = (stderr_text or "").lower()

    if input_duration > 0 and output_duration > 0 and not _is_nearly_full_duration(
        expected_seconds=input_duration,
        actual_seconds=output_duration,
    ):
        return {
            "error": "source_media_corrupt",
            "detail": (
                "O vídeo original parece estar truncado ou corrompido: o processamento só conseguiu "
                f"chegar até {_format_media_clock(output_duration)} de {_format_media_clock(input_duration)}.\n"
                "Reenvie o arquivo original.\n\n"
                f"Detalhe do ffmpeg:\n{summary}"
            ),
        }

    if _looks_like_media_corruption(stderr_text):
        return {
            "error": "source_media_corrupt",
            "detail": (
                "O vídeo original parece estar corrompido ou incompleto. "
                "Tente reenviar o MP4 original.\n\n"
                f"Detalhe do ffmpeg:\n{summary}"
            ),
        }

    return {"error": "ffmpeg_failed", "detail": summary}


def _quick_media_integrity_check(*, in_path: str, expected_duration: float) -> Optional[Dict[str, Any]]:
    """Detect obvious late-file corruption quickly before a long burn starts."""
    expected_duration = max(0.0, float(expected_duration or 0.0))
    if expected_duration <= 0:
        return None

    max_seek = max(0.0, expected_duration - 0.5)
    if max_seek <= 0:
        return None

    sample_duration = 1.5 if expected_duration >= 900 else 2.0
    if expected_duration < 120:
        ratios = [0.50, 0.85]
    elif expected_duration < 600:
        ratios = [0.25, 0.50, 0.75, 0.92]
    else:
        ratios = [0.10, 0.18, 0.25, 0.40, 0.60, 0.85, 0.97]

    checkpoints: List[float] = []
    seen: set[int] = set()
    for ratio in ratios:
        pos = min(max_seek, max(0.0, expected_duration * ratio))
        bucket = int(round(pos * 10))
        if bucket in seen:
            continue
        seen.add(bucket)
        checkpoints.append(pos)

    timeout_s = max(25, min(120, int(sample_duration * 30)))
    for checkpoint in checkpoints:
        cmd = [
            "ffmpeg",
            "-v", "warning",
            "-xerror",
            "-ss", f"{checkpoint:.3f}",
            "-t", f"{sample_duration:.3f}",
            "-i", in_path,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-f", "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            stderr_text = (proc.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return {
                "checkpoint_seconds": checkpoint,
                "detail": "Validação prévia da mídia excedeu o tempo limite.",
                "timed_out": True,
            }

        has_corruption = _looks_like_media_corruption(stderr_text)
        # returncode != 0 alone is not enough — VBR files often can't seek to a specific
        # timestamp and ffmpeg exits non-zero with only "no filtered frames" noise.
        if has_corruption:
            return {
                "checkpoint_seconds": checkpoint,
                "detail": _summarize_ffmpeg_stderr(stderr_text) or f"Falha ao validar trecho em {_format_media_clock(checkpoint)}.",
            }

    return None


def _attempt_truncated_burn_recovery(
    *,
    out_path: str,
    expected_duration: float,
    actual_duration: float,
    crf: int,
    preset: str,
    threads: int,
) -> Optional[Dict[str, Any]]:
    expected_duration = max(0.0, float(expected_duration or 0.0))
    actual_duration = max(0.0, float(actual_duration or 0.0))
    if expected_duration <= 0 or actual_duration <= 0:
        return None
    if _is_nearly_full_duration(expected_seconds=expected_duration, actual_seconds=actual_duration):
        return None

    # Só tenta “resgate” quando ainda temos material útil suficiente.
    min_usable_duration = max(60.0, expected_duration * 0.50)
    if actual_duration < min_usable_duration:
        return None

    pad_duration = expected_duration - actual_duration
    if pad_duration <= _duration_shortfall_tolerance(expected_duration):
        return None

    recovery_crf = max(20, min(int(crf or 26) + 2, 35))
    recovery_preset = "ultrafast"
    rescued_path = out_path + ".rescued.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", out_path,
        "-map", "0:v:0",
        "-vf", f"tpad=stop_mode=clone:stop_duration={pad_duration:.3f}",
        "-threads", str(max(0, int(threads or 0))),
        "-c:v", "libx264", "-crf", str(recovery_crf), "-preset", recovery_preset,
    ]
    if _probe_has_audio_stream(out_path):
        cmd.extend([
            "-map", "0:a:0",
            "-af", f"atrim=end={expected_duration:.3f},apad=whole_dur={expected_duration:.3f}",
            "-c:a", "aac", "-b:a", "128k",
        ])
    else:
        cmd.append("-an")
    cmd.extend([
        "-t", f"{expected_duration:.3f}",
        "-movflags", "+faststart",
        rescued_path,
    ])

    timeout_s = max(300, min(3600, int(expected_duration * 2.0)))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    stderr_text = (proc.stderr or "").strip()
    if proc.returncode != 0:
        print(f"burn-subtitles recovery ffmpeg error: {_summarize_ffmpeg_stderr(stderr_text)}", flush=True)
        return None

    rescued_duration = _probe_duration(rescued_path)
    if not _is_duration_close(expected_seconds=expected_duration, actual_seconds=rescued_duration):
        try:
            os.remove(rescued_path)
        except Exception:
            pass
        print(
            "burn-subtitles recovery produced unexpected duration: "
            f"rescued={rescued_duration:.3f}s expected={expected_duration:.3f}s",
            flush=True,
        )
        return None

    return {
        "path": rescued_path,
        "duration": rescued_duration,
        "warning": (
            "Arquivo original corrompido após "
            f"{_format_media_clock(actual_duration)}; finalizei o vídeo congelando o último frame "
            f"até {_format_media_clock(expected_duration)}. "
            f"Para acelerar a recuperação, usei preset {recovery_preset}."
        ),
    }


def _extract_audio_to_wav(*, in_path: str, out_path: str, enhance_audio: bool = True, quality: str = "standard") -> None:
    """Extrai áudio como WAV PCM mono via pipe:1.
    quality="standard": 16kHz, lowpass=7800 (para modelos small/medium).
    quality="premium":  24kHz, lowpass=11000 (para large-v3, preserva harmônicos).
    Usar pipe impede o ffmpeg de deletar o arquivo em caso de erro no decoder —
    problema comum com AAC não-conformes ('Reserved bit set', 'Number of bands exceeds limit').
    O ffmpeg escreve para stdout; nós redirecionamos para o arquivo, então mesmo que
    o ffmpeg saia com código de erro, o áudio já está no disco.
    """
    is_premium = quality == "premium"
    sample_rate = 24000 if is_premium else 16000
    base_cmd = [
        "ffmpeg", "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt",
        "-i", in_path,
        "-vn", "-ac", "1", "-ar", str(sample_rate),
    ]
    if is_premium:
        # Premium é otimizado para pornô BR em CPU: abre fala baixa sem esmagar
        # gemidos/respiração em ruído branco. Ganho demais aqui aumenta alucinação.
        adult_voice_filter = (
            "highpass=f=70,"
            "lowpass=f=11500,"
            "afftdn=nf=-24,"
            "dynaudnorm=f=150:g=10:p=0.86:m=8,"
            "loudnorm=I=-17:TP=-1.5:LRA=9"
        )
    else:
        adult_voice_filter = (
            "highpass=f=65,"
            "lowpass=f=7800,"
            "afftdn=nf=-25,"
            "dynaudnorm=f=180:g=18:p=0.92:m=10,"
            "loudnorm=I=-18:TP=-1.5:LRA=9"
        )

    attempts: List[List[str]] = []
    if enhance_audio:
        attempts.append(base_cmd + ["-af", adult_voice_filter, "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"])
    attempts.append(base_cmd + ["-c:a", "pcm_s16le", "-f", "wav", "pipe:1"])

    last_stderr = ""
    for idx, cmd in enumerate(attempts):
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass
        with open(out_path, "wb") as fout:
            proc = subprocess.Popen(cmd, stdout=fout, stderr=subprocess.PIPE)
            _, stderr_bytes = proc.communicate()
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        last_stderr = stderr
        lowered = stderr.lower()
        out_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        if out_size > 4096:
            if proc.returncode != 0:
                print(f"[transcribe] WAV pipe ok ({out_size}B), ignorando rc={proc.returncode}: {stderr[-200:]}", flush=True)
            if idx == 0 and enhance_audio:
                print("[transcribe] audio enhance aplicado para fala baixa/adulta", flush=True)
            return
        if "does not contain any stream" in lowered or "stream map 'a'" in lowered:
            raise RuntimeError("missing_audio_stream")
        if idx == 0 and enhance_audio:
            print(f"[transcribe] audio enhance falhou, tentando extração simples: {stderr[-200:]}", flush=True)

    print(f"[transcribe] WAV pipe erro fatal:\n{last_stderr[-800:]}", flush=True)
    raise RuntimeError(last_stderr[-600:] or "ffmpeg_failed")


def _preprocess_audio_for_porn_br_transcription(
    *,
    in_path: str,
    out_path: str,
    enhance_audio: bool = True,
    premium: bool = True,
) -> None:
    """Pré-processa áudio para transcrição adulta PT-BR.

    A meta é inteligibilidade, não "embelezamento": mono PCM, 24 kHz no premium,
    leve redução de ruído e normalização moderada para fala baixa. Evitamos
    compressão agressiva porque ela transforma gemido/respiração em falso texto.
    """
    _extract_audio_to_wav(
        in_path=in_path,
        out_path=out_path,
        enhance_audio=enhance_audio,
        quality="premium" if premium else "standard",
    )


def _extract_audio_to_aac(*, in_path: str, out_path: str, enhance_audio: bool = True) -> None:
    """Extrai áudio como AAC 32kbps para APIs (OpenAI/Groq, limite 25MB).
    Two-pass: primeiro extrai WAV via pipe (tolerante a erros no input AAC),
    depois re-encoda WAV→AAC (sempre funciona pois input é PCM limpo).
    """
    wav_tmp = out_path + ".wav"
    try:
        _extract_audio_to_wav(in_path=in_path, out_path=wav_tmp, enhance_audio=enhance_audio)
        proc2 = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_tmp,
             "-c:a", "aac", "-b:a", "32k", out_path],
            capture_output=True, text=True,
        )
        if proc2.returncode != 0:
            raise RuntimeError(proc2.stderr[-600:] or "aac_transcode_failed")
    finally:
        if os.path.exists(wav_tmp):
            os.unlink(wav_tmp)


def _assemblyai_language_code(lang: str) -> str:
    v = _norm_lang_code(lang)
    return {
        "pt": "pt",
        "en": "en_us",
        "es": "es",
        "fr": "fr",
        "de": "de",
        "it": "it",
        "ja": "ja",
        "zh": "zh",
        "ko": "ko",
    }.get(v, v)


def _assemblyai_words_to_segments(words: List[Dict[str, Any]], *, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    clean_words: List[Dict[str, Any]] = []
    for raw in words or []:
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(raw.get("confidence") if raw.get("confidence") is not None else 1.0)
        except Exception:
            confidence = 1.0
        if min_confidence > 0.0 and confidence < min_confidence:
            continue
        try:
            start_ms = float(raw.get("start") or 0.0)
            end_ms = float(raw.get("end") or start_ms)
        except Exception:
            continue
        clean_words.append({
            "text": text,
            "start": max(0.0, start_ms / 1000.0),
            "end": max(0.0, end_ms / 1000.0),
            "confidence": confidence,
        })

    if not clean_words:
        return []

    segments: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(w["text"] for w in current).strip()
        if text:
            segments.append({
                "start": float(current[0]["start"]),
                "end": float(current[-1]["end"]),
                "text": text,
                "confidence": min(float(w.get("confidence", 1.0)) for w in current),
            })
        current = []

    for word in clean_words:
        if current:
            gap = float(word["start"]) - float(current[-1]["end"])
            duration = float(current[-1]["end"]) - float(current[0]["start"])
            prev_text = str(current[-1].get("text") or "")
            if gap > 0.9 or duration >= 7.5 or prev_text.endswith((".", "!", "?", "…")):
                flush_current()
        current.append(word)
    flush_current()
    return segments


def _deepgram_language_code(lang: str) -> str:
    v = _norm_lang_code(lang)
    return {
        "pt": "pt-BR",
        "en": "en-US",
        "es": "es",
        "fr": "fr",
        "de": "de",
        "it": "it",
        "ja": "ja",
        "zh": "zh",
    }.get(v, v)


def _deepgram_words_to_segments(words: List[Dict[str, Any]], *, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for raw in words or []:
        text = str(raw.get("punctuated_word") or raw.get("word") or "").strip()
        if not text:
            continue
        try:
            confidence = float(raw.get("confidence") if raw.get("confidence") is not None else 1.0)
        except Exception:
            confidence = 1.0
        if min_confidence > 0.0 and confidence < min_confidence:
            folded = _fold_text(text)
            # Mantém vocalizações/dirty talk comuns mesmo com confiança baixa:
            # são exatamente os tokens que ASR costuma tratar como ruído.
            if folded not in _PT_TRANSCRIPT_KEEP_WORDS and folded not in {"ai", "ah", "ahh", "hum", "hmm", "ui", "oi"}:
                continue
        try:
            start = float(raw.get("start") or 0.0)
            end = float(raw.get("end") or start)
        except Exception:
            continue
        normalized.append({
            "text": text,
            "start": max(0.0, start),
            "end": max(0.0, end),
            "confidence": confidence,
        })

    if not normalized:
        return []

    segments: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(w["text"] for w in current).strip()
        if text:
            segments.append({
                "start": float(current[0]["start"]),
                "end": float(current[-1]["end"]),
                "text": text,
                "confidence": min(float(w.get("confidence", 1.0)) for w in current),
            })
        current = []

    for word in normalized:
        if current:
            gap = float(word["start"]) - float(current[-1]["end"])
            duration = float(current[-1]["end"]) - float(current[0]["start"])
            text_len = len(" ".join(w["text"] for w in current))
            prev_text = str(current[-1].get("text") or "")
            if gap > 0.85 or duration >= 6.5 or text_len >= 54 or prev_text.endswith((".", "!", "?", "…")):
                flush_current()
        current.append(word)
    flush_current()
    return segments


async def _transcribe_deepgram(audio_path: str, language: str = "", *, include_vocalizations: bool = False) -> Dict[str, Any]:
    api_key = (
        (settings_get(key="token:deepgram") or {}).get("value")
        or os.environ.get("DEEPGRAM_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError("missing_deepgram_token")

    lang_code = _deepgram_language_code(language)
    # Nova-3 já suporta pt-BR e keyterm prompting; é o melhor default para
    # legenda queimável porque devolve timestamps por palavra.
    model = os.environ.get("DEEPGRAM_STT_MODEL", "nova-3").strip() or "nova-3"
    params: List[tuple[str, str]] = [
        ("model", model),
        ("language", lang_code or "pt-BR"),
        ("punctuate", "true"),
        ("smart_format", "false"),
        ("profanity_filter", "false"),
        ("utterances", "true"),
        ("filler_words", "true" if include_vocalizations else "false"),
        ("detect_language", "false"),
    ]
    if include_vocalizations:
        adult_terms = [
            "ai", "ah", "ahh", "hum", "hmm", "ui", "isso", "vai", "mete",
            "gostoso", "gostosa", "delicia", "tesao", "porra", "caralho",
            "goza", "leite", "chupa", "buceta", "pau", "pica", "me enche de leite",
            "goza pra mim", "que delicia", "que gostoso",
        ]
        if model.startswith("nova-3"):
            for term in adult_terms:
                params.append(("keyterm", term))
        else:
            for term in adult_terms:
                params.append(("keywords", f"{term}:2"))

    url = "https://api.deepgram.com/v1/listen"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/mp4",
    }
    timeout = httpx.Timeout(1800.0, connect=30.0, write=900.0, read=1800.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(audio_path, "rb") as f:
            response = await client.post(url, headers=headers, params=params, content=f.read())
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        try:
            body = response.json()
            detail = body.get("err_msg") or body.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(f"deepgram_failed:{response.status_code}:{detail[:500]}")

    result = response.json() or {}
    alt: Dict[str, Any] = {}
    try:
        channels = result.get("results", {}).get("channels") or []
        if channels:
            alternatives = channels[0].get("alternatives") or []
            if alternatives:
                alt = alternatives[0] or {}
    except Exception:
        alt = {}
    transcript_text = str(alt.get("transcript") or "").strip()
    words = alt.get("words") or []
    segments = _deepgram_words_to_segments(words, min_confidence=0.0)
    if not segments and transcript_text:
        duration = float((result.get("metadata") or {}).get("duration") or 0.0)
        segments = [{
            "start": 0.0,
            "end": duration,
            "text": transcript_text,
        }]
    text = " ".join((s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip()) or transcript_text
    return {
        "language": _norm_lang_code(language or "pt"),
        "text": text,
        "segments": segments,
        "model": model,
        "request_id": (result.get("metadata") or {}).get("request_id"),
        "duration": (result.get("metadata") or {}).get("duration"),
        "word_count_raw": len(words),
        "word_count_kept": sum(len((s.get("text") or "").split()) for s in segments),
    }


async def _transcribe_assemblyai(audio_path: str, language: str = "", *, include_vocalizations: bool = False) -> Dict[str, Any]:
    api_key = (
        (settings_get(key="token:assemblyai") or {}).get("value")
        or os.environ.get("ASSEMBLYAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError("missing_assemblyai_token")

    base_url = os.environ.get("ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com").rstrip("/")
    headers = {"Authorization": api_key}
    timeout = httpx.Timeout(1800.0, connect=30.0, write=600.0, read=1800.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        upload = await client.post(
            f"{base_url}/v2/upload",
            headers={**headers, "Content-Type": "application/octet-stream"},
            content=audio_bytes,
        )
        if upload.status_code >= 400:
            raise RuntimeError(f"assemblyai_upload_failed:{upload.status_code}:{(upload.text or '')[:300]}")
        upload_url = (upload.json() or {}).get("upload_url")
        if not upload_url:
            raise RuntimeError("assemblyai_upload_missing_url")

        payload: Dict[str, Any] = {
            "audio_url": upload_url,
            "speech_models": ["universal-3-pro", "universal-2"],
            "filter_profanity": False,
            "punctuate": True,
            "format_text": True,
            "disfluencies": bool(include_vocalizations),
            # Não use limite alto aqui: AssemblyAI aborta o job inteiro quando
            # a fala global do áudio fica abaixo do threshold. Para vídeos com
            # fala baixa, filtramos depois por confiança das palavras.
            "speech_threshold": 0.20,
        }
        lang_code = _assemblyai_language_code(language)
        if lang_code:
            payload["language_code"] = lang_code
        else:
            payload["language_detection"] = True
            payload["language_confidence_threshold"] = 0.45
        if include_vocalizations:
            pt_terms = [
                "ah", "ahh", "ai", "hum", "hmm", "uh", "uhm",
                "goza", "gozei", "gostoso", "delicia", "porra",
            ]
            en_terms = ["ah", "ahh", "hmm", "uh", "uhm", "fuck", "eat it", "harder", "yes"]
            es_terms = ["ah", "ay", "hum", "delicia", "rico", "duro", "ven"]
            if lang_code == "pt":
                payload["keyterms_prompt"] = pt_terms
            elif lang_code == "en_us":
                payload["keyterms_prompt"] = en_terms
            elif lang_code == "es":
                payload["keyterms_prompt"] = es_terms
            else:
                payload["keyterms_prompt"] = pt_terms + en_terms[:5] + es_terms[:4]

        submit = await client.post(f"{base_url}/v2/transcript", headers=headers, json=payload)
        if submit.status_code >= 400:
            raise RuntimeError(f"assemblyai_submit_failed:{submit.status_code}:{(submit.text or '')[:300]}")
        transcript = submit.json() or {}
        transcript_id = transcript.get("id")
        if not transcript_id:
            raise RuntimeError("assemblyai_missing_transcript_id")

        deadline = time.time() + 1800
        while True:
            status = str(transcript.get("status") or "").lower()
            if status == "completed":
                break
            if status == "error":
                raise RuntimeError(f"assemblyai_transcript_error:{transcript.get('error') or 'unknown_error'}")
            if time.time() > deadline:
                raise RuntimeError("assemblyai_timeout")
            await asyncio.sleep(3)
            poll = await client.get(f"{base_url}/v2/transcript/{transcript_id}", headers=headers)
            if poll.status_code >= 400:
                raise RuntimeError(f"assemblyai_poll_failed:{poll.status_code}:{(poll.text or '')[:300]}")
            transcript = poll.json() or {}

    words = transcript.get("words") or []
    segments = _assemblyai_words_to_segments(words)
    if not segments and transcript.get("text"):
        segments = [{
            "start": 0.0,
            "end": float(transcript.get("audio_duration") or 0.0),
            "text": str(transcript.get("text") or "").strip(),
        }]
    text = " ".join((s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip())
    return {
        "language": _norm_lang_code(transcript.get("language_code") or language or "auto"),
        "text": text,
        "segments": segments,
        "transcript_id": transcript.get("id"),
        "language_confidence": transcript.get("language_confidence"),
        "speech_model": transcript.get("speech_model") or "universal-3-pro",
        "word_count_raw": len(words),
        "word_count_kept": sum(len((s.get("text") or "").split()) for s in segments),
    }


def _plain_text_to_timed_segments(
    text: str,
    *,
    start_offset: float = 0.0,
    duration_seconds: float = 0.0,
    chunk_words: int = 10,
    timing_source: str = "synthetic_plain_text",
    spread_to_duration: bool = False,
) -> List[Dict[str, Any]]:
    """Cria segmentos estimados quando o provedor retorna apenas texto puro."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    words = clean.split()
    if not words:
        return []
    duration = max(float(duration_seconds or 0.0), len(words) / 2.4)
    word_chunks = [
        " ".join(words[idx:idx + max(4, chunk_words)]).strip()
        for idx in range(0, len(words), max(4, chunk_words))
    ]
    word_chunks = [chunk for chunk in word_chunks if chunk]
    segments: List[Dict[str, Any]] = []

    if spread_to_duration and duration_seconds and len(word_chunks) > 1:
        # OpenRouter currently returns plain text without per-word timing. The
        # old fallback compressed all text into the first seconds of each
        # 5-minute chunk. For burn, spreading cues across the full chunk is much
        # safer: estimated, but not visually frozen/desynced by minutes.
        window = max(1.0, float(duration_seconds or duration))
        cue_duration = max(2.2, min(7.5, (window / max(len(word_chunks), 1)) * 0.45))
        usable = max(0.0, window - cue_duration)
        step = usable / max(len(word_chunks) - 1, 1)
        for pos, chunk in enumerate(word_chunks):
            start = start_offset + (pos * step)
            end = min(start_offset + window, start + cue_duration)
            item = {"start": start, "end": max(end, start + 1.2), "text": chunk}
            if timing_source:
                item["timing_source"] = timing_source
            segments.append(item)
        return segments

    words_per_sec = max(1.35, min(3.2, len(words) / duration))
    cursor = 0
    for chunk in word_chunks:
        chunk_len = len(chunk.split())
        start = start_offset + (cursor / words_per_sec)
        end = start_offset + ((cursor + chunk_len) / words_per_sec)
        cursor += chunk_len
        if end <= start:
            end = start + max(1.2, chunk_len / 2.4)
        item = {"start": start, "end": end, "text": chunk}
        if timing_source:
            item["timing_source"] = timing_source
        segments.append(item)
    return segments


def _split_audio_for_openrouter_stt(audio_path: str, chunk_dir: str, *, segment_time: int = 300) -> List[str]:
    pattern = os.path.join(chunk_dir, "openrouter_stt_%03d.wav")
    proc = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-f", "segment",
            "-segment_time", str(max(60, int(segment_time))),
            "-reset_timestamps", "1",
            pattern,
        ],
        capture_output=True,
        text=True,
    )
    chunks = sorted(
        os.path.join(chunk_dir, name)
        for name in os.listdir(chunk_dir)
        if name.startswith("openrouter_stt_") and name.endswith(".wav")
    )
    chunks = [p for p in chunks if os.path.getsize(p) > 512]
    if proc.returncode != 0 or not chunks:
        detail = (proc.stderr or "").strip()[-600:] or "openrouter_stt_split_failed"
        print(f"[transcribe] OpenRouter STT split fallback: {detail}", flush=True)
        return [audio_path]
    return chunks


async def _openrouter_stt_request(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    audio_path: str,
    model: str,
    language: str = "",
) -> Dict[str, Any]:
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(audio_path)[1].lower().lstrip(".") or "wav"
    audio_format = "wav" if ext not in {"mp3", "m4a", "wav", "webm", "ogg", "flac"} else ext
    payload: Dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "input_audio": {
            "data": audio_b64,
            "format": audio_format,
        },
    }
    if language:
        payload["language"] = language
        if _norm_lang_code(language) == "pt":
            payload["prompt"] = PORN_BR_WHISPER_INITIAL_PROMPT
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://caripost.n8nmikael.com.br/",
        "X-Title": "MetaPorn Admin",
    }
    response = await client.post(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        headers=headers,
        json=payload,
    )
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        try:
            body = response.json()
            detail = body.get("error", {}).get("message") or body.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(f"openrouter_stt_failed:{response.status_code}:{detail[:500]}")
    return response.json() or {}


async def _transcribe_openrouter_stt(
    audio_path: str,
    language: str = "",
    *,
    duration_seconds: float = 0.0,
) -> Dict[str, Any]:
    api_key = (
        (settings_get(key="token:openrouter") or {}).get("value")
        or os.environ.get("OPENROUTER_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError("missing_openrouter_token")
    model = os.environ.get("OPENROUTER_STT_MODEL", "openai/whisper-large-v3").strip() or "openai/whisper-large-v3"
    total_duration = float(duration_seconds or 0.0)
    if total_duration <= 0:
        try:
            total_duration = float((_probe_metadata(audio_path) or {}).get("duration_seconds") or 0.0)
        except Exception:
            total_duration = 0.0

    with tempfile.TemporaryDirectory(prefix="openrouter-stt-", dir=_preferred_tmpdir_root("transcribe")) as chunk_dir:
        chunk_paths = [audio_path]
        if total_duration > 420 or os.path.getsize(audio_path) > 16 * 1024 * 1024:
            try:
                openrouter_chunk_seconds = int(os.environ.get("OPENROUTER_STT_CHUNK_SECONDS", "120") or "120")
            except Exception:
                openrouter_chunk_seconds = 120
            chunk_paths = _split_audio_for_openrouter_stt(
                audio_path,
                chunk_dir,
                segment_time=max(60, min(openrouter_chunk_seconds, 300)),
            )

        timeout = httpx.Timeout(240.0, connect=20.0, write=180.0, read=240.0)
        segments: List[Dict[str, Any]] = []
        texts: List[str] = []
        offset = 0.0
        attempts: List[Dict[str, Any]] = []
        def _append_text_segments(chunk_text: str, *, base_offset: float, chunk_duration: float) -> None:
            clean_text = str(chunk_text or "").strip()
            if not clean_text:
                return
            texts.append(clean_text)
            segments.extend(_plain_text_to_timed_segments(
                clean_text,
                start_offset=base_offset,
                duration_seconds=chunk_duration,
                timing_source="synthetic_openrouter_chunk",
                spread_to_duration=True,
            ))

        async with httpx.AsyncClient(timeout=timeout) as client:
            async def _retry_openrouter_subchunks(chunk_path: str, *, base_offset: float, chunk_duration: float, label: str) -> bool:
                retry_dir = os.path.join(chunk_dir, f"retry_{len(attempts)}")
                os.makedirs(retry_dir, exist_ok=True)
                retry_paths = _split_audio_for_openrouter_stt(
                    chunk_path,
                    retry_dir,
                    segment_time=60,
                )
                if not retry_paths or (len(retry_paths) == 1 and os.path.abspath(retry_paths[0]) == os.path.abspath(chunk_path)):
                    return False
                ok_any = False
                retry_offset = base_offset
                for idx, retry_path in enumerate(retry_paths):
                    try:
                        retry_probe = await asyncio.to_thread(_probe_metadata, retry_path)
                        retry_duration = float(retry_probe.get("duration_seconds") or 0.0)
                    except Exception:
                        retry_duration = min(60.0, max(1.0, chunk_duration))
                    try:
                        retry_result = await _openrouter_stt_request(
                            client,
                            api_key=api_key,
                            audio_path=retry_path,
                            model=model,
                            language=language,
                        )
                        retry_text = str(retry_result.get("text") or "").strip()
                        attempts.append({
                            "status": "ok" if retry_text else "empty",
                            "chars": len(retry_text),
                            "duration": retry_duration,
                            "offset": retry_offset,
                            "label": f"{label}.retry{idx}",
                        })
                        if retry_text:
                            _append_text_segments(retry_text, base_offset=retry_offset, chunk_duration=retry_duration)
                            ok_any = True
                    except Exception as exc:
                        attempts.append({
                            "status": "error",
                            "detail": _safe_error_detail(exc, "openrouter_stt_failed")[:240],
                            "duration": retry_duration,
                            "offset": retry_offset,
                            "label": f"{label}.retry{idx}",
                        })
                        print(f"[transcribe] openrouter stt retry chunk failed: {exc}", flush=True)
                    retry_offset += max(0.0, retry_duration)
                return ok_any

            for idx, chunk_path in enumerate(chunk_paths):
                try:
                    chunk_probe = await asyncio.to_thread(_probe_metadata, chunk_path)
                    chunk_duration = float(chunk_probe.get("duration_seconds") or 0.0)
                except Exception:
                    chunk_duration = total_duration if len(chunk_paths) == 1 else 300.0
                chunk_label = f"chunk{idx}"
                try:
                    result = await _openrouter_stt_request(
                        client,
                        api_key=api_key,
                        audio_path=chunk_path,
                        model=model,
                        language=language,
                    )
                    chunk_text = str(result.get("text") or "").strip()
                    attempts.append({
                        "status": "ok" if chunk_text else "empty",
                        "chars": len(chunk_text),
                        "duration": chunk_duration,
                        "offset": offset,
                        "label": chunk_label,
                    })
                    if chunk_text:
                        _append_text_segments(chunk_text, base_offset=offset, chunk_duration=chunk_duration)
                    elif chunk_duration >= 70.0:
                        await _retry_openrouter_subchunks(
                            chunk_path,
                            base_offset=offset,
                            chunk_duration=chunk_duration,
                            label=chunk_label,
                        )
                except Exception as exc:
                    attempts.append({
                        "status": "error",
                        "detail": _safe_error_detail(exc, "openrouter_stt_failed")[:240],
                        "duration": chunk_duration,
                        "offset": offset,
                        "label": chunk_label,
                    })
                    print(f"[transcribe] openrouter stt chunk failed: {exc}", flush=True)
                    if chunk_duration >= 70.0:
                        await _retry_openrouter_subchunks(
                            chunk_path,
                            base_offset=offset,
                            chunk_duration=chunk_duration,
                            label=chunk_label,
                        )
                offset += max(0.0, chunk_duration)

    text = " ".join(t for t in texts if t).strip()
    if not text:
        details = "; ".join(str(a.get("detail") or a.get("status")) for a in attempts[-3:])
        raise RuntimeError(f"openrouter_stt_empty:{details or 'empty'}")
    return {
        "language": language or "auto",
        "text": text,
        "segments": segments or _plain_text_to_timed_segments(text, duration_seconds=total_duration),
        "model": model,
        "chunks": len(attempts),
        "chunk_fail_count": sum(1 for a in attempts if a.get("status") == "error"),
        "chunk_empty_count": sum(1 for a in attempts if a.get("status") == "empty"),
        "attempts": attempts,
        "timing_quality": "synthetic_spread_estimated",
        "burn_safe": True,
        "timing_warning": (
            "OpenRouter STT retornou texto sem timestamps reais; os tempos foram reespalhados pelo bloco. "
            "É seguro para queima visual, mas não é alinhamento palavra-a-palavra."
        ),
    }


def _detect_scene_timestamps(in_path: str, threshold: float, duration: float, quick: bool = False) -> List[float]:
    """Run ffmpeg scene detection pass, return timestamps where scene score > threshold."""
    if quick:
        # Analyze context: cap at 45s, use 240p for speed
        scene_timeout = min(45, max(15, int(duration * 0.1)))
        scale = "240"
    else:
        scene_timeout = max(300, int(duration * 3) + 120)
        scale = "360"
    proc = subprocess.run(
        [
            "ffmpeg",
            "-i", in_path,
            "-vf", f"scale=-2:{scale}:flags=bilinear,select='gt(scene,{threshold})',showinfo",
            "-vsync", "vfr",
            "-f", "null",
            "/dev/null",
        ],
        capture_output=True,
        text=True,
        timeout=scene_timeout,
    )
    timestamps: List[float] = []
    for line in (proc.stderr or "").splitlines():
        if "pts_time:" in line and "showinfo" in line.lower():
            m = re.search(r"pts_time:(\d+\.?\d*)", line)
            if m:
                t = float(m.group(1))
                if 0 < t <= duration:
                    timestamps.append(t)
    return sorted(set(timestamps))


def _thin_timestamps(timestamps: List[float], min_gap: float, max_count: int) -> List[float]:
    """Filter timestamps: enforce minimum gap between frames, keep at most max_count."""
    result: List[float] = []
    last = -9999.0
    for t in sorted(timestamps):
        if t - last >= min_gap:
            result.append(t)
            last = t
        if len(result) >= max_count:
            break
    return result


def _frame_indexes_to_timestamps(indexes: List[int], frames_count: int, duration: float) -> List[float]:
    """Map selected frame indexes (from screenshot grid) to approximate video timestamps."""
    if duration <= 0 or not indexes:
        return []

    # If frontend couldn't send frames_count, infer from max selected index.
    if frames_count <= 1:
        try:
            frames_count = max(indexes) + 1
        except Exception:
            frames_count = 0
    if frames_count <= 1:
        return []

    out: List[float] = []
    seen: set = set()
    max_idx = frames_count - 1
    for raw_idx in indexes:
        try:
            idx = int(raw_idx)
        except Exception:
            continue
        if idx < 0:
            continue
        idx = min(idx, max_idx)
        if idx in seen:
            continue
        seen.add(idx)
        # Use midpoints instead of exact edges so frame 0 does not seek to t=0,
        # which commonly yields black frames/fades on HQ extraction.
        ratio = ((idx + 1) / (frames_count + 1)) if max_idx > 0 else 0.5
        t = max(0.0, min(duration - 0.05, duration * ratio))
        out.append(t)
    out.sort()
    return out


def _pick_frame_timestamp_by_index(
    frame_index: int,
    frames_count: int,
    duration: float,
    timestamps: List[Any],
) -> Optional[float]:
    """Pick the best timestamp for a screenshot index from a timestamp list."""
    if duration <= 0 or not timestamps:
        return None

    cleaned: List[float] = []
    for raw in timestamps:
        try:
            t = float(raw)
        except Exception:
            continue
        if t < 0:
            continue
        cleaned.append(max(0.0, min(duration - 0.05, t)))

    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]

    try:
        src_idx = max(0, int(frame_index))
    except Exception:
        src_idx = 0

    src_max = max(0, int(frames_count or len(cleaned)) - 1)
    dst_max = len(cleaned) - 1
    if src_max > 0 and dst_max > 0:
        mapped_idx = round(min(src_idx, src_max) * dst_max / src_max)
    else:
        mapped_idx = min(src_idx, dst_max)
    return cleaned[max(0, min(mapped_idx, dst_max))]


def _build_intelligent_adult_keyframe_timestamps(
    *,
    in_path: str,
    duration: float,
    max_frames: int = 10,
    scene_threshold: float = 0.32,
    _precomputed_cut_points: Optional[List[float]] = None,
    quick: bool = False,
) -> tuple[List[float], List[float]]:
    """Return (filtered_timestamps, raw_cut_points) for keyframe extraction.

    Accepts pre-computed cut points to avoid a duplicate scene detection pass.
    """
    if duration <= 0:
        return [], []

    if _precomputed_cut_points is not None:
        timestamps = list(_precomputed_cut_points)
    else:
        try:
            timestamps = _detect_scene_timestamps(in_path, scene_threshold, duration, quick=quick)
        except Exception:
            timestamps = []

    raw_cut_points = list(timestamps)

    if len(timestamps) < 4:
        for r in [0.05, 0.15, 0.30, 0.50, 0.65, 0.80, 0.92]:
            t = duration * r
            if not any(abs(t - ex) < 8.0 for ex in timestamps):
                timestamps.append(t)
        timestamps.sort()

    filtered = _thin_timestamps(timestamps, min_gap=5.0, max_count=max_frames)
    return [max(0.0, min(duration - 0.05, float(t))) for t in filtered], raw_cut_points


def _extract_intelligent_adult_keyframes(
    *,
    in_path: str,
    out_dir: str,
    duration: float,
    max_frames: int = 10,
    scene_threshold: float = 0.32,
    probe: Optional[Dict[str, Any]] = None,
    _precomputed_cut_points: Optional[List[float]] = None,
    quick: bool = False,
) -> tuple[List[Dict[str, Any]], List[float]]:
    """Extract keyframes at visual scene changes using ffmpeg scene detection.

    Falls back to evenly-spaced frames if too few scene changes are detected.
    Returns (frames, raw_cut_points). Applies HDR→SDR tone-mapping if source is HDR.
    Uses a single batched ffmpeg call for all frames to avoid repeated file opens.
    """
    filtered, raw_cut_points = _build_intelligent_adult_keyframe_timestamps(
        in_path=in_path,
        duration=duration,
        max_frames=max_frames,
        scene_threshold=scene_threshold,
        _precomputed_cut_points=_precomputed_cut_points,
        quick=quick,
    )

    if not filtered:
        return [], raw_cut_points

    hdr_filter = _build_hdr_to_sdr_filter(probe) if (probe and _is_hdr_source(probe)) else ""
    # Build vf chain: optional HDR→SDR, then scale to 480p for Vision API
    scale_filter = "scale=-2:min(ih\\,480):flags=bilinear"
    vf_chain = f"{hdr_filter},{scale_filter}" if hdr_filter else scale_filter

    frames: List[Dict[str, Any]] = []

    if not quick and len(filtered) <= 30:
        # Batched: single ffmpeg decode pass with select filter (slow but accurate)
        select_expr = "+".join(
            f"between(t,{max(0.0, t - 0.1):.3f},{t + 0.1:.3f})" for t in filtered
        )
        pattern_path = os.path.join(out_dir, "kf_%03d.jpg")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", in_path,
                "-vf", f"{vf_chain},select='{select_expr}',vsync=0",
                "-q:v", "3",
                pattern_path,
            ],
            capture_output=True,
            timeout=max(120, int(duration * 2) + 60),
        )
        for i, t in enumerate(filtered):
            out_path = os.path.join(out_dir, f"kf_{i + 1:03d}.jpg")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                frames.append({"path": out_path, "timestamp": round(float(t), 3)})
    else:
        # Fast individual seeks with -ss before -i (keyframe seek, instant even on long videos)
        for i, t in enumerate(filtered):
            out_path = os.path.join(out_dir, f"kf_{i:03d}.jpg")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-ss", f"{t:.3f}",
                        "-i", in_path,
                        "-frames:v", "1",
                        "-vf", vf_chain,
                        "-q:v", "3",
                        out_path,
                    ],
                    capture_output=True,
                    timeout=30,
                )
            except Exception:
                pass
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                frames.append({"path": out_path, "timestamp": round(float(t), 3)})

    return frames, raw_cut_points


def _file_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _format_srt_timestamp(seconds: float) -> str:
    # whisper pode retornar None ou negativo em caso de erro
    seconds = max(0.0, seconds or 0.0)
    td = int(seconds * 1000)
    ms = td % 1000
    sec = (td // 1000) % 60
    mnt = (td // 60000) % 60
    hrs = (td // 3600000)
    return f"{hrs:02d}:{mnt:02d}:{sec:02d},{ms:03d}"


def _shift_srt(srt_content: str, delay_secs: float) -> str:
    """Desloca todos os timestamps do SRT em delay_secs segundos (positivo = atrasa, negativo = adianta)."""
    if not delay_secs:
        return srt_content

    def _shift_ts(m: re.Match) -> str:
        ts = m.group(0)
        h, mn, rest = ts.split(":", 2)
        s, ms = rest.split(",", 1)
        total = int(h) * 3600 + int(mn) * 60 + int(s) + int(ms) / 1000 + delay_secs
        total = max(0.0, total)
        h2 = int(total // 3600)
        mn2 = int((total % 3600) // 60)
        s2 = int(total % 60)
        ms2 = int(round((total - int(total)) * 1000))
        return f"{h2:02d}:{mn2:02d}:{s2:02d},{ms2:03d}"

    return re.sub(r"\d{2}:\d{2}:\d{2},\d{3}", _shift_ts, srt_content)


def _format_srt(segments: List[Dict[str, Any]]) -> str:
    if not segments:
        return ""
    lines = []
    for i, s in enumerate(segments, start=1):
        start = _format_srt_timestamp(s.get("start", 0.0))
        end = _format_srt_timestamp(s.get("end", 0.0))
        text = (s.get("text") or "").strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _format_srt_premium(segments: List[Dict[str, Any]]) -> str:
    """SRT premium: merge segments <1.5s, capitalize sentences, smart line breaks."""
    if not segments:
        return ""

    merged: List[Dict[str, Any]] = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        end = s.get("end", 0.0)
        start = s.get("start", 0.0)
        dur = end - start
        if merged and dur < 1.5:
            prev = merged[-1]
            prev["end"] = max(prev["end"], end)
            gap = start - prev["end"]
            if gap < 0.5:
                prev["text"] += " " + text
                continue
        merged.append({"start": start, "end": end, "text": text})

    lines = []
    for i, s in enumerate(merged, start=1):
        start = _format_srt_timestamp(s["start"])
        end = _format_srt_timestamp(s["end"])
        raw = s["text"]

        raw = raw[0].upper() + raw[1:] if raw else raw

        if len(raw) > 40:
            mid = raw.rfind(" ", 0, 40)
            if mid > 20:
                raw = raw[:mid] + "\n" + raw[mid + 1:]

        lines.append(f"{i}\n{start} --> {end}\n{raw}\n")
    return "\n".join(lines)


_OPEN_ACCESS_SEEN: set = set()


def _audit_open_access(req: Request) -> None:
    """MAPEAMENTO p/ ativar auth depois (sem quebrar integrações): registra 1x por rota+cliente quem usa o
    acesso ABERTO atual, SEM bloquear. Grava em /data/open_access_audit.log. Browser = UA Mozilla; integrações
    (n8n, python-requests, axios…) = UA próprio → mostra exatamente o que precisa de chave antes de fechar."""
    try:
        ua = (req.headers.get("user-agent") or "")[:160]
        parts = [p for p in req.url.path.split("/") if p][:2]
        route = "/" + "/".join(parts)
        sig = route + "|" + ua[:48]
        if sig in _OPEN_ACCESS_SEEN:
            return
        _OPEN_ACCESS_SEEN.add(sig)
        ip = req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")
        with open("/data/open_access_audit.log", "a") as _f:
            _f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "method": req.method,
                                 "path": req.url.path, "route": route, "ua": ua, "ip": ip}) + "\n")
    except Exception:
        pass


def _require_api_key(req: Request) -> Optional[dict]:
    """Return error dict if not authorized, else None.

    Accepts either:
      - X-API-Key header / ?api_key= query param (legacy programmatic access)
      - X-Session-Token header with a valid JWT (browser session)
    """
    # Always accept valid session tokens regardless of API_KEY config
    session_token = req.headers.get("x-session-token")
    if session_token and verify_session_token(session_token):
        return None

    if not API_KEY:
        # No API key configured and no valid session. Fail CLOSED unless a dev
        # explicitly opted into open access. This is what keeps "dev-mode closed"
        # true even if the key env is ever dropped by a redeploy.
        if ALLOW_OPEN_ACCESS:
            _audit_open_access(req)   # dev opt-in: MAPEIA (não bloqueia) quem usa o acesso aberto
            return None
        return {"error": "unauthorized", "detail": "api_not_configured"}

    provided = req.headers.get("x-api-key") or req.query_params.get("api_key")
    if provided != API_KEY:
        return {"error": "unauthorized", "detail": "missing_or_invalid_api_key"}

    return None


# Serve legacy admin UI under /ui (kept for reference)
app.mount("/ui", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "ui"), html=True), name="ui")

# Serve MetaPorn OS design under /os
app.mount("/os", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "os"), html=True), name="os")

# Serve company uploads (logos, mood board references)
_uploads_dir = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


@app.get("/")
def root_redirect():
    # Root → redirect to /os/ so relative asset paths resolve correctly
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/os/", status_code=302)


@app.get("/robots.txt")
def robots_txt():
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    provider: Optional[str] = None
    lang: Optional[str] = None
    text: str = ""
    segments: Optional[List[TranscriptSegment]] = None
    srt: Optional[str] = None


class AnalyzeRequest(BaseModel):
    # Base
    video_object_key: Optional[str] = None
    video_url: Optional[str] = None
    video_metadata: Dict[str, Any] = Field(default_factory=dict)
    original_filename: str = ""
    transcript: Optional[Transcript] = None

    # Conteúdo social (Caripost)
    creator_id: Optional[str] = None
    platforms: List[str] = Field(default_factory=lambda: ["youtube", "instagram"])
    stt_provider: Optional[str] = None

    # Referências e Filtros (legado adulto — ignorado)
    ref_sites: List[str] = Field(default_factory=lambda: ["xvideos"])
    ref_actor: Optional[str] = None
    ref_actor_count: Optional[str] = None
    ref_country: Optional[str] = None
    ref_category: Optional[str] = None
    ref_studio: Optional[str] = None
    ref_dur_min: Optional[int] = None
    ref_dur_max: Optional[int] = None
    ref_views_min: Optional[int] = None
    ref_views_max: Optional[int] = None
    ref_comm_min: Optional[int] = None
    ref_likes_min: Optional[int] = None

    # knobs
    limit: int = Field(default=20, ge=1, le=200)


def _setup_s3_cors():
    # CORS is configured at MinIO server level via:
    #   mc admin config set minio/ api cors_allow_origin=https://caripost.n8nmikael.com.br
    # PutBucketCors S3 API is not supported by MinIO — silently skip.
    pass


@app.on_event("startup")
def _startup():
    # Marco 0: serialize schema init across swarm replicas so the guarded
    # ADD COLUMN statements in init_*_db() can't race, then apply versioned
    # migrations under the same cross-process lock.
    from .migrations import schema_lock, run_migrations
    with schema_lock():
        init_db()
        init_agency_db()
        init_companies_db()
        run_migrations(_locked=True)
    os.makedirs(LOCAL_MEDIA_ROOT, exist_ok=True)
    _configure_process_tmpdir()
    tmp_root = _preferred_tmpdir_root()
    if tmp_root:
        os.makedirs(tmp_root, exist_ok=True)
        removed_tmp = _cleanup_stale_tmp_entries(remove_all=True)
        if removed_tmp:
            print(f"[startup] removed {removed_tmp} orphan tmp entries from {tmp_root}", flush=True)
    async_jobs_fail_incomplete(
        kinds=[_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER, _ASYNC_JOB_KIND_DRIVE_UPLOAD, "auto_editor"],
        error="service_restarted",
        detail="O serviço reiniciou durante o processamento. Gere novamente.",
    )
    _setup_s3_cors()
    # Initialize vision settings with defaults if not already set
    _now = datetime.now(timezone.utc).isoformat()
    if not settings_get(key="vision:scene_threshold"):
        settings_set(key="vision:scene_threshold", value="0.32", updated_at=_now)
    if not settings_get(key="vision:max_adult_frames"):
        settings_set(key="vision:max_adult_frames", value="10", updated_at=_now)
    if not settings_get(key="vision:model"):
        settings_set(key="vision:model", value="auto", updated_at=_now)


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/xvideos/top")
def xvideos_top(limit: int = 20, request: Request = None):
    auth_err = _require_api_key(request) if request else None
    if auth_err:
        return auth_err
    limit = max(1, min(limit, 100))
    data = fetch_top_videos(limit=limit)
    # Return only the video list + some aggregates (clean for n8n)
    return {
        "ok": True,
        "limit": limit,
        "avg_duration_minutes": data.get("avg_duration_minutes"),
        "top_tags": data.get("top_tags"),
        "videos": data.get("videos", []),
    }


@app.get("/xvideos/search")
def xvideos_search(query: str, limit: int = 20, sort: str = "views", request: Request = None):
    auth_err = _require_api_key(request) if request else None
    if auth_err:
        return auth_err
    limit = max(1, min(limit, 100))
    query = (query or "").strip()
    if not query:
        return {"error": "missing_query"}
    data = fetch_search_videos(query=query, limit=limit, sort=sort)
    return {
        "ok": True,
        "query": query,
        "limit": limit,
        "sort": sort,
        "top_tags": data.get("top_tags"),
        "videos": data.get("videos", []),
    }


@app.get("/xvideos/pornstar")
async def xvideos_pornstar(name: str, limit: int = 20, request: Request = None):
    """Busca vídeos da página estruturada de pornstar do XVideos."""
    auth_err = _require_api_key(request) if request else None
    if auth_err:
        return auth_err
    name = (name or "").strip()
    if not name:
        return {"error": "missing_name"}
    limit = max(1, min(limit, 100))
    data = await asyncio.to_thread(fetch_pornstar_videos, name=name, limit=limit)
    return {
        "ok": True,
        "name": name,
        "limit": limit,
        "pornstar_url": data.get("pornstar_url"),
        "top_tags": data.get("top_tags"),
        "videos": data.get("videos", []),
    }


@app.get("/xvideos/channel")
async def xvideos_channel(name: str, limit: int = 20, request: Request = None):
    """Busca vídeos da página estruturada de canal/studio do XVideos."""
    auth_err = _require_api_key(request) if request else None
    if auth_err:
        return auth_err
    name = (name or "").strip()
    if not name:
        return {"error": "missing_name"}
    limit = max(1, min(limit, 100))
    data = await asyncio.to_thread(fetch_channel_videos, name=name, limit=limit)
    return {
        "ok": True,
        "name": name,
        "limit": limit,
        "channel_url": data.get("channel_url"),
        "top_tags": data.get("top_tags"),
        "videos": data.get("videos", []),
    }


def _maybe_delete_uploaded_video(req: AnalyzeRequest) -> Optional[str]:
    """Delete raw uploaded video (object) after processing.

    Keeps derived artifacts (thumbs/transcript/etc.) in DB; only removes the original object.
    """
    object_key = (req.video_object_key or "").strip()
    if not object_key:
        return None
    if not _is_valid_object_key(object_key):
        return "invalid_object_key"

    try:
        _delete_media_ref(media_ref=object_key, s3=_s3_client())
        return None
    except Exception as e:
        return f"delete_failed:{_safe_error_detail(e, 'storage_delete_failed')}"


async def _analyze_core(req: AnalyzeRequest, request: Optional[Request] = None) -> Dict[str, Any]:
    """Core analyze logic (no auth). Called by /analyze and /analyze/start."""
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    error: Optional[str] = None
    result: Dict[str, Any] = {}

    delete_error: Optional[str] = None

    _emit_analyze_progress(5, "Iniciando análise…")
    try:
        # 1. Vision Analysis (Auto) if video present
        vision_analysis = None
        frames_b64 = []
        frame_timestamps: List[float] = []
        vision_debug: Dict[str, Any] = {"skipped_reason": None}
        if req.video_object_key:
            _emit_analyze_progress(10, "Baixando vídeo do storage…")
            with tempfile.TemporaryDirectory(prefix="vision-", dir=_preferred_tmpdir_root("vision")) as vtd:
                in_path = os.path.join(vtd, "video")
                try:
                    await asyncio.to_thread(_download_media_ref_to_file, media_ref=req.video_object_key, out_path=in_path, s3=_s3_client())
                    probe_req = req.video_metadata.get("probe") or {}
                    duration = float(probe_req.get("duration_seconds") or 0)
                    if duration <= 0:
                        detected = await asyncio.to_thread(_probe_metadata, in_path)
                        duration = float(detected.get("duration_seconds") or 0)
                        vision_debug["probe_auto"] = detected
                    else:
                        vision_debug["probe_from_request"] = True
                    vision_debug["duration_used"] = duration
                    if duration <= 0:
                        vision_debug["skipped_reason"] = "duration_zero_after_probe"
                    else:
                        _emit_analyze_progress(25, "Extraindo frames por cena…")
                        _thresh_s = settings_get(key="vision:scene_threshold")
                        _maxf_s = settings_get(key="vision:max_adult_frames")
                        scene_threshold = float(_thresh_s["value"]) if _thresh_s else 0.22
                        max_frames = int(_maxf_s["value"]) if _maxf_s else 40
                        frame_items, _cut_pts = await asyncio.to_thread(
                            _extract_intelligent_adult_keyframes,
                            in_path=in_path,
                            out_dir=vtd,
                            duration=duration,
                            max_frames=max_frames,
                            scene_threshold=scene_threshold,
                            quick=True,
                        )
                        vision_debug["frames_extracted"] = len(frame_items)
                        frame_timestamps = [
                            round(float(item.get("timestamp") or 0.0), 3)
                            for item in frame_items
                        ]
                        frames_b64 = [
                            await asyncio.to_thread(_file_to_base64, str(item.get("path") or ""))
                            for item in frame_items
                            if str(item.get("path") or "").strip()
                        ]
                        if frames_b64:
                            _emit_analyze_progress(45, f"Vision AI analisando {len(frames_b64)} frames…")
                            vision_analysis = await _analyze_multiple_frames(frames_b64)
                            if vision_analysis is None:
                                has_grok = bool((settings_get(key="token:grok") or {}).get("value"))
                                vision_debug["analysis_error"] = "missing_grok_token" if not has_grok else "empty_or_invalid_vision_response"
                        else:
                            vision_debug["skipped_reason"] = "no_frames_extracted"
                except Exception as ve:
                    vision_debug["error"] = repr(ve)
                    print(f"Vision automation failed: {ve}")
        else:
            vision_debug["skipped_reason"] = "no_video_object_key"

        # Consolidate probe data: prefer auto-detected, fall back to request metadata
        probe: Dict[str, Any] = req.video_metadata.get("probe") or {}
        if vision_debug.get("probe_auto"):
            probe = vision_debug["probe_auto"]

        # ── Transcrição automática (gera SRT/segments p/ legenda) ──
        # stt_provider=none permite Analyze leve: referências + Vision + JSON,
        # sem travar o servidor em Whisper/legendas.
        skip_transcription = (req.stt_provider or "").strip().lower() in {
            "none", "skip", "off", "disabled", "no", "sem_transcricao", "sem-transcricao"
        }
        if skip_transcription:
            _emit_analyze_progress(55, "Transcrição pulada; seguindo com referência e Vision…")
        elif (not (req.transcript and (req.transcript.text or req.transcript.segments))) and req.video_object_key and request is not None:
            _emit_analyze_progress(55, "Transcrevendo áudio…")
            try:
                t_req = TranscribeRequest(
                    video_object_key=req.video_object_key,
                    provider=(req.stt_provider or "auto"),
                    adult_mode=False,
                )
                t_res = await transcribe(t_req, request)
                if isinstance(t_res, dict) and t_res.get("ok") and isinstance(t_res.get("transcript"), dict):
                    t = t_res["transcript"]
                    req.transcript = Transcript(
                        provider=t.get("provider"),
                        lang=t.get("lang"),
                        text=t.get("text") or "",
                        segments=t.get("segments") or None,
                        srt=t.get("srt") or None,
                    )
            except Exception as _te:
                print(f"[analyze] transcrição automática falhou: {_te}", flush=True)

        transcript_text = (req.transcript.text if req.transcript and req.transcript.text else "").strip()
        transcript_snip = transcript_text[:500] if transcript_text else ""

        # ── Referências do criador (sem scraping — contexto de estilo) ──
        _emit_analyze_progress(65, "Carregando referências do criador…")
        creator: Optional[Dict[str, Any]] = None
        creator_refs: List[str] = []
        if req.creator_id:
            try:
                from .db_agency import creator_get
                creator = creator_get(req.creator_id)
            except Exception as _ce:
                print(f"[analyze] creator_get falhou: {_ce}", flush=True)
                creator = None
        if creator:
            for _k in ("reference_channels", "own_channel_urls"):
                for _v in (creator.get(_k) or []):
                    _v = str(_v).strip()
                    if _v and _v not in creator_refs:
                        creator_refs.append(_v)

        def _ctx_list(label: str, values: Any) -> str:
            vals = [str(v).strip() for v in (values or []) if str(v).strip()]
            return f"- **{label}:** {', '.join(vals)}\n" if vals else ""

        creator_ctx = ""
        if creator:
            creator_ctx = (
                "## Perfil do criador / empresa\n"
                f"- **Nome:** {creator.get('name') or creator.get('brand_name') or 'N/A'}\n"
                + _ctx_list("Canais de referência", creator.get("reference_channels"))
                + _ctx_list("Canais próprios", creator.get("own_channel_urls"))
                + _ctx_list("Categorias preferidas", creator.get("preferred_categories"))
                + _ctx_list("Tags habituais", creator.get("preferred_tags"))
                + (f"- **Descrição/estilo:** {creator.get('performer_description')}\n" if creator.get("performer_description") else "")
                + (f"- **Idioma do conteúdo:** {creator.get('content_language')}\n" if creator.get("content_language") else "")
                + "\n"
            )

        # tags sugeridas: visão + tags habituais do criador
        suggested_tags = []
        if vision_analysis and isinstance(vision_analysis, dict):
            for _tag in (vision_analysis.get("tags") or []):
                if _tag and _tag not in suggested_tags:
                    suggested_tags.append(_tag)
        if creator:
            for _tag in (creator.get("preferred_tags") or []):
                if _tag and _tag not in suggested_tags:
                    suggested_tags.append(_tag)
        suggested_tags = suggested_tags[:40]

        _probe_dur = probe.get("duration_seconds") if probe else None
        duration_hint = f"~{round(float(_probe_dur))}s" if _probe_dur else ""
        platforms_list = [str(p).strip().lower() for p in (req.platforms or []) if str(p).strip()] or ["youtube", "instagram"]

        # ── Seção de visão p/ prompt (schema mainstream) ──
        vision_prompt_section = ""
        if vision_analysis and isinstance(vision_analysis, dict):
            va = vision_analysis
            _scenes = va.get("scenes") or []
            vision_prompt_section = (
                "## Análise Visual Automática (Vision IA — frames por cena)\n"
                f"- **Descrição:** {va.get('description', 'N/A')}\n"
                f"- **Tags detectadas:** {', '.join(va.get('tags') or [])}\n"
                f"- **Categorias:** {', '.join(va.get('categories') or [])}\n"
                f"- **Confiança:** {va.get('confidence', 0)}\n"
                + (
                    "- **Cenas:**\n"
                    + "\n".join(
                        f"  - frame {s.get('frame_index','?')}: {s.get('description','')}"
                        + (f" [texto na tela: {s.get('on_screen_text')}]" if s.get('on_screen_text') else "")
                        for s in _scenes[:12]
                    )
                    + "\n"
                    if _scenes else ""
                )
                + "\n"
            )

        _emit_analyze_progress(80, "IA gerando títulos, descrição e thumbnail…")
        _platforms_str = ", ".join(platforms_list)
        markdown_prompt = (
            "# Otimização de Conteúdo para Redes Sociais\n\n"
            "Você é um estrategista de conteúdo e copywriter sênior de redes sociais, especialista em "
            f"crescimento orgânico em {_platforms_str}. Sua missão é maximizar retenção, CTR e "
            "compartilhamentos do vídeo abaixo, mantendo o conteúdo apropriado para plataformas mainstream "
            "(sem linguagem adulta, sem termos sexuais explícitos, sem conteúdo NSFW).\n\n"
            "REGRAS:\n"
            "- Tom alinhado a cada plataforma: YouTube (busca/SEO), Instagram/TikTok (hook rápido, emoção).\n"
            "- Títulos curtos, magnéticos e honestos; nada de clickbait enganoso ou termos proibidos.\n"
            "- Hashtags relevantes e específicas do nicho; nada de spam.\n"
            "- Escreva em pt-BR. Preserve nomes próprios/marcas no idioma original.\n\n"
            "## Dados do vídeo\n"
            f"- duração: {req.video_metadata.get('probe', {}).get('duration_seconds', 'n/a')}s\n"
            f"- resolução: {req.video_metadata.get('probe', {}).get('width', 'n/a')}x{req.video_metadata.get('probe', {}).get('height', 'n/a')}\n"
            f"- plataformas-alvo: {_platforms_str}\n\n"
            + vision_prompt_section
            + creator_ctx
            + "## Transcrição do vídeo (áudio original)\n"
            + (f"```\n{transcript_text[:4000]}\n```\n\n" if transcript_text else "(sem áudio/transcrição)\n\n")
            + "## TAREFA\n\n"
            + "1. TÍTULOS: 3 opções em pt-BR (A=SEO/busca p/ YouTube; B=curiosidade/hook p/ Reels/Shorts/TikTok; C=benefício/resultado claro).\n"
            + "2. DESCRIÇÃO: pt-BR 80-180 palavras, agrega valor e termina com CTA (seguir/comentar/salvar).\n"
            + "3. HASHTAGS: 15-25 relevantes do nicho.\n"
            + "4. CONCEITO DE THUMBNAIL: cena/frame de maior impacto + texto curto (3-5 palavras) que deve aparecer.\n"
            + "5. RECOMENDAÇÕES: hook dos primeiros 3s, duração ideal por formato, melhor horário/frequência.\n\n"
            + "Responda SOMENTE em JSON válido com as chaves: "
            + "{\"titles\": [\"...\",\"...\",\"...\"], \"description\": \"...\", \"hashtags\": [\"#...\"], "
            + "\"thumbnail_concept\": \"...\", \"recommendations\": \"...\"}\n"
        )

        # ── Geração real via LLM (best-effort, mainstream) ──
        grok_out: Dict[str, Any] = {"markdown_prompt_ptbr_keep_original": markdown_prompt}
        try:
            from .llm import ProviderSpec, run_providers_to_completion
            from .db import settings_get as _settings_get
            _provider = None
            for _pname, _pmodel in [
                ("openai", "gpt-4o-mini"),
                ("gemini", "gemini-1.5-flash"),
                ("grok", "grok-3"),
                ("openrouter", "x-ai/grok-3-fast"),
                ("deepseek", "deepseek-chat"),
            ]:
                _saved = _settings_get(key=f"token:{_pname}")
                if _saved and _saved.get("value"):
                    _provider = ProviderSpec(name=_pname, model=_pmodel, api_key=_saved["value"])
                    break
            if _provider is not None:
                _res = await run_providers_to_completion(
                    providers=[_provider],
                    prompt=markdown_prompt,
                    params={"temperature": 0.6, "max_tokens": 1800},
                )
                _txt = (_res[0].get("text") or "").strip() if _res else ""
                if _txt:
                    grok_out["raw"] = _txt
                    _clean = _txt
                    if "```" in _clean:
                        _clean = _clean.split("```", 2)[1] if _clean.count("```") >= 2 else _clean
                        if _clean.lstrip().lower().startswith("json"):
                            _clean = _clean.lstrip()[4:]
                    try:
                        _parsed = json.loads(_clean[_clean.find("{"): _clean.rfind("}") + 1])
                        grok_out["generated"] = _parsed
                        _titles = _parsed.get("titles") or []
                        grok_out["title"] = (_titles[0] if _titles else "") or ""
                        grok_out["description"] = _parsed.get("description") or ""
                        for _h in (_parsed.get("hashtags") or []):
                            _h = str(_h).lstrip("#").strip()
                            if _h and _h not in suggested_tags:
                                suggested_tags.append(_h)
                    except Exception as _pe:
                        print(f"[analyze] parse JSON do LLM falhou: {_pe}", flush=True)
        except Exception as _le:
            print(f"[analyze] geração LLM falhou: {_le}", flush=True)

        result = {
            "run_id": run_id,
            "created_at": created_at,
            "suggested": {
                "tags": suggested_tags,
                "description_template": (
                    "Tags sugeridas: " + ", ".join(suggested_tags[:10])
                    + (f". Duração-alvo: {duration_hint}." if duration_hint else ".")
                ),
            },
            "inputs": {
                "transcript_present": bool(transcript_text),
                "transcript_skipped": bool(skip_transcription),
                "transcript_snippet": transcript_snip,
                "platforms": platforms_list,
                "creator_id": req.creator_id,
            },
            "grok": grok_out,
            "vision": {
                "analysis": vision_analysis,
                "frames_count": len(frames_b64),
                "frames": frames_b64,
                "frame_timestamps": frame_timestamps,
                "debug": vision_debug,
            },
            "sources": {
                "creator_refs": creator_refs,
                "platforms": platforms_list,
            },
        }

    except Exception as e:
        error = _safe_error_detail(e, "analyze_failed")
        result = {
            "run_id": run_id,
            "created_at": created_at,
            "error": error,
            "vision": {
                "analysis": None,
                "frames_count": 0,
                "frames": [],
                "frame_timestamps": [],
                "debug": {
                    "skipped_reason": "analyze_exception",
                    "error": error,
                },
            },
        }

    # Video kept in MinIO so burn-subtitles can use it without re-upload
    delete_error = None  # was: _maybe_delete_uploaded_video(req)

    if delete_error:
        # record deletion failure in result for visibility
        try:
            if isinstance(result, dict):
                result.setdefault("storage", {})
                result["storage"]["raw_video_deleted"] = False
                result["storage"]["delete_error"] = delete_error
                result["storage"]["object_key"] = req.video_object_key
        except Exception:
            pass
    else:
        if isinstance(result, dict):
            result.setdefault("storage", {})
            result["storage"]["raw_video_deleted"] = bool(req.video_object_key)
            result["storage"]["object_key"] = req.video_object_key

    insert_run(
        run_id=run_id,
        created_at=created_at,
        source="mvp",
        request_obj=req.model_dump(),
        result_obj=result,
        error=error,
    )

    return result


@app.post("/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    return await _analyze_core(req, request)


@app.post("/analyze/start")
async def analyze_start(req: AnalyzeRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job_id = str(uuid.uuid4())
    async_job_put(kind=_ASYNC_JOB_KIND_ANALYZE, job_id=job_id, payload={
        "status": "running", "progress_pct": 3, "detail": "Na fila…",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    async def _bg():
        tok = _analyze_job_ctx.set(job_id)
        try:
            print(f"[analyze/start] job={job_id} iniciando", flush=True)
            result = await _analyze_core(req, request)
            async_job_merge(kind=_ASYNC_JOB_KIND_ANALYZE, job_id=job_id, patch={
                "status": "done", "progress_pct": 100, "detail": "✓ Análise concluída",
                "result": result, "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[analyze/start] job={job_id} concluído", flush=True)
        except Exception as exc:
            print(f"[analyze/start] job={job_id} erro: {exc}", flush=True)
            async_job_merge(kind=_ASYNC_JOB_KIND_ANALYZE, job_id=job_id, patch={
                "status": "error", "progress_pct": 0,
                "detail": f"Erro: {exc}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        finally:
            _analyze_job_ctx.reset(tok)

    asyncio.create_task(_bg())
    return {"job_id": job_id}


@app.get("/analyze/status/{job_id}")
async def analyze_status(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = async_job_get(kind=_ASYNC_JOB_KIND_ANALYZE, job_id=job_id)
    if not job:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return job


@app.get("/runs")
def runs(limit: int = 50, request: Request = None):
    # FastAPI will always pass Request when annotated, but keep None-safe.
    auth_err = _require_api_key(request) if request else None
    if auth_err:
        return auth_err
    limit = max(1, min(limit, 500))
    return {"runs": list_runs(limit=limit)}


@app.get("/runs/{run_id}")
def runs_get(run_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    r = get_run(run_id)
    if not r:
        return {"error": "not_found", "run_id": run_id}
    return r


@app.get("/runs/{run_id}/light")
def runs_get_light(run_id: str, request: Request):
    """Versão leve do run para troca rápida de seleção no frontend.

    Retorna request/result já parseados e remove `vision.frames` (payload pesado).
    """
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return {"error": "not_found", "run_id": run_id}

    req_data = _safe_json_obj(row.get("request_json"))
    result_data = _safe_json_obj(row.get("result_json"))
    vision = _safe_json_obj(result_data.get("vision"))
    frames = vision.get("frames")
    frame_timestamps = vision.get("frame_timestamps")
    if isinstance(frames, list):
        vision["frames_count"] = len(frames)
    elif vision.get("frames_count") is None:
        vision["frames_count"] = 0
    if not isinstance(frame_timestamps, list):
        frame_timestamps = []
    vision["frame_timestamps"] = frame_timestamps
    vision["frames"] = []
    result_data["vision"] = vision

    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "source": row.get("source"),
        "error": row.get("error"),
        "request_json": req_data,
        "result_json": result_data,
    }


@app.get("/runs/{run_id}/frames")
def runs_get_frames(run_id: str, request: Request):
    """Entrega apenas os screenshots do run, para carregamento progressivo no frontend."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return {"error": "not_found", "run_id": run_id}

    result_data = _safe_json_obj(row.get("result_json"))
    vision = _safe_json_obj(result_data.get("vision"))
    frames = vision.get("frames")
    if not isinstance(frames, list):
        frames = []
    return {
        "run_id": run_id,
        "frames_count": len(frames),
        "frames": frames,
    }


@app.get("/runs/{run_id}/wizard-data")
def runs_get_wizard_data(run_id: str, request: Request):
    """Payload mínimo para a aba Criação (sem refs/prompt pesados)."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return {"error": "not_found", "run_id": run_id}

    req_data = _safe_json_obj(row.get("request_json"))
    result_data = _safe_json_obj(row.get("result_json"))
    vision = _safe_json_obj(result_data.get("vision"))
    frames = vision.get("frames")
    frame_timestamps = vision.get("frame_timestamps")
    if not isinstance(frames, list):
        frames = []
    if not isinstance(frame_timestamps, list):
        frame_timestamps = []
    storage = _safe_json_obj(result_data.get("storage"))

    result_min = {
        "run_id": result_data.get("run_id") or row.get("id"),
        "created_at": result_data.get("created_at") or row.get("created_at"),
        "storage": storage,
        "vision": {
            "analysis": vision.get("analysis"),
            "frames_count": len(frames),
            "frames": [],
            "frame_timestamps": frame_timestamps,
            "debug": vision.get("debug"),
        },
    }

    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "source": row.get("source"),
        "error": row.get("error"),
        "request_json": req_data,
        "result_json": result_min,
    }


@app.get("/runs/{run_id}/wizard-state")
def run_wizard_state_get(run_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    req_data = _safe_json_obj(row.get("request_json"))
    ws = req_data.get("wizard_state")
    if not isinstance(ws, dict):
        ws = {}
    return {"ok": True, "wizard_state": ws}


@app.put("/runs/{run_id}/wizard-state")
async def run_wizard_state_set(run_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    patch = body.get("state") if isinstance(body, dict) and isinstance(body.get("state"), dict) else body
    if not isinstance(patch, dict):
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    ok = _merge_run_wizard_state(run_id, patch)
    if not ok:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    return {"ok": True}


@app.delete("/runs/{run_id}/creation")
async def run_creation_delete(run_id: str, request: Request):
    """Remove somente os artefatos e o estado da aba Criação deste run."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)

    active = _active_jobs_for_run(run_id, kinds=[_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER])
    if active:
        return JSONResponse(
            {
                "error": "run_has_active_jobs",
                "detail": "Há processamento de criação em andamento. Cancele ou aguarde terminar antes de excluir.",
                "active_jobs": active,
            },
            status_code=409,
        )

    req_data = _safe_json_obj(row.get("request_json"))
    media_refs = _collect_creation_media_refs(req_data)
    media_result = await _delete_media_refs_for_run(run_id, media_refs)
    update_run_request_field(run_id=run_id, field="wizard_state", value={})
    deleted_jobs = delete_async_jobs_for_run(
        run_id=run_id,
        kinds=[_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER],
    )
    dropped_runtime_jobs = _drop_runtime_jobs_for_run(
        run_id,
        kinds=[_ASYNC_JOB_KIND_BURN, _ASYNC_JOB_KIND_TEASER],
    )
    deleted_posts = delete_scheduled_posts_for_run(run_id)
    return JSONResponse({
        "ok": True,
        "run_id": run_id,
        "deleted_jobs": deleted_jobs,
        "dropped_runtime_jobs": dropped_runtime_jobs,
        "deleted_scheduled_posts": deleted_posts,
        **media_result,
    })


@app.delete("/runs/{run_id}")
async def runs_delete(run_id: str, request: Request, delete_media: bool = True):
    """Delete o run e, por padrão, os arquivos ligados só a ele."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)

    active = _active_jobs_for_run(run_id)
    if active:
        return JSONResponse(
            {
                "error": "run_has_active_jobs",
                "detail": "Há processamento em andamento para este run. Cancele ou aguarde terminar antes de excluir.",
                "active_jobs": active,
            },
            status_code=409,
        )

    scheduled_posts = list_scheduled_posts_for_run(run_id)
    async_jobs = list_async_jobs_for_run(run_id=run_id)
    media_result: Dict[str, Any] = {"deleted_media": [], "skipped_media": [], "media_errors": []}
    if delete_media:
        refs = _collect_run_media_refs(
            run_row=row,
            scheduled_posts=scheduled_posts,
            async_jobs=async_jobs,
        )
        media_result = await _delete_media_refs_for_run(run_id, refs)

    deleted_posts = delete_scheduled_posts_for_run(run_id)
    deleted_jobs = delete_async_jobs_for_run(run_id=run_id)
    dropped_runtime_jobs = _drop_runtime_jobs_for_run(run_id)
    ok = delete_run(run_id)
    if not ok:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    return JSONResponse({
        "ok": True,
        "run_id": run_id,
        "deleted_run": True,
        "deleted_scheduled_posts": deleted_posts,
        "deleted_jobs": deleted_jobs,
        "dropped_runtime_jobs": dropped_runtime_jobs,
        **media_result,
    })


@app.post("/api/thumbnail/highres")
async def thumbnail_highres(request: Request):
    """Extract one high-res frame from source video based on selected screenshot index."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    run_id = str((body or {}).get("run_id") or "").strip()
    if not run_id:
        return JSONResponse({"error": "missing_run_id"}, status_code=400)

    run = get_run(run_id)
    if not run:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    result_data = _safe_json_obj(run.get("result_json"))
    vision = _safe_json_obj(result_data.get("vision"))
    stored_frame_timestamps = vision.get("frame_timestamps")
    if not isinstance(stored_frame_timestamps, list):
        stored_frame_timestamps = []

    try:
        req_data = json.loads(run["request_json"]) if isinstance(run.get("request_json"), str) else (run.get("request_json") or {})
    except Exception:
        req_data = {}

    object_key = str((body or {}).get("object_key") or req_data.get("video_object_key") or "").strip()
    if not object_key:
        return JSONResponse({"error": "missing_video_object_key"}, status_code=400)
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_video_object_key"}, status_code=400)

    try:
        frame_index = max(0, int((body or {}).get("frame_index") or 0))
    except Exception:
        frame_index = 0
    try:
        frames_count = max(2, int((body or {}).get("frames_count") or 10))
    except Exception:
        frames_count = 10
    try:
        # max_height=0 → resolução nativa; default 1080 para bater com o burn
        frame_max_height = max(0, _int_with_default((body or {}).get("max_height"), 1080))
    except Exception:
        frame_max_height = 1080
    logo_b64 = str((body or {}).get("logo_b64") or "").strip()
    logos_raw = (body or {}).get("logos")
    try:
        logo_x = max(0, min(int((body or {}).get("logo_x") or 97), 100))
    except Exception:
        logo_x = 97
    try:
        logo_y = max(0, min(int((body or {}).get("logo_y") or 97), 100))
    except Exception:
        logo_y = 97
    try:
        logo_scale_pct = max(5.0, min(float((body or {}).get("logo_scale_pct") or 20.0), 100.0))
    except Exception:
        logo_scale_pct = 20.0
    try:
        logo_opacity = max(5.0, min(float((body or {}).get("logo_opacity") or 85.0), 100.0))
    except Exception:
        logo_opacity = 85.0

    try:
        with tempfile.TemporaryDirectory(prefix="thumb-hq-", dir=_preferred_tmpdir_root("thumb")) as tmpdir:
            in_path = os.path.join(tmpdir, "input_video")
            out_path = os.path.join(tmpdir, "frame.jpg")
            logo_specs: List[Dict[str, Any]] = []
            composited_logo = False

            await asyncio.to_thread(
                _download_media_ref_to_file,
                media_ref=object_key,
                out_path=in_path,
                s3=_s3_client(),
            )

            duration = await asyncio.to_thread(_probe_duration, in_path)
            if duration <= 0:
                return JSONResponse({"error": "no_duration", "detail": "Não foi possível determinar a duração do vídeo."}, status_code=400)

            timestamp = _pick_frame_timestamp_by_index(frame_index, frames_count, duration, stored_frame_timestamps)
            timestamp_source = "stored_frame_timestamps" if timestamp is not None else None
            if timestamp is None:
                _thresh_s = settings_get(key="vision:scene_threshold")
                _maxf_s = settings_get(key="vision:max_adult_frames")
                scene_threshold = float(_thresh_s["value"]) if _thresh_s else 0.32
                max_frames = max(frame_index + 1, frames_count, int(_maxf_s["value"]) if _maxf_s else 10)
                rebuilt_timestamps = await asyncio.to_thread(
                    _build_intelligent_adult_keyframe_timestamps,
                    in_path=in_path,
                    duration=duration,
                    max_frames=max_frames,
                    scene_threshold=scene_threshold,
                )
                timestamp = _pick_frame_timestamp_by_index(frame_index, frames_count, duration, rebuilt_timestamps)
                if timestamp is not None:
                    timestamp_source = "reconstructed_scene_timestamps"
            if timestamp is None:
                ts = _frame_indexes_to_timestamps([frame_index], frames_count, duration)
                timestamp = ts[0] if ts else max(0.0, min(duration - 0.05, duration * 0.5))
                timestamp_source = "uniform_fallback"

            def _extract_frame():
                cmd_frame = [
                    "ffmpeg", "-y",
                    "-ss", f"{timestamp:.3f}",
                    "-i", in_path,
                    "-frames:v", "1",
                    "-q:v", "2",
                ]
                if frame_max_height > 0:
                    # Escala para a mesma resolução do burn → preview fiel
                    cmd_frame += ["-vf", f"scale=-2:min(ih\\,{frame_max_height})"]
                cmd_frame.append(out_path)
                proc = subprocess.run(
                    cmd_frame,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=300,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
                    raise RuntimeError(err[-500:] or "ffmpeg_frame_extract_failed")

            await asyncio.to_thread(_extract_frame)
            if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
                return JSONResponse({"error": "frame_not_extracted"}, status_code=500)

            logo_specs = _write_logo_overlay_specs(
                raw_logos=logos_raw if isinstance(logos_raw, list) else None,
                legacy_logo_b64=logo_b64,
                tmpdir=tmpdir,
                legacy_x=logo_x,
                legacy_y=logo_y,
                legacy_scale_pct=logo_scale_pct,
                legacy_opacity=logo_opacity,
            )

            if logo_specs:
                preview_out_path = os.path.join(tmpdir, "frame_with_logo.jpg")

                def _apply_logo_preview():
                    parts: List[str] = []
                    current_label = "[0:v]"
                    for idx, spec in enumerate(logo_specs):
                        input_idx = idx + 1
                        logo_scaled_label = f"lgs{idx}"
                        base_label = f"lb{idx}"
                        logo_label = f"lg{idx}"
                        out_label = f"vlogo{idx}"
                        scale_boost = max(1.0, min(float(spec.get("scale_boost", 1.0) or 1.0), 1.6))
                        scale_ratio = max(0.05, min((float(spec.get("scale_pct", 20.0)) / 100.0) * scale_boost, 1.0))
                        height_scale = max(1.0, min(float(spec.get("height_scale", 1.0) or 1.0), 1.6))
                        alpha_ratio = max(0.05, min(float(spec.get("opacity", 85.0)) / 100.0, 1.0))
                        _append_logo_aspect_locked_scale(
                            parts,
                            input_idx=input_idx,
                            base_ref=current_label,
                            logo_scaled_label=logo_scaled_label,
                            base_label=base_label,
                            scale_ratio=scale_ratio,
                            tag=f"preview_logo_{idx}",
                            height_scale=height_scale,
                        )
                        chain = f"[{logo_scaled_label}]format=rgba,setsar=1"
                        if bool(spec.get("remove_bg")):
                            col = str(spec.get("bg_key_color") or "#ffffff").replace("#", "")
                            sim = max(0.01, min(float(spec.get("bg_similarity", 0.18)), 0.60))
                            blend = max(0.0, min(float(spec.get("bg_blend", 0.08)), 0.40))
                            chain += f",colorkey=0x{col.upper()}:{sim:.3f}:{blend:.3f}"
                        chain += f",colorchannelmixer=aa={alpha_ratio:.3f}[{logo_label}]"
                        parts.append(chain)
                        x = max(0.0, min(float(spec.get("x", 97.0)), 100.0))
                        y = max(0.0, min(float(spec.get("y", 97.0)), 100.0))
                        parts.append(
                            f"[{base_label}][{logo_label}]overlay=(W-w)*{x:.4f}/100:(H-h)*{y:.4f}/100:shortest=1[{out_label}]"
                        )
                        current_label = f"[{out_label}]"
                    filter_complex = ";".join(parts) + f";{current_label}format=yuvj420p[out]"
                    inputs: List[str] = []
                    for spec in logo_specs:
                        inputs.extend(["-i", str(spec.get("path"))])
                    proc = subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-i", out_path,
                            *inputs,
                            "-filter_complex", filter_complex,
                            "-map", "[out]",
                            "-frames:v", "1",
                            "-q:v", "2",
                            preview_out_path,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        timeout=300,
                    )
                    if proc.returncode != 0:
                        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
                        raise RuntimeError(err[-500:] or "ffmpeg_logo_preview_failed")

                await asyncio.to_thread(_apply_logo_preview)
                if os.path.exists(preview_out_path) and os.path.getsize(preview_out_path) > 0:
                    out_path = preview_out_path
                    composited_logo = True

            frame_b64 = await asyncio.to_thread(_file_to_base64, out_path)
            meta = await asyncio.to_thread(_probe_metadata, out_path)
            width = int(meta.get("width") or 0)
            height = int(meta.get("height") or 0)

            return JSONResponse(
                {
                    "ok": True,
                    "frame_b64": frame_b64,
                    "timestamp": round(float(timestamp), 3),
                    "timestamp_source": timestamp_source,
                    "width": width,
                    "height": height,
                    "object_key": object_key,
                    "composited_logo": composited_logo,
                }
            )
    except Exception as e:
        return JSONResponse({"error": "thumbnail_extract_failed", "detail": _safe_error_detail(e, "thumbnail_extract_failed")}, status_code=500)


@app.get("/runs/{run_id}/srt")
def runs_get_srt(run_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    r = get_run(run_id)
    if not r:
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        req_data = json.loads(r["request_json"]) if isinstance(r["request_json"], str) else (r.get("request_json") or {})
        transcript = req_data.get("transcript") or {}
        # Priority: stored srt string → segments → plain text fallback
        srt_content = (transcript.get("srt") or "").strip()
        if not srt_content:
            segments = transcript.get("segments") or []
            srt_content = _format_srt(segments)
        if not srt_content:
            raw_text = (transcript.get("text") or "").strip()
            if raw_text:
                # Best-effort: split into sentence chunks (~12 words, ~5 s each)
                words = raw_text.split()
                chunk_size = 12
                words_per_sec = 2.5
                fake_segs = []
                for idx in range(0, len(words), chunk_size):
                    chunk = " ".join(words[idx: idx + chunk_size])
                    start_s = idx / words_per_sec
                    end_s = (idx + chunk_size) / words_per_sec
                    fake_segs.append({"start": start_s, "end": end_s, "text": chunk})
                srt_content = _format_srt(fake_segs)
    except Exception as e:
        return JSONResponse({"error": "parse_error", "detail": str(e)}, status_code=500)
    if not srt_content:
        return JSONResponse({"error": "no_transcript", "detail": "Este run não tem transcrição disponível."}, status_code=404)
    filename = f"legenda_{run_id[:8]}.srt"
    return Response(
        content=srt_content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.put("/runs/{run_id}/transcript")
async def update_run_transcript(run_id: str, request: Request):
    """Save edited transcript (and optional SRT) back into the run's request_json."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    transcript = body.get("transcript")
    if not isinstance(transcript, dict):
        return JSONResponse({"error": "invalid_transcript"}, status_code=400)
    ok = update_run_request_field(run_id=run_id, field="transcript", value=transcript)
    if not ok:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    return JSONResponse({"ok": True})


async def _burn_subtitles_worker(
    job_id: str,
    run_id: str,
    caller_object_key: str,
    srt_content: str,
    req_data: dict,
    logo_b64: str = "",
    logos: Optional[List[Dict[str, Any]]] = None,
    font_size: int = 22,
    font_color: str = "white",
    sub_delay_secs: float = 0.0,
    output_crf: int = 26,
    max_height: int = 1080,
    logo_x: int = 97,
    logo_y: int = 97,
    logo_scale_pct: float = 20.0,
    logo_opacity: float = 85.0,
    x264_preset: str = "ultrafast",
    skip_subtitles: bool = False,
    output_prefix: Optional[str] = None,
    output_filename: Optional[str] = None,
    wizard_update_kind: str = "burn",
):
    import traceback
    _burn_control(job_id)
    existing = _burn_job_get(job_id) or {}
    if (existing.get("status") or "").lower() == "cancelled":
        return
    _burn_job_patch(job_id, {"status": "pending", "detail": "Aguardando fila de processamento…"})

    await _burn_worker_semaphore.acquire()
    _burn_dequeue(job_id)

    s3 = _s3_client()
    object_key: Optional[str] = None
    cleanup_temp = False

    try:
        if _burn_cancel_requested(job_id):
            _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
            return

        _burn_job_patch(job_id, {"status": "running", "detail": "Inicializando…"})

        if caller_object_key:
            object_key = caller_object_key
            # Caller-supplied refs can be originals, burned videos, or teasers.
            # Never delete those after a burn. Only clean explicit temporary
            # media refs created under _tmp.
            cleanup_temp = _media_ref_has_prefix(object_key, "_tmp")
        else:
            # Try video_object_key stored directly in the run (direct uploads)
            stored_key = (req_data.get("video_object_key") or "").strip()
            if stored_key:
                object_key = stored_key
            else:
                # Fallback: derive object_key from the stored video_url
                video_url = req_data.get("video_url", "").strip()
                if not video_url:
                    _burn_job_patch(job_id, {"status": "error", "error": "no_video_url", "detail": "Este run não tem URL de vídeo armazenada."})
                    return
                prefix = S3_PUBLIC_BASE_URL.rstrip("/") + "/" + S3_BUCKET + "/"
                if video_url.startswith(prefix):
                    object_key = video_url[len(prefix):]

        if object_key and not await asyncio.to_thread(_media_ref_exists, media_ref=object_key, s3=s3):
            if caller_object_key:
                _burn_job_patch(job_id, {"status": "error", "error": "object_not_found", "detail": "Objeto de mídia não encontrado."})
            else:
                _burn_job_patch(job_id, {"status": "error", "error": "video_deleted", "detail": "O vídeo original foi removido do servidor após o processamento. Faça o upload do arquivo novamente."})
            return

        with tempfile.TemporaryDirectory(prefix="burn-subs-", dir=_preferred_tmpdir_root("burn")) as tmpdir:
            in_path  = os.path.join(tmpdir, "input_video")
            srt_path = os.path.join(tmpdir, "legenda.srt")
            out_path = os.path.join(tmpdir, "legendado.mp4")

            _burn_job_patch(job_id, {"detail": "Baixando vídeo…"})
            if object_key:
                await asyncio.to_thread(_download_media_ref_to_file, media_ref=object_key, out_path=in_path, s3=s3)
            else:
                video_url_fb = req_data.get("video_url", "").strip()
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream("GET", video_url_fb) as resp:
                        resp.raise_for_status()
                        with open(in_path, "wb") as f:
                            async for chunk in resp.aiter_bytes(1024 * 1024):
                                f.write(chunk)

            if _burn_cancel_requested(job_id):
                _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
                return

            # Aplica delay/avanço nos timestamps se solicitado
            if sub_delay_secs:
                srt_content = _shift_srt(srt_content, sub_delay_secs)
            if not skip_subtitles and srt_content:
                srt_content = _wrap_srt_for_burn(srt_content)

            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            # Get video duration for progress reporting
            _burn_job_patch(job_id, {"detail": "Analisando vídeo…"})
            try:
                fp = await asyncio.to_thread(
                    subprocess.run,
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", in_path],
                    capture_output=True, text=True, timeout=30,
                )
                duration_secs = float(fp.stdout.strip())
            except Exception:
                duration_secs = 0.0

            try:
                fp_sar = await asyncio.to_thread(
                    subprocess.run,
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=sample_aspect_ratio",
                     "-of", "default=noprint_wrappers=1:nokey=1", in_path],
                    capture_output=True, text=True, timeout=15,
                )
                raw_sar = fp_sar.stdout.strip()
                if raw_sar and ":" in raw_sar:
                    num, den = raw_sar.split(":")
                    video_sar = float(num) / float(den) if float(den) != 0 else 1.0
                else:
                    video_sar = 1.0
            except Exception:
                video_sar = 1.0

            preflight_issue = None
            effective_output_crf = output_crf
            effective_x264_preset = x264_preset
            warning_notes: List[str] = []

            if duration_secs > 0:
                _burn_job_patch(job_id, {"detail": "Validando mídia original…"})
                validation_result = await asyncio.to_thread(
                    _validate_video_path_sync,
                    in_path=in_path,
                    size_bytes=max(0, int(os.path.getsize(in_path) or 0)),
                )
                if not validation_result.get("ok"):
                    _burn_job_patch(job_id, {
                        "status": "error",
                        "error": validation_result.get("error") or "source_media_corrupt",
                        "detail": validation_result.get("detail") or "O vídeo original falhou na validação prévia.",
                        "validation": validation_result,
                    })
                    return
                _burn_job_patch(job_id, {"detail": "Processando ffmpeg… 0%"})
            else:
                _burn_job_patch(job_id, {"detail": "Processando ffmpeg… 0%"})

            logo_specs = _write_logo_overlay_specs(
                raw_logos=logos if isinstance(logos, list) else None,
                legacy_logo_b64=logo_b64,
                tmpdir=tmpdir,
                legacy_x=logo_x,
                legacy_y=logo_y,
                legacy_scale_pct=logo_scale_pct,
                legacy_opacity=logo_opacity,
            )

            def _run_ffmpeg_progress():
                stderr_path = os.path.join(tmpdir, "ffmpeg_stderr.txt")
                # Mapa de cor para código ASS (&HAABBGGRR, Alpha=00)
                _color_map = {
                    "white":  "&H00FFFFFF",
                    "yellow": "&H0000FFFF",
                    "cyan":   "&H00FFFF00",
                    "orange": "&H000080FF",
                    "black":  "&H00000000",
                }
                primary_colour = _color_map.get((font_color or "white").lower(), "&H00FFFFFF")
                safe_font_size = max(6, min(int(font_size or 22), 72))
                safe_crf = max(18, min(int(effective_output_crf or 26), 35))
                safe_max_h = max(0, _int_with_default(max_height, 1080))
                safe_preset = str(effective_x264_preset or "ultrafast").strip().lower()
                if safe_preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
                    safe_preset = "ultrafast"
                burn_threads_raw = os.environ.get("FFMPEG_BURN_THREADS", "0").strip()
                try:
                    parsed_threads = int(burn_threads_raw)
                    # ffmpeg -threads 0 = auto (all available cores)
                    safe_threads = 0 if parsed_threads <= 0 else min(64, parsed_threads)
                except Exception:
                    safe_threads = 0

                sub_style = (
                    f"FontName=Arial,FontSize={safe_font_size},"
                    f"PrimaryColour={primary_colour},OutlineColour=&H00000000,"
                    f"Bold=1,Outline=2,Shadow=1"
                )

                # Filtro de escala: se max_height > 0, limita altura mantendo proporção
                # scale=-2:min(ih\,MAX) → reduz se o vídeo for maior que MAX, mantém se menor
                if safe_max_h > 0:
                    scale_filter = f"scale=-2:min(ih\\,{safe_max_h})"
                else:
                    scale_filter = None  # sem escala, resolução original

                if logo_specs:
                    parts: List[str] = []
                    if scale_filter:
                        parts.append(f"[0:v]{scale_filter}[vbase]")
                        current_label = "[vbase]"
                    else:
                        current_label = "[0:v]"

                    # Subtitles FIRST so logo (overlaid next) sits on top at its
                    # original position and never gets pushed out of place.
                    if not skip_subtitles:
                        sub_filter = f"subtitles={srt_path}:charenc=utf-8:force_style='{sub_style}'"
                        parts.append(f"{current_label}{sub_filter}[vsub]")
                        current_label = "[vsub]"

                    for idx, spec in enumerate(logo_specs):
                        input_idx = idx + 1
                        logo_scaled_label = f"lgs{idx}"
                        base_label = f"lb{idx}"
                        logo_label = f"lg{idx}"
                        out_label = f"vlogo{idx}"
                        scale_boost = max(1.0, min(float(spec.get("scale_boost", 1.0) or 1.0), 1.6))
                        scale_ratio = max(0.05, min((float(spec.get("scale_pct", 20.0)) / 100.0) * scale_boost, 1.0))
                        height_scale = max(1.0, min(float(spec.get("height_scale", 1.0) or 1.0), 1.6))
                        alpha_ratio = max(0.05, min(float(spec.get("opacity", 85.0)) / 100.0, 1.0))
                        _append_logo_aspect_locked_scale(
                            parts,
                            input_idx=input_idx,
                            base_ref=current_label,
                            logo_scaled_label=logo_scaled_label,
                            base_label=base_label,
                            scale_ratio=scale_ratio,
                            tag=f"burn_logo_{idx}",
                            height_scale=height_scale,
                            video_sar=video_sar,
                        )
                        chain = f"[{logo_scaled_label}]format=rgba,setsar=1"
                        if bool(spec.get("remove_bg")):
                            col = str(spec.get("bg_key_color") or "#ffffff").replace("#", "")
                            sim = max(0.01, min(float(spec.get("bg_similarity", 0.18)), 0.60))
                            blend = max(0.0, min(float(spec.get("bg_blend", 0.08)), 0.40))
                            chain += f",colorkey=0x{col.upper()}:{sim:.3f}:{blend:.3f}"
                        chain += f",colorchannelmixer=aa={alpha_ratio:.3f}[{logo_label}]"
                        parts.append(chain)
                        x = max(0.0, min(float(spec.get("x", 97.0)), 100.0))
                        y = max(0.0, min(float(spec.get("y", 97.0)), 100.0))
                        parts.append(
                            f"[{base_label}][{logo_label}]overlay=(W-w)*{x:.4f}/100:(H-h)*{y:.4f}/100:eof_action=repeat:shortest=1[{out_label}]"
                        )
                        current_label = f"[{out_label}]"

                    parts.append(f"{current_label}format=yuv420p[out]")
                    fcomplex = ";".join(parts)
                    logo_input_args: List[str] = []
                    for spec in logo_specs:
                        if bool(spec.get("is_gif")):
                            logo_input_args.extend(["-stream_loop", "-1", "-ignore_loop", "0", "-i", str(spec.get("path"))])
                        else:
                            logo_input_args.extend(["-loop", "1", "-i", str(spec.get("path"))])
                    cmd = [
                        "ffmpeg", "-y",
                        "-err_detect", "ignore_err",
                        "-fflags", "+discardcorrupt",
                        "-i", in_path,
                        *logo_input_args,
                        "-filter_complex", fcomplex,
                        "-map", "[out]", "-map", "0:a?",
                        "-threads", str(safe_threads),
                        "-c:v", "libx264", "-crf", str(safe_crf), "-preset", safe_preset,
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        "-progress", "pipe:1",
                        out_path,
                    ]
                else:
                    if skip_subtitles:
                        # Sem legenda: só recodifica (com escala se necessário)
                        if scale_filter:
                            vf = scale_filter
                        else:
                            vf = None
                    else:
                        if scale_filter:
                            vf = f"{scale_filter},subtitles={srt_path}:charenc=utf-8:force_style='{sub_style}'"
                        else:
                            vf = f"subtitles={srt_path}:charenc=utf-8:force_style='{sub_style}'"
                    cmd = [
                        "ffmpeg", "-y",
                        "-err_detect", "ignore_err",
                        "-fflags", "+discardcorrupt",
                        "-i", in_path,
                        *(["-vf", vf] if vf else []),
                        "-map", "0:v:0", "-map", "0:a?",
                        "-threads", str(safe_threads),
                        "-c:v", "libx264", "-crf", str(safe_crf), "-preset", safe_preset,
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        "-progress", "pipe:1",
                        out_path,
                    ]
                # stderr → file to avoid pipe buffer deadlock when reading stdout
                with open(stderr_path, "wb") as ferr:
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ferr)
                _burn_set_proc(job_id, proc)
                last_persisted_pct = -1
                try:
                    for raw_line in iter(proc.stdout.readline, b""):
                        if _burn_cancel_requested(job_id):
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            proc.wait()
                            return 130, "cancelled_by_user"
                        kv = raw_line.decode("utf-8", errors="replace").strip()
                        if kv.startswith("out_time=") and duration_secs > 0:
                            try:
                                parts = kv.split("=", 1)[1].split(":")
                                secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                                pct = min(99, int(secs / duration_secs * 100))
                                if pct >= (last_persisted_pct + 3):
                                    _burn_jobs[job_id]["detail"] = f"Processando ffmpeg… {pct}%"
                                    _burn_job_patch(job_id, {"detail": f"Processando ffmpeg… {pct}%", "progress_pct": pct})
                                    last_persisted_pct = pct
                            except Exception:
                                pass
                    proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise
                finally:
                    _burn_set_proc(job_id, None)
                _burn_job_patch(job_id, {"detail": "Salvando vídeo queimado…", "progress_pct": 99})
                try:
                    with open(stderr_path, "rb") as ferr:
                        stderr_text = ferr.read().decode("utf-8", errors="replace")
                except Exception:
                    stderr_text = ""
                return proc.returncode, stderr_text

            returncode, stderr_text = await asyncio.to_thread(_run_ffmpeg_progress)
            try:
                output_duration_secs = _probe_duration(out_path) if os.path.exists(out_path) else 0.0
            except Exception:
                output_duration_secs = 0.0
            safe_crf = max(18, min(int(effective_output_crf or 26), 35))
            safe_preset = str(effective_x264_preset or "ultrafast").strip().lower()
            if safe_preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
                safe_preset = "ultrafast"
            burn_threads_raw = os.environ.get("FFMPEG_BURN_THREADS", "0").strip()
            try:
                parsed_threads = int(burn_threads_raw)
                safe_threads = 0 if parsed_threads <= 0 else min(64, parsed_threads)
            except Exception:
                safe_threads = 0
            final_output_path = out_path
            recovery_warning = None

            if returncode == 130 and _burn_cancel_requested(job_id):
                _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
                return

            output_is_usable = _is_nearly_full_duration(
                expected_seconds=duration_secs,
                actual_seconds=output_duration_secs,
            )
            if duration_secs > 0 and output_duration_secs > 0 and not output_is_usable:
                _burn_job_patch(job_id, {"detail": "Arquivo original corrompido; concluindo em modo de recuperação…"})
                recovery = await asyncio.to_thread(
                    _attempt_truncated_burn_recovery,
                    out_path=out_path,
                    expected_duration=duration_secs,
                    actual_duration=output_duration_secs,
                    crf=safe_crf,
                    preset=safe_preset,
                    threads=safe_threads,
                )
                if recovery:
                    final_output_path = str(recovery.get("path") or out_path)
                    output_duration_secs = float(recovery.get("duration") or output_duration_secs)
                    output_is_usable = _is_nearly_full_duration(
                        expected_seconds=duration_secs,
                        actual_seconds=output_duration_secs,
                    )
                    recovery_warning = str(recovery.get("warning") or "").strip() or None
                    if recovery_warning:
                        warning_notes.append(recovery_warning)
                        print(f"burn-subtitles recovery succeeded: {recovery_warning}", flush=True)

            if returncode != 0:
                if not output_is_usable:
                    failure = _classify_burn_failure(
                        stderr_text=stderr_text,
                        input_duration=duration_secs,
                        output_duration=output_duration_secs,
                    )
                    print(f"burn-subtitles ffmpeg error: {failure['detail']}")
                    _burn_job_patch(job_id, {"status": "error", **failure})
                    return
                print(
                    "burn-subtitles ffmpeg returned non-zero but output duration looks complete; "
                    f"continuando com o arquivo gerado. detail={_summarize_ffmpeg_stderr(stderr_text)}"
                )
                if preflight_issue:
                    warning_notes.append(
                        "O ffmpeg reportou erro, mas o arquivo final ficou utilizável e foi mantido."
                    )

            if duration_secs > 0 and output_duration_secs > 0 and not output_is_usable:
                failure = _classify_burn_failure(
                    stderr_text=stderr_text,
                    input_duration=duration_secs,
                    output_duration=output_duration_secs,
                )
                print(f"burn-subtitles output truncated: {failure['detail']}")
                _burn_job_patch(job_id, {"status": "error", **failure})
                return

            if _burn_cancel_requested(job_id):
                _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
                return

            filename = f"legendado_{run_id[:8]}.mp4"
            effective_filename = output_filename or filename
            effective_prefix = output_prefix or f"burns/{run_id[:8]}"
            _burn_job_patch(job_id, {"detail": "Salvando vídeo queimado…", "progress_pct": 99})
            try:
                stored = await asyncio.to_thread(
                    _store_local_path,
                    src_path=final_output_path,
                    prefix=effective_prefix,
                    filename=effective_filename,
                    content_type="video/mp4",
                )
                result_key = str(stored.get("object_key") or "")
                done_payload = {
                    "status": "done",
                    "progress_pct": 100,
                    "video_url": stored.get("public_url"),
                    "filename": effective_filename,
                    "object_key": result_key,
                    "cancel_requested": False,
                }
                final_warning = " ".join([note.strip() for note in warning_notes if note and note.strip()]).strip()
                if final_warning:
                    done_payload["warning"] = final_warning
                _burn_job_patch(job_id, done_payload)
                if wizard_update_kind == "teaser_logo":
                    _merge_run_wizard_state(
                        run_id,
                        {
                            "teaser_logo_object_key": result_key,
                            "teaser_logo_filename": effective_filename,
                        },
                    )
                else:
                    _merge_run_wizard_state(
                        run_id,
                        {
                            "burned_object_key": result_key,
                            "burned_filename": filename,
                            "burned_quality": str(output_crf),
                            "burned_resolution": str(max_height),
                            "burned_preset": str(x264_preset),
                        },
                    )
                return
            except Exception as upload_err:
                print(f"burn-subtitles local store failed ({upload_err})")
                _burn_job_patch(job_id, {"status": "error", "error": "upload_failed", "detail": str(upload_err)})
                return
    except Exception as e:
        print(f"burn-subtitles worker exception: {traceback.format_exc()}")
        if _burn_cancel_requested(job_id):
            _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
        else:
            _burn_job_patch(job_id, {"status": "error", "error": "internal_error", "detail": str(e)})
    finally:
        _burn_set_proc(job_id, None)
        _burn_worker_semaphore.release()
        _burn_dequeue(job_id)
        if cleanup_temp and object_key:
            try:
                await asyncio.to_thread(_delete_media_ref, media_ref=object_key, s3=s3)
            except Exception:
                pass


@app.post("/api/burn-subtitles")
async def burn_subtitles(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    run_id = body.get("run_id", "").strip()
    if not run_id:
        return JSONResponse({"error": "missing_run_id"}, status_code=400)
    caller_object_key = body.get("video_object_key", "").strip()
    logo_b64 = body.get("logo_b64", "").strip()
    logos_raw = body.get("logos")
    logos: List[Dict[str, Any]] = []
    if isinstance(logos_raw, list):
        for raw in logos_raw[:MAX_LOGO_OVERLAYS]:
            if not isinstance(raw, dict) or raw.get("enabled") is False:
                continue
            raw_b64 = str(raw.get("b64") or raw.get("logo_b64") or raw.get("src") or "").strip()
            if not raw_b64:
                continue
            try:
                raw_x = max(0.0, min(float(raw.get("x", raw.get("logo_x", 97.0))), 100.0))
                raw_y = max(0.0, min(float(raw.get("y", raw.get("logo_y", 97.0))), 100.0))
                raw_scale = max(5.0, min(float(raw.get("scale_pct", raw.get("logo_scale_pct", 20.0))), 100.0))
                raw_opacity = max(5.0, min(float(raw.get("opacity", raw.get("logo_opacity", 85.0))), 100.0))
            except Exception:
                continue
            logos.append({
                "b64": raw_b64,
                "name": str(raw.get("name") or raw.get("logo_name") or f"logo_{len(logos) + 1}.png"),
                "x": raw_x,
                "y": raw_y,
                "scale_pct": raw_scale,
                "opacity": raw_opacity,
                "enabled": True,
            })
    font_size = int(body.get("font_size") or 22)
    font_color = str(body.get("font_color") or "white").strip().lower()
    sub_delay_secs = float(body.get("sub_delay_secs") or 0.0)
    output_crf = max(18, min(int(body.get("output_crf") or 26), 35))
    max_height = max(0, _int_with_default(body.get("max_height"), 1080))
    logo_x = max(0, min(int(body.get("logo_x") or 97), 100))
    logo_y = max(0, min(int(body.get("logo_y") or 97), 100))
    logo_scale_pct = max(5.0, min(float(body.get("logo_scale_pct") or 20.0), 100.0))
    logo_opacity = max(5.0, min(float(body.get("logo_opacity") or 85.0), 100.0))
    x264_preset = str(body.get("x264_preset") or "ultrafast").strip().lower()
    if x264_preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
        x264_preset = "ultrafast"
    skip_subtitles = bool(body.get("skip_subtitles", False))
    body_logo_profile_id = str(body.get("logo_profile_id") or "").strip()
    body_logo_profile_name = str(body.get("logo_profile_name") or "").strip()
    body_logo_profile_layout_linked = _coerce_optional_bool(body.get("logo_profile_layout_linked"))
    body_has_logo_layout_payload = _has_logo_layout_payload(body)

    r = get_run(run_id)
    if not r:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    transcript_meta: Dict[str, Any] = {}
    try:
        req_data = json.loads(r["request_json"]) if isinstance(r["request_json"], str) else (r.get("request_json") or {})
        transcript_meta = req_data.get("transcript") or {}
        if not isinstance(transcript_meta, dict):
            transcript_meta = {}
        wizard_state = _safe_json_obj(req_data.get("wizard_state"))
        effective_logo_profile_id = body_logo_profile_id or str(wizard_state.get("logo_profile_id") or "").strip()
        effective_logo_profile_name = body_logo_profile_name or str(wizard_state.get("logo_profile_name") or "").strip()
        effective_logo_profile_layout_linked = body_logo_profile_layout_linked
        if effective_logo_profile_layout_linked is None:
            effective_logo_profile_layout_linked = _coerce_optional_bool(wizard_state.get("logo_profile_layout_linked"))
        has_logo_profile_ref = bool(effective_logo_profile_id or effective_logo_profile_name)
        if effective_logo_profile_layout_linked is None and has_logo_profile_ref:
            effective_logo_profile_layout_linked = True
        linked_profile = _find_logo_profile(
            profile_id=effective_logo_profile_id,
            company_name=effective_logo_profile_name,
        ) if has_logo_profile_ref else None
        if linked_profile:
                def _layout_differs() -> bool:
                    if not body_has_logo_layout_payload:
                        return False
                    try:
                        return (
                            abs(float(logo_x) - float(linked_profile.get("logo_x") or 0.0)) > 0.05
                            or abs(float(logo_y) - float(linked_profile.get("logo_y") or 0.0)) > 0.05
                            or abs(float(logo_scale_pct) - float(linked_profile.get("logo_scale_pct") or 0.0)) > 0.05
                            or abs(float(logo_opacity) - float(linked_profile.get("logo_opacity") or 0.0)) > 0.05
                        )
                    except Exception:
                        return False
                if _layout_differs():
                    effective_logo_profile_layout_linked = False
                if effective_logo_profile_layout_linked:
                    logo_x = max(0, min(int(linked_profile.get("logo_x") or logo_x), 100))
                    logo_y = max(0, min(int(linked_profile.get("logo_y") or logo_y), 100))
                    logo_scale_pct = max(5.0, min(float(linked_profile.get("logo_scale_pct") or logo_scale_pct), 100.0))
                    logo_opacity = max(5.0, min(float(linked_profile.get("logo_opacity") or logo_opacity), 100.0))
                if not logos:
                    profile_logos = _logo_profile_to_payload_logos(linked_profile)
                    if profile_logos:
                        logos = profile_logos
                        # Apply user position overrides (frontend sends these when logos have no b64)
                        pos_overrides = body.get("logo_position_overrides") or []
                        for i, ov in enumerate(pos_overrides[:len(logos)]):
                            if not isinstance(ov, dict):
                                continue
                            if ov.get("x") is not None:
                                logos[i]["x"] = max(0.0, min(float(ov["x"]), 100.0))
                            if ov.get("y") is not None:
                                logos[i]["y"] = max(0.0, min(float(ov["y"]), 100.0))
                            if ov.get("scale_pct") is not None:
                                logos[i]["scale_pct"] = max(5.0, min(float(ov["scale_pct"]), 100.0))
                            if ov.get("opacity") is not None:
                                logos[i]["opacity"] = max(5.0, min(float(ov["opacity"]), 100.0))
                        if not effective_logo_profile_layout_linked and not pos_overrides and logos:
                            # Layout desvinculado não pode bloquear a imagem da logo.
                            # Sem overrides por-logo, usa a posição/tamanho enviados no payload legado.
                            logos[0]["x"] = logo_x
                            logos[0]["y"] = logo_y
                            logos[0]["scale_pct"] = logo_scale_pct
                            logos[0]["opacity"] = logo_opacity
                        first_logo = logos[0]
                        logo_b64 = str(first_logo.get("b64") or logo_b64)
                        logo_x = max(0, min(int(first_logo.get("x") or logo_x), 100))
                        logo_y = max(0, min(int(first_logo.get("y") or logo_y), 100))
                        logo_scale_pct = max(5.0, min(float(first_logo.get("scale_pct") or logo_scale_pct), 100.0))
                        logo_opacity = max(5.0, min(float(first_logo.get("opacity") or logo_opacity), 100.0))
                if not logo_b64:
                    profile_logo_ref = str(linked_profile.get("logo_object_key") or "").strip()
                    if profile_logo_ref:
                        logo_b64 = _media_ref_to_data_url(profile_logo_ref)
        srt_content = (body.get("srt_content") or "").strip()
        if not srt_content:
            srt_content = (transcript_meta.get("srt") or "").strip()
            if not srt_content:
                segments = transcript_meta.get("segments") or []
                srt_content = _format_srt(segments)
    except Exception as e:
        return JSONResponse({"error": "parse_error", "detail": str(e)}, status_code=500)
    if not srt_content and not skip_subtitles:
        return JSONResponse({"error": "no_transcript", "detail": "Este run não tem transcrição disponível."}, status_code=400)

    if srt_content and not skip_subtitles:
        provider_meta = _safe_json_obj(transcript_meta.get("provider_meta")) if isinstance(transcript_meta, dict) else {}
        timing_quality = str(
            transcript_meta.get("timing_quality")
            or provider_meta.get("timing_quality")
            or ""
        ).strip().lower()
        burn_safe_flag = transcript_meta.get("burn_safe")
        if burn_safe_flag is None:
            burn_safe_flag = provider_meta.get("burn_safe")
        duration_hint = 0.0
        for src in (body.get("video_metadata"), body.get("probe"), req_data.get("video_metadata"), req_data.get("probe")):
            meta_obj = _safe_json_obj(src)
            try:
                duration_hint = float(meta_obj.get("duration_seconds") or meta_obj.get("duration") or duration_hint or 0.0)
            except Exception:
                pass
        timing_diag = _srt_timing_diagnostics(srt_content, media_duration_seconds=duration_hint)
        if timing_diag.get("likely_synthetic_chunk_timing"):
            repaired_srt = _retime_synthetic_chunk_srt(
                srt_content,
                media_duration_seconds=float(timing_diag.get("media_duration_seconds") or duration_hint or 0.0),
            )
            repaired_diag = _srt_timing_diagnostics(repaired_srt, media_duration_seconds=duration_hint)
            if repaired_diag.get("likely_synthetic_chunk_timing"):
                return JSONResponse(
                    {
                        "error": "subtitle_timing_not_burn_safe",
                        "detail": (
                            "Esta legenda tem timestamps estimados por blocos e o reparo automático não conseguiu "
                            "corrigir com segurança. Transcreva novamente ou importe um SRT revisado."
                        ),
                        "timing_quality": timing_quality or "unknown",
                        "timing": timing_diag,
                        "repaired_timing": repaired_diag,
                    },
                    status_code=400,
                )
            srt_content = repaired_srt
            timing_diag = repaired_diag
        elif burn_safe_flag is False and "chunk" in timing_quality:
            return JSONResponse(
                {
                    "error": "subtitle_timing_not_burn_safe",
                    "detail": (
                        "Esta legenda veio de texto sem timestamps reais e não parece reparável automaticamente. "
                        "Use um SRT revisado ou transcreva novamente."
                    ),
                    "timing_quality": timing_quality or "unknown",
                    "timing": timing_diag,
                },
                status_code=400,
            )

    _merge_run_wizard_state(run_id, {
        "logo_x": logo_x,
        "logo_y": logo_y,
        "logo_scale_pct": logo_scale_pct,
        "logo_opacity": logo_opacity,
        "burn_logo_count": len(logos) if logos else (1 if logo_b64 else 0),
        "logo_profile_layout_linked": True if effective_logo_profile_layout_linked else False if effective_logo_profile_layout_linked is not None else None,
        "burned_quality": str(output_crf),
        "burned_resolution": str(max_height),
        "burned_preset": str(x264_preset),
    })
    import logging as _logging
    _logging.getLogger("uvicorn.error").warning(
        f"[burn-subtitles/start.logo] run_id={run_id} skip_subtitles={skip_subtitles} "
        f"logo_present={bool(logo_b64) or bool(logos)} logo_count={len(logos) if logos else (1 if logo_b64 else 0)} "
        f"profile_id={body_logo_profile_id or ''} profile_name={body_logo_profile_name or ''} "
        f"layout_linked={effective_logo_profile_layout_linked}"
    )

    job_id = str(uuid.uuid4())
    _burn_job_put(job_id, {
        "status": "pending",
        "progress_pct": 0,
        "detail": "Aguardando fila de processamento…",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cancel_requested": False,
        "run_id": run_id,
        "logo_count": len(logos) if logos else (1 if logo_b64 else 0),
    })
    _burn_control(job_id)
    _burn_enqueue(job_id)
    asyncio.create_task(_burn_subtitles_worker(
        job_id, run_id, caller_object_key, srt_content, req_data,
        logo_b64=logo_b64, logos=logos, font_size=font_size, font_color=font_color, sub_delay_secs=sub_delay_secs,
        output_crf=output_crf, max_height=max_height, logo_x=logo_x, logo_y=logo_y,
        logo_scale_pct=logo_scale_pct, logo_opacity=logo_opacity, x264_preset=x264_preset,
        skip_subtitles=skip_subtitles,
        wizard_update_kind="burn",
    ))
    return JSONResponse({"job_id": job_id})


@app.get("/api/burn-subtitles/status/{job_id}")
async def burn_subtitles_status(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = _burn_job_get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    payload = dict(job)
    if payload.get("status") == "pending":
        qpos, qsize = _burn_queue_info(job_id)
        if qpos is not None:
            payload["queue_position"] = qpos
            payload["queue_size"] = qsize
    payload["can_cancel"] = payload.get("status") in {"pending", "running"}
    return JSONResponse(payload)


@app.post("/api/burn-subtitles/cancel/{job_id}")
async def burn_subtitles_cancel(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = _burn_job_get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)

    status = (job.get("status") or "").lower()
    if status in {"done", "error", "cancelled"}:
        return JSONResponse({"ok": True, "status": status})

    proc = _burn_request_cancel(job_id)
    if status == "pending":
        _burn_dequeue(job_id)
        _burn_job_patch(job_id, {"status": "cancelled", "detail": "Processamento cancelado pelo usuário.", "cancel_requested": True})
        return JSONResponse({"ok": True, "status": "cancelled"})

    if status == "running":
        try:
            if proc and proc.poll() is None:
                await asyncio.to_thread(proc.kill)
        except Exception:
            pass
        _burn_job_patch(job_id, {"detail": "Cancelando processamento…", "cancel_requested": True})
        return JSONResponse({"ok": True, "status": "running", "detail": "Cancelamento solicitado."})

    return JSONResponse({"ok": True, "status": status or "pending"})


@app.get("/api/burn-subtitles/queue")
async def burn_subtitles_queue(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    try:
        pending_rows = async_job_list(kind=_ASYNC_JOB_KIND_BURN, statuses=["pending"], limit=200)
        running_rows = async_job_list(kind=_ASYNC_JOB_KIND_BURN, statuses=["running"], limit=200)
    except Exception as e:
        detail = _safe_error_detail(e, "queue_temporarily_unavailable")
        print(f"[burn-queue] unable to read queue: {detail}", flush=True)
        return JSONResponse({"ok": False, "pending": [], "running": [], "detail": detail})

    pending_items: List[Dict[str, Any]] = []
    for idx, j in enumerate(pending_rows, start=1):
        pending_items.append(
            {
                "job_id": j.get("job_id") or "",
                "position": idx,
                "status": j.get("status") or "pending",
                "detail": j.get("detail") or "Aguardando fila…",
                "progress_pct": j.get("progress_pct", 0),
                "run_id": j.get("run_id") or "",
                "logo_count": j.get("logo_count", 0),
                "updated_at": j.get("updated_at") or "",
                "created_at": j.get("created_at") or "",
            }
        )

    running_items: List[Dict[str, Any]] = []
    for j in running_rows:
        running_items.append(
            {
                "job_id": j.get("job_id") or "",
                "status": j.get("status") or "running",
                "detail": j.get("detail") or "Processando…",
                "progress_pct": j.get("progress_pct", 0),
                "run_id": j.get("run_id") or "",
                "logo_count": j.get("logo_count", 0),
                "updated_at": j.get("updated_at") or "",
                "created_at": j.get("created_at") or "",
            }
        )

    return JSONResponse({"ok": True, "pending": pending_items, "running": running_items})


# ── Teaser generation ─────────────────────────────────────────────────────────
# Gera um teaser com as melhores cenas do vídeo usando detecção de cenas do ffmpeg.
# Suporta também concatenação (teaser + vídeo principal) via _concat_worker.

_teaser_jobs: Dict[str, Dict] = {}
_drive_upload_jobs: Dict[str, Dict] = {}
_drive_import_jobs: Dict[str, Dict] = {}


async def _drive_upload_worker(job_id: str, *, object_key: str, folder_id: str, filename: str = "") -> None:
    safe_object_key = str(object_key or "").strip()
    safe_folder_id = str(folder_id or "").strip()
    safe_filename = _safe_storage_filename(filename or os.path.basename(_media_ref_relative_path(safe_object_key) or "arquivo.mp4"), "arquivo.mp4")
    _drive_upload_job_patch(job_id, {
        "status": "running",
        "detail": "Preparando upload para o Google Drive…",
        "object_key": safe_object_key,
        "filename": safe_filename,
        "folder_id": safe_folder_id,
        "progress_pct": 0,
    })
    tmpdir_obj = None
    try:
        local_path = ""
        if _is_local_media_ref(safe_object_key):
            local_path = _local_media_abs_path_from_ref(safe_object_key)
        else:
            tmpdir_obj = tempfile.TemporaryDirectory(prefix="drive-upload-", dir=_preferred_tmpdir_root("drive"))
            local_path = os.path.join(tmpdir_obj.name, safe_filename)
            _drive_upload_job_patch(job_id, {"detail": "Baixando arquivo do storage para envio…"})
            await asyncio.to_thread(_download_media_ref_to_file, media_ref=safe_object_key, out_path=local_path, s3=_s3_client())

        def _progress_cb(progress: float) -> None:
            pct = int(max(0.0, min(float(progress or 0.0), 1.0)) * 100)
            _drive_upload_job_patch(job_id, {
                "status": "running",
                "detail": f"Enviando ao Google Drive… {pct}%",
                "progress_pct": pct,
            })

        uploaded = await asyncio.to_thread(
            _google_drive_upload_path_sync,
            src_path=local_path,
            filename=safe_filename,
            folder_id=safe_folder_id,
            progress_cb=_progress_cb,
        )
        _drive_upload_job_patch(job_id, {
            "status": "done",
            "detail": "Arquivo enviado ao Google Drive.",
            "progress_pct": 100,
            "drive_file_id": str(uploaded.get("id") or "").strip(),
            "drive_name": str(uploaded.get("name") or safe_filename).strip(),
            "drive_web_view_link": str(uploaded.get("webViewLink") or "").strip(),
            "drive_download_link": str(uploaded.get("webContentLink") or "").strip(),
        })
    except Exception as exc:
        _drive_upload_job_patch(job_id, {
            "status": "error",
            "detail": _safe_error_detail(exc, "google_drive_upload_failed"),
        })
    finally:
        if tmpdir_obj is not None:
            try:
                tmpdir_obj.cleanup()
            except Exception:
                pass


async def _drive_import_worker(
    job_id: str,
    *,
    creator_id: str,
    drive_file_id: str,
    filename: str = "",
) -> None:
    safe_creator_id = str(creator_id or "").strip()
    safe_drive_file_id = str(drive_file_id or "").strip()
    cfg = _google_drive_creator_config(safe_creator_id)
    _drive_import_job_patch(job_id, {
        "status": "running",
        "detail": "Preparando importação do Google Drive…",
        "creator_id": safe_creator_id,
        "drive_file_id": safe_drive_file_id,
        "progress_pct": 0,
    })
    try:
        if not cfg.get("configured"):
            raise RuntimeError(cfg.get("detail") or "google_drive_not_configured")
        raw_creds = str(cfg.get("_raw_service_account") or "")
        file_meta = await asyncio.to_thread(
            _google_drive_file_metadata_sync,
            file_id=safe_drive_file_id,
            raw_creds=raw_creds,
        )
        safe_filename = _safe_storage_filename(
            filename or str(file_meta.get("name") or "drive-import.bin"),
            "drive-import.bin",
        )
        creator_name = str(cfg.get("creator_name") or safe_creator_id or "creator").strip()
        creator_folder = _safe_storage_filename(creator_name, safe_creator_id or "creator")
        upload_prefix = f"uploads/creator-drive/{creator_folder}"

        with tempfile.TemporaryDirectory(prefix="drive-import-", dir=_preferred_tmpdir_root("drive")) as tmpdir:
            local_path = os.path.join(tmpdir, safe_filename)
            _drive_import_job_patch(job_id, {
                "detail": "Baixando arquivo do Google Drive…",
                "progress_pct": 12,
                "filename": safe_filename,
            })

            def _progress_cb(progress: float) -> None:
                pct = int(max(0.0, min(float(progress or 0.0), 1.0)) * 100)
                _drive_import_job_patch(job_id, {
                    "status": "running",
                    "detail": f"Baixando arquivo do Google Drive… {pct}%",
                    "progress_pct": 12 + int(round(pct * 0.68)),
                })

            await asyncio.to_thread(
                _google_drive_download_file_sync,
                file_id=safe_drive_file_id,
                out_path=local_path,
                raw_creds=raw_creds,
                progress_cb=_progress_cb,
            )
            _drive_import_job_patch(job_id, {
                "detail": "Salvando arquivo no servidor…",
                "progress_pct": 84,
            })
            stored = await asyncio.to_thread(
                _store_local_path,
                src_path=local_path,
                prefix=upload_prefix,
                filename=safe_filename,
                content_type=str(file_meta.get("mime_type") or "application/octet-stream"),
            )

        _drive_import_job_patch(job_id, {
            "status": "done",
            "detail": "Arquivo recebido do Google Drive com sucesso.",
            "progress_pct": 100,
            "filename": safe_filename,
            "imported_item": stored,
            "object_key": str(stored.get("object_key") or "").strip(),
            "creator_name": creator_name,
            "drive_file": file_meta,
        })
    except Exception as exc:
        _drive_import_job_patch(job_id, {
            "status": "error",
            "detail": _safe_error_detail(exc, "google_drive_import_failed"),
        })


async def _teaser_worker(
    job_id: str,
    video_object_key: str,
    logo_b64: str,
    num_clips: int,
    clip_duration: float,
    output_crf: int,
    output_max_height: int = 1080,
    output_max_fps: float = 30.0,
    run_id: Optional[str] = None,
    source_type: str = "burned",
    selected_frame_indexes: Optional[List[int]] = None,
    frames_count: int = 0,
    manual_scene_durations: Optional[Dict[int, float]] = None,
    ordered_scene_durations: Optional[List[float]] = None,
    logos: Optional[List[Dict[str, Any]]] = None,
    logo_x: int = 97,
    logo_y: int = 97,
    logo_scale_pct: float = 20.0,
    logo_opacity: float = 85.0,
    narration_enabled: bool = False,
    original_audio_volume: float = 1.0,
    narration_volume: float = 1.15,
    narration_object_key: str = "",
    narration_offset_sec: float = 0.0,
    opener_object_key: str = "",
    opener_position: str = "start",
) -> None:
    import traceback
    _teaser_job_patch(job_id, {"status": "running", "detail": "Inicializando…"})
    s3 = _s3_client()

    try:
        with tempfile.TemporaryDirectory(prefix="teaser-", dir=_preferred_tmpdir_root("teaser")) as tmpdir:
            in_path = os.path.join(tmpdir, "input_video")

            _teaser_job_patch(job_id, {"detail": "Baixando vídeo…"})
            if video_object_key:
                await asyncio.to_thread(_download_media_ref_to_file, media_ref=video_object_key, out_path=in_path, s3=s3)
            else:
                _teaser_job_put(job_id, {"status": "error", "error": "no_video", "detail": "Vídeo não encontrado."})
                return

            _teaser_job_patch(job_id, {"detail": "Analisando duração…"})
            duration = await asyncio.to_thread(_probe_duration, in_path)
            if duration <= 0:
                _teaser_job_put(job_id, {"status": "error", "error": "no_duration", "detail": "Não foi possível determinar a duração do vídeo."})
                return
            integrity_issue = await asyncio.to_thread(
                _quick_media_integrity_check,
                in_path=in_path,
                expected_duration=duration,
            )
            if integrity_issue:
                checkpoint = max(0.0, float(integrity_issue.get("checkpoint_seconds") or 0.0))
                detail = str(integrity_issue.get("detail") or "").strip() or "Falha na validação rápida da mídia."
                _teaser_job_put(
                    job_id,
                    {
                        "status": "error",
                        "error": "source_media_corrupt",
                        "detail": (
                            "O vídeo original falhou na validação prévia do teaser "
                            f"perto de {_format_media_clock(checkpoint)}.\n\n{detail}"
                        ),
                    },
                )
                return

            # Monta cenas com duração individual quando selecionadas manualmente.
            # Cada item: {timestamp, duration, source, frame_index}
            selected_scenes: List[Dict[str, Any]] = []
            _dur_map: Dict[int, float] = {}
            for raw_k, raw_v in (manual_scene_durations or {}).items():
                try:
                    ik = int(raw_k)
                    dv = float(raw_v)
                except Exception:
                    continue
                if ik < 0:
                    continue
                _dur_map[ik] = _clamp_teaser_scene_duration(dv, clip_duration)

            manual_indexes: List[int] = []
            _seen_manual: set = set()
            for raw_idx in (selected_frame_indexes or []):
                try:
                    ii = int(raw_idx)
                except Exception:
                    continue
                if ii < 0 or ii in _seen_manual:
                    continue
                _seen_manual.add(ii)
                manual_indexes.append(ii)

            stored_run_frame_timestamps: List[Any] = []
            rebuilt_run_frame_timestamps: List[float] = []
            if manual_indexes and run_id:
                run_row = get_run(run_id)
                if run_row:
                    result_data = _safe_json_obj(run_row.get("result_json"))
                    vision = _safe_json_obj(result_data.get("vision"))
                    raw_timestamps = vision.get("frame_timestamps")
                    if isinstance(raw_timestamps, list):
                        stored_run_frame_timestamps = raw_timestamps
                if not stored_run_frame_timestamps:
                    _thresh_s = settings_get(key="vision:scene_threshold")
                    _maxf_s = settings_get(key="vision:max_adult_frames")
                    scene_threshold = float(_thresh_s["value"]) if _thresh_s else 0.32
                    max_frames = max(
                        max(manual_indexes) + 1,
                        int(frames_count or 0),
                        int(_maxf_s["value"]) if _maxf_s else 10,
                    )
                    rebuilt_run_frame_timestamps = await asyncio.to_thread(
                        _build_intelligent_adult_keyframe_timestamps,
                        in_path=in_path,
                        duration=duration,
                        max_frames=max_frames,
                        scene_threshold=scene_threshold,
                    )

            if manual_indexes:
                if frames_count <= 1:
                    try:
                        frames_count = max(manual_indexes) + 1
                    except Exception:
                        frames_count = 0
                if frames_count > 1:
                    max_idx = frames_count - 1
                    manual_candidates: List[Dict[str, Any]] = []
                    for raw_idx in sorted(manual_indexes):
                        idx = min(raw_idx, max_idx)
                        t = _pick_frame_timestamp_by_index(
                            raw_idx,
                            frames_count,
                            duration,
                            stored_run_frame_timestamps or rebuilt_run_frame_timestamps,
                        )
                        if t is None:
                            ratio = ((idx + 1) / (frames_count + 1)) if max_idx > 0 else 0.5
                            t = max(0.0, min(duration - 0.05, duration * ratio))
                        d = _dur_map.get(raw_idx, _dur_map.get(idx, float(clip_duration)))
                        d = _clamp_teaser_scene_duration(d, clip_duration)
                        manual_candidates.append({
                            "timestamp": t,
                            "duration": d,
                            "source": "manual",
                            "frame_index": idx,
                        })

                    for sc in manual_candidates:
                        if not selected_scenes:
                            selected_scenes.append(sc)
                        else:
                            prev = selected_scenes[-1]
                            min_gap = max(
                                1.0,
                                min(float(prev.get("duration") or clip_duration), float(sc.get("duration") or clip_duration)) * 0.6,
                            )
                            if float(sc.get("timestamp") or 0.0) - float(prev.get("timestamp") or 0.0) >= min_gap:
                                selected_scenes.append(sc)
                        if len(selected_scenes) >= num_clips:
                            break

            # Completa com detecção automática se faltar cenas.
            timestamps: List[float] = []
            if len(selected_scenes) < num_clips:
                try:
                    timestamps = await asyncio.to_thread(_detect_scene_timestamps, in_path, 0.30, duration)
                except Exception:
                    timestamps = []

                # Se há poucas cenas, adiciona timestamps uniformes como fallback
                if len(timestamps) < (num_clips - len(selected_scenes)):
                    for r in [i / (num_clips + 1) for i in range(1, num_clips + 1)]:
                        t = duration * r
                        if not any(abs(t - ex) < clip_duration for ex in timestamps):
                            timestamps.append(t)
                    timestamps.sort()

                # Mescla seleção manual + automática sem sobreposição de janelas.
                for t in timestamps:
                    if any(abs(t - float(ex.get("timestamp") or 0.0)) < max(clip_duration, float(ex.get("duration") or clip_duration)) for ex in selected_scenes):
                        continue
                    selected_scenes.append({
                        "timestamp": float(t),
                        "duration": float(clip_duration),
                        "source": "auto",
                        "frame_index": None,
                    })
                    if len(selected_scenes) >= num_clips:
                        break
                selected_scenes = sorted(selected_scenes, key=lambda s: float(s.get("timestamp") or 0.0))[:num_clips]

            if not selected_scenes:
                selected_scenes = [
                    {
                        "timestamp": duration * (i + 1) / (num_clips + 1),
                        "duration": float(clip_duration),
                        "source": "auto",
                        "frame_index": None,
                    }
                    for i in range(num_clips)
                ]

            planned_ordered_durations: List[float] = []
            if isinstance(ordered_scene_durations, list):
                for raw_d in ordered_scene_durations[: max(0, int(num_clips or 0))]:
                    planned_ordered_durations.append(_clamp_teaser_scene_duration(raw_d, clip_duration))
            if planned_ordered_durations:
                while len(planned_ordered_durations) < len(selected_scenes):
                    planned_ordered_durations.append(float(clip_duration))
                for idx, scene in enumerate(selected_scenes):
                    if idx >= len(planned_ordered_durations):
                        break
                    scene["duration"] = float(planned_ordered_durations[idx])

            # Suporta múltiplas logos (incluindo GIF) no teaser.
            # Mantém compatibilidade com payload legado de logo única.
            logo_specs: List[Dict[str, Any]] = []
            raw_logos = logos if isinstance(logos, list) else []
            if raw_logos:
                for raw_logo in raw_logos[:6]:
                    if not isinstance(raw_logo, dict):
                        continue
                    b64_raw = str(raw_logo.get("b64") or raw_logo.get("logo_b64") or "").strip()
                    if not b64_raw:
                        continue
                    mime, payload = _parse_data_url(b64_raw)
                    if not payload:
                        continue
                    ext = _logo_ext_from_mime(mime)
                    path = os.path.join(tmpdir, f"logo_{len(logo_specs)}{ext}")
                    try:
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(payload))
                    except Exception:
                        continue
                    color_hex = _normalize_hex_color(raw_logo.get("bg_key_color") or "#ffffff", "#ffffff")
                    logo_specs.append({
                        "path": path,
                        "is_gif": bool(mime == "image/gif" or path.lower().endswith(".gif")),
                        "x": max(0.0, min(float(raw_logo.get("x", 97.0)), 100.0)),
                        "y": max(0.0, min(float(raw_logo.get("y", 97.0)), 100.0)),
                        "scale_pct": max(5.0, min(float(raw_logo.get("scale_pct", 20.0)), 100.0)),
                        "opacity": max(5.0, min(float(raw_logo.get("opacity", 85.0)), 100.0)),
                        "remove_bg": bool(raw_logo.get("remove_bg")),
                        "bg_key_color": color_hex,
                        "bg_similarity": max(0.01, min(float(raw_logo.get("bg_similarity", 0.18)), 0.60)),
                        "bg_blend": max(0.0, min(float(raw_logo.get("bg_blend", 0.08)), 0.40)),
                    })

            if not logo_specs and logo_b64:
                mime, payload = _parse_data_url(logo_b64)
                if payload:
                    ext = _logo_ext_from_mime(mime)
                    legacy_logo_path = os.path.join(tmpdir, f"logo_legacy{ext}")
                    try:
                        with open(legacy_logo_path, "wb") as f:
                            f.write(base64.b64decode(payload))
                        logo_specs.append({
                            "path": legacy_logo_path,
                            "is_gif": bool(mime == "image/gif" or legacy_logo_path.lower().endswith(".gif")),
                            "x": max(0.0, min(float(logo_x or 97), 100.0)),
                            "y": max(0.0, min(float(logo_y or 97), 100.0)),
                            "scale_pct": max(5.0, min(float(logo_scale_pct or 20.0), 100.0)),
                            "opacity": max(5.0, min(float(logo_opacity or 85.0), 100.0)),
                            "remove_bg": False,
                            "bg_key_color": "#ffffff",
                            "bg_similarity": 0.18,
                            "bg_blend": 0.08,
                        })
                    except Exception:
                        pass

            # Extrai cada clip
            clip_paths: List[str] = []
            clip_audio_flags: List[bool] = []
            clip_failures: List[str] = []
            safe_crf = max(20, min(int(output_crf or 26), 35))
            safe_output_max_h = max(480, min(int(output_max_height or 1080), 2160))
            safe_output_max_fps = max(24, min(int(output_max_fps or 30), 60))
            maxrate, bufsize, level = _encode_params_for_height(safe_output_max_h)
            teaser_video_filter = f"scale=-2:min(ih\\,{safe_output_max_h}):flags=lanczos"
            if safe_output_max_fps < 60:
                teaser_video_filter += f",fps={safe_output_max_fps}"
            teaser_video_encode_args = [
                "-c:v", "libx264",
                "-crf", str(safe_crf),
                "-preset", "veryfast",
                "-maxrate", maxrate,
                "-bufsize", bufsize,
                "-profile:v", "high",
                "-level:v", level,
                "-pix_fmt", "yuv420p",
                "-g", str(max(48, safe_output_max_fps * 2)),
                "-keyint_min", str(max(24, safe_output_max_fps)),
                "-sc_threshold", "0",
            ]
            def _clip_timeout_for_duration(scene_secs: float) -> int:
                safe_scene_secs = max(1.0, float(scene_secs or 1.0))
                return max(180, min(14400, int(safe_scene_secs * 12) + 600))

            clip_timeout_base = _clip_timeout_for_duration(clip_duration)

            def _build_logo_filter_chain() -> tuple[str, str]:
                if not logo_specs:
                    return "", ""
                parts: List[str] = [f"[0:v]{teaser_video_filter}[vbase]"]
                current_label = "vbase"
                for i, spec in enumerate(logo_specs):
                    input_idx = i + 1
                    logo_label = f"lg{i}"
                    logo_scaled_label = f"lgs{i}"
                    base_label = f"vb{i}"
                    out_label = "out" if i == (len(logo_specs) - 1) else f"v{i+1}"
                    scale_boost = max(1.0, min(float(spec.get("scale_boost", 1.0) or 1.0), 1.6))
                    scale_ratio = max(0.05, min((float(spec.get("scale_pct", 20.0)) / 100.0) * scale_boost, 0.60))
                    height_scale = max(1.0, min(float(spec.get("height_scale", 1.0) or 1.0), 1.6))
                    alpha_ratio = max(0.05, min(float(spec.get("opacity", 85.0)) / 100.0, 1.0))
                    _append_logo_aspect_locked_scale(
                        parts,
                        input_idx=input_idx,
                        base_ref=f"[{current_label}]",
                        logo_scaled_label=logo_scaled_label,
                        base_label=base_label,
                        scale_ratio=scale_ratio,
                        tag=f"teaser_logo_{i}",
                        height_scale=height_scale,
                    )
                    chain = f"[{logo_scaled_label}]format=rgba,setsar=1"
                    if bool(spec.get("remove_bg")):
                        col = str(spec.get("bg_key_color") or "#ffffff").replace("#", "")
                        sim = max(0.01, min(float(spec.get("bg_similarity", 0.18)), 0.60))
                        blend = max(0.0, min(float(spec.get("bg_blend", 0.08)), 0.40))
                        chain += f",colorkey=0x{col.upper()}:{sim:.3f}:{blend:.3f}"
                    chain += f",colorchannelmixer=aa={alpha_ratio:.3f}[{logo_label}]"
                    parts.append(chain)
                    x = max(0.0, min(float(spec.get("x", 97.0)), 100.0))
                    y = max(0.0, min(float(spec.get("y", 97.0)), 100.0))
                    parts.append(
                        f"[{base_label}][{logo_label}]overlay=(W-w)*{x:.4f}/100:(H-h)*{y:.4f}/100:eof_action=repeat:shortest=1[{out_label}]"
                    )
                    current_label = out_label
                return ";".join(parts), current_label

            def _run_ffmpeg_cmd(cmd_list: List[str], stderr_path: str, timeout_s: int) -> tuple[int, str]:
                with open(stderr_path, "wb") as ferr:
                    try:
                        proc = subprocess.run(
                            cmd_list,
                            stdout=subprocess.DEVNULL,
                            stderr=ferr,
                            timeout=timeout_s,
                        )
                        rc = int(proc.returncode)
                    except subprocess.TimeoutExpired:
                        return 124, "timeout"
                try:
                    with open(stderr_path, "rb") as ferr:
                        err_text = ferr.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    err_text = ""
                return rc, err_text[-500:]

            for i, scene in enumerate(selected_scenes):
                _teaser_jobs[job_id]["detail"] = f"Extraindo cena {i + 1}/{len(selected_scenes)}…"
                clip_path = os.path.join(tmpdir, f"clip_{i:03d}.mp4")
                t = float(scene.get("timestamp") or 0.0)
                scene_duration = _clamp_teaser_scene_duration(scene.get("duration"), clip_duration)
                max_start = max(0.0, duration - scene_duration)
                start = max(0.0, min(max_start, t - scene_duration / 2.0))
                clip_timeout = max(clip_timeout_base, _clip_timeout_for_duration(scene_duration))

                fcomplex = ""
                out_label = ""
                if logo_specs:
                    fcomplex, out_label = _build_logo_filter_chain()

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{start:.3f}", "-t", f"{scene_duration:.2f}",
                    "-i", in_path,
                ]
                if logo_specs:
                    for spec in logo_specs:
                        if bool(spec.get("is_gif")):
                            cmd.extend(["-stream_loop", "-1", "-ignore_loop", "0"])
                        else:
                            cmd.extend(["-loop", "1"])
                        cmd.extend(["-i", str(spec.get("path"))])
                if logo_specs and fcomplex and out_label:
                    cmd.extend(["-filter_complex", fcomplex, "-map", f"[{out_label}]"])
                else:
                    cmd.extend(["-vf", teaser_video_filter, "-map", "0:v:0"])
                cmd.extend([
                    "-map", "0:a?",
                    *teaser_video_encode_args,
                    "-c:a", "aac", "-b:a", "96k",
                    "-shortest",
                    "-movflags", "+faststart",
                    clip_path,
                ])

                stderr_f = os.path.join(tmpdir, f"clip_{i}_err.txt")
                clip_rc, clip_err = await asyncio.to_thread(_run_ffmpeg_cmd, cmd, stderr_f, clip_timeout)
                clip_invalid_reason = ""
                clip_has_audio = False
                if clip_rc == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                    clip_meta = await asyncio.to_thread(_probe_metadata, clip_path)
                    clip_needs_fix, clip_invalid_reason = _teaser_concat_needs_reencode(
                        clip_meta,
                        scene_duration,
                    )
                    clip_has_audio = bool(clip_meta.get("has_audio"))
                    if clip_needs_fix:
                        clip_rc = -1
                if clip_rc != 0:
                    # Fallback: se o encode do áudio falhar, ainda geramos um clip
                    # com trilha silenciosa do mesmo tamanho para manter a concat estável.
                    fallback_path = os.path.join(tmpdir, f"clip_{i:03d}_silence.mp4")
                    fallback_cmd = [
                        "ffmpeg", "-y",
                        "-ss", f"{start:.3f}", "-t", f"{scene_duration:.2f}",
                        "-i", in_path,
                    ]
                    if logo_specs:
                        for spec in logo_specs:
                            if bool(spec.get("is_gif")):
                                fallback_cmd.extend(["-stream_loop", "-1", "-ignore_loop", "0"])
                            else:
                                fallback_cmd.extend(["-loop", "1"])
                            fallback_cmd.extend(["-i", str(spec.get("path"))])
                    silent_audio_input_idx = 1 + len(logo_specs)
                    fallback_cmd.extend([
                        "-f", "lavfi",
                        "-t", f"{scene_duration:.2f}",
                        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    ])
                    if logo_specs and fcomplex and out_label:
                        fallback_cmd.extend(["-filter_complex", fcomplex, "-map", f"[{out_label}]"])
                    else:
                        fallback_cmd.extend(["-vf", teaser_video_filter, "-map", "0:v:0"])
                    fallback_cmd.extend([
                        "-map", f"{silent_audio_input_idx}:a:0",
                        *teaser_video_encode_args,
                        "-c:a", "aac", "-b:a", "96k",
                        "-shortest",
                        "-movflags", "+faststart",
                        fallback_path,
                    ])
                    stderr_f_fb = os.path.join(tmpdir, f"clip_{i}_fallback_err.txt")
                    fb_rc, fb_err = await asyncio.to_thread(_run_ffmpeg_cmd, fallback_cmd, stderr_f_fb, clip_timeout)
                    if fb_rc == 0 and os.path.exists(fallback_path) and os.path.getsize(fallback_path) > 0:
                        fallback_meta = await asyncio.to_thread(_probe_metadata, fallback_path)
                        fallback_needs_fix, fallback_reason = _teaser_concat_needs_reencode(
                            fallback_meta,
                            scene_duration,
                        )
                        if not fallback_needs_fix:
                            clip_paths.append(fallback_path)
                            clip_audio_flags.append(bool(fallback_meta.get("has_audio")))
                            continue
                        fb_err = fb_err or fallback_reason
                    reason = (
                        fb_err
                        or clip_invalid_reason
                        or clip_err
                        or ("timeout" if clip_rc == 124 or fb_rc == 124 else "ffmpeg_failed")
                    )
                    clip_failures.append(f"cena {i + 1}: {reason[:180]}")
                    continue

                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                    clip_paths.append(clip_path)
                    clip_audio_flags.append(bool(clip_has_audio))
                else:
                    clip_failures.append(f"cena {i + 1}: output vazio")

            if not clip_paths:
                _detail = "Nenhum clip foi extraído."
                if clip_failures:
                    _detail += " " + clip_failures[0]
                _detail += " Tente reduzir número de cenas, ajustar durações individuais ou remover logo."
                _teaser_job_put(job_id, {
                    "status": "error",
                    "error": "no_clips",
                    "detail": _detail,
                    "debug_failures": clip_failures[:5],
                })
                return

            # Concatena todos os clips
            _teaser_job_patch(job_id, {"detail": f"Concatenando {len(clip_paths)} cenas…"})
            list_path = os.path.join(tmpdir, "concat_list.txt")
            with open(list_path, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")

            total_teaser_secs = sum(_clamp_teaser_scene_duration(s.get("duration"), clip_duration) for s in selected_scenes) or (len(clip_paths) * clip_duration)
            out_path = os.path.join(tmpdir, "teaser.mp4")
            concat_cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-c", "copy",
                "-movflags", "+faststart",
                out_path,
            ]
            stderr_f = os.path.join(tmpdir, "concat_err.txt")
            def _run_concat_cmd() -> int:
                with open(stderr_f, "wb") as ferr:
                    try:
                        proc = subprocess.run(
                            concat_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=ferr,
                            timeout=300,
                        )
                        return int(proc.returncode)
                    except subprocess.TimeoutExpired:
                        return 124

            concat_rc = await asyncio.to_thread(_run_concat_cmd)
            concat_ok = concat_rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            concat_needs_reencode = False
            concat_reason = ""
            if concat_ok:
                concat_meta = await asyncio.to_thread(_probe_metadata, out_path)
                concat_needs_reencode, concat_reason = _teaser_concat_needs_reencode(concat_meta, total_teaser_secs)

            if not concat_ok or concat_needs_reencode:
                _teaser_job_patch(job_id, {"detail": "Normalizando timeline do teaser…"})
                out_path_reencoded = os.path.join(tmpdir, "teaser_reencode.mp4")
                concat_filter_parts: List[str] = []
                concat_filter_streams: List[str] = []
                concat_fallback_cmd = ["ffmpeg", "-y"]
                concat_has_audio = bool(clip_audio_flags) and all(clip_audio_flags) and len(clip_audio_flags) == len(clip_paths)
                for clip_idx, clip_file in enumerate(clip_paths):
                    concat_fallback_cmd.extend(["-i", clip_file])
                    concat_filter_parts.append(f"[{clip_idx}:v]setpts=PTS-STARTPTS[v{clip_idx}]")
                    if concat_has_audio:
                        concat_filter_parts.append(
                            f"[{clip_idx}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[a{clip_idx}]"
                        )
                        concat_filter_streams.append(f"[v{clip_idx}][a{clip_idx}]")
                    else:
                        concat_filter_streams.append(f"[v{clip_idx}]")
                if concat_has_audio:
                    concat_filter_parts.append(
                        "".join(concat_filter_streams) + f"concat=n={len(clip_paths)}:v=1:a=1[vcat][acat]"
                    )
                    concat_filter_parts.append(f"[vcat]fps={safe_output_max_fps},format=yuv420p[vout]")
                    concat_filter_parts.append("[acat]aresample=async=1:first_pts=0[aout]")
                else:
                    concat_filter_parts.append(
                        "".join(concat_filter_streams) + f"concat=n={len(clip_paths)}:v=1:a=0[vcat]"
                    )
                    concat_filter_parts.append(f"[vcat]fps={safe_output_max_fps},format=yuv420p[vout]")
                concat_fallback_cmd.extend([
                    "-filter_complex", ";".join(concat_filter_parts),
                    "-map", "[vout]",
                ])
                if concat_has_audio:
                    concat_fallback_cmd.extend(["-map", "[aout]"])
                concat_fallback_cmd.extend([
                    *teaser_video_encode_args,
                ])
                if concat_has_audio:
                    concat_fallback_cmd.extend(["-c:a", "aac", "-b:a", "96k"])
                concat_fallback_cmd.extend([
                    "-shortest",
                    "-t", f"{total_teaser_secs:.3f}",
                    "-movflags", "+faststart",
                    out_path_reencoded,
                ])
                concat_fallback_err = os.path.join(tmpdir, "concat_fallback_err.txt")
                concat_fallback_timeout = max(900, min(21600, int(max(30.0, total_teaser_secs) * 12) + 900))
                fb_rc, fb_err = await asyncio.to_thread(_run_ffmpeg_cmd, concat_fallback_cmd, concat_fallback_err, concat_fallback_timeout)
                if fb_rc != 0 or not os.path.exists(out_path_reencoded) or os.path.getsize(out_path_reencoded) < 1024:
                    detail = "Falha ao concatenar clips."
                    if concat_reason:
                        detail += f" Saída copiada ficou inválida ({concat_reason})."
                    if fb_err:
                        detail += f" Fallback: {fb_err[:220]}"
                    _teaser_job_put(job_id, {"status": "error", "error": "concat_failed", "detail": detail})
                    return
                reencoded_meta = await asyncio.to_thread(_probe_metadata, out_path_reencoded)
                reencoded_needs_fix, reencoded_reason = _teaser_concat_needs_reencode(
                    reencoded_meta,
                    total_teaser_secs,
                )
                if reencoded_needs_fix:
                    detail = (
                        "Falha ao normalizar timeline do teaser. "
                        f"A saída reencodada ainda ficou inválida ({reencoded_reason})."
                    )
                    _teaser_job_put(job_id, {"status": "error", "error": "concat_failed", "detail": detail})
                    return
                out_path = out_path_reencoded

            narration_src_key = (narration_object_key or "").strip()
            safe_original_audio_volume = max(0.0, min(float(original_audio_volume or 1.0), 2.0))
            safe_narration_volume = max(0.0, min(float(narration_volume or 1.15), 2.0))
            safe_narration_offset_sec = max(-30.0, min(float(narration_offset_sec or 0.0), 30.0))
            narration_used = False

            if narration_enabled:
                narration_path = os.path.join(tmpdir, "narration.mp3")
                if not narration_src_key:
                    _teaser_job_put(job_id, {
                        "status": "error",
                        "error": "missing_narration_source",
                        "detail": "Ative a narração e selecione um arquivo de áudio.",
                    })
                    return
                _teaser_job_patch(job_id, {"detail": "Baixando áudio de narração…"})
                try:
                    await asyncio.to_thread(
                        _download_media_ref_to_file,
                        media_ref=narration_src_key,
                        out_path=narration_path,
                        s3=s3,
                    )
                except Exception as e:
                    _teaser_job_put(job_id, {
                        "status": "error",
                        "error": "narration_download_failed",
                        "detail": f"Falha ao baixar áudio de narração: {_safe_error_detail(e, 'narration_download_failed')}",
                    })
                    return

                _teaser_job_patch(job_id, {"detail": "Mixando narração no teaser…"})
                mixed_path = os.path.join(tmpdir, "teaser_mix.mp4")
                has_audio = await asyncio.to_thread(_probe_has_audio_stream, out_path)
                if safe_narration_offset_sec > 0:
                    offset_ms = int(round(safe_narration_offset_sec * 1000))
                    narr_chain = f"adelay={offset_ms}|{offset_ms},volume={safe_narration_volume:.3f}"
                elif safe_narration_offset_sec < 0:
                    cut_sec = abs(safe_narration_offset_sec)
                    narr_chain = f"atrim=start={cut_sec:.3f},asetpts=PTS-STARTPTS,volume={safe_narration_volume:.3f}"
                else:
                    narr_chain = f"volume={safe_narration_volume:.3f}"
                if has_audio:
                    mix_filter = (
                        f"[0:a]volume={safe_original_audio_volume:.3f}[a0];"
                        f"[1:a]{narr_chain}[a1];"
                        "[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[mix]"
                    )
                else:
                    mix_filter = f"[1:a]{narr_chain}[mix]"

                mix_cmd = [
                    "ffmpeg", "-y",
                    "-i", out_path,
                    "-i", narration_path,
                    "-filter_complex", mix_filter,
                    "-map", "0:v:0",
                    "-map", "[mix]",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k",
                    "-shortest",
                    "-movflags", "+faststart",
                    mixed_path,
                ]
                mix_stderr = os.path.join(tmpdir, "mix_err.txt")
                mix_timeout = max(300, min(21600, int(total_teaser_secs * 12) + 900))
                mix_rc, mix_err = await asyncio.to_thread(_run_ffmpeg_cmd, mix_cmd, mix_stderr, mix_timeout)
                if mix_rc != 0 or not os.path.exists(mixed_path) or os.path.getsize(mixed_path) < 1024:
                    _teaser_job_put(job_id, {
                        "status": "error",
                        "error": "audio_mix_failed",
                        "detail": f"Falha ao misturar áudio: {(mix_err or 'ffmpeg_failed')[:260]}",
                    })
                    return
                out_path = mixed_path
                narration_used = True

            opener_src_key = (opener_object_key or "").strip()
            safe_opener_position = "end" if str(opener_position or "").strip().lower() == "end" else "start"
            opener_used = False
            if opener_src_key:
                opener_path = os.path.join(tmpdir, "teaser_opener.mp4")
                _teaser_job_patch(job_id, {"detail": "Baixando vídeo de abertura…"})
                try:
                    await asyncio.to_thread(
                        _download_media_ref_to_file,
                        media_ref=opener_src_key,
                        out_path=opener_path,
                        s3=s3,
                    )
                except Exception as e:
                    _teaser_job_put(job_id, {
                        "status": "error",
                        "error": "opener_download_failed",
                        "detail": f"Falha ao baixar vídeo de abertura: {_safe_error_detail(e, 'opener_download_failed')}",
                    })
                    return

                _teaser_job_patch(job_id, {"detail": "Concatenando abertura no teaser…"})
                opener_list_path = os.path.join(tmpdir, "concat_opener_list.txt")
                with open(opener_list_path, "w") as f:
                    if safe_opener_position == "end":
                        f.write(f"file '{out_path}'\n")
                        f.write(f"file '{opener_path}'\n")
                    else:
                        f.write(f"file '{opener_path}'\n")
                        f.write(f"file '{out_path}'\n")

                teaser_dur = await asyncio.to_thread(_probe_duration, out_path)
                opener_dur = await asyncio.to_thread(_probe_duration, opener_path)
                concat_timeout = max(300, min(21600, int(max(30.0, teaser_dur + opener_dur) * 12) + 900))

                with_opening_path = os.path.join(tmpdir, "teaser_with_opening.mp4")
                concat_open_cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0", "-i", opener_list_path,
                    "-c", "copy",
                    "-movflags", "+faststart",
                    with_opening_path,
                ]
                concat_open_err = os.path.join(tmpdir, "concat_opener_err.txt")
                open_rc, open_err = await asyncio.to_thread(_run_ffmpeg_cmd, concat_open_cmd, concat_open_err, concat_timeout)
                open_ok = open_rc == 0 and os.path.exists(with_opening_path) and os.path.getsize(with_opening_path) >= 1024
                opener_concat_reason = ""
                if open_ok:
                    opener_meta = await asyncio.to_thread(_probe_metadata, with_opening_path)
                    open_needs_reencode, opener_concat_reason = _teaser_concat_needs_reencode(
                        opener_meta,
                        max(0.0, teaser_dur + opener_dur),
                    )
                    open_ok = not open_needs_reencode

                if not open_ok:
                    with_opening_fallback = os.path.join(tmpdir, "teaser_with_opening_reencode.mp4")
                    concat_open_fallback_cmd = [
                        "ffmpeg", "-y",
                        "-f", "concat", "-safe", "0", "-i", opener_list_path,
                        "-vf", teaser_video_filter,
                        *teaser_video_encode_args,
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        with_opening_fallback,
                    ]
                    concat_open_err2 = os.path.join(tmpdir, "concat_opener_err2.txt")
                    open2_rc, open2_err = await asyncio.to_thread(_run_ffmpeg_cmd, concat_open_fallback_cmd, concat_open_err2, max(concat_timeout, 900))
                    if open2_rc != 0 or not os.path.exists(with_opening_fallback) or os.path.getsize(with_opening_fallback) < 1024:
                        _teaser_job_put(job_id, {
                            "status": "error",
                            "error": "opener_concat_failed",
                            "detail": (
                                "Falha ao concatenar vídeo de abertura: "
                                f"{((open2_err or open_err) or 'ffmpeg_failed')[:260]}"
                                + (f" ({opener_concat_reason})" if opener_concat_reason else "")
                            ),
                        })
                        return
                    out_path = with_opening_fallback
                else:
                    out_path = with_opening_path
                opener_used = True

            _teaser_job_patch(job_id, {"detail": "Salvando teaser…"})
            burned_key = video_object_key if source_type == "burned" else ""
            stored = await asyncio.to_thread(
                _store_teaser_with_name,
                src_path=out_path,
                run_id=run_id or str(job_id),
                burned_object_key=burned_key,
            )
            result_key = str(stored.get("object_key") or "")
            _teaser_job_put(job_id, {
                "status": "done",
                "video_url": stored.get("public_url"),
                "object_key": result_key,
                "narration_used": narration_used,
                "original_audio_volume": safe_original_audio_volume if narration_used else None,
                "narration_volume": safe_narration_volume if narration_used else None,
                "narration_offset_sec": safe_narration_offset_sec if narration_used else None,
                "narration_object_key": narration_src_key if (narration_used and narration_src_key) else "",
                "opener_used": opener_used,
                "opener_object_key": opener_src_key if (opener_used and opener_src_key) else "",
                "opener_position": safe_opener_position if opener_used else "",
                "source_type": source_type or "burned",
            })
            if run_id:
                _merge_run_wizard_state(
                    run_id,
                    {
                        "teaser_source_type": source_type or "burned",
                        "teaser_object_key": result_key,
                        "teaser_num_clips": str(num_clips),
                        "teaser_clip_duration": str(int(clip_duration)),
                        "teaser_scene_durations_by_frame": manual_scene_durations or {},
                        "teaser_logo_count": len(logo_specs),
                        "teaser_quality": str(output_crf),
                        "teaser_output_max_height": int(safe_output_max_h),
                        "teaser_output_max_fps": int(safe_output_max_fps),
                        "teaser_narration_enabled": bool(narration_enabled),
                        "teaser_original_audio_volume": round(safe_original_audio_volume * 100.0, 2),
                        "teaser_narration_volume": round(safe_narration_volume * 100.0, 2),
                        "teaser_narration_offset_sec": safe_narration_offset_sec,
                        "teaser_narration_object_key": narration_src_key or None,
                        "teaser_narration_used": narration_used,
                        "teaser_opener_object_key": opener_src_key or None,
                        "teaser_opener_position": safe_opener_position,
                        "teaser_opener_used": opener_used,
                    },
                )
    except Exception as e:
        print(f"teaser worker exception: {traceback.format_exc()}")
        _teaser_job_put(job_id, {"status": "error", "error": "internal_error", "detail": str(e)})


async def _concat_worker(job_id: str, first_key: str, second_key: str, run_id: Optional[str] = None) -> None:
    """Concatena dois vídeos do MinIO (ex: teaser + vídeo legendado)."""
    import traceback
    _teaser_job_patch(job_id, {"status": "running", "detail": "Inicializando…"})
    s3 = _s3_client()

    try:
        with tempfile.TemporaryDirectory(prefix="concat-", dir=_preferred_tmpdir_root("concat")) as tmpdir:
            first_path = os.path.join(tmpdir, "first.mp4")
            second_path = os.path.join(tmpdir, "second.mp4")

            _teaser_job_patch(job_id, {"detail": "Baixando primeiro vídeo (teaser)…"})
            await asyncio.to_thread(_download_media_ref_to_file, media_ref=first_key, out_path=first_path, s3=s3)
            _teaser_job_patch(job_id, {"detail": "Baixando segundo vídeo (principal)…"})
            await asyncio.to_thread(_download_media_ref_to_file, media_ref=second_key, out_path=second_path, s3=s3)

            _teaser_job_patch(job_id, {"detail": "Concatenando…"})
            list_path = os.path.join(tmpdir, "list.txt")
            with open(list_path, "w") as f:
                f.write(f"file '{first_path}'\n")
                f.write(f"file '{second_path}'\n")

            out_path = os.path.join(tmpdir, "combinado.mp4")
            # Tenta sem re-encode (-c copy) primeiro — funciona quando mesmos codecs/resolução
            concat_cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-c", "copy",
                "-movflags", "+faststart",
                out_path,
            ]
            stderr_f = os.path.join(tmpdir, "concat_err.txt")
            def _run_concat_fast() -> int:
                with open(stderr_f, "wb") as ferr:
                    try:
                        proc = subprocess.run(
                            concat_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=ferr,
                            timeout=600,
                        )
                        return int(proc.returncode)
                    except subprocess.TimeoutExpired:
                        return 124

            concat_fast_rc = await asyncio.to_thread(_run_concat_fast)

            if concat_fast_rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
                # Fallback: re-encoding (mais lento mas garante compatibilidade)
                _teaser_job_patch(job_id, {"detail": "Re-codificando para compatibilidade…"})
                out_path2 = os.path.join(tmpdir, "combinado2.mp4")
                fallback_cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0", "-i", list_path,
                    "-c:v", "libx264", "-crf", "26", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    out_path2,
                ]
                stderr_f2 = os.path.join(tmpdir, "concat_err2.txt")
                def _run_concat_fallback() -> int:
                    with open(stderr_f2, "wb") as ferr2:
                        try:
                            proc2 = subprocess.run(
                                fallback_cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=ferr2,
                                timeout=7200,
                            )
                            return int(proc2.returncode)
                        except subprocess.TimeoutExpired:
                            return 124

                concat_fallback_rc = await asyncio.to_thread(_run_concat_fallback)
                if concat_fallback_rc == 124:
                    _teaser_job_put(job_id, {"status": "error", "error": "timeout", "detail": "Re-codificação excedeu 2h."})
                    return
                if concat_fallback_rc != 0 or not os.path.exists(out_path2) or os.path.getsize(out_path2) < 1024:
                    _teaser_job_put(job_id, {"status": "error", "error": "concat_failed", "detail": "Falha ao concatenar. Verifique se os vídeos têm codecs compatíveis."})
                    return
                out_path = out_path2

            _teaser_job_patch(job_id, {"detail": "Salvando combinado…"})
            stored = await asyncio.to_thread(
                _store_local_path,
                src_path=out_path,
                prefix="combined",
                filename="combinado.mp4",
                content_type="video/mp4",
            )
            result_key = str(stored.get("object_key") or "")
            _teaser_job_put(job_id, {"status": "done", "video_url": stored.get("public_url"), "object_key": result_key})
            if run_id:
                _merge_run_wizard_state(run_id, {"teaser_combined_object_key": result_key})
    except Exception as e:
        print(f"concat worker exception: {traceback.format_exc()}")
        _teaser_job_put(job_id, {"status": "error", "error": "internal_error", "detail": str(e)})


# ════════════════ CORTES — clipes verticais p/ redes sociais ════════════════
_CORTES_ASPECTS = {
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
    "4:5":  (1080, 1350),
}
_CORTES_SEMAPHORE = asyncio.Semaphore(3)
_CORTES_VISION_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _cortes_crop_scale_filter(aspect: str, max_h: int) -> str:
    w, h = _CORTES_ASPECTS.get(aspect, _CORTES_ASPECTS["9:16"])
    out_h = max(320, min(int(max_h or h), 2160))
    out_w = int(round(out_h * w / h))
    out_w -= out_w % 2
    out_h -= out_h % 2
    return (
        f"crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})',"
        f"scale={out_w}:{out_h}:flags=lanczos,setsar=1"
    )


def _cortes_video_cache_hash(video_path: str) -> str:
    h = hashlib.sha256()
    size = 0
    with open(video_path, "rb") as f:
        chunk = f.read(1024 * 1024)
        size = len(chunk)
        h.update(chunk)
    try:
        total_size = os.path.getsize(video_path)
    except Exception:
        total_size = size
    return hashlib.sha256(f"{total_size}:".encode("utf-8") + h.digest()).hexdigest()[:24]


def _cortes_vision_cache_path(cache_hash: str) -> str:
    safe_hash = re.sub(r"[^a-fA-F0-9]", "", str(cache_hash or ""))[:64] or "unknown"
    return os.path.join(LOCAL_MEDIA_ROOT, "cache", "vision", f"{safe_hash}.json")


def _load_cortes_vision_cache(cache_hash: str) -> Optional[List[Dict[str, Any]]]:
    path = _cortes_vision_cache_path(cache_hash)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        clips = data.get("clips") if isinstance(data, dict) else None
        if isinstance(clips, list):
            return [c for c in clips if isinstance(c, dict)]
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"[cortes] falha ao ler cache vision {path}: {exc}", flush=True)
    return None


def _save_cortes_vision_cache(cache_hash: str, clips: List[Dict[str, Any]], *, video_object_key: str, duration: float) -> None:
    path = _cortes_vision_cache_path(cache_hash)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "kind": "cortes_vision",
        "version": 1,
        "video_hash": cache_hash,
        "video_object_key": video_object_key,
        "duration": duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips": clips,
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _extract_uniform_cortes_frames(video_path: str, duration: float, out_dir: str, target_frames: int = 100) -> List[Dict[str, Any]]:
    safe_duration = max(0.0, float(duration or 0.0))
    if safe_duration <= 0:
        return []
    count = max(1, min(int(target_frames or 100), 100))
    if safe_duration < count:
        count = max(1, int(math.ceil(safe_duration)))
    fps = max(0.01, count / safe_duration)
    pattern = os.path.join(out_dir, "ai_frame_%03d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps:.6f},scale=-2:240:flags=bilinear",
        "-frames:v", str(count),
        "-q:v", "6",
        pattern,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=max(60, min(600, int(safe_duration * 3))))
    except Exception:
        pass
    frames: List[Dict[str, Any]] = []
    for i in range(count):
        ts = min(max(0.0, safe_duration * (i + 1) / (count + 1)), max(0.0, safe_duration - 0.2))
        out_path = os.path.join(out_dir, f"ai_frame_{i + 1:03d}.jpg")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            frames.append({"path": out_path, "timestamp": round(ts, 3)})
    return frames


async def _analyze_frames_for_clips(frames: List[Dict[str, Any]], duration: float, max_clips: int = 6) -> Optional[Dict[str, Any]]:
    or_saved = settings_get(key="token:openrouter")
    or_key = (or_saved or {}).get("value")
    xai_saved = settings_get(key="token:grok")
    xai_key = (xai_saved or {}).get("value")
    if not or_key and not xai_key:
        return None

    content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analise estes {len(frames)} frames extraídos uniformemente de um vídeo adulto de {duration:.1f}s. "
                "Identifique os MELHORES MOMENTOS para cortes verticais (Shorts/Reels). "
                "Priorize cenas com: ação intensa, close-ups, mudanças de posição, expressões faciais marcantes, boa iluminação. "
                "EVITE: cenas escuras, momentos de pausa/transição, takes muito longos sem variação.\n\n"
                "Responda SOMENTE em JSON com a chave 'clips' contendo uma lista de objetos:\n"
                "- 'start_time': float (segundo exato do início do corte)\n"
                "- 'end_time': float (segundo exato do fim do corte)\n"
                "- 'reason': string pt-BR explicando por que este momento é bom (ex: 'Close-up intenso com expressão marcante')\n"
                "- 'quality_score': float 0.0-1.0 indicando qualidade do corte\n\n"
                "REGRAS:\n"
                f"- Máximo {max_clips} clips\n"
                "- Duração entre 15s e 60s cada clip (start_time e end_time devem refletir isso)\n"
                "- Os clips NÃO devem se sobrepor (espaçamento mínimo de 2s entre eles)\n"
                "- Distribua os clips ao longo do vídeo (não todos no mesmo minuto)\n"
                "- Use os timestamps informados antes de cada frame como referência; não invente tempos fora do vídeo\n"
                "- Inclua pelo menos um hook/abertura forte no primeiro clip quando houver cena boa"
            ),
        }
    ]
    for item in frames:
        ts = float(item.get("timestamp") or 0.0)
        b64 = str(item.get("b64") or "")
        if not b64:
            continue
        content.append({"type": "text", "text": f"Frame em t={ts:.2f}s"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    messages = [
        {
            "role": "system",
            "content": "Você é um editor de vídeo especializado em criar cortes virais para redes sociais (Shorts, Reels, TikTok). Sua função é analisar frames e identificar os momentos de maior impacto. Responda apenas JSON."
        },
        {
            "role": "user",
            "content": content
        }
    ]

    if or_key:
        result = await _openrouter_vision_chat_json(api_key=or_key, messages=messages)
    else:
        result = {"_api_error": 503, "_detail": "no_openrouter_key"}

    if (result.get("_api_error") or result.get("_exception")) and xai_key:
        r2 = await _xai_vision_chat_json(api_key=xai_key, messages=messages)
        if not r2.get("_api_error") and not r2.get("_exception"):
            r2["_or_attempts"] = result.get("_model_attempts") or []
            result = r2

    if "clips" not in result and not result.get("_api_error") and not result.get("_exception"):
        return {"_refused": True, "_raw": result}
    return result


async def _ai_select_best_clips(video_path: str, duration: float, td: str, max_clips: int = 6) -> List[Dict[str, Any]]:
    frame_items = await asyncio.to_thread(
        _extract_uniform_cortes_frames,
        video_path,
        duration,
        td,
        100,
    )
    frames_payload: List[Dict[str, Any]] = []
    for item in frame_items:
        path = str(item.get("path") or "")
        if not path:
            continue
        try:
            frames_payload.append({
                "timestamp": float(item.get("timestamp") or 0.0),
                "b64": await asyncio.to_thread(_file_to_base64, path),
            })
        except Exception:
            continue
    if not frames_payload:
        return []

    result = await _analyze_frames_for_clips(frames_payload, duration, max_clips=max_clips)
    if not result or result.get("_api_error") or result.get("_exception") or result.get("_refused"):
        return []

    clips_raw = result.get("clips") or []
    if not clips_raw:
        return []

    valid = []
    for c in clips_raw:
        try:
            start = float(c.get("start_time") or 0)
            end = float(c.get("end_time") or 0)
            score = float(c.get("quality_score") or 0)
        except Exception:
            continue
        start = max(0.0, min(start, max(0.0, duration - 3.0)))
        end = max(start + 3.0, min(end, duration))
        clip_dur = end - start
        if clip_dur >= 10 and end <= duration and start >= 0 and score >= 0.3:
            valid.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(clip_dur, 1),
                "reason": (c.get("reason") or "").strip(),
                "quality_score": round(score, 2),
            })

    valid.sort(key=lambda x: x["quality_score"], reverse=True)
    selected: List[Dict[str, Any]] = []
    for c in valid:
        if any(not (float(c["end"]) + 2 <= float(prev["start"]) or float(c["start"]) >= float(prev["end"]) + 2) for prev in selected):
            continue
        selected.append(c)
        if len(selected) >= max_clips:
            break
    return sorted(selected, key=lambda x: x["start"])


async def _cortes_worker(job_id, video_object_key, aspect,
                         output_max_height, output_crf, run_id="", max_clips: int = 6):
    def _patch(p):
        cur = async_job_get(kind="cortes", job_id=job_id) or {}
        cur.update(p)
        cur["updated_at"] = datetime.now(timezone.utc).isoformat()
        async_job_put(kind="cortes", job_id=job_id, payload=cur)

    _patch({"status": "running", "detail": "Baixando vídeo…", "progress_pct": 5})
    s3 = _s3_client()
    try:
        with tempfile.TemporaryDirectory(prefix="cortes-", dir=_preferred_tmpdir_root("cortes")) as td:
            in_path = os.path.join(td, "input_video")
            await asyncio.to_thread(_download_media_ref_to_file, media_ref=video_object_key, out_path=in_path, s3=s3)
            duration = await asyncio.to_thread(_probe_duration, in_path)
            if not duration or duration <= 0:
                _patch({"status": "error", "detail": "Não foi possível ler a duração do vídeo.", "progress_pct": 0})
                return

            _patch({"detail": "Calculando hash do vídeo para cache…", "progress_pct": 10})
            video_hash = await asyncio.to_thread(_cortes_video_cache_hash, in_path)
            cache_key = f"cortes_vision:{video_hash}"
            cached = _CORTES_VISION_CACHE.get(cache_key)
            if cached is None:
                cached = await asyncio.to_thread(_load_cortes_vision_cache, video_hash)
                if cached is not None:
                    _CORTES_VISION_CACHE[cache_key] = cached

            if cached is not None:
                ai_clips = cached[:max_clips]
                selection_mode = "ai_cache"
                _patch({"detail": f"Usando análise Vision em cache — {len(ai_clips)} cena(s) encontrada(s).", "progress_pct": 22})
            else:
                _patch({"detail": "Extraindo frames 240p para Vision IA…", "progress_pct": 15})
                ai_results = await _ai_select_best_clips(in_path, duration, td, max_clips=12)
                if ai_results:
                    selection_mode = "ai"
                    _CORTES_VISION_CACHE[cache_key] = ai_results
                    if len(_CORTES_VISION_CACHE) > 500:
                        _CORTES_VISION_CACHE.clear()
                    await asyncio.to_thread(
                        _save_cortes_vision_cache,
                        video_hash,
                        ai_results,
                        video_object_key=video_object_key,
                        duration=duration,
                    )
                else:
                    selection_mode = "fallback"
                ai_clips = ai_results[:max_clips] if ai_results else []

            if not ai_clips:
                selection_mode = "fallback"
                _patch({"detail": "IA indisponível, usando detecção automática de cenas…", "progress_pct": 20})
                timestamps = await asyncio.to_thread(_detect_scene_timestamps, in_path, 0.30, duration)
                if len(timestamps) < max_clips:
                    step = max(1.0, duration / (max_clips + 1))
                    timestamps = sorted(set([round(step * (i + 1), 2) for i in range(max_clips)] + list(timestamps)))
                picked_ts = []
                clip_dur = min(30.0, duration / 3)
                for t in timestamps:
                    if t + clip_dur <= duration + 0.5 and all(abs(t - p) >= clip_dur for p in picked_ts):
                        picked_ts.append(t)
                    if len(picked_ts) >= max_clips:
                        break
                if not picked_ts:
                    picked_ts = [0.0]
                ai_clips = [{"start": t, "end": min(t + clip_dur, duration), "duration": clip_dur, "reason": "Cena detectada automaticamente", "quality_score": 0.5} for t in picked_ts]

            vf = _cortes_crop_scale_filter(aspect, output_max_height)
            outputs = []

            async def _extract_one(i, clip_info):
                start = clip_info["start"]
                end = min(clip_info["end"], duration)
                clip_dur = round(end - start, 3)
                if clip_dur < 3:
                    return None
                async with _CORTES_SEMAPHORE:
                    clip_path = os.path.join(td, f"corte_{i + 1}.mp4")
                    cmd = [
                        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", in_path, "-t", f"{clip_dur:.3f}",
                        "-vf", vf, "-c:v", "libx264", "-crf", str(output_crf), "-preset", "veryfast",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", clip_path,
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                    )
                    _, errb = await proc.communicate()
                    if proc.returncode != 0 or not os.path.exists(clip_path) or os.path.getsize(clip_path) < 1024:
                        print(f"[cortes] job={job_id} corte {i + 1} falhou rc={proc.returncode}", flush=True)
                        return None
                    stored = await asyncio.to_thread(
                        _store_local_path, src_path=clip_path, prefix="cortes",
                        filename=f"corte_{aspect.replace(':', 'x')}_{i + 1}.mp4", content_type="video/mp4",
                    )
                    return {
                        "object_key": stored["object_key"],
                        "start": start,
                        "end": end,
                        "duration": clip_dur,
                        "reason": clip_info.get("reason", ""),
                        "quality_score": clip_info.get("quality_score", 0.5),
                        "index": i + 1,
                    }

            _patch({"detail": f"Extraindo {len(ai_clips)} corte(s) em paralelo (máx 3)…", "progress_pct": 25})
            tasks = [_extract_one(i, c) for i, c in enumerate(ai_clips)]
            outputs = []
            done_count = 0
            for done in asyncio.as_completed(tasks):
                item = await done
                done_count += 1
                if item is not None:
                    outputs.append(item)
                _patch({
                    "detail": f"Extraindo cortes em paralelo… {done_count}/{len(tasks)}",
                    "progress_pct": 25 + int(70 * done_count / max(1, len(tasks))),
                })
            outputs.sort(key=lambda x: int(x.get("index") or 0))

            if not outputs:
                _patch({"status": "error", "detail": "Nenhum corte foi gerado.", "progress_pct": 0})
                return

            _patch({
                "status": "done",
                "detail": (
                    f"✓ {len(outputs)} corte(s) gerado(s) por Vision IA ({aspect})."
                    if selection_mode in {"ai", "ai_cache"}
                    else f"✓ {len(outputs)} corte(s) gerado(s) por detecção automática ({aspect})."
                ),
                "progress_pct": 100,
                "clips": outputs,
                "object_key": outputs[0]["object_key"],
                "aspect": aspect,
                "vision_cache_key": video_hash,
                "selection_mode": selection_mode,
                "ai_used": selection_mode in {"ai", "ai_cache"},
            })
    except Exception as exc:
        import traceback
        traceback.print_exc()
        _patch({"status": "error", "detail": f"Erro: {exc}", "progress_pct": 0})


@app.post("/api/cortes/generate")
async def cortes_generate(request: Request):
    """Gera cortes verticais (Shorts/Reels) usando IA para selecionar as melhores cenas. Retorna job_id."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    video_object_key = (body.get("video_object_key") or "").strip()
    if not video_object_key or not _is_valid_object_key(video_object_key):
        return JSONResponse({"error": "invalid_video_object_key"}, status_code=400)
    aspect = str(body.get("aspect") or "9:16").strip()
    if aspect not in _CORTES_ASPECTS:
        aspect = "9:16"
    output_max_height = max(640, min(int(body.get("output_max_height") or 1920), 2160))
    output_crf = max(18, min(int(body.get("output_crf") or 23), 32))
    run_id = (body.get("run_id") or "").strip()
    job_id = str(uuid.uuid4())
    async_job_put(kind="cortes", job_id=job_id, payload={
        "status": "queued", "progress_pct": 0, "detail": "Na fila…",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    max_clips = max(1, min(int(body.get("max_clips") or 6), 12))
    asyncio.create_task(_cortes_worker(
        job_id, video_object_key, aspect,
        output_max_height, output_crf, run_id,
        max_clips,
    ))
    return {"job_id": job_id}


@app.get("/api/cortes/status/{job_id}")
async def cortes_status(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = async_job_get(kind="cortes", job_id=job_id)
    if not job:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return job


@app.post("/api/teaser/generate")
async def teaser_generate(request: Request):
    """Gera teaser com as melhores cenas do vídeo. Retorna job_id para polling."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    run_id = (body.get("run_id") or "").strip()
    run_row = get_run(run_id) if run_id else None
    if run_id and not run_row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)

    video_object_key = (body.get("video_object_key") or "").strip()
    if not video_object_key:
        return JSONResponse({"error": "missing_video_object_key"}, status_code=400)
    if not _is_valid_object_key(video_object_key):
        return JSONResponse({"error": "invalid_video_object_key"}, status_code=400)

    requested_source_type = str(body.get("source_type") or "").strip().lower()
    inferred_source_type = "burned" if _media_ref_has_prefix(video_object_key, "burns", "combined") else "original"
    source_type = requested_source_type if requested_source_type in {"original", "burned"} else inferred_source_type
    if source_type != inferred_source_type:
        source_type = inferred_source_type
    force_logo_overlay = bool(body.get("force_logo_overlay"))
    if source_type == "burned":
        force_logo_overlay = False
    import logging as _logging
    _logging.getLogger("uvicorn.error").warning(
        f"[teaser/generate] source_type={source_type!r} requested_source_type={requested_source_type!r} video_object_key={video_object_key!r} force_logo={force_logo_overlay}"
    )
    body_logo_profile_id = str(body.get("logo_profile_id") or "").strip()
    body_logo_profile_name = str(body.get("logo_profile_name") or "").strip()
    body_logo_profile_layout_linked = _coerce_optional_bool(body.get("logo_profile_layout_linked"))
    body_has_logo_layout_payload = _has_logo_layout_payload(body)

    def _num_logo(v: Any, default: float, min_v: float, max_v: float) -> float:
        try:
            n = float(v)
        except Exception:
            n = default
        return max(min_v, min(n, max_v))

    logo_b64 = (body.get("logo_b64") or "").strip()
    logos_raw = body.get("logos")
    logos: List[Dict[str, Any]] = []
    if isinstance(logos_raw, list):
        for raw in logos_raw[:MAX_LOGO_OVERLAYS]:
            if not isinstance(raw, dict):
                continue
            raw_b64 = str(raw.get("b64") or raw.get("logo_b64") or raw.get("src") or "").strip()
            if not raw_b64:
                continue
            color_hex = _normalize_hex_color(str(raw.get("bg_key_color") or "#ffffff"), "#ffffff")
            logos.append({
                "b64": raw_b64,
                "name": str(raw.get("name") or "").strip(),
                "mime": str(raw.get("mime") or "").strip().lower(),
                "x": _num_logo(raw.get("x"), 97.0, 0.0, 100.0),
                "y": _num_logo(raw.get("y"), 97.0, 0.0, 100.0),
                "scale_pct": _num_logo(raw.get("scale_pct"), 20.0, 5.0, 100.0),
                "opacity": _num_logo(raw.get("opacity"), 85.0, 5.0, 100.0),
                "remove_bg": bool(raw.get("remove_bg")),
                "sync_main": bool(raw.get("sync_main")),
                "bg_key_color": color_hex,
                "bg_similarity": _num_logo(raw.get("bg_similarity"), 0.18, 0.01, 0.60),
                "bg_blend": _num_logo(raw.get("bg_blend"), 0.08, 0.0, 0.40),
            })
    logo_x = max(0, min(int(body.get("logo_x") or 97), 100))
    logo_y = max(0, min(int(body.get("logo_y") or 97), 100))
    logo_scale_pct = max(5.0, min(float(body.get("logo_scale_pct") or 20.0), 100.0))
    logo_opacity = max(5.0, min(float(body.get("logo_opacity") or 85.0), 100.0))

    linked_logo_profile: Optional[Dict[str, Any]] = None
    effective_logo_profile_layout_linked = body_logo_profile_layout_linked
    if run_row:
        try:
            req_data = json.loads(run_row["request_json"]) if isinstance(run_row["request_json"], str) else (run_row.get("request_json") or {})
        except Exception:
            req_data = {}
        wizard_state = _safe_json_obj(req_data.get("wizard_state"))
        effective_logo_profile_id = body_logo_profile_id or str(wizard_state.get("logo_profile_id") or "").strip()
        effective_logo_profile_name = body_logo_profile_name or str(wizard_state.get("logo_profile_name") or "").strip()
        if effective_logo_profile_layout_linked is None:
            effective_logo_profile_layout_linked = _coerce_optional_bool(wizard_state.get("logo_profile_layout_linked"))
        has_logo_profile_ref = bool(effective_logo_profile_id or effective_logo_profile_name)
        if effective_logo_profile_layout_linked is None and has_logo_profile_ref:
            effective_logo_profile_layout_linked = True
        linked_logo_profile = _find_logo_profile(
            profile_id=effective_logo_profile_id,
            company_name=effective_logo_profile_name,
        ) if has_logo_profile_ref else None
    if run_id:
        _merge_run_wizard_state(
            run_id,
            {
                "teaser_source_type": source_type,
                "teaser_source_object_key": video_object_key,
                "teaser_force_logo_overlay": True if (source_type != "burned" and force_logo_overlay) else False,
            },
        )
    if linked_logo_profile:
        def _layout_differs() -> bool:
            if not body_has_logo_layout_payload:
                return False
            try:
                return (
                    abs(float(logo_x) - float(linked_logo_profile.get("logo_x") or 0.0)) > 0.05
                    or abs(float(logo_y) - float(linked_logo_profile.get("logo_y") or 0.0)) > 0.05
                    or abs(float(logo_scale_pct) - float(linked_logo_profile.get("logo_scale_pct") or 0.0)) > 0.05
                    or abs(float(logo_opacity) - float(linked_logo_profile.get("logo_opacity") or 0.0)) > 0.05
                )
            except Exception:
                return False
        if effective_logo_profile_layout_linked and _layout_differs():
            effective_logo_profile_layout_linked = False
        linked_logo_ref = str(linked_logo_profile.get("logo_object_key") or "").strip()
        linked_logo_name = str(linked_logo_profile.get("logo_name") or "").strip().lower()
        linked_company_name = str(linked_logo_profile.get("company_name") or "").strip().lower()
        # Só carrega logo do perfil quando o usuário quer aplicar logo no teaser.
        # A imagem do perfil é independente do vínculo de layout: desvincular
        # posição/tamanho não pode transformar o job em "sem logo".
        if force_logo_overlay and not logo_b64 and not logos:
            profile_logos = _logo_profile_to_payload_logos(linked_logo_profile)
            if profile_logos:
                if not effective_logo_profile_layout_linked:
                    profile_logos[0]["x"] = logo_x
                    profile_logos[0]["y"] = logo_y
                    profile_logos[0]["scale_pct"] = logo_scale_pct
                    profile_logos[0]["opacity"] = logo_opacity
                logos = profile_logos
            elif linked_logo_ref:
                logo_b64 = _media_ref_to_data_url(linked_logo_ref)
        next_logos: List[Dict[str, Any]] = []
        for idx, item in enumerate(logos):
            next_item = dict(item)
            item_name = str(next_item.get("name") or "").strip().lower()
            should_link_layout = bool(next_item.get("sync_main"))
            if not should_link_layout and len(logos) == 1:
                should_link_layout = (not item_name or item_name == linked_logo_name or item_name == linked_company_name)
            if should_link_layout and effective_logo_profile_layout_linked:
                next_item["x"] = _num_logo(linked_logo_profile.get("logo_x"), next_item.get("x"), 0.0, 100.0)
                next_item["y"] = _num_logo(linked_logo_profile.get("logo_y"), next_item.get("y"), 0.0, 100.0)
                next_item["scale_pct"] = _num_logo(linked_logo_profile.get("logo_scale_pct"), next_item.get("scale_pct"), 5.0, 100.0)
                next_item["opacity"] = _num_logo(linked_logo_profile.get("logo_opacity"), next_item.get("opacity"), 5.0, 100.0)
                if not str(next_item.get("b64") or "").strip() and linked_logo_ref:
                    next_item["b64"] = _media_ref_to_data_url(linked_logo_ref)
                if not str(next_item.get("name") or "").strip():
                    next_item["name"] = str(linked_logo_profile.get("logo_name") or linked_logo_profile.get("company_name") or f"logo_{idx + 1}").strip()
            next_logos.append(next_item)
        logos = next_logos
        if run_id:
            merged_logo_x = _num_logo(linked_logo_profile.get("logo_x"), logo_x, 0.0, 100.0) if effective_logo_profile_layout_linked else logo_x
            merged_logo_y = _num_logo(linked_logo_profile.get("logo_y"), logo_y, 0.0, 100.0) if effective_logo_profile_layout_linked else logo_y
            merged_logo_scale = _num_logo(linked_logo_profile.get("logo_scale_pct"), logo_scale_pct, 5.0, 100.0) if effective_logo_profile_layout_linked else logo_scale_pct
            merged_logo_opacity = _num_logo(linked_logo_profile.get("logo_opacity"), logo_opacity, 5.0, 100.0) if effective_logo_profile_layout_linked else logo_opacity
            _merge_run_wizard_state(
                run_id,
                {
                    "logo_x": merged_logo_x,
                    "logo_y": merged_logo_y,
                    "logo_scale_pct": merged_logo_scale,
                    "logo_opacity": merged_logo_opacity,
                    "logo_profile_layout_linked": True if effective_logo_profile_layout_linked else False,
                },
            )
    # Segurança final: garante que nenhuma logo vaze se o usuário não quis aplicar.
    if not force_logo_overlay:
        logo_b64 = ""
        logos = []
    # Proteção anti-logo duplicada em vídeos já queimados.
    elif _media_ref_has_prefix(video_object_key, "burns", "combined"):
        logo_b64 = ""
        logos = []
    import logging as _logging
    _logging.getLogger("uvicorn.error").warning(
        f"[teaser/generate.logo] force_logo={force_logo_overlay} source_type={source_type!r} "
        f"logo_present={bool(logo_b64) or bool(logos)} logo_count={len(logos) if logos else (1 if logo_b64 else 0)} "
        f"profile_id={body_logo_profile_id or ''} profile_name={body_logo_profile_name or ''} "
        f"layout_linked={effective_logo_profile_layout_linked}"
    )
    num_clips = max(2, min(int(body.get("num_clips") or 6), TEASER_MAX_NUM_CLIPS))
    clip_duration = max(2.0, min(float(body.get("clip_duration") or 5.0), TEASER_MAX_SCENE_DURATION_SEC))
    output_crf = max(20, min(int(body.get("output_crf") or 28), 35))
    output_max_height = max(480, min(int(body.get("output_max_height") or 1080), 2160))
    output_max_fps = max(24.0, min(float(body.get("output_max_fps") or 30.0), 60.0))
    # Só aplica parâmetros do perfil ao layout quando há logo real para posicionar.
    if linked_logo_profile and effective_logo_profile_layout_linked and (logo_b64 or logos):
        logo_x = max(0, min(int(linked_logo_profile.get("logo_x") or logo_x), 100))
        logo_y = max(0, min(int(linked_logo_profile.get("logo_y") or logo_y), 100))
        logo_scale_pct = max(5.0, min(float(linked_logo_profile.get("logo_scale_pct") or logo_scale_pct), 100.0))
        logo_opacity = max(5.0, min(float(linked_logo_profile.get("logo_opacity") or logo_opacity), 100.0))

    narration_cfg = body.get("narration") if isinstance(body.get("narration"), dict) else {}
    narration_enabled = bool(narration_cfg.get("enabled"))
    narration_object_key = str(narration_cfg.get("object_key") or "").strip()
    if narration_object_key and not _is_valid_object_key(narration_object_key):
        return JSONResponse({"error": "invalid_narration_object_key"}, status_code=400)
    try:
        original_audio_volume = max(0.0, min(float(narration_cfg.get("original_audio_volume") or 1.0), 2.0))
    except Exception:
        original_audio_volume = 1.0
    try:
        narration_volume = max(0.0, min(float(narration_cfg.get("narration_volume") or 1.15), 2.0))
    except Exception:
        narration_volume = 1.15
    try:
        narration_offset_sec = max(-30.0, min(float(narration_cfg.get("offset_sec") or 0.0), 30.0))
    except Exception:
        narration_offset_sec = 0.0

    if narration_enabled and not narration_object_key:
        return JSONResponse(
            {"error": "missing_narration_source", "detail": "Selecione um áudio de narração enviado manualmente."},
            status_code=400,
        )

    opener_cfg = body.get("opener") if isinstance(body.get("opener"), dict) else {}
    opener_object_key = str(opener_cfg.get("object_key") or body.get("opener_object_key") or "").strip()
    if opener_object_key and not _is_valid_object_key(opener_object_key):
        return JSONResponse({"error": "invalid_opener_object_key"}, status_code=400)
    opener_position = str(opener_cfg.get("position") or body.get("opener_position") or "start").strip().lower()
    if opener_position not in {"start", "end"}:
        opener_position = "start"

    selected_frame_indexes_raw = body.get("selected_frame_indexes") or []
    selected_frame_indexes: List[int] = []
    if isinstance(selected_frame_indexes_raw, list):
        for item in selected_frame_indexes_raw[:60]:
            try:
                selected_frame_indexes.append(int(item))
            except Exception:
                continue

    scene_durations_by_frame_raw = body.get("scene_durations_by_frame")
    scene_durations_by_frame: Dict[int, float] = {}
    if isinstance(scene_durations_by_frame_raw, dict):
        for raw_k, raw_v in list(scene_durations_by_frame_raw.items())[:120]:
            try:
                k = int(raw_k)
                v = float(raw_v)
            except Exception:
                continue
            if k < 0:
                continue
            scene_durations_by_frame[k] = _clamp_teaser_scene_duration(v, clip_duration)
    ordered_scene_durations_raw = body.get("ordered_scene_durations")
    ordered_scene_durations: List[float] = []
    if isinstance(ordered_scene_durations_raw, list):
        for raw_v in ordered_scene_durations_raw[: max(1, num_clips)]:
            try:
                ordered_scene_durations.append(
                    _clamp_teaser_scene_duration(float(raw_v), clip_duration)
                )
            except Exception:
                continue
    try:
        frames_count = max(0, int(body.get("frames_count") or 0))
    except Exception:
        frames_count = 0

    requested_teaser_duration = _estimate_requested_teaser_duration(
        num_clips=num_clips,
        clip_duration=clip_duration,
        selected_frame_indexes=selected_frame_indexes,
        scene_durations_by_frame=scene_durations_by_frame,
        ordered_scene_durations=ordered_scene_durations,
    )
    if requested_teaser_duration > TEASER_MAX_TOTAL_DURATION_SEC:
        return JSONResponse(
            {
                "error": "teaser_too_long",
                "detail": (
                    f"O teaser solicitado ficaria com cerca de {_format_media_clock(requested_teaser_duration)}. "
                    f"O limite seguro atual é {_format_media_clock(TEASER_MAX_TOTAL_DURATION_SEC)} por job. "
                    "Reduza a duração por cena ou o número de cenas."
                ),
            },
            status_code=400,
        )

    job_id = str(uuid.uuid4())
    _teaser_job_put(job_id, {"status": "pending", "created_at": datetime.now(timezone.utc).isoformat()})
    asyncio.create_task(_teaser_worker(
        job_id, video_object_key, logo_b64, num_clips, clip_duration, output_crf,
        output_max_height=output_max_height,
        output_max_fps=output_max_fps,
        run_id=run_id or None,
        source_type=source_type,
        selected_frame_indexes=selected_frame_indexes,
        frames_count=frames_count,
        manual_scene_durations=scene_durations_by_frame,
        ordered_scene_durations=ordered_scene_durations,
        logos=logos,
        logo_x=logo_x, logo_y=logo_y,
        logo_scale_pct=logo_scale_pct, logo_opacity=logo_opacity,
        narration_enabled=narration_enabled,
        original_audio_volume=original_audio_volume,
        narration_volume=narration_volume,
        narration_object_key=narration_object_key,
        narration_offset_sec=narration_offset_sec,
        opener_object_key=opener_object_key,
        opener_position=opener_position,
    ))
    return JSONResponse({"job_id": job_id})


@app.post("/api/teaser/burn-logo")
async def teaser_burn_logo(request: Request):
    """Queima somente a logo por cima de um teaser já gerado."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    run_id = (body.get("run_id") or "").strip()
    if not run_id:
        return JSONResponse({"error": "missing_run_id"}, status_code=400)
    run_row = get_run(run_id)
    if not run_row:
        return JSONResponse({"error": "run_not_found"}, status_code=404)

    teaser_object_key = (body.get("teaser_object_key") or body.get("video_object_key") or "").strip()
    if not teaser_object_key:
        return JSONResponse({"error": "missing_teaser_object_key"}, status_code=400)
    if not _is_valid_object_key(teaser_object_key):
        return JSONResponse({"error": "invalid_teaser_object_key"}, status_code=400)

    logo_b64 = (body.get("logo_b64") or "").strip()
    body_has_logo_layout_payload = _has_logo_layout_payload(body)
    logos_raw = body.get("logos")
    logos: List[Dict[str, Any]] = []
    if isinstance(logos_raw, list):
        for raw in logos_raw[:MAX_LOGO_OVERLAYS]:
            if not isinstance(raw, dict):
                continue
            raw_b64 = str(raw.get("b64") or raw.get("logo_b64") or raw.get("src") or "").strip()
            if not raw_b64:
                continue
            logos.append({
                "b64": raw_b64,
                "name": str(raw.get("name") or "").strip(),
                "mime": str(raw.get("mime") or "").strip().lower(),
                "x": max(0.0, min(float(raw.get("x", raw.get("logo_x", 97.0))), 100.0)),
                "y": max(0.0, min(float(raw.get("y", raw.get("logo_y", 97.0))), 100.0)),
                "scale_pct": max(5.0, min(float(raw.get("scale_pct", raw.get("logo_scale_pct", 20.0))), 100.0)),
                "opacity": max(5.0, min(float(raw.get("opacity", raw.get("logo_opacity", 85.0))), 100.0)),
                "enabled": raw.get("enabled") is not False,
                "remove_bg": bool(raw.get("remove_bg")),
                "bg_key_color": _normalize_hex_color(raw.get("bg_key_color") or "#ffffff", "#ffffff"),
                "bg_similarity": max(0.01, min(float(raw.get("bg_similarity", 0.18)), 0.60)),
                "bg_blend": max(0.0, min(float(raw.get("bg_blend", 0.08)), 0.40)),
            })
    logo_x = max(0, min(int(body.get("logo_x") or 97), 100))
    logo_y = max(0, min(int(body.get("logo_y") or 97), 100))
    logo_scale_pct = max(5.0, min(float(body.get("logo_scale_pct") or 20.0), 100.0))
    logo_opacity = max(5.0, min(float(body.get("logo_opacity") or 85.0), 100.0))
    output_crf = max(18, min(int(body.get("output_crf") or 26), 35))
    max_height = max(0, _int_with_default(body.get("max_height"), 0))
    x264_preset = str(body.get("x264_preset") or "veryfast").strip().lower()
    if x264_preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
        x264_preset = "veryfast"

    body_logo_profile_id = str(body.get("logo_profile_id") or "").strip()
    body_logo_profile_name = str(body.get("logo_profile_name") or "").strip()
    body_logo_profile_layout_linked = _coerce_optional_bool(body.get("logo_profile_layout_linked"))

    try:
        req_data = json.loads(run_row["request_json"]) if isinstance(run_row["request_json"], str) else (run_row.get("request_json") or {})
    except Exception:
        req_data = {}
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    effective_logo_profile_id = body_logo_profile_id or str(wizard_state.get("logo_profile_id") or "").strip()
    effective_logo_profile_name = body_logo_profile_name or str(wizard_state.get("logo_profile_name") or "").strip()
    effective_logo_profile_layout_linked = body_logo_profile_layout_linked
    if effective_logo_profile_layout_linked is None:
        effective_logo_profile_layout_linked = _coerce_optional_bool(wizard_state.get("logo_profile_layout_linked"))
    has_logo_profile_ref = bool(effective_logo_profile_id or effective_logo_profile_name)
    if effective_logo_profile_layout_linked is None and has_logo_profile_ref:
        effective_logo_profile_layout_linked = True
    linked_profile = _find_logo_profile(
        profile_id=effective_logo_profile_id,
        company_name=effective_logo_profile_name,
    ) if has_logo_profile_ref else None
    if linked_profile:
            # Igual ao /api/burn-subtitles: só usa layout do perfil se o usuário não customizou.
            def _burn_logo_layout_differs() -> bool:
                if not body_has_logo_layout_payload:
                    return False
                try:
                    return (
                        abs(float(logo_x) - float(linked_profile.get("logo_x") or 0.0)) > 0.05
                        or abs(float(logo_y) - float(linked_profile.get("logo_y") or 0.0)) > 0.05
                        or abs(float(logo_scale_pct) - float(linked_profile.get("logo_scale_pct") or 0.0)) > 0.05
                        or abs(float(logo_opacity) - float(linked_profile.get("logo_opacity") or 0.0)) > 0.05
                    )
                except Exception:
                    return False
            if _burn_logo_layout_differs():
                effective_logo_profile_layout_linked = False
            if effective_logo_profile_layout_linked:
                logo_x = max(0, min(int(linked_profile.get("logo_x") or logo_x), 100))
                logo_y = max(0, min(int(linked_profile.get("logo_y") or logo_y), 100))
                logo_scale_pct = max(5.0, min(float(linked_profile.get("logo_scale_pct") or logo_scale_pct), 100.0))
                logo_opacity = max(5.0, min(float(linked_profile.get("logo_opacity") or logo_opacity), 100.0))
            if not logo_b64 and not logos:
                profile_logos = _logo_profile_to_payload_logos(linked_profile)
                if profile_logos:
                    if not effective_logo_profile_layout_linked:
                        profile_logos[0]["x"] = logo_x
                        profile_logos[0]["y"] = logo_y
                        profile_logos[0]["scale_pct"] = logo_scale_pct
                        profile_logos[0]["opacity"] = logo_opacity
                    logos = profile_logos
            if not logo_b64 and not logos:
                profile_logo_ref = str(linked_profile.get("logo_object_key") or "").strip()
                if profile_logo_ref:
                    logo_b64 = _media_ref_to_data_url(profile_logo_ref)

    import logging as _logging
    _logging.getLogger("uvicorn.error").warning(
        f"[teaser/burn-logo] logo_x={logo_x} logo_y={logo_y} logo_scale_pct={logo_scale_pct} "
        f"logo_opacity={logo_opacity} max_height={max_height} profile_linked={effective_logo_profile_layout_linked} "
        f"logo_present={bool(logo_b64) or bool(logos)} logo_count={len(logos) if logos else (1 if logo_b64 else 0)} "
        f"profile_id={body_logo_profile_id or ''} profile_name={body_logo_profile_name or ''}"
    )

    if not logo_b64 and not logos:
        return JSONResponse({"error": "missing_logo", "detail": "Envie uma logo antes de queimar o teaser."}, status_code=400)

    job_id = str(uuid.uuid4())
    _burn_job_put(job_id, {
        "status": "pending",
        "detail": "Queimando logo no teaser…",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cancel_requested": False,
        "run_id": run_id,
    })
    _burn_control(job_id)
    _burn_enqueue(job_id)
    asyncio.create_task(_burn_subtitles_worker(
        job_id, run_id, teaser_object_key, "", req_data,
        logo_b64=logo_b64, logos=logos, font_size=22, font_color="white", sub_delay_secs=0.0,
        output_crf=output_crf, max_height=max_height, logo_x=logo_x, logo_y=logo_y,
        logo_scale_pct=logo_scale_pct, logo_opacity=logo_opacity, x264_preset=x264_preset,
        skip_subtitles=True,
        output_prefix=f"teasers/{run_id[:8]}",
        output_filename=f"teaser_logo_{run_id[:8]}.mp4",
        wizard_update_kind="teaser_logo",
    ))
    return JSONResponse({"job_id": job_id})


@app.get("/api/teaser/status/{job_id}")
async def teaser_status(job_id: str, request: Request):
    """Retorna status de job de teaser ou concat."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = _teaser_job_get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    return JSONResponse(job)


@app.post("/api/teaser/prepend")
async def teaser_prepend(request: Request):
    """Concatena teaser + vídeo principal. position=start|end controla início/fim."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    run_id = (body.get("run_id") or "").strip()
    if run_id and not get_run(run_id):
        return JSONResponse({"error": "run_not_found"}, status_code=404)

    teaser_key = (body.get("teaser_object_key") or "").strip()
    main_key = (body.get("main_object_key") or "").strip()
    position = str(body.get("position") or "start").strip().lower()

    if not teaser_key or not main_key:
        return JSONResponse({"error": "missing_keys", "detail": "teaser_object_key e main_object_key são obrigatórios."}, status_code=400)
    if not _is_valid_object_key(teaser_key) or not _is_valid_object_key(main_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    if position not in {"start", "end"}:
        return JSONResponse({"error": "invalid_position", "detail": "position deve ser 'start' ou 'end'."}, status_code=400)

    job_id = str(uuid.uuid4())
    _teaser_job_put(job_id, {"status": "pending", "created_at": datetime.now(timezone.utc).isoformat()})
    if position == "end":
        # vídeo principal primeiro, teaser no final
        asyncio.create_task(_concat_worker(job_id, main_key, teaser_key, run_id=run_id or None))
    else:
        # teaser no início
        asyncio.create_task(_concat_worker(job_id, teaser_key, main_key, run_id=run_id or None))
    return JSONResponse({"job_id": job_id})


class RepromptRequest(BaseModel):
    selected_urls: List[str]


@app.post("/runs/{run_id}/reprompt")
def run_reprompt(run_id: str, req: RepromptRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    row = get_run(run_id)
    if not row:
        return {"error": "not_found"}

    result = row if isinstance(row, dict) else {}
    if "result_json" in result and isinstance(result["result_json"], str):
        result = json.loads(result["result_json"])

    sources = result.get("sources") or {}
    all_videos: Dict[str, Any] = {}
    for v in (sources.get("xvideos_top") or {}).get("videos") or []:
        if v.get("url"):
            all_videos[v["url"]] = v
    for v in (sources.get("xvideos_search") or {}).get("videos") or []:
        if v.get("url"):
            all_videos[v["url"]] = v

    selected = [all_videos[u] for u in req.selected_urls if u in all_videos]

    refs_lines = []
    for v in selected[:15]:
        refs_lines.append(
            f"- {v.get('title')}\n"
            f"  - url: {v.get('url')}\n"
            f"  - duração: {v.get('duration_raw')}\n"
            f"  - views: {v.get('views_raw')}\n"
            f"  - likes: {v.get('likes_raw')}\n"
            f"  - tags(originais): {', '.join((v.get('tags') or [])[:25])}"
        )

    original = (result.get("grok") or {}).get("markdown_prompt_ptbr_keep_original") or ""
    refs_block = (
        "## Referências de alto desempenho (preserve strings originais)\n"
        + ("\n".join(refs_lines) + "\n\n" if refs_lines else "(sem referências)\n\n")
    )
    new_prompt = re.sub(
        r"## Referências de alto desempenho \(preserve strings originais\)\n.*?(?=^## |\Z)",
        refs_block,
        original,
        flags=re.DOTALL | re.MULTILINE,
    )
    if new_prompt == original and refs_lines:
        new_prompt = original + "\n\n" + refs_block

    return {"prompt": new_prompt, "selected_count": len(selected)}


@app.post("/runs/{run_id}/fetch-refs")
async def run_fetch_refs(run_id: str, request: Request):
    """Re-busca referências XVideos para um run que ficou sem elas (ex: timeout durante analyze)."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    row = get_run(run_id)
    if not row:
        return {"error": "not_found"}

    result = json.loads(row["result_json"]) if isinstance(row.get("result_json"), str) else (row.get("result_json") or {})
    req_data = json.loads(row["request_json"]) if isinstance(row.get("request_json"), str) else (row.get("request_json") or {})
    existing_sources = result.get("sources") or {}
    search_query = existing_sources.get("xvideos_search_query") or ""
    ref_actor = str(req_data.get("ref_actor") or "").strip() or None
    ref_actor_count = str(req_data.get("ref_actor_count") or "").strip() or None
    ref_country = str(req_data.get("ref_country") or "").strip() or None
    ref_category = str(req_data.get("ref_category") or "").strip() or None
    ref_studio = str(req_data.get("ref_studio") or "").strip() or None

    def _opt_int(v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    ref_dur_min = _opt_int(req_data.get("ref_dur_min"))
    ref_dur_max = _opt_int(req_data.get("ref_dur_max"))
    ref_views_min = _opt_int(req_data.get("ref_views_min"))
    ref_views_max = _opt_int(req_data.get("ref_views_max"))
    ref_likes_min = _opt_int(req_data.get("ref_likes_min"))

    has_user_filters = any([
        ref_actor,
        ref_actor_count,
        ref_country,
        ref_category,
        ref_studio,
        ref_dur_min is not None,
        ref_dur_max is not None,
        ref_views_min is not None,
        ref_views_max is not None,
        ref_likes_min is not None,
    ])
    active_filter_count = sum(
        1 for _flag in [
            bool(ref_actor),
            bool(ref_actor_count),
            bool(ref_country),
            bool(ref_category),
            bool(ref_studio),
            ref_dur_min is not None,
            ref_dur_max is not None,
            ref_views_min is not None,
            ref_views_max is not None,
            ref_likes_min is not None,
        ] if _flag
    )
    allow_relaxed_profile_fallback = active_filter_count <= 1 and bool(ref_actor or ref_studio)

    # Tenta usar query salva; se não tiver, usa tags sugeridas ou texto da transcrição
    if not search_query and not has_user_filters:
        suggested_tags = (result.get("suggested") or {}).get("tags") or []
        if suggested_tags:
            search_query = " ".join(suggested_tags[:4])
        else:
            tr = (req_data.get("transcript") or {}).get("text") or ""
            search_query = tr[:80].strip() if tr else ""

    xvideos_top: Dict = {"videos": [], "top_tags": [], "avg_duration_minutes": None}
    top_used_relevance_fallback = False
    xvideos_search = None

    try:
        if has_user_filters:
            xvideos_top = await asyncio.to_thread(
                fetch_search_videos,
                query="",
                limit=20,
                sort="views",
                actor=ref_actor,
                actor_count=ref_actor_count,
                country=ref_country,
                category=ref_category,
                studio=ref_studio,
                dur_min=ref_dur_min,
                dur_max=ref_dur_max,
                views_min=ref_views_min,
                views_max=ref_views_max,
                likes_min=ref_likes_min,
            )
            if not (xvideos_top.get("videos") or []):
                xvideos_top = await asyncio.to_thread(
                    fetch_search_videos,
                    query="",
                    limit=20,
                    sort="relevance",
                    actor=ref_actor,
                    actor_count=ref_actor_count,
                    country=ref_country,
                    category=ref_category,
                    studio=ref_studio,
                    dur_min=ref_dur_min,
                    dur_max=ref_dur_max,
                    views_min=ref_views_min,
                    views_max=ref_views_max,
                    likes_min=ref_likes_min,
                )
                top_used_relevance_fallback = bool(xvideos_top.get("videos") or [])
        elif search_query:
            xvideos_top = await asyncio.to_thread(fetch_search_videos, query=search_query, limit=20, sort="views")
        else:
            xvideos_top = await asyncio.to_thread(fetch_top_videos, limit=20)
    except Exception as e:
        return {"error": "xvideos_fetch_failed", "detail": str(e)}

    if has_user_filters and not top_used_relevance_fallback:
        try:
            xvideos_search = await asyncio.to_thread(
                fetch_search_videos,
                query="",
                limit=20,
                sort="relevance",
                actor=ref_actor,
                actor_count=ref_actor_count,
                country=ref_country,
                category=ref_category,
                studio=ref_studio,
                dur_min=ref_dur_min,
                dur_max=ref_dur_max,
                views_min=ref_views_min,
                views_max=ref_views_max,
                likes_min=ref_likes_min,
            )
        except Exception:
            xvideos_search = None
        if (not ((xvideos_search or {}).get("videos") or [])) and (not allow_relaxed_profile_fallback) and (ref_actor or ref_studio):
            print("run_fetch_refs fallback skipped (strict_multi_filter_mode)")
        if (not ((xvideos_search or {}).get("videos") or [])) and allow_relaxed_profile_fallback and ref_actor:
            try:
                xvideos_search = await asyncio.to_thread(fetch_pornstar_videos, name=ref_actor, limit=20)
            except Exception:
                pass
        if (not ((xvideos_search or {}).get("videos") or [])) and allow_relaxed_profile_fallback and ref_studio:
            try:
                xvideos_search = await asyncio.to_thread(fetch_channel_videos, name=ref_studio, limit=20)
            except Exception:
                pass
    elif search_query:
        try:
            xvideos_search = await asyncio.to_thread(fetch_search_videos, query=search_query, limit=20, sort="views")
        except Exception:
            xvideos_search = None

    def _source_query(src: Optional[Dict[str, Any]]) -> str:
        try:
            return str((((src or {}).get("method") or {}).get("params") or {}).get("query") or "").strip()
        except Exception:
            return ""
    if has_user_filters:
        search_query = _source_query(xvideos_search) or _source_query(xvideos_top) or search_query

    new_sources = {
        **existing_sources,
        "xvideos_top": xvideos_top,
        "xvideos_search": xvideos_search,
        "xvideos_search_query": search_query,
        "xvideos_filter_debug": {
            "has_user_filters": has_user_filters,
            "active_filter_count": active_filter_count,
            "allow_relaxed_profile_fallback": allow_relaxed_profile_fallback,
            "top_used_relevance_fallback": top_used_relevance_fallback,
        },
    }
    update_run_result_sources(run_id=run_id, sources=new_sources)

    top_count = len((xvideos_top or {}).get("videos") or [])
    search_count = len((xvideos_search or {}).get("videos") or []) if xvideos_search else 0
    return {"ok": True, "top": top_count, "search": search_count, "query": search_query}


class LlmCompareRequest(BaseModel):
    prompt_markdown: str
    providers: List[Dict[str, Any]]
    params: Optional[Dict[str, Any]] = None


class TokenSetRequest(BaseModel):
    provider: str
    api_key: str


class LlmCompareResultRequest(BaseModel):
    prompt_markdown: str
    providers: List[Dict[str, Any]]
    params: Optional[Dict[str, Any]] = None


class PresignRequest(BaseModel):
    filename: str
    content_type: Optional[str] = None
    prefix: str = "uploads"


class StorageObjectRequest(BaseModel):
    object_key: str


class ValidateStorageObjectRequest(BaseModel):
    object_key: str
    delete_if_invalid: bool = False


class MediaRenameRequest(BaseModel):
    object_key: str
    new_filename: str


class GoogleDriveConfigRequest(BaseModel):
    folder_id: Optional[str] = None
    service_account_json: Optional[str] = None


class GoogleDriveUploadRequest(BaseModel):
    object_key: str
    folder_id: Optional[str] = None
    filename: Optional[str] = None


class GoogleDriveImportRequest(BaseModel):
    creator_id: str
    drive_file_id: str
    filename: Optional[str] = None


class TranscribeRequest(BaseModel):
    video_object_key: str
    language: Optional[str] = None
    translate_to: Optional[str] = None
    prompt: Optional[str] = None
    provider: Optional[str] = "auto"  # "auto" | "whisper_sync" | "deepgram" | "assemblyai" | "groq/openrouter" | "openai" | "local" | "premium"
    adult_mode: Optional[bool] = True
    include_vocalizations: Optional[bool] = True
    enhance_audio: Optional[bool] = True


class ScreenshotAnalyzeRequest(BaseModel):
    image_base64: str  # format: data:image/jpeg;base64,... or just base64 raw


class ThumbnailHighResRequest(BaseModel):
    run_id: str
    frame_index: int = 0
    frames_count: int = 10
    object_key: Optional[str] = None


class ThumbnailAiGenerateRequest(BaseModel):
    run_id: Optional[str] = None
    prompt: str
    n: int = 2
    aspect_ratio: Optional[str] = "16:9"
    resolution: Optional[str] = "2k"
    style: Optional[str] = None
    quality: Optional[str] = None
    vision_hint: Optional[str] = None
    source_image_b64: Optional[str] = None  # reservado para futura versão image-to-image


class LogoPresetSetRequest(BaseModel):
    name: Optional[str] = "Padrao salvo"
    logo_x: float = Field(default=97.0, ge=0.0, le=100.0)
    logo_y: float = Field(default=97.0, ge=0.0, le=100.0)
    logo_scale_pct: float = Field(default=20.0, ge=5.0, le=100.0)
    logo_opacity: float = Field(default=85.0, ge=5.0, le=100.0)


class LogoProfileSetRequest(BaseModel):
    profile_id: Optional[str] = None
    company_name: str
    logo_b64: Optional[str] = ""
    logo_name: Optional[str] = None
    logos: Optional[List[Dict[str, Any]]] = None
    logo_x: float = Field(default=97.0, ge=0.0, le=100.0)
    logo_y: float = Field(default=97.0, ge=0.0, le=100.0)
    logo_scale_pct: float = Field(default=20.0, ge=5.0, le=100.0)
    logo_opacity: float = Field(default=85.0, ge=5.0, le=100.0)


@app.post("/llm/compare/stream")
async def llm_compare_stream(req: LlmCompareRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    if not req.prompt_markdown.strip():
        return {"error": "missing_prompt_markdown"}
    if len(req.providers) < 2:
        return {"error": "missing_providers", "detail": "send at least 2 providers"}
    try:
        specs = _build_provider_specs(req.providers)
    except ValueError as e:
        return {"error": str(e)}

    async def event_gen():
        async for msg in merge_streams(prompt=req.prompt_markdown, providers=specs, params=req.params):
            # SSE: event name = msg["event"], data = json
            yield {
                "event": msg.get("event", "message"),
                "data": json.dumps(msg, ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())


def _s3_client():
    if not (S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY and S3_ENDPOINT_URL):
        return None

    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=300,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _s3_presign_client():
    """Cliente S3 exclusivo para generate_presigned_url.
    Usa o endpoint público (S3_PUBLIC_BASE_URL) para que as URLs geradas
    sejam acessíveis pelo browser, não o endpoint interno do Docker.
    """
    endpoint = S3_PUBLIC_BASE_URL.rstrip("/") if S3_PUBLIC_BASE_URL else S3_ENDPOINT_URL
    if not (S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY and endpoint):
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


@app.post("/uploads/presign")
def uploads_presign(req: PresignRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    s3 = _s3_client()
    if not s3:
        return {"error": "s3_not_configured"}

    raw_name = os.path.basename((req.filename or "").strip())
    if not raw_name:
        return {"error": "missing_filename"}
    safe_name = re.sub(r"[^a-zA-Z0-9._\-]", "_", raw_name)[:180]
    if not safe_name:
        safe_name = "upload.bin"

    prefix = (req.prefix or "uploads").strip().strip("/")
    prefix = re.sub(r"[^a-zA-Z0-9._/\-]", "_", prefix)
    if ".." in prefix:
        return {"error": "invalid_prefix"}
    if not prefix:
        prefix = "uploads"

    object_key = f"{prefix}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}-{safe_name}"
    if not _is_valid_object_key(object_key):
        return {"error": "invalid_object_key"}

    expires_in = 60 * 10  # 10 min
    put_params = {
        "Bucket": S3_BUCKET,
        "Key": object_key,
    }
    signed_content_type = _normalize_content_type(req.content_type)
    if signed_content_type:
        put_params["ContentType"] = signed_content_type

    upload_url = _s3_presign_client().generate_presigned_url(
        ClientMethod="put_object",
        Params=put_params,
        ExpiresIn=expires_in,
    )

    public_url = S3_PUBLIC_BASE_URL.rstrip("/") + f"/{S3_BUCKET}/{object_key}"

    return {
        "ok": True,
        "bucket": S3_BUCKET,
        "object_key": object_key,
        "upload_url": upload_url,
        "public_url": public_url,
        "expires_in": expires_in,
        "required_headers": ({"Content-Type": signed_content_type} if signed_content_type else {}),
    }

@app.get("/api/local-media/stream")
async def local_media_stream(ref: str, request: Request):
    if not _is_valid_object_key(ref) or not _is_local_media_ref(ref):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    auth_err = _authorize_local_media_request(request, ref, "inline")
    if auth_err:
        return JSONResponse(auth_err, status_code=401)
    try:
        abs_path = _local_media_abs_path_from_ref(ref)
    except Exception:
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    if not os.path.exists(abs_path):
        return JSONResponse({"error": "object_not_found"}, status_code=404)
    response = FileResponse(abs_path, media_type=_guess_response_content_type(ref))
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@app.get("/api/local-media/download")
async def local_media_download(ref: str, request: Request, filename: str = ""):
    if not _is_valid_object_key(ref) or not _is_local_media_ref(ref):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    safe_filename = _safe_storage_filename(filename, os.path.basename(_media_ref_relative_path(ref) or "media.bin"))
    auth_err = _authorize_local_media_request(request, ref, "attachment", safe_filename)
    if auth_err:
        return JSONResponse(auth_err, status_code=401)
    try:
        abs_path = _local_media_abs_path_from_ref(ref)
    except Exception:
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    if not os.path.exists(abs_path):
        return JSONResponse({"error": "object_not_found"}, status_code=404)
    response = FileResponse(abs_path, media_type=_guess_response_content_type(ref))
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@app.get("/api/video-download-url")
async def video_download_url(object_key: str, request: Request, filename: str = ""):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    if not _is_valid_object_key(object_key):
        return {"error": "invalid_object_key"}
    safe_filename = _safe_storage_filename(filename or os.path.basename(_media_ref_relative_path(object_key) or "video.mp4"), "video.mp4")
    if "." not in safe_filename:
        ext = os.path.splitext(_media_ref_relative_path(object_key) or "")[1] or ".mp4"
        safe_filename += ext
    if _is_local_media_ref(object_key):
        return {"ok": True, "url": _build_local_media_url(object_key, disposition="attachment", filename=safe_filename)}

    s3 = _s3_client()
    if not s3:
        return {"error": "s3_not_configured"}
    try:
        url = await asyncio.to_thread(
            lambda: _s3_presign_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_BUCKET,
                    "Key": object_key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_filename}"',
                    "ResponseContentType": _guess_response_content_type(object_key),
                },
                ExpiresIn=3600,
            )
        )
        return {"ok": True, "url": url}
    except Exception as e:
        return {"error": "presign_failed", "detail": str(e)}


@app.get("/api/video-stream-url")
async def video_stream_url(object_key: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    if not _is_valid_object_key(object_key):
        return {"error": "invalid_object_key"}
    if _is_local_media_ref(object_key):
        return {"ok": True, "url": _build_local_media_url(object_key)}

    s3 = _s3_client()
    if not s3:
        return {"error": "s3_not_configured"}
    resp_type = _guess_response_content_type(object_key)
    try:
        url = await asyncio.to_thread(
            lambda: _s3_presign_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_BUCKET,
                    "Key": object_key,
                    "ResponseContentType": resp_type,
                },
                ExpiresIn=3600,
            )
        )
        return {"ok": True, "url": url}
    except Exception as e:
        return {"error": "presign_failed", "detail": str(e)}


@app.get("/api/video-preview-url")
async def video_preview_url(
    object_key: str,
    request: Request,
    max_height: int = 1080,
    max_fps: int = 30,
    output_crf: int = 28,
):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    if not _is_valid_object_key(object_key):
        return {"error": "invalid_object_key"}

    s3 = _s3_client()
    safe_h = max(360, min(int(max_height or 1080), 2160))
    safe_fps = max(24, min(int(max_fps or 30), 60))
    safe_crf = max(22, min(int(output_crf or 28), 35))
    preview_rel = _preview_variant_key(object_key, safe_h, safe_fps, safe_crf)
    preview_ref = _local_media_ref(preview_rel)

    async def _stream_payload_for_media_ref(key: str) -> Dict[str, Any]:
        if _is_local_media_ref(key):
            return {"ok": True, "url": _build_local_media_url(key), "object_key": key}
        resp_type = _guess_response_content_type(key)
        url = await asyncio.to_thread(
            lambda: _s3_presign_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_BUCKET,
                    "Key": key,
                    "ResponseContentType": resp_type,
                },
                ExpiresIn=3600,
            )
        )
        return {"ok": True, "url": url, "object_key": key}

    try:
        if await asyncio.to_thread(_media_ref_exists, media_ref=preview_ref, s3=s3):
            out = await _stream_payload_for_media_ref(preview_ref)
            out["is_preview"] = True
            return out

        lock = await _preview_lock_for(preview_ref)
        async with lock:
            if await asyncio.to_thread(_media_ref_exists, media_ref=preview_ref, s3=s3):
                out = await _stream_payload_for_media_ref(preview_ref)
                out["is_preview"] = True
                return out

            chosen_key, reason = await asyncio.to_thread(
                _create_preview_variant_sync,
                source_key=object_key,
                preview_key=preview_rel,
                max_height=safe_h,
                max_fps=safe_fps,
                output_crf=safe_crf,
            )
            out = await _stream_payload_for_media_ref(chosen_key)
            out["is_preview"] = bool(chosen_key == preview_ref)
            out["reason"] = reason
            return out
    except Exception as e:
        try:
            out = await _stream_payload_for_media_ref(object_key)
            out["is_preview"] = False
            out["fallback"] = True
            out["detail"] = str(e)
            return out
        except Exception as e2:
            return {"error": "preview_failed", "detail": str(e2)}


class UploadMetaRequest(BaseModel):
    object_key: str
    display_name: str = ""
    company_id: str = ""
    company_name: str = ""


class MediaMetadataBatchRequest(BaseModel):
    object_keys: List[str] = Field(default_factory=list)


@app.post("/uploads/set-meta")
async def uploads_set_meta(req: UploadMetaRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    key = str(req.object_key or "").strip()
    if not key:
        return JSONResponse({"error": "missing_object_key"}, status_code=400)
    upload_meta_set(
        object_key=key,
        display_name=str(req.display_name or "").strip(),
        company_id=str(req.company_id or "").strip(),
        company_name=str(req.company_name or "").strip(),
    )
    return {"ok": True}


@app.get("/uploads/list")
async def list_uploads(request: Request, prefix: str = "uploads", max_keys: int = 100):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    safe_max_keys = max(1, min(int(max_keys or 100), 1000))
    items: List[Dict[str, Any]] = []
    try:
        items.extend(await asyncio.to_thread(_list_local_media_items, prefix, safe_max_keys))
    except Exception:
        pass

    s3 = _s3_client()
    if s3:
        try:
            paginator = s3.get_paginator("list_objects_v2")
            safe_prefix = _sanitize_storage_prefix(prefix, "uploads").strip("/") + "/"
            pages = paginator.paginate(
                Bucket=S3_BUCKET,
                Prefix=safe_prefix,
                PaginationConfig={"MaxItems": safe_max_keys},
            )
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    fname = key.split("/")[-1]
                    url = S3_PUBLIC_BASE_URL.rstrip("/") + f"/{S3_BUCKET}/{key}"
                    items.append({
                        "object_key": key,
                        "filename": fname,
                        "public_url": url,
                        "size_bytes": int(obj["Size"] or 0),
                        "size_mb": round(obj["Size"] / 1024 / 1024, 1),
                        "last_modified": obj["LastModified"].isoformat(),
                        "storage_kind": "s3",
                    })
        except Exception as e:
            # S3/MinIO unavailable — continue with local items already collected
            if not items:
                return {"error": "list_uploads_failed", "detail": str(e)}

    items.sort(key=lambda x: x.get("last_modified") or "", reverse=True)
    result_items = items[:safe_max_keys]
    # Enrich with stored display metadata
    keys = [it["object_key"] for it in result_items]
    meta_map = upload_meta_get_many(keys)
    for it in result_items:
        meta = meta_map.get(it["object_key"]) or {}
        if meta.get("display_name"):
            it["filename"] = meta["display_name"]
        else:
            # Auto-clean UUID prefix from filename for existing files
            it["filename"] = _clean_upload_filename(it.get("filename") or "")
        if meta.get("company_name"):
            it["company_name"] = meta["company_name"]
        if meta.get("company_id"):
            it["company_id"] = meta["company_id"]
    return {"ok": True, "items": result_items}


@app.post("/api/media-manager/metadata/batch")
async def media_manager_metadata_batch(req: MediaMetadataBatchRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    raw_keys = [str(v or "").strip() for v in (req.object_keys or [])]
    keys: List[str] = []
    seen: set[str] = set()
    for key in raw_keys:
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
        if len(keys) >= 120:
            break
    items: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for key in keys:
        if not _is_valid_object_key(key):
            errors[key] = "invalid_object_key"
            continue
        try:
            meta = await asyncio.to_thread(_probe_media_ref_metadata_cached, key)
            items[key] = meta
        except Exception as exc:
            errors[key] = _safe_error_detail(exc, "metadata_unavailable")
    return {"ok": True, "items": items, "errors": errors}


@app.get("/api/media-manager/thumbnail-url")
async def media_manager_thumbnail_url(object_key: str, request: Request, width: int = 480, t: float = 8.0):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    object_key = str(object_key or "").strip()
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    try:
        sig_ref = await asyncio.to_thread(
            _media_manager_thumbnail_cache_ref,
            object_key,
            width=max(220, min(int(width or 480), 960)),
            seek_seconds=max(0.1, float(t or 8.0)),
        )
        lock = await _preview_lock_for(sig_ref)
        async with lock:
            out = await asyncio.to_thread(
                _media_manager_thumbnail_sync,
                object_key,
                width=width,
                seek_seconds=t,
            )
        return {"ok": True, **out}
    except Exception as exc:
        return JSONResponse(
            {"error": "thumbnail_unavailable", "detail": _safe_error_detail(exc, "thumbnail_unavailable")},
            status_code=422,
        )


@app.post("/uploads/validate")
async def validate_storage_video(req: ValidateStorageObjectRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    object_key = str(req.object_key or "").strip()
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    try:
        result = await asyncio.to_thread(_validate_video_object_sync, s3=_s3_client(), object_key=object_key)
    except Exception as e:
        return JSONResponse(
            {"error": "validate_failed", "detail": _safe_error_detail(e, "storage_validate_failed")},
            status_code=502,
        )
    if result.get("ok"):
        return {"ok": True, "valid": True, **result}
    deleted = False
    if req.delete_if_invalid:
        try:
            await asyncio.to_thread(_delete_media_ref, media_ref=object_key, s3=_s3_client())
            deleted = True
        except Exception as e:
            result["delete_error"] = _safe_error_detail(e, "storage_delete_failed")
    return JSONResponse(
        {"ok": True, "valid": False, "deleted": deleted, **result},
        status_code=422,
    )


@app.delete("/uploads/object")
async def delete_storage_object(object_key: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    object_key = str(object_key or "").strip()
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    try:
        await asyncio.to_thread(_delete_media_ref, media_ref=object_key, s3=_s3_client())
        return {"ok": True, "deleted_key": object_key}
    except Exception as e:
        return JSONResponse(
            {"error": "delete_failed", "detail": _safe_error_detail(e, "storage_delete_failed")},
            status_code=502,
        )


@app.post("/api/media-manager/rename")
async def media_manager_rename(req: MediaRenameRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    object_key = str(req.object_key or "").strip()
    new_filename = str(req.new_filename or "").strip()
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    if not new_filename:
        return JSONResponse({"error": "missing_new_filename"}, status_code=400)
    try:
        item = await asyncio.to_thread(_rename_media_ref, media_ref=object_key, new_filename=new_filename, s3=_s3_client())
        return {"ok": True, "item": item}
    except FileExistsError:
        return JSONResponse({"error": "target_already_exists"}, status_code=409)
    except FileNotFoundError:
        return JSONResponse({"error": "object_not_found"}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": "rename_failed", "detail": _safe_error_detail(e, "media_rename_failed")},
            status_code=502,
        )


@app.get("/api/media-manager/google-drive/config")
def google_drive_config_get(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    return _google_drive_config_status()


@app.post("/api/media-manager/google-drive/config")
def google_drive_config_set(req: GoogleDriveConfigRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    current_folder = str((settings_get(key=GOOGLE_DRIVE_FOLDER_SETTINGS_KEY) or {}).get("value") or "").strip()
    current_creds = str((settings_get(key=GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY) or {}).get("value") or "")
    next_folder = current_folder if req.folder_id is None else str(req.folder_id or "").strip()
    next_creds = current_creds if req.service_account_json is None else str(req.service_account_json or "")

    if req.service_account_json is not None and str(next_creds or "").strip():
        try:
            _parse_google_drive_service_account(next_creds)
        except Exception as exc:
            return JSONResponse(
                {"error": "invalid_service_account_json", "detail": _safe_error_detail(exc, "google_drive_service_account_invalid")},
                status_code=400,
            )

    now = datetime.now(timezone.utc).isoformat()
    if req.folder_id is not None:
        settings_set(key=GOOGLE_DRIVE_FOLDER_SETTINGS_KEY, value=next_folder, updated_at=now)
    if req.service_account_json is not None:
        settings_set(key=GOOGLE_DRIVE_SERVICE_ACCOUNT_SETTINGS_KEY, value=next_creds, updated_at=now)

    payload = _google_drive_config_status()
    payload["updated_at"] = now
    return payload


@app.post("/api/media-manager/google-drive/upload")
async def google_drive_upload_start(req: GoogleDriveUploadRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    object_key = str(req.object_key or "").strip()
    if not _is_valid_object_key(object_key):
        return JSONResponse({"error": "invalid_object_key"}, status_code=400)
    if not await asyncio.to_thread(_media_ref_exists, media_ref=object_key, s3=_s3_client()):
        return JSONResponse({"error": "object_not_found"}, status_code=404)

    cfg = _google_drive_config_status()
    folder_id = str(req.folder_id or cfg.get("folder_id") or "").strip()
    if not bool(cfg.get("has_credentials")):
        return JSONResponse({"error": "google_drive_credentials_not_configured"}, status_code=400)
    if not str(cfg.get("service_account_email") or "").strip():
        return JSONResponse({"error": "invalid_service_account_json", "detail": cfg.get("detail") or "Credenciais do Google Drive inválidas."}, status_code=400)
    if not folder_id:
        return JSONResponse({"error": "google_drive_folder_not_configured"}, status_code=400)

    filename = _safe_storage_filename(
        str(req.filename or os.path.basename(_media_ref_relative_path(object_key) or "arquivo.mp4")),
        os.path.basename(_media_ref_relative_path(object_key) or "arquivo.mp4"),
    )
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    _drive_upload_job_put(job_id, {
        "kind": _ASYNC_JOB_KIND_DRIVE_UPLOAD,
        "job_id": job_id,
        "status": "pending",
        "detail": "Upload para o Google Drive enfileirado.",
        "object_key": object_key,
        "filename": filename,
        "folder_id": folder_id,
        "created_at": now,
        "updated_at": now,
        "progress_pct": 0,
    })
    asyncio.create_task(_drive_upload_worker(job_id, object_key=object_key, folder_id=folder_id, filename=filename))
    return {"ok": True, "job_id": job_id}


@app.get("/api/media-manager/google-drive/upload/{job_id}")
def google_drive_upload_status(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = _drive_upload_job_get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    return job


@app.get("/api/media-manager/google-drive/intake/config")
def google_drive_intake_config_get(request: Request, creator_id: str = ""):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    cfg = _google_drive_creator_config(creator_id)
    cfg.pop("_raw_service_account", None)
    return cfg


@app.get("/api/media-manager/google-drive/intake/files")
async def google_drive_intake_files(request: Request, creator_id: str, page_size: int = 100):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    safe_creator_id = str(creator_id or "").strip()
    if not safe_creator_id:
        return JSONResponse({"error": "missing_creator_id"}, status_code=400)
    cfg = _google_drive_creator_config(safe_creator_id)
    raw_creds = str(cfg.get("_raw_service_account") or "")
    folder_id = str(cfg.get("folder_id") or "").strip()
    public_cfg = dict(cfg)
    public_cfg.pop("_raw_service_account", None)
    if not cfg.get("configured"):
        return JSONResponse(
            {"error": "google_drive_not_configured", "config": public_cfg, "detail": cfg.get("detail") or "Google Drive do criador não configurado."},
            status_code=400,
        )
    try:
        payload = await asyncio.to_thread(
            _google_drive_list_folder_sync,
            folder_id=folder_id,
            raw_creds=raw_creds,
            page_size=page_size,
        )
        payload["config"] = public_cfg
        return payload
    except Exception as exc:
        return JSONResponse(
            {"error": "google_drive_list_failed", "detail": _safe_error_detail(exc, "google_drive_list_failed"), "config": public_cfg},
            status_code=502,
        )


@app.post("/api/media-manager/google-drive/intake/import")
async def google_drive_intake_import(req: GoogleDriveImportRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    safe_creator_id = str(req.creator_id or "").strip()
    safe_drive_file_id = str(req.drive_file_id or "").strip()
    if not safe_creator_id:
        return JSONResponse({"error": "missing_creator_id"}, status_code=400)
    if not safe_drive_file_id:
        return JSONResponse({"error": "missing_drive_file_id"}, status_code=400)
    creator = creator_get(safe_creator_id)
    if not creator:
        return JSONResponse({"error": "creator_not_found"}, status_code=404)
    cfg = _google_drive_creator_config(safe_creator_id)
    if not cfg.get("configured"):
        return JSONResponse(
            {"error": "google_drive_not_configured", "detail": cfg.get("detail") or "Google Drive do criador não configurado."},
            status_code=400,
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    _drive_import_job_put(job_id, {
        "kind": _ASYNC_JOB_KIND_DRIVE_IMPORT,
        "job_id": job_id,
        "status": "pending",
        "detail": "Importação do Google Drive enfileirada.",
        "creator_id": safe_creator_id,
        "creator_name": str(creator.get("name") or "").strip(),
        "drive_file_id": safe_drive_file_id,
        "filename": str(req.filename or "").strip(),
        "created_at": now,
        "updated_at": now,
        "progress_pct": 0,
    })
    asyncio.create_task(
        _drive_import_worker(
            job_id,
            creator_id=safe_creator_id,
            drive_file_id=safe_drive_file_id,
            filename=str(req.filename or "").strip(),
        )
    )
    return {"ok": True, "job_id": job_id}


@app.get("/api/media-manager/google-drive/intake/import/{job_id}")
def google_drive_intake_import_status(job_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    job = _drive_import_job_get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    return job


# ── Upload chunked local ─────────────────────────────────────────────────────
# Arquivos pequenos continuam em `/uploads/local-stream`. Para arquivos grandes,
# o navegador envia partes menores; o backend monta e valida antes de mover para
# o storage local definitivo.

_CHUNK_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)
_CHUNK_UPLOAD_MAX_PARTS = 100000
_CHUNK_UPLOAD_READ_SIZE = 1024 * 1024
_chunk_complete_locks: Dict[str, threading.Lock] = {}
_chunk_complete_locks_guard = threading.Lock()


class _ChunkUploadHTTPError(Exception):
    def __init__(self, payload: Dict[str, Any], status_code: int = 400):
        super().__init__(str(payload.get("error") or "chunk_upload_error"))
        self.payload = payload
        self.status_code = status_code


def _chunk_upload_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def _chunk_upload_root() -> str:
    root = _preferred_tmpdir_root("upload-chunks") or os.path.join(tempfile.gettempdir(), "upload-chunks")
    os.makedirs(root, exist_ok=True)
    return os.path.abspath(root)


def _safe_chunk_upload_id(upload_id: str) -> str:
    safe_id = str(upload_id or "").strip().lower()
    if not _CHUNK_UPLOAD_ID_RE.fullmatch(safe_id):
        raise ValueError("invalid_upload_id")
    return safe_id


def _chunk_upload_dir(upload_id: str) -> str:
    safe_id = _safe_chunk_upload_id(upload_id)
    root = _chunk_upload_root()
    path = os.path.abspath(os.path.join(root, safe_id))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("invalid_upload_path")
    return path


def _chunk_parts_dir(upload_id: str) -> str:
    return os.path.join(_chunk_upload_dir(upload_id), "parts")


def _chunk_part_path(upload_id: str, part_number: int) -> str:
    return os.path.join(_chunk_parts_dir(upload_id), f"{int(part_number):06d}.part")


def _chunk_meta_path(upload_id: str) -> str:
    return os.path.join(_chunk_upload_dir(upload_id), "meta.json")


def _read_chunk_upload_meta(upload_id: str) -> Dict[str, Any]:
    try:
        with open(_chunk_meta_path(upload_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_chunk_upload_meta(upload_id: str, meta: Dict[str, Any]) -> None:
    upload_dir = _chunk_upload_dir(upload_id)
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(_chunk_parts_dir(upload_id), exist_ok=True)
    tmp_path = f"{_chunk_meta_path(upload_id)}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, sort_keys=True)
    os.replace(tmp_path, _chunk_meta_path(upload_id))


def _delete_chunk_upload(upload_id: str, *, delete_db: bool = True) -> None:
    try:
        shutil.rmtree(_chunk_upload_dir(upload_id), ignore_errors=True)
    except Exception:
        pass
    if delete_db:
        try:
            multipart_delete(_safe_chunk_upload_id(upload_id))
        except Exception:
            pass


def _chunk_completed_key(upload_id: str) -> str:
    return f"chunk-upload-complete:{_safe_chunk_upload_id(upload_id)}"


def _chunk_completed_get(upload_id: str) -> Optional[Dict[str, Any]]:
    try:
        row = settings_get(key=_chunk_completed_key(upload_id))
    except Exception:
        row = None
    if not row:
        return None
    try:
        data = json.loads(row.get("value") or "{}")
    except Exception:
        data = None
    return data if isinstance(data, dict) and data.get("ok") and data.get("object_key") else None


def _chunk_completed_set(upload_id: str, payload: Dict[str, Any]) -> None:
    safe_payload = dict(payload)
    now = datetime.now(timezone.utc).isoformat()
    safe_payload["completed_at"] = now
    try:
        settings_set(
            key=_chunk_completed_key(upload_id),
            value=json.dumps(safe_payload, ensure_ascii=False),
            updated_at=now,
        )
    except Exception:
        pass


def _chunk_complete_lock(upload_id: str) -> threading.Lock:
    safe_id = _safe_chunk_upload_id(upload_id)
    with _chunk_complete_locks_guard:
        lock = _chunk_complete_locks.get(safe_id)
        if lock is None:
            lock = threading.Lock()
            _chunk_complete_locks[safe_id] = lock
        return lock


def _chunk_upload_error(error: str, detail: str, status_code: int = 400, **extra: Any) -> JSONResponse:
    payload = {"error": error, "detail": detail}
    payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _chunk_upload_complete_sync(upload_id: str, state: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    safe_id = _safe_chunk_upload_id(upload_id)
    expected_size = max(0, int(state.get("expected_size") or meta.get("expected_size") or 0))
    expected_parts = max(0, int(state.get("expected_parts") or meta.get("expected_parts") or 0))
    if expected_size <= 0 or expected_parts <= 0:
        raise _ChunkUploadHTTPError(
            {
                "error": "invalid_chunk_upload_state",
                "detail": "Sessão de upload sem tamanho ou quantidade de partes esperada.",
            },
            status_code=400,
        )

    received_parts = set()
    for part in state.get("parts") or []:
        try:
            pn = int(part.get("PartNumber"))
        except Exception:
            continue
        if pn > 0:
            received_parts.add(pn)
    missing = [pn for pn in range(1, expected_parts + 1) if pn not in received_parts or not os.path.exists(_chunk_part_path(safe_id, pn))]
    if missing:
        raise _ChunkUploadHTTPError(
            {
                "error": "missing_upload_parts",
                "detail": f"Upload incompleto: {len(missing)} parte(s) ainda nao chegaram.",
                "missing_parts": missing[:50],
                "expected_parts": expected_parts,
                "received_parts": len(received_parts),
            },
            status_code=409,
        )

    safe_name = _safe_storage_filename(str(meta.get("filename") or state.get("object_key") or "upload.bin"), "upload.bin")
    safe_prefix = _sanitize_storage_prefix(str(meta.get("prefix") or "uploads"), "uploads")
    content_type = _normalize_content_type(str(meta.get("content_type") or "")) or _guess_response_content_type(safe_name)
    assembled_path = os.path.join(_chunk_upload_dir(safe_id), f"assembled-{safe_name}")
    tmp_assembled = f"{assembled_path}.tmp"
    sha256 = hashlib.sha256()
    written = 0

    try:
        with open(tmp_assembled, "wb") as out:
            for pn in range(1, expected_parts + 1):
                part_path = _chunk_part_path(safe_id, pn)
                with open(part_path, "rb") as inp:
                    while True:
                        buf = inp.read(4 * 1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        sha256.update(buf)
                        written += len(buf)
        os.replace(tmp_assembled, assembled_path)
    finally:
        try:
            if os.path.exists(tmp_assembled):
                os.remove(tmp_assembled)
        except Exception:
            pass

    if written <= 0:
        _delete_chunk_upload(safe_id)
        raise _ChunkUploadHTTPError(
            {"error": "empty_upload", "detail": "O arquivo recebido está vazio."},
            status_code=400,
        )
    if expected_size > 0 and written != expected_size:
        _delete_chunk_upload(safe_id)
        raise _ChunkUploadHTTPError(
            {
                "error": "upload_size_mismatch",
                "detail": (
                    "O tamanho montado nao bate com o tamanho informado pelo navegador. "
                    f"Esperado: {expected_size} bytes; recebido: {written} bytes."
                ),
                "expected_bytes": expected_size,
                "received_bytes": written,
            },
            status_code=400,
        )

    validation_result = None
    should_validate = _chunk_upload_bool(meta.get("validate")) and _looks_like_video_upload(filename=safe_name, content_type=content_type)
    if should_validate:
        validation_result = _validate_video_path_sync(
            in_path=assembled_path,
            size_bytes=written,
            storage_path=assembled_path,
        )
        if not validation_result.get("ok"):
            if _chunk_upload_bool(meta.get("delete_if_invalid")):
                _delete_chunk_upload(safe_id)
            raise _ChunkUploadHTTPError(
                {
                    "error": "uploaded_media_invalid",
                    "detail": validation_result.get("detail") or "O vídeo enviado falhou na validação.",
                    "deleted": _chunk_upload_bool(meta.get("delete_if_invalid")),
                    "validation": validation_result,
                },
                status_code=422,
            )

    stored = _store_local_path_by_move(
        src_path=assembled_path,
        prefix=safe_prefix,
        filename=safe_name,
        content_type=content_type,
    )
    result = {
        "ok": True,
        **stored,
        "sha256": sha256.hexdigest(),
        "validation": validation_result,
        "chunked": True,
        "parts": expected_parts,
    }
    _chunk_completed_set(safe_id, result)
    _delete_chunk_upload(safe_id)
    return result


def _chunk_upload_complete_locked(upload_id: str) -> Dict[str, Any]:
    safe_id = _safe_chunk_upload_id(upload_id)
    with _chunk_complete_lock(safe_id):
        completed = _chunk_completed_get(safe_id)
        if completed:
            return completed
        state = multipart_get(safe_id)
        if not state:
            raise _ChunkUploadHTTPError(
                {
                    "error": "upload_not_found",
                    "detail": "Sessão de upload não encontrada ou expirada.",
                },
                status_code=404,
            )
        meta = _read_chunk_upload_meta(safe_id)
        if not meta:
            completed = _chunk_completed_get(safe_id)
            if completed:
                return completed
            raise _ChunkUploadHTTPError(
                {
                    "error": "upload_files_expired",
                    "detail": "Arquivos temporários do upload expiraram. Envie o vídeo novamente.",
                },
                status_code=410,
            )
        return _chunk_upload_complete_sync(safe_id, state, meta)


def _chunk_upload_abort_locked(upload_id: str) -> None:
    safe_id = _safe_chunk_upload_id(upload_id)
    with _chunk_complete_lock(safe_id):
        if _chunk_completed_get(safe_id):
            return
        _delete_chunk_upload(safe_id)


@app.post("/uploads/chunk/init")
async def upload_chunk_init(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    filename = str(body.get("filename") or "upload.bin")
    safe_name = _safe_storage_filename(filename, "upload.bin")
    safe_prefix = _sanitize_storage_prefix(str(body.get("prefix") or "uploads"), "uploads")
    content_type = _normalize_content_type(str(body.get("content_type") or "")) or _guess_response_content_type(safe_name)
    try:
        expected_size = max(0, int(body.get("size") or body.get("total_size") or body.get("expected_size") or 0))
    except Exception:
        expected_size = 0
    try:
        chunk_size = max(1024 * 1024, int(body.get("chunk_size") or (16 * 1024 * 1024)))
    except Exception:
        chunk_size = 16 * 1024 * 1024
    chunk_size = min(chunk_size, 128 * 1024 * 1024)
    try:
        expected_parts = max(0, int(body.get("total_parts") or body.get("expected_parts") or 0))
    except Exception:
        expected_parts = 0
    if expected_parts <= 0 and expected_size > 0:
        expected_parts = (expected_size + chunk_size - 1) // chunk_size

    if expected_size <= 0:
        return _chunk_upload_error("invalid_upload_size", "Tamanho do arquivo ausente ou inválido.", 400)
    if expected_parts <= 0 or expected_parts > _CHUNK_UPLOAD_MAX_PARTS:
        return _chunk_upload_error("invalid_upload_parts", "Quantidade de partes ausente ou inválida.", 400)

    upload_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "upload_id": upload_id,
        "filename": safe_name,
        "original_filename": filename,
        "prefix": safe_prefix,
        "content_type": content_type,
        "expected_size": expected_size,
        "expected_parts": expected_parts,
        "chunk_size": chunk_size,
        "validate": _chunk_upload_bool(body.get("validate")),
        "delete_if_invalid": _chunk_upload_bool(body.get("delete_if_invalid")),
        "created_at": now,
    }
    _write_chunk_upload_meta(upload_id, meta)
    try:
        multipart_create(
            upload_id=upload_id,
            object_key=safe_name,
            minio_upload_id=f"local:{upload_id}",
            created_at=now,
            expected_size=expected_size,
            expected_parts=expected_parts,
        )
    except Exception:
        _delete_chunk_upload(upload_id, delete_db=False)
        raise

    return {
        "ok": True,
        "upload_id": upload_id,
        "chunk_size": chunk_size,
        "expected_size": expected_size,
        "expected_parts": expected_parts,
    }


@app.post("/uploads/chunk/part")
async def upload_chunk_part(request: Request, upload_id: str = Form(...), part_number: int = Form(...), chunk: UploadFile = File(...)):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        safe_id = _safe_chunk_upload_id(upload_id)
    except ValueError:
        return _chunk_upload_error("invalid_upload_id", "ID de upload inválido.", 400)
    state = multipart_get(safe_id)
    if not state:
        return _chunk_upload_error("upload_not_found", "Sessão de upload não encontrada ou expirada.", 404)
    meta = _read_chunk_upload_meta(safe_id)
    expected_parts = max(0, int(state.get("expected_parts") or meta.get("expected_parts") or 0))
    if part_number < 1 or (expected_parts > 0 and part_number > expected_parts):
        return _chunk_upload_error("invalid_part_number", "Número da parte inválido.", 400)

    os.makedirs(_chunk_parts_dir(safe_id), exist_ok=True)
    part_path = _chunk_part_path(safe_id, part_number)
    tmp_path = f"{part_path}.tmp-{uuid.uuid4().hex}"
    sha256 = hashlib.sha256()
    written = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                buf = await chunk.read(_CHUNK_UPLOAD_READ_SIZE)
                if not buf:
                    break
                out.write(buf)
                sha256.update(buf)
                written += len(buf)
        if written <= 0:
            return _chunk_upload_error("empty_upload_part", "Parte recebida vazia.", 400)
        os.replace(tmp_path, part_path)
        etag = f"{written}:{sha256.hexdigest()}"
        multipart_add_part(upload_id=safe_id, part_number=part_number, etag=etag)
        return {
            "ok": True,
            "upload_id": safe_id,
            "part_number": part_number,
            "size_bytes": written,
            "etag": etag,
        }
    except ClientDisconnect:
        return _chunk_upload_error("client_disconnected", "O upload da parte foi interrompido.", 499, part_number=part_number)
    finally:
        try:
            await chunk.close()
        except Exception:
            pass
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@app.post("/uploads/chunk/complete")
async def upload_chunk_complete(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        safe_id = _safe_chunk_upload_id(str(body.get("upload_id") or ""))
    except ValueError:
        return _chunk_upload_error("invalid_upload_id", "ID de upload inválido.", 400)
    try:
        return await asyncio.to_thread(_chunk_upload_complete_locked, safe_id)
    except _ChunkUploadHTTPError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    except Exception as exc:
        return _chunk_upload_error("chunk_complete_failed", _safe_error_detail(exc, "chunk_complete_failed"), 500)


@app.post("/uploads/chunk/abort")
async def upload_chunk_abort(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        safe_id = _safe_chunk_upload_id(str(body.get("upload_id") or ""))
    except ValueError:
        return {"ok": True}
    await asyncio.to_thread(_chunk_upload_abort_locked, safe_id)
    return {"ok": True}


@app.post("/uploads/local-stream")
async def upload_local_stream(
    request: Request,
    prefix: str = "uploads",
    validate: int = 0,
    delete_if_invalid: int = 0,
):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    safe_prefix = _sanitize_storage_prefix(prefix, "uploads")
    filename = request.headers.get("x-filename") or request.query_params.get("filename") or "upload.bin"
    safe_name = _safe_storage_filename(filename, "upload.bin")
    content_type = _normalize_content_type(request.headers.get("content-type")) or _guess_response_content_type(safe_name)
    expected_size_raw = request.headers.get("x-file-size") or request.headers.get("content-length") or ""
    try:
        expected_size = max(0, int(str(expected_size_raw or "0").strip() or "0"))
    except Exception:
        expected_size = 0

    with tempfile.TemporaryDirectory(prefix="upload-local-stream-", dir=_preferred_tmpdir_root("upload")) as tmpdir:
        tmp_path = os.path.join(tmpdir, safe_name)
        sha256 = hashlib.sha256()
        written = 0
        try:
            with open(tmp_path, "wb") as f:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    f.write(chunk)
                    sha256.update(chunk)
                    written += len(chunk)
        except ClientDisconnect:
            return JSONResponse(
                {
                    "error": "client_disconnected",
                    "detail": "O upload foi interrompido antes de terminar. Tente novamente.",
                    "received_bytes": written,
                    "expected_bytes": expected_size,
                },
                status_code=499,
            )

        if written <= 0:
            return JSONResponse(
                {"error": "empty_upload", "detail": "O arquivo recebido está vazio."},
                status_code=400,
            )
        if expected_size > 0 and written != expected_size:
            return JSONResponse(
                {
                    "error": "upload_size_mismatch",
                    "detail": (
                        "O tamanho recebido não bate com o tamanho informado pelo navegador. "
                        f"Esperado: {expected_size} bytes; recebido: {written} bytes."
                    ),
                },
                status_code=400,
            )

        validation_result = None
        should_validate = bool(validate) and _looks_like_video_upload(filename=safe_name, content_type=content_type)
        if should_validate:
            validation_result = await asyncio.to_thread(
                _validate_video_path_sync,
                in_path=tmp_path,
                size_bytes=written,
                storage_path=tmp_path,
            )
            if not validation_result.get("ok"):
                return JSONResponse(
                    {
                        "error": "uploaded_media_invalid",
                        "detail": validation_result.get("detail") or "O vídeo enviado falhou na validação.",
                        "deleted": bool(delete_if_invalid),
                        "validation": validation_result,
                    },
                    status_code=422,
                )

        stored = await asyncio.to_thread(
            _store_local_path,
            src_path=tmp_path,
            prefix=safe_prefix,
            filename=safe_name,
            content_type=content_type,
        )
        return {
            "ok": True,
            **stored,
            "sha256": sha256.hexdigest(),
            "validation": validation_result,
        }


@app.api_route("/uploads/proxy", methods=["GET", "POST"])
async def upload_proxy(
    request: Request,
    file: Optional[UploadFile] = File(None),
    prefix: str = "uploads",
    validate: int = 0,
    delete_if_invalid: int = 0,
):
    if request.method == "GET":
        return {"ok": True, "message": "Proxy endpoint is alive (POST required for upload)"}
    
    if not file:
        return {"error": "missing_file"}
    
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    safe_prefix = _sanitize_storage_prefix(prefix, "uploads")
    safe_name = _safe_storage_filename(file.filename or "upload.bin", "upload.bin")
    content_type = _normalize_content_type(file.content_type) or _guess_response_content_type(safe_name)

    try:
        with tempfile.TemporaryDirectory(prefix="upload-proxy-", dir=_preferred_tmpdir_root("upload")) as tmpdir:
            tmp_path = os.path.join(tmpdir, safe_name)
            file_size = await asyncio.to_thread(_write_fileobj_to_path, file_obj=file.file, out_path=tmp_path)
            if file_size <= 0:
                return JSONResponse(
                    {"error": "empty_upload", "detail": "O arquivo recebido está vazio."},
                    status_code=400,
                )

            validation_result = None
            should_validate = bool(validate) and _looks_like_video_upload(
                filename=file.filename or "",
                content_type=content_type,
            )
            if should_validate:
                validation_result = await asyncio.to_thread(
                    _validate_video_path_sync,
                    in_path=tmp_path,
                    size_bytes=file_size,
                    storage_path=tmp_path,
                )
                if not validation_result.get("ok"):
                    return JSONResponse(
                        {
                            "error": "uploaded_media_invalid",
                            "detail": validation_result.get("detail") or "O vídeo enviado falhou na validação.",
                            "deleted": bool(delete_if_invalid),
                            "validation": validation_result,
                        },
                        status_code=422,
                    )

            stored = await asyncio.to_thread(
                _store_local_path,
                src_path=tmp_path,
                prefix=safe_prefix,
                filename=safe_name,
                content_type=content_type,
            )
            return {
                "ok": True,
                **stored,
                "validation": validation_result,
            }
    except Exception as e:
        return {"error": "upload_proxy_failed", "detail": str(e)}

@app.post("/transcribe")
async def transcribe(req: TranscribeRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    object_key = (req.video_object_key or "").strip()
    if not object_key:
        return {"error": "missing_video_object_key"}
    if not _is_valid_object_key(object_key):
        return {"error": "invalid_video_object_key"}

    provider = (req.provider or "auto").lower()
    lang = _norm_lang_code(req.language or "")
    if lang.lower() == "auto" or not lang:
        lang = ""
    translate_to = _norm_lang_code(req.translate_to or "")
    adult_mode = req.adult_mode is not False
    include_vocalizations = req.include_vocalizations is not False
    enhance_audio = req.enhance_audio is not False
    if adult_mode and not lang:
        # O fluxo real da plataforma é majoritariamente PT-BR. Deixar vazio
        # faz o Whisper alternar idioma ou retornar vazio em gemidos/fala baixa.
        lang = "pt"
    # Whisper "prompt"/faster-whisper "initial_prompt" is previous transcript
    # context, not a system instruction. Passing instructions here makes the
    # model repeat those instructions as subtitles, so we intentionally never
    # forward req.prompt to the transcription engine.

    with tempfile.TemporaryDirectory(prefix="metaporn-", dir=_preferred_tmpdir_root("transcribe")) as td:
        in_path      = os.path.join(td, "input")
        out_audio_wav = os.path.join(td, "audio.wav")
        out_audio_aac = os.path.join(td, "audio.m4a")

        try:
            await asyncio.to_thread(_download_media_ref_to_file, media_ref=object_key, out_path=in_path, s3=_s3_client())
        except Exception as e:
            return {"error": "storage_get_failed", "detail": _safe_error_detail(e, "unable_to_download_object")}

        probe = await asyncio.to_thread(_probe_metadata, in_path)

        # ── Monta lista de candidatos ───────────────────────────────────────
        # "auto" começa local/conservador, mas não pode morrer em transcrição
        # vazia: tenta Whisper Sync e OpenRouter como resgate explícito.
        if provider == "auto":
            configured_auto = [
                c.strip().lower()
                for c in str(os.environ.get("ADULT_META_TRANSCRIBE_AUTO_CANDIDATES", "")).split(",")
                if c.strip()
            ]
            candidates = configured_auto or ["local", "whisper_sync", "openrouter"]
        elif provider in ("whisper_sync", "deepgram", "assemblyai", "groq", "openrouter", "openai", "local", "premium"):
            candidates = [provider]
        else:
            candidates = ["local"]

        print(f"[transcribe] candidates={candidates} provider_req={provider}", flush=True)

        last_error: dict = {}
        tried: List[str] = []
        # Variáveis preenchidas pelo candidato vencedor
        raw_segments: List[Dict[str, Any]] = []
        txt = ""
        detected_lang = ""
        provider_used = ""
        provider_meta: Dict[str, Any] = {}

        for candidate in candidates:
            tried.append(candidate)
            print(f"[transcribe] trying {candidate}…", flush=True)

            # ── DEEPGRAM ──────────────────────────────────────────────────
            if candidate == "deepgram":
                deepgram_key_present = bool(
                    ((settings_get(key="token:deepgram") or {}).get("value") or os.environ.get("DEEPGRAM_API_KEY") or "").strip()
                )
                if not deepgram_key_present:
                    last_error = {"error": "missing_deepgram_token", "detail": "Configure token:deepgram em Settings"}
                    print("[transcribe] deepgram skipped: missing token", flush=True)
                    continue
                if not os.path.exists(out_audio_aac):
                    try:
                        await asyncio.to_thread(_extract_audio_to_aac, in_path=in_path, out_path=out_audio_aac, enhance_audio=enhance_audio)
                    except Exception as e:
                        detail = _safe_error_detail(e, "ffmpeg_failed")
                        if "missing_audio_stream" in detail:
                            return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                        last_error = {"error": "ffmpeg_failed", "detail": detail}
                        continue
                    try:
                        if os.path.getsize(out_audio_aac) == 0:
                            return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                    except OSError:
                        last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                        continue
                try:
                    result = await _transcribe_deepgram(out_audio_aac, lang or "pt", include_vocalizations=include_vocalizations)
                except Exception as e:
                    detail = _safe_error_detail(e, "deepgram_failed")
                    if "missing_deepgram_token" in detail:
                        last_error = {"error": "missing_deepgram_token", "detail": "Configure token:deepgram em Settings"}
                    else:
                        last_error = {"error": "deepgram_failed", "detail": detail}
                    print(f"[transcribe] deepgram failed: {detail}", flush=True)
                    continue
                txt = result.get("text", "").strip()
                if not txt:
                    last_error = {"error": "empty_transcript", "detail": "Deepgram retornou transcrição vazia."}
                    continue
                raw_segments = _segments_from_word_timestamps(result.get("segments") or [])
                detected_lang = lang or _norm_lang_code(result.get("language") or "pt")
                provider_used = f"deepgram_{result.get('model') or 'nova-2'}"
                provider_meta = {
                    "deepgram_model": result.get("model") or "nova-2",
                    "deepgram_request_id": result.get("request_id"),
                    "deepgram_duration": result.get("duration"),
                    "deepgram_word_count_raw": result.get("word_count_raw"),
                    "deepgram_word_count_kept": result.get("word_count_kept"),
                    "timing_quality": "word_timestamps",
                    "burn_safe": True,
                    "skip_llm_postprocess": True,
                    "timing_warning": "Deepgram retorna timestamps por palavra; pós-processamento LLM foi desativado para preservar texto exato.",
                }
                break

            # ── WHISPER SYNC (CPU, word timestamps, sem LLM) ─────────────
            if candidate == "whisper_sync":
                if not os.path.exists(out_audio_wav):
                    try:
                        await asyncio.to_thread(
                            _preprocess_audio_for_porn_br_transcription,
                            in_path=in_path,
                            out_path=out_audio_wav,
                            enhance_audio=enhance_audio,
                            premium=True,
                        )
                    except Exception as e:
                        detail = _safe_error_detail(e, "ffmpeg_failed")
                        if "missing_audio_stream" in detail:
                            return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                        last_error = {"error": "ffmpeg_failed", "detail": detail}
                        continue
                    try:
                        if os.path.getsize(out_audio_wav) == 0:
                            return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                    except OSError:
                        last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                        continue
                try:
                    result = await asyncio.to_thread(
                        _transcribe_premium,
                        out_audio_wav,
                        lang or "pt",
                        include_vocalizations=include_vocalizations,
                    )
                except Exception as e:
                    last_error = {"error": "whisper_sync_failed", "detail": _safe_error_detail(e, "whisper_sync_failed")}
                    print(f"[transcribe] whisper_sync failed: {e}", flush=True)
                    continue
                txt = result.get("text", "").strip()
                if not txt:
                    last_error = {"error": "empty_transcript", "detail": "Whisper Sync retornou transcrição vazia."}
                    continue
                raw_segments = _segments_from_word_timestamps(result.get("segments") or [])
                detected_lang = lang or _norm_lang_code(result.get("language") or "pt")
                provider_used = f"whisper_sync_{result.get('model') or _LOCAL_WHISPER_PREMIUM_MODEL}"
                provider_meta = {
                    "whisper_sync_model": result.get("model") or _premium_whisper_model_name or _LOCAL_WHISPER_PREMIUM_MODEL,
                    "whisper_sync_mode": result.get("premium_mode"),
                    "whisper_sync_quality": result.get("quality") or {},
                    "whisper_sync_attempts": result.get("attempts") or [],
                    "timing_quality": "whisper_word_timestamps",
                    "burn_safe": True,
                    "skip_llm_postprocess": True,
                    "timing_warning": "Whisper Sync usa timestamps por palavra e não aplica pós-processamento LLM.",
                }
                break

            # ── ASSEMBLYAI ──────────────────────────────────────────────────
            if candidate == "assemblyai":
                if not os.path.exists(out_audio_aac):
                    try:
                        await asyncio.to_thread(_extract_audio_to_aac, in_path=in_path, out_path=out_audio_aac, enhance_audio=enhance_audio)
                    except Exception as e:
                        detail = _safe_error_detail(e, "ffmpeg_failed")
                        if "missing_audio_stream" in detail:
                            return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                        last_error = {"error": "ffmpeg_failed", "detail": detail}
                        continue
                    try:
                        if os.path.getsize(out_audio_aac) == 0:
                            return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                    except OSError:
                        last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                        continue

                try:
                    result = await _transcribe_assemblyai(out_audio_aac, lang, include_vocalizations=include_vocalizations)
                except Exception as e:
                    detail = _safe_error_detail(e, "assemblyai_failed")
                    last_error = {"error": "assemblyai_failed", "detail": detail}
                    print(f"[transcribe] assemblyai failed: {detail}", flush=True)
                    continue
                txt = result.get("text", "").strip()
                if not txt:
                    last_error = {"error": "empty_transcript", "detail": "AssemblyAI retornou transcrição vazia."}
                    continue
                raw_segments = result.get("segments") or []
                detected_lang = lang or _norm_lang_code(result.get("language") or "auto")
                provider_used = "assemblyai"
                provider_meta = {
                    "assemblyai_transcript_id": result.get("transcript_id"),
                    "assemblyai_language_confidence": result.get("language_confidence"),
                    "assemblyai_speech_model": result.get("speech_model"),
                    "assemblyai_word_count_raw": result.get("word_count_raw"),
                    "assemblyai_word_count_kept": result.get("word_count_kept"),
                }
                break

            # ── LOCAL ──────────────────────────────────────────────────────
            if candidate == "local":
                if not os.path.exists(out_audio_wav):
                    try:
                        await asyncio.to_thread(_extract_audio_to_wav, in_path=in_path, out_path=out_audio_wav, enhance_audio=enhance_audio)
                    except Exception as e:
                        detail = _safe_error_detail(e, "ffmpeg_failed")
                        if "missing_audio_stream" in detail:
                            return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                        last_error = {"error": "ffmpeg_failed", "detail": detail}
                        continue
                    try:
                        if os.path.getsize(out_audio_wav) == 0:
                            return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                    except OSError:
                        last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                        continue
                try:
                    local_attempts = [
                        ("strict_vad", {"strict": True, "vad_filter": True}),
                        ("relaxed_vad", {"strict": False, "vad_filter": True}),
                        ("no_vad_rescue", {"strict": False, "vad_filter": False}),
                    ]
                    result = {"text": "", "segments": [], "language": lang or "pt", "local_attempt": ""}
                    local_errors: List[str] = []
                    for local_mode, local_opts in local_attempts:
                        attempt = await asyncio.to_thread(
                            _transcribe_local,
                            out_audio_wav,
                            lang or "pt",
                            strict=bool(local_opts["strict"]),
                            include_vocalizations=include_vocalizations,
                            vad_filter=bool(local_opts["vad_filter"]),
                        )
                        attempt["local_attempt"] = local_mode
                        if (attempt.get("text") or "").strip():
                            result = attempt
                            break
                        local_errors.append(local_mode)
                except Exception as e:
                    last_error = {"error": "local_whisper_failed", "detail": str(e)}
                    print(f"[transcribe] local failed: {e}", flush=True)
                    continue
                txt = result.get("text", "").strip()
                if not txt:
                    last_error = {
                        "error": "empty_transcript",
                        "detail": "Whisper local retornou transcrição vazia após tentativas strict_vad, relaxed_vad e no_vad_rescue.",
                        "attempts": local_errors,
                    }
                    continue
                raw_segments  = result.get("segments") or []
                detected_lang = lang or _norm_lang_code(result.get("language") or "auto")
                provider_used = f"faster_whisper_{_LOCAL_WHISPER_MODEL_SIZE}"
                provider_meta = {
                    "local_model": _LOCAL_WHISPER_MODEL_SIZE,
                    "local_attempt": result.get("local_attempt") or "",
                    "timing_quality": "segment_timestamps",
                }
                break

            # ── PREMIUM (large-v3) ─────────────────────────────────────────
            if candidate == "premium":
                if not os.path.exists(out_audio_wav):
                    try:
                        await asyncio.to_thread(
                            _preprocess_audio_for_porn_br_transcription,
                            in_path=in_path,
                            out_path=out_audio_wav,
                            enhance_audio=enhance_audio,
                            premium=True,
                        )
                    except Exception as e:
                        detail = _safe_error_detail(e, "ffmpeg_failed")
                        if "missing_audio_stream" in detail:
                            return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                        last_error = {"error": "ffmpeg_failed", "detail": detail}
                        continue
                    try:
                        if os.path.getsize(out_audio_wav) == 0:
                            return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                    except OSError:
                        last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                        continue
                try:
                    result = await asyncio.to_thread(
                        _transcribe_premium,
                        out_audio_wav,
                        lang,
                        include_vocalizations=include_vocalizations,
                    )
                except Exception as e:
                    last_error = {"error": "premium_whisper_failed", "detail": str(e)}
                    print(f"[transcribe] premium failed: {e}", flush=True)
                    continue
                txt = result.get("text", "").strip()
                if not txt:
                    last_error = {"error": "empty_transcript", "detail": "Whisper premium retornou transcrição vazia."}
                    continue
                raw_segments  = result.get("segments") or []
                detected_lang = lang or _norm_lang_code(result.get("language") or "auto")
                provider_used = f"faster_whisper_{result.get('model') or _LOCAL_WHISPER_PREMIUM_MODEL}"
                provider_meta = {
                    "premium_mode": result.get("premium_mode"),
                    "premium_model": result.get("model") or _premium_whisper_model_name or _LOCAL_WHISPER_PREMIUM_MODEL,
                    "premium_quality": result.get("quality") or {},
                    "premium_attempts": result.get("attempts") or [],
                }
                break

            # ── OPENROUTER STT / OPENAI ────────────────────────────────────
            else:
                if candidate in ("groq", "openrouter"):
                    if not os.path.exists(out_audio_wav):
                        try:
                            await asyncio.to_thread(_extract_audio_to_wav, in_path=in_path, out_path=out_audio_wav, enhance_audio=enhance_audio)
                        except Exception as e:
                            detail = _safe_error_detail(e, "ffmpeg_failed")
                            if "missing_audio_stream" in detail:
                                return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                            last_error = {"error": "ffmpeg_failed", "detail": detail}
                            continue
                        try:
                            if os.path.getsize(out_audio_wav) == 0:
                                return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                        except OSError:
                            last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                            continue
                    try:
                        result = await _transcribe_openrouter_stt(
                            out_audio_wav,
                            lang,
                            duration_seconds=float(probe.get("duration_seconds") or 0.0),
                        )
                    except Exception as e:
                        detail = _safe_error_detail(e, "openrouter_stt_failed")
                        if "missing_openrouter_token" in detail:
                            last_error = {"error": "missing_openrouter_token", "detail": "Configure token:openrouter em Settings"}
                        else:
                            last_error = {"error": "openrouter_stt_failed", "detail": detail}
                        print(f"[transcribe] openrouter stt failed: {detail}", flush=True)
                        continue
                    txt = result.get("text", "").strip()
                    if not txt:
                        last_error = {"error": "empty_transcript", "detail": "OpenRouter STT retornou transcrição vazia."}
                        continue
                    raw_segments = result.get("segments") or []
                    detected_lang = lang or _norm_lang_code(result.get("language") or "auto")
                    provider_used = "openrouter_stt"
                    provider_meta = {
                        "openrouter_stt_model": result.get("model"),
                        "openrouter_stt_chunks": result.get("chunks"),
                        "openrouter_stt_chunk_fail_count": result.get("chunk_fail_count"),
                        "openrouter_stt_chunk_empty_count": result.get("chunk_empty_count"),
                        "openrouter_stt_attempts": result.get("attempts"),
                        "timing_quality": result.get("timing_quality"),
                        "burn_safe": result.get("burn_safe"),
                        "timing_warning": result.get("timing_warning"),
                    }
                    break

                else:  # openai
                    # Extrai AAC 32kbps para respeitar o limite de 25MB da API OpenAI.
                    if not os.path.exists(out_audio_aac):
                        try:
                            await asyncio.to_thread(_extract_audio_to_aac, in_path=in_path, out_path=out_audio_aac, enhance_audio=enhance_audio)
                        except Exception as e:
                            detail = _safe_error_detail(e, "ffmpeg_failed")
                            if "missing_audio_stream" in detail:
                                return {"error": "missing_audio_stream", "detail": "O vídeo não possui faixa de áudio."}
                            last_error = {"error": "ffmpeg_failed", "detail": detail}
                            continue
                        try:
                            if os.path.getsize(out_audio_aac) == 0:
                                return {"error": "missing_audio_stream", "detail": "Áudio não encontrado ou arquivo vazio."}
                        except OSError:
                            last_error = {"error": "ffmpeg_failed", "detail": "Audio output not generated"}
                            continue
                    file_size_mb = os.path.getsize(out_audio_aac) / 1024 / 1024
                    if file_size_mb > 24.5:
                        last_error = {"error": "audio_too_large", "detail": f"Áudio {file_size_mb:.1f}MB > 25MB — pulando API, tente provider local."}
                        continue
                    saved    = settings_get(key="token:openai")
                    api_key  = (saved or {}).get("value")
                    if not api_key:
                        last_error = {"error": "missing_openai_token", "detail": "Configure token:openai em Settings"}
                        continue
                    whisper_url   = "https://api.openai.com/v1/audio/transcriptions"
                    whisper_model = "whisper-1"
                    provider_used = "openai_whisper"

                headers  = {"Authorization": f"Bearer {api_key}"}
                api_data = {"model": whisper_model, "response_format": "verbose_json"}
                if lang:
                    api_data["language"] = lang

                try:
                    timeout = httpx.Timeout(600.0, connect=20.0, write=120.0, read=600.0)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        with open(out_audio_aac, "rb") as f:
                            files = {"file": ("audio.m4a", f, "audio/mp4")}
                            r = await client.post(whisper_url, headers=headers, data=api_data, files=files)
                    if r.status_code >= 400:
                        err_detail = (r.text or "").strip()
                        try:
                            body = r.json()
                            err_detail = body.get("error", {}).get("message") or body.get("message") or err_detail
                        except Exception:
                            pass
                        last_error = {"error": "whisper_api_failed", "status_code": r.status_code, "detail": err_detail[:500]}
                        print(f"[transcribe] {candidate} HTTP {r.status_code}: {err_detail[:200]}", flush=True)
                        continue
                    j = r.json()
                except httpx.TimeoutException:
                    last_error = {"error": "whisper_timeout", "detail": f"{candidate} excedeu o tempo limite."}
                    print(f"[transcribe] {candidate} timeout", flush=True)
                    continue
                except Exception as e:
                    last_error = {"error": "whisper_failed", "detail": _safe_error_detail(e, "request_failed")}
                    print(f"[transcribe] {candidate} exception: {e}", flush=True)
                    continue

                txt = (j.get("text") or "").strip()
                if not txt:
                    last_error = {"error": "empty_transcript", "detail": f"{candidate} retornou transcrição vazia."}
                    continue
                raw_segments  = [
                    {"start": s.get("start", 0.0), "end": s.get("end", 0.0), "text": (s.get("text") or "").strip()}
                    for s in (j.get("segments") or [])
                ]
                detected_lang = lang or _norm_lang_code(j.get("language") or "auto")
                break

        else:
            # Todos os candidatos falharam
            print(f"[transcribe] all providers failed: {tried} last={last_error}", flush=True)
            err = last_error or {"error": "all_providers_failed"}
            err["detail"] = f"[tried: {', '.join(tried)}] " + (err.get("detail") or "todos os providers falharam")
            return err

        cleaned_segments, cleanup_meta = _clean_transcript_segments(raw_segments, lang, detected_lang)
        if cleanup_meta.get("removed_count"):
            print(f"[transcribe] cleanup removed={cleanup_meta}", flush=True)
        if raw_segments and not cleaned_segments:
            return {
                "error": "transcript_filtered",
                "detail": (
                    "A transcrição gerada parecia alucinada ou em idioma incorreto. "
                    "Selecione o idioma falado correto e tente novamente; se o trecho não tiver fala clara, o sistema não vai inventar legenda."
                ),
                "provider": provider_used,
                "cleanup": cleanup_meta,
                "adult_mode": adult_mode,
                "include_vocalizations": include_vocalizations,
                "enhance_audio": enhance_audio,
                "probe": probe,
            }
        raw_segments = cleaned_segments or raw_segments
        txt = " ".join((s.get("text") or "").strip() for s in raw_segments if (s.get("text") or "").strip()) or txt

        if adult_mode and _norm_lang_code(lang or detected_lang) == "pt" and not provider_meta.get("skip_llm_postprocess"):
            raw_segments, llm_meta = await _post_process_with_llm(
                raw_segments,
                expected_lang="pt",
                include_vocalizations=include_vocalizations,
                quality_meta=provider_meta.get("premium_quality") or {},
            )
            provider_meta["llm_postprocess"] = llm_meta
            print(
                "[transcribe] grok_postprocess "
                f"status={llm_meta.get('status')} "
                f"model={llm_meta.get('model') or '-'} "
                f"removed={llm_meta.get('removed_count', 0)} "
                f"changed={llm_meta.get('changed_count', 0)} "
                f"reason={llm_meta.get('reason') or '-'}",
                flush=True,
            )
            if llm_meta.get("status") == "ok":
                cleaned_after_llm, cleanup_after_llm = _clean_transcript_segments(raw_segments, "pt", detected_lang or "pt")
                cleanup_meta["llm_postprocess"] = cleanup_after_llm
                if cleaned_after_llm:
                    raw_segments = cleaned_after_llm
                txt = " ".join((s.get("text") or "").strip() for s in raw_segments if (s.get("text") or "").strip()) or txt

        print(f"[transcribe] success via {provider_used}", flush=True)

        # ── Tradução (opcional) ────────────────────────────────────────────
        final_segments = raw_segments
        final_text     = txt
        translated     = False
        if translate_to and translate_to != detected_lang:
            try:
                final_segments = await _translate_segments_llm(raw_segments, translate_to, detected_lang)
                final_text = " ".join((s.get("text") or "").strip() for s in final_segments if (s.get("text") or "").strip())
                translated = True
            except Exception as e:
                return {"error": "translation_failed", "detail": _safe_error_detail(e, "llm_translate_failed")}

        srt_content = _format_srt_premium(final_segments) if provider == "premium" else _format_srt(final_segments)
        return {
            "ok": True,
            "transcript": {
                "provider":      provider_used,
                "tried":         tried,
                "lang":          translate_to if translated else (detected_lang or "auto"),
                "source_lang":   detected_lang or "auto",
                "target_lang":   translate_to if translated else "",
                "translated":    translated,
                "text":          final_text or txt,
                "srt":           srt_content,
                "segments":      final_segments,
                "cleanup":       cleanup_meta,
                "provider_meta":  provider_meta,
                "timing_quality": provider_meta.get("timing_quality") or "real",
                "burn_safe":      False if provider_meta.get("burn_safe") is False else True,
                "timing_warning": provider_meta.get("timing_warning") or "",
                "adult_mode":    adult_mode,
                "include_vocalizations": include_vocalizations,
                "enhance_audio": enhance_audio,
            },
            "probe": probe,
        }


def _parse_srt_to_segments(srt_content: str) -> List[Dict[str, Any]]:
    """Converte texto SRT em lista de segmentos {start, end, text}."""
    def ts_to_secs(ts: str) -> float:
        h, m, rest = ts.split(":")
        s, ms = rest.replace(",", ".").split(".")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    segments: List[Dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", srt_content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        ts_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1]
        )
        if not ts_match:
            continue
        text = " ".join(l.strip() for l in lines[2:] if l.strip())
        if text:
            segments.append({
                "start": ts_to_secs(ts_match.group(1).replace(".", ",")),
                "end": ts_to_secs(ts_match.group(2).replace(".", ",")),
                "text": text,
            })
    return segments


def _srt_timing_diagnostics(srt_content: str, *, media_duration_seconds: float = 0.0) -> Dict[str, Any]:
    """Detecta SRT com timestamps estimados por bloco, impróprio para burn."""
    try:
        segments = _parse_srt_to_segments(srt_content)
    except Exception:
        segments = []
    if not segments:
        return {
            "segments_count": 0,
            "active_duration_seconds": 0.0,
            "coverage_ratio": 0.0,
            "large_gap_count": 0,
            "max_gap_seconds": 0.0,
            "chunk_boundary_hits": 0,
            "likely_synthetic_chunk_timing": False,
            "burn_safe": True,
        }

    ordered = sorted(segments, key=lambda s: float(s.get("start") or 0.0))
    active_duration = 0.0
    large_gaps: List[float] = []
    chunk_boundary_hits = 0
    prev_end = float(ordered[0].get("end") or ordered[0].get("start") or 0.0)
    first_start = float(ordered[0].get("start") or 0.0)
    span_end = prev_end

    for idx, seg in enumerate(ordered):
        start = float(seg.get("start") or 0.0)
        end = max(start, float(seg.get("end") or start))
        active_duration += max(0.0, end - start)
        span_end = max(span_end, end)
        if idx > 0:
            gap = max(0.0, start - prev_end)
            if gap >= 90.0:
                large_gaps.append(gap)
            if start >= 240.0:
                nearest_5min = round(start / 300.0) * 300.0
                if abs(start - nearest_5min) <= 2.0:
                    chunk_boundary_hits += 1
        prev_end = max(prev_end, end)

    ref_duration = max(float(media_duration_seconds or 0.0), span_end, 1.0)
    coverage_ratio = active_duration / ref_duration
    max_gap = max(large_gaps) if large_gaps else 0.0
    likely_synthetic = (
        len(ordered) >= 8
        and len(large_gaps) >= 2
        and max_gap >= 120.0
        and chunk_boundary_hits >= 2
        and coverage_ratio < 0.55
    )
    return {
        "segments_count": len(ordered),
        "first_start_seconds": round(first_start, 3),
        "span_end_seconds": round(span_end, 3),
        "active_duration_seconds": round(active_duration, 3),
        "media_duration_seconds": round(ref_duration, 3),
        "coverage_ratio": round(coverage_ratio, 4),
        "large_gap_count": len(large_gaps),
        "max_gap_seconds": round(max_gap, 3),
        "chunk_boundary_hits": chunk_boundary_hits,
        "likely_synthetic_chunk_timing": likely_synthetic,
        "burn_safe": not likely_synthetic,
    }


def _wrap_srt_for_burn(srt_content: str, *, max_chars_per_line: int = 42) -> str:
    """Quebra linhas longas antes do filtro subtitles/libass."""
    try:
        segments = _parse_srt_to_segments(srt_content)
    except Exception:
        segments = []
    if not segments:
        return srt_content
    wrapped: List[Dict[str, Any]] = []
    safe_width = max(26, min(int(max_chars_per_line or 42), 56))
    for seg in segments:
        raw = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        if not raw:
            continue
        lines = textwrap.wrap(
            raw,
            width=safe_width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        if len(lines) > 2:
            # Prefer two readable lines over one giant bottom banner.
            midpoint = max(1, len(lines) // 2)
            lines = [" ".join(lines[:midpoint]), " ".join(lines[midpoint:])]
            lines = [textwrap.shorten(line, width=72, placeholder="…") for line in lines]
        wrapped.append({
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "text": "\n".join(lines[:2]) if lines else raw,
        })
    return _format_srt(wrapped)


def _retime_synthetic_chunk_srt(
    srt_content: str,
    *,
    media_duration_seconds: float = 0.0,
    chunk_seconds: float = 300.0,
) -> str:
    """Reespalha cues comprimidas no começo de chunks grandes.

    Isso é usado para SRT criado a partir de texto puro do OpenRouter. Não cria
    timing perfeito, mas transforma um SRT visualmente inválido (texto preso no
    começo de cada bloco) em uma legenda queimável e revisável.
    """
    segments = sorted(_parse_srt_to_segments(srt_content), key=lambda s: float(s.get("start") or 0.0))
    if not segments:
        return srt_content

    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    prev_end = 0.0
    for seg in segments:
        start = float(seg.get("start") or 0.0)
        if current and (start - prev_end) >= 90.0:
            groups.append(current)
            current = []
        current.append(seg)
        prev_end = max(prev_end, float(seg.get("end") or start))
    if current:
        groups.append(current)
    if len(groups) <= 1:
        return srt_content

    media_duration = max(float(media_duration_seconds or 0.0), float(segments[-1].get("end") or 0.0), 1.0)
    chunk = max(60.0, float(chunk_seconds or 300.0))
    retimed: List[Dict[str, Any]] = []

    group_starts: List[float] = []
    for group in groups:
        first_start = float(group[0].get("start") or 0.0)
        # OpenRouter chunk starts are very close to multiples of 300s. Snap to
        # that window to remove the artificial 5-minute holes.
        snapped = round(first_start / chunk) * chunk if first_start >= chunk * 0.75 else 0.0
        if abs(first_start - snapped) > 45.0:
            snapped = max(0.0, (first_start // chunk) * chunk)
        group_starts.append(max(0.0, snapped))

    for idx, group in enumerate(groups):
        window_start = group_starts[idx]
        next_start = group_starts[idx + 1] if idx + 1 < len(group_starts) else media_duration
        window_end = max(window_start + 8.0, min(media_duration, next_start))
        if idx + 1 >= len(group_starts):
            window_end = max(window_end, min(media_duration, window_start + chunk))
        window = max(1.0, window_end - window_start)
        count = len(group)
        cue_duration = max(2.2, min(7.5, (window / max(count, 1)) * 0.45))
        usable = max(0.0, window - cue_duration)
        step = usable / max(count - 1, 1)
        for pos, seg in enumerate(group):
            start = window_start + (pos * step)
            end = min(window_end, start + cue_duration)
            retimed.append({
                "start": round(start, 3),
                "end": round(max(end, start + 1.2), 3),
                "text": str(seg.get("text") or "").strip(),
            })

    return _format_srt(retimed)


def _subtitle_gap_report(srt_content: str, *, media_duration_seconds: float = 0.0) -> Dict[str, Any]:
    segments = sorted(_parse_srt_to_segments(srt_content), key=lambda s: float(s.get("start") or 0.0))
    media_duration = max(float(media_duration_seconds or 0.0), float(segments[-1].get("end") or 0.0) if segments else 0.0)
    gaps: List[Dict[str, Any]] = []
    prev_end = 0.0
    for seg in segments:
        start = float(seg.get("start") or 0.0)
        if start - prev_end >= 120.0:
            gaps.append({
                "start": round(prev_end, 3),
                "end": round(start, 3),
                "duration": round(start - prev_end, 3),
            })
        prev_end = max(prev_end, float(seg.get("end") or start))
    if media_duration and media_duration - prev_end >= 120.0:
        gaps.append({
            "start": round(prev_end, 3),
            "end": round(media_duration, 3),
            "duration": round(media_duration - prev_end, 3),
        })
    active = sum(max(0.0, float(s.get("end") or 0.0) - float(s.get("start") or 0.0)) for s in segments)
    longest_gap = max((g["duration"] for g in gaps), default=0.0)
    return {
        "segments_count": len(segments),
        "media_duration_seconds": round(media_duration, 3),
        "first_start_seconds": round(float(segments[0].get("start") or 0.0), 3) if segments else 0.0,
        "last_end_seconds": round(float(segments[-1].get("end") or 0.0), 3) if segments else 0.0,
        "active_subtitle_seconds": round(active, 3),
        "gap_count_over_120s": len(gaps),
        "longest_gap_seconds": round(float(longest_gap), 3),
        "large_gaps": gaps[:20],
        "has_suspicious_missing_range": bool(longest_gap >= 600.0),
    }


def _slice_srt_to_window(srt_content: str, *, start_seconds: float, duration_seconds: float) -> str:
    """Mantém só cues que cruzam a janela de preview e desloca para 00:00."""
    if not srt_content:
        return ""
    window_start = max(0.0, float(start_seconds or 0.0))
    window_end = window_start + max(0.1, float(duration_seconds or 0.0))
    out: List[Dict[str, Any]] = []
    for seg in _parse_srt_to_segments(srt_content):
        start = float(seg.get("start") or 0.0)
        end = max(start, float(seg.get("end") or start))
        if end <= window_start or start >= window_end:
            continue
        shifted_start = max(0.0, start - window_start)
        shifted_end = min(window_end - window_start, end - window_start)
        if shifted_end - shifted_start < 0.05:
            continue
        out.append({
            "start": round(shifted_start, 3),
            "end": round(shifted_end, 3),
            "text": str(seg.get("text") or "").strip(),
        })
    return _format_srt(out)


def _format_gap_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _burn_body_srt_and_media(
    *,
    body: Dict[str, Any],
    req_data: Dict[str, Any],
) -> tuple[str, str]:
    object_key = str(body.get("video_object_key") or req_data.get("video_object_key") or req_data.get("object_key") or "").strip()
    srt_content = str(body.get("srt_content") or "").strip()
    if not srt_content:
        transcript = req_data.get("transcript") or {}
        if isinstance(transcript, dict):
            srt_content = str(transcript.get("srt") or "").strip()
            if not srt_content:
                srt_content = _format_srt(transcript.get("segments") or [])
    return object_key, srt_content


def _burn_preview_logo_payload(body: Dict[str, Any], req_data: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]], float, float, float, float]:
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    logo_b64 = str(body.get("logo_b64") or "").strip()
    logos: List[Dict[str, Any]] = []
    raw_logos = body.get("logos")
    if isinstance(raw_logos, list):
        for raw in raw_logos[:MAX_LOGO_OVERLAYS]:
            if isinstance(raw, dict) and raw.get("enabled") is not False and str(raw.get("b64") or raw.get("logo_b64") or raw.get("src") or "").strip():
                logos.append(dict(raw))

    def _num(value: Any, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(float(value), hi))
        except Exception:
            return default

    logo_x = _num(body.get("logo_x", wizard_state.get("logo_x", 97.0)), 97.0, 0.0, 100.0)
    logo_y = _num(body.get("logo_y", wizard_state.get("logo_y", 97.0)), 97.0, 0.0, 100.0)
    logo_scale_pct = _num(body.get("logo_scale_pct", wizard_state.get("logo_scale_pct", 20.0)), 20.0, 5.0, 100.0)
    logo_opacity = _num(body.get("logo_opacity", wizard_state.get("logo_opacity", 85.0)), 85.0, 5.0, 100.0)

    profile_id = str(body.get("logo_profile_id") or wizard_state.get("logo_profile_id") or "").strip()
    profile_name = str(body.get("logo_profile_name") or wizard_state.get("logo_profile_name") or "").strip()
    layout_linked = _coerce_optional_bool(body.get("logo_profile_layout_linked"))
    if layout_linked is None:
        layout_linked = _coerce_optional_bool(wizard_state.get("logo_profile_layout_linked"))
    if not logos and (profile_id or profile_name):
        profile = _find_logo_profile(profile_id=profile_id, company_name=profile_name)
        if profile:
            logos = _logo_profile_to_payload_logos(profile)
            overrides = body.get("logo_position_overrides") or []
            for i, ov in enumerate(overrides[:len(logos)]):
                if isinstance(ov, dict):
                    if ov.get("x") is not None:
                        logos[i]["x"] = _num(ov.get("x"), logos[i].get("x", logo_x), 0.0, 100.0)
                    if ov.get("y") is not None:
                        logos[i]["y"] = _num(ov.get("y"), logos[i].get("y", logo_y), 0.0, 100.0)
                    if ov.get("scale_pct") is not None:
                        logos[i]["scale_pct"] = _num(ov.get("scale_pct"), logos[i].get("scale_pct", logo_scale_pct), 5.0, 100.0)
                    if ov.get("opacity") is not None:
                        logos[i]["opacity"] = _num(ov.get("opacity"), logos[i].get("opacity", logo_opacity), 5.0, 100.0)
            if layout_linked is False and not overrides and logos:
                logos[0]["x"] = logo_x
                logos[0]["y"] = logo_y
                logos[0]["scale_pct"] = logo_scale_pct
                logos[0]["opacity"] = logo_opacity
            if logos:
                first = logos[0]
                logo_b64 = str(first.get("b64") or logo_b64)
                logo_x = _num(first.get("x"), logo_x, 0.0, 100.0)
                logo_y = _num(first.get("y"), logo_y, 0.0, 100.0)
                logo_scale_pct = _num(first.get("scale_pct"), logo_scale_pct, 5.0, 100.0)
                logo_opacity = _num(first.get("opacity"), logo_opacity, 5.0, 100.0)
            elif not logo_b64:
                ref = str(profile.get("logo_object_key") or "").strip()
                if ref:
                    logo_b64 = _media_ref_to_data_url(ref)
    return logo_b64, logos, logo_x, logo_y, logo_scale_pct, logo_opacity


@app.post("/api/burn-subtitles/diagnose")
async def burn_subtitles_diagnose(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return JSONResponse({"error": "missing_run_id"}, status_code=400)
    r = get_run(run_id)
    if not r:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    try:
        req_data = json.loads(r["request_json"]) if isinstance(r["request_json"], str) else (r.get("request_json") or {})
    except Exception as exc:
        return JSONResponse({"error": "parse_error", "detail": str(exc)}, status_code=500)
    object_key, srt_content = _burn_body_srt_and_media(body=body, req_data=req_data)
    if not srt_content:
        return JSONResponse({"error": "no_transcript", "detail": "Não há SRT para diagnosticar."}, status_code=400)
    duration = 0.0
    try:
        if object_key:
            if _is_local_media_ref(object_key):
                duration = _probe_duration(_local_media_abs_path_from_ref(object_key))
            else:
                with tempfile.TemporaryDirectory(prefix="subtitle-diag-", dir=_preferred_tmpdir_root("system")) as tmpdir:
                    in_path = os.path.join(tmpdir, "input_video")
                    await asyncio.to_thread(_download_media_ref_to_file, media_ref=object_key, out_path=in_path, s3=_s3_client())
                    duration = _probe_duration(in_path)
    except Exception:
        duration = 0.0
    timing = _srt_timing_diagnostics(srt_content, media_duration_seconds=duration)
    gaps = _subtitle_gap_report(srt_content, media_duration_seconds=duration)
    warnings: List[str] = []
    if gaps.get("has_suspicious_missing_range"):
        g = max(gaps.get("large_gaps") or [], key=lambda item: item.get("duration", 0), default={})
        warnings.append(
            f"Legenda tem um buraco grande de {_format_gap_clock(g.get('duration', 0))} "
            f"entre {_format_gap_clock(g.get('start', 0))} e {_format_gap_clock(g.get('end', 0))}."
        )
    if timing.get("likely_synthetic_chunk_timing"):
        warnings.append("Legenda parece ter timestamps sintéticos por chunks; será reespalhada antes do burn.")
    return {
        "ok": True,
        "run_id": run_id,
        "object_key": object_key,
        "timing": timing,
        "coverage": gaps,
        "warnings": warnings,
    }


@app.post("/api/burn-subtitles/preview")
async def burn_subtitles_preview(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return JSONResponse({"error": "missing_run_id"}, status_code=400)
    r = get_run(run_id)
    if not r:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    try:
        req_data = json.loads(r["request_json"]) if isinstance(r["request_json"], str) else (r.get("request_json") or {})
    except Exception as exc:
        return JSONResponse({"error": "parse_error", "detail": str(exc)}, status_code=500)

    object_key, srt_content = _burn_body_srt_and_media(body=body, req_data=req_data)
    if not object_key:
        return JSONResponse({"error": "no_video", "detail": "Vídeo fonte não encontrado no run."}, status_code=400)
    skip_subtitles = bool(body.get("skip_subtitles", False))
    if not skip_subtitles and not srt_content:
        return JSONResponse({"error": "no_transcript", "detail": "Não há SRT para prévia."}, status_code=400)

    try:
        start_seconds = max(0.0, float(body.get("timestamp") if body.get("timestamp") is not None else body.get("start_seconds") or 0.0))
    except Exception:
        start_seconds = 0.0
    try:
        preview_duration = max(10.0, min(float(body.get("duration_seconds") or 60.0), 180.0))
    except Exception:
        preview_duration = 60.0

    logo_b64, logos, logo_x, logo_y, logo_scale_pct, logo_opacity = _burn_preview_logo_payload(body, req_data)
    font_size = max(6, min(int(body.get("font_size") or 22), 72))
    font_color = str(body.get("font_color") or "white").strip().lower()
    sub_delay_secs = float(body.get("sub_delay_secs") or 0.0)
    s3 = _s3_client()

    try:
        with tempfile.TemporaryDirectory(prefix="burn-preview-", dir=_preferred_tmpdir_root("burn")) as tmpdir:
            if _is_local_media_ref(object_key):
                in_path = _local_media_abs_path_from_ref(object_key)
            else:
                in_path = os.path.join(tmpdir, "input_video")
                await asyncio.to_thread(_download_media_ref_to_file, media_ref=object_key, out_path=in_path, s3=s3)
            srt_path = os.path.join(tmpdir, "preview.srt")
            out_path = os.path.join(tmpdir, "preview.mp4")
            duration = await asyncio.to_thread(_probe_duration, in_path)
            if duration > 0:
                start_seconds = min(start_seconds, max(0.0, duration - 2.0))
                preview_duration = min(preview_duration, max(1.0, duration - start_seconds))

            timing_before = _srt_timing_diagnostics(srt_content, media_duration_seconds=duration) if srt_content else {}
            if srt_content and timing_before.get("likely_synthetic_chunk_timing"):
                srt_content = _retime_synthetic_chunk_srt(srt_content, media_duration_seconds=duration)
            if srt_content and sub_delay_secs:
                srt_content = _shift_srt(srt_content, sub_delay_secs)
            if srt_content:
                srt_content = _slice_srt_to_window(
                    srt_content,
                    start_seconds=start_seconds,
                    duration_seconds=preview_duration,
                )
                srt_content = _wrap_srt_for_burn(srt_content)
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content or "")

            logo_specs = _write_logo_overlay_specs(
                raw_logos=logos if logos else None,
                legacy_logo_b64=logo_b64,
                tmpdir=tmpdir,
                legacy_x=logo_x,
                legacy_y=logo_y,
                legacy_scale_pct=logo_scale_pct,
                legacy_opacity=logo_opacity,
            )
            video_sar = _probe_video_sar(in_path)
            color_map = {
                "white": "&H00FFFFFF",
                "yellow": "&H0000FFFF",
                "cyan": "&H00FFFF00",
                "orange": "&H000080FF",
                "black": "&H00000000",
            }
            sub_style = (
                f"FontName=Arial,FontSize={font_size},"
                f"PrimaryColour={color_map.get(font_color, '&H00FFFFFF')},"
                "OutlineColour=&H00000000,Bold=1,Outline=2,Shadow=1"
            )
            scale_filter = "scale=-2:min(ih\\,720),fps=30"

            if logo_specs:
                parts: List[str] = [f"[0:v]{scale_filter}[vbase]"]
                current_label = "[vbase]"
                if not skip_subtitles and srt_content:
                    parts.append(f"{current_label}subtitles={srt_path}:charenc=utf-8:force_style='{sub_style}'[vsub]")
                    current_label = "[vsub]"
                for idx, spec in enumerate(logo_specs):
                    input_idx = idx + 1
                    logo_scaled_label = f"p_lgs{idx}"
                    base_label = f"p_lb{idx}"
                    logo_label = f"p_lg{idx}"
                    out_label = f"p_vlogo{idx}"
                    scale_ratio = max(0.05, min(float(spec.get("scale_pct", 20.0)) / 100.0, 1.0))
                    _append_logo_aspect_locked_scale(
                        parts,
                        input_idx=input_idx,
                        base_ref=current_label,
                        logo_scaled_label=logo_scaled_label,
                        base_label=base_label,
                        scale_ratio=scale_ratio,
                        tag=f"preview_logo_{idx}",
                        video_sar=video_sar,
                    )
                    alpha_ratio = max(0.05, min(float(spec.get("opacity", 85.0)) / 100.0, 1.0))
                    parts.append(f"[{logo_scaled_label}]format=rgba,setsar=1,colorchannelmixer=aa={alpha_ratio:.3f}[{logo_label}]")
                    x = max(0.0, min(float(spec.get("x", 97.0)), 100.0))
                    y = max(0.0, min(float(spec.get("y", 97.0)), 100.0))
                    parts.append(f"[{base_label}][{logo_label}]overlay=(W-w)*{x:.4f}/100:(H-h)*{y:.4f}/100:eof_action=repeat:shortest=1[{out_label}]")
                    current_label = f"[{out_label}]"
                parts.append(f"{current_label}format=yuv420p[out]")
                logo_args: List[str] = []
                for spec in logo_specs:
                    if bool(spec.get("is_gif")):
                        logo_args.extend(["-stream_loop", "-1", "-ignore_loop", "0", "-i", str(spec.get("path"))])
                    else:
                        logo_args.extend(["-loop", "1", "-i", str(spec.get("path"))])
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{start_seconds:.3f}", "-i", in_path,
                    *logo_args,
                    "-t", f"{preview_duration:.3f}",
                    "-filter_complex", ";".join(parts),
                    "-map", "[out]", "-map", "0:a?",
                    "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
                    "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart",
                    out_path,
                ]
            else:
                vf = scale_filter
                if not skip_subtitles and srt_content:
                    vf += f",subtitles={srt_path}:charenc=utf-8:force_style='{sub_style}'"
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{start_seconds:.3f}", "-i", in_path,
                    "-t", f"{preview_duration:.3f}",
                    "-vf", vf,
                    "-map", "0:v:0", "-map", "0:a?",
                    "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
                    "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart",
                    out_path,
                ]
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=360)
            if proc.returncode != 0 or not os.path.exists(out_path):
                return JSONResponse({"error": "preview_ffmpeg_failed", "detail": (proc.stderr or proc.stdout or "")[-1200:]}, status_code=500)
            stored = await asyncio.to_thread(
                _store_local_path,
                src_path=out_path,
                prefix=f"previews/burn/{run_id[:8]}",
                filename=f"preview_{run_id[:8]}_{int(start_seconds)}s.mp4",
                content_type="video/mp4",
            )
            final_srt = srt_content or ""
            return {
                "ok": True,
                "object_key": stored.get("object_key"),
                "video_url": stored.get("public_url"),
                "start_seconds": round(start_seconds, 3),
                "duration_seconds": round(preview_duration, 3),
                "diagnostics": {
                    "before": timing_before,
                    "coverage": _subtitle_gap_report(final_srt, media_duration_seconds=preview_duration),
                },
            }
    except Exception as exc:
        return JSONResponse({"error": "preview_failed", "detail": _safe_error_detail(exc, "preview_failed")}, status_code=500)


@app.post("/api/translate-srt")
async def translate_srt(request: Request):
    """Traduz um SRT existente para o idioma alvo usando Google Translate."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    srt = (body.get("srt") or "").strip()
    target_lang = _norm_lang_code(body.get("target_lang") or "")

    if not srt:
        return JSONResponse({"error": "missing_srt"}, status_code=400)
    if not target_lang:
        return JSONResponse({"error": "missing_target_lang"}, status_code=400)

    segments = _parse_srt_to_segments(srt)
    if not segments:
        return JSONResponse({"error": "no_segments_parsed", "detail": "Não foi possível interpretar o SRT."}, status_code=400)

    try:
        translated = await _translate_segments_llm(segments, target_lang)
        translated_srt = _format_srt(translated)
        return {"ok": True, "srt": translated_srt, "segments_count": len(translated)}
    except Exception as e:
        return JSONResponse({"error": "translation_failed", "detail": _safe_error_detail(e, "llm_translate_failed")}, status_code=500)


_VISION_MODEL_CANDIDATES_DEFAULT = [
    "grok-2-vision-latest",   # novo / recomendado primeiro
    "grok-2-vision-1212",
    "grok-4",                  # grok-4 tem suporte a visão
    "grok-4-fast",
    "grok-2-vision",
    "grok-vision-beta",
]

# Fallback OpenRouter: tenta Grok primeiro, depois DeepSeek (melhor com conteúdo adulto)
_OPENROUTER_VISION_MODELS = [
    "x-ai/grok-2-vision-1212",
    "x-ai/grok-vision-beta",
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "anthropic/claude-3-haiku",
    "meta-llama/llama-3.2-90b-vision-instruct",
]


def _vision_model_candidates() -> List[str]:
    out: List[str] = []
    cfg = (settings_get(key="vision:model") or {}).get("value")
    env_model = os.getenv("XAI_VISION_MODEL", "").strip()

    def _push(v: str) -> None:
        vv = (v or "").strip()
        if not vv or vv in out:
            return
        out.append(vv)

    if cfg and str(cfg).strip().lower() not in {"", "auto", "default"}:
        _push(str(cfg))
    if env_model and env_model.lower() not in {"auto", "default"}:
        _push(env_model)
    for m in _VISION_MODEL_CANDIDATES_DEFAULT:
        _push(m)
    return out


def _is_model_access_or_availability_error(status_code: int, detail: str) -> bool:
    """Retorna True se o erro indica modelo indisponível/sem acesso — deve pular para próximo."""
    txt = (detail or "").lower()
    if status_code not in {400, 404}:
        return False
    keys = [
        "does not exist",
        "does not have access",
        "requested entity was not found",
        "model not found",
        "unknown model",
        "does not support image",
        "image inputs are not supported",
        "image input",
        "image_url",
        "invalid argument",
        "not supported by this model",
        "no such model",
        "model is not available",
        "model_not_found",
        "not found",
        "no endpoints found",
        "no endpoint",
        "endpoint not found",
    ]
    return any(k in txt for k in keys)


async def _openrouter_vision_chat_json(
    *,
    api_key: str,
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Tenta modelos xAI e DeepSeek via OpenRouter até um funcionar."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://caripost.n8nmikael.com.br",
        "X-Title": "MetaPorn Vision",
    }
    attempts: List[Dict[str, Any]] = []

    for model in _OPENROUTER_VISION_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=payload)
            if r.status_code < 400:
                raw = r.json()
                content = (((raw.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "{}"
                parsed = json.loads(content)
                parsed["_model_used"] = model
                parsed["_provider"] = "openrouter"
                if attempts:
                    parsed["_model_attempts"] = attempts
                return parsed

            detail = (r.text or "").strip()[:700]
            attempts.append({"model": model, "status": r.status_code, "detail": detail[:260], "provider": "openrouter"})
            if _is_model_access_or_availability_error(r.status_code, detail):
                continue
            return {
                "_api_error": r.status_code,
                "_detail": detail,
                "_model_used": model,
                "_provider": "openrouter",
                "_model_attempts": attempts,
            }
        except Exception as ex:
            detail = repr(ex)
            attempts.append({"model": model, "status": 0, "detail": detail[:260], "provider": "openrouter"})
            continue  # tenta próximo modelo mesmo em exceção de rede

    return {
        "_api_error": 404,
        "_detail": "Nenhum modelo OpenRouter acessível para vision. Verifique token:openrouter.",
        "_provider": "openrouter",
        "_model_attempts": attempts,
    }


async def _xai_vision_chat_json(
    *,
    api_key: str,
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    attempts: List[Dict[str, Any]] = []

    for model in _vision_model_candidates():
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=payload)
            if r.status_code < 400:
                raw = r.json()
                content = (((raw.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "{}"
                parsed = json.loads(content)
                parsed["_model_used"] = model
                if attempts:
                    parsed["_model_attempts"] = attempts
                return parsed

            detail = (r.text or "").strip()[:700]
            attempts.append({"model": model, "status": r.status_code, "detail": detail[:260]})
            if _is_model_access_or_availability_error(r.status_code, detail):
                continue
            return {
                "_api_error": r.status_code,
                "_detail": detail,
                "_model_used": model,
                "_model_attempts": attempts,
            }
        except Exception as ex:
            detail = repr(ex)
            attempts.append({"model": model, "status": 0, "detail": detail[:260]})
            return {
                "_exception": detail,
                "_model_used": model,
                "_model_attempts": attempts,
            }

    return {
        "_api_error": 404,
        "_detail": "No accessible xAI vision model found for this token. Configure vision:model or update token:grok.",
        "_model_attempts": attempts,
    }


async def _analyze_multiple_frames(frames: List[str]) -> Optional[Dict[str, Any]]:
    # Prefer OpenRouter; fall back to xAI direct if no OpenRouter token
    or_saved = settings_get(key="token:openrouter")
    or_key = (or_saved or {}).get("value")
    xai_saved = settings_get(key="token:grok")
    xai_key = (xai_saved or {}).get("value")
    if not or_key and not xai_key:
        return None

    content = [
        {
            "type": "text",
            "text": (
                f"Analise estes {len(frames)} frames extraídos em pontos de mudança de cena de um vídeo. "
                "Forneça uma análise consolidada de conteúdo para otimização em redes sociais (títulos, descrição, thumbnail, SEO)."
            ),
        }
    ]
    for b64 in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    messages = [
        {
            "role": "system",
            "content": (
                "Você é um analista de conteúdo de vídeo para redes sociais (YouTube, Instagram, TikTok). "
                "Analise os frames com precisão: descreva objetivamente cena, ambiente, pessoas/objetos, ações, "
                "texto na tela, estética e clima. NÃO invente nada, NÃO suponha o que não está visível. "
                "Conteúdo mainstream — sem linguagem adulta/sexual.\n\n"
                "Responda SOMENTE em JSON com exatamente estas chaves:\n"
                "- 'description': string pt-BR (3-5 frases) resumindo o vídeo e seu apelo de conteúdo\n"
                "- 'scenes': lista de objetos {frame_index, description, on_screen_text} descrevendo cada cena\n"
                "- 'tags': lista de 20-30 tags em inglês para SEO/descoberta (tema, nicho, formato, elementos visuais)\n"
                "- 'categories': lista de 5-10 categorias mainstream (ex: vlog, tutorial, comédia, lifestyle, fitness, beauty, gaming, food, travel, music)\n"
                "- 'hooks': lista de 2-3 ganchos curtos de abertura sugeridos\n"
                "- 'confidence': float 0.0-1.0 indicando confiança na análise"
            )
        },
        {
            "role": "user",
            "content": content
        }
    ]

    # 1ª tentativa: OpenRouter com Grok vision
    if or_key:
        result = await _openrouter_vision_chat_json(api_key=or_key, messages=messages)
    else:
        result = {"_api_error": 503, "_detail": "no_openrouter_key"}

    # Fallback: xAI direto se OpenRouter falhar
    if (result.get("_api_error") or result.get("_exception")) and xai_key:
        r2 = await _xai_vision_chat_json(api_key=xai_key, messages=messages)
        if not r2.get("_api_error") and not r2.get("_exception"):
            r2["_or_attempts"] = result.get("_model_attempts") or []
            result = r2

    # Check if the model refused (returns refusal message instead of JSON keys)
    if "description" not in result and "tags" not in result and not result.get("_api_error") and not result.get("_exception"):
        return {"_refused": True, "_raw": result}
    return result


@app.post("/api/screenshot/analyze")
async def screenshot_analyze(req: ScreenshotAnalyzeRequest, request: Request):

    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    or_saved = settings_get(key="token:openrouter")
    or_key = (or_saved or {}).get("value")
    xai_saved = settings_get(key="token:grok")
    xai_key = (xai_saved or {}).get("value")
    if not or_key and not xai_key:
        return {"error": "missing_vision_token", "detail": "Configure token:openrouter ou token:grok em Settings para usar Visão IA"}

    img_data = req.image_base64
    if "," in img_data:
        img_data = img_data.split(",", 1)[1]

    messages = [
        {
            "role": "system",
            "content": (
                "Você é um analista de conteúdo de vídeo para redes sociais. "
                "Analise a imagem objetivamente: descreva cena, ambiente, pessoas/objetos, ações, texto na tela, "
                "estética e clima. NÃO invente nada, NÃO suponha o que não está visível. Conteúdo mainstream, sem linguagem adulta.\n\n"
                "Responda SOMENTE em JSON com:\n"
                "- 'description' (pt-BR, 2-4 frases: o que aparece, ambiente, ações e apelo de conteúdo)\n"
                "- 'tags' (20-25 tags em inglês: tema, nicho, formato, elementos visuais)\n"
                "- 'categories' (lista de 5 categorias mainstream)\n"
                "- 'confidence' (0.0-1.0)"
            )
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analise esta imagem:"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}}
            ]
        }
    ]

    try:
        if or_key:
            result = await _openrouter_vision_chat_json(api_key=or_key, messages=messages)
        else:
            result = {"_api_error": 503, "_detail": "no_openrouter_key"}

        if (result.get("_api_error") or result.get("_exception")) and xai_key:
            r2 = await _xai_vision_chat_json(api_key=xai_key, messages=messages)
            if not r2.get("_api_error") and not r2.get("_exception"):
                r2["_or_attempts"] = result.get("_model_attempts") or []
                result = r2

        if result.get("_api_error"):
            return {
                "error": "vision_api_failed",
                "status_code": result.get("_api_error"),
                "detail": str(result.get("_detail") or "")[:500],
                "model_used": result.get("_model_used"),
                "provider": result.get("_provider", "xai"),
                "model_attempts": result.get("_model_attempts") or [],
            }
        if result.get("_exception"):
            return {"error": "screenshot_analyze_failed", "detail": result.get("_exception")}
        return result
    except Exception as e:
        return {"error": "screenshot_analyze_failed", "detail": str(e)}



@app.get("/api/vision-diagnostic")
async def vision_diagnostic(request: Request):
    """Diagnóstico xAI Vision API — testa cada modelo e retorna raw HTTP responses para suporte."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    # Pixel transparente 1x1 PNG — teste mínimo sem custo
    PIXEL_B64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    test_messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "Describe this image in one word. Respond with JSON: {\"word\": \"...\"}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PIXEL_B64}"}}
        ]}
    ]

    grok_saved = settings_get(key="token:grok")
    grok_key = (grok_saved or {}).get("value")

    if not grok_key:
        return {"error": "token_not_configured", "detail": "Configure token:grok em Settings primeiro."}

    token_prefix = grok_key[:8] + "..." + grok_key[-4:]
    candidates = _vision_model_candidates()
    results = []

    for model in candidates:
        payload = {"model": model, "messages": test_messages, "max_tokens": 30}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            try:
                body = r.json()
            except Exception:
                body = {"raw_text": r.text[:400]}
            results.append({
                "model": model,
                "status_code": r.status_code,
                "success": r.status_code < 400,
                "response_body": body,
            })
        except Exception as ex:
            results.append({"model": model, "status_code": 0, "success": False, "error": repr(ex)})

    any_success = any(r["success"] for r in results)

    if any_success:
        status = "OK"
        recommendation = "Vision API funcionando — pelo menos um modelo respondeu com sucesso."
    else:
        status = "FALHOU"
        first_error = next((r for r in results if not r["success"]), {})
        sc = first_error.get("status_code", 0)
        body = first_error.get("response_body", {})
        err_msg = (body.get("error") or {})
        if isinstance(err_msg, dict):
            err_msg = err_msg.get("message") or str(err_msg)
        recommendation = (
            f"Todos os modelos retornaram erro. "
            f"Primeiro erro: HTTP {sc} — {err_msg or body}. "
            f"Copie o JSON completo abaixo e envie ao suporte xAI: https://x.ai/support"
        )

    return {
        "status": status,
        "token_prefix": token_prefix,
        "models_tested": candidates,
        "results": results,
        "any_success": any_success,
        "recommendation": recommendation,
    }


_CREATE_POST_SYSTEM = (
    "Você é o maior especialista em criação de posts adultos para XVideos. "
    "Sua missão é transformar um vídeo analisado em um post que explode em views.\n\n"
    "Dados que vão chegar (JSON):\n"
    "- video_id, frames_count\n"
    "- vision_analysis (description, tags, performers, scenes com frame_index)\n"
    "- metadata_prompt (resumo do prompt de metadata gerado)\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. Recomende EXATAMENTE 1 thumbnail (o frame_index mais impactante). "
    "Critérios: ação explícita visível, melhor iluminação, ângulo frontal, expressão facial safada.\n"
    "2. Gere:\n"
    "   - Título otimizado (pt-BR, máximo 100 caracteres, bem clickbait e putão)\n"
    "   - Descrição completa (180-280 palavras, ordem cronológica, super explícita, termine com tags)\n"
    "   - 40 tags (30 principais + 10 long-tail)\n"
    "   - Categoria principal + 3 subcategorias\n"
    "   - Hook dos primeiros 10s\n"
    "3. Thumbnail: recomende frame_index + prompt pronto de edição para adicionar logo "
    "(canto inferior direito, 20% tamanho, opacidade 85%)\n"
    "4. Responda SOMENTE em JSON:\n"
    '{"recommended_thumbnail":{"frame_index":3,"reason":"...","edit_prompt":"..."},'
    '"post_data":{"title":"...","description":"...","tags":["..."],'
    '"categories":["creampie","anal","latina"],"first_10s_hook":"..."},'
    '"ready_to_post":"Texto completo pronto pra copiar no XVideos"}'
)


class CreatePostRequest(BaseModel):
    video_id: str
    logo_base64: Optional[str] = None


class SchedulePostRequest(BaseModel):
    run_id: str
    post_data: Dict[str, Any]
    schedule_at: Optional[str] = None


class UpdateScheduledPostRequest(BaseModel):
    status: str


@app.post("/api/create-post")
async def create_post(req: CreatePostRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    row = get_run(req.video_id)
    if not row:
        return {"error": "not_found", "video_id": req.video_id}

    result_data: Dict[str, Any] = {}
    if isinstance(row.get("result_json"), str):
        try:
            result_data = json.loads(row["result_json"])
        except Exception:
            pass

    vision = result_data.get("vision") or {}
    grok   = result_data.get("grok")   or {}
    frames = vision.get("frames") or []
    vision_analysis = vision.get("analysis") or {}
    metadata_prompt = (grok.get("markdown_prompt_ptbr_keep_original") or "")[:1500]

    saved = settings_get(key="token:grok")
    api_key = saved["value"] if saved else None
    if not api_key:
        return {"error": "missing_grok_token", "detail": "Configure token:grok em Settings"}

    user_content = json.dumps({
        "video_id": req.video_id,
        "frames_count": len(frames),
        "vision_analysis": vision_analysis,
        "metadata_prompt": metadata_prompt,
    }, ensure_ascii=False)

    payload = {
        "model": "grok-3-latest",
        "messages": [
            {"role": "system", "content": _CREATE_POST_SYSTEM},
            {"role": "user",   "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.75,
        "max_tokens": 2500,
    }

    try:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            # Fallback to grok-2-latest if grok-3 not available
            payload["model"] = "grok-2-latest"
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            return {"error": f"grok_api_{r.status_code}", "detail": r.text[:400]}
        result = json.loads(r.json()["choices"][0]["message"]["content"])
        return result
    except Exception as ex:
        return {"error": "create_post_failed", "detail": repr(ex)}


@app.post("/api/scheduled-posts")
def scheduled_posts_create(req: SchedulePostRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    now = datetime.now(timezone.utc).isoformat()
    post_id = str(uuid.uuid4())
    insert_scheduled_post(
        id=post_id, run_id=req.run_id, post_data=req.post_data,
        schedule_at=req.schedule_at, created_at=now,
    )
    return {"ok": True, "id": post_id}


@app.get("/api/scheduled-posts")
def scheduled_posts_list(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    return {"posts": list_scheduled_posts()}


@app.patch("/api/scheduled-posts/{post_id}")
def scheduled_posts_update(post_id: str, req: UpdateScheduledPostRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    ok = update_scheduled_post_status(id=post_id, status=req.status)
    return {"ok": ok}


@app.get("/settings/wizard/logo-preset")
def wizard_logo_preset_get(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    saved = settings_get(key="wizard:logo_preset")
    if not saved:
        return {"ok": True, "preset": _default_logo_preset(), "updated_at": None}
    try:
        raw = json.loads(saved.get("value") or "{}")
    except Exception:
        raw = {}
    preset = _normalize_logo_preset(raw if isinstance(raw, dict) else {})
    return {"ok": True, "preset": preset, "updated_at": saved.get("updated_at")}


@app.post("/settings/wizard/logo-preset")
def wizard_logo_preset_set(req: LogoPresetSetRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    payload = _normalize_logo_preset(req.model_dump())
    now = datetime.now(timezone.utc).isoformat()
    settings_set(
        key="wizard:logo_preset",
        value=json.dumps(payload, ensure_ascii=False),
        updated_at=now,
    )
    return {"ok": True, "preset": payload, "updated_at": now}


@app.get("/settings/wizard/logo-profiles")
def wizard_logo_profiles_get(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    profiles, updated_at = _load_logo_profiles_state()
    return {
        "ok": True,
        "profiles": [_serialize_logo_profile(item) for item in profiles],
        "updated_at": updated_at,
    }


@app.post("/settings/wizard/logo-profiles")
def wizard_logo_profiles_set(req: LogoProfileSetRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err

    company_name = str(req.company_name or "").strip()[:80]
    if not company_name:
        return JSONResponse({"error": "missing_company_name"}, status_code=400)

    profiles, _ = _load_logo_profiles_state()
    incoming_profile_id = _normalize_logo_profile_id(req.profile_id, company_name)
    company_key = _logo_profile_name_key(company_name)
    existing_idx = next(
        (
            idx for idx, item in enumerate(profiles)
            if str(item.get("id") or "") == incoming_profile_id
            or _logo_profile_name_key(str(item.get("company_name") or "")) == company_key
        ),
        None,
    )
    existing = dict(profiles[existing_idx]) if existing_idx is not None else {}
    existing_refs = {
        str(existing.get("logo_object_key") or "").strip(),
        *[
            str(item.get("logo_object_key") or "").strip()
            for item in (existing.get("logos") or [])
            if isinstance(item, dict)
        ],
    }
    existing_refs = {ref for ref in existing_refs if ref}

    def _store_logo_from_b64(raw_b64: str, preferred_name: str) -> tuple[str, str]:
        logo_b64 = str(raw_b64 or "").strip()
        next_logo_name = _safe_storage_filename(preferred_name or f"{company_name}.png", "logo.png")
        try:
            mime, raw = _parse_data_url(logo_b64)
            payload = base64.b64decode(raw)
        except Exception:
            raise ValueError("A imagem da logo não pôde ser decodificada.")
        if not payload:
            raise ValueError("A imagem da logo está vazia.")
        ext = _logo_ext_from_mime(mime) or os.path.splitext(next_logo_name)[1] or ".png"
        if not next_logo_name.lower().endswith(ext.lower()):
            next_logo_name = os.path.splitext(next_logo_name)[0] + ext
        with tempfile.TemporaryDirectory(prefix="logo-profile-save-", dir=_preferred_tmpdir_root("logo")) as tmpdir:
            tmp_path = os.path.join(tmpdir, next_logo_name)
            with open(tmp_path, "wb") as f:
                f.write(payload)
            stored = _store_local_path(
                src_path=tmp_path,
                prefix="logos/companies",
                filename=next_logo_name,
                content_type=mime or _guess_response_content_type(next_logo_name),
            )
        return str(stored.get("object_key") or "").strip(), next_logo_name

    stored_logos: List[Dict[str, Any]] = []
    raw_logos = req.logos if isinstance(req.logos, list) else []
    if raw_logos:
        for idx, raw_logo in enumerate(raw_logos[:MAX_LOGO_OVERLAYS]):
            if not isinstance(raw_logo, dict):
                continue
            raw_b64 = str(raw_logo.get("b64") or raw_logo.get("logo_b64") or raw_logo.get("src") or "").strip()
            if not raw_b64:
                continue
            raw_name = str(raw_logo.get("name") or raw_logo.get("logo_name") or f"{company_name}-{idx + 1}.png").strip()
            try:
                logo_ref, logo_name = _store_logo_from_b64(raw_b64, raw_name)
            except ValueError as exc:
                return JSONResponse({"error": "invalid_logo_data", "detail": str(exc)}, status_code=400)
            normalized_logo = _normalize_logo_profile_logo_entry({
                "id": raw_logo.get("id") or f"logo_{idx + 1}",
                "logo_name": logo_name,
                "logo_object_key": logo_ref,
                "x": raw_logo.get("x", raw_logo.get("logo_x", 97.0)),
                "y": raw_logo.get("y", raw_logo.get("logo_y", 97.0)),
                "scale_pct": raw_logo.get("scale_pct", raw_logo.get("logo_scale_pct", 20.0)),
                "opacity": raw_logo.get("opacity", raw_logo.get("logo_opacity", 85.0)),
                "enabled": raw_logo.get("enabled", True),
            })
            if normalized_logo:
                stored_logos.append(normalized_logo)

    if not stored_logos:
        logo_b64 = str(req.logo_b64 or "").strip()
        next_logo_ref = str(existing.get("logo_object_key") or "").strip()
        next_logo_name = _safe_storage_filename(req.logo_name or existing.get("logo_name") or f"{company_name}.png", "logo.png")
        if logo_b64:
            try:
                next_logo_ref, next_logo_name = _store_logo_from_b64(logo_b64, next_logo_name)
            except ValueError as exc:
                return JSONResponse({"error": "invalid_logo_data", "detail": str(exc)}, status_code=400)
        if next_logo_ref:
            legacy_logo = _normalize_logo_profile_logo_entry({
                "id": "primary",
                "logo_name": next_logo_name,
                "logo_object_key": next_logo_ref,
                "x": req.logo_x,
                "y": req.logo_y,
                "scale_pct": req.logo_scale_pct,
                "opacity": req.logo_opacity,
                "enabled": True,
            })
            if legacy_logo:
                stored_logos.append(legacy_logo)

    if not stored_logos:
        return JSONResponse(
            {"error": "missing_logo", "detail": "Envie pelo menos uma logo antes de salvar a empresa."},
            status_code=400,
        )

    first_logo = stored_logos[0]
    next_logo_ref = str(first_logo.get("logo_object_key") or "").strip()
    next_logo_name = str(first_logo.get("logo_name") or f"{company_name}.png")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": incoming_profile_id,
        "company_name": company_name,
        "logo_name": next_logo_name,
        "logo_object_key": next_logo_ref,
        "logos": stored_logos[:MAX_LOGO_OVERLAYS],
        "logo_x": float(first_logo.get("x") or 97.0),
        "logo_y": float(first_logo.get("y") or 97.0),
        "logo_scale_pct": float(first_logo.get("scale_pct") or 20.0),
        "logo_opacity": float(first_logo.get("opacity") or 85.0),
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
    }

    if existing_idx is None:
        profiles.append(payload)
    else:
        profiles[existing_idx] = payload
    _save_logo_profiles_state(profiles, updated_at=now)

    new_refs = {
        str(item.get("logo_object_key") or "").strip()
        for item in stored_logos
        if isinstance(item, dict) and str(item.get("logo_object_key") or "").strip()
    }
    for old_ref in sorted(existing_refs - new_refs):
        still_used = any(
            old_ref == str(item.get("logo_object_key") or "").strip()
            or any(old_ref == str(lg.get("logo_object_key") or "").strip() for lg in (item.get("logos") or []) if isinstance(lg, dict))
            for item in profiles
        )
        if old_ref and not still_used:
            try:
                _delete_media_ref(media_ref=old_ref, s3=_s3_client())
            except Exception:
                pass

    return {
        "ok": True,
        "profile": _serialize_logo_profile(payload),
        "profiles": [_serialize_logo_profile(item) for item in profiles],
        "updated_at": now,
    }


@app.delete("/settings/wizard/logo-profiles/{profile_id}")
def wizard_logo_profiles_delete(profile_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    safe_profile_id = _normalize_logo_profile_id(profile_id, profile_id)
    profiles, _ = _load_logo_profiles_state()
    existing_idx = next((idx for idx, item in enumerate(profiles) if str(item.get("id") or "") == safe_profile_id), None)
    if existing_idx is None:
        return JSONResponse({"error": "profile_not_found"}, status_code=404)

    existing = dict(profiles.pop(existing_idx))
    now = datetime.now(timezone.utc).isoformat()
    _save_logo_profiles_state(profiles, updated_at=now)

    refs_to_delete = {
        str(existing.get("logo_object_key") or "").strip(),
        *[
            str(item.get("logo_object_key") or "").strip()
            for item in (existing.get("logos") or [])
            if isinstance(item, dict)
        ],
    }
    for logo_ref in sorted(ref for ref in refs_to_delete if ref):
        still_used = any(
            str(item.get("logo_object_key") or "").strip() == logo_ref
            or any(logo_ref == str(lg.get("logo_object_key") or "").strip() for lg in (item.get("logos") or []) if isinstance(lg, dict))
            for item in profiles
        )
        if not still_used:
            try:
                _delete_media_ref(media_ref=logo_ref, s3=_s3_client())
            except Exception:
                pass

    return {
        "ok": True,
        "deleted_profile_id": safe_profile_id,
        "profiles": [_serialize_logo_profile(item) for item in profiles],
        "updated_at": now,
    }


@app.post("/llm/compare")
async def llm_compare(req: LlmCompareResultRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    if not req.prompt_markdown.strip():
        return {"error": "missing_prompt_markdown"}
    if len(req.providers) < 2:
        return {"error": "missing_providers", "detail": "send at least 2 providers"}
    try:
        specs = _build_provider_specs(req.providers)
    except ValueError as e:
        return {"error": str(e)}

    results = await run_providers_to_completion(prompt=req.prompt_markdown, providers=specs, params=req.params)
    return {"ok": True, "results": results}


@app.get("/settings/tokens")
def tokens_list(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    # Do NOT return token values, only which providers are configured
    return {"tokens": settings_list(prefix="token:")}


@app.get("/api/ollama/status")
async def ollama_status():
    """Retorna modelos carregados no Ollama e se estão em GPU ou CPU."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            ps = await client.get(f"{_OLLAMA_BASE_URL}/api/ps")
            tags = await client.get(f"{_OLLAMA_BASE_URL}/api/tags")
        ps_data = ps.json() if ps.status_code == 200 else {}
        tags_data = tags.json() if tags.status_code == 200 else {}
        loaded = ps_data.get("models", [])
        available = tags_data.get("models", [])
        return {
            "ok": True,
            "loaded": [
                {
                    "name": m.get("name"),
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "vram_gb": round(m.get("size_vram", 0) / 1e9, 1),
                    "on_gpu": m.get("size_vram", 0) > 0,
                    "params": m.get("details", {}).get("parameter_size"),
                    "expires_at": m.get("expires_at"),
                }
                for m in loaded
            ],
            "available": [m.get("name") for m in available],
        }
    except Exception as e:
        return {"ok": False, "error": repr(e), "loaded": [], "available": []}


@app.delete("/api/runs/{run_id}/burned-video")
async def delete_burned_video(run_id: str, request: Request):
    """Delete the burned video object and clear burned_object_key from wizard_state."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    run = get_run(run_id)
    if not run:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    req_data = _safe_json_obj(run.get("request_json"))
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    object_key = str(wizard_state.get("burned_object_key") or "").strip()
    if not object_key:
        return JSONResponse({"error": "no_burned_video"}, status_code=404)
    deleted_key = None
    if _is_valid_object_key(object_key):
        try:
            await asyncio.to_thread(_delete_media_ref, media_ref=object_key, s3=_s3_client())
            deleted_key = object_key
        except Exception as e:
            print(f"[delete-burned] delete failed ({object_key}): {e}")
    _merge_run_wizard_state(run_id, {
        "burned_object_key": None,
        "burned_filename": None,
    })
    return JSONResponse({"ok": True, "deleted_key": deleted_key})


@app.delete("/api/runs/{run_id}/teaser-video")
async def delete_teaser_video(run_id: str, request: Request):
    """Delete teaser-derived videos and clear matching wizard_state keys."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        body = {}
    run = get_run(run_id)
    if not run:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    req_data = _safe_json_obj(run.get("request_json"))
    wizard_state = _safe_json_obj(req_data.get("wizard_state"))
    body_object_key = str(
        body.get("object_key")
        or body.get("teaser_object_key")
        or body.get("teaser_logo_object_key")
        or ""
    ).strip()
    target_teaser_key = str(wizard_state.get("teaser_object_key") or "").strip()
    target_teaser_logo_key = str(wizard_state.get("teaser_logo_object_key") or "").strip()
    object_key = body_object_key or target_teaser_key or target_teaser_logo_key
    if not object_key:
        return JSONResponse({"error": "no_teaser_video"}, status_code=404)
    deleted_key = None
    if _is_valid_object_key(object_key):
        try:
            await asyncio.to_thread(_delete_media_ref, media_ref=object_key, s3=_s3_client())
            deleted_key = object_key
        except Exception as e:
            print(f"[delete-teaser] delete failed ({object_key}): {e}")
    updates: Dict[str, Any] = {}
    if object_key == target_teaser_key or body.get("teaser_object_key") is not None:
        updates["teaser_object_key"] = None
    if object_key == target_teaser_logo_key or body.get("teaser_logo_object_key") is not None:
        updates["teaser_logo_object_key"] = None
        updates["teaser_logo_filename"] = None
    if not updates:
        updates["teaser_object_key"] = None
    _merge_run_wizard_state(run_id, updates)
    return JSONResponse({"ok": True, "deleted_key": deleted_key})


@app.post("/settings/tokens")
def tokens_set(req: TokenSetRequest, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    provider = (req.provider or "").strip().lower()
    if provider not in {
        "openai", "deepseek", "openrouter", "grok", "groq", "gemini", "fal", "deepgram", "assemblyai",
        "composio", "composio_auth_config_instagram", "composio_auth_config_facebook",
        "composio_auth_config_tiktok", "composio_auth_config_youtube",
    }:
        return {"error": "unsupported_provider", "detail": "allowed providers: openai, deepseek, openrouter, grok, groq, gemini, fal, deepgram, assemblyai, composio"}
    api_key = (req.api_key or "").strip()
    if not api_key:
        return {"error": "missing_api_key"}

    # Internal MVP: store as plain text in SQLite.
    # TODO: encrypt at rest with a server-side master key.
    now = datetime.now(timezone.utc).isoformat()
    settings_set(key=f"token:{provider}", value=api_key, updated_at=now)
    return {"ok": True, "provider": provider, "updated_at": now}


# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM MODULE — Via n8n Webhook (bot token configurado no n8n)
# ═══════════════════════════════════════════════════════════════════════════════

_TELEGRAM_GROUPS_KEY       = "telegram:groups"
_TELEGRAM_N8N_WEBHOOK_KEY  = "telegram:n8n_webhook_url"
_TELEGRAM_APP_PUBLIC_KEY   = "telegram:app_public_url"


def _tg_groups() -> list:
    row = settings_get(key=_TELEGRAM_GROUPS_KEY)
    if not row:
        return []
    try:
        return json.loads(row["value"])
    except Exception:
        return []


def _tg_n8n_webhook_url() -> str:
    row = settings_get(key=_TELEGRAM_N8N_WEBHOOK_KEY)
    return (row["value"] if row else "").strip()


def _tg_app_public_url() -> str:
    row = settings_get(key=_TELEGRAM_APP_PUBLIC_KEY)
    val = (row["value"] if row else "").strip().rstrip("/")
    if not val:
        val = os.environ.get("APP_PUBLIC_URL", "https://caripost.n8nmikael.com.br").rstrip("/")
    return val


def _tg_build_video_url(object_key: str, expires_in: int = 86400, base_url: str = "") -> str:
    """Gera URL absoluta e assinada para o teaser — acessível pelo n8n."""
    relative_url = _build_local_media_url(object_key, expires_in=expires_in)
    base = (base_url or _tg_app_public_url()).rstrip("/")
    return base + relative_url


def _tg_base_url_from_request(request: Request) -> str:
    """Detecta a URL base pública a partir dos headers da request (considera proxy reverso)."""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.hostname
    # Forçar HTTPS para hosts públicos — Telegram não aceita HTTP
    if host and not host.startswith(("localhost", "127.", "10.", "172.", "192.168.")):
        scheme = "https"
    return f"{scheme}://{host}"


async def _tg_call_n8n_webhook(webhook_url: str, payload: dict) -> dict:
    """Chama o webhook n8n com o payload do post."""
    import logging as _log
    _log.getLogger("uvicorn.error").warning(
        f"[telegram-webhook] POST {webhook_url[:80]} payload_keys={list(payload.keys())}"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(webhook_url, json=payload)
        _log.getLogger("uvicorn.error").warning(
            f"[telegram-webhook] response status={r.status_code} body={r.text[:300]}"
        )
        if r.status_code < 400:
            try:
                return {"ok": True, "data": r.json()}
            except Exception:
                return {"ok": True, "data": r.text[:200]}
        return {"ok": False, "description": f"HTTP {r.status_code}: {r.text[:300]}"}
    except Exception as ex:
        _log.getLogger("uvicorn.error").warning(f"[telegram-webhook] exception: {ex}")
        return {"ok": False, "description": str(ex)}


async def _dispatch_scheduled_post(post: dict) -> None:
    """Executa o envio de um post agendado via n8n webhook."""
    post_id = post["id"]
    pd = post.get("post_data") or {}
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        webhook_url = _tg_n8n_webhook_url()
        if not webhook_url:
            update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log="Webhook n8n não configurado")
            return
        chat_id = str(pd.get("chat_id") or pd.get("telegram_chat_id") or "").strip()
        if not chat_id:
            update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log="chat_id não definido")
            return
        teaser_key = str(pd.get("teaser_object_key") or pd.get("video_object_key") or "").strip()
        if not teaser_key:
            update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log="teaser_object_key não definido")
            return
        try:
            video_url = _tg_build_video_url(teaser_key)
        except Exception as ex:
            update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log=f"URL não gerada: {ex}")
            return
        caption = str(pd.get("caption") or pd.get("title") or "").strip()
        update_scheduled_post_status(id=post_id, status="sending")
        result = await _tg_call_n8n_webhook(webhook_url, {
            "chat_id": chat_id, "video_url": video_url,
            "caption": caption, "post_id": post_id,
        })
        if result.get("ok"):
            update_scheduled_post_sent(id=post_id, status="sent", sent_at=now_iso)
        else:
            err = result.get("description") or str(result)
            update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log=err[:500])
    except Exception as ex:
        update_scheduled_post_sent(id=post_id, status="error", sent_at=now_iso, error_log=repr(ex)[:500])


async def _telegram_scheduler_loop() -> None:
    """Background loop: dispara posts agendados via n8n a cada 30s."""
    import logging as _log
    _log.getLogger("uvicorn.error").info("[telegram-scheduler] iniciado (n8n mode)")
    while True:
        try:
            await asyncio.sleep(30)
            now_iso = datetime.now(timezone.utc).isoformat()
            due = list_scheduled_posts_due(now_iso)
            for post in due:
                asyncio.create_task(_dispatch_scheduled_post(post))
        except asyncio.CancelledError:
            break
        except Exception as ex:
            import logging as _log2
            _log2.getLogger("uvicorn.error").warning(f"[telegram-scheduler] erro: {ex}")


@app.on_event("startup")
async def _telegram_scheduler_startup():
    asyncio.create_task(_telegram_scheduler_loop())


@app.on_event("startup")
async def _agency_scheduler_startup():
    """Start APScheduler for agency cron tasks."""
    try:
        from .scheduler.cron_tasks import setup_scheduler
        setup_scheduler()
    except Exception as exc:
        import logging as _log
        _log.getLogger("uvicorn.error").warning(f"[agency-scheduler] startup error: {exc}")


@app.on_event("shutdown")
async def _agency_scheduler_shutdown():
    try:
        from .scheduler.cron_tasks import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass


# ── Settings endpoints ────────────────────────────────────────────────────────

@app.get("/settings/telegram")
def telegram_settings_get(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    webhook_url = _tg_n8n_webhook_url()
    return {
        "webhook_configured": bool(webhook_url),
        "webhook_url": webhook_url,
        "groups": _tg_groups(),
    }


@app.post("/settings/telegram")
async def telegram_settings_set(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    now = datetime.now(timezone.utc).isoformat()
    if "n8n_webhook_url" in body and str(body["n8n_webhook_url"] or "").strip():
        settings_set(key=_TELEGRAM_N8N_WEBHOOK_KEY, value=str(body["n8n_webhook_url"]).strip(), updated_at=now)
    if "app_public_url" in body and str(body["app_public_url"] or "").strip():
        settings_set(key=_TELEGRAM_APP_PUBLIC_KEY, value=str(body["app_public_url"]).strip().rstrip("/"), updated_at=now)
    return {"ok": True}


@app.post("/settings/telegram/groups")
async def telegram_group_add(request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    group_id = str(body.get("group_id") or "").strip()
    group_name = str(body.get("name") or body.get("group_name") or "").strip()
    if not group_id:
        return JSONResponse({"error": "missing_group_id"}, status_code=400)
    groups = _tg_groups()
    groups = [g for g in groups if str(g.get("id") or "") != group_id]
    groups.append({"id": group_id, "name": group_name or group_id})
    now = datetime.now(timezone.utc).isoformat()
    settings_set(key=_TELEGRAM_GROUPS_KEY, value=json.dumps(groups, ensure_ascii=False), updated_at=now)
    return {"ok": True, "groups": groups}


@app.delete("/settings/telegram/groups/{group_id}")
def telegram_group_remove(group_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    groups = [g for g in _tg_groups() if str(g.get("id") or "") != group_id]
    now = datetime.now(timezone.utc).isoformat()
    settings_set(key=_TELEGRAM_GROUPS_KEY, value=json.dumps(groups, ensure_ascii=False), updated_at=now)
    return {"ok": True, "groups": groups}


@app.post("/api/telegram/test-webhook")
async def telegram_test_webhook(request: Request):
    """Testa o webhook n8n com payload de teste."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    webhook_url = _tg_n8n_webhook_url()
    if not webhook_url:
        return JSONResponse({"error": "webhook_not_configured"}, status_code=400)
    result = await _tg_call_n8n_webhook(webhook_url, {"test": True, "source": "adult-meta"})
    return result


@app.post("/api/telegram/send-now")
async def telegram_send_now(request: Request):
    """Dispara post imediato via n8n webhook."""
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    webhook_url = _tg_n8n_webhook_url()
    if not webhook_url:
        return JSONResponse({"error": "webhook_not_configured", "detail": "Configure o webhook n8n em Configurações → Telegram"}, status_code=400)
    chat_id = str(body.get("chat_id") or "").strip()
    if not chat_id:
        return JSONResponse({"error": "missing_chat_id"}, status_code=400)
    teaser_key = str(body.get("teaser_object_key") or "").strip()
    if not teaser_key:
        return JSONResponse({"error": "missing_teaser_object_key"}, status_code=400)
    caption = str(body.get("caption") or "").strip()
    try:
        video_url = _tg_build_video_url(teaser_key, base_url=_tg_base_url_from_request(request))
    except Exception as ex:
        return JSONResponse({"error": "url_generation_failed", "detail": str(ex)}, status_code=400)
    result = await _tg_call_n8n_webhook(webhook_url, {"chat_id": chat_id, "video_url": video_url, "caption": caption})
    if result.get("ok"):
        now = datetime.now(timezone.utc).isoformat()
        post_id = str(uuid.uuid4())
        insert_scheduled_post(
            id=post_id, run_id=str(body.get("run_id") or "direct"),
            post_data={**body, "teaser_object_key": teaser_key, "caption": caption, "chat_id": chat_id},
            schedule_at=None, created_at=now,
        )
        update_scheduled_post_sent(id=post_id, status="sent", sent_at=now)
        return {"ok": True, "post_id": post_id, "video_url": video_url}
    return JSONResponse({"ok": False, "error": result.get("description", "webhook_error"), "detail": result}, status_code=502)


@app.delete("/api/scheduled-posts/{post_id}")
def scheduled_post_delete(post_id: str, request: Request):
    auth_err = _require_api_key(request)
    if auth_err:
        return auth_err
    ok = delete_scheduled_post(id=post_id)
    return {"ok": ok}
