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
    "app_logo": {"w": 220, "h": 64, "y": 118},      # logo oficial do app (topo-direita)
    "footer": {"y": 96, "size": 30, "logo_w": 200, "logo_h": 60},
    "cover": {"eyebrow_size": 32, "eyebrow_y": 168, "title_start": 118, "title_min": 60,
              "title_step": 4, "title_lh": 1.04, "title_y": 250, "title_box_h": 640,
              "accent_bar_w": 120, "sub_size": 38, "sub_lh": 50, "swipe_label": "arraste", "swipe_size": 34},
    "content": {"num_size": 168, "num_y": 150, "title_y": 372, "title_size": 60, "title_lh": 70,
                "title_max_lines": 3, "body_size": 40, "body_lh": 54, "body_max_lines": 9,
                "gap_title_body": 22, "alternate_bg": True},
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
                           design: Optional[Dict[str, Any]] = None) -> bytes:
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

    # Logo OFICIAL do app no topo-DIREITA (lado oposto ao texto). _stamp_app_logo analisa o fundo e
    # só põe um painel sutil SE a logo fosse sumir — sem a caixa cinza fixa do chip antigo.
    if app_logo_path:
        al = DZ["app_logo"]
        alg = _load_logo(app_logo_path, al["w"], al["h"])
        if alg:
            _stamp_app_logo(canvas, alg, W - Mx - alg.width - 32, al["y"])

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
        d.rounded_rectangle([Mx, by, Mx + tw + 76, by + C["pill_h"]], C["pill_radius"], fill=dark)
        d.text((Mx + 38, by + 24), cta, font=cf, fill=WHITE)
        contato = "  ·  ".join([x for x in [site, slide.get("phone") or ""] if x])
        if contato:
            d.text((Mx, by + 138), contato, font=_font(C["contact_size"], weight="semibold"), fill=fg)

    else:  # content — POSIÇÃO TRAVADA: número + título + corpo SEMPRE à esquerda, mesma régua
        # vertical em todas as telas. layout_variant NÃO move mais o texto. Só a foto muda.
        C = DZ["content"]
        ax, anc = Mx, "la"
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

    # rodapé DETERMINÍSTICO (posição FIXA, sem pulo de colisão): logo da empresa à ESQUERDA,
    # contador à direita. A logo fica sobre a parte mais escura do scrim → legível em qualquer foto.
    # Sem logo transparente usável, cai pro @handle como texto (degradação graciosa).
    F = DZ["footer"]
    fy = H - F["y"]
    cf = _font(F["size"], weight="semibold")
    lg = _load_logo(company_logo_path, F["logo_w"], F["logo_h"])
    if lg and lg.mode == "RGBA" and lg.getextrema()[3][0] < 250:
        ly = fy + 8 + (F["size"] - lg.height) // 2   # centra a logo na linha do contador
        canvas.paste(lg, (Mx, ly), lg)
    else:
        left = ("@" + handle.lstrip("@")) if handle else site
        if left:
            d.text((Mx, fy + 8), left, font=cf, fill=fg)
    d.text((W - Mx, fy + 8), f"{idx}/{total}", font=cf, fill=acc, anchor="ra")

    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


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
