"""
placement.py — CONFIABILIDADE: Maximal Empty Rectangle.

Acha o(s) MAIOR(es) retângulo(s) 100% livre(s) na máscara de proteção, em QUALQUER
posição (sujeito à direita→texto à esquerda, esquerda, centro, canto, 2 sujeitos).
NÃO usa faixa horizontal full-width (falha quando o sujeito está num lado).

Algoritmo: maximal rectangle de células livres (histograma por linha + pilha), O(W·H),
rodado num grid reduzido (GRID_SCALE) pra ficar < ~2-3s em CPU mesmo em 1080x1920.

Sem deps pesadas: numpy + pillow. As detecções entram prontas (do detect.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

Box = tuple[int, int, int, int]  # (x, y, w, h) px

# ---- tuning ---- #
GRID_SCALE = 6          # downscale da máscara p/ o maximal-rect (perf vs precisão)
DEFAULT_PADDING = 26    # respiro em volta de cada região proibida
FACE_PADDING = 40       # rosto = respiro MAIOR (proibição absoluta)
MIN_ZONE_W, MIN_ZONE_H = 190, 120


@dataclass
class Detection:
    box: Box
    kind: str            # person | face | hand | object | salient
    confidence: float = 1.0


@dataclass
class ProtectionMap:
    w: int
    h: int
    regions: list[Detection] = field(default_factory=list)
    silhouette: Optional[np.ndarray] = None   # máscara bool da pessoa (p/ tratamentos)

    def forbidden_mask(self) -> np.ndarray:
        """Une as regiões numa máscara bool (True=proibido) com padding por tipo.
        Rosto leva padding maior (zero tolerância)."""
        mask = np.zeros((self.h, self.w), dtype=bool)
        for d in self.regions:
            pad = FACE_PADDING if d.kind == "face" else DEFAULT_PADDING
            bx, by, bw, bh = d.box
            x0, y0 = max(0, bx - pad), max(0, by - pad)
            x1, y1 = min(self.w, bx + bw + pad), min(self.h, by + bh + pad)
            mask[y0:y1, x0:x1] = True
        return mask


def largest_empty_rect(forbidden: np.ndarray, margin: int) -> Optional[Box]:
    """MAIOR retângulo 100% livre dentro das margens (histograma + pilha)."""
    h, w = forbidden.shape
    s = GRID_SCALE
    gh, gw = h // s, w // s
    m = max(1, margin // s)
    if gh <= 2 * m or gw <= 2 * m:
        return None
    # block-MAX pooling: célula livre só se o bloco s×s INTEIRO está livre → o retângulo
    # devolvido é garantidamente 100% livre em resolução cheia (sem sliver proibido na borda).
    fb = forbidden[:gh * s, :gw * s].reshape(gh, s, gw, s).max(axis=(1, 3))
    free = ~fb
    free[:m, :] = False; free[gh - m:, :] = False
    free[:, :m] = False; free[:, gw - m:] = False
    best = (0, 0, 0, 0, 0)  # area, x, y, w, h (grid)
    heights = [0] * gw
    for y in range(gh):
        rowmask = free[y]
        for x in range(gw):
            heights[x] = heights[x] + 1 if rowmask[x] else 0
        stack: list[tuple[int, int]] = []   # (start_x, height)
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


def top_n_rects(forbidden: np.ndarray, margin: int, n: int = 3) -> list[Box]:
    """Os N maiores retângulos livres NÃO sobrepostos (greedy: acha o maior, ocupa, repete).
    Alimenta os tratamentos (título no maior, CTA no próximo, etc.)."""
    work = forbidden.copy()
    out: list[Box] = []
    for _ in range(n):
        r = largest_empty_rect(work, margin)
        if not r:
            break
        out.append(r)
        x, y, bw, bh = r
        work[y:y + bh, x:x + bw] = True
    return out


def fallback_band(w: int, h: int, margin: int, forbidden: np.ndarray) -> Box:
    """Sem retângulo bom → banda na faixa (base/topo/centro) MENOS ocupada (nunca na cara)."""
    strip = int(h * 0.16)
    cands = [
        (margin, h - margin - strip, w - 2 * margin, strip),
        (margin, margin, w - 2 * margin, strip),
        (margin, (h - strip) // 2, w - 2 * margin, strip),
    ]
    def freefrac(b):
        x, y, bw, bh = b
        r = forbidden[y:y + bh, x:x + bw]
        return 1.0 - float(r.mean()) if r.size else 0.0
    return max(cands, key=freefrac)


def free_fraction(zone: Box, forbidden: np.ndarray) -> float:
    x, y, bw, bh = zone
    r = forbidden[y:y + bh, x:x + bw]
    return 1.0 - float(r.mean()) if r.size else 0.0


def intersects_forbidden(zone: Box, forbidden: np.ndarray) -> bool:
    x, y, bw, bh = zone
    r = forbidden[y:y + bh, x:x + bw]
    return bool(r.any())
