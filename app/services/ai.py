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
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..db import settings_get, settings_set
from ..security.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Settings whitelist
# ─────────────────────────────────────────────────────────────────────────────

SETTINGS_WHITELIST: Dict[str, List[str]] = {
    "ai": ["anthropic", "openai", "openrouter", "cometapi"],
    "image": ["openai", "openrouter", "fal", "cometapi", "piapi", "omniroute"],
    "video": ["fal", "openai", "openrouter", "cometapi"],
}

EXTRA_KEYS = {"postiz.url", "postiz.apiKey", "ai.apiKey"}

DEFAULT_MODELS: Dict[str, Dict[str, List[str]]] = {
    "ai": {
        "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-8"],
        "openai": ["gpt-5.1", "gpt-5-mini", "gpt-4.1", "o4-mini"],
        "openrouter": ["anthropic/claude-sonnet-4.6", "openai/gpt-5.1", "google/gemini-2.5-pro", "meta-llama/llama-4-maverick", "deepseek/deepseek-chat-v3.1"],
        # CometAPI (texto/roteiro) — ids reais do catálogo; preservam acentos. Claude = melhor copy PT-BR.
        "cometapi": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001",
                     "gpt-5.4", "gpt-5.4-mini", "gpt-4o", "gemini-3.5-pro", "gemini-3.1-flash", "deepseek-v3.2"],
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
    """Get AI config for text generation. OpenAI is retired — anything pointing to OpenAI
    is forced through OpenRouter (same models, OpenRouter token)."""
    provider = get_setting("ai.provider") or "anthropic"
    model = get_setting("ai.model")
    if provider == "omniroute":   # gateway das assinaturas (grátis) — ATENÇÃO: remove acentos do texto
        return {"provider": "omniroute", "apiKey": _omniroute_key() or "x", "model": model or "high-availability"}
    if provider == "cometapi":    # texto via CometAPI (OpenAI-compat) — preserva acentos
        return {"provider": "cometapi", "apiKey": _cometapi_key(), "model": model or "gpt-4o"}
    if provider == "openai":
        provider = "openrouter"
        # Mantém o modelo, mas no formato do OpenRouter (precisa do prefixo do provedor).
        if model and "/" not in model:
            model = "openai/" + model
    api_key = get_credential("ai", provider) or (_openrouter_key() if provider == "openrouter" else None)
    if not api_key:
        return None
    if not model:
        defaults = DEFAULT_MODELS["ai"].get(provider, [])
        model = defaults[0] if defaults else None
    if not model:
        env_model = {"anthropic": "ANTHROPIC_MODEL", "openai": "OPENAI_MODEL", "openrouter": "OPENROUTER_MODEL"}
        model = os.environ.get(env_model.get(provider, ""), "openai/gpt-4.1-mini")
    if provider == "openrouter" and model and "/" not in model:
        model = "openai/" + model
    return {"provider": provider, "apiKey": api_key, "model": model}


# Cheaper models for TEXT generation (briefing, copy, trends). Image/video stay on
# their own (better) config. Override globally via setting `ai.textModel`.
# Non-reasoning cheap models: gpt-5-mini/o-series burn the token budget on hidden
# reasoning (empty output on large inputs), so use a fast non-reasoning model for text.
_CHEAP_TEXT_MODELS = {
    "openai": "gpt-4.1-mini",
    "openrouter": "openai/gpt-4.1-mini",
    "anthropic": "claude-haiku-4-5",
    "cometapi": "gpt-4o",
}


def cheap_text_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a copy of the AI config using a cheaper text model.

    Keeps cost low for briefing/copy generation (user is token-constrained).
    Honors the `ai.textModel` setting if set; otherwise picks a cheap default
    for the provider; falls back to the configured model if provider unknown.
    """
    if not config:
        return config
    override = (get_setting("ai.textModel") or "").strip()
    provider = config.get("provider", "")
    model = override or _CHEAP_TEXT_MODELS.get(provider) or config.get("model")
    return {**config, "model": model}


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

    try:
        if provider == "anthropic":
            return _call_anthropic(api_key, model, system, user, max_tokens)
        elif provider in ("openai", "openrouter", "omniroute", "cometapi"):
            return _call_openai_compat(provider, api_key, model, system, user, max_tokens)
        else:
            raise ValueError(f"Provedor não suportado: {provider}")
    except Exception as e:
        es = str(e)
        # TRANSBORDO DE TEXTO: provedor caiu (403/saldo/cota/429/auth) → tenta os OUTROS em ordem (OmniRoute grátis por último).
        if any(x in es for x in ("403", "429", "401", "402", "Forbidden", "额度", "余额", "quota", "insufficient", "balance")):
            for alt in _alt_text_configs(provider):
                try:
                    return _call_openai_compat(alt["provider"], alt["apiKey"], alt["model"], system, user, max_tokens)
                except Exception:
                    continue
        raise


def _alt_text_configs(failed_provider: str):
    """Provedores de TEXTO alternativos p/ transbordo, em ordem: OpenRouter → OmniRoute (grátis) → CometAPI.
    OmniRoute é último recurso (grátis, sua assinatura; pode comer acento) — texto imperfeito > legenda VAZIA."""
    out = []
    for p in ("openrouter", "omniroute", "cometapi"):
        if p == failed_provider:
            continue
        if p == "openrouter":
            key, model = _openrouter_key(), "openai/gpt-4o"
        elif p == "cometapi":
            key, model = _cometapi_key(), "gpt-4o"
        else:
            key, model = (_omniroute_key() or "x"), "high-availability"
        if key:
            out.append({"provider": p, "apiKey": key, "model": model})
    return out


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
    if provider == "omniroute":
        base_url = _omniroute_base()
    elif provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    elif provider == "cometapi":
        base_url = "https://api.cometapi.com/v1"   # OpenAI-compat; PRESERVA acentos (OmniRoute não)
    else:
        base_url = "https://api.openai.com/v1"
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
    body["stream"] = False   # OmniRoute faz streaming por padrão; força JSON único
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

def _repair_truncated_json(s: str) -> Optional[str]:
    """Best-effort close of a JSON object that got cut off (e.g. token limit)."""
    stack: List[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack:
                stack.pop()
    if not stack and not in_str:
        return None  # nothing to repair
    repaired = s.rstrip().rstrip(",")
    if in_str:
        repaired += '"'
    repaired += "".join(reversed(stack))
    return repaired


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON object from text, tolerating truncated responses."""
    import re
    if not text:
        return None
    match = re.search(r'\{[\s\S]*\}', text)
    candidate = match.group() if match else (text[text.find("{"):] if "{" in text else "")
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(candidate)
        if repaired:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                return None
        return None


def generate_trends(company: Dict[str, Any]) -> Dict[str, Any]:
    """Generate trends briefing for a company via AI."""
    config = cheap_text_config(get_ai_config())
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


def get_image_config() -> Optional[Dict[str, Any]]:
    """Image-gen config. Supports OpenAI and OpenRouter (Image API)."""
    provider = (get_setting("image.provider") or "openrouter").strip()
    model = get_setting("image.model") or ""
    # OmniRoute (gateway das assinaturas) — imagem grátis pela assinatura.
    if provider == "omniroute" or model.lower().startswith("omni:"):
        return {"provider": "omniroute", "model": model or "omni:antigravity/gemini-3.1-flash-image",
                "apiKey": _omniroute_key() or "x", "quality": get_setting("image.quality") or "high"}
    # OpenAI image is retired — force everything to OpenRouter. A bare OpenAI model name
    # (no "/") gets dropped in favor of the OpenRouter default.
    if provider == "openai" or not provider:
        provider = "openrouter"
        if model and "/" not in model:
            model = ""
    if provider == "openrouter" or (model and "/" in model):
        provider = "openrouter"
        api_key = _openrouter_key()
    else:
        api_key = get_credential("image", provider)
    if not api_key:
        api_key = _openrouter_key()
        provider = "openrouter"
    if not api_key:
        return None
    if not model:
        model = "google/gemini-2.5-flash-image"
    quality = get_setting("image.quality") or "high"
    return {"provider": provider, "apiKey": api_key, "model": model, "quality": quality}


def _openrouter_key() -> str:
    return (get_credential("image", "openrouter")
            or get_credential("ai", "openrouter")
            or get_setting("token:openrouter")
            or get_setting("openrouter.apiKey")
            or os.environ.get("OPENROUTER_API_KEY") or "").strip()


def _omniroute_base() -> str:
    return (get_setting("omniroute.base") or os.environ.get("OMNIROUTE_BASE")
            or "http://172.17.0.1:20128/v1").rstrip("/")


def _omniroute_key() -> str:
    return (get_credential("image", "omniroute") or get_setting("token:omniroute")
            or os.environ.get("OMNIROUTE_API_KEY") or "").strip()


def generate_image_omniroute(model: str, prompt: str, size: str = "1080x1350"):
    """Gera imagem via OmniRoute (gateway das assinaturas, OpenAI-compat). Retorna (png, cost=0)."""
    import base64
    key = _omniroute_key()
    body = {"model": model, "prompt": prompt[:4000], "n": 1}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        r = c.post(_omniroute_base() + "/images/generations", headers=headers, json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", {}).get("message") or r.text[:300]
        except Exception:
            detail = r.text[:300]
        raise ValueError(f"Falha OmniRoute imagem (HTTP {r.status_code}): {detail}")
    item = (r.json().get("data") or [{}])[0]
    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64), 0.0
    url = item.get("url") or item.get("image_url")
    if url:
        with httpx.Client(timeout=60) as c:
            return c.get(url).content, 0.0
    raise ValueError("OmniRoute não retornou imagem.")


# Top-10 curados (slug real do OpenRouter, nome estilo arena, qualidade, preço/img USD aprox.).
# Espelha o ranking Text-to-Image; reve-2.0/ideogram-4.0/uni-1.1 NÃO existem no OpenRouter.
CURATED_IMAGE = [
    ("reve-2.0", "reve-2.0 (Reve — API própria)", "Top", 0.040),
    ("openai/gpt-5.4-image-2", "gpt-5.4-image-2", "Top", 0.040),
    ("google/gemini-3.1-flash-image-preview", "gemini-3.1-flash-image (nano-banana-2)", "Top", 0.039),
    ("microsoft/mai-image-2.5", "mai-image-2.5", "Top", 0.040),
    ("google/gemini-3-pro-image-preview", "gemini-3-pro-image (nano-banana-pro)", "Top", 0.134),
    ("openai/gpt-5-image", "gpt-5-image", "Alta", 0.040),
    ("x-ai/grok-imagine-image-quality", "grok-imagine-image-quality", "Alta", 0.040),
    ("bytedance-seed/seedream-4.5", "seedream-4.5", "Top", 0.030),
    ("black-forest-labs/flux.2-pro", "flux.2-pro", "Alta", 0.050),
    ("google/gemini-2.5-flash-image", "gemini-2.5-flash-image (nano-banana)", "Alta", 0.039),
    ("sourceful/riverflow-v2.5-pro", "riverflow-v2.5-pro", "Boa", 0.040),
]

# Top-10 vídeo (slug real do OpenRouter). gemini-omni-flash/happyhorse NÃO existem lá.
# Modelos de VÍDEO do OpenRouter (id real do /videos/models). (id, nome, qualidade, preço USD/clipe, MAX_SEGUNDOS por clipe da doc).
CURATED_VIDEO = [
    ("google/veo-3.1", "veo-3.1", "Top", 1.20, 8),
    ("openai/sora-2-pro", "sora-2-pro", "Top", 1.00, 12),
    ("bytedance/seedance-2.0", "seedance-2.0", "Top", 0.40, 12),
    ("kwaivgi/kling-v3.0-pro", "kling-v3.0-pro", "Top", 0.40, 10),
    ("alibaba/wan-2.7", "wan-2.7", "Top", 0.40, 5),
    ("google/veo-3.1-fast", "veo-3.1-fast", "Alta", 0.96, 8),
    ("bytedance/seedance-2.0-fast", "seedance-2.0-fast", "Alta", 0.25, 12),
    ("bytedance/seedance-1-5-pro", "seedance-1.5-pro", "Alta", 0.30, 10),
    ("kwaivgi/kling-v3.0-std", "kling-v3.0-std", "Alta", 0.25, 10),
    ("kwaivgi/kling-video-o1", "kling-video-o1", "Alta", 0.30, 10),
    ("minimax/hailuo-2.3", "hailuo-2.3", "Alta", 0.30, 10),
    ("x-ai/grok-imagine-video", "grok-imagine-video", "Alta", 0.25, 6),
    ("alibaba/wan-2.6", "wan-2.6", "Alta", 0.25, 5),
    ("google/veo-3.1-lite", "veo-3.1-lite", "Boa", 0.18, 8),
]

# Modelos de VÍDEO da CometAPI que usam o contrato documentado POST/GET /v1/videos.
# Kling/Runway/xAI ficam fora daqui porque usam rotas próprias; listar esses ids no mesmo
# seletor fazia o app cobrar tentativa em endpoint errado.
CURATED_VIDEO_COMET = [
    ("veo3.1", "veo3.1", "Top", 2.56, 8),
    ("sora-2-pro", "sora-2-pro", "Top", 2.88, 12),
    ("doubao-seedance-2-0", "seedance-2.0", "Top", 0.40, 12),
    ("veo3.1-fast", "veo3.1-fast", "Alta", 0.64, 8),
    ("sora-2", "sora-2", "Alta", 0.96, 12),
    ("doubao-seedance-1-5-pro", "seedance-1.5-pro", "Alta", 0.30, 10),
    ("wan2.7", "wan-2.7", "Alta", 0.40, 5),
    ("viduq3", "viduq3", "Alta", 0.448, 8),
    ("viduq3-turbo", "viduq3-turbo", "Boa", 0.224, 8),
    ("veo3", "veo3", "Alta", 2.56, 8),
    ("omni-fast", "omni-fast", "Boa", 0.40, 4),
]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _openrouter_video_per_second(pricing_skus: Dict[str, Any]) -> float:
    """USD/s for the 720p text/video path we request. Returns 0 when the API exposes token pricing only."""
    if not isinstance(pricing_skus, dict):
        return 0.0
    for key in (
        "duration_seconds_with_audio_720p",
        "text_to_video_duration_seconds_720p",
        "duration_seconds_720p",
        "per-video-second-720p",
        "per-video-second",
        "duration_seconds_with_audio",
        "text_to_video_duration_seconds",
        "duration_seconds",
    ):
        val = _safe_float(pricing_skus.get(key))
        if val > 0:
            return val
    for key in ("cents_per_video_output_second_720p", "cents_per_video_output_second_480p"):
        val = _safe_float(pricing_skus.get(key))
        if val > 0:
            return val / 100.0
    return 0.0


def _openrouter_video_catalog() -> Dict[str, Dict[str, Any]]:
    key = _openrouter_key()
    if not key:
        return {}
    try:
        with httpx.Client(timeout=20) as c:
            res = c.get("https://openrouter.ai/api/v1/videos/models", headers={"Authorization": f"Bearer {key}"})
        if res.status_code >= 400:
            return {}
        return {m.get("id"): m for m in (res.json().get("data") or []) if m.get("id")}
    except Exception:
        return {}


def _cometapi_model_catalog() -> Dict[str, Dict[str, Any]]:
    key = _cometapi_key()
    if not key:
        return {}
    try:
        with httpx.Client(timeout=20) as c:
            res = c.get("https://api.cometapi.com/api/models", headers={"Authorization": f"Bearer {key}"})
        if res.status_code >= 400:
            return {}
        return {m.get("id"): m for m in (res.json().get("data") or []) if m.get("id")}
    except Exception:
        return {}


def _cometapi_video_prices(model: Dict[str, Any]) -> Tuple[float, float]:
    pricing = model.get("pricing") or {}
    if not isinstance(pricing, dict):
        return 0.0, 0.0
    return _safe_float(pricing.get("per_second")), _safe_float(pricing.get("per_request"))


def _openrouter_avail(url: str) -> set:
    key = _openrouter_key()
    if not key:
        return set()
    try:
        with httpx.Client(timeout=20) as c:
            data = c.get(url, headers={"Authorization": f"Bearer {key}"}).json()
        return {m.get("id") for m in (data.get("data") or [])}
    except Exception:
        return set()


def openrouter_image_models() -> List[Dict[str, Any]]:
    """Top-10 modelos de imagem curados (ranking), só os disponíveis no OpenRouter."""
    avail = _openrouter_avail("https://openrouter.ai/api/v1/images/models")
    # reve-2.0 é API própria (não OpenRouter) → só entra se o token Reve estiver configurado.
    has_reve = bool(_reve_key())
    out = [{"id": s, "name": n, "quality": q, "price_per_image": p, "rank": i}
           for i, (s, n, q, p) in enumerate(CURATED_IMAGE)
           if (s.startswith("reve") and has_reve) or (not s.startswith("reve") and (not avail or s in avail))]
    return out or [{"id": s, "name": n, "quality": q, "price_per_image": p, "rank": i}
                   for i, (s, n, q, p) in enumerate(CURATED_IMAGE) if not s.startswith("reve")]


