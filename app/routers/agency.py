"""Agência automática — API do calendário editorial mensal (etapa 1: ideias + legendas)."""
from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_companies import brand_kit_upsert, company_get
from ..main_utils import company_access_denied as __cad__
from ..services import agency as ag

router = APIRouter(prefix="/api/agency", tags=["agency"])


def _auth(request: Request, company_id: str):
    from ..main_utils import require_api_key
    err = require_api_key(request)
    if err:
        return err
    return __cad__(request, company_id) if company_id else None


def _next_month() -> str:
    t = date.today()
    return f"{t.year + (t.month == 12):04d}-{(t.month % 12) + 1:02d}"


def _plan_or_404(request: Request, plan_id: str):
    plan = ag.plan_get(plan_id)
    if not plan:
        return None, JSONResponse({"detail": "Calendário não encontrado"}, status_code=404)
    return plan, _auth(request, plan["company_id"])


def _item_or_404(request: Request, item_id: str):
    item = ag.item_get(item_id)
    if not item:
        return None, JSONResponse({"detail": "Peça não encontrada"}, status_code=404)
    return item, _auth(request, item["company_id"])


@router.get("/{company_id}/config")
def get_config(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"config": ag.agency_cfg(co), "defaults": ag.AGENCY_DEFAULTS,
            "override": ((co.get("brand_kit") or {}).get("creative_config") or {}).get("agency") or {}}


@router.put("/{company_id}/config")
async def save_config(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    agency = body.get("agency") if isinstance(body.get("agency"), dict) else body
    cc = dict(((co.get("brand_kit") or {}).get("creative_config")) or {})
    cc["agency"] = agency
    brand_kit_upsert(company_id, {"creative_config": cc})
    return {"ok": True, "config": ag.agency_cfg(company_get(company_id))}


@router.get("/{company_id}/plans")
def list_plans(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    return {"plans": ag.plan_list(company_id), "next_month": _next_month()}


@router.post("/{company_id}/plans")
async def create_plan(company_id: str, request: Request):
    """Gera o calendário do mês em segundo plano (lotes de IA). Front faz polling em GET /plans/{id}."""
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    month = (body.get("month") or _next_month()).strip()[:7]
    try:
        y, m = map(int, month.split("-"))
        date(y, m, 1)
    except Exception:
        return JSONResponse({"detail": "month deve ser AAAA-MM"}, status_code=422)
    cfg = ag.agency_cfg(co)     # linha editorial sob medida (1ª vez) é feita DENTRO do job — evita o limite de 100s
    if isinstance(body.get("mix"), dict):
        cfg["mix"] = body["mix"]
    slots = ag.build_slots(y, m, cfg, ag.month_dates(y, m, co))
    if not slots:
        return JSONResponse({"detail": "Não há dias disponíveis nesse mês."}, status_code=422)
    plan = ag.plan_create(company_id, month, cfg)
    ag.start_plan_generation(plan["id"])
    return {"plan": plan, "slots": len(slots)}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, request: Request):
    plan, err = _plan_or_404(request, plan_id)
    if err:
        return err
    plan["dates"] = ag.month_dates(*map(int, plan["month"].split("-")), company_get(plan["company_id"]))
    return {"plan": plan}


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: str, request: Request):
    plan, err = _plan_or_404(request, plan_id)
    if err:
        return err
    ag.plan_delete(plan_id)
    return {"ok": True}


@router.post("/plans/{plan_id}/approve-ideas")
def approve_all_ideas(plan_id: str, request: Request):
    plan, err = _plan_or_404(request, plan_id)
    if err:
        return err
    n = 0
    for it in plan["items"]:
        if it["stage"] == "idea" and it.get("title"):
            ag.item_update(it["id"], {"stage": "idea_ok"})
            n += 1
    return {"approved": n, "plan": ag.plan_get(plan_id)}


_EDITABLE = ("slot_at", "format", "pillar", "product", "title", "angle", "copy", "hashtags", "art_brief", "review_comment")


@router.patch("/items/{item_id}")
async def update_item(item_id: str, request: Request):
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    body = await request.json()
    data = {k: body[k] for k in _EDITABLE if k in body}
    if "format" in data and data["format"] not in ag.FORMAT_LABEL:
        return JSONResponse({"detail": "formato inválido"}, status_code=422)
    stage = body.get("stage")
    if stage:
        if stage not in ("idea", "idea_ok", "idea_rejected"):
            return JSONResponse({"detail": "etapa inválida"}, status_code=422)
        if item["stage"] not in ("idea", "idea_ok", "idea_rejected"):
            return JSONResponse({"detail": "Esta peça já está na etapa de arte."}, status_code=409)
        data["stage"] = stage
    return {"item": ag.item_update(item_id, data)}


