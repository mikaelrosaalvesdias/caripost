"""Smoke tests for image pricing metadata and per-client prompt overrides.

Run inside the app container/image, where project dependencies are installed:
  python scripts/test_image_pricing_and_prompts_no_api.py
"""
from __future__ import annotations

from app.services import ai


def test_comet_image_catalog_price():
    original_key = ai._cometapi_key
    original_catalog = ai._cometapi_model_catalog
    original_learned = ai._learned_image_price
    try:
        ai._cometapi_key = lambda: "test-key"
        ai._learned_image_price = lambda _mid: 0.0
        ai._cometapi_model_catalog = lambda: {
            "gpt-image-2-all": {"pricing": {"per_request": 0.04}},
            "doubao-seedream-5-0-260128": {"pricing": {"per_request": 0.028}},
            "gpt-image-1.5": {"pricing": {"input": 6.4, "output": 25.6}},
        }
        rows = {m["id"]: m for m in ai.cometapi_image_models()}
        assert rows["cometapi:gpt-image-2-all"]["price_per_image"] == 0.04
        assert rows["cometapi:gpt-image-2-all"]["price_source"] == "catalog_api"
        assert rows["cometapi:doubao-seedream-5-0-260128"]["price_per_image"] == 0.028
        assert rows["cometapi:gpt-image-1.5"]["price_source"] == "fallback"
    finally:
        ai._cometapi_key = original_key
        ai._cometapi_model_catalog = original_catalog
        ai._learned_image_price = original_learned


def test_learned_image_price_overrides_fallback():
    original_learned = ai._learned_image_price
    try:
        ai._learned_image_price = lambda mid: 0.1234 if mid == "m1" else 0.0
        assert ai._image_price_fields("m1", 0.04, "fallback") == {
            "price_per_image": 0.1234,
            "price_source": "usage_learned",
        }
    finally:
        ai._learned_image_price = original_learned


def test_per_client_image_and_video_prompt_overrides():
    company = {
        "id": "co1",
        "name": "CARIAP",
        "segment": "SVAs",
        "brand_kit": {
            "colors": {"accent": "#ED5E1F"},
            "creative_config": {
                "image": {
                    "system_prompt": "IMG-SYS {company}",
                    "scene_template": "{system_prompt} | {visual} | {brand_fix} | {client_rules}",
                    "brand_fix": "IMG-BRAND {color}",
                },
                "video": {
                    "system_prompt": "VID-SYS {company}",
                    "scene_template": "{system_prompt} | {visual} | {brand_fix}",
                    "brand_fix": "VID-BRAND {color}",
                },
                "briefing": {
                    "video_storyboard_system": "BRIEF-SYS {duration_rule} {tone_rule}",
                    "video_storyboard_user": "BRIEF-USER {company} {product_context} {theme} {video_prompt}",
                },
            },
            "client_rules": "Nunca usar fundo genérico.",
        },
    }
    img = ai.build_image_prompt(company, "ExitLag", "gamer em casa", title="Lag zero", target_product="ExitLag")
    assert "IMG-SYS CARIAP" in img
    assert "gamer em casa" in img
    assert "IMG-BRAND #ED5E1F" in img
    assert "Nunca usar fundo genérico" in img

    vid = ai.build_video_prompt(company, "ExitLag", "gamer comemorando")
    assert "VID-SYS CARIAP" in vid
    assert "VID-BRAND #ED5E1F" in vid
    assert "gamer comemorando" in vid


