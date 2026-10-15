"""TEXTO COM A FONTE REAL (out/2026). A IA de imagem compõe a arte livre (layout, foto, cores), mas escreve com a
"fonte de IA" — e nem com amostra ela copia a fonte da marca com segurança. Aqui o texto é REFEITO de verdade:

1) find_lines: o OCR acha, na arte da IA, cada linha do TÍTULO / TEXTO / BOTÃO (posição, tamanho, cor), casando
   com os textos esperados (que já vêm com acento certo).
2) clean: a IA apaga SÓ esses textos (mesma arte, fundo continuado). Conferido: se mexer no resto, desiste.
3) typeset: a arte sobe para 2160 px e o Caripost escreve os mesmos textos com o ARQUIVO da fonte da marca, no
   mesmo lugar, mesmo alinhamento, mesma cor e tamanho equivalente. Botão: texto centralizado no botão.

Qualquer etapa que falhe → devolve None e o fluxo mantém a arte original (nunca piora)."""
from __future__ import annotations

import difflib
import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

TARGET_W = 2160


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9%]", "", s)


def _ocr(im) -> List[Dict[str, Any]]:
    import pytesseract
    from PIL import ImageOps
    out = []
    import numpy as np
    from PIL import Image
    g = im.convert("L").resize((im.width * 2, im.height * 2))
    rgb = np.asarray(im.convert("RGB").resize((im.width * 2, im.height * 2))).astype(np.int32)
    white = Image.fromarray(np.where(rgb.min(axis=2) > 200, 0, 255).astype("uint8"))   # texto branco em qualquer fundo (botão)
    for inv in (False, True, "white"):
        src = white if inv == "white" else (ImageOps.invert(g) if inv else g)
        try:
            d = pytesseract.image_to_data(src, lang="por", output_type=pytesseract.Output.DICT, config="--psm 11")
        except Exception:
            d = pytesseract.image_to_data(src, output_type=pytesseract.Output.DICT, config="--psm 11")
        for i, t in enumerate(d["text"]):
            t = (t or "").strip()
            if not _norm(t) or float(d["conf"][i]) < 35:
                continue
            out.append({"t": t, "n": _norm(t), "x": d["left"][i] / 2, "y": d["top"][i] / 2,
                        "w": d["width"][i] / 2, "h": d["height"][i] / 2})
    # dedup (as duas passadas acham a mesma palavra)
    ded: List[Dict[str, Any]] = []
    for w in sorted(out, key=lambda q: -q["h"]):
        if any(abs(w["x"] - q["x"]) < q["h"] * 0.5 and abs(w["y"] - q["y"]) < q["h"] * 0.5 for q in ded):
            continue
        ded.append(w)
    return ded


