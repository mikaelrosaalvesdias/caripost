from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EarningRecord(BaseModel):
    record_id: str
    creator_id: str
    platform: str
    period: str  # YYYY-MM
    video_id: Optional[str] = None
    gross_revenue: float = 0.0
    platform_fee: float = 0.0
    net_revenue: float = 0.0
    agency_commission: float = 0.0
    creator_payout: float = 0.0
    views_in_period: int = 0
    source: str = "scraped"  # scraped, manual, api
    scraped_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class EarningRecordCreate(BaseModel):
    creator_id: str
    platform: str
    period: str  # YYYY-MM
    video_id: Optional[str] = None
    gross_revenue: float = 0.0
    platform_fee_pct: float = 0.0
    platform_fee: float = 0.0
    views_in_period: int = 0
    source: str = "manual"


class MonthlyReport(BaseModel):
    creator_id: str
    month: str  # YYYY-MM
    total_gross: float = 0.0
    total_platform_fees: float = 0.0
    total_net: float = 0.0
    total_agency_commission: float = 0.0
    total_creator_payout: float = 0.0
    total_views: int = 0
    platforms_breakdown: dict = Field(default_factory=dict)
    generated_at: datetime


class AgencyOverview(BaseModel):
    period: str  # YYYY-MM or "all"
    total_gross_all_creators: float = 0.0
    total_agency_commission: float = 0.0
    total_creator_payouts: float = 0.0
    creators_with_earnings: int = 0
    top_creators: list[dict] = Field(default_factory=list)
    platform_breakdown: dict = Field(default_factory=dict)


class EarningsListResponse(BaseModel):
    earnings: list[EarningRecord] = Field(default_factory=list)
    total: int = 0
