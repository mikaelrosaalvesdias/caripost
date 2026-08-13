import importlib.util
import asyncio
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from PIL import Image, ImageDraw


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
fake_fastapi.UploadFile = object
fake_fastapi.File = lambda default=..., **_kwargs: default
fake_fastapi.Form = lambda default=None, **_kwargs: default
fake_responses = types.ModuleType("fastapi.responses")
fake_responses.JSONResponse = _JSONResponse

fake_companies_db = types.ModuleType("app.db_companies")
for symbol in (
    "company_list company_get company_create company_update company_delete company_convert_to_managed company_lifecycle_stage_validate "
    "brand_kit_get brand_kit_upsert brand_kit_extras_patch brand_kit_apply_auto "
    "normalize_brand_colors "
    "competitor_list competitor_create competitor_delete asset_list asset_create asset_delete asset_get "
    "asset_update_meta asset_list_logos asset_list_photos asset_clear_primary asset_set_primary_logo asset_claim_primary_logo_if_empty product_list product_get "
    "product_create product_copy product_update product_delete solution_list solution_get solution_create "
    "solution_update solution_delete "
    "infcompany_get infcompany_list infcompany_create infcompany_update infcompany_delete "
    "influencer_get influencer_list influencer_create influencer_update influencer_delete "
    "organizer_get organizer_list organizer_create organizer_update organizer_delete "
    "event_get event_list event_create event_update event_delete"
).split():
    setattr(fake_companies_db, symbol, Mock(name=symbol))


def _fake_normalize_brand_colors(colors):
    items = [(str(name), str(value)) for name, value in (colors or {}).items() if name and value]
    if not items:
        return {}
    primary_index = next((i for i, (name, _value) in enumerate(items) if name.lower() == "primary"), -1)
    if primary_index < 0:
        primary_index = next((i for i, (name, _value) in enumerate(items) if name.lower() == "accent"), 0)
    out = {"primary": items[primary_index][1]}
    out.update({name: value for i, (name, value) in enumerate(items)
                if i != primary_index and name.lower() != "primary"})
    return out


fake_companies_db.normalize_brand_colors = _fake_normalize_brand_colors
fake_db = types.ModuleType("app.db")
fake_db.settings_get = Mock(name="settings_get")
fake_ai = types.ModuleType("app.services.ai")
fake_ai.enrich_company_from_web = Mock(return_value={})
fake_main_utils = types.ModuleType("app.main_utils")
fake_main_utils.require_api_key = lambda _request: None
fake_main_utils.company_access_denied = lambda _request, _company_id: None
fake_main_utils._session_of = lambda _request: None
fake_main_utils.scoped_company_ids = lambda _request: None

module_name = "app.routers._companies_brand_under_test"
spec = importlib.util.spec_from_file_location(
    module_name,
    Path(__file__).resolve().parents[1] / "app" / "routers" / "companies.py",
)
companies = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "fastapi": fake_fastapi,
    "fastapi.responses": fake_responses,
    "app.db_companies": fake_companies_db,
    "app.db": fake_db,
    "app.services.ai": fake_ai,
    "app.main_utils": fake_main_utils,
    module_name: companies,
}):
    spec.loader.exec_module(companies)


