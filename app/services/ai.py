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
import threading
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..db import settings_get, settings_set
from ..security.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Settings whitelist
# ─────────────────────────────────────────────────────────────────────────────

SETTINGS_WHITELIST: Dict[str, List[str]] = {
    # Texto SÓ via gateways unificados — anthropic/openai DIRETOS removidos. kie.ai não faz texto LLM
    # (só imagem/vídeo via jobs async), por isso fica de fora aqui.
    "ai": ["cometapi", "openrouter", "omniroute"],
    "image": ["openai", "openrouter", "fal", "cometapi", "piapi", "omniroute"],
    "image_ref": ["openrouter", "kie", "cometapi", "omniroute"],   # ESTÚDIO IA (reference_full) — modelo escolhível
    "video": ["fal", "openai", "openrouter", "cometapi"],
}

EXTRA_KEYS = {"postiz.url", "postiz.apiKey", "ai.apiKey"}

# Catálogo de TEXTO CURADO por gateway: ~5 Claude + 5 OpenAI + 5 Grok + 5 diversos (gemini/glm/deepseek/qwen),
# com ids REAIS do catálogo de cada provedor (validados ao vivo). Onde o gateway não expõe uma família
# (ex.: OmniRoute só libera os mirrors grátis das assinaturas), a lista traz só o que responde de verdade.
DEFAULT_MODELS: Dict[str, Dict[str, List[str]]] = {
    "ai": {
        "cometapi": [
            # Claude (melhor copy PT-BR, preserva acentos)
            "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5-20251001",
            # OpenAI
            "gpt-5", "gpt-5-pro", "gpt-5-mini", "gpt-5-thinking", "o4-mini",
            # Grok
            "grok-4", "grok-4.3", "grok-4-fast-reasoning", "grok-4-1-fast-reasoning", "grok-4.20-0309-reasoning",
            # Diversos (Gemini / GLM / DeepSeek / Qwen)
            "gemini-3-pro-preview", "gemini-3.1-pro-preview", "glm-5.2", "deepseek-v3.2", "qwen-max",
        ],
        "openrouter": [
            "anthropic/claude-opus-4.8", "anthropic/claude-opus-4.7", "anthropic/claude-sonnet-4.6", "anthropic/claude-sonnet-4.5", "anthropic/claude-haiku-4.5",
            "openai/gpt-5.5", "openai/gpt-5.5-pro", "openai/gpt-5.4", "openai/gpt-5.4-mini", "openai/o4-mini",
            "x-ai/grok-4.20", "x-ai/grok-4.3", "x-ai/grok-4.20-multi-agent",
            "google/gemini-3.1-pro-preview", "google/gemini-3-flash-preview", "z-ai/glm-5.2", "z-ai/glm-5", "deepseek/deepseek-v3.2",
        ],
        # OmniRoute = mirrors GRÁTIS das assinaturas do usuário (só estes respondem com a chave atual;
        # grok/gemini/glm dão 401/timeout). Claude preserva acento; GPT-web também.
        "omniroute": [
            "cc/claude-opus-4-8", "cc/claude-opus-4-7", "cc/claude-opus-4-6", "antigravity/claude-sonnet-4-6",
            "cgpt-web/gpt-5.5", "cgpt-web/gpt-5.5-pro", "cgpt-web/gpt-5.4-pro",
        ],
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
    provider = get_setting("ai.provider") or "omniroute"
    model = get_setting("ai.model")
    if provider == "omniroute":   # gateway das assinaturas (grátis). Mirror cc/ preserva acento no texto.
        return {"provider": "omniroute", "apiKey": _omniroute_key() or "x", "model": model or "cc/claude-opus-4-8"}
    if provider == "cometapi":    # texto via CometAPI (OpenAI-compat) — preserva acentos
        return {"provider": "cometapi", "apiKey": _cometapi_key(), "model": model or "claude-sonnet-4-6"}
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
    # OmniRoute (grátis · assinaturas): Sonnet aguenta o JSON pesado do carrossel e preserva acento.
    "omniroute": "antigravity/claude-sonnet-4-6",
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

    # TEXTO: catálogo CURADO por gateway (não despeja a API inteira). ids validados em DEFAULT_MODELS["ai"].
    if section == "ai" and provider in ("cometapi", "openrouter", "omniroute"):
        return defaults

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
    """Image-gen config. Default = OmniRoute (grátis, assinaturas). CometAPI/PiAPI sem saldo."""
    provider = (get_setting("image.provider") or "omniroute").strip()
    model = get_setting("image.model") or ""
    # OmniRoute (gateway das assinaturas) — imagem grátis pela assinatura.
    if provider == "omniroute" or model.lower().startswith("omni:"):
        return {"provider": "omniroute", "model": model or "omni:antigravity/gemini-3.1-flash-image",
                "apiKey": _omniroute_key() or "x", "quality": get_setting("image.quality") or "high"}
    # kie.ai / CometAPI / PiAPI (imagem em CRÉDITOS/$): roteados pelo prefixo do id — get_image_config
    # NÃO pode cair no ramo openrouter só porque o id tem "/". O dispatch real usa o prefixo do model.
    _ml = model.lower()
    if (provider in ("kie", "cometapi", "cometapi_gemini", "piapi")
            or _ml.startswith(("kie:", "cometapi:", "cometapi-gemini:", "piapi:"))):
        prov = ("kie" if provider == "kie" or _ml.startswith("kie:")
                else "cometapi_gemini" if provider == "cometapi_gemini" or _ml.startswith("cometapi-gemini:")
                else "cometapi" if provider == "cometapi" or _ml.startswith("cometapi:")
                else "piapi")
        # cometapi_gemini/cometapi usam a MESMA conta CometAPI → _cometapi_key(); dispatch real vai pelo prefixo do model.
        _kcred = _cometapi_key() if prov in ("cometapi", "cometapi_gemini") else (get_credential("image", prov) or "x")
        return {"provider": prov, "model": model, "apiKey": _kcred or "x",
                "quality": get_setting("image.quality") or "high"}
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
    ("omni-fast", "omni-fast", "Boa", 0.40, 8),
]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _usage_cost(data: Any) -> float:
    if not isinstance(data, dict):
        return 0.0
    usage = data.get("usage") or {}
    if isinstance(usage, dict):
        for key in ("cost", "total_cost", "totalCost"):
            val = _safe_float(usage.get(key))
            if val > 0:
                return val
    for key in ("cost", "total_cost", "totalCost"):
        val = _safe_float(data.get(key))
        if val > 0:
            return val
    return 0.0


def _learned_image_price(model_id: str) -> float:
    """Preço real aprendido do último `usage.cost` retornado pelo provedor para este modelo."""
    mid = (model_id or "").strip()
    if not mid:
        return 0.0
    return _safe_float(get_setting("image.price." + mid))


def _remember_image_price(model_id: str, cost: Any) -> None:
    """Cacheia custo real de imagem por modelo quando o provedor devolve usage.cost."""
    mid = (model_id or "").strip()
    val = _safe_float(cost)
    if not mid or val <= 0:
        return
    try:
        from datetime import datetime, timezone
        settings_set(key="image.price." + mid, value=str(val), updated_at=datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def _image_price_fields(model_id: str, fallback: float, fallback_source: str = "fallback") -> Dict[str, Any]:
    learned = _learned_image_price(model_id)
    if learned > 0:
        return {"price_per_image": round(learned, 4), "price_source": "usage_learned"}
    return {"price_per_image": round(_safe_float(fallback), 4), "price_source": fallback_source}


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


def _openrouter_image_catalog() -> Dict[str, Dict[str, Any]]:
    key = _openrouter_key()
    if not key:
        return {}
    try:
        with httpx.Client(timeout=20) as c:
            res = c.get("https://openrouter.ai/api/v1/images/models", headers={"Authorization": f"Bearer {key}"})
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


def _cometapi_image_price(model: Dict[str, Any]) -> float:
    pricing = model.get("pricing") or {}
    if not isinstance(pricing, dict):
        return 0.0
    return _safe_float(pricing.get("per_request"))


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
    """Top-10 modelos de imagem curados, só os disponíveis no OpenRouter.
    O catálogo atual de imagens do OpenRouter lista disponibilidade, mas não expõe preço por modelo;
    por isso o preço fica marcado como estimado até `usage.cost` ensinar o valor real."""
    catalog = _openrouter_image_catalog()
    avail = set(catalog)
    # reve-2.0 é API própria (não OpenRouter) → só entra se o token Reve estiver configurado.
    has_reve = bool(_reve_key())
    out = []
    for i, (s, n, q, p) in enumerate(CURATED_IMAGE):
        if s.startswith("reve"):
            if not has_reve:
                continue
            src = "fallback"
        else:
            if avail and s not in avail:
                continue
            src = "fallback"
        row = {"id": s, "name": n, "quality": q, "rank": i, **_image_price_fields(s, p, src)}
        out.append(row)
    return out or [{"id": s, "name": n, "quality": q, "rank": i, **_image_price_fields(s, p, "fallback")}
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


# ===================== VÍDEO via kie.ai (DIRETO, async createTask/recordInfo) =====================
# Pago em CRÉDITOS (1 crédito ≈ $0,005). id da nossa UI = "kie:" + model_id real do market da kie.
# Custo real vem do recordInfo.creditsConsumed (aprendido por modelo em setting 'kie.credits.<model>').
_KIE_BASE = "https://api.kie.ai/api/v1"

# (model_id real no market da kie, nome amigável, tier top|medium|fast, max_segundos)
CURATED_VIDEO_KIE = [
    # ---- TOP (melhor qualidade) ----
    ("sora2/sora-2-pro-text-to-video",      "Sora 2 Pro",          "top",    12),
    ("sora2/sora-2-text-to-video",          "Sora 2",              "top",    12),
    ("kling/v3-turbo-text-to-video",        "Kling 3 Turbo",       "top",    10),
    ("kling/v25-turbo-text-to-video-pro",   "Kling 2.5 Turbo Pro", "top",    10),
    ("kling/v2-1-master-text-to-video",     "Kling 2.1 Master",    "top",    10),
    ("bytedance/seedance-1-5-pro",          "Seedance 1.5 Pro",    "top",    10),
    ("hailuo/02-text-to-video-pro",         "Hailuo 02 Pro",       "top",    10),
    # ---- MEDIUM (equilíbrio) ----
    ("bytedance/v1-pro-text-to-video",      "Seedance V1 Pro",     "medium", 10),
    ("bytedance/seedance-2",                "Seedance 2",          "medium", 10),
    ("bytedance/seedance-2-fast",           "Seedance 2 Fast",     "medium", 10),
    ("wan/2-7-text-to-video",               "Wan 2.7",             "medium", 8),
    ("wan/2-6-text-to-video",               "Wan 2.6",             "medium", 8),
    ("wan/2-5-text-to-video",               "Wan 2.5",             "medium", 8),
    ("kling/text-to-video",                 "Kling",               "medium", 10),
    ("hailuo/02-text-to-video-standard",    "Hailuo 02 Standard",  "medium", 10),
    # ---- FAST (barato/rápido) ----
    ("grok-imagine/text-to-video",          "Grok Imagine",        "fast",   6),
    ("bytedance/v1-lite-text-to-video",     "Seedance V1 Lite",    "fast",   10),
    ("bytedance/seedance-2-mini",           "Seedance 2 Mini",     "fast",   10),
    ("wan/2-2-a14b-text-to-video-turbo",    "Wan 2.2 Turbo",       "fast",   8),
    ("happyhorse/text-to-video",            "HappyHorse",          "fast",   8),
    ("happyhorse-1-1/text-to-video",        "HappyHorse 1.1",      "fast",   8),
]
_KIE_BY_MODEL = {m: (m, n, t, sec) for (m, n, t, sec) in CURATED_VIDEO_KIE}
_KIE_TIER_RANK = {"top": 0, "medium": 1, "fast": 2}
_KIE_TIER_LABEL = {"top": "TOP", "medium": "MÉDIO", "fast": "RÁPIDO"}


def _kie_key() -> str:
    """Chave da kie.ai (setting 'kie.api_key' / credencial / env). Vazio = kie desligado."""
    try:
        return (get_setting("kie.api_key") or get_credential("video", "kie")
                or os.environ.get("KIE_API_KEY") or "").strip()
    except Exception:
        return (os.environ.get("KIE_API_KEY") or "").strip()


def _kie_resolution(tier: str) -> str:
    return "1080p" if tier == "top" else "720p"        # nunca 480p; top em 1080p


def _kie_build_input(model: str, prompt: str, aspect: str, duration: int, resolution: str) -> Dict[str, Any]:
    """Monta o 'input' do createTask conforme a FAMÍLIA do modelo (schemas variam na kie)."""
    p = (prompt or "")[:4000]
    dur = str(int(duration or 5) or 5)
    if model.startswith("grok-imagine/"):
        return {"prompt": p, "aspect_ratio": aspect, "mode": "normal", "duration": dur, "resolution": resolution}
    if model.startswith("kling/"):                      # kling t2v: sem resolution; usa negative_prompt/cfg_scale
        return {"prompt": p, "aspect_ratio": aspect, "duration": dur,
                "negative_prompt": "blur, distort, low quality", "cfg_scale": 0.5}
    if model.startswith("sora2/"):                      # sora-2: prompt + aspect (+ duração)
        return {"prompt": p, "aspect_ratio": aspect, "duration": dur}
    # bytedance/seedance, wan, hailuo, happyhorse → schema comum
    return {"prompt": p, "aspect_ratio": aspect, "resolution": resolution, "duration": dur}


def kie_video_models() -> List[Dict[str, Any]]:
    """Catálogo de VÍDEO da kie.ai (text-to-video), em tiers top/medium/fast. id prefixado 'kie:'.
    Sem chave → vazio (não quebra a UI). Custo em CRÉDITOS (aprendido por modelo; default por tier)."""
    if not _kie_key():
        return []
    out = []
    cred_default = {"top": 90, "medium": 30, "fast": 15}    # estimativa inicial; o real é aprendido por uso
    for i, (model, name, tier, sec) in enumerate(CURATED_VIDEO_KIE):
        try:
            learned = get_setting("kie.credits." + model)
        except Exception:
            learned = None
        credits = float(learned) if learned else float(cred_default.get(tier, 30))
        out.append({"id": "kie:" + model, "name": f"{name} · {_KIE_TIER_LABEL[tier]}",
                    "quality": _KIE_TIER_LABEL[tier], "tier": tier,
                    "credits": credits, "credits_learned": bool(learned),
                    "price_per_video": 0.0, "price_per_second": 0.0,
                    "max_seconds": sec, "rank": _KIE_TIER_RANK[tier] * 100 + i, "price_source": "credits"})
    return out


def _kie_create_task(model: str, prompt: str, seconds: Any, aspect: str = "9:16", tier: str = "medium") -> str:
    """POST kie /jobs/createTask → devolve taskId. Levanta em erro."""
    key = _kie_key()
    if not key:
        raise ValueError("kie.api_key não configurada.")
    entry = _KIE_BY_MODEL.get(model)
    sec = _video_seconds_value(str(seconds or ""), 5)
    if entry:
        sec = min(sec, entry[3]); tier = entry[2]
    body = {"model": model, "input": _kie_build_input(model, prompt, aspect, sec, _kie_resolution(tier))}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        r = c.post(_KIE_BASE + "/jobs/createTask",
                   headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    try:
        j = r.json()
    except Exception:
        j = {}
    if r.status_code >= 400 or (j.get("code") not in (200, None)):
        raise ValueError(f"kie createTask falhou (HTTP {r.status_code}): {r.text[:300]}")
    tid = (j.get("data") or {}).get("taskId") or (j.get("data") or {}).get("recordId")
    if not tid:
        raise ValueError(f"kie sem taskId: {r.text[:200]}")
    return tid


def _kie_record(task_id: str) -> Dict[str, Any]:
    """GET kie /jobs/recordInfo?taskId= → data (state/resultJson/creditsConsumed/...)."""
    key = _kie_key()
    if not key:
        return {"_poll_error": "kie.api_key não configurada"}
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0)) as c:
            r = c.get(_KIE_BASE + "/jobs/recordInfo",
                      headers={"Authorization": "Bearer " + key}, params={"taskId": task_id})
        payload = r.json() or {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data:
            return data
        detail = (payload.get("msg") if isinstance(payload, dict) else "") or r.text[:160]
        return {"_poll_error": f"HTTP {r.status_code}: {detail}"}
    except Exception as exc:
        # Polling de job longo não pode morrer por uma oscilação curta da rede.
        return {"_poll_error": str(exc)[:180]}


def _kie_result_urls(data: Dict[str, Any]) -> List[str]:
    """Extrai URLs dos formatos de retorno usados pela kie.

    O Market documenta ``resultJson`` como JSON serializado, mas endpoints dedicados
    e modelos novos também aninham o resultado em ``response``/``output`` ou
    devolvem uma única URL. Não percorremos ``param`` para nunca confundir uma
    imagem de entrada com a arte gerada.
    """
    found: List[str] = []
    url_keys = {
        "resultUrls", "result_urls", "urls", "url", "resultUrl", "result_url",
        "imageUrl", "image_url", "videoUrl", "video_url",
    }
    container_keys = {"resultJson", "response", "output", "result", "data"}

    def _decoded(value):
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw or raw[0] not in "[{":
            return value
        try:
            return json.loads(raw)
        except Exception:
            return value

    def _collect(value, allow_all_keys: bool = False) -> None:
        value = _decoded(value)
        if isinstance(value, str):
            if value.startswith(("http://", "https://")):
                found.append(value)
            return
        if isinstance(value, list):
            for item in value:
                _collect(item, True)
            return
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if key in url_keys:
                _collect(item, True)
            elif key in container_keys or allow_all_keys:
                _collect(item, True)

    if isinstance(data, dict):
        for key in container_keys | url_keys:
            if key in data:
                _collect(data[key], key in container_keys)
    return list(dict.fromkeys(found))


# ===================== IMAGEM via kie.ai (text-to-image, CRÉDITOS) =====================
# Mesma infra do vídeo (createTask/recordInfo/creditsConsumed). id da UI = "kie:" + model real do market.


def _kie_credit_usd() -> float:
    """Valor de 1 crédito kie em USD (setting kie.credit_usd; default 0.005 = $5/1000 créditos)."""
    try:
        return float(get_setting("kie.credit_usd") or 0.005)
    except Exception:
        return 0.005


def _kie_cost_usd(model_key: str, credits_consumed, default_credits: float = 0.0) -> float:
    """Custo REAL de uma geração kie em USD: creditsConsumed do recordInfo (e APRENDE no setting
    kie.credits.<model> pra UI mostrar o preço certo); sem cc → usa o aprendido; sem nada → default do
    tier. Antes as funções kie retornavam 0.0 → billing/UI mostravam 'grátis' pra geração PAGA."""
    cc = None
    try:
        cc = float(credits_consumed) if credits_consumed is not None else None
    except Exception:
        cc = None
    if cc:
        try:
            from ..db import settings_set as _ss
            from datetime import datetime as _dt, timezone as _tz
            _ss(key="kie.credits." + model_key, value=str(cc), updated_at=_dt.now(_tz.utc).isoformat())
        except Exception:
            pass
    if cc is None:
        try:
            cc = float(get_setting("kie.credits." + model_key) or 0.0)
        except Exception:
            cc = 0.0
    if not cc:
        cc = float(default_credits or 0.0)
    return round(cc * _kie_credit_usd(), 4)
# IDs VALIDADOS ao vivo (createTask aceita o model name). NÃO adicionar sem validar (queima crédito).
# (model_id real, nome amigável, tier top|medium|fast)
CURATED_IMAGE_KIE = [
    # (model_id REAL validado ao vivo no createTask, descrição clara p/ o usuário escolher, tier)
    # 'chatgpt/*' NÃO usa o market de jobs: vai pelo endpoint dedicado /gpt4o-image (generate_image_kie_gpt)
    ("chatgpt/gpt-5.4-image-2",             "GPT-5.4 Image 2 · ChatGPT — arte completa, texto perfeito, aceita referências", "top"),
    ("bytedance/seedream-v4-text-to-image", "Seedream 4.0 · ByteDance — fotorrealismo forte, ótimo p/ pessoa e produto", "top"),
    ("google/imagen4-ultra",                "Imagen 4 Ultra · Google — máxima qualidade e realismo fotográfico",       "top"),
    ("google/nano-banana",                  "Nano-Banana · Gemini 2.5 Flash — versátil e rápido, bom em cenas com gente","top"),
    ("google/imagen4",                      "Imagen 4 · Google — realismo alto, equilíbrio qualidade/custo",           "medium"),
    ("qwen2/text-to-image",                 "Qwen-Image 2 · Alibaba — forte em texto/tipografia dentro da arte",       "medium"),
    ("grok-imagine/text-to-image",          "Grok Imagine · xAI — estilo criativo/meme, cenas ousadas",               "medium"),
    ("google/imagen4-fast",                 "Imagen 4 Fast · Google — o mais barato/rápido da linha Imagen",           "fast"),
    ("qwen/text-to-image",                  "Qwen-Image · Alibaba — barato e rápido p/ rascunho",                      "fast"),
]
_KIE_IMG_BY_MODEL = {m: (m, n, t) for (m, n, t) in CURATED_IMAGE_KIE}
# Seedream usa image_size em ENUM (não WxH). Mapeia o aspecto do nosso size pro enum mais próximo.
_KIE_SEEDREAM_SIZE = {"1:1": "square_hd", "2:3": "portrait_4_3", "3:4": "portrait_4_3", "9:16": "portrait_16_9",
                      "3:2": "landscape_4_3", "4:3": "landscape_4_3", "16:9": "landscape_16_9"}


def _kie_image_aspect(size: str) -> str:
    try:
        import math as _m
        w, h = (size or "1024x1024").lower().split("x"); w, h = int(w), int(h)
        g = _m.gcd(w, h) or 1
        return f"{w // g}:{h // g}"
    except Exception:
        return "1:1"


def _kie_aspect_for(model: str, size: str) -> str:
    """aspect_ratio no ENUM aceito por cada família (validado ao vivo: imagen4/qwen2 usam 3:4;
    grok-imagine rejeita 3:4 e usa 2:3 no retrato)."""
    try:
        w, h = (size or "1024x1024").lower().split("x"); r = int(w) / max(1, int(h))
    except Exception:
        r = 1.0
    if 0.97 <= r <= 1.03:
        bucket = "square"
    elif r < 0.65:
        bucket = "tall"
    elif r < 0.97:
        bucket = "portrait"
    elif r > 1.5:
        bucket = "wide"
    else:
        bucket = "landscape"
    if "grok-imagine" in model.lower():
        return {"square": "1:1", "tall": "9:16", "portrait": "2:3", "wide": "16:9", "landscape": "3:2"}[bucket]
    return {"square": "1:1", "tall": "9:16", "portrait": "3:4", "wide": "16:9", "landscape": "4:3"}[bucket]


def _kie_build_image_input(model: str, prompt: str, size: str = "1024x1024") -> Dict[str, Any]:
    """input do createTask p/ IMAGEM (schema varia por família — todos validados ao vivo)."""
    p = (prompt or "")[:4000]
    ml = model.lower()
    if "seedream" in ml:                                   # Seedream: image_size em ENUM + resolução
        ar = _kie_image_aspect(size)
        return {"prompt": p, "image_size": _KIE_SEEDREAM_SIZE.get(ar, "portrait_4_3"),
                "image_resolution": "2K", "max_images": 1}
    if any(x in ml for x in ("imagen4", "grok-imagine", "qwen2")):   # exigem aspect_ratio
        return {"prompt": p, "aspect_ratio": _kie_aspect_for(model, size)}
    # google/nano-banana e qwen/text-to-image: só prompt (validado).
    return {"prompt": p}


def _kie_create_image_task(model: str, prompt: str, size: str = "1024x1024") -> str:
    key = _kie_key()
    if not key:
        raise ValueError("kie.api_key não configurada.")
    body = {"model": model, "input": _kie_build_image_input(model, prompt, size)}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        r = c.post(_KIE_BASE + "/jobs/createTask",
                   headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    try:
        j = r.json()
    except Exception:
        j = {}
    if r.status_code >= 400 or (j.get("code") not in (200, None)):
        raise ValueError(f"kie image createTask falhou (HTTP {r.status_code}): {r.text[:300]}")
    tid = (j.get("data") or {}).get("taskId") or (j.get("data") or {}).get("recordId")
    if not tid:
        raise ValueError(f"kie image sem taskId: {r.text[:200]}")
    return tid


def kie_image_models() -> List[Dict[str, Any]]:
    """Catálogo de IMAGEM da kie.ai (text-to-image), tiers top/medium/fast. id 'kie:'. Custo em CRÉDITOS
    (aprendido por modelo; default por tier). Sem chave → vazio (não quebra a UI)."""
    if not _kie_key():
        return []
    out = []
    cred_default = {"top": 6, "medium": 4, "fast": 2}      # estimativa inicial; real aprendido por uso
    for i, (model, name, tier) in enumerate(CURATED_IMAGE_KIE):
        try:
            learned = get_setting("kie.credits." + model)
        except Exception:
            learned = None
        credits = float(learned) if learned else float(cred_default.get(tier, 4))
        out.append({"id": "kie:" + model, "name": f"{name} · {_KIE_TIER_LABEL[tier]}",
                    "quality": _KIE_TIER_LABEL[tier], "tier": tier,
                    "credits": credits, "credits_learned": bool(learned), "price_per_image": 0.0,
                    "rank": _KIE_TIER_RANK[tier] * 100 + i, "price_source": "credits"})
    return out


def generate_image_kie(model_id: str, prompt: str, size: str = "1024x1024") -> Tuple[bytes, float]:
    """Gera imagem via kie (createTask → poll recordInfo → baixa). Retorna (bytes, 0.0): custo é em CRÉDITOS
    (aprende kie.credits.<model> do creditsConsumed). model_id pode vir com prefixo 'kie:'."""
    import time as _t
    real = model_id[len("kie:"):] if str(model_id).lower().startswith("kie:") else model_id
    if real.startswith("chatgpt/"):                        # GPT image tem endpoint próprio na kie (não é o market)
        return generate_image_kie_gpt(prompt, size)
    tid = _kie_create_image_task(real, prompt, size)
    _kie_ledger(tid, real, "jobs")
    last: Dict[str, Any] = {}
    poll_errors = 0
    completed_without_url = 0
    for _ in range(120):                                   # ~6min (fila da conta kie estica com paralelismo)
        _t.sleep(3)
        d = _kie_record(tid)
        if d.get("_poll_error"):
            poll_errors += 1
            if poll_errors >= 10:
                raise ValueError("kie image: consulta de status indisponível: " + str(d["_poll_error"])[:160])
            continue
        poll_errors = 0
        st = (d.get("state") or "").lower()
        if st == "success":
            last = d
            if _kie_result_urls(d):
                break
            # Às vezes o estado vira success alguns segundos antes de o CDN aparecer.
            completed_without_url += 1
            if completed_without_url >= 3:
                raise ValueError("kie image concluiu, mas não publicou a URL do resultado.")
            continue
        if st == "fail":
            raise ValueError("kie image falhou: " + str(d.get("failMsg") or "")[:200])
    cost = _kie_cost_usd(real, last.get("creditsConsumed"), 4)
    urls = _kie_result_urls(last)
    if not urls:
        raise ValueError("kie image sem resultUrls (não concluiu a tempo).")
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
        rr = c.get(urls[0])
    if rr.status_code >= 400 or not rr.content:
        raise ValueError(f"kie image: falha ao baixar (HTTP {rr.status_code})")
    return rr.content, cost


_KIE_GPT_BASE = "https://api.kie.ai/api/v1/gpt4o-image"
_KIE_CALLBACK_COND = threading.Condition()
_KIE_CALLBACKS: Dict[str, Dict[str, Any]] = {}


def kie_callback_token() -> str:
    """Token não reversível usado apenas na URL pública de callback da Kie."""
    import hashlib
    import hmac
    key = _kie_key()
    if not key:
        return ""
    return hmac.new(key.encode(), b"caripost-kie-callback-v1", hashlib.sha256).hexdigest()


def kie_callback_url() -> str:
    base = (
        (get_setting("render.public_base") or "").strip()
        or (os.environ.get("APP_PUBLIC_URL") or "").strip()
        or "https://caripost.cariap.com.br"
    ).rstrip("/")
    token = kie_callback_token()
    return f"{base}/api/posts/kie-callback?token={token}" if token else ""


def accept_kie_callback(payload: Dict[str, Any]) -> bool:
    """Registra e acorda a thread que aguarda a task. O endpoint responde rápido;
    download/OCR continuam na thread original do render."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    task_id = str(data.get("taskId") or data.get("task_id") or payload.get("taskId") or "").strip()
    if not task_id:
        return False
    with _KIE_CALLBACK_COND:
        _KIE_CALLBACKS[task_id] = payload
        _KIE_CALLBACK_COND.notify_all()
    try:
        import time as _tm
        root = os.path.dirname(os.environ.get("ADULT_META_DB_PATH", "/data/runs.db"))
        path = os.path.join(root, "kie_callbacks.jsonl")
        os.makedirs(root, exist_ok=True)
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        callback_path = os.path.join(root, f"kie_callback_{task_id}.json")
        temp_path = callback_path + f".{os.getpid()}.tmp"
        with open(temp_path, "w") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, callback_path)
        with open(path, "a") as handle:
            handle.write(json.dumps({
                "ts": _tm.time(),
                "task_id": task_id,
                "code": payload.get("code"),
                "result_urls": _kie_result_urls(info)[:4],
            }) + "\n")
    except Exception:
        pass
    return True


def _wait_kie_callback(task_id: str, timeout: float) -> Optional[Dict[str, Any]]:
    import time as _tm
    deadline = _tm.monotonic() + timeout
    root = os.path.dirname(os.environ.get("ADULT_META_DB_PATH", "/data/runs.db"))
    callback_path = os.path.join(root, f"kie_callback_{task_id}.json")
    while _tm.monotonic() < deadline:
        with _KIE_CALLBACK_COND:
            payload = _KIE_CALLBACKS.pop(task_id, None)
            if payload:
                try:
                    os.unlink(callback_path)
                except Exception:
                    pass
                return payload
            _KIE_CALLBACK_COND.wait(timeout=min(1.0, max(0.0, deadline - _tm.monotonic())))
        try:
            with open(callback_path) as handle:
                payload = json.load(handle)
            os.unlink(callback_path)
            return payload if isinstance(payload, dict) else None
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return None


def _kie_ledger(task_id: str, model: str, endpoint: str = "jobs"):
    """LEDGER DURÁVEL de tasks kie (dinheiro do cliente): grava o taskId EM DISCO no momento da criação —
    se o processo morrer/travar/reiniciar antes de baixar o resultado, /api/posts/kie-recover repesca
    o que JÁ FOI PAGO. Nunca mais 'gerou na kie e sumiu na plataforma'."""
    try:
        import json as _json
        import time as _tm
        # no VOLUME /data (junto do runs.db) — /media/_tmp tem varredor de temporários que APAGOU o ledger
        p = os.path.join(os.path.dirname(os.environ.get("ADULT_META_DB_PATH", "/data/runs.db")), "kie_tasks.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as f:
            f.write(_json.dumps({"ts": _tm.time(), "task_id": task_id, "model": model, "endpoint": endpoint}) + "\n")
    except Exception:
        pass


def kie_fetch_result(task_id: str) -> Optional[bytes]:
    """Busca o RESULTADO de uma task kie JÁ CRIADA (market/jobs OU gpt4o-image) e baixa a 1ª imagem.
    None = sem resultado ainda. Usado pelo resgate (/kie-recover)."""
    key = _kie_key()
    if not (key and task_id):
        return None
    url = None
    try:
        d = _kie_record(task_id)
        if (d.get("state") or "").lower() == "success":
            u = _kie_result_urls(d)
            url = u[0] if u else None
    except Exception:
        pass
    if not url:
        try:
            with httpx.Client(timeout=30) as c:
                d2 = ((c.get(_KIE_GPT_BASE + "/record-info", params={"taskId": task_id},
                             headers={"Authorization": "Bearer " + key}).json() or {}).get("data") or {})
            if (d2.get("status") or "").upper() == "SUCCESS":
                url = ((d2.get("response") or {}).get("resultUrls") or [None])[0]
        except Exception:
            pass
    if not url:
        return None
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
        rr = c.get(url)
    return rr.content if (rr.status_code < 400 and rr.content) else None


def generate_image_kie_gpt(prompt: str, size: str = "1024x1536", ref_urls: Optional[List[str]] = None) -> Tuple[bytes, float]:
    """GPT Image via kie (endpoint dedicado /gpt4o-image, pago nos MESMOS créditos kie). size vira ratio
    ('2:3'/'3:2'/'1:1'). ref_urls (PÚBLICAS) entram como filesUrl → serve o Estúdio IA com referências.
    Validado ao vivo 2026-07-17 (t2i e com filesUrl). Retorna (png, 0.0) — custo em créditos."""
    key = _kie_key()
    if not key:
        raise ValueError("kie não configurado (token).")
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except Exception:
        w, h = 1024, 1536
    ratio = "2:3" if h > w else ("3:2" if w > h else "1:1")
    body: Dict[str, Any] = {"prompt": prompt[:4000], "size": ratio}
    callback_url = kie_callback_url()
    if callback_url:
        body["callBackUrl"] = callback_url
    urls = [u for u in (ref_urls or []) if u and str(u).startswith("http")]
    if urls:
        body["filesUrl"] = urls[:5]
    H = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        r = c.post(_KIE_GPT_BASE + "/generate", headers=H, json=body)
    try:
        j = r.json()
    except Exception:
        j = {}
    tid = (j.get("data") or {}).get("taskId")
    if not tid:
        raise ValueError(f"kie gpt-image createTask falhou (HTTP {r.status_code}): {r.text[:180]}")
    _kie_ledger(tid, "chatgpt/gpt-5.4-image-2", "gpt4o-image")
    out_url, _cc = None, None
    completed_without_url = 0
    for _ in range(20):                                    # ~10min; callback imediato + polling de segurança a cada 30s
        callback = _wait_kie_callback(tid, 30.0)
        if callback:
            cb_data = callback.get("data") if isinstance(callback.get("data"), dict) else {}
            cb_info = cb_data.get("info") if isinstance(cb_data.get("info"), dict) else cb_data
            if int(callback.get("code") or 0) == 200:
                out_url = (_kie_result_urls(cb_info) or [None])[0]
                if out_url:
                    break
            else:
                raise ValueError("kie gpt-image falhou: " + str(callback.get("msg") or callback.get("code"))[:150])
        try:
            with httpx.Client(timeout=30) as c:
                resp = c.get(_KIE_GPT_BASE + "/record-info", params={"taskId": tid}, headers=H)
                d = ((resp.json() or {}).get("data") or {})
        except Exception:
            continue
        st = (d.get("status") or "").upper()
        if st == "SUCCESS":
            out_url = (_kie_result_urls(d) or [None])[0]
            _cc = d.get("creditsConsumed") or d.get("creditsUsed")
            if out_url:
                break
            completed_without_url += 1
            if completed_without_url >= 3:
                raise ValueError("kie gpt-image concluiu, mas não publicou a URL do resultado.")
            continue
        if (d.get("errorMessage") or "").strip() or (st and st not in ("GENERATING", "QUEUING")):
            raise ValueError("kie gpt-image falhou: " + (str(d.get("errorMessage") or st))[:150])
    if not out_url:
        raise ValueError("kie gpt-image sem resultado (timeout).")
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
        rr = c.get(out_url)
    if rr.status_code >= 400 or not rr.content:
        raise ValueError(f"kie gpt-image download falhou (HTTP {rr.status_code})")
    return rr.content, _kie_cost_usd("chatgpt/gpt-5.4-image-2", _cc, 8)


# === VÍDEO via gateway OmniRoute (assinaturas do user: GPT/Sora, Gemini/Veo, Antigravity) — custo ~$0.
# id da nossa UI = "omni:" + id real do gateway. (sid_real, nome, qualidade, max_segundos).
CURATED_VIDEO_OMNI = [
    ("chatgpt-web/sora-2-pro", "Sora 2 Pro · GPT (grátis na sua conta)", "Top", 12),
    ("cgpt-web/sora-2-pro",    "Sora 2 Pro · GPT (grátis na sua conta)", "Top", 12),
    ("gemini-web/veo3-pro",    "Veo 3 Pro · Gemini (grátis na sua conta)", "Top", 8),
    ("gweb/veo3-pro",          "Veo 3 Pro · Gemini (grátis na sua conta)", "Top", 8),
    ("veo-free/veo",           "Veo · grátis", "Alta", 8),
    ("veoaifree-web/veo",      "Veo · grátis", "Alta", 8),
    ("veo-free/seedance",      "Seedance · grátis", "Alta", 8),
    ("veoaifree-web/seedance", "Seedance · grátis", "Alta", 8),
]


def omniroute_video_models() -> List[Dict[str, Any]]:
    """Modelos de VÍDEO do gateway OmniRoute (Sora/Veo via assinaturas do user, ~$0). id prefixado 'omni:'.
    Só lista os que o gateway realmente expõe agora (consulta /models). Sem chave/gateway → vazio (não quebra a UI)."""
    key = _omniroute_key()
    if not key:
        return []
    try:
        r = httpx.get(_omniroute_base() + "/models", headers={"Authorization": "Bearer " + key}, timeout=15)
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        avail = {(m.get("id") if isinstance(m, dict) else str(m)) for m in (items or [])}
    except Exception:
        return []
    out, seen = [], set()
    for i, (sid, nm, q, sec) in enumerate(CURATED_VIDEO_OMNI):
        if sid in avail and nm not in seen:          # dedup por nome (mantém o 1º alias disponível)
            seen.add(nm)
            out.append({"id": "omni:" + sid, "name": nm, "quality": q, "price_per_video": 0.0,
                        "price_per_second": 0.0, "max_seconds": sec, "rank": i, "price_source": "free"})
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
                            "provider": "omniroute", "quality": "Top", "price_per_image": 0.0,
                            "price_source": "subscription", "rank": -1, "free": True})
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
                           json={"model": model, "stream": False, "max_tokens": max_tokens, "temperature": 0.2,
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
                 + " (produto/serviço digital). Liste fatos concretos, específicos e recentes, com números quando houver.")
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
    ("gpt-image-2", "GPT Image 2", "OpenAI", "Médio", 0.04),
    ("gpt-image-2-all", "GPT Image 2 All", "OpenAI", "Top", 0.04),
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
    catalog = _cometapi_model_catalog()
    def _row(prefix, cid, nm, fam, tier, p):
        model_id = prefix + cid
        per_request = _cometapi_image_price(catalog.get(cid) or {})
        source = "catalog_api" if per_request > 0 else "fallback"
        price = per_request if per_request > 0 else p
        return {"id": prefix + cid, "name": f"{nm} · {fam} ({tier})", "provider": "cometapi",
                "family": fam, "tier": tier, "quality": tier, "rank": -2,
                **_image_price_fields(model_id, price, source)}
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


# ── ESTÚDIO IA (reference_full): catálogo de modelos ESCOLHÍVEIS por provedor ──────────────────────
# Todos aceitam REFERÊNCIAS (menos o omni text-to-image, marcado). O admin escolhe onde TEM saldo;
# se o escolhido falhar (ex.: conta sem crédito), o motor CAI sozinho pro próximo provedor com chave.
IMAGE_REF_MODELS: List[Dict[str, Any]] = [
    {"id": "openai/gpt-5.4-image-2",                  "name": "gpt-5.4-image-2 — referências fiéis",         "provider": "openrouter", "note": "pago (OpenRouter)"},
    {"id": "kie:google/nano-banana-edit",             "name": "nano-banana-edit — ótimo com texto/realismo", "provider": "kie",        "note": "créditos kie"},
    {"id": "kie:bytedance/seedream-v4-edit",          "name": "seedream-v4-edit — fotorrealista",            "provider": "kie",        "note": "créditos kie"},
    {"id": "cometapi:gemini-3.1-flash-image-preview", "name": "gemini-flash (CometAPI)",                     "provider": "cometapi",   "note": "pago (CometAPI)"},
    {"id": "omni:antigravity/gemini-3.1-flash-image", "name": "gemini-flash (OmniRoute) — SEM referências",  "provider": "omniroute",  "note": "grátis · não usa referências"},
]


def image_ref_models() -> List[Dict[str, Any]]:
    return [dict(m) for m in IMAGE_REF_MODELS]


def get_image_ref_model() -> str:
    """Modelo do ESTÚDIO IA (reference_full) — CONFIGURÁVEL. Default = OpenRouter gpt-5.4-image-2."""
    return (get_setting("image_ref.model") or "openai/gpt-5.4-image-2").strip()


def _iref_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("kie:chatgpt/"): return "kie_gpt"   # endpoint GPT da kie ≠ market (fallback entre eles é desejado)
    if m.startswith("kie:"):      return "kie"
    if m.startswith("cometapi:"): return "cometapi"
    if m.startswith("omni:"):     return "omniroute"
    return "openrouter"


def _iref_openrouter(model: str, prompt: str, ref_images, size: str, quality: str) -> Tuple[bytes, Optional[float]]:
    """Estúdio via OpenRouter /images: input_references tipado (dataURI). Retorna (png, custo)."""
    import base64
    key = _openrouter_key()
    if not key:
        raise ValueError("OpenRouter não configurado (token:openrouter).")
    body: Dict[str, Any] = {"model": model, "prompt": prompt[:4000], "n": 1, "quality": quality, "size": size}
    if ref_images:
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}}
            for b in ref_images[:8] if b
        ]
    last_err = ""
    for _att in range(2):
        try:
            with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as c:
                r = c.post("https://openrouter.ai/api/v1/images",
                           headers={"Authorization": f"Bearer {key}", "content-type": "application/json"}, json=body)
            if r.status_code >= 400:
                try:
                    last_err = f"HTTP {r.status_code}: " + (r.json().get('error', {}).get('message') or r.text[:200])
                except Exception:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code < 500 and r.status_code != 429:
                    break
                continue
            d = r.json()
            item = (d.get("data") or [{}])[0]
            cost = _usage_cost(d) or None
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"]), cost
            url = item.get("image_url") or item.get("url")
            if url:
                with httpx.Client(timeout=60) as c:
                    return c.get(url).content, cost
            last_err = "resposta sem imagem"
        except httpx.HTTPError as e:
            last_err = f"rede/timeout: {str(e)[:120]}"
    raise ValueError(f"OpenRouter: {last_err}")


def _iref_kie_edit(model_id: str, prompt: str, ref_urls: Optional[List[str]]) -> Tuple[bytes, Optional[float]]:
    """Estúdio via kie image-EDIT (nano-banana-edit / seedream-v4-edit): as REFERÊNCIAS entram como
    image_urls (precisam ser PÚBLICAS — o kie baixa). Custo em CRÉDITOS kie → (png, 0.0)."""
    import time as _t
    key = _kie_key()
    urls = [u for u in (ref_urls or []) if u and str(u).startswith("http")]
    if not key:
        raise ValueError("kie não configurado (token).")
    if not urls:
        raise ValueError("kie edit exige referências com URL pública.")
    body = {"model": model_id, "input": {"prompt": prompt[:4000], "image_urls": urls[:5]}}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        r = c.post(_KIE_BASE + "/jobs/createTask",
                   headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    try:
        j = r.json()
    except Exception:
        j = {}
    tid = (j.get("data") or {}).get("taskId")
    if not tid:
        raise ValueError(f"kie createTask falhou (HTTP {r.status_code}): {r.text[:180]}")
    _kie_ledger(tid, model_id, "jobs")
    last, done = {}, False
    for _ in range(200):                                   # ~10min: fila da conta kie estica com telas em paralelo
        _t.sleep(3)
        d = _kie_record(tid)
        st = (d.get("state") or "").lower()
        if st == "success":
            last, done = d, True
            break
        if st == "fail":
            raise ValueError("kie edit falhou: " + str(d.get("failMsg") or "")[:150])
    out = _kie_result_urls(last) if done else []
    if not out:
        raise ValueError("kie edit sem resultado (timeout).")
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
        rr = c.get(out[0])
    if rr.status_code >= 400 or not rr.content:
        raise ValueError(f"kie edit download falhou (HTTP {rr.status_code})")
    return rr.content, _kie_cost_usd(model_id, last.get("creditsConsumed"), 4)


def generate_image_reference_full(prompt: str, ref_images: Optional[List[bytes]] = None,
                                  size: str = "1024x1536", model: Optional[str] = None,
                                  quality: str = "medium",
                                  ref_urls: Optional[List[str]] = None) -> Tuple[bytes, Optional[float]]:
    """ESTÚDIO IA (reference_full): a IA arquiteta a ARTE INTEIRA guiada por REFERÊNCIAS reais (versões da
    logo, artes de referência, foto do influencer, slide anterior). Modelo CONFIGURÁVEL (setting
    image_ref.model). Roteia por PROVEDOR e, se o escolhido falhar (ex.: conta sem saldo), CAI sozinho pro
    próximo provedor com chave — nunca fica preso a um só modelo. Retorna (png, custo)."""
    chosen = (model or get_image_ref_model()).strip()
    # cadeia: ESCOLHIDO primeiro; depois os outros provedores com chave (rede de segurança anti-quebra)
    chain = [chosen]
    if _kie_key():        chain.append("kie:google/nano-banana-edit")
    if _openrouter_key(): chain.append("openai/gpt-5.4-image-2")
    if _cometapi_key():   chain.append("cometapi:gemini-3.1-flash-image-preview")
    if _omniroute_key():  chain.append("omni:antigravity/gemini-3.1-flash-image")
    seen, ordered = set(), []
    for mid in chain:                                      # dedup por MODELO (não por provedor): modelo quebrado
        if mid in seen:                                    # ≠ provedor morto — ex.: seedream-edit falhando não pode
            continue                                       # descartar o nano-banana como reserva do MESMO kie
        seen.add(mid); ordered.append(mid)
    errs = []
    for mid in ordered:
        prov = _iref_provider(mid)
        try:
            if prov == "kie_gpt":
                return generate_image_kie_gpt(prompt, size, ref_urls)
            if prov == "kie":
                return _iref_kie_edit(mid.split(":", 1)[1], prompt, ref_urls)
            if prov == "cometapi":
                base = next((b for b in (ref_images or []) if b), None)
                if not base:
                    raise ValueError("cometapi exige ao menos 1 referência em bytes.")
                return generate_image_with_person(base, prompt, mid.split(":", 1)[1])
            if prov == "omniroute":
                return generate_image_omniroute(mid.split(":", 1)[1], prompt, size)
            return _iref_openrouter(mid, prompt, ref_images, size, quality)   # openrouter (default)
        except Exception as e:
            errs.append(f"{prov}: {str(e)[:110]}")
            continue
    raise ValueError("Estúdio IA falhou em todos os provedores (" + " | ".join(errs) + ")")


def generate_image_person_kie(person_url: str, prompt: str, model: str = "google/nano-banana-edit") -> Tuple[bytes, float]:
    """COMPÕE a pessoa real (foto PÚBLICA do influencer) numa cena via kie image-EDIT (nano-banana-edit /
    seedream-v4-edit). Preserva rosto/expressão (é edição da foto, não redesenho). person_url TEM que ser
    público (o kie baixa). Custo em CRÉDITOS kie → retorna (png, 0.0). Levanta em erro (chamador faz fallback)."""
    import time as _t
    key = _kie_key()
    if not key or not person_url:
        raise ValueError("kie/URL da foto ausente.")
    body = {"model": model, "input": {"prompt": prompt[:4000], "image_urls": [person_url]}}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        r = c.post(_KIE_BASE + "/jobs/createTask",
                   headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, json=body)
    j = {}
    try:
        j = r.json()
    except Exception:
        pass
    tid = (j.get("data") or {}).get("taskId")
    if not tid:
        raise ValueError(f"kie edit createTask falhou (HTTP {r.status_code}): {r.text[:180]}")
    last: Dict[str, Any] = {}
    done = False
    for _ in range(90):                                    # ~4.5min: edit (nano-banana) varia bastante (30s–3min)
        _t.sleep(3)
        d = _kie_record(tid)
        st = (d.get("state") or "").lower()
        if st == "success":
            last = d
            done = True
            break
        if st == "fail":
            raise ValueError("kie edit falhou: " + str(d.get("failMsg") or "")[:150])
    urls = _kie_result_urls(last) if done else []
    if not urls:
        raise ValueError("kie edit sem resultado (não concluiu a tempo).")
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
        rr = c.get(urls[0])
    if rr.status_code >= 400 or not rr.content:
        raise ValueError(f"kie edit download falhou (HTTP {rr.status_code})")
    return rr.content, _kie_cost_usd(model, last.get("creditsConsumed"), 4)


def compose_person_scene(person_bytes: bytes, prompt: str, person_url: str = "") -> Tuple[bytes, float]:
    """Compõe a pessoa REAL do influencer numa cena, preservando rosto. Usa o provedor que FUNCIONA:
    kie image-edit (foto pública, créditos) → CometAPI nano-banana (bytes). Como o CometAPI pode estar
    SEM SALDO, o kie é o caminho primário quando há URL pública."""
    errs = []
    if person_url and _kie_key():
        try:
            return generate_image_person_kie(person_url, prompt)
        except Exception as e:
            errs.append("kie: " + str(e)[:90])
    try:
        return generate_image_with_person(person_bytes, prompt)
    except Exception as e:
        errs.append("comet: " + str(e)[:90])
    raise ValueError("compose_person falhou (" + " | ".join(errs) + ")")


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
    if _omniroute_key():    # ASSINATURA (custo ~$0) PRIMEIRO — visão validada: Claude Haiku responde em ~1s
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():   # pago, só fallback
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():     # último recurso (sem saldo hoje)
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 4, "temperature": 0, "messages": [{"role": "user", "content": parts}]})
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
    if _omniroute_key():    # ASSINATURA (custo ~$0) PRIMEIRO — visão validada: Claude Haiku responde em ~1s
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():   # pago, só fallback
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():     # último recurso (sem saldo hoje)
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 4, "temperature": 0, "messages": [{"role": "user", "content": parts}]})
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


def _image_generation_fallback_cost(real_model: str) -> float:
    real = (real_model or "").strip()
    for cid, _nm, _fam, _tier, p in (_CURATED_COMETAPI + _CURATED_COMETAPI_GEMINI):
        if real == cid:
            return _safe_float(p) or 0.06
    return _OPENAI_IMG_COST.get(real, 0.06)


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
            d = r.json()
            item = (d.get("data") or [{}])[0]
            cost = _usage_cost(d) or _image_generation_fallback_cost(real)
            b64 = item.get("b64_json")
            if b64:
                return base64.b64decode(b64), cost
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
    d = r.json()
    item = (d.get("data") or [{}])[0]
    cost = _usage_cost(d) or _image_generation_fallback_cost(real)
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
    return [{"id": s, "name": n, "quality": q, "rank": -2, **_image_price_fields(s, p, "fallback")}
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
    return [{"id": s, "name": n, "quality": q, "rank": -3, **_image_price_fields(s, p, "fallback")}
            for (s, n, q, p) in _CURATED_PIAPI]


def generate_image_openrouter(model: str, prompt: str, size: str = "1024x1024", ref_images: Optional[List[bytes]] = None):
    """Generate via OpenRouter Image API. Returns (png_bytes, cost_usd).

    Payload compat: modelos diferem no que aceitam. Alguns preferem aspect_ratio+
    resolution; outros (seedream-4.5/doubao) EXIGEM um `size` grande em pixel
    (>= 3.686.400 px) e rejeitam aspecto pequeno. Em vez de morrer no 1º HTTP 400
    de schema, escalonamos o payload: (1) aspect_ratio+resolution → (2) size grande
    no mesmo aspecto → (3) só model+prompt (default do modelo). Só troca de variante
    em erro de schema (4xx); 5xx/429 repete a mesma variante.
    """
    import base64
    import math as _m
    from math import gcd
    key = _openrouter_key()
    if not key:
        raise ValueError("OpenRouter não configurado (token:openrouter).")

    base_body: Dict[str, Any] = {"model": model, "prompt": prompt[:4000], "n": 1}
    if ref_images:
        base_body["input_references"] = [
            "data:image/png;base64," + base64.b64encode(b).decode() for b in ref_images[:3] if b
        ]

    variants: List[Dict[str, Any]] = []
    w = h = 0
    if size and "x" in size:
        try:
            w, h = [int(v) for v in size.split("x")[:2]]
        except Exception:
            w = h = 0
    if w > 0 and h > 0:
        g = gcd(w, h) or 1
        aspect = f"{w // g}:{h // g}"                              # ex.: 1080x1350 -> "4:5"
        variants.append({**base_body, "aspect_ratio": aspect, "resolution": "2K" if max(w, h) >= 1200 else "1K"})
        # size explícito escalado p/ >= 4.2MP no MESMO aspecto (satisfaz o mínimo do seedream/doubao)
        MIN_PX = 4_200_000
        scale = _m.sqrt(MIN_PX / float(w * h)) if (w * h) else 1.0
        scale = max(1.0, scale)
        bw = max(8, int(round((w * scale) / 8.0)) * 8)
        bh = max(8, int(round((h * scale) / 8.0)) * 8)
        variants.append({**base_body, "size": f"{bw}x{bh}"})
    variants.append(dict(base_body))                              # último recurso: default do modelo

    last_err = ""
    for body in variants:
        for attempt in range(2):                   # retry transitório dentro da mesma variante
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
                    if res.status_code >= 500 or res.status_code == 429:
                        continue                   # transitório → repete MESMA variante
                    break                          # 4xx schema → próxima variante (payload diferente)
                d = res.json()
                item = (d.get("data") or [{}])[0]
                cost = _usage_cost(d) or None
                if item.get("b64_json"):
                    return base64.b64decode(item["b64_json"]), cost
                url = item.get("image_url") or item.get("url")
                if url:
                    with httpx.Client(timeout=60) as client:
                        return client.get(url).content, cost
                last_err = "resposta sem imagem"
                break                              # sem imagem → próxima variante
            except httpx.HTTPError as e:
                last_err = f"rede/timeout: {str(e)[:120]}"
                continue
    raise ValueError(f"Falha OpenRouter imagem ({last_err}).")


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
    if _omniroute_key():    # ASSINATURA (custo ~$0) PRIMEIRO — visão validada: Claude Haiku responde em ~1s
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():   # pago, só fallback
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():     # último recurso (sem saldo hoje)
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 4, "temperature": 0, "messages": msgs})
            if r.status_code >= 400:
                continue   # provedor sem saldo/erro → tenta o próximo da cadeia
            txt = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip().lower()
            side = "left" if "left" in txt else ("right" if "right" in txt else ("none" if "none" in txt else ""))
            if side:
                return side, 0.004
        except Exception:
            continue
    return "", 0.0


def vision_read_text(img_bytes: bytes) -> Tuple[str, float]:
    """JUIZ DE TEXTO: transcreve VERBATIM todo o texto que a IA renderizou na arte (mesmo com erro), pra
    conferir se saiu quebrado. Retorna (texto_lido, custo). Erro/sem imagem → ('', 0.0). Mesma cadeia de
    visão do vision_clear_side (assinatura ~$0 primeiro)."""
    import base64
    if not img_bytes:
        return "", 0.0
    b64 = base64.b64encode(img_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": ("Transcreva EXATAMENTE todo o texto escrito nesta imagem, palavra por palavra, "
            "do jeito que está (mesmo com erro de ortografia ou letra faltando). NÃO descreva a imagem, NÃO "
            "corrija nada, NÃO explique — responda só o texto visível, separando os blocos por espaço.")},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    chain = []
    if _omniroute_key():
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 400, "temperature": 0, "messages": msgs})
            if r.status_code >= 400:
                continue
            txt = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            _low = txt.lower()
            if txt and not any(x in _low for x in (           # RECUSA do modelo ≠ transcrição → tenta o próximo
                    "can't assist", "cannot assist", "can't help", "i'm sorry", "i am sorry",
                    "unable to", "não posso", "nao posso", "desculpe")):
                return txt, 0.004
        except Exception:
            continue
    return "", 0.0


def _norm_word(x: str) -> str:
    """Normaliza p/ comparação: ascii minúsculo, só [a-z0-9] (foca no QUEBRADO, não no acento)."""
    import re
    import unicodedata
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", x)


def _expected_word_map(expected: List[str]) -> Dict[str, str]:
    """Mapa palavra_normalizada → grafia ORIGINAL (com acento) do briefing."""
    orig: Dict[str, str] = {}
    for phrase in (expected or []):
        for w in phrase.split():
            wc = w.strip('.,:;!?"()«»–—')
            k = _norm_word(wc)
            if k and k not in orig:
                orig[k] = wc
    return orig


def text_render_issues(rendered: str, expected: List[str]) -> List[str]:
    """Palavras do BRIEFING (esperadas) que NÃO aparecem EXATAS na leitura da arte. SEM fuzzy de
    aprovação: calibração real (v1.27.92→93) provou que erro PINTADO de 1 letra ('segurença',
    'bacio', 'portóflio') cai na faixa 0.80-0.92 de similaridade — a MESMA do ruído de leitura do
    OCR — então similaridade não separa os dois; quem separa é a arbitragem letra-a-letra
    (judge_art_text). Fluxo contínuo cobre palavra que o leitor dividiu/colou ('bai xo').
    Vazio = texto ok. `rendered` vazio (leitor falhou) → [] (quem decide é o judge)."""
    import re
    import unicodedata
    if not (rendered or "").strip():
        return []

    def _n(x: str) -> str:
        x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", " ", x)

    toks = _n(rendered).split()
    stream = "".join(toks)                          # fluxo sem espaços: acha palavra que o leitor dividiu/colou
    miss, seen = [], set()
    for phrase in (expected or []):
        for w in _n(phrase).split():
            if len(w) >= 5 and w not in seen:      # só palavras "de conteúdo" (>=5) — evita falso positivo em 'de/no/e'
                seen.add(w)
                if w not in stream:
                    miss.append(w)
    return miss


def vision_spell_words(img_bytes: bytes, words: List[str]) -> Tuple[Dict[str, str], float]:
    """ARBITRAGEM letra-a-letra: pra cada palavra SUSPEITA (OCR não achou exata), a visão copia COMO
    ELA ESTÁ PINTADA na arte, letra por letra — e a comparação acontece em CÓDIGO. Transcrição livre
    não serve: o modelo 'conserta' o typo ao ler ('entrenitemento'→'entretenimento') e aprova arte
    quebrada. Retorna ({palavra_pedida: 'l-e-t-r-a-s' | 'AUSENTE'}, custo). {} = visão indisponível."""
    import base64
    import json as _json
    import re as _re
    if not (img_bytes and words):
        return {}, 0.0
    b64 = base64.b64encode(img_bytes).decode()
    lista = "\n".join("- " + w for w in words[:8])
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": (
            "Isto é um TESTE DE ERRO DE PINTURA: as palavras da lista abaixo podem estar pintadas na arte "
            "COM ERRO DE GRAFIA, e sua tarefa é COPIAR O ERRO — se você 'corrigir' a grafia, o teste "
            "FALHA. Para CADA palavra da lista, encontre na arte a palavra IGUAL ou mais PARECIDA e copie "
            "EXATAMENTE como está pintada, LETRA POR LETRA separadas por hífen (é PROIBIDO corrigir, "
            "completar ou adivinhar). Se não existir nada parecido pintado, responda AUSENTE.\n"
            "Responda SÓ um JSON, sem explicação: {\"palavra pedida\": \"l-e-t-r-a-s\" ou \"AUSENTE\"}.\n"
            "Palavras:\n" + lista)},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    chain = []
    if _omniroute_key():    # ASSINATURA (custo ~$0) PRIMEIRO — visão validada: Claude Haiku responde em ~1s
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():   # pago, só fallback
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 300, "temperature": 0, "messages": msgs})
            if r.status_code >= 400:
                continue
            txt = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            m = _re.search(r"\{.*\}", txt, _re.S)
            if not m:
                continue
            try:
                data = _json.loads(m.group(0))
            except Exception:
                continue
            if isinstance(data, dict) and data:
                out = {}
                norm_map = {_norm_word(k): v for k, v in data.items() if isinstance(v, str)}
                for w in words:
                    v = data.get(w) or norm_map.get(_norm_word(w)) or ""
                    out[w] = (v or "").strip()
                return out, 0.004
        except Exception:
            continue
    return {}, 0.0


def judge_art_text(img_bytes: bytes, expected: List[str]) -> Tuple[List[str], float]:
    """JUIZ DE TEXTO — 3 instâncias, FALHA FECHADA:
    1ª OCR LOCAL (grátis, determinístico, nunca recusa): toda palavra EXATA → aprovado, custo 0.
    2ª suspeita → ARBITRAGEM POR RECORTE (_ocr_crop_confirm, também local/determinística): recorta a
       região da palavra, amplia 4x, relê. Releu exata → ruído de leitura, passa; diferente → QUEBROU.
       Quem APROVA nunca é LLM (visão auto-corrige typo — provado em prod na v1.27.93).
    3ª só palavra que o OCR NEM VIU (região estilizada) → visão soletra e o código compara.
    Visão indisponível/recusou → suspeita CONTA COMO QUEBRA (regenera) — o juiz NUNCA passa cego.
    Tesseract indisponível → transcrição livre da visão decide (legado). Retorna (quebradas, custo)."""
    if not expected:
        return [], 0.0
    ocr, entries, variants = _ocr_scan(img_bytes, expect=expected)
    if not ocr:                                     # sem tesseract → melhor esforço com visão livre
        rendered, vc = vision_read_text(img_bytes)
        return text_render_issues(rendered, expected), vc
    suspects = text_render_issues(ocr, expected)
    if not suspects:
        return [], 0.0
    orig = _expected_word_map(expected)
    broken, unknown = [], []
    for w in suspects:
        verdict = _ocr_crop_confirm(entries, variants, w)
        if verdict == "ok":
            continue
        (broken if verdict == "broken" else unknown).append(w)
    vc = 0.0
    if unknown:
        spelled, vc = vision_spell_words(img_bytes, [orig.get(w, w) for w in unknown])
        for w in unknown:
            got = ((spelled.get(orig.get(w, w)) or spelled.get(w) or "") if spelled else "").strip()
            if (not got) or got.upper().startswith("AUSENTE") \
                    or _norm_word(got.replace("-", "").replace(" ", "")) != w:
                broken.append(w)                    # inclui visão fora do ar → FALHA FECHADA
    return broken, vc


_OCR_GATE = None


def _ocr_gate():
    """PORTÃO GLOBAL de OCR: com telas em paralelo, N juízes × 4 workers = 16 tesseracts nos 8 núcleos →
    CPU 100% e TUDO rasteja (arte pronta da kie ficava minutos presa no juiz). Máx. simultâneo no
    processo inteiro = metade dos núcleos (2–4); os juízes se revezam e cada passe volta a ser rápido."""
    global _OCR_GATE
    if _OCR_GATE is None:
        import os as _os
        import threading
        _OCR_GATE = threading.BoundedSemaphore(max(2, min(4, (_os.cpu_count() or 4) // 2)))
    return _OCR_GATE


def _ocr_scan(img_bytes: bytes, min_conf: float = 40.0, expect: Optional[List[str]] = None):
    """Varre a arte com Tesseract em MÚLTIPLOS pré-processamentos (cinza, invertido, binarizados 150/200
    ± invertidos, canais R/B, upscale) — texto sobre foto/pílula colorida some num passe único.
    VELOCIDADE: os passes rodam em PARALELO (tesseract é subprocesso, 4 workers) e há SAÍDA RÁPIDA —
    se os 2 passes baratos já leram TODAS as palavras esperadas (`expect`), não roda o resto (arte
    limpa julga em segundos; antes eram ~30-40s por arte). Devolve (tokens_str,
    entradas[(texto, conf, box, idx_variante)], variantes). ('', [], []) = tesseract indisponível."""
    if not img_bytes:
        return "", [], []
    try:
        import io as _io
        import pytesseract
        from concurrent.futures import ThreadPoolExecutor
        from PIL import Image, ImageOps
        rgb = Image.open(_io.BytesIO(img_bytes)).convert("RGB")
        base = rgb.convert("L")
        _r, _g, _b2 = rgb.split()
        _bins = {}
        for th in (150, 200):
            _bins[th] = base.point(lambda p, t=th: 255 if p > t else 0)
        # ORDEM POR UTILIDADE (o exit antecipado corta a cauda): cinza/invertido leem a maior parte;
        # binarizado 200 pega texto branco em pílula colorida; canal AZUL pega texto laranja (vira preto,
        # contraste alto — no cinza some); o resto é cauda de recall.
        variants = [base, ImageOps.invert(base), _bins[200], ImageOps.invert(_bins[200]),
                    _b2, ImageOps.invert(_b2), _bins[150], ImageOps.invert(_bins[150]), _r]
        # (sem passe 2x: tesseract em 2048x3072 é brutal em CPU e toda quebra real foi pega em resolução nativa)

        def _pass(v):
            for lang in ("por", None):              # só 'por' (metade do tempo de 'por+eng'; lê nomes EN bem)
                try:
                    kw = {"lang": lang} if lang else {}
                    with _ocr_gate():               # portão GLOBAL: não satura a CPU com juízes paralelos
                        return pytesseract.image_to_data(v, output_type=pytesseract.Output.DICT, **kw)
                except Exception:
                    continue
            return None

        toks: set = set()
        entries = []

        def _collect(vi, data):
            if not data:
                return
            for j in range(len(data.get("text") or [])):
                t = (data["text"][j] or "").strip()
                try:
                    conf = float(data["conf"][j])
                except Exception:
                    conf = -1.0
                if t and conf >= min_conf:
                    toks.add(t)
                    entries.append((t, conf, (data["left"][j], data["top"][j],
                                              data["width"][j], data["height"][j]), vi))

        from concurrent.futures import as_completed
        ex = ThreadPoolExecutor(max_workers=4)
        try:
            futs = {ex.submit(_pass, v): vi for vi, v in enumerate(variants)}
            for f in as_completed(futs):
                _collect(futs[f], f.result())
                if expect and toks and not text_render_issues(" ".join(toks), expect):
                    break                           # SAÍDA RÁPIDA: já leu TODAS as palavras esperadas
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return " ".join(sorted(toks)), entries, variants
    except Exception:
        return "", [], []


def ocr_read_text(img_bytes: bytes, min_conf: float = 40.0) -> str:
    """JUIZ OCR LOCAL (Tesseract): lê o texto renderizado na arte SEM IA de visão — grátis, determinístico,
    NUNCA recusa e NUNCA fica sem saldo. Junta os tokens de todos os passes (o juiz só checa PRESENÇA)."""
    return _ocr_scan(img_bytes, min_conf)[0]


def _ocr_crop_confirm(entries, variants, word_norm: str) -> str:
    """ARBITRAGEM DETERMINÍSTICA — SEM IA, imune a auto-correção (calibração v1.27.93: a visão, mesmo
    soletrando letra a letra, 'conserta' o typo pintado e aprova arte quebrada; LLM não pode ser o
    árbitro que APROVA). Pega os tokens do OCR mais parecidos com a palavra suspeita, RECORTA a região
    na arte, amplia 4x e RELÊ:
      releu a palavra EXATA → 'ok' (era ruído de leitura do passe cheio);
      releu e continua diferente → 'broken' (está pintada errada MESMO);
      nenhum token parecido (OCR cego ali, ex.: pílula estilizada) → 'unknown' (visão decide)."""
    from difflib import SequenceMatcher
    import pytesseract
    from PIL import ImageOps
    cands = []
    for t, conf, box, vi in entries:
        r = SequenceMatcher(None, _norm_word(t), word_norm).ratio()
        if r >= 0.7:                                 # só candidato FORTE (versão mutilada da palavra) pode
            cands.append((r, box, vi))               # condenar; parecido-fraco = outra palavra/região errada
    if not cands:
        return "unknown"                             # OCR não viu a palavra nem mutilada → visão decide
    cands.sort(key=lambda x: -x[0])
    for _r, (l, top, w, h), vi in cands[:3]:
        img = variants[vi]
        pad = max(8, int(h * 1.2))
        crop = img.crop((max(0, l - pad), max(0, top - int(h * 0.6)),
                         min(img.width, l + w + pad), min(img.height, top + h + int(h * 0.6))))
        if crop.width < 4 or crop.height < 4:
            continue
        crop = crop.resize((crop.width * 4, crop.height * 4))
        for c in (crop, ImageOps.invert(crop)):
            txt = ""
            for lang in ("por", None):
                try:
                    kw = {"lang": lang} if lang else {}
                    with _ocr_gate():               # mesmo portão global do _ocr_scan
                        txt = pytesseract.image_to_string(c, config="--psm 7", **kw)
                    break
                except Exception:
                    continue
            stream = "".join(_norm_word(x) for x in (txt or "").split())
            if word_norm in stream:
                return "ok"
    return "broken"


def text_fix_feedback(miss: List[str], expected: List[str]) -> str:
    """Instrução de CORREÇÃO pro RETRY da arte: mapeia a palavra quebrada (normalizada) de volta pra
    grafia ORIGINAL (com acento) e soletra letra a letra — a regeração converge no erro em vez de
    repetir a mesma moeda-ao-ar. Vazio se nada quebrou."""
    if not miss:
        return ""
    orig = _expected_word_map(expected)
    parts = []
    for m in miss[:4]:
        w = orig.get(m, m)
        parts.append("«" + w + "» (soletrando: " + "-".join(list(w.upper())) + ")")
    return ("\nCORREÇÃO OBRIGATÓRIA: na tentativa anterior estas palavras saíram ERRADAS/quebradas na arte: "
            + "; ".join(parts) + ". Refaça a arte escrevendo cada uma EXATAMENTE com essa grafia, letra por "
            "letra, sem trocar, omitir nem inventar letras.")


def vision_product_facts(img_bytes: bytes) -> Tuple[str, float]:
    """VISÃO do PRODUTO (Fase 2): descreve os FATOS VISUAIS IMUTÁVEIS do item da foto (cor, formato,
    material/acabamento, proporção, detalhes marcantes) p/ ancorar a CENA e a NARRAÇÃO no produto REAL —
    NÃO inventa marca/texto/preço/função, SÓ o que vê. Retorna (fatos, custo_usd). Erro/sem imagem → ('', 0.0).
    Transborda CometAPI → OpenRouter (mesmo gpt-4o)."""
    import base64
    if not img_bytes:
        return "", 0.0
    b64 = base64.b64encode(img_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": ("Descreva em PT-BR, em no MÁXIMO 60 palavras, os FATOS VISUAIS do produto/objeto "
            "principal desta imagem que NÃO podem mudar num anúncio: cor(es), formato, material/acabamento, proporção "
            "e detalhes marcantes. SÓ o que você vê — NÃO invente marca, texto, número, preço nem função. "
            "Se não houver um produto/objeto claro, responda apenas 'NENHUM'.")},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    chain = []
    if _omniroute_key():    # ASSINATURA (custo ~$0) PRIMEIRO — visão validada: Claude Haiku responde em ~1s
        chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))
    if _openrouter_key():   # pago, só fallback
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    if _cometapi_key():     # último recurso (sem saldo hoje)
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    for base, key, model in chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": model, "stream": False, "max_tokens": 180, "temperature": 0.1, "messages": msgs})
            if r.status_code >= 400:
                continue
            txt = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
            if txt and "NENHUM" not in txt.upper()[:12]:
                return txt[:600], 0.005
        except Exception:
            continue
    return "", 0.0


# ── TRANSBORDO INTELIGENTE de imagem (anti-"editorial em tudo") ───────────────
def image_models_registry() -> List[Dict[str, Any]]:
    """Universo de modelos de imagem disponíveis (id, provider, tier, price) — fonte p/ achar equivalentes."""
    out: List[Dict[str, Any]] = []
    for lst, p in ((omniroute_image_models(), "omniroute"), (cometapi_image_models(), "cometapi"),
                   (piapi_image_models(), "piapi"), (openrouter_image_models(), "openrouter"),
                   (kie_image_models(), "kie")):
        for m in (lst or []):
            m.setdefault("provider", p)
            out.append(m)
    return out


def _model_provider(model_id: str) -> str:
    """Provedor de um id de modelo. cometapi: e cometapi-gemini: contam como 'cometapi' (MESMA conta/saldo).
    PiAPI tem DUAS carteiras separadas (LLM API em $ vs créditos da Task API) → 'piapi_llm' e 'piapi'
    são provedores distintos no transbordo: uma carteira vazia não mata a outra."""
    ml = (model_id or "").lower()
    if ml.startswith("omni:"):
        return "omniroute"
    if ml.startswith("kie:"):
        return "kie"
    if ml.startswith("cometapi:") or ml.startswith("cometapi-gemini:"):
        return "cometapi"
    if ml.startswith("piapi:"):
        _, _, kind = _PIAPI_MODELS.get(ml.split(":", 1)[1], ("", "", "gemini"))
        return "piapi_llm" if kind == "openai" else "piapi"
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
        pid = _model_provider(m.get("id", ""))   # SEMPRE pela carteira real (piapi_llm ≠ piapi, kie ≠ openrouter)
        by_prov.setdefault(pid, []).append(m.get("id"))
    preq = _model_provider(model_id)
    chain = [model_id]
    for mid in by_prov.get(preq, []):           # +1 do mesmo provedor (caso o modelo esteja quebrado, não o provedor)
        if mid and mid != model_id:
            chain.append(mid)
            break
    for p in ("omniroute", "kie", "piapi", "piapi_llm", "openrouter", "cometapi"):   # melhor de cada OUTRO provedor; grátis 1º
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
    if not model_override:                       # sem override → o modelo da CONFIG entra na MESMA cadeia
        try:                                     # de transbordo (default quebrado não pode parar a geração,
            model_override = (get_image_config() or {}).get("model") or ""   # ex.: kie/imagen4 morto no servidor)
        except Exception:
            model_override = ""
        if not model_override:
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
                    # motivo REAL junto (ex.: '剩余额度: $-0.007') — sem isso o usuário acha que o app quebrou
                    errors.append(f"{cand}: provedor sem saldo/cota — {es[:90]}")
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

    def _ret(img: bytes, cost: Any, used_model: str):
        val = _safe_float(cost)
        if val > 0:
            _remember_image_price(used_model, val)
            return img, val, used_model
        return img, cost, used_model

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
        elif ml.startswith("kie:"):
            provider = "kie"
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
    if model and str(model).lower().startswith("kie:"):
        provider = "kie"
    # Default to OpenRouter (OpenAI is being retired).
    if not model:
        model = "google/gemini-2.5-flash-image"
        provider = "openrouter"
    if provider == "kie":
        b, cost = generate_image_kie(model, prompt, size)
        return _ret(b, cost, model)
    if provider == "omniroute":
        real = model.split(":", 1)[1] if str(model).lower().startswith("omni:") else model
        try:
            b, cost = generate_image_omniroute(real, prompt, size)
            return _ret(b, cost, model)
        except Exception as oe:
            m = str(oe).lower()
            if any(x in m for x in ("429", "usage_limit", "limit reached", "quota", "exhaust", "rate limit")):
                # Cota grátis da assinatura acabou → fallback pago (mesma família, ~$0.04).
                fb = "google/gemini-2.5-flash-image"
                b, cost = generate_image_openrouter(fb, prompt, size, ref_images)
                _remember_image_price(fb, cost)
                return b, (_safe_float(cost) or cost), fb + " (fallback pago)"
            raise
    if provider == "openai_direct":
        b, cost = generate_image_openai_direct(model, prompt, size, ref_urls)
        return _ret(b, cost, model)
    if provider == "piapi":
        b, cost = generate_image_piapi(model, prompt, size, ref_urls)
        return _ret(b, cost, model)
    if provider == "cometapi":
        real = model.split(":", 1)[1] if str(model).lower().startswith("cometapi:") else model
        b, cost = generate_image_openai_direct(real, prompt, size, ref_urls,
                                               base="https://api.cometapi.com/v1", key=_cometapi_key())
        return _ret(b, cost, model)
    if provider == "cometapi_gemini":
        b, cost = generate_image_cometapi_gemini(model, prompt)
        return _ret(b, cost, model)
    if provider == "reve":
        b, cost = generate_image_reve(prompt, size)
        return _ret(b, cost, model)
    if provider == "openrouter":
        b, cost = generate_image_openrouter(model, prompt, size, ref_images)
        return _ret(b, cost, model)
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
    composition = {
        0: "COMPOSIÇÃO: assunto principal (pessoa/dispositivo) à DIREITA; deixe a METADE ESQUERDA limpa e lisa.",
        1: "COMPOSIÇÃO: assunto principal à ESQUERDA; deixe a METADE DIREITA limpa e lisa.",
        2: "COMPOSIÇÃO: assunto principal no TOPO/centro, bem enquadrado; deixe a METADE INFERIOR limpa.",
        3: "COMPOSIÇÃO: cena cinematográfica com profundidade (o sistema escurece a parte de baixo); pode preencher o quadro.",
    }.get(int(variant) % 4, "COMPOSIÇÃO: assunto à direita, metade esquerda limpa.")
    rules = ((company.get("brand_kit") or {}).get("client_rules") or "").strip()
    cfg = (creative_cfg(company).get("image") or {})
    color = (((company.get("brand_kit") or {}).get("colors") or {}).get("primary")
             or ((company.get("brand_kit") or {}).get("colors") or {}).get("accent")
             or "#ED5E1F")
    vals = {
        "company": name,
        "theme": theme or "",
        "title": head,
        "target_product": tgt,
        "focus": foco,
        "visual": scene,
        "composition": composition,
        "refs_rule": "Siga o ESTILO/clima/paleta das imagens de referência fornecidas." if has_refs else "",
        "color": color,
        "client_rules": ("REGRAS DESTE CLIENTE (correções que ele já pediu — NUNCA repita estes erros):\n" + rules) if rules else "",
    }
    vals["brand_fix"] = _render_prompt_template(cfg.get("brand_fix") or IMAGE_GEN["brand_fix"], vals)
    vals["system_prompt"] = _render_prompt_template(cfg.get("system_prompt") or IMAGE_GEN["system_prompt"], vals)
    return _render_prompt_template(cfg.get("scene_template") or IMAGE_GEN["scene_template"], vals)


def get_video_config(model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Config de geração de vídeo CIENTE DO PROVEDOR (openai/openrouter/cometapi): chave + base_url + modelo.
    Provedor vem de video.provider (setado no seletor) ou é derivado do id do modelo.
    ``model_override`` torna preflight/geração independentes do default global."""
    model = (model_override or get_setting("video.model") or "").strip()
    provider = "" if model_override else (get_setting("video.provider") or "").strip()
    if not provider:
        provider = ("kie" if model.startswith("kie:")
                    else "omniroute" if model.startswith("omni:")
                    else "cometapi" if model.startswith("cometapi:")
                    else ("openrouter" if "/" in model else "openai"))
    if provider == "kie" or model.startswith("kie:"):            # kie.ai direto (async createTask) — pago em créditos
        key = _kie_key()
        if not key:
            return None
        return {"provider": "kie", "apiKey": key,
                "model": model[len("kie:"):] if model.startswith("kie:") else model,
                "base": _KIE_BASE}
    if provider == "omniroute" or model.startswith("omni:"):     # gateway das assinaturas (Sora/Veo) — ~$0
        key = _omniroute_key()
        if not key:
            return None
        return {"provider": "omniroute", "apiKey": key,
                "model": model[len("omni:"):] if model.startswith("omni:") else model,
                "base": _omniroute_base()}
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
    if mid.startswith("kie:"):
        e = _KIE_BY_MODEL.get(mid[len("kie:"):])
        return e[3] if e else 8
    if mid.startswith("omni:"):
        oraw = mid[len("omni:"):]
        for sid, nm, q, sec in CURATED_VIDEO_OMNI:
            if oraw == sid:
                return sec
        return 8
    for s, n, q, p, sec in CURATED_VIDEO:
        if mid in (s, n):
            return sec
    for s, n, q, p, sec in CURATED_VIDEO_COMET:
        if mid == ("cometapi:" + s) or raw in (s, n):
            return sec
    return 8


def video_scene_count(target_seconds: int, max_seconds: int, cap: int = 8,
                       target_per: int = 0, ai_count: int = 0) -> int:
    """Quantas cenas cobrem a duração-alvo. Respeita o nº que a IA gerou (ai_count) quando houver;
    senão usa target_per (segundos/cena sugeridos pelo usuário) em vez do máx do modelo — assim 15s
    pede ~3 cenas (5s cada) e não 2 (8s cada). Teto = cap (controle de custo)."""
    import math
    t = max(1, int(target_seconds or 8))
    if ai_count > 0:
        return max(1, min(cap, ai_count))
    step = max(1, int(target_per or max(4, t // 3)))           # sem hint → ~3 cenas por vídeo
    return max(1, min(cap, math.ceil(t / step)))


def video_segment_plan(target_seconds: int, max_seconds: int, ai_count: int,
                       cap: int = 8, min_clip: int = 4) -> Tuple[int, List[int]]:
    """Plano de cenas RESPEITANDO quantas cenas a IA realmente gerou (ai_count), dentro dos limites:
    cobre a duração travada (mín = ai_count quando > 0, senão ceil(t/máx)), não estoura o custo (cap) nem faz
    clipe curto demais (min_clip). Devolve (nº_de_cenas, lista_de_segundos_por_clipe) somando ≈ duração travada —
    a lista (não um 'per' único) é o que impede o bug '15s viram 24s e a 3ª cena some'. target<=0 (livre) →
    nº = o que a IA fez, segs = [mx]*n."""
    import math
    mx = max(1, int(max_seconds or 8))
    ai = max(0, int(ai_count or 0))
    t = int(target_seconds or 0)
    if t <= 0:                                              # livre → segue a IA (1..cap)
        return (max(1, min(cap, ai or 1)), [mx] * max(1, min(cap, ai or 1)))
    n_min = max(1, ai) if ai > 0 else max(1, math.ceil(t / mx))   # respeita o roteiro quando a IA já gerou cenas
    n_max = max(n_min, min(cap, max(1, t // max(1, min_clip))))
    k = max(n_min, min(ai if ai > 0 else n_min, n_max))
    # distribuição não-uniforme: base = t//k, sobra repartida nos primeiros clipes; cada clipe dentro de [1, mx]
    base, rest = divmod(max(1, t), k)
    segs = [base + (1 if i < rest else 0) for i in range(k)]
    segs = [max(1, min(mx, s)) for s in segs]               # clamp por-clipe ao máx do modelo (controle de custo)
    return (k, segs)


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
    """Passthrough: o briefing (guiado pelo System Prompt do cliente) JÁ montou a instrução completa da cena.
    Isto só entrega essa instrução ao modelo, sem adicionar nenhuma regra escondida."""
    return (video_prompt or theme or "cena publicitária premium").strip()


def _video_brief_context(company: Dict[str, Any], theme: str) -> str:
    """Contexto REAL de produto/app pro vídeo — MESMA fonte que a ARTE usa (product_list + funções/objetivo/
    knowledge/web_brief), filtrado pelos apps citados no tema. SÓ LEITURA: não dispara refresh, não toca no
    motor de imagem (generate_carousel fica intacto). Vazio se não houver produto → vídeo segue como antes.
    Faz a CENA e a NARRAÇÃO falarem do app de verdade, com fatos (não genérico)."""
    try:
        from ..db_companies import product_list as _plist
        prods = _plist(company.get("id")) or []
    except Exception:
        return ""
    if not prods:
        return ""
    import unicodedata as _ud

    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")

    tnorm = _norm(theme)
    focus = [p for p in prods if _norm(p.get("name")) and _norm(p.get("name")) in tnorm] or prods[:2]
    blocks = []
    for p in focus[:3]:
        fns = p.get("functions") or []
        if isinstance(fns, str):
            try:
                import json as _j
                fns = _j.loads(fns)
            except Exception:
                fns = [fns] if fns else []
        fns_t = "; ".join(str(f).strip() for f in fns if str(f).strip())[:800]
        obj = (p.get("objective") or "").strip()
        kb = (p.get("knowledge") or "").strip()
        web = (p.get("web_brief") or "").strip()
        seg = []
        if obj:
            seg.append("Objetivo: " + obj)
        if fns_t:
            seg.append("Funções: " + fns_t)
        if kb:
            seg.append("Fatos (use SÓ o que está aqui, não invente recursos): " + kb[:2500])
        if web:
            seg.append("Web: " + web[:1000])
        if seg:
            blocks.append(f"[{p.get('name')}] " + " | ".join(seg))
    if not blocks:
        return ""
    return ("PRODUTO/APP REAL EM FOCO (baseie a CENA e a locução NESTES fatos — específico, NÃO genérico): "
            + (" || ".join(blocks))[:4000] + ". ")


# === System Prompt PADRÃO de VÍDEO (Briefing de Reels) — editável por cliente em creative_config.video.system_prompt.
# As {variáveis} são preenchidas pelo CÓDIGO com os dados REAIS da empresa/produto, em LINGUAGEM HUMANA (não como token cru).
_VIDEO_SYS_DEFAULT = """Você é DIRETOR CRIATIVO, estrategista de conteúdo e roteirista de reels da marca {company} ({segment}). Sua função é transformar a ideia preenchida pelo usuário, somada aos dados de marca e produto, em UM storyboard de vídeo forte, específico e publicável, no formato JSON multi-shot definido abaixo — pronto para ser enviado a um modelo de geração de vídeo.

A régua é a mesma do melhor carrossel: conteúdo que EDUCA, PROVOCA ou REPOSICIONA a visão do público. A venda acontece pela percepção de valor construída e pelo CTA desenhado DEPOIS, na pós-produção. Você não vende no grito.

— LEI ARQUITETURAL INEGOCIÁVEL —
O modelo de vídeo gera APENAS a cena filmada — pessoas, ambiente, luz, movimento e som diegético. Ele é ótimo nisso e PÉSSIMO em qualquer coisa determinística. Portanto:
• O modelo NUNCA renderiza: texto, legenda, número, preço, título, logo, marca, nome de marca, ou tela/interface de aplicativo/celular com conteúdo legível, ícones ou nomes.
• Logo, títulos, legendas, CTA, end-card e qualquer grafismo de marca são compostos DEPOIS, por código, na pós-produção. Você descreve isso no bloco `post_production`, que NÃO é enviado ao modelo.
• Cor de marca SIM entra na cena — mas como PALETA (luz, figurino, objetos, ambiente), nunca como grafismo. Ex.: o laranja aparece numa luminária, num sofá, na luz do fim de tarde — jamais num logo desenhado pelo modelo.
• Apps marcados são representados de DUAS formas, nunca pela interface gerada: (a) pela SENSAÇÃO do benefício na cena; (b) por asset REAL composto na pós. Você descreve (a) nas cenas e (b) no `post_production`. NUNCA peça ao modelo para desenhar a interface ou a logo do app.

— REGRA MAIS IMPORTANTE: PROMPTS MULTI-SHOT —
Cada segmento é UMA SEQUÊNCIA CINEMATOGRÁFICA DE MÚLTIPLAS TOMADAS dentro de uma única geração — não um plano estático, não clipes soltos. O campo `action` deve ser uma narrativa de múltiplos shots, em inglês, com gramática de cinema (planos, cortes, movimentos, ações), terminando em SFX. Sempre que houver continuidade, comece o `action` referenciando a tomada anterior ("starting from the previous medium shot...").

— CONSISTÊNCIA DE PERSONAGEM —
Se QUALQUER cena tiver uma pessoa, é a MESMA pessoa em TODAS. Preencha `character.map` UMA vez, hiper-específico e fixo (em inglês): idade, etnia, cabelo (cor+textura+corte), traços, tom de pele, vestuário e UM acessório-âncora único (ex.: "thin small gold hoop earring"). O código repete esse mapa em cada segmento. Se for só produto/ambiente, `character.present=false` e `map=""`. Mantenha entre segmentos: mesma paleta, energia, lógica e luz.

— ANATOMIA DE UM BOM REELS B2B —
Antes de escrever, raciocine internamente (não escreva): dor real do tema, crença errada do público, mudança de visão a provocar, ação final. Depois ENGRANDEÇA a ideia do usuário num conceito forte e específico (eleve, não copie). ARCO obrigatório: GANCHO (0–2s, visual e imediato), DESENVOLVIMENTO (valor específico/exemplo/quebra de objeção), VIRADA/CLÍMAX (prepara o CTA da pós). Gramática de cada shot: sujeito + contexto + 1 ação + 1 movimento de câmera + luz/clima + emoção. MOSTRE a sensação/benefício; proibido b-roll genérico. Conecte ao dia a dia REAL do público-alvo da marca ({audience}) e ao momento comercial dela (diferenciação, valor percebido, fidelização).
PELE NATURAL (crítico): luz quente no AMBIENTE, mas pele NATURAL e precisa — inclua em cada `style.lighting` algo como "warm practical lighting with natural, accurate skin tones — no orange color cast on skin".
ÁUDIO (obrigatório): descreva em `audio` o som diegético (ambiente, SFX e fala). Diálogo/narração SEMPRE em pt-BR ("dialogue in Brazilian Portuguese: '...'"). Trilha do modelo mínima/ausente — a música de marca e legendas entram na pós.

— IDIOMA, FORMATO E DURAÇÃO —
• Toda INSTRUÇÃO de cena (subject, action, environment, camera, style) em INGLÊS.
• Toda FALA/marca em PORTUGUÊS DO BRASIL (no `audio` como diálogo e no `post_production` como legendas/CTA).
• Responda SOMENTE com JSON válido e compacto no schema abaixo. Sem markdown, sem texto fora do JSON.
• Respeite os segundos informados: distribua o total entre os segmentos (cada geração tipicamente 5–8s); `seconds` por segmento e o total deve bater.
• Use SOMENTE fatos fornecidos nos dados de marca/produto. Faltou dado → demonstre o benefício geral sem inventar recurso, número, preço, data ou promessa.

— DADOS QUE VOCÊ RECEBE —
• Ideia/assunto: {theme}
• Empresa: {company} | Segmento: {segment} | Público: {audience}
• Identidade da marca (USAR como paleta de cena): {brand_identity}
• Produto(s)/app(s) em foco (USAR como sensação na cena + asset na pós): {product_identity}
• Base de conhecimento do produto (única fonte de recursos/benefícios): {product_kb}
• Duração total alvo (segundos): {duration}
• Assets de marca (logos para a PÓS — NUNCA descritos ao modelo): {brand_assets}

— SCHEMA DE SAÍDA (obrigatório) —
{
  "meta": {"language_instructions":"en","language_spoken":"pt-BR","aspect_ratio":"9:16","total_seconds": <int>, "big_idea":"<1 frase pt-BR com a dor/oportunidade real>"},
  "character": {"present": <true|false>, "map":"<mapa fixo em inglês ou string vazia>"},
  "brand_palette": "<como a cor da marca aparece na CENA: luz, figurino, props — em inglês; sem grafismo>",
  "segments": [
    {"id": <int>, "seconds": <int>,
     "subject":"<o mesmo personagem (ref. ao map) ou elemento principal — inglês>",
     "action":"<SEQUÊNCIA MULTI-SHOT em inglês: planos, cortes, movimentos, ações; gramática de cinema; termina com SFX>",
     "environment":"<local, hora do dia, set dressing — inglês>",
     "camera": {"shot":"<wide|medium|close-up|...>", "motion":"<slow push-in|dolly|handheld follow|parallax|static>"},
     "style": {"lighting":"<luz + nota de pele natural sem orange cast>", "look":"<estética: cinematic 35mm, soft grain, shallow depth of field, brand-warm palette>"},
     "audio": {"ambient":"<ambiente em inglês>", "sfx":"<efeitos em inglês>", "dialogue_ptBR":"<fala em pt-BR ou string vazia>"}}
  ],
  "post_production": {
    "captions":"<legenda queimada pt-BR — a mensagem para o mudo>",
    "lower_third":"<logo da empresa + handle, discreto, animado>",
    "music":"<trilha de marca a aplicar na pós (clima) — controlada, não a do modelo>",
    "end_card": {"headline_ptBR":"<chamada final curta>", "cta_ptBR":"<CTA>", "url":"<site>", "logos":["<empresa>","<app(s)>"], "seconds": <int>, "motion":"<end-card com movimento, não slide estático>"},
    "apps_to_composite": ["<app: representação real na pós, ex. 'apenas logo no end-card'>"]
  }
}

NÃO inclua, em NENHUM campo de cena (subject/action/environment/style/audio): texto, letra, legenda, número, logo, marca, nome de marca, preço, tela de app com conteúdo legível, claim não confirmado ou promessa. Esses elementos vivem SOMENTE em `post_production`.

— LEI DO REALISMO DE PRODUTO (nova) —
Você RECEBE nesta instrução os dados REAIS do produto/app em foco (Product context / Base de conhecimento / Funções). É a sua ÚNICA fonte verdadeira. Regras:
• DESENHE a SENSAÇÃO humana do benefício REAL: a pessoa USANDO aquele recurso de verdade (tocando, identificando música, ouvindo offline, montando playlist, etc.) — sem nada renderizado na tela, sem nome do app escrito, sem logo. O benefício é mostrado pela EMOCÃO e AÇÃO, não por grafismo.
• PROIBIDO inventar: nome de app/jogo/filme/música/artista/recurso que NÃO esteja no brief. Se faltar dado, demonstre o benefício de forma genérica (gente ouvindo música, descobrindo som) SEM citar produto inexistente.
• PROIBIDO substituir a app real por outra "parecida" (ex.: Deezer → Spotify, ou nome feito-up "Creezer"). Se o brief é sobre app X, é X; mostre o benefício de X sem nunca escrever o nome X na tela.
• Pode, e DEVE, usar a referência visual recebida (imagens do carrossel aprovado do mesmo app) como guia de paleta/vibe/composição — não para copiar frame a frame, mas para herdar a IDENTIDADE VISUAL já aprovada pelo cliente."""


def _fill_vars(template: str, vals: Dict[str, Any]) -> str:
    """Preenche {chave} com os valores REAIS (linguagem humana). Preserva a formatação (não colapsa espaços/linhas)."""
    txt = template or ""
    for k, v in (vals or {}).items():
        txt = txt.replace("{" + k + "}", "" if v is None else str(v))
    return txt


def _video_template_vars(company: Dict[str, Any], theme: str, target_seconds: int = 0) -> Dict[str, str]:
    """Busca os dados REAIS da empresa/marca/produto e devolve em LINGUAGEM HUMANA pra preencher o system prompt do vídeo."""
    bk = company.get("brand_kit") or {}
    if not bk:
        try:
            from ..db_companies import brand_kit_get
            bk = brand_kit_get(company.get("id")) or {}
        except Exception:
            bk = {}
    cols = bk.get("colors") or {}
    # TODAS as cores cadastradas (dict flexível — o usuário define quantas) entram no prompt.
    col_parts = [f"{k} {v}" for k, v in cols.items() if v]
    voice = (bk.get("voice") or bk.get("persona") or "").strip()
    bi = []
    if col_parts:
        bi.append("Cores da marca: " + ", ".join(col_parts))
    if voice:
        bi.append("Tom de voz: " + voice)
    brand_identity = (". ".join(bi) + ".") if bi else "Sem identidade visual cadastrada — use paleta sóbria e premium."
    try:
        from ..db_companies import product_list as _pl
        prods = _pl(company.get("id")) or []
    except Exception:
        prods = []
    import unicodedata as _ud

    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")

    tn = _norm(theme)
    focus = [p for p in prods if _norm(p.get("name")) and _norm(p.get("name")) in tn] or prods[:2]
    pid, pkb, logos = [], [], []
    for p in focus[:3]:
        nm = (p.get("name") or "").strip()
        obj = (p.get("objective") or "").strip()
        fns = p.get("functions") or []
        if isinstance(fns, str):
            try:
                import json as _j
                fns = _j.loads(fns)
            except Exception:
                fns = [fns] if fns else []
        fns_t = "; ".join(str(f).strip() for f in fns if str(f).strip())[:500]
        seg = ([nm] if nm else []) + ([f"objetivo: {obj}"] if obj else []) + ([f"funções: {fns_t}"] if fns_t else [])
        if seg:
            pid.append(" — ".join(seg))
        kb = (p.get("knowledge") or "").strip()                  # base local (cadastro)
        web = (p.get("web_brief") or "").strip()                 # busca web (cache) — ANTES era ignorada no vídeo
        facts = "  ".join(x for x in (kb[:1500], web[:1500]) if x)
        if facts:
            pkb.append(f"[{nm}] " + facts)
    try:
        from ..db_companies import asset_list_logos as _all
        if _all(company.get("id")):
            logos.append(company.get("name") or "empresa")
        for p in focus[:3]:
            if _all(company.get("id"), p.get("id")):
                logos.append((p.get("name") or "").strip())
    except Exception:
        pass
    return {
        "theme": theme or "",
        "company": company.get("name", "") or "",
        "segment": company.get("segment", "") or "empresa brasileira",
        "audience": (bk.get("audience") or "").strip(),
        "brand_identity": brand_identity,
        "product_identity": " | ".join(pid) if pid else "Nenhum app/produto específico — fale do benefício geral.",
        "product_kb": " || ".join(pkb) if pkb else "Sem base de conhecimento — NÃO invente recurso, número, preço, data ou promessa.",
        "duration": (str(int(target_seconds)) if target_seconds else "livre"),
        "brand_assets": ("Logos oficiais disponíveis para a PÓS (NÃO descreva ao modelo): " + ", ".join([l for l in logos if l])) if any(logos) else "Sem logos cadastradas para a pós.",
    }


_BRLANG_LOCK = ("All spoken dialogue and voice-over MUST be in Brazilian Portuguese (pt-BR) — "
                 "never European Portuguese, never Spanish, never English. Accent and wording are Brazilian.")

def _assemble_segment_prompt(seg: Dict[str, Any], character_map: str = "", brand_palette: str = "",
                             product_context: str = "") -> str:
    """Monta o prompt EM TEXTO de UM segmento multi-shot pro modelo de vídeo, repetindo o mapa do personagem.
    product_context = dados REAIS do app/produto em foco (nome, objetivo, funções, fatos da base de conhecimento)
    — injetados como SENSAÇÃO conceitual, nunca como renderização de logo/interface (o modelo é péssimo nisso).
    pt-BR é travado incondicionalmente (nível do clipe), independente da IA devolver dialogue_ptBR preenchido."""
    parts = []
    if product_context:
        parts.append("Product context (use it to depict the genuine human FEELING of these REAL features in the "
                     "scene — NEVER render logos, app names, text on screens, UI mockups or buttons): "
                     + product_context.rstrip("."))
    if character_map:
        parts.append("Recurring character (identical in every shot): " + character_map.rstrip("."))
    if (seg.get("subject") or "").strip():
        parts.append(seg["subject"].strip().rstrip("."))
    if (seg.get("action") or "").strip():
        parts.append(seg["action"].strip())
    if (seg.get("environment") or "").strip():
        parts.append("Environment: " + seg["environment"].strip().rstrip("."))
    cam = seg.get("camera") or {}
    cam_bits = [x for x in [(cam.get("shot") or "").strip(), (cam.get("motion") or "").strip()] if x]
    if cam_bits:
        parts.append("Camera: " + ", ".join(cam_bits))
    style = seg.get("style") or {}
    if (style.get("lighting") or "").strip():
        parts.append("Lighting: " + style["lighting"].strip().rstrip("."))
    if (style.get("look") or "").strip():
        parts.append("Look: " + style["look"].strip().rstrip("."))
    if brand_palette:
        parts.append("Brand color only as ambiance (light/props/wardrobe, never graphics): " + brand_palette.rstrip("."))
    audio = seg.get("audio") or {}
    aud = [x for x in [(audio.get("ambient") or "").strip(), (audio.get("sfx") or "").strip()] if x]
    if (audio.get("dialogue_ptBR") or "").strip():
        aud.append('dialogue in Brazilian Portuguese: "' + audio["dialogue_ptBR"].strip() + '"')
    if aud:
        parts.append("Audio: " + "; ".join(aud))
    parts.append(_BRLANG_LOCK)                               # trava pt-BR no nível do prompt que chega ao modelo
    return ". ".join(p for p in parts if p).strip()


def _video_enrich_apps_if_needed(company: Dict[str, Any], theme: str) -> None:
    """Frentes 2+3 do conhecimento: se algum app em foco não tem web_brief nem knowledge, dispara enriquecimento.
    SYNC quando tudo está vazio (1ª geração daquele app — bloqueia 5s p/ o storyboard já sair rico);
    background quando só está stale (cache > 7 dias). Best-effort: falhou → segue com a base local."""
    try:
        from ..db_companies import product_list as _pl
        prods = _pl(company.get("id")) or []
    except Exception:
        return
    if not prods:
        return
    import unicodedata as _ud

    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")
    tn = _norm(theme)
    focus = [p for p in prods if _norm(p.get("name")) and _norm(p.get("name")) in tn] or prods[:2]
    if not focus:
        return
    # SYNC só se web_brief E knowledge E functions TODOS vazios (app novo, primeira geração)
    need_sync = [p for p in focus if not (p.get("web_brief") or "").strip()
                                     and not (p.get("knowledge") or "").strip()
                                     and not (p.get("functions") or "")]
    if need_sync:
        try:                                                   # 1ª vez: enriquece síncrono, grava, relê
            for p in need_sync:
                try:
                    data = enrich_product_from_web((p.get("name") or "").strip(),
                                                    (p.get("website") or "").strip(),
                                                    (p.get("instagram") or "").strip())
                    if data:
                        from ..db_companies import product_update as _pu
                        upd = {}
                        if data.get("objective") and not (p.get("objective") or "").strip():
                            upd["objective"] = str(data["objective"])[:600]
                        if data.get("functions") and not (p.get("functions") or []):
                            upd["functions"] = data["functions"]
                        if data.get("knowledge") and not (p.get("knowledge") or "").strip():
                            upd["knowledge"] = str(data["knowledge"])[:6000]
                        if upd:
                            _pu(p.get("id"), upd)
                except Exception:
                    continue
            refresh_web_briefs(company.get("id"), need_sync, theme)  # bloqueia p/ cache web (timeout ~5s via httpx interno)
        except Exception:
            pass
        return
    # Caso contrário: dispara refresh em background se cache está stale (não bloqueia o storyboard)
    try:
        stale = [p for p in focus if _web_brief_stale(p)]
        if stale:
            import threading as _th
            _th.Thread(target=refresh_web_briefs, args=(company.get("id"), stale, theme), daemon=True).start()
    except Exception:
        pass


def _video_find_approved_carousel_images(company: Dict[str, Any], theme: str, limit: int = 8):
    """Frente 4 (referência visual): busca o ÚLTIMO carrossel aprovado cujo produto casa com o tema (app em foco).
    Devolve lista de bytes das TELAS do carrossel (cover+content — não só a capa), ou [] se não houver.
    Matching robusto: 1) meta.product (str/dict) → 2) nome de PRODUTO da empresa aparecendo no TITLE/COPY →
    3) substring de nome de produto no TEMA. Best-effort, nunca bloqueia por erro.

    Carrosséis aprovados gravam `meta.carousel_urls` (lista completa de telas) — é a ESTRUTURA toda que o
    briefing pediu (não só a capa). Fallback: `media_url` (capa) quando o post não tem slides marcados."""
    try:
        from ..db_companies import product_list as _pl
        prods = _pl(company.get("id")) or []
    except Exception:
        prods = []
    import unicodedata as _ud

    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")

    product_names = [_norm(p.get("name")) for p in prods if (p.get("name") or "").strip()]
    tn = _norm(theme)
    posts = []
    try:                                                       # fallback direto: varre posts APPROVED da empresa
        from ..db_companies import post_get
        from ..db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM posts WHERE company_id = ? AND status = 'APPROVED' ORDER BY created_at DESC LIMIT 30",
                (company.get("id"),)).fetchall()
        posts = [post_get(r["id"]) for r in rows if r["id"]]
    except Exception:
        posts = []
    if not posts:
        return []

    def _match_app(p):
        meta = p.get("meta") or {}
        # 1) meta.product — pode ser str (nome direto) ou dict {name: ...}
        mp = meta.get("product") or meta.get("app")
        if isinstance(mp, dict):
            mp = mp.get("name") or ""
        pn = _norm(mp or "")
        if pn and pn in tn:
            return True
        # 2) nome de produto da empresa aparece no title/copy deste post (não depende do tema)
        text = _norm((p.get("title") or "") + " " + (p.get("copy") or ""))
        for prod in product_names:
            if prod and prod in text:
                return True
        # 3) nome de produto da empresa aparece no TEMA (app em foco) — backward case
        for prod in product_names:
            if prod and prod in tn:
                return True
        return False

    matched = [p for p in posts if p and _match_app(p)]
    if not matched:
        return []
    p = matched[0]                                             # só o ÚLTIMO carrossel aprovado do app em foco
    meta = p.get("meta") or {}
    # Preferência: meta.carousel_urls (lista completa de slides — a ESTRUTURA toda). Fallback: media_url (capa).
    urls = []
    cu = meta.get("carousel_urls")
    if isinstance(cu, list) and cu:
        urls = [u for u in cu if isinstance(u, str)]
    if not urls:
        m = p.get("media_url")
        if isinstance(m, list):
            urls = [u for u in m if isinstance(u, str)]
        elif isinstance(m, str) and m:
            urls = [m]
    if not urls:
        return []
    imgs = []
    for url in urls[:limit]:
        if not url.startswith(("http://", "https://")):
            continue
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as c:
                r = c.get(url)
                if r.status_code == 200 and r.content:
                    imgs.append(r.content)
        except Exception:
            continue
        if len(imgs) >= limit:
            break
    return imgs


def _complete_ai_with_images(config, system: str, user: str, images: List[bytes],
                             max_tokens: int = 2400) -> str:
    """Chamada multimodal (visão) para a IA de texto — p/ passar referência visual dos carrosséis aprovados.
    Cai para complete_ai (texto) se o provedor não suporta imagem ou falhar. Custo-seguro."""
    if not images:
        return complete_ai(config, system, user, max_tokens)
    import base64, io
    try:
        from PIL import Image
    except Exception:
        return complete_ai(config, system, user, max_tokens)

    def _thumb(b):
        try:
            im = Image.open(io.BytesIO(b)).convert("RGB"); im.thumbnail((512, 512))
            o = io.BytesIO(); im.save(o, "JPEG", quality=80)
            return "data:image/jpeg;base64," + base64.b64encode(o.getvalue()).decode()
        except Exception:
            return None

    parts = [{"type": "text", "text": user}]
    for b in images[:8]:
        thumb = _thumb(b)
        if thumb:
            parts.append({"type": "image_url", "image_url": {"url": thumb}})
    provider = config.get("provider", "")
    model = config.get("model", "")
    api_key = config.get("apiKey", "")
    # Mesma chain de visão usada por verify_same_person — gpt-4o é o melhor p/ texto+imagem.
    vision_chain = []
    if provider == "cometapi" and api_key:
        vision_chain.append(("https://api.cometapi.com/v1", api_key, model or "gpt-4o"))
    if _cometapi_key():
        vision_chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    if _openrouter_key():
        vision_chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    for base, key, mdl in vision_chain:
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
                r = c.post(base + "/chat/completions",
                           headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                           json={"model": mdl, "max_tokens": max_tokens, "temperature": 0.7,
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": parts}]})
                if r.status_code >= 400:
                    continue
                t = ((r.json().get("choices") or [{}])[0].get("message", {}).get("content") or "")
                if t:
                    return t
        except Exception:
            continue
    return complete_ai(config, system, user, max_tokens)  # fallback texto puro


def build_video_storyboard(company: Dict[str, Any], theme: str, video_prompt: str = "",
                           target_seconds: int = 0, n_scenes: int = 0, per_seconds: int = 8,
                           style: str = "") -> List[Dict[str, str]]:
    """Roteiro de VÍDEO. O System Prompt do cliente (creative_config.video.system_prompt, default = documento do Mikael)
    é a ESTRUTURA que o briefing lê; o CÓDIGO preenche as {variáveis} com os dados REAIS da empresa/produto em
    linguagem humana e a IA devolve o schema multi-shot, que viramos em 1 prompt por segmento pro modelo.

    Frentes de conhecimento ATIVAS neste storyboard (eram o bug central — não chegavam ao modelo de vídeo):
      1. Base local cadastrada (products.knowledge/objective/functions) via _video_brief_context → injetada em cada segmento.
      2. Web search (products.web_brief) — dispara enrich síncrono na 1ª geração do app, background depois.
      3. Site/Instagram do produto — só quando 1 e 2 falham (enrich_product_from_web fallback).
      4. Referência visual do carrossel aprovado DO MESMO APP — enviada como imagens à IA de texto multimodal."""
    fallback = [{"prompt": (video_prompt or theme or "").strip(), "seconds": str(per_seconds or 8), "desc": (video_prompt or theme or "").strip(), "character_map": ""}]
    config = cheap_text_config(get_ai_config())
    if not config:
        return fallback
    _video_enrich_apps_if_needed(company, theme)                     # Frentes 2+3 (web+site) — best-effort, sync só na 1ª vez
    sysp = (creative_cfg(company).get("video") or {}).get("system_prompt") or VIDEO_GEN.get("system_prompt") or ""
    vals = _video_template_vars(company, theme, target_seconds)     # busca dados REAIS → linguagem humana (Frente 1)
    system = _fill_vars(sysp, vals).strip()                         # variáveis preenchidas (formatação preservada)
    product_ctx = _video_brief_context(company, theme)               # contexto real do app em foco — injetado em cada cena
    # Frente 4: referência visual do carrossel aprovado do mesmo app (knob on/off via setting)
    ref_images = []
    try:
        if (get_setting("video.use_carousel_ref") or "1") != "0":  # default ON (knob rápido p/ desligar se empírico falhar)
            ref_images = _video_find_approved_carousel_images(company, theme, limit=8)
    except Exception:
        ref_images = []
    # Força o nº de cenas e o idioma no user (era o bug de "IA decide sozinha e devolve 1 cena" + pt-PT)
    scene_rule = ""
    if int(n_scenes or 0) > 0:
        scene_rule = (f"Responda EXATAMENTE com {int(n_scenes)} segmentos no array 'segments', cada um com campo "
                      f"'seconds' distribuído para somar ≈{int(target_seconds or 0)}s no total. ")
    lang_rule = ("Idioma: 'meta.language_spoken'='pt-BR' OBRIGATÓRIO; toda fala/dialogue_ptBR em português do Brasil "
                 "(nunca pt-PT, nunca sotaque europeu). ")
    truth_rule = ("Use SOMENTE os fatos do brief real (Product context / Base de conhecimento / Funções) — NÃO invente "
                  "nome de app, jogo, filme, música, recurso, número ou preço que não estejam no brief. Se faltar dado, "
                  "demonstre o benefício de forma geral sem citar produto inexistente. ")
    user = scene_rule + lang_rule + truth_rule + "Gere agora o storyboard em JSON, exatamente no schema definido."
    allowed = [4, 8, 12]
    try:
        if ref_images:
            raw = _complete_ai_with_images(config, system, user, ref_images, 2400)
        else:
            raw = complete_ai(config, system, user, 2400)
        parsed = extract_json(raw) or {}
        out = []
        if isinstance(parsed, dict):
            character = parsed.get("character") or {}
            cmap = (character.get("map") or "").strip() if character.get("present") else ""
            bpal = (parsed.get("brand_palette") or "").strip()
            # valida/corrige o nº de cenas quando o usuário pediu um nº específico (P-2: 3 cenas no roteiro = 3 segmentos)
            segs_in = parsed.get("segments") or []
            if int(n_scenes or 0) > 0 and len(segs_in) > 0 and len(segs_in) != int(n_scenes):
                # Segunda chamada de correção (texto barato): IA devolveu nº errado de cenas
                try:
                    fix_user = (f"Seu storyboard anterior devolveu {len(segs_in)} segmentos, mas preciso EXATAMENTE "
                                f"{int(n_scenes)}. Reescreva mantendo a mesma identidade/personagem/paleta, apenas "
                                f"redistribuindo o conteúdo em {int(n_scenes)} segmentos somando ≈{int(target_seconds or 0)}s. "
                                f"JSON no mesmo schema: " + (json.dumps(segs_in[:3], ensure_ascii=False)[:1200]))
                    raw2 = complete_ai(config, system, fix_user, 2000) if ref_images else \
                           (complete_ai(config, system, fix_user, 2000))
                    parsed2 = extract_json(raw2) or {}
                    if isinstance(parsed2, dict) and (parsed2.get("segments") or []):
                        segs_in = parsed2.get("segments") or []
                        parsed = parsed2
                except Exception:
                    pass
            for seg in (segs_in or [])[:8]:                         # schema multi-shot (documento) → 1 prompt por segmento
                if not isinstance(seg, dict):
                    continue
                p = _assemble_segment_prompt(seg, cmap, bpal, product_ctx)
                if not p:
                    continue
                try:
                    sec = int(seg.get("seconds") or 8)
                except Exception:
                    sec = 8
                sec = min(allowed, key=lambda a: abs(a - sec))
                out.append({"prompt": p, "seconds": str(sec), "desc": p, "character_map": cmap})
            if not out:                                              # compat: schema antigo {scenes:[{desc,seconds}]}
                for s in (parsed.get("scenes") or [])[:8]:
                    if not isinstance(s, dict):
                        continue
                    desc = (s.get("desc") or s.get("description") or s.get("prompt") or "").strip()
                    if not desc:
                        continue
                    try:
                        sec = int(s.get("seconds") or 8)
                    except Exception:
                        sec = 8
                    sec = min(allowed, key=lambda a: abs(a - sec))
                    out.append({"prompt": (product_ctx + " " + desc).strip() if product_ctx else desc,
                                "seconds": str(sec), "desc": desc, "character_map": ""})
        if not out and (raw or "").strip():                          # IA não devolveu JSON → resposta crua = 1 cena
            txt = (raw or "").strip()
            out = [{"prompt": (product_ctx + " " + txt).strip() if product_ctx else txt,
                    "seconds": str(per_seconds or 8), "desc": txt, "character_map": ""}]
        if out:
            return out
    except Exception:
        pass
    return fallback


def _elevenlabs_key() -> str:
    """Chave ElevenLabs (voz premium) — settings 'tts.elevenlabs.key' ou env ELEVENLABS_API_KEY. Vazio = desligado."""
    try:
        return (get_setting("tts.elevenlabs.key") or os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    except Exception:
        return (os.environ.get("ELEVENLABS_API_KEY") or "").strip()


def tts_synthesize(text: str, out_path: str, voice: str = "onyx", model: str = "tts-1") -> bool:
    """Locução (narração). Fase 4: usa ElevenLabs (voz premium) quando há chave configurada; senão CometAPI
    /v1/audio/speech (OpenAI-compat). Salva mp3. True/False. Custo-seguro: sem texto/sem chave → False; EL falha → cai no CometAPI."""
    txt = (text or "").strip()
    if not txt:
        return False
    # 1) ElevenLabs — só quando configurado (chave + voz). NÃO verificado ao vivo sem chave; falha → fallback.
    elk = _elevenlabs_key()
    if elk:
        try:
            vid = (get_setting("tts.elevenlabs.voice") or "EXAVITQu4vr4xnSDxMaL").strip()   # voz default EL (override por setting/empresa)
            mdl = (get_setting("tts.elevenlabs.model") or "eleven_multilingual_v2").strip()
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
                r = c.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                           headers={"xi-api-key": elk, "content-type": "application/json", "accept": "audio/mpeg"},
                           json={"text": txt[:4096], "model_id": mdl})
            if r.status_code < 400 and r.content:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                if os.path.getsize(out_path) > 200:
                    return True
        except Exception:
            pass   # EL indisponível → cai no CometAPI (nunca quebra o vídeo)
    # 2) CometAPI (default / fallback)
    key = _cometapi_key()
    if not key:
        return False
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as c:
            r = c.post(_COMETAPI_BASE + "/audio/speech",
                       headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                       json={"model": model, "input": txt[:4096], "voice": (voice or "onyx"),
                             "response_format": "mp3"})
        if r.status_code >= 400 or not r.content:
            return False
        with open(out_path, "wb") as f:
            f.write(r.content)
        return os.path.getsize(out_path) > 200
    except Exception:
        return False


def music_generate(vibe: str, out_path: str, max_wait: int = 150) -> bool:
    """Trilha INSTRUMENTAL via CometAPI Suno (POST /suno/submit/music → poll GET /suno/fetch/{id} → baixa wav/mp3).
    BEST-EFFORT: se falhar/estourar o tempo, retorna False e o vídeo segue SEM música (nunca quebra)."""
    key = _cometapi_key()
    vibe = (vibe or "").strip()
    if not key or not vibe:
        return False
    base = _COMETAPI_BASE.replace("/v1", "")          # Suno fica FORA do /v1
    H = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    try:
        import time as _t
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
            sub = c.post(base + "/suno/submit/music", headers=H,
                         json={"gpt_description_prompt": vibe[:300], "make_instrumental": True,
                               "negative_tags": "vocals, lyrics, speech, voice", "mv": "chirp-v4"})
            if sub.status_code >= 400:
                return False
            j = sub.json() or {}
            dat = j.get("data")
            tid = (dat if isinstance(dat, str) else (dat or {}).get("task_id") if isinstance(dat, dict) else None) or j.get("task_id")
            if not tid:
                return False
            deadline = _t.time() + max_wait
            while _t.time() < deadline:
                _t.sleep(8)
                q = c.get(base + f"/suno/fetch/{tid}", headers=H)
                if q.status_code >= 400:
                    continue
                d = (q.json() or {}).get("data") or {}
                status = str(d.get("status") or "").upper()
                clips = d.get("data") if isinstance(d.get("data"), list) else []
                url = (clips[0].get("audio_url") or clips[0].get("audio") or "") if (clips and isinstance(clips[0], dict)) else ""
                if status in ("SUCCESS", "COMPLETED", "FINISHED") and url:
                    audio = c.get(url)
                    if audio.status_code < 400 and audio.content:
                        with open(out_path, "wb") as f:
                            f.write(audio.content)
                        return os.path.getsize(out_path) > 1000
                    return False
                if status in ("FAILED", "ERROR", "CANCELED"):
                    return False
        return False
    except Exception:
        return False


def build_video_audio_plan(company: Dict[str, Any], theme: str, video_prompt: str = "",
                           total_seconds: int = 24) -> Dict[str, str]:
    """QUEM MANDA NO ÁUDIO É O BRIEFING. Lê o briefing e decide: mode (none|music|narration|both), ROTEIRO de
    locução (tamanho que CASA com a duração) e a VIBE da trilha. Default (briefing neutro) = TRILHA (reel não nasce mudo)."""
    _GENVIBE = "trilha instrumental cinematográfica brasileira, energia crescente, sem vocais"
    safe = {"mode": "music", "script": "", "music": _GENVIBE, "voice": "onyx"}
    config = cheap_text_config(get_ai_config())
    if not config:
        return safe
    bk = company.get("brand_kit") or {}
    voice_brand = (bk.get("voice") or bk.get("persona") or "").strip()
    max_words = max(8, int((total_seconds or 24) * 2.3))     # ~2.3 palavras/seg de locução comercial PT-BR
    system = (
        "Você é DIRETOR DE ÁUDIO de reels publicitários. A PARTIR DO BRIEFING decida o áudio — QUEM MANDA É O "
        "BRIEFING: se pede narração/locução/gravação, escreva a locução; se pede só trilha/música, sem locução; "
        "se pede os dois, faça os dois; se pede mudo/sem som, mode='none'. "
        "Se o briefing NÃO mencionar áudio, use mode='music' (trilha) — reel MUDO performa mal. "
        f"Se houver locução: ROTEIRO em PT-BR de NO MÁXIMO {max_words} palavras, natural e persuasivo, no tom da "
        "marca, que CASA com a duração (nem corre nem sobra). PROIBIDO ler preço/valores ou soletrar URL. "
        "Se houver trilha: descreva a VIBE (gênero, andamento, energia) p/ gerar instrumental SEM vocais. "
        'Responda SOMENTE JSON: {"mode":"none|music|narration|both","script":"<locução ou vazio>",'
        '"music":"<vibe da trilha ou vazio>","voice":"onyx|nova|shimmer|echo|fable|alloy|sage|coral"}'
    )
    user = (f"Marca: {company.get('name','')} ({company.get('segment','')}). "
            + (f"Tom/voz da marca: {voice_brand}. " if voice_brand else "")
            + _video_brief_context(company, theme)
            + f"Duração do vídeo ~{int(total_seconds or 24)}s. Briefing/tema: {theme}. Direção visual: {video_prompt}")
    try:
        p = extract_json(complete_ai(config, system, user, 600)) or {}
        mode = (p.get("mode") or "music").strip().lower()
        if mode not in ("none", "music", "narration", "both"):
            mode = "music"
        _mus = (p.get("music") or "").strip()
        if mode in ("music", "both") and not _mus:
            _mus = _GENVIBE
        return {"mode": mode, "script": (p.get("script") or "").strip(),
                "music": _mus, "voice": ((p.get("voice") or "onyx").strip() or "onyx")}
    except Exception:
        return safe


def build_video_cta(company: Dict[str, Any], theme: str, event: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """CTA do VÍDEO GERADO pelo briefing (igual carrossel: NADA fixo, mas com ESTRUTURA). Retorna
    {eyebrow,title,subtitle,cta} ancorado no produto/KB real. Custo-seguro: sem IA → CTA institucional simples.
    O render usa o MESMO motor do carrossel (compose_card_slide)."""
    name = (company.get("name") or "").strip()
    seg = (company.get("segment") or "").strip()
    safe = {"eyebrow": seg.upper(), "title": (name or "Fale com a gente"), "subtitle": "", "cta": "Fale com a gente"}
    config = cheap_text_config(get_ai_config())
    if not config:
        return safe
    ctx = _video_brief_context(company, theme)
    info = event_cta_info(event)
    system = (
        "Você escreve o CARD DE CTA de um reel publicitário — MESMA régua do carrossel: estrutura forte, copy de "
        "agência, ESPECÍFICO (nada genérico). A partir do briefing e do produto, gere um CTA curto que fecha o vídeo. "
        "PROIBIDO inventar preço ou datas. "
        'Responda SOMENTE JSON: {"eyebrow":"<rótulo curto em MAIÚSCULAS (segmento/produto)>",'
        '"title":"<headline de VALOR, 2-5 palavras, forte>","subtitle":"<1 frase de benefício/oferta>",'
        '"cta":"<texto do botão (ex.: Fale com a gente / Quero contratar)>"}'
    )
    user = (f"Marca: {name} ({seg}). " + ctx + f"Briefing/tema: {theme}. "
            + (f"Dado REAL do evento (use exatamente, não invente): {info}. " if info else ""))
    try:
        p = extract_json(complete_ai(config, system, user, 400)) or {}
        out = {"eyebrow": (p.get("eyebrow") or seg).strip(),
               "title": (p.get("title") or name or "Fale com a gente").strip(),
               "subtitle": (p.get("subtitle") or "").strip(),
               "cta": (p.get("cta") or "Fale com a gente").strip()}
        if info:                                  # dado REAL do evento manda no subtítulo (fonte única)
            out["subtitle"] = info
        return out
    except Exception:
        return safe


# OmniRoute video é SÍNCRONO (1 POST bloqueia até o vídeo ficar pronto — esse é o "delay grande" do Sora/Veo web).
# Para encaixar no fluxo async do render: create_video_job baixa os bytes na hora e guarda aqui; download_video lê daqui.
_OMNI_VIDEO_JOBS: Dict[str, bytes] = {}


def _omni_extract_video_bytes(data: Any, key: str = "") -> bytes:
    """Acha a URL (ou b64) do vídeo na resposta do gateway (formato varia: data[].url, video_url, choices[].message.content
    com link, data URI…) e devolve os bytes do mp4. Levanta se não achar."""
    import re, base64 as _b64

    def _walk(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from _walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from _walk(v)
        elif isinstance(o, str):
            yield o

    strs = list(_walk(data))
    # 1) b64 explícito (estilo images) ou data URI
    try:
        b64 = data["data"][0]["b64_json"]
        if isinstance(b64, str) and len(b64) > 100:
            return _b64.b64decode(b64)
    except Exception:
        pass
    for s in strs:
        if s.startswith("data:") and ";base64," in s:
            return _b64.b64decode(s.split(";base64,", 1)[1])
    # 2) URL de vídeo em qualquer lugar (prioriza .mp4/.webm/.mov e quem tem 'video')
    urls = []
    for s in strs:
        urls += re.findall(r"https?://[^\s\"'\)\]<>]+", s)
    def _score(u):
        ul = u.lower()
        return (3 if any(e in ul for e in (".mp4", ".webm", ".mov")) else 0) + (1 if "video" in ul else 0)
    import time as _t
    for u in sorted(set(urls), key=_score, reverse=True):
        # alguns provedores (veo-free) devolvem a URL ANTES do arquivo existir → retry com espera
        for _att in range(6):
            try:
                host = u.split("/", 3)[2]
                needs = ("20128" in host) or ("172.17.0.1" in host) or ("213.199" in host) or host.endswith("openai.com") or host.endswith("googleapis.com")
                with httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0)) as c:
                    rr = c.get(u, headers=({"Authorization": "Bearer " + key} if needs else {}))
                if rr.status_code < 400 and rr.content:
                    ct = (rr.headers.get("content-type") or "").lower()
                    if "video" in ct or (u.lower().endswith((".mp4", ".webm", ".mov")) and len(rr.content) > 20000) or len(rr.content) > 50000:
                        return rr.content
            except Exception:
                pass
            _t.sleep(10)
    raise ValueError("OmniRoute vídeo: resposta sem URL/b64 reconhecível: " + (json.dumps(data)[:300] if not isinstance(data, str) else data[:300]))


def _omniroute_create_video(model: str, prompt: str, seconds: str, aspect_ratio: str = "9:16",
                            size: str = "720x1280", first_frame_url: Optional[str] = None) -> bytes:
    """POST síncrono no gateway /videos/generations e devolve os bytes do mp4. Timeout longo (Sora/Veo web demoram)."""
    base, key = _omniroute_base(), _omniroute_key()
    body: Dict[str, Any] = {"model": model, "prompt": (prompt or "")[:4000]}
    body["seconds"] = _video_seconds_value(seconds, 8)
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if size:
        body["size"] = size
    if first_frame_url:
        body["image"] = first_frame_url            # continuidade best-effort (gateway pode ignorar)
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0)) as c:
        r = c.post(base + "/videos/generations",
                   headers={"Authorization": "Bearer " + key, "content-type": "application/json"}, json=body)
    if r.status_code >= 400:
        raise ValueError(f"Falha OmniRoute vídeo (HTTP {r.status_code}): {r.text[:300]}")
    try:
        data = r.json()
    except Exception:
        data = r.text
    return _omni_extract_video_bytes(data, key)


def create_video_job(prompt: str, seconds: str = "8", size: str = "720x1280",
                     first_frame_url: Optional[str] = None, model: Optional[str] = None,
                     aspect_ratio: str = "9:16", target_seconds: Optional[int] = None,
                     config_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cria um job de vídeo (async) no PROVEDOR configurado. Retorna o job (id/status).
    first_frame_url → CONTINUIDADE: a imagem entra como PRIMEIRO FRAME (= último frame da cena anterior).
    aspect_ratio → 9:16 (reels/story) por padrão; verificado que sem isso o veo sai 16:9.
    target_seconds → duração TOTAL do vídeo (não por-clipe). Quando o provedor suporta um campo de duração
    total/distint de "por-clipe" (ex: CometAPI's 'total_duration'), é repassado para promover o alcance do alvo.
    Já 'seconds' permanece sendo o por-clipe (clampado ao máx do modelo)."""
    # O job congela provedor/modelo no clique de gerar. Sem isso, uma troca no
    # seletor durante o render fazia polling/download no modelo seguinte.
    config = config_override or get_video_config()
    if not config:
        raise ValueError("Geração de vídeo não configurada — escolha o modelo de vídeo no painel.")
    prov = config["provider"]
    mdl = model or config["model"]
    if prov == "kie":
        # ASSÍNCRONO de verdade: cria a task e devolve o taskId; o render faz o polling (get_video_job).
        tid = _kie_create_task(mdl, prompt, seconds, aspect_ratio or "9:16")
        return {"id": tid, "status": "queued", "provider": "kie"}
    if prov == "omniroute":
        # SÍNCRONO: gera e baixa agora (bloqueia minutos), guarda os bytes e devolve job já "completed".
        import uuid as _uuid
        data = _omniroute_create_video(mdl, prompt, seconds, aspect_ratio, size, first_frame_url)
        jid = "omni_" + _uuid.uuid4().hex
        _OMNI_VIDEO_JOBS[jid] = data
        return {"id": jid, "status": "completed", "provider": "omniroute"}
    if prov == "openrouter":
        # OpenRouter POST /api/v1/videos: duration inteiro + frame_images tipado.
        # generate_audio=True: o modelo gera o som diegético (ambiente/SFX/fala), conforme a instrução do briefing.
        body: Dict[str, Any] = {"model": mdl, "prompt": prompt[:4000], "generate_audio": True}
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        body["duration"] = min(_video_seconds_value(seconds), video_model_max_seconds(mdl) or 12)  # trava custo: nunca > máx do modelo
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
            ("seconds", (None, str(min(_video_seconds_value(seconds, 4), video_model_max_seconds(mdl) or 12)))),
            ("aspect_ratio", (None, aspect_ratio or "9:16")),
            ("resolution", (None, "720p")),
        ]
        if target_seconds and int(target_seconds) > 0:  # best-effort: gateway pode ignorar — 'seconds' já traba por-clipe
            fields.append(("total_seconds", (None, str(int(target_seconds)))))
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
    if config and config.get("provider") == "kie":
        d = _kie_record(job_id)
        st = (d.get("state") or "").lower()
        status = {"success": "completed", "fail": "failed"}.get(st, "processing")
        cc = d.get("creditsConsumed")
        if status == "completed" and cc:                    # aprende o custo REAL em créditos por modelo
            try:
                from ..db import settings_set as _ss
                from datetime import datetime, timezone
                _ss(key="kie.credits." + (config.get("model") or ""), value=str(float(cc)),
                    updated_at=datetime.now(timezone.utc).isoformat())
            except Exception:
                pass
        return {"id": job_id, "status": status, "state": st, "progress": d.get("progress"),
                "creditsConsumed": cc, "failMsg": d.get("failMsg"), "_result_urls": _kie_result_urls(d)}
    if (config and config.get("provider") == "omniroute") or (job_id or "").startswith("omni_"):
        return {"id": job_id, "status": "completed" if job_id in _OMNI_VIDEO_JOBS else "failed"}
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
    if prov == "kie":
        urls = _kie_result_urls(_kie_record(job_id))
        if not urls:
            raise ValueError("kie: vídeo sem resultUrls (job não concluído).")
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            res = client.get(urls[0])
        if res.status_code >= 400 or not res.content:
            raise ValueError(f"kie: falha ao baixar vídeo (HTTP {res.status_code})")
        return res.content
    if prov == "omniroute" or (job_id or "").startswith("omni_"):
        data = _OMNI_VIDEO_JOBS.pop(job_id, None)
        if not data:
            raise ValueError("OmniRoute vídeo: bytes não encontrados (job expirado ou falhou).")
        return data
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


def enrich_company_from_web(name: str, site_url: str = "", instagram: str = "", segment: str = "",
                            facebook: str = "") -> Dict[str, Any]:
    """Read the company's site/Instagram and define brand voice/persona/audience/visual base
    for the agency. NEVER returns prices."""
    import re as _re
    import json as _json
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — adicione sua chave em Configurações.")
    text = _fetch_site_text(site_url)
    facebook_text = _fetch_site_text(facebook) if facebook.startswith(("http://", "https://")) else ""
    if facebook_text:
        text = (text + "\nPERFIL FACEBOOK:\n" + facebook_text)[:16000]
    system = (
        "Você é um estrategista de marca. A partir do site/Instagram de uma EMPRESA, defina a "
        "identidade verbal e o posicionamento para uma agência criar posts. Responda SOMENTE com "
        "JSON válido, sem markdown. IGNORE textos de cookies/LGPD/privacidade. NUNCA inclua preços."
    )
    user = (
        f"Empresa: {name}\nSegmento atual: {segment or '(não informado)'}\n"
        f"Instagram: {instagram or '(não informado)'}\n"
        f"Facebook: {facebook or '(não informado)'}\n"
        f"Conteúdo do site:\n{text or '(site indisponível — infira pelo nome e Instagram)'}\n\n"
        "Extraia exatamente este JSON:\n"
        '{"description":"o que a empresa faz (1-2 frases)",'
        '"segment":"segmento curto (ex: agência de SVAs para provedores)",'
        '"audience":"PÚBLICO + MODELO DE NEGÓCIO: para quem vende e como (a IA segue isto à risca em todo conteúdo)",'
        '"voice":"tom de voz em poucas palavras (ex: próximo, confiante, sem jargão técnico)",'
        '"persona":"persona da marca: quem é, como fala, como se posiciona",'
        '"visual_prompt_base":"base visual para as imagens dos posts: estilo, paleta, elementos, clima",'
        '"colors":{"nome_da_cor":"#RRGGBB"}}\n'
        "Em colors, retorne apenas cores sustentadas pelo site, com nomes curtos e até 8 tons realmente distintos; "
        "não invente variações quase iguais para completar quantidade. "
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
    "app_rule": "Em \"app\": se a tela falar de um produto/serviço/procedimento específico da empresa, escreva o nome EXATO; senão deixe vazio. ",
    "name_rule": "NOMES EXATOS E OBRIGATÓRIOS (nunca abrevie/erre): E-Saúde, Looke (NUNCA \"Look\"), Deezer, ExitLag, CARIAP. ",
    "content_rules": ("REGRAS: sem preços; nada de 'compre/contrate/assine' nos slides de conteúdo (só no CTA); "
                      "conteúdo que EDUCA o público sobre o tema; frases específicas, não clichê."),
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
    "video_template": ("Formato: VÍDEO/REELS (15-60s). Estruture assim:\n"
                       "GRANDE IDEIA: (1 frase específica, com dor/oportunidade real)\n"
                       "GANCHO 0-2s: (benefício concreto ou tensão comercial que prende)\n"
                       "CENAS: cada cena deve avançar a narrativa com sujeito + contexto + 1 ação + 1 movimento de câmera\n"
                       "VIRADA/PROVA: (o que muda na visão do público)\n"
                       "CTA: (chamada final curta; texto/logo entram na pós)\n"
                       "ÁUDIO: (trilha/locução/captions, se fizer sentido)"),
    "video_storyboard_system": (
        "Você é DIRETOR CRIATIVO, estrategista editorial e planejador de reels B2B. Sua função é transformar o briefing "
        "em um storyboard de vídeo forte, específico e publicável, com a MESMA régua do carrossel: conteúdo que educa, "
        "provoca ou reposiciona a visão do público; a venda acontece pela percepção de valor construída e pelo CTA desenhado "
        "DEPOIS pelo sistema. {duration_rule}{tone_rule}{style_rule}"
        "ANTES de escrever as cenas, raciocine internamente sobre: dor real por trás do tema, crença errada do público, "
        "mudança de visão que o vídeo precisa provocar e ação que o público deve tomar no final. Não escreva esse raciocínio. "
        "O roteiro deve ter ARCO: (1) GANCHO visual até 2s com benefício concreto ou tensão comercial; "
        "(2) DESENVOLVIMENTO com valor específico, exemplo aplicável, erro comum, oportunidade ou quebra de objeção; "
        "(3) VIRADA/CLÍMAX que prepara o CTA. "
        "REGRAS PARA CARIAP/PROVEDORES: quando o tema envolver ISP, SVAs, apps, carteira de clientes, fiscal, telecom ou rentabilização, "
        "conecte tudo ao dia a dia comercial do provedor: diferenciação de planos, redução da guerra de preço, fidelização, "
        "valor percebido pelo assinante e rentabilização da base. Não fale genericamente de 'tecnologia'. "
        "CADA cena deve ser uma UNIDADE DE SHOT: sujeito ou elemento principal + contexto/local + 1 ação principal + "
        "1 movimento de câmera + luz/clima + emoção clara. Vídeo curto não aceita cena cheia de coisa. "
        "NÃO gere b-roll genérico: proibido 'executivos apertando as mãos', 'pessoa mexendo no celular' ou 'ambiente tecnológico' "
        "se isso serviria para qualquer marca. A cena precisa ancorar o produto/serviço real no mundo e no benefício concreto. "
        "CONTINUIDADE: mantenha paleta, energia e lógica narrativa entre cenas; não troque de universo visual sem motivo. "
        "MOSTRE a sensação/benefício; não dependa de interface de app, tela com texto ou texto dentro do vídeo. "
        "O sistema aplica logo, títulos, captions, CTA e marca depois. Portanto NÃO crie cena de CTA, NÃO peça logo e NÃO peça texto em quadro. "
        "CONSISTÊNCIA DE PERSONAGEM: se em QUALQUER cena aparecer uma pessoa, ela tem de ser a MESMA pessoa em TODAS as cenas. "
        "Preencha 'character' UMA vez com um mapa HIPER-ESPECÍFICO e FIXO: idade aparente, etnia, cabelo (cor+textura+corte), "
        "traços do rosto, tom de pele, vestuário (cor+padrão+corte) e UM acessório-âncora único e marcante "
        "(ex.: 'brinco pequeno em formato de estrela banhado a prata'). O sistema repete esse mapa em cada cena pra travar a identidade. "
        "Se o vídeo for SÓ de produto/ambiente (sem pessoa), use character.present=false e map vazio. "
        "Em cada cena, escolha de propósito 'framing' (enquadramento), 'movement' (movimento de câmera) e 'style' (estética) — linguagem de cinema, não amador. "
        "Responda SOMENTE JSON válido e compacto: {\"character\":{\"present\":true,\"map\":\"idade+etnia+cabelo+rosto+pele+vestuário+acessório-âncora único\"},"
        "\"scenes\":[{\"desc\":\"sujeito/elemento + contexto + 1 ação + luz/clima + emoção + motivo estratégico\","
        "\"framing\":\"close-up|plano médio|plano aberto\",\"movement\":\"push-in lento|dolly|pan discreto|parallax\","
        "\"style\":\"estética da cena (ex.: 35mm granulado quente)\",\"seconds\":8}, ...]} . "
        "PROIBIDO em 'desc': qualquer TEXTO, letra, legenda, número; LOGO, marca, nome de marca; TELA/interface de app/celular com "
        "conteúdo legível, ícones ou nomes; claim não confirmado; preço inventado; promessa de resultado garantido. Só a CENA fotográfica em movimento, em PT-BR."
    ),
    "video_storyboard_user": (
        "DADOS FIXOS DA MARCA E DO CLIENTE:\n"
        "- Empresa: {company} ({segment}).\n"
        "{audience_line}{visual_base_line}{client_rules_line}"
        "{product_context}"
        "PEDIDO DO USUÁRIO / TEMA:\n{theme}\n\n"
        "DIREÇÃO VISUAL INFORMADA:\n{video_prompt}\n\n"
        "Use SOMENTE fatos e recursos fornecidos acima para falar de produto. Se faltar dado, faça a cena demonstrar o benefício geral sem inventar recurso, número, preço, data ou promessa."
    ),
    "post_template": ("Formato: POST ÚNICO (feed). Entregue:\n"
                      "GRANDE IDEIA:\nHeadline:\nÂngulo: (pra quem e por quê)\nMensagem:\n"
                      "Destaques: (3 bullets fortes)\nCTA:\nVisual: (cena concreta e cinematográfica, sem clichê de banco de imagem)"),
}


# Template do PROMPT de imagem: a IA cria a CENA ({visual}); a identidade ({brand_fix}) é fixa
# e aplicada por código. Tudo editável por cliente.
IMAGE_GEN: Dict[str, Any] = {
    "system_prompt": (
        "Gere APENAS a IMAGEM DE FUNDO (cenário fotográfico) de um post publicitário — "
        "SEM nenhum texto e SEM nenhum logo. É uma FOTO/cena, não um cartaz pronto."
    ),
    "scene_template": (
        "{system_prompt} {focus}Cena: {visual}. "
        "Estilo de CAMPANHA PUBLICITÁRIA PREMIUM: cinematográfico, iluminação de campanha, profundidade, "
        "cores ricas, foco/desfoque intencional, aparência de anúncio profissional de marca — NÃO foto de banco de imagem. "
        "Paleta que combina com a marca {company}, usando sua cor principal {color} quando natural. "
        "{composition} A FAIXA INFERIOR sempre limpa (vai o rodapé). É onde o sistema aplica texto e logos depois. "
        "PROIBIDO desenhar: qualquer texto, letra, número, palavra, título, logotipo, marca, ícone de app, "
        "telefone, site, rodapé, banner ou interface com palavras legíveis. Apenas o cenário. "
        "Pessoas realistas e naturais (sem cara de IA, sem deformação). VARIE bastante o cenário a cada geração. "
        "EVITE: aparência genérica de IA, cara de banco de imagem/stock, pessoas artificiais demais, "
        "cenário corporativo clichê, excesso de elementos abstratos, interface com texto falso, "
        "marcas de terceiros, visual infantil, estética poluída. {refs_rule} "
        "Vertical 1080x1350, altíssima qualidade, nítida, com cara de campanha real. {client_rules}"
    ),
    "brand_fix": ("IDENTIDADE FIXA (o sistema aplica DEPOIS — não desenhe, não escreva): cor de marca {color}; "
                  "a logo oficial do app é carimbada pelo código; todo TEXTO entra como camada de design. "
                  "NA FOTO: sem texto, sem letras, sem logo, sem marca d'água."),
}

# Template do PROMPT de vídeo/reels (placeholder editável; a geração de vídeo usa isto quando ligada).
VIDEO_GEN: Dict[str, Any] = {
    "system_prompt": _VIDEO_SYS_DEFAULT,
    "scene_template": (
        "{system_prompt} "
        "SHOT CANÔNICO: {visual}. "
        "Construa a cena com sujeito/elemento principal claro, contexto brasileiro verossímil, UMA ação principal e UM movimento de câmera. "
        "CÂMERA: movimento suave e cinematográfico (push-in leve, dolly, pan discreto ou parallax), sem tremedeira, sem cortes caóticos dentro do shot. "
        "{brand_grade}"
        "ILUMINAÇÃO E ESTÉTICA: luz dramática/direcional quando fizer sentido, profundidade real em camadas, textura rica, foco nítido, micro-contraste, grão fino e acabamento de campanha premium. "
        "Pessoas brasileiras reais e naturais quando a cena pedir (sem deformação, sem rosto distorcido, sem mãos estranhas); use só elementos/produto/ambiente quando isso ilustrar melhor a função. "
        "NÃO faça b-roll genérico: a cena precisa parecer feita para este briefing, não para qualquer marca. "
        "{brand_fix} "
        "ÁUDIO NATIVO DO MODELO: se o provedor tentar gerar áudio, use apenas ambiente natural/trilha instrumental sutil; SEM fala, SEM narração, SEM vozes humanas e SEM canto/letras. "
        "O texto, logo, legenda, CTA, locução e trilha final entram depois pelo sistema."
    ),
    "brand_fix": (
        "PROIBIDO ABSOLUTO em QUALQUER frame e QUALQUER lugar do quadro: TEXTO, letra, palavra, número, legenda, título; "
        "LOGO, marca, logotipo, watermark; INTERFACE/TELA de app ou celular com ícones/nomes/texto legível; nota musical com texto. "
        "Telas de aparelhos só com brilho ABSTRATO. NADA escrito em lugar nenhum — o texto e a marca entram DEPOIS pelo sistema."
    ),
}

# Estilos virais de vídeo (Fase 3): preset id → diretiva injetada no roteiro. Override por empresa em creative_config.video.styles.
VIDEO_STYLES: Dict[str, Dict[str, str]] = {
    "auto":     {"name": "Automático (a IA decide)", "directive": ""},
    "reveal":   {"name": "Revelação de produto",     "directive": "ESTILO DE VÍDEO: REVELAÇÃO DE PRODUTO — surgimento dramático do item (da sombra/luz), close cinematográfico, push-in lento, reflexos e partículas sutis; o produto é o herói da cena."},
    "city_cgi": {"name": "CGI na cidade",            "directive": "ESTILO DE VÍDEO: CGI URBANO — o produto/elemento integrado em escala grande no ambiente urbano brasileiro, movimentos aéreos/drone, perspectiva épica, hora dourada."},
    "unboxing": {"name": "Unboxing de luxo",         "directive": "ESTILO DE VÍDEO: UNBOXING DE LUXO — abertura de embalagem premium, mãos cuidadosas, macro nos detalhes/textura, luz suave de estúdio, ritmo elegante e tátil."},
    "slowmo":   {"name": "Tecnologia em slow-motion","directive": "ESTILO DE VÍDEO: SLOW-MOTION TECH — câmera lenta em close nos detalhes técnicos, micro-movimentos, reflexos, profundidade e acabamento high-tech."},
}


def video_style_directive(company: Optional[Dict[str, Any]], style_id: str) -> str:
    """Diretiva do estilo viral escolhido (Fase 3). Override por empresa em creative_config.video.styles. '' = sem estilo (auto)."""
    sid = (style_id or "auto").strip().lower()
    ov = (((company or {}).get("brand_kit") or {}).get("creative_config") or {}).get("video") or {}
    styles = {**VIDEO_STYLES, **((ov.get("styles") or {}) if isinstance(ov.get("styles"), dict) else {})}
    ent = styles.get(sid) if isinstance(styles.get(sid), dict) else {}
    return (ent.get("directive") or "").strip()


def video_styles_list(company: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Lista [{id,name}] de estilos virais (defaults + overrides da empresa) p/ o seletor da UI."""
    ov = (((company or {}).get("brand_kit") or {}).get("creative_config") or {}).get("video") or {}
    styles = {**VIDEO_STYLES, **((ov.get("styles") or {}) if isinstance(ov.get("styles"), dict) else {})}
    return [{"id": k, "name": (v.get("name") or k)} for k, v in styles.items() if isinstance(v, dict)]

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


def _render_prompt_template(template: Any, values: Dict[str, Any]) -> str:
    """Substitui só placeholders conhecidos ({visual}, {company}, etc.) sem quebrar JSON literal no prompt."""
    txt = "" if template is None else str(template)
    for key, val in values.items():
        txt = txt.replace("{" + key + "}", "" if val is None else str(val))
    return re.sub(r"\s{2,}", " ", txt).strip()


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
        usr = (f"Marca: {company.get('name','')} ({(company.get('segment') or 'empresa brasileira').strip()}). "
               f"Tema: {theme}. Telas do carrossel:\n{plano}\n\n"
               + (f"Regras do cliente: {rules}. " if rules else "")
               + "Escreva uma LEGENDA envolvente: 1 GANCHO forte na 1a linha, 2-4 linhas de valor (fale COM o "
                 "público-alvo da marca), e um CTA de contato no fim. Depois 8-12 HASHTAGS relevantes (do segmento da marca + o tema). "
                 'Responda SÓ JSON: {"copy":"<legenda com \\n entre linhas>","hashtags":"#a #b #c"}')
        data = extract_json(complete_ai(config, sys, usr, 900)) or {}
        return {"copy": (data.get("copy") or "").strip(), "hashtags": (data.get("hashtags") or "").strip()}
    except Exception:
        return {"copy": "", "hashtags": ""}


def generate_briefing(company: Dict[str, Any], theme: str, objetivo: str = "educar",
                      formato: str = "carrossel", n_telas: int = 0,
                      intent: str = "produtos", event: Optional[Dict[str, Any]] = None,
                      apps_focus: Optional[List[str]] = None, seconds: int = 0) -> str:
    """Plano de conteúdo COMPLETO a partir de um assunto, adaptado ao FORMATO e ao OBJETIVO.
    carrossel → plano tela a tela; video → roteiro em cenas; post → pauta rica. Texto (não JSON)."""
    config = cheap_text_config(get_ai_config())
    if not config:
        raise ValueError("IA não configurada — configure o provedor de texto.")
    G = creative_cfg(company)["briefing"]
    bk = company.get("brand_kit") or {}
    audience = (bk.get("audience") or "o público-alvo da marca").strip()
    rules = (bk.get("client_rules") or "").strip()
    obj = (G.get("objetivos") or _OBJ_BRIEF).get((objetivo or "").lower(), objetivo or "educar")
    fmt = (formato or "carrossel").lower()
    system = G["brief_system"]
    _seg = (company.get("segment") or "").strip() or "empresa brasileira"   # do CADASTRO — nunca hardcode de outra marca
    base = (f'Empresa: {company.get("name","")} — {_seg}. '
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
    # VÍDEO → MESMA engine da GERAÇÃO (build_video_storyboard): respeita a duração escolhida (8/15/30/60s),
    # SÓ cena visual (sem texto na tela), ancorada no produto/KB real. O roteiro mostrado = o que VAI gerar.
    if fmt in ("video", "vídeo", "reel", "reels"):
        import math as _m
        mx = video_model_max_seconds()
        try:
            target = int(float(seconds or 0))
        except Exception:
            target = 0
        if target > 0:
            per = max(1, min(mx, target, 12)); n_want = max(1, min(8, _m.ceil(target / per)))
        else:
            per, n_want = (mx or 8), 1            # sem duração → 1 cena concisa (custo mínimo no preview)
        sb = build_video_storyboard(company, theme, theme, target, n_want, per)
        linhas = [f"GRANDE IDEIA: {theme}",
                  (f"Roteiro p/ ~{target or per}s · {len(sb)} cena(s) · SÓ imagem em movimento — "
                   "texto, locução, marca e CTA entram na PÓS (o modelo de vídeo NÃO escreve)."), ""]
        for i, s in enumerate(sb, 1):
            linhas.append(f"Cena {i} ({s.get('seconds','')}s): {(s.get('desc') or '').strip()}")
        _ap = {}
        try:                                              # mostra o ÁUDIO que o briefing pediu (narração/trilha)
            _ap = build_video_audio_plan(company, theme, theme, target or (n_want * per)) or {}
            _am = _ap.get("mode")
            if _am == "narration":
                linhas += ["", '🔊 Narração: "' + (_ap.get("script") or "")[:400] + '"']
            elif _am == "both":
                linhas += ["", '🔊 Narração + trilha: "' + (_ap.get("script") or "")[:400] + '"']
            elif _am == "music":
                linhas += ["", "🔊 Trilha: " + (_ap.get("music") or "")[:160]]
            elif _am == "none":
                linhas += ["", "🔇 Sem som (mudo)"]
        except Exception:
            pass
        return {"formato": fmt, "telas": [], "storyboard": [s.get("prompt") for s in sb],
                "scene_seconds": [s.get("seconds") for s in sb], "audio_plan": _ap,
                "text": "\n".join(linhas).strip()}
    # POST/PAUTA em prosa (fallback)
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
    audience = (bk.get("audience") or "o público-alvo da marca").strip()
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
    kb_line = (("CONHECIMENTO REAL DAS OFERTAS EM FOCO — produtos/serviços/procedimentos (baseie o conteúdo NESTES fatos — específico e profundo, "
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
    apps_line = ("OFERTAS desta empresa — produtos/serviços/procedimentos (use SOMENTE estes no campo 'app', nome EXATO): "
                 + ", ".join(_apps) + ". Em CADA slide de CONTEÚDO que trate de uma oferta, preencha 'app' com a oferta "
                 "MAIS relevante daquele slide e DISTRIBUA as ofertas citadas no tema entre as telas (não deixe 'app' "
                 "vazio quando a tela é sobre uma oferta). Telas de conceito geral podem ficar com 'app' vazio. ") if _apps else ""
    cover_line = (f"COBERTURA OBRIGATÓRIA: o tema cita estas ofertas → {', '.join(themed)}. CADA uma precisa de PELO "
                  f"MENOS 1 slide de conteúdo dedicado, E aparecer no CTA. NÃO pule NENHUMA — nem a que parecer menos "
                  f"óbvia pro tema: ache o ângulo certo dela dentro do tema. ") if themed else ""
    # LEAD por MODO: em 'criativo' a CENA/IDEIA do usuário é a ESTRELA (newsjacking) e a marca é só
    # contexto leve — NÃO reescrever o assunto como pauta institucional de ISP. Em produtos/evento,
    # mantém o enquadramento aprovado (empresa vende SVAs p/ provedores).
    _name = company.get('name', '')
    if intent == "criativo":
        lead = (f"MODO CRIATIVO / NEWSJACKING — a CENA/IDEIA do usuário é a ESTRELA e deve ser retratada "
                f"FIELMENTE, SEM virar pauta institucional de provedor/ISP nem 'grande ideia' corporativa. "
                f"Marca só como contexto leve para assinatura + CTA (NÃO é o assunto): {_name}. Público: {audience}. ")
        theme_kw = "CENA/IDEIA (retrate FIELMENTE, não reescreva)"
    else:
        _seg = (company.get("segment") or "").strip() or "empresa brasileira"   # do CADASTRO — sem cara de CARIAP
        lead = (f"Empresa: {_name} — {_seg}. "
                f"Público (fale COM ele): {audience}. ")
        theme_kw = "Tema"
    # NOMES EXATOS: dos PRODUTOS desta empresa (dinâmico) — o default G["name_rule"] citava apps da CARIAP e
    # vazaria identidade pra outros clientes. Sem produtos → sem regra (nunca nomes de outra marca).
    _nrule = ("NOMES EXATOS E OBRIGATÓRIOS (nunca abrevie/erre): " + ", ".join(_apps) + ". ") if _apps else ""
    if single:
        # ARTE ÚNICA: UMA peça completa (mensagem + CTA), estrutura própria, sem regras de carrossel.
        user = (
            lead + f"{theme_kw}: {theme}. "
            + event_line + apps_line + kb_line + web_line + excl_line
            + (f"Regras do cliente (obedeça): {rules}. " if rules else "")
            + G["single_json_format"] + G["visual_rule"] + G["app_rule"] + _nrule + G["content_rules"]
        )
    else:
        user = (
            lead + f"{theme_kw} do carrossel: {theme}. {n_rule} "
            + event_line + apps_line + cover_line + kb_line + web_line + excl_line
            + (f"Regras do cliente (obedeça): {rules}. " if rules else "")
            + G["json_format"] + G["visual_rule"] + G["app_rule"] + _nrule
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
        # MOTOR CRIATIVO (biblioteca de padrões) ainda EM CONSTRUÇÃO → DESLIGADO por padrão. Só liga quando
        # `creative.free_engine` estiver on (setting). Assim carrossel/Produtos/clientes futuros ficam 100% intactos.
        if intent == "criativo" and (get_setting("creative.free_engine") or "").strip().lower() in ("1", "true", "on", "yes"):
            s0["free_text"] = True   # ARTE LIVRE: motor de padrões (quando ligado)
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
