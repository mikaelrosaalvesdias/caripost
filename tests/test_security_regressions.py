import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from app.services import ai
from app.social import composio_provider


def _dns_row(address: str, port: int = 443):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (address, port))


class _StreamResponse:
    def __init__(self, *, status=200, headers=None, chunks=None, encoding="utf-8"):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks or []
        self.encoding = encoding

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_bytes(self):
        yield from self._chunks


class _HTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class SiteFetchSecurityTests(unittest.TestCase):
    def test_private_initial_target_is_rejected_before_http(self):
        client_factory = Mock()
        with patch.object(socket, "getaddrinfo", return_value=[_dns_row("127.0.0.1", 80)]), \
             patch.object(ai.httpx, "Client", client_factory):
            result = ai._fetch_site_text("http://internal.example")

        self.assertEqual(result, "")
        client_factory.assert_called_once()
        client_factory.return_value.stream.assert_not_called()

    def test_redirect_to_private_target_is_not_requested(self):
        client = _HTTPClient([
            _StreamResponse(status=302, headers={"location": "http://127.0.0.1/admin"}),
        ])

        def resolve(host, port, **_kwargs):
            if host == "public.example":
                return [_dns_row("93.184.216.34", port)]
            return [_dns_row("127.0.0.1", port)]

        with patch.object(socket, "getaddrinfo", side_effect=resolve), \
             patch.object(ai.httpx, "Client", return_value=client):
            result = ai._fetch_site_text("https://public.example/start")

        self.assertEqual(result, "")
        self.assertEqual([call[1] for call in client.calls], ["https://public.example/start"])

    def test_streamed_response_is_capped_after_decompression(self):
        client = _HTTPClient([
            _StreamResponse(
                headers={"content-type": "text/html"},
                chunks=[b"x" * (3 * 1024 * 1024), b"y"],
            ),
        ])
        with patch.object(socket, "getaddrinfo", return_value=[_dns_row("93.184.216.34")]), \
             patch.object(ai.httpx, "Client", return_value=client):
            result = ai._fetch_site_text("https://public.example")

        self.assertEqual(result, "")

    def test_safe_html_is_fetched_without_environment_proxy(self):
        html = b"<html><head><title>Rio Cable</title><meta name='description' content='Conectividade'></head><body>Site oficial</body></html>"
        client = _HTTPClient([
            _StreamResponse(headers={"content-type": "text/html; charset=utf-8"}, chunks=[html]),
        ])
        constructor = Mock(return_value=client)
        with patch.object(socket, "getaddrinfo", return_value=[_dns_row("93.184.216.34")]), \
             patch.object(ai.httpx, "Client", constructor):
            result = ai._fetch_site_text("https://public.example")

        self.assertIn("Rio Cable", result)
        self.assertIn("Conectividade", result)
        self.assertFalse(constructor.call_args.kwargs["trust_env"])


class _UploadResponse:
    status_code = 200
    text = "ok"

    def __init__(self, url):
        self.url = url

    def json(self):
        return {"data": {"url": self.url}}


class _AsyncHTTPClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class RehostMediaSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rehost_requires_exact_origin_canonical_path_and_brand(self):
        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "target-1" / "generated"
            media.mkdir(parents=True)
            Image.new("RGB", (16, 16), (20, 30, 40)).save(media / "post.png")
            calls = []
            client = _AsyncHTTPClient(
                _UploadResponse("https://tmpfiles.org/abc/post.jpg"), calls,
            )
            with patch.dict(os.environ, {
                "ADULT_META_MEDIA_ROOT": root,
                "UPLOAD_URL_PREFIX": "/uploads",
            }, clear=False), \
                 patch.object(composio_provider, "_setting_value", return_value="https://media.example:8443"), \
                 patch("httpx.AsyncClient", return_value=client):
                result = await composio_provider._rehost_media(
                    "https://media.example:8443/uploads/target-1/generated/post.png",
                    False,
                    "target-1",
                )
                self.assertEqual(result, "https://tmpfiles.org/dl/abc/post.jpg")

                unsafe = (
                    "http://media.example:8443/uploads/target-1/generated/post.png",
                    "https://media.example/uploads/target-1/generated/post.png",
                    "https://user@media.example:8443/uploads/target-1/generated/post.png",
                    "https://media.example:8443/uploads/other-1/generated/post.png",
                    "https://media.example:8443/uploads/target-1/%2e%2e/post.png",
                    "//media.example:8443/uploads/target-1/generated/post.png",
                )
                with self.assertLogs("caripost.social", level="ERROR"):
                    for url in unsafe:
                        with self.subTest(url=url):
                            self.assertIsNone(await composio_provider._rehost_media(
                                url, False, "target-1",
                            ))

            self.assertEqual(len(calls), 1)

    async def test_rehost_rejects_untrusted_upload_response_origin(self):
        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "target-1"
            media.mkdir()
            Image.new("RGB", (8, 8), (0, 0, 0)).save(media / "post.png")
            client = _AsyncHTTPClient(
                _UploadResponse("https://evil.example/abc/post.jpg"), [],
            )
            with patch.dict(os.environ, {
                "ADULT_META_MEDIA_ROOT": root,
                "UPLOAD_URL_PREFIX": "/uploads",
            }, clear=False), patch("httpx.AsyncClient", return_value=client):
                with self.assertLogs("caripost.social", level="ERROR"):
                    result = await composio_provider._rehost_media(
                        "/uploads/target-1/post.png", False, "target-1",
                    )

        self.assertIsNone(result)

    def test_public_media_allowlist_requires_a_domain_boundary(self):
        self.assertTrue(composio_provider._is_publicly_accessible_url(
            "https://cdn.tmpfiles.org/media/post.jpg",
        ))
        self.assertFalse(composio_provider._is_publicly_accessible_url(
            "https://eviltmpfiles.org/media/post.jpg",
        ))
        self.assertFalse(composio_provider._is_publicly_accessible_url(
            "https://tmpfiles.org:bad/media/post.jpg",
        ))


if __name__ == "__main__":
    unittest.main()
