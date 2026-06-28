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
    asset_list, asset_create, asset_delete, asset_get, asset_update_meta,
    asset_list_logos, asset_clear_primary,
    product_list, product_get, product_create, product_update, product_delete,
    solution_list, solution_get, solution_create, solution_update, solution_delete,
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
    for key in ("logo_url", "voice", "persona", "visual_prompt_base", "audience", "assuntos", "client_rules"):
        if key in body:
            data[key] = body[key]
    bk = brand_kit_upsert(company_id, data)
    return {"brand_kit": bk}


@router.get("/{company_id}/creative-config")
def get_creative_config(company_id: str, request: Request):
    """Config criativa do cliente: defaults globais + override atual (nada travado no código)."""
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    from ..services.ai import CREATIVE_DEFAULTS
    from ..services.template_composer import EDITORIAL_DESIGN
    defaults = {**CREATIVE_DEFAULTS, "design": EDITORIAL_DESIGN}
    override = (co.get("brand_kit") or {}).get("creative_config") or {}
    return {"defaults": defaults, "override": override}


@router.post("/{company_id}/creative-config")
async def save_creative_config(company_id: str, request: Request):
    """Salva os overrides criativos do cliente (prompts/regras/design/imagem/vídeo). {} = restaura padrão."""
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    override = body.get("creative_config")
    if override is None:
        override = body.get("override") or {}
    if not isinstance(override, dict):
        return JSONResponse({"detail": "creative_config deve ser um objeto"}, status_code=422)
    brand_kit_upsert(company_id, {"creative_config": override})
    return {"ok": True, "override": override}


# ─────────────────────────────────────────────────────────────────────────────
# Logo upload
# ─────────────────────────────────────────────────────────────────────────────

UPLOAD_DIR = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
UPLOAD_URL_PREFIX = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")