def openrouter_video_models() -> List[Dict[str, Any]]:
    """Top-10 modelos de vídeo curados (ranking), só os disponíveis no OpenRouter."""
    catalog = _openrouter_video_catalog()
    avail = set(catalog)
    out = []
    for i, (s, n, q, p, sec) in enumerate(CURATED_VIDEO):
        if avail and s not in avail:
            continue
        per_second = _openrouter_video_per_second((catalog.get(s) or {}).get("pricing_skus") or {})
        price = round(per_second * sec, 4) if per_second > 0 else p
        out.append({"id": s, "name": n, "quality": q, "price_per_video": price, "price_per_second": per_second,
                    "max_seconds": sec, "rank": i, "price_source": "catalog_api" if per_second > 0 else "fallback"})
    return out or [{"id": s, "name": n, "quality": q, "price_per_video": p, "max_seconds": sec, "rank": i}
                   for i, (s, n, q, p, sec) in enumerate(CURATED_VIDEO)]


def cometapi_video_models() -> List[Dict[str, Any]]:
    """Modelos de VÍDEO da CometAPI (curados). id prefixado 'cometapi:'. Preço aprox. de mercado por clipe."""
    if not _cometapi_key():
        return []
    catalog = _cometapi_model_catalog()
    out = []
    for i, (s, n, q, p, sec) in enumerate(CURATED_VIDEO_COMET):
        per_second, per_request = _cometapi_video_prices(catalog.get(s) or {})
        price = round(per_second * sec, 4) if per_second > 0 else (round(per_request, 4) if per_request > 0 else p)
        out.append({"id": "cometapi:" + s, "name": n, "quality": q, "price_per_video": price,
                    "price_per_second": per_second, "price_per_request": per_request,
                    "max_seconds": sec, "rank": i, "price_source": "catalog_api" if (per_second > 0 or per_request > 0) else "fallback"})
    return out


def omniroute_image_models() -> List[Dict[str, Any]]:
    """Modelos de IMAGEM do OmniRoute (gateway das assinaturas). Grátis pela assinatura.
    id prefixado 'omni:' p/ roteamento. Vazio se a key não estiver configurada."""
    key = _omniroute_key()
    if not key:
        return []
    out, seen = [], set()
    try:
        with httpx.Client(timeout=8) as c:
            data = c.get(_omniroute_base() + "/models", headers={"Authorization": "Bearer " + key}).json()
        for m in (data.get("data") or []):
            mid = m.get("id") or ""
            prov = mid.split("/")[0].lower()
            name = mid.split("/")[-1].lower()
            # PULA provedores '-web' (cgpt-web/chatgpt-web/gweb/gemini-web): geram por NAVEGADOR headless
            # → travam ~180s e derrubam o gateway (OOM). Só modelos de API real (ex.: antigravity) servem.
            if "web" in prov:
                continue
            # DEDUP por nome do modelo (o gateway repete o mesmo modelo sob vários apelidos).
            if mid and name not in seen and any(x in mid.lower() for x in ("image", "imagen", "flux", "dall", "banana", "seedream")):
                seen.add(name)
                out.append({"id": "omni:" + mid, "name": mid.split("/")[-1] + " (grátis · assinatura)",
                            "provider": "omniroute", "quality": "Top", "price_per_image": 0.0, "rank": -1, "free": True})
    except Exception:
        pass
    return out


# ── CometAPI (api.cometapi.com) — gateway unificado OpenAI-compat. Curadoria: famílias × níveis (top/médio/barato).
def _cometapi_key() -> str:
    return (get_credential("ai", "cometapi") or get_credential("image", "cometapi")
            or get_setting("token:cometapi") or os.environ.get("COMETAPI_API_KEY") or "").strip()


def web_research(query: str, max_tokens: int = 700) -> str:
    """BUSCA WEB AO VIVO p/ enriquecer o briefing (3ª fonte: internet). Perplexity Sonar via OpenRouter
    (busca nativa, com fontes); fallback CometAPI. Retorna digest factual em PT-BR — ou '' se indisponível.
    Silencioso em erro (nunca derruba a geração)."""
    if not (query or "").strip():
        return ""
    sysmsg = ("Você é pesquisador. Responda em PORTUGUÊS do Brasil, SÓ com fatos verificáveis e ATUAIS da web "
              "(recursos/funções reais, números, novidades, casos). Conciso, em tópicos curtos e específicos. "
              "NÃO invente: se não houver dado, diga que não encontrou. Sem rodeios, sem marketing vazio.")
    chain = []
    ok = _openrouter_key()
    if ok:
        chain.append(("https://openrouter.ai/api/v1", ok, "perplexity/sonar"))       # RÁPIDO (primário)
        chain.append(("https://openrouter.ai/api/v1", ok, "perplexity/sonar-pro"))   # mais rico (fallback)
    ck = _cometapi_key()
    if ck:
        chain.append((_COMETAPI_BASE, ck, "perplexity/sonar"))           # fallback Comet
    import time as _t
    _deadline = _t.time() + 16   # ORÇAMENTO TOTAL da busca (não soma timeouts dos fallbacks → nunca estoura o briefing)
    for base, key, model in chain:
        if _t.time() > _deadline:
            break
        try:
            # timeout CURTO: a busca NÃO pode estourar o tempo do briefing (gateway 502). Se demorar, pula → site+KB.
            with httpx.Client(timeout=httpx.Timeout(14.0, connect=6.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "max_tokens": max_tokens, "temperature": 0.2,
                                 "messages": [{"role": "system", "content": sysmsg},
                                              {"role": "user", "content": query[:1500]}]})
            if r.status_code >= 400:
                continue
            txt = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
            if txt and len(txt) > 40:
                return txt
        except Exception:
            continue
    return ""


def _web_brief_stale(prod: Dict[str, Any], max_age_days: int = 7) -> bool:
    """Cache web do produto está velho/faltando? (decide se dispara refresh em background)."""
    if not (prod.get("web_brief") or "").strip():
        return True
    at = (prod.get("web_brief_at") or "").strip()
    if not at:
        return True
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).days >= max_age_days
    except Exception:
        return True


def refresh_web_briefs(company_id: str, prods: List[Dict[str, Any]], theme: str = "") -> None:
    """BACKGROUND: busca web por app e GRAVA no cache (products.web_brief). NÃO bloqueia o briefing → sem 502."""
    from datetime import datetime, timezone
    try:
        from ..db_companies import product_update
    except Exception:
        return
    for p in (prods or []):
        try:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            q = ("Recursos, funções e novidades REAIS e ATUAIS de " + name
                 + " (app/SVA para provedores de internet). Liste fatos concretos, específicos e recentes, com números quando houver.")
            txt = web_research(q, 700)
            if txt:
                product_update(p.get("id"), {"web_brief": ("[" + name + "] " + txt)[:6000],
                                             "web_brief_at": datetime.now(timezone.utc).isoformat()})
        except Exception:
            continue


_COMETAPI_BASE = "https://api.cometapi.com/v1"
# (id real no catálogo CometAPI, nome, família, nível, preço USD aprox.)
# SÓ modelos que usam /v1/images/generations E geram de verdade (verificado: gpt-image-2/1.5 + seedream).
# Gemini/Flux/Midjourney usam OUTROS endpoints; gpt-4o-image (chat), gpt-image-1-mini e qwen-image-2 não
# geram por aqui → fora (eram a causa do erro "invalid character '<'").
_CURATED_COMETAPI = [
    ("gpt-image-1.5", "GPT Image 1.5", "OpenAI", "Top", 0.08),
    ("gpt-image-2", "GPT Image 2", "OpenAI", "Médio", 0.06),
    ("gpt-image-2-all", "GPT Image 2 All", "OpenAI", "Top", 0.06),
    ("doubao-seedream-5-0-260128", "Seedream 5.0", "Seedream", "Top", 0.028),
    ("doubao-seedream-4-5-251128", "Seedream 4.5", "Seedream", "Médio", 0.032),
    ("doubao-seedream-4-0-250828", "Seedream 4.0", "Seedream", "Barato", 0.032),
]
# Gemini (nano-banana) na CometAPI usa o endpoint generateContent (não /v1/images/generations) →
# prefixo 'cometapi-gemini:'. gemini-3-pro-image = nano-banana PRO (o melhor; testado, gera 200 OK).
_CURATED_COMETAPI_GEMINI = [
    ("gemini-3-pro-image", "Gemini 3 Pro Image (nano-banana pro)", "Gemini", "Top", 0.10),
    ("gemini-3.1-flash-image-preview", "Gemini 3.1 Flash Image (nano-banana)", "Gemini", "Rápido", 0.04),
]


def cometapi_image_models() -> List[Dict[str, Any]]:
    """Modelos curados da CometAPI. 'cometapi:'→/v1/images/generations; 'cometapi-gemini:'→generateContent."""
    if not _cometapi_key():
        return []
    def _row(prefix, cid, nm, fam, tier, p):
        return {"id": prefix + cid, "name": f"{nm} · {fam} ({tier})", "provider": "cometapi",
                "family": fam, "tier": tier, "quality": tier, "price_per_image": p, "rank": -2}
    return ([_row("cometapi:", *m) for m in _CURATED_COMETAPI]
            + [_row("cometapi-gemini:", *m) for m in _CURATED_COMETAPI_GEMINI])


def generate_image_cometapi_gemini(model: str, prompt: str):
    """Gera imagem via Gemini (nano-banana) na CometAPI — endpoint generateContent. Retorna (png, custo)."""
    import base64
    key = _cometapi_key()
    if not key:
        raise ValueError("CometAPI não configurada (chave ausente).")
    real = model.split(":", 1)[1] if ":" in model else model
    cost = 0.04 if "flash" in real.lower() else 0.10
    url = _COMETAPI_BASE.replace("/v1", "") + f"/v1beta/models/{real}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt[:4000]}]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        r = c.post(url, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", {}).get("message") or r.text[:300]
        except Exception:
            detail = r.text[:300]
        raise ValueError(f"Falha CometAPI Gemini (HTTP {r.status_code}): {detail}")
    parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    for p in parts:
        d = p.get("inlineData") or p.get("inline_data")
        if d and d.get("data"):
            return base64.b64decode(d["data"]), cost
    raise ValueError("CometAPI Gemini não retornou imagem (sem inlineData).")


def generate_image_with_person(person_bytes: bytes, prompt: str, model: str = "gemini-3.1-flash-image-preview"):
    """COMPÕE a PESSOA (foto recortada do influencer, com rebarba) DENTRO da cena da marca via nano-banana
    (Gemini image-to-image). Limpa a borda do recorte + harmoniza luz/cor, MANTENDO rosto e expressão.
    Retorna (png, custo). Em erro levanta (o chamador cai pra cena sem pessoa)."""
    import base64
    key = _cometapi_key()
    if not key or not person_bytes:
        raise ValueError("CometAPI/foto ausente.")
    real = model.split(":", 1)[1] if ":" in model else model
    cost = 0.04 if "flash" in real.lower() else 0.10
    url = _COMETAPI_BASE.replace("/v1", "") + f"/v1beta/models/{real}:generateContent"
    b64 = base64.b64encode(person_bytes).decode()
    body = {"contents": [{"parts": [
        {"text": prompt[:4000]},
        {"inlineData": {"mimeType": "image/png", "data": b64}},
    ]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        r = c.post(url, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    if r.status_code >= 400:
        raise ValueError(f"Falha nano-banana edit (HTTP {r.status_code}): {r.text[:200]}")
    parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    for p in parts:
        d = p.get("inlineData") or p.get("inline_data")
        if d and d.get("data"):
            return base64.b64decode(d["data"]), cost
    raise ValueError("nano-banana edit não retornou imagem.")


def verify_same_person(ref_bytes: bytes, gen_bytes: bytes):
    """Confere por VISÃO (gpt-4o) se a pessoa da imagem GERADA é a MESMA da foto de referência.
    Retorna (is_same: bool, custo). Em erro de API → (True, 0) — não regenera à toa quando a visão cai."""
    import base64, io
    from PIL import Image
    def _thumb(b):
        try:
            im = Image.open(io.BytesIO(b)).convert("RGB"); im.thumbnail((360, 360))
            o = io.BytesIO(); im.save(o, "JPEG", quality=82)
            return "data:image/jpeg;base64," + base64.b64encode(o.getvalue()).decode()
        except Exception:
            return "data:image/png;base64," + base64.b64encode(b).decode()
    txt = ("FOTO 1 = a pessoa REAL. IMAGEM 2 foi gerada a partir dela. A pessoa da IMAGEM 2 é a MESMA pessoa da FOTO 1 "
           "(mesmo rosto, mesma identidade — considere formato do rosto, barba, traços, etnia, cabelo)? "
           "Se for OUTRA pessoa / rosto claramente diferente, responda NAO. Responda SÓ: SIM ou NAO.")
    parts = [{"type": "text", "text": txt},
             {"type": "image_url", "image_url": {"url": _thumb(ref_bytes)}},
             {"type": "image_url", "image_url": {"url": _thumb(gen_bytes)}}]
    chain = []
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    if _openrouter_key():
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "max_tokens": 4, "temperature": 0, "messages": [{"role": "user", "content": parts}]})
            if r.status_code >= 400:
                continue
            t = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip().upper()
            return (("NAO" not in t and "NÃO" not in t), 0.004)
        except Exception:
            continue
    return (True, 0.0)


def pick_influencer_photo(photos, headline: str = "", slide_type: str = "cover", exclude=None) -> int:
    """Escolhe, do PORTFÓLIO do influencer, a foto cuja EXPRESSÃO/EMOÇÃO combina com o tom da tela (visão).
    photos = lista de bytes. Retorna o ÍNDICE. Usa gpt-4o visão (CometAPI→OpenRouter). `exclude` = índices já usados
    (variação: capa e CTA pegam fotos diferentes). Em erro → 1ª não-excluída."""
    import base64, re
    n = len(photos or [])
    ex = set(exclude or [])
    if n == 0:
        return 0
    if n == 1:
        return 0
    txt = (f"Escolha a MELHOR foto deste influencer para uma tela de carrossel do tipo '{slide_type}'. "
           f"Texto da tela: \"{(headline or '')[:160]}\". São {n} fotos numeradas de 1 a {n} na ordem enviada. "
           f"Escolha a foto cuja EXPRESSÃO/EMOÇÃO mais combina com o tom desse texto "
           f"(pergunta/problema/dor → séria, preocupada, questionadora; convite/CTA/positivo → confiante, sorridente, apontando). "
           f"Responda SÓ o NÚMERO da foto.")
    import io
    from PIL import Image
    def _thumb(b):
        try:
            im = Image.open(io.BytesIO(b)).convert("RGB"); im.thumbnail((320, 320))
            o = io.BytesIO(); im.save(o, "JPEG", quality=80)
            return "data:image/jpeg;base64," + base64.b64encode(o.getvalue()).decode()
        except Exception:
            return "data:image/png;base64," + base64.b64encode(b).decode()
    parts = [{"type": "text", "text": txt}]
    for b in photos:
        parts.append({"type": "image_url", "image_url": {"url": _thumb(b)}})
    chain = []
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    if _openrouter_key():
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "max_tokens": 4, "temperature": 0, "messages": [{"role": "user", "content": parts}]})
            if r.status_code >= 400:
                continue
            t = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "")
            m = re.search(r"\d+", t)
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < n and idx not in ex:
                    return idx
        except Exception:
            continue
    for i in range(n):   # fallback: 1ª não-excluída (variação mesmo sem visão)
        if i not in ex:
            return i
    return 0


# ── OpenAI imagem (API direta do cliente) ────────────────────────────────────
_OPENAI_IMG_COST = {"gpt-image-1": 0.06, "gpt-image-2": 0.04, "chatgpt-image-latest-high-fidelity": 0.08,
                    "gemini-3-pro-image-preview-2k": 0.06, "gemini-3.1-flash-image-preview": 0.04,
                    "dall-e-3": 0.04, "dall-e-2": 0.018}
_CURATED_OPENAI = [
    ("openai:gpt-image-1", "gpt-image-1 (OpenAI · sua conta)", "Top", 0.06),
    ("openai:dall-e-3", "DALL·E 3 (OpenAI · sua conta)", "Alta", 0.04),
]


def _openai_key() -> str:
    return (get_credential("ai", "openai") or get_credential("image", "openai")
            or get_setting("token:openai") or os.environ.get("OPENAI_API_KEY") or "").strip()


def generate_image_openai_direct(model: str, prompt: str, size: str = "1024x1536", ref_urls=None,
                                 base: str = "https://api.openai.com/v1", key: str = None, quality: str = None):
    """Gera imagem por API OpenAI-compatível (OpenAI direta OU PiAPI LLM API). ref_urls = logos oficiais.
    gpt-image-1 com referência usa /images/edits (sobe o arquivo da logo). Retorna (png_bytes, custo_usd)."""
    import base64
    key = key or _openai_key()
    if not key:
        raise ValueError("Provedor de imagem GPT não configurado (chave ausente).")
    real = model.split(":", 1)[1] if ":" in model else model
    sz = "1024x1792" if real == "dall-e-3" else ("1024x1024" if real.startswith("dall-e-2") else "1024x1536")
    refs = [u for u in (ref_urls or []) if u]
    H = {"Authorization": "Bearer " + key}
    if refs and real == "gpt-image-1":  # referência → edits (a IA usa a logo oficial, igual ChatGPT)
        files = []
        with httpx.Client(timeout=60) as c:
            for j, u in enumerate(refs[:4]):
                try:
                    files.append(("image[]", (f"ref{j}.png", c.get(u).content, "image/png")))
                except Exception:
                    pass
        if files:
            edata = {"model": real, "prompt": prompt[:4000], "size": sz}
            if quality:
                edata["quality"] = quality
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
                r = c.post(f"{base}/images/edits", headers=H, data=edata, files=files)
            if r.status_code >= 400:
                raise ValueError(f"Falha GPT imagem (edits HTTP {r.status_code}): {r.text[:200]}")
            item = (r.json().get("data") or [{}])[0]
            b64 = item.get("b64_json")
            if b64:
                return base64.b64decode(b64), _OPENAI_IMG_COST.get(real, 0.06)
    body = {"model": real, "prompt": prompt[:4000], "n": 1}
    if sz and not any(x in real.lower() for x in ("seedream", "doubao")):  # Seedream/Doubao rejeitam 'size'
        body["size"] = sz
    if quality:
        body["quality"] = quality
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        r = c.post(f"{base}/images/generations", headers=H, json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", {}).get("message") or r.text[:300]
        except Exception:
            detail = r.text[:300]
        raise ValueError(f"Falha OpenAI imagem (HTTP {r.status_code}): {detail}")
    item = (r.json().get("data") or [{}])[0]
    cost = _OPENAI_IMG_COST.get(real, 0.06)
    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64), cost
    url = item.get("url") or item.get("image_url")
    if url:
        with httpx.Client(timeout=60) as c:
            return c.get(url).content, cost
    raise ValueError("OpenAI não retornou imagem.")