def find_lines(im, texts: Dict[str, str]) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """→ (linhas [{role, text, x, y, w, h}], cobertura por papel 0..1)."""
    words = _ocr(im)
    exp = {}
    for role, s in texts.items():
        toks = [t for t in re.split(r"\s+", (s or "").strip()) if t]
        if toks:
            exp[role] = [(t, _norm(t)) for t in toks]
    hits = []
    W = im.width
    for w in words:
        if len(w["n"]) < 3:                     # "e", "o", "a" casam com qualquer lixo do OCR
            continue
        best = None
        for role, toks in exp.items():
            for i, (_t, n) in enumerate(toks):
                if not n:
                    continue
                r = 1.0 if w["n"] == n else difflib.SequenceMatcher(None, w["n"], n).ratio()
                if r >= 0.72 and (best is None or r > best[0]):
                    best = (r, role, i)
        if best:
            hits.append(dict(w, role=best[1], idx=best[2]))
    lines: List[Dict[str, Any]] = []
    cover: Dict[str, float] = {}
    for role, toks in exp.items():
        hs = sorted([h for h in hits if h["role"] == role], key=lambda q: (q["y"] + q["h"] / 2, q["x"]))
        groups: List[List[Dict[str, Any]]] = []
        for h in hs:
            cy = h["y"] + h["h"] / 2
            for g in groups:
                gy = sum(q["y"] + q["h"] / 2 for q in g) / len(g)
                gh = max(q["h"] for q in g)
                if abs(cy - gy) < 0.45 * max(gh, h["h"]):
                    g.append(h); break
            else:
                groups.append([h])
        # fora do bloco principal do papel (ex.: "CARIAP" da logo, "e" num cartão) → descarta
        if groups:
            import statistics as _st
            ref = max(groups, key=len)                       # bloco principal = o grupo com mais palavras
            mh, mx = max(q["h"] for q in ref), min(q["x"] for q in ref)
            ys_ = sorted(min(q["y"] for q in g) for g in groups)
            groups = [g for g in groups
                      if max(q["h"] for q in g) <= 1.8 * mh and max(q["h"] for q in g) >= 0.5 * mh
                      and (abs(min(q["x"] for q in g) - mx) < 0.22 * W
                           or abs(sum(q["x"] + q["w"] / 2 for q in g) / len(g) - W / 2) < 0.08 * W)]
            # e verticalmente contíguo: linhas a mais de 3 alturas do vizinho mais próximo saem
            keep = []
            for g in groups:
                gy = min(q["y"] for q in g)
                others = [min(q["y"] for q in o) for o in groups if o is not g]
                if not others or min(abs(gy - oy) for oy in others) < 3.2 * mh:
                    keep.append(g)
            groups = keep
        used = set()
        for g in groups:
            idxs = sorted({q["idx"] for q in g})
            i0, i1 = idxs[0], idxs[-1]
            x0 = min(q["x"] for q in g); x1 = max(q["x"] + q["w"] for q in g)
            y0 = min(q["y"] for q in g); y1 = max(q["y"] + q["h"] for q in g)
            lines.append({"role": role, "i0": i0, "i1": i1, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
            used.update(range(i0, i1 + 1))
        cover[role] = len(used) / max(1, len(toks))
        # buracos entre linhas (palavra que o OCR não leu) → vai para o fim da linha anterior
        rl = sorted([l for l in lines if l["role"] == role], key=lambda l: l["i0"])
        for a, b in zip(rl, rl[1:]):
            if b["i0"] > a["i1"] + 1:
                a["i1"] = b["i0"] - 1
        if rl:
            rl[0]["i0"] = 0
            rl[-1]["i1"] = len(toks) - 1
        for l in rl:
            l["text"] = " ".join(t for t, _n in toks[l["i0"]: l["i1"] + 1])
    return lines, cover


def _ink_color(im, box) -> Tuple[int, int, int]:
    import numpy as np
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    crop = np.asarray(im.crop((x0, y0, x1, y1)).convert("RGB")).astype(np.float32)
    if crop.size == 0:
        return (255, 255, 255)
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    d = np.sqrt(((crop - bg) ** 2).sum(axis=2))
    ink = crop[d > max(60, np.percentile(d, 80))]
    return tuple(int(v) for v in (np.median(ink, axis=0) if len(ink) else 255 - bg))


def _button_box(im, line) -> Optional[Tuple[int, int, int, int]]:
    """Botão = região de cor sólida em volta do texto do CTA (flood fill a partir da margem esquerda do texto)."""
    import numpy as np
    from scipy import ndimage as ndi
    a = np.asarray(im.convert("RGB")).astype(np.int32)
    x, y, w, h = (int(line[k]) for k in ("x", "y", "w", "h"))
    sx, sy = max(0, x - max(4, h // 3)), min(a.shape[0] - 1, y + h // 2)
    seed = a[sy, sx]
    same = (np.abs(a - seed).sum(axis=2) < 60)
    lab, _ = ndi.label(same)
    k = lab[sy, sx]
    if not k:
        return None
    ys, xs = np.where(lab == k)
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    # tem que envolver o texto e não ser o fundo inteiro
    if not (bx0 <= x and bx1 >= x + w * 0.9 and by0 <= y and by1 >= y + h) or (bx1 - bx0) * (by1 - by0) > 0.2 * a.shape[0] * a.shape[1]:
        return None
    return int(bx0), int(by0), int(bx1), int(by1)


def clean(img_bytes: bytes, lines: List[Dict[str, Any]], texts: Dict[str, str],
          model: str = "codex/gpt-5.6-luna-image") -> Optional[bytes]:
    from PIL import Image
    import numpy as np
    from .ai import _iref_omni_edit
    roles = sorted({l["role"] for l in lines})
    labels = {"title": "o título", "body": "o parágrafo", "cta": "o texto DENTRO do botão (o botão continua, vazio)"}
    lst = "; ".join(f"{labels.get(r, r)} «{texts[r]}»" for r in roles if texts.get(r))
    prompt = ("Refaça esta imagem IDÊNTICA — mesma foto, mesmos objetos, mesmos cartões/logos, mesmas cores, luz, "
              "composição, botões e rodapé — porém APAGUE completamente estes textos: " + lst + ". Onde estavam, "
              "deixe só o fundo (ou o botão) continuando naturalmente, sem letras nem manchas. Não apague nenhum "
              "outro texto ou logo.")
    im0 = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    W, H = im0.size
    size = "1024x1792" if H / W > 1.6 else ("1536x1024" if W > H else "1024x1536")
    try:
        out, _ = _iref_omni_edit(model, prompt, [img_bytes], size)
    except Exception as exc:
        print(f"[tipo] limpeza falhou: {str(exc)[:120]}", flush=True)
        return None
    im1 = Image.open(io.BytesIO(out)).convert("RGB").resize((W, H))
    # a IA não pode ter mexido no resto: diferença média FORA das caixas de texto
    a0 = np.asarray(im0).astype(np.float32); a1 = np.asarray(im1).astype(np.float32)
    mask = np.ones((H, W), bool)
    for l in lines:
        p = int(l["h"] * 0.6)
        mask[max(0, int(l["y"]) - p): int(l["y"] + l["h"]) + p, max(0, int(l["x"]) - p): int(l["x"] + l["w"]) + p] = False
    diff = float(np.abs(a0 - a1).mean(axis=2)[mask].mean())
    if diff > 22:
        print(f"[tipo] limpeza alterou a arte (dif {diff:.1f}) → desiste", flush=True)
        return None
    left = _ocr(im1)
    gone = sum(1 for w in left for l in lines
               if l["x"] - 5 <= w["x"] <= l["x"] + l["w"] and l["y"] - 5 <= w["y"] <= l["y"] + l["h"] and len(w["n"]) >= 3)
    if gone > 2:
        print(f"[tipo] limpeza deixou {gone} palavras → desiste", flush=True)
        return None
    print(f"[tipo] limpeza ok (dif fora do texto {diff:.1f})", flush=True)
    buf = io.BytesIO(); im1.save(buf, "PNG")
    return buf.getvalue()


def _font_path(spec: Dict[str, Any]) -> Optional[str]:
    from .brand_fonts import _path
    return _path(spec["file"]) if spec and spec.get("file") else None


def typeset(clean_bytes: bytes, orig_bytes: bytes, lines: List[Dict[str, Any]], typo: Dict[str, Any]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    orig = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
    base = Image.open(io.BytesIO(clean_bytes)).convert("RGB")
    W0, H0 = base.size
    k = TARGET_W / W0
    big = base.resize((TARGET_W, int(round(H0 * k))), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    tf = _font_path((typo or {}).get("title") or {})
    bf = _font_path((typo or {}).get("body") or {}) or tf
    from .brand_fonts import fetch_ttf, _dir
    bfam = ((typo or {}).get("body") or (typo or {}).get("title") or {}).get("family") or ""
    cta_f = (fetch_ttf(bfam, 700, _dir()) if bfam else None) or bf
    by_role: Dict[str, List[Dict[str, Any]]] = {}
    for l in lines:
        by_role.setdefault(l["role"], []).append(l)
    for role, ls in by_role.items():
        path = tf if role == "title" else (cta_f if role == "cta" else bf)
        if not path:
            continue
        ls.sort(key=lambda l: l["y"])
        # tamanho: o que faz cada linha ter a MESMA LARGURA que a IA deu; o papel usa a mediana (consistente)
        sizes = []
        for l in ls:
            f = ImageFont.truetype(path, 200)
            bb = d.textbbox((0, 0), l["text"], font=f)
            sizes.append(200 * (l["w"] * k) / max(1, bb[2] - bb[0]))
        sizes.sort()
        size = sizes[len(sizes) // 2]
        xs = sorted(l["x"] for l in ls)
        cxs = sorted(l["x"] + l["w"] / 2 for l in ls)
        mxs, mcx = xs[len(xs) // 2], cxs[len(cxs) // 2]
        n_left = sum(1 for l in ls if abs(l["x"] - mxs) < 0.03 * W0)
        n_ctr = sum(1 for l in ls if abs(l["x"] + l["w"] / 2 - mcx) < 0.03 * W0)
        align = "center" if (n_ctr > n_left and len(ls) > 1) else "left"
        left_x = min(l["x"] for l in ls if abs(l["x"] - mxs) < 0.05 * W0)    # margem comum (OCR às vezes recua 1 linha)
        for l in ls:
            s = size
            f = ImageFont.truetype(path, max(8, int(s)))
            bb = d.textbbox((0, 0), l["text"], font=f)
            # nunca mais largo que 112% do espaço que a IA usou (não invade a foto ao lado)
            if (bb[2] - bb[0]) > l["w"] * k * 1.12:
                f = ImageFont.truetype(path, max(8, int(s * l["w"] * k * 1.12 / (bb[2] - bb[0]))))
                bb = d.textbbox((0, 0), l["text"], font=f)
            col = _ink_color(orig, (l["x"], l["y"], l["x"] + l["w"], l["y"] + l["h"]))
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            if role == "cta" and l.get("button"):
                bx0, by0, bx1, by1 = (v * k for v in l["button"])
                x = (bx0 + bx1) / 2 - tw / 2
                y = (by0 + by1) / 2 - th / 2
            else:
                x = left_x * k if align == "left" else mcx * k - tw / 2
                y = (l["y"] + l["h"]) * k - th          # alinha pela BASE da caixa (linha de base visual)
            d.text((x - bb[0], y - bb[1]), l["text"], font=f, fill=col)
    buf = io.BytesIO(); big.save(buf, "PNG")
    return buf.getvalue()


def retypeset(img_bytes: bytes, typo: Dict[str, Any], texts: Dict[str, str]) -> Optional[bytes]:
    """Fluxo completo. None = não deu com segurança (mantém a arte da IA)."""
    from PIL import Image
    if not ((typo or {}).get("title") or {}).get("file"):
        return None
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    texts = {k: v for k, v in texts.items() if (v or "").strip()}
    lines, cover = find_lines(im, texts)
    if cover.get("title", 0) < 0.75:
        print(f"[tipo] OCR não achou o título com segurança ({cover}) → mantém", flush=True)
        return None
    lines = [l for l in lines if cover.get(l["role"], 0) >= 0.75]
    for l in lines:
        if l["role"] == "cta":
            l["button"] = _button_box(im, l)
    lines = [l for l in lines if l["role"] != "cta" or l.get("button")]
    cleaned = clean(img_bytes, lines, texts)
    if not cleaned:
        return None
    out = typeset(cleaned, img_bytes, lines, typo)
    print(f"[tipo] texto refeito com a fonte da marca: {sorted({l['role'] for l in lines})} cobertura={cover}", flush=True)
    return out
