from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .base import ConnectAccountResult, PublishResult, SocialProviderError, SocialProviderNotConfigured


PLATFORM_TOOLKITS = {
    "instagram": "instagram",
    "facebook": "facebook",
    "youtube": "youtube",
    "tiktok": "tiktok",
}


def _setting_value(key: str, *, decrypt_value: bool = False) -> str:
    try:
        from ..db import settings_get
        row = settings_get(key=key)
    except Exception:
        return ""
    value = str((row or {}).get("value") or "").strip()
    if not value:
        return ""
    if decrypt_value:
        try:
            from ..security.encryption import decrypt
            return (decrypt(value) or value).strip()
        except Exception:
            return value
    return value


@dataclass
class ComposioConfig:
    api_key: str
    base_url: str
    project_id: str = ""

    @classmethod
    def from_env(cls) -> "ComposioConfig":
        base = (os.environ.get("COMPOSIO_BASE_URL") or "https://backend.composio.dev").strip().rstrip("/")
        if not base.endswith("/api/v3.1"):
            base = base + "/api/v3.1"
        return cls(
            api_key=(_setting_value("social.apiKey.composio", decrypt_value=True)
                     or _setting_value("token:composio")
                     or os.environ.get("COMPOSIO_API_KEY")
                     or "").strip(),
            base_url=base,
            project_id=(os.environ.get("COMPOSIO_PROJECT_ID") or "").strip(),
        )


