"""Acabamento determinístico do Estúdio para marcas sem rodapé original e logos de apps."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .layered_composer import _font, _ink_on, _rgb, _wrap
from .template_composer import _logo_lum, _pick_logo_variant, _region_lum


def _png(im):
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def _paste_logo(im, logo, x, y):
    lum = _region_lum(im, (x, y, x + logo.width, y + logo.height))
    if abs(_logo_lum(logo) - lum) < 55:
        pad = max(4, round(im.width * 0.008))
        fill = (250, 250, 250) if _logo_lum(logo) < 140 else (25, 25, 28)
        ImageDraw.Draw(im).rounded_rectangle(
            (x - pad, y - pad, x + logo.width + pad, y + logo.height + pad), radius=pad, fill=fill)
    im.paste(logo, (x, y), logo)


def stamp_footer(image: bytes, logos, contact: str, colors: dict, typo: dict) -> bytes:
    """Logo à direita e contatos em linhas legíveis, dentro dos 16% reservados no prompt."""
    from .brand_fonts import _path
    im = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = im.size
    margin = round(w * 0.055)
    top = round(h * 0.84)
    # A faixa é contínua com o fundo local; elimina contatos e assinaturas inventados pela IA.
    bg = im.crop((0, top, w, h)).resize((1, 1)).getpixel((0, 0))
    ink = _ink_on(bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, top, w, h), fill=bg)
    accent = _rgb(colors.get("primary") or colors.get("accent"), ink)
    d.line((margin, top + margin // 3, w - margin, top + margin // 3), fill=accent, width=max(1, w // 540))
    logo = _pick_logo_variant(logos or [], _region_lum(im, (0, top, w, h)),
                              round(w * 0.26), round(h * 0.085))
    text_w = w - 2 * margin - (round(w * 0.30) if logo else 0)
    size = max(16, round(w * 0.024))
    path = ((typo or {}).get("body") or {}).get("file")
    def font(sz):
        try:
            return ImageFont.truetype(_path(path), sz) if path else _font("regular", sz)
        except (OSError, ValueError):
            return _font("regular", sz)
    parts = [part.strip() for part in contact.split(" · ") if part.strip()]
    while True:
        f = font(size)
        lines = [line for part in parts for line in _wrap(d, part, f, text_w)]
        line_h = round(size * 1.45)
        if (len(lines) * line_h <= h - top - margin and
                all(d.textlength(line, font=f) <= text_w for line in lines)) or size <= 12:
            break
        size -= 1
    y = top + (h - top - len(lines) * line_h) // 2 + margin // 6
    for line in lines:
        d.text((margin, y), line, font=f, fill=ink)
        y += line_h
    if logo:
        x, y = w - margin - logo.width, top + (h - top - logo.height) // 2
        _paste_logo(im, logo, x, y)
    return _png(im)


def stamp_apps(image: bytes, groups) -> bytes:
    """Os arquivos oficiais entram na faixa superior reservada, sem depender da cópia da IA."""
    groups = [g for g in (groups or []) if g][:3]
    if not groups:
        return image
    im = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = im.size
    margin = round(w * 0.055)
    slot = (w - 2 * margin) // len(groups)
    for i, variants in enumerate(groups):
        x = margin + i * slot
        y = round(h * 0.025)
        lum = _region_lum(im, (x, y, x + slot, round(h * 0.11)))
        logo = _pick_logo_variant(variants, lum, min(round(w * 0.23), slot - margin // 2), round(h * 0.065))
        if logo:
            _paste_logo(im, logo, x, y)
    return _png(im)
