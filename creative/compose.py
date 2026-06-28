"""Public API for the Caripost creative engine."""
from __future__ import annotations

import random
from typing import Optional

from PIL import Image, ImageDraw

from .detect import detect, mock_protection_map
from .placement import Detection, ProtectionMap, top_n_rects
from .treatments import TREATMENTS, pick_treatment, placements_as_dict


def compose_creative(
    image: Image.Image,
    blocks: list[dict],
    art_config: Optional[dict] = None,
    seed: Optional[int] = None,
    pmap: Optional[ProtectionMap] = None,
    mock: Optional[str] = None,
) -> tuple[Image.Image, dict]:
    cfg = dict(art_config or {})
    pmap = pmap or (mock_protection_map(image, mock) if mock else detect(image))
    name = pick_treatment(cfg, seed)
    rng = random.Random(seed)
    out, placements = TREATMENTS[name](image, blocks, pmap, rng, cfg)
    zones = top_n_rects(pmap.forbidden_mask(), int(cfg.get("margin", 48)), max(1, len(blocks)))
    metadata = {
        "treatment": name,
        "seed": seed,
        "zones": zones,
        "placements": placements_as_dict(placements),
        "regions": [{"box": d.box, "kind": d.kind, "confidence": round(d.confidence, 3)} for d in pmap.regions],
        "has_silhouette": pmap.silhouette is not None,
    }
    return out, metadata


def debug_overlay(
    image: Image.Image,
    art_config: Optional[dict] = None,
    pmap: Optional[ProtectionMap] = None,
    mock: Optional[str] = None,
    extra_regions: Optional[list[Detection]] = None,
) -> Image.Image:
    cfg = dict(art_config or {})
    pmap = pmap or (mock_protection_map(image, mock) if mock else detect(image))
    base = image.convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    for det in pmap.regions + list(extra_regions or []):
        x, y, w, h = det.box
        color = (255, 30, 40, 255) if det.kind == "face" else (255, 145, 30, 235)
        draw.rectangle([x, y, x + w, y + h], outline=color, width=4)
        draw.text((max(0, x), max(0, y - 18)), det.kind, fill=color)
    for zone in top_n_rects(pmap.forbidden_mask(extra_regions), int(cfg.get("margin", 48)), 5):
        x, y, w, h = zone
        draw.rectangle([x, y, x + w, y + h], outline=(40, 235, 120, 255), width=5)
    return base.convert("RGB")