def _near(actual, expected, tolerance=70):
    a = tuple(int(actual[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(expected[i:i + 2], 16) for i in (1, 3, 5))
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5 <= tolerance


class CompanyLifecycleRouterTests(unittest.TestCase):
    class Request:
        headers = {}
        cookies = {}

        def __init__(self, body=None):
            self.body = body or {}

        async def json(self):
            return self.body

    def test_create_defaults_to_prospect_and_rejects_invalid_stage(self):
        created = {"id": "c1", "name": "Rio Cable", "lifecycle_stage": "prospect", "socials": {}}
        fake_main_utils = types.ModuleType("app.main_utils")
        fake_main_utils._session_of = lambda _request: None
        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_lifecycle_stage_validate", return_value="prospect"), \
             patch.object(companies, "company_create", return_value=created) as create, \
             patch.dict(sys.modules, {"app.main_utils": fake_main_utils}):
            result = asyncio.run(companies.create_company(self.Request({"name": "Rio Cable"})))

        self.assertEqual(result["company"]["lifecycle_stage"], "prospect")
        self.assertEqual(create.call_args.args[0]["lifecycle_stage"], "prospect")

        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_lifecycle_stage_validate", side_effect=ValueError("inválido")), \
             patch.object(companies, "company_create") as create:
            invalid = asyncio.run(companies.create_company(self.Request({
                "name": "Rio Cable", "lifecycle_stage": "cliente",
            })))
        self.assertEqual(invalid.status_code, 422)
        create.assert_not_called()

    def test_put_rejects_invalid_stage_before_mutating_company(self):
        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_lifecycle_stage_validate", side_effect=ValueError("inválido")), \
             patch.object(companies, "company_get") as get_company, \
             patch.object(companies, "company_update") as update:
            result = asyncio.run(companies.update_company(
                "c1", self.Request({"lifecycle_stage": "cliente"}),
            ))

        self.assertEqual(result.status_code, 422)
        get_company.assert_not_called()
        update.assert_not_called()

    def test_convert_endpoint_is_authorized_and_returns_not_found(self):
        denied = _JSONResponse({"detail": "Unauthorized"}, status_code=401)
        with patch.object(companies, "_api_key_required", return_value=denied), \
             patch.object(companies, "company_convert_to_managed") as convert:
            result = companies.convert_company_to_managed("c1", self.Request())
        self.assertEqual(result.status_code, 401)
        convert.assert_not_called()

        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_convert_to_managed", return_value=None):
            result = companies.convert_company_to_managed("missing", self.Request())
        self.assertEqual(result.status_code, 404)


class BrandPaletteTests(unittest.TestCase):
    def _save_logo(self, colors, *, hidden=(255, 0, 255)):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        canvas = Image.new("RGBA", (800, 240), (*hidden, 0))
        draw = ImageDraw.Draw(canvas)
        width = 660 // len(colors)
        for index, color in enumerate(colors):
            draw.rectangle((70 + index * width, 50, 70 + (index + 1) * width - 8, 190), fill=(*color, 255))
        canvas.resize((200, 60), Image.Resampling.LANCZOS).save(tmp.name)
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        return tmp.name

    def test_logo_upload_normalizes_raster_and_rejects_active_content(self):
        raw = io.BytesIO()
        Image.new("RGB", (80, 40), (10, 20, 30)).save(raw, "JPEG")

        normalized = companies._normalize_logo_upload(raw.getvalue())

        self.assertEqual(Image.open(io.BytesIO(normalized)).format, "PNG")
        with self.assertRaises(ValueError):
            companies._normalize_logo_upload(b"<svg><script>alert(1)</script></svg>")

    def test_rio_style_palette_keeps_white_and_deduplicates_lime(self):
        path = self._save_logo([(191, 245, 3), (254, 111, 26), (255, 255, 255), (208, 248, 67)])
        palette = companies._dominant_colors(path, 8)

        self.assertTrue(any(_near(color, "#BFF503") for color in palette), palette)
        self.assertTrue(any(_near(color, "#FE6F1A") for color in palette), palette)
        self.assertTrue(any(_near(color, "#FFFFFF", 35) for color in palette), palette)
        self.assertFalse(any(_near(color, "#FF00FF", 35) for color in palette), palette)
        for index, color in enumerate(palette):
            for other in palette[index + 1:]:
                self.assertFalse(companies._brand_colors_similar(color, other), (color, other, palette))

    def test_palette_is_not_limited_to_three_when_logo_has_real_diversity(self):
        bases = [(230, 25, 40), (245, 190, 15), (20, 170, 70), (10, 175, 205), (30, 75, 220), (180, 35, 205)]
        path = self._save_logo(bases)
        palette = companies._dominant_colors(path, 8)

        self.assertGreaterEqual(len(palette), 5, palette)
        self.assertLessEqual(len(palette), 8, palette)
        for base in bases:
            expected = "#%02X%02X%02X" % base
            self.assertTrue(any(_near(color, expected, 80) for color in palette), (expected, palette))

    def test_opaque_institutional_background_is_kept(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        image = Image.new("RGB", (128, 128), (191, 245, 3))
        draw = ImageDraw.Draw(image)
        draw.ellipse((38, 38, 90, 90), fill=(255, 255, 255))
        image.save(tmp.name)
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))

        palette = companies._dominant_colors(tmp.name, 8)

        self.assertTrue(any(_near(color, "#BFF503", 35) for color in palette), palette)
        self.assertTrue(any(_near(color, "#FFFFFF", 35) for color in palette), palette)

    def test_nearly_transparent_halo_does_not_become_a_brand_color(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        image = Image.new("RGBA", (180, 180), (255, 0, 0, 50))
        draw = ImageDraw.Draw(image)
        draw.rectangle((45, 45, 135, 135), fill=(0, 80, 230, 255))
        image.save(tmp.name)
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))

        palette = companies._dominant_colors(tmp.name, 8)

        self.assertTrue(_near(palette[0], "#0050E6", 40), palette)
        self.assertFalse(any(_near(color, "#FF0000", 40) for color in palette), palette)

    def test_company_palette_uses_semantic_neutral_names(self):
        path = self._save_logo([(191, 245, 3), (254, 111, 26), (255, 255, 255), (208, 248, 67)])
        with tempfile.TemporaryDirectory() as media:
            rel = "company/logo.png"
            os.makedirs(os.path.join(media, "company"))
            Image.open(path).save(os.path.join(media, rel))
            logo = {
                "id": "logo-1", "source": "UPLOADED", "url": "/uploads/" + rel,
                "meta": {"role": "logo", "is_primary": True},
            }
            with patch.object(companies, "UPLOAD_DIR", media), \
                 patch.object(companies, "company_get", return_value={"name": "Rio Cable"}), \
                 patch.object(companies, "asset_list_logos", return_value=[logo]):
                colors = companies._company_logo_colors("company", 8)

        self.assertTrue(_near(colors["primary"], "#BFF503"), colors)
        self.assertTrue(_near(colors["accent"], "#FE6F1A"), colors)
        self.assertTrue(_near(colors["neutral_light"], "#FFFFFF", 35), colors)

    def test_site_render_completes_a_neutral_wordmark_palette(self):
        with tempfile.TemporaryDirectory() as media:
            os.makedirs(os.path.join(media, "company"))
            wordmark = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
            ImageDraw.Draw(wordmark).rectangle((20, 15, 180, 45), fill=(255, 255, 255, 255))
            wordmark.save(os.path.join(media, "company", "wordmark.png"))
            rendered = Image.new("RGB", (200, 80), (191, 245, 3))
            ImageDraw.Draw(rendered).rectangle((145, 20, 180, 60), fill=(254, 111, 26))
            rendered.save(os.path.join(media, "company", "render.png"))
            logos = [
                {"id": "wordmark", "source": "UPLOADED", "url": "/uploads/company/wordmark.png",
                 "meta": {"role": "logo", "is_primary": True}},
                {"id": "render", "source": "WEB", "url": "/uploads/company/render.png",
                 "meta": {"role": "logo", "variant": "site_render", "identity_scope": "company", "confidence": .8}},
            ]
            with patch.object(companies, "UPLOAD_DIR", media), \
                 patch.object(companies, "company_get", return_value={"name": "Empresa"}), \
                 patch.object(companies, "asset_list_logos", return_value=logos):
                colors = companies._company_logo_colors("company", 8)

        self.assertTrue(any(_near(value, "#BFF503", 45) for value in colors.values()), colors)
        self.assertTrue(any(_near(value, "#FE6F1A", 45) for value in colors.values()), colors)


