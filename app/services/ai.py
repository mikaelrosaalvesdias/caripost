"""
AI integration service — supports Anthropic, OpenAI, and OpenRouter.
Mirrors caripost-web's lib/ai module.

Settings are stored in the existing settings table (db.py) with keys like:
  ai.provider, ai.model, ai.apiKey.anthropic, ai.apiKey.openai, ai.apiKey.openrouter
  image.provider, image.model, image.apiKey.openai, ...
  video.provider, video.model, video.apiKey.fal, ...

API keys are encrypted via security/encryption.py (Fernet).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..db import settings_get, settings_set
from ..security.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Settings whitelist
# ─────────────────────────────────────────────────────────────────────────────

SETTINGS_WHITELIST: Dict[str, List[str]] = {
    "ai": ["anthropic", "openai", "openrouter"],
    "image": ["openai", "openrouter", "fal"],
    "video": ["fal", "openai", "openrouter"],
}

EXTRA_KEYS = {"postiz.url", "postiz.apiKey", "ai.apiKey"}

DEFAULT_MODELS: Dict[str, Dict[str, List[str]]] = {
    "ai": {
        "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-8"],
        "openai": ["gpt-5.1", "gpt-5-mini", "gpt-4.1", "o4-mini"],
        "openrouter": ["anthropic/claude-sonnet-4.6", "openai/gpt-5.1", "google/gemini-2.5-pro", "meta-llama/llama-4-maverick", "deepseek/deepseek-chat-v3.1"],
    },
    "image": {
        "openai": ["gpt-image-1", "dall-e-3"],
        "openrouter": [],
        "fal": ["fal-ai/flux/dev", "fal-ai/flux-pro/v1.1-ultra"],
    },
    "video": {
        "fal": ["fal-ai/kling-video/v2.5-turbo/pro", "fal-ai/veo3"],
        "openai": ["sora-2"],
        "openrouter": [],
    },
}


def _is_valid_key(key: str) -> bool:
    if key in EXTRA_KEYS:
        return True
    parts = key.split(".")
    if len(parts) >= 2 and parts[0] in SETTINGS_WHITELIST:
        section = parts[0]
        if parts[1] == "provider" or parts[1] == "model":
            return True
        if parts[1] == "apiKey" and len(parts) >= 3 and parts[2] in SETTINGS_WHITELIST[section]:
            return True
    return False


def _mask_key(value: str) -> str:
    if not value or len(value) < 4:
        return "••••••••"
    return f"••••••••{value[-4:]}"


# ─────────────────────────────────────────────────────────────────────────────
# Settings access
# ─────────────────────────────────────────────────────────────────────────────

def get_setting(key: str) -> Optional[str]:
    row = settings_get(key=key)
    if row is None:
        return None
    return row.get("value") if isinstance(row, dict) else None


def set_setting(key: str, value: str) -> None:
    if not _is_valid_key(key):
        raise ValueError(f"Invalid settings key: {key}")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if "apiKey" in key and value:
        value = encrypt(value)
    settings_set(key=key, value=value, updated_at=now)


def get_credential(section: str, provider: str) -> Optional[str]:
    """Get decrypted API key for a section+provider, with fallbacks."""
    key = f"{section}.apiKey.{provider}"
    raw = get_setting(key)
    if raw:
        decrypted_val = decrypt(raw)
        if decrypted_val:
            return decrypted_val
    # fallback to ai.apiKey for anthropic
    if section == "ai" and provider in ("anthropic", "openai", "openrouter"):
        raw = get_setting("ai.apiKey")
        if raw:
            decrypted_val = decrypt(raw)
            if decrypted_val:
                return decrypted_val
    # fallback to env vars
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "fal": "FAL_KEY",
    }
    env_var = env_map.get(provider)
    if env_var:
        return os.environ.get(env_var)
    return None


def get_ai_config() -> Optional[Dict[str, Any]]:
    """Get AI config for text generation."""
    provider = get_setting("ai.provider") or "anthropic"
    api_key = get_credential("ai", provider)
    if not api_key:
        return None
    model = get_setting("ai.model")
    if not model:
        defaults = DEFAULT_MODELS["ai"].get(provider, [])
        model = defaults[0] if defaults else None
    if not model:
        # env fallback
        env_model = {
            "anthropic": "ANTHROPIC_MODEL",
            "openai": "OPENAI_MODEL",
            "openrouter": "OPENROUTER_MODEL",
        }
        model = os.environ.get(env_model.get(provider, ""), "claude-sonnet-4-6")
    return {"provider": provider, "apiKey": api_key, "model": model}


def is_ai_enabled() -> bool:
    return get_ai_config() is not None


def get_settings_map() -> Dict[str, Any]:
    """Get all AI-related settings with masked keys for UI display."""
    result: Dict[str, Any] = {}
    for section in ("ai", "image", "video"):
        provider = get_setting(f"{section}.provider")
        if not provider:
            defaults = SETTINGS_WHITELIST[section]
            provider = defaults[0] if defaults else ""
        model = get_setting(f"{section}.model") or ""
        key_masks: Dict[str, str] = {}
        for p in SETTINGS_WHITELIST[section]:
            raw = get_setting(f"{section}.apiKey.{p}")
            if raw:
                decrypted_val = decrypt(raw)
                if decrypted_val:
                    key_masks[p] = _mask_key(decrypted_val)
        result[section] = {"provider": provider, "model": model, "keyMasks": key_masks}
    # postiz
    result["postizUrl"] = get_setting("postiz.url") or ""
    raw_pk = get_setting("postiz.apiKey")
    if raw_pk:
        dec_pk = decrypt(raw_pk)
        result["postizKeyMask"] = _mask_key(dec_pk) if dec_pk else ""
    else:
        result["postizKeyMask"] = ""
    return result


# ─────────────────────────────────────────────────────────────────────────────
# AI completion
# ─────────────────────────────────────────────────────────────────────────────

def complete_ai(
    config: Dict[str, Any],
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> str:
    """Call AI provider and return text response."""
    provider = config.get("provider", "anthropic")
    api_key = config.get("apiKey", "")
    model = config.get("model", "")

    if not api_key or not model:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")

    if provider == "anthropic":
        return _call_anthropic(api_key, model, system, user, max_tokens)
    elif provider in ("openai", "openrouter"):
        return _call_openai_compat(provider, api_key, model, system, user, max_tokens)
    else:
        raise ValueError(f"Provedor não suportado: {provider}")


def _call_anthropic(api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        return ""


def _call_openai_compat(provider: str, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
    base_url = "https://openrouter.ai/api/v1" if provider == "openrouter" else "https://api.openai.com/v1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://caripost.n8nmikael.com.br"
        headers["X-Title"] = "Caripost"
    # OpenAI newer models (gpt-5+, o1, o3, o4) require max_completion_tokens instead of max_tokens
    if provider == "openai":
        body = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    else:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(f"{base_url}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def test_ai() -> Optional[str]:
    """Test AI connection. Returns None on success, error string on failure."""
    try:
        config = get_ai_config()
        if not config:
            return "IA não configurada — adicione sua chave em Configurações."
        result = complete_ai(config, "Responda apenas: ok", "ping", 100)
        if not result:
            return "Resposta vazia do provedor."
        return None
    except httpx.HTTPStatusError as exc:
        try:
            err_data = exc.response.json()
            err_msg = err_data.get("error", {}).get("message", "") or str(err_data)
            return f"HTTP {exc.response.status_code}: {err_msg}"
        except Exception:
            return f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except Exception as exc:
        return str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# List models
# ─────────────────────────────────────────────────────────────────────────────

def list_models(section: str, provider: str, api_key: Optional[str] = None) -> List[str]:
    """List available models for a section+provider."""
    if not api_key:
        api_key = get_credential(section, provider)
    defaults = DEFAULT_MODELS.get(section, {}).get(provider, [])

    try:
        if provider == "openrouter" and api_key:
            return _list_openrouter_models(api_key, section)
        elif provider == "openai" and api_key:
            return _list_openai_models(api_key, section)
        elif provider == "anthropic" and api_key:
            return _list_anthropic_models(api_key)
        elif provider == "fal":
            return defaults
    except Exception as exc:
        logger.warning("list_models failed for %s/%s: %s", section, provider, exc)

    return defaults


def _list_openrouter_models(api_key: str, section: str) -> List[str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("https://openrouter.ai/api/v1/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    modality_map = {"ai": "text", "image": "image", "video": "video"}
    target = modality_map.get(section, "text")
    models = []
    for m in data.get("data", []):
        modalities = m.get("architecture", {}).get("output_modalities", [])
        if target in modalities:
            models.append(m.get("id", ""))
    return sorted([m for m in models if m])[:50] or DEFAULT_MODELS.get(section, {}).get("openrouter", [])


def _list_openai_models(api_key: str, section: str) -> List[str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("https://api.openai.com/v1/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    all_ids = [m.get("id", "") for m in data.get("data", [])]
    if section == "ai":
        filtered = [m for m in all_ids if m and not any(x in m for x in ("audio", "tts", "embed", "whisper", "moderation"))]
        filtered = [m for m in filtered if m.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))]
        return sorted(set(filtered))[:50] or DEFAULT_MODELS["ai"]["openai"]
    elif section == "image":
        filtered = [m for m in all_ids if "image" in m or "dall-e" in m]
        return sorted(set(filtered))[:20] or DEFAULT_MODELS["image"]["openai"]
    elif section == "video":
        filtered = [m for m in all_ids if "sora" in m or "video" in m]
        return sorted(set(filtered))[:20] or DEFAULT_MODELS["video"]["openai"]
    return DEFAULT_MODELS.get(section, {}).get("openai", [])


def _list_anthropic_models(api_key: str) -> List[str]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("https://api.anthropic.com/v1/models?limit=100", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models = [m.get("id", "") for m in data.get("data", [])]
    return sorted([m for m in models if m])[:50] or DEFAULT_MODELS["ai"]["anthropic"]


# ─────────────────────────────────────────────────────────────────────────────
# High-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON object from text."""
    import re
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def generate_trends(company: Dict[str, Any]) -> Dict[str, Any]:
    """Generate trends briefing for a company via AI."""
    config = get_ai_config()
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")

    brand_kit = company.get("brand_kit") or {}
    system = (
        "Você é um estrategista de conteúdo brasileiro especializado em redes sociais. "
        'Responda SOMENTE com JSON válido neste formato: '
        '{"summary":"...","themes":[{"title":"...","why":"...","formats":["reels","carrossel"],"example":"..."}],"hashtags":["#...","#..."]} '
        "Gere 5 temas em alta para o nicho da empresa, com formato sugerido e exemplo de pauta. "
        "Sem markdown, sem texto fora do JSON, tudo em PT-BR."
    )
    user_parts = [f"Empresa: {company.get('name', '')}"]
    if company.get("segment"):
        user_parts.append(f"Segmento: {company['segment']}")
    if company.get("city"):
        user_parts.append(f"Cidade: {company['city']}/{company.get('state', '')}")
    if brand_kit.get("voice"):
        user_parts.append(f"Tom de voz: {brand_kit['voice']}")
    if brand_kit.get("persona"):
        user_parts.append(f"Persona da marca: {brand_kit['persona']}")
    user = "\n".join(user_parts)

    result = complete_ai(config, system, user, 2048)
    parsed = extract_json(result)
    if not parsed:
        raise ValueError("IA não retornou JSON válido.")
    return parsed


