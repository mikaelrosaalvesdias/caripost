"""Visual treatments for the protection-aware creative engine."""
from __future__ import annotations

import os
import random
from dataclasses import asdict
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .placement import Box, Placement, ProtectionMap, fallback_band, intersects_forbidden, top_n_rects

FONT_DIRS = [
    "/usr/share/fonts/truetype/brand",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
]
FONT_NAMES = ["Poppins-ExtraBold", "Poppins-Bold", "DejaVuSans-Bold", "LiberationSans-Bold"]
PAD = 34

TreatmentFn = Callable[[Image.Image, list[dict], ProtectionMap, random.Random, dict], tuple[Image.Image, list[Placement]]]
TREATMENTS: dict[str, TreatmentFn] = {}


def treatment(name: str):
    def deco(fn: TreatmentFn) -> TreatmentFn:
        TREATMENTS[name] = fn
        return fn
    return deco


def list_treatments() -> list[str]:
    return sorted(TREATMENTS)


def pick_treatment(art_config: Optional[dict], seed: Optional[int]) -> str:
    requested = (art_config or {}).get("treatment")
    if requested in TREATMENTS:
        return requested
    rng = random.Random(seed)
    return rng.choice(list_treatments())


def _hex(color: str | None, default=(237, 94, 31)):
    if not color:
        return default
    c = str(color).strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return default


def _font(path: Optional[str], size: int):
    candidates = [path] if path else []
    for name in FONT_NAMES:
        for root in FONT_DIRS:
            for ext in (".ttf", ".otf"):
                candidates.append(os.path.join(root, name + ext))
    for cand in candidates:
        if cand and os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _line_height(font) -> int:
    bb = font.getbbox("Ájg")
    return max(1, int((bb[3] - bb[1]) * 1.17))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit(draw: ImageDraw.ImageDraw, block: dict, zone: Box) -> tuple[int, list[str]]:
    _, _, bw, bh = zone
    lo = int(block.get("min_font_size") or 18)
    hi = int(block.get("max_font_size") or 92)
    best = (lo, [(block.get("text") or "")])
    inner_w = max(20, bw - 2 * PAD)
    inner_h = max(20, bh - 2 * PAD)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _font(block.get("font_path"), mid)
        lines = _wrap(draw, block.get("text") or "", font, inner_w)
        if _line_height(font) * len(lines) <= inner_h and max((draw.textlength(l, font=font) for l in lines), default=0) <= inner_w:
            best = (mid, lines)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _zones(pmap: ProtectionMap, cfg: dict, count: int, min_w=220, min_h=130) -> list[Box]:
    forbidden = pmap.forbidden_mask()
    zones = top_n_rects(forbidden, int(cfg.get("margin", 48)), count, min_w=min_w, min_h=min_h)
    if not zones and min_w > 170:
        zones = top_n_rects(forbidden, int(cfg.get("margin", 48)), count, min_w=170, min_h=min_h)
    if not zones:
        zones = [fallback_band(pmap.w, pmap.h, forbidden, int(cfg.get("margin", 48)))]
    return zones


def _safe_zone(pmap: ProtectionMap, cfg: dict, preferred: Box, min_w=220, min_h=130) -> Box:
    forbidden = pmap.forbidden_mask()
    if preferred[2] >= min_w and preferred[3] >= min_h and not intersects_forbidden(preferred, forbidden):
        return preferred
    zones = top_n_rects(forbidden, int(cfg.get("margin", 48)), 1, min_w=min_w, min_h=min_h)
    if not zones and min_w > 170:
        zones = top_n_rects(forbidden, int(cfg.get("margin", 48)), 1, min_w=170, min_h=min_h)
    return zones[0] if zones else fallback_band(pmap.w, pmap.h, forbidden, int(cfg.get("margin", 48)))


def _scrim(canvas: Image.Image, zone: Box, alpha=150, blur=36):
    x, y, w, h = zone
    halo = Image.new("L", (w + 80, h + 80), 0)
    ImageDraw.Draw(halo).rounded_rectangle([0, 0, w + 80, h + 80], 36, fill=alpha)
    halo = halo.filter(ImageFilter.GaussianBlur(blur))
    dark = Image.new("RGBA", halo.size, (0, 0, 0, 255))
    dark.putalpha(halo)
    canvas.alpha_composite(dark, (max(0, x - 40), max(0, y - 40)))


def _draw_block(canvas: Image.Image, block: dict, zone: Box, align="left") -> Placement:
    draw = ImageDraw.Draw(canvas)
    size, lines = _fit(draw, block, zone)
    font = _font(block.get("font_path"), size)
    lh = _line_height(font)
    x, y, w, h = zone
    ty = y + (h - lh * len(lines)) // 2
    for line in lines:
        tw = draw.textlength(line, font=font)
        tx = x + PAD if align == "left" else x + (w - tw) // 2
        draw.text((tx + 2, ty + 3), line, font=font, fill=(0, 0, 0, 130))
        draw.text((tx, ty), line, font=font, fill=block.get("color") or "#FFFFFF")
        ty += lh
    return Placement(block.get("role") or "titulo", zone, size, lines)


