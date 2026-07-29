from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_companies import asset_list_logos, company_get
from ..services.template_video import (
    UPLOAD_DIR,
    UPLOAD_URL_PREFIX,
    list_template_video_templates,
    render_template_video,
)


router = APIRouter(prefix="/api/template-video", tags=["template-video"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _first_logo_path(company_id: str) -> Optional[str]:
    for asset in asset_list_logos(company_id) or []:
        url = asset.get("url") or ""
        if not url.startswith(UPLOAD_URL_PREFIX) or url.lower().endswith(".svg"):
            continue
        path = os.path.abspath(os.path.join(UPLOAD_DIR, url[len(UPLOAD_URL_PREFIX):].lstrip("/")))
        root = os.path.abspath(UPLOAD_DIR)
        if (path.startswith(root + os.sep) or path == root) and os.path.exists(path):
            return path
    return None


@router.get("/templates")
def templates(request: Request):
    err = _auth(request)
    if err:
        return err
    return {"templates": list_template_video_templates()}


def _fallback_suggestion(company: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    subject = (body.get("subject") or body.get("theme") or body.get("title") or "conteudo da marca").strip()
    cta = (body.get("cta") or "Fale com a gente").strip()
    template_id = (body.get("template_id") or "brand_pulse_15s").strip()
    if template_id == "meme_vs_10s":
        return {
            "template_id": template_id,
            "title": subject,
            "left_label": "SEM SOLUCAO",
            "left_text": "travando, frustrando e perdendo tempo",
            "right_label": company.get("name") or "MARCA",
            "right_text": "mais controle, menos atrito e experiencia melhor",
            "punchline": subject,
            "cta": cta,
            "duration_sec": int(body.get("duration_sec") or 10),
        }
    return {
        "template_id": template_id,
        "eyebrow": company.get("name") or "Caripost",
        "title": subject[:80],
        "subtitle": "Uma mensagem direta, visual e fiel a marca.",
        "cta": cta,
        "offer": body.get("offer") or "condicao especial",
        "quote": "Marca consistente, mensagem clara e criativo rapido de aprovar.",
        "stat": "token zero no render",
        "benefits": ["identidade preservada", "ritmo de video", "CTA claro"],
        "scenes": [subject, "A marca aparece com clareza", "O CTA fecha a mensagem"],
        "duration_sec": int(body.get("duration_sec") or 12),
    }


@router.post("/suggest")
async def suggest(request: Request):
    err = _auth(request)
    if err:
        return err
    body = await request.json()
    company_id = (body.get("company_id") or "").strip()
    if not company_id:
        return JSONResponse({"detail": "company_id obrigatorio"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa nao encontrada"}, status_code=404)
    subject = (body.get("subject") or body.get("theme") or "").strip()
    if not subject:
        return JSONResponse({"detail": "subject/theme obrigatorio"}, status_code=422)

    fallback = _fallback_suggestion(company, body)
    try:
        from ..services.ai import cheap_text_config, complete_ai, extract_json, get_ai_config

        config = cheap_text_config(get_ai_config())
        if not config:
            return {"ok": True, "suggestion": fallback, "source": "fallback"}
        brand = company.get("brand_kit") or {}
        colors = brand.get("colors") or {}
        system = (
            "Voce e um diretor criativo de social video. Responda SOMENTE JSON valido. "
            "Crie copy curta para video vertical de marca. Nao invente preco, data, promessa legal ou numero factual. "
            "Preserve a identidade, mas gere uma ideia visual forte, brasileira, moderna e facil de aprovar."
        )
        user = {
            "empresa": company.get("name"),
            "segmento": company.get("segment"),
            "tom": brand.get("voice") or "",
            "cores": colors,
            "template_id": body.get("template_id") or "auto",
            "objetivo": body.get("objective") or body.get("objetivo") or "engajar",
            "assunto": subject,
            "cta": body.get("cta") or "",
            "formato": body.get("format") or "story",
            "saida_obrigatoria": {
                "template_id": "um dos ids enviados ou o mesmo solicitado",
                "eyebrow": "ate 36 chars",
                "title": "ate 72 chars",
                "subtitle": "ate 110 chars",
                "cta": "ate 48 chars",
                "offer": "opcional",
                "quote": "opcional",
                "stat": "opcional sem inventar numeros",
                "benefits": ["3 itens curtos"],
                "scenes": ["3 cenas curtas"],
                "left_label": "para meme_vs",
                "left_text": "para meme_vs",
                "right_label": "para meme_vs",
                "right_text": "para meme_vs",
                "punchline": "para meme_vs",
                "duration_sec": 8,
            },
        }
        raw = complete_ai(config, system, json.dumps(user, ensure_ascii=False), 1000)
        data = extract_json(raw) or {}
        suggestion = {**fallback, **{k: v for k, v in data.items() if v not in (None, "", [])}}
        if "template_id" not in suggestion:
            suggestion["template_id"] = fallback["template_id"]
        return {"ok": True, "suggestion": suggestion, "source": "ai_text"}
    except Exception as exc:
        return {"ok": True, "suggestion": fallback, "source": "fallback", "warning": str(exc)[:180]}


@router.post("/render")
async def render(request: Request):
    err = _auth(request)
    if err:
        return err
    body = await request.json()
    company_id = (body.get("company_id") or "").strip()
    if not company_id:
        return JSONResponse({"detail": "company_id obrigatorio"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa nao encontrada"}, status_code=404)
    if not (body.get("title") or body.get("headline")):
        return JSONResponse({"detail": "title/headline obrigatorio"}, status_code=422)
    try:
        result = render_template_video(company=company, payload=body, logo_path=_first_logo_path(company_id))
    except Exception as exc:
        return JSONResponse({"detail": "Falha ao renderizar template: " + str(exc)[:300]}, status_code=502)
    return {
        "ok": True,
        "job_id": result.job_id,
        "artifact_type": result.artifact_type,
        "url": result.url,
        "preview_url": result.preview_url,
        "manifest_url": result.manifest_url,
        "frames": result.frames,
        "mp4_url": result.mp4_url,
        "fallback_reason": result.fallback_reason,
        "width": result.width,
        "height": result.height,
        "duration_sec": result.duration_sec,
        "token_cost": 0,
        "engine": "template_video_poc",
    }
