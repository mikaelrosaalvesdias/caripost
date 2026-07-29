"""
Shared utilities for routers — e.g. API key checking.
Extracted here to avoid circular imports with main.py.
"""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

_API_KEY = None


def _get_api_key() -> str:
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("ADULT_META_API_KEY", "")
    return _API_KEY


def require_api_key(request: Request):
    """
    Check browser session or X-API-Key header.
    Returns JSONResponse(401) if invalid, None if OK.
    Compatible with the existing _require_api_key pattern in main.py.
    """
    from .routers.auth import verify_session_token

    session_token = request.headers.get("X-Session-Token", "")
    if session_token and verify_session_token(session_token):
        return None

    api_key = _get_api_key()
    if not api_key:
        # Fail closed unless explicit dev opt-in (mirrors main.py _require_api_key)
        if os.environ.get("ALLOW_OPEN_ACCESS", "").strip().lower() in ("1", "true", "yes", "on"):
            return None
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    provided = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
    if provided != api_key:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return None


def _session_of(request: Request):
    token = request.headers.get("X-Session-Token") or request.cookies.get("session")
    if not token:
        return None
    try:
        from .routers.auth import verify_session_token
        return verify_session_token(token) or None
    except Exception:
        return None


def scoped_company_ids(request: Request):
    """CONJUNTO de empresas que o usuário pode acessar. None = sem escopo (super-admin/staff/API-key).
    role owner (CLIENTE FINAL) → {a empresa dele}. role agency (AGÊNCIA) → {empresas com owner_user_id=ele}."""
    sess = _session_of(request)
    if not sess:
        return None
    role = sess.get("role") or ""
    if role == "owner" and sess.get("company_id"):
        return {str(sess["company_id"])}
    if role == "agency":
        try:
            from .db import get_conn
            with get_conn() as c:
                rows = c.execute("SELECT id FROM companies WHERE owner_user_id=?", (sess.get("user_id"),)).fetchall()
            ids = {str(r[0]) for r in rows}
            if sess.get("company_id"):
                ids.add(str(sess["company_id"]))
            return ids
        except Exception:
            return set()
    if sess.get("company_id"):
        return {str(sess["company_id"])}
    return None


def scoped_company_id(request: Request):
    """Compat: id ÚNICO quando o escopo é de 1 empresa (cliente final); None caso contrário."""
    ids = scoped_company_ids(request)
    if ids is not None and len(ids) == 1:
        return next(iter(ids))
    return None


def company_access_denied(request: Request, company_id):
    """403 se o usuário escopado tentar acessar empresa FORA do conjunto dele. None = liberado."""
    ids = scoped_company_ids(request)
    if ids is not None and company_id and str(company_id) not in ids:
        return JSONResponse({"detail": "Acesso negado a esta empresa.", "error": "company_scope"}, status_code=403)
    return None
