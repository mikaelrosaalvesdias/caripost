"""
Trend briefing generator — uses Grok (or configured LLM) to produce
personalized content briefings for each creator.

Now enriched with real data from the creator's reference channels.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db_agency import (
    creator_get, trend_raw_list, trend_channel_videos_for_creator,
    briefing_create, publications_by_creator,
)
from ..llm import ProviderSpec, run_providers_to_completion
from ..db import settings_get

logger = logging.getLogger(__name__)

TREND_BRIEFING_PROMPT = """\
Você é um produtor pornô raiz, com 18 anos de bagunça pesada. Tá falando comigo como se a gente \
estivesse os dois no camarim, fumando um cigarro depois da gravação, porta fechada, sem câmera, sem frescura. \
Só papo reto de produtor pra produtor.

Fala com gíria de camarim: "mano", "porra", "cara", "tá ligado", "essa merda", "vai bombar pra caralho", \
"o pau vai agradecer", "a puta vai gritar" etc. Seja sujo, direto e sem nenhum filtro. \
Aqui a gente fala pau latejando, buceta pingando, cu arrombado, garganta destruída, gozada grossa, \
creampie escorrendo, squirt jorrando no chão — tudo na cara.

CRIADOR: {creator_name}
CATEGORIAS QUE ELE FAZ: {preferred_categories}
TAGS QUE ELE USA: {preferred_tags}
CANAIS QUE ELE ASSISTE PARA SE INSPIRAR: {reference_channels}

===== PERFIL DE PRODUÇÃO DO CRIADOR (O QUE ELE CONSEGUE FAZER DE VERDADE) =====
Setup de filmagem: {filming_setup}
Performers: {performer_description}
Local de gravação: {location_type}
Nível de produção: {production_level}
Limitações e restrições: {production_constraints}

===== ANÁLISE DO PRÓPRIO CANAL DO CRIADOR (vídeos dele com mais views) =====
{own_channel_analysis}

===== VÍDEOS REAIS DOS CANAIS DE REFERÊNCIA (dados coletados agora) =====
{channel_top_videos}

===== O QUE ESTÁ BOMBANDO NA PLATAFORMA ESSA SEMANA =====
{trending_videos_summary}

===== VÍDEOS QUE ELE JÁ PUBLICOU =====
{recent_videos}

===== SUA TAREFA =====
Mano, olha esses números aí. Vê o que tá passando de 500K views pra cima. \
Me fala na cara dura que tipo de foda braba o {creator_name} tem que gravar essa semana pra explodir de view.

REGRA FUNDAMENTAL: Tudo que você sugerir tem que caber na realidade desse criador. \
Se ele grava sozinho, não manda fazer gangbang. Se é amador em casa, não fala em estúdio profissional. \
Adapta o fetiche, a fantasia e a pegada pro setup real dele — é isso que distingue produtor foda de idiota. \
Fala direto o que mandar a puta fazer: posição, buraco, intensidade, quanto de porra, como humilhar, \
como arrombar, como terminar. Sem enrolação.

Pra cada sugestão, joga também um `image_prompt` bem safado em inglês pra thumbnail. \
Usa o perfil físico real do criador pra descrever os performers — não inventa corpo que não existe.

REGRA FODA sobre reference_url: só bota URL se tiver EXATAMENTE nos dados acima no campo "URL:". \
Se não tiver, coloca null. Nunca inventa porra nenhuma. Copia e cola direto do input ou null.

