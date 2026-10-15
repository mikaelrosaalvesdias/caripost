"""TIPOGRAFIA ORIGINAL do cliente (out/2026). A IA de imagem escreve com a "fonte de IA" (sans geométrica pesada
genérica) mesmo quando pedimos outra por nome. O que funciona: mostrar a ela a fonte DESENHADA com o próprio texto.

1) identify(): a visão compara as artes do cliente com uma folha de AMOSTRAS (fontes reais do Google Fonts, numeradas)
   e escolhe a família/peso do TÍTULO e do TEXTO. Candidatas = as sugeridas no DNA visual + uma base comum.
2) Baixa os TTFs (Google Fonts CSS API) para /media/<empresa>/brand/fonts/.
3) specimen(): na hora da arte, renderiza o TÍTULO real daquela tela nessa fonte → vai como imagem de referência
   rotulada "AMOSTRA DA TIPOGRAFIA OFICIAL" (a IA copia o desenho das letras).

Salvo em brand_kit.creative_config.design.typography = {title:{family,weight,file}, body:{...}, at, edited?}."""
from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

MEDIA_ROOT = os.environ.get("CARIPOST_MEDIA_ROOT") or "/media"
BASE = ["Montserrat", "Poppins", "Inter", "Raleway", "Oswald", "Bebas Neue", "Anton", "Archivo Black", "Barlow",
        "Barlow Condensed", "Rubik", "Nunito", "Outfit", "Sora", "Lexend", "Kanit", "Exo 2", "League Spartan",
        "Red Hat Display", "Plus Jakarta Sans", "Titillium Web", "Saira", "Roboto Slab", "Playfair Display",
        "Bangers", "Fredoka", "Space Grotesk", "Work Sans", "Chakra Petch", "Rajdhani", "Russo One",
        "Jura", "Encode Sans", "Mulish"]
SAMPLE = "Turbine sua oferta 2026"
UA_TTF = "Mozilla/4.0"           # UA antigo → a CSS API devolve TTF (não woff2), que o PIL lê


def _dir(company_id: str = "") -> str:
    """Fontes do Google Fonts são públicas → cache único para todas as empresas."""
    d = os.path.join(MEDIA_ROOT, "_fonts")
    os.makedirs(d, exist_ok=True)
    return d


def _slug(family: str, weight: int) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", family) + f"-{weight}.ttf"