@treatment("column_glass")
def column_glass(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    placements = []
    for block, zone in zip(blocks, _zones(pmap, cfg, len(blocks))):
        crop = base.crop((zone[0], zone[1], zone[0] + zone[2], zone[1] + zone[3])).filter(ImageFilter.GaussianBlur(22))
        crop = Image.alpha_composite(crop, Image.new("RGBA", crop.size, (18, 14, 12, 182)))
        mask = Image.new("L", crop.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, crop.width, crop.height], 30, fill=255)
        base.paste(crop, (zone[0], zone[1]), mask)
        placements.append(_draw_block(base, block, zone))
    return base.convert("RGB"), placements


@treatment("column_solid")
def column_solid(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    acc = _hex(cfg.get("accent"))
    placements = []
    for block, zone in zip(blocks, _zones(pmap, cfg, len(blocks))):
        x, y, w, h = zone
        d = ImageDraw.Draw(base, "RGBA")
        d.rounded_rectangle([x, y, x + w, y + h], 12, fill=(12, 10, 15, 238))
        d.rectangle([x, y + 16, x + 10, y + h - 16], fill=acc + (255,))
        placements.append(_draw_block(base, block, zone))
    return base.convert("RGB"), placements


@treatment("scrim_float")
def scrim_float(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    placements = []
    for block, zone in zip(blocks, _zones(pmap, cfg, len(blocks))):
        _scrim(base, zone, 178, 46)
        placements.append(_draw_block(base, block, zone))
    return base.convert("RGB"), placements


@treatment("big_type_bleed")
def big_type_bleed(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    zones = _zones(pmap, cfg, len(blocks), min_w=220, min_h=160)
    placements = []
    first = dict(blocks[0])
    first["max_font_size"] = int(first.get("max_font_size") or 120) + 34
    placements.append(_draw_block(base, first, zones[0], align="left"))
    for block, zone in zip(blocks[1:], zones[1:]):
        _scrim(base, zone, 135, 34)
        placements.append(_draw_block(base, block, zone))
    return base.convert("RGB"), placements


@treatment("behind_subject")
def behind_subject(img, blocks, pmap, rng, cfg):
    if pmap.silhouette is None or not pmap.silhouette.any():
        return big_type_bleed(img, blocks, pmap, rng, cfg)
    base = img.convert("RGBA")
    layer = base.copy()
    zone = (int(pmap.w * 0.03), int(pmap.h * 0.13), int(pmap.w * 0.94), int(pmap.h * 0.42))
    title = dict(blocks[0])
    title["max_font_size"] = int(title.get("max_font_size") or 130) + 42
    placement = _draw_block(layer, title, zone, align="center")
    mask = Image.fromarray((pmap.silhouette * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1))
    layer.paste(base, (0, 0), mask)
    placements = [placement]
    for block, z in zip(blocks[1:], _zones(pmap, cfg, max(1, len(blocks) - 1))):
        _scrim(layer, z, 145, 34)
        placements.append(_draw_block(layer, block, z))
    return layer.convert("RGB"), placements


@treatment("contour_silhouette")
def contour_silhouette(img, blocks, pmap, rng, cfg):
    """Text hugs the largest free zone adjacent to protected silhouette/body."""
    base = img.convert("RGBA")
    forbidden = pmap.forbidden_mask()
    zones = top_n_rects(forbidden, int(cfg.get("margin", 36)), len(blocks), min_w=240, min_h=140)
    if not zones:
        zones = [fallback_band(pmap.w, pmap.h, forbidden, int(cfg.get("margin", 36)))]
    placements = []
    acc = _hex(cfg.get("accent"))
    for i, (block, zone) in enumerate(zip(blocks, zones)):
        x, y, w, h = zone
        d = ImageDraw.Draw(base, "RGBA")
        if i == 0:
            d.line([x, y + h, x + w, y + h], fill=acc + (255,), width=8)
        _scrim(base, zone, 120 if i == 0 else 155, 30)
        placements.append(_draw_block(base, block, zone))
    return base.convert("RGB"), placements


@treatment("cut_band")
def cut_band(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    forbidden = pmap.forbidden_mask()
    zone = fallback_band(pmap.w, pmap.h, forbidden, int(cfg.get("margin", 42)))
    zone = _safe_zone(pmap, cfg, zone, min_w=220, min_h=130)
    x, y, w, h = zone
    acc = _hex(cfg.get("accent"))
    d = ImageDraw.Draw(base, "RGBA")
    d.polygon([(x, y + 10), (x + w, y), (x + w - 24, y + h), (x + 18, y + h - 8)], fill=(8, 7, 10, 220))
    d.line([(x + 10, y + h - 10), (x + w - 30, y + h - 18)], fill=acc + (255,), width=5)
    placements = [_draw_block(base, blocks[0], zone)]
    for block, z in zip(blocks[1:], _zones(pmap, cfg, len(blocks) - 1)):
        placements.append(_draw_block(base, block, z))
    return base.convert("RGB"), placements


def placements_as_dict(placements: list[Placement]) -> list[dict]:
    return [asdict(p) for p in placements]
