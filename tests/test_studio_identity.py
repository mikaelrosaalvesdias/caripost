import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageFont

from app.services import brand_fonts
from app.services.brand_footer import get_kit
from app.services.studio_identity import stamp_apps, stamp_footer


def png(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class StudioIdentityTests(unittest.TestCase):
    def test_automatic_footer_rejects_photo_fragments_but_preserves_structured_and_manual_kits(self):
        def company(kit):
            return {"brand_kit": {"creative_config": {"design": {"footer_kit": kit}}}}
        kit = {"auto": True, "light": {"url": "footer.png"}, "spec": {"elements": [
            {"type": "logo", "w": 0.2, "h": 0.06},
            {"type": "text", "w": 0.4, "h": 0.02},
            {"type": "icon", "w": 0.025, "h": 0.025},
        ]}}
        self.assertEqual(get_kit(company(kit)), kit)
        bad = dict(kit, spec={"elements": kit["spec"]["elements"] + [
            {"type": "icon", "w": 0.45, "h": 0.18},
        ]})
        self.assertEqual(get_kit(company(bad)), {})
        self.assertEqual(get_kit(company(dict(bad, edited=True))), dict(bad, edited=True))
        self.assertEqual(get_kit(company({"auto": True, "light": {"url": "unverified.png"}})), {})

    def test_no_references_gets_real_local_fonts_without_persisting_a_fake_identity(self):
        with patch.object(brand_fonts, "_own_arts", return_value=[]), patch.object(brand_fonts, "save") as save:
            typo = brand_fonts.ensure({"id": "prospect"})
        self.assertEqual(typo["method"], "fallback")
        for role in ("title", "body"):
            ImageFont.truetype(typo[role]["file"], 32)
            self.assertNotIn("Cariap", typo[role]["file"])
        self.assertTrue(brand_fonts.specimen(typo, "Conexão para sua família", "Conheça os benefícios"))
        save.assert_not_called()

    def test_manual_typography_without_timestamp_and_disabled_typography_are_respected(self):
        for typo in ({"title": {"family": "Minha fonte", "file": "manual.ttf"}}, {"enabled": False}):
            company = {"id": "client", "brand_kit": {"creative_config": {"design": {"typography": typo}}}}
            with patch.object(brand_fonts, "_own_arts") as arts:
                actual = brand_fonts.ensure(company)
            self.assertEqual(actual, typo if typo.get("title") else {})
            arts.assert_not_called()

    def test_identification_failure_keeps_a_readable_fallback(self):
        with patch.object(brand_fonts, "_own_arts", return_value=[b"reference"]), \
                patch.object(brand_fonts, "identify", side_effect=ValueError("offline")):
            self.assertEqual(brand_fonts.ensure({"id": "client"})["method"], "fallback")

    def test_footer_and_app_logos_preserve_content_for_feed_story_and_upscaled_art(self):
        with tempfile.TemporaryDirectory() as temp:
            light, dark = Path(temp) / "white.png", Path(temp) / "black.png"
            Image.new("RGBA", (180, 60), "white").save(light)
            Image.new("RGBA", (180, 60), "black").save(dark)
            for size in ((1080, 1350), (1080, 1920), (2160, 2700), (2160, 3840)):
                for bg, expected in (("white", (0, 0, 0)), ("black", (255, 255, 255))):
                    with self.subTest(size=size, bg=bg):
                        orig = Image.new("RGB", size, bg)
                        data = stamp_footer(png(orig), [str(light), str(dark)],
                                            "WhatsApp (11) 99999-9999 · exemplo.com.br · @cliente",
                                            {"primary": "#ED5E1F"}, brand_fonts.fallback_typography())
                        data = stamp_apps(data, [[str(light), str(dark)]] * 3)
                        out = Image.open(io.BytesIO(data)).convert("RGB")
                        w, h = size
                        self.assertEqual(out.size, size)
                        area = (0, round(h * 0.12), w, round(h * 0.84))
                        self.assertIsNone(ImageChops.difference(orig.crop(area), out.crop(area)).getbbox())
                        self.assertEqual(out.getpixel((round(w * 0.07), round(h * 0.04))), expected)
                        self.assertEqual(out.getpixel((round(w * 0.90), round(h * 0.92))), expected)

    def test_missing_optional_logos_and_contacts_do_not_break_render(self):
        data = png(Image.new("RGB", (1080, 1350), "white"))
        self.assertEqual(stamp_apps(data, []), data)
        out = stamp_footer(data, [], "", {}, {})
        self.assertEqual(Image.open(io.BytesIO(out)).size, (1080, 1350))


if __name__ == "__main__":
    unittest.main()