def fetch_ttf(family: str, weight: int, dest_dir: str) -> Optional[str]:
    """Baixa a família/peso do Google Fonts. Peso inexistente → tenta o mais próximo disponível."""
    path = os.path.join(dest_dir, _slug(family, weight))
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    tries = [weight] + sorted({400, 500, 600, 700, 800, 900} - {weight}, key=lambda w: abs(w - weight))
    for w in tries:
        try:
            css = httpx.get("https://fonts.googleapis.com/css2?family=" + family.replace(" ", "+") + f":wght@{w}",
                            headers={"User-Agent": UA_TTF}, timeout=20)
            if css.status_code != 200:
                continue
            m = re.search(r"url\((https://[^)]+\.ttf)\)", css.text)
            if not m:
                continue
            r = httpx.get(m.group(1), timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(path, "wb") as f:
                    f.write(r.content)
                return path
        except Exception:
            continue
    return None


def _font(path: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def _sheet(cands: List[Dict[str, Any]], sample: str = SAMPLE) -> bytes:
    """Folha de amostras numeradas (cada linha: nº, título pesado, texto médio)."""
    from PIL import Image, ImageDraw
    row = 118
    W = 1400
    im = Image.new("RGB", (W, 30 + row * len(cands)), "white")
    d = ImageDraw.Draw(im)
    lab = _font(cands[0]["regular"] or cands[0]["heavy"], 30)
    for i, c in enumerate(cands):
        y = 20 + i * row
        d.text((14, y + 30), f"{i + 1:>2}", fill=(220, 30, 30), font=lab)
        if c.get("heavy"):
            d.text((80, y), sample.upper() if c.get("caps") else sample, fill="black", font=_font(c["heavy"], 56))
        if c.get("regular"):
            d.text((80, y + 70), "Fale conosco: 11 97445-1971 · SVA's para provedores", fill=(60, 60, 60),
                   font=_font(c["regular"], 30))
        d.line((0, y + row - 8, W, y + row - 8), fill=(225, 225, 225))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _dna_fonts(company: Dict[str, Any]) -> List[str]:
    dna = ((((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}).get("visual_dna") or {})
    txt = str((dna.get("data") or {}).get("tipografia") or dna.get("text") or "")
    names = re.findall(r"\b([A-Z][a-zA-Z]+(?: [A-Z0-9][a-zA-Z0-9]+){0,2})\b", txt)
    stop = {"Tipografia", "Google", "Fonts", "Fonte", "Fontes", "Títulos", "Texto", "Evite", "Caixa", "Peso", "Se",
            "Para", "Com", "Sem", "Use", "Bold", "Black", "Regular", "Medium", "Light", "Semibold", "ExtraBold"}
    out = []
    for n in names:
        n = n.strip()
        if n.split(" ")[0] in stop or len(n) < 3:
            continue
        if n not in out:
            out.append(n)
    return out[:6]


def _ocr_words(im) -> List[Dict[str, Any]]:
    """Palavras legíveis da arte com caixa (tesseract). Só alfabéticas ≥3 letras, confiança alta."""
    import pytesseract
    data = None
    for lang in ("por", "eng"):
        try:
            data = pytesseract.image_to_data(im, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 11")
            break
        except Exception:
            continue
    out = []
    for i, t in enumerate((data or {}).get("text") or []):
        t = (t or "").strip()
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1
        if conf < 75 or len(t) < 3 or not re.fullmatch(r"[A-Za-zÀ-ÿ]+[!?.,:]?", t):
            continue
        out.append({"text": t.rstrip("!?.,:"), "x": data["left"][i], "y": data["top"][i],
                    "w": data["width"][i], "h": data["height"][i]})
    return out


def _mask(img_l, thr: int = 60):
    """Imagem L → máscara booleana da TINTA (texto), recortada justo. Fundo = mediana da borda."""
    import numpy as np
    a = np.asarray(img_l, dtype=np.float32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = float(np.median(border))
    m = np.abs(a - bg) > thr
    ys, xs = np.where(m)
    if not len(xs):
        return None
    return m[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]


def _render_mask(path: str, text: str, size: int = 160):
    from PIL import Image, ImageDraw
    f = _font(path, size)
    im = Image.new("L", (int(size * (len(text) + 2) * 0.9), int(size * 1.8)), 255)
    ImageDraw.Draw(im).text((size // 2, size // 3), text, fill=0, font=f)
    return _mask(im, 100)


def _glyphs(m):
    """Máscara de palavra → glifos (componentes conexos) da esquerda p/ direita, sem acentos/pontos minúsculos."""
    from scipy import ndimage as ndi
    lab, _n = ndi.label(m)
    H = m.shape[0]
    out = []
    for i, sl in enumerate(ndi.find_objects(lab)):
        g = lab[sl] == i + 1
        if g.sum() < max(12, (H * H) // 400):
            continue
        out.append((sl[1].start, g))
    out.sort(key=lambda x: x[0])
    return [g for _, g in out], H


def _glyph_cmp(a, b, Ha: int, Hb: int) -> float:
    """Glifo x glifo: forma no próprio contorno (Dice 48×48) × proporção × altura relativa (x-height/ascendentes)."""
    import math
    import numpy as np
    from PIL import Image
    n = lambda g: np.asarray(Image.fromarray(g.astype("uint8") * 255).resize((48, 48), Image.BILINEAR)) > 127
    A, B = n(a), n(b)
    dice = 2 * float((A & B).sum()) / max(1.0, float(A.sum() + B.sum()))
    ra, rb = a.shape[1] / a.shape[0], b.shape[1] / b.shape[0]
    return dice * math.exp(-2 * abs(math.log(ra / rb))) * math.exp(-3 * abs(a.shape[0] / Ha - b.shape[0] / Hb))


def _shape_score(a, b) -> float:
    """Semelhança de duas máscaras de palavra. LETRA A LETRA quando dá para separar os glifos (imune a espaçamento
    entre letras, que domina a comparação da palavra inteira); senão, a palavra toda (Dice × proporção)."""
    import math
    import numpy as np
    from PIL import Image
    if a is None or b is None or a.shape[0] < 6 or b.shape[0] < 6:
        return 0.0
    try:
        ga, Ha = _glyphs(a)
        gb, Hb = _glyphs(b)
        if ga and len(ga) == len(gb):
            return float(np.mean([_glyph_cmp(x, y, Ha, Hb) for x, y in zip(ga, gb)]))
    except Exception:
        pass
    ra, rb = a.shape[1] / a.shape[0], b.shape[1] / b.shape[0]
    H = 64
    W = max(8, int(H * ra))
    A = np.asarray(Image.fromarray(a.astype("uint8") * 255).resize((W, H), Image.BILINEAR)) > 127
    B = np.asarray(Image.fromarray(b.astype("uint8") * 255).resize((W, H), Image.BILINEAR)) > 127
    dice = 2 * float((A & B).sum()) / max(1.0, float(A.sum() + B.sum()))
    return 0.85 * dice * math.exp(-2.5 * abs(math.log(ra / rb)))


def _word_sheet(words: List[Dict[str, Any]], finalists, d: str) -> bytes:
    """Colunas = palavras reais; linha 0 = recorte ORIGINAL da arte; linhas 1..N = a mesma palavra em cada finalista."""
    from PIL import Image, ImageDraw
    H, GAP = 86, 22
    words = words[:3]
    col_w = []
    rows = []
    for w in words:
        om = Image.fromarray(((~w["mask"]).astype("uint8")) * 255)        # original binarizado: tinta preta
        hh0 = int(H * 0.78)
        cells = [om.resize((max(1, int(om.width * hh0 / om.height)), hh0))]
        for (_s, wt), fam in finalists:
            p = fetch_ttf(fam, wt, d)
            m = _render_mask(p, w["text"]) if p else None
            if m is None:
                cells.append(Image.new("L", (10, H), 255)); continue
            im = Image.fromarray(((~m).astype("uint8")) * 255)
            hh = int(H * 0.78)
            cells.append(im.resize((max(1, int(im.width * hh / im.height)), hh)))
        rows.append(cells)
        col_w.append(max(c.width for c in cells))
    n = len(finalists) + 1
    W = 90 + sum(col_w) + GAP * len(col_w)
    sheet = Image.new("L", (W, n * (H + GAP) + GAP), 255)
    dr = ImageDraw.Draw(sheet)
    lab = _font(fetch_ttf("Inter", 700, d) or finalists[0][1], 34)
    for r in range(n):
        y = GAP + r * (H + GAP)
        dr.text((12, y + 20), "ORIG" if r == 0 else str(r), fill=0, font=lab)
        x = 90
        for ci, cells in enumerate(rows):
            sheet.paste(cells[r], (x, y + (H - cells[r].height) // 2)); x += col_w[ci] + GAP
        dr.line((0, y + H + GAP // 2, W, y + H + GAP // 2), fill=200)
    buf = io.BytesIO(); sheet.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _vision_final(words, ranked, d: str, k: int = 6):
    """Desempate: a visão vê o recorte REAL de cada palavra ao lado da mesma palavra em cada finalista (top-k dos
    pixels). Comparar palavra com palavra é fácil; arte inteira x amostra, não. Falhou → mantém o ranking."""
    from .visual_dna import _vision
    from .ai import extract_json
    fin = ranked[:k]
    if len(fin) < 2 or not words:
        return None
    try:
        sheet = _word_sheet(sorted(words, key=lambda x: -len(x["text"])), fin, d)
        content = [{"type": "text", "text": (
            "Identificação de fonte. Na imagem, a linha ORIG mostra palavras RECORTADAS de uma arte real. As linhas "
            f"1 a {len(fin)} mostram as MESMAS palavras escritas em fontes candidatas. Compare letra a letra (curvas "
            "redondas ou quadradas, largura, abertura do 'e'/'a'/'s', terminais, peso). Qual linha é a MESMA fonte "
            'da linha ORIG? Responda SÓ JSON: {"n":<número>,"certeza":"alta|media|baixa"}')},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(sheet).decode()}}]
        r = extract_json(_vision(content, max_tokens=120)) or {}
        n = int(r.get("n")) - 1
        if 0 <= n < len(fin):
            print(f"[fonts] desempate visual: {fin[n][1]} ({r.get('certeza')}) entre {[f for _, f in fin]}", flush=True)
            return [fin[n]] + [x for i, x in enumerate(ranked) if i != n]
    except Exception as exc:
        print(f"[fonts] desempate visual falhou: {str(exc)[:120]}", flush=True)
    return None


def match_pixels(arts: List[bytes], cands: List[Dict[str, Any]], d: str, exclude: Optional[set] = None,
                 footer_frac: float = 0.0) -> Dict[str, Any]:
    """Título = palavras de letra GRANDE; texto = palavras pequenas. Ranking de famílias por forma; depois o peso.
    `exclude` = nomes de marca/produtos (são LOGOS, desenho próprio); a faixa do rodapé oficial é ignorada."""
    from PIL import Image
    excl = {e.lower() for e in (exclude or set()) if e}
    big, small = [], []
    for raw in arts[:4]:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im = im.resize((2160, int(2160 * im.height / im.width)), Image.LANCZOS)
        g = im.convert("L")
        cut_y = im.height * (1 - footer_frac) if footer_frac else im.height
        words = [w for w in _ocr_words(im) if w["text"].lower() not in excl
                 and not any(w["text"].lower() in e or e in w["text"].lower() for e in excl if len(e) >= 4)
                 and w["y"] + w["h"] <= cut_y]
        if not words:
            continue
        hmax = max(w["h"] for w in words)
        for w in words:
            pad = max(4, w["h"] // 6)
            crop = g.crop((w["x"] - pad, w["y"] - pad, w["x"] + w["w"] + pad, w["y"] + w["h"] + pad))
            m = _mask(crop)
            if m is None:
                continue
            item = {"text": w["text"], "mask": m, "crop": crop}
            if w["h"] >= 0.85 * hmax and w["h"] >= 60:
                big.append(item)
            elif 27 <= w["h"] < 0.85 * hmax:
                small.append(item)
    big = sorted(big, key=lambda x: -len(x["text"]))[:10]
    small = sorted(small, key=lambda x: -len(x["text"]))[:10]
    if len(big) < 2:
        return {}
    caps = sum(1 for w in big if w["text"].isupper()) >= len(big) * 0.6

    def fam_score(fam, words, weights):
        """Melhor peso da família para essas palavras → (score médio, peso)."""
        best = (0.0, weights[0])
        for wt in weights:
            p = fetch_ttf(fam, wt, d)
            if not p:
                continue
            s = sum(_shape_score(w["mask"], _render_mask(p, w["text"])) for w in words) / len(words)
            best = max(best, (s, wt))
        return best

    def rank(words, weights):
        res = [(fam_score(c["family"], words, weights), c["family"]) for c in cands]
        res.sort(key=lambda x: -x[0][0])
        return res

    rt = rank(big, [600, 700, 800, 900])
    if rt[0][0][0] - rt[1][0][0] < 0.005:
        rt = _vision_final(big, rt, d) or rt
    (st, wt), top_fam = rt[0]
    out: Dict[str, Any] = {"title": {"family": top_fam, "weight": wt, "score": st}, "caps": caps,
                           "words": len(big) + len(small),
                           "ranking": [f"{f} {w}:{s:.3f}" for (s, w), f in rt[:5]]}
    gap = rt[0][0][0] - rt[1][0][0]
    out["confidence"] = "alta" if gap > 0.03 else "media" if gap > 0.012 else "baixa"
    if len(small) >= 2:
        rb = rank(small, [300, 400, 500, 600])
        if rb[0][0][0] - rb[1][0][0] < 0.005:
            rb = _vision_final(small, rb, d) or rb
        (sb, wb), bf_ = rb[0]
        out["body"] = {"family": bf_, "weight": wb, "score": sb}
        out["ranking_body"] = [f"{f} {w}:{s:.3f}" for (s, w), f in rb[:3]]
    return out


def identify(company: Dict[str, Any], arts: List[bytes]) -> Dict[str, Any]:
    """Visão escolhe a fonte do título e do texto entre amostras reais. Retorna o dict de typography."""
    from .visual_dna import _vision, _thumb
    from .ai import extract_json
    d = _dir(company["id"])
    names = []
    for n in _dna_fonts(company) + BASE:
        if n not in names:
            names.append(n)
    cands = []
    for n in names[:40]:
        heavy = fetch_ttf(n, 800, d)
        if not heavy:
            continue
        cands.append({"family": n, "heavy": heavy, "regular": fetch_ttf(n, 500, d) or heavy})
    if len(cands) < 3:
        raise ValueError("não consegui baixar fontes candidatas")
    # 1º: comparação por PIXELS (OCR acha as palavras reais; cada fonte escreve a mesma palavra; vence a forma
    # mais parecida). A visão sozinha confunde famílias parecidas (ex.: Exo 2 x Montserrat).
    try:
        _ex = {company.get("name") or ""}
        try:
            from ..db_companies import product_list
            _ex |= {(p.get("name") or "") for p in (product_list(company["id"]) or [])}
        except Exception:
            pass
        _kit = (((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}).get("footer_kit") or {}
        px = match_pixels(arts, cands, d, exclude=_ex, footer_frac=float(_kit.get("frac") or 0))
    except Exception as exc:
        print(f"[fonts] comparação por pixels falhou: {str(exc)[:160]}", flush=True)
        px = {}
    if px.get("title"):
        def as_entry(sel, caps=False):
            fam, w = sel["family"], sel["weight"]
            f = fetch_ttf(fam, w, d)
            return {"family": fam, "weight": w, "file": (f or "").replace(MEDIA_ROOT, "/uploads", 1), "caps": caps,
                    "score": round(sel["score"], 3)}
        typo = {"title": as_entry(px["title"], px.get("caps", False)),
                "body": as_entry(px.get("body") or {"family": px["title"]["family"], "weight": 400, "score": 0}),
                "confidence": px.get("confidence", "media"), "method": "pixels", "words": px.get("words"),
                "ranking": px.get("ranking"), "at": datetime.now(timezone.utc).isoformat(), "auto": True}
        print(f"[fonts] {company.get('name')}: título={typo['title']['family']} {typo['title']['weight']} "
              f"texto={typo['body']['family']} {typo['body']['weight']} (pixels, {px.get('words')} palavras, "
              f"ranking={px.get('ranking')})", flush=True)
        return typo
    def img(b: bytes, side: int = 900) -> Dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(_thumb(b, side)).decode()}}
    # RODADA 1 — triagem: cada folha separada (numeração própria e curta = a visão não se perde), top-3 de cada.
    chunk = 9
    finalists: List[Dict[str, Any]] = []
    lido = ""
    for k in range(0, len(cands), chunk):
        part = cands[k:k + chunk]
        content: List[Dict[str, Any]] = [{"type": "text", "text": (
            "As primeiras imagens são ARTES REAIS da marca " + (company.get("name") or "") + ". A ÚLTIMA imagem é uma "
            f"folha com {len(part)} fontes, linhas numeradas de 1 a {len(part)} em vermelho. Compare o DESENHO DAS "
            "LETRAS dos TÍTULOS das artes (proporção, largura, curvas redondas x quadradas, terminais, forma do "
            "a/e/g/R/S, peso) com cada linha. Ignore a LOGO (desenho próprio) e artes temáticas pontuais (ex.: "
            "quadrinhos de evento). Responda SÓ JSON: "
            '{"ranking":[<até 3 números da folha, do mais parecido ao menos>],"titulo_lido":"<um título curto '
            'copiado de uma arte, com acentos>"}')}]
        content += [img(b) for b in arts[:4]]
        content.append(img(_sheet(part), 1400))
        try:
            r1 = extract_json(_vision(content, max_tokens=300)) or {}
        except Exception:
            continue
        lido = lido or str(r1.get("titulo_lido") or "")[:40]
        for n in (r1.get("ranking") or [])[:3]:
            try:
                c = part[int(n) - 1]
            except Exception:
                continue
            if c not in finalists:
                finalists.append(c)
    finalists = finalists or cands[:6]
    # RODADA 2 — final: as finalistas escrevendo o MESMO texto que aparece nas artes (comparação direta).
    final_sheet = _sheet(finalists[:9], lido or SAMPLE)
    content = [{"type": "text", "text": (
        "As primeiras imagens são ARTES REAIS da marca " + (company.get("name") or "") + ". A ÚLTIMA imagem mostra "
        f"{len(finalists[:9])} fontes candidatas (linhas numeradas em vermelho) escrevendo o mesmo texto das artes. "
        "Qual linha tem o desenho de letra MAIS IDÊNTICO aos TÍTULOS das artes? E qual linha (texto menor, cinza) "
        "mais parece o TEXTO DE APOIO? Ignore a logo. Responda SÓ JSON: "
        '{"titulo":{"n":<número>,"peso":<400-900>,"caixa":"alta|mista"},"texto":{"n":<número>,"peso":<300-700>},'
        '"confianca":"alta|media|baixa","obs":"curto"}')}]
    content += [img(b) for b in arts[:4]]
    content.append(img(final_sheet, 1400))
    res = extract_json(_vision(content, max_tokens=400)) or {}
    cands = finalists[:9]
    def pick(key, default_w):
        o = res.get(key) or {}
        try:
            c = cands[int(o.get("n")) - 1]
        except Exception:
            c = cands[0]
        w = int(o.get("peso") or default_w)
        w = max(300, min(900, round(w / 100) * 100))
        f = fetch_ttf(c["family"], w, d) or c["heavy"]
        return {"family": c["family"], "weight": w, "file": f.replace(MEDIA_ROOT, "/uploads", 1),
                "caps": (o.get("caixa") == "alta")}
    typo = {"title": pick("titulo", 800), "body": pick("texto", 500), "confidence": res.get("confianca") or "",
            "obs": str(res.get("obs") or "")[:200], "at": datetime.now(timezone.utc).isoformat(), "auto": True}
    print(f"[fonts] {company.get('name')}: título={typo['title']['family']} {typo['title']['weight']} "
          f"texto={typo['body']['family']} {typo['body']['weight']} ({typo['confidence']})", flush=True)
    return typo


def save(company_id: str, typo: Dict[str, Any]) -> None:
    from ..db_companies import brand_kit_upsert, company_get
    co = company_get(company_id) or {}
    cc = dict(((co.get("brand_kit") or {}).get("creative_config")) or {})
    design = dict(cc.get("design") or {})
    design["typography"] = typo
    cc["design"] = design
    brand_kit_upsert(company_id, {"creative_config": cc})


def _own_arts(company_id: str, limit: int = 4) -> List[bytes]:
    """Artes do cliente, primeiro as que seguem o PADRÃO da marca (as que têm o rodapé oficial detectado)."""
    from ..db_companies import asset_list, company_get
    from .visual_dna import _media_path
    kit = (((company_get(company_id) or {}).get("brand_kit") or {}).get("creative_config") or {}).get("design", {}).get("footer_kit") or {}
    std = set(kit.get("sources") or [])
    refs = sorted(asset_list(company_id, role="brand_reference") or [], key=lambda a: a.get("url") not in std)
    if len(std) >= 2:                      # há padrão (rodapé oficial) → só as artes do padrão; temáticas pontuais fora
        refs = [a for a in refs if a.get("url") in std]
    out = []
    for a in refs:
        try:
            out.append(open(_media_path(a["url"]), "rb").read())
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def ensure(company: Dict[str, Any]) -> Dict[str, Any]:
    design = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}
    typo = design.get("typography") or {}
    if typo.get("at"):
        return typo if typo.get("title") and typo.get("enabled", True) else {}
    arts = _own_arts(company["id"])
    if not arts:
        return {}
    try:
        typo = identify(company, arts)
    except Exception as exc:
        print(f"[fonts] {company.get('name')}: identificação falhou: {str(exc)[:160]}", flush=True)
        return {}
    save(company["id"], typo)
    return typo


def _path(u: str) -> str:
    return u.replace("/uploads", MEDIA_ROOT, 1) if u.startswith("/uploads") else u


def specimen(typo: Dict[str, Any], title: str, body: str = "") -> Optional[bytes]:
    """O TÍTULO REAL da tela desenhado na fonte oficial (preto no branco) + uma linha do texto na fonte de apoio."""
    from PIL import Image, ImageDraw
    t = (typo or {}).get("title") or {}
    if not t.get("file") or not (title or "").strip():
        return None
    try:
        ft = _font(_path(t["file"]), 92)
        b = (typo.get("body") or {})
        fb = _font(_path(b["file"]), 40) if b.get("file") else None
    except Exception:
        return None
    text = title.strip().upper() if t.get("caps") else title.strip()
    W = 1400
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d0.textlength(test, font=ft) > W - 120 and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    lines = lines[:4]
    H = 80 + len(lines) * 112 + (90 if fb and body else 20)
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    y = 50
    for ln in lines:
        d.text((60, y), ln, fill="black", font=ft); y += 112
    if fb and body:
        d.text((60, y + 10), (body.strip()[:70] + ("…" if len(body.strip()) > 70 else "")), fill=(50, 50, 50), font=fb)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def prompt_line(typo: Dict[str, Any]) -> str:
    t, b = (typo or {}).get("title") or {}, (typo or {}).get("body") or {}
    if not t.get("family"):
        return ""
    return (f" TIPOGRAFIA OFICIAL DA MARCA (extraída das artes dela — OBRIGATÓRIA): títulos em {t['family']} peso "
            f"{t.get('weight')}{' em CAIXA ALTA' if t.get('caps') else ''}; textos de apoio em {b.get('family') or t['family']} "
            f"peso {b.get('weight') or 500}. A imagem 'AMOSTRA DA TIPOGRAFIA OFICIAL' mostra o título desta tela já "
            "desenhado nessa fonte: COPIE exatamente esse desenho de letra (proporção, largura, terminais, peso). "
            "É PROIBIDO usar outra fonte nos títulos. ")


def _ocr_hits(img_bytes: bytes, expected: List[str]) -> float:
    """Fração das palavras esperadas (≥3 letras) que o OCR lê na arte — proteção da 2ª passada."""
    import unicodedata
    import pytesseract
    from PIL import Image
    norm = lambda s: unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    words = [norm(w) for t in expected for w in re.findall(r"[A-Za-zÀ-ÿ]{3,}", t or "")]
    if not words:
        return 1.0
    im = Image.open(io.BytesIO(img_bytes)).convert("L")
    try:
        txt = norm(pytesseract.image_to_string(im, lang="por"))
    except Exception:
        txt = norm(pytesseract.image_to_string(im))
    return sum(1 for w in words if w in txt) / len(words)


def reletter(img_bytes: bytes, typo: Dict[str, Any], texts: List[str],
             model: str = "codex/gpt-5.6-luna-image") -> Optional[bytes]:
    """2ª PASSADA DE LETREIRO: a IA de imagem refaz a arte IDÊNTICA trocando só o desenho das letras pela fonte
    oficial (amostra com o próprio título). Na 1ª passada ela compõe a arte e tende a cair na "fonte de IA"; aqui
    a única tarefa é o letreiro → copia a fonte. Só aceita se o OCR ler o texto pelo menos tão bem quanto antes."""
    from PIL import Image
    from .ai import _iref_omni_edit
    t, b = (typo or {}).get("title") or {}, (typo or {}).get("body") or {}
    title = next((x for x in texts if (x or "").strip()), "")
    spec = specimen(typo, title, texts[1] if len(texts) > 1 else "")
    if not spec:
        return None
    W, H = Image.open(io.BytesIO(img_bytes)).size
    size = "1024x1792" if H / W > 1.6 else ("1536x1024" if W > H else "1024x1536")
    prompt = (
        "Imagem 1 é uma arte pronta. Imagem 2 é a AMOSTRA DA FONTE OFICIAL da marca "
        f"({t.get('family')} peso {t.get('weight')} nos títulos; {b.get('family') or t.get('family')} peso "
        f"{b.get('weight') or 500} nos textos menores). Refaça a imagem 1 IDÊNTICA — mesma foto, mesma composição, "
        "mesmas cores, mesmas posições e tamanhos, mesmos elementos — mudando SOMENTE o desenho das letras dos "
        "textos para a fonte da imagem 2 (copie proporção, largura, cantos, terminais e peso). Os textos continuam "
        "EXATAMENTE os mesmos, com todos os acentos. Logos são imagens: não mexa nelas. Não acrescente nada.")
    try:
        out, _ = _iref_omni_edit(model, prompt, [img_bytes, spec], size)
    except Exception as exc:
        print(f"[fonts] letreiro: motor falhou ({str(exc)[:120]}) → mantém a 1ª versão", flush=True)
        return None
    try:
        before, after = _ocr_hits(img_bytes, texts), _ocr_hits(out, texts)
    except Exception:
        before, after = 0.0, 0.0
    if after + 0.05 < before:
        print(f"[fonts] letreiro: texto piorou (OCR {before:.2f}→{after:.2f}) → mantém a 1ª versão", flush=True)
        return None
    print(f"[fonts] letreiro ok (OCR {before:.2f}→{after:.2f})", flush=True)
    return out
