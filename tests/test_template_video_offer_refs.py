import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class _Router:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: (lambda fn: fn)


class _JSONResponse(dict):
    def __init__(self, content, status_code=200):
        super().__init__(content)
        self.status_code = status_code


class _Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return dict(self.body)


fake_fastapi = types.ModuleType("fastapi")
fake_fastapi.APIRouter = lambda **_kwargs: _Router()
fake_fastapi.Request = _Request
fake_responses = types.ModuleType("fastapi.responses")
fake_responses.JSONResponse = _JSONResponse

fake_db = types.ModuleType("app.db_companies")
fake_db.asset_list_logos = Mock(name="asset_list_logos")
fake_db.company_get = Mock(name="company_get")

fake_main_utils = types.ModuleType("app.main_utils")
fake_main_utils.company_access_denied = Mock(name="company_access_denied", return_value=None)
fake_main_utils.require_api_key = Mock(name="require_api_key", return_value=None)

fake_service = types.ModuleType("app.services.template_video")
fake_service.UPLOAD_DIR = "/tmp/caripost-template-video-tests"
fake_service.UPLOAD_URL_PREFIX = "/uploads"
fake_service.list_template_video_templates = Mock(return_value=[])
fake_service.render_template_video = Mock(name="render_template_video")

fake_posts = types.ModuleType("app.routers.posts")
fake_posts._offer_context = Mock(name="offer_context")
fake_posts._offer_products = Mock(name="offer_products")
fake_posts._resolve_offer_refs = Mock(name="resolve_offer_refs")

module_name = "app.routers._template_video_offer_refs_under_test"
spec = importlib.util.spec_from_file_location(
    module_name,
    Path(__file__).resolve().parents[1] / "app" / "routers" / "template_video.py",
)
template_video = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "fastapi": fake_fastapi,
    "fastapi.responses": fake_responses,
    "app.db_companies": fake_db,
    "app.main_utils": fake_main_utils,
    "app.services.template_video": fake_service,
    "app.routers.posts": fake_posts,
    module_name: template_video,
}):
    spec.loader.exec_module(template_video)


def _ai_module(*, configured=True, capture=None):
    module = types.ModuleType("app.services.ai")
    module.get_ai_config = Mock(return_value={"provider": "test"})
    module.cheap_text_config = Mock(return_value={"provider": "test"} if configured else None)

    def complete_ai(_config, system, user, _max_tokens):
        if capture is not None:
            capture.update({"system": system, "user": json.loads(user)})
        return '{"title":"Titulo gerado","eyebrow":"CARIAP"}'

    module.complete_ai = complete_ai
    module.extract_json = lambda raw: json.loads(raw)
    return module


