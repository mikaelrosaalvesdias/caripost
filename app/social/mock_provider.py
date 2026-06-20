from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from .base import ConnectAccountResult, PublishResult


class MockSocialProvider:
    provider = "mock"

    async def connect_account(self, *, platform: str, user_id: str, brand_id: str, callback_url: Optional[str] = None) -> ConnectAccountResult:
        cid = "mock_" + uuid.uuid4().hex[:12]
        return ConnectAccountResult(
            provider=self.provider,
            platform=platform,
            user_id=user_id,
            brand_id=brand_id,
            redirect_url=callback_url or "mock://connected",
            connected_account_id=cid,
            raw={"mock": True, "connected_account_id": cid},
        )

    async def disconnect_account(self, *, composio_connection_id: str) -> None:
        return None

    async def publish_post(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> PublishResult:
        pid = "mock_post_" + uuid.uuid4().hex[:10]
        return PublishResult(
            provider=self.provider,
            platform=channel.get("platform") or connection.get("platform"),
            external_post_id=pid,
            external_post_url=f"https://social.example/{pid}",
            status="published",
            raw={"mock": True, "post_id": pid},
        )

    async def get_post_status(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        return {"mock": True, "status": channel.get("status") or "published"}

    async def get_post_metrics(self, *, post: Dict[str, Any], channel: Dict[str, Any], connection: Dict[str, Any]) -> Dict[str, Any]:
        return {"mock": True, "views": 100, "likes": 10, "comments": 2}

    async def analyze_profile(self, *, platform: str, handle: str, connection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "mock": True,
            "platform": platform,
            "handle": handle,
            "summary": "Perfil mock analisado.",
            "metrics": {"followers": 1000, "avg_engagement": 0.042},
            "themes": ["referências visuais", "frequência", "formatos"],
        }