def test_per_client_video_storyboard_prompt_override():
    company = {
        "id": "co1",
        "name": "CARIAP",
        "segment": "SVAs",
        "brand_kit": {
            "creative_config": {
                "briefing": {
                    "video_storyboard_system": "BRIEF-SYS {duration_rule} {tone_rule}",
                    "video_storyboard_user": "BRIEF-USER {company} {product_context} {theme} {video_prompt}",
                }
            }
        },
    }
    captured = {}
    originals = {
        "cheap_text_config": ai.cheap_text_config,
        "get_ai_config": ai.get_ai_config,
        "complete_ai": ai.complete_ai,
        "_video_brief_context": ai._video_brief_context,
    }
    try:
        ai.cheap_text_config = lambda _cfg: {"provider": "fake"}
        ai.get_ai_config = lambda: {}
        ai._video_brief_context = lambda _company, _theme: "CTX-PRODUTO "

        def fake_complete(_config, system, user, _max_tokens):
            captured["system"] = system
            captured["user"] = user
            return '{"scenes":[{"desc":"cena real do app","seconds":8}]}'

        ai.complete_ai = fake_complete
        out = ai.build_video_storyboard(company, "tema real", "direcao visual", 8, 1, 8)
        assert out and out[0]["desc"] == "cena real do app"
        assert captured["system"].startswith("BRIEF-SYS Quebre em EXATAMENTE 1 CENAS")
        assert "BRIEF-USER CARIAP CTX-PRODUTO tema real direcao visual" in captured["user"]
    finally:
        ai.cheap_text_config = originals["cheap_text_config"]
        ai.get_ai_config = originals["get_ai_config"]
        ai.complete_ai = originals["complete_ai"]
        ai._video_brief_context = originals["_video_brief_context"]


def test_default_video_prompts_follow_adaptive_briefing_rules():
    company = {
        "id": "co1",
        "name": "CARIAP",
        "segment": "SVAs para provedores",
        "brand_kit": {"colors": {"accent": "#ED5E1F"}},
    }
    prompt = ai.build_video_prompt(company, "ExitLag para provedores", "gamer percebe conexao estavel")
    assert "CLIPE DE FUNDO" in prompt
    assert "UMA ação principal" in prompt
    assert "UM movimento de câmera" in prompt
    assert "NÃO faça b-roll genérico" in prompt
    assert "texto, logo, legenda, CTA" in prompt


def test_default_video_storyboard_prompt_uses_carousel_quality_rules():
    company = {"id": "co1", "name": "CARIAP", "segment": "SVAs para provedores", "brand_kit": {}}
    captured = {}
    originals = {
        "cheap_text_config": ai.cheap_text_config,
        "get_ai_config": ai.get_ai_config,
        "complete_ai": ai.complete_ai,
        "_video_brief_context": ai._video_brief_context,
    }
    try:
        ai.cheap_text_config = lambda _cfg: {"provider": "fake"}
        ai.get_ai_config = lambda: {}
        ai._video_brief_context = lambda _company, _theme: "PRODUTO/APP REAL EM FOCO: [ExitLag] Funções: redução de latência. "

        def fake_complete(_config, system, user, _max_tokens):
            captured["system"] = system
            captured["user"] = user
            return '{"scenes":[{"desc":"gamer brasileiro percebe partida estavel, camera push-in leve, luz neon controlada","seconds":8}]}'

        ai.complete_ai = fake_complete
        out = ai.build_video_storyboard(company, "ExitLag para reduzir guerra de preço", "", 8, 1, 8)
        assert out and "gamer brasileiro" in out[0]["desc"]
        assert "dor real por trás do tema" in captured["system"]
        assert "crença errada do público" in captured["system"]
        assert "NÃO gere b-roll genérico" in captured["system"]
        assert "redução da guerra de preço" in captured["system"]
        assert "DADOS FIXOS DA MARCA E DO CLIENTE" in captured["user"]
        assert "PRODUTO/APP REAL EM FOCO" in captured["user"]
    finally:
        ai.cheap_text_config = originals["cheap_text_config"]
        ai.get_ai_config = originals["get_ai_config"]
        ai.complete_ai = originals["complete_ai"]
        ai._video_brief_context = originals["_video_brief_context"]


if __name__ == "__main__":
    test_comet_image_catalog_price()
    test_learned_image_price_overrides_fallback()
    test_per_client_image_and_video_prompt_overrides()
    test_per_client_video_storyboard_prompt_override()
    test_default_video_prompts_follow_adaptive_briefing_rules()
    test_default_video_storyboard_prompt_uses_carousel_quality_rules()
    print("image pricing + prompt override tests: OK")
