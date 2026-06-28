"""Carimbo de identidade (modo híbrido): a IA gera o post branded variado (usando os posts
reais da Cariap como referência); aqui o código só GARANTE os elementos que não podem sair
errados — logo do app (com chip de contraste pra logo clara não sumir) + rodapé com logo
Cariap, site e contato. Layout do post é da IA, não fixo. PIL puro.
"""
from __future__ import annotations

import io
import os
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350
ORANGE = (237, 94, 31)
CHAR = (38, 37, 35)
WHITE = (255, 255, 255)
CREAM = (237, 234, 230)
FOOT_H = 142

# Pasta da fonte da MARCA (vai na imagem via COPY app). Solte aqui os .ttf/.otf da Cariap:
#   Cariap-Bold.ttf / Cariap-ExtraBold.ttf / Cariap-Regular.ttf (e variações) → usadas automaticamente.
_BRAND_FONTS = os.path.join(os.path.dirname(__file__), "fonts")
_FONT_DIRS = [
    _BRAND_FONTS,
    "/usr/share/fonts/truetype/brand/",   # Poppins (baixada no build)
    "/usr/share/fonts/truetype/dejavu/",
    "/usr/share/fonts/truetype/liberation/",
    "/usr/share/fonts/truetype/freefont/",
]


def _font(size: int, bold: bool = True, weight: str = "") -> ImageFont.FreeTypeFont:
    # Preferência: fonte da Cariap (se enviada) → Poppins/Montserrat → genérica.
    # weight: "black"/"extrabold"/"semibold" pedem um peso específico (títulos do carrossel).
    heavy = {"black": ["Cariap-Black", "Poppins-Black", "Montserrat-Black"],
             "extrabold": ["Cariap-ExtraBold", "Poppins-ExtraBold", "Montserrat-ExtraBold"],
             "semibold": ["Cariap-SemiBold", "Poppins-SemiBold", "Montserrat-SemiBold"]}.get(weight, [])
    pref = (heavy + ["Cariap-Bold", "Poppins-Bold", "Montserrat-Bold",
                     "DejaVuSans-Bold", "LiberationSans-Bold", "FreeSansBold"]
            if (bold or weight) else
            ["Cariap-Medium", "Cariap-Regular", "Poppins-Medium", "Poppins-Regular", "Montserrat-Regular",
             "DejaVuSans", "LiberationSans-Regular", "FreeSans"])
    for nm in pref:
        for dpath in _FONT_DIRS:
            for ext in (".ttf", ".otf"):
                p = os.path.join(dpath, nm + ext)
                if os.path.exists(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        pass
    return ImageFont.load_default()


def _hex(c, default):
    c = (c or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return default
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except Exception:
        return default


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    sr, dr = img.width / img.height, w / h
    if sr > dr:
        nh, nw = h, int(h * sr)
    else:
        nw, nh = w, int(w / sr)
    img = img.resize((nw, nh), Image.LANCZOS)
    # Corte horizontal: centralizado. Vertical: preserva o TOPO (headline) — corta mais do fundo,
    # que é coberto pelo rodapé. Evita cortar o título em modelos mais altos que 4:5 (ex.: gpt 2:3).
    x = (nw - w) // 2
    y = int((nh - h) * 0.30)
    return img.crop((x, y, x + w, y + h))


def _load_logo(path, max_w, max_h) -> Optional[Image.Image]:
    if not path or not os.path.exists(path) or path.lower().endswith(".svg"):
        return None
    try:
        lg = Image.open(path).convert("RGBA")
    except Exception:
        return None
    bbox = lg.getchannel("A").getbbox()   # corta a moldura transparente → logo no tamanho REAL (não sai minúscula)
    if bbox:
        lg = lg.crop(bbox)
    r = min(max_w / lg.width, max_h / lg.height)
    if r < 1:
        lg = lg.resize((max(1, int(lg.width * r)), max(1, int(lg.height * r))), Image.LANCZOS)
    return lg


def _logo_is_light(lg: Image.Image) -> bool:
    """Média de luminância dos pixels visíveis. True = logo clara (precisa de fundo escuro)."""
    small = lg.resize((40, 40))
    px = small.load()
    tot, lum = 0, 0.0
    for y in range(40):
        for x in range(40):
            r, g, b, a = px[x, y]
            if a > 40:
                tot += 1
                lum += 0.299 * r + 0.587 * g + 0.114 * b
    if not tot:
        return False
    return (lum / tot) > 150


def _paste_logo_chip(canvas, lg, x, y, pad=14):
    """Cola a logo sobre um chip arredondado com contraste (logo clara→chip escuro)."""
    cw, ch = lg.width + pad * 2, lg.height + pad * 2
    chip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    bg = CHAR + (235,) if _logo_is_light(lg) else WHITE + (235,)
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, cw, ch], 16, fill=bg)
    chip.paste(lg, (pad, pad), lg)
    canvas.paste(chip, (x, y), chip)


def _region_lum(img: Image.Image, box) -> float:
    crop = img.convert("RGB").crop(box).resize((24, 24))
    px = list(crop.getdata())
    return sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px) / max(1, len(px))


def _stamp_app_logo(canvas: Image.Image, lg: Image.Image, x: int = 44, y: int = 44):
    """Carimba a logo REAL do app. Se o contraste com o fundo for baixo, põe um HALO suave
    (glow da luminância oposta, borrado) atrás — destaca a logo SEM caixa visível. Senão, só a logo."""
    pad = 18
    box = (x, y, min(W, x + lg.width + pad * 2), min(H, y + lg.height + pad * 2))
    bg_lum = _region_lum(canvas, box)
    light = _logo_is_light(lg)
    low_contrast = (light and bg_lum > 150) or ((not light) and bg_lum < 110)
    px, py = x + pad, y + pad
    if low_contrast:
        glow = (0, 0, 0, 255) if light else (255, 255, 255, 255)   # logo clara→glow escuro; escura→glow claro
        sil = Image.new("RGBA", lg.size, glow); sil.putalpha(lg.getchannel("A"))
        halo = Image.new("RGBA", (lg.width + pad * 4, lg.height + pad * 4), (0, 0, 0, 0))
        halo.paste(sil, (pad * 2, pad * 2), sil)
        halo = halo.filter(ImageFilter.GaussianBlur(pad))
        for _ in range(3):   # reforça o glow p/ separar bem da foto
            canvas.paste(halo, (px - pad * 2, py - pad * 2), halo)
    canvas.paste(lg, (px, py), lg)


