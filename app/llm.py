from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

import httpx

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

ProviderName = Literal["ollama", "deepseek", "grok", "gemini", "openai", "openrouter"]


@dataclass
class ProviderSpec:
    name: ProviderName
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None


async def stream_ollama(
    *,
    prompt: str,
    model: str,
    base_url: str = "http://127.0.0.1:11434",
    options: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream tokens from Ollama via /api/generate.

    Yields dict events: {type: 'delta'|'done'|'error', ...}
    """
    url = base_url.rstrip("/") + "/api/generate"

    # Estimate ~1.5 tokens per word; clamp prompt to 3800 tokens to stay inside
    # most local models' 4096-token context without truncation.
    _words = prompt.split()
    _max_words = int(3800 / 1.5)
    if len(_words) > _max_words:
        prompt = " ".join(_words[:_max_words])

    import multiprocessing as _mp
    _ncpu = _mp.cpu_count()
    # leave half the cores free so online-provider requests aren't starved
    _threads = max(4, _ncpu // 2)

    base_options: Dict[str, Any] = {
        "num_ctx": 4096,    # explicit context window
        "num_predict": 500, # reduced from 1024 — cuts wait time ~50% on CPU
        "num_thread": _threads,  # cap CPU threads so other requests stay responsive
    }
    if options:
        base_options.update(options)

    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": base_options,
    }

    # 600 s — 7B CPU @ 3 tok/s × 500 tokens ≈ 3 min; leave margin
    timeout = httpx.Timeout(600.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", url, json=payload) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    try:
                        msg = json.loads(body).get("error") or body.decode("utf-8", errors="replace")[:400]
                    except Exception:
                        msg = body.decode("utf-8", errors="replace")[:400]
                    yield {"type": "error", "error": f"Ollama {r.status_code}: {msg}"}
                    return
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    if obj.get("done") is True:
                        yield {"type": "done", "raw": obj}
                        return

                    delta = obj.get("response")
                    if delta:
                        yield {"type": "delta", "delta": delta}

        except Exception as e:
            yield {"type": "error", "error": repr(e)}


async def stream_openai_compatible(
    *,
    prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    params: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream tokens from an OpenAI-compatible Chat Completions API.

    Supports OpenAI and DeepSeek (OpenAI-compatible).
    """

    params = params or {}
    url = base_url.rstrip("/") + "/v1/chat/completions"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    for k in ("temperature", "top_p", "max_tokens"):
        if k in params and params[k] is not None:
            payload[k] = params[k]

    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }

    timeout = httpx.Timeout(120.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    yield {"type": "error", "error": f"HTTP {r.status_code}: {body.decode('utf-8', errors='replace')[:400]}"}
                    return
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        yield {"type": "done"}
                        return
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue

                    # Standard OpenAI SSE schema
                    delta = (
                        (obj.get("choices") or [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        yield {"type": "delta", "delta": delta}

        except Exception as e:
            yield {"type": "error", "error": repr(e)}


async def stream_provider(
    *,
    spec: ProviderSpec,
    prompt: str,
    params: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    params = params or {}

    if spec.name == "ollama":
        options = {}
        # Map generic params to ollama options
        if "temperature" in params:
            options["temperature"] = params["temperature"]
        if "top_p" in params:
            options["top_p"] = params["top_p"]
        if "max_tokens" in params:
            options["num_predict"] = params["max_tokens"]

        async for ev in stream_ollama(
            prompt=prompt,
            model=spec.model,
            base_url=spec.base_url or _OLLAMA_BASE_URL,
            options=options or None,
        ):
            yield ev
        return

    if spec.name in ("openai", "deepseek", "openrouter", "grok", "gemini"):
        if not spec.api_key:
            yield {"type": "error", "error": "missing_api_key"}
            return

        _default_bases = {
            "openai":      "https://api.openai.com",
            "deepseek":    "https://api.deepseek.com",
            "openrouter":  "https://openrouter.ai/api",
            "grok":        "https://api.x.ai",
            "gemini":      "https://generativelanguage.googleapis.com/v1beta/openai",
        }
        default_base = _default_bases[spec.name]
        async for ev in stream_openai_compatible(
            prompt=prompt,
            model=spec.model,
            api_key=spec.api_key,
            base_url=spec.base_url or default_base,
            params=params,
        ):
            yield ev
        return

    # placeholders for other external providers
    yield {"type": "error", "error": f"provider_not_implemented:{spec.name}"}


async def merge_streams(
    *,
    prompt: str,
    providers: List[ProviderSpec],
    params: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Merge multiple provider streams into a single async generator.

    Emits events with: provider_index, provider_name, ...
    """

    queue: asyncio.Queue = asyncio.Queue()

    async def _run_one(idx: int, spec: ProviderSpec):
        await queue.put(
            {
                "event": "provider_start",
                "provider_index": idx,
                "provider": spec.name,
                "model": spec.model,
            }
        )
        async for ev in stream_provider(spec=spec, prompt=prompt, params=params):
            t = ev.get("type")
            if t == "delta":
                await queue.put(
                    {
                        "event": "delta",
                        "provider_index": idx,
                        "provider": spec.name,
                        "delta": ev.get("delta", ""),
                    }
                )
            elif t == "done":
                await queue.put(
                    {
                        "event": "provider_done",
                        "provider_index": idx,
                        "provider": spec.name,
                    }
                )
                break
            else:
                await queue.put(
                    {
                        "event": "error",
                        "provider_index": idx,
                        "provider": spec.name,
                        "error": ev.get("error"),
                    }
                )
                break

    tasks = [asyncio.create_task(_run_one(i, p)) for i, p in enumerate(providers)]

    done_count = 0
    total = len(tasks)
    while done_count < total:
        msg = await queue.get()
        yield msg
        if msg.get("event") in ("provider_done", "error"):
            done_count += 1

    for t in tasks:
        if not t.done():
            t.cancel()


async def run_providers_to_completion(
    *,
    prompt: str,
    providers: List[ProviderSpec],
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Non-streaming helper for UX + n8n.

    Uses merge_streams under the hood and returns final text per provider.

    Returns list in same order as providers:
    [{ provider, model, ok, text, error, events_count }]
    """

    texts = [""] * len(providers)
    errors: List[Optional[str]] = [None] * len(providers)
    done: List[bool] = [False] * len(providers)
    events_count = [0] * len(providers)

    async for msg in merge_streams(prompt=prompt, providers=providers, params=params):
        idx = int(msg.get("provider_index", 0))
        events_count[idx] += 1
        ev = msg.get("event")
        if ev == "delta":
            texts[idx] += msg.get("delta", "")
        elif ev == "error":
            errors[idx] = msg.get("error")
            done[idx] = True
        elif ev == "provider_done":
            done[idx] = True

    out: List[Dict[str, Any]] = []
    for i, p in enumerate(providers):
        ok = errors[i] is None
        out.append(
            {
                "provider": p.name,
                "model": p.model,
                "ok": ok,
                "text": texts[i],
                "error": errors[i],
                "events_count": events_count[i],
            }
        )
    return out
