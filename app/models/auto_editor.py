from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AutoEditorRequest(BaseModel):
    creator_id: Optional[str] = None
    video_object_key: str
    video_object_keys: list[str] = Field(default_factory=list)
    title_hint: Optional[str] = None
    language: str = "pt-BR"

    target_duration_minutes: int = 40
    output_crf: int = 23
    output_max_height: int = 1080
    audio_normalize: bool = True
    audio_denoise: bool = True
    skip_transcription: bool = True

    scene_threshold: float = 0.32
    min_scene_duration_sec: float = 25.0
    max_scene_duration_sec: float = 150.0
    max_scenes: int = 24
    llm_select: bool = True
    delete_source_on_success: bool = False

    transition_mode: str = "smart"
    crossfade_video_sec: float = Field(default=0.5, ge=0.3, le=2.0)
    crossfade_audio_sec: float = Field(default=0.3, ge=0.2, le=2.0)
    transition_type: str = "fade"
    smart_cut_tolerance_sec: float = Field(default=1.5, ge=0.5, le=5.0)
    output_max_fps: int = Field(default=30, ge=12, le=120)


class AutoEditorScene(BaseModel):
    scene_index: int
    start: float
    end: float
    duration: float
    source_index: int = 0
    source_video_key: str = ""
    source_label: str = ""
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    score: float = 0.0
    transcript_excerpt: str = ""
    vision_excerpt: str = ""
    vision_relevance: float = 0.0
    selected: bool = False


class AutoEditorStartResponse(BaseModel):
    job_id: str
    status: str


class AutoEditorStatus(BaseModel):
    kind: str = "auto_editor"
    job_id: str
    status: str
    detail: str = ""
    progress_pct: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    creator_id: Optional[str] = None
    source_video_key: str = ""
    source_video_keys: list[str] = Field(default_factory=list)
    run_id: Optional[str] = None

    input_probe: dict = Field(default_factory=dict)
    output_probe: dict = Field(default_factory=dict)
    selected_scenes: list[AutoEditorScene] = Field(default_factory=list)
    transcript_excerpt: str = ""
    vision_analysis: dict = Field(default_factory=dict)
    vision_debug: dict = Field(default_factory=dict)
    selection_method: str = "heuristic"

    result_video_object_key: str = ""
    result_video_url: str = ""
    error: Optional[str] = None
