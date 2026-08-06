import io
import unittest

from PIL import Image

from app.services.template_composer import _brand_color, compose_carousel_slide
from app.services.template_video import _brand_colors
from app.services.video_composer import _grade_filter


class BrandColorPriorityTests(unittest.TestCase):
    def test_primary_wins_over_accent_in_shared_composer_contract(self):
        colors = {"primary": "#123456", "accent": "#ABCDEF"}
        self.assertEqual(_brand_color(colors), (18, 52, 86))

        rendered = compose_carousel_slide(
            {"type": "cta", "title": "Teste"}, 1, 1, colors,
        )
        self.assertEqual(Image.open(io.BytesIO(rendered)).getpixel((0, 0)), (18, 52, 86))

    def test_video_grade_uses_primary_and_keeps_accent_as_fallback(self):
        both = _grade_filter({"primary": "#FF0000", "accent": "#00FF00"})
        self.assertEqual(both, _grade_filter({"primary": "#FF0000"}))
        self.assertNotEqual(both, _grade_filter({"accent": "#00FF00"}))

    def test_template_video_does_not_inject_default_colors_into_primary_only_palette(self):
        primary, accent, secondary = _brand_colors({
            "brand_kit": {"colors": {"primary": "#123456"}},
        })
        self.assertEqual(primary, (18, 52, 86))
        self.assertEqual(accent, primary)
        self.assertEqual(secondary, primary)


if __name__ == "__main__":
    unittest.main()