def generate_post_copy(company: Dict[str, Any], briefing: str, networks: List[str]) -> Dict[str, Any]:
    """Generate post copy via AI."""
    config = get_ai_config()
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")

    brand_kit = company.get("brand_kit") or {}
    system = (
        "Você é um social media sênior brasileiro. Responda SOMENTE com JSON válido: "
        '{"title":"...","copy":"...","hashtags":["..."]} '
        "Sem markdown, sem texto fora do JSON. "
        "Copy pronta para publicar, em PT-BR, com gancho forte na primeira linha, "
        "quebras de linha e CTA no final."
    )
    user_parts = [f"Empresa: {company.get('name', '')}"]
    if company.get("segment"):
        user_parts.append(f"Segmento: {company['segment']}")
    if brand_kit.get("voice"):
        user_parts.append(f"Tom de voz: {brand_kit['voice']}")
    if brand_kit.get("persona"):
        user_parts.append(f"Persona da marca: {brand_kit['persona']}")
    if networks:
        user_parts.append(f"Redes alvo: {', '.join(networks)}")
    user_parts.append(f"Briefing do post: {briefing}")
    user = "\n".join(user_parts)

    result = complete_ai(config, system, user, 1024)
    parsed = extract_json(result)
    if not parsed:
        raise ValueError("IA não retornou JSON válido.")
    hashtags = parsed.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags = " ".join(hashtags)
    return {
        "title": parsed.get("title", ""),
        "copy": parsed.get("copy", ""),
        "hashtags": hashtags,
    }
