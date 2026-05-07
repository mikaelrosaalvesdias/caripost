"""
Module 6: Editorial Calendar
Schedule and manage video publications across platforms.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import (
    calendar_create, calendar_list, calendar_get, calendar_update, calendar_delete,
    creator_get,
)
from ..models.calendar import (
    AutoScheduleRequest,
    CalendarEntry,
    CalendarEntryCreate,
    CalendarEntryUpdate,
    CalendarListResponse,
    CalendarNextResponse,
)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


@router.get("", response_model=CalendarListResponse)
def list_entries(
    request: Request,
    creator_id: Optional[str] = None,
    status: Optional[str] = None,
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
    limit: int = 100,
):
    err = _auth(request)
    if err:
        return err
    entries = calendar_list(creator_id=creator_id, status=status,
                             from_dt=from_dt, to_dt=to_dt, limit=limit)
    return {"entries": entries, "total": len(entries)}


@router.post("", response_model=CalendarEntry)
async def create_entry(body: CalendarEntryCreate, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)

    creator_id = body.get("creator_id")
    video_key = body.get("video_object_key")
    publish_at = body.get("publish_at")

    if not creator_id or not video_key or not publish_at:
        return JSONResponse(
            {"detail": "creator_id, video_object_key and publish_at are required"},
            status_code=422,
        )
    if not creator_get(creator_id):
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    calendar_create({
        **body,
        "entry_id": entry_id,
        "created_at": now,
        "updated_at": now,
    })
    return calendar_get(entry_id)


@router.get("/next", response_model=CalendarNextResponse)
def next_publications(request: Request, days: int = 7, creator_id: Optional[str] = None):
    """Upcoming publications in the next N days."""
    err = _auth(request)
    if err:
        return err
    from_dt = datetime.now(timezone.utc).isoformat()
    from datetime import timedelta
    to_dt = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    entries = calendar_list(creator_id=creator_id, status="scheduled",
                             from_dt=from_dt, to_dt=to_dt, limit=50)
    return {"entries": entries, "period_days": days}


@router.get("/optimal-times")
def optimal_times(request: Request):
    """Return known peak hours per platform."""
    err = _auth(request)
    if err:
        return err
    return {
        "optimal_times": {
            "xvideos": {"br": "21:00-01:00", "us": "14:00-18:00", "utc": "00:00-04:00"},
            "pornhub": {"br": "22:00-02:00", "us": "15:00-19:00", "utc": "01:00-05:00"},
            "xnxx": {"br": "21:00-01:00", "us": "14:00-18:00", "utc": "00:00-04:00"},
            "xhamster": {"br": "20:00-00:00", "us": "13:00-17:00", "utc": "23:00-03:00"},
        },
        "recommendation": "Publish at 22:00 BRT (01:00 UTC) for best coverage across platforms",
    }


@router.post("/auto-schedule")
async def auto_schedule(body: AutoScheduleRequest, request: Request):
    err = _auth(request)
    if err:
        return err
    body = _model_dump(body)
    creator_id = body.get("creator_id")
    if not creator_id:
        return JSONResponse({"detail": "creator_id is required"}, status_code=422)

    video_keys = body.get("video_object_keys", [])
    if not video_keys:
        return JSONResponse({"detail": "video_object_keys required"}, status_code=422)

    from ..services.calendar_scheduler import auto_schedule as do_auto_schedule
    result = await do_auto_schedule(
        creator_id=creator_id,
        video_object_keys=video_keys,
        platforms=body.get("platforms", ["xvideos"]),
        period_days=body.get("period_days", 7),
        timezone_str=body.get("timezone", "America/Sao_Paulo"),
    )
    return result


@router.get("/{entry_id}", response_model=CalendarEntry)
def get_entry(entry_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    entry = calendar_get(entry_id)
    if not entry:
        return JSONResponse({"detail": "Entry not found"}, status_code=404)
    return entry


@router.put("/{entry_id}", response_model=CalendarEntry)
async def update_entry(entry_id: str, body: CalendarEntryUpdate, request: Request):
    err = _auth(request)
    if err:
        return err
    entry = calendar_get(entry_id)
    if not entry:
        return JSONResponse({"detail": "Entry not found"}, status_code=404)
    body = _model_dump(body)

    # Remove read-only fields
    for f in ("entry_id", "creator_id", "created_at"):
        body.pop(f, None)

    calendar_update(entry_id, body)
    return calendar_get(entry_id)


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, request: Request):
    err = _auth(request)
    if err:
        return err
    entry = calendar_get(entry_id)
    if not entry:
        return JSONResponse({"detail": "Entry not found"}, status_code=404)
    calendar_delete(entry_id)
    return {"ok": True, "entry_id": entry_id}
