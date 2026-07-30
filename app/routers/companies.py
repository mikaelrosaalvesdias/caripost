"""
Companies (Clientes) router — CRUD, brand kit, competitors, assets.
Mirrors caripost-web's company management features.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from ..db_companies import (
    company_list, company_get, company_create, company_update, company_delete,
    brand_kit_get, brand_kit_upsert,
    competitor_list, competitor_create, competitor_delete,
    asset_list, asset_create, asset_delete, asset_get, asset_update_meta,
    asset_list_logos, asset_list_photos, asset_clear_primary,
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
    socials: Dict[str, str] = {}
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
    # AUTO-ENRICH no CADASTRO: com site preenchido, o perfil (cores, voz, LOGO, planos) monta SOZINHO em
    # background (~30-60s) — sem caçar botão. Mesmo caminho do botão "Puxar do site/Instagram da empresa".
    if (company.get("website") or "").strip() or any((company.get("socials") or {}).get(k) for k in ("instagram", "facebook")):
        _spawn_bg_enrich(company["id"])
    return {"company": company}


def _spawn_bg_enrich(company_id: str):
    """Dispara o enrich (cores, voz, LOGO, planos) em BACKGROUND — perfil se monta sozinho, sem botão."""
    import threading

    def _bg(cid: str):
        try:
            import httpx as _hx
            _hx.post("http://localhost:8765/api/companies/" + cid + "/enrich",
                     headers={"X-API-Key": os.environ.get("ADULT_META_API_KEY", "")},
                     json={}, timeout=_hx.Timeout(420.0, connect=10.0))
        except Exception:
            pass

    threading.Thread(target=_bg, args=(company_id,), daemon=True).start()


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
    socials = existing.get("socials") or {}
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
    # site ADICIONADO depois do cadastro, com perfil ainda vazio → monta sozinho (mesmo auto do create).
    # Perfil já preenchido não é sobrescrito (curadoria do usuário vale mais que o robô).
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
        data["colors"] = {str(k).strip(): str(v).strip() for k, v in body["colors"].items()
                          if str(k).strip() and str(v).strip()}
    elif colors:
        if existing.get("brand_kit") and existing["brand_kit"].get("colors"):
            merged = existing["brand_kit"]["colors"].copy()
            merged.update(colors)
            colors = merged
        data["colors"] = colors
    for key in ("logo_url", "voice", "persona", "visual_prompt_base", "audience", "assuntos", "client_rules"):
        if key in body:
            data[key] = body[key]
    bk = brand_kit_upsert(company_id, data)
    return {"brand_kit": bk}


@router.get("/{company_id}/creative-config")
def get_creative_config(company_id: str, request: Request):
    """Config criativa do cliente: defaults globais + override atual (nada travado no código)."""
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


def _identity_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", value)


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

    def handle_starttag(self, tag: str, attrs):
        amap = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag == "header":
            self._in_header += 1
        if tag == "nav":
            self._in_nav += 1
        if tag == "img":
            src = amap.get("src") or amap.get("data-src") or amap.get("data-lazy-src") or ""
            if src:
                self.images.append({
                    "src": src,
                    # Do not include src here: the company name in the site's DOMAIN would otherwise
                    # make every product image look like an institutional match.
                    "attrs": " ".join(v for k, v in amap.items()
                                      if k not in ("src", "data-src", "data-lazy-src", "srcset")),
                    "header": "1" if self._in_header else "",
                    "nav": "1" if self._in_nav else "",
                })

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
    seen = set()
    for idx, item in enumerate(parser.images):
        absolute = urljoin(base_url, item["src"].strip())
        if absolute in seen:
            continue
        seen.add(absolute)
        haystack = _identity_key(item["attrs"] + " " + urlparse(absolute).path)
        basename = _identity_key(os.path.basename(urlparse(absolute).path))
        score, reasons = max(0, 18 - idx // 4), []
        if company_key and len(company_key) >= 3 and company_key in haystack:
            score += 80
            reasons.append("company-name")
        if any(mark in haystack for mark in ("customlogo", "sitelogo", "brandlogo", "headerlogo")):
            score += 70
            reasons.append("brand-marker")
        elif "logo" in haystack:
            score += 14
            reasons.append("generic-logo")
        if item["header"] or item["nav"]:
            score += 45
            reasons.append("header-nav")
        if basename in ("logo", "logotipo", company_key) and basename:
            score += 25
        foreign = sorted(x for x in _THIRD_PARTY_BRANDS if x in haystack and x not in company_key)
        if foreign:
            score -= 140
            reasons.append("third-party:" + ",".join(foreign))
        ranked.append({"url": absolute, "score": score, "reasons": reasons, "index": idx})
    ranked.sort(key=lambda x: (-int(x["score"]), int(x["index"])))
    return ranked


def _trusted_company_logo(asset: Dict[str, Any], company_name: str) -> bool:
    meta = asset.get("meta") or {}
    if asset.get("source") in ("UPLOADED", "INSTAGRAM"):
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
            pg.goto(url, timeout=35000, wait_until="networkidle")
            html = pg.content() or ""
            txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            txt = re.sub(r"<[^>]+>", " ", txt)
            out["text"] = re.sub(r"\s+", " ", txt).strip()
            out["html"] = html
            try:
                # <img> de logo OU SVG INLINE em container 'logo' (site sem <img> de logo — ex.: kpsfibra)
                # OU 1º svg do header. Screenshot do ELEMENTO vira PNG transparente.
                for _sel in ("header img, nav img, img.custom-logo, [class*='site-logo' i] img",
                             "img[src*='logo' i], img[alt*='logo' i], img[class*='logo' i]",
                             "a[class*='logo' i], div[class*='logo' i], span[class*='logo' i]",   # CONTAINER (ícone+texto)
                             "[class*='logo' i] svg, svg[class*='logo' i], svg[id*='logo' i]",
                             "header svg, a[href='/'] svg"):
                    el = pg.locator(_sel).first
                    if not el or el.count() == 0:
                        continue
                    try:
                        bb = el.bounding_box() or {}
                        _w, _h = (bb.get("width") or 0), (bb.get("height") or 0)
                        if (_w < 40 and _h < 40) or _w > 720 or _h > 240:
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
    existing = {(p.get("name") or "").strip().lower() for p in (product_list(company_id) or [])}
    added = 0
    for it in items[:12]:
        nm = (it.get("name") or "").strip()
        if not nm or nm.lower() in existing:
            continue
        _fns = [str(f).strip() for f in (it.get("functions") or []) if str(f).strip()][:8]
        if (it.get("price") or "").strip():
            _fns.append("Preço: " + it["price"].strip())
        product_create(company_id, {"name": nm, "description": (it.get("description") or "").strip(),
                                    "objective": (it.get("objective") or "").strip(), "functions": _fns})
        existing.add(nm.lower())
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
    handle = (instagram or "").strip().rstrip("/").split("/")[-1].lstrip("@")
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
                saved_meta.update({"identity_scope": "company", "confidence": 0.95})
            asset_create(company_id, {"kind": kind, "source": "INSTAGRAM", "url": u, "meta": saved_meta})
            if role == "logo" and not (brand_kit_get(company_id) or {}).get("logo_url"):
                brand_kit_upsert(company_id, {"logo_url": u})
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


def _auto_fetch_logo(company_id: str, website: str) -> Optional[str]:
    """Baixa o LOGO do site do cliente (og:image / apple-touch-icon / <img ...logo...>) e cadastra como asset
    primário — pra montagem de perfil vir com logo + cores + identidade já preenchidos. Retorna a URL ou None."""
    import re
    import uuid as _uuid
    import io as _io
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
    ranked = _site_logo_candidates(html, str(r.url), company.get("name") or "")
    # Abaixo deste limiar é mais seguro fotografar o cabeçalho do que promover uma marca de produto.
    cands = [c for c in ranked if c["score"] >= 55]
    seen = set()
    content_seen = set()
    first_url = None
    for candidate in cands:
        u = candidate["url"]
        if u in seen or u.lower().endswith(".svg"):
            continue
        seen.add(u)
        try:
            ir = _hx.get(u, timeout=_hx.Timeout(20.0, connect=10.0), follow_redirects=True)
            if ir.status_code >= 400 or not ir.content:
                continue
            import hashlib
            digest = hashlib.sha256(ir.content).hexdigest()
            if digest in content_seen:
                continue
            content_seen.add(digest)
            im = _Img.open(_io.BytesIO(ir.content))
            if im.width < 64 and im.height < 64:   # só rejeita se AMBAS as dimensões forem minúsculas
                continue                            # (logo horizontal real pode ter só ~40px de altura)
            ext = ".png"
            subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
            os.makedirs(subdir, exist_ok=True)
            filename = f"{_uuid.uuid4().hex}{ext}"
            im.convert("RGBA").save(os.path.join(subdir, filename), "PNG")
            url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
            asset_create(company_id, {"kind": "IMAGE", "source": "WEB", "url": url,
                                      "meta": {"role": "logo", "is_primary": first_url is None, "from": u[:200],
                                               "identity_scope": "company",
                                               "confidence": min(1.0, candidate["score"] / 100.0),
                                               "evidence": candidate["reasons"]}})
            if first_url is None:
                first_url = url
                brand_kit_upsert(company_id, {"logo_url": url})
            if len(content_seen) >= 4:
                break
        except Exception:
            continue
    if first_url:
        return first_url
    # FALLBACK (site JS / logo SVG): Playwright fotografa a logo em 2 VERSÕES — transparente (primária)
    # e no fundo do site — e cadastra as duas como variantes (o Estúdio escolhe a que encaixa na arte).
    try:
        _r2 = _render_site(base)
        subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
        os.makedirs(subdir, exist_ok=True)
        first_url = None
        for _png, _tag in ((_r2.get("logo_png_alpha"), "playwright_alpha"),
                           (_r2.get("logo_png"), "playwright_render")):
            if not _png:
                continue
            try:
                im = _Img.open(_io.BytesIO(_png))
                if im.width < 64 and im.height < 64:
                    continue
                if _tag == "playwright_alpha":                # captura transparente VAZIA (logo era CSS-bg) → pula
                    _a = im.convert("RGBA").getchannel("A")
                    if (sum(1 for px in _a.getdata() if px > 16) / float(im.width * im.height)) < 0.01:
                        continue
                fn = f"{_uuid.uuid4().hex}.png"
                im.convert("RGBA").save(os.path.join(subdir, fn), "PNG")
                url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{fn}"
                asset_create(company_id, {"kind": "IMAGE", "source": "WEB", "url": url,
                                          "meta": {"role": "logo", "is_primary": first_url is None, "from": _tag,
                                                   "identity_scope": "company", "confidence": 0.7}})
                if first_url is None:
                    first_url = url
                    brand_kit_upsert(company_id, {"logo_url": url})
            except Exception:
                continue
        if first_url:
            return first_url
    except Exception:
        pass
    return None



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
    handle = (handle or "").strip().rstrip("/").split("/")[-1].lstrip("@")
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
                saved_meta.update({"identity_scope": "company", "confidence": 0.95})
            asset_create(company_id, {"kind": "IMAGE", "source": "INSTAGRAM", "url": url2, "meta": saved_meta})
            if role == "logo":
                brand_kit_upsert(company_id, {"logo_url": url2})
            return url2
        except Exception:
            return None

    out = {"logo": 0, "refs": 0, "handle": handle}
    if kind == "own" and not (asset_list_logos(company_id) or []):
        pic = u.get("profile_pic_url_hd") or u.get("profile_pic_url")
        if pic and _save_img(pic, "logo", "logo", {"is_primary": True, "from": f"instagram:@{handle}"}):
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


@router.post("/{company_id}/enrich")
async def enrich_company(company_id: str, request: Request):
    """Read the company's site + Instagram and fill Dados Gerais + Voz e Persona
    (tom de voz, persona, público/modelo, base visual) + colors from the logo. No prices."""
    err = _api_key_required(request)
    if err:
        return err
    co = company_get(company_id)
    if not co:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    website = (body.get("website") or co.get("website") or "").strip()
    instagram = (body.get("instagram") or (co.get("socials") or {}).get("instagram") or "").strip()
    facebook = (body.get("facebook") or (co.get("socials") or {}).get("facebook") or "").strip()
    if not website and not instagram and not facebook:
        return JSONResponse({"detail": "Cadastre o site e/ou o Instagram em Dados Gerais primeiro."}, status_code=422)
    data: Dict[str, Any] = {}
    ai_warning = ""
    try:
        import asyncio
        from ..services.ai import enrich_company_from_web
        # to_thread: a montagem do perfil (site+Instagram+IA) leva 30-120s — rodar síncrono aqui TRAVAVA o
        # event loop inteiro e derrubava a plataforma toda com 502 enquanto durava.
        data = await asyncio.to_thread(
            enrich_company_from_web, co.get("name") or "", website, instagram, co.get("segment") or "", facebook,
        )
    except Exception as exc:
        # Logo/cores/fontes oficiais are deterministic and must still be imported when the
        # language-model profile is temporarily unavailable or not configured.
        ai_warning = str(exc)[:300]
    # Dados Gerais
    cup: Dict[str, Any] = {"website": website, "socials": {**(co.get("socials") or {}), "instagram": instagram}}
    if data.get("segment"):
        cup["segment"] = data["segment"]
    if data.get("description") and not (co.get("notes") or "").strip():
        cup["notes"] = data["description"]
    company_update(company_id, cup)
    # LOGO automático do site (se a empresa ainda não tem) → alimenta as cores abaixo e o motor de arte.
    ig_stats = {"logo": 0, "refs": 0}
    prods_added = 0
    try:
        import asyncio as _aio
        _remove_misclassified_web_logos(company_id, co.get("name") or "")
        if not (asset_list_logos(company_id) or []):
            await _aio.to_thread(_auto_fetch_logo, company_id, website)
        # INSTAGRAM → logo (perfil) + artes de referência (posts) — identidade visual real do cliente
        if instagram:
            ig_stats = await _aio.to_thread(_ig_fetch_brand, company_id, instagram)
        # SITE → catálogo de ofertas (planos/serviços/produtos) cadastrado automaticamente
        prods_added = await _aio.to_thread(_auto_extract_products, company_id, website)
    except Exception:
        pass
    # Cores: a LOGO é a verdade da marca (mais confiável que texto do site ou palpite da IA).
    colors = dict(data.get("colors") or {})
    logo_cols = _company_logo_colors(company_id)
    if logo_cols:
        colors.update(logo_cols)                    # sobrescreve o palpite da IA com a cor real da logo
    # Voz e Persona (brand kit)
    bk: Dict[str, Any] = {}
    for k in ("voice", "persona", "visual_prompt_base", "audience"):
        if data.get(k):
            bk[k] = data[k]
    if colors:
        bk["colors"] = colors
    if bk:
        brand_kit_upsert(company_id, bk)
    return {"company": company_get(company_id), "extracted": data,
            "products_added": prods_added, "instagram": ig_stats, "warning": ai_warning or None}


@router.post("/{company_id}/logo")
async def upload_logo(company_id: str, request: Request, file: UploadFile = File(...)):
    err = _api_key_required(request)
    if err:
        return err
    existing = company_get(company_id)
    if not existing:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    import uuid as _uuid
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "logo")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    filepath = os.path.join(subdir, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logo/{filename}"
    # update brand kit
    brand_kit_upsert(company_id, {"logo_url": url})
    # create asset
    asset_create(company_id, {"kind": "IMAGE", "source": "UPLOADED", "url": url,
                              "meta": {"role": "logo", "identity_scope": "company", "confidence": 1.0}})
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
    extras["reference_profile"] = profile
    brand_kit_upsert(company_id, {"extras": extras})


def _spawn_reference_analysis(company_id: str) -> None:
    import threading
    current = brand_kit_get(company_id) or {}
    extras = dict(current.get("extras") or {})
    extras["reference_profile"] = {
        **(extras.get("reference_profile") or {}),
        "status": "analyzing",
        "reference_count": len(asset_list(company_id, role="brand_reference")),
    }
    brand_kit_upsert(company_id, {"extras": extras})
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


def _dominant_colors(path: str, n: int = 3) -> List[str]:
    """Cores REAIS da marca a partir da logo, como #RRGGBB. Ranqueia por SATURAÇÃO×presença (a cor viva
    da marca ganha do anti-aliasing lavado — o bug antigo era ordenar só por contagem de pixel, então
    cinzas de borda venciam o azul/verde da marca). Fallback p/ logo monocromática (preto/cinza)."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("RGB").resize((128, 128))
        q = img.quantize(colors=32)
        pal = q.getpalette() or []
        cols = []                                   # (count, sat, r, g, b) — sem near-white/near-black
        for cnt, idx in (q.getcolors() or []):
            r, g, b = pal[idx * 3], pal[idx * 3 + 1], pal[idx * 3 + 2]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx > 238 and mn > 238:               # near-white (fundo)
                continue
            if mx < 26:                              # near-black
                continue
            cols.append((cnt, mx - mn, r, g, b))

        def _pick(min_sat: int, weight: float) -> List[str]:
            scored = [(cnt * ((sat / 255.0) ** weight if weight else 1.0), r, g, b)
                      for (cnt, sat, r, g, b) in cols if sat >= min_sat]
            scored.sort(reverse=True)
            picked: List[str] = []
            for _s, r, g, b in scored:
                hexv = "#%02X%02X%02X" % (r, g, b)
                # dedup por proximidade (evita dois tons quase iguais ocupando 2 das 3 vagas)
                if any(abs(int(h[1:3], 16) - r) + abs(int(h[3:5], 16) - g) + abs(int(h[5:7], 16) - b) < 60
                       for h in picked):
                    continue
                picked.append(hexv)
                if len(picked) >= n:
                    break
            return picked

        out = _pick(45, 1.5)                         # cores VIVAS da marca (peso na saturação)
        if len(out) < n:                             # logo monocromática → completa com o que houver
            for h in _pick(0, 0.0):
                if h not in out:
                    out.append(h)
                if len(out) >= n:
                    break
        return out
    except Exception:
        return []