Responde SOMENTE com este JSON (sem markdown, sem explicação, sem texto fora do JSON, puro e cru):
{{
  "market_summary": "2-3 frases bem no jeito de camarim: o que tá fazendo o pau gozar mais essa semana, \
números reais, que tipo de foda tá dominando",
  "creator_profile_analysis": "análise honesta do que tá funcionando no próprio canal do criador — \
quais categorias e tags performam melhor, qual formato gera mais view, o que ele deve continuar e o que tá \
perdendo tempo",
  "top_channel_insights": [
    {{
      "channel": "nome ou url do canal",
      "best_format": "fala direto o que esse canal tá mandando bem — ex: POV garganta profunda no banheiro, \
anal sem vaselina, bukkake com 8 caras",
      "top_tags": ["tag1", "tag2", "tag3", "tag4"],
      "opportunity": "o que o {creator_name} pode roubar e deixar ainda mais pesado no estilo e no setup dele"
    }}
  ],
  "suggestions": [
    {{
      "title": "Título bem puto e otimizado pra rankear",
      "concept": "Descreve cena por cena bem explícito e sujo: começa com a puta fazendo o que, depois fode \
em qual buraco, posição, como arromba, como termina (gozada na cara, creampie, squirt etc) — tudo adaptado \
pro setup real do criador",
      "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],
      "why_trending": "Por que essa merda vai bombar agora — cita os dados reais dos canais",
      "why_fits_creator": "Por que essa cena cabe no setup e no perfil real do {creator_name}",
      "reference_url": null,
      "difficulty": "easy|medium|hard",
      "view_potential": "low|medium|high|viral",
      "image_prompt": "Photorealistic hardcore porn thumbnail, ultra detailed 8k: [descreve os corpos \
baseado no perfil real do criador, pau, buceta, cu, fluidos, expressões de prazer e degradação, ângulo \
da câmera, iluminação — tudo bem explícito e pornográfico possível]"
    }}
  ],
  "avoid": ["quais tipos de vídeo estão saturados pra caralho e não vale a pena gravar agora, e o que não \
é viável pra esse criador — e por quê"],
  "generated_at": "{now}"
}}"""


def _get_provider() -> Optional[ProviderSpec]:
    """Always use Grok for adult content briefings. Falls back to openrouter grok-3-fast if needed."""
    try:
        from ..db import settings_get
        # Grok is mandatory for adult content — no content filtering, best for this use case
        for provider_name, model in [
            ("grok", "grok-3"),
            ("openrouter", "x-ai/grok-3-fast"),
        ]:
            saved = settings_get(key=f"token:{provider_name}")
            if saved and saved.get("value"):
                logger.info("Briefing LLM provider: %s / %s", provider_name, model)
                return ProviderSpec(
                    name=provider_name,  # type: ignore[arg-type]
                    model=model,
                    api_key=saved["value"],
                )
        logger.warning("No Grok API key configured — briefings require Grok (token:grok or token:openrouter)")
        return None
    except Exception:
        return None


def _format_channel_videos(channel_rows: List[Dict]) -> str:
    """Format channel video data into a concise text block for the LLM."""
    if not channel_rows:
        return "Nenhum dado coletado ainda dos canais de referência. Configure os canais e colete os dados."

    # Group by channel
    by_channel: Dict[str, List[Dict]] = {}
    for row in channel_rows:
        data = row.get("data") or {}
        ch = str(data.get("channel_url") or row.get("platform") or "canal")
        by_channel.setdefault(ch, []).append(data)

    lines = []
    for ch, videos in by_channel.items():
        # Sort by views, top 10
        videos.sort(key=lambda v: int(v.get("views") or 0), reverse=True)
        top = videos[:10]
        lines.append(f"\n### Canal: {ch}")
        for i, v in enumerate(top, 1):
            title = v.get("title") or "sem título"
            views = int(v.get("views") or 0)
            tags = ", ".join(str(t) for t in (v.get("tags") or [])[:8]) or "—"
            url = v.get("url") or ""
            views_fmt = f"{views/1_000_000:.1f}M" if views >= 1_000_000 else f"{views/1000:.0f}K" if views >= 1000 else str(views)
            lines.append(f"  {i}. [{views_fmt} views] {title}")
            if tags != "—":
                lines.append(f"     Tags: {tags}")
            if url:
                lines.append(f"     URL: {url}")

    return "\n".join(lines) if lines else "Sem dados de canais de referência."


async def _check_url(url: str, client) -> bool:
    """Return True if URL returns HTTP 200-399."""
    try:
        r = await client.head(url, follow_redirects=True, timeout=6.0)
        if r.status_code < 400:
            return True
        # HEAD blocked — try GET with range to avoid downloading
        r2 = await client.get(url, follow_redirects=True, timeout=8.0,
                              headers={"Range": "bytes=0-0"})
        return r2.status_code < 400 or r2.status_code == 416  # 416 = range not satisfiable = exists
    except Exception:
        return False


async def _validate_briefing_urls(content: Dict[str, Any]) -> Dict[str, Any]:
    """Validate all reference_urls in suggestions concurrently. Removes dead/hallucinated links."""
    suggestions = content.get("suggestions") or []
    urls_to_check = [
        (i, s["reference_url"])
        for i, s in enumerate(suggestions)
        if s.get("reference_url") and str(s["reference_url"]).startswith("http")
    ]
    if not urls_to_check:
        return content

    import httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(headers=headers, verify=False) as client:
        results = await asyncio.gather(
            *[_check_url(url, client) for _, url in urls_to_check],
            return_exceptions=True,
        )

    removed = 0
    for (idx, url), ok in zip(urls_to_check, results):
        if not ok or isinstance(ok, Exception):
            logger.info("[briefing] reference_url inválida removida: %s", url)
            suggestions[idx]["reference_url"] = None
            removed += 1

    if removed:
        logger.info("[briefing] %d/%d reference_urls removidas por serem inválidas", removed, len(urls_to_check))

    content["suggestions"] = suggestions
    return content


def _analyze_own_channel(own_channel_rows: List[Dict]) -> str:
    """Summarize creator's own scraped channel data — top videos, best tags, patterns."""
    if not own_channel_rows:
        return "Nenhum dado coletado do canal próprio do criador ainda."

    videos = []
    for row in own_channel_rows:
        data = row.get("data") or {}
        videos.append(data)

    videos.sort(key=lambda v: int(v.get("views") or 0), reverse=True)
    top = videos[:15]

    # Aggregate tags
    tag_counts: Dict[str, int] = {}
    for v in videos:
        for t in (v.get("tags") or []):
            tag_counts[str(t)] = tag_counts.get(str(t), 0) + 1
    top_tags = sorted(tag_counts, key=lambda t: tag_counts[t], reverse=True)[:10]

    lines = ["Vídeos com mais views no canal próprio:"]
    for i, v in enumerate(top, 1):
        title = v.get("title") or "sem título"
        views = int(v.get("views") or 0)
        tags = ", ".join(str(t) for t in (v.get("tags") or [])[:6]) or "—"
        views_fmt = f"{views/1_000_000:.1f}M" if views >= 1_000_000 else f"{views/1000:.0f}K" if views >= 1000 else str(views)
        lines.append(f"  {i}. [{views_fmt} views] {title}")
        if tags != "—":
            lines.append(f"     Tags: {tags}")
    if top_tags:
        lines.append(f"\nTags que mais aparecem nos vídeos dele: {', '.join(top_tags)}")

    return "\n".join(lines)


