from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .base import SUPPORTED_SOCIAL_PLATFORMS, SocialProviderError
from .composio_provider import ComposioSocialProvider
from .mock_provider import MockSocialProvider


def get_social_provider():
    if (os.environ.get("SOCIAL_PROVIDER") or "").strip().lower() == "mock":
        return MockSocialProvider()
    return ComposioSocialProvider()


def get_request_user_id(request: Any) -> str:
    token = request.headers.get("X-Session-Token") or request.cookies.get("session")
    if token:
        try:
            from ..routers.auth import verify_session_token
            session = verify_session_token(token)
            if session and session.get("user_id"):
                return str(session["user_id"])
        except Exception:
            pass
    return "api"


def normalize_platform(value: str) -> str:
    platform = str(value or "").strip().lower()
    aliases = {"facebook_pages": "facebook", "fb": "facebook", "yt": "youtube", "ig": "instagram"}
    platform = aliases.get(platform, platform)
    if platform not in SUPPORTED_SOCIAL_PLATFORMS:
        raise SocialProviderError(f"Plataforma social não suportada: {value}", status_code=422)
    return platform


def ensure_brand_exists(brand_id: str) -> Dict[str, Any]:
    if not brand_id:
        raise SocialProviderError("brandId é obrigatório.", status_code=422)
    try:
        from ..db_companies import company_get
        company = company_get(brand_id)
        if company:
            return {"kind": "company", "brand": company}
    except Exception:
        pass
    try:
        from ..db_agency import creator_get
        creator = creator_get(brand_id)
        if creator:
            return {"kind": "creator", "brand": creator}
    except Exception:
        pass
    raise SocialProviderError("Marca/empresa não encontrada.", status_code=404)


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_or_none(value: Optional[str]) -> Optional[str]:
    dt = parse_iso_datetime(value)
    return dt.isoformat() if dt else None


def is_future(value: Optional[str]) -> bool:
    dt = parse_iso_datetime(value)
    return bool(dt and dt > datetime.now(timezone.utc))


def _asset_type(url: str, content_type: Optional[str] = None) -> str:
    if content_type in {"image", "video", "carousel", "text"}:
        return content_type
    path = urlparse(url).path
    mime = mimetypes.guess_type(path)[0] or ""
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext in {"mp4", "mov", "webm", "m4v"}:
        return "video"
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "image"
    return "text"


def _platform_requires_media(platform: str, content_type: str) -> bool:
    if platform in {"instagram", "tiktok", "youtube"}:
        return True
    return content_type in {"image", "video", "carousel"}


