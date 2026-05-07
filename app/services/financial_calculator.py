"""
Financial calculator: processes earning records and computes agency/creator splits.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db_agency import (
    creator_get, creator_list, earning_create, earnings_list, earnings_report,
)

logger = logging.getLogger(__name__)


def record_earning(
    creator_id: str,
    platform: str,
    period: str,
    gross_revenue: float,
    platform_fee_pct: float = 0.0,
    views_in_period: int = 0,
    video_id: Optional[str] = None,
    source: str = "manual",
) -> Dict[str, Any]:
    """
    Record a new earning entry and calculate splits.
    Returns the created record.
    """
    creator = creator_get(creator_id)
    if not creator:
        return {"error": "creator_not_found"}

    commission_pct = float(creator.get("commission_pct", 25.0))
    platform_fee = gross_revenue * (platform_fee_pct / 100.0)
    net_revenue = gross_revenue - platform_fee
    agency_commission = net_revenue * (commission_pct / 100.0)
    creator_payout = net_revenue - agency_commission

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    earning_create({
        "record_id": record_id,
        "creator_id": creator_id,
        "platform": platform,
        "period": period,
        "video_id": video_id,
        "gross_revenue": round(gross_revenue, 4),
        "platform_fee": round(platform_fee, 4),
        "net_revenue": round(net_revenue, 4),
        "agency_commission": round(agency_commission, 4),
        "creator_payout": round(creator_payout, 4),
        "views_in_period": views_in_period,
        "source": source,
        "scraped_at": now if source == "scraped" else None,
        "created_at": now,
    })

    return {
        "record_id": record_id,
        "creator_id": creator_id,
        "platform": platform,
        "period": period,
        "gross_revenue": gross_revenue,
        "platform_fee": round(platform_fee, 4),
        "net_revenue": round(net_revenue, 4),
        "agency_commission": round(agency_commission, 4),
        "creator_payout": round(creator_payout, 4),
        "views_in_period": views_in_period,
    }


def get_monthly_report(creator_id: str, period: str) -> Dict[str, Any]:
    """Generate monthly report for a creator."""
    creator = creator_get(creator_id)
    if not creator:
        return {"error": "creator_not_found"}
    commission_pct = float(creator.get("commission_pct", 25.0))
    return earnings_report(creator_id, period, commission_pct)


def get_agency_overview(period: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate overview across all creators for the agency."""
    creators = creator_list()
    total_gross = 0.0
    total_agency = 0.0
    total_payout = 0.0
    creators_with_earnings = 0
    top_list: List[Dict] = []
    platform_breakdown: Dict[str, float] = {}

    for creator in creators:
        cid = creator["creator_id"]
        commission_pct = float(creator.get("commission_pct", 25.0))
        records = earnings_list(creator_id=cid, period=period)
        if not records:
            continue
        c_gross = sum(float(r.get("gross_revenue") or 0) for r in records)
        c_payout = sum(float(r.get("creator_payout") or 0) for r in records)
        c_agency = sum(float(r.get("agency_commission") or 0) for r in records)
        if c_gross > 0:
            creators_with_earnings += 1
            total_gross += c_gross
            total_agency += c_agency
            total_payout += c_payout
            top_list.append({
                "creator_id": cid,
                "name": creator["name"],
                "gross": round(c_gross, 2),
                "agency": round(c_agency, 2),
                "payout": round(c_payout, 2),
            })
        for r in records:
            p = r.get("platform", "unknown")
            platform_breakdown[p] = platform_breakdown.get(p, 0.0) + float(r.get("gross_revenue") or 0)

    top_list.sort(key=lambda x: x["gross"], reverse=True)
    return {
        "period": period or "all",
        "total_gross_all_creators": round(total_gross, 2),
        "total_agency_commission": round(total_agency, 2),
        "total_creator_payouts": round(total_payout, 2),
        "creators_with_earnings": creators_with_earnings,
        "top_creators": top_list[:10],
        "platform_breakdown": {k: round(v, 2) for k, v in platform_breakdown.items()},
    }