def _company_logo_colors(company_id: str) -> Dict[str, str]:
    """{primary, secondary, accent} extraídos da PRIMEIRA logo (não-SVG) da empresa — FONTE ÚNICA de cor
    (logo = verdade da marca). Vazio se não houver logo utilizável. Usado pelo enrich e pelo social analyze
    (assim o palpite da IA nunca sobrescreve a cor real da logo)."""
    try:
        company_name = (company_get(company_id) or {}).get("name") or ""
        logos = list(asset_list_logos(company_id) or [])
        logos.sort(key=lambda lg: 0 if (lg.get("meta") or {}).get("is_primary") else 1)
        for lg in logos:
            if not _trusted_company_logo(lg, company_name):
                continue
            u = lg.get("url") or ""
            if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
                continue
            cols = _dominant_colors(os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/")))
            if cols:
                keys = ["primary", "secondary", "accent"]
                return {keys[i]: c for i, c in enumerate(cols)}
    except Exception:
        pass
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
            cols = _dominant_colors(os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/")))
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

@router.get("/{company_id}/logos")
def list_logos(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return {"logos": asset_list_logos(company_id)}


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
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    subdir = os.path.join(UPLOAD_DIR, company_id, "logos")
    os.makedirs(subdir, exist_ok=True)
    filename = f"{_uuid.uuid4().hex}{ext}"
    with open(os.path.join(subdir, filename), "wb") as f:
        f.write(await file.read())
    url = f"{UPLOAD_URL_PREFIX}/{company_id}/logos/{filename}"
    is_primary = str(primary).lower() in ("1", "true", "yes")
    if is_primary:
        asset_clear_primary(company_id)
    asset = asset_create(company_id, {
        "kind": "IMAGE", "source": "UPLOADED", "url": url,
        "meta": {"role": "logo", "variant": variant or "light", "is_primary": is_primary},
    })
    # Keep brand kit's primary logo_url in sync when this is the primary logo.
    if is_primary:
        brand_kit_upsert(company_id, {"logo_url": url})
    return {"logo": asset}


@router.delete("/{company_id}/logos/{asset_id}")
def delete_logo(company_id: str, asset_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    asset = asset_get(asset_id)
    if asset and (asset.get("url") or "").startswith(UPLOAD_URL_PREFIX):
        rel_path = asset["url"][len(UPLOAD_URL_PREFIX):].lstrip("/")
        abs_path = os.path.join(UPLOAD_DIR, rel_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    if not asset_delete(asset_id):
        return JSONResponse({"detail": "Logo não encontrado"}, status_code=404)
    return {"deleted": True}
