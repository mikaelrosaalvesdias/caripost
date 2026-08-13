import importlib.util
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class _Router:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: (lambda fn: fn)


class _JSONResponse(dict):
    def __init__(self, content, status_code=200):
        super().__init__(content)
        self.status_code = status_code


fake_fastapi = types.ModuleType("fastapi")
fake_fastapi.APIRouter = lambda **_kwargs: _Router()
fake_fastapi.Request = object
fake_responses = types.ModuleType("fastapi.responses")
fake_responses.JSONResponse = _JSONResponse

fake_db = types.ModuleType("app.db_companies")
for symbol in (
    "post_list post_get post_create post_transition post_update post_delete post_stats "
    "POST_STATUSES POST_TRANSITIONS POST_LABELS company_get company_list report_get_latest report_create "
    "asset_list_logos asset_list asset_list_photos product_list product_get solution_list "
    "influencer_get influencer_list event_get organizer_get"
).split():
    setattr(fake_db, symbol, [] if symbol == "POST_STATUSES" else Mock(name=symbol))
fake_db.POST_TRANSITIONS = {}
fake_db.POST_LABELS = {}

fake_ai = types.ModuleType("app.services.ai")
for symbol in (
    "get_ai_config generate_post_copy generate_trends is_ai_enabled generate_image_bytes "
    "generate_image_with_cost generate_image_resilient image_models_registry vision_clear_side "
    "vision_read_text text_render_issues judge_art_text text_fix_feedback generate_image_with_person "
    "compose_person_scene verify_same_person pick_influencer_photo generate_image_edit build_image_prompt "
    "get_image_config generate_image_reference_full image_ref_models get_image_ref_model "
    "openrouter_image_models openrouter_video_models cometapi_video_models omniroute_video_models "
    "kie_video_models kie_image_models omniroute_image_models openai_image_models piapi_image_models "
    "cometapi_image_models usd_to_brl get_setting create_video_job get_video_job download_video "
    "build_video_prompt build_video_storyboard get_video_config accept_kie_callback kie_callback_token"
).split():
    setattr(fake_ai, symbol, Mock(name=symbol))

fake_main_utils = types.ModuleType("app.main_utils")
fake_main_utils.company_access_denied = Mock(return_value=None)
fake_main_utils.require_api_key = Mock(return_value=None)
fake_main_utils.scoped_company_ids = Mock(return_value=None)

module_name = "app.routers._posts_offer_refs_under_test"
spec = importlib.util.spec_from_file_location(
    module_name,
    Path(__file__).resolve().parents[1] / "app" / "routers" / "posts.py",
)
posts = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "fastapi": fake_fastapi,
    "fastapi.responses": fake_responses,
    "app.db_companies": fake_db,
    "app.services.ai": fake_ai,
    "app.main_utils": fake_main_utils,
    module_name: posts,
}):
    spec.loader.exec_module(posts)


