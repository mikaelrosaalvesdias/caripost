from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


UPLOAD_DIR = os.environ.get(
    "ADULT_META_MEDIA_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"),
)
UPLOAD_URL_PREFIX = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")


@dataclass
class TemplateVideoResult:
    job_id: str
    artifact_type: str
    url: str
    preview_url: str
    manifest_url: str
    frames: List[str]
    mp4_url: Optional[str]
    fallback_reason: Optional[str]
    width: int
    height: int
    duration_sec: float


TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "brand_pulse_15s",
        "name": "Brand Pulse",
        "duration_sec": 15,
        "formats": ["story", "feed"],
        "objective": "institucional",
        "description": "Hero de marca: headline forte, suporte curto, CTA e identidade fixa.",
        "fields": ["eyebrow", "title", "subtitle", "cta", "image_url"],
    },
    {
        "id": "offer_snap_10s",
        "name": "Oferta Snap",
        "duration_sec": 10,
        "formats": ["story", "feed"],
        "objective": "venda",
        "description": "Oferta direta com faixa de destaque, valor/beneficio grande e CTA claro.",
        "fields": ["eyebrow", "title", "subtitle", "offer", "cta"],
    },
    {
        "id": "proof_wave_12s",
        "name": "Prova Social",
        "duration_sec": 12,
        "formats": ["story", "feed"],
        "objective": "confiança",
        "description": "Depoimento, estatistica ou autoridade em formato premium.",
        "fields": ["eyebrow", "title", "quote", "stat", "subtitle", "cta"],
    },
    {
        "id": "meme_vs_10s",
        "name": "Meme VS 10s",
        "duration_sec": 10,
        "formats": ["story", "feed"],
        "objective": "criativo",
        "description": "Comparacao rapida para newsjacking: lado A, lado B e punchline final.",
        "fields": ["left_label", "left_text", "right_label", "right_text", "punchline", "cta"],
    },
    {
        "id": "cinematic_story_15s",
        "name": "Story Cinematico",
        "duration_sec": 15,
        "formats": ["story", "feed"],
        "objective": "storytelling",
        "description": "Sequencia em cenas para roteiro curto, com ritmo de teaser.",
        "fields": ["eyebrow", "title", "scenes", "subtitle", "cta", "image_url"],
    },
    {
        "id": "benefit_stack_12s",
        "name": "Beneficios em Pilha",
        "duration_sec": 12,
        "formats": ["story", "feed"],
        "objective": "produto",
        "description": "Lista visual de beneficios com movimento e hierarquia segura.",
        "fields": ["eyebrow", "title", "benefits", "subtitle", "cta"],
    },
]


def list_template_video_templates() -> List[Dict[str, Any]]:
    return TEMPLATES


def _template_by_id(template_id: str) -> Dict[str, Any]:
    wanted = (template_id or "").strip()
    for tmpl in TEMPLATES:
        if tmpl["id"] == wanted:
            return tmpl
    return TEMPLATES[0]


