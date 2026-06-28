"""
treatments.py — CRIATIVIDADE (mata o template). Vários tratamentos distintos; cada um
compõe RESPEITANDO o mapa de proteção (placement.top_n_rects / forbidden_mask).

Os ousados (texto ATRÁS do sujeito, contornando) só existem porque o detect deu a silhueta.
Registry extensível: adicione uma função + @treatment("nome").
"""
from __future__ import annotations

import os
import random
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from placement import ProtectionMap, top_n_rects, fallback_band, Box

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
PAD = 36

TREATMENTS: dict[str, Callable] = {}


def treatment(name: str):
    def deco(fn):
        TREATMENTS[name] = fn
        return fn
    return deco


# ---------- helpers de texto ---------- #
def _font(path: Optional[str], size: int):
    for p in ([path] if path else []) + _FONTS:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def _lh(font):
    bb = font.getbbox("Ájg")
    return int((bb[3] - bb[1]) * 1.16)


def _fit(draw, text, zone, font_path, max_size, min_size=18):
    _, _, bw, bh = zone
    lo, hi, best = min_size, max_size, (min_size, [text])
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _font(font_path, mid)
        lines = _wrap(draw, text, f, bw)
        if _lh(f) * len(lines) <= bh and max((draw.textlength(l, font=f) for l in lines), default=0) <= bw:
            best = (mid, lines); lo = mid + 1
        else:
            hi = mid - 1
    return best


def _hex(c, default=(237, 94, 31)):
    try:
        c = c.lstrip("#"); return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except Exception:
        return default


def _zones(pmap: ProtectionMap, margin: int, n=3) -> list[Box]:
    forb = pmap.forbidden_mask()
    zs = top_n_rects(forb, margin, n)
    return zs or [fallback_band(pmap.w, pmap.h, margin, forb)]


def _draw_block(canvas, zone, text, color, font_path, max_size, align="left"):
    d = ImageDraw.Draw(canvas)
    size, lines = _fit(d, text, (zone[0], zone[1], zone[2] - 2 * PAD, zone[3] - 2 * PAD), font_path, max_size)
    f = _font(font_path, size); lh = _lh(f)
    x, y, bw, bh = zone
    ty = y + (bh - lh * len(lines)) // 2
    for ln in lines:
        lw = d.textlength(ln, font=f)
        tx = x + PAD if align == "left" else x + (bw - lw) // 2
        d.text((tx, ty), ln, font=f, fill=color); ty += lh
    return size


def _accent_bar(canvas, zone, acc):
    x, y, _, bh = zone
    ImageDraw.Draw(canvas, "RGBA").rectangle([x, y + 14, x + 9, y + bh - 14], fill=acc)


# ---------- tratamentos ---------- #
@treatment("column_glass")
def column_glass(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA"); acc = _hex(cfg.get("accent"))
    zs = _zones(pmap, cfg.get("margin", 48), len(blocks))
    for blk, z in zip(blocks, zs):
        reg = base.crop((z[0], z[1], z[0] + z[2], z[1] + z[3])).filter(ImageFilter.GaussianBlur(20))
        reg = Image.alpha_composite(reg, Image.new("RGBA", reg.size, (18, 14, 12, 180)))
        m = Image.new("L", reg.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, *reg.size], 30, fill=255)
        base.paste(reg, (z[0], z[1]), m)
        _draw_block(base, z, blk["text"], blk.get("color", "#FFFFFF"), blk.get("font_path"), blk.get("max_font_size", 90))
    return base.convert("RGB")


