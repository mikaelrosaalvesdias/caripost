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
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..db_companies import (
    company_list, company_get, company_create, company_update, company_delete,
    company_convert_to_managed, company_lifecycle_stage_validate,
    brand_kit_get, brand_kit_upsert, brand_kit_extras_patch, brand_kit_apply_auto,
    normalize_brand_colors,
    competitor_list, competitor_create, competitor_delete,
    asset_list, asset_create, asset_delete, asset_get, asset_update_meta,
    asset_list_logos, asset_list_photos, asset_clear_primary, asset_set_primary_logo,
    asset_claim_primary_logo_if_empty,
    product_list, product_get, product_create, product_copy, product_update, product_delete,
    product_group_list, product_group_get, product_group_create, product_group_update, product_group_delete,
    product_plan_list, product_plan_get, product_plan_create, product_plan_update, product_plan_delete,
    catalog_link_list, catalog_link_get, catalog_link_create, catalog_link_delete,
    catalog_link_references_product, catalog_link_references_plan, catalog_link_references_solution,
    solution_list, solution_get, solution_create, solution_update, solution_delete,
)
from ..db import settings_get
from ..main_utils import company_access_denied as _company_access_denied

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _company_scope_required(request: Request, company_id: str):
    return _company_access_denied(request, company_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ENRICHMENT_RUNNING: set[str] = set()
_ENRICHMENT_GUARD = threading.Lock()
_REFERENCE_ANALYSIS_GUARD = threading.Lock()


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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    try:
        lifecycle_stage = company_lifecycle_stage_validate(body.get("lifecycle_stage", "prospect"))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
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
        "lifecycle_stage": lifecycle_stage,
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
            products_found=0,
            product_pages_scanned=0,
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    body = await request.json()
    if "lifecycle_stage" in body:
        try:
            body["lifecycle_stage"] = company_lifecycle_stage_validate(body["lifecycle_stage"])
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
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


@router.post("/{company_id}/convert-to-managed")
def convert_company_to_managed(company_id: str, request: Request):
    """Idempotently promote a prospect while preserving its ID and accumulated data."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    company = company_convert_to_managed(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"company": company}


@router.delete("/{company_id}")
def delete_company(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    try:
        ok = company_delete(company_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    bk = brand_kit_get(company_id)
    return {"brand_kit": bk}


@router.post("/{company_id}/brand-kit")
async def save_brand_kit(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    if not _catalog_public_url(url):
        return out
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            context = b.new_context(
                viewport={"width": 1366, "height": 900}, device_scale_factor=3,
                service_workers="block",
            )   # logo nítida (3x)
            pg = context.new_page()
            def _guard_request(route):
                request_url = route.request.url
                scheme = urlparse(request_url).scheme.lower()
                if scheme in ("about", "blob", "data") or _catalog_public_url(request_url):
                    route.continue_()
                else:
                    route.abort()
            pg.route("**/*", _guard_request)
            try:
                # Static brand/catalog reading never needs a WebSocket; blocking it closes an SSRF bypass.
                pg.route_web_socket("**/*", lambda websocket: websocket.close())
            except (AttributeError, TypeError):
                pass
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


_CATALOG_ASSET_EXTENSIONS = {
    ".css", ".js", ".mjs", ".json", ".xml", ".map", ".txt", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".webm", ".zip",
}
_CATALOG_URL_TERMS = re.compile(
    r"plano|planos|servi[cç]|produto|combo|pacote|oferta|internet|fibra|residencial|empresarial|loja|"
    r"contrate|contratar|assine|assinar",
    re.I,
)
_CATALOG_ACTION_TERMS = re.compile(
    r"\bcontrat(?:e|ar|a[cç][aã]o)\b|\bassin(?:e|ar)\b|conhe[cç]a|ver\s+planos?|saiba\s+mais", re.I,
)
_CATALOG_SENSITIVE_PATH = re.compile(
    r"/(?:_?api|admin|auth|login|logout|sign-?in|sign-?out|conta|account|perfil|profile|"
    r"delete|remove|cancel|checkout|cart|carrinho|boletos?|faturas?|segunda-?via|"
    r"(?:c[oó]pia-)?contratos?)(?:/|$)",
    re.I,
)
_BRAZIL_STATE_LABEL = re.compile(
    r"(?:^|[-,\s])(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\s*$",
    re.I,
)
_BRAZIL_STATE_CODES = frozenset(
    "ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to".split()
)
_CATALOG_MIN_SCORE = 5


def _catalog_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()


def _catalog_name_has_location(name: str, location: str) -> bool:
    name_words = re.findall(r"[a-z0-9]+", _catalog_fold(name))
    location_words = re.findall(r"[a-z0-9]+", _catalog_fold(location))
    if not name_words or not location_words:
        return False
    candidates = [location_words]
    if len(location_words) > 1 and location_words[-1] in _BRAZIL_STATE_CODES:
        candidates.append(location_words[:-1])
    return any(
        name_words[index:index + len(candidate)] == candidate
        for candidate in candidates
        for index in range(len(name_words) - len(candidate) + 1)
    )


class _CatalogLinkParser(HTMLParser):
    """Collect navigable catalog links, including locality selectors rendered by JS sites."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: List[Dict[str, Any]] = []
        self._active: List[tuple[str, Dict[str, Any]]] = []
        self._json_parts: Optional[List[str]] = None

    def _append_json_options(self, value: Any) -> None:
        if isinstance(value, dict):
            target = value.get("value")
            label = value.get("text")
            if (isinstance(target, str) and isinstance(label, str)
                    and re.match(r"^(?:https?:)?//|^/", target.strip())):
                self.items.append({
                    "target": target.strip(), "label": label.strip(),
                    "kind": "option", "index": len(self.items),
                })
            for child in value.values():
                self._append_json_options(child)
        elif isinstance(value, list):
            for child in value:
                self._append_json_options(child)

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        amap = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag == "script" and "json" in (amap.get("type") or "").lower():
            self._json_parts = []
            return
        if tag not in ("a", "option"):
            return
        target = amap.get("href") if tag == "a" else amap.get("value")
        if not (target or "").strip():
            return
        item = {
            "target": target.strip(),
            "label": " ".join(filter(None, (amap.get("aria-label"), amap.get("title")))).strip(),
            "kind": tag,
            "index": len(self.items),
        }
        self.items.append(item)
        self._active.append((tag, item))

    def handle_data(self, data: str):
        if self._json_parts is not None:
            self._json_parts.append(data or "")
            return
        clean = re.sub(r"\s+", " ", data or " ").strip()
        if not clean:
            return
        for _tag, item in self._active:
            item["label"] = (item["label"] + " " + clean).strip()

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag == "script" and self._json_parts is not None:
            try:
                import json
                self._append_json_options(json.loads("".join(self._json_parts)))
            except Exception:
                pass
            self._json_parts = None
            return
        for index in range(len(self._active) - 1, -1, -1):
            if self._active[index][0] == tag:
                self._active.pop(index)
                break


class _CatalogTextParser(HTMLParser):
    """Extract user-facing text plus useful image labels; never feed JS/CSS payloads to the AI."""

    _SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        amap = {str(key).lower(): str(value or "") for key, value in attrs}
        for key in ("aria-label", "alt", "title"):
            if amap.get(key):
                self.parts.append(amap[key])

    def handle_endtag(self, tag: str):
        if tag.lower() in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str):
        if not self._skip_depth and (data or "").strip():
            self.parts.append(data)


def _catalog_visible_text(html: str) -> str:
    parser = _CatalogTextParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _catalog_offer_score(text: str) -> int:
    """Rank actual commercial content instead of treating any long page as a catalog."""
    raw = text or ""
    folded = _catalog_fold(raw)
    score = 0
    score += min(3, len(re.findall(r"\b\d{2,4}\s*(?:mega|mb(?:ps)?|giga|gb(?:ps)?)\b", folded))) * 12
    score += min(3, len(re.findall(r"r\$\s*\d", folded))) * 12
    if re.search(r"\bplanos?\b|\bpacotes?\b|\bcombos?\b|\bofertas?\b", folded):
        score += 7
    if re.search(r"\bprodutos?\b|\bservicos?\b", folded):
        score += 5
    if re.search(r"contrat|assine|por\s+mes|mensal", folded):
        score += 4
    if re.search(r"\binternet\b|\bfibra\b", folded):
        score += 2
    return score


def _catalog_has_concrete_offer_signal(text: str) -> bool:
    """Prices/speeds prove card content; generic menu words alone must still trigger rendering."""
    folded = _catalog_fold(text or "")
    return bool(
        re.search(r"\b\d{2,4}\s*(?:mega|mb(?:ps)?|giga|gb(?:ps)?)\b", folded)
        or re.search(r"r\$\s*\d", folded)
    )


def _catalog_should_render(text: str, html: str) -> bool:
    if _catalog_has_concrete_offer_signal(text):
        return False
    visible_length = len((text or "").strip())
    html_length = len(html or "")
    return visible_length < 2500 or bool(html_length and visible_length * 30 < html_length)


def _catalog_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _catalog_related_host(url: str, base_host: str) -> bool:
    host = _catalog_host(url)
    normalized_base = (base_host or "").lower().rstrip(".")
    return bool(host and normalized_base and (host == normalized_base or host.endswith("." + normalized_base)))


def _catalog_public_host(host: str, port: int) -> bool:
    import ipaddress
    import socket

    normalized = (host or "").lower().rstrip(".")
    if (not normalized or normalized == "localhost"
            or normalized.endswith((".localhost", ".local", ".internal"))):
        return False
    try:
        addresses = {item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)}
    except Exception:
        return False
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        return False


def _catalog_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in (80, 443):
            return False
        return _catalog_public_host(parsed.hostname or "", port)
    except (TypeError, ValueError):
        return False


class _CatalogResponse:
    def __init__(self, *, status_code: int, url: str, headers: Dict[str, str], body: bytes):
        self.status_code = status_code
        self.url = url
        self.headers = headers
        content_type = headers.get("content-type", "")
        charset_match = re.search(r"charset=([\w.-]+)", content_type, re.I)
        charset = charset_match.group(1) if charset_match else "utf-8"
        try:
            self.text = body.decode(charset, errors="replace")
        except LookupError:
            self.text = body.decode("utf-8", errors="replace")


