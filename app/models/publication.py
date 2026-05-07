from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PublishMetadata(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = "Amateur"
    is_premium: bool = False


class PublishRequest(BaseModel):
    creator_id: str
    video_object_key: str
    platforms: list[str]  # ["xvideos", "pornhub", ...]
    metadata: PublishMetadata
    thumbnail_object_key: Optional[str] = None
    schedule_at: Optional[datetime] = None  # None = publish now


class PublishResult(BaseModel):
    platform: str
    status: str  # queued, uploading, done, error
    video_url: Optional[str] = None
    video_id: Optional[str] = None
    error: Optional[str] = None
    screenshot: Optional[str] = None


class PublishJobStatus(BaseModel):
    job_id: str
    status: str  # pending, processing, done, error
    creator_id: str
    video_object_key: str
    platforms: dict[str, PublishResult] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
