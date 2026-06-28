from __future__ import annotations

import argparse
import json
import sys

from PIL import Image

from .compose import compose_creative, debug_overlay
from .treatments import list_treatments


def main() -> int:
    parser = argparse.ArgumentParser(description="Caripost protection-aware creative composer")
    parser.add_argument("input", help="input PNG/JPG")
    parser.add_argument("--config", required=True, help="JSON with blocks and optional art_config")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("-o", "--out", default="out.png")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--mock", default=None, help="right|left|center|corner|two")
    parser.add_argument("--treatment", choices=list_treatments(), default=None)
    args = parser.parse_args()

    payload = json.load(open(args.config, encoding="utf-8"))
    blocks = payload.get("blocks") or []
    if not blocks:
        raise SystemExit("config precisa conter blocks[]")
    art_config = dict(payload.get("art_config") or {})
    if args.treatment:
        art_config["treatment"] = args.treatment
    image = Image.open(args.input).convert("RGB")
    out, meta = compose_creative(image, blocks, art_config, args.seed, mock=args.mock)
    out.save(args.out)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if args.debug:
        dbg = args.out.rsplit(".", 1)[0] + "_debug.png"
        debug_overlay(image, art_config, mock=args.mock).save(dbg)
        print("debug:", dbg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
