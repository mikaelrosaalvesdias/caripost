"""Acabamento determinístico do Estúdio para marcas sem rodapé original e logos de apps."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .layered_composer import _font, _ink_on, _rgb, _wrap
from .template_composer import _load_logo, _logo_lum, _region_lum


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


def _pick_logo_variant(paths, lum, max_w, max_h):
    # Entre versões legíveis, prefere resolução real: uma favicon/miniatura não deve vencer o logo em alta.
    logos = [logo for path in paths or [] if (logo := _load_logo(path, max_w, max_h)) is not None]
    readable = [logo for logo in logos if abs(_logo_lum(logo) - lum) >= 60]
    logo = max(readable, key=lambda logo: logo.width * logo.height) if readable else max(
        logos, key=lambda logo: abs(_logo_lum(logo) - lum), default=None)
    if logo is not None:
        scale = min(max_w / logo.width, max_h / logo.height)
        if scale > 1:
            logo = logo.resize((max(1, round(logo.width * scale)), max(1, round(logo.height * scale))), Image.Resampling.LANCZOS)
    return logo


def stamp_footer(image: bytes, logos, contact: str, colors: dict, typo: dict) -> bytes:
    """Logo à direita e contatos em linhas legíveis, dentro dos 16% reservados no prompt."""
    from .brand_fonts import _path
    im = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = im.size
    margin = round(w * 0.055)
    top = round(h * 0.84)
    # A faixa é contínua com o fundo local; elimina contatos e assinaturas inventados pela IA.
    bg = im.crop((0, 0, max(1, w // 20), max(1, h // 40))).resize((1, 1)).getpixel((0, 0))
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


def compose_text(image: bytes, slide: dict, typo: dict, size=(2160, 2700)) -> bytes:
    """Foto sem letras + blocos tipográficos medidos; nenhuma segunda geração/limpeza por IA."""
    from .brand_fonts import _path
    im = ImageOps.fit(Image.open(io.BytesIO(image)).convert("RGB"), size, method=Image.Resampling.LANCZOS)
    w, h = im.size
    shade = Image.new("RGBA", (w, 1))
    shade.putdata([(8, 15, 25, round(255 * max(0, min(1, (0.9 - x / w) / 0.23)))) for x in range(w)])
    im = Image.alpha_composite(im.convert("RGBA"), shade.resize((w, h))).convert("RGB")
    d = ImageDraw.Draw(im)
    x, y, max_w = round(w * 0.055), round(h * 0.145), round(w * 0.61)
    roles = [("title", slide.get("title") or "", 0.075, 0.24, 1.18),
             ("body", slide.get("body") or slide.get("subtitle") or "", 0.031, 0.17, 1.4),
             ("cta", slide.get("cta") or "", 0.031, 0.10, 1.35)]
    for role, text, start, height, spacing in roles:
        if not text.strip():
            continue
        spec = (typo or {}).get("title" if role == "title" else "body") or {}
        if role == "title" and spec.get("caps"):
            text = text.upper()
        font_size = round(w * start)
        while True:
            try:
                f = ImageFont.truetype(_path(spec["file"]), font_size) if spec.get("file") else _font("semibold" if role == "title" else "regular", font_size)
            except (OSError, ValueError):
                f = _font("semibold" if role == "title" else "regular", font_size)
            lines = _wrap(d, text, f, max_w - (round(w * 0.04) if role == "cta" else 0))
            # Inclui ascendentes/descendentes reais: tamanho nominal sozinho pode sobrepor linhas.
            bbox = f.getbbox("Ágj")
            line_h = max(round(font_size * spacing), bbox[3] - bbox[1] + round(font_size * 0.2))
            if (len(lines) * line_h <= h * height and all(d.textlength(t, font=f) <= max_w for t in lines)) or font_size <= 14:
                break
            font_size -= 2
        if role == "cta":
            pad = round(w * 0.02)
            box_w = min(max_w, round(max(d.textlength(t, font=f) for t in lines)) + 2 * pad)
            d.rounded_rectangle((x, y, x + box_w, y + len(lines) * line_h + 2 * pad), radius=pad, fill=(250, 250, 250))
            tx, ty, ink = x + pad, y + pad, (15, 20, 30)
        else:
            tx, ty, ink = x, y, (255, 255, 255)
        for line in lines:
            d.text((tx, ty), line, font=f, fill=ink, anchor="lt")
            ty += line_h
        y = ty + round(w * 0.035)
    return _png(im)


def write_preview(image: bytes, path: str) -> None:
    im = Image.open(io.BytesIO(image)).convert("RGB")
    im.thumbnail((720, 1280), Image.Resampling.LANCZOS)
    im.save(path, "WEBP", quality=82, method=4)