def _public_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _approved_from_source(source_post_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not source_post_id:
        return None
    try:
        from ..db_companies import post_get
        post = post_get(source_post_id)
        if post:
            return post
    except Exception:
        pass
    return None


def is_approved_payload(body: Dict[str, Any], source_post: Optional[Dict[str, Any]] = None) -> bool:
    if bool(body.get("approved")):
        return True
    status = str(body.get("status") or "").strip().lower()
    if status == "approved":
        return True
    if source_post and str(source_post.get("status") or "").upper() in {"APPROVED", "SCHEDULED"}:
        return True
    return False


async def connect_account(body: Dict[str, Any], request: Any) -> Dict[str, Any]:
    brand_id = body.get("brandId") or body.get("brand_id")
    platform = normalize_platform(body.get("platform"))
    ensure_brand_exists(brand_id)
    return await connect_brand_account(
        brand_id=brand_id,
        platform=platform,
        callback_url=body.get("callbackUrl") or body.get("callback_url"),
        account_name=body.get("accountName") or body.get("account_name"),
    )


async def connect_brand_account(
    *,
    brand_id: str,
    platform: str,
    callback_url: Optional[str] = None,
    account_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria a autorização no escopo da empresa, não do operador da agência."""
    ensure_brand_exists(brand_id)
    platform = normalize_platform(platform)
    user_id = f"brand:{brand_id}"
    provider = get_social_provider()
    result = await provider.connect_account(
        platform=platform,
        user_id=user_id,
        brand_id=brand_id,
        callback_url=callback_url,
    )
    from ..db_agency import social_connection_upsert
    connection = social_connection_upsert({
        "user_id": user_id,
        "brand_id": brand_id,
        "provider": result.provider,
        "platform": platform,
        "external_account_id": result.connected_account_id,
        "external_account_name": account_name,
        "composio_entity_id": result.raw.get("entity_id") or result.raw.get("user_id"),
        "composio_connection_id": result.connected_account_id,
        "status": "pending" if result.redirect_url else "connected",
        "metadata": {
            "redirect_url": result.redirect_url,
            "link_token": result.link_token,
            "expires_at": result.expires_at,
            "raw": result.raw,
        },
    })
    return {
        "connection": connection,
        "redirect_url": result.redirect_url,
        "link_token": result.link_token,
        "expires_at": result.expires_at,
    }


async def handle_connection_callback(payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..db_agency import social_connection_get_by_composio, social_connection_update, social_connection_upsert
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    comp_id = (
        data.get("connected_account_id")
        or data.get("connectedAccountId")
        or data.get("connection_id")
        or data.get("connectionId")
        or data.get("id")
        or metadata.get("connected_account_id")
        or metadata.get("connectedAccountId")
    )
    if not comp_id:
        return {"ok": True, "ignored": True, "detail": "callback sem connected_account_id"}
    status_raw = str(data.get("status") or metadata.get("status") or "connected").lower()
    status = "connected" if status_raw in {"active", "connected", "success", "completed"} else status_raw
    existing = social_connection_get_by_composio(comp_id)
    if existing:
        social_connection_update(existing["id"], {
            "status": status,
            "external_account_id": data.get("external_account_id") or data.get("account_id") or existing.get("external_account_id"),
            "external_account_name": data.get("name") or data.get("account_name") or existing.get("external_account_name"),
            "metadata": {**(existing.get("metadata") or {}), "callback": _safe_log_payload(payload)},
            "last_sync_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"ok": True, "connection": social_connection_get_by_composio(comp_id)}
    brand_id = data.get("brand_id") or data.get("brandId") or metadata.get("brand_id") or metadata.get("brandId")
    platform = data.get("platform") or metadata.get("platform")
    if not brand_id or not platform:
        return {"ok": True, "ignored": True, "detail": "callback sem brand_id/platform para nova conexão"}
    connection = social_connection_upsert({
        "user_id": data.get("user_id") or metadata.get("user_id") or "api",
        "brand_id": brand_id,
        "platform": normalize_platform(platform),
        "provider": "composio",
        "external_account_id": data.get("external_account_id") or data.get("account_id"),
        "external_account_name": data.get("name") or data.get("account_name"),
        "composio_connection_id": comp_id,
        "status": status,
        "metadata": {"callback": _safe_log_payload(payload)},
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "connection": connection}


def list_accounts(brand_id: str, platform: Optional[str] = None) -> Dict[str, Any]:
    ensure_brand_exists(brand_id)
    if platform:
        platform = normalize_platform(platform)
    from ..db_agency import social_connection_list
    return {"accounts": social_connection_list(brand_id=brand_id, platform=platform)}


async def disconnect_account(connection_id: str) -> Dict[str, Any]:
    from ..db_agency import social_connection_get, social_connection_revoke
    connection = social_connection_get(connection_id)
    if not connection:
        raise SocialProviderError("Conta social não encontrada.", status_code=404)
    provider = get_social_provider()
    try:
        if connection.get("provider") == "composio" and connection.get("composio_connection_id"):
            await provider.disconnect_account(composio_connection_id=connection["composio_connection_id"])
    finally:
        social_connection_revoke(connection_id)
    return {"deleted": True}


def _build_assets(asset_urls: List[str], content_type: str) -> List[Dict[str, Any]]:
    assets = []
    for url in asset_urls:
        url = str(url or "").strip()
        if not url:
            continue
        assets.append({
            "asset_url": url,
            "asset_type": _asset_type(url, content_type),
            "storage_provider": "external_url" if _public_url(url) else "internal",
            "mime_type": mimetypes.guess_type(urlparse(url).path)[0],
        })
    return assets


async def create_post(body: Dict[str, Any], request: Any) -> Dict[str, Any]:
    from ..db_agency import social_connection_get, social_post_create, social_post_log_create
    brand_id = body.get("brandId") or body.get("brand_id")
    ensure_brand_exists(brand_id)
    source_post = _approved_from_source(body.get("sourcePostId") or body.get("source_post_id"))
    approved = is_approved_payload(body, source_post)
    scheduled_at = iso_or_none(body.get("scheduledAt") or body.get("scheduled_at"))
    asset_urls = body.get("assetUrls") or body.get("asset_urls") or []
    if isinstance(asset_urls, str):
        asset_urls = [asset_urls]
    content_type = str(body.get("contentType") or body.get("content_type") or "").strip().lower()
    if not content_type:
        content_type = _asset_type(asset_urls[0], None) if asset_urls else "text"
    if content_type not in {"image", "video", "carousel", "text", "story"}:
        raise SocialProviderError("contentType inválido.", status_code=422)

    channels = []
    for item in body.get("channels") or []:
        conn_id = item.get("socialConnectionId") or item.get("social_connection_id") or item.get("id")
        connection = social_connection_get(conn_id)
        if not connection:
            raise SocialProviderError("Conta social não encontrada para um dos canais.", status_code=422)
        platform = normalize_platform(item.get("platform") or connection.get("platform"))
        if connection.get("brand_id") != brand_id:
            raise SocialProviderError("Conta social pertence a outra marca.", status_code=403)
        if connection.get("status") not in {"connected", "active"}:
            raise SocialProviderError(f"Conta {platform} não está conectada.", status_code=422)
        if _platform_requires_media(platform, content_type) and not asset_urls:
            raise SocialProviderError(f"{platform} exige mídia pública para publicar.", status_code=422)
        for url in asset_urls:
            if _platform_requires_media(platform, content_type) and not _public_url(url):
                raise SocialProviderError(f"{platform} exige URL pública/acessível da mídia.", status_code=422)
        channels.append({"social_connection_id": conn_id, "platform": platform})

    publish_now = not scheduled_at or not is_future(scheduled_at)
    if (publish_now or scheduled_at) and not channels:
        raise SocialProviderError("Selecione pelo menos um canal social.", status_code=422)
    if (publish_now or scheduled_at) and not approved:
        raise SocialProviderError("Post precisa estar aprovado antes de publicar/agendar.", status_code=422)

    caption = body.get("caption")
    if caption is None and source_post:
        tags = source_post.get("hashtags") or []
        caption = " ".join([source_post.get("copy") or "", " ".join(tags)]).strip()

    status = "draft"
    if approved:
        status = "scheduled" if scheduled_at and is_future(scheduled_at) else "approved"
    post = social_post_create({
        "user_id": get_request_user_id(request),
        "brand_id": brand_id,
        "source_post_id": body.get("sourcePostId") or body.get("source_post_id"),
        "title": body.get("title") or (source_post or {}).get("title"),
        "caption": caption or "",
        "content_type": content_type,
        "status": status,
        "scheduled_at": scheduled_at,
        "metadata": {
            "source_status": (source_post or {}).get("status"),
            "tags": body.get("tags") or [],
            "made_for_kids": bool(body.get("madeForKids", False)),
            "collaborators": body.get("collaborators") or body.get("collab") or [],   # COLLAB: @ do influencer
            "also_story": bool(body.get("alsoStory") or body.get("also_story")),       # republicar no story (opção)
            "story_url": body.get("storyUrl") or body.get("story_url") or "",          # 9:16 bonito p/ o story-repost
        },
        "assets": _build_assets(asset_urls, content_type),
        "channels": channels,
    })
    social_post_log_create(post["id"], "Post social criado.", payload={"status": status, "channels": len(channels)})
    if publish_now and approved:
        task = asyncio.create_task(publish_social_post(post["id"]))
        _log_publish_task_error(task, post["id"])
        social_post_log_create(post["id"], "Publicação imediata enviada para o worker social.")
        post = {**post, "publish_started": True}
    return {"post": post}


def _log_publish_task_error(task: "asyncio.Task", post_id: str) -> None:
    """Captura exceções da task fire-and-forget para que erros de publicação
    não fiquem silenciosos (sem log) quando acontecem antes do try/except do worker."""
    def _cb(t: "asyncio.Task") -> None:
        exc = t.exception()
        if exc:
            logging.getLogger("caripost.social").error(
                "[publish_task] post_id=%s falhou: %s", post_id, exc
            )
            try:
                from ..db_agency import social_post_log_create
                social_post_log_create(post_id, f"Erro na task de publicação: {exc}", level="error")
            except Exception:
                pass
    task.add_done_callback(_cb)


async def publish_social_post(post_id: str, *, already_acquired: bool = False) -> Dict[str, Any]:
    from ..db_agency import (
        social_channel_update,
        social_connection_get,
        social_post_acquire_for_publish,
        social_post_finalize,
        social_post_get,
        social_post_log_create,
        social_post_update,
    )
    post = social_post_get(post_id)
    if not post:
        raise SocialProviderError("Post social não encontrado.", status_code=404)
    if post.get("status") not in {"approved", "scheduled", "publishing"}:
        raise SocialProviderError("Post precisa estar aprovado antes de publicar.", status_code=422)
    if not already_acquired and post.get("status") != "publishing":
        if not social_post_acquire_for_publish(post_id):
            post = social_post_get(post_id)
            return {"post": post, "skipped": True}
    else:
        social_post_update(post_id, {"status": "publishing"})

    provider = get_social_provider()
    max_attempts = max(1, min(int(os.environ.get("SOCIAL_PUBLISH_MAX_ATTEMPTS", "2") or "2"), 5))
    post = social_post_get(post_id)
    for channel in post.get("channels") or []:
        if channel.get("status") == "published":
            continue
        connection = social_connection_get(channel["social_connection_id"])
        if not connection or connection.get("brand_id") != post.get("brand_id"):
            social_channel_update(channel["id"], {"status": "failed", "error_message": "Conexão social inválida para esta marca."})
            social_post_log_create(post_id, "Conexão inválida para canal.", channel_id=channel["id"], level="error")
            continue
        if connection.get("status") not in {"connected", "active"}:
            social_channel_update(channel["id"], {"status": "failed", "error_message": "Conta social expirada/revogada."})
            social_post_log_create(post_id, "Conta social expirada/revogada.", channel_id=channel["id"], level="error")
            continue
        platform = normalize_platform(channel.get("platform") or connection.get("platform"))
        if _platform_requires_media(platform, post.get("content_type") or "text") and not post.get("assets"):
            social_channel_update(channel["id"], {"status": "failed", "error_message": f"{platform} exige mídia pública."})
            social_post_log_create(post_id, f"{platform} exige mídia pública.", channel_id=channel["id"], level="error")
            continue

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                social_channel_update(channel["id"], {"status": "publishing", "retry_count": attempt - 1, "error_message": None})
                social_post_log_create(post_id, f"Publicando em {platform} via {connection.get('provider')}.", channel_id=channel["id"], payload={"attempt": attempt})
                result = await provider.publish_post(post=post, channel=channel, connection=connection)
                social_channel_update(channel["id"], {
                    "status": "published",
                    "external_post_id": result.external_post_id,
                    "external_post_url": result.external_post_url,
                    "metadata": result.raw,
                    "error_message": None,
                })
                social_post_log_create(post_id, f"Publicado em {platform}.", channel_id=channel["id"], payload={
                    "external_post_id": result.external_post_id,
                    "external_post_url": result.external_post_url,
                    "status": result.status,
                })
                break
            except Exception as exc:
                last_error = str(getattr(exc, "message", exc))
                social_channel_update(channel["id"], {"status": "failed", "retry_count": attempt, "error_message": last_error})
                social_post_log_create(post_id, f"Falha ao publicar em {platform}: {last_error}", channel_id=channel["id"], level="error", payload={"attempt": attempt})
                if attempt < max_attempts:
                    await asyncio.sleep(min(2 * attempt, 5))
        if last_error:
            continue
    final_post = social_post_finalize(post_id)
    return {"post": final_post}


async def process_due_social_posts() -> Dict[str, Any]:
    from ..db_agency import social_post_acquire_for_publish, social_post_due, social_post_log_create
    now = datetime.now(timezone.utc).isoformat()
    due = social_post_due(now)
    triggered = 0
    for post in due:
        post_id = post["id"]
        if not social_post_acquire_for_publish(post_id, from_statuses=["scheduled"]):
            continue
        social_post_log_create(post_id, "Worker social iniciou publicação agendada.")
        await publish_social_post(post_id, already_acquired=True)
        triggered += 1
    return {"triggered": triggered, "checked_at": now}


def post_status(post_id: str) -> Dict[str, Any]:
    from ..db_agency import social_post_get
    post = social_post_get(post_id)
    if not post:
        raise SocialProviderError("Post social não encontrado.", status_code=404)
    return {"post": post}


async def post_metrics(post_id: str) -> Dict[str, Any]:
    from ..db_agency import social_connection_get, social_post_get
    post = social_post_get(post_id, include_logs=False)
    if not post:
        raise SocialProviderError("Post social não encontrado.", status_code=404)
    provider = get_social_provider()
    metrics = []
    for channel in post.get("channels") or []:
        connection = social_connection_get(channel["social_connection_id"])
        if not connection:
            continue
        try:
            data = await provider.get_post_metrics(post=post, channel=channel, connection=connection)
        except Exception as exc:
            data = {"error": str(getattr(exc, "message", exc))}
        metrics.append({"channel_id": channel["id"], "platform": channel["platform"], "metrics": data})
    return {"post_id": post_id, "metrics": metrics}


def _safe_log_payload(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if any(s in str(key).lower() for s in ("token", "secret", "password", "api_key", "authorization")):
                clean[key] = "***"
            else:
                clean[key] = _safe_log_payload(item)
        return clean
    if isinstance(value, list):
        return [_safe_log_payload(v) for v in value[:100]]
    return value
