import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.social import service
from app.social.base import ConnectAccountResult, SocialProviderError


class _Router:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: (lambda fn: fn)


class _Response:
    def __init__(self, content=None, status_code=200, **_kwargs):
        self.content = content
        self.status_code = status_code
        if isinstance(content, (dict, list)):
            self.body = json.dumps(content).encode()
        else:
            self.body = str(content or "").encode()


try:
    from fastapi.responses import JSONResponse
    from app.routers import social as social_router
except ModuleNotFoundError:
    fake_fastapi = types.ModuleType("fastapi")
    fake_fastapi.APIRouter = lambda **_kwargs: _Router()
    fake_fastapi.Request = object
    fake_responses = types.ModuleType("fastapi.responses")
    fake_responses.HTMLResponse = _Response
    fake_responses.JSONResponse = _Response
    fake_responses.RedirectResponse = _Response
    with patch.dict(sys.modules, {"fastapi": fake_fastapi, "fastapi.responses": fake_responses}):
        from app.routers import social as social_router
    JSONResponse = _Response


def _brand(stage=None, *, kind="company"):
    company = {"id": "brand-1", "name": "Marca"}
    if stage is not None:
        company["lifecycle_stage"] = stage
    return {"kind": kind, "brand": company}


class _Request:
    def __init__(self, body=None):
        self._body = body or {}
        self.headers = {}
        self.cookies = {}
        self.query_params = {}

    async def json(self):
        return self._body


class SocialLifecycleUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_only_managed_internal_and_legacy_companies_are_eligible(self):
        for stage in ("managed", "internal", None):
            with self.subTest(stage=stage), patch.object(service, "ensure_brand_exists", return_value=_brand(stage)):
                result = service.ensure_social_brand_eligible("brand-1")
                self.assertEqual(result["brand"]["id"], "brand-1")

        with patch.object(service, "ensure_brand_exists", return_value=_brand(None, kind="creator")):
            self.assertEqual(service.ensure_social_brand_eligible("creator-1")["kind"], "creator")

    def test_prospect_and_lost_are_forbidden_with_clear_403(self):
        for stage in ("prospect", "lost"):
            with self.subTest(stage=stage), patch.object(service, "ensure_brand_exists", return_value=_brand(stage)):
                with self.assertRaises(SocialProviderError) as raised:
                    service.ensure_social_brand_eligible("brand-1", action="publicar conteúdo social")
                self.assertEqual(raised.exception.status_code, 403)
                self.assertEqual(raised.exception.detail["error"], "social_lifecycle_forbidden")
                self.assertEqual(raised.exception.detail["lifecycle_stage"], stage)

    async def test_connect_keeps_brand_scoped_user_id_for_internal_company(self):
        provider = Mock()
        provider.connect_account = AsyncMock(return_value=ConnectAccountResult(
            provider="composio",
            platform="instagram",
            user_id="brand:brand-1",
            brand_id="brand-1",
            connected_account_id="remote-1",
            raw={},
        ))
        stored = {"id": "conn-1", "user_id": "brand:brand-1", "brand_id": "brand-1"}
        with patch.object(service, "ensure_brand_exists", return_value=_brand("internal")), \
             patch.object(service, "get_social_provider", return_value=provider), \
             patch("app.db_agency.social_connection_upsert", return_value=stored):
            result = await service.connect_brand_account(brand_id="brand-1", platform="instagram")

        provider.connect_account.assert_awaited_once_with(
            platform="instagram",
            user_id="brand:brand-1",
            brand_id="brand-1",
            callback_url=None,
        )
        self.assertEqual(result["connection"]["user_id"], "brand:brand-1")

    async def test_prospect_cannot_start_but_can_revoke_existing_connection(self):
        provider = Mock()
        provider.connect_account = AsyncMock()
        provider.disconnect_account = AsyncMock()
        with patch.object(service, "ensure_brand_exists", return_value=_brand("prospect")), \
             patch.object(service, "get_social_provider", return_value=provider):
            with self.assertRaises(SocialProviderError) as connect_error:
                await service.connect_brand_account(brand_id="brand-1", platform="instagram")
            self.assertEqual(connect_error.exception.status_code, 403)

            with patch("app.db_agency.social_connection_get", return_value={
                "id": "conn-1",
                "brand_id": "brand-1",
                "provider": "composio",
                "composio_connection_id": "remote-1",
            }), patch("app.db_agency.social_connection_revoke") as revoke:
                result = await service.disconnect_account("conn-1")
                self.assertTrue(result["deleted"])
                revoke.assert_called_once_with("conn-1")

        provider.connect_account.assert_not_awaited()
        provider.disconnect_account.assert_awaited_once_with(composio_connection_id="remote-1")

    async def test_prospect_cannot_test_connection(self):
        provider = Mock()
        provider._request = AsyncMock()
        connection = {
            "id": "conn-1",
            "brand_id": "brand-1",
            "provider": "composio",
            "composio_connection_id": "remote-1",
            "status": "connected",
        }
        with patch("app.db_agency.social_connection_get", return_value=connection), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("prospect")), \
             patch.object(service, "get_social_provider", return_value=provider):
            with self.assertRaises(SocialProviderError) as raised:
                await service.test_account("conn-1")
        self.assertEqual(raised.exception.status_code, 403)
        provider._request.assert_not_awaited()
        update.assert_not_called()

    async def test_connection_test_reads_remote_composio_status(self):
        connection = {
            "id": "conn-1",
            "brand_id": "brand-1",
            "provider": "composio",
            "composio_connection_id": "remote id",
            "status": "pending",
        }
        updated = {**connection, "status": "connected"}
        provider = Mock()
        provider._request = AsyncMock(return_value={"data": {"status": "ACTIVE"}})
        with patch("app.db_agency.social_connection_get", side_effect=[connection, updated]), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("managed")), \
             patch.object(service, "get_social_provider", return_value=provider):
            result = await service.test_account("conn-1")

        provider._request.assert_awaited_once_with("GET", "/connected_accounts/remote%20id")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "connected")
        self.assertEqual(update.call_args.args[0], "conn-1")
        self.assertEqual(update.call_args.args[1]["status"], "connected")

    async def test_connection_test_executes_platform_tool_and_persists_page_choice(self):
        connection = {
            "id": "conn-1",
            "brand_id": "brand-1",
            "user_id": "brand:brand-1",
            "provider": "composio",
            "platform": "facebook",
            "composio_connection_id": "remote-1",
            "status": "connected",
            "metadata": {},
        }
        updated = {**connection, "external_account_id": "page-2"}
        provider = Mock()
        provider._request = AsyncMock(return_value={"data": {"status": "ACTIVE"}})
        provider.test_connection = AsyncMock(return_value={
            "platform": "facebook",
            "tool_tested": True,
            "managed_pages": [
                {"id": "page-1", "name": "Outra"},
                {"id": "page-2", "name": "CARIAP"},
            ],
            "selected_page": {"id": "page-2", "name": "CARIAP"},
            "selection_required": False,
        })
        with patch("app.db_agency.social_connection_get", side_effect=[connection, updated]), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("internal")), \
             patch.object(service, "get_social_provider", return_value=provider):
            result = await service.test_account("conn-1", page_id="page-2")

        provider.test_connection.assert_awaited_once()
        self.assertTrue(result["ok"])
        stored = update.call_args.args[1]
        self.assertEqual(stored["external_account_id"], "page-2")
        self.assertEqual(stored["metadata"]["facebook_page_id"], "page-2")
        self.assertEqual(len(stored["metadata"]["managed_pages"]), 2)

    async def test_callback_only_completes_a_locally_initiated_connection(self):
        pending = {
            "id": "conn-1",
            "brand_id": "brand-1",
            "platform": "instagram",
            "status": "pending",
            "composio_connection_id": None,
            "metadata": {"redirect_url": "https://auth.example"},
        }
        completed = {**pending, "status": "connected", "composio_connection_id": "remote-1"}
        payload = {
            "connected_account_id": "remote-1",
            "brand_id": "brand-1",
            "platform": "instagram",
            "status": "ACTIVE",
        }
        with patch("app.db_agency.social_connection_get_by_composio", side_effect=[None, completed]), \
             patch("app.db_agency.social_connection_list", return_value=[pending]), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("managed")):
            result = await service.handle_connection_callback(payload)

        self.assertEqual(result["connection"]["composio_connection_id"], "remote-1")
        self.assertEqual(update.call_args.args[0], "conn-1")
        self.assertEqual(update.call_args.args[1]["composio_connection_id"], "remote-1")

    async def test_callback_does_not_create_uninitiated_connection(self):
        payload = {
            "connected_account_id": "remote-1",
            "brand_id": "brand-1",
            "platform": "instagram",
            "status": "ACTIVE",
        }
        with patch("app.db_agency.social_connection_get_by_composio", return_value=None), \
             patch("app.db_agency.social_connection_list", return_value=[]), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("managed")):
            result = await service.handle_connection_callback(payload)

        self.assertTrue(result["ignored"])
        self.assertIn("sem conexão local pendente", result["detail"])
        update.assert_not_called()

    async def test_callback_cannot_complete_after_company_becomes_lost(self):
        existing = {
            "id": "conn-1",
            "brand_id": "brand-1",
            "platform": "instagram",
            "status": "pending",
            "composio_connection_id": "remote-1",
        }
        with patch("app.db_agency.social_connection_get_by_composio", return_value=existing), \
             patch("app.db_agency.social_connection_update") as update, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("lost")):
            with self.assertRaises(SocialProviderError) as raised:
                await service.handle_connection_callback({"connected_account_id": "remote-1", "status": "ACTIVE"})

        self.assertEqual(raised.exception.status_code, 403)
        update.assert_not_called()

    async def test_prospect_cannot_create_or_publish_social_post(self):
        with patch.object(service, "ensure_brand_exists", return_value=_brand("prospect")), \
             patch("app.db_agency.social_post_create") as create:
            with self.assertRaises(SocialProviderError) as create_error:
                await service.create_post({"brandId": "brand-1"}, _Request())
            self.assertEqual(create_error.exception.status_code, 403)
            create.assert_not_called()

        post = {"id": "post-1", "brand_id": "brand-1", "status": "approved"}
        with patch.object(service, "ensure_brand_exists", return_value=_brand("prospect")), \
             patch("app.db_agency.social_post_get", return_value=post), \
             patch("app.db_agency.social_post_acquire_for_publish") as acquire:
            with self.assertRaises(SocialProviderError) as publish_error:
                await service.publish_social_post("post-1")
            self.assertEqual(publish_error.exception.status_code, 403)
            acquire.assert_not_called()

    async def test_worker_marks_forbidden_lifecycle_post_failed_once(self):
        post = {
            "id": "post-1", "brand_id": "brand-1", "status": "scheduled",
            "metadata": {"source": "test"},
        }
        with patch("app.db_agency.social_post_due", return_value=[post]), \
             patch("app.db_agency.social_post_update") as update, \
             patch("app.db_agency.social_post_log_create") as log, \
             patch("app.db_agency.social_post_acquire_for_publish") as acquire, \
             patch.object(service, "ensure_brand_exists", return_value=_brand("lost")):
            result = await service.process_due_social_posts()

        self.assertEqual(result["triggered"], 0)
        update.assert_called_once()
        self.assertEqual(update.call_args.args[1]["status"], "failed")
        self.assertEqual(update.call_args.args[1]["metadata"]["failure_reason"],
                         "social_lifecycle_forbidden")
        log.assert_called_once()
        acquire.assert_not_called()


class SocialRouterTenancyTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_access_guard_preserves_company_scope_error(self):
        denied = JSONResponse({"detail": "Acesso negado a esta empresa."}, status_code=403)
        fake_main_utils = types.ModuleType("app.main_utils")
        fake_main_utils.company_access_denied = Mock(return_value=denied)
        with patch.dict(sys.modules, {"app.main_utils": fake_main_utils}):
            with self.assertRaises(SocialProviderError) as raised:
                social_router._ensure_brand_access(_Request(), "other-brand")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["error"], "company_scope")

    async def test_connect_route_checks_tenancy_before_starting_oauth(self):
        forbidden = SocialProviderError(
            "Acesso negado a esta empresa.",
            status_code=403,
            detail={"error": "company_scope"},
        )
        request = _Request({"brandId": "other-brand", "platform": "instagram"})
        with patch.object(social_router, "_auth", return_value=None), \
             patch.object(social_router, "_ensure_brand_access", side_effect=forbidden), \
             patch.object(social_router, "connect_account", new=AsyncMock()) as connect:
            response = await social_router.connect(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.body)["error"], "company_scope")
        connect.assert_not_awaited()

    async def test_publish_route_checks_post_owner_before_publishing(self):
        forbidden = SocialProviderError(
            "Acesso negado a esta empresa.",
            status_code=403,
            detail={"error": "company_scope"},
        )
        with patch.object(social_router, "_auth", return_value=None), \
             patch.object(social_router, "_social_post_brand_id", return_value="other-brand"), \
             patch.object(social_router, "_ensure_brand_access", side_effect=forbidden), \
             patch.object(social_router, "publish_social_post", new=AsyncMock()) as publish:
            response = await social_router.publish("post-1", _Request())

        self.assertEqual(response.status_code, 403)
        publish.assert_not_awaited()

    def test_unfiltered_post_list_is_restricted_to_session_companies(self):
        fake_main_utils = types.ModuleType("app.main_utils")
        fake_main_utils.scoped_company_ids = Mock(return_value={"brand-1", "brand-2"})

        def listed(*, brand_id, status, limit):
            return [{"id": f"post-{brand_id}", "brand_id": brand_id, "updated_at": brand_id}]

        with patch.object(social_router, "_auth", return_value=None), \
             patch.dict(sys.modules, {"app.main_utils": fake_main_utils}), \
             patch("app.db_agency.social_post_list", side_effect=listed) as post_list:
            result = social_router.list_social_posts(_Request(), brandId=None, limit=100)

        self.assertEqual({post["brand_id"] for post in result["posts"]}, {"brand-1", "brand-2"})
        self.assertEqual({call.kwargs["brand_id"] for call in post_list.call_args_list}, {"brand-1", "brand-2"})
        self.assertNotIn(None, {call.kwargs["brand_id"] for call in post_list.call_args_list})


if __name__ == "__main__":
    unittest.main()