@router.post("/{company_id}/enrich")
async def enrich_company(company_id: str, request: Request):
    """Read the company's site + Instagram and fill Dados Gerais + Voz e Persona
    (tom de voz, persona, público/modelo, base visual) + colors from the logo. No prices."""
    err = _api_key_required(request)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    website = (body.get("website") or co.get("website") or "").strip()
    instagram = (body.get("instagram") or (co.get("socials") or {}).get("instagram") or "").strip()
    if not website and not instagram:
        return JSONResponse({"detail": "Cadastre o site e/ou o Instagram em Dados Gerais primeiro."}, status_code=422)
    try:
        from ..services.ai import enrich_company_from_web
        data = enrich_company_from_web(co.get("name") or "", website, instagram, co.get("segment") or "")
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    # Dados Gerais
    cup: Dict[str, Any] = {"website": website, "socials": {**(co.get("socials") or {}), "instagram": instagram}}
    if data.get("segment"):
        cup["segment"] = data["segment"]
    if data.get("description") and not (co.get("notes") or "").strip():
        cup["notes"] = data["description"]
    company_update(company_id, cup)
    # Colors from the company logo (more reliable than site text).
    colors = dict(data.get("colors") or {})
    try:
        for lg in (asset_list_logos(company_id) or []):
            u = lg.get("url") or ""
            if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
                continue
            cols = _dominant_colors(os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/")))
            if cols:
                keys = ["primary", "secondary", "accent"]
                colors.update({keys[i]: c for i, c in enumerate(cols)})
                break
    except Exception:
        pass
    # Voz e Persona (brand kit)
    bk: Dict[str, Any] = {}
    for k in ("voice", "persona", "visual_prompt_base", "audience"):
        if data.get(k):
            bk[k] = data[k]
    if colors:
        bk["colors"] = colors
    if bk:
        brand_kit_upsert(company_id, bk)
    return {"company": company_get(company_id), "extracted": data}


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
# Influencers (por empresa) — cadastro + banco de imagem (fotos reais p/ compor na arte + collab @)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{company_id}/influencer-companies")
def list_infcompanies(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import infcompany_list
    return {"companies": infcompany_list(company_id)}


@router.post("/{company_id}/influencer-companies")
async def create_infcompany(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome da empresa influencer é obrigatório"}, status_code=422)
    from ..db_companies import infcompany_create
    return infcompany_create(company_id, body)


@router.put("/{company_id}/influencer-companies/{infco_id}")
async def update_infcompany(company_id: str, infco_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import infcompany_update
    o = infcompany_update(infco_id, body)
    return o or JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)


@router.delete("/{company_id}/influencer-companies/{infco_id}")
def delete_infcompany(company_id: str, infco_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import infcompany_delete
    return {"ok": infcompany_delete(infco_id)}


@router.post("/{company_id}/influencer-companies/{infco_id}/logo")
async def upload_infcompany_logo(company_id: str, infco_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "inf_companies", infco_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/inf_companies/{infco_id}/{filename}"
    a = asset_create(company_id, {"kind": "INFCOMPANY_LOGO", "source": "UPLOADED", "url": url, "meta": {"infcompany_id": infco_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/influencer-companies/{infco_id}/logo/{asset_id}")
def delete_infcompany_logo(company_id: str, infco_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.get("/{company_id}/influencers")
def list_influencers(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import influencer_list
    return {"influencers": influencer_list(company_id)}


@router.post("/{company_id}/influencers")
async def create_influencer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do influencer é obrigatório"}, status_code=422)
    from ..db_companies import influencer_create
    return influencer_create(company_id, body)


@router.put("/{company_id}/influencers/{inf_id}")
async def update_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import influencer_update
    inf = influencer_update(inf_id, body)
    return inf or JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)


@router.delete("/{company_id}/influencers/{inf_id}")
def delete_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import influencer_delete
    return {"ok": influencer_delete(inf_id)}


@router.post("/{company_id}/influencers/{inf_id}/photo")
async def upload_influencer_photo(company_id: str, inf_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "foto.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "influencers", inf_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/influencers/{inf_id}/{filename}"
    a = asset_create(company_id, {"kind": "INFLUENCER_PHOTO", "source": "UPLOADED", "url": url, "meta": {"influencer_id": inf_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/influencers/{inf_id}/photo/{asset_id}")
def delete_influencer_photo(company_id: str, inf_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Organizador do evento (empresa do evento, ex.: ExPSP) — IG + site + logo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/event-organizers")
def list_organizers(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import organizer_list
    return {"organizers": organizer_list(company_id)}


@router.post("/{company_id}/event-organizers")
async def create_organizer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome da empresa do evento é obrigatório"}, status_code=422)
    from ..db_companies import organizer_create
    return organizer_create(company_id, body)


@router.put("/{company_id}/event-organizers/{org_id}")
async def update_organizer(company_id: str, org_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import organizer_update
    o = organizer_update(org_id, body)
    return o or JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)


@router.delete("/{company_id}/event-organizers/{org_id}")
def delete_organizer(company_id: str, org_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import organizer_delete
    return {"ok": organizer_delete(org_id)}


@router.post("/{company_id}/event-organizers/{org_id}/logo")
async def upload_organizer_logo(company_id: str, org_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "event_orgs", org_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/event_orgs/{org_id}/{filename}"
    a = asset_create(company_id, {"kind": "ORGANIZER_LOGO", "source": "UPLOADED", "url": url, "meta": {"organizer_id": org_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/event-organizers/{org_id}/logo/{asset_id}")
def delete_organizer_logo(company_id: str, org_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Eventos (edição embaixo do organizador): data início/fim, cidade, logos + imagens
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/events")
def list_events(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import event_list
    return {"events": event_list(company_id)}


@router.post("/{company_id}/events")
async def create_event(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do evento é obrigatório"}, status_code=422)
    from ..db_companies import event_create
    return event_create(company_id, body)


@router.put("/{company_id}/events/{event_id}")
async def update_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import event_update
    ev = event_update(event_id, body)
    return ev or JSONResponse({"detail": "Evento não encontrado"}, status_code=404)


@router.delete("/{company_id}/events/{event_id}")
def delete_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import event_delete
    return {"ok": event_delete(event_id)}


@router.post("/{company_id}/events/{event_id}/logo")
async def upload_event_logo(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "events", event_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/events/{event_id}/{filename}"
    a = asset_create(company_id, {"kind": "EVENT_LOGO", "source": "UPLOADED", "url": url, "meta": {"event_id": event_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/events/{event_id}/logo/{asset_id}")
def delete_event_logo(company_id: str, event_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.post("/{company_id}/events/{event_id}/image")
async def upload_event_image(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "img.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "events", event_id, "img")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/events/{event_id}/img/{filename}"
    a = asset_create(company_id, {"kind": "EVENT_IMAGE", "source": "UPLOADED", "url": url, "meta": {"event_id": event_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/events/{event_id}/image/{asset_id}")
def delete_event_image(company_id: str, event_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


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


# ─────────────────────────────────────────────────────────────────────────────
# Products (Cliente → Produto) + Solutions (→ Solução) — content sources
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/products")
def list_products(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    products = product_list(company_id)
    for p in products:
        p["solutions"] = solution_list(p["id"])
        p["logos"] = asset_list_logos(company_id, p["id"])
    return {"products": products}


@router.post("/{company_id}/products")
async def create_product(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not (data.get("name") or "").strip():
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    return {"product": product_create(company_id, data)}


@router.put("/{company_id}/products/{product_id}")
async def update_product(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    product = product_update(product_id, data)
    if not product:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"product": product}


def _extract_doc_text(name: str, raw: bytes) -> str:
    """Extrai texto de PDF/TXT/MD/CSV. PDF via pypdf; resto decodifica UTF-8."""
    ext = os.path.splitext(name or "")[1].lower()
    if ext == ".pdf":
        import io as _io
        from pypdf import PdfReader
        rd = PdfReader(_io.BytesIO(raw))
        return "\n".join((pg.extract_text() or "") for pg in rd.pages)
    return raw.decode("utf-8", "ignore")


@router.post("/{company_id}/products/{product_id}/kb")
async def upload_product_kb(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    """BASE DE CONHECIMENTO do produto: sobe PDF/TXT/MD, EXTRAI o texto e ACUMULA em product.knowledge.
    O briefing usa esse texto (funções/fatos REAIS) p/ não ficar raso. Junta com o site (functions) e a internet."""
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    raw = await file.read()
    name = file.filename or "doc.txt"
    try:
        text = (_extract_doc_text(name, raw) or "").strip()
    except Exception as e:
        return JSONResponse({"detail": f"Falha ao ler '{name}': {e}"}, status_code=400)
    if not text:
        return JSONResponse({"detail": "Não consegui extrair texto desse arquivo (PDF pode ser imagem escaneada)."}, status_code=400)
    prev = (prod.get("knowledge") or "").strip()
    merged = (prev + f"\n\n===== {name} =====\n" + text).strip()[:60000]   # teto p/ não estourar o prompt
    product_update(product_id, {"knowledge": merged})
    return {"ok": True, "file": name, "chars": len(text), "total_chars": len(merged)}


@router.get("/{company_id}/products/{product_id}/kb")
def get_product_kb(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    kb = (prod.get("knowledge") or "")
    return {"chars": len(kb), "preview": kb[:2000]}


@router.delete("/{company_id}/products/{product_id}/kb")
def clear_product_kb(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    product_update(product_id, {"knowledge": ""})
    return {"ok": True}


def _dominant_colors(path: str, n: int = 3) -> List[str]:
    """Top vivid colors from a logo image, as #RRGGBB. Skips near-white/black/gray."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("RGB").resize((96, 96))
        q = img.quantize(colors=16)
        pal = q.getpalette() or []
        out: List[str] = []
        for _count, idx in sorted(q.getcolors() or [], reverse=True):
            r, g, b = pal[idx * 3], pal[idx * 3 + 1], pal[idx * 3 + 2]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx > 240 and mn > 240:        # near-white
                continue
            if mx < 28:                       # near-black
                continue
            if mx - mn < 24 and mx > 60:      # gray
                continue
            hexv = "#%02X%02X%02X" % (r, g, b)
            if hexv not in out:
                out.append(hexv)
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


@router.post("/{company_id}/products/{product_id}/enrich")
async def enrich_product(company_id: str, product_id: str, request: Request):
    """Read the product's site + Instagram and auto-fill its profile (functions, objective,
    colors, à-la-carte) — never prices."""
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    website = (body.get("website") or prod.get("website") or "").strip()
    instagram = (body.get("instagram") or (prod.get("socials") or {}).get("instagram") or "").strip()
    try:
        from ..services.ai import enrich_product_from_web
        data = enrich_product_from_web(prod.get("name") or "", website, instagram)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    update = {"website": website, "socials": {**(prod.get("socials") or {}), "instagram": instagram}}
    for k in ("description", "objective", "category", "functions"):
        if data.get(k):
            update[k] = data[k]
    # Colors from the uploaded product logo (more reliable than site text).
    try:
        for lg in (asset_list_logos(company_id, product_id) or []):
            u = lg.get("url") or ""
            if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
                continue
            cols = _dominant_colors(os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/")))
            if cols:
                keys = ["primary", "secondary", "accent"]
                data["colors"] = {**(data.get("colors") or {}), **{keys[i]: c for i, c in enumerate(cols)}}
                break
    except Exception:
        pass
    if data.get("colors"):
        update["colors"] = {**(prod.get("colors") or {}), **data["colors"]}
    product = product_update(product_id, update)
    created = []
    if body.get("create_alacarte"):
        existing = {(s.get("name") or "").strip().lower() for s in solution_list(product_id)}
        for item in (data.get("alacarte") or []):
            if item.strip().lower() not in existing:
                solution_create(product_id, {"name": item})
                created.append(item)
    return {"product": product, "extracted": data, "alacarte_created": created}


@router.delete("/{company_id}/products/{product_id}")
def delete_product(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not product_delete(product_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"deleted": True}


@router.post("/{company_id}/products/{product_id}/logo")
async def upload_product_logo(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not product_get(product_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "products", product_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/products/{product_id}/{filename}"
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url, "product_id": product_id,
        "meta": {"role": "logo", "variant": "light"},
    })
    return {"logo": asset}


@router.get("/{company_id}/products/{product_id}/solutions")
def list_solutions(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"solutions": solution_list(product_id)}


@router.post("/{company_id}/products/{product_id}/solutions")
async def create_solution(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not (data.get("name") or "").strip():
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    sol = solution_create(product_id, data)
    if not sol:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"solution": sol}


@router.put("/{company_id}/solutions/{solution_id}")
async def update_solution(company_id: str, solution_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    sol = solution_update(solution_id, data)
    if not sol:
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    return {"solution": sol}


@router.delete("/{company_id}/solutions/{solution_id}")
def delete_solution(company_id: str, solution_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not solution_delete(solution_id):
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Multi-logo (company): principal + variations (light/dark/format)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/logos")
def list_logos(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"logos": asset_list_logos(company_id)}


@router.post("/{company_id}/logos")
async def upload_logo_variant(
    company_id: str,
    request: Request,
    file: UploadFile = File(...),
    variant: str = Form("light"),
    primary: str = Form("false"),
):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "logos")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logos/{filename}"
    is_primary = str(primary).lower() in ("1", "true", "yes")
    if is_primary:
        asset_clear_primary(company_id)
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url,
        "meta": {"role": "logo", "variant": variant or "light", "is_primary": is_primary},
    })
    # Keep brand kit's primary logo_url in sync when this is the primary logo.
    if is_primary:
        brand_kit_upsert(company_id, {"logo_url": url})
    return {"logo": asset}


@router.delete("/{company_id}/logos/{asset_id}")
def delete_logo(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    asset = asset_get(asset_id)
    if asset and (asset.get("url") or "").startswith(UPLOAD_URL_PREFIX):
        rel_path = asset["url"][len(UPLOAD_URL_PREFIX):].lstrip("/")
        abs_path = os.path.join(UPLOAD_DIR, rel_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    if not asset_delete(asset_id):
        return JSONResponse({"detail": "Logo não encontrado"}, status_code=404)
    return {"deleted": True}