def openai_image_models() -> List[Dict[str, Any]]:
    """Modelos de imagem OpenAI (API direta). Vazio se a chave não estiver configurada."""
    if not _openai_key():
        return []
    return [{"id": s, "name": n, "quality": q, "price_per_image": p, "rank": -2}
            for (s, n, q, p) in _CURATED_OPENAI]


def usd_to_brl(usd: Optional[float]) -> float:
    """Converte USD→BRL pela cotação em get_setting('fx.usd_brl') (default 5.40)."""
    try:
        rate = float(get_setting("fx.usd_brl") or 5.40)
    except Exception:
        rate = 5.40
    return round((usd or 0.0) * rate, 2)


# ── PiAPI (piapi.ai) — API unificada (Flux, Nano Banana, Seedream, Qwen…). Assíncrona: cria task → poll ──
_PIAPI_BASE = "https://api.piapi.ai/api/v1"
# id_suffix: (model, task_type, kind)
# SÓ estes 4 (todos via PiAPI LLM API, OpenAI-compat). suffix -> (model_real, quality|None, "openai")
_PIAPI_MODELS = {
    "gpt-image-2": ("gpt-image-2", "medium", "openai"),                  # LLM API (/v1/images, sync)
    "chatgpt-hifi": ("chatgpt-image-latest-high-fidelity", None, "openai"),  # LLM API
    "gemini-3-pro-2k": ("gemini", "nano-banana-pro", "gemini"),          # TASK API (async, 2K)
    "nano-banana-2": ("gemini", "nano-banana-2", "gemini"),             # TASK API (async)
}
_CURATED_PIAPI = [
    ("piapi:gpt-image-2", "gpt-image-2 (medium)", "Top", 0.04),
    ("piapi:chatgpt-hifi", "ChatGPT Image — high fidelity", "Top", 0.08),
    ("piapi:gemini-3-pro-2k", "Gemini 3 Pro Image (2K)", "Top", 0.06),
    ("piapi:nano-banana-2", "Gemini 3.1 Flash Image (nano-banana-2)", "Top", 0.04),
]
_PIAPI_IMG_COST = {"gpt-image-2": 0.04, "chatgpt-hifi": 0.08, "gemini-3-pro-2k": 0.06, "nano-banana-2": 0.04}


def _piapi_key() -> str:
    return (get_credential("ai", "piapi") or get_credential("image", "piapi")
            or get_setting("token:piapi") or os.environ.get("PIAPI_API_KEY") or "").strip()


def generate_image_piapi(model_id: str, prompt: str, size: str = "1024x1536", ref_urls=None):
    """Gera imagem via PiAPI (task assíncrona). ref_urls = imagens de REFERÊNCIA (logos oficiais)
    que a IA deve usar sem inventar. Retorna (png_bytes, custo_usd)."""
    import time
    key = _piapi_key()
    if not key:
        raise ValueError("PiAPI não configurada (adicione a chave em Configurações).")
    suffix = model_id.split(":", 1)[1] if ":" in model_id else model_id
    m, arg2, kind = _PIAPI_MODELS.get(suffix, ("gpt-image-2", "medium", "openai"))
    if kind == "openai":  # modelos OpenAI-compat via PiAPI LLM API (/v1/images). Saldo PiAPI, respeita logo (edits).
        return generate_image_openai_direct(m, prompt, size, ref_urls, base="https://api.piapi.ai/v1", key=key, quality=arg2)
    task_type = arg2
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except Exception:
        w, h = 1024, 1280
    ar = "4:5" if h > w else ("16:9" if w > h else "1:1")
    if kind == "flux":
        inp = {"prompt": prompt[:3000], "width": w, "height": h}
    elif kind == "seedream":
        inp = {"prompt": prompt[:3000], "aspect_ratio": ar, "output_format": "png", "size": "2K"}
    else:  # gemini / nano-banana
        inp = {"prompt": prompt[:3000], "output_format": "png", "aspect_ratio": ar, "resolution": "2K"}
    refs = [u for u in (ref_urls or []) if u]
    if refs:  # logos oficiais como referência (a IA usa, não inventa)
        if kind == "gemini":
            inp["images"] = refs
        else:
            inp["image"] = refs[0]
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    payload = {"model": m, "task_type": task_type, "input": inp, "config": {"service_mode": "public"}}
    # create com retry — PiAPI pode dar 400/429 transitório quando disparamos várias telas em rajada
    task_id, last_err = None, ""
    for attempt in range(3):
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
            r = c.post(f"{_PIAPI_BASE}/task", headers=headers, json=payload)
        try:
            d = (r.json() or {}).get("data") or {}
        except Exception:
            d = {}
        if r.status_code < 400 and (d.get("status") or "").lower() != "failed" and d.get("task_id"):
            task_id = d.get("task_id")
            break
        last_err = (((d.get("error") or {}).get("message")) or f"HTTP {r.status_code}: {r.text[:160]}")
        time.sleep(2 + attempt * 2)
    if not task_id:
        raise ValueError(f"Falha PiAPI ao criar tarefa (3x): {last_err}")
    url = None
    for _ in range(150):  # ~300s (nano-banana 2K demora)
        time.sleep(2)
        with httpx.Client(timeout=30) as c:
            gd = ((c.get(f"{_PIAPI_BASE}/task/{task_id}", headers=headers).json() or {}).get("data") or {})
        st = (gd.get("status") or "").lower()
        if st == "completed":
            out = gd.get("output") or {}
            url = (out.get("image_url") or (out.get("image_urls") or [None])[0]
                   or (out.get("temporary_image_urls") or [None])[0])
            break
        if st == "failed":
            raise ValueError("PiAPI falhou: " + (((gd.get("error") or {}).get("message")) or "tarefa falhou"))
    if not url:
        raise ValueError("PiAPI: imagem não disponível (timeout ou sem URL).")
    with httpx.Client(timeout=60) as c:
        img = c.get(url).content
    return img, _PIAPI_IMG_COST.get(suffix, 0.02)


def piapi_image_models() -> List[Dict[str, Any]]:
    """Modelos de imagem do PiAPI. Vazio se a chave não estiver configurada."""
    if not _piapi_key():
        return []
    return [{"id": s, "name": n, "quality": q, "price_per_image": p, "rank": -3}
            for (s, n, q, p) in _CURATED_PIAPI]


def generate_image_openrouter(model: str, prompt: str, size: str = "1024x1024", ref_images: Optional[List[bytes]] = None):
    """Generate via OpenRouter Image API. Returns (png_bytes, cost_usd)."""
    import base64
    key = _openrouter_key()
    if not key:
        raise ValueError("OpenRouter não configurado (token:openrouter).")
    body: Dict[str, Any] = {"model": model, "prompt": prompt[:4000], "n": 1}
    if size and "x" in size:
        try:
            from math import gcd
            w, h = [int(v) for v in size.split("x")[:2]]
            g = gcd(w, h) or 1
            body["aspect_ratio"] = f"{w // g}:{h // g}"          # ex.: 1080x1350 -> "4:5"
            body["resolution"] = "2K" if max(w, h) >= 1200 else "1K"
            # NÃO enviar size em pixel: vários modelos (riverflow) rejeitam size+aspect_ratio juntos.
        except Exception:
            pass
    if ref_images:
        body["input_references"] = [
            "data:image/png;base64," + base64.b64encode(b).decode() for b in ref_images[:3] if b
        ]
    last_err = ""
    for attempt in range(3):                       # retry: modelos 'pro' (riverflow) falham intermitente
        try:
            with httpx.Client(timeout=httpx.Timeout(240.0, connect=15.0)) as client:
                res = client.post("https://openrouter.ai/api/v1/images",
                                  headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                                  json=body)
            if res.status_code >= 400:
                try:
                    detail = res.json().get("error", {}).get("message") or res.text[:300]
                except Exception:
                    detail = res.text[:300]
                last_err = f"HTTP {res.status_code}: {detail}"
                if res.status_code < 500 and res.status_code != 429:
                    raise ValueError(f"Falha OpenRouter imagem ({last_err})")   # 4xx não repete
                continue
            d = res.json()
            item = (d.get("data") or [{}])[0]
            cost = (d.get("usage") or {}).get("cost")
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"]), cost
            url = item.get("image_url") or item.get("url")
            if url:
                with httpx.Client(timeout=60) as client:
                    return client.get(url).content, cost
            last_err = "resposta sem imagem"
        except httpx.HTTPError as e:
            last_err = f"rede/timeout: {str(e)[:120]}"
    raise ValueError(f"Falha OpenRouter imagem após 3 tentativas ({last_err}).")


def _reve_key() -> str:
    return (get_credential("ai", "reve") or get_setting("token:reve")
            or os.environ.get("REVE_API_KEY") or "").strip()


def generate_image_reve(prompt: str, size: str = "1080x1350"):
    """Gera via API própria da Reve (api.reve.com). Retorna (png_bytes, cost_usd|None).
    Reve não aceita 4:5 → usa 3:4. Custo vem em créditos (não USD)."""
    import base64
    key = _reve_key()
    if not key:
        raise ValueError("Reve não configurado (token:reve).")
    ar = "3:4"
    if size and "x" in size:
        try:
            w, h = [int(v) for v in size.split("x")[:2]]
            ar = "1:1" if w == h else ("3:4" if h > w else "4:3")
        except Exception:
            pass
    body = {"prompt": prompt[:4000], "aspect_ratio": ar}
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        r = c.post("https://api.reve.com/v1/image/create",
                   headers={"Authorization": "Bearer " + key, "content-type": "application/json"},
                   json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("message") or r.text[:300]
        except Exception:
            detail = r.text[:300]
        raise ValueError(f"Falha Reve (HTTP {r.status_code}): {detail}")
    d = r.json()
    b64 = d.get("image") or d.get("b64_json")
    if not b64 and isinstance(d.get("images"), list) and d["images"]:
        it = d["images"][0]
        b64 = it if isinstance(it, str) else (it.get("image") or it.get("b64_json"))
    if b64:
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64), None
    url = d.get("url") or d.get("image_url")
    if url:
        with httpx.Client(timeout=60) as c:
            return c.get(url).content, None
    raise ValueError("Reve não retornou imagem (keys: " + ",".join(d.keys()) + ").")


def vision_clear_side(img_bytes: bytes):
    """JUIZ POR VISÃO: pergunta a um modelo de visão qual METADE vertical da foto está TOTALMENTE livre de
    pessoa/rosto/corpo (mesmo desfocado) — onde o texto pode entrar sem cobrir ninguém.
    Retorna ('left'|'right'|'none', custo_usd). Em erro → ('', 0.0) → o compositor cai pra heurística."""
    import base64
    if not img_bytes:
        return "", 0.0
    b64 = base64.b64encode(img_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": ("Nesta imagem vertical, qual METADE (esquerda OU direita) é FUNDO/ESPAÇO VAZIO — "
            "SEM nenhuma pessoa, rosto, cabeça, mão ou corpo (mesmo desfocado/ao fundo) E SEM o objeto/elemento "
            "PRINCIPAL em foco (celular, tela, produto, dispositivo, mãos segurando algo)? Se as duas metades têm "
            "gente ou objeto importante, responda NONE. Responda SÓ uma palavra: LEFT, RIGHT ou NONE.")},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    # TRANSBORDO do juiz: CometAPI → OpenRouter (mesmo gpt-4o). Um sem saldo → usa o outro.
    chain = []
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    if _openrouter_key():
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "max_tokens": 4, "temperature": 0, "messages": msgs})
            if r.status_code >= 400:
                continue   # provedor sem saldo/erro → tenta o próximo da cadeia
            txt = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip().lower()
            side = "left" if "left" in txt else ("right" if "right" in txt else ("none" if "none" in txt else ""))
            if side:
                return side, 0.004
        except Exception:
            continue
    return "", 0.0


# ── TRANSBORDO INTELIGENTE de imagem (anti-"editorial em tudo") ───────────────
def image_models_registry() -> List[Dict[str, Any]]:
    """Universo de modelos de imagem disponíveis (id, provider, tier, price) — fonte p/ achar equivalentes."""
    out: List[Dict[str, Any]] = []
    for lst, p in ((omniroute_image_models(), "omniroute"), (cometapi_image_models(), "cometapi"),
                   (piapi_image_models(), "piapi"), (openrouter_image_models(), "openrouter")):
        for m in (lst or []):
            m.setdefault("provider", p)
            out.append(m)
    return out


def _model_provider(model_id: str) -> str:
    """Provedor de um id de modelo. cometapi: e cometapi-gemini: contam como 'cometapi' (MESMA conta/saldo)."""
    ml = (model_id or "").lower()
    if ml.startswith("omni:"):
        return "omniroute"
    if ml.startswith("cometapi:") or ml.startswith("cometapi-gemini:"):
        return "cometapi"
    if ml.startswith("piapi:"):
        return "piapi"
    if ml.startswith("openai:"):
        return "openai_direct"
    return "openrouter"


def _err_provider_dead(es: str) -> bool:
    """True se o erro indica PROVEDOR morto p/ a rodada (saldo/cota/auth) — não adianta repetir nele.
    Reconhece mensagens em PT/EN/CN (ex.: CometAPI '用户额度不足 / 剩余额度: $-0.00')."""
    s = (es or "").lower()
    return any(x in s for x in (
        "额度", "余额", "用户额度", "剩余额度",                       # CN: cota/saldo
        "insufficient", "balance", "quota", "credit", "billing", "out of credits",
        "exhaust", "usage_limit", "limit reached", "no funds",
        "http 401", "http 402", "http 403", "(401", "(402", "(403", " 401", " 402", " 403",
    ))


def _image_fallback_chain(model_id: str, reg: List[Dict[str, Any]]) -> List[str]:
    """Cadeia de modelos a tentar: o pedido → +1 do MESMO provedor → o MELHOR de cada OUTRO provedor
    (OmniRoute grátis primeiro). Provedor morto é pulado em runtime. Garante imagem real antes do editorial."""
    by_prov: Dict[str, List[str]] = {}
    for m in reg:
        pid = m.get("provider") or _model_provider(m.get("id", ""))
        by_prov.setdefault(pid, []).append(m.get("id"))
    preq = _model_provider(model_id)
    chain = [model_id]
    for mid in by_prov.get(preq, []):           # +1 do mesmo provedor (caso o modelo esteja quebrado, não o provedor)
        if mid and mid != model_id:
            chain.append(mid)
            break
    for p in ("omniroute", "piapi", "openrouter", "cometapi"):   # melhor de cada OUTRO provedor; grátis 1º
        if p == preq:
            continue
        for mid in by_prov.get(p, []):
            if mid:
                chain.append(mid)
                break
    seen, out = set(), []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def generate_image_resilient(prompt: str, size: str = "1024x1024", ref_images: Optional[List[bytes]] = None,
                             model_override: Optional[str] = None, ref_urls: Optional[List[str]] = None,
                             dead_providers=None, registry=None):
    """Gera imagem com TRANSBORDO: tenta o modelo pedido (1 retry p/ erro transitório); se o PROVEDOR
    morreu (saldo/cota/auth), marca-o como morto e PULA pra um modelo EQUIVALENTE de OUTRO provedor
    (OmniRoute grátis primeiro). `dead_providers` (set) é compartilhado entre as telas → provedor morto
    numa tela não é tentado de novo na próxima (não desperdiça tempo nem dinheiro). Retorna
    (bytes, cost, model_usado). Levanta só se a cadeia INTEIRA falhar (aí o chamador cai pro editorial)."""
    import time
    dead = dead_providers if dead_providers is not None else set()
    if not model_override:                       # sem override → comportamento simples (config padrão)
        return generate_image_with_cost(prompt, size, ref_images, None, ref_urls)
    try:
        reg = registry if registry is not None else image_models_registry()
    except Exception:
        reg = []
    chain = _image_fallback_chain(model_override, reg)
    errors: List[str] = []
    for cand in chain:
        prov = _model_provider(cand)
        if prov in dead:                         # provedor já caiu nesta rodada → nem tenta
            continue
        for attempt in range(2):                 # 1 retry no MESMO modelo p/ erro transitório
            try:
                img, cost, used = generate_image_with_cost(prompt, size, ref_images, cand, ref_urls)
                return img, cost, used
            except Exception as e:
                es = str(e)
                if _err_provider_dead(es):
                    dead.add(prov)
                    errors.append(f"{cand}: provedor sem saldo/cota")
                    break                        # pula o provedor inteiro (não adianta outro modelo dele)
                errors.append(f"{cand}: {es[:70]}")
                if attempt == 0:
                    time.sleep(2)                # transitório → 1 retry; senão segue p/ o próximo da cadeia
    raise ValueError("Transbordo esgotado (todos os modelos falharam): " + " | ".join(errors[:5]))