def _as_list(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        parts = [p.strip(" -\t") for p in value.replace(";", "\n").split("\n")]
        return [p for p in parts if p]
    return fallback or []


def _text(value: Any, fallback: str = "") -> str:
    return str(value or fallback or "").strip()


def _brand_colors(company: Dict[str, Any]) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    brand = company.get("brand_kit") or {}
    colors = brand.get("colors") or {}
    primary_raw = colors.get("primary") or colors.get("primaryColor")
    accent_raw = colors.get("accent") or colors.get("accentColor")
    secondary_raw = colors.get("secondary") or colors.get("secondaryColor")
    primary = _hex_to_rgb(primary_raw or "#111827", (20, 24, 32))
    # Uma paleta válida pode ter somente primary. Nesse caso toda a identidade parte dela;
    # laranja/ciano são defaults apenas para uma empresa ainda sem paleta cadastrada.
    accent = (_hex_to_rgb(accent_raw, primary) if accent_raw
              else primary if colors else (255, 122, 24))
    secondary = (_hex_to_rgb(secondary_raw, accent) if secondary_raw
                 else accent if colors else (32, 213, 255))
    return primary, accent, secondary


def _hex_to_rgb(value: str, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    try:
        if len(v) == 6:
            return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except Exception:
        pass
    return fallback


def _mix(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> List[str]:
    words = (text or "").strip().split()
    if not words:
        return []
    lines: List[str] = []
    cur = ""
    for word in words:
        nxt = (cur + " " + word).strip()
        if draw.textbbox((0, 0), nxt, font=font)[2] <= max_width or not cur:
            cur = nxt
            continue
        lines.append(cur)
        cur = word
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and len(words) > len(" ".join(lines).split()):
        lines[-1] = lines[-1].rstrip(".,;:") + "..."
    return lines[:max_lines]


def _lines_height(draw: ImageDraw.ImageDraw, lines: List[str], font: ImageFont.ImageFont, line_gap: int) -> int:
    if not lines:
        return 0
    h = 0
    for i, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=font)
        h += max(1, box[3] - box[1])
        if i < len(lines) - 1:
            h += line_gap
    return h


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    bold: bool,
    line_gap: int,
) -> Tuple[ImageFont.ImageFont, List[str]]:
    text = (text or "").strip()
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold)
        lines = _fit_lines(draw, text, font, max_width, max_lines)
        widest = max((draw.textbbox((0, 0), line, font=font)[2] for line in lines), default=0)
        if widest <= max_width and _lines_height(draw, lines, font, line_gap) <= max_height:
            return font, lines
    font = _font(min_size, bold)
    return font, _fit_lines(draw, text, font, max_width, max_lines)


