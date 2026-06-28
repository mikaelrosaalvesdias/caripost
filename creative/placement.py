"""Protection-aware placement using Maximal Empty Rectangle.

This module is dependency-light on purpose. Detection can be expensive, but once
regions are known, finding safe text zones should be deterministic and fast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

Box = tuple[int, int, int, int]

GRID_SCALE = 6
DEFAULT_PADDING = 28
FACE_PADDING = 48
HAND_PADDING = 34
OBJECT_PADDING = 24
MIN_ZONE_W = 180
MIN_ZONE_H = 110


@dataclass
class Block:
    text: str
    role: str = "titulo"
    font_path: Optional[str] = None
    max_font_size: int = 96
    min_font_size: int = 18
    color: str = "#FFFFFF"


@dataclass
class Detection:
    box: Box
    kind: str
    confidence: float = 1.0


@dataclass
class Placement:
    role: str
    zone: Box
    font_size: int
    lines: list[str] = field(default_factory=list)


@dataclass
class ProtectionMap:
    w: int
    h: int
    regions: list[Detection] = field(default_factory=list)
    silhouette: Optional[np.ndarray] = None

    def forbidden_mask(self, extra_regions: Optional[list[Detection]] = None) -> np.ndarray:
        return build_forbidden_mask(self.w, self.h, self.regions + list(extra_regions or []))


def _padding(kind: str) -> int:
    if kind == "face":
        return FACE_PADDING
    if kind == "hand":
        return HAND_PADDING
    if kind == "object":
        return OBJECT_PADDING
    return DEFAULT_PADDING


def clamp_box(box: Box, w: int, h: int, padding: int = 0) -> Box:
    x, y, bw, bh = box
    x0 = max(0, x - padding)
    y0 = max(0, y - padding)
    x1 = min(w, x + bw + padding)
    y1 = min(h, y + bh + padding)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def build_forbidden_mask(w: int, h: int, regions: list[Detection]) -> np.ndarray:
    mask = np.zeros((h, w), dtype=bool)
    for det in regions:
        x, y, bw, bh = clamp_box(det.box, w, h, _padding(det.kind))
        if bw > 0 and bh > 0:
            mask[y:y + bh, x:x + bw] = True
    return mask


def _downsample_forbidden(forbidden: np.ndarray, scale: int) -> np.ndarray:
    h, w = forbidden.shape
    gh = (h + scale - 1) // scale
    gw = (w + scale - 1) // scale
    pad_h = gh * scale - h
    pad_w = gw * scale - w
    padded = np.pad(forbidden, ((0, pad_h), (0, pad_w)), constant_values=True)
    return padded.reshape(gh, scale, gw, scale).max(axis=(1, 3))


def largest_empty_rect(
    forbidden: np.ndarray,
    margin: int = 48,
    min_w: int = MIN_ZONE_W,
    min_h: int = MIN_ZONE_H,
    grid_scale: int = GRID_SCALE,
) -> Optional[Box]:
    """Return the largest 100% free rectangle using histogram + stack.

    The search happens on a block-max downsampled mask, so a free cell means the
    whole high-res block is free. This keeps the returned rectangle conservative.
    """
    h, w = forbidden.shape
    s = max(1, int(grid_scale))
    blocked = _downsample_forbidden(forbidden, s)
    gh, gw = blocked.shape
    free = ~blocked
    m = max(1, margin // s)
    if gh <= 2 * m or gw <= 2 * m:
        return None
    free[:m, :] = False
    free[gh - m:, :] = False
    free[:, :m] = False
    free[:, gw - m:] = False

    best = (0, 0, 0, 0, 0)
    heights = [0] * gw
    for y in range(gh):
        row = free[y]
        for x in range(gw):
            heights[x] = heights[x] + 1 if row[x] else 0
        stack: list[tuple[int, int]] = []
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
    if area <= 0:
        return None
    x, y, bw, bh = gx * s, gy * s, min(gbw * s, w - gx * s), min(gbh * s, h - gy * s)
    if bw < min_w or bh < min_h:
        return None
    return x, y, bw, bh


def top_n_rects(
    forbidden: np.ndarray,
    margin: int = 48,
    n: int = 3,
    min_w: int = MIN_ZONE_W,
    min_h: int = MIN_ZONE_H,
    spacing: int = 18,
) -> list[Box]:
    work = forbidden.copy()
    out: list[Box] = []
    for _ in range(max(1, n)):
        rect = largest_empty_rect(work, margin, min_w, min_h)
        if not rect:
            break
        out.append(rect)
        x, y, bw, bh = clamp_box(rect, work.shape[1], work.shape[0], spacing)
        work[y:y + bh, x:x + bw] = True
    return out


def free_fraction(zone: Box, forbidden: np.ndarray) -> float:
    x, y, bw, bh = clamp_box(zone, forbidden.shape[1], forbidden.shape[0])
    if bw <= 0 or bh <= 0:
        return 0.0
    roi = forbidden[y:y + bh, x:x + bw]
    return 1.0 - float(roi.mean()) if roi.size else 0.0


def intersects_forbidden(zone: Box, forbidden: np.ndarray) -> bool:
    x, y, bw, bh = clamp_box(zone, forbidden.shape[1], forbidden.shape[0])
    if bw <= 0 or bh <= 0:
        return True
    return bool(forbidden[y:y + bh, x:x + bw].any())


def fallback_band(w: int, h: int, forbidden: np.ndarray, margin: int = 48) -> Box:
    strip = int(h * 0.16)
    cands = [
        (margin, h - margin - strip, w - 2 * margin, strip),
        (margin, margin, w - 2 * margin, strip),
        (margin, (h - strip) // 2, w - 2 * margin, strip),
    ]
    return max(cands, key=lambda b: free_fraction(b, forbidden))
