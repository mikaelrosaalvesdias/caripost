import unittest
from unittest.mock import AsyncMock

from app.social.composio_provider import ComposioConfig, ComposioSocialProvider


class ComposioResearchTests(unittest.IsolatedAsyncioTestCase):
    def provider(self):
        return ComposioSocialProvider(ComposioConfig(api_key="test", base_url="https://example.test/api/v3.1"))

    async def test_business_discovery_uses_facebook_login_and_relative_proxy(self):
        provider = self.provider()
        provider._request = AsyncMock(side_effect=[
            {
                "successful": True,
                "data": {"data": [{
                    "id": "page-1",
                    "instagram_business_account": {"id": "ig-research", "username": "cariap"},
                }]},
            },
            {
                "status": 200,
                "data": {"business_discovery": {
                    "id": "ig-target", "username": "riocable",
                    "media": {"data": [{"id": "media-1", "media_type": "IMAGE"}]},
                }},
            },
        ])

        result = await provider.discover_instagram_business(
            handle="@riocable",
            connection={
                "id": "local-1", "user_id": "brand:cariap",
                "composio_connection_id": "ca-facebook",
            },
            media_limit=4,
        )

        self.assertEqual(result["id"], "ig-target")
        self.assertEqual(result["media"][0]["id"], "media-1")
        managed_call = provider._request.await_args_list[0]
        self.assertEqual(managed_call.kwargs["json"]["version"], "20260721_00")
        proxy_call = provider._request.await_args_list[1]
        self.assertEqual(proxy_call.args[1], "/tools/execute/proxy")
        self.assertEqual(proxy_call.kwargs["json"]["endpoint"], "/v23.0/ig-research")
        self.assertEqual(proxy_call.kwargs["json"]["connected_account_id"], "ca-facebook")

    async def test_owned_instagram_tools_are_pinned_and_wrappers_are_parsed(self):
        provider = self.provider()
        provider._request = AsyncMock(side_effect=[
            {"successful": True, "data": {
                "id": "ig-own", "username": "cariap", "profile_picture_url": "https://cdn.example/avatar.jpg",
            }},
            {"successful": True, "data": {"data": [{
                "id": "media-own", "media_type": "IMAGE", "media_url": "https://cdn.example/post.jpg",
            }]}},
        ])

        result = await provider.get_owned_instagram_profile_media(
            connection={"user_id": "brand:cariap", "composio_connection_id": "ca-instagram"},
            media_limit=4,
        )

        self.assertEqual(result["username"], "cariap")
        self.assertEqual(result["media"][0]["id"], "media-own")
        for call in provider._request.await_args_list:
            self.assertEqual(call.kwargs["json"]["version"], "20260730_00")
            self.assertEqual(call.kwargs["json"]["connected_account_id"], "ca-instagram")

    async def test_facebook_page_is_matched_by_url_and_download_candidates_are_returned(self):
        provider = self.provider()
        provider._request = AsyncMock(side_effect=[
            {"successful": True, "data": {"data": [{
                "id": "42", "name": "Rio Cable", "link": "https://www.facebook.com/riocable",
                "website": "https://riocable.com.br", "picture": {"url": "https://cdn.example/small.jpg"},
            }]}},
            {"successful": True, "data": {
                "id": "42", "name": "Rio Cable", "link": "https://www.facebook.com/riocable",
                "website": "https://riocable.com.br",
                "picture": {"data": {"url": "https://cdn.example/avatar.jpg"}},
                "cover": {"source": "https://cdn.example/cover.jpg"},
            }},
            {"successful": True, "data": {"data": [{
                "id": "photo-1", "from": {"id": "42", "name": "Rio Cable"},
                "album": {"id": "album-1", "name": "Campanhas"},
                "images": [{"source": "https://cdn.example/photo.jpg", "width": 1600, "height": 1200}],
                "link": "https://www.facebook.com/photo-1",
            }]}},
        ])

        result = await provider.discover_facebook_page(
            company_name="Rio Cable", facebook="https://facebook.com/riocable",
            website="https://riocable.com.br",
            connection={"user_id": "brand:cariap", "composio_connection_id": "ca-facebook"},
            photo_limit=4,
        )

        self.assertEqual(result["id"], "42")
        self.assertEqual(result["profile_picture_url"], "https://cdn.example/avatar.jpg")
        self.assertEqual(result["photos"][0]["media_url"], "https://cdn.example/photo.jpg")
        for call in provider._request.await_args_list:
            if call.args[1] != "/tools/execute/proxy":
                self.assertEqual(call.kwargs["json"]["version"], "20260721_00")

    async def test_facebook_connection_probe_lists_and_selects_managed_page(self):
        provider = self.provider()
        provider._request = AsyncMock(return_value={
            "successful": True,
            "data": {"data": [
                {"id": "page-1", "name": "Outra"},
                {
                    "id": "page-2", "name": "CARIAP", "username": "cariap",
                    "instagram_business_account": {"id": "ig-2", "username": "cariap"},
                },
            ]},
        })

        result = await provider.test_connection(
            platform="facebook",
            connection={"user_id": "brand:cariap", "composio_connection_id": "ca-facebook"},
            selected_page_id="page-2",
        )

        self.assertTrue(result["tool_tested"])
        self.assertEqual(result["selected_page"]["id"], "page-2")
        self.assertEqual(result["managed_pages"][1]["instagram_business_account"]["id"], "ig-2")
        call = provider._request.await_args
        self.assertEqual(call.args[1], "/tools/execute/FACEBOOK_LIST_MANAGED_PAGES")
        self.assertEqual(call.kwargs["json"]["version"], "20260721_00")


if __name__ == "__main__":
    unittest.main()