class TemplateVideoOfferRefsTests(unittest.TestCase):
    def setUp(self):
        template_video._auth = Mock(return_value=None)
        template_video.__cad__.reset_mock(return_value=True, side_effect=True)
        template_video.__cad__.return_value = None
        template_video.company_get.reset_mock(return_value=True, side_effect=True)
        template_video.company_get.return_value = {
            "id": "target-1",
            "name": "Rio Cable",
            "segment": "Telecom",
            "brand_kit": {"voice": "direta", "colors": {"primary": "#123456"}},
        }
        template_video.asset_list_logos.reset_mock(return_value=True, side_effect=True)
        template_video.asset_list_logos.return_value = []
        template_video._resolve_offer_refs.reset_mock(return_value=True, side_effect=True)
        template_video._offer_products.reset_mock(return_value=True, side_effect=True)
        template_video._offer_context.reset_mock(return_value=True, side_effect=True)
        self.offer_ref = {"source_company_id": "seller-1", "product_id": "prod-1"}
        self.product = {
            "id": "prod-1",
            "name": "CARIAP Growth",
            "_source_company_name": "CARIAP",
            "_offer_ref": dict(self.offer_ref),
        }
        template_video._resolve_offer_refs.return_value = (True, [{"product": self.product}], None)
        template_video._offer_products.return_value = [self.product]
        template_video._offer_context.return_value = (
            "OFERTAS SELECIONADAS: CARIAP Growth | Automacao comercial validada"
        )
        template_video.render_template_video.reset_mock(return_value=True, side_effect=True)
        template_video.render_template_video.return_value = SimpleNamespace(
            job_id="job-1",
            artifact_type="mp4",
            url="/uploads/video.mp4",
            preview_url="/uploads/preview.png",
            manifest_url="/uploads/manifest.json",
            frames=[],
            mp4_url="/uploads/video.mp4",
            fallback_reason=None,
            width=1080,
            height=1920,
            duration_sec=12,
        )

    def test_suggest_uses_selected_offer_facts_but_keeps_target_brand(self):
        capture = {}
        request = _Request({
            "company_id": "target-1",
            "subject": "Venda mais",
            "offer_refs": [self.offer_ref],
        })

        with patch.dict(sys.modules, {"app.services.ai": _ai_module(capture=capture)}):
            response = asyncio.run(template_video.suggest(request))

        self.assertEqual(capture["user"]["empresa"], "Rio Cable")
        self.assertIn("CARIAP Growth", capture["user"]["ofertas_selecionadas"])
        self.assertIn("empresa-alvo", capture["system"])
        self.assertEqual(response["suggestion"]["eyebrow"], "Rio Cable")
        self.assertEqual(response["suggestion"]["offer"], "CARIAP Growth")
        self.assertEqual(response["offer_refs"], [self.offer_ref])
        template_video.__cad__.assert_called_once_with(request, "target-1")
        template_video._resolve_offer_refs.assert_called_once_with(request, request.body, "target-1")

    def test_target_tenancy_denial_stops_company_and_offer_reads(self):
        denied = _JSONResponse({"detail": "Acesso negado"}, status_code=403)
        template_video.__cad__.return_value = denied
        request = _Request({"company_id": "target-1", "subject": "Tema", "offer_refs": []})

        response = asyncio.run(template_video.suggest(request))

        self.assertIs(response, denied)
        template_video.company_get.assert_not_called()
        template_video._resolve_offer_refs.assert_not_called()

    def test_render_validates_refs_and_never_replaces_target_company(self):
        request = _Request({
            "company_id": "target-1",
            "title": "Uma oferta para voce",
            "eyebrow": "CARIAP",
            "right_label": "CARIAP",
            "offer_refs": [self.offer_ref],
        })

        response = asyncio.run(template_video.render(request))

        call = template_video.render_template_video.call_args.kwargs
        self.assertEqual(call["company"]["id"], "target-1")
        self.assertEqual(call["company"]["name"], "Rio Cable")
        self.assertEqual(call["payload"]["offer"], "CARIAP Growth")
        self.assertEqual(call["payload"]["eyebrow"], "Rio Cable")
        self.assertEqual(call["payload"]["right_label"], "Rio Cable")
        self.assertEqual(call["payload"]["offer_refs"], [self.offer_ref])
        self.assertEqual(response["offer_refs"], [self.offer_ref])

    def test_absent_offer_refs_keeps_legacy_payload_and_response_shape(self):
        template_video._resolve_offer_refs.return_value = (False, [], None)
        template_video._offer_products.return_value = []
        request = _Request({"company_id": "target-1", "title": "Institucional"})

        response = asyncio.run(template_video.render(request))

        payload = template_video.render_template_video.call_args.kwargs["payload"]
        self.assertEqual(payload, request.body)
        self.assertNotIn("offer_refs", response)
        self.assertNotIn("_offer_refs_explicit", payload)

    def test_logo_helper_skips_unapproved_social_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_upload_dir = template_video.UPLOAD_DIR
            template_video.UPLOAD_DIR = tmp
            try:
                for name in ("candidate.png", "rejected.png", "approved.png"):
                    Path(tmp, name).write_bytes(b"png")
                template_video.asset_list_logos.return_value = [
                    {"url": "/uploads/candidate.png", "meta": {"review_status": "candidate_needs_review"}},
                    {"url": "/uploads/rejected.png", "meta": {"review_status": "rejected"}},
                    {"url": "/uploads/approved.png", "meta": {"review_status": "approved"}},
                ]

                selected = template_video._first_logo_path("target-1")

                self.assertEqual(selected, os.path.join(tmp, "approved.png"))
            finally:
                template_video.UPLOAD_DIR = old_upload_dir


if __name__ == "__main__":
    unittest.main()
