"""
detect.py — Mapa de proteção (o NÚCLEO). Roda 1x os modelos (singleton), nunca por request.

- YOLO11n / YOLO11n-seg (ultralytics): box de `person` + objetos COCO + máscara de silhueta.
- MediaPipe Face Detector: box de cada rosto (FACE = proibição absoluta).
- MediaPipe Hand Landmarker: box de cada mão (a partir dos 21 landmarks).

Se as deps pesadas não estiverem instaladas, `detect()` levanta ImportError com a dica de
instalar. Pra validar placement/treatments SEM GPU/deps, use `mock_protection_map()`.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
from PIL import Image

from placement import Detection, ProtectionMap

# objetos COCO que importam (mão segurando algo, produto na cena)
_OBJECT_CLASSES = {"cell phone", "bottle", "cup", "book", "laptop", "handbag", "tv",
                   "remote", "keyboard", "mouse", "wine glass", "backpack"}
_CONF_PERSON = 0.35
_CONF_OBJECT = 0.40
_CONF_FACE = 0.5

_models = {"yolo": None, "face": None, "hand": None, "loaded": False}


def _ensure_models():
    """Carrega YOLO + MediaPipe UMA vez. Levanta ImportError claro se faltar dep."""
    if _models["loaded"]:
        return
    try:
        from ultralytics import YOLO
    except Exception as e:  # noqa
        raise ImportError(
            "ultralytics não instalado. `pip install ultralytics` (ou use mock_protection_map / --mock)."
        ) from e
    weights = os.environ.get("YOLO_WEIGHTS", "yolo11n-seg.pt")
    _models["yolo"] = YOLO(weights)   # baixa o peso na 1ª vez
    try:
        import mediapipe as mp
        _models["face"] = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=_CONF_FACE)
        _models["hand"] = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=4, min_detection_confidence=0.4)
    except Exception:
        _models["face"] = None
        _models["hand"] = None   # YOLO person já cobre o corpo; face/hand é refino
    _models["loaded"] = True


def detect(image: Image.Image) -> ProtectionMap:
    """Imagem PIL -> ProtectionMap (regiões + silhueta). Rosto leva padding maior no placement."""
    _ensure_models()
    w, h = image.size
    arr = np.asarray(image.convert("RGB"))
    regions: list[Detection] = []
    silhouette = np.zeros((h, w), dtype=bool)

    res = _models["yolo"](arr, verbose=False)[0]
    names = res.names
    if res.boxes is not None:
        for b in res.boxes:
            cls = names.get(int(b.cls[0]), "")
            conf = float(b.conf[0])
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            box = (x1, y1, x2 - x1, y2 - y1)
            if cls == "person" and conf >= _CONF_PERSON:
                regions.append(Detection(box, "person", conf))
            elif cls in _OBJECT_CLASSES and conf >= _CONF_OBJECT:
                regions.append(Detection(box, "object", conf))
    # silhueta (instance seg) das pessoas
    if getattr(res, "masks", None) is not None and res.boxes is not None:
        for m, b in zip(res.masks.data, res.boxes):
            if names.get(int(b.cls[0]), "") == "person":
                mk = m.cpu().numpy() if hasattr(m, "cpu") else np.asarray(m)
                if mk.shape != (h, w):
                    mk = np.asarray(Image.fromarray((mk * 255).astype("uint8")).resize((w, h))) > 127
                silhouette |= mk.astype(bool)

    if _models["face"] is not None:
        fr = _models["face"].process(arr)
        if fr and fr.detections:
            for det in fr.detections:
                bb = det.location_data.relative_bounding_box
                box = (int(bb.xmin * w), int(bb.ymin * h), int(bb.width * w), int(bb.height * h))
                regions.append(Detection(box, "face", float(det.score[0])))
    if _models["hand"] is not None:
        hr = _models["hand"].process(arr)
        if hr and hr.multi_hand_landmarks:
            for lms in hr.multi_hand_landmarks:
                xs = [p.x * w for p in lms.landmark]; ys = [p.y * h for p in lms.landmark]
                box = (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))
                regions.append(Detection(box, "hand", 1.0))

    return ProtectionMap(w, h, regions, silhouette if silhouette.any() else None)


def mock_protection_map(image: Image.Image, scenario: str = "right") -> ProtectionMap:
    """Detecções MOCK (sem deps) p/ validar placement/treatments. scenario:
    right | left | center | corner | two."""
    w, h = image.size
    def person(cx, cw):
        bx = int(w * cx); bw = int(w * cw)
        regs = [Detection((bx, int(h * 0.16), bw, int(h * 0.82)), "person", 0.9),
                Detection((bx + int(bw * 0.22), int(h * 0.18), int(bw * 0.5), int(h * 0.22)), "face", 0.95)]
        sil = np.zeros((h, w), dtype=bool)
        sil[int(h * 0.16):, bx:bx + bw] = True
        return regs, sil
    if scenario == "left":
        regs, sil = person(0.04, 0.46)
    elif scenario == "center":
        regs, sil = person(0.30, 0.40)
    elif scenario == "corner":
        regs, sil = person(0.55, 0.42)
        regs[0] = Detection((int(w * 0.55), int(h * 0.45), int(w * 0.42), int(h * 0.53)), "person", 0.9)
    elif scenario == "two":
        r1, s1 = person(0.02, 0.30); r2, s2 = person(0.66, 0.30)
        regs, sil = r1 + r2, (s1 | s2)
    else:  # right
        regs, sil = person(0.50, 0.46)
    return ProtectionMap(w, h, regs, sil)
