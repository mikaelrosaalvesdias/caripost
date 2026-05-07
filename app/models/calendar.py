from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CalendarEntry(BaseModel):
    entry_id: str
    creator_id: str
    video_object_key: str
    run_id: Optional[str] = None

    # Main publish
    publish_platforms: list[str] = Field(default_factory=list)
    publish_at: datetime
    published: bool = False
    publish_results: dict = Field(default_factory=dict)

    # Cross-promotion
    cross_promote: bool = True
    cross_channels: list[str] = Field(default_factory=list)  # telegram, twitter, reddit
    cross_promote_at: Optional[datetime] = None
    cross_results: dict = Field(default_factory=dict)

    # Metadata
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = "Amateur"

    status: str = "scheduled"  # scheduled, publishing, done, error
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CalendarEntryCreate(BaseModel):
    creator_id: str
    video_object_key: str
    run_id: Optional[str] = None
    publish_platforms: list[str] = Field(default_factory=list)
    publish_at: datetime
    cross_promote: bool = True
    cross_channels: list[str] = Field(default_factory=list)
    cross_promote_at: Optional[datetime] = None
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = "Amateur"


class CalendarEntryUpdate(BaseModel):
    publish_platforms: Optional[list[str]] = None
    publish_at: Optional[datetime] = None
    cross_promote: Optional[bool] = None
    cross_channels: Optional[list[str]] = None
    cross_promote_at: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    status: Optional[str] = None


class AutoScheduleRequest(BaseModel):
    creator_id: str
    video_count: int = 5
    period_days: int = 7
    video_object_keys: Optional[list[str]] = None
    platforms: Optional[list[str]] = None
    timezone: str = "America/Sao_Paulo"


class CalendarListResponse(BaseModel):
    entries: list[CalendarEntry] = Field(default_factory=list)
    total: int = 0


class CalendarNextResponse(BaseModel):
    entries: list[CalendarEntry] = Field(default_factory=list)
    period_days: int = 7
