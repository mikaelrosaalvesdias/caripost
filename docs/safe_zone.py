"""
safe_zone.py — Posicionamento determinístico de texto em SAFE ZONES (maximal rectangle 2D).

Em cima do esqueleto do user, com o fix que importa pra Caripost:
o achador de zona é o MAIOR RETÂNGULO VAZIO da máscara proibida (não faixa horizontal),
então funciona pro caso real "personagem/influencer num lado, texto no lado livre".

A IA gera SÓ a imagem. Este módulo NÃO chama IA: detecções entram prontas (mock aqui;
no real = YOLO11n 'person'+objetos COCO + MediaPipe Face/Hand). REGRA: o box 'person' do
YOLO é a zona proibida PRIMÁRIA (corpo inteiro) — rosto/mão só refinam. Assim, rosto
missado não vira texto na cara.

INTEGRAÇÃO CARIPOST: use place_zones() que devolve só as ZONAS [x,y,w,h]; o compositor
da Caripost (card de vidro/sólido, logo, rodapé, fonte Poppins) desenha o texto NELAS.
render() aqui é só pra demo/standalone.

Deps: pillow, numpy.   Rodar: python docs/safe_zone.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Box = tuple[int, int, int, int]  # (x, y, w, h) px

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
MIN_ZONE_W, MIN_ZONE_H = 200, 130   # zona menor que isso → fallback banda
GRID_SCALE = 6                       # downscale da máscara p/ o maximal-rect (perf)


@dataclass
class Block:
    text: str
    role: str = "titulo"
    font_path: Optional[str] = None
    max_font_size: int = 96
    min_font_size: int = 18
    color: str = "#FFFFFF"
    preferred: Optional[str] = None
    scrim: bool = True


@dataclass
class Detection:
    box: Box
    kind: str           # person | face | hand | object | salient
    confidence: float = 1.0


@dataclass
class Placement:
    role: str
    zone: Box
    font_size: int
    lines: list[str]


_ROLE_PRIORITY = {"titulo": 0, "subtitulo": 1, "cta": 2}


def build_forbidden_mask(w: int, h: int, dets: list[Detection], padding: int = 24) -> np.ndarray:
    mask = np.zeros((h, w), dtype=bool)
    for d in dets:
        bx, by, bw, bh = d.box
        x0, y0 = max(0, bx - padding), max(0, by - padding)
        x1, y1 = min(w, bx + bw + padding), min(h, by + bh + padding)
        mask[y0:y1, x0:x1] = True
    return mask


def largest_free_rect(forbidden: np.ndarray, margin: int) -> Optional[Box]:
    """MAIOR retângulo 100% livre dentro das margens (maximal rectangle, histograma+pilha).
    Acha coluna lateral, faixa ou canto — o que for maior. Roda em grid reduzido (perf)."""
    h, w = forbidden.shape
    s = GRID_SCALE
    free = ~forbidden[::s, ::s]
    gh, gw = free.shape
    m = max(1, margin // s)
    free[:m, :] = False; free[max(m, gh - m):, :] = False
    free[:, :m] = False; free[:, max(m, gw - m):] = False
    best = (0, 0, 0, 0, 0)  # area, x, y, w, h (grid)
    heights = [0] * gw
    for y in range(gh):
        row = free[y]
        for x in range(gw):
            heights[x] = heights[x] + 1 if row[x] else 0
        stack = []  # (start_x, height)
        for x in range(gw + 1):
            cur = heights[x] if x < gw else 0
            start = x
            while stack and stack[-1][1] >= cur:
                sx, sh = stack.pop()
                area = sh * (x - sx)
                if area > best[0]:
                    best = (area, sx, y - sh + 1, x - sx, sh)
                start = sx
            if not stack or stack[-1][1] < cur:
                stack.append((start, cur))
    area, gx, gy, gbw, gbh = best
    rect = (gx * s, gy * s, gbw * s, gbh * s)
    if rect[2] < MIN_ZONE_W or rect[3] < MIN_ZONE_H:
        return None
    return rect


def _cap_zone(zone: Box, h: int, max_frac: float = 0.5) -> Box:
    """Limita a altura da zona (uma coluna lateral inteira é alta demais p/ um bloco):
    centra o bloco verticalmente na zona, ocupando no máx. max_frac da imagem."""
    x, y, bw, bh = zone
    cap = int(h * max_frac)
    if bh > cap:
        y = y + (bh - cap) // 2
        bh = cap
    return (x, y, bw, bh)


def _free_fraction(zone: Box, forbidden: np.ndarray) -> float:
    x, y, bw, bh = zone
    r = forbidden[y:y + bh, x:x + bw]
    return 1.0 - float(r.mean()) if r.size else 0.0


def _fallback_band(w: int, h: int, margin: int, forbidden: np.ndarray) -> Box:
    strip = int(h * 0.16)
    cands = [
        (margin, h - margin - strip, w - 2 * margin, strip),
        (margin, margin, w - 2 * margin, strip),
    ]
    return max(cands, key=lambda b: _free_fraction(b, forbidden))


def mark_occupied(forbidden: np.ndarray, zone: Box) -> None:
    x, y, bw, bh = zone
    forbidden[y:y + bh, x:x + bw] = True


def place_zones(w: int, h: int, blocks: list[Block], dets: list[Detection],
                margin: int = 48, padding: int = 24) -> list[Box]:
    """API p/ integrar na Caripost: devolve a ZONA [x,y,w,h] de cada bloco (na ordem de prioridade).
    O compositor da Caripost desenha o texto/card branded NELA. NÃO renderiza nada aqui."""
    forbidden = build_forbidden_mask(w, h, dets, padding)
    zones: list[Box] = []
    for block in sorted(blocks, key=lambda b: _ROLE_PRIORITY.get(b.role, 9)):
        rect = largest_free_rect(forbidden, margin)
        zone = _cap_zone(rect, h) if rect else _fallback_band(w, h, margin, forbidden)
        zones.append(zone)
        mark_occupied(forbidden, zone)
    return zones


# ----- render (só demo standalone; na Caripost usa o composer de marca) ----- #
def _load_font(path, size):
    for p in ([path] if path else []) + _FONT_CANDIDATES:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def _line_h(font):
    bb = font.getbbox("Ájg")
    return int((bb[3] - bb[1]) * 1.2)


def fit_font(draw, block, zone):
    _, _, bw, bh = zone
    lo, hi = block.min_font_size, block.max_font_size
    best_size, best_lines = block.min_font_size, [block.text]
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(block.font_path, mid)
        lines = _wrap(draw, block.text, font, bw)
        if _line_h(font) * len(lines) <= bh and max((draw.textlength(l, font=font) for l in lines), default=0) <= bw:
            best_size, best_lines = mid, lines; lo = mid + 1
        else:
            hi = mid - 1
    return best_size, best_lines


def render(img, zones, blocks):
    base = img.convert("RGBA")
    ordered = sorted(blocks, key=lambda b: _ROLE_PRIORITY.get(b.role, 9))
    probe = ImageDraw.Draw(base)
    placements = []
    for block, zone in zip(ordered, zones):
        if block.scrim:
            ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
            x, y, bw, bh = zone
            ImageDraw.Draw(ov).rounded_rectangle([x, y, x + bw, y + bh], 24, fill=(0, 0, 0, 140))
            base.alpha_composite(ov)
        size, lines = fit_font(probe, block, zone)
        font = _load_font(block.font_path, size)
        x, y, bw, bh = zone; lh = _line_h(font); cy = y + (bh - lh * len(lines)) // 2
        d = ImageDraw.Draw(base)
        for ln in lines:
            d.text((x + 18, cy), ln, font=font, fill=block.color); cy += lh
        placements.append(Placement(block.role, zone, size, lines))
    return base.convert("RGB"), placements


# ----- MOCK: sujeito (person) à DIREITA + rosto + mão + celular (o caso real) ----- #
def get_mock_detections(w: int, h: int) -> list[Detection]:
    return [
        Detection((int(w * 0.50), int(h * 0.18), int(w * 0.46), int(h * 0.80)), "person"),   # PRIMÁRIO: corpo todo à direita
        Detection((int(w * 0.60), int(h * 0.20), int(w * 0.24), int(h * 0.22)), "face"),
        Detection((int(w * 0.55), int(h * 0.55), int(w * 0.14), int(h * 0.12)), "hand"),
        Detection((int(w * 0.52), int(h * 0.58), int(w * 0.10), int(h * 0.14)), "object"),    # celular
    ]


def _demo_bg(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    arr = np.dstack([(30 + 90 * xx / w).astype(np.uint8), (24 + 70 * yy / h).astype(np.uint8),
                     (60 + 70 * (xx + yy) / (w + h)).astype(np.uint8)])
    img = Image.fromarray(arr, "RGB"); d = ImageDraw.Draw(img)
    d.ellipse([w * 0.62, h * 0.20, w * 0.82, h * 0.42], fill=(205, 175, 150))   # "cabeça" à direita
    d.rectangle([w * 0.55, h * 0.42, w * 0.90, h * 0.98], fill=(150, 120, 100))  # "corpo"
    return img


def _debug(img, dets, zones, padding):
    base = img.convert("RGBA"); d = ImageDraw.Draw(base)
    for det in dets:
        x, y, bw, bh = det.box
        d.rectangle([x - padding, y - padding, x + bw + padding, y + bh + padding], outline=(255, 60, 60), width=4)
    for z in zones:
        x, y, bw, bh = z
        d.rectangle([x, y, x + bw, y + bh], outline=(40, 230, 120), width=5)
    return base.convert("RGB")


if __name__ == "__main__":
    W, H, MARGIN, PADDING = 1080, 1350, 48, 28
    image = _demo_bg(W, H)
    dets = get_mock_detections(W, H)
    blocks = [
        Block("Distribua SVAs e fature mais com sua ISP", "titulo", max_font_size=92, preferred="bottom"),
        Block("Fale com a CARIAP hoje", "cta", max_font_size=44),
    ]
    zones = place_zones(W, H, blocks, dets, MARGIN, PADDING)
    composed, placements = render(image, zones, blocks)
    composed.save("/opt/caripost/uploads/_preview/sz_composed.png")
    _debug(image, dets, zones, PADDING).save("/opt/caripost/uploads/_preview/sz_debug.png")
    forbidden = build_forbidden_mask(W, H, dets, PADDING)
    print("zonas:", zones)
    for z in zones:
        print("  livre na zona:", round(_free_fraction(z, forbidden) * 100, 1), "%  (100% = nada proibido)")