class ManualPaletteValidationTests(unittest.TestCase):
    def test_manual_palette_normalizes_hex_aliases_and_primary(self):
        self.assertEqual(companies._normalize_manual_colors({
            "Principal": "#bf5", "Dourado": "112233", "accentColor": "#aabbcc",
        }), {
            "primary": "#BBFF55", "Dourado": "#112233", "accent": "#AABBCC",
        })
        self.assertEqual(companies._normalize_manual_colors({
            "accent": "#123456", "branco": "#fff",
        }), {
            "primary": "#123456", "branco": "#FFFFFF",
        })

    def test_manual_palette_rejects_empty_invalid_and_duplicate_roles(self):
        for palette in (
            {},
            {"primary": "laranja"},
            {"primary": "#123456", "principal": "#654321"},
            {"primary": "#000000", "accent": "#111111", "Destaque": "#222222"},
        ):
            with self.subTest(palette=palette), self.assertRaises(ValueError):
                companies._normalize_manual_colors(palette)

    def test_brand_kit_endpoint_replaces_removed_colors_and_rejects_invalid_hex(self):
        class Request:
            def __init__(self, body):
                self.body = body

            async def json(self):
                return self.body

        existing = {"brand_kit": {"colors": {"primary": "#111111", "azul": "#222222"}, "extras": {}}}
        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_get", return_value=existing), \
             patch.object(companies, "brand_kit_extras_patch"), \
             patch.object(companies, "brand_kit_upsert", side_effect=lambda _cid, data: data) as upsert:
            result = asyncio.run(companies.save_brand_kit("c1", Request({
                "colors": {"primary": "#ABCDEF", "branco": "#fff"},
            })))

        self.assertEqual(result["brand_kit"]["colors"], {
            "primary": "#ABCDEF", "branco": "#FFFFFF",
        })
        self.assertNotIn("azul", upsert.call_args.args[1]["colors"])

        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "company_get", return_value=existing):
            invalid = asyncio.run(companies.save_brand_kit("c1", Request({
                "colors": {"primary": "não-é-hex"},
            })))
        self.assertEqual(invalid.status_code, 422)