def _logo_lum(lg: Image.Image) -> float:
    """Luminância média dos pixels VISÍVEIS da logo (0-255)."""
    small = lg.convert("RGBA").resize((40, 40)); px = small.load()
    tot, lum = 0, 0.0
    for yy in range(40):
        for xx in range(40):
            r, g, b, a = px[xx, yy]
            if a > 40:
                tot += 1; lum += 0.299 * r + 0.587 * g + 0.114 * b
    return (lum / tot) if tot else 0.0


def _place_brand_logo(canvas: Image.Image, lg: Image.Image, x: int, y: int, mode: str = "auto"):
    """Cola a logo da marca no rodapé. mode 'auto': se o contraste com o fundo for BAIXO em
    QUALQUER cor (ex.: logo laranja sobre CTA laranja → some), põe um BACKING suave borrado
    (blob arredondado de luminância oposta, baixa opacidade — sem caixa dura) p/ a logo aparecer.
    mode 'none': cola direto. Resolve o caso do CTA sem depender de claro/escuro."""
    if mode != "none":
        bg_lum = _region_lum(canvas, (x, y, min(W, x + lg.width), min(H, y + lg.height)))
        if abs(_logo_lum(lg) - bg_lum) < 55:
            pad = 24
            fill = (255, 255, 255, 165) if bg_lum < 140 else (0, 0, 0, 150)   # backing claro p/ fundo médio/escuro
            back = Image.new("RGBA", (lg.width + pad * 2, lg.height + pad * 2), (0, 0, 0, 0))
            ImageDraw.Draw(back).rounded_rectangle([0, 0, back.width, back.height],
                                                   (lg.height + pad * 2) // 2, fill=fill)
            back = back.filter(ImageFilter.GaussianBlur(pad // 2))   # bordas suaves: vira halo, não caixa
            canvas.paste(back, (x - pad, y - pad), back)
    canvas.paste(lg, (x, y), lg)


def _pick_logo_variant(paths, bg_lum: float, max_w: int, max_h: int) -> Optional[Image.Image]:
    """Escolhe, entre as VARIANTES de logo cadastradas (branca, preta, colorida…), a de MELHOR
    contraste contra o fundo daquela região (branca em fundo escuro, escura em fundo claro).
    Retorna a Image já carregada/redimensionada. Assim não precisa do backing feio quando há variante."""
    items = paths if isinstance(paths, (list, tuple)) else [paths]
    best, best_score = None, -1.0
    for p in items:
        if not p:
            continue
        lg = _load_logo(p, max_w, max_h)
        if not lg:
            continue
        score = abs(_logo_lum(lg) - bg_lum)   # quanto maior a diferença de luminância, melhor o contraste
        if score > best_score:
            best, best_score = lg, score
    return best


def _wrap(draw, text, font, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_headline(draw, text, max_w, max_h, start=80, min_size=42):
    for size in range(start, min_size - 1, -3):
        f = _font(size, bold=True)
        lines = _wrap(draw, text, f, max_w)
        lh = int(size * 1.12)
        if len(lines) <= 4 and lh * len(lines) <= max_h:
            return f, lines, lh
    f = _font(min_size, bold=True)
    return f, _wrap(draw, text, f, max_w)[:4], int(min_size * 1.12)


M = 60
GREY = (74, 71, 67)


def _text_block(d, x, y, max_w, headline, subheadline, benefits, cta, base_col, sub_col, h_start=80):
    hf, hlines, hlh = _fit_headline(d, (headline or "").upper(), max_w, 400, start=h_start)
    for ln in hlines:
        d.text((x, y), ln, font=hf, fill=base_col); y += hlh
    d.rectangle([x, y + 8, x + 96, y + 17], fill=ORANGE); y += 40
    if subheadline:
        sf = _font(28, bold=False)
        for ln in _wrap(d, subheadline, sf, max_w)[:3]:
            d.text((x, y), ln, font=sf, fill=sub_col); y += 37
        y += 14
    bf = _font(28, bold=True)
    for b in benefits:
        d.ellipse([x, y + 9, x + 17, y + 26], fill=ORANGE)
        d.text((x + 32, y), b, font=bf, fill=base_col); y += 46
    if benefits:
        y += 10
    if cta:
        cf = _font(27, bold=True)
        tw = d.textlength(cta, font=cf)
        d.rounded_rectangle([x, y + 4, x + tw + 48, y + 56], 26, fill=ORANGE)
        d.text((x + 24, y + 14), cta, font=cf, fill=WHITE)
    return y


def _side_scrim(canvas, side, width=700):
    sh = H - FOOT_H
    solid = int(width * 0.72)
    vals = [235 if i < solid else max(0, int(235 * (1 - (i - solid) / (width - solid)))) for i in range(width)]
    if side == "right":
        vals = vals[::-1]
    grad = Image.new("L", (width, 1)); grad.putdata(vals)
    scrim = Image.new("RGBA", (width, sh), CREAM + (255,))
    scrim.putalpha(grad.resize((width, sh)))
    canvas.paste(scrim, (0 if side == "left" else W - width, 0), scrim)


def _footer(d, canvas, company_logo_path, site, phone):
    fy = H - FOOT_H
    d.rectangle([0, fy, W, H], fill=CREAM)
    d.rectangle([0, H - 12, W, H], fill=ORANGE)
    co = _load_logo(company_logo_path, 320, FOOT_H - 56)
    if co:
        canvas.paste(co, (48, fy + (FOOT_H - 12 - co.height) // 2), co)
    site_t = (site or "").replace("https://", "").replace("http://", "").strip("/").upper()
    if site_t:
        d.text((W - 48, fy + 30), site_t, font=_font(32, bold=True), fill=ORANGE, anchor="ra")
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) == 11:
            phone = f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
        elif len(digits) == 10:
            phone = f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
        d.text((W - 48, fy + 80), f"FALE CONOSCO:  {phone}", font=_font(23, bold=True), fill=CHAR, anchor="ra")


def compose_branded_post(post_bytes: bytes, headline: str = "", subheadline: str = "",
                         benefits=None, cta: str = "",
                         company_logo_path: Optional[str] = None,
                         app_logo_path: Optional[str] = None,
                         site: str = "", phone: str = "",
                         colors: Optional[Dict[str, str]] = None, variant: int = 0) -> bytes:
    """A IA gera só o FUNDO; o código desenha headline/benefícios/logo/rodapé. 4 LAYOUTS que
    alternam (variant) pra não ficar tudo igual: 0=texto esq · 1=texto dir · 2=faixa embaixo · 3=sobreposto."""
    benefits = [str(b).strip() for b in (benefits or []) if str(b).strip()][:3]
    canvas = _cover(Image.open(io.BytesIO(post_bytes)), W, H).convert("RGB")
    d = ImageDraw.Draw(canvas)
    al = _load_logo(app_logo_path, 220, 74)
    variant = int(variant) % 4

    if variant in (0, 1):
        side = "left" if variant == 0 else "right"
        _side_scrim(canvas, side, 700)
        col_w = int(W * 0.50)
        tx = M if side == "left" else (W - col_w - M)
        y0 = 150
        if al:
            if _logo_is_light(al):
                lx = (W - al.width - M) if side == "left" else M     # logo clara no lado da foto
            else:
                lx = tx; y0 = 54 + al.height + 26                    # logo escura acima do texto
            canvas.paste(al, (lx, 54), al)
        _text_block(d, tx, y0, col_w, headline, subheadline, benefits, cta, CHAR, GREY)

    elif variant == 2:
        band_top = int(H * 0.50)
        d.rectangle([0, band_top, W, H - FOOT_H], fill=CREAM)
        if al:
            canvas.paste(al, (M, 34), al)
        _text_block(d, M, band_top + 40, W - M * 2, headline, subheadline, benefits, cta, CHAR, GREY, h_start=72)

    else:  # 3: foto cheia + gradiente escuro embaixo + texto branco
        gh = int(H * 0.66)
        grad = Image.new("L", (1, gh)); grad.putdata([max(0, int(240 * (i / gh))) for i in range(gh)])
        shade = Image.new("RGBA", (W, gh), (12, 12, 14, 255))
        shade.putalpha(grad.resize((W, gh)))
        canvas.paste(shade, (0, H - FOOT_H - gh), shade)
        if al:
            canvas.paste(al, (M, 40), al)
        _text_block(d, M, int(H * 0.33), W - M * 2, headline, subheadline, benefits, cta, WHITE, (222, 220, 216), h_start=74)

    _footer(d, canvas, company_logo_path, site, phone)
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Carrossel editorial (estilo g4/v4): tipografia forte, identidade, sem cara de venda
# ─────────────────────────────────────────────────────────────────────────────

def _mix(a, b, t):
    """Mistura cor a→b (t=0..1)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _overlap(a, b) -> bool:
    """True se os retângulos (x0,y0,x1,y1) se sobrepõem. Bbox guard."""
    if not a or not b:
        return False
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


# ─────────────────────────────────────────────────────────────────────────────
# DESIGN SYSTEM EDITORIAL — config ABERTA (antes era número mágico no código).
# Edite aqui (ou via get_setting("carousel.design") JSON) p/ mudar margens, tamanhos,
# pesos, cores de esquema e layout. As CORES da marca vêm do brand_kit do cliente.
# ─────────────────────────────────────────────────────────────────────────────
EDITORIAL_DESIGN: Dict[str, Any] = {
    "margin": 96,                                   # margem lateral (px)
    "progress": {"y": 72, "h": 8, "radius": 4, "gap": 3, "muted_mix": 0.72},
    "app_logo": {"w": 220, "h": 64, "y": 118, "pos": "top_right", "on_all": False, "max_per_slide": 3},  # on_all=todas as telas; max_per_slide=quantas logos de app por tela (maleável)
    "footer": {"y": 96, "size": 30, "logo_w": 200, "logo_h": 60,
               "logo_pos": "bottom_left", "logo_contrast": "auto", "show_handle": True, "show_counter": True},
    "cover": {"eyebrow_size": 32, "eyebrow_y": 168, "title_start": 118, "title_min": 60,
              "title_step": 4, "title_lh": 1.04, "title_y": 250, "title_box_h": 640,
              "accent_bar_w": 120, "sub_size": 38, "sub_lh": 50, "swipe_label": "arraste", "swipe_size": 34},
    "content": {"num_size": 168, "num_y": 150, "title_y": 372, "title_size": 60, "title_lh": 70,
                "title_max_lines": 3, "body_size": 40, "body_lh": 54, "body_max_lines": 9,
                "gap_title_body": 22, "alternate_bg": True, "align": "left"},  # align: left|center|right (igual em todas as telas)
    "cta": {"title_start": 92, "title_min": 52, "title_y": 250, "title_box_h": 520, "sub_size": 40,
            "sub_lh": 54, "cta_size": 40, "pill_h": 96, "pill_radius": 30, "default_cta": "Fale conosco",
            "contact_size": 34},
}


def _coerce_nums(o):
    """Converte strings numéricas/booleanas em número/bool (o editor de config salva tudo como texto)."""
    import re as _re
    if isinstance(o, dict):
        return {k: _coerce_nums(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_coerce_nums(v) for v in o]
    if isinstance(o, str):
        s = o.strip()
        if _re.fullmatch(r"-?\d+", s):
            return int(s)
        if _re.fullmatch(r"-?\d*\.\d+", s):
            return float(s)
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
    return o


def _design(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Design system editorial EFETIVO = default + override do CLIENTE (creative_config.design).
    Coage números (o editor de config grava como texto) p/ não estourar na conta do compositor."""
    base = EDITORIAL_DESIGN
    if isinstance(override, dict) and override:
        merged = {**base}
        for k, v in override.items():
            merged[k] = {**base.get(k, {}), **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        return _coerce_nums(merged)
    return base


def compose_carousel_slide(slide: Dict, idx: int, total: int,
                           colors: Optional[Dict] = None,
                           company_logo_path: Optional[str] = None,
                           site: str = "", handle: str = "",
                           bg_bytes: Optional[bytes] = None,
                           app_logo_path: Optional[str] = None,
                           design: Optional[Dict[str, Any]] = None,
                           app_logos=None) -> bytes:
    """Renderiza 1 slide editorial. type: cover | content | cta. idx é 1-based.
    bg_bytes (opcional): imagem de fundo gerada por IA → modo híbrido (foto + scrim + texto).
    app_logo_path (opcional): logo OFICIAL do app desta tela → carimbada limpa (topo-direita).
    design (opcional): override do design system DO CLIENTE (merge com EDITORIAL_DESIGN)."""
    DZ = _design(design)
    colors = colors or {}
    orange = _hex(colors.get("accent") or colors.get("primary"), ORANGE)
    dark = _hex(colors.get("dark"), CHAR)
    cream = _hex(colors.get("bg"), CREAM)
    t = (slide.get("type") or "content").lower()
    Mx = DZ["margin"]

    if t == "cta":
        bg, fg, sub_fg, acc = orange, WHITE, _mix(WHITE, orange, 0.18), WHITE
    elif t == "cover":
        bg, fg, sub_fg, acc = dark, WHITE, _mix(WHITE, dark, 0.45), orange
    else:  # content — alterna escuro/claro p/ ritmo editorial
        if DZ["content"].get("alternate_bg", True) and idx % 2 == 0:
            bg, fg, sub_fg, acc = cream, dark, GREY, orange
        else:
            bg, fg, sub_fg, acc = dark, WHITE, _mix(WHITE, dark, 0.45), orange

    if bg_bytes:
        # Híbrido: fundo gerado por IA + scrim escuro p/ legibilidade + texto branco editorial.
        try:
            photo = _cover(Image.open(io.BytesIO(bg_bytes)).convert("RGB"), W, H)
            canvas = photo.copy()
            grad = Image.new("L", (1, H))
            grad.putdata([int(150 + 95 * (i / H)) for i in range(H)])  # mais escuro embaixo
            scrim = Image.new("RGBA", (W, H), (16, 15, 14, 255))
            scrim.putalpha(grad.resize((W, H)))
            canvas = canvas.convert("RGBA"); canvas.alpha_composite(scrim); canvas = canvas.convert("RGB")
            bg = dark; fg = WHITE; sub_fg = _mix(WHITE, dark, 0.30); acc = orange
        except Exception:
            canvas = Image.new("RGB", (W, H), bg)
    else:
        canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)

    # barra de progresso (quantos slides, onde estamos)
    pr = DZ["progress"]
    seg_w = (W - Mx * 2) / max(1, total)
    muted = _mix(fg, bg, pr["muted_mix"])
    for i in range(total):
        x0 = Mx + i * seg_w
        d.rounded_rectangle([x0 + pr["gap"], pr["y"], x0 + seg_w - pr["gap"], pr["y"] + pr["h"]], pr["radius"],
                            fill=acc if i < idx else muted)

    # Marco 1 (PADRÃO): a posição do texto é TRAVADA — sempre à esquerda, mesma régua em TODAS as
    # telas. A variedade vem da FOTO, não do lugar do texto (consistência > liberdade).

    # Logos de app — MALEÁVEL: 1..N por tela (a tela decide). Cada item de `app_logos` é a lista de
    # VARIANTES de um app; sem ele, usa o `app_logo_path` único (compat). Máximo por tela = token
    # app_logo.max_per_slide (default 3). _stamp_app_logo escolhe a variante e só põe halo se sumir.
    al = DZ["app_logo"]
    apps_to_draw = [a for a in (app_logos if app_logos else ([app_logo_path] if app_logo_path else [])) if a]
    apps_to_draw = apps_to_draw[:int(al.get("max_per_slide", 3))]
    if apps_to_draw:
        left_side = "left" in (al.get("pos") or "top_right").lower()
        x_cursor = Mx if left_side else (W - Mx)   # esquerda→ avança p/ direita; direita→ recua p/ esquerda
        for variants in apps_to_draw:
            probe = (x_cursor, al["y"], x_cursor + al["w"], al["y"] + al["h"]) if left_side \
                else (x_cursor - al["w"], al["y"], x_cursor, al["y"] + al["h"])
            alg = _pick_logo_variant(variants, _region_lum(canvas, probe), al["w"], al["h"])
            if not alg:
                continue
            x = x_cursor if left_side else (x_cursor - alg.width - 32)
            _stamp_app_logo(canvas, alg, x, al["y"])
            x_cursor = (x + alg.width + 56 + 36) if left_side else (x - 56)

    title = (slide.get("title") or "").strip()
    body = (slide.get("body") or "").strip()
    sub = (slide.get("subtitle") or "").strip()

    if t == "cover":
        C = DZ["cover"]
        eb = (slide.get("eyebrow") or "").strip().upper()
        if eb:
            d.text((Mx, C["eyebrow_y"]), eb, font=_font(C["eyebrow_size"], weight="semibold"), fill=acc)
        y = C["title_y"]
        for size in range(C["title_start"], C["title_min"] - 1, -C["title_step"]):
            f = _font(size, weight="black")
            lines = _wrap(d, title.upper(), f, W - Mx * 2)
            lh = int(size * C["title_lh"])
            if len(lines) <= 5 and lh * len(lines) <= C["title_box_h"]:
                break
        for ln in lines:
            d.text((Mx, y), ln, font=f, fill=fg); y += lh
        d.rectangle([Mx, y + 18, Mx + C["accent_bar_w"], y + 30], fill=acc)
        if sub:
            y += 64
            for ln in _wrap(d, sub, _font(C["sub_size"]), W - Mx * 2)[:3]:
                d.text((Mx, y), ln, font=_font(C["sub_size"]), fill=sub_fg); y += C["sub_lh"]
        af = _font(C["swipe_size"], weight="semibold")
        d.text((Mx, H - 184), C["swipe_label"], font=af, fill=acc)
        ax = Mx + d.textlength(C["swipe_label"], font=af) + 22; ay = H - 184 + 18
        d.polygon([(ax, ay - 13), (ax, ay + 13), (ax + 22, ay)], fill=acc)

    elif t == "cta":
        C = DZ["cta"]
        y = C["title_y"]
        f, lines, lh = _fit_headline(d, title.upper(), W - Mx * 2, C["title_box_h"], start=C["title_start"], min_size=C["title_min"])
        f = _font(f.size, weight="extrabold")
        for ln in lines:
            d.text((Mx, y), ln, font=f, fill=fg); y += lh
        if sub:
            y += 28
            for ln in _wrap(d, sub, _font(C["sub_size"]), W - Mx * 2)[:3]:
                d.text((Mx, y), ln, font=_font(C["sub_size"]), fill=sub_fg); y += C["sub_lh"]
        cta = (slide.get("cta") or C["default_cta"]).strip()
        cf = _font(C["cta_size"], weight="semibold"); tw = d.textlength(cta, font=cf)
        by = y + 56
        pill_fill = orange if bg_bytes else dark   # foto(scrim escuro)→botão laranja; CTA laranja sólido→botão escuro
        d.rounded_rectangle([Mx, by, Mx + tw + 76, by + C["pill_h"]], C["pill_radius"], fill=pill_fill)
        d.text((Mx + 38, by + 24), cta, font=cf, fill=WHITE)
        # contato EMPILHADO e limpo (sem "·"): telefone em destaque, site menor embaixo
        cy = by + C["pill_h"] + 40
        ph = (slide.get("phone") or "").strip()
        site_t = (site or "").replace("https://", "").replace("http://", "").strip("/")
        cs = C["contact_size"]
        if ph:
            d.text((Mx, cy), ph, font=_font(cs + 6, weight="extrabold"), fill=acc); cy += int((cs + 6) * 1.45)
        if site_t:
            d.text((Mx, cy), site_t, font=_font(int(cs * 0.82), weight="semibold"), fill=sub_fg)

    else:  # content — alinhamento vem do token C["align"] (default 'left'), IGUAL em todas as telas
        # da empresa (consistência), mas configurável por cliente. Régua vertical determinística.
        C = DZ["content"]
        align = (C.get("align") or "left").lower()
        ax, anc = (W - Mx, "ra") if align == "right" else (W // 2, "ma") if align == "center" else (Mx, "la")
        d.text((ax, C["num_y"]), f"{int(slide.get('number') or idx):02d}",
               font=_font(C["num_size"], weight="black"), fill=acc, anchor=anc)
        y = C["title_y"]
        tf = _font(C["title_size"], weight="extrabold")
        for ln in _wrap(d, title, tf, W - Mx * 2)[:C["title_max_lines"]]:
            d.text((ax, y), ln, font=tf, fill=fg, anchor=anc); y += int(C["title_size"] * 1.16)
        y += C["gap_title_body"]
        bf = _font(C["body_size"])
        safe_bottom = H - DZ["footer"]["y"] - 36   # bbox guard: corpo não invade o footer
        for ln in _wrap(d, body, bf, W - Mx * 2)[:C["body_max_lines"]]:
            if y + C["body_lh"] > safe_bottom:
                break
            d.text((ax, y), ln, font=bf, fill=sub_fg, anchor=anc); y += C["body_lh"]

    # rodapé CONFIGURÁVEL (tokens em F): logo da marca na posição F["logo_pos"], com contraste
    # AUTO (halo suave quando a logo fosse sumir num fundo da mesma cor — ex.: CTA laranja).
    # Contador à direita. Sem logo transparente usável → @handle (degradação graciosa).
    F = DZ["footer"]
    fy = H - F["y"]
    cf = _font(F["size"], weight="semibold")
    foot_bg_lum = _region_lum(canvas, (Mx, fy, Mx + F["logo_w"], H))   # fundo atrás da logo → escolhe a variante certa
    lg = _pick_logo_variant(company_logo_path, foot_bg_lum, F["logo_w"], F["logo_h"])
    if lg and lg.mode == "RGBA" and lg.getextrema()[3][0] < 250:
        pos = (F.get("logo_pos") or "bottom_left").lower()
        lx = (W - Mx - lg.width) if "right" in pos else (W - lg.width) // 2 if "center" in pos else Mx
        ly = fy + 8 + (F["size"] - lg.height) // 2   # centra a logo na linha do contador
        _place_brand_logo(canvas, lg, lx, ly, F.get("logo_contrast", "auto"))
    elif F.get("show_handle", True):
        left = ("@" + handle.lstrip("@")) if handle else site
        if left:
            d.text((Mx, fy + 8), left, font=cf, fill=fg)
    if F.get("show_counter", True):
        d.text((W - Mx, fy + 8), f"{idx}/{total}", font=cf, fill=acc, anchor="ra")

    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# MARCO 3 — design "nível agência": foto FORTE + CARD de vidro. Travas DURAS: texto sempre
# legível (dentro do card), logo NUNCA coberta (zonas reservadas), card no ESPAÇO NEGATIVO da
# arte (lado oposto ao sujeito). Capa/conteúdo/CTA falam a mesma língua. Tudo em tokens (design.card).
# ─────────────────────────────────────────────────────────────────────────────
def _frost_card(canvas, box, tint, radius, blur=20):
    """Card de vidro: borra o trecho da arte atrás + tint da marca semi-transparente + cantos arredondados.
    A arte aparece (frosted), o texto fica legível por cima."""
    x0, y0, x1, y1 = box
    reg = canvas.crop(box).filter(ImageFilter.GaussianBlur(blur)).convert("RGBA")
    reg = Image.alpha_composite(reg, Image.new("RGBA", reg.size, tuple(tint)))
    m = Image.new("L", reg.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, reg.size[0], reg.size[1]], radius, fill=255)
    canvas.paste(reg, (x0, y0), m)
    ImageDraw.Draw(canvas).rounded_rectangle(box, radius, outline=(255, 255, 255, 42), width=2)


def _text_bg(canvas, box, style, tint, radius, acc):
    """Tratamento do FUNDO do texto — VARIEDADE criativa, mantendo o texto legível no lado livre:
    glass=vidro fosco (padrão) · solid=bloco escuro c/ barra de acento · scrim=gradiente sem caixa (foto aparece) ·
    outline=blur leve + contorno de acento. Acaba com o 'mesmo quadrado em toda arte'."""
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(canvas, "RGBA")
    if style == "solid":
        d.rounded_rectangle(box, max(8, radius // 2), fill=(15, 12, 17, 236))
        d.rectangle([x0, y0 + radius, x0 + 9, y1 - radius], fill=acc)            # barra de acento na lateral
    elif style == "scrim":
        pad = 42
        bx = (max(0, x0 - pad), max(0, y0 - pad), min(canvas.width, x1 + pad), min(canvas.height, y1 + pad))
        gw, gh = bx[2] - bx[0], bx[3] - bx[1]
        g = Image.new("L", (gw, gh), 0)
        ImageDraw.Draw(g).ellipse([0, 0, gw, gh], fill=175)
        g = g.filter(ImageFilter.GaussianBlur(48))
        dark = Image.new("RGBA", (gw, gh), (6, 5, 9, 255)); dark.putalpha(g)
        canvas.alpha_composite(dark, (bx[0], bx[1]))                            # vinheta escura, SEM caixa
    elif style == "outline":
        reg = canvas.crop(box).filter(ImageFilter.GaussianBlur(9)).convert("RGBA")
        reg = Image.alpha_composite(reg, Image.new("RGBA", reg.size, (12, 10, 14, 150)))
        m = Image.new("L", reg.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, reg.size[0], reg.size[1]], radius, fill=255)
        canvas.paste(reg, (x0, y0), m)
        d.rounded_rectangle(box, radius, outline=acc, width=3)                  # contorno de acento
    else:  # glass (padrão aprovado)
        _frost_card(canvas, box, tint, radius)


def _calm_side(canvas, slide):
    """Lado (left/right) onde o card deve sentar = onde a arte deixou ESPAÇO NEGATIVO (não cobre o sujeito).
    Respeita text_area/layout_variant; senão escolhe a metade inferior de MENOR variância (mais calma)."""
    ta = (slide.get("text_area") or "").lower()
    lv = (slide.get("layout_variant") or "").lower()
    if ta in ("left", "right"):
        return ta
    if "right" in lv:
        return "right"
    if "left" in lv:
        return "left"
    g = canvas.convert("L")
    def _var(box):
        data = list(g.crop(box).resize((36, 36)).getdata())
        mu = sum(data) / len(data)
        return sum((v - mu) ** 2 for v in data) / len(data)
    yb = int(H * 0.45)
    return "left" if _var((0, yb, W // 2, H)) <= _var((W // 2, yb, W, H)) else "right"


def _pill(d, x, y, txt, acc, fs=24):
    f = _font(fs, weight="extrabold")
    w = d.textlength(txt, font=f)
    d.rounded_rectangle([x, y, x + w + 38, y + fs + 20], (fs + 20) // 2, fill=acc)
    d.text((x + 19, y + 10), txt, font=f, fill=WHITE)
    return w + 38


def _arraste(d, x, y, acc):
    """Pílula 'arraste' + TRIÂNGULO desenhado (não depende de glyph ▶ que a fonte pode não ter)."""
    f = _font(28, weight="extrabold"); txt = "arraste"
    w = d.textlength(txt, font=f)
    d.rounded_rectangle([x, y, x + w + 80, y + 48], 24, fill=acc)
    d.text((x + 26, y + 9), txt, font=f, fill=WHITE)
    cx, cy = x + w + 48, y + 24
    d.polygon([(cx, cy - 9), (cx + 15, cy), (cx, cy + 9)], fill=WHITE)


def _soft_panel(canvas, box, radius):
    """Área JÁ ESCURA → véu MUITO sutil (não mata a arte de trás), bordas borradas. Texto legível, fundo aparece."""
    x0, y0, x1, y1 = box
    ov = Image.new("RGBA", (max(1, x1 - x0), max(1, y1 - y0)), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle([0, 0, x1 - x0, y1 - y0], radius, fill=(8, 6, 8, 92))
    ov = ov.filter(ImageFilter.GaussianBlur(10))
    base = canvas.crop(box).convert("RGBA")
    canvas.paste(Image.alpha_composite(base, ov), (x0, y0))


def _best_region(canvas, cw, bh, has_app, M):
    """PADRÃO DE PENSAMENTO: acha ONDE o texto encaixa melhor — a região mais ESCURA e CALMA (não sobre o
    sujeito/elementos), longe das logos. Varia de verdade por arte. Retorna (x0, y0, luminância média)."""
    g = canvas.convert("L")
    def stat(x0, y0):
        crop = g.crop((x0, y0, x0 + cw, y0 + bh)).resize((44, 44))
        data = list(crop.getdata()); mu = sum(data) / len(data)
        var = sum((v - mu) ** 2 for v in data) / len(data)
        return mu, var
    bot = H - 150 - bh; top = 200; mid = (H - bh) // 2
    cands = [(M, bot), (W - M - cw, bot), (M, top), (M, mid), (W - M - cw, mid)]
    if not has_app:
        cands.append((W - M - cw, top))
    best, bscore = (M, max(200, bot), 128.0), 1e9
    for (x0, y0) in cands:
        if y0 < 196 or y0 + bh > H - 130:
            continue
        mu, var = stat(x0, y0)
        score = mu + 0.35 * (var ** 0.5)   # escuro + calmo = score baixo = melhor lugar p/ o texto
        if score < bscore:
            bscore, best = score, (x0, y0, mu)
    return best


def _subject_side(canvas):
    """Metade (left/right) com MENOS detalhe = lado VAZIO → o texto vai pra lá (o sujeito está no outro).
    Compara METADES INTEIRAS por densidade de BORDAS — uma cara BORRADA não engana (o lado do sujeito tem
    mais borda no total: roupa, mãos, objetos, partes em foco). Confiável mesmo com bokeh."""
    W_, H_ = canvas.width, canvas.height
    e = canvas.convert("L").filter(ImageFilter.FIND_EDGES)
    def busy(box):
        c = e.crop(box).resize((50, 80)); data = list(c.getdata())
        return sum(data) / len(data)
    return "left" if busy((0, 0, W_ // 2, H_)) <= busy((W_ // 2, 0, W_, H_)) else "right"


def _place_y(canvas, x0, cw, bh):
    """Na coluna do lado vazio, acha a faixa VERTICAL mais LISA (menos borda) p/ o card — foge de rosto/detalhe
    residual. Reserva a barra de progresso (topo) e o rodapé."""
    H_ = canvas.height
    e = canvas.convert("L").filter(ImageFilter.FIND_EDGES)
    lo, hi = 200, H_ - 130 - bh
    if hi <= lo:
        return max(196, H_ - 150 - bh)
    best, bscore, y = lo, 1e18, lo
    while y <= hi:
        c = e.crop((x0, y, x0 + cw, y + bh)).resize((44, 44)); data = list(c.getdata())
        s = sum(data) / len(data)
        if s < bscore:
            bscore, best = s, y
        y += 36
    return best


def compose_card_slide(slide: Dict, idx: int, total: int,
                       colors: Optional[Dict] = None, company_logo_path=None,
                       site: str = "", handle: str = "", bg_bytes: Optional[bytes] = None,
                       app_logo_path=None, design: Optional[Dict[str, Any]] = None, app_logos=None,
                       canvas_size=None) -> bytes:
    """Marco 3: foto da IA + CARD de vidro (capa/conteúdo/CTA). MESMA assinatura do compose_carousel_slide.
    canvas_size=(w,h) p/ outros formatos (post 4:5, story 9:16); default = carrossel 4:5 (1080×1350).
    SEM foto OU em QUALQUER erro → cai pro compose_carousel_slide aprovado (degradação graciosa)."""
    if not bg_bytes:
        return compose_carousel_slide(slide, idx, total, colors, company_logo_path, site, handle,
                                      bg_bytes, app_logo_path, design, app_logos)
    try:
        colors = colors or {}
        ACC = _hex(colors.get("accent") or colors.get("primary"), ORANGE)
        cardcfg = (design or {}).get("card") or {}
        tint = cardcfg.get("tint", [20, 12, 9, 184])   # opaco o bastante p/ ESCONDER quem estiver atrás (não "texto na cara")
        radius = int(cardcfg.get("radius", 40))
        M = int(cardcfg.get("margin", 72))
        W_, H_ = canvas_size or (W, H)
        canvas = _cover(Image.open(io.BytesIO(bg_bytes)).convert("RGB"), W_, H_).convert("RGBA")
        d = ImageDraw.Draw(canvas)
        t = (slide.get("type") or "content").lower()
        page = f"{idx}/{total}"
        # barra de progresso — SÓ no carrossel (1 arte avulsa não tem "telas")
        if total > 1:
            seg = (W_ - 2 * M - (total - 1) * 12) / max(1, total)
            for i in range(total):
                x = M + i * (seg + 12)
                d.rounded_rectangle([x, 56, x + seg, 62], 3, fill=ACC if i < idx else (255, 255, 255, 70))
        # logo(s) de app no topo-direita (melhor variante por contraste) — ZONA RESERVADA, nunca coberta
        applist = [a for a in (app_logos or []) if a] or ([[app_logo_path]] if app_logo_path else [])
        ax = W_ - M
        for variants in applist[:3]:
            lg = _pick_logo_variant(variants, _region_lum(canvas.convert("RGB"), (max(0, ax - 210), 92, ax, 168)), 200, 56)
            if lg:
                _stamp_app_logo(canvas, lg, ax - lg.width, 96); ax -= lg.width + 28
        # rodapé: logo da marca (melhor variante) embaixo-esquerda + número — ZONA RESERVADA
        bl = _pick_logo_variant(company_logo_path, _region_lum(canvas.convert("RGB"), (M, H_ - 110, M + 240, H_ - 40)), 240, 66)
        if bl:
            _stamp_app_logo(canvas, bl, M, H_ - 40 - bl.height)
        if total > 1:
            d.text((W_ - 150, H_ - 70), page, font=_font(30, weight="bold"), fill=(255, 255, 255, 220))
        title = (slide.get("title") or "").strip()
        body = (slide.get("body") or slide.get("subheadline") or "").strip()
        pad = 40
        has_app = bool(applist)
        # ESTILO do tratamento de texto (variedade por carrossel; configurável via design.text_style):
        style = (slide.get("text_style") or cardcfg.get("style") or "glass").lower()
        def _put(cw, bh):
            # CONFIÁVEL: lado VAZIO definido pelo JUIZ DE VISÃO (slide['text_side']); senão heurística de borda.
            side = (slide.get("text_side") or "").lower()
            if side not in ("left", "right"):
                side = _subject_side(canvas)
            x0 = M if side == "left" else W_ - M - cw
            y0 = _place_y(canvas, x0, cw, bh)
            _text_bg(canvas, (x0, y0, x0 + cw, y0 + bh), style, tint, radius, ACC)
            return x0, y0
        if t == "cover":
            cw = int(W_ * 0.44); inner = cw - 2 * pad     # ESTREITO: fica na metade vazia, não cruza o centro/sujeito
            tf = _font(int(cardcfg.get("title_size", 58)), weight="extrabold")
            eb = (slide.get("eyebrow") or ("Arraste para o lado" if total > 1 else "")).strip().upper()
            tl = _wrap(d, title, tf, inner)
            foot = 80 if total > 1 else 0          # espaço do "arraste" SÓ no carrossel
            bh = pad + (44 if eb else 0) + len(tl) * int(tf.size * 1.05) + foot + pad
            x0, y0 = _put(cw, bh); tx = x0 + pad; ty = y0 + pad
            if eb:
                d.text((tx, ty), eb, font=_font(26, weight="extrabold"), fill=ACC); ty += 44
            for k, ln in enumerate(tl):
                if k == len(tl) - 1 and " " in ln:   # destaca a última palavra em ACC
                    pre, last = ln.rsplit(" ", 1)
                    d.text((tx, ty), pre + " ", font=tf, fill=WHITE)
                    d.text((tx + d.textlength(pre + " ", font=tf), ty), last, font=tf, fill=ACC)
                else:
                    d.text((tx, ty), ln, font=tf, fill=WHITE)
                ty += int(tf.size * 1.05)
            if total > 1:
                _arraste(d, tx, ty + 12, ACC)
        elif t == "cta":
            cw = int(W_ * 0.44); inner = cw - 2 * pad     # ESTREITO: dentro da metade vazia
            hf = _font(42, weight="extrabold")
            hl = _wrap(d, title or "Fale com a gente", hf, inner)
            sub = (slide.get("subtitle") or slide.get("body") or "").strip()   # ex.: datas/stand do evento
            sf = _font(25, weight="semibold")
            sln = _wrap(d, sub, sf, inner) if sub else []
            phone = (slide.get("phone") or "").strip()
            site_t = (site or "").replace("https://", "").replace("http://", "").strip("/")
            btn = (slide.get("cta") or "Fale com a gente").strip()
            bh = pad + len(hl) * 54 + (len(sln) * 32 + 14 if sln else 0) + 24 + 72 + 26 + (50 if phone else 0) + (38 if site_t else 0) + pad
            x0, y0 = _put(cw, bh); tx = x0 + pad; ty = y0 + pad
            for ln in hl:
                d.text((tx, ty), ln, font=hf, fill=WHITE); ty += 54
            if sln:
                ty += 8
                for ln in sln:
                    d.text((tx, ty), ln, font=sf, fill=(255, 255, 255, 235)); ty += 32
            ty += 18
            bf = _font(32, weight="extrabold")
            while d.textlength(btn, font=bf) + 64 > inner and bf.size > 20:   # encolhe até CABER no bloco (nunca invade a arte)
                bf = _font(bf.size - 2, weight="extrabold")
            bw = d.textlength(btn, font=bf); btn_w = int(min(bw + 64, inner))
            d.rounded_rectangle([tx, ty, tx + btn_w, ty + 68], 34, fill=ACC)
            d.text((tx + (btn_w - bw) // 2, ty + 16), btn, font=bf, fill=WHITE); ty += 94
            if phone:
                d.text((tx, ty), phone, font=_font(38, weight="extrabold"), fill=ACC); ty += 50
            if site_t:
                d.text((tx, ty), site_t, font=_font(28, weight="semibold"), fill=(255, 255, 255, 220))
        else:  # content — SEM pílula de nome (a logo do app já está no topo): número + título + corpo
            cw = int(W_ * 0.44); inner = cw - 2 * pad     # ESTREITO: dentro da metade vazia, longe do sujeito
            tf = _font(44, weight="extrabold"); bf = _font(28, weight="medium")
            tl = _wrap(d, title, tf, inner); blines = _wrap(d, body, bf, inner)
            bh = pad + 64 + len(tl) * 56 + 14 + len(blines) * 40 + pad
            x0, y0 = _put(cw, bh); tx = x0 + pad; ty = y0 + pad
            d.text((tx, ty), f"{idx:02d}", font=_font(54, weight="extrabold"), fill=ACC); ty += 70
            for ln in tl:
                d.text((tx, ty), ln, font=tf, fill=WHITE); ty += 56
            ty += 14
            for ln in blines:
                d.text((tx, ty), ln, font=bf, fill=(255, 255, 255, 235)); ty += 40
        out = io.BytesIO(); canvas.convert("RGB").save(out, "PNG"); return out.getvalue()
    except Exception:
        return compose_carousel_slide(slide, idx, total, colors, company_logo_path, site, handle,
                                      bg_bytes, app_logo_path, design, app_logos)


def compose_story_repost(cover_bytes: bytes, colors: Optional[Dict] = None) -> bytes:
    """Transforma a CAPA (4:5) num STORY 9:16 BONITO p/ republicar (look nativo de 'compartilhar post'):
    fundo = a própria capa borrada + escurecida; capa nítida centralizada, cantos arredondados + sombra.
    NÃO é clicável (limite da API), mas fica intencional — não 'desgunçado'."""
    SW, SH = 1080, 1920
    cov = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
    bg = _cover(cov, SW, SH).filter(ImageFilter.GaussianBlur(42))
    bg = Image.blend(bg, Image.new("RGB", (SW, SH), (0, 0, 0)), 0.58)
    canvas = bg.convert("RGBA")
    cw = int(SW * 0.86); ch = int(cw * cov.height / cov.width)
    if ch > int(SH * 0.74):                      # cabe na vertical com folga
        ch = int(SH * 0.74); cw = int(ch * cov.width / cov.height)
    card = cov.resize((cw, ch), Image.LANCZOS).convert("RGBA")
    rad = 40
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw, ch], rad, fill=255)
    x = (SW - cw) // 2; y = (SH - ch) // 2
    shadow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x, y + 14, x + cw, y + ch + 14], rad, fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(card, (x, y), mask)
    out = io.BytesIO(); canvas.convert("RGB").save(out, "PNG"); return out.getvalue()


def compose_logos_only(img_bytes: bytes, company_logo_path: Optional[str] = None,
                       app_logo_path: Optional[str] = None, colors: Optional[Dict] = None) -> bytes:
    """Modo IA-LIVRE: a IA gerou a arte INTEIRA (texto + design). O código NÃO desenha nada —
    só recorta pro 4:5 e carimba as logos OFICIAIS (app no topo-direita, empresa no rodapé-esquerda),
    cada uma em chip de contraste pra ficar legível sobre qualquer fundo."""
    canvas = _cover(Image.open(io.BytesIO(img_bytes)).convert("RGB"), W, H).convert("RGBA")
    # Logo OFICIAL no TOPO-CENTRO, PURA (transparente, SEM painel/fundo). A IA já deixou o topo limpo.
    primary = app_logo_path or company_logo_path
    if primary:
        lg = _load_logo(primary, 320, 104)
        if lg:
            canvas.alpha_composite(lg.convert("RGBA"), (int(W / 2 - lg.width / 2), 52))
    # logo da empresa pequena no rodapé se a do topo for de app (assinatura dupla), também pura
    if app_logo_path and company_logo_path:
        clg = _load_logo(company_logo_path, 150, 46)
        if clg:
            canvas.alpha_composite(clg.convert("RGBA"), (int(W / 2 - clg.width / 2), H - 50 - clg.height))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    return out.getvalue()


def compose_cta_footer(img_bytes: bytes, company_logo_path: Optional[str] = None,
                       site: str = "", phone: str = "", colors: Optional[Dict] = None) -> bytes:
    """Rodapé de contato na tela de CTA: barra com logo da empresa + 'FALE CONOSCO NO WHATSAPP: <número>'.
    Número vem do cadastro do cliente. Carimbado por código (a IA não acerta número)."""
    colors = colors or {}
    orange = _hex(colors.get("accent") or colors.get("primary"), ORANGE)
    base = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if base.size != (W, H):
        base = _cover(base, W, H)
    base = base.convert("RGBA")
    bh, mx, my = 188, 48, 48
    panel = Image.new("RGBA", (W - mx * 2, bh), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle([0, 0, W - mx * 2 - 1, bh - 1], 32,
                                            fill=(16, 15, 14, 255), outline=orange + (255,), width=3)  # OPACO: não vaza nada atrás
    py = H - bh - my
    base.alpha_composite(panel, (mx, py))
    d = ImageDraw.Draw(base)
    cy = py + bh // 2
    lg = _load_logo(company_logo_path, 240, 104)
    if lg:
        base.alpha_composite(lg.convert("RGBA"), (mx + 44, cy - lg.height // 2))
    tel = (phone or "").strip()
    dg = "".join(ch for ch in tel if ch.isdigit())
    if len(dg) == 11:
        tel = f"({dg[:2]}) {dg[2:7]}-{dg[7:]}"
    elif len(dg) == 10:
        tel = f"({dg[:2]}) {dg[2:6]}-{dg[6:]}"
    if tel:
        d.text((W - mx - 48, cy - 34), "FALE CONOSCO NO WHATSAPP:", font=_font(25, weight="semibold"), fill=(230, 230, 230), anchor="ra")
        d.text((W - mx - 48, cy + 2), tel, font=_font(44, weight="extrabold"), fill=orange, anchor="ra")
    elif site:
        d.text((W - mx - 48, cy - 16), site, font=_font(34, weight="extrabold"), fill=orange, anchor="ra")
    out = io.BytesIO()
    base.convert("RGB").save(out, "PNG")
    return out.getvalue()
