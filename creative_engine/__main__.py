"""CLI:  python __main__.py <input.png> --config blocks.json --seed 42 -o out.png [--debug] [--mock right]"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # roda de qualquer cwd

from PIL import Image

from compose import compose_creative, debug_overlay
from treatments import list_treatments


def main():
    ap = argparse.ArgumentParser(description="Motor de composição de criativos (CARIAP).")
    ap.add_argument("input", help="imagem de entrada (PNG/JPG)")
    ap.add_argument("--config", help="JSON com blocks + art_config", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("-o", "--out", default="out.png")
    ap.add_argument("--debug", action="store_true", help="salva *_debug.png com mapa de proteção + zonas")
    ap.add_argument("--mock", default=None, help="right|left|center|corner|two (sem YOLO/MediaPipe)")
    ap.add_argument("--treatment", default=None, help="força um tratamento: " + ", ".join(list_treatments()))
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGB")
    cfg, blocks = {}, [{"text": "Título de exemplo", "role": "titulo", "max_font_size": 96},
                       {"text": "Fale com a CARIAP", "role": "cta", "max_font_size": 44}]
    if args.config:
        data = json.load(open(args.config, encoding="utf-8"))
        blocks = data.get("blocks", blocks)
        cfg = data.get("art_config", {})
    if args.treatment:
        cfg["treatment"] = args.treatment

    out, meta = compose_creative(img, blocks, cfg, args.seed, args.mock)
    out.save(args.out)
    print("OK ->", args.out, "| tratamento:", meta["treatment"], "| silhueta:", meta["has_silhouette"])
    print("regiões protegidas:", [(r["kind"], r["box"]) for r in meta["regions"]])
    if args.debug:
        dbg = args.out.rsplit(".", 1)[0] + "_debug.png"
        debug_overlay(img, cfg, args.mock).save(dbg)
        print("debug ->", dbg)


if __name__ == "__main__":
    sys.exit(main())
