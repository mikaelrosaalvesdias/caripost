from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

from .compose import compose_creative, debug_overlay
from .detect import mock_protection_map
from .placement import intersects_forbidden, top_n_rects

SCENARIOS = ("right", "left", "center", "corner", "two")


def _bg(w=1080, h=1350, scenario="right"):
    yy, xx = np.mgrid[0:h, 0:w]
    arr = np.dstack([
        (28 + 70 * xx / w).astype(np.uint8),
        (22 + 55 * yy / h).astype(np.uint8),
        (50 + 70 * (xx + yy) / (w + h)).astype(np.uint8),
    ])
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)

    def person(cx, cw, y0=0.16, y1=0.98):
        d.ellipse([w * (cx + cw * 0.24), h * (y0 + 0.02), w * (cx + cw * 0.72), h * (y0 + 0.22)], fill=(214, 180, 145))
        d.rectangle([w * cx, h * (y0 + 0.22), w * (cx + cw), h * y1], fill=(130, 105, 92))

    if scenario == "left":
        person(0.04, 0.44)
    elif scenario == "center":
        person(0.30, 0.40)
    elif scenario == "corner":
        person(0.56, 0.40, 0.44, 0.98)
    elif scenario == "two":
        person(0.02, 0.30)
        person(0.66, 0.30)
    else:
        person(0.52, 0.44)
    return img


def main() -> int:
    outdir = os.environ.get("CREATIVE_TEST_OUT", "/tmp/caripost-creative-tests")
    os.makedirs(outdir, exist_ok=True)
    blocks = [
        {"text": "Distribua SVAs e fature mais com sua ISP", "role": "titulo", "max_font_size": 96},
        {"text": "Fale com a CARIAP hoje", "role": "cta", "max_font_size": 44},
    ]
    ok = True
    for scenario in SCENARIOS:
        img = _bg(scenario=scenario)
        pmap = mock_protection_map(img, scenario)
        forbidden = pmap.forbidden_mask()
        zones = top_n_rects(forbidden, 48, len(blocks))
        safe = bool(zones) and all(not intersects_forbidden(z, forbidden) for z in zones)
        for treatment in ("column_glass", "column_solid", "scrim_float", "big_type_bleed", "behind_subject", "contour_silhouette", "cut_band"):
            rendered, meta = compose_creative(img, blocks, {"treatment": treatment, "accent": "#ED5E1F"}, seed=42, pmap=pmap)
            rendered.save(os.path.join(outdir, f"{scenario}_{treatment}.png"))
            ok = ok and safe and all(not intersects_forbidden(tuple(p["zone"]), forbidden) for p in meta["placements"] if treatment != "behind_subject")
        debug_overlay(img, {"margin": 48}, pmap=pmap).save(os.path.join(outdir, f"{scenario}_debug.png"))
        print(f"{scenario}: zones={zones} safe={safe}")
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
