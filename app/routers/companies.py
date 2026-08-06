"""
Companies (Clientes) router — CRUD, brand kit, competitors, assets.
Mirrors caripost-web's company management features.
"""
from __future__ import annotations

import os
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..db_companies import (
    company_list, company_get, company_create, company_update, company_delete,
    brand_kit_get, brand_kit_upsert, brand_kit_extras_patch, brand_kit_apply_auto,
    normalize_brand_colors,
    competitor_list, competitor_create, competitor_delete,
    asset_list, asset_create, asset_delete, asset_get, asset_update_meta,
    asset_list_logos, asset_list_photos, asset_clear_primary, asset_set_primary_logo,
    asset_claim_primary_logo_if_empty,
    product_list, product_get, product_create, product_copy, product_update, product_delete,
    solution_list, solution_get, solution_create, solution_update, solution_delete,
)
from ..db import settings_get

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ENRICHMENT_RUNNING: set[str] = set()
_ENRICHMENT_GUARD = threading.Lock()


def _enrichment_status(company_id: str) -> Dict[str, Any]:
    extras = (brand_kit_get(company_id) or {}).get("extras") or {}
    status = dict(extras.get("enrichment") or {})
    if status.get("state") not in ("queued", "running"):
        return status
    with _ENRICHMENT_GUARD:
        active_here = company_id in _ENRICHMENT_RUNNING
    if active_here:
        return status
    # Threads are intentionally in-process. After a deploy/restart, turn an abandoned marker into
    # a retryable failure instead of leaving the UI spinning forever.
    timestamp = status.get("started_at") if status.get("state") == "running" else status.get("queued_at")
    try:
        when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        stale = datetime.now(timezone.utc) - when > timedelta(minutes=15)
    except Exception:
        stale = True
    if stale:
        return _store_enrichment_status(
            company_id,
            state="failed",
            stage="failed",
            message="A importação foi interrompida por uma reinicialização. Tente novamente.",
            error="Importação interrompida antes da conclusão.",
            finished_at=_now(),
        )
    return status


def _store_enrichment_status(
    company_id: str, *, run_id: Optional[str] = None, replace: bool = False, **patch: Any,
) -> Dict[str, Any]:
    """Persist lightweight progress so create/update and the UI share one truthful flow."""
    current = brand_kit_get(company_id) or {}
    extras = dict(current.get("extras") or {})
    previous = dict(extras.get("enrichment") or {})
    if run_id and not replace and previous.get("run_id") not in (None, run_id):
        return previous
    status = {} if replace else previous
    if run_id:
        status["run_id"] = run_id
    status.update({key: value for key, value in patch.items() if value is not None})
    brand_kit_extras_patch(company_id, {"enrichment": status})
    return status


# ─────────────────────────────────────────────────────────────────────────────
# Companies CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_companies(request: Request, active: Optional[bool] = None, limit: int = 200):
    err = _api_key_required(request)
    if err:
        return err
    companies = company_list(active_only=active if active is not None else False, limit=limit)
    from ..main_utils import scoped_company_ids
    scids = scoped_company_ids(request)
    if scids is not None:
        companies = [c for c in companies if str(c.get("id")) in scids]   # tenancy: só as empresas do usuário
    return {"companies": companies}


@router.get("/{company_id}")
def get_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    status = _enrichment_status(company_id)
    if status and status != (((company.get("brand_kit") or {}).get("extras") or {}).get("enrichment") or {}):
        company = company_get(company_id) or company
    # attach competitors and assets
    company["competitors"] = competitor_list(company_id)
    company["references"] = asset_list(company_id, role="brand_reference")
    return {"company": company}