class OfferRefsTests(unittest.TestCase):
    def setUp(self):
        fake_main_utils.scoped_company_ids.return_value = None
        posts.company_get = Mock(side_effect=lambda company_id: {
            "id": company_id, "name": "Catálogo " + company_id,
        })
        posts.product_get = Mock(return_value={
            "id": "prod-1", "company_id": "seller-1", "name": "Oferta Um",
            "knowledge": "fato verificado",
        })
        posts.asset_list_logos = Mock(return_value=[{"url": "/uploads/logo.png"}])
        posts.asset_list_photos = Mock(return_value=[{"url": "/uploads/photo.png"}])
        posts.solution_list = Mock(return_value=[{"name": "Benefício"}])
        posts.__cad__ = Mock(return_value=None)

    def test_absent_key_preserves_legacy_without_catalog_reads(self):
        explicit, offers, error = posts._resolve_offer_refs(object(), {}, "target-1")

        self.assertFalse(explicit)
        self.assertEqual(offers, [])
        self.assertIsNone(error)
        posts.product_get.assert_not_called()
        posts.asset_list_logos.assert_not_called()

    def test_explicit_empty_list_means_no_product_and_disables_legacy_lookup(self):
        explicit, offers, error = posts._resolve_offer_refs(
            object(), {"offer_refs": []}, "target-1",
        )
        scoped = posts._company_with_offer_products({"id": "target-1"}, explicit, [])

        self.assertTrue(explicit)
        self.assertEqual(offers, [])
        self.assertIsNone(error)
        self.assertTrue(scoped["_offer_products_explicit"])
        self.assertEqual(scoped["_offer_products_override"], [])
        posts.product_get.assert_not_called()

    def test_selected_pair_is_deduplicated_and_materialized_by_validated_ids(self):
        ref = {"source_company_id": "seller-1", "product_id": "prod-1"}
        explicit, offers, error = posts._resolve_offer_refs(
            object(), {"offer_refs": [ref, dict(ref)]}, "target-1",
        )
        products = posts._offer_products(offers)

        self.assertTrue(explicit)
        self.assertIsNone(error)
        self.assertEqual(len(offers), 1)
        self.assertEqual(products[0]["_offer_ref"], ref)
        self.assertEqual(products[0]["_source_company_id"], "seller-1")
        self.assertEqual(products[0]["_photos"][0]["url"], "/uploads/photo.png")
        posts.asset_list_logos.assert_called_once_with("seller-1", "prod-1")
        posts.asset_list_photos.assert_called_once_with("seller-1", "prod-1")

    def test_product_must_belong_to_declared_catalog_company(self):
        posts.product_get.return_value = {
            "id": "prod-1", "company_id": "different-company", "name": "Outra",
        }
        explicit, offers, error = posts._resolve_offer_refs(object(), {
            "offer_refs": [{"source_company_id": "seller-1", "product_id": "prod-1"}],
        }, "target-1")

        self.assertTrue(explicit)
        self.assertEqual(offers, [])
        self.assertEqual(error.status_code, 422)
        posts.asset_list_logos.assert_not_called()
        posts.asset_list_photos.assert_not_called()

    def test_tenancy_denial_is_returned_before_product_or_asset_reads(self):
        posts.__cad__.return_value = _JSONResponse(
            {"detail": "Acesso negado", "error": "company_scope"}, status_code=403,
        )
        explicit, offers, error = posts._resolve_offer_refs(object(), {
            "offer_refs": [{"source_company_id": "seller-1", "product_id": "prod-1"}],
        }, "target-1")

        self.assertTrue(explicit)
        self.assertEqual(offers, [])
        self.assertEqual(error.status_code, 403)
        posts.product_get.assert_not_called()
        posts.asset_list_logos.assert_not_called()

    def test_slide_gets_exact_offer_ref_from_selected_product(self):
        product = {
            "id": "prod-1", "name": "Oferta Um",
            "_offer_ref": {"source_company_id": "seller-1", "product_id": "prod-1"},
        }
        slides = [{"app": "Oferta Um", "title": "Uma proposta"}]

        posts._attach_offer_refs(slides, [product])

        self.assertEqual(slides[0]["offer_ref"], product["_offer_ref"])

    def test_catalog_endpoint_filters_companies_by_tenancy(self):
        fake_main_utils.scoped_company_ids.return_value = {"target-1", "seller-1"}
        fake_db.company_list.return_value = [
            {"id": "target-1", "name": "Prospect"},
            {"id": "seller-1", "name": "CARIAP"},
            {"id": "hidden-1", "name": "Outro tenant"},
        ]
        posts.product_list = Mock(side_effect=lambda company_id: [{
            "id": "prod-" + company_id, "name": "Oferta " + company_id, "active": True,
            "knowledge": "kb",
        }])
        posts.asset_list_logos = Mock(return_value=[])
        posts.asset_list_photos = Mock(return_value=[])

        with patch.dict(sys.modules, {
            "app.db_companies": fake_db,
            "app.main_utils": fake_main_utils,
        }):
            response = posts.offer_catalog(object(), "target-1")

        self.assertEqual(
            [catalog["company_id"] for catalog in response["catalogs"]],
            ["target-1", "seller-1"],
        )
        self.assertNotIn("hidden-1", [call.args[0] for call in posts.product_list.call_args_list])


