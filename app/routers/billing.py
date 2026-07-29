"""Admin de billing/acesso por empresa: saldo, recarga, consumo e feature flags (Marco 4)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.billing import add_credits, get_balance, usage_summary, set_features

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


@router.get("/summary")
def billing_summary(request: Request, company_id: str = "", days: int = 30):
    err = _auth(request)
    if err:
        return err
    from ..main_utils import scoped_company_id
    scid = scoped_company_id(request)
    if scid:
        company_id = scid                                   # tenancy: cliente só vê o próprio consumo
    return {"summary": usage_summary(company_id or None, days=days)}


@router.get("/balance")
def billing_balance(request: Request, company_id: str):
    err = _auth(request)
    if err:
        return err
    from ..main_utils import company_access_denied
    _d = company_access_denied(request, company_id)
    if _d:
        return _d
    return {"company_id": company_id, "balance": get_balance(company_id)}


@router.post("/credits")
async def billing_add_credits(request: Request):
    """Recarga manual: {company_id, amount} (amount pode ser negativo p/ ajuste)."""
    err = _auth(request)
    if err:
        return err
    body = await request.json()
    cid = (body.get("company_id") or "").strip()
    try:
        amount = float(body.get("amount"))
    except Exception:
        return JSONResponse({"detail": "amount inválido"}, status_code=422)
    if not cid:
        return JSONResponse({"detail": "company_id obrigatório"}, status_code=422)
    return {"company_id": cid, "balance": add_credits(cid, amount)}


@router.post("/features")
async def billing_set_features(request: Request):
    """Liberar/bloquear função por empresa: {company_id, features: {"video": false, ...}}."""
    err = _auth(request)
    if err:
        return err
    body = await request.json()
    cid = (body.get("company_id") or "").strip()
    feats = body.get("features")
    if not cid or not isinstance(feats, dict):
        return JSONResponse({"detail": "company_id e features{} obrigatórios"}, status_code=422)
    set_features(cid, feats)
    return {"company_id": cid, "features": feats}
