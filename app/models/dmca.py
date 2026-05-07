from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DmcaInfringement(BaseModel):
    infringement_id: str
    creator_id: str
    original_video_id: Optional[str] = None
    original_url: str
    infringing_url: str
    infringing_site: str
    detection_method: str  # google_search, thumbnail_match, title_match
    confidence: float = 0.0
    status: str = "detected"  # detected, takedown_sent, removed, ignored, failed
    takedown_sent_at: Optional[datetime] = None
    removed_at: Optional[datetime] = None
    notes: str = ""
    detected_at: datetime


class DmcaScanRequest(BaseModel):
    creator_id: str


class DmcaTakedownRequest(BaseModel):
    infringement_id: str


class DmcaBulkTakedownRequest(BaseModel):
    infringement_ids: list[str]
    contact_email: Optional[str] = None


class DmcaSendTakedownRequest(BaseModel):
    contact_email: Optional[str] = None


class DmcaStatusUpdateRequest(BaseModel):
    status: str


class DmcaStats(BaseModel):
    total_detected: int = 0
    total_takedown_sent: int = 0
    total_removed: int = 0
    total_ignored: int = 0
    total_failed: int = 0
    pending_action: int = 0
