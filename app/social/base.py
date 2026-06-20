from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


SUPPORTED_SOCIAL_PLATFORMS = {"instagram", "facebook", "youtube", "tiktok"}


class SocialProviderError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


class SocialProviderNotConfigured(SocialProviderError):
    def __init__(self, message: str = "Composio não configurado. Defina COMPOSIO_API_KEY."):
        super().__init__(message, status_code=503)


@dataclass
class ConnectAccountResult:
    provider: str
    platform: str
    user_id: str
    brand_id: str
    redirect_url: Optional[str] = None
    link_token: Optional[str] = None
    connected_account_id: Optional[str] = None
    expires_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    provider: str
    platform: str
    external_post_id: Optional[str] = None
    external_post_url: Optional[str] = None
    status: str = "published"
    raw: Dict[str, Any] = field(default_factory=dict)


class SocialProvider(Protocol):
    async def connect_account(
        self,
        *,
        platform: str,
        user_id: str,
        brand_id: str,
        callback_url: Optional[str] = None,
    ) -> ConnectAccountResult:
        ...

    async def disconnect_account(self, *, composio_connection_id: str) -> None:
        ...

    async def publish_post(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> PublishResult:
        ...

    async def get_post_status(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def get_post_metrics(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        ...

    async def analyze_profile(self, *, platform: str, handle: str, connection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ...
