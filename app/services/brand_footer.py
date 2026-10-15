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
    return kit


def get_kit(company: Dict[str, Any]) -> Dict[str, Any]:
    design = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}
    kit = design.get("footer_kit") or {}
    return kit if kit.get("enabled", True) and (kit.get("light") or kit.get("dark")) else {}


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


def stamp(img_bytes: bytes, kit: Dict[str, Any]) -> bytes:
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