class LogoCandidateTests(unittest.TestCase):
    def test_instagram_handle_accepts_profile_urls_with_query_and_fragment(self):
        cases = {
            "@riocable": "riocable",
            "https://www.instagram.com/riocable/?igsh=abc#perfil": "riocable",
            "https://instagram.com/riocable?igsh=abc": "riocable",
            "www.instagram.com/rio.cable_1/?utm_source=site": "rio.cable_1",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(companies._instagram_handle(value), expected)
        self.assertEqual(companies._instagram_handle("https://www.instagram.com/reel/ABC123"), "")
        self.assertEqual(companies._instagram_handle("https://example.com/riocable"), "")

    def test_instagram_importers_use_the_normalized_official_handle(self):
        profile_url = "https://www.instagram.com/riocable/?igsh=abc#perfil"
        with patch.object(companies, "_instagram_research_import", return_value={
            "status": "not_available", "logo": 0, "refs": 0,
        }) as official_import:
            companies._ig_import("c1", profile_url, "own", 4)
        official_import.assert_called_once_with("c1", "riocable", "own", 4)

        with patch("httpx.get") as request:
            result = companies._ig_fetch_brand("c1", profile_url)
        request.assert_not_called()
        self.assertEqual(result["status"], "disabled")

    def test_reference_profile_of_managed_brand_uses_house_discovery_not_owned_instagram(self):
        company = {"id": "c1", "lifecycle_stage": "managed"}
        house = {"id": "house-fb", "platform": "facebook"}
        provider = Mock()
        provider.discover_instagram_business = AsyncMock(return_value={"id": "target", "media": []})
        provider.get_owned_instagram_profile_media = AsyncMock()
        fake_social = types.ModuleType("app.social.composio_provider")
        fake_social.ComposioSocialProvider = Mock(return_value=provider)
        with patch.object(companies, "company_get", return_value=company), \
             patch.object(companies, "_owned_social_connection", return_value={"id": "own-ig"}), \
             patch.object(companies, "_research_social_connection", return_value=house), \
             patch.dict(sys.modules, {"app.social.composio_provider": fake_social}):
            result = companies._instagram_research_import("c1", "@referencia", "reference", 4)

        self.assertEqual(result["mode"], "business_discovery")
        provider.discover_instagram_business.assert_awaited_once_with(
            handle="referencia", connection=house, media_limit=4,
        )
        provider.get_owned_instagram_profile_media.assert_not_awaited()

    def test_unapproved_social_logo_is_never_promoted_automatically(self):
        candidate = {
            "id": "logo-1", "url": "/media/uploads/c1/logo/social.png",
            "source": "INSTAGRAM",
            "meta": {"role": "logo", "review_status": "candidate_needs_review", "is_primary": False},
        }
        with patch.object(companies, "brand_kit_get", return_value={"logo_url": ""}), \
             patch.object(companies, "asset_clear_primary") as clear_primary, \
             patch.object(companies, "brand_kit_upsert") as kit_upsert, \
             patch.object(companies, "asset_set_primary_logo") as set_primary, \
             patch.object(companies, "asset_list_logos", return_value=[candidate]):
            result = companies._ensure_logo_primary_consistency("c1", [candidate])

        self.assertEqual(result, [candidate])
        set_primary.assert_not_called()
        clear_primary.assert_not_called()
        kit_upsert.assert_not_called()

    def test_parser_accepts_wordmark_and_icon_but_not_social_hero_or_partner(self):
        html = """
        <head>
          <link rel="icon" sizes="192x192" href="/media/rio-icon.png">
          <meta property="og:image" content="/campanhas/rio-cable-verao.jpg">
        </head>
        <header><picture><source srcset="/media/rio-logo-320.png 320w, /media/rio-logo-640.png 640w">
          <img src="/media/rio-logo.png" alt="Logo Rio Cable"></picture></header>
        <main><img src="/products/espn-logo.png" alt="ESPN logo"></main>
        """
        ranked = companies._site_logo_candidates(html, "https://www.riocable.com.br", "Rio Cable")
        by_kind = {item["kind"]: item for item in ranked}
        wordmark = next(item for item in ranked if item["url"].endswith("/rio-logo.png"))

        self.assertGreaterEqual(by_kind["site-icon"]["score"], 55)
        self.assertGreaterEqual(wordmark["score"], 55)
        self.assertLess(by_kind["og:image"]["score"], 55)
        partner = next(item for item in ranked if "espn" in item["url"])
        self.assertLess(partner["score"], 0)

    def test_wix_resizes_share_one_canonical_source(self):
        first = "https://static.wixstatic.com/media/b16366_abc~mv2.png/v1/fill/w_157,h_59/logo.png"
        second = "https://static.wixstatic.com/media/b16366_abc~mv2.png/v1/fill/w_97,h_36/logo.png"
        self.assertEqual(companies._canonical_logo_source(first), companies._canonical_logo_source(second))

    def test_wix_srcset_commas_do_not_split_the_logo_url(self):
        wix_url = (
            "https://static.wixstatic.com/media/b16366_abc~mv2.png/"
            "v1/fill/w_157,h_59,al_c,q_85,enc_avif,quality_auto/logo%20branca.png"
        )
        html = f'<header><img alt="Logo branca" src="/fallback.png" srcset="{wix_url} 1x"></header>'

        ranked = companies._site_logo_candidates(html, "https://www.riocable.com.br", "Rio Cable")

        self.assertEqual(ranked[0]["url"], wix_url)
        self.assertGreaterEqual(ranked[0]["score"], 55)
        self.assertNotIn("/enc_avif", [item["url"] for item in ranked])

    def test_unknown_partner_logo_in_header_is_ambiguous(self):
        html = '<header><img src="/parceiros/abrint.png" alt="Abrint"></header>'

        ranked = companies._site_logo_candidates(html, "https://empresa.example", "Empresa")

        self.assertLess(ranked[0]["score"], 55)

    def test_non_wix_query_variants_keep_distinct_source_keys(self):
        light = companies._canonical_logo_source("https://cdn.example/logo.png?theme=light")
        dark = companies._canonical_logo_source("https://cdn.example/logo.png?theme=dark")
        self.assertNotEqual(light, dark)


class OfficialFacebookOwnershipTests(unittest.TestCase):
    def _run_import(self, selected_page_id):
        provider = Mock()
        provider.discover_facebook_page = AsyncMock(return_value={
            "id": "page-1",
            "link": "https://facebook.com/rio-cable",
            "profile_picture_url": "https://cdn.example/rio-cable.png",
            "photos": [],
        })
        provider.test_connection = AsyncMock(return_value={
            "selected_page": {"id": selected_page_id},
        })
        fake_social = types.ModuleType("app.social.composio_provider")
        fake_social.ComposioSocialProvider = Mock(return_value=provider)
        own_connection = {"id": "facebook-own", "composio_connection_id": "remote-1"}

        with patch.object(companies, "company_get", return_value={
            "id": "c1", "name": "Rio Cable", "website": "https://rio.example",
            "lifecycle_stage": "managed",
        }), patch.object(companies, "_owned_social_connection", return_value=own_connection), \
             patch.object(companies, "_research_social_connection") as research_connection, \
             patch.object(companies, "_download_public_image", return_value=b"image"), \
             patch.object(companies, "_save_logo_candidate", return_value={"id": "logo-1"}) as save_logo, \
             patch.dict(sys.modules, {"app.social.composio_provider": fake_social}):
            result = companies._facebook_research_import("c1", "rio-cable", 4)

        research_connection.assert_not_called()
        provider.test_connection.assert_awaited_once_with(
            platform="facebook", connection=own_connection, selected_page_id="page-1",
        )
        return result, save_logo.call_args.kwargs["metadata"]

    def test_owned_mode_requires_exact_managed_page_match(self):
        result, metadata = self._run_import("page-1")

        self.assertTrue(result["ownership_verified"])
        self.assertEqual(result["mode"], "owned")
        self.assertEqual(metadata["rights_basis"], "owned_connected_account")
        self.assertEqual(metadata["allowed_use"], "production")
        self.assertTrue(metadata["managed_page_verified"])

    def test_managed_connection_does_not_prove_ownership_of_another_page(self):
        result, metadata = self._run_import("another-page")

        self.assertFalse(result["ownership_verified"])
        self.assertEqual(result["mode"], "page_discovery")
        self.assertEqual(metadata["rights_basis"], "official_meta_api")
        self.assertEqual(metadata["allowed_use"], "analysis_only")
        self.assertFalse(metadata["managed_page_verified"])


class CandidateImageSafetyTests(unittest.TestCase):
    def test_oversized_reference_is_rejected_before_pixel_decode(self):
        image = Mock(width=6001, height=6001)

        with patch.object(Image, "open", return_value=image):
            saved = companies._save_reference_image(
                "c1", b"encoded-image", source="WEB",
                source_url="https://example.com/ref.png", source_key="ref:1",
            )

        self.assertIsNone(saved)
        image.load.assert_not_called()

    def test_oversized_logo_is_rejected_before_pixel_decode(self):
        image = Mock(width=6001, height=6001)

        with patch.object(Image, "open", return_value=image):
            saved = companies._save_logo_candidate(
                "c1", b"encoded-image", source="FACEBOOK",
                source_url="https://example.com/logo.png", source_key="logo:1",
            )

        self.assertIsNone(saved)
        image.load.assert_not_called()


class ReferenceAnalysisConcurrencyTests(unittest.TestCase):
    def test_same_snapshot_reuses_running_revision_and_worker(self):
        refs = [{"id": "ref-1", "url": "/media/uploads/c1/references/ref.png"}]
        snapshot = {
            "reference_count": 1,
            "items": [{"id": "ref-1", "url": refs[0]["url"], "sha256": "abc", "source_key": "upload:abc"}],
        }
        state = {"profile": {}}

        def get_brand_kit(_company_id):
            return {"extras": {"reference_profile": dict(state["profile"])}}

        def patch_extras(_company_id, payload):
            state["profile"] = dict(payload["reference_profile"])

        worker = Mock()
        with patch.object(companies, "_reference_analysis_state", return_value=(refs, snapshot, "snapshot-1")), \
             patch.object(companies, "brand_kit_get", side_effect=get_brand_kit), \
             patch.object(companies, "brand_kit_extras_patch", side_effect=patch_extras), \
             patch.object(companies.threading, "Thread", return_value=worker) as thread:
            first = companies._spawn_reference_analysis("c1")
            second = companies._spawn_reference_analysis("c1")

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["snapshot"], snapshot)
        self.assertEqual(first["snapshot_key"], "snapshot-1")
        thread.assert_called_once()
        worker.start.assert_called_once()

    def test_stale_run_cannot_overwrite_newer_reference_profile(self):
        current = {"run_id": "new-run", "revision": 2, "status": "analyzing"}
        profile = {"run_id": "old-run", "revision": 1, "status": "ready"}

        with patch.dict(sys.modules, {"app.db": fake_db}), \
             patch.object(companies, "brand_kit_get", return_value={
                 "extras": {"reference_profile": current},
             }), patch.object(companies, "brand_kit_extras_patch") as persist:
            stored = companies._store_reference_profile_if_current(
                "c1", "old-run", 1, profile,
            )

        self.assertFalse(stored)
        persist.assert_not_called()

    def test_current_run_can_commit_reference_profile(self):
        current = {"run_id": "run-2", "revision": 2, "status": "analyzing"}
        profile = {"run_id": "run-2", "revision": 2, "status": "ready"}

        with patch.dict(sys.modules, {"app.db": fake_db}), \
             patch.object(companies, "brand_kit_get", return_value={
                 "extras": {"reference_profile": current},
             }), patch.object(companies, "brand_kit_extras_patch") as persist:
            stored = companies._store_reference_profile_if_current(
                "c1", "run-2", 2, profile,
            )

        self.assertTrue(stored)
        persist.assert_called_once_with("c1", {"reference_profile": profile})