@router.post("/items/{item_id}/regenerate")
async def regenerate_item(item_id: str, request: Request):
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if item["stage"] not in ("idea", "idea_ok", "idea_rejected"):
        return JSONResponse({"detail": "Esta peça já está na etapa de arte."}, status_code=409)
    try:
        out = await asyncio.to_thread(ag.regenerate_item_sync, item_id, (body.get("comment") or "").strip())
    except Exception as exc:
        return JSONResponse({"detail": f"Não consegui refazer: {exc}"}, status_code=502)
    return {"item": out}


# ── Marco B: artes ──────────────────────────────────────────────────────────────────────────────

@router.post("/plans/{plan_id}/produce")
async def produce_plan(plan_id: str, request: Request):
    """Enfileira a produção das artes das ideias APROVADAS (ou das peças informadas em item_ids)."""
    plan, err = _plan_or_404(request, plan_id)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    n = ag.queue_production(plan_id, body.get("item_ids") or None)
    return {"queued": n, "plan": ag.plan_get(plan_id)}


@router.post("/items/{item_id}/produce")
async def produce_one(item_id: str, request: Request):
    """Gera (ou refaz) a arte de uma peça; comentário opcional vira instrução."""
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if item["stage"] not in ("idea_ok", "art", "art_rejected", "art_ok"):
        return JSONResponse({"detail": "Aprove a ideia antes de gerar a arte."}, status_code=409)
    if (body.get("comment") or "").strip():
        ag.item_update(item_id, {"review_comment": body["comment"].strip()})
    ag.item_update(item_id, {"stage": "art_queued", "error": None})
    ag.ensure_worker()
    return {"item": ag.item_get(item_id)}


@router.post("/items/{item_id}/approve-art")
async def approve_art(item_id: str, request: Request):
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    try:
        out = await ag.approve_art(item_id)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    return {"item": out}


@router.post("/items/{item_id}/reject-art")
async def reject_art(item_id: str, request: Request):
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if item["stage"] != "art":
        return JSONResponse({"detail": "A peça não está com arte para aprovar."}, status_code=409)
    return {"item": ag.item_update(item_id, {"stage": "art_rejected", "review_comment": (body.get("comment") or "").strip() or None})}


@router.post("/tick")
async def run_tick(request: Request):
    err = _auth(request, "")
    if err:
        return err
    return {"stats": await ag.tick()}


# ── Multi-cliente ───────────────────────────────────────────────────────────────────────────────

@router.get("/overview")
def agency_overview(request: Request):
    from ..main_utils import require_api_key, scoped_company_ids
    err = require_api_key(request)
    if err:
        return err
    scoped = scoped_company_ids(request)
    return {"clients": ag.overview(list(scoped) if scoped is not None else None), "next_month": _next_month()}


@router.post("/{company_id}/suggest-config")
async def suggest_config(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        return {"suggestion": await asyncio.to_thread(ag.suggest_config, co)}
    except Exception as exc:
        return JSONResponse({"detail": f"Não consegui sugerir agora: {exc}"}, status_code=502)


@router.post("/items/{item_id}/refresh-art")
def refresh_art(item_id: str, request: Request):
    """Depois de 'Trazer do Canva': sincroniza as telas da peça com o post (versão editada)."""
    item, err = _item_or_404(request, item_id)
    if err:
        return err
    from ..db_companies import post_get
    post = post_get(item.get("post_id") or "") or {}
    urls = (post.get("meta") or {}).get("carousel_urls") or []
    if urls:
        meta = dict(item.get("meta") or {}); meta["slides"] = urls
        meta["slide_previews"] = (post.get("meta") or {}).get("carousel_preview_urls") or urls
        item = ag.item_update(item_id, {"meta": meta})
    return {"item": item}


# ── DNA visual do cliente ────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/visual-dna")
def get_visual_dna(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    from ..services import visual_dna as vd
    dna = (((co.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}).get("visual_dna") or {}
    return {"dna": dna, "n_refs": vd.collect_sources(company_id)["n_refs"]}


@router.post("/{company_id}/visual-dna")
async def analyze_visual_dna(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    from ..services import visual_dna as vd
    try:
        dna = await asyncio.to_thread(vd.analyze, co)
    except Exception as exc:
        return JSONResponse({"detail": f"Não consegui analisar agora: {exc}"}, status_code=424)
    vd.save(company_id, dna)
    return {"dna": dna}


@router.put("/{company_id}/visual-dna")
async def edit_visual_dna(company_id: str, request: Request):
    err = _auth(request, company_id)
    if err:
        return err
    body = await request.json()
    from ..services import visual_dna as vd
    co = company_get(company_id) or {}
    old = (((co.get("brand_kit") or {}).get("creative_config") or {}).get("design") or {}).get("visual_dna") or {}
    dna = dict(old, text=(body.get("text") or "").strip()[:3000], edited=True)
    vd.save(company_id, dna)
    return {"dna": dna}