@router.post("")
async def create_company(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    if not body.get("name"):
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    # parse socials
    socials: Dict[str, str] = dict(body.get("socials") or {})
    for key in ("instagram", "facebook", "tiktok"):
        val = body.get(f"social_{key}")
        if val:
            socials[key] = val
    # parse inline competitors
    competitors = body.get("competitors") or []
    data = {
        "name": body.get("name"),
        "segment": body.get("segment"),
        "city": body.get("city"),
        "state": body.get("state"),
        "website": body.get("website"),
        "phone": body.get("phone"),
        "email": body.get("email"),
        "socials": socials,
        "notes": body.get("notes"),
        "competitors": competitors,
    }
    from ..main_utils import _session_of
    sess = _session_of(request) or {}
    if sess.get("role") == "owner":
        return JSONResponse({"detail": "Seu acesso é de empresa única. Fale com seu consultor para virar agência.",
                             "error": "feature_blocked"}, status_code=403)
    company = company_create(data)
    if sess.get("role") == "agency":
        try:
            company_update(company["id"], {"owner_user_id": sess.get("user_id")})   # empresa da AGÊNCIA
            company = company_get(company["id"])
        except Exception:
            pass
    # Cadastro e importação usam um único fluxo observável. A resposta já contém o status persistido,
    # e a tela acompanha cada etapa sem depender de um segundo botão escondido.
    enrichment = None
    if (company.get("website") or "").strip() or any((company.get("socials") or {}).get(k) for k in ("instagram", "facebook")):
        enrichment = _spawn_bg_enrich(company["id"])
        company = company_get(company["id"])
    return {"company": company, "enrichment": enrichment}


def _spawn_bg_enrich(company_id: str, overrides: Optional[Dict[str, Any]] = None):
    """Start one in-process enrichment per company and expose its real progress in the DB."""
    with _ENRICHMENT_GUARD:
        already_running = company_id in _ENRICHMENT_RUNNING
        if not already_running:
            _ENRICHMENT_RUNNING.add(company_id)
    if already_running:
        return _enrichment_status(company_id)
    run_id = uuid.uuid4().hex
    try:
        queued = _store_enrichment_status(
            company_id, run_id=run_id, replace=True,
            state="queued",
            stage="queued",
            message="Preparando a importação da identidade…",
            queued_at=_now(),
            warnings=[],
            logos_added=0,
            logos_total=0,
            colors_found=0,
            products_added=0,
            palette_preserved=False,
            error="",
        )
    except Exception as exc:
        with _ENRICHMENT_GUARD:
            _ENRICHMENT_RUNNING.discard(company_id)
        return {"state": "failed", "stage": "failed", "error": str(exc)[:300]}

    def _bg(cid: str, payload: Dict[str, Any], rid: str):
        try:
            _run_company_enrichment(cid, payload, run_id=rid)
        except Exception as exc:
            _store_enrichment_status(
                cid, run_id=rid,
                state="failed",
                stage="failed",
                message="Não foi possível concluir a importação.",
                error=str(exc)[:300],
                finished_at=_now(),
            )
        finally:
            with _ENRICHMENT_GUARD:
                _ENRICHMENT_RUNNING.discard(cid)

    try:
        threading.Thread(
            target=_bg, args=(company_id, dict(overrides or {}), run_id), daemon=True,
        ).start()
    except Exception as exc:
        with _ENRICHMENT_GUARD:
            _ENRICHMENT_RUNNING.discard(company_id)
        return _store_enrichment_status(
            company_id, run_id=run_id, state="failed", stage="failed",
            message="Não foi possível iniciar a importação.", error=str(exc)[:300], finished_at=_now(),
        )
    return queued


@router.put("/{company_id}")
async def update_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    # merge socials
    # Copy before editing: mutating the existing dict made old/new sources identical and
    # prevented automatic enrichment after Instagram/Facebook were added.
    socials = dict(existing.get("socials") or {})
    for key in ("instagram", "facebook", "tiktok"):
        val = body.get(f"social_{key}")
        if val is not None:
            if val:
                socials[key] = val
            elif key in socials:
                del socials[key]
    if "socials" in body:
        socials = body["socials"]
    data = {k: v for k, v in body.items() if k not in ("social_instagram", "social_facebook", "social_tiktok")}
    data["socials"] = socials
    _old_identity_sources = (
        (existing.get("website") or "").strip(),
        ((existing.get("socials") or {}).get("instagram") or "").strip(),
        ((existing.get("socials") or {}).get("facebook") or "").strip(),
    )
    company = company_update(company_id, data)
    # Uma fonte oficial adicionada ou alterada inicia o mesmo fluxo observável do cadastro.
    _new_identity_sources = (
        (company.get("website") or "").strip(),
        ((company.get("socials") or {}).get("instagram") or "").strip(),
        ((company.get("socials") or {}).get("facebook") or "").strip(),
    )
    if any(_new_identity_sources) and _new_identity_sources != _old_identity_sources:
        try:
            _spawn_bg_enrich(company_id)
        except Exception:
            pass
    return {"company": company}


@router.delete("/{company_id}")
def delete_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    ok = company_delete(company_id)
    if not ok:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Brand kit
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_manual_colors(colors: Any) -> Dict[str, str]:
    """Validate a user-curated palette and guarantee its canonical primary color."""
    if not isinstance(colors, dict) or not colors:
        raise ValueError("Adicione pelo menos uma cor principal.")
    cleaned: Dict[str, str] = {}
    seen = set()
    aliases = {
        "primary": "primary", "primarycolor": "primary", "primarycolour": "primary",
        "principal": "primary", "primaria": "primary", "corprincipal": "primary", "corprimaria": "primary",
        "secondary": "secondary", "secondarycolor": "secondary", "secondarycolour": "secondary",
        "secundaria": "secondary", "corsecundaria": "secondary",
        "accent": "accent", "accentcolor": "accent", "accentcolour": "accent",
        "destaque": "accent", "cordestaque": "accent",
    }
    for raw_name, raw_hex in colors.items():
        name = str(raw_name or "").strip()
        value = str(raw_hex or "").strip()
        if not name or not value:
            raise ValueError("Todas as cores precisam de nome e hexadecimal.")
        compact = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        compact = re.sub(r"[^a-z0-9]+", "", compact)
        name = aliases.get(compact, name)
        key = name.lower()
        if key in seen:
            raise ValueError(f'Nome de cor repetido: "{name}".')
        seen.add(key)
        raw = value.lstrip("#")
        if re.fullmatch(r"[0-9a-fA-F]{3}", raw):
            raw = "".join(char * 2 for char in raw)
        if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
            raise ValueError(f'Cor inválida em "{name}". Use #RRGGBB.')
        cleaned[name] = "#" + raw.upper()
    return normalize_brand_colors(cleaned)

@router.get("/{company_id}/brand-kit")
def get_brand_kit(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    bk = brand_kit_get(company_id)
    return {"brand_kit": bk}


@router.post("/{company_id}/brand-kit")
async def save_brand_kit(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    colors = {}
    for key in ("primaryColor", "secondaryColor", "accentColor"):   # legado (3 fixas)
        if key in body:
            mapped = key.replace("Color", "")
            colors[mapped] = body[key]
    data: Dict[str, Any] = {}
    if isinstance(body.get("colors"), dict):
        # PALETA LIVRE: o usuário define QUANTAS cores quiser (nome → hex). SUBSTITUI a paleta inteira
        # (permite remover cor). Todas entram nos prompts via _palette_str.
        try:
            data["colors"] = _normalize_manual_colors(body["colors"])
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
    elif colors:
        if existing.get("brand_kit") and existing["brand_kit"].get("colors"):
            merged = existing["brand_kit"]["colors"].copy()
            merged.update(colors)
            colors = merged
        try:
            data["colors"] = _normalize_manual_colors(colors)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
    editable_fields = ("logo_url", "voice", "persona", "visual_prompt_base", "audience", "assuntos", "client_rules")
    for key in editable_fields:
        if key in body:
            data[key] = body[key]
    kit = existing.get("brand_kit") or {}
    extras = dict(kit.get("extras") or {})
    manual_fields = set(extras.get("manual_fields") or [])
    manual_fields.update(key for key in editable_fields if key in body)
    extra_patch: Dict[str, Any] = {}
    if manual_fields:
        extra_patch["manual_fields"] = sorted(manual_fields)
    if "colors" in data:
        extra_patch["palette_source"] = "manual"
        extra_patch["palette_curated_at"] = _now()
    if extra_patch:
        data["source"] = "MANUAL"
    if extra_patch:
        brand_kit_extras_patch(company_id, extra_patch)
    bk = brand_kit_upsert(company_id, data)
    return {"brand_kit": bk}


@router.get("/{company_id}/creative-config")
def get_creative_config(company_id: str, request: Request):
    """Config criativa do cliente: defaults globais + override atual (nada travado no código)."""
    err = _api_key_required(request)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    from ..services.ai import CREATIVE_DEFAULTS
    from ..services.template_composer import EDITORIAL_DESIGN
    defaults = {**CREATIVE_DEFAULTS, "design": EDITORIAL_DESIGN}
    override = (co.get("brand_kit") or {}).get("creative_config") or {}
    return {"defaults": defaults, "override": override}


@router.post("/{company_id}/creative-config")
async def save_creative_config(company_id: str, request: Request):
    """Salva os overrides criativos do cliente (prompts/regras/design/imagem/vídeo). {} = restaura padrão."""
    err = _api_key_required(request)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    override = body.get("creative_config")
    if override is None:
        override = body.get("override") or {}
    if not isinstance(override, dict):
        return JSONResponse({"detail": "creative_config deve ser um objeto"}, status_code=422)
    brand_kit_upsert(company_id, {"creative_config": override})
    return {"ok": True, "override": override}


# ─────────────────────────────────────────────────────────────────────────────
# Logo upload
# ─────────────────────────────────────────────────────────────────────────────

UPLOAD_DIR = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
UPLOAD_URL_PREFIX = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")
_MAX_LOGO_UPLOAD_BYTES = 10 * 1024 * 1024


def _normalize_logo_upload(content: bytes) -> bytes:
    """Validate raster image bytes and normalize them to a safe, transparent PNG."""
    if not content:
        raise ValueError("O arquivo da logo está vazio.")
    if len(content) > _MAX_LOGO_UPLOAD_BYTES:
        raise ValueError("A logo deve ter no máximo 10 MB.")
    try:
        import io
        from PIL import Image, ImageOps
        probe = Image.open(io.BytesIO(content))
        if probe.width < 2 or probe.height < 2:
            raise ValueError("A imagem da logo é pequena demais.")
        if probe.width * probe.height > 40_000_000:
            raise ValueError("A imagem da logo tem dimensões grandes demais.")
        probe.verify()
        image = Image.open(io.BytesIO(content))
        image.seek(0)
        image = ImageOps.exif_transpose(image)
        image.load()
        rgba = image.convert("RGBA")
        visible = sum(1 for _r, _g, _b, alpha in rgba.getdata() if alpha >= 32)
        if visible / float(max(1, rgba.width * rgba.height)) < 0.002:
            raise ValueError("A logo enviada está totalmente transparente.")
        output = io.BytesIO()
        rgba.save(output, "PNG", optimize=True)
        return output.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Envie uma logo raster válida em PNG, JPEG ou WebP.") from exc


def _identity_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def _instagram_handle(value: str) -> str:
    """Normalize an Instagram @handle or profile URL, dropping query strings and fragments."""
    raw = (value or "").strip()
    if not raw:
        return ""

    candidate = raw.rstrip("/")
    looks_like_url = bool(re.match(r"(?i)^https?://", raw))
    looks_like_instagram_host = bool(re.match(r"(?i)^(?:www\.|m\.)?instagram\.com(?:/|$)", raw))
    if looks_like_url or looks_like_instagram_host:
        parsed = urlparse(raw if looks_like_url else "https://" + raw)
        host = (parsed.hostname or "").lower()
        if host not in ("instagram.com", "www.instagram.com", "m.instagram.com"):
            return ""
        segments = [segment for segment in (parsed.path or "").split("/") if segment]
        if not segments or segments[0].lower() in {
            "accounts", "direct", "explore", "p", "reel", "reels", "stories", "tv",
        }:
            return ""
        candidate = segments[0]

    candidate = candidate.lstrip("@").strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9._]{1,30}", candidate) else ""


_THIRD_PARTY_BRANDS = {
    "espn", "premiere", "sportv", "getv", "tnt", "bandsports", "telecine", "hbo",
    "megapix", "universal", "globoplay", "cnn", "bandnews", "disney", "deezer",
    "netflix", "paramount", "youtube", "spotify", "playstore", "appstore",
}


class _ImageCandidateParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: List[Dict[str, str]] = []
        self._in_header = 0
        self._in_nav = 0

    @staticmethod
    def _best_srcset(srcset: str) -> str:
        candidates = []
        raw_srcset = srcset or ""
        # Commas are legal inside image URLs (Wix resize paths use many of them). A comma is a
        # separator only after a density/width descriptor or before a new absolute/root URL.
        parts, start = [], 0
        for match in re.finditer(",", raw_srcset):
            left = raw_srcset[start:match.start()].strip()
            right = raw_srcset[match.end():].lstrip()
            if (re.search(r"\s\d+(?:\.\d+)?[wx]\s*$", left, re.I)
                    or re.match(r"(?:(?:https?:)?//|/|\.\.?/)", right, re.I)):
                parts.append(left)
                start = match.end()
        parts.append(raw_srcset[start:].strip())
        for idx, part in enumerate(parts):
            bits = part.strip().split()
            if not bits:
                continue
            weight = idx
            if len(bits) > 1:
                raw = bits[-1].lower().rstrip("wx")
                try:
                    weight = int(float(raw))
                except Exception:
                    pass
            candidates.append((weight, bits[0]))
        return max(candidates, default=(0, ""))[1]

    def _append(self, src: str, attrs: Dict[str, str], kind: str) -> None:
        if not (src or "").strip():
            return
        self.images.append({
            "src": src.strip(),
            # Keep descriptive attributes, not raw src: the company name in a domain must not
            # turn every product image into an institutional match.
            "attrs": " ".join(v for k, v in attrs.items()
                              if k not in ("src", "data-src", "data-lazy-src", "srcset", "href", "content")),
            "header": "1" if self._in_header else "",
            "nav": "1" if self._in_nav else "",
            "kind": kind,
        })

    def handle_starttag(self, tag: str, attrs):
        amap = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag == "header":
            self._in_header += 1
        if tag == "nav":
            self._in_nav += 1
        if tag == "img":
            src = (self._best_srcset(amap.get("srcset") or "") or amap.get("src")
                   or amap.get("data-src") or amap.get("data-lazy-src") or "")
            self._append(src, amap, "img")
        elif tag == "source":
            self._append(self._best_srcset(amap.get("srcset") or ""), amap, "picture")
        elif tag == "link":
            rel = (amap.get("rel") or "").lower()
            if "icon" in rel:
                self._append(amap.get("href") or "", amap, "site-icon")
        elif tag == "meta":
            marker = (amap.get("property") or amap.get("name") or "").lower()
            if marker in ("og:logo", "og:image", "twitter:image", "twitter:image:src"):
                self._append(amap.get("content") or "", amap, marker)

    def handle_endtag(self, tag: str):
        if tag == "header" and self._in_header:
            self._in_header -= 1
        if tag == "nav" and self._in_nav:
            self._in_nav -= 1


def _site_logo_candidates(html: str, base_url: str, company_name: str) -> List[Dict[str, Any]]:
    """Rank institutional-logo candidates and reject product/partner marks.

    A filename merely containing ``logo`` is a weak signal: product grids commonly contain
    dozens of those (the AW site has ESPN, Premiere, HBO, etc.). Company-name, header/nav and
    WordPress brand markers are the strong signals.
    """
    parser = _ImageCandidateParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    company_key = _identity_key(company_name)
    ranked: List[Dict[str, Any]] = []
    for idx, item in enumerate(parser.images):
        absolute = urljoin(base_url, item["src"].strip())
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        kind = item.get("kind") or "img"
        haystack = _identity_key(item["attrs"] + " " + urlparse(absolute).path + " " + kind)
        basename = _identity_key(os.path.splitext(os.path.basename(urlparse(absolute).path))[0])
        score, reasons = max(0, 18 - idx // 4), []
        strong_identity = False
        if (kind not in ("og:image", "twitter:image", "twitter:image:src")
                and company_key and len(company_key) >= 3 and company_key in haystack):
            score += 80
            reasons.append("company-name")
            strong_identity = True
        if any(mark in haystack for mark in ("customlogo", "sitelogo", "brandlogo", "headerlogo")):
            score += 70
            reasons.append("brand-marker")
            strong_identity = True
        elif "logo" in haystack:
            score += 14
            reasons.append("generic-logo")
        if item["header"] or item["nav"]:
            score += 45
            reasons.append("header-nav")
        if kind == "site-icon":
            score += 58
            reasons.append("site-icon")
            strong_identity = True
        elif kind == "og:logo":
            score += 65
            reasons.append("og-logo")
            strong_identity = True
        elif kind in ("og:image", "twitter:image", "twitter:image:src"):
            score += 8
            reasons.append("social-preview")
        if basename in ("logo", "logotipo", company_key) and basename:
            score += 25
            strong_identity = True
        foreign = sorted(x for x in _THIRD_PARTY_BRANDS if x in haystack and x not in company_key)
        if foreign:
            score -= 140
            reasons.append("third-party:" + ",".join(foreign))
        if (kind in ("img", "picture") and (item["header"] or item["nav"])
                and not strong_identity):
            suspicious_context = any(mark in haystack for mark in (
                "parceiro", "partner", "patrocin", "sponsor", "associad", "certific",
                "pagamento", "payment", "bandeira", "flag", "social", "search", "lupa",
            ))
            if "generic-logo" in reasons and idx <= 5 and not suspicious_context:
                score += 18
                reasons.append("early-header-logo")
                strong_identity = True
            else:
                score -= 32
                reasons.append("ambiguous-header-logo")
        ranked.append({
            "url": absolute, "score": score, "reasons": reasons, "index": idx,
            "kind": kind, "strong_identity": strong_identity,
        })
    best_by_url: Dict[str, Dict[str, Any]] = {}
    for item in ranked:
        previous = best_by_url.get(item["url"])
        if previous is None or int(item["score"]) > int(previous["score"]):
            best_by_url[item["url"]] = item
    ranked = list(best_by_url.values())
    ranked.sort(key=lambda x: (-int(x["score"]), int(x["index"])))
    return ranked


def _trusted_company_logo(asset: Dict[str, Any], company_name: str) -> bool:
    meta = asset.get("meta") or {}
    if asset.get("source") in ("UPLOADED", "INSTAGRAM", "FACEBOOK"):
        return True
    if meta.get("identity_scope") == "company" and float(meta.get("confidence") or 0) >= 0.6:
        return True
    origin = str(meta.get("from") or "")
    if origin.startswith("playwright_"):
        return meta.get("identity_scope") == "company"
    ranked = _site_logo_candidates(f'<img src="{origin}">', origin, company_name)
    return bool(ranked and ranked[0]["score"] >= 55)


def _remove_misclassified_web_logos(company_id: str, company_name: str) -> int:
    """Remove only auto-imported WEB logos that cannot be tied to the company itself."""
    removed = 0
    bk = brand_kit_get(company_id) or {}
    for logo in list(asset_list_logos(company_id) or []):
        if logo.get("source") != "WEB" or _trusted_company_logo(logo, company_name):
            continue
        url = logo.get("url") or ""
        if url.startswith(UPLOAD_URL_PREFIX):
            path = os.path.join(UPLOAD_DIR, url[len(UPLOAD_URL_PREFIX):].lstrip("/"))
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        asset_delete(logo["id"])
        if bk.get("logo_url") == url:
            brand_kit_upsert(company_id, {"logo_url": None})
        removed += 1
    return removed


def _render_site(url: str) -> Dict[str, Any]:
    """Renderiza site JS via Playwright (já usado pelo publisher): devolve texto real da página, html e o
    PNG da logo (screenshot do elemento <img ...logo...> — resolve logo SVG que o PIL não lê)."""
    import re
    out = {"text": "", "html": "", "logo_png": None}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1366, "height": 900}, device_scale_factor=3)   # logo nítida (3x)
            # Wix/analytics pages may never become network-idle. The brand header is available
            # after DOMContentLoaded plus a short render window.
            pg.goto(url, timeout=35000, wait_until="domcontentloaded")
            pg.wait_for_timeout(1800)
            html = pg.content() or ""
            txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            txt = re.sub(r"<[^>]+>", " ", txt)
            out["text"] = re.sub(r"\s+", " ", txt).strip()
            out["html"] = html
            try:
                # <img> de logo OU SVG INLINE em container 'logo' (site sem <img> de logo — ex.: kpsfibra)
                # OU 1º svg do header. Screenshot do ELEMENTO vira PNG transparente.
                for _sel in ("img.custom-logo, [class*='site-logo' i] img, img[src*='logo' i], "
                             "img[alt*='logo' i], img[class*='logo' i]",
                             "a[class*='logo' i], div[class*='logo' i], span[class*='logo' i]",   # CONTAINER (ícone+texto)
                             "[class*='logo' i] svg, svg[class*='logo' i], svg[id*='logo' i]",
                             "header a[href='/'] img, nav a[href='/'] img, header a[href='/'] svg, a[href='/'] svg"):
                    el = pg.locator(_sel).first
                    if not el or el.count() == 0:
                        continue
                    try:
                        bb = el.bounding_box() or {}
                        _w, _h = (bb.get("width") or 0), (bb.get("height") or 0)
                        if (_w <= 40 and _h <= 40) or _w > 720 or _h > 240:
                            continue                           # ícone minúsculo OU wrapper gigante ≠ logo
                    except Exception:
                        pass
                    try:                                       # recorte da PÁGINA com FOLGA: o wordmark costuma
                        _bb = el.bounding_box() or {}          # vazar do box do elemento (saía cortado à direita)
                        _pd = max(8, int((_bb.get("height") or 40) * 0.3))
                        _clip = {"x": max(0, (_bb.get("x") or 0) - _pd),
                                 "y": max(0, (_bb.get("y") or 0) - _pd),
                                 "width": (_bb.get("width") or 200) + 2 * _pd + 30,
                                 "height": (_bb.get("height") or 60) + 2 * _pd}
                        out["logo_png"] = pg.screenshot(clip=_clip)          # versão 1: no fundo do site
                        try:                                   # versão 2: TRANSPARENTE — CSS zera os fundos e
                            pg.add_style_tag(content=(         # o screenshot sai com alfa (2 variantes p/ o Estúdio)
                                "html,body,header,nav,div,section,a,span{background:transparent !important;"
                                "background-color:transparent !important;background-image:none !important;"
                                "box-shadow:none !important}"))
                            out["logo_png_alpha"] = pg.screenshot(clip=_clip, omit_background=True)
                        except Exception:
                            pass
                    except Exception:
                        out["logo_png"] = el.screenshot(type="png", omit_background=True)
                    if out["logo_png"]:
                        break
            except Exception:
                pass
            b.close()
    except Exception:
        pass
    return out


def _auto_extract_products(company_id: str, website: str) -> int:
    """Extrai PLANOS/SERVIÇOS/PRODUTOS do SITE do cliente (home + páginas de planos/serviços) via IA e
    cadastra os que faltam — o usuário não precisa cadastrar oferta por oferta. Retorna quantos criou."""
    import re
    import httpx as _hx
    from ..db_companies import product_list, product_create
    if not website:
        return 0
    base = website if website.startswith("http") else "https://" + website
    ua = {"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"}
    texts = []
    try:
        r = _hx.get(base, timeout=20.0, follow_redirects=True, headers=ua)
        html = r.text or ""
        texts.append(html)
        # até 3 páginas internas de planos/serviços/produtos
        links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
        from urllib.parse import urljoin
        seen = set()
        for u in links:
            if re.search(r"plano|servi|produto|combo|pacote|internet", u, re.I):
                full = urljoin(str(r.url), u)
                if full.startswith("http") and full not in seen and len(seen) < 3:
                    seen.add(full)
                    try:
                        texts.append(_hx.get(full, timeout=15.0, follow_redirects=True, headers=ua).text or "")
                    except Exception:
                        pass
    except Exception:
        return 0
    blob = " ".join(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S | re.I) for t in texts)
    blob = re.sub(r"<[^>]+>", " ", blob)
    blob = re.sub(r"\s+", " ", blob)[:14000]
    if len(blob) < 300:
        # site 100% JavaScript (HTML estático vazio) → renderiza com Playwright e usa o texto REAL
        rend = _render_site(base)
        blob = (rend.get("text") or "")[:14000]
        # + páginas internas de planos/serviços renderizadas (até 2)
        try:
            from urllib.parse import urljoin
            _lks = re.findall(r'href=["\']([^"\']+)["\']', rend.get("html") or "", re.I)
            _seen = set()
            for _u in _lks:
                if re.search(r"plano|servi|produto|combo", _u, re.I):
                    _full = urljoin(base, _u)
                    if _full.startswith("http") and _full not in _seen and len(_seen) < 2:
                        _seen.add(_full)
                        blob += " " + (_render_site(_full).get("text") or "")[:6000]
        except Exception:
            pass
        blob = blob[:14000]
    if len(blob) < 300:
        return 0
    try:
        from ..services.ai import cheap_text_config, get_ai_config, complete_ai, extract_json
        cfg = cheap_text_config(get_ai_config())
        if not cfg:
            return 0
        sysm = "Você extrai o catálogo de ofertas de um site. Responda SÓ JSON válido, pt-BR."
        usr = ('Do texto do site abaixo, liste as OFERTAS REAIS da empresa (planos, serviços, produtos, combos). '
               'Formato: {"products":[{"name":"nome curto EXATO","description":"1 frase","objective":"como vender (1 frase)",'
               '"functions":["velocidade/itens inclusos/beneficios reais",...],"price":"preço REAL publicado (ex.: R$ 99,90/mês) ou vazio"}]} (até 12). TEXTO: ' + blob)
        data = extract_json(complete_ai(cfg, sysm, usr, 2000)) or {}
        items = data.get("products") or []
    except Exception:
        return 0
    company_words = set(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", (company_get(company_id) or {}).get("name") or "")
                                   .encode("ascii", "ignore").decode().lower()))
    generic_words = {
        "plano", "planos", "servico", "servicos", "produto", "produtos", "oferta", "ofertas",
        "internet", "telecom", "telecomunicacoes", "fibra", "da", "de", "do", "para", "com",
    }

    def _offer_key(name: str) -> str:
        clean = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
        words = [word for word in re.findall(r"[a-z0-9]+", clean)
                 if word not in company_words and word not in generic_words]
        # Numbers distinguish real speed tiers (500 mega vs 700 mega); an empty key represents
        # a generic restatement of the company, which must not be duplicated on every refresh.
        return "|".join(sorted(set(words))) or "__generic_company_offer__"

    existing_products = product_list(company_id) or []
    existing_names = {(p.get("name") or "").strip().lower() for p in existing_products}
    existing_keys = {_offer_key(p.get("name") or "") for p in existing_products}
    added = 0
    for it in items[:12]:
        nm = (it.get("name") or "").strip()
        offer_key = _offer_key(nm)
        if not nm or nm.lower() in existing_names or offer_key in existing_keys:
            continue
        _fns = [str(f).strip() for f in (it.get("functions") or []) if str(f).strip()][:8]
        if (it.get("price") or "").strip():
            _fns.append("Preço: " + it["price"].strip())
        product_create(company_id, {"name": nm, "description": (it.get("description") or "").strip(),
                                    "objective": (it.get("objective") or "").strip(), "functions": _fns})
        existing_names.add(nm.lower())
        existing_keys.add(offer_key)
        added += 1
    return added