class CompanyChildRouteOwnershipTests(unittest.TestCase):
    class Request:
        headers = {}
        cookies = {}

        def __init__(self, body=None):
            self.body = body or {}

        async def json(self):
            return self.body

    def test_cross_company_updates_are_rejected_before_mutation(self):
        cases = (
            (companies.update_infcompany, "infcompany_get", "infcompany_update"),
            (companies.update_influencer, "influencer_get", "influencer_update"),
            (companies.update_organizer, "organizer_get", "organizer_update"),
            (companies.update_event, "event_get", "event_update"),
        )
        for route, getter_name, updater_name in cases:
            with self.subTest(route=route.__name__), \
                 patch.dict(sys.modules, {"app.db_companies": fake_companies_db}), \
                 patch.object(companies, "_api_key_required", return_value=None), \
                 patch.object(companies, "_company_scope_required", return_value=None), \
                 patch.object(fake_companies_db, getter_name, return_value={"id": "foreign", "company_id": "c2"}), \
                 patch.object(fake_companies_db, updater_name) as update:
                result = asyncio.run(route("c1", "foreign", self.Request({"name": "X"})))

            self.assertEqual(result.status_code, 404)
            update.assert_not_called()

    def test_event_cannot_reference_an_organizer_from_another_company(self):
        with patch.dict(sys.modules, {"app.db_companies": fake_companies_db}), \
             patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "_company_scope_required", return_value=None), \
             patch.object(companies, "company_get", return_value={"id": "c1"}), \
             patch.object(fake_companies_db, "organizer_get", return_value={"id": "org-2", "company_id": "c2"}), \
             patch.object(fake_companies_db, "event_create") as create:
            result = asyncio.run(companies.create_event(
                "c1", self.Request({"name": "Expo", "organizer_id": "org-2"}),
            ))

        self.assertEqual(result.status_code, 404)
        create.assert_not_called()

    def test_event_asset_delete_checks_parent_binding(self):
        asset = {
            "id": "asset-1", "company_id": "c1", "kind": "EVENT_IMAGE",
            "meta": {"event_id": "another-event"},
        }
        with patch.dict(sys.modules, {"app.db_companies": fake_companies_db}), \
             patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "_company_scope_required", return_value=None), \
             patch.object(fake_companies_db, "event_get", return_value={"id": "event-1", "company_id": "c1"}), \
             patch.object(companies, "asset_get", return_value=asset), \
             patch.object(fake_companies_db, "asset_delete") as delete:
            result = companies.delete_event_image("c1", "event-1", "asset-1", self.Request())

        self.assertEqual(result.status_code, 404)
        delete.assert_not_called()

    def test_all_competitors_is_filtered_to_request_scope(self):
        scope_module = types.ModuleType("app.main_utils")
        scope_module.scoped_company_ids = Mock(return_value={"c1"})
        rows = [
            {"id": "r1", "company_id": "c1", "name": "Visible"},
            {"id": "r2", "company_id": "c2", "name": "Hidden"},
        ]
        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "competitor_list", return_value=rows), \
             patch.dict(sys.modules, {"app.main_utils": scope_module}):
            result = companies.list_all_competitors(self.Request())

        self.assertEqual(result["competitors"], rows[:1])


