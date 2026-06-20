"""
Companies (Clientes) router — CRUD, brand kit, competitors, assets.
Mirrors caripost-web's company management features.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..db_companies import (
    company_list, company_get, company_create, company_update, company_delete,
    brand_kit_get, brand_kit_upsert,
    competitor_list, competitor_create, competitor_delete,
    asset_list, asset_create, asset_delete,
)
from ..db import settings_get

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Companies CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_companies(request: Request, active: Optional[bool] = None, limit: int = 200):
    err = _api_key_required(request)
    if err:
        return err
    companies = company_list(active_only=active if active is not None else False, limit=limit)
    return {"companies": companies}


@router.get("/{company_id}")
def get_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    # attach competitors and assets
    company["competitors"] = competitor_list(company_id)
    company["references"] = asset_list(company_id, role="brand_reference")
    return {"company": company}


@router.post("")
async def create_company(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    if not body.get("name"):
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    # parse socials
    socials: Dict[str, str] = {}
    for key in ("instagram", "facebook", "tiktok"):
        val = body.get(f"social_{key}")
        if val:
            socials[key] = val
    # parse inline competitors
    competitors = body.get("competitors") or []
    data = {
        "name": body.get("name"),
        "segment": body.get("segment"),
        "city": body.get("city"),
        "state": body.get("state"),
        "website": body.get("website"),
        "phone": body.get("phone"),
        "email": body.get("email"),
        "socials": socials,
        "notes": body.get("notes"),
        "competitors": competitors,
    }
    company = company_create(data)
    return {"company": company}


@router.put("/{company_id}")
async def update_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    # merge socials
    socials = existing.get("socials") or {}
    for key in ("instagram", "facebook", "tiktok"):
        val = body.get(f"social_{key}")
        if val is not None:
            if val:
                socials[key] = val
            elif key in socials:
                del socials[key]
    if "socials" in body:
        socials = body["socials"]
    data = {k: v for k, v in body.items() if k not in ("social_instagram", "social_facebook", "social_tiktok")}
    data["socials"] = socials
    company = company_update(company_id, data)
    return {"company": company}


@router.delete("/{company_id}")
def delete_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    ok = company_delete(company_id)
    if not ok:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Brand kit
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/brand-kit")
def get_brand_kit(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    bk = brand_kit_get(company_id)
    return {"brand_kit": bk}


@router.post("/{company_id}/brand-kit")
async def save_brand_kit(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    colors = {}
    for key in ("primaryColor", "secondaryColor", "accentColor"):
        if key in body:
            mapped = key.replace("Color", "")
            colors[mapped] = body[key]
    if existing.get("brand_kit") and existing["brand_kit"].get("colors"):
        merged = existing["brand_kit"]["colors"].copy()
        merged.update(colors)
        colors = merged
    data: Dict[str, Any] = {}
    if colors:
        data["colors"] = colors
    for key in ("logo_url", "voice", "persona", "visual_prompt_base"):
        if key in body:
            data[key] = body[key]
    bk = brand_kit_upsert(company_id, data)
    return {"brand_kit": bk}


# ─────────────────────────────────────────────────────────────────────────────
# Logo upload
# ─────────────────────────────────────────────────────────────────────────────

UPLOAD_DIR = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
UPLOAD_URL_PREFIX = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")


@router.post("/{company_id}/logo")
async def upload_logo(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    filepath = os.path.join(subdir, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
    # update brand kit
    brand_kit_upsert(company_id, {"logo_url": url})
    # create asset
    asset_create(company_id, {"kind": "IMAGE", "source": "UPLOADED", "url": url, "meta": {"role": "logo"}})
    return {"url": url}


# ─────────────────────────────────────────────────────────────────────────────
# Reference images (mood board)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/references")
def list_references(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    refs = asset_list(company_id, role="brand_reference")
    return {"references": refs}


@router.post("/{company_id}/references")
async def upload_reference(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "ref.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "references")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    filepath = os.path.join(subdir, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/references/{filename}"
    asset = asset_create(company_id, {"kind": "IMAGE", "source": "UPLOADED", "url": url, "meta": {"role": "brand_reference"}})
    return {"reference": asset}


@router.delete("/{company_id}/references/{asset_id}")
def delete_reference(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    # get asset to find file path
    refs = asset_list(company_id, role="brand_reference")
    ref = next((r for r in refs if r["id"] == asset_id), None)
    if ref:
        # try to delete file
        url = ref.get("url", "")
        if url.startswith(UPLOAD_URL_PREFIX):
            rel_path = url[len(UPLOAD_URL_PREFIX):].lstrip("/")
            abs_path = os.path.join(UPLOAD_DIR, rel_path)
            if os.path.exists(abs_path):
                os.remove(abs_path)
    ok = asset_delete(asset_id)
    if not ok:
        return JSONResponse({"detail": "Referência não encontrada"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Competitors
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/competitors")
def list_competitors(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    comps = competitor_list(company_id)
    return {"competitors": comps}


@router.post("/{company_id}/competitors")
async def add_competitor(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    if not body.get("name"):
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    handles: Dict[str, str] = {}
    if body.get("instagram"):
        handles["instagram"] = body["instagram"]
    if body.get("website"):
        handles["website"] = body["website"]
    comp = competitor_create(company_id, {"name": body["name"], "handles": handles})
    return {"competitor": comp}


@router.delete("/{company_id}/competitors/{competitor_id}")
def remove_competitor(company_id: str, competitor_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    ok = competitor_delete(competitor_id)
    if not ok:
        return JSONResponse({"detail": "Concorrente não encontrado"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# All competitors (cross-company view)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/all/competitors")
def list_all_competitors(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    comps = competitor_list()
    return {"competitors": comps}
