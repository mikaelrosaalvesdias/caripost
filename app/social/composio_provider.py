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
            api_key=(os.environ.get("COMPOSIO_API_KEY") or "").strip(),
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

    def _auth_config_id(self, platform: str) -> str:
        upper = platform.upper()
        candidates = [
            f"COMPOSIO_AUTH_CONFIG_{upper}",
            f"COMPOSIO_{upper}_AUTH_CONFIG_ID",
            f"COMPOSIO_AUTH_CONFIG_ID_{upper}",
            f"{upper}_COMPOSIO_AUTH_CONFIG_ID",
        ]
        for key in candidates:
            value = (os.environ.get(key) or "").strip()
            if value:
                return value
        raise SocialProviderError(
            f"Auth config do Composio não configurado para {platform}. Defina {candidates[0]}.",
            status_code=503,
        )

    async def connect_account(
        self,
        *,
        platform: str,
        user_id: str,
        brand_id: str,
        callback_url: Optional[str] = None,
    ) -> ConnectAccountResult:
        auth_config_id = self._auth_config_id(platform)
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
