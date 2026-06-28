"""Deterministic identity-preserving person composition.

The image model may create the scene, but it must not redraw a registered
influencer. This module cuts the uploaded photo into a real RGBA person layer
and composites those original pixels over the generated scene.
"""
from __future__ import annotations

import io
import random
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter


_LOCK = threading.Lock()
_SELFIE = {"loaded": False, "model": None}


@dataclass
class IdentityComposite:
    image: Image.Image
    metadata: dict


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    sr, dr = img.width / img.height, w / h
    if sr > dr:
        nh, nw = h, int(h * sr)
    else:
        nw, nh = w, int(w / sr)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = int((nh - h) * 0.38)
    return img.crop((x, y, x + w, y + h))


def _selfie_model():
    if _SELFIE["loaded"]:
        return _SELFIE["model"]
    with _LOCK:
        if _SELFIE["loaded"]:
            return _SELFIE["model"]
        try:
            import mediapipe as mp

            _SELFIE["model"] = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
        except Exception:
            _SELFIE["model"] = None
        _SELFIE["loaded"] = True
        return _SELFIE["model"]


def _alpha_from_selfie(img: Image.Image) -> Optional[Image.Image]:
    model = _selfie_model()
    if model is None:
        return None
    try:
        rgb = img.convert("RGB")
        arr = np.asarray(rgb)
        seg = model.process(arr)
        raw = getattr(seg, "segmentation_mask", None)
        if raw is None:
            return None
        mask = (np.asarray(raw) * 255).clip(0, 255).astype("uint8")
        try:
            import cv2

            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.GaussianBlur(mask, (0, 0), 2.2)
        except Exception:
            pass
        return Image.fromarray(mask, "L").point(lambda v: 255 if v > 96 else int(v * 1.35))
    except Exception:
        return None


def _solid_alpha_fallback(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 245 and alpha.getbbox():
        return alpha
    # Conservative fallback: keep the full image. It preserves identity even if
    # the upload has no clean background, and the detector still protects it.
    return Image.new("L", rgba.size, 255)


def person_cutout(person_bytes: bytes) -> tuple[Image.Image, dict]:
    src = Image.open(io.BytesIO(person_bytes)).convert("RGBA")
    original_alpha = src.getchannel("A")
    selfie_alpha = _alpha_from_selfie(src)
    if original_alpha.getextrema()[0] < 245 and original_alpha.getbbox():
        alpha = Image.composite(original_alpha, selfie_alpha or original_alpha, original_alpha)
        method = "uploaded-alpha"
    elif selfie_alpha is not None and selfie_alpha.getbbox():
        alpha = selfie_alpha
        method = "mediapipe-selfie"
    else:
        alpha = _solid_alpha_fallback(src)
        method = "full-photo-fallback"

    alpha = alpha.filter(ImageFilter.GaussianBlur(1.0))
    out = src.copy()
    out.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        pad = max(8, int(min(src.size) * 0.025))
        x0 = max(0, bbox[0] - pad)
        y0 = max(0, bbox[1] - pad)
        x1 = min(src.width, bbox[2] + pad)
        y1 = min(src.height, bbox[3] + pad)
        out = out.crop((x0, y0, x1, y1))
    return out, {"method": method, "source_size": src.size, "cutout_size": out.size}


def compose_identity_cutout(
    scene_bytes: bytes,
    person_bytes: bytes,
    canvas_size: tuple[int, int] = (1080, 1350),
    side: str = "auto",
    seed: Optional[int] = None,
) -> tuple[bytes, dict]:
    """Paste the registered person over a people-free scene using original pixels."""
    w, h = canvas_size
    bg = _cover(Image.open(io.BytesIO(scene_bytes)).convert("RGB"), w, h).convert("RGBA")
    cutout, meta = person_cutout(person_bytes)
    rng = random.Random(seed)
    side = side if side in ("left", "right") else rng.choice(("left", "right"))

    max_h = int(h * (0.72 if h <= 1400 else 0.66))
    max_w = int(w * 0.46)
    scale = min(max_h / max(1, cutout.height), max_w / max(1, cutout.width))
    scale = max(0.15, min(scale, 1.35))
    nw, nh = max(1, int(cutout.width * scale)), max(1, int(cutout.height * scale))
    cutout = cutout.resize((nw, nh), Image.LANCZOS)

    margin_x = int(w * 0.055)
    bottom = int(h * 0.02)
    x = margin_x if side == "left" else w - margin_x - nw
    y = h - bottom - nh
    if y < int(h * 0.12):
        y = int(h * 0.12)

    alpha = cutout.getchannel("A")
    shadow = Image.new("RGBA", cutout.size, (0, 0, 0, 160))
    shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(14)))
    bg.alpha_composite(shadow, (x + int(w * 0.012), y + int(h * 0.012)))
    bg.alpha_composite(cutout, (x, y))

    out = io.BytesIO()
    bg.convert("RGB").save(out, "PNG")
    meta.update({
        "identity_composite": "deterministic_cutout",
        "person_box": (x, y, nw, nh),
        "person_side": side,
        "canvas_size": (w, h),
    })
    return out.getvalue(), meta