def generate_image_with_cost(prompt: str, size: str = "1024x1024", ref_images: Optional[List[bytes]] = None, model_override: Optional[str] = None, ref_urls: Optional[List[str]] = None):
    """Route image generation by configured provider (or an explicit model_override).
    Returns (bytes, cost_usd|None, model)."""
    config = get_image_config() or {}
    provider, model = config.get("provider", "openrouter"), config.get("model")
    if model_override:
        model = model_override
        ml = model_override.lower()
        if ml.startswith("omni:"):
            provider = "omniroute"
        elif ml.startswith("openai:"):
            provider = "openai_direct"
        elif ml.startswith("piapi:"):
            provider = "piapi"
        elif ml.startswith("cometapi-gemini:"):
            provider = "cometapi_gemini"
        elif ml.startswith("cometapi:"):
            provider = "cometapi"
        elif ml.startswith("reve"):
            provider = "reve"
        elif "/" in model_override:
            provider = "openrouter"
    if model and str(model).lower().startswith("omni:"):
        provider = "omniroute"
    if model and str(model).lower().startswith("openai:"):
        provider = "openai_direct"
    if model and str(model).lower().startswith("piapi:"):
        provider = "piapi"
    if model and str(model).lower().startswith("cometapi-gemini:"):
        provider = "cometapi_gemini"
    if model and str(model).lower().startswith("cometapi:"):
        provider = "cometapi"
    # Default to OpenRouter (OpenAI is being retired).
    if not model:
        model = "google/gemini-2.5-flash-image"
        provider = "openrouter"
    if provider == "omniroute":
        real = model.split(":", 1)[1] if str(model).lower().startswith("omni:") else model
        try:
            b, cost = generate_image_omniroute(real, prompt, size)
            return b, cost, model
        except Exception as oe:
            m = str(oe).lower()
            if any(x in m for x in ("429", "usage_limit", "limit reached", "quota", "exhaust", "rate limit")):
                # Cota grátis da assinatura acabou → fallback pago (mesma família, ~$0.04).
                fb = "google/gemini-2.5-flash-image"
                b, cost = generate_image_openrouter(fb, prompt, size, ref_images)
                return b, cost, fb + " (fallback pago)"
            raise
    if provider == "openai_direct":
        b, cost = generate_image_openai_direct(model, prompt, size, ref_urls)
        return b, cost, model
    if provider == "piapi":
        b, cost = generate_image_piapi(model, prompt, size, ref_urls)
        return b, cost, model
    if provider == "cometapi":
        real = model.split(":", 1)[1] if str(model).lower().startswith("cometapi:") else model
        b, cost = generate_image_openai_direct(real, prompt, size, ref_urls,
                                               base="https://api.cometapi.com/v1", key=_cometapi_key())
        return b, cost, model
    if provider == "cometapi_gemini":
        b, cost = generate_image_cometapi_gemini(model, prompt)
        return b, cost, model
    if provider == "reve":
        b, cost = generate_image_reve(prompt, size)
        return b, cost, model
    if provider == "openrouter":
        b, cost = generate_image_openrouter(model, prompt, size, ref_images)
        return b, cost, model
    if not config.get("apiKey"):
        raise ValueError("Geração de imagem não configurada.")
    if ref_images:
        return generate_image_edit(prompt, ref_images, size), None, model
    return _generate_image_openai(prompt, size, config), None, model


def generate_image_edit(prompt: str, ref_images: List[bytes], size: str = "1024x1024") -> bytes:
    """gpt-image-1 image edit: generate guided by reference images (brand logo + refs)
    so the output carries the real brand identity instead of a generic AI look."""
    import base64
    config = get_image_config()
    if not config:
        raise ValueError("Geração de imagem não configurada — adicione a chave OpenAI em Configurações.")
    if config["provider"] != "openai":
        raise ValueError("Geração com referências só suportada no OpenAI por enquanto.")
    files = []
    for i, b in enumerate([r for r in ref_images if r][:4]):
        files.append(("image[]", (f"ref{i}.png", b, "image/png")))
    if not files:
        return generate_image_bytes(prompt, size)
    data = {"model": config["model"] or "gpt-image-1", "prompt": prompt[:4000], "size": size}
    if config.get("quality"):
        data["quality"] = config["quality"]
    with httpx.Client(timeout=httpx.Timeout(240.0, connect=15.0)) as client:
        res = client.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {config['apiKey']}"},
            data=data, files=files,
        )
    if res.status_code >= 400:
        try:
            detail = res.json().get("error", {}).get("message") or res.text[:300]
        except Exception:
            detail = res.text[:300]
        raise ValueError(f"Falha ao gerar imagem com referências (HTTP {res.status_code}): {detail}")
    item = (res.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    raise ValueError("API de imagem (edits) não retornou conteúdo.")


def generate_image_bytes(prompt: str, size: str = "1024x1024") -> bytes:
    """Generate an image and return raw bytes (routes by configured provider)."""
    return generate_image_with_cost(prompt, size)[0]


def _generate_image_openai(prompt: str, size: str, config: Dict[str, Any]) -> bytes:
    """Generate an image via OpenAI (gpt-image-1)."""
    import base64
    body = {"model": config["model"] or "gpt-image-1", "prompt": prompt[:4000], "size": size, "n": 1}
    if config.get("quality"):
        body["quality"] = config["quality"]
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        res = client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {config['apiKey']}", "content-type": "application/json"},
            json=body,
        )
    if res.status_code >= 400:
        try:
            detail = res.json().get("error", {}).get("message") or res.text[:300]
        except Exception:
            detail = res.text[:300]
        raise ValueError(f"Falha ao gerar imagem (HTTP {res.status_code}): {detail}")
    data = res.json()
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with httpx.Client(timeout=60) as client:
            return client.get(item["url"]).content
    raise ValueError("API de imagem não retornou conteúdo.")


def build_image_prompt(company: Dict[str, Any], theme: str, visual_prompt: str = "",
                       products: Optional[List[Dict[str, Any]]] = None, has_refs: bool = False,
                       title: str = "", target_product: str = "", variant: int = 0) -> str:
    """Prompt para a IA gerar uma PEÇA DE MARKETING branded (estilo Cariap) — não foto crua.
    Foca só no app-alvo e proíbe logos de outras marcas (a IA erra logos = 'viagem')."""
    name = company.get("name", "")
    scene = visual_prompt or theme or "tema do post"
    head = (title or "").strip()
    tgt = (target_product or "").strip()
    foco = f"Contexto do app: {tgt}. " if tgt else "Contexto: portfólio de SVAs da Cariap. "
    parts = [
        "Gere APENAS a IMAGEM DE FUNDO (cenário fotográfico) de um post publicitário — "
        "SEM nenhum texto e SEM nenhum logo. É uma FOTO/cena, não um cartaz pronto.",
        f"{foco}Cena: {scene}.",
        "Estilo de CAMPANHA PUBLICITÁRIA PREMIUM: cinematográfico, iluminação de campanha, profundidade, "
        "cores ricas, foco/desfoque intencional, aparência de anúncio profissional de marca — NÃO foto de banco de imagem.",
        f"Paleta que combina com a marca {name} (acentos em laranja #ED5E1F quando natural).",
        {
            0: "COMPOSIÇÃO: assunto principal (pessoa/dispositivo) à DIREITA; deixe a METADE ESQUERDA limpa e lisa.",
            1: "COMPOSIÇÃO: assunto principal à ESQUERDA; deixe a METADE DIREITA limpa e lisa.",
            2: "COMPOSIÇÃO: assunto principal no TOPO/centro, bem enquadrado; deixe a METADE INFERIOR limpa.",
            3: "COMPOSIÇÃO: cena cinematográfica com profundidade (o sistema escurece a parte de baixo); pode preencher o quadro.",
        }.get(int(variant) % 4, "COMPOSIÇÃO: assunto à direita, metade esquerda limpa.")
        + " A FAIXA INFERIOR sempre limpa (vai o rodapé). É onde o sistema aplica texto e logos depois.",
        "PROIBIDO desenhar: qualquer texto, letra, número, palavra, título, logotipo, marca, ícone de app, "
        "telefone, site, rodapé, banner ou interface com palavras legíveis. Apenas o cenário.",
        "Pessoas realistas e naturais (sem cara de IA, sem deformação). VARIE bastante o cenário a cada geração.",
        "EVITE: aparência genérica de IA, cara de banco de imagem/stock, pessoas artificiais demais, "
        "cenário corporativo clichê, excesso de elementos abstratos, interface com texto falso, "
        "marcas de terceiros, visual infantil, estética poluída.",
        ("Siga o ESTILO/clima/paleta das imagens de referência fornecidas." if has_refs else ""),
        "Vertical 1080x1350, altíssima qualidade, nítida, com cara de campanha real.",
    ]
    rules = ((company.get("brand_kit") or {}).get("client_rules") or "").strip()
    if rules:
        parts.append("REGRAS DESTE CLIENTE (correções que ele já pediu — NUNCA repita estes erros):\n" + rules)
    return " ".join(p for p in parts if p).strip()


def get_video_config() -> Optional[Dict[str, Any]]:
    """Config de geração de vídeo CIENTE DO PROVEDOR (openai/openrouter/cometapi): chave + base_url + modelo.
    Provedor vem de video.provider (setado no seletor) ou é derivado do id do modelo."""
    model = (get_setting("video.model") or "").strip()
    provider = (get_setting("video.provider") or "").strip()
    if not provider:
        provider = "cometapi" if model.startswith("cometapi:") else ("openrouter" if "/" in model else "openai")
    if provider == "openrouter":
        key, base = _openrouter_key(), "https://openrouter.ai/api/v1"
    elif provider == "cometapi":
        key, base = _cometapi_key(), _COMETAPI_BASE
    else:
        key, base = (get_credential("video", "openai") or get_credential("ai", "openai")), "https://api.openai.com/v1"
        model = model or "sora-2"
    if not key:
        return None
    if model.startswith("cometapi:"):
        model = model[len("cometapi:"):]            # id real na Comet (sem o prefixo do nosso catálogo)
    return {"provider": provider, "apiKey": key, "model": model, "base": base}


def video_model_max_seconds(model_id: str = "") -> int:
    """Máximo de segundos/clipe do modelo (do catálogo CURATED_VIDEO*). Default 8."""
    mid = (model_id or get_setting("video.model") or "").strip()
    raw = mid[len("cometapi:"):] if mid.startswith("cometapi:") else mid
    for s, n, q, p, sec in CURATED_VIDEO:
        if mid in (s, n):
            return sec
    for s, n, q, p, sec in CURATED_VIDEO_COMET:
        if mid == ("cometapi:" + s) or raw in (s, n):
            return sec
    return 8


def video_scene_count(target_seconds: int, max_seconds: int, cap: int = 8) -> int:
    """Quantas cenas cobrem a duração-alvo com clipes de até max_seconds (teto de cenas = controle de custo)."""
    import math
    t = max(1, int(target_seconds or 8))
    m = max(1, int(max_seconds or 8))
    return max(1, min(cap, math.ceil(t / m)))


def _video_catalog_entry(model_id: str):
    """Acha (preço, max_seconds, nome) do modelo no catálogo (OpenRouter+Comet). None se não achar."""
    mid = (model_id or "").strip()
    raw = mid[len("cometapi:"):] if mid.startswith("cometapi:") else mid
    for s, nm, q, p, sec in CURATED_VIDEO:
        if mid in (s, nm):
            return (p, sec, nm)
    for s, nm, q, p, sec in CURATED_VIDEO_COMET:
        if mid == ("cometapi:" + s) or raw in (s, nm):
            return (p, sec, nm)
    return None


def video_clip_price(model_id: str = "") -> float:
    """Preço por clipe (USD): usa o PREÇO REAL APRENDIDO (usage.cost da última geração desse modelo) se existir;
    senão a estimativa do catálogo. Faz a previsão CONVERGIR pro real após o 1º uso de cada modelo."""
    mid = (model_id or get_setting("video.model") or "").strip()
    learned = get_setting("video.price." + mid)
    if learned:
        try:
            v = float(learned)
            if v > 0:
                return v
        except Exception:
            pass
    ent = _video_catalog_entry(mid)
    return ent[0] if ent else 0.40


def video_price_per_second(model_id: str = "") -> float:
    """Preço real por segundo via catálogo do provedor, quando disponível. Cacheia em settings."""
    mid = (model_id or get_setting("video.model") or "").strip()
    if not mid:
        return 0.0
    cached = get_setting("video.persec." + mid)
    if cached:
        try:
            return float(cached)
        except Exception:
            pass
    try:
        if mid.startswith("cometapi:"):
            raw = mid[len("cometapi:"):]
            ps, _per_request = _cometapi_video_prices(_cometapi_model_catalog().get(raw) or {})
        elif "/" in mid:
            ps = _openrouter_video_per_second((_openrouter_video_catalog().get(mid) or {}).get("pricing_skus") or {})
        else:
            ps = 0.0
        if ps > 0:
            from datetime import datetime, timezone
            from ..db import settings_set
            settings_set(key="video.persec." + mid, value=str(ps), updated_at=datetime.now(timezone.utc).isoformat())
        return ps
    except Exception:
        return 0.0


def video_model_id_from_config(config: Optional[Dict[str, Any]]) -> str:
    """Reconstrói o id do catálogo a partir da config congelada do job."""
    if not config:
        return (get_setting("video.model") or "").strip()
    provider = (config.get("provider") or "").strip()
    model = (config.get("model") or "").strip()
    if provider == "cometapi" and model and not model.startswith("cometapi:"):
        return "cometapi:" + model
    return model or (get_setting("video.model") or "").strip()


def video_estimated_clip_cost(model_id: str = "", seconds: Any = None) -> float:
    """Custo estimado de uma cena quando o provedor nao retorna usage.cost."""
    mid = (model_id or get_setting("video.model") or "").strip()
    if not mid:
        return 0.0
    sec = _video_seconds_value(str(seconds or ""), video_model_max_seconds(mid))
    persec = video_price_per_second(mid)
    if persec > 0:
        return round(persec * sec, 4)
    return round(video_clip_price(mid), 4)


def video_cost_estimate(target_seconds: int, model_id: str = "") -> Dict[str, Any]:
    """PREFLIGHT: nº de cenas + custo p/ a duração no modelo. Usa preço APRENDIDO (real) se já houver; senão catálogo."""
    mid = model_id or get_setting("video.model") or ""
    ent = _video_catalog_entry(mid)
    price = video_clip_price(mid)
    mx = ent[1] if ent else 8
    name = ent[2] if ent else (mid or "modelo")
    n = video_scene_count(target_seconds, mx)
    total = round(price * n, 2)
    return {"model": name, "model_id": mid, "max_seconds": mx, "scenes": n,
            "price_per_clip_usd": price, "total_usd": total, "total_brl": round(usd_to_brl(total), 2),
            "price_learned": bool(get_setting("video.price." + (mid or "")))}


def _video_seconds_value(seconds: str, default: int = 8) -> int:
    try:
        val = int(float(seconds)) if seconds is not None and str(seconds).strip() else default
    except Exception:
        val = default
    return max(1, val)


def build_video_prompt(company: Dict[str, Any], theme: str, video_prompt: str = "") -> str:
    """Prompt SÓ-CENA pro modelo de vídeo — MESMA régua de qualidade da ARTE (campanha premium + grade na cor da
    marca + proibição dura de texto/logo). O código desenha marca/legenda/CTA depois."""
    scene = (video_prompt or theme or "cena publicitária premium").strip()
    cols = (company.get("brand_kit") or {}).get("colors") or {}
    if not cols:
        try:
            from ..db_companies import brand_kit_get
            cols = (brand_kit_get(company.get("id")) or {}).get("colors") or {}
        except Exception:
            cols = {}
    acc = (cols.get("accent") or cols.get("primary") or "").strip()
    grade = (f"GRADE DE COR cinematográfica puxando para a COR DA MARCA {acc} (acentos e luz nessa cor). " if acc
             else "Grade de cor cinematográfica de campanha premium. ")
    return (
        "VÍDEO vertical 9:16 EM MOVIMENTO, nível AGÊNCIA de propaganda — estética de CAMPANHA publicitária real, "
        "altíssima produção. NÃO foto de banco de imagem, NÃO cara de IA/cartoon/render barato. " + grade +
        "Iluminação dramática e direcional (rim light, contraluz, glow), profundidade real em camadas, textura rica "
        "(partículas, bokeh, atmosfera). Movimento de câmera suave e cinematográfico (push-in leve/parallax), ação natural contínua. "
        "Pessoas brasileiras reais e naturais quando a cena pedir (sem deformação, sem rosto distorcido) — ou só elementos/produto se ilustrar melhor. "
        f"CENA (interprete cinematograficamente, com a personalidade da marca): {scene}. "
        "PROIBIDO ABSOLUTO em QUALQUER frame e QUALQUER lugar do quadro: TEXTO, letra, palavra, número, legenda, título; "
        "LOGO, marca, logotipo, watermark; INTERFACE/TELA de app ou celular com ícones/nomes/texto legível; nota musical com texto. "
        "Telas de aparelhos só com brilho ABSTRATO. NADA escrito em lugar nenhum — o texto e a marca entram DEPOIS pelo sistema. "
        "ÁUDIO: APENAS som ambiente natural da cena e/ou trilha instrumental SUTIL — SEM fala, SEM narração, SEM vozes humanas, "
        "SEM canto/letras (nada de pessoa falando; voz inventada pelo modelo sai garbled e acelerada). "
        "Acabamento de revista: foco nítido, micro-contraste, grão fino, zero aspecto amador."
    )


