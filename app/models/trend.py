from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TrendSuggestion(BaseModel):
    title: str
    concept: str
    tags: list[str] = Field(default_factory=list)
    why_trending: str
    reference_url: Optional[str] = None
    difficulty: str = "medium"  # easy, medium, hard
    view_potential: str = "medium"  # low, medium, high, viral


class TrendBriefing(BaseModel):
    briefing_id: str
    creator_id: str
    market_summary: str
    suggestions: list[TrendSuggestion] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    generated_at: datetime
    sent_email: bool = False
    sent_whatsapp: bool = False
    email_sent_at: Optional[datetime] = None
    whatsapp_sent_at: Optional[datetime] = None


class TrendCollectResult(BaseModel):
    job_id: str
    status: str
    collected_at: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)
    record_count: int = 0


class BriefingGenerateRequest(BaseModel):
    creator_id: str


class BriefingSendRequest(BaseModel):
    briefing_id: str
    channels: list[str] = Field(default_factory=lambda: ["email"])  # email, whatsapp


class TrendScheduleUpdateRequest(BaseModel):
    creator_id: str
    trend_report_frequency: str
