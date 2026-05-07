"""
Authentication router — login/logout, session management, user CRUD.

Password hashing: PBKDF2-HMAC-SHA256 (stdlib, no extra deps).
Session token: JWT-style HMAC-SHA256 (same pattern as portal.py).

Roles:
  admin  → acesso total (pode gerenciar usuários e settings)
  editor → acesso a todos os módulos exceto settings de usuários
  viewer → acesso somente leitura às abas configuradas

Permissões por aba: lista de nomes de abas. Lista vazia = usar defaults do role.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import (
    appuser_create, appuser_list, appuser_get, appuser_get_by_username,
    appuser_update, appuser_delete, appuser_count,
    activity_log_insert, activity_log_list,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Constants ──────────────────────────────────────────────────────────────

SESSION_SECRET = os.environ.get("AUTH_SESSION_SECRET", "change-me-in-production-32chars!")
SESSION_TTL = int(os.environ.get("AUTH_SESSION_TTL_HOURS", "24")) * 3600

ROLE_DEFAULTS: Dict[str, List[str]] = {
    "admin": [
        "analyze", "runs", "media", "referencia", "criacao", "compare",
        "settings", "telegram", "creators", "autoeditor", "videoenhancer", "publisher", "trends",
        "calendar", "financial", "dmca",
    ],
    "editor": [
        "analyze", "runs", "media", "referencia", "criacao", "compare",
        "telegram", "creators", "autoeditor", "videoenhancer", "publisher", "trends",
        "calendar", "financial", "dmca",
    ],
    "viewer": ["analyze", "runs", "media", "referencia"],
}

ALL_TABS = ROLE_DEFAULTS["admin"]


# ── Password helpers ────────────────────────────────────────────────────────

def _hash_password(password: str, salt: Optional[str] = None) -> str:
    """Return 'salt$hash' string. Generates random salt if not provided."""
    if salt is None:
        salt = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 260_000
    )
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
        return hmac.compare_digest(_hash_password(password, salt), stored)
    except Exception:
        return False


# ── JWT helpers ─────────────────────────────────────────────────────────────

def _make_token(payload: Dict) -> str:
    payload["iat"] = int(time.time())
    payload["exp"] = payload["iat"] + SESSION_TTL
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body_b64 = body.encode().hex()
    sig = hmac.new(SESSION_SECRET.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
    return f"{body_b64}.{sig}"


def _decode_token(token: str) -> Optional[Dict]:
    try:
        body_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SESSION_SECRET.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(bytes.fromhex(body_b64).decode())
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def verify_session_token(token: str) -> Optional[Dict]:
    """Public helper used by main.py middleware."""
    return _decode_token(token)


def get_effective_permissions(role: str, custom: List[str]) -> List[str]:
    """Return the actual list of allowed tabs for this user.
    Admin always gets all tabs regardless of custom permissions.
    """
    if role == "admin":
        return ROLE_DEFAULTS["admin"]
    return custom if custom else ROLE_DEFAULTS.get(role, [])


# ── Auth guard helper (used inside this router) ─────────────────────────────

def _get_session(request: Request) -> Optional[Dict]:
    token = request.headers.get("X-Session-Token") or request.cookies.get("session")
    if not token:
        return None
    return _decode_token(token)


def _is_open_mode() -> bool:
    """True quando auth não está configurado — sem env admin e sem usuários no banco."""
    return not os.environ.get("AUTH_ADMIN_PASS") and appuser_count() == 0


def _require_admin(request: Request):
    # Modo setup: sem nenhum usuário configurado — acesso livre para criar o primeiro admin
    if _is_open_mode():
        return None
    sess = _get_session(request)
    if not sess or sess.get("role") != "admin":
        return JSONResponse({"error": "forbidden", "detail": "admin only"}, status_code=403)
    return None


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return JSONResponse({"error": "missing_credentials"}, status_code=400)

    # Bootstrap: accept env-var credentials as admin (before any user is created)
    admin_user = os.environ.get("AUTH_ADMIN_USER", "admin")
    admin_pass = os.environ.get("AUTH_ADMIN_PASS", "")
    total_users = appuser_count()

    if admin_pass and username == admin_user and password == admin_pass:
        token = _make_token({
            "user_id": "__env_admin__",
            "username": username,
            "role": "admin",
            "permissions": [],
        })
        ip = request.client.host if request.client else None
        try:
            activity_log_insert("__env_admin__", username, "login", details="env admin login", ip=ip)
        except Exception:
            pass
        return {
            "ok": True,
            "token": token,
            "user": {
                "user_id": "__env_admin__",
                "username": username,
                "role": "admin",
                "permissions": ROLE_DEFAULTS["admin"],
                "active": True,
            },
        }

    user = appuser_get_by_username(username)
    if not user:
        return JSONResponse({"error": "invalid_credentials"}, status_code=401)

    # Need password_hash — fetch directly
    from ..db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM app_users WHERE username=?", (username,)).fetchone()
    if not row or not _verify_password(password, row[0]):
        return JSONResponse({"error": "invalid_credentials"}, status_code=401)

    if not user.get("active"):
        return JSONResponse({"error": "account_inactive"}, status_code=403)

    effective_perms = get_effective_permissions(user["role"], user["permissions"])
    token = _make_token({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "permissions": effective_perms,
    })
    ip = request.client.host if request.client else None
    try:
        activity_log_insert(user["user_id"], user["username"], "login", ip=ip)
    except Exception:
        pass
    return {
        "ok": True,
        "token": token,
        "user": {
            **user,
            "permissions": effective_perms,
        },
    }


@router.get("/me")
async def me(request: Request):
    sess = _get_session(request)
    if not sess:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    # Re-read permissions from DB so they update without re-login
    user_id = sess.get("user_id")
    if user_id and user_id != "__env_admin__":
        db_user = appuser_get_by_username(sess.get("username", ""))
        if db_user:
            sess = dict(sess)
            sess["permissions"] = get_effective_permissions(db_user["role"], db_user["permissions"])
    elif user_id == "__env_admin__":
        sess = dict(sess)
        sess["permissions"] = ROLE_DEFAULTS["admin"]
    return {"ok": True, "user": sess}


@router.get("/users")
async def list_users(request: Request):
    err = _require_admin(request)
    if err:
        return err
    users = appuser_list()
    # Add effective permissions to each user
    for u in users:
        u["effective_permissions"] = get_effective_permissions(u["role"], u["permissions"])
    return {"ok": True, "users": users, "all_tabs": ALL_TABS, "role_defaults": ROLE_DEFAULTS}


@router.post("/users")
async def create_user(request: Request):
    err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role", "viewer")

    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)
    if role not in ("admin", "editor", "viewer"):
        return JSONResponse({"error": "invalid role"}, status_code=400)
    if appuser_get_by_username(username):
        return JSONResponse({"error": "username_taken"}, status_code=409)

    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    permissions = body.get("permissions", [])  # [] = use role defaults

    appuser_create({
        "user_id": user_id,
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "permissions": permissions,
        "active": True,
        "created_at": now,
        "updated_at": now,
    })
    sess = _get_session(request)
    actor = sess.get("username", "setup") if sess else "setup"
    actor_id = sess.get("user_id", "__setup__") if sess else "__setup__"
    try:
        activity_log_insert(actor_id, actor, "create_user", target=username,
                            details=f"role={role}", ip=request.client.host if request.client else None)
    except Exception:
        pass
    user = appuser_get(user_id)
    user["effective_permissions"] = get_effective_permissions(role, permissions)
    return {"ok": True, "user": user}


@router.put("/users/{user_id}")
async def update_user(user_id: str, request: Request):
    err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    existing = appuser_get(user_id)
    if not existing:
        return JSONResponse({"error": "not_found"}, status_code=404)

    update: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if "username" in body:
        username = body["username"].strip()
        if not username:
            return JSONResponse({"error": "username cannot be empty"}, status_code=400)
        collision = appuser_get_by_username(username)
        if collision and collision["user_id"] != user_id:
            return JSONResponse({"error": "username_taken"}, status_code=409)
        update["username"] = username

    if "password" in body and body["password"]:
        update["password_hash"] = _hash_password(body["password"])

    if "role" in body:
        if body["role"] not in ("admin", "editor", "viewer"):
            return JSONResponse({"error": "invalid role"}, status_code=400)
        update["role"] = body["role"]

    if "permissions" in body:
        update["permissions"] = body["permissions"]

    if "active" in body:
        update["active"] = 1 if body["active"] else 0

    appuser_update(user_id, update)
    sess = _get_session(request)
    actor = sess.get("username", "setup") if sess else "setup"
    actor_id = sess.get("user_id", "__setup__") if sess else "__setup__"
    changed = [k for k in ("username", "role", "active", "permissions", "password_hash") if k in update]
    try:
        activity_log_insert(actor_id, actor, "update_user", target=existing["username"],
                            details=f"changed: {', '.join(changed)}",
                            ip=request.client.host if request.client else None)
    except Exception:
        pass
    user = appuser_get(user_id)
    role = user["role"]
    perms = user["permissions"]
    user["effective_permissions"] = get_effective_permissions(role, perms)
    return {"ok": True, "user": user}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    err = _require_admin(request)
    if err:
        return err

    # Prevent deleting yourself
    sess = _get_session(request)
    if sess and sess.get("user_id") == user_id:
        return JSONResponse({"error": "cannot delete yourself"}, status_code=400)

    existing = appuser_get(user_id)
    if not existing:
        return JSONResponse({"error": "not_found"}, status_code=404)

    appuser_delete(user_id)
    sess = _get_session(request)
    actor = sess.get("username", "setup") if sess else "setup"
    actor_id = sess.get("user_id", "__setup__") if sess else "__setup__"
    try:
        activity_log_insert(actor_id, actor, "delete_user", target=existing["username"],
                            ip=request.client.host if request.client else None)
    except Exception:
        pass
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, request: Request):
    err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    new_password = body.get("password") or ""
    if len(new_password) < 4:
        return JSONResponse({"error": "password too short (min 4 chars)"}, status_code=400)

    existing = appuser_get(user_id)
    if not existing:
        return JSONResponse({"error": "not_found"}, status_code=404)

    now = datetime.now(timezone.utc).isoformat()
    appuser_update(user_id, {"password_hash": _hash_password(new_password), "updated_at": now})

    sess = _get_session(request)
    actor = sess.get("username", "setup") if sess else "setup"
    actor_id = sess.get("user_id", "__setup__") if sess else "__setup__"
    try:
        activity_log_insert(actor_id, actor, "reset_password", target=existing["username"],
                            ip=request.client.host if request.client else None)
    except Exception:
        pass
    return {"ok": True}


@router.get("/logs")
async def get_all_logs(request: Request, limit: int = 200):
    err = _require_admin(request)
    if err:
        return err
    logs = activity_log_list(limit=limit)
    return {"ok": True, "logs": logs}


@router.get("/users/{user_id}/logs")
async def get_user_logs(user_id: str, request: Request, limit: int = 100):
    err = _require_admin(request)
    if err:
        return err
    logs = activity_log_list(user_id=user_id, limit=limit)
    return {"ok": True, "logs": logs}


@router.get("/check")
async def check_auth_setup():
    """Public endpoint: returns whether auth is configured (has users or env admin)."""
    has_env_admin = bool(os.environ.get("AUTH_ADMIN_PASS", ""))
    total_users = appuser_count()
    return {
        "auth_enabled": has_env_admin or total_users > 0,
        "has_env_admin": has_env_admin,
        "user_count": total_users,
    }