class LogoDeletionReviewTests(unittest.TestCase):
    class Request:
        headers = {}
        cookies = {}

    def test_deleting_primary_never_promotes_candidate_or_rejected_logo(self):
        primary = {
            "id": "logo-primary", "company_id": "c1", "url": "https://cdn.example/primary.png",
            "meta": {"role": "logo", "is_primary": True, "review_status": "approved"},
        }
        remaining = [
            {
                "id": "candidate", "company_id": "c1", "url": "https://cdn.example/candidate.png",
                "meta": {"role": "logo", "is_primary": False, "review_status": "candidate_needs_review"},
            },
            {
                "id": "rejected", "company_id": "c1", "url": "https://cdn.example/rejected.png",
                "meta": {"role": "logo", "is_primary": False, "review_status": "rejected"},
            },
        ]
        with patch.object(companies, "_api_key_required", return_value=None), \
             patch.object(companies, "_company_scope_required", return_value=None), \
             patch.object(companies, "asset_get", return_value=primary), \
             patch.object(companies, "asset_delete", return_value=True), \
             patch.object(companies, "brand_kit_get", return_value={"logo_url": primary["url"]}), \
             patch.object(companies, "asset_list_logos", return_value=remaining), \
             patch.object(companies, "asset_set_primary_logo") as set_primary, \
             patch.object(companies, "asset_clear_primary") as clear_primary, \
             patch.object(companies, "brand_kit_upsert") as update_kit:
            result = companies.delete_logo("c1", "logo-primary", self.Request())

        self.assertTrue(result["deleted"])
        set_primary.assert_not_called()
        clear_primary.assert_called_once_with("c1")
        update_kit.assert_called_once_with("c1", {"logo_url": None})


class ProductCatalogExtractionTests(unittest.TestCase):
    def test_catalog_name_location_ignores_state_suffix_and_punctuation(self):
        self.assertTrue(companies._catalog_name_has_location(
            "700 Mega + Streaming – Cordeiro", "Cordeiro-RJ",
        ))
        self.assertTrue(companies._catalog_name_has_location(
            "Plano São Gonçalo, RJ", "São Gonçalo / RJ",
        ))
        self.assertFalse(companies._catalog_name_has_location(
            "700 Mega + Streaming", "Cordeiro-RJ",
        ))

    def test_catalog_http_rejects_private_redirect_before_requesting_it(self):
        calls = []

        class RedirectResponse:
            status_code = 302
            url = "https://empresa.example"
            text = ""
            headers = {"location": "http://100.64.0.1/admin"}

        client = types.SimpleNamespace(get=lambda url, **_kwargs: (calls.append(url) or RedirectResponse()))
        with patch.object(companies, "_catalog_public_url", side_effect=lambda url: "100.64.0.1" not in url):
            with self.assertRaises(RuntimeError):
                companies._catalog_http_get(
                    client, "https://empresa.example", timeout=5, headers={"User-Agent": "test"},
                )

        self.assertEqual(calls, ["https://empresa.example"])

    def test_catalog_public_url_rejects_local_private_and_nonstandard_ports(self):
        for url in (
            "http://127.0.0.1", "http://169.254.169.254/latest/meta-data",
            "http://100.64.0.1", "http://localhost", "https://example.com:8443",
        ):
            self.assertFalse(companies._catalog_public_url(url), url)

    def test_catalog_candidates_ignore_assets_and_prioritize_registered_city(self):
        html = """
        <a href="https://static.parastorage.com/services/wix-thunderbolt/app.css">Wix services</a>
        <a href="https://tracking.example/services/offers">Ofertas externas</a>
        <a href="/contratos">Contratos</a>
        <a href="/cópia-contratos">Cópia contratos</a>
        <a href="/sobre">Saiba mais</a>
        <a href="/historia">Conheça</a>
        <a href="/carreiras">Saiba mais</a>
        <a href="/planos-empresariais">Planos empresariais</a>
        <a href="/planos-sem-contrato">Planos sem contrato</a>
        <a href="/internet-no-boleto">Internet no boleto</a>
        <p>Escolha sua cidade:</p>
        <script type="application/json">{"options":[
          {"value":"/resende","text":"Resende"},
          {"value":"/cordeiro","text":"Cordeiro"},
          {"value":"/logout","text":"Sair"},
          {"value":"/account/delete","text":"Excluir conta"}
        ]}</script>
        """

        candidates = companies._catalog_page_candidates(
            "https://www.riocable.com.br", [html], city="Cordeiro",
        )
        urls = [item["url"] for item in candidates]

        self.assertEqual(urls[0], "https://www.riocable.com.br/cordeiro")
        self.assertIn("https://www.riocable.com.br/planos-empresariais", urls)
        self.assertIn("https://www.riocable.com.br/planos-sem-contrato", urls)
        self.assertIn("https://www.riocable.com.br/internet-no-boleto", urls)
        self.assertNotIn("https://www.riocable.com.br/resende", urls)
        self.assertNotIn("https://www.riocable.com.br/contratos", urls)
        self.assertNotIn("https://www.riocable.com.br/cópia-contratos", urls)
        self.assertNotIn("https://www.riocable.com.br/logout", urls)
        self.assertNotIn("https://www.riocable.com.br/account/delete", urls)
        self.assertFalse(any(url.endswith(("/sobre", "/historia", "/carreiras")) for url in urls))
        self.assertFalse(any("parastorage" in url or "tracking.example" in url for url in urls))

    def test_city_hub_over_300_chars_renders_and_creates_real_tiers_idempotently(self):
        base = "https://www.riocable.com.br"
        city_url = base + "/cordeiro"
        home_html = (
            "<html><body>Planos de internet | Serviços | Área do cliente. Escolha sua cidade "
            + ("Informações institucionais. " * 30) +
            '<a href="https://static.parastorage.com/services/wix/app.css">CSS Wix</a>'
            '<script type="application/json">{"options":[{"value":"/cordeiro","text":"Cordeiro-RJ"}]}</script>'
            '</body></html>'
        )
        city_shell = "<html><body>" + ("Carregando conteúdo. " * 25) + "</body></html>"
        city_text = (
            "Planos de Internet Cordeiro. 400 MEGA por R$ 89,90/mês. "
            "700 MEGA com TV digital por R$ 159,90/mês. Contratar agora."
        )
        http_calls = []

        class Response:
            def __init__(self, text, url):
                self.text = text
                self.url = url
                self.status_code = 200
                self.headers = {"content-type": "text/html; charset=utf-8"}

        fake_httpx = types.ModuleType("httpx")

        def http_get(url, **_kwargs):
            http_calls.append(url)
            if url == base:
                return Response(home_html, base)
            if url == city_url:
                return Response(city_shell, city_url)
            raise AssertionError("URL externa não deveria ser acessada: " + url)

        fake_httpx.get = http_get
        render_calls = []

        def render(url):
            render_calls.append(url)
            if url == city_url:
                return {"text": city_text, "html": "<main>" + city_text + "</main>"}
            return {"text": "Escolha sua cidade", "html": home_html}

        first_ai_payload = json.dumps({"products": [
            {
                "name": "400 Mega", "description": "Internet de 400 Mega.",
                "objective": "Vender velocidade com economia.", "functions": ["400 Mbps"],
                "price": "R$ 89,90/mês", "location": "", "source_url": city_url,
            },
            {
                "name": "700 Mega + Streaming – Cordeiro", "description": "Internet de 700 Mega com TV.",
                "objective": "Vender conectividade e entretenimento.", "functions": ["700 Mbps", "TV digital"],
                "price": "R$ 159,90/mês", "location": "Cordeiro-RJ", "source_url": city_url,
            },
            {"name": "Internet Fibra Óptica", "location": "Cordeiro-RJ", "source_url": city_url},
        ]})
        second_ai_payload = json.dumps({"products": [
            {
                "name": "400 Mbps", "description": "Internet de 400 Mega.",
                "objective": "Vender velocidade com economia.", "functions": ["400 Mbps"],
                "price": "R$ 89,90/mês", "location": "Cordeiro", "source_url": "",
            },
            {
                "name": "700 Mbps + Streaming - Cordeiro", "description": "Internet de 700 Mega com TV.",
                "objective": "Vender conectividade e entretenimento.", "functions": ["700 Mbps", "TV digital"],
                "price": "R$ 159,90/mês", "location": "Cordeiro", "source_url": city_url,
            },
        ]})
        stored = []

        def create_product(_company_id, data):
            product = dict(data, id=f"p{len(stored) + 1}")
            stored.append(product)
            return product

        with patch.dict(sys.modules, {
                 "httpx": fake_httpx, "app.services.ai": fake_ai, "app.db_companies": fake_companies_db,
             }), \
             patch.object(companies, "company_get", return_value={"id": "c1", "name": "Rio Cable", "city": ""}), \
             patch.object(companies, "_catalog_public_url", return_value=True), \
             patch.object(companies, "_render_site", side_effect=render), \
             patch.object(fake_companies_db, "product_list", side_effect=lambda _cid: list(stored)), \
             patch.object(fake_companies_db, "product_create", side_effect=create_product), \
             patch.object(fake_ai, "get_ai_config", return_value={"provider": "test"}, create=True), \
             patch.object(fake_ai, "cheap_text_config", side_effect=lambda value: value, create=True), \
             patch.object(fake_ai, "complete_ai", side_effect=[first_ai_payload, second_ai_payload], create=True), \
             patch.object(fake_ai, "extract_json", side_effect=json.loads, create=True):
            first = companies._auto_extract_products("c1", base)
            second = companies._auto_extract_products("c1", base)

        self.assertGreater(len(companies._catalog_visible_text(home_html)), 300)
        self.assertGreaterEqual(companies._catalog_offer_score(home_html), companies._CATALOG_MIN_SCORE)
        self.assertFalse(companies._catalog_has_concrete_offer_signal(home_html))
        self.assertIn(base, render_calls, "A home longa, mas sem ofertas, precisa ser renderizada")
        self.assertIn(city_url, render_calls)
        self.assertFalse(any("parastorage" in url for url in http_calls))
        self.assertEqual(first["found"], 2, first)
        self.assertEqual(first["added"], 2)
        self.assertEqual(second["found"], 2)
        self.assertEqual(second["added"], 0)
        self.assertEqual(
            [item["name"] for item in stored],
            ["400 Mega — Cordeiro-RJ", "700 Mega + Streaming – Cordeiro"],
        )
        self.assertIn("Preço: R$ 89,90/mês", stored[0]["functions"])
        self.assertEqual(stored[0]["website"], city_url)


