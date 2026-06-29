"""Smoke tests for video provider adapters without calling paid APIs.

Run inside the app container/image, where project dependencies are installed:
  python scripts/test_video_providers_no_api.py
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from app.services import ai


class FakeResponse:
    def __init__(self, data=None, status_code=200, text="", content=b""):
        self._data = data or {}
        self.status_code = status_code
        self.text = text
        self.content = content

    def json(self):
        return self._data


class FakeClient:
    calls = []
    get_responses = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None, files=None):
        self.calls.append({"method": "POST", "url": url, "headers": headers or {}, "json": json, "files": files})
        return FakeResponse({"id": "job_123", "status": "pending"})

    def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers or {}})
        if self.get_responses:
            return self.get_responses.pop(0)
        return FakeResponse({"id": "job_123", "status": "completed", "unsigned_urls": ["https://openrouter.ai/api/v1/videos/job_123/content?index=0"]})


def _patch(provider: str):
    ai.get_video_config = lambda: {
        "provider": provider,
        "apiKey": "test-key",
        "model": "google/veo-3.1" if provider == "openrouter" else "veo3.1-fast",
        "base": "https://openrouter.ai/api/v1" if provider == "openrouter" else "https://api.cometapi.com/v1",
    }
    ai.httpx.Client = FakeClient


def test_openrouter_payload():
    FakeClient.calls = []
    _patch("openrouter")
    ai.create_video_job("prompt", "8", first_frame_url="https://cdn.example/frame.png")
    call = FakeClient.calls[-1]
    body = call["json"]
    assert call["url"] == "https://openrouter.ai/api/v1/videos"
    assert body["duration"] == 8
    assert "seconds" not in body
    assert body["frame_images"][0]["type"] == "image_url"
    assert body["frame_images"][0]["image_url"]["url"] == "https://cdn.example/frame.png"
    assert body["frame_images"][0]["frame_type"] == "first_frame"


def test_comet_payload():
    FakeClient.calls = []
    _patch("cometapi")
    ai.create_video_job("prompt", "4")
    call = FakeClient.calls[-1]
    fields = dict((k, v[1]) for k, v in call["files"])
    assert call["url"] == "https://api.cometapi.com/v1/videos"
    assert call["json"] is None
    assert "content-type" not in {k.lower(): v for k, v in call["headers"].items()}
    assert fields["model"] == "veo3.1-fast"
    assert fields["prompt"] == "prompt"
    assert fields["seconds"] == "4"
    assert fields["aspect_ratio"] == "9:16"
    assert fields["resolution"] == "720p"


def test_openrouter_download_content_url():
    FakeClient.calls = []
    FakeClient.get_responses = [
        FakeResponse({"id": "job_123", "status": "completed", "unsigned_urls": ["https://openrouter.ai/api/v1/videos/job_123/content?index=0"]}),
        FakeResponse(content=b"mp4"),
    ]
    _patch("openrouter")
    assert ai.download_video("job_123") == b"mp4"
    assert FakeClient.calls[-1]["headers"]["Authorization"] == "Bearer test-key"


def test_price_parsers():
    assert ai._openrouter_video_per_second({"duration_seconds_with_audio_720p": "0.05"}) == 0.05
    assert ai._openrouter_video_per_second({"cents_per_video_output_second_720p": "7"}) == 0.07
    assert ai._openrouter_video_per_second({"video_tokens": "0.0000012"}) == 0.0
    assert ai._cometapi_video_prices({"pricing": {"per_second": 0.028, "per_request": 0.4}}) == (0.028, 0.4)


def test_cost_fallback_helpers():
    original_per_second = ai.video_price_per_second
    original_clip_price = ai.video_clip_price
    try:
        ai.video_price_per_second = lambda mid="": 0.028 if mid == "cometapi:viduq3-turbo" else 0.0
        ai.video_clip_price = lambda mid="": 0.40
        assert ai.video_model_id_from_config({"provider": "cometapi", "model": "viduq3-turbo"}) == "cometapi:viduq3-turbo"
        assert ai.video_estimated_clip_cost("cometapi:viduq3-turbo", "4") == 0.112
        assert ai.video_estimated_clip_cost("cometapi:omni-fast", "4") == 0.40
        assert ai.video_model_max_seconds("cometapi:omni-fast") == 8
        assert ai.video_scene_count(8, ai.video_model_max_seconds("cometapi:omni-fast")) == 1
    finally:
        ai.video_price_per_second = original_per_second
        ai.video_clip_price = original_clip_price


def test_composer_trims_provider_clip_duration():
    from app.services.video_composer import compose_branded_video, _media_dur

    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "provider_ignored_seconds.mp4")
        out = os.path.join(tmp, "out.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=#222222:s=720x1280:d=10:r=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=10",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src,
        ], check=True)
        ok = compose_branded_video(
            [{"path": src, "seconds": 2}],
            out,
            {"accent": "#ED5E1F"},
            [],
            {"title": "Fale com a gente", "cta": "Fale com a gente"},
            "cariap.com.br",
            "",
        )
        assert ok
        dur = _media_dur(out)
        assert 4.4 <= dur <= 5.0, dur  # 2s clipe + 2.6s CTA, com folga de encoder


if __name__ == "__main__":
    original_config = ai.get_video_config
    original_client = ai.httpx.Client
    try:
        test_openrouter_payload()
        test_comet_payload()
        test_openrouter_download_content_url()
        test_price_parsers()
        test_cost_fallback_helpers()
        test_composer_trims_provider_clip_duration()
    finally:
        ai.get_video_config = original_config
        ai.httpx.Client = original_client
    print("video provider adapter tests: OK")
