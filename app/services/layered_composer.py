"""ARTE EM CAMADAS (out/2026): a IA faz só a FOTO (sem texto); título, texto, botão, contato e logo são
camadas desenhadas pelo Caripost em alta resolução (2160×2700 feed / 2160×3840 story) com a fonte da marca.

Por quê: (1) tira a "cara de IA" (sem neon/glow, tipografia contida, grid limpo); (2) texto sempre nítido;
(3) as camadas viram um design EDITÁVEL no Canva (PPTX → import), cada elemento móvel.

Saída de compose(): (png_bytes, layers) — `layers` é a descrição das camadas (px do canvas) usada pelo
exportador do Canva. Tudo moldável por design tokens (creative_config.design.layered)."""
from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT_DIRS = [os.path.join(os.path.dirname(__file__), "fonts"), "/usr/share/fonts/truetype/brand/",
             "/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/"]
WEIGHTS = {"regular": ["Poppins-Regular", "DejaVuSans", "LiberationSans-Regular"],
           "medium": ["Poppins-Medium", "Poppins-Regular", "DejaVuSans"],
           "semibold": ["Poppins-SemiBold", "Poppins-Medium", "DejaVuSans-Bold"],
           "bold": ["Poppins-Bold", "Poppins-SemiBold", "DejaVuSans-Bold"]}
