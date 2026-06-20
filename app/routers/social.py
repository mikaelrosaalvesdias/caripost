from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..social.base import SUPPORTED_SOCIAL_PLATFORMS, SocialProviderError
from ..social.service import (
    connect_account,
    create_post,
    disconnect_account,
    ensure_brand_exists,
    handle_connection_callback,
    list_accounts,
    normalize_platform,
    post_metrics,
    post_status,
    process_due_social_posts,
    publish_social_post,
    get_social_provider,
)

router = APIRouter(prefix="/api/social", tags=["social"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, SocialProviderError):
        return JSONResponse({"detail": exc.message, **(exc.detail or {})}, status_code=exc.status_code)
    return JSONResponse({"detail": str(exc)}, status_code=500)


def _verify_webhook(raw_body: bytes, request: Request) -> Optional[JSONResponse]:
    secret = (os.environ.get("COMPOSIO_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return None
    webhook_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signature = request.headers.get("webhook-signature", "")
    if not webhook_id or not timestamp or not signature:
        return JSONResponse({"detail": "Assinatura Composio ausente."}, status_code=401)
    try:
        ts_int = int(float(timestamp))
        if abs(int(time.time()) - ts_int) > 300:
            return JSONResponse({"detail": "Assinatura Composio expirada."}, status_code=401)
    except Exception:
        return JSONResponse({"detail": "Timestamp Composio inválido."}, status_code=401)
    signing_string = f"{webhook_id}.{timestamp}.{raw_body.decode('utf-8')}"
    expected = base64.b64encode(hmac.new(secret.encode(), signing_string.encode(), hashlib.sha256).digest()).decode()
    received = signature.split(",", 1)[1] if "," in signature else signature
    if not hmac.compare_digest(expected, received):
        return JSONResponse({"detail": "Assinatura Composio inválida."}, status_code=401)
    return None


@router.get("/config")
def social_config(request: Request):
    err = _auth(request)
    if err:
        return err
    return {
        "enabled": (os.environ.get("SOCIAL_COMPOSIO_ENABLED", "1") != "0"),
        "provider": (os.environ.get("SOCIAL_PROVIDER") or "composio"),
        "composio_configured": bool(os.environ.get("COMPOSIO_API_KEY")),
        "platforms": sorted(SUPPORTED_SOCIAL_PLATFORMS),
    }


@router.post("/connect")
async def connect(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
        return await connect_account(body, request)
    except Exception as exc:
        return _error(exc)


@router.post("/callback")
async def callback(request: Request):
    raw = await request.body()
    sig_error = _verify_webhook(raw, request)
    if sig_error:
        return sig_error
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
        return await handle_connection_callback(payload)
    except Exception as exc:
        return _error(exc)


@router.get("/callback")
async def callback_get(request: Request):
    try:
        payload = dict(request.query_params)
        result = await handle_connection_callback(payload)
        detail = "Conta social conectada. Você já pode fechar esta aba e voltar ao Caripost."
        if result.get("ignored"):
            detail = "Callback recebido. Se a conta ainda aparecer pendente, confira o webhook do Composio."
        return HTMLResponse(f"<html><body><h1>Caripost</h1><p>{detail}</p></body></html>")
    except Exception as exc:
        return HTMLResponse(f"<html><body><h1>Caripost</h1><p>Erro: {str(exc)}</p></body></html>", status_code=500)


@router.get("/accounts")
def accounts(request: Request, brandId: str, platform: Optional[str] = None):
    err = _auth(request)
    if err:
        return err
    try:
        return list_accounts(brandId, platform)
    except Exception as exc:
        return _error(exc)


@router.delete("/accounts/{connection_id}")
async def delete_account(connection_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        return await disconnect_account(connection_id)
    except Exception as exc:
        return _error(exc)


@router.get("/posts")
def list_social_posts(request: Request, brandId: Optional[str] = None, status: Optional[str] = None, limit: int = 100):
    err = _auth(request)
    if err:
        return err
    try:
        if brandId:
            ensure_brand_exists(brandId)
        from ..db_agency import social_post_list
        return {"posts": social_post_list(brand_id=brandId, status=status, limit=limit)}
    except Exception as exc:
        return _error(exc)


@router.post("/posts")
async def create_social_post(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
        return await create_post(body, request)
    except Exception as exc:
        return _error(exc)


@router.post("/posts/{post_id}/publish")
async def publish(post_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        return await publish_social_post(post_id)
    except Exception as exc:
        return _error(exc)


@router.get("/posts/{post_id}/status")
def status(post_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        return post_status(post_id)
    except Exception as exc:
        return _error(exc)


@router.get("/posts/{post_id}/metrics")
async def metrics(post_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        return await post_metrics(post_id)
    except Exception as exc:
        return _error(exc)


@router.post("/worker/run")
async def run_worker(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        return await process_due_social_posts()
    except Exception as exc:
        return _error(exc)


@router.get("/competitors")
def list_competitors(request: Request, brandId: str):
    err = _auth(request)
    if err:
        return err
    try:
        ensure_brand_exists(brandId)
        from ..db_companies import competitor_list
        return {"competitors": competitor_list(brandId)}
    except Exception as exc:
        return _error(exc)


@router.post("/competitors")
async def create_competitor(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
        brand_id = body.get("brandId") or body.get("brand_id")
        ensure_brand_exists(brand_id)
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
        handles = body.get("handles") or {}
        for platform in SUPPORTED_SOCIAL_PLATFORMS:
            if body.get(platform):
                handles[platform] = body.get(platform)
        from ..db_companies import competitor_create
        return {"competitor": competitor_create(brand_id, {"name": name, "handles": handles})}
    except Exception as exc:
        return _error(exc)


@router.post("/competitors/{competitor_id}/analyze")
async def analyze_competitor(competitor_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        from ..db_companies import competitor_list, competitor_update
        competitor = next((c for c in competitor_list() if c.get("id") == competitor_id), None)
        if not competitor:
            return JSONResponse({"detail": "Concorrente não encontrado"}, status_code=404)
        provider = get_social_provider()
        handles = competitor.get("handles") or {}
        results = {}
        for platform, handle in handles.items():
            try:
                platform_norm = normalize_platform(platform)
            except Exception:
                continue
            if handle:
                results[platform_norm] = await provider.analyze_profile(platform=platform_norm, handle=str(handle))
        dossier = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "summary": "Análise de concorrente via camada social. Dados dependem das permissões/ferramentas disponíveis no Composio.",
        }
        updated = competitor_update(competitor_id, {
            "metrics": results,
            "dossier": json.dumps(dossier, ensure_ascii=False),
            "last_analyzed_at": dossier["generated_at"],
        })
        return {"competitor": updated, "analysis": dossier}
    except Exception as exc:
        return _error(exc)


@router.delete("/competitors/{competitor_id}")
def delete_competitor(competitor_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    from ..db_companies import competitor_delete
    ok = competitor_delete(competitor_id)
    if not ok:
        return JSONResponse({"detail": "Concorrente não encontrado"}, status_code=404)
    return {"deleted": True}


@router.get("/references")
def list_references(request: Request, brandId: str):
    err = _auth(request)
    if err:
        return err
    try:
        ensure_brand_exists(brandId)
        from ..db_companies import asset_list
        return {"references": asset_list(brandId)}
    except Exception as exc:
        return _error(exc)


@router.post("/references")
async def create_reference(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
        brand_id = body.get("brandId") or body.get("brand_id")
        ensure_brand_exists(brand_id)
        url = (body.get("url") or "").strip()
        if not url:
            return JSONResponse({"detail": "url é obrigatório"}, status_code=422)
        from ..db_companies import asset_create
        ref = asset_create(brand_id, {
            "kind": body.get("kind") or "LINK",
            "source": "REFERENCE",
            "url": url,
            "meta": {
                "role": "social_reference",
                "title": body.get("title") or "",
                "platform": body.get("platform") or "",
                "notes": body.get("notes") or "",
                "tags": body.get("tags") or [],
            },
        })
        return {"reference": ref}
    except Exception as exc:
        return _error(exc)


@router.delete("/references/{reference_id}")
def delete_reference(reference_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    from ..db_companies import asset_delete
    ok = asset_delete(reference_id)
    if not ok:
        return JSONResponse({"detail": "Referência não encontrada"}, status_code=404)
    return {"deleted": True}
