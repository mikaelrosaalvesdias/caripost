"""
compose.py — API pública do motor: junta detect + placement + treatments.

    compose_creative(image, blocks, art_config=None, seed=None, mock=None) -> (PIL.Image, metadata)

- image: PIL.Image (4:5, 1:1 ou 9:16). A IA gera SÓ ela.
- blocks: [{text, role, font_path?, max_font_size?, color?}]
- art_config: {treatment?, accent?, margin?, font_path?} — escolha explícita do tratamento.
- seed: determinístico (mesmo input+seed -> mesmo output).
- mock: None=detecção real (YOLO/MediaPipe); "right"|"left"|"center"|"corner"|"two"=mock sem deps.
"""
from __future__ import annotations

import random
from typing import Optional

from PIL import Image, ImageDraw

from placement import top_n_rects
from treatments import TREATMENTS, pick_treatment
from detect import detect, mock_protection_map


def compose_creative(image: Image.Image, blocks: list[dict], art_config: Optional[dict] = None,
                     seed: Optional[int] = None, mock: Optional[str] = None):
    pmap = mock_protection_map(image, mock) if mock else detect(image)
    name = pick_treatment(art_config, seed)
    cfg = dict(art_config or {})
    out = TREATMENTS[name](image, blocks, pmap, random.Random(seed), cfg)
    meta = {
        "treatment": name,
        "regions": [{"kind": d.kind, "box": d.box, "conf": round(d.confidence, 2)} for d in pmap.regions],
        "has_silhouette": pmap.silhouette is not None,
        "zones": top_n_rects(pmap.forbidden_mask(), cfg.get("margin", 48), len(blocks)),
    }
    return out, meta


def debug_overlay(image: Image.Image, art_config: Optional[dict] = None, mock: Optional[str] = None) -> Image.Image:
    """Imagem com mapa de proteção (vermelho = proibido) + zonas escolhidas (verde)."""
    pmap = mock_protection_map(image, mock) if mock else detect(image)
    base = image.convert("RGBA"); d = ImageDraw.Draw(base)
    pad = {"face": 40}
    for det in pmap.regions:
        x, y, bw, bh = det.box
        p = pad.get(det.kind, 26)
        col = (255, 40, 40) if det.kind == "face" else (255, 140, 40)
        d.rectangle([x - p, y - p, x + bw + p, y + bh + p], outline=col, width=4)
        d.text((max(0, x - p), max(0, y - p - 16)), det.kind, fill=col)
    for z in top_n_rects(pmap.forbidden_mask(), (art_config or {}).get("margin", 48), 3):
        x, y, bw, bh = z
        d.rectangle([x, y, x + bw, y + bh], outline=(40, 230, 120), width=5)
    return base.convert("RGB")