def build_video_storyboard(company: Dict[str, Any], theme: str, video_prompt: str = "",
                           target_seconds: int = 0, n_scenes: int = 0, per_seconds: int = 8) -> List[Dict[str, str]]:
    """Roteiro em CENAS. Se n_scenes>0 (usuário TRAVOU a duração) gera EXATAMENTE n_scenes cenas distintas de
    per_seconds cada; senão a IA decide (modo LIVRE). Retorna [{prompt, seconds}]."""
    fallback = [{"prompt": build_video_prompt(company, theme, video_prompt), "seconds": str(per_seconds or 8)}]
    config = cheap_text_config(get_ai_config())
    if not config:
        return fallback
    if n_scenes and int(n_scenes) > 0:
        dur_rule = (f"Quebre em EXATAMENTE {int(n_scenes)} CENAS DISTINTAS e sequenciais (com continuidade entre elas), "
                    f"cada uma com {int(per_seconds)} segundos, totalizando ~{int(target_seconds or n_scenes*per_seconds)}s. "
                    f"NÃO repita cenas — cada uma avança a narrativa. ")
    else:
        dur_rule = ("DECIDA a duração ideal do reel (o que performa melhor — normalmente 15 a 60s) e quebre em cenas. ")
    bk = company.get("brand_kit") or {}
    if not bk:
        try:
            from ..db_companies import brand_kit_get
            bk = brand_kit_get(company.get("id")) or {}
        except Exception:
            bk = {}
    voice = (bk.get("voice") or bk.get("persona") or "").strip()
    tom_rule = (f"TOM/VOZ DA MARCA (mantenha CONSISTENTE em todo vídeo — define o clima, o ritmo e a energia das cenas): {voice}. " if voice else
                "TOM consistente, brasileiro, premium e confiante. ")
    system = (
        "Você é DIRETOR de reels/vídeo publicitário no nível das agências g4.business e v4company. A partir do briefing, "
        + dur_rule + tom_rule +
        "Monte um ROTEIRO CINEMATOGRÁFICO com ARCO: (1) GANCHO visual forte nos primeiros segundos (prende o olho), "
        "(2) DESENVOLVIMENTO mostrando o VALOR/benefício de forma concreta e emocional, (3) CLÍMAX/virada que deixa o gancho "
        "pro CTA. NÃO crie cena de CTA nem de logo — o sistema desenha CTA, logo, texto e marca DEPOIS. "
        "Cada cena é uma CENA VISUAL REAL e cinematográfica: ambiente brasileiro real, sujeito (PESSOA natural OU produto/elemento "
        "— o que MELHOR ilustrar), com NO MÁXIMO 1 AÇÃO principal e 1 MOVIMENTO de câmera por cena (clareza). EMOÇÃO clara. "
        "CONTINUIDADE entre as cenas (mesmo personagem/clima/paleta da marca). MOSTRE a sensação/benefício, NÃO a tela do app. "
        'Responda SOMENTE JSON válido e compacto: {"scenes":[{"desc":"cena visual concreta: sujeito + 1 ação + 1 movimento de câmera + luz/clima","seconds":8}, ...]} . '
        "PROIBIDO em 'desc': qualquer TEXTO, letra, legenda, número; LOGO, marca, nome de marca; TELA/interface de app/celular com "
        "conteúdo legível, ícones ou nomes. Só a CENA fotográfica em movimento, em PT-BR."
    )
    user = f"Empresa: {company.get('name','')} ({company.get('segment','')}). Briefing/tema: {theme}. Direção visual: {video_prompt}"
    allowed = [4, 8, 12]
    try:
        parsed = extract_json(complete_ai(config, system, user, 1500)) or {}
        out = []
        for s in (parsed.get("scenes") or [])[:8]:
            if not isinstance(s, dict):
                continue
            desc = (s.get("desc") or s.get("description") or "").strip()
            if not desc:
                continue
            try:
                sec = int(s.get("seconds") or 8)
            except Exception:
                sec = 8
            sec = min(allowed, key=lambda a: abs(a - sec))  # snap to 4/8/12
            out.append({"prompt": build_video_prompt(company, theme, desc), "seconds": str(sec)})
        if out:
            return out
    except Exception:
        pass
    return fallback


def create_video_job(prompt: str, seconds: str = "8", size: str = "720x1280",
                     first_frame_url: Optional[str] = None, model: Optional[str] = None,
                     aspect_ratio: str = "9:16") -> Dict[str, Any]:
    """Cria um job de vídeo (async) no PROVEDOR configurado. Retorna o job (id/status).
    first_frame_url → CONTINUIDADE: a imagem entra como PRIMEIRO FRAME (= último frame da cena anterior).
    aspect_ratio → 9:16 (reels/story) por padrão; verificado que sem isso o veo sai 16:9."""
    config = get_video_config()
    if not config:
        raise ValueError("Geração de vídeo não configurada — escolha o modelo de vídeo no painel.")
    prov = config["provider"]
    mdl = model or config["model"]
    if prov == "openrouter":
        # OpenRouter POST /api/v1/videos: duration inteiro + frame_images tipado.
        body: Dict[str, Any] = {"model": mdl, "prompt": prompt[:4000], "generate_audio": True}
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        body["duration"] = _video_seconds_value(seconds)
        body["resolution"] = "720p"
        if first_frame_url:
            # OpenRouter exige type=image_url; sem isso retorna ZodError em frame_images[0].type.
            body["frame_images"] = [{"type": "image_url", "image_url": {"url": first_frame_url}, "frame_type": "first_frame"}]
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            res = client.post(config["base"] + "/videos",
                              headers={"Authorization": f"Bearer {config['apiKey']}", "content-type": "application/json"},
                              json=body)
        if res.status_code >= 400:
            raise ValueError(f"Falha ao criar vídeo OpenRouter (HTTP {res.status_code}): {res.text[:300]}")
        return res.json()
    if prov == "openai":
        body = {"model": mdl or "sora-2", "prompt": prompt[:4000], "seconds": str(seconds), "size": size}
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            res = client.post("https://api.openai.com/v1/videos",
                              headers={"Authorization": f"Bearer {config['apiKey']}", "content-type": "application/json"},
                              json=body)
        if res.status_code >= 400:
            try:
                detail = res.json().get("error", {}).get("message") or res.text[:300]
            except Exception:
                detail = res.text[:300]
            raise ValueError(f"Falha ao criar vídeo (HTTP {res.status_code}): {detail}")
        return res.json()
    if prov == "cometapi":
        # CometAPI vídeo documentado: POST /v1/videos multipart/form-data, retorna task id;
        # polling em GET /v1/videos/{id}; download em /content ou video_url.
        fields = [
            ("model", (None, mdl)),
            ("prompt", (None, prompt[:4000])),
            ("seconds", (None, str(_video_seconds_value(seconds, 4)))),
            ("aspect_ratio", (None, aspect_ratio or "9:16")),
            ("resolution", (None, "720p")),
        ]
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            res = client.post(config["base"] + "/videos",
                              headers={"Authorization": f"Bearer {config['apiKey']}"},
                              files=fields)
        if res.status_code >= 400:
            raise ValueError(f"Falha ao criar vídeo CometAPI (HTTP {res.status_code}): {res.text[:300]}")
        return res.json()
    raise ValueError(f"Provedor de vídeo '{prov}' não suportado.")