async def generate_briefing_for_creator(creator_id: str) -> Optional[Dict[str, Any]]:
    """Generate a trend briefing for one creator. Returns briefing dict or None."""
    creator = creator_get(creator_id)
    if not creator:
        logger.warning("Creator %s not found", creator_id)
        return None

    # Gather recent publications
    recent_pubs = publications_by_creator(creator_id, limit=10)
    recent_titles_str = "Nenhum vídeo publicado ainda"

    # Gather channel-specific data (real scraped videos — reference channels)
    channel_rows = trend_channel_videos_for_creator(creator_id, limit=200)

    # Separate own channel rows from reference channel rows
    own_channel_urls = set(str(u).lower() for u in (creator.get("own_channel_urls") or []))
    if own_channel_urls:
        own_rows = [r for r in channel_rows if str((r.get("data") or {}).get("channel_url") or "").lower() in own_channel_urls]
        ref_rows = [r for r in channel_rows if str((r.get("data") or {}).get("channel_url") or "").lower() not in own_channel_urls]
    else:
        own_rows = []
        ref_rows = channel_rows

    channel_videos_text = _format_channel_videos(ref_rows)
    own_channel_analysis = _analyze_own_channel(own_rows)

    # Gather global trending data
    trends = trend_raw_list(limit=100)
    trending_summary_parts = []
    for t in trends[:30]:
        data = t.get("data") or {}
        title = data.get("title") or data.get("name") or ""
        if title:
            views = data.get("views") or data.get("nb_visits") or ""
            trending_summary_parts.append(f"{title}" + (f" ({views} views)" if views else ""))
    trending_summary = "; ".join(trending_summary_parts[:20]) or "Sem dados de tendências globais"

    # Production profile
    filming_setup_labels = {
        "solo": "solo (filma sozinho/a)",
        "couple": "casal fixo",
        "small_group": "grupo pequeno (3-4 pessoas)",
        "large_group": "grupo grande / orgia",
    }
    location_labels = {
        "home": "casa / apartamento",
        "studio": "estúdio profissional",
        "outdoor": "ar livre / externo",
        "hotel": "hotel / motel",
    }
    level_map = {
        "amateur": "amador (câmera simples, sem iluminação profissional)",
        "semi-pro": "semi-profissional (boa câmera, iluminação básica)",
        "professional": "profissional (câmera profissional, iluminação completa, pós-produção)",
    }

    filming_setups = creator.get("filming_setups") or []
    filming_setup = ", ".join(filming_setup_labels.get(s, s) for s in filming_setups) if filming_setups else "não informado"
    location_types = creator.get("location_types") or []
    location_type = ", ".join(location_labels.get(l, l) for l in location_types) if location_types else "não informado"
    production_level = level_map.get(creator.get("production_level") or "amateur", creator.get("production_level") or "amador")
    performer_description = creator.get("performer_description") or "Não informado"
    production_constraints = creator.get("production_constraints") or "Nenhuma restrição informada"

    now = datetime.now(timezone.utc).isoformat()
    prompt = TREND_BRIEFING_PROMPT.format(
        creator_name=creator["name"],
        preferred_categories=", ".join(creator.get("preferred_categories") or []) or "Não especificado",
        preferred_tags=", ".join(creator.get("preferred_tags") or []) or "Não especificado",
        reference_channels=", ".join(str(c) for c in (creator.get("reference_channels") or [])) or "Não configurado",
        filming_setup=filming_setup,
        performer_description=performer_description,
        location_type=location_type,
        production_level=production_level,
        production_constraints=production_constraints,
        own_channel_analysis=own_channel_analysis,
        channel_top_videos=channel_videos_text,
        trending_videos_summary=trending_summary,
        recent_videos=recent_titles_str,
        now=now,
    )

    provider = _get_provider()
    if not provider:
        logger.warning("No LLM provider configured — cannot generate briefing")
        return None

    try:
        results = await run_providers_to_completion(
            providers=[provider],
            prompt=prompt,
            params={"temperature": 0.5, "max_tokens": 4000},
        )
        if not results or not results[0].get("ok") or not results[0].get("text"):
            logger.error("LLM returned empty result for briefing")
            return None
        result_text = results[0]["text"]

        text = result_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        content = json.loads(text)
        # Validate reference_urls — remove hallucinated/dead links before saving
        content = await _validate_briefing_urls(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse briefing JSON: %s\nRaw: %.500s", exc, result_text)
        content = {"market_summary": result_text[:500], "suggestions": [], "avoid": [], "raw": result_text}
    except Exception as exc:
        logger.error("Briefing generation failed for %s: %s", creator_id, exc)
        return None

    briefing_id = str(uuid.uuid4())
    generated_at = now
    briefing_create({
        "briefing_id": briefing_id,
        "creator_id": creator_id,
        "content": content,
        "generated_at": generated_at,
    })

    briefing = {
        "briefing_id": briefing_id,
        "creator_id": creator_id,
        "content": content,
        "generated_at": generated_at,
    }

    # Send Telegram notification
    try:
        await _send_briefing_telegram(creator, briefing)
    except Exception as exc:
        logger.warning("Telegram notification failed for briefing %s: %s", briefing_id, exc)

    return briefing


async def _send_briefing_telegram(creator: Dict[str, Any], briefing: Dict[str, Any]) -> None:
    """Send a briefing notification to Telegram groups via n8n webhook."""
    from ..db import settings_get
    webhook_row = settings_get(key="telegram:n8n_webhook_url")
    webhook_url = (webhook_row["value"] if webhook_row else "").strip()
    if not webhook_url:
        return

    content = briefing.get("content") or {}
    suggestions = content.get("suggestions") or []
    top3 = suggestions[:3]

    lines = [
        f"📊 *Novo Briefing — {creator['name']}*",
        f"_{content.get('market_summary', '')}_",
        "",
        "🎬 *Sugestões principais:*",
    ]
    for i, s in enumerate(top3, 1):
        potential = s.get("view_potential", "")
        emoji = {"viral": "🔥", "high": "⬆️", "medium": "➡️", "low": "⬇️"}.get(potential, "")
        lines.append(f"{i}. {emoji} *{s.get('title', '')}*")
        lines.append(f"   {s.get('concept', '')}")

    if content.get("avoid"):
        lines += ["", "⚠️ *Evitar esta semana:*"]
        for a in content["avoid"][:3]:
            lines.append(f"• {a}")

    lines += ["", f"📅 Gerado em: {str(briefing.get('generated_at',''))[:10]}"]

    import httpx as _httpx
    payload = {
        "type": "briefing",
        "creator_id": creator["creator_id"],
        "creator_name": creator["name"],
        "briefing_id": briefing["briefing_id"],
        "text": "\n".join(lines),
        "suggestions_count": len(suggestions),
    }
    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            await client.post(webhook_url, json=payload)
    except Exception as exc:
        logger.warning("Telegram webhook call failed: %s", exc)


async def generate_briefings_for_all_creators() -> Dict[str, Any]:
    """Generate briefings for all active creators. Called by cron."""
    from ..db_agency import creator_list
    creators = creator_list(status="active")
    results: Dict[str, Any] = {"generated": 0, "failed": 0, "creators": []}
    for creator in creators:
        try:
            b = await generate_briefing_for_creator(creator["creator_id"])
            if b:
                results["generated"] += 1
                results["creators"].append({
                    "creator_id": creator["creator_id"],
                    "briefing_id": b["briefing_id"],
                })
            else:
                results["failed"] += 1
        except Exception as exc:
            logger.error("Briefing failed for %s: %s", creator["creator_id"], exc)
            results["failed"] += 1
    return results
