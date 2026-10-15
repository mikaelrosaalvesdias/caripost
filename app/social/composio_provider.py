from __future__ import annotations

import os
import re
import uuid
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
            "alias": f"{brand_id}-{platform}-{uuid.uuid4().hex[:8]}",
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

        # ── CARROSSEL: 2+ imagens → 1 container por slide (is_carousel_item) +
        #    1 container CAROUSEL (children) + publish. (Post único cairia só no 1º slide.)
        if not is_video and len(media_urls) > 1:
            child_ids: List[str] = []
            for i, mu in enumerate(media_urls, 1):
                u = mu
                if not _is_publicly_accessible_url(u):
                    u = await _rehost_media(u, False, post.get("brand_id"))
                    if not u:
                        raise SocialProviderError(
                            f"Não consegui hospedar a imagem {i}/{len(media_urls)} do carrossel em URL pública.",
                            status_code=502)
                cid = await self._ig_create_container(create_slug, composio_conn_id, user_id, {
                    "ig_user_id": ig_user_id, "image_url": u, "is_carousel_item": True,
                }, step=f"carousel_child_{i}")
                child_ids.append(str(cid))
                log.info("[composio/instagram] carrossel slide %s/%s container=%s", i, len(media_urls), cid)
            carousel_args = {"ig_user_id": ig_user_id, "media_type": "CAROUSEL", "children": child_ids, "caption": caption}
            collabs = self._collaborators(post)
            if collabs:
                carousel_args["collaborators"] = collabs          # COLLAB: marca o influencer como colaborador do post
                log.info("[composio/instagram] collab=%s", collabs)
            carousel_id = await self._ig_create_container(create_slug, composio_conn_id, user_id, carousel_args, step="carousel_container")
            log.info("[composio/instagram] carrossel container=%s (%s slides)", carousel_id, len(child_ids))
            feed_result = await self._ig_publish_container(publish_slug, composio_conn_id, user_id, ig_user_id, carousel_id, max_wait=60)
            # STORY simultâneo (opção): publica a CAPA como story. Falha aqui NÃO derruba o feed (já publicado).
            await self._maybe_publish_story(post, media_urls, create_slug, publish_slug, composio_conn_id, user_id, ig_user_id, log)
            return feed_result

        # Re-hostear imagem em URL pública se necessário (Instagram não busca de URLs internas)
        if not _is_publicly_accessible_url(media_url):
            log.info("[composio/instagram] re-hosteando mídia: %s", media_url)
            media_url = await _rehost_media(media_url, is_video, post.get("brand_id"))
            if not media_url:
                raise SocialProviderError(
                    "Não foi possível publicar a imagem em URL pública acessível pelo Instagram. "
                    "Verifique a conexão com tmpfiles.org ou se a mídia já está em URL pública.",
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
            if content_type == "story":
                create_args["media_type"] = "STORIES"   # FORMATO story → publica como STORY de verdade (9:16)
        collabs = self._collaborators(post)
        if collabs:
            create_args["collaborators"] = collabs          # COLLAB no post único também
            log.info("[composio/instagram] collab=%s", collabs)

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
                "ig_user_id": ig_user_id,
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
        # STORY simultâneo (opção): publica a mesma arte como story (falha não derruba o feed já publicado).
        await self._maybe_publish_story(post, media_urls, create_slug, publish_slug, composio_conn_id, user_id, ig_user_id, log)
        return PublishResult(
            provider=self.provider,
            platform="instagram",
            external_post_id=ext_id,
            external_post_url=ext_url,
            status=str(pub_data.get("status") or "published"),
            raw=self._safe_payload(pub_resp),
        )

    def _collaborators(self, post: Dict[str, Any]) -> List[str]:
        """@ dos colaboradores (influencer) p/ marcar no post — vem de metadata.collaborators. Máx 3, sem '@'."""
        meta = post.get("metadata") or {}
        c = meta.get("collaborators") or post.get("collaborators") or []
        if isinstance(c, str):
            c = [c]
        return [str(x).strip().lstrip("@") for x in c if str(x).strip()][:3]

    async def _maybe_publish_story(self, post: Dict[str, Any], media_urls: List[str], create_slug: str,
                                   publish_slug: str, composio_conn_id: str, user_id: str, ig_user_id: str, log) -> None:
        """STORY simultâneo (opção metadata.also_story): publica a CAPA (1ª mídia) como STORIES.
        Falha aqui é LOGADA mas NÃO propaga — o feed já foi publicado com sucesso."""
        meta = post.get("metadata") or {}
        if not (meta.get("also_story") or meta.get("publish_story")):
            return
        import asyncio
        try:
            await asyncio.sleep(5)   # delay p/ o feed ASSENTAR antes de republicar no story (evita corrida)
            cover = (meta.get("story_url") or "").strip() or media_urls[0]   # 9:16 bonito; senão a capa
            if not _is_publicly_accessible_url(cover):
                cover = await _rehost_media(cover, False, post.get("brand_id"))
            if not cover:
                log.warning("[composio/instagram] story-repost: sem URL pública — pulando")
                return
            sid = await self._ig_create_container(create_slug, composio_conn_id, user_id, {
                "ig_user_id": ig_user_id, "image_url": cover, "media_type": "STORIES",
            }, step="story_container")
            await self._ig_publish_container(publish_slug, composio_conn_id, user_id, ig_user_id, sid, max_wait=60)
            log.info("[composio/instagram] story-repost (9:16) publicado")
        except Exception as se:
            log.error("[composio/instagram] story-repost falhou (feed OK): %s", se)

    async def _ig_create_container(self, slug: str, composio_conn_id: str, user_id: str,
                                   args: Dict[str, Any], step: str) -> str:
        """Cria um container de mídia no Instagram (child ou carrossel) e devolve o creation_id."""
        import logging
        log = logging.getLogger("caripost.social")
        payload = {"connected_account_id": composio_conn_id, "user_id": user_id,
                   "arguments": args, "allow_tracing": False}
        resp = await self._request("POST", f"/tools/execute/{slug}", json=payload)
        if resp.get("successful") is False:
            msg = self._extract_error(resp) or "Composio não criou o container do Instagram."
            log.error("[composio/instagram] %s falhou: %s", step, msg)
            raise SocialProviderError(msg, status_code=502, detail={"step": step, "composio": self._safe_payload(resp)})
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        cid = self._pick(data, ["id", "creation_id", "container_id", "media_id"])
        if not cid:
            raise SocialProviderError(f"Container criado mas sem creation_id ({step}).",
                                      status_code=502, detail={"step": step, "composio": self._safe_payload(resp)})
        return cid

    async def _ig_publish_container(self, slug: str, composio_conn_id: str, user_id: str,
                                    ig_user_id: str, creation_id: str, max_wait: int = 30) -> PublishResult:
        """Publica um container já criado (single ou carrossel) e devolve o PublishResult."""
        import logging
        log = logging.getLogger("caripost.social")
        payload = {"connected_account_id": composio_conn_id, "user_id": user_id,
                   "arguments": {"creation_id": str(creation_id), "ig_user_id": ig_user_id,
                                 "max_wait_seconds": max_wait},
                   "allow_tracing": False}
        resp = await self._request("POST", f"/tools/execute/{slug}", json=payload)
        if resp.get("successful") is False:
            msg = self._extract_error(resp) or "Composio não publicou no Instagram."
            log.error("[composio/instagram] publish falhou: %s", msg)
            raise SocialProviderError(msg, status_code=502, detail={"step": "publish", "creation_id": creation_id, "composio": self._safe_payload(resp)})
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        return PublishResult(
            provider=self.provider, platform="instagram",
            external_post_id=self._pick(data, ["id", "post_id", "media_id", "ig_media_id"]),
            external_post_url=self._pick(data, ["permalink", "url", "share_url", "html_url", "external_url"]),
            status=str(data.get("status") or "published"),
            raw=self._safe_payload(resp),
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

    async def discover_instagram_business(
        self,
        *,
        handle: str,
        connection: Dict[str, Any],
        media_limit: int = 6,
    ) -> Dict[str, Any]:
        """Read an eligible public Business/Creator profile through Meta's official API.

        The authorization belongs to the agency's research account, never to the
        prospect being researched. Business Discovery is not currently exposed as
        a dedicated Composio Instagram tool, so Proxy Execute is used while
        Composio continues to inject and refresh the connected account credential.
        """
        clean_handle = str(handle or "").strip().lstrip("@").split("?", 1)[0].strip("/")
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", clean_handle):
            raise SocialProviderError("Perfil do Instagram inválido para pesquisa.", status_code=422)
        composio_conn_id = str(connection.get("composio_connection_id") or "").strip()
        if not composio_conn_id:
            raise SocialProviderError("A conta de pesquisa do Instagram não está conectada.", status_code=422)
        user_id = str(connection.get("user_id") or "").strip() or "api"
        facebook_version = (
            os.environ.get("COMPOSIO_FACEBOOK_TOOLKIT_VERSION") or "20260721_00"
        ).strip()
        managed_response = await self._request(
            "POST", "/tools/execute/FACEBOOK_LIST_MANAGED_PAGES",
            json={
                "connected_account_id": composio_conn_id,
                "user_id": user_id,
                "version": facebook_version,
                "arguments": {
                    "user_id": "me", "limit": 100,
                    "fields": (
                        "id,name,username,link,instagram_business_account"
                        "{id,username,name,profile_picture_url}"
                    ),
                },
                "allow_tracing": False,
            },
        )
        if managed_response.get("successful") is False:
            raise SocialProviderError(
                self._extract_error(managed_response) or "Não foi possível validar a conta Meta de pesquisa.",
                status_code=502,
                detail={"reason": "research_connection_unavailable"},
            )
        managed_payload = (managed_response.get("data")
                           if isinstance(managed_response.get("data"), dict) else managed_response)
        managed_pages = managed_payload.get("data") if isinstance(managed_payload.get("data"), list) else []
        candidates = []
        for page in managed_pages:
            instagram_account = page.get("instagram_business_account") if isinstance(page, dict) else None
            if isinstance(instagram_account, dict) and instagram_account.get("id"):
                candidates.append((page, instagram_account))
        metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
        expected_page_id = str(
            metadata.get("facebook_page_id") or metadata.get("research_page_id") or ""
        ).strip()
        if expected_page_id:
            candidates = [item for item in candidates if str(item[0].get("id") or "") == expected_page_id]
        if len(candidates) != 1:
            reason = "research_page_selection_required" if candidates else "research_instagram_account_missing"
            raise SocialProviderError(
                "Selecione uma única Página da CARIAP com Instagram profissional vinculado para a pesquisa.",
                status_code=422,
                detail={"reason": reason, "eligible_pages": len(candidates)},
            )
        ig_user_id = str(candidates[0][1]["id"])
        media_limit = max(1, min(int(media_limit or 6), 30))
        fields = (
            f"business_discovery.username({clean_handle})"
            "{id,username,name,biography,website,profile_picture_url,followers_count,media_count,"
            f"media.limit({media_limit})"
            "{id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp}}"
        )
        graph_version = (os.environ.get("META_GRAPH_VERSION") or "v23.0").strip().lstrip("/")
        payload = {
            "connected_account_id": composio_conn_id,
            # Business Discovery belongs to the Facebook Login Graph host. A relative
            # endpoint keeps Composio's same-domain proxy guard intact.
            "endpoint": f"/{graph_version}/{ig_user_id}",
            "method": "GET",
            "parameters": [{"name": "fields", "value": fields, "type": "query"}],
        }
        response = await self._request("POST", "/tools/execute/proxy", json=payload)
        status = int(response.get("status") or 200)
        raw = response.get("data") if isinstance(response.get("data"), dict) else response
        if status >= 400:
            raise SocialProviderError(
                self._extract_error(raw) or f"Meta retornou HTTP {status} na pesquisa do perfil.",
                status_code=502,
                detail={"meta_status": status},
            )
        profile = raw.get("business_discovery") if isinstance(raw, dict) else None
        if not isinstance(profile, dict) or not profile.get("id"):
            raise SocialProviderError(
                "A Meta não disponibilizou este perfil para pesquisa oficial. "
                "Somente contas públicas Business/Creator elegíveis são suportadas.",
                status_code=422,
                detail={"reason": "unsupported_or_not_found"},
            )
        media = profile.get("media") if isinstance(profile.get("media"), dict) else {}
        items = media.get("data") if isinstance(media.get("data"), list) else []
        return {
            "id": str(profile.get("id")),
            "username": str(profile.get("username") or clean_handle),
            "name": str(profile.get("name") or ""),
            "biography": str(profile.get("biography") or ""),
            "website": str(profile.get("website") or ""),
            "profile_picture_url": str(profile.get("profile_picture_url") or ""),
            "followers_count": profile.get("followers_count"),
            "media_count": profile.get("media_count"),
            "media": [item for item in items if isinstance(item, dict)][:media_limit],
        }

    async def get_owned_instagram_profile_media(
        self,
        *,
        connection: Dict[str, Any],
        media_limit: int = 6,
    ) -> Dict[str, Any]:
        """Read the profile and recent media belonging to a connected brand account."""
        composio_conn_id = str(connection.get("composio_connection_id") or "").strip()
        if not composio_conn_id:
            raise SocialProviderError("A conta do Instagram não está conectada.", status_code=422)
        user_id = str(connection.get("user_id") or "").strip() or "api"
        toolkit_version = (
            os.environ.get("COMPOSIO_INSTAGRAM_TOOLKIT_VERSION") or "20260730_00"
        ).strip()
        common = {
            "connected_account_id": composio_conn_id,
            "user_id": user_id,
            "version": toolkit_version,
            "allow_tracing": False,
        }
        profile_response = await self._request(
            "POST", "/tools/execute/INSTAGRAM_GET_USER_INFO",
            json={**common, "arguments": {"ig_user_id": "me"}},
        )
        if profile_response.get("successful") is False:
            raise SocialProviderError(
                self._extract_error(profile_response) or "Não foi possível ler o perfil conectado.",
                status_code=502,
            )
        profile = profile_response.get("data") if isinstance(profile_response.get("data"), dict) else profile_response
        # Some tools wrap the upstream body one more time.
        if isinstance(profile.get("data"), dict) and not profile.get("id"):
            profile = profile["data"]
        ig_user_id = str(profile.get("id") or profile.get("ig_user_id") or "me")
        media_limit = max(1, min(int(media_limit or 6), 30))
        fields = (
            "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
            "permalink,timestamp,username,children{media_url,media_type,thumbnail_url}"
        )
        media_response = await self._request(
            "POST", "/tools/execute/INSTAGRAM_GET_IG_USER_MEDIA",
            json={**common, "arguments": {
                "ig_user_id": ig_user_id, "limit": media_limit, "fields": fields,
            }},
        )
        if media_response.get("successful") is False:
            raise SocialProviderError(
                self._extract_error(media_response) or "Não foi possível ler as mídias da conta conectada.",
                status_code=502,
            )
        media_payload = media_response.get("data") if isinstance(media_response.get("data"), dict) else media_response
        if isinstance(media_payload.get("data"), dict) and isinstance(media_payload["data"].get("data"), list):
            media_payload = media_payload["data"]
        media_items = media_payload.get("data") if isinstance(media_payload.get("data"), list) else []
        return {
            "id": ig_user_id,
            "username": str(profile.get("username") or ""),
            "name": str(profile.get("name") or ""),
            "biography": str(profile.get("biography") or ""),
            "website": str(profile.get("website") or ""),
            "profile_picture_url": str(profile.get("profile_picture_url") or ""),
            "followers_count": profile.get("followers_count"),
            "media_count": profile.get("media_count"),
            "account_type": profile.get("account_type"),
            "media": [item for item in media_items if isinstance(item, dict)][:media_limit],
        }

    async def test_connection(
        self,
        *,
        platform: str,
        connection: Dict[str, Any],
        selected_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a harmless official tool instead of trusting OAuth status alone."""
        platform = str(platform or "").strip().lower()
        if platform == "instagram":
            profile = await self.get_owned_instagram_profile_media(
                connection=connection,
                media_limit=1,
            )
            return {
                "platform": platform,
                "tool_tested": True,
                "account": {
                    key: profile.get(key)
                    for key in ("id", "username", "name", "account_type", "media_count")
                    if profile.get(key) is not None
                },
            }

        if platform == "facebook":
            composio_conn_id = str(connection.get("composio_connection_id") or "").strip()
            if not composio_conn_id:
                raise SocialProviderError("A conta Facebook não está conectada.", status_code=422)
            user_id = str(connection.get("user_id") or "").strip() or "api"
            version = (os.environ.get("COMPOSIO_FACEBOOK_TOOLKIT_VERSION") or "20260721_00").strip()
            response = await self._request(
                "POST", "/tools/execute/FACEBOOK_LIST_MANAGED_PAGES",
                json={
                    "connected_account_id": composio_conn_id,
                    "user_id": user_id,
                    "version": version,
                    "arguments": {
                        "user_id": "me",
                        "limit": 100,
                        "fields": (
                            "id,name,username,link,category,is_published,"
                            "instagram_business_account{id,username,name}"
                        ),
                    },
                    "allow_tracing": False,
                },
            )
            if response.get("successful") is False:
                raise SocialProviderError(
                    self._extract_error(response) or "O Facebook não liberou as Páginas gerenciadas.",
                    status_code=422,
                    detail={"reason": "facebook_permission_missing"},
                )
            payload = response.get("data") if isinstance(response.get("data"), dict) else response
            if isinstance(payload.get("data"), dict):
                payload = payload["data"]
            raw_pages = payload.get("data") if isinstance(payload.get("data"), list) else []
            pages = []
            for raw in raw_pages:
                if not isinstance(raw, dict) or not raw.get("id"):
                    continue
                linked_ig = raw.get("instagram_business_account")
                pages.append({
                    "id": str(raw.get("id")),
                    "name": str(raw.get("name") or ""),
                    "username": str(raw.get("username") or ""),
                    "link": str(raw.get("link") or ""),
                    "category": str(raw.get("category") or ""),
                    "instagram_business_account": {
                        key: linked_ig.get(key)
                        for key in ("id", "username", "name")
                        if isinstance(linked_ig, dict) and linked_ig.get(key) is not None
                    },
                })
            if not pages:
                raise SocialProviderError(
                    "Esta conta Facebook não administra nenhuma Página disponível para a Caripost.",
                    status_code=422,
                    detail={"reason": "facebook_managed_page_missing"},
                )
            requested = str(selected_page_id or "").strip()
            if requested and requested not in {page["id"] for page in pages}:
                raise SocialProviderError(
                    "A Página selecionada não pertence a esta conexão Facebook.",
                    status_code=422,
                    detail={"reason": "facebook_page_not_managed"},
                )
            chosen_id = requested or (pages[0]["id"] if len(pages) == 1 else "")
            chosen = next((page for page in pages if page["id"] == chosen_id), None)
            return {
                "platform": platform,
                "tool_tested": True,
                "managed_pages": pages,
                "selected_page": chosen,
                "selection_required": len(pages) > 1 and not chosen,
            }

        return {"platform": platform, "tool_tested": False}

    async def discover_facebook_page(
        self,
        *,
        company_name: str,
        facebook: str,
        website: str,
        connection: Dict[str, Any],
        photo_limit: int = 6,
    ) -> Dict[str, Any]:
        """Resolve an eligible public Page with official Facebook tools.

        The connected account belongs to CARIAP. Matching is conservative so a
        similarly named Page can never silently become the prospect's identity.
        """
        from urllib.parse import urlparse

        composio_conn_id = str(connection.get("composio_connection_id") or "").strip()
        if not composio_conn_id:
            raise SocialProviderError("A conta Facebook de pesquisa não está conectada.", status_code=422)
        user_id = str(connection.get("user_id") or "").strip() or "api"
        version = (os.environ.get("COMPOSIO_FACEBOOK_TOOLKIT_VERSION") or "20260721_00").strip()
        raw_page = str(facebook or "").strip()
        parsed_page = urlparse(raw_page if "://" in raw_page else "https://facebook.com/" + raw_page.lstrip("@/"))
        expected_handle = (parsed_page.path or "").strip("/").split("/", 1)[0].lower()
        if expected_handle in {"pages", "profile.php", "people"}:
            expected_handle = ""

        def _key(value: Any) -> str:
            import unicodedata
            normalized = unicodedata.normalize("NFKD", str(value or ""))
            return re.sub(r"[^a-z0-9]+", "", normalized.encode("ascii", "ignore").decode().lower())

        query = str(company_name or expected_handle or "").strip()
        if not query:
            raise SocialProviderError("Nome ou URL da Página Facebook ausente.", status_code=422)
        common = {
            "connected_account_id": composio_conn_id,
            "user_id": user_id,
            "version": version,
            "allow_tracing": False,
        }
        search_response = await self._request(
            "POST", "/tools/execute/FACEBOOK_SEARCH_PAGES",
            json={**common, "arguments": {
                "query": query, "limit": 20,
                "fields": (
                    "id,name,category,link,picture,cover,fan_count,is_verified,"
                    "website,about,description,location"
                ),
            }},
        )
        if search_response.get("successful") is False:
            raise SocialProviderError(
                self._extract_error(search_response) or "A pesquisa oficial de Páginas não está disponível.",
                status_code=502,
                detail={"reason": "facebook_search_unavailable"},
            )
        search_payload = (search_response.get("data")
                          if isinstance(search_response.get("data"), dict) else search_response)
        pages = search_payload.get("data") if isinstance(search_payload.get("data"), list) else []
        company_key = _key(company_name)
        website_host = urlparse(
            website if "://" in str(website or "") else "https://" + str(website or "")
        ).netloc.lower().removeprefix("www.")
        ranked = []
        for page in pages:
            if not isinstance(page, dict) or not page.get("id"):
                continue
            name_key = _key(page.get("name"))
            link_path = urlparse(str(page.get("link") or "")).path.strip("/").split("/", 1)[0].lower()
            page_host = urlparse(str(page.get("website") or "")).netloc.lower().removeprefix("www.")
            score = 0
            if expected_handle and link_path == expected_handle:
                score += 120
            if company_key and name_key == company_key:
                score += 80
            elif company_key and (company_key in name_key or name_key in company_key):
                score += 35
            if website_host and page_host and (website_host == page_host or website_host.endswith("." + page_host)):
                score += 70
            if page.get("is_verified"):
                score += 5
            ranked.append((score, page))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] < 70:
            raise SocialProviderError(
                "Nenhuma Página oficial correspondeu com segurança ao nome, URL ou domínio da empresa.",
                status_code=422,
                detail={"reason": "facebook_page_not_found"},
            )
        if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
            raise SocialProviderError(
                "Há mais de uma Página compatível; confirme a URL exata antes de importar.",
                status_code=422,
                detail={"reason": "facebook_page_ambiguous"},
            )
        selected = ranked[0][1]
        page_id = str(selected["id"])
        detail_response = await self._request(
            "POST", "/tools/execute/FACEBOOK_GET_PAGE_DETAILS",
            json={**common, "arguments": {
                "page_id": page_id,
                "fields": (
                    "id,name,about,category,description,fan_count,followers_count,website,"
                    "link,username,is_published,emails,phone,location,cover,picture"
                ),
            }},
        )
        details = (detail_response.get("data")
                   if isinstance(detail_response.get("data"), dict) else {})
        if detail_response.get("successful") is False:
            details = selected
        photo_limit = max(1, min(int(photo_limit or 6), 12))
        photos = []
        try:
            photos_response = await self._request(
                "POST", "/tools/execute/FACEBOOK_GET_PAGE_PHOTOS",
                json={**common, "arguments": {
                    "page_id": page_id, "type": "uploaded", "limit": photo_limit + 6,
                    "fields": "id,created_time,name,images,height,width,picture,link,album,from",
                }},
            )
            photos_payload = (photos_response.get("data")
                              if isinstance(photos_response.get("data"), dict) else {})
            raw_photos = photos_payload.get("data") if isinstance(photos_payload.get("data"), list) else []
            for photo in raw_photos:
                if not isinstance(photo, dict) or not photo.get("id"):
                    continue
                author = photo.get("from") if isinstance(photo.get("from"), dict) else {}
                album = photo.get("album") if isinstance(photo.get("album"), dict) else {}
                if author.get("id") and str(author.get("id")) != page_id:
                    continue
                if _key(album.get("name")) in {"profilepictures", "coverphotos", "fotosdoperfil", "fotosdacapa"}:
                    continue
                versions = [v for v in (photo.get("images") or []) if isinstance(v, dict) and v.get("source")]
                versions.sort(key=lambda v: int(v.get("width") or 0) * int(v.get("height") or 0), reverse=True)
                image_url = str((versions[0].get("source") if versions else None) or photo.get("picture") or "")
                if image_url:
                    photos.append({**photo, "media_url": image_url})
                if len(photos) >= photo_limit:
                    break
        except SocialProviderError:
            # Public Page photos require extra Meta review in some projects. Page
            # identity remains useful and the website/upload fallback stays active.
            photos = []

        picture = details.get("picture") if isinstance(details.get("picture"), dict) else {}
        picture_data = picture.get("data") if isinstance(picture.get("data"), dict) else picture
        cover = details.get("cover") if isinstance(details.get("cover"), dict) else {}
        return {
            "id": page_id,
            "name": str(details.get("name") or selected.get("name") or ""),
            "link": str(details.get("link") or selected.get("link") or raw_page),
            "website": str(details.get("website") or selected.get("website") or ""),
            "about": str(details.get("about") or details.get("description") or ""),
            "profile_picture_url": str(picture_data.get("url") or ""),
            "cover_url": str(cover.get("source") or ""),
            "photos": photos,
        }

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
    try:
        if parsed.scheme != "https" or parsed.username or parsed.password:
            return False
        if parsed.query or parsed.fragment or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    # Domínios conhecidamente acessíveis pelos crawlers do Meta/Instagram
    trusted = (
        "tmpfiles.org",
        "imgur.com", "i.imgur.com",
        "amazonaws.com", "s3.amazonaws.com",
        "cloudinary.com", "res.cloudinary.com",
        "githubusercontent.com", "raw.githubusercontent.com",
        "googleusercontent.com", "lh3.googleusercontent.com",
        "fbcdn.net", "cdninstagram.com",
        "twimg.com", "pinterest.com",
    )
    host = (parsed.hostname or "").lower().rstrip(".")
    return any(host == t or host.endswith("." + t) for t in trusted)


async def _rehost_media(local_url: str, is_video: bool,
                        allowed_company_id: str) -> Optional[str]:
    """Re-hostea mídia em URL pública (tmpfiles.org) para o Instagram poder buscar.

    Os crawlers do Meta/Instagram não conseguem buscar de URLs internas/privadas,
    então a imagem é enviada para tmpfiles.org (upload anônimo, sem auth) e a
    URL pública direta é retornada.
    """
    import logging
    log = logging.getLogger("caripost.social")
    allowed_company_id = str(allowed_company_id or "").strip()
    if not allowed_company_id:
        log.error("[rehost] empresa proprietária da mídia não informada")
        return None

    # Resolver o caminho local do arquivo a partir da URL
    upload_prefix = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")
    media_root = os.environ.get("CARIPOST_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
    # Handle full URLs like https://domain.com/uploads/...
    from urllib.parse import unquote, urlparse
    parsed = urlparse(str(local_url or ""))
    if parsed.netloc and not parsed.scheme:
        log.error("[rehost] URL sem esquema não é aceita")
        return None
    if parsed.scheme:
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            log.error("[rehost] origem da URL não é aceita")
            return None
        public_base = (_setting_value("render.public_base")
                       or os.environ.get("RENDER_PUBLIC_BASE")
                       or "https://caripost.cariap.com.br")
        expected = urlparse(public_base)
        try:
            expected_port = expected.port or (443 if expected.scheme == "https" else 80)
            parsed_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return None
        if (
            not expected.hostname
            or parsed.scheme != expected.scheme
            or (parsed.hostname or "").lower().rstrip(".")
            != expected.hostname.lower().rstrip(".")
            or parsed_port != expected_port
        ):
            log.error("[rehost] URL externa não pertence ao host público da Caripost")
            return None
    if parsed.query or parsed.fragment:
        log.error("[rehost] URL com query/fragment não é aceita")
        return None
    local_url = unquote(parsed.path or "")
    if "\\" in local_url or "\x00" in local_url:
        return None
    if not local_url.startswith(upload_prefix.rstrip("/") + "/"):
        log.error("[rehost] URL fora do diretório de uploads")
        return None
    relative = local_url[len(upload_prefix.rstrip("/")) + 1:]
    parts = relative.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        log.error("[rehost] caminho de upload não canônico")
        return None
    if parts[0] != allowed_company_id:
        log.error("[rehost] mídia pertence a outra empresa")
        return None
    root_path = os.path.realpath(media_root)
    local_path = os.path.realpath(os.path.join(root_path, *parts))
    try:
        if os.path.commonpath((root_path, local_path)) != root_path:
            log.error("[rehost] caminho fora do diretório de uploads")
            return None
    except ValueError:
        return None

    if not os.path.exists(local_path):
        log.error("[rehost] arquivo não encontrado: %s", local_path)
        return None
    max_source_bytes = 250 * 1024 * 1024 if is_video else 24 * 1024 * 1024
    try:
        if not os.path.isfile(local_path) or os.path.getsize(local_path) > max_source_bytes:
            log.error("[rehost] arquivo excede o limite permitido")
            return None
    except OSError:
        return None

    # Converter para JPEG se for imagem (Instagram prefere JPEG sem query params)
    try:
        import io
        if not is_video:
            from PIL import Image
            with Image.open(local_path) as source:
                if source.width * source.height > 40_000_000:
                    log.error("[rehost] imagem excede o limite de pixels")
                    return None
                img = source.convert("RGB")
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

    # Upload para tmpfiles.org (anônimo, sem auth, retorna URL pública sem query params)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as client:
            res = await client.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": (f"post.{ext}", file_data, mime)},
            )
            if res.status_code >= 400:
                log.error("[rehost] tmpfiles.org rejeitou: %d %s", res.status_code, res.text[:300])
                return None
            data = res.json()
            page_url = (data.get("data") or {}).get("url")
            if not page_url:
                log.error("[rehost] tmpfiles.org não retornou URL: %s", res.text[:300])
                return None
            # Converter URL de página para URL direta de download:
            # https://tmpfiles.org/xxx/file.jpg -> https://tmpfiles.org/dl/xxx/file.jpg
            returned = urlparse(str(page_url))
            if (returned.scheme not in ("http", "https")
                    or (returned.hostname or "").lower().rstrip(".") != "tmpfiles.org"
                    or returned.username or returned.password or returned.query or returned.fragment):
                log.error("[rehost] tmpfiles.org retornou uma origem inesperada")
                return None
            direct_url = "https://tmpfiles.org/dl/" + returned.path.lstrip("/")
            log.info("[rehost] mídia hospedada em: %s", direct_url)
            return direct_url
    except Exception as exc:
        log.error("[rehost] erro no upload tmpfiles.org: %s", exc)
        return None

    return None