def get_video_job(job_id: str, config_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config_override or get_video_config()
    base = config["base"] if config else "https://api.openai.com/v1"
    key = config["apiKey"] if config else ""
    with httpx.Client(timeout=60) as client:
        res = client.get(f"{base}/videos/{job_id}", headers={"Authorization": f"Bearer {key}"})
    if res.status_code >= 400:
        raise ValueError(f"Falha ao consultar vídeo (HTTP {res.status_code}): {res.text[:300]}")
    return res.json()


def _video_url_from_job(job: Dict[str, Any]) -> str:
    """Extrai a URL do vídeo pronto do job. OpenRouter usa unsigned_urls/signed_urls (lista); outros variam."""
    for k in ("unsigned_urls", "signed_urls"):     # OpenRouter (verificado no 1º teste)
        u = job.get(k)
        if isinstance(u, list) and u and isinstance(u[0], str) and u[0].startswith("http"):
            return u[0]
    for path in (("video", "url"), ("output", "url"), ("data", 0, "url"), ("assets", "video"), ("url",), ("video_url",)):
        cur = job
        try:
            for k in path:
                cur = cur[k]
            if isinstance(cur, str) and cur.startswith("http"):
                return cur
        except Exception:
            continue
    return ""


def _download_video_url(url: str, headers: Dict[str, str]) -> bytes:
    parsed_host = url.split("/", 3)[2] if "://" in url else ""
    needs_auth = parsed_host.endswith("openrouter.ai") or parsed_host.endswith("cometapi.com")
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
        res = client.get(url, headers=(headers if needs_auth else {}))
    if res.status_code >= 400:
        raise ValueError(f"Falha ao baixar vídeo (HTTP {res.status_code})")
    return res.content


def download_video(job_id: str, config_override: Optional[Dict[str, Any]] = None) -> bytes:
    config = config_override or get_video_config()
    if not config:
        raise ValueError("Geração de vídeo não configurada.")
    prov, base = config["provider"], config["base"]
    H = {"Authorization": f"Bearer {config['apiKey']}"}
    if prov == "openai":
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            res = client.get(f"{base}/videos/{job_id}/content", headers=H)
        if res.status_code >= 400:
            raise ValueError(f"Falha ao baixar vídeo (HTTP {res.status_code})")
        return res.content
    job = get_video_job(job_id, config)
    vurl = _video_url_from_job(job)
    if vurl:
        return _download_video_url(vurl, H)
    suffix = "/content?index=0" if prov == "openrouter" else "/content"
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
        res = client.get(f"{base}/videos/{job_id}{suffix}", headers=H)
    if res.status_code >= 400:
        raise ValueError(f"Falha ao baixar vídeo (HTTP {res.status_code})")
    return res.content


def _fetch_site_text(site_url: str) -> str:
    """Fetch a site → text for AI extraction. Prefers meta description/title (SPA-safe)
    and strips cookie-consent boilerplate. Returns '' on failure."""
    import re
    if not site_url:
        return ""
    url = site_url if site_url.startswith("http") else "https://" + site_url

    def meta(html: str, key: str, attr: str = "name") -> str:
        m = re.search(r'<meta[^>]+' + attr + r'=["\']' + re.escape(key) + r'["\'][^>]*\bcontent=["\']([^"\']*)', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*' + attr + r'=["\']' + re.escape(key) + r'["\']', html, re.I)
        return (m.group(1).strip() if m else "")

    try:
        with httpx.Client(timeout=25.0, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"}) as c:
            html = c.get(url).text
        tm = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
        metas = [(tm.group(1).strip() if tm else ""), meta(html, "description"), meta(html, "keywords"),
                 meta(html, "og:title", "property"), meta(html, "og:description", "property"),
                 meta(html, "og:site_name", "property")]
        summary = " | ".join(dict.fromkeys([m for m in metas if m and len(m) > 2]))
        body = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', html)
        body = re.sub(r'(?s)<[^>]+>', ' ', body)
        body = re.sub(r'\s+', ' ', body).strip()
        junk = re.compile(r'(cookie consent|consent management|termsfeed|política de cookies|cookie policy|aceitar cookies|gerenciar cookies)', re.I)
        if junk.search(body) and len(body) < 400:
            body = ""
        else:
            body = junk.sub(' ', body)
        return (summary + " || " + body).strip()[:6500]
    except Exception:
        return ""


def enrich_company_from_web(name: str, site_url: str = "", instagram: str = "", segment: str = "") -> Dict[str, Any]:
    """Read the company's site/Instagram and define brand voice/persona/audience/visual base
    for the agency. NEVER returns prices."""
    import re as _re
    import json as _json
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")
    text = _fetch_site_text(site_url)
    system = (
        "Você é um estrategista de marca. A partir do site/Instagram de uma EMPRESA, defina a "
        "identidade verbal e o posicionamento para uma agência criar posts. Responda SOMENTE com "
        "JSON válido, sem markdown. IGNORE textos de cookies/LGPD/privacidade. NUNCA inclua preços."
    )
    user = (
        f"Empresa: {name}\nSegmento atual: {segment or '(não informado)'}\n"
        f"Instagram: {instagram or '(não informado)'}\n"
        f"Conteúdo do site:\n{text or '(site indisponível — infira pelo nome e Instagram)'}\n\n"
        "Extraia exatamente este JSON:\n"
        '{"description":"o que a empresa faz (1-2 frases)",'
        '"segment":"segmento curto (ex: agência de SVAs para provedores)",'
        '"audience":"PÚBLICO + MODELO DE NEGÓCIO: para quem vende e como (a IA segue isto à risca em todo conteúdo)",'
        '"voice":"tom de voz em poucas palavras (ex: próximo, confiante, sem jargão técnico)",'
        '"persona":"persona da marca: quem é, como fala, como se posiciona",'
        '"visual_prompt_base":"base visual para as imagens dos posts: estilo, paleta, elementos, clima",'
        '"colors":{"primary":"#RRGGBB","secondary":"#RRGGBB","accent":"#RRGGBB"}}\n'
        "Sem preços. Responda só o JSON."
    )
    raw = _call_openai_compat(config["provider"], config["apiKey"], config["model"], system, user, 1600)
    m = _re.search(r'\{.*\}', raw, _re.S)
    data = _json.loads(m.group(0)) if m else {}
    for k in ("price", "preco", "preço", "pricing", "valor", "plano", "planos"):
        data.pop(k, None)
    if not isinstance(data.get("colors"), dict):
        data["colors"] = {}
    data["site_text_used"] = bool(text)
    return data


def enrich_product_from_web(name: str, site_url: str = "", instagram: str = "") -> Dict[str, Any]:
    """Read the product's website and extract its profile (functions, objective, colors,
    à-la-carte items) via AI. NEVER returns prices. Returns a dict to fill the product."""
    import re as _re
    import json as _json
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")
    text = _fetch_site_text(site_url)
    system = (
        "Você analisa o site de um aplicativo/SVA e extrai o PERFIL do produto para uma agência "
        "que cria posts. Responda SOMENTE com JSON válido, sem markdown. "
        "IGNORE COMPLETAMENTE textos de banner de cookies, consentimento, LGPD, política de "
        "privacidade e 'TermsFeed' — eles NÃO descrevem o produto. Baseie-se na descrição, no "
        "título e no conteúdo real do app. "
        "REGRA ABSOLUTA: NUNCA inclua preços, valores, mensalidades, planos ou números de R$/$."
    )
    user = (
        f"Produto/app: {name}\n"
        f"Instagram: {instagram or '(não informado)'}\n"
        f"Conteúdo do site:\n{text or '(site indisponível — infira pelo nome e Instagram)'}\n\n"
        "Extraia exatamente este JSON:\n"
        '{"description":"1-2 frases: o que é e diferenciais",'
        '"objective":"como a agência deve posicionar/vender este app nos posts (público, ângulo)",'
        '"functions":["função/recurso 1","função 2","..."],'
        '"category":"categoria curta (ex: streaming de música, segurança/VPN, e-books)",'
        '"colors":{"primary":"#RRGGBB","secondary":"#RRGGBB","accent":"#RRGGBB"},'
        '"alacarte":["itens entregues juntos / add-ons dentro do app, se houver (ex: Telecine, Premiere)"]}\n'
        "Se não houver cores claras, use {}. SEM PREÇOS. Responda só o JSON."
    )
    raw = _call_openai_compat(config["provider"], config["apiKey"], config["model"], system, user, 1400)
    m = _re.search(r'\{.*\}', raw, _re.S)
    data = _json.loads(m.group(0)) if m else {}
    for k in ("price", "preco", "preço", "pricing", "valor", "plano", "planos"):
        data.pop(k, None)
    # normalize
    data["functions"] = [str(f).strip() for f in (data.get("functions") or []) if str(f).strip()][:12]
    data["alacarte"] = [str(a).strip() for a in (data.get("alacarte") or []) if str(a).strip()][:12]
    if not isinstance(data.get("colors"), dict):
        data["colors"] = {}
    data["site_text_used"] = bool(text)
    return data


def generate_post_copy(company: Dict[str, Any], briefing: str, networks: List[str]) -> Dict[str, Any]:
    """Generate post copy via AI."""
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")

    brand_kit = company.get("brand_kit") or {}
    system = (
        "Você é um social media sênior brasileiro. Responda SOMENTE com JSON válido: "
        '{"title":"...","headline":"...","subheadline":"...","benefits":["...","...","..."],'
        '"cta":"...","copy":"...","hashtags":["..."],"product":"...","media_type":"image|video",'
        '"visual_prompt":"...","video_prompt":"..."} '
        "Sem markdown, sem texto fora do JSON. "
        "ÂNGULO: a maioria dos posts fala COM o provedor de internet (B2B: rentabilizar, fidelizar, agregar valor); "
        "mas se o briefing pedir, pode ser pro provedor repostar ao ASSINANTE FINAL (benefício direto pro usuário). Adeque o tom. "
        "headline: o GANCHO da ARTE em 4-7 palavras, forte e direto (será desenhado GRANDE no post). "
        "subheadline: 1 frase curta de apoio (até ~12 palavras). "
        "benefits: EXATAMENTE 3 benefícios curtíssimos (2-4 palavras cada) que vão virar bullets na arte. "
        "cta: chamada curta (ex.: 'Fale conosco', 'Seja parceiro'). "
        "Copy pronta para publicar (legenda), em PT-BR, com gancho forte na primeira linha, "
        "quebras de linha e CTA no final. "
        "product: o NOME EXATO do app/produto principal do post, escolhido da lista de produtos "
        "fornecida (ex.: Looke, Deezer, ExitLag). Se nenhum produto específico, deixe vazio. "
        "media_type: escolha 'video' se o tema do briefing pede movimento/demonstração/storytelling, "
        "senão 'image'. "
        "visual_prompt: descreva uma CENA cinematográfica e PREMIUM, específica e DIFERENTE para este post "
        "(ambiente, objetos, ação, ângulo, profundidade, clima e luz de campanha), rica em detalhes e com ALMA, "
        "fiel ao tema — fuja de clichê de banco de imagem e de cara genérica de IA; sem texto/letras na imagem. "
        "video_prompt: se media_type for 'video', descreva a cena/ação/movimento do vídeo curto (5-8s) "
        "alinhado ao briefing; senão deixe vazio."
    )
    _audience = (brand_kit.get("audience") or "").strip()
    if _audience:
        system += " CONTEXTO DE NEGÓCIO (siga à risca, define público e posicionamento): " + _audience
    _rules = (brand_kit.get("client_rules") or "").strip()
    if _rules:
        system += " REGRAS DESTE CLIENTE (correções já pedidas por ele — NUNCA repita estes erros): " + _rules
    user_parts = [f"Empresa: {company.get('name', '')}"]
    if company.get("segment"):
        user_parts.append(f"Segmento: {company['segment']}")
    if brand_kit.get("voice"):
        user_parts.append(f"Tom de voz: {brand_kit['voice']}")
    if brand_kit.get("persona"):
        user_parts.append(f"Persona da marca: {brand_kit['persona']}")
    if networks:
        user_parts.append(f"Redes alvo: {', '.join(networks)}")
    try:
        from ..db_companies import product_list
        _prods = product_list(company.get("id") or "") or []
    except Exception:
        _prods = []
    if _prods:
        user_parts.append(
            "Produtos/apps que a empresa vende (fale de um produto real e seus benefícios, "
            "escolhendo o mais alinhado ao briefing; siga o 'objetivo' de cada um): "
            + "; ".join(f"{p.get('name')}: {(p.get('description') or '')[:120]}" + (f" [objetivo: {(p.get('objective') or '')[:150]}]" if p.get('objective') else "") for p in _prods[:25])
        )
    user_parts.append(f"Briefing do post: {briefing}")
    user = "\n".join(user_parts)

    result = complete_ai(config, system, user, 1024)
    parsed = extract_json(result)
    if not parsed:
        raise ValueError("IA não retornou JSON válido.")
    hashtags = parsed.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags = " ".join(hashtags)
    media_type = str(parsed.get("media_type") or "").lower()
    if media_type not in ("image", "video"):
        text = (briefing + " " + str(parsed.get("visual_prompt") or "") + " " + str(parsed.get("video_prompt") or "")).lower()
        video_kw = ("vídeo", "video", "reels", "reel", "bastidor", "movimento", "demonstra", "tutorial",
                    "passo a passo", "tiktok", "animaç", "desfile", "making of", "unbox", "timelapse")
        media_type = "video" if any(k in text for k in video_kw) else "image"
    benefits = parsed.get("benefits") or []
    if not isinstance(benefits, list):
        benefits = [str(benefits)]
    benefits = [str(b).strip() for b in benefits if str(b).strip()][:3]
    return {
        "title": parsed.get("title", ""),
        "headline": (parsed.get("headline") or parsed.get("title") or "").strip(),
        "subheadline": (parsed.get("subheadline") or "").strip(),
        "benefits": benefits,
        "cta": (parsed.get("cta") or "Fale conosco").strip(),
        "copy": parsed.get("copy", ""),
        "hashtags": hashtags,
        "product": parsed.get("product", ""),
        "visual_prompt": parsed.get("visual_prompt", ""),
        "video_prompt": parsed.get("video_prompt", ""),
        "media_type": media_type,
    }


_OBJ_BRIEF = {
    "vender": "conversão — mostre valor concreto e diferencial e leve à ação no fim, sem ser apelão",
    "engajar": "engajamento — provoque, faça perguntas, gere comentários e salvamentos",
    "educar": "educação — ensine algo útil e específico, posicione a marca como autoridade",
    "lançar": "lançamento — novidade, expectativa, o que muda na prática pra quem usa",
    "awareness": "reconhecimento de marca — território, valores e diferencial da marca",
}

# Nomes canônicos dos apps — validados/corrigidos POR SISTEMA (não confia no modelo).
# (regex tolerante a acento/caixa/espaço → forma exata). Ex.: e-Saúde/E-Saude/e-Sáude → E-Saúde.
_APP_CANON = [
    (r"e[\s\-]?s[aáàâ]ude", "E-Saúde"),
    (r"\blooke?\b", "Looke"),       # Look / Looke → Looke
    (r"\bdeezer\b", "Deezer"),
    (r"\bexit[\s\-]?lag\b", "ExitLag"),
    (r"\bcariap\b", "CARIAP"),
]


def _canon_app_names(text: Optional[str]) -> str:
    """Corrige variações de nome de app (acento/caixa/grafia) para a forma exata."""
    if not text:
        return text or ""
    import re as _re
    for pat, repl in _APP_CANON:
        text = _re.sub(pat, repl, text, flags=_re.IGNORECASE | _re.UNICODE)
    return text

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG ABERTA da GERAÇÃO de briefing/carrossel (antes: prompts fixos no código).
# Edite aqui ou via get_setting("carousel.prompts") (JSON) p/ mudar tom, regras, formato.
# {n} em n_exact é substituído pelo nº de telas. NÃO use chaves soltas em json_format.
# ─────────────────────────────────────────────────────────────────────────────
BRIEFING_GEN: Dict[str, Any] = {
    "objetivos": _OBJ_BRIEF,
    "carousel_system": (
        "Você cria CARROSSEL editorial de Instagram no nível das agências g4.business e v4company: "
        "conteúdo de ALTO VALOR, informativo e específico, SEM aspecto de venda no miolo. "
        "A CAPA tem um gancho forte e curto (promessa/curiosidade). Cada slide de CONTEÚDO traz 1 ideia/insight "
        "(título curto + 1 a 3 frases densas, concretas, úteis — nada genérico). O ÚLTIMO slide é o CTA de contratação. "
        "Tom direto, inteligente, brasileiro. Responda SOMENTE com JSON VÁLIDO e COMPACTO: use APENAS os campos pedidos no formato "
        "(NÃO adicione objective, target_audience, main_angle, slide_number, body vazio nem comentários). Sem markdown, sem ```."
    ),
    "carousel_system_evento": (
        "Você cria um CARROSSEL de DIVULGAÇÃO DE EVENTO no Instagram, nível agência. A empresa VAI PARTICIPAR de um evento: "
        "o carrossel ANUNCIA essa participação e CONVIDA a visitar o estande — NÃO é um carrossel institucional de apps. "
        "USE OS DADOS REAIS DO EVENTO fornecidos (nome, datas, local, stand). A CAPA anuncia a presença (ex.: 'A [empresa] vai estar na [evento]') "
        "com gancho. Os slides de CONTEÚDO falam: por que ir ao estande, o que a empresa vai mostrar lá (os apps/soluções como a OFERTA do evento, "
        "NÃO um slide fixo por app), novidades/experiência. O CTA traz 'Visite nosso estande' com as DATAS e o STAND reais e VISÍVEIS (ponha no campo "
        "subtitle/body do CTA). Tom brasileiro, animado, de quem convida. "
        "PROIBIDO INVENTAR: use SOMENTE os dados do evento fornecidos. NUNCA invente datas, local, número de stand, horários ou números — "
        "se um dado não foi dado, NÃO o mencione. O sistema vai carimbar as datas/local/stand REAIS no CTA. Responda SOMENTE JSON válido e compacto, sem markdown."
    ),
    "carousel_system_criativo": (
        "Você cria um POST/CARROSSEL CRIATIVO e OPORTUNO (meme, data comemorativa, acontecimento atual — jogo do Brasil, Copa, feriado, tendência), "
        "fazendo NEWSJACKING: conecta o ACONTECIMENTO do assunto à marca de um jeito leve, esperto e bem-humorado. Mantém a identidade (cores/logo via "
        "sistema) mas a CRIATIVIDADE é LIVRE — gancho cultural forte, pode ser engraçado/direto. NÃO force falar de todos os apps; foque na sacada. "
        "Se fizer sentido, amarre 1 benefício/app à ideia (ex.: 'preparado pro jogo? sua experiência também'). Tom brasileiro, atual. Responda SOMENTE JSON válido e compacto, sem markdown."
    ),
    "n_exact": "Use EXATAMENTE {n} slides no total (incluindo capa e CTA).",
    "n_default": ("Gere de 7 a 9 slides no total (1 capa + 5 a 7 de conteúdo + 1 CTA). "
                  "NUNCA menos que 7 — carrossel curto demais perde valor."),
    "json_format": ('Formato JSON: {"theme":"...","slides":['
                    '{"type":"cover","eyebrow":"CATEGORIA CURTA","title":"gancho 3-8 palavras","subtitle":"1 linha (opcional)","app":"","visual":"cena fotográfica concreta","layout_variant":"center_statement","text_area":"left","brand_logo_position":"bottom_left"},'
                    '{"type":"content","title":"título curto","body":"1-3 frases de valor, sem vender","app":"nome EXATO do app se a tela for sobre um app, senão vazio","visual":"cena fotográfica concreta","layout_variant":"editorial_left|editorial_right|center_statement|app_focus|numbered_insight","text_area":"left|right|center","app_logo_position":"top_right|top_left","brand_logo_position":"bottom_left|bottom_right"},'
                    '... (repita content, VARIANDO o layout_variant),'
                    '{"type":"cta","title":"chamada final p/ contratar","subtitle":"1 linha","cta":"Fale conosco","app":"","visual":"cena fotográfica concreta","layout_variant":"cta_clean","text_area":"left","brand_logo_position":"bottom_left"}]}. '),
    "layout_rule": ("POLÍTICA DE LAYOUT (liberdade controlada): NÃO defina pixels, tamanhos, fonte nem cor — o SISTEMA aplica isso. "
                    "Por slide escolha só: layout_variant (editorial_left, editorial_right, center_statement, app_focus, numbered_insight, split_photo_panel, cta_clean), "
                    "text_area (left|right|center|bottom), app_logo_position e brand_logo_position (top_left|top_right|bottom_left|bottom_right). "
                    "O sistema aplica tamanhos/posições finais, contraste, a logo OFICIAL e ajustes de colisão. "
                    "NUNCA peça pra desenhar logo/texto/marca DENTRO da imagem. VARIE o layout_variant entre as telas (não repita o mesmo). "
                    "Se a tela for sobre um app, use a logo oficial via o campo 'app'. "),
    "visual_rule": ("Em \"visual\" descreva a CENA que MELHOR ilustra ESTE conteúdo — VOCÊ escolhe livremente entre: "
                    "(a) PESSOAS (brasileiras reais, naturais), (b) só ELEMENTOS (o app/produto, tela ou device em uso, objeto, "
                    "cenário, símbolo visual da FUNÇÃO/recurso) ou (c) PESSOAS + ELEMENTOS juntos. Para funções/recursos técnicos, "
                    "prefira MOSTRAR a função (device/elemento), com ou sem pessoa. NÃO ponha pessoa em TODA tela — varie conforme "
                    "o conteúdo rico. Cinematográfico, premium, realista — SEM texto na imagem, SEM logo, SEM clichê de banco de imagem. "),
    "app_rule": "Em \"app\": se a tela falar de um app específico, escreva o nome EXATO; senão deixe vazio. ",
    "name_rule": "NOMES EXATOS E OBRIGATÓRIOS (nunca abrevie/erre): E-Saúde, Looke (NUNCA \"Look\"), Deezer, ExitLag, CARIAP. ",
    "content_rules": ("REGRAS: sem preços; nada de 'compre/contrate/assine' nos slides de conteúdo (só no CTA); "
                      "conteúdo que EDUCA o provedor sobre o tema; frases específicas, não clichê."),
    # ARTE ÚNICA (post fixo / story): cada formato tem sua particularidade. NÃO é carrossel — é UMA peça com tudo junto.
    "single_addendum": (
        " >>> FORMATO ARTE ÚNICA (post fixo / story), NÃO é carrossel: gere UMA ÚNICA peça que entrega TUDO numa tacada — "
        "gancho + a mensagem essencial + o CTA, já juntos. NÃO existe 'próxima página': é PROIBIDO escrever 'arraste', "
        "'veja a seguir', 'no próximo', 'continua', 'role', 'swipe'. Tenha MAIS CRIATIVIDADE e ousadia no conceito "
        "(sem fugir da identidade da marca). Uma frase-conceito forte + no MÁXIMO 1 linha de apoio + um CTA curto e direto. "
        "Densidade máxima numa peça só — nada de encher de texto."
    ),
    "single_json_format": (
        'Formato JSON (UMA tela só, nada além disso): {"theme":"...","slides":[{'
        '"type":"cover","eyebrow":"CATEGORIA CURTA","title":"frase-conceito forte de 3-8 palavras",'
        '"subtitle":"no máx. 1 linha de apoio OU um dado real (data/local do evento); pode ficar vazio",'
        '"cta":"chamada de ação curta (ex.: Fale com a gente, Visite nosso estande, Saiba mais)",'
        '"app":"nome EXATO do app se a peça for sobre um app, senão vazio",'
        '"visual":"cena fotográfica concreta, CRIATIVA e premium que apoie a mensagem (sem texto/logo na imagem)",'
        '"text_area":"left","brand_logo_position":"bottom_left"}]}. '
    ),
    "brief_system": (
        "Você é planejador de conteúdo de uma agência social de alto nível (referência g4.business / v4company). "
        "A partir de um ASSUNTO, entregue um PLANO COMPLETO, específico e forte — nada genérico nem raso. "
        "Conteúdo de VALOR, SEM cara de venda no miolo (CTA de contratação só no fim). "
        "Português do Brasil, em texto organizado e pronto pra produção (não use JSON)."
    ),
    "video_template": ("Formato: VÍDEO/REELS (15-40s). Estruture assim:\n"
                       "GRANDE IDEIA: (1 frase)\n"
                       "Gancho (0-3s): (o que prende nos primeiros segundos)\n"
                       "Cena 1:, Cena 2:, ... (cada cena: o que APARECE + a FALA/legenda)\n"
                       "CTA: (chamada final)\n"
                       "Trilha/clima: (ritmo e sensação)"),
    "post_template": ("Formato: POST ÚNICO (feed). Entregue:\n"
                      "GRANDE IDEIA:\nHeadline:\nÂngulo: (pra quem e por quê)\nMensagem:\n"
                      "Destaques: (3 bullets fortes)\nCTA:\nVisual: (cena concreta e cinematográfica, sem clichê de banco de imagem)"),
}


# Template do PROMPT de imagem: a IA cria a CENA ({visual}); a identidade ({brand_fix}) é fixa
# e aplicada por código. Tudo editável por cliente.
IMAGE_GEN: Dict[str, Any] = {
    "scene_template": ("Foto editorial premium, cinematográfica e realista para carrossel 4:5 (1080x1350): {visual}. "
                       "Pessoas e ambientes brasileiros reais, luz natural controlada, profundidade de campo, lente 35-50mm, "
                       "color grading quente e profissional, espaço negativo para texto. "
                       "NADA de aparência de IA/3D/cartoon/banco de imagem genérico. {brand_fix}"),
    "brand_fix": ("IDENTIDADE FIXA (o sistema aplica DEPOIS — não desenhe, não escreva): cor de marca {color}; "
                  "a logo oficial do app é carimbada pelo código; todo TEXTO entra como camada de design. "
                  "NA FOTO: sem texto, sem letras, sem logo, sem marca d'água."),
}

# Template do PROMPT de vídeo/reels (placeholder editável; a geração de vídeo usa isto quando ligada).
VIDEO_GEN: Dict[str, Any] = {
    "scene_template": ("Cena de vídeo vertical 9:16 cinematográfica e realista: {visual}. "
                       "Movimento natural, luz controlada, ritmo dinâmico, ambiente brasileiro real. "
                       "Sem texto na imagem (entra como camada). {brand_fix}"),
    "brand_fix": "Identidade da marca aplicada por código (cor {color}, logo oficial). Não desenhe texto/logo.",
}

# Defaults criativos GLOBAIS (usados só quando o cliente NÃO personalizou). Tudo editável por cliente.
# Política de layout "liberdade controlada": a IA ESCOLHE entre opções permitidas;
# o CÓDIGO aplica tamanhos/posições finais, logo oficial, contraste e colisão.
LAYOUT_POLICY: Dict[str, Any] = {
    "mode": "controlled_dynamic",
    "ai_can_choose": ["layout_variant", "text_area", "subject_area", "app_logo_position", "brand_logo_position", "logo_variant"],
    "ai_cannot_choose": ["exact_pixel_position", "exact_logo_size", "font_file", "brand_color", "fake_logo", "generated_text_inside_image"],
    "available_layout_variants": ["editorial_left", "editorial_right", "center_statement", "app_focus", "numbered_insight", "cta_clean"],
    "default_layout": "editorial_left",
}
BRAND_LOGO: Dict[str, Any] = {
    "enabled": True, "source": "official_asset_only", "fit": "contain", "preserve_aspect_ratio": True,
    "auto_contrast": True, "max_w": 150, "max_h": 46, "min_w": 110, "min_h": 34,
    "preferred_positions": ["bottom_left", "bottom_right", "top_right"], "avoid_when_app_logo_same_area": True,
}
TEXT_FIT: Dict[str, Any] = {
    "auto_shrink": True, "max_shrink_steps": 5, "prefer_reduce_body_before_title": True, "avoid_orphans": True,
    "max_title_chars_cover": 48, "max_title_chars_content": 56, "max_body_chars_content": 230, "max_subtitle_chars": 90,
}
QUALITY_GUARD: Dict[str, Any] = {
    "detect_text_collision": True, "detect_logo_collision": True, "detect_low_contrast": True, "detect_face_overlap": True,
    "min_text_contrast_ratio": 4.5, "regenerate_if_logo_missing": True, "regenerate_if_fake_logo": True, "regenerate_if_text_inside_image": True,
}

# PADRÕES (templates) de imagem por TIPO. Cada um = estrutura FIXA de diagramação que vai no prompt
# de TODAS as telas → identidade consistente. A IA cria a CENA livre; a ESTRUTURA é travada.
# O cliente pode salvar os próprios (creative_config.templates) via "virar template padrão".
_T_EDITORIAL_ESCURO = (
    "ESTRUTURA FIXA (siga EXATAMENTE, IDÊNTICA em todas as telas): fundo ESCURO (preto/grafite) com leve brilho/textura laranja. "
    "Topo (~16% da altura): área escura sólida e LIMPA, reservada para a logo (não desenhe nada nela). "
    "TÍTULO: grande, negrito forte, alinhado À ESQUERDA, no terço superior; palavras-chave em laranja, o resto em branco. "
    "TEXTO DE APOIO: menor, embaixo À ESQUERDA, com uma BARRA VERTICAL laranja à esquerda. "
    "FOTO: cena fotográfica cinematográfica realista (pessoas/ambiente brasileiro real) ocupando o lado DIREITO e a parte de baixo, "
    "fundida ao fundo escuro com gradiente. Diagramação IGUAL em todas as telas — muda só a foto e o texto."
)
_T_EDITORIAL_CLARO = (
    "ESTRUTURA FIXA (siga EXATAMENTE, IDÊNTICA em todas as telas): fundo CLARO (branco/cinza-claro) limpo e premium. "
    "Topo (~16% da altura): área clara LIMPA reservada para a logo (não desenhe nada nela). "
    "TÍTULO: grande, negrito forte, À ESQUERDA, no terço superior; palavras-chave em laranja, o resto em grafite escuro. "
    "TEXTO DE APOIO: menor, embaixo À ESQUERDA, com BARRA VERTICAL laranja. "
    "FOTO: cena fotográfica cinematográfica realista (pessoas/ambiente brasileiro real) ocupando o lado DIREITO/baixo, com luz clara. "
    "Diagramação IGUAL em todas as telas — muda só a foto e o texto."
)
_T_VIDEO_DINAMICO = (
    "VÍDEO VERTICAL 9:16, ritmo dinâmico de agência. Gancho forte nos primeiros 3s. "
    "Texto-chave GRANDE aparecendo em cena (palavras em laranja sobre fundo escuro). "
    "Cortes rápidos, movimento de câmera suave, ambiente brasileiro real, color grading quente. "
    "Faixa do topo reservada pra logo. Mesma identidade em todas as cenas."
)
_T_VIDEO_CLEAN = (
    "VÍDEO VERTICAL 9:16, clean e premium. Fundo claro, tipografia forte, "
    "transições suaves, foco no produto/benefício, cor de destaque laranja. "
    "Faixa do topo reservada pra logo. Identidade consistente entre as cenas."
)
# Perfis (templates) por CONTEXTO. default + os salvos pelo cliente em creative_config.templates.
IMAGE_TEMPLATES: Dict[str, Any] = {
    "carrossel": [
        {"id": "editorial-escuro", "name": "Editorial Escuro", "variant": "escuro", "structure": _T_EDITORIAL_ESCURO},
        {"id": "editorial-claro", "name": "Editorial Claro", "variant": "claro", "structure": _T_EDITORIAL_CLARO},
    ],
    "post": [
        {"id": "editorial-escuro", "name": "Editorial Escuro", "variant": "escuro", "structure": _T_EDITORIAL_ESCURO},
        {"id": "editorial-claro", "name": "Editorial Claro", "variant": "claro", "structure": _T_EDITORIAL_CLARO},
    ],
    "video": [
        {"id": "dinamico-escuro", "name": "Dinâmico Escuro", "variant": "escuro", "structure": _T_VIDEO_DINAMICO},
        {"id": "clean-claro", "name": "Clean Claro", "variant": "claro", "structure": _T_VIDEO_CLEAN},
    ],
}


def image_templates(company: Optional[Dict[str, Any]] = None, ctype: str = "carrossel") -> List[Dict[str, Any]]:
    """Templates de imagem do tipo (default + os salvos pelo cliente em creative_config.templates)."""
    out = list((IMAGE_TEMPLATES.get(ctype) or []))
    ov = (((company or {}).get("brand_kit") or {}).get("creative_config") or {}).get("templates") or {}
    for t in (ov.get(ctype) or []):
        if isinstance(t, dict) and t.get("id") and t.get("structure"):
            out = [x for x in out if x.get("id") != t["id"]] + [t]
    return out


def image_template_get(company, ctype, tid):
    for t in image_templates(company, ctype):
        if t.get("id") == tid:
            return t
    return None


CREATIVE_DEFAULTS: Dict[str, Any] = {
    "briefing": BRIEFING_GEN,        # geração de texto (carrossel/post/vídeo)
    "image": IMAGE_GEN,              # prompt de imagem
    "video": VIDEO_GEN,              # prompt de vídeo
    "templates": IMAGE_TEMPLATES,    # padrões de diagramação por tipo
    "layout_policy": LAYOUT_POLICY,  # liberdade controlada (a IA escolhe opções; código aplica)
    "brand_logo": BRAND_LOGO,        # regras da logo da marca
    "text_fit": TEXT_FIT,            # auto-ajuste de texto
    "quality_guard": QUALITY_GUARD,  # checagens de qualidade/colisão
}


def _deep_merge(base: Dict[str, Any], ov: Dict[str, Any]) -> Dict[str, Any]:
    out = {**base}
    for k, v in (ov or {}).items():
        out[k] = _deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def creative_cfg(company: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Config criativa EFETIVA = defaults globais + override do CLIENTE (brand_kit.creative_config).
    Nada fica travado no código: o cliente pode sobrescrever qualquer prompt/regra/design."""
    ov = ((company or {}).get("brand_kit") or {}).get("creative_config") or {}
    return _deep_merge(CREATIVE_DEFAULTS, ov if isinstance(ov, dict) else {})


def generate_carousel_caption(company: Dict[str, Any], telas: list, theme: str = "") -> Dict[str, str]:
    """LEGENDA do Instagram (copy + hashtags) a partir das telas do carrossel — pra publicar com TEXTO,
    não só imagem. Retorna {'copy': '...', 'hashtags': '#a #b ...'}. Em erro → vazio (não derruba a geração)."""
    try:
        config = cheap_text_config(get_ai_config())
        if not config or not telas:
            return {"copy": "", "hashtags": ""}
        plano = "\n".join(f"- {t.get('title','')}: {(t.get('body') or t.get('subtitle') or '')[:120]}"
                          for t in telas[:10] if t.get('title'))
        rules = ((company.get("brand_kit") or {}).get("client_rules") or "").strip()
        sys = "Você escreve a LEGENDA de um post de carrossel do Instagram em pt-BR, no tom da marca. Acentuação correta."
        usr = (f"Marca: {company.get('name','')} (vende apps/SVAs para provedores de internet). "
               f"Tema: {theme}. Telas do carrossel:\n{plano}\n\n"
               + (f"Regras do cliente: {rules}. " if rules else "")
               + "Escreva uma LEGENDA envolvente: 1 GANCHO forte na 1a linha, 2-4 linhas de valor (fale COM o "
                 "provedor), e um CTA de contato no fim. Depois 8-12 HASHTAGS relevantes (provedores/ISP/SVA/o tema). "
                 'Responda SÓ JSON: {"copy":"<legenda com \\n entre linhas>","hashtags":"#a #b #c"}')
        data = extract_json(complete_ai(config, sys, usr, 900)) or {}
        return {"copy": (data.get("copy") or "").strip(), "hashtags": (data.get("hashtags") or "").strip()}
    except Exception:
        return {"copy": "", "hashtags": ""}


def generate_briefing(company: Dict[str, Any], theme: str, objetivo: str = "educar",
                      formato: str = "carrossel", n_telas: int = 0,
                      intent: str = "produtos", event: Optional[Dict[str, Any]] = None,
                      apps_focus: Optional[List[str]] = None) -> str:
    """Plano de conteúdo COMPLETO a partir de um assunto, adaptado ao FORMATO e ao OBJETIVO.
    carrossel → plano tela a tela; video → roteiro em cenas; post → pauta rica. Texto (não JSON)."""
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — configure o provedor de texto.")
    G = creative_cfg(company)["briefing"]
    bk = company.get("brand_kit") or {}
    audience = (bk.get("audience") or "provedores de internet (ISPs)").strip()
    rules = (bk.get("client_rules") or "").strip()
    obj = (G.get("objetivos") or _OBJ_BRIEF).get((objetivo or "").lower(), objetivo or "educar")
    fmt = (formato or "carrossel").lower()
    system = G["brief_system"]
    base = (f'Empresa: {company.get("name","")} — vende SVAs/apps para provedores de internet. '
            f'Público (fale COM ele): {audience}. Assunto: "{theme}". Objetivo do conteúdo: {obj}. '
            + (f'Regras do cliente (obedeça à risca): {rules}. ' if rules else ''))
    # CARROSSEL → plano ESTRUTURADO (mesmas telas que o renderizador usa) + texto legível.
    if fmt == "carrossel":
        cr = generate_carousel(company, theme, n_telas, intent=intent, event=event, formato="carrossel", apps_focus=apps_focus)
        telas = cr.get("slides") or []
        linhas = [f"GRANDE IDEIA: {cr.get('theme') or theme}", ""]
        for i, s in enumerate(telas, 1):
            tipo = {"cover": "capa", "cta": "CTA"}.get(s.get("type"), "conteúdo")
            linhas.append(f"Tela {i} — {tipo}: {s.get('title','')}")
            corpo = (s.get("body") or s.get("subtitle") or "").strip()
            if corpo:
                linhas.append(f"  • {corpo}")
            if s.get("visual"):
                linhas.append(f"  • Visual: {s.get('visual')}")
            linhas.append("")
        return {"formato": "carrossel", "telas": telas, "text": "\n".join(linhas).strip()}
    # POST / STORY → 1 ARTE RICA: reusa a MESMA máquina do carrossel e pega a CAPA (forte, standalone,
    # com visual concreto + app → mesma qualidade do carrossel; type=cover → influencer entra). NÃO é pauta pelada.
    if fmt in ("post", "story", "stories", "storie"):
        cr = generate_carousel(company, theme, 1, intent=intent, event=event, formato=fmt, apps_focus=apps_focus)
        slides = cr.get("slides") or []
        tela = dict(slides[0]) if slides else {"type": "cover", "title": theme, "eyebrow": obj}
        tela["type"] = "cover"   # influencer/sanitize tratam como capa; o composer detecta arte única por total==1
        corpo = (tela.get("subtitle") or tela.get("body") or "").strip()
        cta = (tela.get("cta") or "").strip()
        text = "\n".join([f"GRANDE IDEIA: {cr.get('theme') or theme}", "",
                          f"{'Story (9:16)' if fmt != 'post' else 'Post fixo (4:5)'} — {tela.get('title','')}",
                          (f"  • {corpo}" if corpo else ""),
                          (f"  • CTA: {cta}" if cta else ""),
                          (f"  • Visual: {tela.get('visual')}" if tela.get('visual') else "")]).strip()
        return {"formato": fmt, "telas": [tela], "text": text}
    # VÍDEO → roteiro em prosa.
    if fmt in ("video", "vídeo", "reel", "reels"):
        user = base + G["video_template"]
    else:  # fallback (pauta em prosa)
        user = base + G["post_template"]
    return {"formato": fmt, "telas": [], "text": complete_ai(config, system, user, 1700).strip()}


def event_cta_info(event: Optional[Dict[str, Any]]) -> str:
    """Linha de info REAL do evento (datas/local/stand do CADASTRO) — FONTE ÚNICA da verdade.
    Usada pra SANEAR o plano (briefing/legenda) E o render. A IA NÃO decide datas/stand."""
    if not event:
        return ""
    MES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    def _d(s):
        try:
            y, m, d = (s or "").split("-")[:3]; return (int(d), int(m), int(y))
        except Exception:
            return None
    ds = _d(event.get("date_start") or event.get("event_date")); de = _d(event.get("date_end"))
    per = ""
    if ds and de and ds != de:
        per = (f"{ds[0]} a {de[0]} de {MES[ds[1]]} de {ds[2]}" if (ds[1] == de[1] and ds[2] == de[2])
               else f"{ds[0]}/{ds[1]:02d}/{ds[2]} a {de[0]}/{de[1]:02d}/{de[2]}")
    elif ds:
        per = f"{ds[0]} de {MES[ds[1]]} de {ds[2]}"
    stand = (event.get("meta") or {}).get("stand")
    parts = [p for p in [per, (event.get("location") or "").strip(), (("estande " + str(stand)) if stand else "")] if p]
    return " · ".join(parts)


_MES_RE = "janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
_RE_STAND = re.compile(r"\b(estande|stand)\s*#?\s*[A-Za-z]?\d+\b", re.I)  # 'stand 45', 'estande #45', 'stand B12'
_RE_DATE = re.compile(r"\b(dias?\s+)?\d{1,2}(\s*(?:e|a|à|at[eé]|/|-|ao?)\s*\d{1,2})?\s+de\s+(?:" + _MES_RE + r")(?:\s+de\s+\d{4})?\b", re.I)
_RE_MY = re.compile(r"\b(?:" + _MES_RE + r")\s+de\s+\d{4}\b", re.I)
# datas NUMÉRICAS inventadas — sem pegar "24/7": exige ANO, ou RANGE, ou contexto (dias/agenda/data/período).
_RE_NUMDATE = re.compile(
    r"\b\d{1,2}\s*(?:[-–]|a|e|à|at[eé]|ao?)\s*\d{1,2}\s*[/.\-]\s*\d{1,2}(?:\s*[/.\-]\s*\d{2,4})?\b"   # 10-11/11/2026, 10 e 11/11
    r"|\b\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{2,4}\b"                                              # 10/11/2026, 10.11.26
    r"|\b(?:dias?|agenda|data|per[ií]odo)\s*:?\s*\d{1,2}\s*[/.\-]\s*\d{1,2}\b",                        # "Agenda 10/11", "dias 10/11"
    re.I)


def _scrub_event(v):
    """Remove datas (por extenso E numéricas) e 'estande/stand N' INVENTADOS de um texto (a IA não decide isso)."""
    if not isinstance(v, str) or not v:
        return v
    v2 = _RE_NUMDATE.sub("", _RE_MY.sub("", _RE_DATE.sub("", _RE_STAND.sub("", v))))
    return re.sub(r"\s{2,}", " ", v2).strip(" ·,–—-.")


def sanitize_event_plan(event: Optional[Dict[str, Any]], slides: list) -> list:
    """FONTE ÚNICA do dado de evento. (1) REMOVE datas/stand inventados de TODOS os campos públicos de TODAS as
    telas — inclusive 'visual' (que vai pro briefing e pro prompt de imagem). (2) Põe a data/local/stand REAL do
    cadastro no CTA E na capa (em body+subtitle → cobre quem lê body antes). Briefing, legenda e render = mesmo plano."""
    info = event_cta_info(event)
    if not info or not slides:
        return slides
    for s in slides:
        for f in ("title", "body", "subtitle", "cta", "eyebrow", "visual"):
            if s.get(f):
                s[f] = _scrub_event(s[f])
        if (s.get("type") or "") == "cta" and not (s.get("title") or "").strip():
            s["title"] = "Venha nos visitar"   # se o scrub esvaziou o título do CTA, default sensato
    for s in slides:
        if (s.get("type") or "") in ("cta", "cover"):   # CTA e CAPA (post/story pega a capa) recebem o dado REAL
            s["subtitle"] = info
            s["body"] = info
    return slides


def generate_carousel(company: Dict[str, Any], theme: str, n_slides: int = 0, intent: str = "produtos", event: Optional[Dict[str, Any]] = None, formato: str = "carrossel", apps_focus: Optional[List[str]] = None) -> Dict[str, Any]:
    """Gera um CARROSSEL editorial (estilo g4.business / v4company): capa com gancho,
    slides de conteúdo de VALOR (sem cara de venda) e último slide com CTA de contratação.
    n_slides=0 → a IA escolhe (6–9 no total). Texto via Claude (assinatura)."""
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — configure o provedor de texto.")
    G = creative_cfg(company)["briefing"]
    bk = company.get("brand_kit") or {}
    audience = (bk.get("audience") or "provedores de internet (ISPs)").strip()
    rules = (bk.get("client_rules") or "").strip()
    intent = (intent or "produtos").lower()
    single = (formato or "carrossel").lower() in ("post", "story", "stories", "storie")   # ARTE ÚNICA (post/story)
    system = G.get("carousel_system_" + intent) or G["carousel_system"]   # MODO: produtos | evento | criativo
    if single:
        system = system + G["single_addendum"]                            # particularidade do formato arte única
    # Apps REAIS cadastrados → a IA tagueia o campo 'app' por tela a partir DESTES (não inventa) e distribui.
    try:
        from ..db_companies import product_list as _plist
        _prods = _plist(company.get("id")) or []
        _apps = [(p.get("name") or "").strip() for p in _prods if (p.get("name") or "").strip()]
    except Exception:
        _prods, _apps = [], []
    # FOCO EXCLUSIVO: se o usuário marcou só certos apps (caixinhas), restringe o universo a eles (case-insensitive, nome exato do banco).
    _focus_names = [a.strip() for a in (apps_focus or []) if (a or "").strip()]
    if _focus_names:
        _fset = {a.lower() for a in _focus_names}
        _prods = [p for p in _prods if (p.get("name") or "").strip().lower() in _fset]
        _apps = [(p.get("name") or "").strip() for p in _prods if (p.get("name") or "").strip()]
    # Apps CITADOS no tema → TODOS precisam aparecer (1 slide cada). Piso de telas = capa + 1 por app + CTA
    # (teto 10 = limite do Instagram). Cobertura completa vence até a contagem exata pedida.
    import unicodedata as _ud
    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")
    _tnorm = _norm(theme)
    themed = list(_apps) if _focus_names else ([a for a in _apps if _norm(a) and _norm(a) in _tnorm] if intent == "produtos" else [])
    floor = min(len(themed) + 2, 10) if themed else 0
    # BASE DE CONHECIMENTO: junta site(functions) + objetivo + docs(knowledge) dos apps EM FOCO (citados no tema)
    # → briefing PROFUNDO e específico, baseado em fatos REAIS (não raso, não inventado).
    def _app_brief(p):
        fns = p.get("functions") or []
        if isinstance(fns, str):
            try:
                import json as _j; fns = _j.loads(fns)
            except Exception:
                fns = [fns] if fns else []
        fns_t = "; ".join(str(f).strip() for f in fns if str(f).strip())[:2000]
        kb = (p.get("knowledge") or "").strip()
        obj = (p.get("objective") or "").strip()
        seg = []
        if obj:
            seg.append("Objetivo: " + obj)
        if fns_t:
            seg.append("Funções: " + fns_t)
        if kb:
            seg.append("Base de conhecimento (fatos REAIS — use SÓ o que está aqui, não invente recursos):\n" + kb[:8000])
        return (p.get("name"), " | ".join(seg)) if seg else None
    _focus = list(_prods) if _focus_names else [p for p in _prods if _norm(p.get("name")) and _norm(p.get("name")) in _tnorm]
    _kb_blocks = [b for b in (_app_brief(p) for p in _focus) if b]
    kb_line = (("CONHECIMENTO REAL DOS APPS EM FOCO (baseie o conteúdo NESTES fatos/funções — específico e profundo, "
                "sem inventar recursos): " + (" || ".join(f"[{n}] {t}" for n, t in _kb_blocks))[:7000] + ". ") if _kb_blocks else "")
    excl_line = (("FOCO EXCLUSIVO: este conteúdo é SOMENTE sobre " + ", ".join(_apps) + " — NÃO mencione, NÃO cite e NÃO "
                  "crie telas de NENHUM outro app/produto da empresa. ") if (_focus_names and _apps) else "")
    # 3ª FONTE — INTERNET via CACHE por produto (rápido, NÃO bloqueia → adeus 502). Se o cache estiver velho/faltando,
    # dispara refresh em BACKGROUND (o briefing não espera); o cache enriquece a partir do próximo briefing.
    web_line = ""
    _wfocus = _focus or _prods[:3]
    _wtexts = [(p.get("web_brief") or "").strip() for p in _wfocus if (p.get("web_brief") or "").strip()]
    if _wtexts:
        web_line = ("PESQUISA WEB (fatos REAIS da internet — combine com o acima, NÃO invente): "
                    + (" || ".join(_wtexts))[:3000] + ". ")
    try:
        _stale = [p for p in _wfocus if _web_brief_stale(p)]
        if _stale:
            import threading as _th
            _th.Thread(target=refresh_web_briefs, args=(company.get("id"), _stale, theme), daemon=True).start()
    except Exception:
        pass
    # MODO EVENTO: injeta os dados REAIS do evento (datas/local/stand) na instrução do briefing.
    event_line = ""
    if event:
        _ds = (event.get("date_start") or event.get("event_date") or "")
        _de = (event.get("date_end") or "")
        _per = (_ds + (" a " + _de if (_de and _de != _ds) else "")) if _ds else ""
        event_line = ("DADOS REAIS DO EVENTO (use exatamente, não invente; o CTA tem que mostrar datas/local): "
                      "nome=\"" + (event.get("name") or "") + "\""
                      + ((", período=" + _per) if _per else "")
                      + ((", local=" + (event.get("location") or "")) if event.get("location") else "")
                      + ((", sobre: " + (event.get("description") or "")) if event.get("description") else "")
                      + ((", organizador=" + (event.get("organizer_name") or "")) if event.get("organizer_name") else "") + ". ")
    if n_slides and int(n_slides) >= 3:
        n_rule = G["n_exact"].format(n=max(int(n_slides), floor))
    elif floor >= 7:
        n_rule = G["n_exact"].format(n=floor)
    else:
        n_rule = G["n_default"] + (f" Garanta NO MÍNIMO {floor} telas no total. " if floor else "")
    apps_line = ("APPS DISPONÍVEIS desta empresa (use SOMENTE estes no campo 'app', nome EXATO): "
                 + ", ".join(_apps) + ". Em CADA slide de CONTEÚDO que trate de um app, preencha 'app' com o app "
                 "MAIS relevante daquele slide e DISTRIBUA os apps citados no tema entre as telas (não deixe 'app' "
                 "vazio quando a tela é sobre um app). Telas de conceito geral podem ficar com 'app' vazio. ") if _apps else ""
    cover_line = (f"COBERTURA OBRIGATÓRIA: o tema cita estes apps → {', '.join(themed)}. CADA um precisa de PELO "
                  f"MENOS 1 slide de conteúdo dedicado, E aparecer no CTA. NÃO pule NENHUM — nem o que parecer menos "
                  f"óbvio pro tema (ex.: E-Saúde/saúde): ache o ângulo (telemedicina no frio evita sair de casa, "
                  f"consulta sem fila, etc.). ") if themed else ""
    if single:
        # ARTE ÚNICA: UMA peça completa (mensagem + CTA), estrutura própria, sem regras de carrossel.
        user = (
            f"Empresa: {company.get('name','')} — vende SVAs/apps para provedores de internet. "
            f"Público (fale COM ele): {audience}. Tema: {theme}. "
            + event_line + apps_line + kb_line + web_line + excl_line
            + (f"Regras do cliente (obedeça): {rules}. " if rules else "")
            + G["single_json_format"] + G["visual_rule"] + G["app_rule"] + G["name_rule"] + G["content_rules"]
        )
    else:
        user = (
            f"Empresa: {company.get('name','')} — vende SVAs/apps para provedores de internet. "
            f"Público (fale COM ele): {audience}. "
            f"Tema do carrossel: {theme}. {n_rule} "
            + event_line + apps_line + cover_line + kb_line + web_line + excl_line
            + (f"Regras do cliente (obedeça): {rules}. " if rules else "")
            + G["json_format"] + G["visual_rule"] + G["app_rule"] + G["name_rule"]
            + G.get("layout_rule", "") + G["content_rules"]
        )
    # ROBUSTEZ: token alto (JSON de 6+ telas é longo → 4096 truncava e dava 502) + até 3 tentativas.
    slides, data = [], {}
    for _att in range(3):
        sys2 = system + (" Devolva SÓ o JSON COMPLETO e FECHADO (todas as chaves/colchetes), SEM markdown/```, compacto." if _att else "")
        raw = complete_ai(config, sys2, user, 8000)
        data = extract_json(raw) or {}
        slides = data.get("slides") or []
        if slides:
            break
    if not slides:
        raise ValueError("A IA não retornou as telas do carrossel (JSON inválido). Tente de novo.")
    if single:
        # ARTE ÚNICA: 1 peça completa. Garante CTA e tag do app (a IA às vezes omite); pula a cobertura multi-slide.
        s0 = slides[0]; s0["type"] = "cover"
        if not (s0.get("cta") or "").strip():
            s0["cta"] = "Visite nosso estande" if intent == "evento" else "Fale com a gente"
        if not (s0.get("app") or "").strip() and themed:
            s0["app"] = themed[0]
        return {"theme": data.get("theme") or theme, "slides": [s0]}
    # COBERTURA DETERMINÍSTICA: todo app citado TEM que aparecer. Refaz 1x; se AINDA faltar, o CÓDIGO gera
    # a tela do app que sobrou e insere À FORÇA (não depende da boa-vontade da IA).
    if themed:
        def _covered_in(sl, app):
            na = _norm(app)
            return any(na in _norm(" ".join(str(s.get(k) or "") for k in ("app", "title", "body", "subtitle"))) for s in sl)
        if [a for a in themed if not _covered_in(slides, a)]:
            falt = [a for a in themed if not _covered_in(slides, a)]
            raw2 = complete_ai(config, system,
                               user + f" ATENÇÃO: você ESQUECEU estes apps OBRIGATÓRIOS: {', '.join(falt)}. Refaça TODAS as "
                                      f"telas incluindo UMA tela de conteúdo dedicada para CADA um (campo 'app' com o nome exato) "
                                      f"e cite-os no CTA. Não pule nenhum.", 4096)
            s2 = (extract_json(raw2) or {}).get("slides") or []
            if s2 and sum(1 for a in themed if _covered_in(s2, a)) > sum(1 for a in themed if _covered_in(slides, a)):
                slides = s2
        for app in [a for a in themed if not _covered_in(slides, a)]:   # ainda faltou → FORÇA via código
            try:
                one = complete_ai(config, "Você escreve UM slide de carrossel e devolve só JSON.",
                                  f"Empresa {company.get('name','')} oferece o app {app} para provedores de internet. Tema: {theme}. "
                                  f"Escreva 1 slide de conteúdo vendendo o {app} dentro do tema (ache o ângulo, copy curta). "
                                  f'Responda SÓ JSON: {{"title":"...","body":"...","visual":"...","app":"{app}"}}', 600)
                sl1 = extract_json(one) or {}
                if sl1.get("title"):
                    sl1["type"] = "content"; sl1["app"] = app
                    slides.insert(max(1, len(slides) - 1), sl1)   # insere antes do CTA (último)
            except Exception:
                pass
    _LV = (creative_cfg(company).get("layout_policy") or {}).get("available_layout_variants") or ["editorial_left"]
    _DEF_LV = (creative_cfg(company).get("layout_policy") or {}).get("default_layout") or "editorial_left"
    # normaliza: numera os content, garante 1 cover no início e 1 cta no fim
    if slides and slides[0].get("type") != "cover":
        slides[0]["type"] = "cover"
    if slides and slides[-1].get("type") != "cta":
        slides[-1]["type"] = "cta"
    n = 0
    _alt = ["editorial_left", "editorial_right"]
    for i, s in enumerate(slides):
        tp = s.get("type") or "content"
        # validação POR SISTEMA dos nomes de app (corrige acento/caixa/grafia)
        for f in ("title", "body", "subtitle", "eyebrow", "cta"):
            if s.get(f):
                s[f] = _canon_app_names(s[f])
        s["app"] = _canon_app_names((s.get("app") or "").strip())
        if tp == "content":
            n += 1
            s["number"] = n
        # layout_variant: valida contra os permitidos; default por tipo; alterna esquerda/direita se inválido
        lv = (s.get("layout_variant") or "").strip()
        if lv not in _LV:
            lv = "center_statement" if tp == "cover" else ("cta_clean" if tp == "cta" else _alt[n % 2])
        if lv in ("center_statement",) and tp == "content":
            pass
        s["layout_variant"] = lv if lv in _LV else _DEF_LV
        s.setdefault("text_area", "left")
        s.setdefault("app_logo_position", "top_right")
        s.setdefault("brand_logo_position", "bottom_left")
    # SANEAMENTO NA FONTE (briefing + legenda + render): dado REAL do evento; remove stand inventado.
    slides = sanitize_event_plan(event, slides)
    return {"theme": _canon_app_names(data.get("theme") or theme), "slides": slides}


def generate_social_strategy(
    company: Dict[str, Any],
    own_profile: Dict[str, Any],
    competitor_profiles: List[Dict[str, Any]],
    references: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate a practical social media strategy from profile/competitor signals."""
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")

    brand_kit = company.get("brand_kit") or {}
    system = (
        "Você é um diretor de estratégia social media e diretor de arte brasileiro. "
        "Transforme perfil da empresa, concorrentes e referências em um plano operacional. "
        "Responda SOMENTE com JSON válido neste formato: "
        '{"summary":"...","brand_identity":{"positioning":"...","voice":"...","persona":"...",'
        '"visual_prompt_base":"...","style_keywords":["..."],"colors":["#..."],"do":["..."],"dont":["..."]},'
        '"content_pillars":[{"name":"...","angle":"...","formats":["reels","carrossel"],"cadence":"..."}],'
        '"competitor_insights":[{"competitor":"...","what_works":"...","gap":"...","adaptation":"..."}],'
        '"post_ideas":[{"title":"...","caption":"...","format":"reels|carrossel|story|feed",'
        '"network":"instagram","visual_prompt":"...","hashtags":["#..."],"why":"..."}],'
        '"production_brief":["..."],"next_actions":["..."]} '
        "Gere no mínimo 8 ideias de posts. Não invente números de métricas se não vierem nos dados. "
        "OBRIGATÓRIO: baseie os pilares e as ideias nos PRODUTOS/APLICATIVOS reais que a empresa "
        "vende (campo 'products'). Cada ideia deve promover um produto específico citando o nome e "
        "seus benefícios — nada genérico, fora do que a empresa realmente vende. "
        "Tudo em PT-BR, prático, sem markdown."
    )
    _audience = (brand_kit.get("audience") or "").strip()
    if _audience:
        system += " CONTEXTO DE NEGÓCIO (siga à risca, define público e posicionamento): " + _audience
    _rules = (brand_kit.get("client_rules") or "").strip()
    if _rules:
        system += " REGRAS DESTE CLIENTE (correções já pedidas por ele — NUNCA repita estes erros): " + _rules
    payload = {
        "company": {
            "name": company.get("name"),
            "segment": company.get("segment"),
            "city": company.get("city"),
            "state": company.get("state"),
            "website": company.get("website"),
            "socials": company.get("socials") or {},
        },
        "current_brand_kit": {
            "voice": brand_kit.get("voice"),
            "persona": brand_kit.get("persona"),
            "visual_prompt_base": brand_kit.get("visual_prompt_base"),
            "colors": brand_kit.get("colors") or {},
        },
        "own_profile_analysis": own_profile or {},
        "competitor_profiles": competitor_profiles or [],
        "references": references or [],
    }
    # Inject the real products/apps the company sells so ideas talk about them.
    try:
        from ..db_companies import product_list
        _prods = product_list(company.get("id") or "") or []
    except Exception:
        _prods = []
    payload["products"] = [{"name": p.get("name"), "description": (p.get("description") or "")[:200], "objetivo": (p.get("objective") or "")[:300]} for p in _prods[:25]]
    # Keep input small/cheap: cap the bulky Composio analysis + competitor dossiers.
    def _cap(value: Any, limit: int) -> Any:
        s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return s[:limit]

    if payload.get("own_profile_analysis"):
        payload["own_profile_analysis"] = _cap(payload["own_profile_analysis"], 2000)
    payload["competitor_profiles"] = [
        {"name": (c or {}).get("name"), "note": _cap(c, 1200)} for c in (payload.get("competitor_profiles") or [])[:5]
    ]
    payload["references"] = [(r or {}).get("url") for r in (payload.get("references") or [])[:5] if isinstance(r, dict)]

    result = complete_ai(config, system, json.dumps(payload, ensure_ascii=False), 8000)
    parsed = extract_json(result)
    if not parsed:
        raise ValueError("IA não retornou JSON válido para a estratégia social.")
    if not isinstance(parsed.get("post_ideas"), list):
        parsed["post_ideas"] = []
    if not isinstance(parsed.get("content_pillars"), list):
        parsed["content_pillars"] = []
    if not isinstance(parsed.get("competitor_insights"), list):
        parsed["competitor_insights"] = []
    return parsed