class EnrichmentOrchestrationTests(unittest.TestCase):
    @staticmethod
    def _png_bytes(color, alpha=255):
        buffer = io.BytesIO()
        Image.new("RGBA", (128, 64), (*color, alpha)).save(buffer, "PNG")
        return buffer.getvalue()

    def test_rediscovery_runs_even_when_a_logo_already_exists(self):
        company = {"id": "c1", "name": "Empresa", "website": "https://example.com", "socials": {}, "brand_kit": {}}
        existing_logo = {"id": "l1", "source": "UPLOADED", "url": "/uploads/c1/logo.png",
                         "meta": {"role": "logo", "is_primary": True}}
        with patch.object(companies, "company_get", return_value=company), \
             patch.object(companies, "company_update"), \
             patch.object(companies, "brand_kit_get", return_value={"colors": {}, "extras": {}}), \
             patch.object(companies, "brand_kit_upsert"), \
             patch.object(companies, "_store_enrichment_status", return_value={}) as store_status, \
             patch.object(companies, "asset_list_logos", return_value=[existing_logo]), \
             patch.object(companies, "_remove_misclassified_web_logos"), \
             patch.object(companies, "_auto_fetch_logo") as discover, \
             patch.object(companies, "_auto_extract_products", return_value={
                 "added": 2, "found": 3, "pages_scanned": 4, "warnings": ["uma oferta foi ignorada"],
             }), \
             patch.object(companies, "_company_logo_colors", return_value={"primary": "#112233"}), \
             patch.object(fake_ai, "enrich_company_from_web", return_value={}), \
             patch.dict(sys.modules, {"app.services.ai": fake_ai}):
            companies._run_company_enrichment("c1", {})

        discover.assert_called_once_with("c1", "https://example.com")
        final_status = next(call.kwargs for call in reversed(store_status.call_args_list)
                            if call.kwargs.get("state") == "done")
        self.assertEqual(final_status["products_added"], 2)
        self.assertEqual(final_status["products_found"], 3)
        self.assertEqual(final_status["product_pages_scanned"], 4)
        self.assertIn("Produtos e serviços: uma oferta foi ignorada", final_status["warnings"])

    def _run_palette_case(self, current_kit, detected):
        company = {"id": "c1", "name": "Rio Cable", "website": "https://example.com", "socials": {}}
        with patch.object(companies, "company_get", return_value=company), \
             patch.object(companies, "company_update"), \
             patch.object(companies, "brand_kit_get", return_value=current_kit), \
             patch.object(companies, "brand_kit_apply_auto") as apply_auto, \
             patch.object(companies, "brand_kit_extras_patch") as patch_extras, \
             patch.object(companies, "_store_enrichment_status", return_value={}), \
             patch.object(companies, "asset_list_logos", return_value=[]), \
             patch.object(companies, "_remove_misclassified_web_logos"), \
             patch.object(companies, "_auto_fetch_logo"), \
             patch.object(companies, "_auto_extract_products", return_value=0), \
             patch.object(companies, "_company_logo_colors", return_value=detected), \
             patch.object(fake_ai, "enrich_company_from_web", return_value={}), \
             patch.dict(sys.modules, {"app.services.ai": fake_ai}):
            companies._run_company_enrichment("c1", {})
        return apply_auto.call_args.args[1], patch_extras

    def test_rio_legacy_duplicate_palette_is_repaired(self):
        old = {
            "colors": {"primary": "#BFF503", "secondary": "#FE6F1A", "accent": "#D0F843"},
            "extras": {},
        }
        corrected = {"primary": "#BFF503", "accent": "#FE6F1A", "neutral_light": "#FFFFFF"}

        automatic_update, _extras = self._run_palette_case(old, corrected)

        self.assertEqual(automatic_update["colors"], corrected)

    def test_unmarked_legacy_palette_without_duplicate_is_preserved(self):
        legacy = {"colors": {"primary": "#123456", "accent": "#FEDCBA"}, "extras": {}}

        automatic_update, extras_patch = self._run_palette_case(
            legacy, {"primary": "#010203", "accent": "#AABBCC"},
        )

        self.assertNotIn("colors", automatic_update)
        self.assertTrue(any(
            call.args[1].get("palette_source") == "legacy_preserved"
            for call in extras_patch.call_args_list
        ))

    def test_missing_local_logo_is_redownloaded_from_the_same_source(self):
        source_url = "https://cdn.example/logo.png"
        stale_url = "/uploads/c1/logo/missing.png"
        stale = {
            "id": "stale", "source": "WEB", "url": stale_url,
            "meta": {"role": "logo", "is_primary": True, "from": source_url},
        }
        html = f'<header><img src="{source_url}" alt="Logo Empresa"></header>'
        image_bytes = self._png_bytes((20, 110, 220))

        class Response:
            def __init__(self, *, text="", content=b"", url="https://empresa.example", status=200):
                self.text, self.content, self.url, self.status_code = text, content, url, status

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Timeout = lambda *_args, **_kwargs: None
        fake_httpx.Client = MagicMock()
        fake_httpx.get = lambda url, **_kwargs: (
            Response(text=html) if url == "https://empresa.example" else
            Response(content=image_bytes, url=source_url)
        )
        kit = {"logo_url": stale_url}

        def update_kit(_company_id, data):
            kit.update(data)
            return dict(kit)

        with tempfile.TemporaryDirectory() as media, \
             patch.dict(sys.modules, {"httpx": fake_httpx}), \
             patch.object(companies, "UPLOAD_DIR", media), \
             patch.object(companies, "company_get", return_value={"name": "Empresa"}), \
             patch.object(companies, "asset_list_logos", return_value=[stale]), \
             patch.object(companies, "asset_delete") as delete_asset, \
             patch.object(companies, "asset_create") as create_asset, \
             patch.object(companies, "brand_kit_get", side_effect=lambda _cid: dict(kit)), \
             patch.object(companies, "brand_kit_upsert", side_effect=update_kit), \
             patch.object(companies, "_catalog_http_get", return_value=Response(text=html)), \
             patch.object(companies, "_download_public_image", return_value=image_bytes), \
             patch.object(companies, "_render_site", return_value={}):
            result = companies._auto_fetch_logo("c1", "https://empresa.example")

        delete_asset.assert_called_once_with("stale")
        create_asset.assert_called_once()
        self.assertTrue(result and result != stale_url, result)

    def test_fully_transparent_candidate_is_not_saved_as_primary(self):
        source_url = "https://cdn.example/logo.png"
        html = f'<header><img src="{source_url}" alt="Logo Empresa"></header>'
        image_bytes = self._png_bytes((255, 255, 255), alpha=0)

        class Response:
            def __init__(self, *, text="", content=b"", url="https://empresa.example"):
                self.text, self.content, self.url, self.status_code = text, content, url, 200

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Timeout = lambda *_args, **_kwargs: None
        fake_httpx.get = lambda url, **_kwargs: (
            Response(text=html) if url == "https://empresa.example" else
            Response(content=image_bytes, url=source_url)
        )
        with tempfile.TemporaryDirectory() as media, \
             patch.dict(sys.modules, {"httpx": fake_httpx}), \
             patch.object(companies, "UPLOAD_DIR", media), \
             patch.object(companies, "company_get", return_value={"name": "Empresa"}), \
             patch.object(companies, "asset_list_logos", return_value=[]), \
             patch.object(companies, "asset_create") as create_asset, \
             patch.object(companies, "brand_kit_get", return_value={}), \
             patch.object(companies, "brand_kit_upsert"), \
             patch.object(companies, "_render_site", return_value={}):
            result = companies._auto_fetch_logo("c1", "https://empresa.example")

        create_asset.assert_not_called()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