def _ig_fetch_brand(company_id: str, instagram: str) -> Dict[str, int]:
    """Puxa do INSTAGRAM público: foto do perfil (vira LOGO se não houver) + thumbnails de posts (viram ARTES
    DE REFERÊNCIA p/ o Estúdio IA). IG pode bloquear IP de datacenter — melhor esforço, retorna contagens."""
    import re
    import io as _io
    import uuid as _uuid
    import httpx as _hx
    from PIL import Image as _Img
    out = {"logo": 0, "refs": 0}
    handle = _instagram_handle(instagram)
    if not handle:
        return out
    try:
        r = _hx.get(f"https://www.instagram.com/{handle}/", timeout=20.0, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"})
        html = r.text or ""
    except Exception:
        return out
    def _save(url, sub, kind, role, meta):
        try:
            ir = _hx.get(url.replace("&amp;", "&"), timeout=20.0, follow_redirects=True)
            if ir.status_code >= 400 or not ir.content:
                return False
            im = _Img.open(_io.BytesIO(ir.content))
            subdir = os.path.join(UPLOAD_DIR, company_id, sub)
            os.makedirs(subdir, exist_ok=True)
            fn = f"{_uuid.uuid4().hex}.png"
            im.convert("RGBA").save(os.path.join(subdir, fn), "PNG")
            u = f"{UPLOAD_URL_PREFIX}/{company_id}/{sub}/{fn}"
            saved_meta = dict(meta, role=role)
            if role == "logo":
                saved_meta.update({"identity_scope": "company", "confidence": 0.95, "is_primary": False})
            asset = asset_create(company_id, {"kind": kind, "source": "INSTAGRAM", "url": u, "meta": saved_meta})
            if role == "logo":
                asset_claim_primary_logo_if_empty(company_id, asset["id"], "AUTO")
            return True
        except Exception:
            return False
    # Foto de perfil é uma variante institucional válida mesmo quando o site já forneceu outra logo.
    # Evita duplicar a mesma origem em re-enriches.
    has_ig_profile = any((a.get("meta") or {}).get("from") == "instagram_profile"
                         for a in (asset_list_logos(company_id) or []))
    if not has_ig_profile:
        m = re.search(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m and _save(m.group(1), "logo", "IMAGE", "logo",
                       {"is_primary": not bool(asset_list_logos(company_id)), "from": "instagram_profile"}):
            out["logo"] = 1
    # thumbnails de posts → artes de referência (display_url no JSON embutido)
    urls = re.findall(r'"display_url":"([^"]+)"', html)[:4]
    for u in urls:
        if _save(u.encode().decode("unicode_escape"), "references", "IMAGE", "brand_reference", {"from": "instagram_post"}):
            out["refs"] += 1
    return out


def _facebook_fetch_logo(company_id: str, facebook: str) -> int:
    """Importa a foto pública somente quando título do perfil confirma empresa/handle."""
    import io as _io
    import uuid as _uuid
    import httpx as _hx
    from PIL import Image as _Img
    raw = (facebook or "").strip()
    if not raw:
        return 0
    page_url = raw if raw.startswith(("http://", "https://")) else "https://www.facebook.com/" + raw.lstrip("@/")
    if any((a.get("meta") or {}).get("from") == "facebook_profile"
           for a in (asset_list_logos(company_id) or [])):
        return 0
    try:
        response = _hx.get(
            page_url, timeout=_hx.Timeout(20.0, connect=10.0), follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                   "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"},
        )
        html = response.text or ""
    except Exception:
        return 0
    title_match = re.search(
        r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I,
    )
    image_match = re.search(
        r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I,
    )
    company_key = _identity_key((company_get(company_id) or {}).get("name") or "")
    handle_key = _identity_key(urlparse(page_url).path.strip("/").split("/")[0])
    title_key = _identity_key(title_match.group(1) if title_match else "")
    identity_keys = [key for key in (company_key, handle_key) if len(key) >= 3]
    if not image_match or not title_key or not any(key in title_key or title_key in key for key in identity_keys):
        return 0
    try:
        image_url = image_match.group(1).replace("&amp;", "&")
        image_response = _hx.get(image_url, timeout=20.0, follow_redirects=True)
        image = _Img.open(_io.BytesIO(image_response.content))
        if image.width < 64 and image.height < 64:
            return 0
        subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
        os.makedirs(subdir, exist_ok=True)
        filename = f"{_uuid.uuid4().hex}.png"
        image.convert("RGBA").save(os.path.join(subdir, filename), "PNG")
        url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
        asset = asset_create(company_id, {
            "kind": "IMAGE", "source": "FACEBOOK", "url": url,
            "meta": {"role": "logo", "is_primary": False, "from": "facebook_profile",
                     "source_url": page_url[:200], "identity_scope": "company", "confidence": 0.9},
        })
        asset_claim_primary_logo_if_empty(company_id, asset["id"], "AUTO")
        return 1
    except Exception:
        return 0


def _canonical_logo_source(url: str) -> str:
    """Collapse CDN resize URLs to one source asset while keeping genuinely different marks."""
    parsed = urlparse(url or "")
    path = parsed.path or ""
    if "static.wixstatic.com" in parsed.netloc and "/media/" in path:
        wix_asset = path.split("/media/", 1)[1].split("/", 1)[0]
        return f"{parsed.netloc}/media/{wix_asset}"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def _logo_visual_hash(image) -> str:
    """Shape + color hash: resize duplicates collapse, but light/dark variants remain distinct."""
    try:
        import imagehash
        from PIL import Image
        rgba = image.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (127, 127, 127, 255))
        flattened = Image.alpha_composite(bg, rgba).convert("RGB")
        visible = [(r, g, b, a) for r, g, b, a in rgba.getdata() if a >= 48]
        if visible:
            total_alpha = sum(pixel[3] for pixel in visible)
            mean = tuple(int(sum(pixel[channel] * pixel[3] for pixel in visible) / total_alpha)
                         for channel in range(3))
        else:
            mean = (127, 127, 127)
        return f"{imagehash.phash(flattened)}:{mean[0]:02x}{mean[1]:02x}{mean[2]:02x}"
    except Exception:
        return ""


