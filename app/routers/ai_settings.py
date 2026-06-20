"""
AI settings router — save/load/test AI provider config.
Mirrors caripost-web's settings page.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.ai import (
    get_settings_map, set_setting, test_ai, list_models,
    is_ai_enabled, get_ai_config, SETTINGS_WHITELIST,
)

router = APIRouter(prefix="/api/ai-settings", tags=["ai-settings"])


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


@router.get("")
def get_settings(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return get_settings_map()


@router.post("")
async def save_settings(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    for key, value in body.items():
        if not value and "apiKey" in key:
            continue  # keep existing
        try:
            set_setting(key, str(value))
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
    return {"saved": True, "settings": get_settings_map()}


@router.post("/test")
def test_connection(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    result = test_ai()
    if result is None:
        return {"test_result": "ok", "message": "Conexão ok — IA pronta para gerar conteúdo."}
    return {"test_result": "error", "message": result}


@router.post("/models")
async def load_models(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    section = body.get("section", "ai")
    provider = body.get("provider", "anthropic")
    api_key = body.get("api_key")  # optional: use typed key before saving
    if section not in SETTINGS_WHITELIST:
        return JSONResponse({"detail": f"Seção inválida: {section}"}, status_code=422)
    if provider not in SETTINGS_WHITELIST[section]:
        return JSONResponse({"detail": f"Provedor inválido: {provider}"}, status_code=422)
    try:
        models = list_models(section, provider, api_key or None)
        return {"models": models}
    except Exception as exc:
        return {"models": [], "error": "Nenhum modelo retornado — confira a chave do provedor."}


@router.get("/status")
def get_status(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    config = get_ai_config()
    return {
        "ai_enabled": is_ai_enabled(),
        "provider": config.get("provider") if config else None,
        "model": config.get("model") if config else None,
    }
