import re
import socket
import unicodedata
import statistics
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from xvideos_api.xvideos_api import Client, Pornstar, Channel
from xvideos_api.modules.sorting import Sort, SortDate, SortVideoTime, SortQuality

_XVIDEOS_SOCKET_TIMEOUT = 25  # segundos — previne travamento em scraping


# ── Helpers de slug ──────────────────────────────────────────────────────────

def _name_to_slug(name: str) -> str:
    """Converte nome para slug XVideos: 'Mônica Matos' → 'monica-matos'."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


# ── Mapeamentos ───────────────────────────────────────────────────────────────

# Países → keywords em inglês reconhecidas pelo XVideos
_COUNTRY_MAP: Dict[str, str] = {
    "brasil": "brasileira", "brazil": "brasileira", "br": "brasileira",
    "argentina": "argentina",
    "colombia": "colombiana",
    "mexico": "mexican", "mexico": "mexican",
    "peru": "peruana",
    "chile": "chilena",
    "venezuela": "venezolana",
    "espanha": "spanish", "spain": "spanish",
    "portugal": "portuguese",
    "eua": "american", "usa": "american", "estados unidos": "american", "united states": "american",
    "uk": "british", "reino unido": "british",
    "franca": "french", "france": "french",
    "alemanha": "german", "germany": "german",
    "italia": "italian", "italy": "italian",
    "russia": "russian",
    "japao": "japanese", "japan": "japanese",
    "coreia": "korean", "korea": "korean",
    "china": "chinese",
    "india": "indian",
    "tailandia": "thai", "thailand": "thai",
    "arabia": "arab", "arab": "arab",
    "africa": "african", "africana": "ebony",
    "latina": "latina",
}

# Qtd de atores → keyword textual no XVideos
_ACTOR_COUNT_MAP: Dict[str, str] = {
    "1": "solo",
    "2": "couple",
    "3": "threesome",
    "4": "foursome",
    "5+": "gangbang",
}


# ── Filtros de duração nativos ────────────────────────────────────────────────

def _seconds_to_sort_time(dur_min: Optional[int], dur_max: Optional[int]) -> str:
    """Converte faixa de segundos para o enum SortVideoTime nativo do XVideos."""
    dmin = dur_min or 0
    dmax = dur_max

    if dmin >= 1200:
        return SortVideoTime.Sort_really_long    # 20min+
    if dmin >= 600 and dmax and dmax <= 1200:
        return SortVideoTime.Sort_long_10_20min  # 10-20min
    if dmin >= 600:
        return SortVideoTime.Sort_long           # 10min+
    if dmin >= 180 and dmax and dmax <= 600:
        return SortVideoTime.Sort_middle         # 3-10min
    if dmin >= 60 and dmax and dmax <= 180:
        return SortVideoTime.Sort_short          # 1-3min
    return SortVideoTime.Sort_all


# ── Parser de contagens ("1.2M", "450K") ────────────────────────────────────

def _parse_count(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    s = str(raw).strip().upper().replace(",", "")
    try:
        if "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000)
        if "K" in s:
            return int(float(s.replace("K", "")) * 1_000)
        return int(s)
    except Exception:
        return None


# ── Parser de duração ─────────────────────────────────────────────────────────

def _parse_duration_to_seconds(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.strip().lower()

    h = m = sec = 0
    mh = re.search(r"(\d+)\s*h", s)
    mm = re.search(r"(\d+)\s*min", s)
    ms = re.search(r"(\d+)\s*sec", s)
    if mh:
        h = int(mh.group(1))
    if mm:
        m = int(mm.group(1))
    if ms:
        sec = int(ms.group(1))

    # formatos como 12:34 ou 1:02:03
    if not (mh or mm or ms) and re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s):
        parts = list(map(int, s.split(":")))
        if len(parts) == 2:
            m, sec = parts
        else:
            h, m, sec = parts

    return h * 3600 + m * 60 + sec


def _norm_text(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _actor_match(actor: Optional[str], haystacks: List[str]) -> bool:
    a = _norm_text(actor)
    if not a:
        return True
    a_tokens = [t for t in a.split() if len(t) >= 3] or a.split()
    a_token_set = set(a_tokens)

    for raw in haystacks:
        h = _norm_text(raw)
        if not h:
            continue
        if a in h or h in a:
            return True
        h_tokens = set(h.split())
        common = a_token_set & h_tokens
        if len(common) >= 2:
            return True
        if len(a_tokens) == 1 and common:
            return True
        if any(len(tok) >= 4 for tok in common):
            return True
        if SequenceMatcher(None, a, h).ratio() >= 0.78:
            return True
    return False


def _studio_terms(studio: Optional[str]) -> List[str]:
    s = _norm_text(studio)
    if not s:
        return []
    compact = s.replace(" ", "")
    terms = {compact}
    for suffix in ("studios", "studio", "channel"):
        if compact.endswith(suffix) and len(compact) > len(suffix) + 1:
            terms.add(compact[: -len(suffix)])
    terms.update(t for t in s.split() if len(t) >= 3)
    return [t for t in terms if t]


def _studio_match(studio: Optional[str], haystacks: List[str]) -> bool:
    terms = _studio_terms(studio)
    if not terms:
        return True
    normalized_haystacks = [_norm_text(h) for h in haystacks if _norm_text(h)]
    for h in normalized_haystacks:
        h_compact = h.replace(" ", "")
        for term in terms:
            if term in h_compact:
                return True
    return False


# ── Busca interna ─────────────────────────────────────────────────────────────

def _search(
    *,
    query: str,
    limit: int,
    pages: int = 1,
    sort: Any = None,
    datef: Any = None,
    sorting_time: Any = None,
) -> List:
    socket.setdefaulttimeout(_XVIDEOS_SOCKET_TIMEOUT)
    client = Client()
    videos = []

    kwargs: Dict[str, Any] = {"query": query, "pages": pages}
    if sort is not None:
        kwargs["sorting_sort"] = sort
    if datef is not None:
        kwargs["sorting_date"] = datef
    if sorting_time is not None and sorting_time != SortVideoTime.Sort_all:
        kwargs["sorting_time"] = sorting_time

    for v in client.search(**kwargs):
        videos.append(v)
        if len(videos) >= limit:
            break

    return videos


# ── Serialização ──────────────────────────────────────────────────────────────

def _videos_to_payload(
    videos,
    *,
    dur_min: Optional[int] = None,
    dur_max: Optional[int] = None,
    views_min: Optional[int] = None,
    views_max: Optional[int] = None,
    likes_min: Optional[int] = None,
    actor: Optional[str] = None,
    studio: Optional[str] = None,
) -> Dict[str, Any]:
    """Serializa vídeos e aplica pós-filtros de views/likes."""
    out: List[Dict[str, Any]] = []
    durations: List[int] = []
    tag_counts: Counter = Counter()
    rank = 0

    for v in videos:
        dur_s = getattr(v, "length", None)
        dur = _parse_duration_to_seconds(dur_s)
        if dur is not None:
            durations.append(dur)
        if dur_min is not None and dur is not None and dur < dur_min:
            continue
        if dur_max is not None and dur is not None and dur > dur_max:
            continue

        views_val = _parse_count(getattr(v, "views", None))
        likes_val = _parse_count(getattr(v, "likes", None))

        try:
            tags = list(getattr(v, "tags", []) or [])
        except Exception:
            tags = []
        title = (getattr(v, "title", None) or "")
        description = (getattr(v, "description", None) or "").strip()
        author_name = None
        author_url = None
        try:
            author_obj = getattr(v, "author", None)
            author_name = getattr(author_obj, "name", None) if author_obj else None
            author_url = getattr(author_obj, "url", None) if author_obj else None
        except Exception:
            pass
        pornstars: List[str] = []
        try:
            for ps in (getattr(v, "pornstars", []) or []):
                ps_name = getattr(ps, "name", None)
                if ps_name:
                    pornstars.append(ps_name)
        except Exception:
            pornstars = []

        if not _actor_match(actor, [*pornstars, title, description, " ".join(tags)]):
            continue
        if not _studio_match(studio, [author_name or "", author_url or "", title, description, " ".join(tags)]):
            continue

        # Pós-filtros (só aplicados se valor fornecido E valor parseable)
        if views_min is not None and views_val is not None and views_val < views_min:
            continue
        if views_max is not None and views_val is not None and views_val > views_max:
            continue
        if likes_min is not None and likes_val is not None and likes_val < likes_min:
            continue

        for t in tags:
            tag_counts[t] += 1

        try:
            thumb = v.thumbnail_url if hasattr(v, "thumbnail_url") else None
        except Exception:
            thumb = None

        rank += 1
        out.append({
            "rank": rank,
            "url": getattr(v, "url", None),
            "title": title,
            "description": description,
            "tags": tags,
            "duration_raw": dur_s,
            "duration_seconds": dur,
            "views_raw": getattr(v, "views", None),
            "views_int": views_val,
            "likes_raw": getattr(v, "likes", None),
            "likes_int": likes_val,
            "publish_date": getattr(v, "publish_date", None),
            "thumb": thumb,
            "author_name": author_name,
            "author_url": author_url,
            "pornstars": pornstars,
        })

    avg = statistics.mean(durations) if durations else None
    return {
        "count": len(out),
        "avg_duration_seconds": avg,
        "avg_duration_minutes": (avg / 60 if avg else None),
        "top_tags": tag_counts.most_common(50),
        "videos": out,
    }


# ── Funções públicas ──────────────────────────────────────────────────────────

def fetch_top_videos(limit: int = 20) -> Dict[str, Any]:
    """Vídeos mais vistos agora (sem query, por views, últimos 3 dias)."""
    socket.setdefaulttimeout(_XVIDEOS_SOCKET_TIMEOUT)
    videos = _search(query="", limit=limit, pages=1, sort=Sort.Sort_views, datef=SortDate.Sort_last_3_days)
    payload = _videos_to_payload(videos)
    return {
        "source": "xvideos",
        "method": {"impl": "xvideos_api.search", "params": {"query": "", "sort": "views", "datef": "last_3_days"}},
        **payload,
    }


def fetch_search_videos(
    query: str,
    limit: int = 20,
    sort: str = "views",
    *,
    actor: Optional[str] = None,
    actor_count: Optional[str] = None,
    country: Optional[str] = None,
    category: Optional[str] = None,
    studio: Optional[str] = None,
    dur_min: Optional[int] = None,
    dur_max: Optional[int] = None,
    views_min: Optional[int] = None,
    views_max: Optional[int] = None,
    likes_min: Optional[int] = None,
) -> Dict[str, Any]:
    """Busca XVideos com query textual + filtros nativos da API + pós-filtros."""

    # ── Monta query textual ──
    parts = []
    sq = (query or "").strip()
    if sq:
        parts.append(sq)

    # Ator como keyword (busca por página de pornstar é feita em fetch_pornstar_videos)
    if actor:
        parts.append(f'"{actor.strip()}"')

    # Qtd de atores → keyword semântica
    if actor_count:
        kw = _ACTOR_COUNT_MAP.get(str(actor_count).strip())
        if kw and kw not in " ".join(parts):
            parts.append(kw)

    # País → keyword EN mapeada
    if country:
        country_clean = country.strip().lower()
        country_ascii = unicodedata.normalize("NFKD", country_clean).encode("ascii", "ignore").decode("ascii")
        kw = _COUNTRY_MAP.get(country_clean) or _COUNTRY_MAP.get(country_ascii) or country.strip()
        if kw not in " ".join(parts):
            parts.append(kw)

    # Categoria
    if category:
        cat = category.strip()
        if cat not in " ".join(parts):
            parts.append(cat)

    # Studio entre aspas (busca exata)
    if studio:
        parts.append(f'"{studio.strip()}"')

    full_query = " ".join(parts).strip() or "mature"

    # ── Filtros nativos da API ──
    sorting_sort = (
        Sort.Sort_views if sort == "views" else
        Sort.Sort_rating if sort == "rating" else
        Sort.Sort_relevance
    )
    sorting_time = _seconds_to_sort_time(dur_min, dur_max)

    # Busca mais vídeos quando há pós-filtros para compensar os descartados
    fetch_limit = limit * 3 if (views_min or views_max or likes_min) else limit

    videos = _search(
        query=full_query,
        limit=min(fetch_limit, 60),
        pages=1,
        sort=sorting_sort,
        sorting_time=sorting_time,
    )

    payload = _videos_to_payload(
        videos,
        dur_min=dur_min,
        dur_max=dur_max,
        views_min=views_min,
        views_max=views_max,
        likes_min=likes_min,
        actor=actor,
        studio=studio,
    )
    # Trunca ao limite solicitado após pós-filtro
    payload["videos"] = payload["videos"][:limit]
    payload["count"] = len(payload["videos"])

    return {
        "source": "xvideos",
        "method": {
            "impl": "xvideos_api.search",
            "params": {
                "query": full_query,
                "input_query": query,
                "sort": sort,
                "sorting_time": sorting_time,
                "filters": {
                    "actor": actor,
                    "actor_count": actor_count,
                    "country": country,
                    "category": category,
                    "studio": studio,
                    "dur_min": dur_min,
                    "dur_max": dur_max,
                    "views_min": views_min,
                    "views_max": views_max,
                    "likes_min": likes_min,
                },
            },
        },
        **payload,
    }


def _find_pornstar_url(name: str, client: Client) -> Optional[str]:
    """Busca o nome textualmente e extrai a URL real do perfil de pornstar dos resultados.

    O XVideos usa slugs próprios (ex: /models/monica-mattos) que não seguem
    um padrão previsível a partir do nome digitado. Esta função acha a URL correta
    buscando vídeos com o nome e lendo o atributo .pornstars de cada vídeo.
    """
    name_lower = name.lower().strip()
    name_words = set(name_lower.split())
    seen: set = set()

    try:
        for v in client.search(query=name.replace(" ", "+"), pages=1):
            try:
                for ps in v.pornstars:
                    ps_url = getattr(ps, "url", "") or ""
                    if not ps_url or ps_url in seen:
                        continue
                    seen.add(ps_url)
                    ps_name = (getattr(ps, "name", "") or "").lower().strip()
                    ps_words = set(ps_name.split())
                    # Match se pelo menos 2 palavras coincidem (ou 1 se nome tem 1 palavra)
                    common = name_words & ps_words
                    if len(common) >= min(len(name_words), 2):
                        print(f"_find_pornstar_url: encontrou '{ps_name}' → {ps_url}")
                        return ps_url
            except Exception:
                continue
    except Exception as e:
        print(f"_find_pornstar_url search error: {e}")

    return None


def _find_channel_url(name: str, client: Client) -> Optional[str]:
    """Busca o nome textualmente e extrai a URL real do canal/studio dos resultados."""
    name_lower = name.lower().strip()
    seen: set = set()

    try:
        for v in client.search(query=name.replace(" ", "+"), pages=1):
            try:
                au = v.author
                au_url = getattr(au, "url", "") or ""
                if not au_url or au_url in seen:
                    continue
                seen.add(au_url)
                au_name = (getattr(au, "name", "") or "").lower().strip()
                # Match se canal contém o nome ou vice-versa
                if name_lower in au_name or au_name in name_lower:
                    print(f"_find_channel_url: encontrou '{au_name}' → {au_url}")
                    return au_url
            except Exception:
                continue
    except Exception as e:
        print(f"_find_channel_url search error: {e}")

    return None


def fetch_pornstar_videos(name: str, limit: int = 20) -> Dict[str, Any]:
    """Busca vídeos de uma atriz/ator pela página estruturada de pornstar do XVideos.

    Estratégia: busca textualmente primeiro para achar a URL real do perfil
    (XVideos usa slugs próprios que não seguem padrão previsível), depois
    acessa a página estruturada para buscar todos os vídeos dela.
    """
    socket.setdefaulttimeout(_XVIDEOS_SOCKET_TIMEOUT)
    client = Client()

    # 1. Tenta achar a URL real via busca textual (mais confiável)
    real_url = _find_pornstar_url(name, client)

    # 2. Se não achou, tenta slugs comuns como fallback
    if not real_url:
        slug = _name_to_slug(name)
        for url_base in [
            f"https://xvideos.com/models/{slug}",
            f"https://www.xvideos.com/pornstars/{slug}",
            f"https://www.xvideos.com/model/{slug}",
        ]:
            try:
                test = Pornstar(url=url_base, core=client.core)
                if (test.data.get("nb_videos") or 0) > 0:
                    real_url = url_base
                    break
            except Exception:
                continue

    if real_url:
        try:
            pornstar = Pornstar(url=real_url, core=client.core)
            videos: List = []
            for v in pornstar.videos(pages=1, videos_concurrency=3, pages_concurrency=1):
                videos.append(v)
                if len(videos) >= limit:
                    break
            if videos:
                payload = _videos_to_payload(videos)
                return {
                    "source": "xvideos_pornstar",
                    "pornstar_url": real_url,
                    **payload,
                }
        except Exception as e:
            print(f"fetch_pornstar_videos page error: {e}")

    # Fallback: busca textual com nome exato entre aspas
    print(f"fetch_pornstar_videos fallback textual para: {name}")
    return fetch_search_videos(query=f'"{name}"', limit=limit, sort="relevance")


def fetch_channel_videos(name: str, limit: int = 20) -> Dict[str, Any]:
    """Busca vídeos de um canal/studio pela página estruturada de canal do XVideos.

    Estratégia: igual fetch_pornstar_videos — busca textual para achar URL real.
    """
    socket.setdefaulttimeout(_XVIDEOS_SOCKET_TIMEOUT)
    client = Client()

    # 1. Tenta achar a URL real via busca textual
    real_url = _find_channel_url(name, client)

    # 2. Fallback com slugs comuns
    if not real_url:
        slug = _name_to_slug(name)
        for url_base in [
            f"https://xvideos.com/channels/{slug}",
            f"https://www.xvideos.com/channels/{slug}",
            f"https://www.xvideos.com/profiles/{slug}",
        ]:
            try:
                test = Channel(url=url_base, core=client.core)
                if (test.data.get("nb_videos") or 0) > 0 or (getattr(test, "total_pages", 0) or 0) > 0:
                    real_url = url_base
                    break
            except Exception:
                continue

    if real_url:
        try:
            channel = Channel(url=real_url, core=client.core)
            videos: List = []
            for v in channel.videos(pages=1, videos_concurrency=3, pages_concurrency=1):
                videos.append(v)
                if len(videos) >= limit:
                    break
            if videos:
                payload = _videos_to_payload(videos)
                return {
                    "source": "xvideos_channel",
                    "channel_url": real_url,
                    **payload,
                }
        except Exception as e:
            print(f"fetch_channel_videos page error: {e}")

    # Fallback: busca textual com nome entre aspas
    print(f"fetch_channel_videos fallback textual para: {name}")
    return fetch_search_videos(query=f'"{name}"', limit=limit, sort="views")
