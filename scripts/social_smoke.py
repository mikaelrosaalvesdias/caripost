#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


async def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ADULT_META_DB_PATH"] = os.path.join(tmp, "runs.db")
        os.environ["SOCIAL_PROVIDER"] = "mock"

        from app.db import init_db
        from app.db_agency import (
            init_agency_db,
            social_connection_create,
            social_post_create,
            social_post_get,
        )
        from app.db_companies import init_companies_db, company_create
        from app.social.base import SocialProviderError
        from app.social.service import create_post, process_due_social_posts

        init_db()
        init_agency_db()
        init_companies_db()

        company = company_create({"name": "Smoke Social"})
        brand_id = company["id"]
        connection = social_connection_create({
            "user_id": "smoke",
            "brand_id": brand_id,
            "provider": "mock",
            "platform": "instagram",
            "external_account_name": "Smoke IG",
            "composio_connection_id": "mock_connection",
            "status": "connected",
        })
        request = SimpleNamespace(headers={}, cookies={})

        try:
            await create_post({
                "brandId": brand_id,
                "caption": "Não deve publicar sem aprovação",
                "contentType": "image",
                "assetUrls": ["https://example.com/post.jpg"],
                "channels": [{"socialConnectionId": connection["id"], "platform": "instagram"}],
            }, request)
        except SocialProviderError as exc:
            assert "aprovado" in exc.message.lower()
        else:
            raise AssertionError("publicação sem aprovação não foi bloqueada")

        due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        post = social_post_create({
            "user_id": "smoke",
            "brand_id": brand_id,
            "title": "Smoke",
            "caption": "Post aprovado",
            "content_type": "image",
            "status": "scheduled",
            "scheduled_at": due_at,
            "assets": [{"asset_url": "https://example.com/post.jpg", "asset_type": "image"}],
            "channels": [{"social_connection_id": connection["id"], "platform": "instagram"}],
        })

        result = await process_due_social_posts()
        assert result["triggered"] == 1
        final_post = social_post_get(post["id"])
        assert final_post["status"] == "published", final_post
        assert final_post["channels"][0]["status"] == "published", final_post["channels"]
        assert final_post["logs"], "logs sociais não foram gravados"

        print("social_smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