def _catalog_http_get(
    client: Any, url: str, *, timeout: float, headers: Dict[str, str], allowed_host: str = "",
):
    """Follow redirects one by one so no request can jump from an official site to a private host."""
    import time

    current = url
    deadline = time.monotonic() + max(20.0, timeout + 5.0)
    max_body_bytes = 3 * 1024 * 1024
    for _attempt in range(5):
        if not _catalog_public_url(current):
            raise RuntimeError("URL de catálogo não é pública ou usa uma porta não permitida")
        if allowed_host and not _catalog_related_host(current, allowed_host):
            raise RuntimeError("redirecionamento para domínio não oficial bloqueado")
        if time.monotonic() >= deadline:
            raise RuntimeError("o site excedeu o tempo total permitido")
        stream = getattr(client, "stream", None)
        if callable(stream):
            with stream(
                "GET", current, timeout=min(timeout, 10.0), follow_redirects=False, headers=headers,
            ) as streamed:
                status_code = int(getattr(streamed, "status_code", 200) or 200)
                response_headers = {str(key).lower(): str(value) for key, value in streamed.headers.items()}
                length = response_headers.get("content-length") or ""
                if length.isdigit() and int(length) > max_body_bytes:
                    raise RuntimeError("a página excede o limite de 3 MB")
                location = response_headers.get("location", "").strip()
                if status_code in (301, 302, 303, 307, 308) and location:
                    current = urldefrag(urljoin(current, location))[0]
                    continue
                body = bytearray()
                content_type = response_headers.get("content-type", "").lower()
                if status_code < 400 and (not content_type or "html" in content_type):
                    for chunk in streamed.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_body_bytes:
                            raise RuntimeError("a página excede o limite de 3 MB")
                        if time.monotonic() >= deadline:
                            raise RuntimeError("o site excedeu o tempo total permitido")
                return _CatalogResponse(
                    status_code=status_code, url=str(streamed.url), headers=response_headers, body=bytes(body),
                )
        response = client.get(current, timeout=timeout, follow_redirects=False, headers=headers)
        status_code = int(getattr(response, "status_code", 200) or 200)
        location = str((getattr(response, "headers", {}) or {}).get("location", "")).strip()
        if status_code in (301, 302, 303, 307, 308) and location:
            current = urldefrag(urljoin(current, location))[0]
            continue
        return response
    raise RuntimeError("o site excedeu o limite seguro de redirecionamentos")


def _catalog_page_candidates(base_url: str, html_sources: List[str], city: str = "") -> List[Dict[str, Any]]:
    """Return ranked, same-site HTML pages. Option values let city-hub sites expose their plans."""
    base_host = _catalog_host(base_url)
    base_parts = urlparse(base_url)
    base_path = (base_parts.path or "/").rstrip("/") or "/"
    city_key = re.sub(r"[^a-z0-9]", "", _catalog_fold(city))
    merged: Dict[str, Dict[str, Any]] = {}
    source_index = 0
    for source in html_sources:
        parser = _CatalogLinkParser()
        try:
            parser.feed(source or "")
        except Exception:
            pass
        option_count = sum(1 for item in parser.items if item.get("kind") == "option")
        location_hint = bool(re.search(
            r"(?:escolha|selecione|informe|troque).{0,40}(?:cidade|localidade)|(?:sua|por)\s+cidade",
            _catalog_fold(_catalog_visible_text(source or "")), re.I,
        ))
        for item in parser.items:
            full = urldefrag(urljoin(base_url, item["target"]))[0]
            parsed = urlparse(full)
            if parsed.scheme not in ("http", "https") or not _catalog_related_host(full, base_host):
                continue
            path = unquote(parsed.path or "/")
            if (path.rstrip("/") or "/") == base_path and not parsed.query:
                continue
            if os.path.splitext(path.lower())[1] in _CATALOG_ASSET_EXTENSIONS:
                continue
            if (_CATALOG_SENSITIVE_PATH.search(path)
                    or re.search(r"(?:^|[?&])(?:action|do)=(?:delete|remove|logout|cancel)(?:&|$)", parsed.query, re.I)):
                continue
            label = re.sub(r"\s+", " ", item.get("label") or "").strip()
            haystack = f"{path} {label}"
            folded_haystack = _catalog_fold(haystack)
            compact_haystack = re.sub(r"[^a-z0-9]", "", folded_haystack)
            city_match = bool(city_key and city_key in compact_haystack)
            state_label = bool(_BRAZIL_STATE_LABEL.search(label))
            catalog_term = bool(_CATALOG_URL_TERMS.search(haystack))
            location_option = bool(city_match or state_label or (option_count >= 2 and location_hint))
            score = 0
            if item.get("kind") == "option" and (location_option or catalog_term):
                score += 70
            if catalog_term:
                score += 100
            if catalog_term and _CATALOG_ACTION_TERMS.search(label):
                score += 30
            if city_match:
                score += 220
            if score <= 0:
                continue
            normalized = parsed._replace(fragment="").geturl()
            candidate = {
                "url": normalized,
                "label": label,
                "kind": item.get("kind") or "a",
                "score": score,
                "city_match": city_match,
                "is_location": location_option,
                "index": source_index + int(item.get("index") or 0),
            }
            previous = merged.get(normalized)
            if not previous or candidate["score"] > previous["score"]:
                merged[normalized] = candidate
            elif previous and label and label not in previous.get("label", ""):
                previous["label"] = (previous.get("label", "") + " / " + label).strip(" /")
        source_index += len(parser.items) + 1
    candidates = sorted(merged.values(), key=lambda item: (-item["score"], item["index"], item["url"]))
    if city_key and any(item["city_match"] for item in candidates):
        # A known city is authoritative. Keep its locality plus generic catalog pages, not prices
        # from unrelated municipalities.
        candidates = [item for item in candidates if item["city_match"] or item["kind"] != "option"]
    return candidates


