"""
Module 5: DMCA Protection
Monitor and take down infringing content.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import dmca_list, dmca_update_status, dmca_stats
from ..models.dmca import (
    DmcaBulkTakedownRequest,
    DmcaScanRequest,
    DmcaSendTakedownRequest,
    DmcaStats,
    DmcaStatusUpdateRequest,
)

router = APIRouter(prefix="/api/dmca", tags=["dmca"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


@router.get("/infringements")
def list_infringements(
    request: Request,
    creator_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    err = _auth(request)
    if err:
        return err
    infringements = dmca_list(creator_id=creator_id, status=status, limit=limit)
    return {"infringements": infringements, "total": len(infringements)}


@router.post("/scan")
async def scan_creator(body: DmcaScanRequest, request: Request):
    """Trigger DMCA scan for a creator."""
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    creator_id = body.get("creator_id")
    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    from ..services.dmca_scanner import scan_creator as do_scan
    asyncio.create_task(do_scan(creator_id))
    return {"ok": True, "creator_id": creator_id, "message": "DMCA scan started in background"}


@router.post("/scan-sync")
async def scan_creator_sync(body: DmcaScanRequest, request: Request):
    """Synchronous DMCA scan (waits for result)."""
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    creator_id = body.get("creator_id")
    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    from ..services.dmca_scanner import scan_creator as do_scan
    result = await do_scan(creator_id)
    return result


@router.post("/takedown/{infringement_id}")
async def send_takedown(infringement_id: str, body: DmcaSendTakedownRequest, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    contact_email = body.get("contact_email", "dmca@metaporn.com.br")

    from ..services.dmca_takedown import send_takedown as do_takedown
    result = await do_takedown(infringement_id, contact_email=contact_email)
    return result


@router.post("/bulk-takedown")
async def bulk_takedown(body: DmcaBulkTakedownRequest, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    infringement_ids = body.get("infringement_ids", [])
    contact_email = body.get("contact_email", "dmca@metaporn.com.br")

    from ..services.dmca_takedown import send_takedown as do_takedown
    results = {}
    for iid in infringement_ids:
        results[iid] = await do_takedown(iid, contact_email=contact_email)

    return {"results": results, "total": len(results)}


@router.patch("/infringements/{infringement_id}/status")
async def update_infringement_status(infringement_id: str, body: DmcaStatusUpdateRequest, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    new_status = body.get("status")
    valid_statuses = {"detected", "takedown_sent", "removed", "ignored", "failed"}
    if new_status not in valid_statuses:
        return JSONResponse({"detail": f"Invalid status. Must be one of: {valid_statuses}"}, status_code=422)

    dmca_update_status(infringement_id, new_status)
    return {"ok": True, "infringement_id": infringement_id, "status": new_status}


@router.get("/stats", response_model=DmcaStats)
def get_dmca_stats(request: Request, creator_id: Optional[str] = None):
    err = _auth(request)
    if err:
        return err
    return dmca_stats(creator_id=creator_id)
