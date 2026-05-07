from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..db import async_job_get, async_job_put, insert_run, settings_get
from ..db_agency import creator_get
from ..llm import ProviderSpec, run_providers_to_completion

ASYNC_KIND = "auto_editor"


def _model_dump(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if hasattr(obj, "dict"):
        return obj.dict(exclude_none=True)
    return dict(obj or {})


def _job_put(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return async_job_put(kind=ASYNC_KIND, job_id=job_id, payload=payload)


def _job_patch(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    current = async_job_get(kind=ASYNC_KIND, job_id=job_id) or {}
    merged = dict(current)
    merged.update(patch or {})
    return _job_put(job_id, merged)


def _get_grok_provider() -> tuple[Optional[ProviderSpec], Optional[str]]:
    saved = settings_get(key="token:grok") or {}
    api_key = str(saved.get("value") or "").strip()
    if not api_key:
        return None, "token:grok não configurado"
    model = str(saved.get("model") or "grok-4").strip() or "grok-4"
    base_url = str(saved.get("base_url") or "").strip() or None
    return (
        ProviderSpec(
            name="grok",
            model=model,
            api_key=api_key,
            base_url=base_url,
        ),
        None,
    )


def _scene_excerpt(segments: List[Dict[str, Any]], start: float, end: float, *, max_chars: int = 220) -> str:
    if not segments:
        return ""
    parts: List[str] = []
    for seg in segments:
        try:
            seg_start = float(seg.get("start") or 0.0)
            seg_end = float(seg.get("end") or 0.0)
        except Exception:
            continue
        if seg_end < start or seg_start > end:
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            parts.append(text)
        joined = " ".join(parts).strip()
        if len(joined) >= max_chars:
            return joined[:max_chars].rstrip() + "…"
    return " ".join(parts).strip()[:max_chars]


def _coerce_source_keys(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for raw in list(payload.get("video_object_keys") or []) + [payload.get("video_object_key")]:
        value = str(raw or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _vision_scene_excerpt(scene: Dict[str, Any], *, max_chars: int = 220) -> str:
    parts: List[str] = []
    for key in ("position", "acts", "body_parts", "context"):
        value = scene.get(key)
        if isinstance(value, list):
            cleaned = [str(item or "").strip() for item in value if str(item or "").strip()]
            if cleaned:
                parts.append(", ".join(cleaned))
        else:
            text = str(value or "").strip()
            if text:
                parts.append(text)
    excerpt = " | ".join(parts).strip()
    return excerpt[:max_chars]


def _enrich_candidates_with_vision(
    *,
    candidates: List[Dict[str, Any]],
    vision_analysis: Optional[Dict[str, Any]],
    frame_timestamps: List[float],
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    scenes = list((vision_analysis or {}).get("scenes") or [])
    mapped_scenes: List[Dict[str, Any]] = []
    for raw in scenes:
        try:
            frame_index = int(raw.get("frame_index"))
        except Exception:
            continue
        if frame_index < 0 or frame_index >= len(frame_timestamps):
            continue
        excerpt = _vision_scene_excerpt(raw)
        acts = raw.get("acts") or []
        if isinstance(acts, str):
            acts = [acts]
        body_parts = raw.get("body_parts") or []
        if isinstance(body_parts, str):
            body_parts = [body_parts]
        weight = 1.0 + (0.15 * min(4, len([x for x in acts if str(x).strip()]))) + (0.05 * min(4, len([x for x in body_parts if str(x).strip()])))
        mapped_scenes.append({
            "timestamp": float(frame_timestamps[frame_index]),
            "excerpt": excerpt,
            "weight": weight,
        })

    if not mapped_scenes:
        return [dict(item, vision_excerpt="", vision_relevance=0.0) for item in candidates]

    enriched: List[Dict[str, Any]] = []
    for item in candidates:
        scene = dict(item)
        start = float(scene.get("start") or 0.0)
        end = float(scene.get("end") or start)
        midpoint = start + ((end - start) / 2.0)
        match_window = max(10.0, min(35.0, (end - start) * 0.55))
        matches = [
            hit for hit in mapped_scenes
            if (start - 6.0) <= float(hit["timestamp"]) <= (end + 6.0)
            or abs(float(hit["timestamp"]) - midpoint) <= match_window
        ]

        if matches:
            best = sorted(matches, key=lambda hit: (hit["weight"], -abs(float(hit["timestamp"]) - midpoint)), reverse=True)[0]
            vision_boost = min(0.38, 0.12 + (0.06 * (len(matches) - 1)) + (0.05 * float(best["weight"])))
            scene["score"] = round(min(1.0, float(scene.get("score") or 0.0) + vision_boost), 4)
            scene["vision_excerpt"] = str(best.get("excerpt") or "")
            scene["vision_relevance"] = round(vision_boost, 4)
        else:
            scene["vision_excerpt"] = ""
            scene["vision_relevance"] = 0.0

        enriched.append(scene)
    return enriched


def _build_scene_candidates(
    *,
    duration: float,
    cut_points: List[float],
    min_scene_duration: float,
    max_scene_duration: float,
    transcript_segments: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build scene candidates from scene cut points.

    Clips use their NATURAL duration from scene detection — we do NOT inflate
    short clips to min_scene_duration. min_scene_duration is only used to filter
    out truly micro-segments (<3s) that would be unusable. The LLM sees real cuts.
    """
    transcript_segments = transcript_segments or []
    # Minimum clip we'll ever pass to LLM — 12s eliminates micro-cuts before LLM
    _HARD_MIN = 12.0

    bounded = [0.0]
    for raw in sorted(cut_points):
        t = max(0.0, min(duration, float(raw or 0.0)))
        if t <= 0.0 or t >= duration:
            continue
        if abs(t - bounded[-1]) < 1.0:
            continue
        bounded.append(t)
    if duration > 0:
        bounded.append(duration)

    candidates: List[Dict[str, Any]] = []

    for idx in range(max(0, len(bounded) - 1)):
        seg_start = bounded[idx]
        seg_end = bounded[idx + 1]
        raw_duration = max(0.0, seg_end - seg_start)

        # Skip only truly unusable micro-segments
        if raw_duration < _HARD_MIN:
            continue

        # Respect max_scene_duration by trimming from center — but never inflate
        if raw_duration > max_scene_duration:
            clip_duration = max_scene_duration
            clip_start = seg_start + ((raw_duration - clip_duration) / 2.0)
        else:
            clip_duration = raw_duration
            clip_start = seg_start

        clip_end = min(duration, clip_start + clip_duration)
        clip_duration = max(0.0, clip_end - clip_start)
        midpoint = clip_start + (clip_duration / 2.0)

        # Score: duration weighted higher (0.70) to favor longer natural takes
        ideal = min(30.0, max_scene_duration * 0.3)
        duration_score = 1.0 - min(abs(clip_duration - ideal) / max(ideal, 1.0), 1.0)
        center_score = 1.0 - abs((midpoint / max(duration, 1.0)) - 0.5)
        edge_penalty = 0.15 if clip_start < 5.0 or clip_end > max(0.0, duration - 5.0) else 0.0
        score = round((duration_score * 0.70) + (center_score * 0.15) - edge_penalty, 4)

        candidates.append({
            "scene_index": idx,
            "start": round(clip_start, 3),
            "end": round(clip_end, 3),
            "duration": round(clip_duration, 3),
            "score": score,
            "transcript_excerpt": _scene_excerpt(transcript_segments, clip_start, clip_end),
            "selected": False,
        })

    if len(candidates) >= 6:
        return candidates

    # Fallback evenly spaced if scene detection returned too little.
    fallback_count = max(6, min(24, int(duration / 30.0) or 6))
    step = duration / max(fallback_count, 1)
    out: List[Dict[str, Any]] = []
    for idx in range(fallback_count):
        clip_duration = min(max_scene_duration, step * 0.85)
        clip_start = max(0.0, min(duration - clip_duration, (idx * step) + ((step - clip_duration) / 2.0)))
        clip_end = min(duration, clip_start + clip_duration)
        out.append({
            "scene_index": idx,
            "start": round(clip_start, 3),
            "end": round(clip_end, 3),
            "duration": round(clip_end - clip_start, 3),
            "score": round(0.5 + ((idx % 3) * 0.08), 4),
            "transcript_excerpt": _scene_excerpt(transcript_segments, clip_start, clip_end),
            "selected": False,
        })
    return out


def _heuristic_select_scenes(
    *,
    candidates: List[Dict[str, Any]],
    duration: float,
    max_scenes: int,
    quality_threshold: float = 0.35,
) -> List[Dict[str, Any]]:
    """Select scenes based on quality score with temporal coverage guarantee.

    Divides the timeline into buckets (1 per ~2 min) and picks the best scene
    per bucket to ensure coverage across the whole video, then fills remaining
    slots with highest-scoring scenes.

    Minimum scenes floor: at least 1 scene per 3 minutes of content.
    """
    if not candidates:
        return []
    # Dynamic floor: at least 1 scene per 3 minutes of content
    min_scenes_floor = max(6, int(duration / 180.0))
    effective_max = max(min_scenes_floor, max_scenes, 1)
    effective_max = min(effective_max, len(candidates))

    # Bucket every ~2 minutes for good coverage
    bucket_count = max(4, min(effective_max, max(1, int(duration / 120.0))))
    bucket_size = duration / max(bucket_count, 1)

    chosen_ids: set[int] = set()
    selected: List[Dict[str, Any]] = []

    # Pick best scene from each temporal bucket (ensures spread across timeline)
    for bucket in range(bucket_count):
        start = bucket * bucket_size
        end = duration if bucket == bucket_count - 1 else (bucket + 1) * bucket_size
        bucket_items = [c for c in candidates if start <= ((c["start"] + c["end"]) / 2.0) < end]
        if not bucket_items:
            continue
        best = sorted(bucket_items, key=lambda item: (item["score"], item["duration"]), reverse=True)[0]
        if best["scene_index"] in chosen_ids:
            continue
        chosen_ids.add(best["scene_index"])
        selected.append(dict(best))
        if len(selected) >= effective_max:
            break

    # Fill remaining slots with highest-scoring scenes above quality threshold
    for item in sorted(candidates, key=lambda c: (c["score"], c["duration"]), reverse=True):
        if item["scene_index"] in chosen_ids:
            continue
        if len(selected) >= effective_max:
            break
        if float(item.get("score") or 0.0) < quality_threshold and len(selected) >= min_scenes_floor:
            continue
        selected.append(dict(item))
        chosen_ids.add(item["scene_index"])

    selected = sorted(selected, key=lambda c: c["start"])
    for item in selected:
        item["selected"] = True
    return selected


_EQUIPMENT_KEYWORDS = [
    "câmera", "camera", "tripé", "tripod", "equipamento", "equipment",
    "microfone", "microphone", "luz de estúdio", "ring light", "bastidor",
    "filmagem", "filming setup", "production crew", "behind the scenes",
]


def _filter_equipment_scenes(selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove scenes where vision_excerpt mentions filming equipment."""
    clean = []
    for s in selected:
        excerpt = str(s.get("vision_excerpt") or "").lower()
        if any(kw in excerpt for kw in _EQUIPMENT_KEYWORDS):
            continue
        clean.append(s)
    return clean


async def _build_timelapse_opener(
    selected: List[Dict[str, Any]],
    source_map: Dict[int, Dict[str, Any]],
    td: str,
    max_height: int,
    crf: int,
    semaphore: asyncio.Semaphore,
) -> List[str]:
    """Extract 2.5s center crops from top-8 scenes (by vision_relevance), speed up 2x.

    Returns list of teaser clip paths to prepend before the main edit.
    Total duration: up to 8 × ~1.25s ≈ 10s opener.
    """
    top = sorted(selected, key=lambda s: float(s.get("vision_relevance") or 0), reverse=True)[:8]
    teaser_clips: List[str] = []
    for i, s in enumerate(top):
        entry = source_map.get(int(s.get("source_index") or 0))
        if not entry:
            continue
        src_start = float(s.get("source_start") or s.get("start") or 0)
        src_end = float(s.get("source_end") or s.get("end") or 0)
        center = (src_start + src_end) / 2.0
        t_start = max(0.0, center - 1.25)
        out = os.path.join(td, f"teaser_{i:02d}.mp4")
        probe = dict(entry.get("probe") or {})
        src_has_audio = bool(probe.get("has_audio"))
        vf = _build_video_filter(max_height=max_height, target_fps=25, source_probe=probe)
        vf += ",setpts=0.5*PTS"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{t_start:.3f}", "-i", entry["path"],
        ]
        if not src_has_audio:
            cmd += ["-f", "lavfi", "-t", "2.5", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += [
            "-t", "2.5",
            "-map", "0:v:0",
            "-map", "1:a:0" if not src_has_audio else "0:a:0?",
            "-vf", vf,
            "-af", "atempo=2.0",
            "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "48000", "-ac", "2",
            "-shortest",
            out,
        ]
        async with semaphore:
            result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True)
        if os.path.exists(out) and os.path.getsize(out) > 1000 and _probe_clip_valid(out):
            teaser_clips.append(out)
        elif result.returncode != 0:
            print(f"[timelapse] clip {i} falhou rc={result.returncode}: {(result.stderr or b'')[-200:].decode('utf-8','replace')}", flush=True)
    return teaser_clips


def _merge_adjacent_candidates(
    candidates: List[Dict[str, Any]],
    gap_threshold: float = 5.0,
    max_merge_duration: float = 120.0,
) -> List[Dict[str, Any]]:
    """Merge consecutive same-source candidates separated by <= gap_threshold seconds.

    Prevents Grok from receiving dozens of 3-8s micro-segments that lead to
    micro-cut output videos. Merged candidate keeps best score/vision_relevance.
    """
    if not candidates:
        return candidates
    sorted_cands = sorted(candidates, key=lambda x: (int(x.get("source_index") or 0), float(x.get("source_start") or x.get("start") or 0)))
    merged: List[Dict[str, Any]] = []
    for c in sorted_cands:
        c_start = float(c.get("source_start") or c.get("start") or 0)
        c_end = float(c.get("source_end") or c.get("end") or 0)
        if (
            merged
            and int(merged[-1].get("source_index") or 0) == int(c.get("source_index") or 0)
            and c_start - float(merged[-1].get("source_end") or merged[-1].get("end") or 0) <= gap_threshold
            and (c_end - float(merged[-1].get("source_start") or merged[-1].get("start") or 0)) <= max_merge_duration
        ):
            prev = merged[-1]
            new_end = c_end
            new_dur = new_end - float(prev.get("source_start") or prev.get("start") or 0)
            prev["source_end"] = new_end
            prev["end"] = float(prev.get("start") or 0) + new_dur if "start" in prev else new_end
            prev["duration"] = round(new_dur, 3)
            prev["score"] = round(max(float(prev.get("score") or 0), float(c.get("score") or 0)), 4)
            prev["vision_relevance"] = round(max(float(prev.get("vision_relevance") or 0), float(c.get("vision_relevance") or 0)), 4)
            if not prev.get("vision_excerpt") and c.get("vision_excerpt"):
                prev["vision_excerpt"] = c["vision_excerpt"]
        else:
            merged.append(dict(c))
    # Re-index scene_index sequentially after merging
    for i, item in enumerate(merged):
        item["scene_index"] = i
    return merged


def _default_narrative_rules(n_sources: int = 1) -> str:
    return (
        "═══ CRITÉRIOS DE SELEÇÃO ═══\n\n"
        "Você está montando um vídeo adulto longo. Cada candidato é um trecho contínuo de ação. "
        "Selecione os melhores trechos com base no conteúdo visual (vision_excerpt) e no score.\n\n"
        "PRIORIZAR:\n"
        "- Penetração ativa (vaginal, anal, oral) com boa qualidade visual e reações das performers\n"
        "- Variedade de posições e ângulos entre as cenas selecionadas\n"
        "- Apresentação das performers (se aparecer naturalmente no início)\n"
        "- Cena de gozada — OBRIGATÓRIO incluir ao menos UMA (is_gozada_candidate=true)\n\n"
        "REJEITAR:\n"
        "- Cenas de troca de posição sem ação (transição entre poses)\n"
        "- Aplicação de gel, lubrificante, ajuste de brinquedos ou acessórios\n"
        "- Cenas paradas, sem movimento ou de qualidade visual baixa\n"
        "- Cenas fora de foco, com iluminação inadequada ou performers saindo de quadro\n"
        "⚠️ PROIBIDO: NUNCA selecionar cenas onde equipamento de filmagem esteja visível "
        "(câmera, tripé, cabos, refletor, microfone, iluminador)\n\n"
        "═══ REGRAS DE COBERTURA ═══\n"
        f"- Existem {n_sources} vídeos de origem (source_index 0 a {n_sources - 1}). "
        "OBRIGATÓRIO selecionar cenas de TODOS os source_index disponíveis.\n"
        "- Cenas com is_gozada_candidate=true são do final do último vídeo — "
        "OBRIGATÓRIO incluir ao menos UMA como cena final.\n"
        "- Respeite a ordem temporal DENTRO de cada vídeo (source_index igual).\n"
        "- Selecione todas as cenas boas disponíveis — não limite artificialmente.\n\n"
    )


async def _llm_select_scenes_grok(
    *,
    candidates: List[Dict[str, Any]],
    max_scenes: int,
    vision_analysis: Optional[Dict[str, Any]] = None,
    channel_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    provider, provider_error = _get_grok_provider()
    if provider_error:
        return {"indexes": None, "error": provider_error, "provider": "grok"}
    if not provider or not candidates:
        return {"indexes": None, "error": "grok indisponível", "provider": "grok"}

    # Pre-filter: keep top candidates per source_index to ensure all videos are covered.
    # Without this, with 11 videos × 50 candidates, [:80] would only show ~1.5 videos.
    _PER_SOURCE_MAX = 15
    by_src: Dict[int, List[Dict[str, Any]]] = {}
    for item in candidates:
        src = int(item.get("source_index") or 0)
        by_src.setdefault(src, []).append(item)
    all_source_ids = sorted(by_src.keys())
    n_sources = len(all_source_ids)

    # Always include last 90s of last source as gozada candidates (high priority)
    last_src_id = all_source_ids[-1] if all_source_ids else 0
    last_src_cands = by_src.get(last_src_id, [])
    last_src_duration = max((float(c.get("source_end") or c.get("end") or 0) for c in last_src_cands), default=0)
    for c in last_src_cands:
        seg_start = float(c.get("source_start") or c.get("start") or 0)
        if last_src_duration > 0 and seg_start >= last_src_duration - 90:
            c = dict(c)
            c["is_gozada_candidate"] = True

    filtered_per_src: List[Dict[str, Any]] = []
    for src_id in all_source_ids:
        src_cands = sorted(by_src[src_id], key=lambda c: -float(c.get("score") or 0))
        filtered_per_src.extend(src_cands[:_PER_SOURCE_MAX])

    compact = []
    for item in filtered_per_src:
        compact.append({
            "scene_index": item["scene_index"],
            "source_index": item.get("source_index", 0),
            "source_time_start": round(float(item.get("source_start") or item["start"]), 1),
            "source_time_end": round(float(item.get("source_end") or item["end"]), 1),
            "duration": round(float(item["duration"]), 1),
            "score": item["score"],
            "vision_relevance": round(float(item.get("vision_relevance") or 0), 2),
            "is_gozada_candidate": bool(item.get("is_gozada_candidate")),
            "vision_excerpt": item.get("vision_excerpt", "")[:120],
        })

    vision_summary = ""
    if vision_analysis:
        vision_summary = (
            "\nResumo consolidado da Vision:\n"
            + json.dumps({
                "description": str(vision_analysis.get("description") or "")[:500],
                "categories": list(vision_analysis.get("categories") or [])[:10],
                "tags": list(vision_analysis.get("tags") or [])[:18],
                "performers": vision_analysis.get("performers") or {},
                "scenes": list(vision_analysis.get("scenes") or [])[:6],
            }, ensure_ascii=False)
            + "\n"
        )

    channel_context = str((channel_profile or {}).get("channel_context") or "").strip()

    # Load prompt from DB if user has customized it, otherwise use default
    _custom_rules = (settings_get(key="ae_narrative_rules") or {}).get("value") or None
    if _custom_rules:
        narrative_rules = _custom_rules.replace("{n_sources}", str(n_sources)).replace("{n_sources_minus1}", str(n_sources - 1))
    else:
        narrative_rules = _default_narrative_rules(n_sources=n_sources)

    prompt = (
        "Você é um editor profissional de vídeos adultos. Sua missão é montar o melhor corte possível respeitando "
        "as regras de narrativa abaixo.\n\n"
        + (channel_context + "\n\n" if channel_context else "")
        + narrative_rules
        + f"Máximo de cenas no corte final: {max_scenes}\n"
        + "Retorne SOMENTE JSON válido no formato "
        + '{"scenes_to_keep":[1,2,3],"narrative_structure":{"intro":[],"prelim":[],"sex":[],"cumshot":[]},"reason":"..."}.\n\n'
        + vision_summary
        + "Cenas candidatas:\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    try:
        results = await run_providers_to_completion(
            prompt=prompt,
            providers=[provider],
            params={"temperature": 0.2, "max_tokens": 2400},
        )
        if not results:
            return {"indexes": None, "error": "Grok não retornou resposta", "provider": "grok"}
        first = results[0]
        if not first.get("ok"):
            return {"indexes": None, "error": str(first.get("error") or "Grok falhou"), "provider": "grok"}
        raw = str(results[0].get("text") or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
        parsed = json.loads(raw)
        indexes = parsed.get("scenes_to_keep")
        if not isinstance(indexes, list):
            indexes = parsed.get("selected_indexes", [])
        if not isinstance(indexes, list):
            return {"indexes": None, "error": "JSON do Grok sem scenes_to_keep", "provider": "grok"}
        out: List[int] = []
        for idx in indexes:
            try:
                out.append(int(idx))
            except Exception:
                continue
        return {
            "indexes": out or None,
            "error": None if out else "Grok retornou lista vazia",
            "provider": "grok",
            "reason": str(parsed.get("reason") or "").strip(),
        }
    except Exception as exc:
        return {"indexes": None, "error": str(exc), "provider": "grok"}


async def _fetch_creator_channel_profile(
    creator: Optional[Dict[str, Any]],
    *,
    videos_per_channel: int = 5,
) -> Dict[str, Any]:
    """Disabled: XVideos reference fetch temporarily disabled due to instability."""
    return {}

    own_channel_urls: List[str] = list(creator.get("own_channel_urls") or [])
    reference_channels: List[str] = list(creator.get("reference_channels") or [])

    # Build list of (type, name_or_url) to try
    channels_to_try: List[tuple] = []
    for url in own_channel_urls:
        url = str(url or "").strip()
        if url:
            channels_to_try.append(("channel_url", url))
    for ref in reference_channels:
        ref = str(ref or "").strip()
        if ref:
            channels_to_try.append(("channel_name", ref))

    if not channels_to_try:
        return {}

    from ..xvideos_source import fetch_channel_videos

    all_videos: List[Dict[str, Any]] = []
    for channel_type, channel_ref in channels_to_try[:3]:  # max 3 channels
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(fetch_channel_videos, channel_ref, videos_per_channel),
                timeout=20.0,
            )
            videos = list((result or {}).get("videos") or [])
            all_videos.extend(videos)
        except (asyncio.TimeoutError, Exception) as e:
            print(f"[auto-editor] creator channel fetch failed ({channel_ref}): {e}", flush=True)
            continue

    if not all_videos:
        return {}

    # Aggregate categories and tags
    from collections import Counter
    cat_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    titles: List[str] = []

    for v in all_videos:
        for tag in list(v.get("tags") or []):
            tag_counter[str(tag).lower().strip()] += 1
        title = str(v.get("title") or "").strip()
        if title:
            titles.append(title)
        # Infer categories from tags
        tag_str = " ".join(str(t).lower() for t in (v.get("tags") or []))
        if any(w in tag_str for w in ["anal", "ass fuck", "anal sex"]):
            cat_counter["anal"] += 2
        if any(w in tag_str for w in ["blowjob", "oral", "deepthroat"]):
            cat_counter["oral"] += 1
        if any(w in tag_str for w in ["threesome", "3some", "ffm", "mmf"]):
            cat_counter["threesome"] += 2
        if any(w in tag_str for w in ["solo", "masturbat"]):
            cat_counter["solo"] += 2
        if any(w in tag_str for w in ["lesbian"]):
            cat_counter["lesbian"] += 2
        if any(w in tag_str for w in ["pov"]):
            cat_counter["pov"] += 1
        if any(w in tag_str for w in ["squirt"]):
            cat_counter["squirt"] += 2
        if any(w in tag_str for w in ["creampie"]):
            cat_counter["creampie"] += 2

    top_categories = [cat for cat, _ in cat_counter.most_common(5)]
    top_tags = [tag for tag, _ in tag_counter.most_common(10)]
    dominant_category = top_categories[0] if top_categories else "vaginal"

    # Build editing profile based on dominant category
    category_profiles = {
        "anal": (
            "PERFIL DO CRIADOR: conteúdo majoritariamente ANAL. "
            "Regra especial: começar pelo anal direto, sem necessidade de vaginal primeiro. "
            "Focar em penetração anal, close no ânus, reações. "
            "Gozada: preferencialmente no ânus ou nas nádegas."
        ),
        "oral": (
            "PERFIL DO CRIADOR: conteúdo focado em ORAL/BLOWJOB. "
            "Priorizar cenas de felação, deepthroat e reações faciais. "
            "Gozada facial (cumshot facial) é esperada."
        ),
        "threesome": (
            "PERFIL DO CRIADOR: conteúdo de TRIO/GANGBANG. "
            "Priorizar interações entre múltiplos participantes, diversidade de ângulos e posições simultâneas."
        ),
        "solo": (
            "PERFIL DO CRIADOR: conteúdo SOLO/MASTURBAÇÃO. "
            "Focar na performer solo, close em expressões, brinquedos e orgasmo."
        ),
        "lesbian": (
            "PERFIL DO CRIADOR: conteúdo LÉSBICO. "
            "Priorizar interações entre as performers, tribbing, cunnilingus, brinquedos."
        ),
        "squirt": (
            "PERFIL DO CRIADOR: conteúdo com SQUIRT. "
            "Priorizar cenas que levam ao squirt, dar close no momento do squirt."
        ),
        "vaginal": (
            "PERFIL DO CRIADOR: conteúdo vaginal padrão. "
            "Seguir regras padrão: vaginal primeiro, depois anal se houver."
        ),
    }

    profile_text = category_profiles.get(dominant_category, category_profiles["vaginal"])

    channel_context = (
        f"\n{profile_text}\n"
        f"Categorias detectadas no canal: {', '.join(top_categories) if top_categories else 'n/a'}\n"
        f"Top tags do canal: {', '.join(top_tags[:8]) if top_tags else 'n/a'}\n"
        f"Vídeos de referência analisados: {len(all_videos)}\n"
    )

    return {
        "categories": top_categories,
        "dominant_category": dominant_category,
        "top_tags": top_tags,
        "sample_titles": titles[:5],
        "channel_context": channel_context,
    }


def _ffmpeg_run(cmd: List[str], timeout: int, err_path: str) -> tuple[int, str]:
    with open(err_path, "wb") as ferr:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=ferr,
                timeout=timeout,
            )
            rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            return 124, "timeout"
    try:
        with open(err_path, "rb") as ferr:
            err = ferr.read().decode("utf-8", errors="replace").strip()
    except Exception:
        err = ""
    return rc, err[-600:]


def _build_audio_filter(*, normalize: bool, denoise: bool) -> str:
    filters: List[str] = []
    if denoise:
        filters.append("afftdn=nf=-25")
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    return ",".join(filters)


def _fps_str(value: float) -> str:
    safe = round(float(value or 0.0), 3)
    if safe <= 0:
        return "30"
    if abs(safe - round(safe)) < 0.001:
        return str(int(round(safe)))
    return f"{safe:.3f}".rstrip("0").rstrip(".")


def _normalize_transition_mode(value: Any) -> str:
    mode = str(value or "smart").strip().lower()
    if mode not in {"none", "smart", "always_crossfade"}:
        return "smart"
    return mode


def _normalize_transition_type(value: Any) -> str:
    transition = str(value or "fade").strip().lower()
    allowed = {"fade", "dissolve", "wiperight", "wipeleft", "slideright", "slideleft"}
    return transition if transition in allowed else "fade"


def _build_video_filter(*, max_height: int, target_fps: float, source_probe: Optional[Dict[str, Any]] = None) -> str:
    from .. import main as _main_mod
    filters = []
    if source_probe and _main_mod._is_hdr_source(source_probe):
        filters.append(_main_mod._build_hdr_to_sdr_filter(source_probe))
    filters.append(f"scale=-2:min(ih\\,{max(480, min(int(max_height or 1080), 2160))}):flags=lanczos")
    if target_fps > 0:
        filters.append(f"fps={_fps_str(target_fps)}")
    return ",".join(filters)


def _nearest_scene_change(target: float, scene_changes: List[float], tolerance: float) -> Optional[float]:
    best_value: Optional[float] = None
    best_delta = float(tolerance) + 1.0
    for raw in scene_changes or []:
        try:
            sc = float(raw or 0.0)
        except Exception:
            continue
        delta = abs(sc - float(target or 0.0))
        if delta <= tolerance and delta < best_delta:
            best_value = sc
            best_delta = delta
    return best_value


def _plan_scene_transitions(
    *,
    scenes: List[Dict[str, Any]],
    scene_changes: List[float],
    transition_mode: str,
    smart_cut_tolerance_sec: float,
    min_scene_duration: float,
    source_duration: float,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    planned = [dict(item) for item in sorted(scenes, key=lambda entry: float(entry.get("start") or 0.0))]
    transitions: List[Dict[str, Any]] = []
    if len(planned) <= 1:
        return planned, transitions

    if transition_mode == "none":
        return planned, [{"type": "cut", "index": idx} for idx in range(len(planned) - 1)]

    for idx in range(len(planned) - 1):
        if transition_mode == "always_crossfade":
            transitions.append({"type": "crossfade", "index": idx})
            continue

        current = planned[idx]
        nxt = planned[idx + 1]
        if int(current.get("source_index") or 0) != int(nxt.get("source_index") or 0):
            transitions.append({"type": "crossfade", "index": idx})
            continue
        current_start = float(current.get("start") or 0.0)
        current_end = float(current.get("end") or current_start)
        next_start = float(nxt.get("start") or 0.0)
        next_end = float(nxt.get("end") or next_start)

        natural_cut = False
        options: List[tuple[str, float, float]] = []
        match_current_end = _nearest_scene_change(current_end, scene_changes, smart_cut_tolerance_sec)
        match_next_start = _nearest_scene_change(next_start, scene_changes, smart_cut_tolerance_sec)
        if match_current_end is not None:
            options.append(("current_end", match_current_end, abs(match_current_end - current_end)))
        if match_next_start is not None:
            options.append(("next_start", match_next_start, abs(match_next_start - next_start)))

        for where, candidate, _delta in sorted(options, key=lambda item: item[2]):
            if where == "current_end":
                min_end = current_start + max(0.35, min_scene_duration * 0.25)
                max_end = min(next_start - 0.05, source_duration)
                new_end = max(min_end, min(float(candidate), max_end))
                if new_end < max_end and new_end > current_start + 0.25:
                    delta = new_end - current_end
                    current["end"] = round(new_end, 3)
                    if current.get("source_end") is not None:
                        current["source_end"] = round(float(current.get("source_end") or 0.0) + delta, 3)
                    current["duration"] = round(float(current["end"]) - float(current["start"]), 3)
                    natural_cut = True
                    break
            else:
                min_start = max(current_end + 0.05, 0.0)
                max_start = next_end - max(0.35, min_scene_duration * 0.25)
                new_start = min(max(float(candidate), min_start), max_start)
                if new_start > min_start and new_start < next_end - 0.25:
                    delta = new_start - next_start
                    nxt["start"] = round(new_start, 3)
                    if nxt.get("source_start") is not None:
                        nxt["source_start"] = round(float(nxt.get("source_start") or 0.0) + delta, 3)
                    nxt["duration"] = round(float(nxt["end"]) - float(nxt["start"]), 3)
                    natural_cut = True
                    break

        transitions.append({"type": "cut" if natural_cut else "crossfade", "index": idx})

    return planned, transitions


def _probe_clip_valid(path: str) -> bool:
    """Return True only if the clip has at least 1 video frame and is readable."""
    try:
        import json as _json
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-count_packets", "-show_entries", "stream=nb_read_packets",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = _json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return False
        nb = int(streams[0].get("nb_read_packets") or 0)
        return nb > 0
    except Exception:
        return False


def _filter_valid_clips(clip_paths: List[str]) -> tuple[List[str], List[str]]:
    """Probe each clip; return (valid, skipped) lists."""
    valid, skipped = [], []
    for p in clip_paths:
        if os.path.exists(p) and os.path.getsize(p) >= 1024 and _probe_clip_valid(p):
            valid.append(p)
        else:
            skipped.append(p)
    return valid, skipped


async def _concat_clips_reencode(
    *,
    clip_paths: List[str],
    has_audio: bool,
    output_path: str,
    output_crf: int,
    target_fps: float,
) -> tuple[bool, str]:
    concat_cmd = ["ffmpeg", "-y"]
    filter_parts: List[str] = []
    stream_refs: List[str] = []
    for idx, clip_path in enumerate(clip_paths):
        concat_cmd.extend(["-i", clip_path])
        filter_parts.append(f"[{idx}:v]setpts=PTS-STARTPTS,format=yuv420p[v{idx}]")
        if has_audio:
            filter_parts.append(f"[{idx}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[a{idx}]")
            stream_refs.append(f"[v{idx}][a{idx}]")
        else:
            stream_refs.append(f"[v{idx}]")

    if has_audio:
        filter_parts.append("".join(stream_refs) + f"concat=n={len(clip_paths)}:v=1:a=1[vout][aout]")
    else:
        filter_parts.append("".join(stream_refs) + f"concat=n={len(clip_paths)}:v=1:a=0[vout]")

    concat_cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[vout]"])
    if has_audio:
        concat_cmd.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"])
    else:
        concat_cmd.append("-an")
    concat_cmd.extend([
        "-c:v", "libx264",
        "-crf", str(max(18, min(output_crf, 35))),
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ])
    if target_fps > 0:
        concat_cmd.extend(["-r", _fps_str(target_fps)])
    concat_cmd.extend(["-movflags", "+faststart", output_path])

    concat_err = os.path.join(os.path.dirname(output_path), "concat_reencode.err")
    concat_timeout = max(600, min(21600, len(clip_paths) * 900))
    rc, err = await asyncio.to_thread(_ffmpeg_run, concat_cmd, concat_timeout, concat_err)
    return rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) >= 1024, err


async def _concat_clips_copy(
    *,
    clip_paths: List[str],
    output_path: str,
) -> tuple[bool, str]:
    manifest_path = os.path.join(os.path.dirname(output_path), "concat_copy.txt")
    with open(manifest_path, "w", encoding="utf-8") as manifest:
        for clip_path in clip_paths:
            manifest.write(f"file '{clip_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", manifest_path,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    concat_err = os.path.join(os.path.dirname(output_path), "concat_copy.err")
    concat_timeout = max(300, min(10800, len(clip_paths) * 480))
    rc, err = await asyncio.to_thread(_ffmpeg_run, cmd, concat_timeout, concat_err)
    return rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) >= 1024, err


async def _concat_clips_with_transitions(
    *,
    clip_paths: List[str],
    transitions: List[Dict[str, Any]],
    has_audio: bool,
    output_path: str,
    output_crf: int,
    transition_type: str,
    crossfade_video_sec: float,
    crossfade_audio_sec: float,
    target_fps: float,
    main_mod: Any,
) -> tuple[bool, str]:
    inputs: List[str] = []
    durations: List[float] = []
    for clip_path in clip_paths:
        inputs.extend(["-i", clip_path])
        probe = await asyncio.to_thread(main_mod._probe_metadata, clip_path)
        durations.append(max(0.1, float(probe.get("duration_seconds") or 0.0)))

    filter_parts: List[str] = []
    current_v = "[0:v]"
    current_v_duration = durations[0]
    current_a = "[0:a]" if has_audio else ""

    for idx, trans in enumerate(transitions):
        next_v = f"[{idx + 1}:v]"
        out_v = f"[v{idx}]"
        if str(trans.get("type") or "cut") == "crossfade":
            offset = max(current_v_duration - crossfade_video_sec, 0.0)
            filter_parts.append(
                f"{current_v}{next_v}xfade=transition={transition_type}:duration={crossfade_video_sec:.3f}:offset={offset:.3f}{out_v}"
            )
            current_v = out_v
            current_v_duration = max(0.1, current_v_duration + durations[idx + 1] - crossfade_video_sec)
        else:
            filter_parts.append(f"{current_v}{next_v}concat=n=2:v=1:a=0{out_v}")
            current_v = out_v
            current_v_duration = current_v_duration + durations[idx + 1]

        if has_audio:
            next_a = f"[{idx + 1}:a]"
            out_a = f"[a{idx}]"
            if str(trans.get("type") or "cut") == "crossfade":
                filter_parts.append(
                    f"{current_a}{next_a}acrossfade=d={crossfade_audio_sec:.3f}:c1=tri:c2=tri{out_a}"
                )
            else:
                filter_parts.append(f"{current_a}{next_a}concat=n=2:v=0:a=1{out_a}")
            current_a = out_a

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filter_parts), "-map", current_v]
    if has_audio:
        cmd.extend(["-map", current_a, "-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")
    cmd.extend([
        "-c:v", "libx264",
        "-crf", str(max(18, min(output_crf, 35))),
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ])
    if target_fps > 0:
        cmd.extend(["-r", _fps_str(target_fps)])
    cmd.extend(["-movflags", "+faststart", output_path])

    err_path = os.path.join(os.path.dirname(output_path), "concat_transitions.err")
    timeout = max(600, min(21600, int(sum(durations) * 10) + 900))
    rc, err = await asyncio.to_thread(_ffmpeg_run, cmd, timeout, err_path)
    return rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) >= 1024, err


async def _run_embedded_vision_analysis(
    *,
    main_mod: Any,
    in_path: str,
    duration: float,
    source_probe: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[Dict[str, Any]], Dict[str, Any], List[float], List[float]]:
    """Run Vision analysis on the video.

    Returns (vision_analysis, vision_debug, frame_timestamps, raw_cut_points).
    raw_cut_points comes from scene detection and is reused by the caller to avoid
    a duplicate detection pass.
    """
    vision_analysis: Optional[Dict[str, Any]] = None
    vision_debug: Dict[str, Any] = {"skipped_reason": None}
    frame_timestamps: List[float] = []
    raw_cut_points: List[float] = []
    if duration <= 0:
        vision_debug["skipped_reason"] = "duration_zero_after_probe"
        return vision_analysis, vision_debug, frame_timestamps, raw_cut_points

    try:
        _thresh_s = settings_get(key="vision:scene_threshold")
        _maxf_s = settings_get(key="vision:max_adult_frames")
        scene_threshold = float(_thresh_s["value"]) if _thresh_s else 0.25
        max_frames = int(_maxf_s["value"]) if _maxf_s else 10
        with tempfile.TemporaryDirectory(prefix="autoeditor-vision-", dir=main_mod._preferred_tmpdir_root("vision")) as vtd:
            frame_items, raw_cut_points = await asyncio.to_thread(
                main_mod._extract_intelligent_adult_keyframes,
                in_path=in_path,
                out_dir=vtd,
                duration=duration,
                max_frames=max_frames,
                scene_threshold=scene_threshold,
                probe=source_probe,
            )
            vision_debug["frames_extracted"] = len(frame_items)
            frame_timestamps = [
                round(float(item.get("timestamp") or 0.0), 3)
                for item in frame_items
            ]
            frames_b64 = [
                await asyncio.to_thread(main_mod._file_to_base64, str(item.get("path") or ""))
                for item in frame_items
                if str(item.get("path") or "").strip()
            ]
            if frames_b64:
                vision_analysis = await main_mod._analyze_multiple_frames(frames_b64)
                if vision_analysis is None:
                    has_grok = bool((settings_get(key="token:grok") or {}).get("value"))
                    vision_debug["analysis_error"] = "missing_grok_token" if not has_grok else "empty_or_invalid_vision_response"
            else:
                vision_debug["skipped_reason"] = "no_frames_extracted"
    except Exception as exc:
        vision_debug["error"] = repr(exc)

    return vision_analysis, vision_debug, frame_timestamps, raw_cut_points


def _summarize_input_probe(source_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    probes = [dict(item.get("probe") or {}) for item in source_entries]
    if not probes:
        return {}

    positive_fps = [
        float(probe.get("fps") or probe.get("avg_fps") or 0.0)
        for probe in probes
        if float(probe.get("fps") or probe.get("avg_fps") or 0.0) > 0
    ]
    total_duration = sum(float(probe.get("duration_seconds") or 0.0) for probe in probes)
    return {
        "duration_seconds": round(total_duration, 3),
        "width": max(int(probe.get("width") or 0) for probe in probes),
        "height": max(int(probe.get("height") or 0) for probe in probes),
        "fps": round(max(positive_fps), 3) if positive_fps else 0.0,
        "avg_fps": round(max(positive_fps), 3) if positive_fps else 0.0,
        "has_audio": any(bool(probe.get("has_audio")) for probe in probes),
        "source_count": len(source_entries),
        "sources": [
            {
                "source_index": int(item.get("source_index") or 0),
                "source_video_key": str(item.get("source_video_key") or ""),
                "source_label": str(item.get("source_label") or ""),
                "duration_seconds": round(float((item.get("probe") or {}).get("duration_seconds") or 0.0), 3),
                "width": int((item.get("probe") or {}).get("width") or 0),
                "height": int((item.get("probe") or {}).get("height") or 0),
                "fps": float((item.get("probe") or {}).get("fps") or (item.get("probe") or {}).get("avg_fps") or 0.0),
                "has_audio": bool((item.get("probe") or {}).get("has_audio")),
                "color_primaries": str((item.get("probe") or {}).get("color_primaries") or ""),
                "color_transfer": str((item.get("probe") or {}).get("color_transfer") or ""),
                "color_space": str((item.get("probe") or {}).get("color_space") or ""),
                "pix_fmt": str((item.get("probe") or {}).get("pix_fmt") or ""),
            }
            for item in source_entries
        ],
    }


def _merge_vision_payloads(source_entries: List[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    categories: List[str] = []
    tags: List[str] = []
    descriptions: List[str] = []
    scenes: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    debug_sources: List[Dict[str, Any]] = []
    analysis_errors: List[str] = []
    skipped_reasons: List[str] = []

    for item in source_entries:
        source_index = int(item.get("source_index") or 0)
        source_key = str(item.get("source_video_key") or "")
        source_label = str(item.get("source_label") or "")
        offset = float(item.get("offset") or 0.0)
        vision = dict(item.get("vision_analysis") or {})
        debug = dict(item.get("vision_debug") or {})
        frame_timestamps = list(item.get("frame_timestamps") or [])

        desc = str(vision.get("description") or "").strip()
        if desc:
            descriptions.append(f"{source_label}: {desc}")

        for raw in list(vision.get("categories") or []):
            value = str(raw or "").strip()
            if value and value not in categories:
                categories.append(value)

        for raw in list(vision.get("tags") or []):
            value = str(raw or "").strip()
            if value and value not in tags:
                tags.append(value)

        raw_scenes = list(vision.get("scenes") or [])
        for raw_scene in raw_scenes[:8]:
            scene = dict(raw_scene or {})
            frame_index = int(scene.get("frame_index") or -1)
            local_timestamp = None
            if 0 <= frame_index < len(frame_timestamps):
                local_timestamp = round(float(frame_timestamps[frame_index]), 3)
            if local_timestamp is None:
                try:
                    local_timestamp = round(float(scene.get("timestamp") or 0.0), 3)
                except Exception:
                    local_timestamp = 0.0
            scene["source_index"] = source_index
            scene["source_video_key"] = source_key
            scene["source_label"] = source_label
            scene["timestamp_local"] = local_timestamp
            scene["timestamp_global"] = round(offset + float(local_timestamp or 0.0), 3)
            scenes.append(scene)

        sources.append({
            "source_index": source_index,
            "source_video_key": source_key,
            "source_label": source_label,
            "description": desc,
            "categories": list(vision.get("categories") or [])[:10],
            "tags": list(vision.get("tags") or [])[:15],
            "frames_extracted": int(debug.get("frames_extracted") or 0),
        })
        debug_sources.append({
            "source_index": source_index,
            "source_video_key": source_key,
            "source_label": source_label,
            **debug,
        })
        if debug.get("analysis_error"):
            analysis_errors.append(str(debug.get("analysis_error")))
        if debug.get("skipped_reason"):
            skipped_reasons.append(str(debug.get("skipped_reason")))

    merged_analysis = {
        "description": " | ".join([text for text in descriptions if text][:3])[:900],
        "categories": categories[:18],
        "tags": tags[:24],
        "scenes": sorted(scenes, key=lambda item: float(item.get("timestamp_global") or 0.0))[:24],
        "sources": sources,
    }
    merged_debug = {
        "source_count": len(source_entries),
        "sources": debug_sources,
    }
    if analysis_errors:
        merged_debug["analysis_error"] = analysis_errors[0]
    elif skipped_reasons:
        merged_debug["skipped_reason"] = skipped_reasons[0]
    if not any([
        merged_analysis["description"],
        merged_analysis["categories"],
        merged_analysis["tags"],
        merged_analysis["scenes"],
    ]):
        merged_analysis = {}
    return merged_analysis, merged_debug


async def _prepare_source_inputs(
    *,
    main_mod: Any,
    source_keys: List[str],
    workdir: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    source_entries: List[Dict[str, Any]] = []
    offset = 0.0

    for idx, source_key in enumerate(source_keys):
        ext = Path(source_key).suffix or ".mp4"
        src_path = os.path.join(workdir, f"source_{idx:03d}{ext}")
        try:
            await asyncio.to_thread(
                main_mod._download_media_ref_to_file,
                media_ref=source_key,
                out_path=src_path,
                s3=main_mod._s3_client(),
            )
            probe = await asyncio.to_thread(main_mod._probe_metadata, src_path)
        except Exception as exc:
            return [], {}, f"Falha ao baixar/preparar vídeo {idx + 1}: {exc}"

        duration = max(0.0, float(probe.get("duration_seconds") or 0.0))
        source_entries.append({
            "source_index": idx,
            "source_video_key": source_key,
            "source_label": Path(source_key).name or f"vídeo {idx + 1}",
            "path": src_path,
            "probe": probe,
            "offset": round(offset, 3),
            "duration": round(duration, 3),
        })
        offset += duration

    if not source_entries:
        return [], {}, "Nenhum vídeo de origem foi baixado."

    return source_entries, _summarize_input_probe(source_entries), ""


async def _extract_scene_clip(
    *,
    scene: Dict[str, Any],
    source_entry: Dict[str, Any],
    output_path: str,
    output_crf: int,
    max_height: int,
    target_fps: float,
    overall_has_audio: bool,
    audio_normalize: bool,
    audio_denoise: bool,
) -> tuple[bool, str]:
    source_path = str(source_entry.get("path") or "")
    source_probe = dict(source_entry.get("probe") or {})
    source_has_audio = bool(source_probe.get("has_audio"))
    clip_start = float(scene.get("source_start") if scene.get("source_start") is not None else scene.get("start") or 0.0)
    clip_duration = max(0.1, float(scene.get("duration") or 0.0))

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{clip_start:.3f}",
        "-t", f"{clip_duration:.3f}",
        "-i", source_path,
    ]
    if overall_has_audio and not source_has_audio:
        cmd.extend([
            "-f", "lavfi",
            "-t", f"{clip_duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ])

    vf = _build_video_filter(max_height=max_height, target_fps=target_fps, source_probe=source_probe)
    cmd.extend([
        "-map", "0:v:0",
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", str(max(18, min(output_crf, 35))),
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
    ])

    if overall_has_audio:
        if source_has_audio:
            cmd.extend(["-map", "0:a:0?"])
            audio_filter = _build_audio_filter(normalize=audio_normalize, denoise=audio_denoise)
            if audio_filter:
                cmd.extend(["-af", audio_filter])
        else:
            cmd.extend(["-map", "1:a:0"])
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
        ])
        if not source_has_audio:
            cmd.append("-shortest")
    else:
        cmd.append("-an")

    cmd.extend(["-movflags", "+faststart", output_path])
    err_path = os.path.join(os.path.dirname(output_path), Path(output_path).stem + ".err")
    timeout = max(300, min(10800, int(clip_duration * 18) + 300))
    rc, err = await asyncio.to_thread(_ffmpeg_run, cmd, timeout, err_path)
    return rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) >= 1024, err


async def run_recut_job(original_job_id: str, recut_job_id: str) -> None:
    """Re-cut an existing AutoEditor job without repeating Vision/scene-detection.

    Reuses: source_video_keys, vision_analysis, creator_id from the original job.
    Re-runs: scene detection at 360p (fast), candidate building with natural cuts,
             LLM selection with coverage+gozada guarantee, clip extraction, concat.
    """
    orig = async_job_get(kind=ASYNC_KIND, job_id=original_job_id)
    recut = async_job_get(kind=ASYNC_KIND, job_id=recut_job_id)
    if not orig or not recut:
        return

    from .. import main as main_mod

    def _patch(d: Dict[str, Any]) -> None:
        _job_patch(recut_job_id, d)

    _patch({"status": "running", "detail": "Iniciando re-cut…", "progress_pct": 2})

    source_keys: List[str] = list(orig.get("source_video_keys") or [])
    if not source_keys:
        _patch({"status": "error", "detail": "Job original sem source_video_keys.", "progress_pct": 0})
        return

    stored_vision = dict(orig.get("vision_analysis") or {})
    creator_id = str(orig.get("creator_id") or "").strip() or None
    orig_probe = dict(orig.get("input_probe") or {})
    orig_sources = {int(s["source_index"]): s for s in (orig_probe.get("sources") or [])}

    # Resolve params from original job request (fall back to defaults)
    orig_req = dict(orig.get("request") or {})
    output_crf = int(orig_req.get("output_crf") or 23)
    output_max_height = int(orig_req.get("output_max_height") or 1080)
    output_max_fps = int(orig_req.get("output_max_fps") or 30)
    audio_normalize = bool(orig_req.get("audio_normalize", True))
    audio_denoise = bool(orig_req.get("audio_denoise", True))
    max_scenes = int(orig_req.get("max_scenes") or 60)
    max_scene_duration = float(orig_req.get("max_scene_duration_sec") or 150.0)
    scene_threshold = float(orig_req.get("scene_threshold") or 0.25)
    transition_mode = _normalize_transition_mode(orig_req.get("transition_mode") or "smart")
    crossfade_video_sec = float(orig_req.get("crossfade_video_sec") or 0.5)
    crossfade_audio_sec = float(orig_req.get("crossfade_audio_sec") or 0.3)
    transition_type = _normalize_transition_type(orig_req.get("transition_type") or "fade")
    smart_cut_tolerance_sec = float(orig_req.get("smart_cut_tolerance_sec") or 1.5)
    min_scene_duration = 3.0  # Always use natural cuts for re-cut

    creator = creator_get(creator_id) if creator_id else None
    creator_dict = dict(creator or {})

    try:
        with tempfile.TemporaryDirectory(prefix="auto-recut-", dir=main_mod._preferred_tmpdir_root("autoeditor")) as td:
            # Step 1: resolve/download source files
            _patch({"detail": f"Preparando {len(source_keys)} vídeos de origem…", "progress_pct": 5})
            source_entries: List[Dict[str, Any]] = []
            for i, skey in enumerate(source_keys):
                entry_path: Optional[str] = None
                if main_mod._is_local_media_ref(skey):
                    try:
                        entry_path = main_mod._local_media_abs_path_from_ref(skey)
                    except Exception:
                        entry_path = None
                if not entry_path or not os.path.exists(entry_path):
                    # Fallback: download from S3
                    ext = Path(skey).suffix or ".mp4"
                    dl_path = os.path.join(td, f"src_{i:03d}{ext}")
                    try:
                        s3 = main_mod._s3_client()
                        await asyncio.to_thread(main_mod._download_object_to_file, s3=s3, object_key=skey, out_path=dl_path)
                        entry_path = dl_path
                    except Exception as exc:
                        _patch({"status": "error", "detail": f"Falha ao obter vídeo {i+1}: {exc}", "progress_pct": 0})
                        return
                # Always re-probe to get accurate HDR metadata (color_transfer, pix_fmt etc.)
                # Stored probe from old jobs may be missing HDR fields.
                probe = main_mod._probe_metadata(entry_path)
                src_dur = float(probe.get("duration_seconds") or 0)
                source_entries.append({
                    "source_index": i,
                    "source_video_key": skey,
                    "source_label": Path(skey).name,
                    "path": entry_path,
                    "duration": src_dur,
                    "offset": sum(float((orig_sources.get(j) or {}).get("duration_seconds") or 0) for j in range(i)),
                    "probe": probe,
                })

            total_duration = sum(float(e["duration"]) for e in source_entries)
            has_audio = any(bool((e.get("probe") or {}).get("has_audio")) for e in source_entries)
            fps_values = [float((e.get("probe") or {}).get("fps") or 30) for e in source_entries]
            target_fps = min(max(max(fps_values), 1.0), float(output_max_fps))

            # Step 2: fast scene detection (360p) per source — skip Vision
            all_cut_points: List[float] = []
            candidates: List[Dict[str, Any]] = []
            global_scene_index = 0

            for i, entry in enumerate(source_entries):
                src_path = entry["path"]
                src_dur = float(entry["duration"])
                src_offset = float(entry["offset"])
                pct = 8 + int((i / len(source_entries)) * 30)
                _patch({"detail": f"Detectando cortes {i+1}/{len(source_entries)}: {entry['source_label'][:40]}…", "progress_pct": pct})

                try:
                    cut_points = await asyncio.to_thread(main_mod._detect_scene_timestamps, src_path, scene_threshold, src_dur)
                except Exception:
                    cut_points = []

                src_cands = _build_scene_candidates(
                    duration=src_dur,
                    cut_points=cut_points,
                    min_scene_duration=min_scene_duration,
                    max_scene_duration=max_scene_duration,
                )
                src_cands = _enrich_candidates_with_vision(
                    candidates=src_cands,
                    vision_analysis=stored_vision if i == 0 else {},
                    frame_timestamps=[],
                )
                for item in src_cands:
                    local_start = float(item.get("start") or 0)
                    local_end = float(item.get("end") or local_start)
                    candidates.append({
                        **dict(item),
                        "scene_index": global_scene_index,
                        "source_index": i,
                        "source_video_key": entry["source_video_key"],
                        "source_label": entry["source_label"],
                        "source_start": round(local_start, 3),
                        "source_end": round(local_end, 3),
                        "start": round(src_offset + local_start, 3),
                        "end": round(src_offset + local_end, 3),
                        "duration": round(local_end - local_start, 3),
                    })
                    global_scene_index += 1
                all_cut_points.extend(round(src_offset + float(p), 3) for p in cut_points)

            if not candidates:
                _patch({"status": "error", "detail": "Nenhum candidato encontrado.", "progress_pct": 0})
                return

            # (merge disabled — LLM receives all natural candidates for full granularity)

            # Step 3: channel profile (fast, skip if no creator)
            channel_profile: Dict[str, Any] = {}
            if creator_dict:
                try:
                    channel_profile = await _fetch_creator_channel_profile(creator_dict)
                except Exception:
                    pass

            # Step 4: LLM selection with coverage guarantee
            _patch({"detail": f"Grok selecionando cenas ({len(candidates)} candidatos, {len(source_entries)} vídeos)…", "progress_pct": 42})
            selected = _heuristic_select_scenes(candidates=candidates, duration=total_duration, max_scenes=max_scenes)

            llm_result = await _llm_select_scenes_grok(
                candidates=candidates,
                max_scenes=max_scenes,
                vision_analysis=stored_vision or None,
                channel_profile=channel_profile or None,
            )
            llm_indexes = llm_result.get("indexes") or []
            if llm_indexes:
                indexed = {int(c["scene_index"]): dict(c) for c in candidates}
                llm_selected = []
                for idx in llm_indexes:
                    item = indexed.get(int(idx))
                    if item:
                        item["selected"] = True
                        llm_selected.append(item)
                        if len(llm_selected) >= max_scenes:
                            break
                if llm_selected:
                    selected = sorted(llm_selected, key=lambda s: s["start"])
                    # Coverage fix
                    selected_src_ids = set(int(s.get("source_index") or 0) for s in selected)
                    missing = [i for i in range(len(source_entries)) if i not in selected_src_ids]
                    if missing:
                        by_src = {}
                        for c in candidates:
                            by_src.setdefault(int(c.get("source_index") or 0), []).append(c)
                        fill = []
                        for src_id in missing:
                            top = sorted(by_src.get(src_id, []), key=lambda c: -float(c.get("score") or 0))
                            for c in top[:3]:
                                item = dict(c); item["selected"] = True; fill.append(item)
                        selected = sorted(selected + fill, key=lambda s: (int(s.get("source_index") or 0), float(s.get("start") or 0)))[:max_scenes]

            # Remove scenes with visible filming equipment
            selected = _filter_equipment_scenes(selected)

            _patch({"detail": f"Extraindo {len(selected)} cenas em paralelo…", "progress_pct": 50, "selected_scenes": selected})

            # Step 5: parallel clip extraction
            source_map = {int(e["source_index"]): e for e in source_entries}
            _sem = asyncio.Semaphore(3)
            _done = 0

            async def _extract_one(idx: int, scene: Dict[str, Any]) -> tuple[int, str, bool, str]:
                nonlocal _done
                clip_path = os.path.join(td, f"clip_{idx:03d}.mp4")
                async with _sem:
                    ok, err = await _extract_scene_clip(
                        scene=scene,
                        source_entry=source_map[int(scene.get("source_index") or 0)],
                        output_path=clip_path,
                        output_crf=output_crf,
                        max_height=output_max_height,
                        target_fps=target_fps,
                        overall_has_audio=has_audio,
                        audio_normalize=audio_normalize,
                        audio_denoise=audio_denoise,
                    )
                _done += 1
                _patch({"detail": f"Extraindo… {_done}/{len(selected)} prontas", "progress_pct": min(78, 50 + int((_done / max(len(selected), 1)) * 28))})
                return idx, clip_path, ok, err

            results = await asyncio.gather(*[_extract_one(i, s) for i, s in enumerate(selected)])

            clip_paths: List[str] = []
            for idx, clip_path, ok, err in sorted(results, key=lambda r: r[0]):
                if not ok:
                    _patch({"status": "error", "detail": f"Falha cena {idx+1}: {(err or '')[:200]}", "progress_pct": 0})
                    return
                clip_paths.append(clip_path)

            # Step 5b: build timelapse opener (best moments at 2x speed)
            _patch({"detail": "Montando teaser de abertura…", "progress_pct": 80})
            teaser_clips = await _build_timelapse_opener(
                selected=selected,
                source_map=source_map,
                td=td,
                max_height=output_max_height,
                crf=output_crf,
                semaphore=_sem,
            )

            # Step 6: concat (teaser + main)
            _patch({"detail": "Concatenando…", "progress_pct": 82})
            final_path = os.path.join(td, "recut_final.mp4")
            all_clip_paths_raw = teaser_clips + clip_paths
            all_clip_paths, skipped_clips = await asyncio.to_thread(_filter_valid_clips, all_clip_paths_raw)
            if skipped_clips:
                print(f"[recut][concat] descartados {len(skipped_clips)} clips inválidos/vazios: {[os.path.basename(p) for p in skipped_clips]}", flush=True)
            if not all_clip_paths:
                _patch({"status": "error", "detail": "Nenhum clip válido para concatenar.", "progress_pct": 0})
                return
            # xfade chain breaks with large clip counts — cap at 30 clips
            _MAX_XFADE_CLIPS = 30
            has_crossfade = (
                len(all_clip_paths) <= _MAX_XFADE_CLIPS
                and any(str(t.get("type") or "") == "crossfade" for t in
                    _plan_scene_transitions(scenes=selected, scene_changes=sorted(all_cut_points),
                        transition_mode=transition_mode, smart_cut_tolerance_sec=smart_cut_tolerance_sec,
                        min_scene_duration=min_scene_duration, source_duration=total_duration)[1])
            )

            if len(all_clip_paths) == 1 or transition_mode == "none" or not has_crossfade:
                # For large clip counts skip copy (mismatched streams) and go straight to reencode
                if len(all_clip_paths) > 30:
                    ok, err = await _concat_clips_reencode(clip_paths=all_clip_paths, has_audio=has_audio, output_path=final_path, output_crf=output_crf, target_fps=target_fps)
                else:
                    ok, err = await _concat_clips_copy(clip_paths=all_clip_paths, output_path=final_path)
                    if not ok:
                        copy_err = err
                        ok, err = await _concat_clips_reencode(clip_paths=all_clip_paths, has_audio=has_audio, output_path=final_path, output_crf=output_crf, target_fps=target_fps)
                        if not ok:
                            err = f"copy: {copy_err[:150]} | reencode: {err[:150]}"
            else:
                planned, transitions = _plan_scene_transitions(scenes=selected, scene_changes=sorted(all_cut_points), transition_mode=transition_mode, smart_cut_tolerance_sec=smart_cut_tolerance_sec, min_scene_duration=min_scene_duration, source_duration=total_duration)
                ok, err = await _concat_clips_with_transitions(clip_paths=all_clip_paths, transitions=transitions, has_audio=has_audio, output_path=final_path, output_crf=output_crf, transition_type=transition_type, crossfade_video_sec=crossfade_video_sec, crossfade_audio_sec=crossfade_audio_sec, target_fps=target_fps, main_mod=main_mod)

            if not ok:
                _patch({"status": "error", "detail": f"Concat falhou: {(err or '')[:200]}", "progress_pct": 0})
                return

            # Step 7: store result
            _patch({"detail": "Salvando resultado…", "progress_pct": 90})
            safe_name = f"recut_{recut_job_id[:8]}_{Path(source_keys[0]).name}"
            if not safe_name.lower().endswith(".mp4"):
                safe_name += ".mp4"
            stored = await asyncio.to_thread(
                main_mod._store_local_path,
                src_path=final_path,
                prefix="autoeditor",
                filename=safe_name,
                content_type="video/mp4",
            )
            result_probe = await asyncio.to_thread(main_mod._probe_metadata, final_path)
            total_min = round(sum(float(s.get("duration", 0)) for s in selected) / 60, 1)
            _patch({
                "status": "done",
                "detail": f"✓ Re-cut concluído. {len(selected)} cenas, {total_min}min.",
                "progress_pct": 100,
                "result_video_object_key": stored.get("object_key"),
                "result_video_url": stored.get("public_url"),
                "output_probe": result_probe,
                "selected_scenes": selected,
                "selection_method": "recut_llm_grok",
                "source_video_keys": source_keys,
                "creator_id": creator_id or "",
            })

    except Exception as exc:
        import traceback
        _patch({"status": "error", "detail": f"Erro inesperado: {str(exc)[:300]}", "progress_pct": 0, "error": traceback.format_exc()[:1000]})


async def run_auto_editor_job(job_id: str) -> None:
    job = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not job:
        return

    from .. import main as main_mod

    payload = dict(job.get("request") or {})
    creator_id = str(payload.get("creator_id") or "").strip() or None
    source_keys = _coerce_source_keys(payload)
    source_key = source_keys[0] if source_keys else ""
    if not source_key:
        _job_patch(job_id, {"status": "error", "error": "missing_video_object_key", "detail": "Selecione ao menos um vídeo para o AutoEditor."})
        return

    creator = creator_get(creator_id) if creator_id else None
    creator_cfg = dict((creator or {}).get("default_edit_config") or {})
    creator_dict = dict(creator or {})

    output_crf = int(payload.get("output_crf") or creator_cfg.get("output_crf") or 23)
    output_max_height = int(payload.get("output_max_height") or creator_cfg.get("output_max_height") or 1080)
    output_max_fps = max(12, min(int(payload.get("output_max_fps") or 30), 120))
    audio_normalize = bool(payload.get("audio_normalize") if "audio_normalize" in payload else creator_cfg.get("audio_normalize", True))
    audio_denoise = bool(payload.get("audio_denoise") if "audio_denoise" in payload else creator_cfg.get("audio_denoise", True))
    skip_transcription = bool(payload.get("skip_transcription") if "skip_transcription" in payload else creator_cfg.get("skip_transcription", True))
    scene_threshold = max(0.05, min(float(payload.get("scene_threshold") or 0.25), 0.95))
    min_scene_duration = max(3.0, min(float(payload.get("min_scene_duration_sec") or 3.0), 600.0))
    max_scene_duration = max(min_scene_duration, min(float(payload.get("max_scene_duration_sec") or 150.0), 1200.0))
    max_scenes = max(2, min(int(payload.get("max_scenes") or 60), 120))
    transition_mode = _normalize_transition_mode(payload.get("transition_mode") or "smart")
    crossfade_video_sec = max(0.3, min(float(payload.get("crossfade_video_sec") or 0.5), 2.0))
    crossfade_audio_sec = max(0.2, min(float(payload.get("crossfade_audio_sec") or 0.3), 2.0))
    transition_type = _normalize_transition_type(payload.get("transition_type") or "fade")
    smart_cut_tolerance_sec = max(0.5, min(float(payload.get("smart_cut_tolerance_sec") or 1.5), 5.0))
    title_hint = str(payload.get("title_hint") or "").strip()
    delete_source_on_success = bool(payload.get("delete_source_on_success"))

    _job_patch(job_id, {
        "status": "running",
        "detail": "Preparando vídeos de origem…",
        "progress_pct": 5,
        "creator_id": creator_id or "",
        "source_video_key": source_key,
        "source_video_keys": source_keys,
        "run_id": job_id,
    })

    try:
        with tempfile.TemporaryDirectory(prefix="auto-editor-", dir=main_mod._preferred_tmpdir_root("autoeditor")) as td:
            source_entries, probe, prepare_err = await _prepare_source_inputs(
                main_mod=main_mod,
                source_keys=source_keys,
                workdir=td,
            )
            if not source_entries:
                _job_patch(job_id, {
                    "status": "error",
                    "error": "source_prepare_failed",
                    "detail": prepare_err or "Falha ao preparar os vídeos de origem.",
                })
                return

            duration = float(probe.get("duration_seconds") or 0.0)
            has_audio = bool(probe.get("has_audio"))
            fps_values = [
                float((entry.get("probe") or {}).get("fps") or (entry.get("probe") or {}).get("avg_fps") or 0.0)
                for entry in source_entries
                if float((entry.get("probe") or {}).get("fps") or (entry.get("probe") or {}).get("avg_fps") or 0.0) > 0
            ]
            input_fps = max(fps_values) if fps_values else 0.0
            target_fps = min(max(input_fps, 1.0), float(output_max_fps)) if input_fps > 0 else float(output_max_fps)
            if duration <= 0:
                _job_patch(job_id, {
                    "status": "error",
                    "error": "invalid_duration",
                    "detail": "Não consegui detectar a duração total dos vídeos selecionados.",
                    "input_probe": probe,
                })
                return

            _job_patch(job_id, {
                "detail": (
                    f"Preparei {len(source_keys)} vídeos e vou analisar cada fonte antes de montar o corte…"
                    if len(source_keys) > 1 else
                    "Analisando o vídeo de origem…"
                ),
                "progress_pct": 12,
                "input_probe": probe,
            })

            all_cut_points: List[float] = []
            candidates: List[Dict[str, Any]] = []
            transcript_excerpt_parts: List[str] = []
            global_scene_index = 0

            for source_entry in source_entries:
                source_index = int(source_entry.get("source_index") or 0)
                source_label = str(source_entry.get("source_label") or f"vídeo {source_index + 1}")
                source_key_current = str(source_entry.get("source_video_key") or "")
                source_path = str(source_entry.get("path") or "")
                source_duration = float(source_entry.get("duration") or 0.0)
                source_probe = dict(source_entry.get("probe") or {})
                source_has_audio = bool(source_probe.get("has_audio"))
                source_offset = float(source_entry.get("offset") or 0.0)

                if source_duration <= 0.0:
                    _job_patch(job_id, {
                        "status": "error",
                        "error": "invalid_source_duration",
                        "detail": f"O vídeo {source_index + 1} ({source_label}) não tem duração válida.",
                    })
                    return

                base_progress = 14 + int((source_index / max(len(source_entries), 1)) * 24)
                _job_patch(job_id, {
                    "detail": f"Rodando Analyze/Vision no vídeo {source_index + 1}/{len(source_entries)}: {source_label}",
                    "progress_pct": min(38, base_progress),
                })
                # Vision analysis also runs scene detection internally; reuse cut points
                # to avoid a second full-resolution decode pass per video.
                source_vision_analysis, source_vision_debug, frame_timestamps, local_cut_points = await _run_embedded_vision_analysis(
                    main_mod=main_mod,
                    in_path=source_path,
                    duration=source_duration,
                    source_probe=source_probe,
                )

                transcript_segments: List[Dict[str, Any]] = []
                source_transcript_excerpt = ""
                if not skip_transcription and source_has_audio:
                    _job_patch(job_id, {
                        "detail": f"Transcrevendo áudio do vídeo {source_index + 1}/{len(source_entries)}…",
                        "progress_pct": min(42, base_progress + 6),
                    })
                    try:
                        wav_path = os.path.join(td, f"audio_{source_index:03d}.wav")
                        await asyncio.to_thread(main_mod._extract_audio_to_wav, in_path=source_path, out_path=wav_path)
                        tresult = await asyncio.to_thread(main_mod._transcribe_local, wav_path, str(payload.get("language") or ""))
                        transcript_segments = list(tresult.get("segments") or [])
                        source_transcript_excerpt = " ".join(
                            str(seg.get("text") or "").strip()
                            for seg in transcript_segments[:10]
                            if str(seg.get("text") or "").strip()
                        )[:500]
                    except Exception:
                        transcript_segments = []
                        source_transcript_excerpt = ""

                source_candidates = _build_scene_candidates(
                    duration=source_duration,
                    cut_points=local_cut_points,
                    min_scene_duration=min_scene_duration,
                    max_scene_duration=max_scene_duration,
                    transcript_segments=transcript_segments,
                )
                source_candidates = _enrich_candidates_with_vision(
                    candidates=source_candidates,
                    vision_analysis=source_vision_analysis,
                    frame_timestamps=frame_timestamps,
                )

                normalized_candidates: List[Dict[str, Any]] = []
                for item in source_candidates:
                    local_start = float(item.get("start") or 0.0)
                    local_end = float(item.get("end") or local_start)
                    normalized_candidates.append({
                        **dict(item),
                        "scene_index": global_scene_index,
                        "source_index": source_index,
                        "source_video_key": source_key_current,
                        "source_label": source_label,
                        "source_start": round(local_start, 3),
                        "source_end": round(local_end, 3),
                        "start": round(source_offset + local_start, 3),
                        "end": round(source_offset + local_end, 3),
                        "duration": round(local_end - local_start, 3),
                    })
                    global_scene_index += 1

                source_entry["vision_analysis"] = source_vision_analysis or {}
                source_entry["vision_debug"] = source_vision_debug or {}
                source_entry["frame_timestamps"] = frame_timestamps
                source_entry["cut_points"] = local_cut_points
                source_entry["transcript_segments"] = transcript_segments
                source_entry["transcript_excerpt"] = source_transcript_excerpt
                source_entry["candidates"] = normalized_candidates

                candidates.extend(normalized_candidates)
                all_cut_points.extend(round(source_offset + float(point or 0.0), 3) for point in local_cut_points)
                if source_transcript_excerpt:
                    transcript_excerpt_parts.append(f"{source_label}: {source_transcript_excerpt}")

            vision_analysis, vision_debug = _merge_vision_payloads(source_entries)
            transcript_excerpt = " | ".join(text for text in transcript_excerpt_parts if text)[:1400]
            if not candidates:
                _job_patch(job_id, {"status": "error", "error": "no_scene_candidates", "detail": "Nenhuma cena candidata foi encontrada."})
                return

            # Fetch creator channel profile for category-aware editing
            channel_profile: Dict[str, Any] = {}
            if creator_dict:
                _job_patch(job_id, {"detail": "Buscando perfil do canal do criador…", "progress_pct": 42})
                try:
                    channel_profile = await _fetch_creator_channel_profile(creator_dict)
                    if channel_profile.get("dominant_category"):
                        print(f"[auto-editor] creator profile: category={channel_profile['dominant_category']} tags={channel_profile.get('top_tags', [])[:5]}", flush=True)
                except Exception as _ce:
                    print(f"[auto-editor] channel profile fetch failed: {_ce}", flush=True)

            # Merge adjacent micro-segments before Grok to prevent micro-cut output
            candidates = _merge_adjacent_candidates(candidates, gap_threshold=60.0, max_merge_duration=300.0)

            _job_patch(job_id, {"detail": "Selecionando melhores cenas com Vision + IA…", "progress_pct": 44})
            selected = _heuristic_select_scenes(
                candidates=candidates,
                duration=duration,
                max_scenes=max_scenes,
            )
            selection_method = "heuristic_vision" if vision_analysis else "heuristic"
            llm_note = ""
            if bool(payload.get("llm_select", True)):
                _job_patch(job_id, {"detail": "Grok selecionando as melhores cenas com contexto Vision + perfil do criador…", "progress_pct": 52})
                llm_result = await _llm_select_scenes_grok(
                    candidates=candidates,
                    max_scenes=max_scenes,
                    vision_analysis=vision_analysis,
                    channel_profile=channel_profile or None,
                )
                llm_indexes = llm_result.get("indexes") or []
                if llm_indexes:
                    indexed = {int(item["scene_index"]): dict(item) for item in candidates}
                    llm_selected: List[Dict[str, Any]] = []
                    for idx in llm_indexes:
                        item = indexed.get(int(idx))
                        if not item:
                            continue
                        item["selected"] = True
                        llm_selected.append(item)
                        if len(llm_selected) >= max_scenes:
                            break
                    if llm_selected:
                        selected = sorted(llm_selected, key=lambda item: item["start"])
                        selection_method = "llm_grok_vision" if vision_analysis else "llm_grok"

                        # Coverage guarantee: if Grok missed entire source_indexes, fill them
                        n_sources = len(source_entries)
                        if n_sources > 1:
                            selected_src_ids = set(int(s.get("source_index") or 0) for s in selected)
                            missing_src_ids = [i for i in range(n_sources) if i not in selected_src_ids]
                            if missing_src_ids:
                                # Budget: at most 3 fill scenes per missed source, up to max_scenes total
                                by_src = {int(c.get("source_index") or 0): [] for c in candidates}
                                for c in candidates:
                                    by_src[int(c.get("source_index") or 0)].append(c)
                                fill_scenes: List[Dict[str, Any]] = []
                                for src_id in missing_src_ids:
                                    src_cands = sorted(by_src.get(src_id, []), key=lambda c: -float(c.get("score") or 0))
                                    for c in src_cands[:3]:
                                        item = dict(c)
                                        item["selected"] = True
                                        fill_scenes.append(item)
                                combined = selected + fill_scenes
                                combined = sorted(combined, key=lambda s: (int(s.get("source_index") or 0), float(s.get("start") or 0)))
                                selected = combined[:max_scenes]
                                print(f"[auto-editor] coverage fix: added {len(fill_scenes)} scenes for missing sources {missing_src_ids}", flush=True)
                else:
                    llm_note = str(llm_result.get("error") or "Grok falhou")
                    _job_patch(job_id, {
                        "detail": f"Grok indisponível; seguindo com heurística ({llm_note[:140]})…",
                        "progress_pct": 56,
                    })

            # Remove scenes with visible filming equipment
            selected = _filter_equipment_scenes(selected)

            if not selected:
                _job_patch(job_id, {"status": "error", "error": "no_selected_scenes", "detail": "Nenhuma cena foi selecionada para o corte final."})
                return

            selected, transitions = _plan_scene_transitions(
                scenes=selected,
                scene_changes=sorted(all_cut_points),
                transition_mode=transition_mode,
                smart_cut_tolerance_sec=smart_cut_tolerance_sec,
                min_scene_duration=min_scene_duration,
                source_duration=duration,
            )
            _job_patch(job_id, {
                "detail": f"Extraindo {len(selected)} cenas para o corte final…",
                "progress_pct": 60,
                "selected_scenes": selected,
                "transcript_excerpt": transcript_excerpt,
                "selection_method": selection_method,
                "vision_analysis": vision_analysis or {},
                "vision_debug": vision_debug or {},
            })

            source_map = {int(entry.get("source_index") or 0): entry for entry in source_entries}

            # Validate all source mappings before starting extraction
            for idx, scene in enumerate(selected):
                if not source_map.get(int(scene.get("source_index") or 0)):
                    _job_patch(job_id, {
                        "status": "error",
                        "error": "missing_source_mapping",
                        "detail": f"Não encontrei a origem da cena {idx + 1} para extrair o clip final.",
                    })
                    return

            # Parallel clip extraction with a concurrency semaphore (max 3 ffmpeg processes)
            _sem = asyncio.Semaphore(3)
            _completed_count = 0

            async def _extract_one(idx: int, scene: Dict[str, Any]) -> tuple[int, str, bool, str]:
                nonlocal _completed_count
                clip_path = os.path.join(td, f"clip_{idx:03d}.mp4")
                src_entry = source_map[int(scene.get("source_index") or 0)]
                async with _sem:
                    ok, err = await _extract_scene_clip(
                        scene=scene,
                        source_entry=src_entry,
                        output_path=clip_path,
                        output_crf=output_crf,
                        max_height=output_max_height,
                        target_fps=target_fps,
                        overall_has_audio=has_audio,
                        audio_normalize=audio_normalize,
                        audio_denoise=audio_denoise,
                    )
                _completed_count += 1
                _job_patch(job_id, {
                    "detail": f"Extraindo cenas… {_completed_count}/{len(selected)} prontas",
                    "progress_pct": min(78, 48 + int((_completed_count / max(len(selected), 1)) * 30)),
                })
                return idx, clip_path, ok, err

            extraction_results = await asyncio.gather(
                *[_extract_one(i, s) for i, s in enumerate(selected)]
            )

            # Check for failures and assemble ordered clip list
            clip_paths: List[str] = []
            for idx, clip_path, ok, err in sorted(extraction_results, key=lambda r: r[0]):
                if not ok:
                    _job_patch(job_id, {
                        "status": "error",
                        "error": "clip_extract_failed",
                        "detail": f"Falha ao extrair a cena {idx + 1}: {(err or 'ffmpeg_failed')[:260]}",
                    })
                    return
                clip_paths.append(clip_path)

            # Validate clips before concat — skip empty/corrupt ones
            clip_paths, skipped_clips = await asyncio.to_thread(_filter_valid_clips, clip_paths)
            if skipped_clips:
                print(f"[autoeditor][concat] descartados {len(skipped_clips)} clips inválidos: {[os.path.basename(p) for p in skipped_clips]}", flush=True)
            if not clip_paths:
                _job_patch(job_id, {"status": "error", "detail": "Nenhum clip válido para concatenar.", "progress_pct": 0})
                return

            _job_patch(job_id, {"detail": "Concatenando corte final e aplicando transições…", "progress_pct": 82})
            final_path = os.path.join(td, "autoeditor_final.mp4")
            concat_ok = False
            concat_err = ""
            if len(clip_paths) == 1:
                concat_ok, concat_err = await _concat_clips_copy(
                    clip_paths=clip_paths,
                    output_path=final_path,
                )
                if not concat_ok:
                    concat_ok, concat_err = await _concat_clips_reencode(
                        clip_paths=clip_paths,
                        has_audio=has_audio,
                        output_path=final_path,
                        output_crf=output_crf,
                        target_fps=target_fps,
                    )
            else:
                # xfade chain breaks with large clip counts — cap at 30 clips
                has_any_crossfade = (
                    len(clip_paths) <= 30
                    and any(str(item.get("type") or "") == "crossfade" for item in transitions)
                )
                if transition_mode == "none":
                    concat_ok, concat_err = await _concat_clips_reencode(
                        clip_paths=clip_paths,
                        has_audio=has_audio,
                        output_path=final_path,
                        output_crf=output_crf,
                        target_fps=target_fps,
                    )
                elif not has_any_crossfade:
                    concat_ok, concat_err = await _concat_clips_copy(
                        clip_paths=clip_paths,
                        output_path=final_path,
                    )
                    if not concat_ok:
                        concat_ok, concat_err = await _concat_clips_reencode(
                            clip_paths=clip_paths,
                            has_audio=has_audio,
                            output_path=final_path,
                            output_crf=output_crf,
                            target_fps=target_fps,
                        )
                else:
                    concat_ok, concat_err = await _concat_clips_with_transitions(
                        clip_paths=clip_paths,
                        transitions=transitions,
                        has_audio=has_audio,
                        output_path=final_path,
                        output_crf=output_crf,
                        transition_type=transition_type,
                        crossfade_video_sec=crossfade_video_sec,
                        crossfade_audio_sec=crossfade_audio_sec,
                        target_fps=target_fps,
                        main_mod=main_mod,
                    )
            if not concat_ok:
                _job_patch(job_id, {
                    "status": "error",
                    "error": "concat_failed",
                    "detail": f"Falha ao concatenar o resultado final: {(concat_err or 'ffmpeg_failed')[:260]}",
                })
                return

            _job_patch(job_id, {"detail": "Salvando vídeo editado…", "progress_pct": 92})
            original_name = title_hint or Path(source_key).name or "autoeditor.mp4"
            if not original_name.lower().endswith(".mp4"):
                original_name += ".mp4"
            safe_name = f"autoeditor_{job_id[:8]}_{Path(original_name).name}"
            stored = await asyncio.to_thread(
                main_mod._store_local_path,
                src_path=final_path,
                prefix="autoeditor",
                filename=safe_name,
                content_type="video/mp4",
            )
            output_probe = await asyncio.to_thread(main_mod._probe_metadata, final_path)

            result_obj = {
                "auto_editor": {
                    "job_id": job_id,
                    "creator_id": creator_id,
                    "source_video_key": source_key,
                    "source_video_keys": source_keys,
                    "selection_method": selection_method,
                    "selected_scenes": selected,
                    "vision_analysis": vision_analysis or {},
                    "probe": output_probe,
                    "result_video_object_key": stored.get("object_key"),
                    "result_video_url": stored.get("public_url"),
                }
            }
            request_obj = {
                "source": "auto_editor",
                "payload": payload,
            }
            insert_run(
                run_id=job_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                source="auto_editor",
                request_obj=request_obj,
                result_obj=result_obj,
                error=None,
            )

            if delete_source_on_success:
                for key in source_keys:
                    try:
                        await asyncio.to_thread(main_mod._delete_media_ref, media_ref=key, s3=main_mod._s3_client())
                    except Exception:
                        pass

            final_detail = (
                "✓ AutoEditor concluído com sucesso."
                if not llm_note
                else f"✓ AutoEditor concluído com sucesso. Grok indisponível; usei heurística ({llm_note[:140]})."
            )
            if len(source_keys) > 1:
                final_detail += " Cada vídeo foi analisado separadamente antes da montagem final."
            if vision_analysis:
                final_detail += " Vision foi usada para priorizar as cenas."
            elif vision_debug.get("analysis_error") or vision_debug.get("skipped_reason"):
                final_detail += " Vision não conseguiu contribuir nesta execução."
            if not has_audio:
                final_detail += " A fonte analisada não tinha áudio."

            _job_patch(job_id, {
                "status": "done",
                "detail": final_detail,
                "progress_pct": 100,
                "source_video_key": source_key,
                "source_video_keys": source_keys,
                "output_probe": output_probe,
                "selected_scenes": selected,
                "transcript_excerpt": transcript_excerpt,
                "vision_analysis": vision_analysis or {},
                "vision_debug": vision_debug or {},
                "selection_method": selection_method,
                "result_video_object_key": stored.get("object_key", ""),
                "result_video_url": stored.get("public_url", ""),
            })
    except Exception as exc:
        _job_patch(job_id, {
            "status": "error",
            "error": "auto_editor_failed",
            "detail": str(exc),
        })