def _auto_extract_products(company_id: str, website: str) -> Dict[str, Any]:
    """Discover real offer pages, extract their catalog with AI and persist only missing items."""
    import httpx as _hx
    from ..db_companies import product_list, product_create

    result: Dict[str, Any] = {
        "added": 0, "found": 0, "pages_scanned": 0, "source_pages": [], "warnings": [],
    }
    if not website:
        return result
    base = website if website.startswith("http") else "https://" + website
    ua = {"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"}
    company = company_get(company_id) or {}
    city = (company.get("city") or "").strip()
    render_budget = 2

    def _render_catalog_page(url: str) -> Dict[str, Any]:
        nonlocal render_budget
        if render_budget <= 0:
            return {}
        render_budget -= 1
        return _render_site(url) or {}

    try:
        response = _catalog_http_get(_hx, base, timeout=20.0, headers=ua)
        if int(getattr(response, "status_code", 200) or 200) >= 400:
            raise RuntimeError(f"site respondeu HTTP {response.status_code}")
    except Exception as exc:
        result["warnings"].append("Não foi possível abrir o site para importar ofertas: " + str(exc)[:160])
        return result

    home_url = str(getattr(response, "url", None) or base)
    home_html = response.text or ""
    home_text = _catalog_visible_text(home_html)
    home_score = _catalog_offer_score(home_text)
    rendered_home: Dict[str, Any] = {}
    if _catalog_should_render(home_text, home_html):
        # Length is not relevance: Wix/SPA shells can have thousands of chars and no offer at all.
        rendered_home = _render_catalog_page(home_url)
        rendered_text = (rendered_home.get("text") or "").strip()
        if not rendered_text and rendered_home.get("html"):
            rendered_text = _catalog_visible_text(rendered_home["html"])
        rendered_score = _catalog_offer_score(rendered_text)
        if rendered_text and (
            _catalog_has_concrete_offer_signal(rendered_text)
            or rendered_score > home_score
            or (rendered_score >= _CATALOG_MIN_SCORE and len(rendered_text) > len(home_text))
            or not home_text
        ):
            home_text, home_score = rendered_text, rendered_score

    candidate_sources = [home_html]
    if rendered_home.get("html"):
        candidate_sources.append(rendered_home["html"])
    candidates = _catalog_page_candidates(home_url, candidate_sources, city)
    selected = candidates[:3]
    pages: List[Dict[str, Any]] = []
    result["pages_scanned"] = 1
    if home_score >= _CATALOG_MIN_SCORE and home_text:
        pages.append({
            "url": home_url, "label": "Página inicial", "text": home_text,
            "score": home_score, "is_location": False,
        })

    page_errors: List[str] = []
    for candidate in selected:
        try:
            page_response = _catalog_http_get(
                _hx, candidate["url"], timeout=18.0, headers=ua, allowed_host=_catalog_host(home_url),
            )
            result["pages_scanned"] += 1
            status_code = int(getattr(page_response, "status_code", 200) or 200)
            content_type = str((getattr(page_response, "headers", {}) or {}).get("content-type", "")).lower()
            final_url = str(getattr(page_response, "url", None) or candidate["url"])
            if status_code >= 400 or not _catalog_related_host(final_url, _catalog_host(home_url)):
                continue
            if content_type and "html" not in content_type:
                continue
            page_html = page_response.text or ""
            page_text = _catalog_visible_text(page_html)
            page_score = _catalog_offer_score(page_text)
            if _catalog_should_render(page_text, page_html):
                rendered = _render_catalog_page(final_url)
                rendered_text = (rendered.get("text") or "").strip()
                if not rendered_text and rendered.get("html"):
                    rendered_text = _catalog_visible_text(rendered["html"])
                rendered_score = _catalog_offer_score(rendered_text)
                if rendered_text and (
                    _catalog_has_concrete_offer_signal(rendered_text)
                    or rendered_score > page_score
                    or (rendered_score >= _CATALOG_MIN_SCORE and len(rendered_text) > len(page_text))
                ):
                    page_text, page_score = rendered_text, rendered_score
            if page_text and page_score >= _CATALOG_MIN_SCORE:
                pages.append({
                    "url": final_url,
                    "label": candidate.get("label") or urlparse(final_url).path.strip("/") or "Oferta",
                    "text": page_text,
                    "score": page_score + min(20, candidate["score"] // 10),
                    "is_location": bool(candidate.get("is_location")),
                })
        except Exception as exc:
            page_errors.append(str(exc)[:100])

    if not pages:
        detail = " O site possui seletor de localidade; informe a cidade da empresa." if any(
            item.get("is_location") for item in candidates
        ) else ""
        result["warnings"].append("Nenhuma página oficial com ofertas reais foi encontrada." + detail)
        if page_errors:
            result["warnings"].append("Algumas páginas de oferta não puderam ser abertas.")
        return result

    if not city and any(item.get("is_location") for item in selected):
        result["warnings"].append(
            "O site varia planos por cidade. Como o cadastro não informa uma cidade, as ofertas importadas mantêm a localidade da fonte."
        )

    # Most relevant offer pages go first, so navigation/footer copy can never consume the prompt.
    corpus_parts: List[str] = []
    source_context: Dict[str, Dict[str, Any]] = {}
    remaining = 22000
    seen_texts = set()
    for page in sorted(pages, key=lambda item: -item["score"]):
        text_key = _catalog_fold(page["text"][:7000])
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        header = f"\n### FONTE OFICIAL\nURL: {page['url']}\nLOCALIDADE/CONTEXTO: {page['label']}\n"
        body = page["text"][:7000]
        if len(body) < 80:
            continue
        if remaining < len(header) + 80:
            break
        chunk = (header + body)[:remaining]
        corpus_parts.append(chunk)
        result["source_pages"].append(page["url"])
        source_context[page["url"].rstrip("/")] = page
        remaining -= len(chunk)
        if remaining < 500:
            break
    blob = "".join(corpus_parts)
    if not corpus_parts:
        result["warnings"].append("O conteúdo das páginas de oferta foi insuficiente para leitura.")
        return result

    try:
        from ..services.ai import cheap_text_config, get_ai_config, complete_ai, extract_json
        cfg = cheap_text_config(get_ai_config())
        if not cfg:
            result["warnings"].append("A IA de texto não está configurada para importar produtos.")
            return result
        sysm = "Você extrai catálogos de fontes oficiais. Responda SOMENTE JSON válido, em pt-BR, sem inventar dados."
        usr = (
            'Liste somente OFERTAS REAIS e específicas (planos, serviços, produtos ou combos) publicadas nas fontes. '
            'Não transforme o nome/descrição genérica da empresa em produto. Preserve velocidade, itens, benefícios e preço exatos. '
            'Se as fontes forem de cidades diferentes, não misture condições: informe "location" e inclua a localidade no nome. '
            'Use em "source_url" apenas uma URL fornecida abaixo. Formato: '
            '{"products":[{"name":"nome curto e exato","description":"1 frase factual",'
            '"objective":"como posicionar/vender em 1 frase","functions":["velocidade/item/benefício real",...],'
            '"price":"preço publicado ou vazio","location":"cidade/região ou vazio","source_url":"URL da fonte"}]} '
            '(até 12). FONTES:' + blob
        )
        data = extract_json(complete_ai(cfg, sysm, usr, 2400)) or {}
        items = data.get("products") or []
        if not isinstance(items, list):
            items = []
    except Exception as exc:
        result["warnings"].append("A IA não conseguiu interpretar as ofertas do site: " + str(exc)[:160])
        return result

    company_words = set(re.findall(r"[a-z0-9]+", _catalog_fold(company.get("name") or "")))
    generic_words = {
        "plano", "planos", "servico", "servicos", "produto", "produtos", "oferta", "ofertas",
        "internet", "telecom", "telecomunicacoes", "fibra", "optica", "banda", "larga",
        "conexao", "conectividade", "da", "de", "do", "para", "com",
    }
    state_words = _BRAZIL_STATE_CODES

    def _offer_key(name: str) -> str:
        clean = _catalog_fold(name)
        clean = re.sub(r"(\d)\s*(?:mb|mbps|megabits?)\b", r"\1 mega", clean)
        clean = re.sub(r"(\d)\s*(?:gb|gbps|gigabits?)\b", r"\1 giga", clean)
        words = [word for word in re.findall(r"[a-z0-9]+", clean)
                 if word not in company_words and word not in generic_words and word not in state_words]
        return "|".join(sorted(set(words))) or "__generic_company_offer__"

    existing_products = product_list(company_id) or []
    existing_names = {(p.get("name") or "").strip().lower() for p in existing_products}
    existing_keys = {_offer_key(p.get("name") or "") for p in existing_products}
    known_sources = {url.rstrip("/"): url for url in result["source_pages"]}
    rejected_without_source = 0
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        location = str(item.get("location") or "").strip()[:80]
        requested_source = str(item.get("source_url") or "").strip().rstrip("/")
        source_url = known_sources.get(requested_source, "")
        if not source_url and location:
            location_key = re.sub(r"[^a-z0-9]", "", _catalog_fold(location))
            matching_sources = [url for key, url in known_sources.items()
                                if location_key and location_key in re.sub(
                                    r"[^a-z0-9]", "", _catalog_fold((source_context.get(key) or {}).get("label") or "")
                                )]
            if len(matching_sources) == 1:
                source_url = matching_sources[0]
        if not source_url and len(known_sources) == 1:
            source_url = next(iter(known_sources.values()))
        if not source_url:
            rejected_without_source += 1
            continue
        source_page = source_context.get(source_url.rstrip("/")) if source_url else None
        if not location and source_page and source_page.get("is_location"):
            location = str(source_page.get("label") or "").strip()[:80]
        name = raw_name
        if location and not _catalog_name_has_location(name, location):
            name = f"{name} — {location}" if name else location
        offer_key = _offer_key(name)
        # Reject the exact failure mode seen in Rio: company/profile summaries posing as products.
        if not name or _offer_key(raw_name) == "__generic_company_offer__":
            continue
        result["found"] += 1
        if name.lower() in existing_names or offer_key in existing_keys:
            continue
        raw_functions = item.get("functions") or []
        if isinstance(raw_functions, str):
            raw_functions = [raw_functions]
        functions = [str(value).strip() for value in raw_functions if str(value).strip()][:8]
        price = str(item.get("price") or "").strip()
        if price and not any(price.lower() in value.lower() for value in functions):
            functions.append("Preço: " + price)
        if location and not any(location.lower() in value.lower() for value in functions):
            functions.append("Disponibilidade: " + location)
        product_create(company_id, {
            "name": name[:180],
            "description": str(item.get("description") or "").strip(),
            "objective": str(item.get("objective") or "").strip(),
            "functions": functions[:10],
            "website": source_url or None,
        })
        existing_names.add(name.lower())
        existing_keys.add(offer_key)
        result["added"] += 1

    if rejected_without_source:
        result["warnings"].append(
            f"{rejected_without_source} item(ns) sem página oficial identificável foram ignorados."
        )
    if not result["found"]:
        result["warnings"].append("A leitura terminou, mas nenhuma oferta específica e verificável foi identificada.")
    return result


def _ig_fetch_brand(company_id: str, instagram: str) -> Dict[str, int]:
    """Deprecated anonymous scraper kept as a no-op for extension compatibility."""
    return {"logo": 0, "refs": 0, "status": "disabled"}


def _facebook_fetch_logo(company_id: str, facebook: str) -> int:
    """Legacy compatibility: Facebook login pages are never scraped for identity.

    Official Page import belongs to the managed/connected-account path. Prospect
    enrichment relies on the official company website and reviewable uploads.
    """
    return 0


def _research_social_connection(platform: str) -> Optional[Dict[str, Any]]:
    """Resolve a house-owned research connection without borrowing a prospect's auth."""
    configured_connection = ""
    try:
        configured_connection = str(
            (settings_get(key=f"social.research.{platform}_connection_id") or {}).get("value") or ""
        ).strip()
    except Exception:
        configured_connection = ""
    try:
        from ..db_agency import social_connection_get, social_connection_list
        if configured_connection:
            selected = social_connection_get(configured_connection)
            if (selected and str(selected.get("status") or "").lower() in ("active", "connected")
                    and selected.get("composio_connection_id")):
                return selected
        connections = [
            row for row in social_connection_list(platform=platform, include_revoked=False)
            if str(row.get("status") or "").lower() in ("active", "connected")
            and row.get("composio_connection_id")
        ]
    except Exception:
        return None
    configured_brand = ""
    for key in (f"social.research.{platform}_brand_id", "social.research.brand_id"):
        try:
            configured_brand = str((settings_get(key=key) or {}).get("value") or "").strip()
        except Exception:
            configured_brand = ""
        if configured_brand:
            break

    ranked: List[tuple[int, Dict[str, Any]]] = []
    for connection in connections:
        brand_id = str(connection.get("brand_id") or "")
        company = company_get(brand_id) or {}
        stage = str(company.get("lifecycle_stage") or "").lower()
        name_key = _identity_key(company.get("name") or "")
        score = 0
        if configured_brand and brand_id == configured_brand:
            score += 100
        if stage == "internal":
            score += 60
        if "cariap" in name_key:
            score += 40
        if score:
            ranked.append((score, connection))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _owned_social_connection(company_id: str, platform: str) -> Optional[Dict[str, Any]]:
    try:
        from ..db_agency import social_connection_list
        return next((
            row for row in social_connection_list(brand_id=company_id, platform=platform, include_revoked=False)
            if str(row.get("status") or "").lower() in ("active", "connected")
            and row.get("composio_connection_id")
        ), None)
    except Exception:
        return None


def _download_public_image(url: str, *, max_bytes: int = 12 * 1024 * 1024) -> Optional[bytes]:
    """Download a public image with redirect/size/type guards for enrichment jobs."""
    import httpx
    target = str(url or "").replace("&amp;", "").strip()
    if not _catalog_public_url(target):
        return None
    try:
        with httpx.Client(timeout=httpx.Timeout(22.0, connect=8.0), follow_redirects=False,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostResearch/1.0)"}) as client:
            response = None
            for _ in range(4):
                if not _catalog_public_url(target):
                    return None
                with client.stream("GET", target) as streamed:
                    if streamed.status_code in (301, 302, 303, 307, 308):
                        target = urljoin(target, streamed.headers.get("location") or "")
                        continue
                    length = str(streamed.headers.get("content-length") or "")
                    if length.isdigit() and int(length) > max_bytes:
                        return None
                    body = bytearray()
                    for chunk in streamed.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            return None
                    response = _CatalogResponse(
                        status_code=streamed.status_code,
                        url=str(streamed.url),
                        headers={str(k).lower(): str(v) for k, v in streamed.headers.items()},
                        body=bytes(body),
                    )
                    response.content = bytes(body)
                    break
        if response is None or response.status_code >= 400:
            return None
        content_type = str(response.headers.get("content-type") or "").lower()
        if content_type and not content_type.startswith("image/"):
            return None
        content = response.content
        if not content or len(content) > max_bytes:
            return None
        return content
    except Exception:
        return None


def _save_reference_image(
    company_id: str,
    content: bytes,
    *,
    source: str,
    source_url: str,
    source_key: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Validate, deduplicate and persist a candidate used as visual inspiration."""
    import hashlib
    import io
    from PIL import Image
    if not content or len(content) > 12 * 1024 * 1024:
        return None
    try:
        image = Image.open(io.BytesIO(content))
        if image.width < 240 or image.height < 140 or image.width * image.height > 36_000_000:
            return None
        image.load()
        normalized = image.convert("RGB")
        output = io.BytesIO()
        normalized.save(output, "PNG", optimize=True)
        normalized_bytes = output.getvalue()
    except Exception:
        return None
    digest = hashlib.sha256(normalized_bytes).hexdigest()
    existing = asset_list(company_id, role="brand_reference") or []
    if any(
        (item.get("meta") or {}).get("source_key") == source_key
        or (item.get("meta") or {}).get("sha256") == digest
        for item in existing
    ):
        return None
    subdir = os.path.join(UPLOAD_DIR, company_id, "references")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(subdir, filename)
    temporary = filepath + ".tmp"
    try:
        with open(temporary, "wb") as stream:
            stream.write(normalized_bytes)
        os.replace(temporary, filepath)
    except Exception:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass
        return None
    parsed = urlparse(source_url or "")
    clean_source_url = parsed._replace(query="", fragment="").geturl()[:500]
    meta = {
        "role": "brand_reference",
        "source_key": source_key[:500],
        "source_url": clean_source_url,
        "sha256": digest,
        "owner_scope": "prospect_or_client",
        "rights_basis": "public_brand_research",
        "allowed_use": "analysis_only",
        "review_status": "candidate_needs_review",
        **(metadata or {}),
    }
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/references/{filename}"
    return asset_create(company_id, {"kind": "IMAGE", "source": source, "url": url, "meta": meta})


def _save_logo_candidate(
    company_id: str,
    content: bytes,
    *,
    source: str,
    source_url: str,
    source_key: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a social avatar as a reviewable logo candidate, never as primary."""
    import hashlib
    import io
    from PIL import Image
    if not content or len(content) > 12 * 1024 * 1024:
        return None
    try:
        image = Image.open(io.BytesIO(content))
        if image.width < 64 or image.height < 64 or image.width * image.height > 36_000_000:
            return None
        image.load()
        normalized = image.convert("RGBA")
        output = io.BytesIO(); normalized.save(output, "PNG", optimize=True)
        normalized_bytes = output.getvalue()
    except Exception:
        return None
    digest = hashlib.sha256(normalized_bytes).hexdigest()
    existing = asset_list_logos(company_id) or []
    if any(
        (item.get("meta") or {}).get("source_key") == source_key
        or (item.get("meta") or {}).get("sha256") == digest
        for item in existing
    ):
        return None
    subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(subdir, filename)
    temporary = filepath + ".tmp"
    try:
        with open(temporary, "wb") as stream:
            stream.write(normalized_bytes)
        os.replace(temporary, filepath)
    except Exception:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass
        return None
    parsed = urlparse(source_url or "")
    meta = {
        "role": "logo", "is_primary": False, "identity_scope": "company",
        "source_key": source_key[:500], "source_url": parsed._replace(query="", fragment="").geturl()[:500],
        "sha256": digest, "review_status": "candidate_needs_review",
        **(metadata or {}),
    }
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
    return asset_create(company_id, {"kind": "IMAGE", "source": source, "url": url, "meta": meta})


def _auto_fetch_site_references(company_id: str, website: str, limit: int = 3) -> Dict[str, Any]:
    """Collect public campaign/hero imagery from the official site, never from Meta scraping."""
    import httpx
    company = company_get(company_id) or {}
    base = website if str(website or "").startswith(("http://", "https://")) else "https://" + str(website or "").strip()
    if not base or not _catalog_public_url(base):
        return {"status": "not_available", "added": 0, "reason": "invalid_website"}
    try:
        response = _catalog_http_get(
            httpx, base, timeout=22.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostResearch/1.0)"},
        )
        if response.status_code >= 400 or not _catalog_public_url(str(response.url)):
            return {"status": "not_available", "added": 0, "reason": "website_unavailable"}
    except Exception:
        return {"status": "temporarily_unavailable", "added": 0, "reason": "website_unavailable"}
    parser = _ImageCandidateParser()
    try:
        parser.feed(response.text or "")
    except Exception:
        pass
    if len(parser.images) < 3 or _catalog_should_render(
        _catalog_visible_text(response.text or ""), response.text or "",
    ):
        try:
            rendered = _render_site(str(response.url)) or {}
            if rendered.get("html"):
                parser.feed(rendered["html"])
        except Exception:
            pass
    company_key = _identity_key(company.get("name") or "")
    ranked: List[tuple[int, str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(parser.images):
        kind = item.get("kind") or "img"
        absolute = urljoin(str(response.url), item.get("src") or "")
        if absolute in seen or not _catalog_public_url(absolute):
            continue
        seen.add(absolute)
        hay = _catalog_fold(" ".join((item.get("attrs") or "", urlparse(absolute).path, kind)))
        if kind in ("site-icon", "og:logo") or "logo" in hay:
            continue
        if any(term in hay for term in ("avatar", "icon", "sprite", "payment", "parceiro", "partner")):
            continue
        score = max(0, 20 - index)
        if kind in ("og:image", "twitter:image", "twitter:image:src"):
            score += 80
        if any(term in hay for term in ("hero", "banner", "campaign", "campanha", "offer", "oferta", "promo", "planos")):
            score += 55
        if company_key and company_key in _identity_key(hay):
            score += 15
        ranked.append((score, absolute, kind))
    ranked.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for score, image_url, kind in ranked:
        if added >= max(1, min(int(limit or 3), 5)):
            break
        if score < 35:
            continue
        content = _download_public_image(image_url)
        if content and _save_reference_image(
            company_id, content, source="WEB", source_url=image_url,
            source_key="website:" + urlparse(image_url)._replace(query="", fragment="").geturl(),
            metadata={"from": "official_site", "kind": kind, "confidence": min(1.0, score / 100.0)},
        ):
            added += 1
    return {"status": "added" if added else "not_available", "added": added,
            "reason": "" if added else "no_campaign_images"}


def _instagram_research_import(
    company_id: str, handle: str, kind: str = "reference", count: int = 4,
) -> Dict[str, Any]:
    """Import through a CARIAP-owned official Meta connection; the target never logs in."""
    import asyncio
    handle = _instagram_handle(handle)
    if not handle:
        return {"status": "action_required", "reason": "invalid_handle", "logo": 0, "refs": 0}
    company = company_get(company_id) or {}
    lifecycle = str(company.get("lifecycle_stage") or "managed").lower()
    own_connection = (
        _owned_social_connection(company_id, "instagram")
        if kind == "own" and lifecycle in ("managed", "internal") else None
    )
    # Public Business Discovery requires Facebook Login. The authorization is
    # the CARIAP research Page, never an Instagram login from the prospect.
    connection = own_connection or _research_social_connection("facebook")
    if not connection:
        return {
            "status": "action_required", "reason": "research_connection_missing",
            "detail": "Conecte uma Página Facebook da CARIAP, com Instagram profissional vinculado, para pesquisa oficial.",
            "handle": handle, "logo": 0, "refs": 0,
        }
    try:
        from ..social.composio_provider import ComposioSocialProvider
        provider = ComposioSocialProvider()
        if own_connection:
            profile = asyncio.run(provider.get_owned_instagram_profile_media(
                connection=connection, media_limit=count,
            ))
            connected_handle = _instagram_handle(profile.get("username") or "")
            if connected_handle and connected_handle.lower() != handle.lower():
                return {
                    "status": "action_required", "reason": "connected_account_mismatch",
                    "detail": f"A conta conectada é @{connected_handle}, mas a empresa informa @{handle}.",
                    "handle": handle, "logo": 0, "refs": 0,
                }
        else:
            profile = asyncio.run(provider.discover_instagram_business(
                handle=handle, connection=connection, media_limit=count,
            ))
    except Exception as exc:
        detail = getattr(exc, "detail", None) or {}
        return {
            "status": "not_available",
            "reason": detail.get("reason") or "official_discovery_unavailable",
            "detail": str(getattr(exc, "message", exc))[:240],
            "handle": handle, "logo": 0, "refs": 0,
        }
    rights_basis = "owned_connected_account" if own_connection else "official_meta_api"
    owner_scope = "own" if own_connection else "prospect"
    allowed_use = "production" if own_connection else "analysis_only"
    result = {
        "status": "already_current", "reason": "", "handle": handle, "logo": 0, "refs": 0,
        "mode": "owned" if own_connection else "business_discovery",
    }
    account_id = str(profile.get("id") or handle)
    if kind == "own" and profile.get("profile_picture_url"):
        content = _download_public_image(profile["profile_picture_url"])
        if content and _save_logo_candidate(
            company_id, content, source="INSTAGRAM",
            source_url=f"https://instagram.com/{handle}/",
            source_key=f"instagram:{account_id}:profile",
            metadata={
                "from": f"instagram:@{handle}", "external_id": account_id,
                "confidence": 0.9, "rights_basis": rights_basis,
                "owner_scope": owner_scope, "allowed_use": allowed_use,
            },
        ):
            result["logo"] = 1
    for item in profile.get("media") or []:
        media_url = item.get("media_url") if item.get("media_type") == "IMAGE" else item.get("thumbnail_url")
        media_id = str(item.get("id") or "")
        if not media_url or not media_id:
            continue
        content = _download_public_image(media_url)
        if content and _save_reference_image(
            company_id, content, source="INSTAGRAM", source_url=item.get("permalink") or media_url,
            source_key=f"instagram:{account_id}:{media_id}",
            metadata={
                "from": f"instagram:@{handle}", "kind": kind, "external_id": media_id,
                "permalink": str(item.get("permalink") or "")[:500], "confidence": 1.0,
                "rights_basis": rights_basis, "review_status": "candidate_needs_review",
                "owner_scope": owner_scope, "allowed_use": allowed_use,
            },
        ):
            result["refs"] += 1
    if result["logo"] or result["refs"]:
        result["status"] = "added"
    return result


def _facebook_research_import(
    company_id: str, facebook: str, count: int = 4,
) -> Dict[str, Any]:
    """Import a Page through official Facebook tools using a house-owned connection."""
    import asyncio
    company = company_get(company_id) or {}
    lifecycle = str(company.get("lifecycle_stage") or "managed").lower()
    own_connection = (_owned_social_connection(company_id, "facebook")
                      if lifecycle in ("managed", "internal") else None)
    connection = own_connection or _research_social_connection("facebook")
    if not connection:
        return {
            "status": "action_required", "reason": "research_connection_missing",
            "detail": "Conecte a Página Facebook da CARIAP para pesquisar Páginas oficiais sem login do prospecto.",
            "logo": 0, "refs": 0,
        }
    provider = None
    try:
        from ..social.composio_provider import ComposioSocialProvider
        provider = ComposioSocialProvider()
        profile = asyncio.run(provider.discover_facebook_page(
            company_name=company.get("name") or "", facebook=facebook,
            website=company.get("website") or "", connection=connection,
            photo_limit=count,
        ))
    except Exception as exc:
        detail = getattr(exc, "detail", None) or {}
        return {
            "status": "not_available",
            "reason": detail.get("reason") or "official_page_unavailable",
            "detail": str(getattr(exc, "message", exc))[:240],
            "logo": 0, "refs": 0,
        }
    page_id = str(profile.get("id") or "")
    ownership_verified = False
    if own_connection and page_id and provider is not None:
        try:
            probe = asyncio.run(provider.test_connection(
                platform="facebook", connection=own_connection, selected_page_id=page_id,
            ))
            selected_page = probe.get("selected_page") if isinstance(probe, dict) else None
            ownership_verified = bool(
                isinstance(selected_page, dict)
                and str(selected_page.get("id") or "") == page_id
            )
        except Exception:
            # A conexão do cliente pode pesquisar páginas públicas, mas isso não
            # prova que a página encontrada é administrada por ele. Nesse caso a
            # importação continua apenas como candidata de pesquisa/revisão.
            ownership_verified = False
    rights_basis = "owned_connected_account" if ownership_verified else "official_meta_api"
    owner_scope = "own" if ownership_verified else "prospect"
    allowed_use = "production" if ownership_verified else "analysis_only"
    result = {
        "status": "already_current", "reason": "", "page_id": page_id,
        "logo": 0, "refs": 0, "mode": "owned" if ownership_verified else "page_discovery",
        "ownership_verified": ownership_verified,
    }
    picture_url = str(profile.get("profile_picture_url") or "")
    picture = _download_public_image(picture_url) if picture_url else None
    if picture and _save_logo_candidate(
        company_id, picture, source="FACEBOOK",
        source_url=profile.get("link") or facebook,
        source_key=f"facebook:{page_id}:profile",
        metadata={
            "from": "facebook_page", "external_id": page_id, "confidence": 0.9,
            "rights_basis": rights_basis, "owner_scope": owner_scope, "allowed_use": allowed_use,
            "managed_page_verified": ownership_verified,
        },
    ):
        result["logo"] = 1
    candidates = []
    if profile.get("cover_url"):
        candidates.append({
            "id": "cover", "media_url": profile["cover_url"],
            "link": profile.get("link") or facebook, "kind": "cover",
        })
    candidates.extend(profile.get("photos") or [])
    for item in candidates[:max(1, min(int(count or 4), 8))]:
        media_id = str(item.get("id") or "")
        media_url = str(item.get("media_url") or "")
        if not media_id or not media_url:
            continue
        content = _download_public_image(media_url)
        if content and _save_reference_image(
            company_id, content, source="FACEBOOK",
            source_url=item.get("link") or profile.get("link") or facebook,
            source_key=f"facebook:{page_id}:{media_id}",
            metadata={
                "from": "facebook_page", "kind": item.get("kind") or "photo",
                "external_id": media_id, "confidence": 1.0,
                "rights_basis": rights_basis, "review_status": "candidate_needs_review",
                "owner_scope": owner_scope, "allowed_use": allowed_use,
                "managed_page_verified": ownership_verified,
            },
        ):
            result["refs"] += 1
    if result["logo"] or result["refs"]:
        result["status"] = "added"
    return result


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
        with _hx.Client() as client:
            r = _catalog_http_get(
                client, base, timeout=20.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CaripostBot/1.0)"},
            )
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
            content = _download_public_image(candidate["url"], max_bytes=10 * 1024 * 1024)
            if not content:
                continue
            variant = "site_icon" if candidate.get("kind") == "site-icon" else "site_logo"
            _save_image(content, origin=candidate["url"], variant=variant,
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



def _ig_import(company_id: str, handle: str, kind: str = "reference", count: int = 4) -> Dict[str, Any]:
    """Compatibility wrapper for the official, house-authorized research path."""
    return _instagram_research_import(company_id, _instagram_handle(handle), kind, count)


@router.post("/{company_id}/import-instagram")
async def import_instagram(company_id: str, request: Request):
    """Importa identidade/referências do Instagram: {handle, kind: 'own'|'reference', count}.
    'own' = o Instagram DO cliente (identidade); 'reference' = perfil que ele admira (família de estilo)."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    if res.get("status") in ("action_required", "not_available"):
        return JSONResponse({
            "detail": res.get("detail") or "Este perfil não está disponível pela pesquisa oficial da Meta.",
            "reason": res.get("reason") or "not_available",
            "fallbacks": ["site_official", "upload_manual"],
        }, status_code=422)
    if res.get("refs"):
        _spawn_reference_analysis(company_id)
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

    source_results: Dict[str, Any] = {
        "website": {"status": "not_applicable", "references_added": 0},
        "instagram": {"status": "not_applicable", "logo": 0, "refs": 0},
        "facebook": {"status": "not_applicable", "logo": 0, "refs": 0},
    }
    references_added = 0
    if website:
        try:
            site_references = _auto_fetch_site_references(company_id, website, 3)
            references_added += int(site_references.get("added") or 0)
            source_results["website"] = {
                "status": site_references.get("status") or "not_available",
                "references_added": int(site_references.get("added") or 0),
                "reason": site_references.get("reason") or "",
            }
        except Exception as exc:
            source_results["website"] = {
                "status": "temporarily_unavailable", "references_added": 0,
                "reason": "reference_import_failed", "detail": str(exc)[:160],
            }

    instagram_stats: Dict[str, Any] = {"status": "not_applicable", "logo": 0, "refs": 0}
    if instagram:
        try:
            instagram_stats = _ig_import(company_id, instagram, "own", 4)
            references_added += int(instagram_stats.get("refs") or 0)
            source_results["instagram"] = dict(instagram_stats)
        except Exception as exc:
            instagram_stats = {
                "status": "temporarily_unavailable", "reason": "official_discovery_failed",
                "detail": str(exc)[:180], "logo": 0, "refs": 0,
            }
            source_results["instagram"] = dict(instagram_stats)
    facebook_stats: Dict[str, Any] = {"status": "not_applicable", "logo": 0, "refs": 0}
    if facebook:
        try:
            facebook_stats = _facebook_research_import(company_id, facebook, 4)
            references_added += int(facebook_stats.get("refs") or 0)
            source_results["facebook"] = dict(facebook_stats)
        except Exception as exc:
            facebook_stats = {
                "status": "temporarily_unavailable", "reason": "official_page_discovery_failed",
                "detail": str(exc)[:180], "logo": 0, "refs": 0,
            }
            source_results["facebook"] = dict(facebook_stats)
    facebook_logo = int(facebook_stats.get("logo") or 0)
    if references_added:
        _spawn_reference_analysis(company_id)

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
    products_found = 0
    product_pages_scanned = 0
    if website:
        try:
            product_result = _auto_extract_products(company_id, website)
            if isinstance(product_result, dict):
                products_added = int(product_result.get("added") or 0)
                products_found = int(product_result.get("found") or 0)
                product_pages_scanned = int(product_result.get("pages_scanned") or 0)
                for product_warning in product_result.get("warnings") or []:
                    warning = "Produtos e serviços: " + str(product_warning)[:220]
                    if warning not in warnings:
                        warnings.append(warning)
            else:
                # Compatibility with older mocks/extensions that returned only the added count.
                products_added = int(product_result or 0)
                products_found = products_added
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
    reference_assets = asset_list(company_id, role="brand_reference") or []
    if not isinstance(reference_assets, (list, tuple)):
        reference_assets = []
    references_total = len(reference_assets)
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
        products_found=products_found,
        product_pages_scanned=product_pages_scanned,
        references_total=references_total,
        sources=source_results,
        palette_preserved=bool(palette_is_manual and not replace_manual),
        warnings=warnings,
        error="",
    )
    return {
        "company": company_get(company_id), "extracted": data,
        "products_added": products_added, "products_found": products_found,
        "product_pages_scanned": product_pages_scanned, "instagram": instagram_stats,
        "facebook_logo": facebook_logo, "logos_added": logos_added,
        "logos_total": len(after_logos), "colors": final_colors,
        "references_total": references_total,
        "sources": source_results,
        "warnings": warnings, "enrichment": final_status,
    }


@router.post("/{company_id}/enrich")
async def enrich_company(company_id: str, request: Request):
    """Backward-compatible synchronous enrichment; the OS uses the observable background endpoint."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"enrichment": _enrichment_status(company_id)}


@router.post("/{company_id}/logo")
async def upload_logo(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
def _record_belongs_to_company(record: Optional[Dict[str, Any]], company_id: str) -> bool:
    return bool(record and str(record.get("company_id") or "") == str(company_id or ""))


def _asset_belongs_to_entity(
    asset: Optional[Dict[str, Any]], company_id: str, *, kind: str, meta_key: str, entity_id: str,
) -> bool:
    meta = (asset or {}).get("meta") or {}
    return bool(
        asset
        and str(asset.get("company_id") or "") == str(company_id or "")
        and str(asset.get("kind") or "") == kind
        and str(meta.get(meta_key) or "") == str(entity_id or "")
    )


@router.get("/{company_id}/influencer-companies")
def list_infcompanies(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_list
    return {"companies": infcompany_list(company_id)}


@router.post("/{company_id}/influencer-companies")
async def create_infcompany(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_get, infcompany_update
    current = infcompany_get(infco_id)
    if not _record_belongs_to_company(current, company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
    body = await request.json()
    o = infcompany_update(infco_id, body)
    return o or JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)


@router.delete("/{company_id}/influencer-companies/{infco_id}")
def delete_infcompany(company_id: str, infco_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_delete, infcompany_get
    if not _record_belongs_to_company(infcompany_get(infco_id), company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
    return {"ok": infcompany_delete(infco_id)}


@router.post("/{company_id}/influencer-companies/{infco_id}/logo")
async def upload_infcompany_logo(company_id: str, infco_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_get
    if not _record_belongs_to_company(infcompany_get(infco_id), company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_get
    if not _record_belongs_to_company(infcompany_get(infco_id), company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
    asset = asset_get(asset_id)
    if not _asset_belongs_to_entity(
        asset, company_id, kind="INFCOMPANY_LOGO", meta_key="infcompany_id", entity_id=infco_id,
    ):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.get("/{company_id}/influencers")
def list_influencers(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import influencer_list
    return {"influencers": influencer_list(company_id)}


@router.post("/{company_id}/influencers")
async def create_influencer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do influencer é obrigatório"}, status_code=422)
    from ..db_companies import infcompany_get, influencer_create
    infcompany_id = str(body.get("infcompany_id") or "").strip()
    if infcompany_id and not _record_belongs_to_company(infcompany_get(infcompany_id), company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
    return influencer_create(company_id, body)


@router.put("/{company_id}/influencers/{inf_id}")
async def update_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import infcompany_get, influencer_get, influencer_update
    current = influencer_get(inf_id)
    if not _record_belongs_to_company(current, company_id):
        return JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)
    body = await request.json()
    infcompany_id = str(body.get("infcompany_id") or "").strip()
    if infcompany_id and not _record_belongs_to_company(infcompany_get(infcompany_id), company_id):
        return JSONResponse({"detail": "Empresa influencer não encontrada"}, status_code=404)
    inf = influencer_update(inf_id, body)
    return inf or JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)


@router.delete("/{company_id}/influencers/{inf_id}")
def delete_influencer(company_id: str, inf_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import influencer_delete, influencer_get
    if not _record_belongs_to_company(influencer_get(inf_id), company_id):
        return JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)
    return {"ok": influencer_delete(inf_id)}


@router.post("/{company_id}/influencers/{inf_id}/photo")
async def upload_influencer_photo(company_id: str, inf_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import influencer_get
    if not _record_belongs_to_company(influencer_get(inf_id), company_id):
        return JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import influencer_get
    if not _record_belongs_to_company(influencer_get(inf_id), company_id):
        return JSONResponse({"detail": "Influencer não encontrado"}, status_code=404)
    asset = asset_get(asset_id)
    if not _asset_belongs_to_entity(
        asset, company_id, kind="INFLUENCER_PHOTO", meta_key="influencer_id", entity_id=inf_id,
    ):
        return JSONResponse({"detail": "Foto não encontrada"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import organizer_list
    return {"organizers": organizer_list(company_id)}


@router.post("/{company_id}/event-organizers")
async def create_organizer(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import organizer_get, organizer_update
    current = organizer_get(org_id)
    if not _record_belongs_to_company(current, company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
    body = await request.json()
    o = organizer_update(org_id, body)
    return o or JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)


@router.delete("/{company_id}/event-organizers/{org_id}")
def delete_organizer(company_id: str, org_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import organizer_delete, organizer_get
    if not _record_belongs_to_company(organizer_get(org_id), company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
    return {"ok": organizer_delete(org_id)}


@router.post("/{company_id}/event-organizers/{org_id}/logo")
async def upload_organizer_logo(company_id: str, org_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import organizer_get
    if not _record_belongs_to_company(organizer_get(org_id), company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import organizer_get
    if not _record_belongs_to_company(organizer_get(org_id), company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
    asset = asset_get(asset_id)
    if not _asset_belongs_to_entity(
        asset, company_id, kind="ORGANIZER_LOGO", meta_key="organizer_id", entity_id=org_id,
    ):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_list
    return {"events": event_list(company_id)}


@router.post("/{company_id}/events")
async def create_event(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    body = await request.json()
    if not (body.get("name") or "").strip():
        return JSONResponse({"detail": "Nome do evento é obrigatório"}, status_code=422)
    from ..db_companies import event_create, organizer_get
    organizer_id = str(body.get("organizer_id") or "").strip()
    if organizer_id and not _record_belongs_to_company(organizer_get(organizer_id), company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
    return event_create(company_id, body)


@router.put("/{company_id}/events/{event_id}")
async def update_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_get, event_update, organizer_get
    current = event_get(event_id)
    if not _record_belongs_to_company(current, company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
    body = await request.json()
    organizer_id = str(body.get("organizer_id") or "").strip()
    if organizer_id and not _record_belongs_to_company(organizer_get(organizer_id), company_id):
        return JSONResponse({"detail": "Organizador não encontrado"}, status_code=404)
    ev = event_update(event_id, body)
    return ev or JSONResponse({"detail": "Evento não encontrado"}, status_code=404)


@router.delete("/{company_id}/events/{event_id}")
def delete_event(company_id: str, event_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_delete, event_get
    if not _record_belongs_to_company(event_get(event_id), company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
    return {"ok": event_delete(event_id)}


@router.post("/{company_id}/events/{event_id}/logo")
async def upload_event_logo(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_get
    if not _record_belongs_to_company(event_get(event_id), company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_get
    if not _record_belongs_to_company(event_get(event_id), company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
    asset = asset_get(asset_id)
    if not _asset_belongs_to_entity(
        asset, company_id, kind="EVENT_LOGO", meta_key="event_id", entity_id=event_id,
    ):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


@router.post("/{company_id}/events/{event_id}/image")
async def upload_event_image(company_id: str, event_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_get
    if not _record_belongs_to_company(event_get(event_id), company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    from ..db_companies import event_get
    if not _record_belongs_to_company(event_get(event_id), company_id):
        return JSONResponse({"detail": "Evento não encontrado"}, status_code=404)
    asset = asset_get(asset_id)
    if not _asset_belongs_to_entity(
        asset, company_id, kind="EVENT_IMAGE", meta_key="event_id", entity_id=event_id,
    ):
        return JSONResponse({"detail": "Imagem não encontrada"}, status_code=404)
    from ..db_companies import asset_delete
    return {"ok": asset_delete(asset_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Reference images (mood board)
# ─────────────────────────────────────────────────────────────────────────────

def _approved_references(company_id: str) -> List[Dict[str, Any]]:
    refs = asset_list(company_id, role="brand_reference") or []
    return [
        ref for ref in refs
        if (ref.get("meta") or {}).get("review_status") == "approved"
        or (
            not (ref.get("meta") or {}).get("review_status")
            and ref.get("source") == "UPLOADED"
        )
    ]


def _reference_analysis_state(
    company_id: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """Return the exact approved-reference snapshot consumed by one analysis run."""
    import hashlib
    import json

    approved = _approved_references(company_id)
    selected = approved[:8]
    snapshot = {
        "reference_count": len(approved),
        "items": [
            {
                "id": str(ref.get("id") or ""),
                "url": str(ref.get("url") or ""),
                "sha256": str((ref.get("meta") or {}).get("sha256") or ""),
                "source_key": str((ref.get("meta") or {}).get("source_key") or ""),
            }
            for ref in selected
        ],
    }
    snapshot_key = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return selected, snapshot, snapshot_key


def _reference_profile_is_current(company_id: str, run_id: str, revision: int) -> bool:
    profile = (((brand_kit_get(company_id) or {}).get("extras") or {}).get("reference_profile") or {})
    try:
        current_revision = int(profile.get("revision") or 0)
    except (TypeError, ValueError):
        current_revision = 0
    return str(profile.get("run_id") or "") == str(run_id or "") and current_revision == int(revision or 0)


def _store_reference_profile_if_current(
    company_id: str, run_id: str, revision: int, profile: Dict[str, Any],
) -> bool:
    """Cross-process compare-and-set: a stale visual analysis can never win."""
    import json

    try:
        from ..db import get_conn
        with get_conn() as conn:
            current = conn.execute(
                "SELECT 1 FROM brand_kits WHERE company_id = ?",
                (company_id,),
            ).fetchone()
            if current:
                cursor = conn.execute(
                    """
                    UPDATE brand_kits
                    SET extras = json_set(
                            CASE WHEN json_valid(extras) THEN extras ELSE '{}' END,
                            '$.reference_profile', json(?)
                        ),
                        updated_at = ?
                    WHERE company_id = ?
                      AND COALESCE(json_extract(extras, '$.reference_profile.run_id'), '') = ?
                      AND COALESCE(CAST(json_extract(
                            extras, '$.reference_profile.revision'
                          ) AS INTEGER), 0) = ?
                    """,
                    (json.dumps(profile), _now(), company_id, run_id, int(revision or 0)),
                )
                return cursor.rowcount > 0
    except Exception:
        # Unit-test adapters and old extension hosts may not expose get_conn. The
        # in-process guard still preserves the same compare-and-set semantics.
        pass

    with _REFERENCE_ANALYSIS_GUARD:
        if not _reference_profile_is_current(company_id, run_id, revision):
            return False
        brand_kit_extras_patch(company_id, {"reference_profile": profile})
        return True


def _refresh_reference_profile(
    company_id: str,
    *,
    run_id: str = "",
    revision: int = 0,
    snapshot: Optional[Dict[str, Any]] = None,
    snapshot_key: str = "",
    refs: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Turn reference art into reusable visual direction without replacing official brand identity."""
    if refs is None or snapshot is None or not snapshot_key:
        refs, snapshot, snapshot_key = _reference_analysis_state(company_id)
    refs = list(refs or [])[:8]
    snapshot = dict(snapshot or {})
    if run_id and not _reference_profile_is_current(company_id, run_id, revision):
        return False
    profile: Dict[str, Any] = {
        "status": "ready",
        "analyzed_at": _now(),
        "reference_count": int(snapshot.get("reference_count") or len(refs)),
        "run_id": run_id,
        "revision": int(revision or 0),
        "snapshot": snapshot,
        "snapshot_key": snapshot_key,
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
    if run_id:
        return _store_reference_profile_if_current(company_id, run_id, revision, profile)
    brand_kit_extras_patch(company_id, {"reference_profile": profile})
    return True


def _reference_analysis_worker(
    company_id: str,
    run_id: str,
    revision: int,
    snapshot: Dict[str, Any],
    snapshot_key: str,
    refs: List[Dict[str, Any]],
) -> None:
    try:
        _refresh_reference_profile(
            company_id, run_id=run_id, revision=revision,
            snapshot=snapshot, snapshot_key=snapshot_key, refs=refs,
        )
    except Exception as exc:
        failed = {
            "status": "failed", "failed_at": _now(),
            "reference_count": int(snapshot.get("reference_count") or len(refs)),
            "run_id": run_id, "revision": revision,
            "snapshot": snapshot, "snapshot_key": snapshot_key,
            "analysis_note": ("análise visual indisponível: " + str(exc))[:300],
        }
        _store_reference_profile_if_current(company_id, run_id, revision, failed)


def _spawn_reference_analysis(company_id: str) -> Dict[str, Any]:
    refs, snapshot, snapshot_key = _reference_analysis_state(company_id)
    with _REFERENCE_ANALYSIS_GUARD:
        current = brand_kit_get(company_id) or {}
        extras = dict(current.get("extras") or {})
        previous = dict(extras.get("reference_profile") or {})
        same_snapshot = previous.get("snapshot_key") == snapshot_key
        if same_snapshot and previous.get("status") == "ready":
            return previous
        if same_snapshot and previous.get("status") == "analyzing":
            try:
                started = datetime.fromisoformat(str(previous.get("started_at") or "").replace("Z", "+00:00"))
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - started < timedelta(minutes=15):
                    return previous
            except Exception:
                pass
        try:
            revision = int(previous.get("revision") or 0) + 1
        except (TypeError, ValueError):
            revision = 1
        run_id = uuid.uuid4().hex
        reference_profile = {
            **previous,
            "status": "analyzing",
            "started_at": _now(),
            "run_id": run_id,
            "revision": revision,
            "reference_count": int(snapshot.get("reference_count") or len(refs)),
            "snapshot": snapshot,
            "snapshot_key": snapshot_key,
        }
        brand_kit_extras_patch(company_id, {"reference_profile": reference_profile})

    try:
        threading.Thread(
            target=_reference_analysis_worker,
            args=(company_id, run_id, revision, snapshot, snapshot_key, refs),
            daemon=True,
        ).start()
    except Exception as exc:
        failed = {
            **reference_profile,
            "status": "failed", "failed_at": _now(),
            "analysis_note": ("não foi possível iniciar a análise: " + str(exc))[:300],
        }
        _store_reference_profile_if_current(company_id, run_id, revision, failed)
        return failed
    return reference_profile


@router.get("/{company_id}/references")
def list_references(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    refs = asset_list(company_id, role="brand_reference")
    return {"references": refs}


@router.post("/{company_id}/references")
async def upload_reference(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import hashlib
    content = await file.read(12 * 1024 * 1024 + 1)
    if len(content) > 12 * 1024 * 1024:
        return JSONResponse({"detail": "A referência excede o limite de 12 MB."}, status_code=422)
    source_key = "upload:" + hashlib.sha256(content).hexdigest()
    asset = _save_reference_image(
        company_id, content, source="UPLOADED", source_url="", source_key=source_key,
        metadata={
            "filename": os.path.basename(file.filename or "referencia"),
            "owner_scope": "user_provided", "rights_basis": "user_provided",
            "allowed_use": "visual_reference", "review_status": "approved", "confidence": 1.0,
        },
    )
    if not asset:
        return JSONResponse({
            "detail": "Arquivo inválido, pequeno demais, corrompido ou já cadastrado. Use PNG, JPEG ou WebP.",
        }, status_code=422)
    analysis = _spawn_reference_analysis(company_id)
    return {"reference": asset, "analysis_status": analysis.get("status") or "analyzing"}


@router.post("/{company_id}/references/{asset_id}/review")
async def review_reference(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    try:
        body = await request.json()
    except Exception:
        body = {}
    status = str(body.get("status") or "").strip().lower()
    if status not in ("approved", "rejected"):
        return JSONResponse({"detail": "status deve ser approved ou rejected"}, status_code=422)
    asset = asset_get(asset_id)
    if (not asset or asset.get("company_id") != company_id
            or (asset.get("meta") or {}).get("role") != "brand_reference"):
        return JSONResponse({"detail": "Referência não encontrada"}, status_code=404)
    meta = dict(asset.get("meta") or {})
    if str(meta.get("review_status") or "").strip().lower() == status:
        updated = asset
    else:
        meta.update({
            "review_status": status,
            "reviewed_at": _now(),
            "allowed_use": "visual_reference" if status == "approved" else "none",
        })
        updated = asset_update_meta(asset_id, meta)
    analysis = _spawn_reference_analysis(company_id)
    return {"reference": updated, "analysis_status": analysis.get("status") or "analyzing"}


@router.delete("/{company_id}/references/{asset_id}")
def delete_reference(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    # get asset to find file path
    refs = asset_list(company_id, role="brand_reference")
    ref = next((r for r in refs if r["id"] == asset_id), None)
    if not ref:
        return JSONResponse({"detail": "Referência não encontrada"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    comps = competitor_list(company_id)
    return {"competitors": comps}


@router.post("/{company_id}/competitors")
async def add_competitor(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not any(str(item.get("id")) == str(competitor_id) for item in competitor_list(company_id)):
        return JSONResponse({"detail": "Concorrente não encontrado"}, status_code=404)
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
    from ..main_utils import scoped_company_ids
    allowed = scoped_company_ids(request)
    if allowed is not None:
        comps = [item for item in comps if str(item.get("company_id") or "") in allowed]
    return {"competitors": comps}


# ─────────────────────────────────────────────────────────────────────────────
# Catalog (Grupo → Produto → Plano) + adicionais — content sources
# ─────────────────────────────────────────────────────────────────────────────

def _catalog_group_for_product(product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    group_id = str(product.get("group_id") or "").strip()
    if not group_id:
        return None
    group = product_group_get(group_id)
    if not group or str(group.get("company_id") or "") != str(product.get("company_id") or ""):
        return None
    return group


def _catalog_product_entry(company_id: str, product: Dict[str, Any], *, assets: bool = False) -> Dict[str, Any]:
    """Return one product with its hierarchy while keeping legacy product fields intact."""
    item = dict(product)
    item["group"] = _catalog_group_for_product(item)
    item["plans"] = product_plan_list(str(item.get("id") or ""))
    item["solutions"] = solution_list(str(item.get("id") or ""))
    if assets:
        item["logos"] = asset_list_logos(company_id, str(item.get("id") or ""))
        item["photos"] = asset_list_photos(company_id, str(item.get("id") or ""))
    return item


def _catalog_link_view(link: Dict[str, Any]) -> Dict[str, Any]:
    """Expand a stored client link with names used by the client screen."""
    item = dict(link)
    product = product_get(str(item.get("product_id") or ""))
    plan = product_plan_get(str(item.get("plan_id") or "")) if item.get("plan_id") else None
    source = company_get(str(item.get("source_company_id") or ""))
    group = _catalog_group_for_product(product) if product else None
    wanted = {str(value) for value in (item.get("solution_ids") or []) if str(value)}
    additions = [row for row in (solution_list(str(item.get("product_id") or "")) if product else [])
                 if str(row.get("id") or "") in wanted]
    item.update({
        "source_company_name": (source or {}).get("name") or "",
        "group": group,
        "product": product,
        "plan": plan,
        "solutions": additions,
    })
    return item


def _validated_product_group(company_id: str, raw_group_id: Any):
    group_id = str(raw_group_id or "").strip()
    if not group_id:
        return None, None
    group = product_group_get(group_id)
    if not group or str(group.get("company_id") or "") != str(company_id):
        return None, JSONResponse({"detail": "Grupo de produtos não pertence a esta empresa."}, status_code=422)
    return group_id, None


@router.get("/{company_id}/product-groups")
def list_product_groups(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"groups": product_group_list(company_id)}


@router.post("/{company_id}/product-groups")
async def create_product_group(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    data["name"] = str(data.get("name") or "").strip()
    if not data["name"]:
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    try:
        return {"group": product_group_create(company_id, data)}
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)


@router.put("/{company_id}/product-groups/{group_id}")
async def update_product_group(company_id: str, group_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    group = product_group_get(group_id)
    if not group or str(group.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Grupo de produtos não encontrado"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if "name" in data:
        data["name"] = str(data.get("name") or "").strip()
        if not data["name"]:
            return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    try:
        updated = product_group_update(group_id, data)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    return {"group": updated}


@router.delete("/{company_id}/product-groups/{group_id}")
def delete_product_group(company_id: str, group_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    group = product_group_get(group_id)
    if not group or str(group.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Grupo de produtos não encontrado"}, status_code=404)
    if not product_group_delete(group_id):
        return JSONResponse(
            {"detail": "O grupo possui produtos. Mova os produtos antes de excluir."}, status_code=409,
        )
    return {"deleted": True}


@router.get("/{company_id}/products")
def list_products(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    products = [_catalog_product_entry(company_id, product, assets=True)
                for product in product_list(company_id)]
    return {"products": products}


@router.post("/{company_id}/products")
async def create_product(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not (data.get("name") or "").strip():
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    group_id, group_error = _validated_product_group(company_id, data.get("group_id"))
    if group_error:
        return group_error
    if "group_id" in data:
        data["group_id"] = group_id
    return {"product": product_create(company_id, data)}


@router.get("/{company_id}/products/copy-sources")
def product_copy_sources(company_id: str, request: Request):
    """Lista OUTRAS empresas (as que este usuário enxerga) com seus produtos, pra popular o seletor de
    'copiar produtos de outro cliente'. Respeita o escopo de tenancy (agência só vê as suas)."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    existing_product = product_get(product_id)
    if not existing_product or str(existing_product.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if "group_id" in data:
        group_id, group_error = _validated_product_group(company_id, data.get("group_id"))
        if group_error:
            return group_error
        data["group_id"] = group_id
    product = product_update(product_id, data)
    if not product:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"product": product}


@router.get("/{company_id}/products/{product_id}/plans")
def list_product_plans(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    product = product_get(product_id)
    if not product or str(product.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"plans": product_plan_list(product_id)}


@router.post("/{company_id}/products/{product_id}/plans")
async def create_product_plan(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    product = product_get(product_id)
    if not product or str(product.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    data["name"] = str(data.get("name") or "").strip()
    if not data["name"]:
        return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    try:
        plan = product_plan_create(product_id, data)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    return {"plan": plan}


@router.put("/{company_id}/plans/{plan_id}")
async def update_product_plan(company_id: str, plan_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    plan = product_plan_get(plan_id)
    if not plan or str(plan.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if "name" in data:
        data["name"] = str(data.get("name") or "").strip()
        if not data["name"]:
            return JSONResponse({"detail": "name é obrigatório"}, status_code=422)
    try:
        updated = product_plan_update(plan_id, data)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    return {"plan": updated}


@router.delete("/{company_id}/plans/{plan_id}")
def delete_product_plan(company_id: str, plan_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    plan = product_plan_get(plan_id)
    if not plan or str(plan.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    if catalog_link_references_plan(plan_id):
        return JSONResponse(
            {"detail": "Plano vinculado a cliente. Remova o vínculo antes de excluir."}, status_code=409,
        )
    if not product_plan_delete(plan_id):
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    return {"deleted": True}


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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or prod.get("company_id") != company_id:
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    product_update(product_id, {"knowledge": ""})
    return {"ok": True}


@router.post("/{company_id}/plans/{plan_id}/kb")
async def upload_plan_kb(company_id: str, plan_id: str, request: Request, file: UploadFile = File(...)):
    """BASE DE CONHECIMENTO do plano/subproduto: sobe PDF/TXT/MD, EXTRAI o texto e ACUMULA em plan.knowledge."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    plan = product_plan_get(plan_id)
    if not plan or plan.get("company_id") != company_id:
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    raw = await file.read()
    name = file.filename or "doc.txt"
    import asyncio as _aio
    try:
        text = ((await _aio.to_thread(_extract_doc_text, name, raw)) or "").strip()
    except Exception as e:
        return JSONResponse({"detail": f"Falha ao ler '{name}': {e}"}, status_code=400)
    if not text or len(text) < 20:
        try:
            text = ((await _aio.to_thread(_vision_ocr_doc, name, raw)) or "").strip()
        except Exception:
            text = ""
    if not text:
        return JSONResponse({"detail": f"Não consegui extrair texto de '{name}'. Formatos: PDF, DOCX, TXT, MD, CSV e imagem/PDF escaneado."}, status_code=400)
    prev = (plan.get("knowledge") or "").strip()
    merged = (prev + f"\n\n===== {name} =====\n" + text).strip()[:60000]
    product_plan_update(plan_id, {"knowledge": merged})
    filled = {}
    try:
        need_desc = not (plan.get("description") or "").strip()
        _fns = plan.get("functions") or []
        if isinstance(_fns, str):
            try:
                import json as _j
                _fns = _j.loads(_fns)
            except Exception:
                _fns = [_fns] if _fns.strip() else []
        need_obj = not (plan.get("knowledge") or "").strip()
        need_fns = not _fns
        if need_desc or need_obj or need_fns:
            from ..services.ai import cheap_text_config, get_ai_config, complete_ai, extract_json
            cfg = cheap_text_config(get_ai_config())
            if cfg:
                sysm = "Você extrai dados de um plano/subproduto de um documento. Responda SÓ JSON válido, pt-BR, sem preços."
                usr = (f"Plano: {plan.get('name','')}. Do texto do documento abaixo, extraia: "
                       '{"description":"descrição clara em 1-2 frases","objective":"como VENDER/posicionar este plano '
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
                    product_plan_update(plan_id, upd)
                    filled = upd
    except Exception:
        pass
    return {"ok": True, "file": name, "chars": len(text), "total_chars": len(merged),
            "filled": filled, "plan": product_plan_get(plan_id)}


@router.get("/{company_id}/plans/{plan_id}/kb")
def get_plan_kb(company_id: str, plan_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    plan = product_plan_get(plan_id)
    if not plan or plan.get("company_id") != company_id:
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    kb = (plan.get("knowledge") or "")
    return {"chars": len(kb), "preview": kb[:2000]}


@router.delete("/{company_id}/plans/{plan_id}/kb")
def clear_plan_kb(company_id: str, plan_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    plan = product_plan_get(plan_id)
    if not plan or plan.get("company_id") != company_id:
        return JSONResponse({"detail": "Plano não encontrado"}, status_code=404)
    product_plan_update(plan_id, {"knowledge": ""})
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
            # Avatares descobertos externamente são apenas candidatos. Até a
            # aprovação explícita eles não alteram a paleta oficial da marca.
            if str(meta.get("review_status") or "").strip().lower() in {
                "candidate_needs_review", "rejected",
            }:
                continue
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    if catalog_link_references_product(product_id):
        return JSONResponse(
            {"detail": "Produto vinculado a cliente. Remova o vínculo antes de excluir."}, status_code=409,
        )
    if not product_delete(product_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"deleted": True}


@router.post("/{company_id}/products/{product_id}/logo")
async def upload_product_logo(company_id: str, product_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    asset = asset_get(asset_id)
    if (not asset or str(asset.get("company_id") or "") != str(company_id)
            or str(asset.get("product_id") or "") != str(product_id)):
        return JSONResponse({"detail": "Foto não encontrada"}, status_code=404)
    return {"deleted": asset_delete(asset_id)}


@router.get("/{company_id}/products/{product_id}/solutions")
def list_solutions(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
    return {"solutions": solution_list(product_id)}


@router.post("/{company_id}/products/{product_id}/solutions")
async def create_solution(company_id: str, product_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    prod = product_get(product_id)
    if not prod or str(prod.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Produto não encontrado"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    existing_solution = solution_get(solution_id)
    if not existing_solution or str(existing_solution.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    existing_solution = solution_get(solution_id)
    if not existing_solution or str(existing_solution.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    if catalog_link_references_solution(solution_id):
        return JSONResponse(
            {"detail": "Adicional vinculado a cliente. Remova o vínculo antes de excluir."}, status_code=409,
        )
    if not solution_delete(solution_id):
        return JSONResponse({"detail": "Solução não encontrada"}, status_code=404)
    return {"deleted": True}


@router.get("/{company_id}/catalog-links")
def list_catalog_links(company_id: str, request: Request):
    """List the exact catalog products/plans contracted by this client."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    return {"links": [_catalog_link_view(link) for link in catalog_link_list(company_id)]}


@router.get("/{company_id}/catalog-links/options")
def catalog_link_options(company_id: str, request: Request):
    """Catalogs visible to the operator, nested as group → product → plan/add-on."""
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    from ..main_utils import scoped_company_ids
    scoped = scoped_company_ids(request)
    catalogs = []
    for source in (company_list(active_only=True) or []):
        source_id = str(source.get("id") or "")
        if not source_id or source_id == str(company_id):
            continue
        if scoped is not None and source_id not in scoped:
            continue
        products = [_catalog_product_entry(source_id, product)
                    for product in (product_list(source_id) or []) if product.get("active", True)]
        if not products:
            continue
        catalogs.append({
            "company_id": source_id,
            "company_name": source.get("name") or "",
            "lifecycle_stage": source.get("lifecycle_stage") or "managed",
            "groups": [group for group in product_group_list(source_id) if group.get("active", True)],
            "products": products,
        })
    catalogs.sort(key=lambda item: (
        item.get("lifecycle_stage") != "internal",
        "cariap" not in str(item.get("company_name") or "").lower(),
        str(item.get("company_name") or "").lower(),
    ))
    return {"catalogs": catalogs}


@router.post("/{company_id}/catalog-links")
async def create_catalog_link(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    source_company_id = str(data.get("source_company_id") or "").strip()
    product_id = str(data.get("product_id") or "").strip()
    plan_id = str(data.get("plan_id") or "").strip() or None
    if not source_company_id or not product_id:
        return JSONResponse(
            {"detail": "source_company_id e product_id são obrigatórios."}, status_code=422,
        )
    if source_company_id == str(company_id):
        return JSONResponse({"detail": "Escolha um catálogo diferente do cliente-alvo."}, status_code=422)
    source_denied = _company_scope_required(request, source_company_id)
    if source_denied:
        return source_denied
    product = product_get(product_id)
    if not product or str(product.get("company_id") or "") != source_company_id:
        return JSONResponse({"detail": "Produto não pertence ao catálogo informado."}, status_code=422)
    if plan_id:
        plan = product_plan_get(plan_id)
        if not plan or str(plan.get("product_id") or "") != product_id:
            return JSONResponse({"detail": "Plano não pertence ao produto informado."}, status_code=422)
    raw_solution_ids = data.get("solution_ids") or []
    if not isinstance(raw_solution_ids, list):
        return JSONResponse({"detail": "solution_ids deve ser uma lista."}, status_code=422)
    solution_ids = list(dict.fromkeys(str(value).strip() for value in raw_solution_ids if str(value).strip()))
    if len(solution_ids) > 50:
        return JSONResponse({"detail": "Selecione no máximo 50 adicionais."}, status_code=422)
    valid_solution_ids = {str(row.get("id") or "") for row in solution_list(product_id)}
    if any(solution_id not in valid_solution_ids for solution_id in solution_ids):
        return JSONResponse({"detail": "Um adicional não pertence ao produto informado."}, status_code=422)
    payload = {
        "source_company_id": source_company_id,
        "product_id": product_id,
        "plan_id": plan_id,
        "solution_ids": solution_ids,
        "notes": str(data.get("notes") or "").strip()[:2000],
        "active": bool(data.get("active", True)),
    }
    try:
        link = catalog_link_create(company_id, payload)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    return {"link": _catalog_link_view(link)}


@router.delete("/{company_id}/catalog-links/{link_id}")
def delete_catalog_link(company_id: str, link_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    link = catalog_link_get(link_id)
    if not link or str(link.get("company_id") or "") != str(company_id):
        return JSONResponse({"detail": "Vínculo de catálogo não encontrado"}, status_code=404)
    if not catalog_link_delete(link_id):
        return JSONResponse({"detail": "Vínculo de catálogo não encontrado"}, status_code=404)
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
    eligible = [
        logo for logo in logos
        if str((logo.get("meta") or {}).get("review_status") or "").strip().lower()
        not in {"candidate_needs_review", "rejected"}
    ]
    primary = [logo for logo in eligible if (logo.get("meta") or {}).get("is_primary")]
    kit_url = (brand_kit_get(company_id) or {}).get("logo_url") or ""
    matching = next((logo for logo in eligible if logo.get("url") == kit_url), None)
    if len(primary) == 1 and (not matching or primary[0].get("id") == matching.get("id")):
        return logos
    if not eligible:
        # A descoberta social nunca pode se autopromover por ser a única imagem.
        if any((logo.get("meta") or {}).get("is_primary") for logo in logos):
            asset_clear_primary(company_id)
        if kit_url and any(logo.get("url") == kit_url for logo in logos):
            brand_kit_upsert(company_id, {"logo_url": None})
        return list(asset_list_logos(company_id) or logos)
    chosen = matching or min(eligible, key=_logo_promotion_rank)
    source = None if matching else ("MANUAL" if chosen.get("source") == "UPLOADED" else "AUTO")
    asset_set_primary_logo(company_id, chosen["id"], source)
    return list(asset_list_logos(company_id) or logos)

@router.get("/{company_id}/logos")
def list_logos(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
    asset = asset_get(asset_id)
    meta = (asset or {}).get("meta") or {}
    if (not asset or asset.get("company_id") != company_id or asset.get("product_id") is not None
            or meta.get("role") != "logo"):
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    asset = asset_set_primary_logo(company_id, asset_id, "MANUAL")
    if not asset:
        return JSONResponse({"detail": "Logo não encontrada"}, status_code=404)
    approved_meta = dict(asset.get("meta") or {})
    approved_meta.update({"review_status": "approved", "reviewed_at": _now()})
    asset_update_meta(asset_id, approved_meta)
    asset = asset_get(asset_id) or asset
    return {"logo": asset}


@router.delete("/{company_id}/logos/{asset_id}")
def delete_logo(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    denied = _company_scope_required(request, company_id)
    if denied:
        return denied
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
        eligible = [
            logo for logo in remaining
            if str((logo.get("meta") or {}).get("review_status") or "").strip().lower()
            not in {"candidate_needs_review", "rejected"}
        ]
        if eligible:
            chosen = min(eligible, key=_logo_promotion_rank)
            chosen = asset_set_primary_logo(company_id, chosen["id"], "MANUAL") or chosen
        else:
            asset_clear_primary(company_id)
            brand_kit_upsert(company_id, {"logo_url": None})
    return {"deleted": True, "logos": asset_list_logos(company_id)}