def _draw_text_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Tuple[int, int, int, int],
    fill: Tuple[int, int, int],
    max_size: int,
    min_size: int,
    max_lines: int,
    bold: bool = True,
    line_gap: int = 8,
    align: str = "left",
    valign: str = "top",
) -> int:
    x1, y1, x2, y2 = box
    font, lines = _fit_font(draw, text, x2 - x1, y2 - y1, max_lines, max_size, min_size, bold, line_gap)
    total_h = _lines_height(draw, lines, font, line_gap)
    y = y1 if valign == "top" else y1 + max(0, (y2 - y1 - total_h) // 2)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = x1
        if align == "center":
            x = x1 + max(0, (x2 - x1 - line_w) // 2)
        elif align == "right":
            x = x2 - line_w
        draw.text((x, y), line, font=font, fill=fill)
        y += max(1, bbox[3] - bbox[1]) + line_gap
    return y


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: Tuple[int, int],
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    max_width: int,
    max_lines: int,
    line_gap: int = 10,
) -> int:
    y = xy[1]
    for line in _fit_lines(draw, text, font, max_width, max_lines):
        draw.text((xy[0], y), line, font=font, fill=fill)
        box = draw.textbbox((xy[0], y), line, font=font)
        y = box[3] + line_gap
    return y


def _center_text(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = box[0] + ((box[2] - box[0]) - (bbox[2] - bbox[0])) // 2
    y = box[1] + ((box[3] - box[1]) - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _draw_logo_mark(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    company: Dict[str, Any],
    logo_path: Optional[str],
    xy: Tuple[int, int],
    max_w: int,
    max_h: int,
    accent: Tuple[int, int, int],
) -> None:
    pad_x = max(14, int(max_w * 0.08))
    pad_y = max(9, int(max_h * 0.12))
    plate_w = max(86, max_w + pad_x * 2)
    plate_h = max(54, max_h + pad_y * 2)
    x, y = xy
    draw.rounded_rectangle((x, y, x + plate_w, y + plate_h), radius=18, fill=(255, 255, 255, 28), outline=(255, 255, 255, 50))
    logo = _load_logo(logo_path, max_w, max_h)
    if logo:
        lx = x + (plate_w - logo.width) // 2
        ly = y + (plate_h - logo.height) // 2
        canvas.alpha_composite(logo, (lx, ly))
        return
    size = min(max_w, max_h, 48)
    bx = x + (plate_w - size) // 2
    by = y + (plate_h - size) // 2
    draw.rounded_rectangle((bx, by, bx + size, by + size), radius=max(10, size // 4), fill=accent)
    draw.text((bx + size * 0.33, by + size * 0.16), (company.get("name") or "C")[:1].upper(), font=_font(int(size * 0.50), True), fill=(255, 255, 255))


def _draw_brand_footer(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    company: Dict[str, Any],
    logo_path: Optional[str],
    margin: int,
    height: int,
    accent: Tuple[int, int, int],
) -> None:
    footer_h = 52
    y = height - margin - footer_h + 4
    logo = _load_logo(logo_path, 150, footer_h)
    if logo:
        canvas.alpha_composite(logo, (margin, y + max(0, (footer_h - logo.height) // 2)))
        return
    size = 38
    draw.rounded_rectangle((margin, y + 6, margin + size, y + 6 + size), radius=10, fill=accent)
    draw.text((margin + 12, y + 10), (company.get("name") or "C")[:1].upper(), font=_font(24, True), fill=(255, 255, 255))
    draw.text((margin + size + 10, y + 10), (company.get("name") or "Caripost").upper()[:18], font=_font(22, True), fill=(255, 255, 255))


def _draw_cta_bar(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    margin: int,
    cta: str,
    accent: Tuple[int, int, int],
    dark_text: Tuple[int, int, int] = (18, 22, 28),
) -> None:
    cta = (cta or "Saiba mais").strip()[:48]
    cta_font = _font(max(20, int(width * 0.026)), True)
    bbox = draw.textbbox((0, 0), cta, font=cta_font)
    pill_w = min(width - 2 * margin, max(170, bbox[2] - bbox[0] + 54))
    pill_h = max(46, int(height * 0.036))
    x = margin
    y = height - margin - 132
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h), radius=pill_h // 2, fill=accent)
    _center_text(draw, (x + 18, y, x + pill_w - 30, y + pill_h), cta, cta_font, (255, 255, 255))
    tri_x = x + pill_w - 26
    tri_y = y + pill_h // 2
    draw.polygon([(tri_x - 4, tri_y - 8), (tri_x - 4, tri_y + 8), (tri_x + 8, tri_y)], fill=(255, 255, 255))


def _draw_progress(draw: ImageDraw.ImageDraw, width: int, height: int, margin: int, progress: float, accent: Tuple[int, int, int]) -> None:
    y = max(30, int(height * 0.030))
    gap = 8
    segments = 5
    seg_w = int((width - 2 * margin - gap * (segments - 1)) / segments)
    filled = max(0, min(1, progress)) * segments
    for i in range(segments):
        x = margin + i * (seg_w + gap)
        draw.rounded_rectangle((x, y, x + seg_w, y + 6), radius=3, fill=(255, 255, 255, 70))
        if filled > i:
            w = int(seg_w * min(1, filled - i))
            draw.rounded_rectangle((x, y, x + w, y + 6), radius=3, fill=accent)


def _frame_phase(frame_idx: int, frame_count: int) -> float:
    return frame_idx / max(1, frame_count - 1)


def _load_logo(path: Optional[str], max_w: int, max_h: int) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        logo = Image.open(path).convert("RGBA")
        logo.thumbnail((max_w, max_h), Image.LANCZOS)
        return logo
    except Exception:
        return None


def _local_upload_path(url: str) -> Optional[str]:
    if not url or not url.startswith(UPLOAD_URL_PREFIX):
        return None
    rel = url[len(UPLOAD_URL_PREFIX):].lstrip("/")
    path = os.path.abspath(os.path.join(UPLOAD_DIR, rel))
    root = os.path.abspath(UPLOAD_DIR)
    if not path.startswith(root + os.sep) and path != root:
        return None
    return path if os.path.exists(path) else None


def _background(width: int, height: int, primary: Tuple[int, int, int], accent: Tuple[int, int, int], frame_idx: int, frame_count: int) -> Image.Image:
    gw, gh = 96, 144
    img = Image.new("RGB", (gw, gh), (12, 13, 18))
    px = img.load()
    denom = max(1, gw + gh)
    for y in range(gh):
        for x in range(gw):
            t = (x + y) / denom
            pulse = frame_idx / max(1, frame_count - 1)
            r = int(10 + primary[0] * 0.11 * (1 - t) + accent[0] * 0.09 * t + 12 * pulse)
            g = int(12 + primary[1] * 0.10 * (1 - t) + accent[1] * 0.08 * t)
            b = int(18 + primary[2] * 0.10 * (1 - t) + accent[2] * 0.08 * t)
            px[x, y] = (min(255, r), min(255, g), min(255, b))
    img = img.resize((width, height), Image.BICUBIC)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    shift = int((frame_idx / max(1, frame_count - 1)) * width * 0.16)
    d.ellipse((width - int(width * 0.55) + shift, -int(height * 0.12), width + int(width * 0.15) + shift, int(height * 0.36)), fill=(*accent, 42))
    d.rectangle((0, int(height * 0.70), width, height), fill=(0, 0, 0, 88))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _paste_media(canvas: Image.Image, image_url: str, area: Tuple[int, int, int, int]) -> None:
    path = _local_upload_path(image_url)
    if not path:
        return
    try:
        src = Image.open(path).convert("RGBA")
        aw, ah = area[2] - area[0], area[3] - area[1]
        src_ratio = src.width / max(1, src.height)
        dst_ratio = aw / max(1, ah)
        if src_ratio > dst_ratio:
            nh = ah
            nw = int(nh * src_ratio)
        else:
            nw = aw
            nh = int(nw / src_ratio)
        src = src.resize((nw, nh), Image.LANCZOS)
        left = max(0, (nw - aw) // 2)
        top = max(0, (nh - ah) // 2)
        src = src.crop((left, top, left + aw, top + ah))
        mask = Image.new("L", (aw, ah), 210)
        canvas.alpha_composite(src, (area[0], area[1]))
        shade = Image.new("RGBA", (aw, ah), (0, 0, 0, 90))
        canvas.alpha_composite(shade, (area[0], area[1]))
    except Exception:
        return


def _draw_frame(
    payload: Dict[str, Any],
    company: Dict[str, Any],
    logo_path: Optional[str],
    width: int,
    height: int,
    frame_idx: int,
    frame_count: int,
) -> Image.Image:
    template_id = _template_by_id(payload.get("template_id") or payload.get("template") or "")["id"]
    primary, accent, secondary = _brand_colors(company)
    canvas = _background(width, height, primary, accent, frame_idx, frame_count)
    draw = ImageDraw.Draw(canvas)
    progress = _frame_phase(frame_idx, frame_count)
    image_url = payload.get("image_url") or payload.get("background_url") or ""
    if image_url and template_id in ("brand_pulse_15s", "cinematic_story_15s"):
        _paste_media(canvas, image_url, (int(width * 0.48), int(height * 0.12), width - 48, int(height * 0.68)))

    margin = int(width * 0.07)

    company_name = (company.get("name") or "Caripost").strip()
    eyebrow = (payload.get("eyebrow") or company_name).strip()[:48]
    title = (payload.get("title") or payload.get("headline") or "Video por template").strip()
    subtitle = (payload.get("subtitle") or payload.get("body") or "").strip()
    cta = (payload.get("cta") or "Fale com a gente").strip()

    title_font = _font(max(38, int(width * 0.056)), True)
    mega_font = _font(max(44, int(width * 0.066)), True)
    subtitle_font = _font(max(20, int(width * 0.026)), False)
    small_font = _font(max(15, int(width * 0.018)), True)

    if template_id == "offer_snap_10s":
        offer = _text(payload.get("offer") or payload.get("price") or payload.get("badge"), "Oferta especial")
        band_y = int(height * (0.20 + 0.025 * math.sin(progress * math.pi)))
        draw.text((margin, band_y), eyebrow.upper(), font=small_font, fill=accent)
        y = int(height * 0.31)
        y = _draw_text_box(draw, title, (margin, y, width - margin, y + int(height * 0.20)), (255, 255, 255), 68, 38, 3, True, 4)
        offer_y = y + 24
        draw.rounded_rectangle((margin, offer_y, width - margin * 2, offer_y + int(height * 0.085)), radius=22, fill=(0, 0, 0, 150), outline=(*accent, 170))
        _draw_text_box(draw, offer, (margin + 24, offer_y + 10, width - margin * 2 - 24, offer_y + int(height * 0.085) - 8), accent, 42, 24, 1, True, 0, "left", "center")
        if subtitle:
            _draw_text_box(draw, subtitle, (margin, offer_y + int(height * 0.11), width - margin * 2, offer_y + int(height * 0.18)), (232, 238, 244), 28, 20, 2, False, 4)
        _draw_cta_bar(draw, width, height, margin, cta, accent)
    elif template_id == "proof_wave_12s":
        quote = _text(payload.get("quote"), subtitle or "Resultado real, marca presente e mensagem clara.")
        stat = _text(payload.get("stat") or payload.get("metric"), "prova real")
        y = int(height * 0.24)
        draw.text((margin, y), eyebrow.upper(), font=small_font, fill=accent)
        y = _draw_text_box(draw, title, (margin, y + int(height * 0.045), width - margin * 2, y + int(height * 0.18)), (255, 255, 255), 58, 34, 2, True, 5)
        quote_y = y + int(height * 0.055)
        draw.rounded_rectangle((margin, quote_y, width - margin * 2, quote_y + int(height * 0.20)), radius=24, fill=(0, 0, 0, 150), outline=(255, 255, 255, 55))
        _draw_text_box(draw, "“" + quote[:180] + "”", (margin + 28, quote_y + 24, width - margin * 2 - 28, quote_y + int(height * 0.20) - 20), (255, 255, 255), 34, 22, 4, True, 6)
        stat_y = quote_y + int(height * 0.235)
        draw.rounded_rectangle((margin, stat_y, margin + int(width * 0.52), stat_y + int(height * 0.055)), radius=18, fill=(*accent, 255))
        _draw_text_box(draw, stat.upper(), (margin + 18, stat_y, margin + int(width * 0.52) - 18, stat_y + int(height * 0.055)), (255, 255, 255), 26, 16, 1, True, 0, "center", "center")
        _draw_cta_bar(draw, width, height, margin, cta, accent)
    elif template_id == "meme_vs_10s":
        left_label = _text(payload.get("left_label"), "ANTES")
        right_label = _text(payload.get("right_label"), "DEPOIS")
        left_text = _text(payload.get("left_text"), "travando")
        right_text = _text(payload.get("right_text"), "fluindo")
        punchline = _text(payload.get("punchline"), title)
        box_top = int(height * 0.22)
        box_h = int(height * 0.28)
        gap = 22
        col_w = (width - 2 * margin - gap) // 2
        left = (margin, box_top, margin + col_w, box_top + box_h)
        right = (margin + col_w + gap, box_top, width - margin, box_top + box_h)
        draw.rounded_rectangle(left, radius=28, fill=(255, 255, 255, 226))
        draw.rounded_rectangle(right, radius=28, fill=(*accent, 242))
        _center_text(draw, (left[0], left[1] + 24, left[2], left[1] + 82), left_label.upper(), small_font, (20, 25, 31))
        _center_text(draw, (right[0], right[1] + 24, right[2], right[1] + 82), right_label.upper(), small_font, (255, 255, 255))
        _draw_text_box(draw, left_text, (left[0] + 22, left[1] + 96, left[2] - 22, left[3] - 24), (18, 22, 28), 34, 20, 4, True, 4)
        _draw_text_box(draw, right_text, (right[0] + 22, right[1] + 96, right[2] - 22, right[3] - 24), (255, 255, 255), 34, 20, 4, True, 4)
        y = box_top + box_h + int(height * 0.055)
        _draw_text_box(draw, punchline, (margin, y, width - margin, y + int(height * 0.20)), (255, 255, 255), 66, 36, 3, True, 4)
        _draw_cta_bar(draw, width, height, margin, cta, accent)
    elif template_id == "cinematic_story_15s":
        scenes = _as_list(payload.get("scenes"), [subtitle or title])
        scene_idx = min(len(scenes) - 1, int(progress * len(scenes))) if scenes else 0
        scene = scenes[scene_idx] if scenes else subtitle
        shade = Image.new("RGBA", (width, height), (0, 0, 0, 50 + int(55 * progress)))
        canvas = Image.alpha_composite(canvas, shade)
        draw = ImageDraw.Draw(canvas)
        y = int(height * 0.22)
        draw.text((margin, y), eyebrow.upper(), font=small_font, fill=accent)
        if progress < 0.35:
            _draw_text_box(draw, title, (margin, y + int(height * 0.06), width - margin, y + int(height * 0.26)), (255, 255, 255), 66, 36, 3, True, 4)
        else:
            draw.rounded_rectangle((margin, int(height * 0.50), width - margin * 2, int(height * 0.66)), radius=26, fill=(0, 0, 0, 150))
            _draw_text_box(draw, scene, (margin + 28, int(height * 0.515), width - margin * 2 - 28, int(height * 0.65)), (255, 255, 255), 38, 22, 3, True, 6)
        _draw_cta_bar(draw, width, height, margin, cta, accent)
    elif template_id == "benefit_stack_12s":
        benefits = _as_list(payload.get("benefits"), [subtitle, "mais controle", "mais resultado"])
        benefits = benefits[:4] or ["mais controle", "mais resultado"]
        y = int(height * 0.23)
        draw.text((margin, y), eyebrow.upper(), font=small_font, fill=accent)
        y = _draw_text_box(draw, title, (margin, y + int(height * 0.050), width - margin, y + int(height * 0.19)), (255, 255, 255), 58, 34, 2, True, 5)
        base_y = y + int(height * 0.055)
        for idx, item in enumerate(benefits):
            active = progress >= (idx / max(1, len(benefits)))
            xoff = 0 if active else int(width * 0.08)
            fill = (0, 0, 0, 145) if active else (0, 0, 0, 88)
            yy = base_y + idx * int(height * 0.078)
            row_h = int(height * 0.058)
            draw.rounded_rectangle((margin + xoff, yy, width - margin * 2, yy + row_h), radius=18, fill=fill, outline=(255, 255, 255, 45))
            draw.rounded_rectangle((margin + 16 + xoff, yy + 13, margin + 46 + xoff, yy + row_h - 13), radius=9, fill=accent)
            _center_text(draw, (margin + 16 + xoff, yy + 13, margin + 46 + xoff, yy + row_h - 13), str(idx + 1), small_font, (255, 255, 255))
            _draw_text_box(draw, item, (margin + 62 + xoff, yy + 6, width - margin * 2 - 16, yy + row_h - 4), (255, 255, 255), 28, 18, 1, True, 0, "left", "center")
        _draw_cta_bar(draw, width, height, margin, cta, accent)
    else:
        y = int(height * 0.24 + (1 - min(1, progress * 2)) * 24)
        draw.text((margin, y), eyebrow.upper(), font=small_font, fill=accent)
        y += int(height * 0.055)
        y = _draw_text_box(draw, title, (margin, y, width - margin * 2, y + int(height * 0.22)), (255, 255, 255), 58, 34, 3, True, 5)
        if subtitle:
            y += int(height * 0.025)
            _draw_text_box(draw, subtitle, (margin, y, width - margin * 2, y + int(height * 0.12)), (224, 229, 235), 28, 18, 3, False, 5)
        _draw_cta_bar(draw, width, height, margin, cta, accent)

    _draw_brand_footer(canvas, draw, company, logo_path, margin, height, accent)
    _draw_progress(draw, width, height, margin, progress, _mix(accent, secondary, 0.25))
    return canvas.convert("RGB")


def render_template_video(
    *,
    company: Dict[str, Any],
    payload: Dict[str, Any],
    logo_path: Optional[str] = None,
) -> TemplateVideoResult:
    fmt = (payload.get("format") or payload.get("formato") or "story").lower()
    width, height = (1080, 1350) if fmt in ("feed", "post", "4:5") else (1080, 1920)
    template = _template_by_id(payload.get("template_id") or payload.get("template") or "")
    try:
        duration_sec = float(payload.get("duration_sec") or payload.get("seconds") or template.get("duration_sec") or 10)
    except Exception:
        duration_sec = 10.0
    duration_sec = max(4.0, min(duration_sec, 30.0))
    fps = int(max(6, min(12, int(payload.get("fps") or 8))))
    frame_count = int(max(fps * 4, min(fps * 30, round(duration_sec * fps))))

    company_id = str(company.get("id") or payload.get("company_id") or "default")
    job_id = uuid.uuid4().hex
    rel_dir = os.path.join(company_id, "template_video", job_id)
    out_dir = os.path.join(UPLOAD_DIR, rel_dir)
    os.makedirs(out_dir, exist_ok=True)

    frame_urls: List[str] = []
    frames: List[Image.Image] = []
    for idx in range(frame_count):
        frame = _draw_frame(payload, company, logo_path, width, height, idx, frame_count)
        frames.append(frame)
        fn = f"frame_{idx:03d}.png"
        frame.save(os.path.join(out_dir, fn), "PNG", optimize=True)
        frame_urls.append(f"{UPLOAD_URL_PREFIX}/{rel_dir}/{fn}")

    preview_path = os.path.join(out_dir, "preview.png")
    frames[min(len(frames) - 1, max(0, len(frames) // 2))].save(preview_path, "PNG", optimize=True)
    gif_path = os.path.join(out_dir, "preview.gif")
    per_frame_ms = int(duration_sec * 1000 / max(1, frame_count))
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=per_frame_ms,
        loop=0,
        optimize=True,
    )

    mp4_url = None
    fallback_reason = None
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp4_path = os.path.join(out_dir, "video.mp4")
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(fps), "-i", os.path.join(out_dir, "frame_%03d.png"),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4_path,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=120)
            if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 1024:
                mp4_url = f"{UPLOAD_URL_PREFIX}/{rel_dir}/video.mp4"
        except Exception as exc:
            fallback_reason = f"ffmpeg falhou; entregue GIF/frames: {str(exc)[:120]}"
    else:
        fallback_reason = "ffmpeg nao encontrado no servidor; entregue GIF animado e frames PNG."

    artifact_url = mp4_url or f"{UPLOAD_URL_PREFIX}/{rel_dir}/preview.gif"
    artifact_type = "mp4" if mp4_url else "gif"
    manifest = {
        "job_id": job_id,
        "template": template["id"],
        "variant": payload.get("variant") or payload.get("motion") or "auto",
        "artifact_type": artifact_type,
        "url": artifact_url,
        "preview_url": f"{UPLOAD_URL_PREFIX}/{rel_dir}/preview.png",
        "mp4_url": mp4_url,
        "frames": frame_urls,
        "fallback_reason": fallback_reason,
        "width": width,
        "height": height,
        "duration_sec": duration_sec,
        "fps": fps,
        "frame_count": frame_count,
        "token_cost": 0,
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return TemplateVideoResult(
        job_id=job_id,
        artifact_type=artifact_type,
        url=artifact_url,
        preview_url=f"{UPLOAD_URL_PREFIX}/{rel_dir}/preview.png",
        manifest_url=f"{UPLOAD_URL_PREFIX}/{rel_dir}/manifest.json",
        frames=frame_urls,
        mp4_url=mp4_url,
        fallback_reason=fallback_reason,
        width=width,
        height=height,
        duration_sec=duration_sec,
    )
