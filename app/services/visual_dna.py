"""DNA VISUAL por cliente (out/2026): a "personalidade" das artes do provedor, extraída das artes de referência
(as que ele já publica — upload ou Instagram) + logo. Vira instrução fixa do Estúdio IA para as artes saírem com a
cara DELE (tipografia, posicionamento, elementos, fotografia), e não com a cara genérica de IA.

Salvo em brand_kit.creative_config.design.visual_dna = {text, data, sources, at}. Editável à mão."""
from __future__ import annotations

import base64
import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

MEDIA_ROOT = os.environ.get("CARIPOST_MEDIA_ROOT") or "/media"

PROMPT = (
    "Você é diretor de arte sênior de uma agência brasileira. As imagens são artes reais publicadas pela marca "
    "{name} ({segment}) e a logo dela. Extraia o DNA VISUAL para que novas artes pareçam feitas pelo MESMO designer "
    "dessa marca — e NÃO com a cara genérica de IA. Seja específico e prático. Responda SÓ JSON:\n"
    '{{"tipografia":"famílias e estilo dos títulos e do texto de apoio (serifada/condensada/arredondada/grotesca/manuscrita, '
    'peso, caixa alta ou baixa, itálico, espaçamento) + 2 ou 3 fontes REAIS parecidas (Google Fonts) — evite Poppins/Montserrat '
    'se a marca não usa",'
    '"composicao":"onde costumam ficar título, logo, CTA e foto; alinhamento; grid; margens; densidade de texto",'
    '"elementos":"formas, molduras, faixas, texturas, ícones, adesivos, recortes, mascote/personagem — o que se repete",'
    '"fotografia":"tipo de imagem (foto real, 3D, ilustração), pessoas, cenários, luz, tratamento de cor",'
    '"cores":"como a paleta é usada (fundo, destaque, texto), proporção e contraste",'
    '"tom":"personalidade visual em poucas palavras",'
    '"assinatura":"os 3 traços que tornam a marca reconhecível",'
    '"evitar":"o que NÃO combina com essa marca"}}\n'
    "Se houver poucas artes, deduza com cuidado a partir da logo e do segmento e diga isso em 'tom'."
)


def _media_path(url: str) -> str:
    rel = (url or "").split("?")[0]
    if rel.startswith("/uploads/"):
        rel = rel[len("/uploads/"):]
    return os.path.join(MEDIA_ROOT, rel)


def _thumb(raw: bytes, side: int = 768) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def collect_sources(company_id: str, limit: int = 6) -> Dict[str, Any]:
    from ..db_companies import asset_list
    refs = [a for a in (asset_list(company_id, role="brand_reference") or []) if a.get("url")]
    logos = [a for a in (asset_list(company_id) or []) if (a.get("meta") or {}).get("role") == "logo"
             and not a.get("product_id") and a.get("url")]
    logos.sort(key=lambda a: not (a.get("meta") or {}).get("is_primary"))
    imgs, used = [], []
    for a in refs[:limit] + logos[:1]:
        p = _media_path(a["url"])
        try:
            imgs.append(_thumb(open(p, "rb").read())); used.append(a["url"])
        except Exception:
            continue
    return {"images": imgs, "urls": used, "n_refs": min(len(refs), limit)}


def _vision(content: List[Dict[str, Any]], max_tokens: int = 1400) -> str:
    from .ai import _omniroute_base, _omniroute_key
    import time as _t
    msgs = [{"role": "user", "content": content}]
    for model in ("cc/claude-opus-4-8", "cx/gpt-5.6-sol", "cc/claude-haiku-4-5-20251001",
                  "cc/claude-opus-4-8", "cx/gpt-5.6-sol"):    # 2ª rodada: instabilidade momentânea do gateway
        try:
            with httpx.Client(timeout=httpx.Timeout(150.0, connect=10.0)) as c:
                r = c.post(_omniroute_base() + "/chat/completions",
                           headers={"Authorization": "Bearer " + (_omniroute_key() or "x"), "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": max_tokens, "temperature": 0.2, "messages": msgs})
            if r.status_code >= 400:
                print(f"[dna] {model} HTTP {r.status_code}: {r.text[:120]}", flush=True)
                _t.sleep(3)
                continue
            txt = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
            if txt:
                return txt
        except Exception as exc:
            print(f"[dna] {model} falhou: {str(exc)[:120]}", flush=True)
            _t.sleep(3)
            continue
    raise ValueError("a visão não respondeu agora")


def to_text(d: Dict[str, Any]) -> str:
    rot = [("tipografia", "Tipografia"), ("composicao", "Composição"), ("elementos", "Elementos"),
           ("fotografia", "Fotografia"), ("cores", "Cores"), ("tom", "Tom"), ("assinatura", "Assinatura"), ("evitar", "Evitar")]
    return " ".join(f"{lbl}: {str(d.get(k)).strip()}." for k, lbl in rot if d.get(k))[:2200]


def analyze(company: Dict[str, Any]) -> Dict[str, Any]:
    from .ai import extract_json
    src = collect_sources(company["id"])
    content: List[Dict[str, Any]] = [{"type": "text", "text": PROMPT.format(name=company.get("name") or "",
                                                                          segment=company.get("segment") or "")}]
    for b in src["images"]:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}})
    data = extract_json(_vision(content)) or {}
    if not data:
        raise ValueError("a análise não devolveu o DNA")
    return {"text": to_text(data), "data": data, "sources": src["urls"], "n_refs": src["n_refs"],
            "at": datetime.now(timezone.utc).isoformat()}


def save(company_id: str, dna: Dict[str, Any]) -> None:
    from ..db_companies import brand_kit_upsert, company_get
    co = company_get(company_id) or {}
    cc = dict(((co.get("brand_kit") or {}).get("creative_config")) or {})
    design = dict(cc.get("design") or {})
    design["visual_dna"] = dna
    cc["design"] = design
    brand_kit_upsert(company_id, {"creative_config": cc})


def ensure(company: Dict[str, Any]) -> Dict[str, Any]:
    """DNA salvo → usa. Sem DNA e com artes de referência → analisa uma vez e salva."""
    design = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}
    dna = design.get("visual_dna") or {}
    if dna.get("text"):
        return dna
    if not collect_sources(company["id"])["n_refs"]:
        return {}
    dna = analyze(company)
    save(company["id"], dna)
    return dna


def prompt_block(dna: Dict[str, Any]) -> str:
    t = (dna or {}).get("text") or ""
    if not t:
        return ""
    return (" DNA VISUAL DESTE CLIENTE (tirado das artes que ele já publica — PRIORIDADE sobre qualquer direção genérica; "
            "a peça tem que parecer feita pelo designer DELE): " + t + " Tipografia: siga a do DNA; NUNCA a sans "
            "geométrica pesada genérica que toda IA usa, a menos que o DNA diga que a marca usa. ")
