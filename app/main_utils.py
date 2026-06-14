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
        return None  # no key configured → open
    provided = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
    if provided != api_key:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return None
