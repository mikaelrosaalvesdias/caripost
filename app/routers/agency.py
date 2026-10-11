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
    cfg = ag.agency_cfg(co)
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
