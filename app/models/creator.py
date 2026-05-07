from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CreatorStatus(str, Enum):
    active = "active"
    paused = "paused"
    trial = "trial"
    churned = "churned"


class PlatformAccount(BaseModel):
    platform: str  # xvideos, pornhub, xnxx, xhamster, redtube, onlyfans
    username: str
    profile_url: Optional[str] = None
    # cookies_json is write-only — never returned in API responses
    is_verified: bool = False
    partner_program: bool = False
    last_login_check: Optional[datetime] = None
    status: str = "active"  # active, expired, banned


class PlatformAccountCreate(PlatformAccount):
    """Used when creating/updating — includes cookies."""
    cookies_json: Optional[str] = None


class PortalBranding(BaseModel):
    brand_name: Optional[str] = None
    headline: Optional[str] = None
    tagline: Optional[str] = None
    primary_color: str = "#67e8f9"
    secondary_color: str = "#8b5cf6"
    accent_color: str = "#22d3ee"
    surface_color: str = "#0f172a"
    text_color: str = "#e2e8f0"
    logo_b64: Optional[str] = None


class CreatorBase(BaseModel):
    name: str
    slug: Optional[str] = None
    real_name: Optional[str] = None  # stored encrypted
    email: str
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    status: CreatorStatus = CreatorStatus.trial

    # Logo / watermark
    logo_b64: Optional[str] = None
    logo_position: str = "bottom-right"
    logo_opacity: float = 0.7

    # Financial
    commission_model: str = "percentage"  # percentage, fixed, hybrid
    commission_pct: float = 25.0
    fixed_monthly: float = 0.0

    # Content prefs
    reference_channels: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    preferred_tags: list[str] = Field(default_factory=list)
    content_language: str = "pt-BR"

    # Production profile — used to personalize briefings
    own_channel_urls: list[str] = Field(default_factory=list)  # creator's own channels to analyze
    filming_setups: list[str] = Field(default_factory=list)  # solo, couple, small_group, large_group — what they CAN do
    performer_description: Optional[str] = None  # e.g. "mulher 28 anos morena, corpo atlético"
    location_types: list[str] = Field(default_factory=list)  # home, studio, outdoor, hotel — available locations
    production_level: str = "amateur"  # amateur, semi-pro, professional
    production_constraints: Optional[str] = None  # free text: what they CAN'T do

    # Notifications
    notification_email: bool = True
    notification_whatsapp: bool = False
    trend_report_frequency: str = "weekly"  # daily, weekly, biweekly, monthly

    # Google Drive
    drive_folder_id: Optional[str] = None
    drive_service_account: Optional[str] = None
    portal_branding: PortalBranding = Field(default_factory=PortalBranding)

    # Default edit config
    default_edit_config: dict = Field(default_factory=lambda: {
        "target_duration_minutes": 40,
        "output_crf": 23,
        "output_max_height": 1080,
        "audio_normalize": True,
        "audio_denoise": True,
        "skip_transcription": True,
    })

    notes: Optional[str] = None


class CreatorCreate(CreatorBase):
    pass


class CreatorUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    status: Optional[CreatorStatus] = None
    logo_b64: Optional[str] = None
    logo_position: Optional[str] = None
    logo_opacity: Optional[float] = None
    commission_model: Optional[str] = None
    commission_pct: Optional[float] = None
    fixed_monthly: Optional[float] = None
    reference_channels: Optional[list[str]] = None
    preferred_categories: Optional[list[str]] = None
    preferred_tags: Optional[list[str]] = None
    content_language: Optional[str] = None
    own_channel_urls: Optional[list[str]] = None
    filming_setups: Optional[list[str]] = None
    performer_description: Optional[str] = None
    location_types: Optional[list[str]] = None
    production_level: Optional[str] = None
    production_constraints: Optional[str] = None
    notification_email: Optional[bool] = None
    notification_whatsapp: Optional[bool] = None
    trend_report_frequency: Optional[str] = None
    drive_folder_id: Optional[str] = None
    drive_service_account: Optional[str] = None
    portal_branding: Optional[PortalBranding] = None
    default_edit_config: Optional[dict] = None
    notes: Optional[str] = None


class Creator(CreatorBase):
    creator_id: str
    platforms: list[PlatformAccount] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreatorListResponse(BaseModel):
    creators: list[Creator] = Field(default_factory=list)
    total: int = 0


class CreatorCreateResponse(BaseModel):
    creator: Creator
    creator_id: str


class CreatorPortalBrandingPublic(BaseModel):
    creator_id: str
    slug: str
    name: str
    status: CreatorStatus
    portal_branding: PortalBranding = Field(default_factory=PortalBranding)
