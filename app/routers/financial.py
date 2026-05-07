"""
Module 7: Financial
Track earnings, calculate splits, generate reports.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import earnings_list, creator_get
from ..models.financial import AgencyOverview, EarningRecordCreate, EarningsListResponse, MonthlyReport
from ..services.financial_calculator import record_earning, get_monthly_report, get_agency_overview

router = APIRouter(prefix="/api/financial", tags=["financial"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


@router.post("/record-earning")
async def add_earning(body: EarningRecordCreate, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)

    required = ("creator_id", "platform", "period")
    for f in required:
        if not body.get(f):
            return JSONResponse({"detail": f"{f} is required"}, status_code=422)

    result = record_earning(
        creator_id=body["creator_id"],
        platform=body["platform"],
        period=body["period"],
        gross_revenue=float(body.get("gross_revenue", 0)),
        platform_fee_pct=float(body.get("platform_fee_pct", 0)),
        views_in_period=int(body.get("views_in_period", 0)),
        video_id=body.get("video_id"),
        source=body.get("source", "manual"),
    )
    if "error" in result:
        return JSONResponse({"detail": result["error"]}, status_code=400)
    return result


@router.get("/earnings", response_model=EarningsListResponse)
def list_earnings(
    request: Request,
    creator_id: Optional[str] = None,
    period: Optional[str] = None,
    limit: int = 200,
):
    err = _auth(request)
    if err:
        return err
    records = earnings_list(creator_id=creator_id, period=period, limit=limit)
    return {"earnings": records, "total": len(records)}


@router.get("/report/{creator_id}/{month}", response_model=MonthlyReport)
def monthly_report(creator_id: str, month: str, request: Request):
    err = _auth(request)
    if err:
        return err
    if not creator_get(creator_id):
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    return get_monthly_report(creator_id, month)


@router.get("/agency-overview", response_model=AgencyOverview)
def agency_overview(request: Request, period: Optional[str] = None):
    err = _auth(request)
    if err:
        return err
    return get_agency_overview(period=period)


@router.post("/generate-report")
async def generate_and_send_report(request: Request):
    """Generate monthly report and send it to the creator via email."""
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    creator_id = body.get("creator_id")
    month = body.get("month") or datetime.now(timezone.utc).strftime("%Y-%m")

    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    report = get_monthly_report(creator_id, month)
    if "error" in report:
        return JSONResponse({"detail": report["error"]}, status_code=400)

    # Send email
    send_result = {"email": {"success": False, "error": "Not attempted"}}
    if creator.get("notification_email") and creator.get("email"):
        from ..services.email_sender import send_monthly_report_email
        email_result = await send_monthly_report_email(creator, report)
        send_result["email"] = email_result

    return {"report": report, "sent": send_result}
