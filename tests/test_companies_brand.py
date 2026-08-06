import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
    "company_list company_get company_create company_update company_delete brand_kit_get brand_kit_upsert brand_kit_extras_patch brand_kit_apply_auto "
    "competitor_list competitor_create competitor_delete asset_list asset_create asset_delete asset_get "
    "asset_update_meta asset_list_logos asset_list_photos asset_clear_primary asset_set_primary_logo asset_claim_primary_logo_if_empty product_list product_get "
    "product_create product_copy product_update product_delete solution_list solution_get solution_create "
    "solution_update solution_delete"
).split():
    setattr(fake_companies_db, symbol, Mock(name=symbol))
fake_db = types.ModuleType("app.db")
fake_db.settings_get = Mock(name="settings_get")
fake_ai = types.ModuleType("app.services.ai")
fake_ai.enrich_company_from_web = Mock(return_value={})

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
    module_name: companies,
}):
    spec.loader.exec_module(companies)


def _near(actual, expected, tolerance=70):
    a = tuple(int(actual[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(expected[i:i + 2], 16) for i in (1, 3, 5))
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5 <= tolerance


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
        api_response = Mock(status_code=200)
        api_response.json.return_value = {"data": {"user": {}}}
        public_response = Mock(status_code=200, text="")

        with patch.object(companies, "_ig_headers", return_value=({"User-Agent": "test"}, False)), \
             patch("httpx.get", return_value=api_response) as request:
            companies._ig_import("c1", profile_url, "own", 4)
            self.assertEqual(
                request.call_args.args[0],
                "https://i.instagram.com/api/v1/users/web_profile_info/?username=riocable",
            )

        with patch.object(companies, "asset_list_logos", return_value=[]), \
             patch("httpx.get", return_value=public_response) as request:
            companies._ig_fetch_brand("c1", profile_url)
            self.assertEqual(request.call_args.args[0], "https://www.instagram.com/riocable/")

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
             patch.object(companies, "_store_enrichment_status", return_value={}), \
             patch.object(companies, "asset_list_logos", return_value=[existing_logo]), \
             patch.object(companies, "_remove_misclassified_web_logos"), \
             patch.object(companies, "_auto_fetch_logo") as discover, \
             patch.object(companies, "_auto_extract_products", return_value=0), \
             patch.object(companies, "_company_logo_colors", return_value={"primary": "#112233"}), \
             patch.object(fake_ai, "enrich_company_from_web", return_value={}), \
             patch.dict(sys.modules, {"app.services.ai": fake_ai}):
            companies._run_company_enrichment("c1", {})

        discover.assert_called_once_with("c1", "https://example.com")

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