class ComposioSocialProvider:
    provider = "composio"

    def __init__(self, config: Optional[ComposioConfig] = None):
        self.config = config or ComposioConfig.from_env()
        self._tool_cache: Dict[Tuple[str, str], str] = {}

    def _ensure_configured(self) -> None:
        if not self.config.api_key:
            raise SocialProviderNotConfigured()

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "content-type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        self._ensure_configured()
        url = self.config.base_url + path
        try:
            import httpx
        except ImportError as exc:
            raise SocialProviderError("Dependência httpx não instalada no ambiente.", status_code=500) from exc
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                res = await client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise SocialProviderError(f"Falha ao chamar Composio: {exc}", status_code=502) from exc
        try:
            data = res.json()
        except Exception:
            data = {"text": res.text}
        if res.status_code >= 400:
            message = self._extract_error(data) or f"Composio retornou HTTP {res.status_code}"
            raise SocialProviderError(message, status_code=502, detail={"composio_status": res.status_code})
        return data if isinstance(data, dict) else {"data": data}

    def _cached_auth_config_id(self, platform: str) -> str:
        """Read a previously configured/created auth config id. Never raises."""
        upper = platform.upper()
        env_candidates = [
            f"COMPOSIO_AUTH_CONFIG_{upper}",
            f"COMPOSIO_{upper}_AUTH_CONFIG_ID",
            f"COMPOSIO_AUTH_CONFIG_ID_{upper}",
            f"{upper}_COMPOSIO_AUTH_CONFIG_ID",
        ]
        for key in env_candidates:
            value = (os.environ.get(key) or "").strip()
            if value:
                return value
        setting_candidates = [
            f"composio.authConfig.{platform}",
            f"composio.auth_config.{platform}",
            f"token:composio_auth_config_{platform}",
            f"token:composio_{platform}_auth_config",
        ]
        for key in setting_candidates:
            value = _setting_value(key)
            if value:
                return value
        return ""

    @staticmethod
    def _save_auth_config_id(platform: str, auth_config_id: str) -> None:
        if not auth_config_id:
            return
        try:
            from datetime import datetime, timezone
            from ..db import settings_set
            settings_set(
                key=f"composio.authConfig.{platform}",
                value=auth_config_id,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            pass

    @staticmethod
    def _extract_auth_config_id(data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("id", "uuid", "nanoid"):
            v = data.get(key)
            if v:
                return str(v)
        nested = data.get("auth_config") or data.get("authConfig")
        if isinstance(nested, dict):
            for key in ("id", "uuid", "nanoid"):
                v = nested.get(key)
                if v:
                    return str(v)
        return ""

    async def ensure_auth_config(self, platform: str) -> str:
        """Return an auth config id for the platform, reusing or creating a
        Composio-managed one so connecting works with just the API key."""
        cached = self._cached_auth_config_id(platform)
        if cached:
            return cached
        toolkit = PLATFORM_TOOLKITS.get(platform, platform)
        # 1) Reuse an existing auth config for this toolkit, if any.
        try:
            listing = await self._request("GET", "/auth_configs", params={"toolkit_slug": toolkit})
            items = listing.get("items") or listing.get("data") or []
            if isinstance(items, list):
                for item in items:
                    cid = self._extract_auth_config_id(item if isinstance(item, dict) else {})
                    if cid:
                        self._save_auth_config_id(platform, cid)
                        return cid
        except SocialProviderError:
            pass  # fall through to creation
        # 2) Create a Composio-managed auth config (no own OAuth app needed).
        try:
            created = await self._request("POST", "/auth_configs", json={
                "toolkit": {"slug": toolkit},
                "auth_config": {"type": "use_composio_managed_auth", "name": f"caripost-{toolkit}"},
            })
        except SocialProviderError as exc:
            raise SocialProviderError(
                f"Não consegui criar a conexão gerenciada do Composio para {platform}. "
                f"{platform} pode exigir um app próprio (ex.: Meta para Instagram/Facebook). "
                f"Detalhe do Composio: {getattr(exc, 'message', exc)}",
                status_code=422,
                detail=getattr(exc, "detail", None),
            ) from exc
        cid = self._extract_auth_config_id(created)
        if not cid:
            raise SocialProviderError(
                f"Composio criou o auth config de {platform} mas não retornou um id reconhecível.",
                status_code=502,
            )
        self._save_auth_config_id(platform, cid)
        return cid

    async def connect_account(
        self,
        *,
        platform: str,
        user_id: str,
        brand_id: str,
        callback_url: Optional[str] = None,
    ) -> ConnectAccountResult:
        auth_config_id = await self.ensure_auth_config(platform)
        body: Dict[str, Any] = {
            "auth_config_id": auth_config_id,
            "user_id": user_id,
            "alias": f"{brand_id}-{platform}",
            "connection_data": {"brand_id": brand_id, "platform": platform},
        }
        if callback_url:
            body["callback_url"] = callback_url
        data = await self._request("POST", "/connected_accounts/link", json=body)
        return ConnectAccountResult(
            provider=self.provider,
            platform=platform,
            user_id=user_id,
            brand_id=brand_id,
            redirect_url=data.get("redirect_url"),
            link_token=data.get("link_token"),
            connected_account_id=data.get("connected_account_id"),
            expires_at=data.get("expires_at"),
            raw=self._safe_payload(data),
        )

    async def disconnect_account(self, *, composio_connection_id: str) -> None:
        if not composio_connection_id:
            return
        await self._request("DELETE", f"/connected_accounts/{composio_connection_id}")

    async def publish_post(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> PublishResult:
        platform = channel.get("platform") or connection.get("platform")
        if platform == "instagram":
            return await self._publish_instagram(post, channel, connection)
        # Fallback genérico para outras plataformas (texto/instrução)
        tool_slug = await self._resolve_tool_slug(platform, "publish")
        media_urls = [a.get("asset_url") for a in post.get("assets") or [] if a.get("asset_url")]
        text = self._publish_instruction(platform, post, media_urls)
        payload = {
            "connected_account_id": connection.get("composio_connection_id"),
            "user_id": connection.get("user_id") or post.get("user_id") or "api",
            "text": text,
            "allow_tracing": False,
        }
        data = await self._request("POST", f"/tools/execute/{tool_slug}", json=payload)
        if data.get("successful") is False:
            raise SocialProviderError(self._extract_error(data) or "Composio não confirmou a publicação.", status_code=502)
        raw_data = data.get("data") if isinstance(data.get("data"), dict) else data
        return PublishResult(
            provider=self.provider,
            platform=platform,
            external_post_id=self._pick(raw_data, ["id", "post_id", "media_id", "video_id", "run_id"]),
            external_post_url=self._pick(raw_data, ["url", "permalink", "share_url", "html_url", "external_url"]),
            status=str(raw_data.get("status") or "published"),
            raw=self._safe_payload(data),
        )

    async def _publish_instagram(self, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> PublishResult:
        """Instagram exige 2 passos estruturados via Composio:
        1) INSTAGRAM_POST_IG_USER_MEDIA — cria o container com image_url/video_url + caption
        2) INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH — publica o container (creation_id)

        Composio v3.1 exige que os parâmetros da tool vão dentro de 'arguments'.
        O ig_user_id é obtido automaticamente via INSTAGRAM_GET_USER_INFO.
        A imagem é re-hosteada em URL pública (Imgur) porque o Instagram não
        consegue buscar de URLs internas/privadas.
        """
        import logging
        log = logging.getLogger("caripost.social")
        composio_conn_id = connection.get("composio_connection_id")
        user_id = connection.get("user_id") or post.get("user_id") or "api"
        media_urls = [a.get("asset_url") for a in post.get("assets") or [] if a.get("asset_url")]
        content_type = (post.get("content_type") or "image").lower()
        caption = post.get("caption") or ""

        if not media_urls:
            raise SocialProviderError(
                "Instagram exige mídia pública (image_url ou video_url). Sem mídia, não é possível publicar.",
                status_code=422,
            )

        media_url = media_urls[0]
        is_video = content_type == "video"

        # Slugs explícitos (docs.composio.dev/toolkits/instagram)
        create_slug = (os.environ.get("COMPOSIO_TOOL_INSTAGRAM_CREATE_MEDIA") or "").strip()
        if not create_slug:
            create_slug = "INSTAGRAM_POST_IG_USER_MEDIA"
        publish_slug = (os.environ.get("COMPOSIO_TOOL_INSTAGRAM_PUBLISH_MEDIA") or "").strip()
        if not publish_slug:
            publish_slug = "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH"

        # Buscar ig_user_id automaticamente
        ig_user_id = await self._get_instagram_user_id(composio_conn_id, user_id, connection)
        log.info("[composio/instagram] ig_user_id=%s", ig_user_id)

        # Re-hostear imagem em URL pública se necessário (Instagram não busca de URLs internas)
        if not _is_publicly_accessible_url(media_url):
            log.info("[composio/instagram] re-hosteando mídia: %s", media_url)
            media_url = await _rehost_media(media_url, is_video)
            if not media_url:
                raise SocialProviderError(
                    "Não foi possível publicar a imagem em URL pública acessível pelo Instagram. "
                    "Configure IMGUR_CLIENT_ID ou verifique se a mídia está em URL pública.",
                    status_code=502,
                )
            log.info("[composio/instagram] mídia re-hosteada: %s", media_url)

        # Passo 1: criar media container (parâmetros dentro de 'arguments')
        create_args: Dict[str, Any] = {
            "ig_user_id": ig_user_id,
            "caption": caption,
        }
        if is_video:
            create_args["video_url"] = media_url
            create_args["media_type"] = "REELS"
        else:
            create_args["image_url"] = media_url

        create_payload: Dict[str, Any] = {
            "connected_account_id": composio_conn_id,
            "user_id": user_id,
            "arguments": create_args,
            "allow_tracing": False,
        }

        log.info("[composio/instagram] passo 1: criar container slug=%s url=%s is_video=%s", create_slug, media_url, is_video)
        create_resp = await self._request("POST", f"/tools/execute/{create_slug}", json=create_payload)
        if create_resp.get("successful") is False:
            err_msg = self._extract_error(create_resp) or "Composio não criou o container de mídia do Instagram."
            log.error("[composio/instagram] passo 1 falhou: %s", err_msg)
            raise SocialProviderError(err_msg, status_code=502, detail={"step": "create_container", "composio": self._safe_payload(create_resp)})

        create_data = create_resp.get("data") if isinstance(create_resp.get("data"), dict) else create_resp
        creation_id = self._pick(create_data, ["id", "creation_id", "container_id", "media_id"])
        if not creation_id:
            err_msg = "Composio criou o container mas não retornou creation_id."
            log.error("[composio/instagram] passo 1 sem creation_id: %s", self._safe_payload(create_resp))
            raise SocialProviderError(err_msg, status_code=502, detail={"step": "create_container", "composio": self._safe_payload(create_resp)})
        log.info("[composio/instagram] passo 1 ok: creation_id=%s", creation_id)

        # Passo 2: publicar o container (parâmetros dentro de 'arguments')
        publish_payload: Dict[str, Any] = {
            "connected_account_id": composio_conn_id,
            "user_id": user_id,
            "arguments": {
                "creation_id": str(creation_id),
                "max_wait_seconds": 120 if is_video else 30,
            },
            "allow_tracing": False,
        }
        log.info("[composio/instagram] passo 2: publicar creation_id=%s", creation_id)
        pub_resp = await self._request("POST", f"/tools/execute/{publish_slug}", json=publish_payload)
        if pub_resp.get("successful") is False:
            err_msg = self._extract_error(pub_resp) or "Composio não publicou o container no Instagram."
            log.error("[composio/instagram] passo 2 falhou: %s", err_msg)
            raise SocialProviderError(err_msg, status_code=502, detail={"step": "publish", "creation_id": creation_id, "composio": self._safe_payload(pub_resp)})

        pub_data = pub_resp.get("data") if isinstance(pub_resp.get("data"), dict) else pub_resp
        ext_id = self._pick(pub_data, ["id", "post_id", "media_id", "ig_media_id"])
        ext_url = self._pick(pub_data, ["permalink", "url", "share_url", "html_url", "external_url"])
        log.info("[composio/instagram] passo 2 ok: id=%s url=%s", ext_id, ext_url)
        return PublishResult(
            provider=self.provider,
            platform="instagram",
            external_post_id=ext_id,
            external_post_url=ext_url,
            status=str(pub_data.get("status") or "published"),
            raw=self._safe_payload(pub_resp),
        )

    async def _get_instagram_user_id(self, composio_conn_id: str, user_id: str, connection: Dict[str, Any]) -> str:
        """Obtém o IG User ID automaticamente via INSTAGRAM_GET_USER_INFO.

        Cacheia no metadata da conexão para evitar chamadas repetidas.
        """
        import logging
        log = logging.getLogger("caripost.social")

        # Tenta do cache na conexão
        meta = connection.get("metadata") or {}
        cached_ig_id = meta.get("ig_user_id")
        if cached_ig_id:
            return str(cached_ig_id)

        # Busca via Composio
        try:
            resp = await self._request("POST", "/tools/execute/INSTAGRAM_GET_USER_INFO", json={
                "connected_account_id": composio_conn_id,
                "user_id": user_id,
                "arguments": {"ig_user_id": "me"},
                "allow_tracing": False,
            })
            if resp.get("successful") is not False:
                data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
                ig_id = self._pick(data, ["id", "ig_id", "ig_user_id"])
                if ig_id:
                    # Cacheia na conexão
                    try:
                        from ..db_agency import social_connection_update
                        social_connection_update(connection["id"], {"metadata": {**meta, "ig_user_id": str(ig_id)}})
                    except Exception:
                        pass
                    return str(ig_id)
        except Exception as exc:
            log.warning("[composio/instagram] não foi possível obter ig_user_id: %s", exc)

        return "me"

    async def get_post_status(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        platform = channel.get("platform") or connection.get("platform")
        tool_slug = await self._resolve_tool_slug(platform, "status", required=False)
        if not tool_slug:
            return {"available": False, "detail": f"Ferramenta de status não configurada para {platform}."}
        text = (
            f"Verifique o status da publicação {channel.get('external_post_id') or channel.get('external_post_url')} "
            f"no {platform}. Retorne status, URL e qualquer erro público."
        )
        data = await self._request("POST", f"/tools/execute/{tool_slug}", json={
            "connected_account_id": connection.get("composio_connection_id"),
            "user_id": connection.get("user_id") or post.get("user_id") or "api",
            "text": text,
            "allow_tracing": False,
        })
        return self._safe_payload(data)

    async def get_post_metrics(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        platform = channel.get("platform") or connection.get("platform")
        tool_slug = await self._resolve_tool_slug(platform, "metrics", required=False)
        if not tool_slug:
            return {"available": False, "detail": f"Ferramenta de métricas não configurada para {platform}."}
        target = channel.get("external_post_id") or channel.get("external_post_url")
        data = await self._request("POST", f"/tools/execute/{tool_slug}", json={
            "connected_account_id": connection.get("composio_connection_id"),
            "user_id": connection.get("user_id") or post.get("user_id") or "api",
            "text": f"Busque métricas públicas e de conta para a publicação {target} em {platform}.",
            "allow_tracing": False,
        })
        return self._safe_payload(data)

    async def analyze_profile(self, *, platform: str, handle: str, connection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tool_slug = await self._resolve_tool_slug(platform, "metrics", required=False)
        if not tool_slug:
            return {"available": False, "detail": f"Ferramenta de análise não configurada para {platform}.", "handle": handle}
        payload = {
            "user_id": (connection or {}).get("user_id") or "api",
            "text": (
                f"Analise o perfil público {handle} no {platform}. Retorne métricas disponíveis, "
                "posts recentes, frequência, temas, formatos e oportunidades de referência."
            ),
            "allow_tracing": False,
        }
        if connection and connection.get("composio_connection_id"):
            payload["connected_account_id"] = connection["composio_connection_id"]
        data = await self._request("POST", f"/tools/execute/{tool_slug}", json=payload)
        return self._safe_payload(data)

    async def _resolve_tool_slug(self, platform: str, purpose: str, *, required: bool = True) -> Optional[str]:
        key = (platform, purpose)
        if key in self._tool_cache:
            return self._tool_cache[key]
        upper = platform.upper()
        env_candidates = [
            f"COMPOSIO_TOOL_{upper}_{purpose.upper()}",
            f"COMPOSIO_{upper}_{purpose.upper()}_TOOL",
        ]
        for env_key in env_candidates:
            value = (os.environ.get(env_key) or "").strip()
            if value:
                self._tool_cache[key] = value
                return value
        toolkit = PLATFORM_TOOLKITS.get(platform)
        if not toolkit:
            if required:
                raise SocialProviderError(f"Plataforma social não suportada: {platform}", status_code=422)
            return None
        query = {
            "publish": "publish post create upload media video",
            "status": "status get post media video",
            "metrics": "analytics metrics insights profile posts",
        }.get(purpose, purpose)
        data = await self._request("GET", "/tools", params={"toolkit_slug": toolkit, "query": query, "limit": 50})
        items = data.get("items") or data.get("data") or []
        if not isinstance(items, list):
            items = []
        chosen = self._choose_tool(items, purpose)
        if chosen:
            self._tool_cache[key] = chosen
            return chosen
        if required:
            raise SocialProviderError(
                f"Nenhuma ferramenta Composio encontrada para {platform}/{purpose}. "
                f"Configure {env_candidates[0]} com o tool slug correto.",
                status_code=503,
            )
        return None

    def _choose_tool(self, items: List[Dict[str, Any]], purpose: str) -> Optional[str]:
        terms = {
            "publish": ("publish", "post", "create", "upload", "media", "video"),
            "status": ("status", "get", "retrieve"),
            "metrics": ("analytics", "metrics", "insights", "profile", "posts", "statistics"),
        }.get(purpose, (purpose,))
        scored: List[Tuple[int, str]] = []
        for item in items:
            slug = str(item.get("slug") or "")
            hay = " ".join([
                slug,
                str(item.get("name") or ""),
                str(item.get("description") or ""),
                str(item.get("human_description") or ""),
            ]).lower()
            score = sum(1 for term in terms if term in hay)
            if purpose == "publish" and "comment" in hay:
                score -= 2
            if slug and score > 0:
                scored.append((score, slug))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    def _publish_instruction(self, platform: str, post: Dict[str, Any], media_urls: List[str]) -> str:
        title = post.get("title") or ""
        caption = post.get("caption") or ""
        tags = post.get("metadata", {}).get("tags") or []
        parts = [
            f"Publique este post aprovado no {platform}.",
            "Use exatamente a mídia já pronta nas URLs abaixo; não converta, não edite e não gere novo arquivo.",
            f"Tipo de conteúdo: {post.get('content_type') or 'text'}.",
        ]
        if title:
            parts.append(f"Título: {title}")
        if caption:
            parts.append(f"Legenda/descrição: {caption}")
        if tags:
            parts.append("Tags: " + ", ".join(map(str, tags)))
        if media_urls:
            parts.append("Mídia pública: " + " | ".join(media_urls))
        if platform == "youtube":
            parts.append("Defina madeForKids como false, salvo se o payload informar o contrário.")
        return "\n".join(parts)

    def _extract_error(self, data: Dict[str, Any]) -> str:
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("slug") or err)
        if err:
            return str(err)
        return str(data.get("detail") or data.get("message") or "")

    def _pick(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        for key in keys:
            value = data.get(key)
            if value is not None:
                return str(value)
        return None

    def _safe_payload(self, value: Any) -> Any:
        secret_re = re.compile(r"(token|secret|password|api[_-]?key|authorization|credential)", re.I)
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                clean[k] = "***" if secret_re.search(str(k)) else self._safe_payload(v)
            return clean
        if isinstance(value, list):
            return [self._safe_payload(v) for v in value[:100]]
        return value


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para re-hostear mídia em URL pública (Instagram não busca de URLs internas)
# ─────────────────────────────────────────────────────────────────────────────

def _is_publicly_accessible_url(url: str) -> bool:
    """Verifica se a URL é HTTPS, sem query params, e de um domínio público conhecido.

    Instagram rejeita URLs com query params (signed URLs) e URLs que seus
    crawlers não conseguem buscar (servidores locais/privados).
    """
    from urllib.parse import urlparse
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        return False
    if parsed.query:
        return False
    # Domínios conhecidamente acessíveis pelos crawlers do Meta/Instagram
    trusted = (
        "imgur.com", "i.imgur.com",
        "amazonaws.com", "s3.amazonaws.com",
        "cloudinary.com", "res.cloudinary.com",
        "githubusercontent.com", "raw.githubusercontent.com",
        "googleusercontent.com", "lh3.googleusercontent.com",
        "fbcdn.net", "cdninstagram.com",
        "twimg.com", "pinterest.com",
    )
    host = (parsed.netloc or "").lower()
    return any(host.endswith(t) or host == t for t in trusted)


async def _rehost_media(local_url: str, is_video: bool) -> Optional[str]:
    """Re-hostea mídia em URL pública (Imgur) para o Instagram poder buscar.

    Usa a API anônima do Imgur (IMGUR_CLIENT_ID env).
    Retorna a URL pública ou None se falhar.
    """
    import asyncio
    import logging
    log = logging.getLogger("caripost.social")

    imgur_client_id = (os.environ.get("IMGUR_CLIENT_ID") or _setting_value("imgur.clientId") or "").strip()
    if not imgur_client_id:
        log.error("[rehost] IMGUR_CLIENT_ID não configurado — não é possível re-hostear mídia")
        return None

    # Resolver o caminho local do arquivo a partir da URL
    upload_prefix = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")
    media_root = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
    if local_url.startswith(upload_prefix):
        local_path = os.path.join(media_root, local_url[len(upload_prefix):].lstrip("/"))
    elif local_url.startswith("/"):
        local_path = os.path.join(media_root, local_url.lstrip("/"))
    else:
        local_path = local_url  # já é um caminho

    if not os.path.exists(local_path):
        log.error("[rehost] arquivo não encontrado: %s", local_path)
        return None

    # Ler e converter para JPEG se for imagem (Instagram prefere JPEG)
    try:
        import io
        if not is_video:
            from PIL import Image
            img = Image.open(local_path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            file_data = buf.getvalue()
            mime = "image/jpeg"
            ext = "jpg"
        else:
            with open(local_path, "rb") as f:
                file_data = f.read()
            mime = "video/mp4"
            ext = "mp4"
    except Exception as exc:
        log.error("[rehost] erro ao processar mídia: %s", exc)
        return None

    # Upload para Imgur
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                "https://api.imgur.com/3/image" if not is_video else "https://api.imgur.com/3/upload",
                headers={"Authorization": f"Client-ID {imgur_client_id}"},
                files={"image": (f"post.{ext}", file_data, mime)},
            )
            if res.status_code >= 400:
                log.error("[rehost] Imgur rejeitou: %d %s", res.status_code, res.text[:300])
                return None
            data = res.json()
            public_url = data.get("data", {}).get("link")
            if public_url:
                # Imgur retorna http:// — Instagram precisa de https://
                public_url = public_url.replace("http://", "https://")
                log.info("[rehost] mídia hospedada em: %s", public_url)
                return public_url
    except Exception as exc:
        log.error("[rehost] erro no upload Imgur: %s", exc)
        return None

    return None
