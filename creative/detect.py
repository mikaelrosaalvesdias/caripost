"""Detection layer for the Caripost creative engine.

Models are loaded lazily and kept as process singletons. The detector combines:
- YOLO11n-seg for person/object boxes and person silhouette.
- MediaPipe FaceDetection for hard face boxes.
- MediaPipe Hands for hand boxes from 21 landmarks.
- MediaPipe SelfieSegmentation as a silhouette fallback.
"""
from __future__ import annotations

import os
import threading

import numpy as np
from PIL import Image

from .placement import Detection, ProtectionMap

OBJECT_CLASSES = {
    "cell phone", "bottle", "cup", "book", "laptop", "handbag", "tv",
    "remote", "keyboard", "mouse", "wine glass", "backpack", "sports ball",
}
CONF_PERSON = 0.32
CONF_OBJECT = 0.38
CONF_FACE = 0.45

_LOCK = threading.Lock()
_MODELS = {"loaded": False, "yolo": None, "face": None, "hands": None, "selfie": None}


def _ensure_models() -> None:
    if _MODELS["loaded"]:
        return
    with _LOCK:
        if _MODELS["loaded"]:
            return
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise ImportError("ultralytics ausente. Instale ultralytics para ativar detecção real.") from exc

        weights = os.environ.get("YOLO_WEIGHTS", "yolo11n-seg.pt")
        _MODELS["yolo"] = YOLO(weights)

        try:
            import mediapipe as mp

            _MODELS["face"] = mp.solutions.face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=CONF_FACE,
            )
            _MODELS["hands"] = mp.solutions.hands.Hands(
                static_image_mode=True,
                max_num_hands=6,
                min_detection_confidence=0.42,
            )
            _MODELS["selfie"] = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)
        except Exception:
            _MODELS["face"] = None
            _MODELS["hands"] = None
            _MODELS["selfie"] = None

        _MODELS["loaded"] = True


def detect(image: Image.Image) -> ProtectionMap:
    _ensure_models()
    img = image.convert("RGB")
    w, h = img.size
    arr = np.asarray(img)
    regions: list[Detection] = []
    silhouette = np.zeros((h, w), dtype=bool)

    result = _MODELS["yolo"](arr, verbose=False)[0]
    names = result.names

    if result.boxes is not None:
        for box in result.boxes:
            cls = names.get(int(box.cls[0]), "")
            conf = float(box.conf[0])
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            det_box = (max(0, x1), max(0, y1), max(0, x2 - x1), max(0, y2 - y1))
            if cls == "person" and conf >= CONF_PERSON:
                regions.append(Detection(det_box, "person", conf))
            elif cls in OBJECT_CLASSES and conf >= CONF_OBJECT:
                regions.append(Detection(det_box, "object", conf))

    if getattr(result, "masks", None) is not None and result.boxes is not None:
        for mask, box in zip(result.masks.data, result.boxes):
            cls = names.get(int(box.cls[0]), "")
            conf = float(box.conf[0])
            if cls != "person" or conf < CONF_PERSON:
                continue
            mk = mask.cpu().numpy() if hasattr(mask, "cpu") else np.asarray(mask)
            if mk.shape != (h, w):
                mk = np.asarray(Image.fromarray((mk * 255).astype("uint8")).resize((w, h), Image.BILINEAR)) > 127
            silhouette |= mk.astype(bool)

    if _MODELS["face"] is not None:
        faces = _MODELS["face"].process(arr)
        for det in getattr(faces, "detections", None) or []:
            bb = det.location_data.relative_bounding_box
            regions.append(Detection(
                (int(bb.xmin * w), int(bb.ymin * h), int(bb.width * w), int(bb.height * h)),
                "face",
                float(det.score[0]) if det.score else 1.0,
            ))

    if _MODELS["hands"] is not None:
        hands = _MODELS["hands"].process(arr)
        for hand in getattr(hands, "multi_hand_landmarks", None) or []:
            xs = [p.x * w for p in hand.landmark]
            ys = [p.y * h for p in hand.landmark]
            regions.append(Detection(
                (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))),
                "hand",
                1.0,
            ))

    if not silhouette.any() and _MODELS["selfie"] is not None:
        try:
            seg = _MODELS["selfie"].process(arr)
            if getattr(seg, "segmentation_mask", None) is not None:
                silhouette = np.asarray(seg.segmentation_mask) > 0.55
        except Exception:
            pass

    return ProtectionMap(w, h, regions, silhouette if silhouette.any() else None)


def mock_protection_map(image: Image.Image, scenario: str = "right") -> ProtectionMap:
    w, h = image.size

    def person(cx: float, cw: float, y0: float = 0.16, y1: float = 0.98):
        bx, by, bw, bh = int(w * cx), int(h * y0), int(w * cw), int(h * (y1 - y0))
        face = (bx + int(bw * 0.25), by + int(bh * 0.04), int(bw * 0.48), int(bh * 0.22))
        hand = (bx + int(bw * 0.18), by + int(bh * 0.45), int(bw * 0.22), int(bh * 0.14))
        sil = np.zeros((h, w), dtype=bool)
        sil[max(0, by):min(h, by + bh), max(0, bx):min(w, bx + bw)] = True
        return [Detection((bx, by, bw, bh), "person", 0.95), Detection(face, "face", 0.98), Detection(hand, "hand", 0.9)], sil

    if scenario == "left":
        regs, sil = person(0.04, 0.44)
    elif scenario == "center":
        regs, sil = person(0.30, 0.40)
    elif scenario == "corner":
        regs, sil = person(0.56, 0.40, 0.44, 0.98)
    elif scenario == "two":
        r1, s1 = person(0.02, 0.30)
        r2, s2 = person(0.66, 0.30)
        regs, sil = r1 + r2, s1 | s2
    else:
        regs, sil = person(0.52, 0.44)
    return ProtectionMap(w, h, regs, sil)