@treatment("column_solid")
def column_solid(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA"); acc = _hex(cfg.get("accent"))
    zs = _zones(pmap, cfg.get("margin", 48), len(blocks))
    for blk, z in zip(blocks, zs):
        ImageDraw.Draw(base, "RGBA").rounded_rectangle([z[0], z[1], z[0] + z[2], z[1] + z[3]], 14, fill=(15, 12, 17, 236))
        _accent_bar(base, z, acc)
        _draw_block(base, z, blk["text"], blk.get("color", "#FFFFFF"), blk.get("font_path"), blk.get("max_font_size", 90))
    return base.convert("RGB")


@treatment("scrim_float")
def scrim_float(img, blocks, pmap, rng, cfg):
    base = img.convert("RGBA")
    zs = _zones(pmap, cfg.get("margin", 48), len(blocks))
    for blk, z in zip(blocks, zs):
        pad = 44
        gw, gh = z[2] + 2 * pad, z[3] + 2 * pad
        g = Image.new("L", (gw, gh), 0); ImageDraw.Draw(g).ellipse([0, 0, gw, gh], fill=175)
        g = g.filter(ImageFilter.GaussianBlur(46))
        dark = Image.new("RGBA", (gw, gh), (6, 5, 9, 255)); dark.putalpha(g)
        base.alpha_composite(dark, (max(0, z[0] - pad), max(0, z[1] - pad)))
        _draw_block(base, z, blk["text"], blk.get("color", "#FFFFFF"), blk.get("font_path"), blk.get("max_font_size", 96))
    return base.convert("RGB")


@treatment("big_type_bleed")
def big_type_bleed(img, blocks, pmap, rng, cfg):
    """Tipografia GIGANTE no maior espaço livre, podendo sangrar a borda. Sem caixa."""
    base = img.convert("RGBA"); d = ImageDraw.Draw(base)
    zs = _zones(pmap, cfg.get("margin", 36), len(blocks))
    title = blocks[0]; z = zs[0]
    size, lines = _fit(d, title["text"], (z[0], z[1], z[2], z[3]), title.get("font_path"), title.get("max_font_size", 150))
    size = int(size * 1.18)  # deixa sangrar um pouco
    f = _font(title.get("font_path"), size); lh = _lh(f)
    ty = z[1] + (z[3] - lh * len(lines)) // 2
    for ln in lines:
        d.text((z[0] + 6, ty + 4), ln, font=f, fill=(0, 0, 0, 120))   # sombra
        d.text((z[0], ty), ln, font=f, fill=title.get("color", "#FFFFFF")); ty += lh
    for blk, z2 in zip(blocks[1:], zs[1:]):
        _draw_block(base, z2, blk["text"], blk.get("color", "#FFFFFF"), blk.get("font_path"), blk.get("max_font_size", 44))
    return base.convert("RGB")


@treatment("behind_subject")
def behind_subject(img, blocks, pmap, rng, cfg):
    """Texto GIGANTE atrás do sujeito (recorte pela silhueta). Só roda se houver silhueta;
    senão cai pro big_type_bleed. É o tratamento 'wow' — o sujeito ocupa a frente do texto."""
    if pmap.silhouette is None or not pmap.silhouette.any():
        return big_type_bleed(img, blocks, pmap, rng, cfg)
    base = img.convert("RGBA"); W, H = base.size
    layer = base.copy(); d = ImageDraw.Draw(layer)
    title = blocks[0]
    size, lines = _fit(d, title["text"], (0, 0, int(W * 0.86), int(H * 0.5)), title.get("font_path"), title.get("max_font_size", 170))
    f = _font(title.get("font_path"), size); lh = _lh(f)
    ty = int(H * 0.18)
    for ln in lines:
        lw = d.textlength(ln, font=f)
        d.text(((W - lw) // 2, ty), ln, font=f, fill=title.get("color", "#FFFFFF")); ty += lh
    # re-cola o sujeito (da imagem ORIGINAL) por cima → texto fica ATRÁS dele
    sil = Image.fromarray((pmap.silhouette * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1))
    layer.paste(base, (0, 0), sil)
    base = layer
    # CTA/subtítulo num espaço livre (na frente, legível)
    for blk, z in zip(blocks[1:], _zones(pmap, cfg.get("margin", 48), len(blocks))[:len(blocks) - 1]):
        _draw_block(base, z, blk["text"], blk.get("color", "#FFFFFF"), blk.get("font_path"), blk.get("max_font_size", 44))
    return base.convert("RGB")


def list_treatments():
    return list(TREATMENTS.keys())


def pick_treatment(art_config, seed):
    if art_config and art_config.get("treatment") in TREATMENTS:
        return art_config["treatment"]
    rng = random.Random(seed)
    return rng.choice(list_treatments())