def _auto_fetch_logo(company_id: str, website: str) -> Optional[str]:
    """Discover multiple institutional marks, idempotently, without replacing a curated primary logo."""
    import hashlib
    import io as _io
    import uuid as _uuid
    import httpx as _hx
    from PIL import Image as _Img

    if not website:
        return None
    base = website if website.startswith("http") else "https://" + website
    try:
        r = _hx.get(base, timeout=_hx.Timeout(20.0, connect=10.0), follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"})
        html = r.text or ""
    except Exception:
        return None

    company = company_get(company_id) or {}
    existing = list(asset_list_logos(company_id) or [])
    existing_sha, existing_phash, existing_capture = set(), [], set()
    kit_logo_url = (brand_kit_get(company_id) or {}).get("logo_url") or ""
    has_primary = bool(kit_logo_url and not kit_logo_url.startswith(UPLOAD_URL_PREFIX))
    valid_existing = []
    for logo in existing:
        meta = logo.get("meta") or {}
        local_url = logo.get("url") or ""
        if local_url.startswith(UPLOAD_URL_PREFIX):
            path = os.path.join(UPLOAD_DIR, local_url[len(UPLOAD_URL_PREFIX):].lstrip("/"))
            if not path.lower().endswith(".svg"):
                try:
                    with open(path, "rb") as handle:
                        raw = handle.read()
                    image = _Img.open(_io.BytesIO(raw))
                    if image.width * image.height > 40_000_000:
                        raise ValueError("imagem grande demais")
                    image.load()
                except Exception:
                    # Only auto-imported WEB rows are safe to self-heal. Never delete a curated
                    # upload merely because Pillow cannot decode it (legacy SVGs are valid here).
                    if logo.get("source") == "WEB":
                        asset_delete(logo.get("id"))
                        if kit_logo_url == local_url:
                            kit_logo_url = ""
                            brand_kit_upsert(company_id, {"logo_url": None})
                        continue
                else:
                    existing_sha.add(hashlib.sha256(raw).hexdigest())
                    phash = _logo_visual_hash(image)
                    if phash:
                        existing_phash.append(phash)
        valid_existing.append(logo)
        if meta.get("sha256"):
            existing_sha.add(str(meta["sha256"]))
        if meta.get("phash"):
            existing_phash.append(str(meta["phash"]))
        origin = str(meta.get("from") or "")
        if origin.startswith("playwright_"):
            existing_capture.add(origin)
        if meta.get("is_primary") or (kit_logo_url and kit_logo_url == local_url):
            has_primary = True
    existing = valid_existing
    existing = _ensure_logo_primary_consistency(company_id, existing)
    if any((logo.get("meta") or {}).get("is_primary") for logo in existing):
        has_primary = True

    def _looks_duplicate(digest: str, phash: str) -> bool:
        if digest in existing_sha:
            return True
        if not phash:
            return False
        try:
            import imagehash
            current_shape, _, current_color = phash.partition(":")
            for old in existing_phash:
                old_shape, _, old_color = old.partition(":")
                if not old_shape:
                    continue
                if imagehash.hex_to_hash(current_shape) - imagehash.hex_to_hash(old_shape) > 5:
                    continue
                if current_color and old_color and len(current_color) == 6 and len(old_color) == 6:
                    current_rgb = tuple(int(current_color[index:index + 2], 16) for index in (0, 2, 4))
                    old_rgb = tuple(int(old_color[index:index + 2], 16) for index in (0, 2, 4))
                    distance = sum((current_rgb[index] - old_rgb[index]) ** 2 for index in range(3)) ** 0.5
                    if distance <= 42:
                        return True
                elif current_shape == old_shape:
                    return True
            return False
        except Exception:
            return phash in existing_phash

    subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
    os.makedirs(subdir, exist_ok=True)
    saved_urls: List[str] = []

    def _save_image(raw: bytes, *, origin: str, variant: str, confidence: float,
                    evidence: Optional[List[str]] = None) -> Optional[str]:
        nonlocal has_primary
        if not raw or len(raw) > 10 * 1024 * 1024:
            return None
        try:
            digest = hashlib.sha256(raw).hexdigest()
            im = _Img.open(_io.BytesIO(raw))
            if im.width * im.height > 40_000_000:
                return None
            im.load()
            if im.width < 48 and im.height < 48:
                return None
            rgba = im.convert("RGBA")
            visible_pixels = sum(1 for _r, _g, _b, alpha in rgba.getdata() if alpha >= 32)
            if visible_pixels / float(max(1, rgba.width * rgba.height)) < 0.002:
                return None
            phash = _logo_visual_hash(rgba)
            if _looks_duplicate(digest, phash):
                return None
            filename = f"{_uuid.uuid4().hex}.png"
            rgba.save(os.path.join(subdir, filename), "PNG")
            url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
            asset = asset_create(company_id, {
                "kind": "IMAGE", "source": "WEB", "url": url,
                "meta": {
                    "role": "logo", "variant": variant, "is_primary": False,
                    "from": origin[:500], "source_key": _canonical_logo_source(origin),
                    "identity_scope": "company", "confidence": confidence,
                    "evidence": evidence or [], "sha256": digest, "phash": phash,
                },
            })
            existing_sha.add(digest)
            if phash:
                existing_phash.append(phash)
            is_primary = asset_claim_primary_logo_if_empty(company_id, asset["id"], "AUTO")
            if is_primary:
                has_primary = True
            saved_urls.append(url)
            return url
        except Exception:
            return None

    ranked = _site_logo_candidates(html, str(r.url), company.get("name") or "")
    candidates = [candidate for candidate in ranked if candidate["score"] >= 55]
    for candidate in candidates[:12]:
        if len(saved_urls) >= 5 or urlparse(candidate["url"]).path.lower().endswith(".svg"):
            continue
        try:
            response = _hx.get(candidate["url"], timeout=_hx.Timeout(20.0, connect=10.0),
                               follow_redirects=True,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"})
            if response.status_code >= 400:
                continue
            variant = "site_icon" if candidate.get("kind") == "site-icon" else "site_logo"
            _save_image(response.content, origin=candidate["url"], variant=variant,
                        confidence=min(1.0, candidate["score"] / 100.0),
                        evidence=candidate.get("reasons") or [])
        except Exception:
            continue

    # A rendered-on-site version is useful for white marks. Unlike the old fallback, it is
    # attempted even after a raster was found; captures already saved are not repeated.
    wanted_captures = ["playwright_render"]
    if not existing and not saved_urls:
        wanted_captures.insert(0, "playwright_alpha")
    if any(tag not in existing_capture for tag in wanted_captures):
        try:
            rendered = _render_site(base)
            capture_map = {
                "playwright_alpha": rendered.get("logo_png_alpha"),
                "playwright_render": rendered.get("logo_png"),
            }
            for tag in wanted_captures:
                raw = capture_map.get(tag)
                if not raw or tag in existing_capture:
                    continue
                _save_image(raw, origin=tag, variant=("transparent" if tag.endswith("alpha") else "site_render"),
                            confidence=0.72, evidence=["rendered-header"])
        except Exception:
            pass

    return ((brand_kit_get(company_id) or {}).get("logo_url")
            or (saved_urls[0] if saved_urls else None))



def _ig_headers():
    """Sessão do Instagram (1 conta da casa): setting ig.session_cookie (cole o cookie 'sessionid' UMA vez)."""
    from ..services.ai import get_setting
    ck = (get_setting("ig.session_cookie") or os.environ.get("IG_SESSION_COOKIE") or "").strip()
    H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
         "x-ig-app-id": "936619743392459"}
    if ck:
        H["Cookie"] = ck if "=" in ck.split(";")[0] else f"sessionid={ck}"
    return H, bool(ck)


def _ig_import(company_id: str, handle: str, kind: str = "reference", count: int = 4) -> Dict[str, Any]:
    """Importa do Instagram: 'own' = identidade do cliente (foto de perfil vira LOGO se faltar + posts viram
    referências); 'reference' = perfil que o cliente admira/concorrente (posts viram ARTES DE REFERÊNCIA do
    Estúdio). Precisa de sessão (ig.session_cookie) — IG bloqueia acesso anônimo de servidor."""
    import io as _io
    import uuid as _uuid
    import httpx as _hx
    from PIL import Image as _Img
    handle = _instagram_handle(handle)
    if not handle:
        return {"error": "informe o @ do perfil"}
    H, has_sess = _ig_headers()
    try:
        r = _hx.get(f"https://i.instagram.com/api/v1/users/web_profile_info/?username={handle}",
                    headers=H, timeout=25.0, follow_redirects=True)
    except Exception as e:
        return {"error": f"falha de rede no Instagram: {str(e)[:80]}"}
    if r.status_code == 429 or r.status_code == 403 or (r.status_code >= 400 and not has_sess):
        return {"error": "O Instagram exige sessão para importar. Configure o cookie em ig.session_cookie "
                         "(Instagram logado no navegador → DevTools → Cookies → copie o valor de 'sessionid')."}
    try:
        u = ((r.json() or {}).get("data") or {}).get("user") or {}
    except Exception:
        u = {}
    if not u:
        return {"error": f"perfil @{handle} não encontrado (ou sessão expirada)."}

    def _save_img(url, sub, role, meta):
        try:
            ir = _hx.get(url, timeout=25.0, follow_redirects=True, headers={"User-Agent": H["User-Agent"]})
            if ir.status_code >= 400 or not ir.content:
                return None
            im = _Img.open(_io.BytesIO(ir.content))
            subdir = os.path.join(UPLOAD_DIR, company_id, sub)
            os.makedirs(subdir, exist_ok=True)
            fn = f"{_uuid.uuid4().hex}.png"
            im.convert("RGBA" if role == "logo" else "RGB").save(os.path.join(subdir, fn), "PNG")
            url2 = f"{UPLOAD_URL_PREFIX}/{company_id}/{sub}/{fn}"
            saved_meta = dict(meta, role=role)
            if role == "logo":
                saved_meta.update({"identity_scope": "company", "confidence": 0.95, "is_primary": False})
            asset = asset_create(company_id, {"kind": "IMAGE", "source": "INSTAGRAM", "url": url2, "meta": saved_meta})
            if role == "logo":
                asset_claim_primary_logo_if_empty(company_id, asset["id"], "AUTO")
            return url2
        except Exception:
            return None

    out = {"logo": 0, "refs": 0, "handle": handle}
    profile_origin = f"instagram:@{handle}"
    has_profile_logo = any((logo.get("meta") or {}).get("from") == profile_origin
                           for logo in (asset_list_logos(company_id) or []))
    if kind == "own" and not has_profile_logo:
        pic = u.get("profile_pic_url_hd") or u.get("profile_pic_url")
        if pic and _save_img(pic, "logo", "logo", {"from": profile_origin}):
            out["logo"] = 1
    edges = ((u.get("edge_owner_to_timeline_media") or {}).get("edges")) or []
    for e in edges[:max(1, min(8, int(count or 4)))]:
        node = (e or {}).get("node") or {}
        du = node.get("display_url")
        if du and _save_img(du, "references", "brand_reference", {"from": f"instagram:@{handle}", "kind": kind}):
            out["refs"] += 1
    return out


@router.post("/{company_id}/import-instagram")
async def import_instagram(company_id: str, request: Request):
    """Importa identidade/referências do Instagram: {handle, kind: 'own'|'reference', count}.
    'own' = o Instagram DO cliente (identidade); 'reference' = perfil que ele admira (família de estilo)."""
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    handle = (body.get("handle") or (company_get(company_id).get("socials") or {}).get("instagram") or "").strip()
    kind = (body.get("kind") or "reference").strip()
    import asyncio as _aio
    res = await _aio.to_thread(_ig_import, company_id, handle, kind, int(body.get("count") or 4))
    if res.get("error"):
        return JSONResponse({"detail": res["error"]}, status_code=422)
    return res


def _run_company_enrichment(
    company_id: str, overrides: Optional[Dict[str, Any]] = None, *, run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Single, observable enrichment service used by create, update and manual refresh."""
    overrides = dict(overrides or {})
    company = company_get(company_id)
    if not company:
        raise ValueError("Empresa não encontrada")

    website = (overrides.get("website") or company.get("website") or "").strip()
    socials = dict(company.get("socials") or {})
    instagram = (overrides.get("instagram") or socials.get("instagram") or "").strip()
    facebook = (overrides.get("facebook") or socials.get("facebook") or "").strip()
    if not website and not instagram and not facebook:
        raise ValueError("Cadastre o site, Instagram ou Facebook primeiro.")

    started_at = _now()
    warnings: List[str] = []
    _store_enrichment_status(
        company_id, run_id=run_id, state="running", stage="profile", started_at=started_at,
        message="Lendo site e posicionamento da empresa…", error="", warnings=[],
    )

    data: Dict[str, Any] = {}
    try:
        from ..services.ai import enrich_company_from_web
        data = enrich_company_from_web(
            company.get("name") or "", website, instagram, company.get("segment") or "", facebook,
        )
    except Exception as exc:
        warnings.append("Perfil verbal: " + str(exc)[:220])

    socials.update({"instagram": instagram, "facebook": facebook})
    update: Dict[str, Any] = {"website": website, "socials": {k: v for k, v in socials.items() if v}}
    if data.get("segment"):
        update["segment"] = data["segment"]
    if data.get("description") and not (company.get("notes") or "").strip():
        update["notes"] = data["description"]
    company_update(company_id, update)

    _store_enrichment_status(
        company_id, run_id=run_id, state="running", stage="logos",
        message="Localizando logos e variantes institucionais…", warnings=warnings,
    )
    before_logos = {logo.get("id") for logo in (asset_list_logos(company_id) or [])}
    try:
        _remove_misclassified_web_logos(company_id, company.get("name") or "")
    except Exception as exc:
        warnings.append("Limpeza de logos antigas: " + str(exc)[:180])
    if website:
        try:
            # Always rediscover. The importer is idempotent and keeps a manually selected primary.
            _auto_fetch_logo(company_id, website)
        except Exception as exc:
            warnings.append("Site/logos: " + str(exc)[:180])

    instagram_stats = {"logo": 0, "refs": 0}
    if instagram:
        try:
            instagram_stats = _ig_import(company_id, instagram, "own", 4)
            instagram_error = instagram_stats.pop("error", "")
            if instagram_error:
                instagram_stats = _ig_fetch_brand(company_id, instagram)
            if not instagram_stats.get("logo") and not instagram_stats.get("refs"):
                detail = (": " + instagram_error[:140]) if instagram_error else ""
                warnings.append("Instagram não liberou imagens deste perfil" + detail)
        except Exception as exc:
            warnings.append("Instagram: " + str(exc)[:180])
    facebook_logo = 0
    if facebook:
        try:
            facebook_logo = _facebook_fetch_logo(company_id, facebook)
            if not facebook_logo:
                warnings.append("Facebook não liberou a foto pública desta página.")
        except Exception as exc:
            warnings.append("Facebook: " + str(exc)[:180])

    after_logos = list(asset_list_logos(company_id) or [])
    logo_ids = {logo.get("id") for logo in after_logos}
    logos_added = len(logo_ids - before_logos)
    if website and not after_logos:
        warnings.append("Nenhuma logo institucional foi encontrada no site.")

    _store_enrichment_status(
        company_id, run_id=run_id, state="running", stage="products",
        message="Importando produtos e serviços sem duplicar cadastros…",
        logos_added=logos_added, logos_total=len(after_logos), warnings=warnings,
    )
    products_added = 0
    if website:
        try:
            products_added = _auto_extract_products(company_id, website)
        except Exception as exc:
            warnings.append("Produtos e serviços: " + str(exc)[:180])

    _store_enrichment_status(
        company_id, run_id=run_id, state="running", stage="palette",
        message="Extraindo e agrupando as cores principais…", warnings=warnings,
    )
    detected_colors = normalize_brand_colors(
        _company_logo_colors(company_id, 8) or dict(data.get("colors") or {})
    )
    current_kit = brand_kit_get(company_id) or {}
    extras = dict(current_kit.get("extras") or {})
    current_colors = dict(current_kit.get("colors") or {})
    palette_source = extras.get("palette_source")
    legacy_three_keys = set(current_colors).issubset({"primary", "secondary", "accent"})
    legacy_has_duplicate = any(
        _brand_colors_similar(first, second)
        for index, first in enumerate(current_colors.values())
        for second in list(current_colors.values())[index + 1:]
    )
    # Older automatic palettes were incorrectly stored as MANUAL. The Rio Cable signature is the
    # old fixed three slots with a duplicated color family; repair that automatically, but preserve
    # every unmarked legacy palette that may have been curated by a person.
    legacy_auto_palette = bool(current_colors and legacy_three_keys and legacy_has_duplicate)
    palette_is_manual = palette_source in ("manual", "legacy_preserved") or (
        bool(current_colors) and not palette_source and not legacy_auto_palette
    )
    replace_manual = bool(overrides.get("replace_manual_palette"))
    extra_patch: Dict[str, Any] = {
        "detected_colors": detected_colors,
        "palette_detected_at": _now(),
    }

    kit_update: Dict[str, Any] = {}
    manual_fields = set(extras.get("manual_fields") or [])
    replace_curated = bool(overrides.get("replace_curated_fields"))
    for key in ("voice", "persona", "visual_prompt_base", "audience"):
        if data.get(key) and (replace_curated or (not current_kit.get(key) and key not in manual_fields)):
            kit_update[key] = data[key]
    if detected_colors and (not palette_is_manual or replace_manual):
        kit_update["colors"] = detected_colors
    elif current_colors and not palette_source:
        extra_patch["palette_source"] = "legacy_preserved"
    brand_kit_apply_auto(
        company_id, kit_update,
        replace_manual_palette=replace_manual,
        replace_curated_fields=replace_curated,
    )
    brand_kit_extras_patch(company_id, extra_patch)

    final_colors = (brand_kit_get(company_id) or {}).get("colors") or {}
    final_status = _store_enrichment_status(
        company_id, run_id=run_id,
        state="done",
        stage="done",
        message="Identidade pronta para revisão.",
        finished_at=_now(),
        logos_added=logos_added,
        logos_total=len(after_logos),
        colors_found=len(final_colors),
        products_added=products_added,
        palette_preserved=bool(palette_is_manual and not replace_manual),
        warnings=warnings,
        error="",
    )
    return {
        "company": company_get(company_id), "extracted": data,
        "products_added": products_added, "instagram": instagram_stats,
        "facebook_logo": facebook_logo, "logos_added": logos_added,
        "logos_total": len(after_logos), "colors": final_colors,
        "warnings": warnings, "enrichment": final_status,
    }


@router.post("/{company_id}/enrich")
async def enrich_company(company_id: str, request: Request):
    """Backward-compatible synchronous enrichment; the OS uses the observable background endpoint."""
    err = _api_key_required(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    with _ENRICHMENT_GUARD:
        already_running = company_id in _ENRICHMENT_RUNNING
        if not already_running:
            _ENRICHMENT_RUNNING.add(company_id)
    if already_running:
        return JSONResponse(
            {"detail": "A importação desta empresa já está em andamento.",
             "enrichment": _enrichment_status(company_id)},
            status_code=409,
        )
    run_id = uuid.uuid4().hex
    try:
        import asyncio
        _store_enrichment_status(
            company_id, run_id=run_id, replace=True, state="queued", stage="queued",
            message="Preparando a importação da identidade…", queued_at=_now(), warnings=[], error="",
        )
        return await asyncio.to_thread(_run_company_enrichment, company_id, body, run_id=run_id)
    except ValueError as exc:
        _store_enrichment_status(
            company_id, run_id=run_id, state="failed", stage="failed",
            message="Não foi possível concluir a importação.", error=str(exc)[:300], finished_at=_now(),
        )
        status = 404 if "não encontrada" in str(exc) else 422
        return JSONResponse({"detail": str(exc)}, status_code=status)
    except Exception as exc:
        _store_enrichment_status(
            company_id, run_id=run_id, state="failed", stage="failed",
            message="Não foi possível concluir a importação.", error=str(exc)[:300], finished_at=_now(),
        )
        return JSONResponse({"detail": "Falha ao importar a identidade: " + str(exc)[:260]}, status_code=500)
    finally:
        with _ENRICHMENT_GUARD:
            _ENRICHMENT_RUNNING.discard(company_id)


@router.post("/{company_id}/enrich/start")
async def start_company_enrichment(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sources = [
        (body.get("website") or company.get("website") or "").strip(),
        (body.get("instagram") or (company.get("socials") or {}).get("instagram") or "").strip(),
        (body.get("facebook") or (company.get("socials") or {}).get("facebook") or "").strip(),
    ]
    if not any(sources):
        return JSONResponse({"detail": "Cadastre o site, Instagram ou Facebook primeiro."}, status_code=422)
    enrichment = _spawn_bg_enrich(company_id, body)
    return JSONResponse(
        {"enrichment": enrichment}, status_code=500 if enrichment.get("state") == "failed" else 202,
    )


@router.get("/{company_id}/enrich/status")
def get_company_enrichment_status(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"enrichment": _enrichment_status(company_id)}


@router.post("/{company_id}/logo")
async def upload_logo(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}.png"
    filepath = os.path.join(subdir, filename)
    try:
        content = _normalize_logo_upload(await file.read(_MAX_LOGO_UPLOAD_BYTES + 1))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    with open(filepath, "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
    asset = asset_create(company_id, {"kind": "IMAGE", "source": "UPLOADED", "url": url,
                                        "meta": {"role": "logo", "is_primary": False,
                                                 "identity_scope": "company", "confidence": 1.0}})
    asset_set_primary_logo(company_id, asset["id"], "MANUAL")
    return {"url": url}


# ─────────────────────────────────────────────────────────────────────────────
# Influencers (por empresa) — cadastro + banco de imagem (fotos reais p/ compor na arte + collab @)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{company_id}/influencer-companies")
def list_infcompanies(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import infcompany_list
    return {"companies": infcompany_list(company_id)}


@router.post("/{company_id}/influencer-companies")
async def create_infcompany(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome da empresa influencer é obrigatório"}, status_code=422)
    from ..db_companies import infcompany_create
    return infcompany_create(company_id, body)


@router.put("/{company_id}/influencer-companies/{infco_id}")
async def update_infcompany(company_id: str, infco_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import infcompany_update
    o = infcompany_update(infco_id, body)
    return o or JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)


@router.delete("/{company_id}/influencer-companies/{infco_id}")
def delete_infcompany(company_id: str, infco_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import infcompany_delete
    return {"ok": infcompany_delete(infco_id)}


@router.post("/{company_id}/influencer-companies/{infco_id}/logo")
async def upload_infcompany_logo(company_id: str, infco_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "inf_companies", infco_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/inf_companies/{infco_id}/{filename}"
    a = asset_create(company_id, {"kind": "INFCOMPANY_LOGO", "source": "UPLOADED", "url": url, "meta": {"infcompany_id": infco_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/influencer-companies/{infco_id}/logo/{asset_id}")
def delete_infcompany_logo(company_id: str, infco_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.get("/{company_id}/influencers")
def list_influencers(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import influencer_list
    return {"influencers": influencer_list(company_id)}


@router.post("/{company_id}/influencers")
async def create_influencer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do influencer é obrigatório"}, status_code=422)
    from ..db_companies import influencer_create
    return influencer_create(company_id, body)


@router.put("/{company_id}/influencers/{inf_id}")
async def update_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import influencer_update
    inf = influencer_update(inf_id, body)
    return inf or JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)


@router.delete("/{company_id}/influencers/{inf_id}")
def delete_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import influencer_delete
    return {"ok": influencer_delete(inf_id)}


@router.post("/{company_id}/influencers/{inf_id}/photo")
async def upload_influencer_photo(company_id: str, inf_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "foto.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "influencers", inf_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/influencers/{inf_id}/{filename}"
    a = asset_create(company_id, {"kind": "INFLUENCER_PHOTO", "source": "UPLOADED", "url": url, "meta": {"influencer_id": inf_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/influencers/{inf_id}/photo/{asset_id}")
def delete_influencer_photo(company_id: str, inf_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Organizador do evento (empresa do evento, ex.: ExPSP) — IG + site + logo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/event-organizers")
def list_organizers(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import organizer_list
    return {"organizers": organizer_list(company_id)}


@router.post("/{company_id}/event-organizers")
async def create_organizer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome da empresa do evento é obrigatório"}, status_code=422)
    from ..db_companies import organizer_create
    return organizer_create(company_id, body)


@router.put("/{company_id}/event-organizers/{org_id}")
async def update_organizer(company_id: str, org_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import organizer_update
    o = organizer_update(org_id, body)
    return o or JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)


@router.delete("/{company_id}/event-organizers/{org_id}")
def delete_organizer(company_id: str, org_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import organizer_delete
    return {"ok": organizer_delete(org_id)}


@router.post("/{company_id}/event-organizers/{org_id}/logo")
async def upload_organizer_logo(company_id: str, org_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "event_orgs", org_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/event_orgs/{org_id}/{filename}"
    a = asset_create(company_id, {"kind": "ORGANIZER_LOGO", "source": "UPLOADED", "url": url, "meta": {"organizer_id": org_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/event-organizers/{org_id}/logo/{asset_id}")
def delete_organizer_logo(company_id: str, org_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Eventos (edição embaixo do organizador): data início/fim, cidade, logos + imagens
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/events")
def list_events(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import event_list
    return {"events": event_list(company_id)}


@router.post("/{company_id}/events")
async def create_event(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do evento é obrigatório"}, status_code=422)
    from ..db_companies import event_create
    return event_create(company_id, body)


@router.put("/{company_id}/events/{event_id}")
async def update_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..db_companies import event_update
    ev = event_update(event_id, body)
    return ev or JSONResponse({"detail": "Evento não encontrado"}, status_code=404)


@router.delete("/{company_id}/events/{event_id}")
def delete_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import event_delete
    return {"ok": event_delete(event_id)}


@router.post("/{company_id}/events/{event_id}/logo")
async def upload_event_logo(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "events", event_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/events/{event_id}/{filename}"
    a = asset_create(company_id, {"kind": "EVENT_LOGO", "source": "UPLOADED", "url": url, "meta": {"event_id": event_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/events/{event_id}/logo/{asset_id}")
def delete_event_logo(company_id: str, event_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.post("/{company_id}/events/{event_id}/image")
async def upload_event_image(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "img.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "events", event_id, "img")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/events/{event_id}/img/{filename}"
    a = asset_create(company_id, {"kind": "EVENT_IMAGE", "source": "UPLOADED", "url": url, "meta": {"event_id": event_id}})
    return {"url": url, "asset_id": a.get("id")}


@router.delete("/{company_id}/events/{event_id}/image/{asset_id}")
def delete_event_image(company_id: str, event_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Reference images (mood board)
# ─────────────────────────────────────────────────────────────────────────────

def _refresh_reference_profile(company_id: str) -> None:
    """Turn reference art into reusable visual direction without replacing official brand identity."""
    refs = asset_list(company_id, role="brand_reference")[:5]
    existing = brand_kit_get(company_id) or {}
    extras = dict(existing.get("extras") or {})
    profile: Dict[str, Any] = {
        "status": "ready",
        "analyzed_at": _now(),
        "reference_count": len(refs),
        "palette": [],
        "logo_position": "unknown",
        "layout_direction": "",
        "typography": "",
        "style_keywords": [],
    }
    images: List[bytes] = []
    palette: List[str] = []
    for ref in refs:
        url = ref.get("url") or ""
        if not url.startswith(UPLOAD_URL_PREFIX):
            continue
        path = os.path.join(UPLOAD_DIR, url[len(UPLOAD_URL_PREFIX):].lstrip("/"))
        try:
            with open(path, "rb") as fh:
                images.append(fh.read())
            for color in _dominant_colors(path, 4):
                if color not in palette:
                    palette.append(color)
        except Exception:
            continue
    profile["palette"] = palette[:8]
    if images:
        try:
            from ..services.ai import (
                _complete_ai_with_images, cheap_text_config, extract_json, get_ai_config,
            )
            cfg = cheap_text_config(get_ai_config())
            if cfg:
                system = (
                    "Você é diretor de arte e analisa artes de referência. Responda somente JSON válido. "
                    "Separe identidade institucional de logos de produtos, canais, parceiros e ofertas. "
                    "Não declare uma marca de produto como marca da empresa."
                )
                user = (
                    "Analise o padrão recorrente das imagens. A posição pedida é da assinatura/logo "
                    "INSTITUCIONAL da empresa, nunca de logos de produtos dentro da oferta. Retorne: "
                    '{"logo_position":"top_left|top_right|bottom_left|bottom_right|center|unknown",'
                    '"layout_direction":"descrição curta de composição, hierarquia, margens e blocos",'
                    '"typography":"descrição curta",'
                    '"style_keywords":["até 6 termos"],'
                    '"color_usage":"como a paleta é aplicada",'
                    '"confidence":0.0}.'
                )
                parsed = extract_json(_complete_ai_with_images(cfg, system, user, images, 900)) or {}
                try:
                    parsed_confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0)))
                except Exception:
                    parsed_confidence = 0.0
                analysis_text = " ".join(str(parsed.get(k) or "") for k in
                                         ("layout_direction", "typography", "color_usage")).lower()
                # Text-only fallback cannot inspect the uploaded pixels. Do not persist its
                # characteristic "no images attached" answer as if it were visual analysis.
                if parsed_confidence < 0.25 or any(mark in analysis_text for mark in
                                                   ("sem imagem", "nenhuma imagem", "nenhum conteúdo visual")):
                    parsed = {}
                allowed = {"top_left", "top_right", "bottom_left", "bottom_right", "center", "unknown"}
                pos = str(parsed.get("logo_position") or "unknown")
                profile["logo_position"] = pos if pos in allowed else "unknown"
                profile["layout_direction"] = str(parsed.get("layout_direction") or "")[:800]
                profile["typography"] = str(parsed.get("typography") or "")[:400]
                profile["style_keywords"] = [
                    str(v)[:80] for v in (parsed.get("style_keywords") or [])[:6] if str(v).strip()
                ]
                profile["color_usage"] = str(parsed.get("color_usage") or "")[:500]
                profile["confidence"] = parsed_confidence if parsed else 0.0
        except Exception as exc:
            profile["analysis_note"] = ("análise visual indisponível: " + str(exc))[:300]
    brand_kit_extras_patch(company_id, {"reference_profile": profile})


def _spawn_reference_analysis(company_id: str) -> None:
    import threading
    current = brand_kit_get(company_id) or {}
    extras = dict(current.get("extras") or {})
    reference_profile = {
        **(extras.get("reference_profile") or {}),
        "status": "analyzing",
        "reference_count": len(asset_list(company_id, role="brand_reference")),
    }
    brand_kit_extras_patch(company_id, {"reference_profile": reference_profile})
    threading.Thread(target=_refresh_reference_profile, args=(company_id,), daemon=True).start()


@router.get("/{company_id}/references")
def list_references(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    refs = asset_list(company_id, role="brand_reference")
    return {"references": refs}


@router.post("/{company_id}/references")
async def upload_reference(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "ref.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "references")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    filepath = os.path.join(subdir, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/references/{filename}"
    asset = asset_create(company_id, {"kind": "IMAGE", "source": "UPLOADED", "url": url, "meta": {"role": "brand_reference"}})
    _spawn_reference_analysis(company_id)
    return {"reference": asset, "analysis_status": "analyzing"}


@router.delete("/{company_id}/references/{asset_id}")
def delete_reference(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    # get asset to find file path
    refs = asset_list(company_id, role="brand_reference")
    ref = next((r for r in refs if r["id"] == asset_id), None)
    if ref:
        # try to delete file
        url = ref.get("url", "")
        if url.startswith(UPLOAD_URL_PREFIX):
            rel_path = url[len(UPLOAD_URL_PREFIX):].lstrip("/")
            abs_path = os.path.join(UPLOAD_DIR, rel_path)
            if os.path.exists(abs_path):
                os.remove(abs_path)
    ok = asset_delete(asset_id)
    if not ok:
        return JSONResponse({"detail": "Referência não encontrada"}, status_code=404)
    _spawn_reference_analysis(company_id)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Competitors
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/competitors")
def list_competitors(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    comps = competitor_list(company_id)
    return {"competitors": comps}


@router.post("/{company_id}/competitors")
async def add_competitor(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    if not body.get("name"):
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    handles: Dict[str, str] = {}
    if body.get("instagram"):
        handles["instagram"] = body["instagram"]
    if body.get("website"):
        handles["website"] = body["website"]
    comp = competitor_create(company_id, {"name": body["name"], "handles": handles})
    return {"competitor": comp}


@router.delete("/{company_id}/competitors/{competitor_id}")
def remove_competitor(company_id: str, competitor_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    ok = competitor_delete(competitor_id)
    if not ok:
        return JSONResponse({"detail": "Concorrente não encontrado"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# All competitors (cross-company view)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/all/competitors")
def list_all_competitors(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    comps = competitor_list()
    return {"competitors": comps}


# ─────────────────────────────────────────────────────────────────────────────
# Products (Cliente → Produto) + Solutions (→ Solução) — content sources
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{company_id}/products")
def list_products(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    products = product_list(company_id)
    for p in products:
        p["solutions"] = solution_list(p["id"])
        p["logos"] = asset_list_logos(company_id, p["id"])
        p["photos"] = asset_list_photos(company_id, p["id"])   # Fase 2: fotos do produto (a IA analisa)
    return {"products": products}


@router.post("/{company_id}/products")
async def create_product(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not (data.get("name") or "").strip():
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    return {"product": product_create(company_id, data)}


@router.get("/{company_id}/products/copy-sources")
def product_copy_sources(company_id: str, request: Request):
    """Lista OUTRAS empresas (as que este usuário enxerga) com seus produtos, pra popular o seletor de
    'copiar produtos de outro cliente'. Respeita o escopo de tenancy (agência só vê as suas)."""
    err = _api_key_required(request)
    if err:
        return err
    from ..main_utils import scoped_company_ids
    scoped = scoped_company_ids(request)                       # None = super-admin (vê todas)
    out = []
    for co in (company_list() or []):
        cid = co.get("id")
        if cid == company_id:
            continue
        if scoped is not None and cid not in scoped:
            continue
        prods = product_list(cid) or []
        if not prods:
            continue
        out.append({"company_id": cid, "company_name": co.get("name") or "",
                    "products": [{"id": p.get("id"), "name": p.get("name") or "",
                                  "category": p.get("category") or ""} for p in prods]})
    return {"sources": out}


@router.post("/{company_id}/products/copy")
async def copy_products(company_id: str, request: Request):
    """Copia (duplica) produtos de OUTRO cliente pra este. Body: {source_company_id, product_ids?}.
    Sem product_ids → copia TODOS os produtos da origem. Cada cópia é independente (editar não afeta a origem)."""
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    src_cid = (data.get("source_company_id") or "").strip()
    if not src_cid or src_cid == company_id:
        return JSONResponse({"detail": "Informe um cliente de origem diferente."}, status_code=422)
    # escopo: o usuário só copia de empresas que ele enxerga
    from ..main_utils import scoped_company_ids
    scoped = scoped_company_ids(request)
    if scoped is not None and (src_cid not in scoped or company_id not in scoped):
        return JSONResponse({"detail": "Acesso negado a esse cliente."}, status_code=403)
    wanted = set(data.get("product_ids") or [])
    src_prods = product_list(src_cid) or []
    if wanted:
        src_prods = [p for p in src_prods if p.get("id") in wanted]
    copied = []
    for p in src_prods:
        np = product_copy(p.get("id"), company_id)
        if np:
            copied.append({"id": np.get("id"), "name": np.get("name")})
    return {"copied": copied, "count": len(copied)}


@router.put("/{company_id}/products/{product_id}")
async def update_product(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    product = product_update(product_id, data)
    if not product:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"product": product}


def _extract_doc_text(name: str, raw: bytes) -> str:
    """Extrai texto de PDF/DOCX/TXT/MD/CSV. PDF via pypdf; DOCX via zip+xml (sem dependência nova);
    resto decodifica UTF-8."""
    import io as _io
    ext = os.path.splitext(name or "")[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        rd = PdfReader(_io.BytesIO(raw))
        return "\n".join((pg.extract_text() or "") for pg in rd.pages)
    # DOCX (ou .doc que na real é docx): zip contendo word/document.xml
    if ext in (".docx", ".doc") or raw[:2] == b"PK":
        try:
            import zipfile
            import re as _re
            with zipfile.ZipFile(_io.BytesIO(raw)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            xml = _re.sub(r"</w:p>", "\n", xml)               # fim de parágrafo → quebra de linha
            txt = _re.sub(r"<[^>]+>", "", xml)                 # remove as tags
            return _re.sub(r"\n{3,}", "\n\n", txt)
        except Exception:
            if ext in (".docx", ".doc"):
                raise ValueError("DOCX inválido/corrompido — salve como PDF ou TXT e tente de novo.")
    return raw.decode("utf-8", "ignore")


def _vision_ocr_doc(name: str, raw: bytes) -> str:
    """OCR por VISÃO IA (OpenRouter gpt-4o): lê imagem (jpg/png/webp) ou PDF ESCANEADO (extrai as imagens
    das páginas via pypdf, sem poppler). Retorna o texto transcrito ou ''. Usado como fallback da KB."""
    import base64
    import io as _io
    import httpx as _hx
    from ..services.ai import _openrouter_key
    key = _openrouter_key()
    if not key:
        return ""
    ext = os.path.splitext(name or "")[1].lower()
    imgs: List[bytes] = []
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        imgs = [raw]
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            rd = PdfReader(_io.BytesIO(raw))
            for pg in rd.pages[:6]:                                   # teto de páginas (custo/latência)
                for im in (pg.images or []):
                    if im.data:
                        imgs.append(im.data)
                        break                                          # 1 imagem (a página) por página
        except Exception:
            return ""
    if not imgs:
        return ""
    parts = [{"type": "text", "text": "Transcreva TODO o texto legível destas imagens de documento, em ordem, "
                                      "mantendo títulos e listas. Responda SÓ com o texto transcrito."}]
    for b in imgs[:6]:
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}})
    from ..services.ai import _omniroute_base, _omniroute_key
    _chain = []
    if _omniroute_key():
        _chain.append((_omniroute_base(), _omniroute_key(), "cc/claude-haiku-4-5-20251001"))   # assinatura ($0)
    _chain.append(("https://openrouter.ai/api/v1", key, "openai/gpt-4o"))                       # pago, fallback
    for _b, _k, _m in _chain:
        try:
            r = _hx.post(_b + "/chat/completions",
                         headers={"Authorization": "Bearer " + _k, "Content-Type": "application/json"},
                         json={"model": _m, "stream": False, "max_tokens": 4000,
                               "messages": [{"role": "user", "content": parts}]},
                         timeout=_hx.Timeout(120.0, connect=15.0))
            if r.status_code >= 400:
                continue
            txt = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""


@router.post("/{company_id}/products/{product_id}/kb")
async def upload_product_kb(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    """BASE DE CONHECIMENTO do produto: sobe PDF/TXT/MD, EXTRAI o texto e ACUMULA em product.knowledge.
    O briefing usa esse texto (funções/fatos REAIS) p/ não ficar raso. Junta com o site (functions) e a internet."""
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    raw = await file.read()
    name = file.filename or "doc.txt"
    import asyncio as _aio
    try:
        text = ((await _aio.to_thread(_extract_doc_text, name, raw)) or "").strip()
    except Exception as e:
        return JSONResponse({"detail": f"Falha ao ler '{name}': {e}"}, status_code=400)
    if not text or len(text) < 20:
        # PDF escaneado (imagem) ou arquivo de imagem → OCR por VISÃO IA (fallback)
        try:
            text = ((await _aio.to_thread(_vision_ocr_doc, name, raw)) or "").strip()
        except Exception:
            text = ""
    if not text:
        return JSONResponse({"detail": f"Não consegui extrair texto de '{name}'. Formatos: PDF, DOCX, TXT, MD, CSV, "
                                       f"e imagem/PDF escaneado (via OCR). Se falhou, tente salvar como PDF ou TXT."}, status_code=400)
    prev = (prod.get("knowledge") or "").strip()
    merged = (prev + f"\n\n===== {name} =====\n" + text).strip()[:60000]   # teto p/ não estourar o prompt
    product_update(product_id, {"knowledge": merged})
    # AUTO-PREENCHER descrição/objetivo/funções a partir do documento (só campos VAZIOS — não sobrescreve).
    filled = {}
    try:
        need_desc = not (prod.get("description") or "").strip()
        _fns = prod.get("functions") or []
        if isinstance(_fns, str):
            try:
                import json as _j
                _fns = _j.loads(_fns)
            except Exception:
                _fns = [_fns] if _fns.strip() else []
        need_obj = not (prod.get("objective") or "").strip()
        need_fns = not _fns
        if need_desc or need_obj or need_fns:
            from ..services.ai import cheap_text_config, get_ai_config, complete_ai, extract_json
            cfg = cheap_text_config(get_ai_config())
            if cfg:
                sysm = "Você extrai dados de produto/serviço de um documento. Responda SÓ JSON válido, pt-BR, sem preços."
                usr = (f"Oferta: {prod.get('name','')}. Do texto do documento abaixo, extraia: "
                       '{"description":"descrição clara em 1-2 frases","objective":"como VENDER/posicionar esta oferta '
                       '(1-2 frases)","functions":["benefício/função 1","benefício 2","..."]} (3 a 8 functions). '
                       "DOCUMENTO:\n" + text[:12000])
                import asyncio as _aio2
                data = extract_json(await _aio2.to_thread(complete_ai, cfg, sysm, usr, 900)) or {}
                upd = {}
                if need_desc and (data.get("description") or "").strip():
                    upd["description"] = data["description"].strip()
                if need_obj and (data.get("objective") or "").strip():
                    upd["objective"] = data["objective"].strip()
                if need_fns and isinstance(data.get("functions"), list) and data["functions"]:
                    upd["functions"] = [str(f).strip() for f in data["functions"] if str(f).strip()][:10]
                if upd:
                    product_update(product_id, upd)
                    filled = upd
    except Exception:
        pass
    return {"ok": True, "file": name, "chars": len(text), "total_chars": len(merged),
            "filled": filled, "product": product_get(product_id)}


@router.get("/{company_id}/products/{product_id}/kb")
def get_product_kb(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    kb = (prod.get("knowledge") or "")
    return {"chars": len(kb), "preview": kb[:2000]}


@router.delete("/{company_id}/products/{product_id}/kb")
def clear_product_kb(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    product_update(product_id, {"knowledge": ""})
    return {"ok": True}


def _hex_hsv(value: str):
    import colorsys
    value = (value or "").lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def _brand_colors_similar(first: str, second: str) -> bool:
    """Group perceptually equivalent shades, including the lime pair seen on Rio Cable."""
    try:
        a = tuple(int(first.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        b = tuple(int(second.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        if sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5 < 46:
            return True
        ah, ass, av = _hex_hsv(first)
        bh, bss, bv = _hex_hsv(second)
        if ass < 0.16 and bss < 0.16:
            return abs(av - bv) < 0.18
        hue_distance = min(abs(ah - bh), 1.0 - abs(ah - bh))
        return ass >= 0.16 and bss >= 0.16 and hue_distance < 0.045 and abs(av - bv) < 0.28
    except Exception:
        return first.upper() == second.upper()


def _dominant_colors(path: str, n: int = 8, *, remove_background: bool = False) -> List[str]:
    """Extract up to ``n`` distinct brand colors while preserving white/black foreground marks.

    Transparent pixels are ignored instead of being composited over white. On opaque images only a
    dominant border color is treated as page background. Chromatic families are ranked by presence,
    then useful neutral colors are appended.
    """
    try:
        import colorsys
        from collections import Counter
        from PIL import Image

        img = Image.open(path).convert("RGBA")
        img.thumbnail((192, 192), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())
        visible_pixels = [(r, g, b, a) for r, g, b, a in pixels if a >= 64]
        if not visible_pixels:
            return []
        visible = [(r, g, b) for r, g, b, _a in visible_pixels]
        total_visible_weight = sum(a / 255.0 for _r, _g, _b, a in visible_pixels)

        transparent_ratio = sum(1 for _r, _g, _b, a in pixels if a < 240) / float(len(pixels))
        background = None
        if remove_background and transparent_ratio < 0.02 and img.width > 2 and img.height > 2:
            border = []
            for x in range(img.width):
                border.extend((img.getpixel((x, 0))[:3], img.getpixel((x, img.height - 1))[:3]))
            for y in range(1, img.height - 1):
                border.extend((img.getpixel((0, y))[:3], img.getpixel((img.width - 1, y))[:3]))
            buckets = Counter(tuple(min(255, int(round(channel / 16.0) * 16)) for channel in rgb)
                              for rgb in border)
            if buckets:
                candidate, count = buckets.most_common(1)[0]
                if count / float(len(border)) >= 0.48:
                    share = sum(1 for rgb in visible
                                if sum((rgb[i] - candidate[i]) ** 2 for i in range(3)) ** 0.5 < 34) / float(len(visible))
                    if share >= 0.22:
                        background = candidate

        strip = Image.new("RGB", (len(visible), 1))
        strip.putdata(visible)
        quantized = strip.quantize(colors=48)
        palette = quantized.getpalette() or []
        weighted_counts: Counter = Counter()
        for index, (_r, _g, _b, alpha) in zip(quantized.getdata(), visible_pixels):
            weighted_counts[index] += alpha / 255.0
        candidates = []
        for index, count in weighted_counts.items():
            r, g, b = palette[index * 3:index * 3 + 3]
            if background and sum(((r, g, b)[i] - background[i]) ** 2 for i in range(3)) ** 0.5 < 38:
                continue
            h, saturation, value = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if count / total_visible_weight < 0.0015:
                continue
            score = count * (0.78 + 0.22 * saturation)
            candidates.append((score, count, saturation, value, r, g, b))

        # Merge a color family before ranking it. Merely dropping the second lime shade made a
        # small orange detail outrank Rio Cable's structural green instead of adding both lime shares.
        families: List[Dict[str, Any]] = []
        for item in sorted(candidates, key=lambda candidate: candidate[1], reverse=True):
            score, count, saturation, value, r, g, b = item
            color = f"#{r:02X}{g:02X}{b:02X}"
            family = next((entry for entry in families
                           if _brand_colors_similar(color, entry["color"])), None)
            if family:
                family["score"] += score
                family["count"] += count
                if count > family["representative_count"]:
                    family.update({"color": color, "saturation": saturation, "value": value,
                                   "rgb": (r, g, b), "representative_count": count})
            else:
                families.append({
                    "color": color, "score": score, "count": count, "saturation": saturation,
                    "value": value, "rgb": (r, g, b), "representative_count": count,
                })

        grouped = [(entry["score"], entry["count"], entry["saturation"], entry["value"], *entry["rgb"])
                   for entry in families]
        chromatic = sorted((item for item in grouped if item[2] >= 0.16), reverse=True)
        neutral = sorted((item for item in grouped if item[2] < 0.16), key=lambda item: item[1], reverse=True)
        picked: List[str] = []
        for item in chromatic + neutral:
            _score, _count, _sat, _value, r, g, b = item
            value = f"#{r:02X}{g:02X}{b:02X}"
            if any(_brand_colors_similar(value, old) for old in picked):
                continue
            picked.append(value)
            if len(picked) >= max(1, n):
                break
        return picked
    except Exception:
        return []


def _company_logo_colors(company_id: str, max_colors: int = 8) -> Dict[str, str]:
    """Build one free-size palette from every trusted logo, with semantic neutral names."""
    try:
        company_name = (company_get(company_id) or {}).get("name") or ""
        logos = list(asset_list_logos(company_id) or [])
        logos.sort(key=lambda logo: (
            0 if (logo.get("meta") or {}).get("is_primary") else 1,
            1 if (logo.get("meta") or {}).get("variant") == "site_render" else 0,
        ))
        palette: List[str] = []
        for logo in logos:
            if not _trusted_company_logo(logo, company_name):
                continue
            meta = logo.get("meta") or {}
            # A screenshot with the site's background is a useful logo variant, but its background
            # must not contaminate the official palette when transparent assets are available.
            has_chromatic = any(_hex_hsv(color)[1] >= 0.16 for color in palette)
            if meta.get("variant") == "site_render" and has_chromatic:
                continue
            url = logo.get("url") or ""
            if url.lower().endswith(".svg") or not url.startswith(UPLOAD_URL_PREFIX):
                continue
            path = os.path.join(UPLOAD_DIR, url[len(UPLOAD_URL_PREFIX):].lstrip("/"))
            for color in _dominant_colors(path, max_colors):
                if any(_brand_colors_similar(color, old) for old in palette):
                    continue
                palette.append(color)
                if len(palette) >= max_colors:
                    break
            if len(palette) >= max_colors:
                break

        if not palette:
            return {}
        chromatic, neutrals = [], []
        for color in palette:
            (_h, saturation, value) = _hex_hsv(color)
            (chromatic if saturation >= 0.16 else neutrals).append((color, value))

        named: Dict[str, str] = {}
        if chromatic:
            named["primary"] = chromatic[0][0]
            if len(chromatic) == 2:
                named["accent"] = chromatic[1][0]
            elif len(chromatic) >= 3:
                named["secondary"] = chromatic[1][0]
                named["accent"] = chromatic[2][0]
                for index, (color, _value) in enumerate(chromatic[3:], start=4):
                    named[f"color{index}"] = color
        else:
            named["primary"] = neutrals.pop(0)[0]

        neutral_names = {"light": 0, "mid": 0, "dark": 0}
        for color, value in neutrals:
            tone = "light" if value >= 0.78 else ("dark" if value <= 0.30 else "mid")
            neutral_names[tone] += 1
            suffix = "" if neutral_names[tone] == 1 else str(neutral_names[tone])
            named[f"neutral_{tone}{suffix}"] = color
        return named
    except Exception:
        return {}


@router.post("/{company_id}/products/{product_id}/enrich")
async def enrich_product(company_id: str, product_id: str, request: Request):
    """Read the product's site + Instagram and auto-fill its profile (functions, objective,
    colors, à-la-carte) — never prices."""
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    website = (body.get("website") or prod.get("website") or "").strip()
    instagram = (body.get("instagram") or (prod.get("socials") or {}).get("instagram") or "").strip()
    try:
        from ..services.ai import enrich_product_from_web
        data = enrich_product_from_web(prod.get("name") or "", website, instagram)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    update = {"website": website, "socials": {**(prod.get("socials") or {}), "instagram": instagram}}
    for k in ("description", "objective", "category", "functions"):
        if data.get(k):
            update[k] = data[k]
    # Colors from the uploaded product logo (more reliable than site text).
    try:
        for lg in (asset_list_logos(company_id, product_id) or []):
            u = lg.get("url") or ""
            if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
                continue
            # Product colors are still stored in the legacy three semantic slots.
            cols = _dominant_colors(
                os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/")), 3,
            )
            if cols:
                keys = ["primary", "secondary", "accent"]
                data["colors"] = {**(data.get("colors") or {}), **{keys[i]: c for i, c in enumerate(cols)}}
                break
    except Exception:
        pass
    if data.get("colors"):
        update["colors"] = {**(prod.get("colors") or {}), **data["colors"]}
    product = product_update(product_id, update)
    created = []
    if body.get("create_alacarte"):
        existing = {(s.get("name") or "").strip().lower() for s in solution_list(product_id)}
        for item in (data.get("alacarte") or []):
            if item.strip().lower() not in existing:
                solution_create(product_id, {"name": item})
                created.append(item)
    return {"product": product, "extracted": data, "alacarte_created": created}


@router.delete("/{company_id}/products/{product_id}")
def delete_product(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not product_delete(product_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"deleted": True}


@router.post("/{company_id}/products/{product_id}/logo")
async def upload_product_logo(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    if not product_get(product_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "products", product_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/products/{product_id}/{filename}"
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url, "product_id": product_id,
        "meta": {"role": "logo", "variant": "light"},
    })
    return {"logo": asset}


@router.post("/{company_id}/products/{product_id}/photo")
async def upload_product_photo(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    """FOTO do produto (Fase 2): sobe a imagem, analisa por VISÃO (gpt-4o) os FATOS VISUAIS imutáveis do item e
    ACUMULA em product.knowledge com prefixo [IMAGEM DO PRODUTO] → a CENA e a NARRAÇÃO do vídeo ancoram no item
    REAL (não alucina). Custo-seguro: se a visão falhar, a foto é salva mesmo assim."""
    err = _api_key_required(request)
    if err:
        return err
    prod = product_get(product_id)
    if not prod:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    import uuid as _uuid
    raw = await file.read()
    ext = os.path.splitext(file.filename or "photo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "products", product_id)
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(raw)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/products/{product_id}/{filename}"
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url, "product_id": product_id, "meta": {"role": "photo"},
    })
    facts = ""
    try:
        from ..services.ai import vision_product_facts
        facts, _cost = vision_product_facts(raw)
        if facts:
            prev = (prod.get("knowledge") or "").strip()
            tag = f"[IMAGEM DO PRODUTO] {facts}"
            if tag not in prev:                                # acumula sem duplicar; vira "fato" no _video_brief_context
                product_update(product_id, {"knowledge": (prev + ("\n\n" if prev else "") + tag)})
    except Exception:
        facts = ""
    return {"photo": asset, "facts": facts}


@router.delete("/{company_id}/products/{product_id}/photo/{asset_id}")
def delete_product_photo(company_id: str, product_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"deleted": asset_delete(asset_id)}


@router.get("/{company_id}/products/{product_id}/solutions")
def list_solutions(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"solutions": solution_list(product_id)}


@router.post("/{company_id}/products/{product_id}/solutions")
async def create_solution(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not (data.get("name") or "").strip():
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    sol = solution_create(product_id, data)
    if not sol:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"solution": sol}


@router.put("/{company_id}/solutions/{solution_id}")
async def update_solution(company_id: str, solution_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    sol = solution_update(solution_id, data)
    if not sol:
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    return {"solution": sol}


@router.delete("/{company_id}/solutions/{solution_id}")
def delete_solution(company_id: str, solution_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    if not solution_delete(solution_id):
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Multi-logo (company): principal + variations (light/dark/format)
# ─────────────────────────────────────────────────────────────────────────────

def _logo_promotion_rank(logo: Dict[str, Any]):
    meta = logo.get("meta") or {}
    source = logo.get("source") or ""
    variant = meta.get("variant") or ""
    source_rank = 0 if source == "UPLOADED" else (1 if source in ("INSTAGRAM", "FACEBOOK") else 2)
    variant_rank = {
        "transparent": 0, "site_logo": 1, "logo": 1, "light": 1,
        "dark": 1, "site_icon": 3, "site_render": 5,
    }.get(variant, 2)
    return source_rank, variant_rank, logo.get("created_at") or "", logo.get("id") or ""


def _ensure_logo_primary_consistency(
    company_id: str, logos: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    logos = list(logos if logos is not None else (asset_list_logos(company_id) or []))
    if not logos:
        return logos
    primary = [logo for logo in logos if (logo.get("meta") or {}).get("is_primary")]
    kit_url = (brand_kit_get(company_id) or {}).get("logo_url") or ""
    matching = next((logo for logo in logos if logo.get("url") == kit_url), None)
    if len(primary) == 1 and (not matching or primary[0].get("id") == matching.get("id")):
        return logos
    chosen = matching or min(logos, key=_logo_promotion_rank)
    source = None if matching else ("MANUAL" if chosen.get("source") == "UPLOADED" else "AUTO")
    asset_set_primary_logo(company_id, chosen["id"], source)
    return list(asset_list_logos(company_id) or logos)

@router.get("/{company_id}/logos")
def list_logos(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"logos": _ensure_logo_primary_consistency(company_id)}


@router.post("/{company_id}/logos")
async def upload_logo_variant(
    company_id: str,
    request: Request,
    file: UploadFile = File(...),
    variant: str = Form("light"),
    primary: str = Form("false"),
):
    err = _api_key_required(request)
    if err:
        return err
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    subdir = os.path.join(UPLOAD_DIR, company_id, "logos")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}.png"
    try:
        content = _normalize_logo_upload(await file.read(_MAX_LOGO_UPLOAD_BYTES + 1))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logos/{filename}"
    is_primary = str(primary).lower() in ("1", "true", "yes") or not bool(asset_list_logos(company_id))
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url,
        "meta": {"role": "logo", "variant": variant or "logo", "is_primary": False,
                 "identity_scope": "company", "confidence": 1.0},
    })
    # Keep brand kit's primary logo_url in sync when this is the primary logo.
    if is_primary:
        asset = asset_set_primary_logo(company_id, asset["id"], "MANUAL") or asset
    return {"logo": asset}


@router.post("/{company_id}/logos/{asset_id}/primary")
def set_primary_logo(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    asset = asset_get(asset_id)
    meta = (asset or {}).get("meta") or {}
    if (not asset or asset.get("company_id") != company_id or asset.get("product_id") is not None
            or meta.get("role") != "logo"):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    asset = asset_set_primary_logo(company_id, asset_id, "MANUAL")
    if not asset:
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    return {"logo": asset}


@router.delete("/{company_id}/logos/{asset_id}")
def delete_logo(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    asset = asset_get(asset_id)
    meta = (asset or {}).get("meta") or {}
    if (not asset or asset.get("company_id") != company_id or asset.get("product_id") is not None
            or meta.get("role") != "logo"):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    if asset and (asset.get("url") or "").startswith(UPLOAD_URL_PREFIX):
        rel_path = asset["url"][len(UPLOAD_URL_PREFIX):].lstrip("/")
        abs_path = os.path.join(UPLOAD_DIR, rel_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    if not asset_delete(asset_id):
        return JSONResponse({"detail": "Logo não encontrado"}, status_code=404)
    kit = brand_kit_get(company_id) or {}
    if meta.get("is_primary") or kit.get("logo_url") == asset.get("url"):
        remaining = list(asset_list_logos(company_id) or [])
        if remaining:
            chosen = min(remaining, key=_logo_promotion_rank)
            chosen = asset_set_primary_logo(company_id, chosen["id"], "MANUAL") or chosen
        else:
            brand_kit_upsert(company_id, {"logo_url": None})
    return {"deleted": True, "logos": asset_list_logos(company_id)}
