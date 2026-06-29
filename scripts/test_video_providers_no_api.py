"""Smoke tests for video provider adapters without calling paid APIs.

Run inside the app container/image, where project dependencies are installed:
  python scripts/test_video_providers_no_api.py
"""
from __future__ import annotations

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


if __name__ == "__main__":
    original_config = ai.get_video_config
    original_client = ai.httpx.Client
    try:
        test_openrouter_payload()
        test_comet_payload()
        test_openrouter_download_content_url()
    finally:
        ai.get_video_config = original_config
        ai.httpx.Client = original_client
    print("video provider adapter tests: OK")