FONT_FAMILY = "Poppins"   # nome que vai para o Canva/PPTX
SIZES = {"post": (2160, 2700), "story": (2160, 3840)}
DEFAULTS: Dict[str, Any] = {
    "margin": 0.074,            # margem lateral (fração da largura)
    "photo_ratio": 0.60,        # altura da foto no layout foto+bloco
    "title_max": 0.098, "title_min": 0.052,   # tamanho do título (fração da largura)
    "body": 0.034, "button": 0.033, "contact": 0.023,
    "radius": 0.022,            # cantos do botão
    "light_bg": "#F6F4EF",      # fundo das telas de conteúdo
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for nm in WEIGHTS.get(weight, WEIGHTS["regular"]):
        for d in FONT_DIRS:
            for ext in (".ttf", ".otf"):
                p = os.path.join(d, nm + ext)
                if os.path.exists(p):
                    return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _rgb(hex_: str, default=(30, 30, 30)) -> Tuple[int, int, int]:
    h = (hex_ or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore
    except Exception:
        return default


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(rgb[:3])


def _lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b) -> float:
    la, lb = sorted([_lum(a), _lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _ink_on(bg) -> Tuple[int, int, int]:
    return (255, 255, 255) if _contrast((255, 255, 255), bg) >= _contrast((20, 20, 24), bg) else (20, 20, 24)


def _pick_brand(colors: Dict[str, str]) -> Dict[str, Tuple[int, int, int]]:
    """Cor do bloco = a mais 'de marca' (saturada, não quase-branca/preta); botão = cor que contrasta com o bloco."""
    import colorsys
    vals = [_rgb(v) for k, v in (colors or {}).items() if isinstance(v, str) and v.startswith("#")]
    vals = vals or [(30, 64, 175)]

    def score(c):
        h, l, s = colorsys.rgb_to_hls(*[x / 255 for x in c])
        return s * (1 - abs(l - 0.45) * 1.4)
    block = max(vals, key=score)
    others = [c for c in vals if c != block]
    btn = max(others, key=lambda c: _contrast(c, block)) if others else _ink_on(block)
    if _contrast(btn, block) < 2.2:
        btn = _ink_on(block)
    return {"block": block, "button": btn, "on_block": _ink_on(block), "on_button": _ink_on(btn)}


def _wrap(draw, text: str, font, max_w: int) -> List[str]:
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


def _fit(draw, text: str, weight: str, max_w: int, max_h: int, size_max: int, size_min: int, lh: float = 1.12):
    size = size_max
    while True:
        f = _font(weight, size)
        lines = _wrap(draw, text, f, max_w)
        h = int(len(lines) * size * lh)
        if (h <= max_h and all(draw.textlength(l, font=f) <= max_w for l in lines)) or size <= size_min:
            return f, size, lines, h
        size = max(size_min, int(size * 0.94))


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Recorta/estica a foto para (w,h) mantendo proporção (LANCZOS + nitidez leve — upscale sem IA)."""
    im = ImageOps.fit(img.convert("RGB"), (w, h), method=Image.LANCZOS, centering=(0.5, 0.42))
    if max(w / max(1, img.width), h / max(1, img.height)) > 1.2:
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    return im


def _logo_fit(path: str, max_w: int, max_h: int) -> Optional[Image.Image]:
    try:
        lg = Image.open(path).convert("RGBA")
    except Exception:
        return None
    bbox = lg.getbbox()
    if bbox:
        lg = lg.crop(bbox)
    r = min(max_w / lg.width, max_h / lg.height)
    return lg.resize((max(1, int(lg.width * r)), max(1, int(lg.height * r))), Image.LANCZOS)


def _logo_lum(lg: Image.Image) -> Optional[float]:
    px = [p for p in lg.resize((60, 60)).getdata() if p[3] > 160]
    if not px:
        return None
    return sum(_lum(p) for p in px) / len(px)


def pick_logo(logo_paths: List[str], bg) -> Optional[str]:
    """Escolhe a versão da logo que mais contrasta com o fundo (logos com fundo próprio também valem)."""
    best, best_c = None, -1.0
    bl = _lum(bg)
    for p in logo_paths or []:
        try:
            lg = Image.open(p).convert("RGBA")
        except Exception:
            continue
        has_alpha = lg.getextrema()[3][0] < 250
        L = _logo_lum(lg) if has_alpha else None
        c = 3.0 if L is None else (max(L, bl) + 0.05) / (min(L, bl) + 0.05)
        if c > best_c:
            best, best_c = p, c
    return best


class Canvas:
    def __init__(self, w: int, h: int, bg):
        self.w, self.h = w, h
        self.im = Image.new("RGB", (w, h), bg)
        self.d = ImageDraw.Draw(self.im)
        self.layers: List[Dict[str, Any]] = [{"kind": "rect", "name": "fundo", "x": 0, "y": 0, "w": w, "h": h, "fill": _hex(bg)}]

    def photo(self, img: Image.Image, x, y, w, h, name="foto"):
        ph = _cover(img, w, h)
        self.im.paste(ph, (x, y))
        buf = io.BytesIO(); ph.save(buf, "JPEG", quality=94)
        self.layers.append({"kind": "image", "name": name, "x": x, "y": y, "w": w, "h": h, "data": buf.getvalue(), "mime": "image/jpeg"})

    def rect(self, x, y, w, h, fill, radius=0, name="bloco"):
        if radius:
            self.d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)
        else:
            self.d.rectangle([x, y, x + w, y + h], fill=fill)
        self.layers.append({"kind": "rect", "name": name, "x": x, "y": y, "w": w, "h": h, "fill": _hex(fill), "radius": radius})

    def text(self, lines, font, size, x, y, color, lh=1.12, name="texto", weight="regular"):
        yy = y
        for ln in lines:
            self.d.text((x, yy), ln, font=font, fill=color)
            yy += int(size * lh)
        self.layers.append({"kind": "text", "name": name, "x": x, "y": y, "w": int(max((self.d.textlength(l, font=font) for l in lines), default=0)) + 4,
                            "h": yy - y, "text": "\n".join(lines), "size": size, "color": _hex(color), "weight": weight,
                            "font": FONT_FAMILY, "line_height": lh})
        return yy

    def logo(self, path, x, y, max_w, max_h, anchor="left", name="logo"):
        lg = _logo_fit(path, max_w, max_h)
        if not lg:
            return
        px = x if anchor == "left" else x - lg.width
        self.im.paste(lg, (px, y), lg)
        buf = io.BytesIO(); lg.save(buf, "PNG")
        self.layers.append({"kind": "image", "name": name, "x": px, "y": y, "w": lg.width, "h": lg.height, "data": buf.getvalue(), "mime": "image/png"})

    def png(self) -> bytes:
        buf = io.BytesIO(); self.im.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def _button(cv: Canvas, label: str, x: int, y: int, fill, ink, W: int, tok: Dict[str, Any]) -> int:
    size = int(W * tok["button"]); f = _font("semibold", size)
    tw = int(cv.d.textlength(label, font=f)); padx, pady = int(size * 1.1), int(size * 0.72)
    bw, bh = tw + 2 * padx, size + 2 * pady
    cv.rect(x, y, bw, bh, fill, radius=int(W * tok["radius"]), name="botão")
    cv.text([label], f, size, x + padx, y + pady - int(size * 0.12), ink, name="texto do botão", weight="semibold")
    return y + bh


def _app_row(cv: "Canvas", groups: List[List[str]], x: int, y: int, bg, W: int, max_w: int) -> int:
    """Linha com as LOGOS OFICIAIS dos apps citados (versão que contrasta com o fundo). Devolve o novo y."""
    h = int(W * 0.052); gap = int(W * 0.035); cx = x
    placed = False
    for grp in groups or []:
        p = pick_logo(list(grp or []), bg)
        if not p:
            continue
        lg = _logo_fit(p, int(W * 0.26), h)
        if not lg or cx + lg.width > x + max_w:
            continue
        cv.logo(p, cx, y + (h - lg.height) // 2, int(W * 0.26), h, name="logo do app")
        cx += lg.width + gap; placed = True
    return (y + h + int(W * 0.035)) if placed else y


def compose(slide: Dict[str, Any], photo: Optional[Image.Image], colors: Dict[str, str], logo_paths: List[str],
            fmt: str = "post", role: str = "cover", contact: str = "", tokens: Optional[Dict[str, Any]] = None,
            app_logo_groups: Optional[List[List[str]]] = None) -> Tuple[bytes, List[Dict[str, Any]]]:
    """role: cover | content | cta. Layouts: foto+bloco (capa/post), conteúdo claro com foto em card, CTA em bloco."""
    tok = dict(DEFAULTS, **(tokens or {}))
    W, H = SIZES.get("story" if fmt == "story" else "post")
    pal = _pick_brand(colors)
    M = int(W * tok["margin"])
    title = (slide.get("title") or "").strip()
    body = (slide.get("body") or slide.get("subtitle") or "").strip()
    cta = (slide.get("cta") or "").strip()
    eyebrow = (slide.get("eyebrow") or "").strip()

    if role == "content":
        bg = _rgb(tok["light_bg"]); ink = (24, 24, 28)
        cv = Canvas(W, H, bg)
        y = M
        lp = pick_logo(logo_paths, bg)
        if lp:
            cv.logo(lp, M, y, int(W * 0.24), int(W * 0.075))
        y += int(W * 0.13)
        if eyebrow:
            f = _font("semibold", int(W * 0.022))
            y = cv.text([eyebrow.upper()], f, int(W * 0.022), M, y, pal["block"], name="chamada", weight="semibold") + int(W * 0.02)
        tf, ts, tl, th = _fit(cv.d, title, "semibold", W - 2 * M, int(H * 0.22), int(W * tok["title_max"] * 0.85), int(W * tok["title_min"]))
        y = cv.text(tl, tf, ts, M, y, ink, name="título", weight="semibold") + int(W * 0.03)
        if body:
            bf, bs, bl, bh = _fit(cv.d, body, "regular", W - 2 * M, int(H * 0.26), int(W * tok["body"]), int(W * 0.024), lh=1.38)
            y = cv.text(bl, bf, bs, M, y, (70, 70, 78), lh=1.38, name="texto", weight="regular") + int(W * 0.05)
        y = _app_row(cv, app_logo_groups, M, y, bg, W, W - 2 * M)
        if photo is not None:
            ph_h = H - M - y
            if ph_h > H * 0.2:
                cv.photo(photo, M, y, W - 2 * M, ph_h)
        return cv.png(), cv.layers

    if role == "cta":
        bg = pal["block"]; ink = pal["on_block"]
        cv = Canvas(W, H, bg)
        y = int(H * 0.16)
        lp = pick_logo(logo_paths, bg)
        if lp:
            cv.logo(lp, M, M, int(W * 0.34), int(W * 0.12))
        tf, ts, tl, th = _fit(cv.d, title, "semibold", W - 2 * M, int(H * 0.32), int(W * tok["title_max"] * 1.12), int(W * tok["title_min"]))
        bf = bs = bl = None; bh = 0
        if body:
            bf, bs, bl, bh = _fit(cv.d, body, "regular", W - 2 * M, int(H * 0.2), int(W * tok["body"] * 1.1), int(W * 0.026), lh=1.38)
        btn_h = int(W * tok["button"] * 1.15 * 2.45) if cta else 0
        group = th + int(W * 0.04) + bh + (int(W * 0.06) if bh else 0) + btn_h
        y = max(int(H * 0.22), (H - group) // 2)          # centraliza o bloco de texto na vertical
        y = cv.text(tl, tf, ts, M, y, ink, name="título", weight="semibold") + int(W * 0.04)
        if bl:
            y = cv.text(bl, bf, bs, M, y, ink, lh=1.38, name="texto", weight="regular") + int(W * 0.06)
        y = _app_row(cv, app_logo_groups, M, y, bg, W, W - 2 * M)
        if cta:
            y = _button(cv, cta, M, y, pal["button"], pal["on_button"], W, dict(tok, button=tok["button"] * 1.15)) + int(W * 0.04)
        if contact:
            cs = int(W * tok["contact"]); cf = _font("medium", cs)
            cl = _wrap(cv.d, contact, cf, W - 2 * M)
            cv.text(cl, cf, cs, M, H - M - int(len(cl) * cs * 1.3), ink, lh=1.3, name="contato", weight="medium")
        return cv.png(), cv.layers

    # role == cover (capa de carrossel / post único / story): foto em cima + bloco chapado da marca embaixo
    block = pal["block"]; ink = pal["on_block"]
    cv = Canvas(W, H, block)
    ph_h = int(H * tok["photo_ratio"]) if photo is not None else 0
    if photo is not None:
        cv.photo(photo, 0, 0, W, ph_h)
    cv.rect(0, ph_h, W, H - ph_h, block, name="bloco da marca")
    y = ph_h + int(W * 0.07)
    reserve = int(W * 0.22) if cta else int(W * 0.08)
    if contact:
        reserve += int(W * 0.05)
    avail = H - y - M - reserve
    tf, ts, tl, th = _fit(cv.d, title, "semibold", int(W * 0.84), int(avail * (0.66 if body else 1)), int(W * tok["title_max"]), int(W * tok["title_min"]))
    y = cv.text(tl, tf, ts, M, y, ink, name="título", weight="semibold") + int(W * 0.025)
    if body:
        bf, bs, bl, bh = _fit(cv.d, body, "regular", int(W * 0.72), max(int(W * 0.06), H - y - M - reserve), int(W * tok["body"]), int(W * 0.022), lh=1.38)
        y = cv.text(bl, bf, bs, M, y, ink, lh=1.38, name="texto", weight="regular") + int(W * 0.045)
    y = _app_row(cv, app_logo_groups, M, y, block, W, int(W * 0.62))
    by = y
    if cta:
        by = _button(cv, cta, M, y, pal["button"], pal["on_button"], W, tok)
    lp = pick_logo(logo_paths, block)
    if lp:
        lw, lh_ = int(W * 0.22), int(W * 0.085)
        cv.logo(lp, W - M, (by - lh_) if cta else (H - M - lh_ - (int(W * 0.05) if contact else 0)), lw, lh_, anchor="right")
    if contact:
        cs = int(W * tok["contact"]); cf = _font("medium", cs)
        cl = _wrap(cv.d, contact, cf, W - 2 * M)[:1]
        cv.text(cl, cf, cs, M, H - M - cs, ink, name="contato", weight="medium")
    return cv.png(), cv.layers
