"""
Prova determinística (sem YOLO/MediaPipe): roda o placement nas 5 posições do sujeito
e VALIDA que toda zona escolhida é 100% livre (texto nunca na área proibida).
Também renderiza 1 tratamento por posição + overlay de debug.

    python test_positions.py
Saídas em ../uploads/_preview/ce_<scenario>.png e ce_<scenario>_debug.png
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compose import compose_creative, debug_overlay
from detect import mock_protection_map
from placement import top_n_rects, intersects_forbidden

OUT = "/opt/caripost/uploads/_preview"
os.makedirs(OUT, exist_ok=True)
SCEN = {"right": (0.50, 0.46), "left": (0.04, 0.46), "center": (0.30, 0.40),
        "corner": (0.55, 0.42), "two": None}


def bg(w, h, scen):
    yy, xx = np.mgrid[0:h, 0:w]
    arr = np.dstack([(28 + 80 * xx / w).astype(np.uint8), (22 + 60 * yy / h).astype(np.uint8),
                     (55 + 70 * (xx + yy) / (w + h)).astype(np.uint8)])
    img = Image.fromarray(arr, "RGB"); d = ImageDraw.Draw(img)

    def draw_person(cx, cw, ytop=0.16):
        d.ellipse([w * (cx + cw * 0.22), h * (ytop + 0.02), w * (cx + cw * 0.72), h * (ytop + 0.26)], fill=(205, 175, 150))
        d.rectangle([w * cx, h * (ytop + 0.24), w * (cx + cw), h * 0.99], fill=(150, 120, 100))
    if scen == "two":
        draw_person(0.02, 0.30); draw_person(0.66, 0.30)
    elif scen == "corner":
        draw_person(0.55, 0.42, 0.45)
    else:
        cx, cw = SCEN[scen]; draw_person(cx, cw)
    return img


def _overlap(z, b):
    zx, zy, zw, zh = z; bx, by, bw, bh = b
    return not (zx + zw <= bx or bx + bw <= zx or zy + zh <= by or by + bh <= zy)


blocks = [{"text": "Distribua SVAs e fature mais com sua ISP", "role": "titulo", "max_font_size": 96},
          {"text": "Fale com a CARIAP hoje", "role": "cta", "max_font_size": 44}]
cfg = {"accent": "#ED5E1F", "margin": 48, "treatment": "column_solid"}

ok_all = True
for scen in SCEN:
    img = bg(1080, 1350, scen)
    pmap = mock_protection_map(img, scen)
    forb = pmap.forbidden_mask()
    zones = top_n_rects(forb, cfg["margin"], len(blocks))
    safe = all(not intersects_forbidden(z, forb) for z in zones)
    faces = [r.box for r in pmap.regions if r.kind == "face"]
    face_clear = all(not any(_overlap(z, f) for f in faces) for z in zones)
    out, meta = compose_creative(img, blocks, cfg, seed=42, mock=scen)
    out.save(f"{OUT}/ce_{scen}.png")
    debug_overlay(img, cfg, scen).save(f"{OUT}/ce_{scen}_debug.png")
    print(f"[{scen:7}] zonas={len(zones)} | texto 100% fora do proibido? {safe} | fora do ROSTO? {face_clear} | trat={meta['treatment']}")
    ok_all = ok_all and safe and face_clear

print("\nRESULTADO:", "OK — em TODAS as posições o texto fica fora do proibido e do rosto" if ok_all else "FALHOU")