class ReferenceApprovalTests(unittest.TestCase):
    def test_only_approved_or_legacy_manual_references_are_usable(self):
        self.assertTrue(posts._reference_is_approved({
            "source": "WEB", "meta": {"review_status": "approved"},
        }))
        self.assertTrue(posts._reference_is_approved({"source": "UPLOADED", "meta": {}}))
        self.assertFalse(posts._reference_is_approved({
            "source": "INSTAGRAM", "meta": {"review_status": "candidate_needs_review"},
        }))
        self.assertFalse(posts._reference_is_approved({
            "source": "FACEBOOK", "meta": {"review_status": "rejected"},
        }))

    def test_social_logo_candidate_is_not_used_before_approval(self):
        self.assertFalse(posts._logo_is_approved({
            "source": "INSTAGRAM", "meta": {"review_status": "candidate_needs_review"},
        }))
        self.assertTrue(posts._logo_is_approved({
            "source": "INSTAGRAM", "meta": {"review_status": "approved"},
        }))
        self.assertTrue(posts._logo_is_approved({"source": "WEB", "meta": {}}))


class UploadPathSafetyTests(unittest.TestCase):
    def test_local_upload_loader_is_contained_and_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as root, patch.object(posts, "UPLOAD_DIR", root):
            own_dir = Path(root) / "target-1" / "generated"
            own_dir.mkdir(parents=True)
            (own_dir / "art.png").write_bytes(b"safe")
            other_dir = Path(root) / "other-1"
            other_dir.mkdir()
            (other_dir / "private.png").write_bytes(b"private")

            self.assertEqual(
                posts._load_upload_bytes("/uploads/target-1/generated/art.png", {"target-1"}),
                b"safe",
            )
            self.assertIsNone(posts._load_upload_bytes(
                "/uploads/other-1/private.png", {"target-1"},
            ))
            self.assertIsNone(posts._load_upload_bytes(
                "/uploads/target-1/../../other-1/private.png", {"target-1"},
            ))
            self.assertIsNone(posts._load_upload_bytes(
                "https://evil.example/uploads/target-1/generated/art.png", {"target-1"},
            ))

    def test_absolute_upload_url_requires_the_exact_configured_origin(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(posts, "UPLOAD_DIR", root), \
             patch.object(posts, "get_setting", return_value="https://media.example:8443"):
            own_dir = Path(root) / "target-1"
            own_dir.mkdir()
            (own_dir / "art.png").write_bytes(b"safe")

            accepted = posts._resolve_upload_path(
                "https://media.example:8443/uploads/target-1/art.png", "target-1",
            )

            self.assertEqual(accepted, str(own_dir / "art.png"))
            for unsafe in (
                "http://media.example:8443/uploads/target-1/art.png",
                "https://media.example/uploads/target-1/art.png",
                "https://user@media.example:8443/uploads/target-1/art.png",
                "//media.example:8443/uploads/target-1/art.png",
            ):
                with self.subTest(url=unsafe):
                    self.assertIsNone(posts._resolve_upload_path(unsafe, {"target-1"}))

    def test_loader_enforces_stream_limit_and_rejects_noncanonical_paths(self):
        with tempfile.TemporaryDirectory() as root, patch.object(posts, "UPLOAD_DIR", root):
            own_dir = Path(root) / "target-1"
            own_dir.mkdir()
            (own_dir / "large.bin").write_bytes(b"12345")

            self.assertIsNone(posts._load_upload_bytes(
                "/uploads/target-1/large.bin", {"target-1"}, max_bytes=4,
            ))
            self.assertIsNone(posts._resolve_upload_path(
                "/uploads/target-1//large.bin", {"target-1"},
            ))
            self.assertIsNone(posts._resolve_upload_path(
                "/uploads/target-1/%2e%2e/other.bin", {"target-1"},
            ))


class NestedOwnershipTests(unittest.TestCase):
    class Request:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    def test_influencer_photos_are_filtered_by_asset_owner_and_path(self):
        with tempfile.TemporaryDirectory() as root, patch.object(posts, "UPLOAD_DIR", root):
            target = Path(root) / "target-1" / "influencers" / "inf-1"
            other = Path(root) / "other-1" / "influencers" / "inf-1"
            target.mkdir(parents=True)
            other.mkdir(parents=True)
            (target / "safe.jpg").write_bytes(b"safe")
            (other / "private.jpg").write_bytes(b"private")
            fake_db.influencer_get.return_value = {
                "id": "inf-1", "company_id": "target-1", "photos": [
                    {
                        "id": "safe", "company_id": "target-1",
                        "url": "/uploads/target-1/influencers/inf-1/safe.jpg",
                    },
                    {
                        "id": "foreign-row", "company_id": "other-1",
                        "url": "/uploads/target-1/influencers/inf-1/safe.jpg",
                    },
                    {
                        "id": "foreign-path", "company_id": "target-1",
                        "url": "/uploads/other-1/influencers/inf-1/private.jpg",
                    },
                ],
            }

            with patch.dict(sys.modules, {"app.db_companies": fake_db}):
                result = posts._load_owned_influencer("inf-1", "target-1")

            self.assertEqual([photo["id"] for photo in result["photos"]], ["safe"])
            fake_db.influencer_get.return_value = {
                "id": "inf-1", "company_id": "other-1", "photos": [],
            }
            with patch.dict(sys.modules, {"app.db_companies": fake_db}):
                self.assertIsNone(posts._load_owned_influencer("inf-1", "target-1"))

    def test_event_rejects_foreign_organizer_and_filters_nested_assets(self):
        with tempfile.TemporaryDirectory() as root, patch.object(posts, "UPLOAD_DIR", root):
            event_dir = Path(root) / "target-1" / "events" / "event-1"
            event_dir.mkdir(parents=True)
            (event_dir / "logo.png").write_bytes(b"logo")
            fake_db.event_get.return_value = {
                "id": "event-1", "company_id": "target-1", "organizer_id": "org-1",
                "logos": [{
                    "id": "event-logo", "company_id": "target-1",
                    "url": "/uploads/target-1/events/event-1/logo.png",
                }],
                "images": [],
            }
            fake_db.organizer_get.return_value = {
                "id": "org-1", "company_id": "other-1", "logos": [],
            }

            with patch.dict(sys.modules, {"app.db_companies": fake_db}):
                event, organizer = posts._load_owned_event("event-1", "target-1")

            self.assertIsNone(event)
            self.assertIsNone(organizer)

            fake_db.organizer_get.return_value = {
                "id": "org-1", "company_id": "target-1", "logos": [{
                    "id": "bad-logo", "company_id": "other-1",
                    "url": "/uploads/target-1/events/event-1/logo.png",
                }],
            }
            with patch.dict(sys.modules, {"app.db_companies": fake_db}):
                event, organizer = posts._load_owned_event("event-1", "target-1")
            self.assertEqual([logo["id"] for logo in event["logos"]], ["event-logo"])
            self.assertEqual(organizer["logos"], [])

    def test_render_and_briefing_fail_closed_on_foreign_nested_records(self):
        company = {"id": "target-1", "name": "Prospect", "brand_kit": {}}
        with patch.object(posts, "_api_key_required", return_value=None), \
             patch.object(posts, "company_get", return_value=company), \
             patch.object(posts, "__cad__", return_value=None), \
             patch.object(posts, "_resolve_offer_refs", return_value=(False, [], None)), \
             patch.object(posts, "_load_owned_influencer", return_value=None):
            response = asyncio.run(posts.render_carousel(self.Request({
                "company_id": "target-1",
                "influencer_id": "foreign-influencer",
                "telas": [{"title": "Teste"}],
            })))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["detail"], "Influencer não encontrado")

        with patch.object(posts, "_api_key_required", return_value=None), \
             patch.object(posts, "company_get", return_value=company), \
             patch.object(posts, "__cad__", return_value=None), \
             patch.object(posts, "_resolve_offer_refs", return_value=(False, [], None)), \
             patch.object(posts, "_load_owned_event", return_value=(None, None)):
            response = asyncio.run(posts.generate_briefing_ep(self.Request({
                "company_id": "target-1", "theme": "Evento", "event_id": "foreign-event",
            })))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["detail"], "Evento não encontrado")


if __name__ == "__main__":
    unittest.main()
