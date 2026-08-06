from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..social.base import SUPPORTED_SOCIAL_PLATFORMS, SocialProviderError
from ..social.service import (
    connect_account,
    connect_brand_account,
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


def _invite_secret() -> bytes:
    from .auth import SESSION_SECRET
    return SESSION_SECRET.encode()


def _make_invite_token(brand_id: str, platform: str, expires_at: int) -> str:
    payload = json.dumps({
        "brand_id": brand_id,
        "platform": platform,
        "exp": expires_at,
        "nonce": os.urandom(8).hex(),
    }, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(_invite_secret(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + signature


def _read_invite_token(token: str) -> Optional[dict]:
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(_invite_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw.decode())
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        ensure_brand_exists(str(payload.get("brand_id") or ""))
        normalize_platform(str(payload.get("platform") or ""))
        return payload
    except Exception:
        return None


def _public_base(request: Request) -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if not base:
        try:
            from ..db import get_setting
            base = (get_setting("render.public_base") or "").strip().rstrip("/")
        except Exception:
            base = ""
    return base or "https://caripost.cariap.com.br"


def _invite_page(title: str, detail: str, *, token: str = "", error: bool = False) -> HTMLResponse:
    action = (
        f'<form method="post" action="/api/social/connect-invite/{escape(token)}/start">'
        '<button type="submit">Conectar Instagram</button></form>'
        if token and not error else ""
    )
    color = "#ef4444" if error else "#ff7a18"
    return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Caripost</title><style>
body{{margin:0;background:#0b0910;color:#fff;font:16px system-ui;display:grid;min-height:100vh;place-items:center}}
main{{width:min(520px,calc(100% - 40px));background:#17131f;border:1px solid #342b43;border-radius:20px;padding:32px;text-align:center}}
b{{color:{color}}}p{{color:#cbd5e1;line-height:1.6}}button{{border:0;border-radius:12px;padding:15px 24px;
background:#ff7a18;color:#fff;font-weight:800;font-size:16px;cursor:pointer;width:100%}}
small{{display:block;color:#8b8199;margin-top:18px}}</style></head><body><main>
<b>CARIPOST</b><h1>{escape(title)}</h1><p>{escape(detail)}</p>{action}
<small>A autorização acontece no ambiente oficial do Instagram/Meta via Composio. O Caripost não recebe sua senha.</small>
</main></body></html>""")


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, SocialProviderError):
        return JSONResponse({"detail": exc.message, **(exc.detail or {})}, status_code=exc.status_code)
    # Surface the real error instead of swallowing it into a bare 500.
    import logging
    import traceback
    logging.getLogger("caripost.social").error("social error: %s\n%s", exc, traceback.format_exc())
    return JSONResponse({"detail": str(exc) or exc.__class__.__name__, "error_type": exc.__class__.__name__}, status_code=500)


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
    from ..social.composio_provider import ComposioConfig
    composio_config = ComposioConfig.from_env()
    return {
        "enabled": (os.environ.get("SOCIAL_COMPOSIO_ENABLED", "1") != "0"),
        "provider": (os.environ.get("SOCIAL_PROVIDER") or "composio"),
        "composio_configured": bool(composio_config.api_key),
        "platforms": sorted(SUPPORTED_SOCIAL_PLATFORMS),
    }


@router.get("/workspace")
def workspace(request: Request, brandId: str):
    from ..main_utils import company_access_denied as _cad
    _d = _cad(request, brandId)
    if _d:
        return _d
    err = _auth(request)
    if err:
        return err
    try:
        ensure_brand_exists(brandId)
        from ..db_agency import social_connection_list, social_post_list
        from ..db_companies import (
            asset_list,
            company_get,
            competitor_list,
            post_list,
            report_get_latest,
        )
        company = company_get(brandId)
        if not company:
            return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
        return {
            "company": company,
            "accounts": social_connection_list(brand_id=brandId),
            "competitors": competitor_list(brandId),
            "references": asset_list(brandId),
            "strategy": report_get_latest(brandId, "SOCIAL_STRATEGY"),
            "posts": post_list(company_id=brandId, limit=50),
            "social_posts": social_post_list(brand_id=brandId, limit=50),
        }
    except Exception as exc:
        return _error(exc)


@router.post("/brands/{brand_id}/analyze")
async def analyze_brand(brand_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from ..db_companies import (
            asset_list,
            brand_kit_apply_auto,
            company_get,
            company_update,
            competitor_list,
            competitor_update,
            report_create,
        )
        from ..services.ai import generate_social_strategy

        company = company_get(brand_id)
        if not company:
            return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)

        instagram = (body.get("instagram") or body.get("social_instagram") or "").strip()
        if instagram:
            socials = dict(company.get("socials") or {})
            socials["instagram"] = instagram
            company = company_update(brand_id, {"socials": socials}) or company

        provider = get_social_provider()
        socials = company.get("socials") or {}
        own_profile = {"handle": socials.get("instagram") or instagram, "platform": "instagram"}
        if own_profile.get("handle"):
            try:
                own_profile["analysis"] = await provider.analyze_profile(platform="instagram", handle=str(own_profile["handle"]))
            except Exception as exc:
                own_profile["error"] = str(getattr(exc, "message", exc))

        competitor_profiles = []
        for comp in competitor_list(brand_id):
            handles = comp.get("handles") or {}
            item = {"id": comp.get("id"), "name": comp.get("name"), "handles": handles, "results": {}}
            for platform, handle in handles.items():
                if not handle:
                    continue
                try:
                    platform_norm = normalize_platform(platform)
                except Exception:
                    continue
                try:
                    item["results"][platform_norm] = await provider.analyze_profile(platform=platform_norm, handle=str(handle))
                except Exception as exc:
                    item["results"][platform_norm] = {"error": str(getattr(exc, "message", exc))}
            if item["results"]:
                competitor_update(comp["id"], {
                    "metrics": item["results"],
                    "dossier": json.dumps(item, ensure_ascii=False),
                    "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
                })
            competitor_profiles.append(item)

        refs = asset_list(brand_id)
        try:
            strategy_payload = generate_social_strategy(company, own_profile, competitor_profiles, refs)
        except Exception as ai_exc:
            import logging
            import traceback
            logging.getLogger("caripost.social").error(
                "analyze strategy failed: %s\n%s", ai_exc, traceback.format_exc()
            )
            return JSONResponse(
                {
                    "detail": f"Falha ao gerar a estratégia com IA: {ai_exc}",
                    "error_type": ai_exc.__class__.__name__,
                    "own_profile": own_profile,
                    "competitors": competitor_profiles,
                },
                status_code=502,
            )
        report = report_create(brand_id, "SOCIAL_STRATEGY", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "own_profile": own_profile,
            "competitors": competitor_profiles,
            "strategy": strategy_payload,
        })

        if body.get("applyBrandKit", True):
            identity = strategy_payload.get("brand_identity") or {}
            colors = identity.get("colors")
            normalized_colors = {}
            if isinstance(colors, list):
                if len(colors) > 0:
                    normalized_colors["primary"] = colors[0]
                if len(colors) > 1:
                    normalized_colors["secondary"] = colors[1]
                if len(colors) > 2:
                    normalized_colors["accent"] = colors[2]
            elif isinstance(colors, dict):
                normalized_colors = colors
            # A LOGO é a verdade da marca: se houver logo, a cor real dela vence o palpite da IA
            # (era daqui que saíam cores totalmente erradas — azul/laranja inventados p/ a Gironetfibra).
            try:
                from .companies import _company_logo_colors
                _lc = _company_logo_colors(brand_id)
                if _lc:
                    normalized_colors = _lc
            except Exception:
                pass
            auto_update = {
                key: value for key, value in {
                    "voice": identity.get("voice") or "",
                    "persona": identity.get("persona") or identity.get("positioning") or "",
                    "visual_prompt_base": identity.get("visual_prompt_base") or "",
                }.items() if value
            }
            if normalized_colors:
                auto_update["colors"] = normalized_colors
            # Análise social é automática: nunca pode apagar uma paleta/voz já curada manualmente.
            brand_kit_apply_auto(brand_id, auto_update)

        return {"report": report, "strategy": strategy_payload}
    except Exception as exc:
        return _error(exc)


@router.post("/brands/{brand_id}/generate-drafts")
async def generate_brand_drafts(brand_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from ..db_companies import company_get, post_create, report_get_latest
        company = company_get(brand_id)
        if not company:
            return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
        report = report_get_latest(brand_id, "SOCIAL_STRATEGY")
        if not report:
            return JSONResponse({"detail": "Gere a análise social antes de criar os rascunhos."}, status_code=422)
        payload = report.get("payload") or {}
        strategy = payload.get("strategy") or {}
        ideas = strategy.get("post_ideas") or []
        if not ideas:
            return JSONResponse({"detail": "A estratégia não contém ideias de posts."}, status_code=422)
        limit = max(1, min(int(body.get("count") or 4), 12))
        created = []
        for idea in ideas[:limit]:
            hashtags = idea.get("hashtags") or []
            if isinstance(hashtags, list):
                hashtags = " ".join(str(h) for h in hashtags)
            networks = [idea.get("network") or "instagram"]
            if body.get("networks"):
                networks = body.get("networks")
            post = post_create({
                "company_id": brand_id,
                "status": "REVIEW",
                "title": idea.get("title") or "Ideia social",
                "copy": idea.get("caption") or idea.get("copy") or "",
                "hashtags": hashtags,
                "networks": networks,
                "scheduled_at": body.get("scheduledAt") or body.get("scheduled_at"),
            })
            created.append(post)
        return {"created": created}
    except Exception as exc:
        return _error(exc)


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


@router.post("/connect-invite")
async def create_connect_invite(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    brand_id = str(body.get("brandId") or body.get("brand_id") or "").strip()
    denied = None
    try:
        from ..main_utils import company_access_denied
        denied = company_access_denied(request, brand_id)
    except Exception:
        pass
    if denied:
        return denied
    try:
        platform = normalize_platform(body.get("platform") or "instagram")
        brand = ensure_brand_exists(brand_id)
        expires_at = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
        token = _make_invite_token(brand_id, platform, expires_at)
        return {
            "url": f"{_public_base(request)}/api/social/connect-invite/{token}",
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "company": (brand.get("brand") or {}).get("name"),
            "platform": platform,
        }
    except Exception as exc:
        return _error(exc)


@router.get("/connect-invite/{token}")
def connect_invite_page(token: str):
    payload = _read_invite_token(token)
    if not payload:
        return _invite_page("Link inválido ou expirado", "Peça um novo link à sua agência.", error=True)
    from ..db_companies import company_get
    company = company_get(payload["brand_id"]) or {}
    return _invite_page(
        "Conectar Instagram",
        f"Autorize o Instagram profissional da empresa {company.get('name') or 'no Caripost'}.",
        token=token,
    )


@router.post("/connect-invite/{token}/start")
async def start_connect_invite(token: str, request: Request):
    payload = _read_invite_token(token)
    if not payload:
        return _invite_page("Link inválido ou expirado", "Peça um novo link à sua agência.", error=True)
    try:
        result = await connect_brand_account(
            brand_id=payload["brand_id"],
            platform=payload["platform"],
            callback_url=f"{_public_base(request)}/api/social/callback",
        )
        redirect_url = result.get("redirect_url")
        if not redirect_url:
            return _invite_page("Conta conectada", "A autorização foi concluída. Você já pode fechar esta página.")
        return RedirectResponse(redirect_url, status_code=303)
    except Exception as exc:
        message = getattr(exc, "message", str(exc)) or "Não foi possível iniciar a autorização."
        return _invite_page("Não foi possível conectar", message, error=True)


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
