"""
DMCA scanner: searches for infringing copies of a creator's content online.
Uses Google search (via httpx) and title/thumbnail matching.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from ..db_agency import creator_get, publications_by_creator, dmca_create

logger = logging.getLogger(__name__)

# Known legitimate platform domains (not infringing)
LEGITIMATE_DOMAINS = {
    "xvideos.com", "pornhub.com", "xnxx.com", "xhamster.com", "redtube.com",
    "tube8.com", "youporn.com", "beeg.com", "spankbang.com", "eporner.com",
    "onlyfans.com", "fansly.com", "manyvids.com", "clips4sale.com",
}

# Headers to mimic a browser for search requests
_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def _domain_from_url(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _is_legitimate(url: str) -> bool:
    domain = _domain_from_url(url)
    return any(domain.endswith(d) for d in LEGITIMATE_DOMAINS)


async def _google_search_urls(query: str, limit: int = 10) -> List[str]:
    """Do a Google search and extract result URLs. Returns list of URLs."""
    try:
        encoded = quote_plus(query)
        search_url = f"https://www.google.com/search?q={encoded}&num={limit}&hl=pt-BR"
        async with httpx.AsyncClient(headers=_SEARCH_HEADERS, timeout=20, follow_redirects=True) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                return []
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            urls = []
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                if href.startswith("/url?q="):
                    actual = href[7:].split("&")[0]
                    if actual.startswith("http") and not _is_legitimate(actual):
                        urls.append(actual)
            return list(dict.fromkeys(urls))[:limit]  # deduplicate
    except Exception as exc:
        logger.warning("Google search failed for '%s': %s", query, exc)
        return []


async def scan_creator(creator_id: str) -> Dict[str, Any]:
    """
    Scan for DMCA infringements for a single creator.
    Returns a dict with scan results.
    """
    creator = creator_get(creator_id)
    if not creator:
        return {"error": "creator_not_found"}

    creator_name = creator["name"]
    publications = publications_by_creator(creator_id, limit=50)

    detected: List[Dict] = []
    now = datetime.now(timezone.utc).isoformat()

    # Search by creator name
    name_queries = [
        f'"{creator_name}" porn site:xleaks.net OR site:thothub.tv OR site:coomer.su',
        f'"{creator_name}" leaked video',
    ]

    for query in name_queries:
        await asyncio.sleep(2)  # rate-limit Google queries
        urls = await _google_search_urls(query, limit=10)
        for url in urls:
            detected.append({
                "infringement_id": str(uuid.uuid4()),
                "creator_id": creator_id,
                "original_video_id": None,
                "original_url": f"https://xvideos.com/{creator_name}",  # best-effort
                "infringing_url": url,
                "infringing_site": _domain_from_url(url),
                "detection_method": "google_search",
                "confidence": 0.6,
                "status": "detected",
                "notes": f"Query: {query}",
                "detected_at": now,
            })

    # Search by video titles
    for pub in publications[:10]:
        title = pub.get("metadata", {}).get("title") if isinstance(pub.get("metadata"), dict) else None
        if not title:
            continue
        await asyncio.sleep(1)
        query = f'"{title}" -{" -".join(LEGITIMATE_DOMAINS)}'
        urls = await _google_search_urls(query, limit=5)
        for url in urls:
            detected.append({
                "infringement_id": str(uuid.uuid4()),
                "creator_id": creator_id,
                "original_video_id": pub.get("video_id_platform"),
                "original_url": pub.get("video_url", ""),
                "infringing_url": url,
                "infringing_site": _domain_from_url(url),
                "detection_method": "title_match",
                "confidence": 0.8,
                "status": "detected",
                "notes": f"Title match: {title}",
                "detected_at": now,
            })

    # Deduplicate by infringing_url
    seen_urls: set = set()
    unique_detected = []
    for d in detected:
        if d["infringing_url"] not in seen_urls:
            seen_urls.add(d["infringing_url"])
            unique_detected.append(d)

    # Persist to DB
    for inf in unique_detected:
        try:
            dmca_create(inf)
        except Exception as exc:
            logger.warning("Could not save infringement: %s", exc)

    logger.info("DMCA scan for %s: %d potential infringements found", creator_name, len(unique_detected))
    return {
        "creator_id": creator_id,
        "scanned_at": now,
        "infringements_found": len(unique_detected),
        "infringement_ids": [d["infringement_id"] for d in unique_detected],
    }
