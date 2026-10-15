"""RODAPÉ ORIGINAL do cliente (out/2026): muitas marcas assinam TODAS as artes com o mesmo rodapé (ex.: CARIAP —
fio fino, "Fale conosco no WhatsApp 11 97445-1971" à esquerda, logo à direita). Em vez do rodapé genérico do
Caripost, detectamos esse rodapé nas artes de referência e o reaplicamos IDÊNTICO nas artes novas.

Detecção (determinística, grátis): a faixa inferior de cada arte vira um "mapa de tinta" (distância de cada pixel até
a cor de fundo da faixa — independe de fundo claro/escuro). Faixas que se repetem entre várias artes = rodapé fixo.
Guarda 1 exemplar por fundo (claro/escuro) com o fundo REMOVIDO (PNG transparente), para colar sobre qualquer arte.

Salvo em brand_kit.creative_config.design.footer_kit = {frac, n, light, dark, at, auto} (editável/desligável)."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

MEDIA_ROOT = os.environ.get("CARIPOST_MEDIA_ROOT") or "/media"
FRACS = [x / 100 for x in range(6, 21)]          # altura candidata do rodapé: 6%..20% da arte
SIG_W = 216


def _media_path(url: str) -> str:
    rel = (url or "").split("?")[0]
    if rel.startswith("/uploads/"):
        rel = rel[len("/uploads/"):]
    return os.path.join(MEDIA_ROOT, rel)


def _bg_color(strip):
    """Cor de fundo da faixa = cor mais frequente (quantizada)."""
    small = strip.resize((96, max(4, int(96 * strip.height / strip.width))))
    q = small.quantize(colors=6, method=2)
    pal = q.getpalette()
    idx = max(q.getcolors(), key=lambda c: c[0])[1]
    return tuple(pal[idx * 3: idx * 3 + 3])


def _ink(strip, bg):
    """Mapa 0..1 de 'tinta' (distância à cor de fundo)."""
    import numpy as np
    a = np.asarray(strip, dtype=np.float32)
    d = np.sqrt(((a - np.array(bg, dtype=np.float32)) ** 2).sum(axis=2)) / 255.0
    return np.clip(d * 2.2, 0, 1)


def _signature(im, frac: float):
    import numpy as np
    from PIL import Image
    W, H = im.size
    h = max(8, int(H * frac))
    strip = im.crop((0, H - h, W, H))
    bg = _bg_color(strip)
    ink = _ink(strip, bg)
    sig = np.asarray(Image.fromarray((ink * 255).astype("uint8")).resize((SIG_W, max(6, int(SIG_W * frac * 1.25)))),
                     dtype=np.float32) / 255.0
    return sig, bg


def _corr(a, b) -> float:
    import numpy as np
    if a.shape != b.shape:
        return 0.0
    a = a - a.mean(); b = b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 0.0


def _lum(rgb) -> float:
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


REGION = 0.28          # o rodapé é procurado nos 28% de baixo de cada arte


def _region_ink(im):
    """Mapa de tinta (SIG_W de largura) dos 28% de baixo, normalizado por largura; textura fraca do fundo zerada."""
    import numpy as np
    from PIL import Image
    W, H = im.size
    h = int(H * REGION)
    strip = im.crop((0, H - h, W, H))
    bg = _bg_color(strip.crop((0, int(h * 0.55), W, h)))       # fundo medido no pé (onde o rodapé fica)
    ink = _ink(strip, bg)
    ink = np.where(ink < 0.28, 0.0, ink)
    sh = max(8, int(SIG_W * h / W))
    m = np.asarray(Image.fromarray((ink * 255).astype("uint8")).resize((SIG_W, sh), Image.BILINEAR),
                   dtype=np.float32) / 255.0
    return m, bg, H / W


def _win(m, aspect: float, frac: float, shift: float = 0.0):
    """Janela [frac de altura da arte] terminando `shift` acima do pé."""
    rows = m.shape[0]
    per = rows / REGION                       # linhas do mapa por "1.0" de altura da arte
    h = max(4, int(round(frac * per)))
    end = rows - int(round(shift * per))
    return m[max(0, end - h): end]


def detect(images: List[Any], min_votes: int = 2) -> Optional[Dict[str, Any]]:
    """images = PIL RGB. → {frac, members:[idx], score, bgs} ou None se não houver rodapé repetido.
    Tolera o rodapé alguns pixels mais alto/baixo entre artes (busca de deslocamento vertical)."""
    if len(images) < 2:
        return None
    regs = [_region_ink(im) for im in images]
    n = len(regs)
    SHIFTS = [x / 200 for x in range(0, 9)]           # 0..4% de deslocamento
    best_by_frac = {}
    for f in [x / 100 for x in range(6, 19)]:
        C = [[1.0] * n for _ in range(n)]
        for i in range(n):
            a = _win(regs[i][0], regs[i][2], f)
            if float(a.mean()) < 0.01:                # faixa vazia não é rodapé
                for j in range(n):
                    if j != i:
                        C[i][j] = 0.0
                continue
            for j in range(n):
                if j == i:
                    continue
                best = 0.0
                for s in SHIFTS:
                    b = _win(regs[j][0], regs[j][2], f, s)
                    best = max(best, _corr(a, b))
                    b2 = _win(regs[i][0], regs[i][2], f, s)
                    best = max(best, _corr(b2, _win(regs[j][0], regs[j][2], f)))
                C[i][j] = best
        sigs = [(None, r[1]) for r in regs]
        # melhor "semente": a arte cujo rodapé mais se repete
        best = None
        for i in range(n):
            members = [j for j in range(n) if C[i][j] >= 0.55]
            if len(members) < min_votes:
                continue
            score = sum(C[i][j] for j in members if j != i) / max(1, len(members) - 1)
            cand = (len(members), score, i, members)
            if best is None or cand[:2] > best[:2]:
                best = cand
        if best:
            best_by_frac[f] = {"frac": f, "votes": best[0], "score": best[1], "seed": best[2], "members": best[3],
                               "bgs": [sigs[j][1] for j in best[3]]}
    if not best_by_frac:
        return None
    top_votes = max(v["votes"] for v in best_by_frac.values())
    pool = [v for v in best_by_frac.values() if v["votes"] == top_votes]
    top_score = max(v["score"] for v in pool)
    # maior faixa que ainda se repete quase tão bem quanto a melhor → pega o rodapé INTEIRO (fio + textos + logo)
    ok = [v for v in pool if v["score"] >= top_score - 0.06]
    return max(ok, key=lambda v: v["frac"])


def _tight_frac(im, frac: float, bg) -> float:
    """Sobe/desce o topo do recorte até a 1ª linha de tinta do rodapé (fio ou texto) + respiro."""
    import numpy as np
    W, H = im.size
    h = int(H * frac)
    ink = _ink(im.crop((0, H - h, W, H)), bg)
    rows = ink.mean(axis=1)
    hit = np.where(rows > 0.02)[0]
    if not len(hit):
        return frac
    top = max(0, int(hit[0]) - int(H * 0.012))
    return (h - top) / H


def cutout(im, frac: float) -> Tuple[Any, Tuple[int, int, int]]:
    """Recorte do rodapé com o FUNDO removido (RGBA)."""
    import numpy as np
    from PIL import Image
    W, H = im.size
    h = max(8, int(H * frac))
    strip = im.crop((0, H - h, W, H)).convert("RGB")
    bg = _bg_color(strip)
    a = np.asarray(strip, dtype=np.float32)
    bgv = np.array(bg, dtype=np.float32)
    d = np.sqrt(((a - bgv) ** 2).sum(axis=2))
    alpha = np.clip((d - 24.0) / 70.0, 0, 1)              # textura fraca do fundo some; borda das letras fica suave
    # Cores de TINTA reais (preto do texto, laranja da logo...): pixels bem opacos → paleta de até 5 cores.
    solid = a[alpha > 0.85]
    if len(solid) >= 50:
        sample = Image.fromarray(solid[: 200000].reshape(-1, 1, 3).astype("uint8"))
        q = sample.quantize(colors=5, method=2)
        pal = np.array(q.getpalette()[: 15], dtype=np.float32).reshape(-1, 3)
        used = sorted(set(np.asarray(q).ravel().tolist()))
        pal = pal[used]
        # cada pixel recebe a cor de tinta mais próxima da sua cor "desmisturada" do fundo → sem halo nem pontilhado
        al = np.maximum(alpha[..., None], 0.08)
        est = np.clip((a - bgv * (1 - al)) / al, 0, 255)
        dist = ((est[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
        rgb = pal[dist.argmin(axis=2)]
    else:
        rgb = a
    rgba = np.dstack([rgb, alpha * 255]).astype("uint8")
    return Image.fromarray(rgba, "RGBA"), bg


def _trim_top(cut, art_h: int):
    """Do pé para cima: o rodapé termina no 1º VÃO vazio (≥2,5% da arte). O que estiver acima (pedaço da arte) sai."""
    import numpy as np
    a = np.asarray(cut)[..., 3].astype(np.float32) / 255.0
    rows = a.mean(axis=1) > 0.004
    gap_need = max(4, int(art_h * 0.025))
    top, gap, seen = 0, 0, False
    for y in range(len(rows) - 1, -1, -1):
        if rows[y]:
            seen, gap = True, 0
        elif seen:
            gap += 1
            if gap >= gap_need:
                top = y + gap - int(art_h * 0.028)        # mantém um respiro acima do fio/texto
                break
    top = max(0, top)
    cut = cut.crop((0, top, cut.width, cut.height))
    return cut, cut.height / art_h


def _recolor_for(cut, want_dark_bg: bool):
    """Exemplar de fundo claro usado em arte escura (ou vice-versa): tinta NEUTRA (preto/cinza/branco) inverte;
    tinta COLORIDA (logo laranja, ícones) fica como está."""
    import numpy as np
    from PIL import Image
    a = np.asarray(cut, dtype=np.float32).copy()
    rgb = a[..., :3]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    neutral = sat < 0.22
    v = rgb.mean(axis=2)
    target = 255.0 - v
    for c in range(3):
        rgb[..., c] = np.where(neutral, target, rgb[..., c])
    a[..., :3] = rgb
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"), "RGBA")


def build_kit(company_id: str) -> Dict[str, Any]:
    """Detecta o rodapé nas artes de referência e salva os PNGs (claro/escuro). {} se não houver padrão."""
    from PIL import Image
    from ..db_companies import asset_list
    refs = [a for a in (asset_list(company_id, role="brand_reference") or []) if a.get("url")]
    ims, urls = [], []
    for a in refs[:30]:
        try:
            ims.append(Image.open(_media_path(a["url"])).convert("RGB")); urls.append(a["url"])
        except Exception:
            continue
    det = detect(ims, min_votes=2)
    if not det or (det["votes"] == 2 and det["score"] < 0.7):     # só 2 artes iguais → exige semelhança alta
        return {}
    out_dir = os.path.join(MEDIA_ROOT, company_id, "brand")
    os.makedirs(out_dir, exist_ok=True)
    kit: Dict[str, Any] = {"n": det["votes"], "of": len(ims), "score": round(det["score"], 3),
                           "at": datetime.now(timezone.utc).isoformat(), "auto": True, "enabled": True}
    by_pol: Dict[str, List[int]] = {"light": [], "dark": []}
    for j, bg in zip(det["members"], det["bgs"]):
        by_pol["dark" if _lum(bg) < 0.45 else "light"].append(j)
    fr_list = []
    for pol, idxs in by_pol.items():
        if not idxs:
            continue
        j = det["seed"] if det["seed"] in idxs else idxs[0]
        im = ims[j]
        bg = _bg_color(im.crop((0, int(im.height * (1 - det["frac"])), im.width, im.height)))
        fr = _tight_frac(im, det["frac"], bg)
        cut, bg = cutout(im, fr)
        cut, fr = _trim_top(cut, im.height)
        fn = f"footer_{pol}.png"
        cut.save(os.path.join(out_dir, fn))
        kit[pol] = {"url": f"/uploads/{company_id}/brand/{fn}", "frac": round(fr, 4), "bg": "#%02x%02x%02x" % bg,
                    "src": urls[j], "w": im.width}
        fr_list.append(fr)
    kit["frac"] = round(max(fr_list), 4)
    kit["sources"] = [urls[j] for j in det["members"]]
    kit["company_id"] = company_id
    # LAYOUT para reconstrução em alta (logo oficial + textos na fonte + fio + ícone nítido)
    try:
        from ..db_companies import company_get
        pol = "light" if kit.get("light") else "dark"
        cut = Image.open(_media_path(kit[pol]["url"])).convert("RGBA")
        kit["spec"] = extract_spec(cut, (company_get(company_id) or {}).get("name") or "", _hex2rgb(kit[pol]["bg"]))
        kit["spec"]["from"] = pol
    except Exception as exc:
        print(f"[rodape] reconstrução indisponível ({str(exc)[:140]}) → usa o recorte", flush=True)
    return kit


def get_kit(company: Dict[str, Any]) -> Dict[str, Any]:
    design = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}
    kit = design.get("footer_kit") or {}
    if kit.get("auto") and not kit.get("edited") and not _safe_auto_kit(kit):
        return {}
    return kit if kit.get("enabled", True) and (kit.get("light") or kit.get("dark")) else {}


def _safe_auto_kit(kit: Dict[str, Any]) -> bool:
    """Recortes de fotos podem se repetir; só reaproveita assinaturas com estrutura reconhecida.

    Ícones são pequenos (WhatsApp etc.), nunca recortes grandes de pessoas/objetos. Kits manuais
    ficam sob controle do usuário. Também valida kits antigos já salvos, sem alterar o cadastro.
    """
    elements = (kit.get("spec") or {}).get("elements") or []
    if not any(e.get("type") in ("logo", "text") for e in elements):
        return False
    for e in elements:
        width, height = float(e.get("w") or 0), float(e.get("h") or 0)
        if e.get("type") == "icon" and (width > 0.09 or height > 0.05):
            return False
        if e.get("type") == "logo" and (width > 0.5 or height > 0.13):
            return False
    return True


def save_kit(company_id: str, kit: Dict[str, Any]) -> None:
    from ..db_companies import brand_kit_upsert, company_get
    co = company_get(company_id) or {}
    cc = dict(((co.get("brand_kit") or {}).get("creative_config")) or {})
    design = dict(cc.get("design") or {})
    design["footer_kit"] = kit
    cc["design"] = design
    brand_kit_upsert(company_id, {"creative_config": cc})


def ensure(company: Dict[str, Any]) -> Dict[str, Any]:
    design = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}
    kit = design.get("footer_kit")
    if isinstance(kit, dict) and kit.get("at"):
        return get_kit(company)
    kit = build_kit(company["id"]) or {"at": datetime.now(timezone.utc).isoformat(), "none": True}
    save_kit(company["id"], kit)
    return get_kit({"brand_kit": {"creative_config": {"design": {"footer_kit": kit}}}})


def stamp(img_bytes: bytes, kit: Dict[str, Any], typo: Optional[Dict[str, Any]] = None) -> bytes:
    """Cola o rodapé ORIGINAL no pé da arte: escolhe a versão pelo fundo da arte; arte movimentada no pé ganha uma
    base suave da própria cor do fundo para o rodapé ficar legível (como nas artes originais)."""
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    W, H = im.size
    frac = float(kit.get("frac") or 0.1)
    h = int(H * frac)
    zone = im.crop((0, H - h, W, H))
    zbg = _bg_color(zone)
    dark = _lum(zbg) < 0.45
    pol = "dark" if dark else "light"
    cut = None
    if kit.get("spec") and kit.get("company_id"):
        try:                                   # reconstruído na resolução da arte (nítido)
            cut = render_spec(kit["spec"], W, dark, kit["company_id"], typo or {})
            ch = cut.height
        except Exception as exc:
            print(f"[rodape] reconstrução falhou ({str(exc)[:120]}) → recorte", flush=True)
            cut = None
    if cut is None:
        var = kit.get(pol) or kit.get("light" if dark else "dark")
        cut = Image.open(_media_path(var["url"])).convert("RGBA")
        if (var is not kit.get(pol)):
            cut = _recolor_for(cut, dark)
        ch = int(round(cut.height * W / cut.width))
        cut = cut.resize((W, ch), Image.LANCZOS)
    # pé movimentado (foto/textura) → base suave na cor dominante, esfumando para cima
    busy = float(np.asarray(zone.convert("L"), dtype=np.float32).std()) > 9      # qualquer resto da IA no pé (texto fantasma, objeto) some sob a base
    if busy:
        base = Image.new("RGB", (W, ch + int(H * 0.05)), zbg)
        mask = Image.new("L", base.size, 0)
        m = np.zeros((base.height, W), dtype=np.float32)
        ramp = int(H * 0.05)
        m[ramp:, :] = 1.0                    # opaco sob o rodapé: nada da IA vaza (logo/texto fantasma)
        m[:ramp, :] = np.linspace(0, 1.0, ramp)[:, None]
        mask = Image.fromarray((m * 255).astype("uint8"))
        im.paste(base, (0, H - base.height), mask)
    im.paste(cut, (0, H - ch), cut)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


# ───────────────────────── RECONSTRUÇÃO EM ALTA (out/2026) ─────────────────────────
# O recorte vem de uma arte de ~1080 px: ampliado fica borrado. Do recorte guardamos só o LAYOUT (onde está cada
# bloco, texto, cor, peso) e redesenhamos na resolução da arte: logo OFICIAL (arquivo em alta), textos na fonte
# da marca, fio vetorial e ícone com borda nítida.

def _palette_colors(rgba, mask):
    import numpy as np
    px = rgba[..., :3][mask]
    if not len(px):
        return (0, 0, 0)
    return tuple(int(v) for v in np.median(px, axis=0))


def extract_spec(cut, company_name: str, bg) -> Dict[str, Any]:
    """Recorte RGBA do rodapé → elementos {logo, line, text, icon} em coordenadas RELATIVAS (0..1 da largura)."""
    import numpy as np
    import pytesseract
    from PIL import Image
    from scipy import ndimage as ndi
    W, H = cut.size
    a = np.asarray(cut)
    alpha = a[..., 3] > 128
    rel = lambda v: round(v / W, 5)
    els: List[Dict[str, Any]] = []
    # 1) FIOS (finos e largos) saem antes — senão "costuram" todos os blocos num só
    comps, nc = ndi.label(alpha)
    for k, sl in enumerate(ndi.find_objects(comps), 1):
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if ww > 0.3 * W and hh <= max(6, H // 25):
            m = comps == k
            px = a[..., :3][m & (a[..., 3] > 60)].astype(np.float32)
            sat = (px.max(axis=1) - px.min(axis=1)) if len(px) else np.zeros(0)
            lc = tuple(int(v) for v in px[sat >= np.percentile(sat, 85)].mean(axis=0)) if len(px) else (0, 0, 0)
            els.append({"type": "line", "x": rel(sl[1].start), "y": rel(sl[0].start), "w": rel(ww), "h": rel(max(2, hh)),
                        "color": "#%02x%02x%02x" % lc})
            alpha = alpha & ~m
    # 2) CAIXAS geométricas: cada linha de texto / ícone / parte da logo (agrupa letras na horizontal)
    grow = ndi.binary_dilation(alpha, structure=np.ones((1, 3), bool), iterations=max(3, W // 110))
    grow = ndi.binary_dilation(grow, structure=np.ones((3, 1), bool), iterations=1)
    lab, n = ndi.label(grow)
    boxes = []
    for k, sl in enumerate(ndi.find_objects(lab), 1):
        m = (lab == k) & alpha
        ys, xs = np.where(m)
        if len(xs) < 25:
            continue
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    boxes.sort(key=lambda bb: (bb[0] // max(1, W // 8), bb[1]))
    flat = Image.new("RGB", cut.size, bg); flat.paste(cut, (0, 0), cut)
    kinds = _classify_boxes(flat, boxes, company_name)
    logo_boxes = [bb for bb, kd in zip(boxes, kinds) if kd["tipo"] == "logo"]
    if logo_boxes:
        lx0, ly0 = min(q[0] for q in logo_boxes), min(q[1] for q in logo_boxes)
        lx1, ly1 = max(q[2] for q in logo_boxes), max(q[3] for q in logo_boxes)
        m = np.zeros_like(alpha); m[ly0:ly1, lx0:lx1] = True; m &= alpha
        els.append({"type": "logo", "x": rel(lx0), "y": rel(ly0), "w": rel(lx1 - lx0), "h": rel(ly1 - ly0),
                    "colors": _logo_signature(a, m)})
    for (x0, y0, x1, y1), kd in zip(boxes, kinds):
        if kd["tipo"] == "logo":
            continue
        m = np.zeros_like(alpha); m[y0:y1, x0:x1] = True; m &= alpha
        if kd["tipo"] == "texto" and kd.get("texto"):
            els.append({"type": "text", "text": kd["texto"], "x": rel(x0), "y": rel(y0), "w": rel(x1 - x0),
                        "h": rel(y1 - y0), "color": "#%02x%02x%02x" % _palette_colors(a, m),
                        "ink": round(float(m.sum()) / max(1, (x1 - x0) * (y1 - y0)), 4)})
        else:
            els.append(_icon_el(cut, x0, y0, x1, y1, W))
    # fio fino sai "lavado" (mistura com o fundo): puxa para a cor saturada de mesmo matiz que existe no rodapé
    import colorsys
    solid = a[..., :3][a[..., 3] > 220].astype(np.float32)
    if len(solid):
        mx, mn = solid.max(axis=1), solid.min(axis=1)
        vivid = solid[(mx - mn) / np.maximum(mx, 1) > 0.6]
        for e in els:
            if e["type"] != "line" or not len(vivid):
                continue
            r, g, b = _hex2rgb(e["color"])
            h0 = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0]
            hues = np.array([colorsys.rgb_to_hsv(*(v / 255))[0] for v in vivid[:: max(1, len(vivid) // 400)]])
            vv = vivid[:: max(1, len(vivid) // 400)]
            dh = np.minimum(np.abs(hues - h0), 1 - np.abs(hues - h0))
            near = vv[dh < 0.06]
            if len(near):
                e["color"] = "#%02x%02x%02x" % tuple(int(c) for c in np.median(near, axis=0))
    return {"w": W, "h": H, "ratio": round(H / W, 5), "elements": els}


def _classify_boxes(flat, boxes, company_name: str) -> List[Dict[str, Any]]:
    """Visão classifica cada caixa numerada: texto (com transcrição exata), ícone ou logo da marca."""
    import base64
    from PIL import ImageDraw, ImageFont
    from .visual_dna import _vision
    from .ai import extract_json
    k = 3
    big = flat.resize((flat.width * k, flat.height * k)).convert("RGB")
    d = ImageDraw.Draw(big)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/brand/Poppins-Bold.ttf", 26)
    except Exception:
        f = None
    for i, (x0, y0, x1, y1) in enumerate(boxes, 1):
        d.rectangle((x0 * k - 3, y0 * k - 3, x1 * k + 3, y1 * k + 3), outline=(0, 160, 255), width=2)
        d.text((x0 * k - 3, max(0, y0 * k - 30)), str(i), fill=(0, 120, 255), font=f)
    buf = io.BytesIO(); big.save(buf, "JPEG", quality=90)
    content = [{"type": "text", "text": (
        f"Rodapé de uma arte da marca {company_name}. Cada caixa azul numerada é um elemento. Para CADA número diga "
        "o tipo: 'logo' (qualquer parte da logo/marca da empresa, incluindo símbolo, nome estilizado e slogan da "
        "logo), 'texto' (texto comum — transcreva EXATAMENTE, com maiúsculas, acentos, pontuação e números) ou "
        "'icone' (desenho/ícone que não é logo da marca). Responda SÓ JSON: "
        '{"itens":[{"n":1,"tipo":"logo|texto|icone","texto":"..."}]}')},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]
    res = extract_json(_vision(content, max_tokens=700)) or {}
    by_n = {int(it.get("n", 0)): it for it in (res.get("itens") or []) if str(it.get("n", "")).isdigit()}
    out = []
    for i in range(1, len(boxes) + 1):
        it = by_n.get(i) or {}
        tipo = str(it.get("tipo") or "icone").lower()
        tipo = "icone" if tipo.startswith("ic") else ("logo" if tipo.startswith("logo") else "texto")
        out.append({"tipo": tipo, "texto": str(it.get("texto") or "").strip()})
    return out


def _icon_el(cut, x0, y0, x1, y1, W) -> Dict[str, Any]:
    import base64
    pad = 2
    crop = cut.crop((max(0, x0 - pad), max(0, y0 - pad), min(cut.width, x1 + pad), min(cut.height, y1 + pad)))
    buf = io.BytesIO(); crop.save(buf, "PNG")
    return {"type": "icon", "x": round((x0 - pad) / W, 5), "y": round((y0 - pad) / W, 5),
            "w": round(crop.width / W, 5), "h": round(crop.height / W, 5),
            "png": base64.b64encode(buf.getvalue()).decode()}


def _logo_signature(a, mask) -> List[str]:
    """Cores principais da logo no rodapé (para escolher/recolorir a versão oficial igual)."""
    from PIL import Image
    px = a[..., :3][mask]
    if len(px) < 10:
        return []
    im = Image.fromarray(px.reshape(-1, 1, 3).astype("uint8")).quantize(colors=3, method=2)
    pal = im.getpalette()[:9]
    counts = sorted(im.getcolors(), reverse=True)
    return ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _c, i in counts]


def _hex2rgb(h: str):
    h = (h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _crisp_icon(png_b64: str, tw: int, th: int):
    """Ícone recortado (baixa resolução) → ampliado com borda NÍTIDA: alfa ampliado + curva dura; cor = cor de tinta."""
    import base64
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    up = im.resize((tw, th), Image.LANCZOS)
    al = np.asarray(up.split()[3].filter(ImageFilter.GaussianBlur(max(0.6, tw / 260)))).astype(np.float32) / 255
    al = np.clip((al - 0.42) / 0.16, 0, 1)                       # borda dura e lisa
    rgb = np.asarray(up.convert("RGB")).astype(np.float32)
    # cor sólida por região: cada pixel recebe a cor de tinta (paleta do ícone) mais próxima
    solid = a[..., :3][a[..., 3] > 200]
    if len(solid) >= 10:
        q = Image.fromarray(solid.reshape(-1, 1, 3).astype("uint8")).quantize(colors=3, method=2)
        pal = np.array(q.getpalette()[:9], dtype=np.float32).reshape(-1, 3)
        dist = ((rgb[:, :, None, :] - pal[None, None]) ** 2).sum(axis=3)
        rgb = pal[dist.argmin(axis=2)]
    return Image.fromarray(np.dstack([rgb, al * 255]).astype("uint8"), "RGBA")


def _pick_official_logo(company_id: str, colors: List[str], dark: bool):
    """Versão oficial (arquivo em alta) mais parecida com a do rodapé original; ajusta texto neutro ao fundo."""
    import numpy as np
    from PIL import Image
    from ..db_companies import asset_list_logos
    want = [_hex2rgb(c) for c in (colors or [])]
    best, best_d = None, 1e18
    for lg in asset_list_logos(company_id) or []:
        try:
            im = Image.open(_media_path(lg["url"])).convert("RGBA")
        except Exception:
            continue
        im.thumbnail((1200, 1200))
        for inv in (False, True):
            cand = _recolor_for(im, dark) if inv else im
            a = np.asarray(cand).astype(np.float32)
            px = a[..., :3][a[..., 3] > 200]
            if not len(px):
                continue
            # legível no fundo?
            lum = float(np.mean(px @ np.array([0.299, 0.587, 0.114]))) / 255
            if not want:
                d = abs(lum - (0.9 if dark else 0.1))
            else:
                d = 0.0
                for c in want:
                    d += float(np.min(((px - np.array(c)) ** 2).sum(axis=1)))
                # cores do logo que NÃO existem no original pesam também
                q = Image.fromarray(px.reshape(-1, 1, 3).astype("uint8")).quantize(colors=3, method=2)
                pal = np.array(q.getpalette()[:9], dtype=np.float32).reshape(-1, 3)
                for c in pal:
                    d += float(min(((np.array(w) - c) ** 2).sum() for w in want))
            if d < best_d:
                best, best_d = (lg["url"], inv), d
    if not best:
        return None
    im = Image.open(_media_path(best[0])).convert("RGBA")
    return _recolor_for(im, dark) if best[1] else im


def render_spec(spec: Dict[str, Any], W: int, dark: bool, company_id: str, typo: Dict[str, Any]):
    """Desenha o rodapé na largura W (RGBA transparente). Cores neutras invertem em fundo escuro."""
    from PIL import Image, ImageDraw, ImageFont
    from . import brand_fonts as bfo
    H = int(round(spec["ratio"] * W))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    font_file = ((typo or {}).get("body") or (typo or {}).get("title") or {}).get("family")

    def col(hexc: str):
        r, g, b = _hex2rgb(hexc)
        mx, mn = max(r, g, b), min(r, g, b)
        neutral = (mx - mn) / max(mx, 1) < 0.22
        light_src = (r + g + b) / 3 > 128
        if neutral and dark and not light_src:
            v = 255 - (r + g + b) // 3
            return (v, v, v, 255)
        return (r, g, b, 255)

    for e in spec["elements"]:
        x, y, w, h = (int(round(e[k] * W)) for k in ("x", "y", "w", "h"))
        if e["type"] == "line":
            d.rectangle((x, y, x + w, y + max(1, h)), fill=col(e["color"]))
        elif e["type"] == "icon":
            out.alpha_composite(_crisp_icon(e["png"], max(1, w), max(1, h)), (x, y))
        elif e["type"] == "logo":
            want = []
            for c in e.get("colors") or []:            # em fundo escuro, as cores NEUTRAS da logo original invertem
                r, g, b = _hex2rgb(c)
                if dark and (max(r, g, b) - min(r, g, b)) / max(1, max(r, g, b)) < 0.22:
                    r = g = b = 255 - (r + g + b) // 3
                want.append("#%02x%02x%02x" % (r, g, b))
            lg = _pick_official_logo(company_id, want, dark)
            if lg is None:
                continue
            bb = lg.getbbox() or (0, 0, lg.width, lg.height)
            lg = lg.crop(bb)
            s = min(w / lg.width, h / lg.height)
            lg = lg.resize((max(1, int(lg.width * s)), max(1, int(lg.height * s))), Image.LANCZOS)
            out.alpha_composite(lg, (x + (w - lg.width) // 2, y + (h - lg.height) // 2))
        elif e["type"] == "text":
            fam = font_file or "Exo 2"
            # peso: o que reproduz a densidade de tinta do original; tamanho: largura igual à do original
            best = None
            for wt in (400, 500, 600, 700, 800):
                p = bfo.fetch_ttf(fam, wt, bfo._dir())
                if not p:
                    continue
                f = ImageFont.truetype(p, 100)
                bx = d.textbbox((0, 0), e["text"], font=f)
                size = max(6, int(100 * w / max(1, bx[2] - bx[0])))
                f = ImageFont.truetype(p, size)
                bx = d.textbbox((0, 0), e["text"], font=f)
                tmp = Image.new("L", (bx[2] - bx[0] + 4, bx[3] - bx[1] + 4), 0)
                ImageDraw.Draw(tmp).text((-bx[0] + 2, -bx[1] + 2), e["text"], font=f, fill=255)
                import numpy as np
                ink = float((np.asarray(tmp) > 128).sum()) / max(1, (bx[2] - bx[0]) * (bx[3] - bx[1]))
                hdiff = abs((bx[3] - bx[1]) - h) / max(1, h)
                score = abs(ink - e.get("ink", ink)) + 0.6 * hdiff
                if best is None or score < best[0]:
                    best = (score, f, bx)
            if best:
                _s, f, bx = best
                d.text((x - bx[0], y - bx[1]), e["text"], font=f, fill=col(e["color"]))
    return out
