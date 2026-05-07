"""
Module 1: Creator Management
CRUD for creators and their platform accounts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_agency import (
    creator_create, creator_list, creator_get, creator_update, creator_delete, creator_resolve_slug,
    platform_account_upsert, platform_account_delete, platform_account_get_with_cookies,
    platform_account_update_login_check,
    creator_stats_latest, publications_by_creator,
    earnings_report,
)
from ..models.creator import (
    Creator,
    CreatorCreate,
    CreatorCreateResponse,
    CreatorListResponse,
    CreatorUpdate,
    PlatformAccountCreate,
)
from ..security.encryption import encrypt, decrypt

router = APIRouter(prefix="/api/creators", tags=["creators"])


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model.dict(exclude_none=True)


# ─────────────────────────────────────────────────────────────────────────────
# Creators CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=CreatorCreateResponse)
async def create_creator(body: CreatorCreate, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = _model_dump(body)

    # Validate required fields
    if not body.get("name") or not body.get("email"):
        return JSONResponse({"detail": "name and email are required"}, status_code=422)

    creator_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    body["slug"] = creator_resolve_slug(body.get("name") or "criador", body.get("slug"))

    # Encrypt real_name if provided
    if body.get("real_name"):
        body["real_name"] = encrypt(body["real_name"])

    data = {**body, "creator_id": creator_id, "created_at": now, "updated_at": now}
    creator_create(data)
    creator = creator_get(creator_id)
    return {"creator": creator, "creator_id": creator_id}


@router.get("", response_model=CreatorListResponse)
def list_creators(request: Request, status: Optional[str] = None, limit: int = 100):
    err = _api_key_required(request)
    if err:
        return err
    creators = creator_list(status=status, limit=limit)
    # Attach platform counts (platforms are in a separate call for list view)
    from ..db_agency import get_conn
    with get_conn() as conn:
        for c in creators:
            cid = c["creator_id"]
            pcount = conn.execute(
                "SELECT COUNT(*) FROM platform_accounts WHERE creator_id=?", (cid,)
            ).fetchone()[0]
            c["platform_count"] = pcount
    return {"creators": creators, "total": len(creators)}


@router.get("/{creator_id}", response_model=Creator)
def get_creator(creator_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    return creator


@router.put("/{creator_id}", response_model=Creator)
async def update_creator(creator_id: str, body: CreatorUpdate, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    body = _model_dump(body)

    # Encrypt real_name if being updated
    if body.get("real_name"):
        body["real_name"] = encrypt(body["real_name"])

    if "slug" in body:
        body["slug"] = creator_resolve_slug(
            body.get("name") or creator.get("name") or "criador",
            body.get("slug") or creator.get("slug"),
            exclude_creator_id=creator_id,
        )
    elif not creator.get("slug"):
        body["slug"] = creator_resolve_slug(
            body.get("name") or creator.get("name") or "criador",
            creator.get("slug"),
            exclude_creator_id=creator_id,
        )

    # Remove read-only fields
    for f in ("creator_id", "created_at"):
        body.pop(f, None)

    creator_update(creator_id, body)
    return creator_get(creator_id)


@router.delete("/{creator_id}")
def delete_creator(creator_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    creator_delete(creator_id)
    return {"ok": True, "creator_id": creator_id, "status": "churned"}


# ─────────────────────────────────────────────────────────────────────────────
# Platform accounts
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{creator_id}/platforms")
async def add_platform(creator_id: str, body: PlatformAccountCreate, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)
    body = _model_dump(body)

    if not body.get("platform") or not body.get("username"):
        return JSONResponse({"detail": "platform and username are required"}, status_code=422)

    # Encrypt cookies before storing
    if body.get("cookies_json"):
        body["cookies_json"] = encrypt(body["cookies_json"])

    platform_account_upsert(creator_id, body)
    return {"ok": True, "platform": body["platform"]}


@router.put("/{creator_id}/platforms/{platform}")
async def update_platform(creator_id: str, platform: str, body: PlatformAccountCreate, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = _model_dump(body)
    body["platform"] = platform
    if body.get("cookies_json"):
        body["cookies_json"] = encrypt(body["cookies_json"])

    platform_account_upsert(creator_id, body)
    return {"ok": True, "platform": platform}


@router.delete("/{creator_id}/platforms/{platform}")
def remove_platform(creator_id: str, platform: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    platform_account_delete(creator_id, platform)
    return {"ok": True, "platform": platform}


# ─────────────────────────────────────────────────────────────────────────────
# Login check & stats
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{creator_id}/login-check")
async def login_check(creator_id: str, request: Request):
    """Check if platform cookies are still valid using Playwright."""
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        body = {}
    platform_filter = body.get("platform")  # check specific platform or all

    results = {}
    platforms = creator.get("platforms", [])
    if platform_filter:
        platforms = [p for p in platforms if p.get("platform") == platform_filter]

    from ..publishers.registry import get_driver
    for p in platforms:
        platform = p.get("platform", "")
        DriverClass = get_driver(platform)
        if not DriverClass:
            results[platform] = {"status": "unsupported"}
            continue

        account = platform_account_get_with_cookies(creator_id, platform)
        cookies_json = None
        if account and account.get("cookies_json"):
            cookies_json = decrypt(account["cookies_json"])

        try:
            async with DriverClass(cookies_json=cookies_json, headless=True) as driver:
                is_logged = await driver.check_login()
            status = "valid" if is_logged else "expired"
            platform_account_update_login_check(creator_id, platform, status)
            results[platform] = {"status": status}
        except Exception as exc:
            results[platform] = {"status": "error", "error": str(exc)}

    return {"creator_id": creator_id, "platforms": results}


@router.post("/{creator_id}/scrape-stats")
async def scrape_stats(creator_id: str, request: Request):
    """Start an async job to scrape stats from all platforms."""
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    import asyncio
    asyncio.create_task(_scrape_stats_task(creator_id))
    return {"ok": True, "message": "Stats scraping started in background"}


async def _scrape_stats_task(creator_id: str):
    from ..db_agency import creator_stats_upsert, platform_account_get_with_cookies, get_conn
    from ..publishers.registry import get_driver
    from datetime import datetime, timezone

    creator = creator_get(creator_id)
    if not creator:
        return
    now = datetime.now(timezone.utc).isoformat()
    platforms = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT platform FROM platform_accounts WHERE creator_id=? AND status='active'",
            (creator_id,)
        ).fetchall()
        platforms = [r["platform"] for r in rows]

    for platform in platforms:
        DriverClass = get_driver(platform)
        if not DriverClass:
            continue
        account = platform_account_get_with_cookies(creator_id, platform)
        cookies_json = decrypt(account.get("cookies_json") or "") if account else None
        try:
            async with DriverClass(cookies_json=cookies_json, headless=True) as driver:
                stats = await driver.scrape_channel_stats()
            creator_stats_upsert({
                **stats,
                "creator_id": creator_id,
                "platform": platform,
                "scraped_at": now,
            })
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Scrape stats failed for %s/%s: %s", creator_id, platform, exc)


@router.get("/{creator_id}/stats")
def get_stats(creator_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    stats = creator_stats_latest(creator_id)
    return {"creator_id": creator_id, "stats": stats}


@router.get("/{creator_id}/videos")
def get_videos(creator_id: str, request: Request, limit: int = 50):
    err = _api_key_required(request)
    if err:
        return err
    pubs = publications_by_creator(creator_id, limit=limit)
    return {"creator_id": creator_id, "videos": pubs, "total": len(pubs)}


@router.get("/{creator_id}/financial")
def get_financial(creator_id: str, request: Request, month: Optional[str] = None):
    err = _api_key_required(request)
    if err:
        return err
    creator = creator_get(creator_id)
    if not creator:
        return JSONResponse({"detail": "Creator not found"}, status_code=404)

    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    from ..services.financial_calculator import get_monthly_report
    report = get_monthly_report(creator_id, month)
    return report
