"""
Posts router — approval workflow + AI generation.
Mirrors caripost-web's post management and approval center.
"""
from __future__ import annotations

from ..main_utils import company_access_denied as __cad__

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db_companies import (
    post_list, post_get, post_create, post_transition, post_update, post_delete,
    post_stats, POST_STATUSES, POST_TRANSITIONS, POST_LABELS,
    company_get, report_get_latest, report_create, asset_list_logos, asset_list, product_list,
)
from ..services.ai import (
    get_ai_config, generate_post_copy, generate_trends, is_ai_enabled,
    generate_image_bytes, generate_image_with_cost, generate_image_resilient, image_models_registry, vision_clear_side, vision_read_text, text_render_issues, judge_art_text, text_fix_feedback, generate_image_with_person, compose_person_scene, verify_same_person, pick_influencer_photo, generate_image_edit, build_image_prompt, get_image_config, generate_image_reference_full, image_ref_models, get_image_ref_model,
    openrouter_image_models, openrouter_video_models, cometapi_video_models, omniroute_video_models, kie_video_models, kie_image_models, omniroute_image_models, openai_image_models, piapi_image_models, cometapi_image_models, usd_to_brl, get_setting,
    create_video_job, get_video_job, download_video, build_video_prompt, build_video_storyboard, get_video_config,
    accept_kie_callback, kie_callback_token,
)

import os
import uuid as _uuid

UPLOAD_DIR = os.environ.get("ADULT_META_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
UPLOAD_URL_PREFIX = os.environ.get("UPLOAD_URL_PREFIX", "/uploads")


def _first_raster_logo(assets) -> Optional[str]:
    """Return the file path of the first non-SVG logo that exists (PIL can't open SVG)."""
    for a in (assets or []):
        u = a.get("url") or ""
        if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
            continue
        p = os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/"))
        if os.path.exists(p):
            return p
    return None


def _logo_is_clean(path: str) -> bool:
    """True se a logo tem RECORTE (fundo transparente) — pronta pra carimbar sobre foto.
    False se é um retângulo de fundo sólido (gif/jpg/png achatado) que carimbaria uma CAIXA feia."""
    try:
        from PIL import Image
        im = Image.open(path)
        if "A" not in im.mode and "transparency" not in im.info:
            return False                              # sem canal alfa = fundo sólido (ex.: gif do Deezer)
        im = im.convert("RGBA")
        a = im.getchannel("A")
        if not a.getbbox():
            return False                              # alfa todo vazio
        w, h = im.size
        corners = [a.getpixel((0, 0)), a.getpixel((w - 1, 0)), a.getpixel((0, h - 1)), a.getpixel((w - 1, h - 1))]
        return sum(1 for v in corners if v < 16) >= 2  # ≥2 cantos transparentes = recorte de verdade
    except Exception:
        return True                                   # na dúvida, não descarta (não esconde logo boa)


def _all_raster_logos(assets) -> List[str]:
    """TODAS as variantes raster de logo que existem (branca/preta/colorida) — pro compositor
    escolher a de melhor contraste por fundo. Primária primeiro. SANEADO: se houver variante com
    recorte (fundo transparente), usa SÓ essas; descarta as de fundo assado (que virariam caixa)."""
    out: List[str] = []
    ordered = sorted(assets or [], key=lambda l: 0 if (l.get("meta") or {}).get("is_primary") else 1)
    for a in ordered:
        u = a.get("url") or ""
        if u.lower().endswith(".svg") or not u.startswith(UPLOAD_URL_PREFIX):
            continue
        p = os.path.join(UPLOAD_DIR, u[len(UPLOAD_URL_PREFIX):].lstrip("/"))
        if os.path.exists(p) and p not in out:
            out.append(p)
    clean = [p for p in out if _logo_is_clean(p)]
    return clean or out                               # tem recorte? usa só elas. senão degrada com o que há.


def _png_ref(path: str) -> Optional[bytes]:
    """Normalize any image file to a clean RGBA PNG (<=1024px) for the image-edit API."""
    try:
        import io
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        im.thumbnail((1024, 1024))
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None


def _logo_cutout(logo):
    """Remove a logo's solid background via flood-fill from the borders.

    Only the background *connected to the edges* is removed, so interior pixels
    of the same color (e.g. black inside a logo on a black tile) are preserved —
    avoiding the "broken logo" of a global color-key. The resulting alpha edge is
    feathered (Gaussian blur) so it isn't pixelated. Logos that already have real
    transparency are returned untouched.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter
        logo = logo.convert("RGBA")
        if logo.getchannel("A").getextrema()[0] < 200:
            return logo  # already has transparency
        w, h = logo.size
        rgb = logo.convert("RGB")
        SENT = (1, 254, 2)  # sentinel unlikely in a logo
        seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
        for s in seeds:
            try:
                ImageDraw.floodfill(rgb, s, SENT, thresh=72)
            except Exception:
                pass
        rp = rgb.load()
        mask = Image.new("L", (w, h), 255)
        mp = mask.load()
        removed = 0
        for y in range(h):
            for x in range(w):
                if rp[x, y] == SENT:
                    mp[x, y] = 0
                    removed += 1
        if removed < w * h * 0.04:
            return logo  # no clean solid background found → keep original
        # Feather the alpha edge so the cutout isn't jagged/pixelated.
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, min(w, h) * 0.006)))
        logo.putalpha(mask)
        return logo
    except Exception:
        return logo


def _logo_path_cutout(path: str) -> str:
    """Aplica _logo_cutout num ARQUIVO de logo (remove fundo branco assado → transparente) e devolve o
    caminho do PNG recortado (cacheado). Usado nas logos de EVENTO (que vêm com fundo branco/caixa)."""
    try:
        cache = path + ".cut.png"
        if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
            return cache
        from PIL import Image
        out = _logo_cutout(Image.open(path))
        out.save(cache)
        return cache
    except Exception:
        return path


def _overlay_logo(image_bytes: bytes, logo_path: str, position: str = "top-right", scale: float = 0.15) -> bytes:
    """Overlay the logo as a clean white rounded badge with a soft shadow.

    The brand assets are square tiles (often with text) — pasting them cut-out
    degrades the text. Instead we place the logo crisp (LANCZOS) on a white
    rounded card with padding, which reads as an intentional, legible badge for
    any logo (light or dark background).
    """
    try:
        import io
        from PIL import Image, ImageDraw, ImageFilter
        base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        target_w = max(90, int(base.width * scale))
        logo = logo.resize((target_w, max(1, int(logo.height * target_w / logo.width))), Image.LANCZOS)
        lw, lh = logo.size
        pad = int(max(lw, lh) * 0.14)
        bw, bh = lw + 2 * pad, lh + 2 * pad
        rad = int(min(bw, bh) * 0.22)
        badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(badge).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=rad, fill=(255, 255, 255, 255))
        badge.alpha_composite(logo, (pad, pad))
        m = int(base.width * 0.04)
        if position == "bottom-left":
            pos = (m, base.height - bh - m)
        elif position == "bottom-right":
            pos = (base.width - bw - m, base.height - bh - m)
        elif position == "top-left":
            pos = (m, m)
        else:  # top-right
            pos = (base.width - bw - m, m)
        # Soft shadow under the badge.
        sh = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=rad, fill=(0, 0, 0, 90))
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shadow.paste(sh, (pos[0] + int(bw * 0.02), pos[1] + int(bh * 0.04)), sh)
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, int(bw * 0.05))))
        base = Image.alpha_composite(base, shadow)
        base.alpha_composite(badge, pos)
        out = io.BytesIO()
        base.convert("RGB").save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return image_bytes

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.post("/kie-callback")
async def kie_callback(request: Request):
    """Webhook público da Kie. A URL contém token derivado da chave Kie e não dá
    acesso a nenhuma outra operação da API."""
    import hmac
    supplied = request.query_params.get("token") or ""
    expected = kie_callback_token()
    if not expected or not hmac.compare_digest(supplied, expected):
        return JSONResponse({"detail": "callback inválido"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not accept_kie_callback(payload if isinstance(payload, dict) else {}):
        return JSONResponse({"detail": "taskId ausente"}, status_code=422)
    return {"ok": True}


def _api_key_required(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


# ─────────────────────────────────────────────────────────────────────────────
# Posts CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_posts(request: Request, status: Optional[str] = None, company_id: Optional[str] = None, limit: int = 200):
    err = _api_key_required(request)
    if err:
        return err
    from ..main_utils import scoped_company_ids
    _scids = scoped_company_ids(request)
    if _scids is not None:
        if company_id and str(company_id) not in _scids:
            return JSONResponse({"detail": "Acesso negado a esta empresa.", "error": "company_scope"}, status_code=403)
        if not company_id and len(_scids) == 1:
            company_id = next(iter(_scids))                  # cliente final: força a empresa dele
    statuses = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip() in POST_STATUSES]
    posts = post_list(statuses=statuses, company_id=company_id, limit=limit)
    return {"posts": posts, "labels": POST_LABELS, "transitions": POST_TRANSITIONS}


@router.get("/stats")
def get_stats(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    return post_stats()


@router.get("/ai-models")
def ai_models(request: Request):
    """Image models available (id, name, quality, price/img) for the model picker.
    Defined BEFORE /{post_id} so it isn't captured as a post id."""
    err = _api_key_required(request)
    if err:
        return err
    # 4 PROVEDORES (fonte única, cada modelo marcado com 'provider'): OmniRoute grátis primeiro,
    # depois CometAPI, PiAPI, OpenRouter. GPT-direto (openai_direct) removido do seletor.
    # CACHE 5min: cada lista consulta a API do provedor AO VIVO — sem cache o dropdown da Criação
    # demorava segundos e o usuário clicava várias vezes achando que tinha travado.
    def _prov(lst, p):
        for m in lst:
            m.setdefault("provider", p)
        return lst
    import time as _tm
    global _MODELS_CACHE
    try:
        _MODELS_CACHE
    except NameError:
        _MODELS_CACHE = {"ts": 0.0, "img": None, "vid": None}
    if _MODELS_CACHE["img"] is None or (_tm.time() - _MODELS_CACHE["ts"]) > 300:
        _MODELS_CACHE["img"] = (_prov(omniroute_image_models(), "omniroute")
                                + _prov(cometapi_image_models(), "cometapi")
                                + _prov(piapi_image_models(), "piapi")
                                + _prov(openrouter_image_models(), "openrouter")
                                + _prov(kie_image_models(), "kie"))
        _MODELS_CACHE["vid"] = (_prov(kie_video_models(), "kie") + _prov(openrouter_video_models(), "openrouter")
                                + _prov(cometapi_video_models(), "cometapi"))
        _MODELS_CACHE["ts"] = _tm.time()
    img = [dict(m) for m in _MODELS_CACHE["img"]]
    vid = [dict(m) for m in _MODELS_CACHE["vid"]]
    for m in img:
        m["price_brl"] = usd_to_brl(m.get("price_per_image") or 0)
    for m in vid:
        m["price_brl"] = usd_to_brl(m.get("price_per_video") or 0)
    # Provedores de imagem que o usuário escolheu MOSTRAR na criação (Settings → Provedores). Default: todos.
    import json as _json
    try:
        _hidden = _json.loads(get_setting("image.providers.hidden") or "[]")
    except Exception:
        _hidden = []
    _img_provs = ["omniroute", "cometapi", "piapi", "openrouter", "kie"]
    img = [m for m in img if m.get("provider") not in _hidden]
    return {
        "image": img,
        "image_current": get_setting("image.model") or "",
        "image_provider": get_setting("image.provider") or "omniroute",
        "image_providers": [{"id": p, "enabled": p not in _hidden} for p in _img_provs],
        "image_ref_models": image_ref_models(),                                 # ESTÚDIO IA (motor de arte)
        "image_ref_current": get_setting("image_ref.model") or "openai/gpt-5.4-image-2",
        # MODULAR: admin fixa provedor+modelo e decide se o usuário TEM escolha na Criação.
        "choice_enabled": (get_setting("image.choice.enabled") or "1") != "0",
        "video": vid,
        "video_current": get_setting("video.model") or "",
        "fx_usd_brl": float(get_setting("fx.usd_brl") or 5.40),
    }


@router.post("/image-providers")
async def set_image_providers(request: Request):
    """Settings: define quais PROVEDORES de imagem aparecem na lista de criação (esconde o resto).
    NÃO mexe nos modelos nem nos provedores em si — só a visibilidade na UI."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    valid = {"omniroute", "cometapi", "piapi", "openrouter", "kie"}
    hidden = [p for p in (body.get("hidden") or []) if isinstance(p, str) and p in valid]
    import json as _json
    from ..db import settings_set
    settings_set(key="image.providers.hidden", value=_json.dumps(hidden),
                 updated_at=datetime.now(timezone.utc).isoformat())
    if "choice_enabled" in body:   # interruptor: usuário PODE (1) ou NÃO PODE (0) escolher modelo na Criação
        settings_set(key="image.choice.enabled", value=("1" if body.get("choice_enabled") else "0"),
                     updated_at=datetime.now(timezone.utc).isoformat())
    return {"ok": True, "hidden": hidden}


@router.get("/{post_id}")
def get_post(post_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    post = post_get(post_id)
    if not post:
        return JSONResponse({"detail": "Post não encontrado"}, status_code=404)
    return {"post": post}


@router.post("")
async def create_post(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    if not company_id:
        return JSONResponse({"detail": "company_id é obrigatório"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    # parse hashtags
    hashtags = body.get("hashtags", "")
    if isinstance(hashtags, list):
        hashtags = " ".join(hashtags)
    # ensure # prefix
    parts = [t.strip() for t in hashtags.replace(",", " ").split() if t.strip()]
    parts = [f"#{t}" if not t.startswith("#") else t for t in parts]
    hashtags = " ".join(parts)
    # title fallback
    title = body.get("title") or ""
    copy = body.get("copy") or ""
    if not title and copy:
        title = copy[:60]
    intent = body.get("intent", "draft")
    status = "REVIEW" if intent == "review" else "DRAFT"
    data = {
        "company_id": company_id,
        "status": status,
        "title": title,
        "copy": copy,
        "hashtags": hashtags,
        "networks": body.get("networks") or ["instagram"],
        "media_url": body.get("media_url"),
        "scheduled_at": body.get("scheduled_at"),
        "meta": body.get("meta") or {},
    }
    post = post_create(data)
    return {"post": post}


@router.post("/{post_id}/transition")
async def transition_post(post_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    to_status = body.get("to", "")
    if to_status not in POST_STATUSES:
        return JSONResponse({"detail": f"Status inválido: {to_status}"}, status_code=422)
    post = post_get(post_id)
    if not post:
        return JSONResponse({"detail": "Post não encontrado"}, status_code=404)
    current = post.get("status", "DRAFT")
    allowed = POST_TRANSITIONS.get(current, [])
    if to_status not in allowed:
        return JSONResponse({"detail": f"Transição não permitida: {current} → {to_status}"}, status_code=422)
    if to_status == "SCHEDULED" and not post.get("scheduled_at"):
        return JSONResponse({"detail": "Defina data de agendamento antes"}, status_code=422)
    updated = post_transition(post_id, to_status)
    return {"post": updated}


@router.put("/{post_id}")
async def update_post(post_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    post = post_get(post_id)
    if not post:
        return JSONResponse({"detail": "Post não encontrado"}, status_code=404)
    updated = post_update(post_id, body)
    return {"post": updated}


@router.delete("/{post_id}")
def delete_post(post_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    ok = post_delete(post_id)
    if not ok:
        return JSONResponse({"detail": "Post não encontrado"}, status_code=404)
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# AI generation
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate-ai")
async def generate_with_ai(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    briefing = body.get("briefing", "")
    networks = body.get("networks") or ["instagram"]
    if not company_id or not briefing:
        return JSONResponse({"detail": "company_id e briefing são obrigatórios"}, status_code=422)
    if not is_ai_enabled():
        return JSONResponse({"detail": "IA não configurada — adicione sua chave em Configurações."}, status_code=400)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    try:
        generated = generate_post_copy(company, briefing, networks)
        return {"generated": generated}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)


@router.post("/generate-image")
async def generate_post_image(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    if not company_id:
        return JSONResponse({"detail": "company_id é obrigatório"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    if not get_image_config():
        return JSONResponse({"detail": "Geração de imagem não configurada (chave OpenAI)."}, status_code=400)
    theme = (body.get("theme") or body.get("briefing") or "").strip()
    visual_prompt = (body.get("visual_prompt") or "").strip()
    products = product_list(company_id) or []
    colors = (company.get("brand_kit") or {}).get("colors") or {}
    brand_color = colors.get("accent") or colors.get("primary") or "#ED5E1F"
    model_override = (body.get("model") or "").strip() or None
    ai_bg = bool(model_override) and model_override.lower() != "editorial"
    # Mapeia o post numa "tela" + carrega o PERFIL (mesma lógica do carrossel).
    title = (body.get("headline") or body.get("title") or theme or "").strip()
    benefits = body.get("benefits") or []
    if not isinstance(benefits, list):
        benefits = [str(benefits)]
    sub = (body.get("subheadline") or "").strip()
    body_txt = sub or " · ".join([b for b in benefits if b])
    cta = (body.get("cta") or "").strip()
    product = (body.get("product") or "").strip()
    s = {"type": "cta" if cta else "content", "title": title, "body": body_txt, "cta": cta,
         "app": product, "visual": visual_prompt, "number": 1}
    from ..services.ai import image_template_get
    tmpl = image_template_get(company, "post", (body.get("template_id") or "").strip()) if body.get("template_id") else None
    structure = (tmpl or {}).get("structure")
    prompt = _full_slide_prompt(s, brand_color, company.get("name", ""), structure, (tmpl or {}).get("variant"), _palette_str(colors))
    prod = next((p for p in products if (p.get("name") or "").strip().lower() == product.lower()), None)
    co_logo = _first_raster_logo(sorted(asset_list_logos(company_id) or [], key=lambda l: 0 if (l.get("meta") or {}).get("is_primary") else 1))
    app_logo = _first_raster_logo(asset_list_logos(company_id, prod["id"])) if prod else None
    site = company.get("website") or ""
    phone = (company.get("phone") or "").strip()
    design_ov = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design")
    try:
        import asyncio
        from ..services.template_composer import compose_logos_only, compose_cta_footer, compose_carousel_slide
        cost, model = 0.0, model_override or "editorial"
        # POST FIXO: por padrão a IA desenha a peça inteira (modo criativo antigo).
        # O compositor com caixa/card fica opt-in, porque no post fixo ele mata a
        # direção de arte e deixa a peça com cara de template.
        rm = (body.get("render_mode") or "legacy_ai_full_art").strip().lower()
        handle = ((company.get("socials") or {}).get("instagram") or "").strip().lstrip("@")
        if ai_bg:
            # Transbordo inteligente também no post único (mesmo cérebro do carrossel): se o provedor cair, usa equivalente.
            img, cost, model = await asyncio.to_thread(generate_image_resilient, prompt, "1024x1536", None, model_override, None, set(), None)
            if rm == "legacy_ai_full_art":   # modo antigo ISOLADO: IA desenha a arte inteira, código carimba logo
                png = await asyncio.to_thread(compose_logos_only, img, co_logo, app_logo, colors)
                if cta:  # post com CTA → rodapé de contato (WhatsApp + número do cadastro)
                    png = await asyncio.to_thread(compose_cta_footer, png, co_logo, site, phone, colors)
            else:                            # photo_ai_composer (padrão): IA = só a foto, código tipografa tudo
                png = await asyncio.to_thread(compose_carousel_slide, s, 1, 1, colors, co_logo, site, handle, img, app_logo, design_ov)
        else:  # composer_only (grátis) — valida o fluxo sem gastar
            png = await asyncio.to_thread(compose_carousel_slide, s, 1, 1, colors, co_logo, site, handle, None, app_logo, design_ov)
        subdir = os.path.join(UPLOAD_DIR, company_id, "generated")
        os.makedirs(subdir, exist_ok=True)
        filename = f"{_uuid.uuid4().hex}.png"
        with open(os.path.join(subdir, filename), "wb") as f:
            f.write(png)
        url = f"{UPLOAD_URL_PREFIX}/{company_id}/generated/{filename}"
        return {"url": url, "prompt": prompt, "cost": usd_to_brl(cost), "cost_usd": cost, "currency": "BRL",
                "model": model, "composed": True, "template": (tmpl or {}).get("id")}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/generate-briefing")
async def generate_briefing_ep(request: Request):
    """Plano de conteúdo rico a partir de um assunto, adaptado a objetivo + formato
    (carrossel = plano de telas; video = roteiro; post = pauta)."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company = company_get(body.get("company_id"))
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    _dscope = __cad__(request, company.get("id"))
    if _dscope:
        return _dscope
    theme = (body.get("theme") or body.get("assunto") or "").strip()
    if not theme:
        return JSONResponse({"detail": "Informe o assunto/tema"}, status_code=422)
    try:
        n = int(body.get("n_telas") or body.get("n_slides") or 0)
    except Exception:
        n = 0
    try:
        import asyncio
        from ..services.ai import generate_briefing
        intent = (body.get("intent") or "produtos").strip().lower()
        event = None
        _eid = (body.get("event_id") or "").strip()
        if _eid:
            try:
                from ..db_companies import event_get, organizer_get
                event = event_get(_eid)
                if event and event.get("organizer_id"):
                    _org = organizer_get(event["organizer_id"])
                    if _org:
                        event = {**event, "organizer_name": _org.get("name")}
                if event:
                    intent = "evento"   # selecionou evento → modo evento
            except Exception:
                event = None
        if intent == "evento" and not event:
            # modo evento SEM evento real = prompt de evento sem dados → cai pra produtos (evita invenção).
            intent = "produtos"
        res = await asyncio.to_thread(generate_briefing, company, theme,
                                      body.get("objetivo") or "educar",
                                      body.get("formato") or "carrossel", n, intent, event,
                                      [a for a in (body.get("apps") or []) if (a or "").strip()],
                                      body.get("seconds") or 0)
        # storyboard/scene_seconds: o ROTEIRO de vídeo que o briefing JÁ gerou — vai pro front e volta na
        # criação (preflight) p/ NÃO re-gerar (era o bug do "1 cena só / caixas vazias na criação").
        return {"briefing": res.get("text", ""), "telas": res.get("telas", []), "formato": res.get("formato"),
                "storyboard": res.get("storyboard", []), "scene_seconds": res.get("scene_seconds", []),
                "audio_plan": res.get("audio_plan", {})}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/posts/{post_id}/story-image")
async def post_story_image(post_id: str, request: Request):
    """Gera (sob demanda, grátis — só PIL) a versão 9:16 BONITA da capa do post p/ republicar no story.
    Reusa se já existe (meta.story_url). NÃO usa IA, não custa nada."""
    err = _api_key_required(request)
    if err:
        return err
    import asyncio
    post = post_get(post_id)
    if not post:
        return JSONResponse({"detail": "Post não encontrado"}, status_code=404)
    meta = post.get("meta") or {}
    if meta.get("story_url"):
        return {"url": meta["story_url"]}
    urls = meta.get("carousel_urls") or ([post.get("media_url")] if post.get("media_url") else [])
    urls = [u for u in urls if u]
    if not urls:
        return JSONResponse({"detail": "Post sem imagem"}, status_code=422)
    try:
        from ..services.template_composer import compose_story_repost
        cid = post.get("company_id")
        company = company_get(cid) if cid else None
        colors = ((company or {}).get("brand_kit") or {}).get("colors") or {}
        cov_rel = urls[0].split(UPLOAD_URL_PREFIX, 1)[-1].lstrip("/")
        with open(os.path.join(UPLOAD_DIR, cov_rel), "rb") as cf:
            cov = cf.read()
        srep = await asyncio.to_thread(compose_story_repost, cov, colors)
        sdir = os.path.join(UPLOAD_DIR, cid, "story")
        os.makedirs(sdir, exist_ok=True)
        with open(os.path.join(sdir, f"{post_id}.png"), "wb") as sf:
            sf.write(srep)
        url = f"{UPLOAD_URL_PREFIX}/{cid}/story/{post_id}.png"
        meta["story_url"] = url
        post_update(post_id, {"meta": meta})
        return {"url": url}
    except Exception as e:
        return JSONResponse({"detail": str(e)[:200]}, status_code=500)


@router.post("/generate-carousel")
async def generate_post_carousel(request: Request):
    """Gera um CARROSSEL editorial (estilo g4/v4): capa + conteúdo (sem venda) + CTA.
    Texto via IA (assinatura) + slides renderizados pelo compositor com a identidade da marca."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    if not company_id:
        return JSONResponse({"detail": "company_id é obrigatório"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    theme = (body.get("theme") or body.get("assunto") or body.get("briefing") or "").strip()
    if not theme:
        return JSONResponse({"detail": "Informe o tema/assunto do carrossel"}, status_code=422)
    try:
        n = int(body.get("n_slides") or body.get("slides") or 0)
    except Exception:
        n = 0
    try:
        import asyncio
        from ..services.ai import generate_carousel
        from ..services.template_composer import compose_carousel_slide
        cr = await asyncio.to_thread(generate_carousel, company, theme, n)
        slides = cr.get("slides") or []
        if not slides:
            return JSONResponse({"detail": "IA não retornou slides para o carrossel."}, status_code=502)
        colors = (company.get("brand_kit") or {}).get("colors") or {}
        co_logo = _first_raster_logo(sorted(asset_list_logos(company_id) or [], key=lambda l: 0 if (l.get("meta") or {}).get("is_primary") else 1))
        site = company.get("website") or ""
        handle = ((company.get("socials") or {}).get("instagram") or "").strip().lstrip("@").rstrip("/").split("/")[-1]
        hexid = _uuid.uuid4().hex
        subdir = os.path.join(UPLOAD_DIR, company_id, "carousel", hexid)
        os.makedirs(subdir, exist_ok=True)
        total = len(slides)
        out = []
        for i, s in enumerate(slides, 1):
            img = await asyncio.to_thread(compose_carousel_slide, s, i, total, colors, co_logo, site, handle)
            fn = f"{i:02d}.png"
            with open(os.path.join(subdir, fn), "wb") as f:
                f.write(img)
            out.append({"url": f"{UPLOAD_URL_PREFIX}/{company_id}/carousel/{hexid}/{fn}",
                        "type": s.get("type"), "title": s.get("title", ""), "body": s.get("body", "")})
        return {"theme": cr.get("theme") or theme, "count": total, "slides": out}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


def _palette_str(colors: dict) -> str:
    """TODAS as cores cadastradas da marca (dict flexível — o usuário define quantas) em linha p/ prompt."""
    try:
        return ", ".join(f"{k} {v}" for k, v in (colors or {}).items() if v)
    except Exception:
        return ""


def _full_slide_prompt(s: dict, color: str, brand: str, structure: str = None, variant: str = None, palette: str = "") -> str:
    """A IA gera a ARTE COMPLETA. Se 'structure' (template) vier, a diagramação é TRAVADA nela (padrão consistente);
    senão, liberdade criativa. Reforço de acentos sempre. Logo e rodapé entram por código depois.
    variant ('escuro'/'claro') trava o FUNDO igual em todas as telas (padrão visual)."""
    title = (s.get("title") or "").strip()
    body = (s.get("body") or s.get("subtitle") or "").strip()
    cta = (s.get("cta") or "").strip()
    visual = (s.get("visual") or "").strip()
    is_cta = (s.get("type") == "cta")
    extra = []
    if body and not is_cta:   # no CTA o corpo NÃO é desenhado pela IA (a barra de contato cobre o rodapé)
        extra.append(f'Texto de apoio menor (legível): "{body}".')
    if is_cta and cta:
        extra.append(f'Chamada final curta e forte no centro: "{cta}".')
    struct = (structure + " ") if structure else "Tipografia forte, hierarquia clara, alto contraste, layout moderno e editorial, liberdade criativa elegante. "
    bg = ""   # trava de fundo + paleta + temperatura + escala = padrão visual idêntico entre TODAS as telas
    consist = ("MESMA paleta, MESMA temperatura de cor e MESMA grade de cor em todas as telas; "
               "MESMO enquadramento e MESMA escala dos elementos (não aproxime nem afaste de uma tela pra outra). ")
    if variant == "escuro":
        bg = ("FUNDO OBRIGATÓRIO grafite escuro uniforme, quase preto (#141418), em TODA a arte — idêntico em todas as telas. "
              "Iluminação quente sutil e cinematográfica. " + consist)
    elif variant == "claro":
        bg = ("FUNDO OBRIGATÓRIO claro off-white uniforme (#F2F2F0) em TODA a arte — idêntico em todas as telas. "
              "Luz natural suave e neutra. " + consist)
    accents = ("Texto em PORTUGUÊS DO BRASIL com TODOS os acentos CORRETOS (ã õ ç á é í ó ú â ê à) — NUNCA escreva palavra sem acento "
               "(ex.: experiência, família, não, só, preço, também, música, conexão, público). ")
    logo_line = ("DEIXE a faixa do TOPO (~16% da altura) TOTALMENTE LIMPA (sem texto e sem nada) — a logo oficial é carimbada pelo sistema. "
                 "NÃO desenhe NENHUM logo, marca, símbolo, ícone de app, nem a palavra 'logo', em lugar ALGUM da arte. ")
    foot_line = ("DEIXE a faixa de BAIXO (~26% da altura) LIMPA, sem texto — uma barra de contato é aplicada pelo sistema; "
                 "NÃO escreva telefone, WhatsApp, site nem 'fale conosco'. ") if is_cta else ""
    return (
        "Crie a ARTE COMPLETA e FINAL de UM slide de carrossel premium de Instagram, vertical 4:5 (1080x1350), "
        f"nível de agência top. Marca: {brand} (B2B brasileiro, SVAs para provedores de internet). "
        + struct + bg
        + f'TÍTULO em DESTAQUE, grande e perfeitamente legível: "{title}". ' + " ".join(extra) + " "
        + f"Cores da marca: destaque {color}" + (f"; PALETA COMPLETA (use como base): {palette}" if palette else " + escuros/neutros sofisticados") + ". " + accents
        + "Foto/arte premium real (nada de cara de IA/cartoon/3D barato). " + logo_line + foot_line
        + (f"Cena de base: {visual}. " if visual else "") + "Sem marca d'água."
    )


def _creative_full_prompt(s: dict, color: str, brand: str, palette: str = "", dna: str = "") -> str:
    """ARTE LIVRE / CRIATIVA: a IA ARQUITETA a arte social INTEIRA (cena + tipografia + CTA), na IDENTIDADE da
    marca (paleta + DNA visual). Só a logo entra por código depois (topo livre)."""
    title = (s.get("title") or "").strip()
    sub = (s.get("subtitle") or s.get("body") or "").strip()
    cta = (s.get("cta") or "").strip()
    visual = (s.get("visual") or "").strip()
    parts = [
        "Você é DIRETOR DE ARTE. Crie a ARTE SOCIAL COMPLETA e FINAL de um post de Instagram vertical 4:5 "
        "(1080x1350), na MELHOR qualidade e com os MELHORES detalhes, estilo VIRAL e CRIATIVO (meme / cultura pop / "
        "oportuno) — NADA corporativo/institucional. Direção de arte de agência premium. ",
        "ARQUITETE a composição INTEIRA em função do texto: decida ONDE vai o TEXTO e ONDE vai o "
        "PERSONAGEM/ELEMENTO de modo que UM NÃO SOBREPONHA o OUTRO — texto nunca por cima do rosto/sujeito, "
        "cada um no seu espaço, equilíbrio e respiro. ",
        f'A MENSAGEM em DESTAQUE máximo, tipografia criativa (peso/escala/cor) e SUPER legível, integrada à cena: "{title}". ',
    ]
    if sub:
        parts.append(f'Apoio menor, hierarquia clara abaixo do principal: "{sub}". ')
    if cta:
        parts.append(f'Inclua uma CHAMADA/CTA clara e bem posicionada (tipo botão ou etiqueta destacada, na cor da '
                     f'marca), SEM cobrir o sujeito nem o título: "{cta}". ')
    if visual:
        parts.append(f"Cena/ideia base: {visual}. ")
    # IDENTIDADE DA MARCA — cores + DNA visual (o que faltava)
    parts.append(f"IDENTIDADE DA MARCA {brand} (OBRIGATÓRIA): use a PALETA da marca como base da arte — "
                 f"{palette or color}. Acento principal {color}. ")
    if dna:
        parts.append(f"DNA visual da marca (siga o clima/estética): {dna} ")
    parts.append(
        "A TIPOGRAFIA e a CENA são UMA composição só, pensada junta (não é caixa de texto colada num canto). "
        "Fotográfico/realista premium (nada de 3D barato, cartoon ou cara de IA). "
        "Texto em PORTUGUÊS DO BRASIL com TODOS os acentos corretos (ã õ ç á é í ó ú â ê). "
        "DEIXE a faixa do TOPO (~14% da altura) e a faixa de BAIXO (~20% da altura) TOTALMENTE LIMPAS: sem texto, sem "
        "elementos, sem logo, sem contato — o sistema carimba a LOGO no topo e a BARRA DE CONTATO (site/telefone) embaixo. "
        "PROIBIDO ABSOLUTO em QUALQUER canto/parte da arte: desenhar logo, escudo, marca ou nome de marca (ex.: 'CARIP', "
        "'CARIAP', escudo da CBF), marca d'água, selo, badge, texto de metadados/preset (ex.: 'Premium', 'Instagram', "
        "'Preset', 'Mockup', 'Presigns'), hashtag (#...), código de cor (ex.: #FF4350) ou qualquer rótulo. A ÚNICA marca "
        "da arte é a logo oficial que o sistema carimba — a IA NÃO desenha marca nenhuma. Sem marca d'água."
    )
    return "".join(parts)


# PERSONALIDADE de design por produto (DNA de direção de arte) → tempera a INSTRUÇÃO. Moldável por empresa
# via creative_config.design.personalities (defaults bons aqui). Capa/CTA usam o DNA institucional da marca.
_PRODUCT_DNA = {
    "exitlag": ("PERSONALIDADE ExitLag (games): estética GAMER futurista de ALTA ENERGIA — neon (roxo/azul/ciano "
                "junto do laranja da marca), ELEMENTOS 3D flutuantes, velocidade, motion blur, partículas de luz, "
                "glow intenso, clima cyber/adrenalina. OUSADO e dinâmico."),
    "deezer": ("PERSONALIDADE Deezer (música): estética MUSICAL vibrante e FELIZ — ondas sonoras e equalizador em 3D, "
               "cores saturadas e alegres, ritmo e movimento, fones, luz colorida, energia jovem. Leve e gostoso."),
    "e-saúde": ("PERSONALIDADE E-Saúde (saúde): estética CLEAN e INSTITUCIONAL — tons suaves e luz natural, calma, "
                "confiança, cuidado humano, ambiente clínico premium e acolhedor, muito respiro. Sério e profissional."),
    "looke": ("PERSONALIDADE Looke (filmes): estética CINEMATOGRÁFICA imersiva — clima de cinema, luz dramática de "
              "projeção, profundidade e atmosfera de filme, escapismo premium que 'tira da realidade'."),
    "cariap": ("PERSONALIDADE CARIAP (institucional): estética CORPORATIVA futurista porém SÓBRIA — tech premium, "
               "moderno e confiável, dark elegante com o laranja da marca, sofisticado (sem exagero gamer)."),
}


def _product_dna(app_name: str, design: dict = None) -> str:
    """DNA de direção de arte do produto (default + override por empresa em design.personalities)."""
    key = (app_name or "").strip().lower()
    ov = ((design or {}).get("personalities") or {})
    for k in (key, key.replace("ú", "u").replace("-", "")):
        if k and k in ov:
            return ov[k]
    for k in (key, key.replace("ú", "u"), key.replace("-", "")):
        if k in _PRODUCT_DNA:
            return _PRODUCT_DNA[k]
    # Fallback NEUTRO (multi-empresa): nunca vazar o DNA/cor da CARIAP pra outro cliente.
    return ("PERSONALIDADE institucional da marca: estética premium, moderna e confiável, "
            "usando SOMENTE as cores oficiais do brand kit desta marca, sofisticada e alinhada à identidade dela.")


def _photo_only_prompt(s: dict, brand: str, variant: str = None, brand_hex: str = "", design: dict = None, avoid_people: bool = False, palette: str = "") -> str:
    """Marco 3 (photo_ai_composer): a IA gera SÓ a IMAGEM — sem texto/logo/marca; o código desenha o resto.
    A instrução é TEMPERADA pela PERSONALIDADE do produto (3D/neon/cinema/clean) → qualidade + variação,
    não padronice. Mantém ESPAÇO NEGATIVO p/ o texto e a proibição de texto/logo na imagem."""
    visual = (s.get("visual") or "").strip()
    lv = (s.get("layout_variant") or "").lower()
    ta = (s.get("text_area") or "").lower()
    if lv == "editorial_right" or ta == "right":
        empty, subject = "à direita", "à esquerda"
    elif lv in ("center_statement", "app_focus") or ta == "center":
        empty, subject = "na metade de cima", "mais abaixo / ao fundo"
    else:
        empty, subject = "à esquerda", "à direita"
    dna = _product_dna((s.get("app") or "").strip() or brand, design)   # default = a PRÓPRIA marca (CARIAP casa com o DNA dela; outra empresa cai no neutro)
    grade = (f"Grade de cor puxando para a PALETA DA MARCA ({palette or brand_hex}) " if (palette or brand_hex)
             else "Grade de cor cinematográfica de campanha ")
    # PROTAGONISTA orientado a CONTEÚDO (não trava pessoa em toda arte): pessoa, elemento/produto, ou os dois.
    if avoid_people:
        protag = ("CENA SEM PESSOAS: nenhuma figura humana, nenhum rosto, nenhuma mão — o PROTAGONISTA é o produto/elemento "
                  "(dispositivo, objeto, cenário, atmosfera tech, telas com brilho ABSTRATO), recorte nítido. ")
    else:
        protag = ("PROTAGONISTA conforme a cena base: pode ser uma PESSOA (brasileira real, expressiva, art-directed), um "
                  "ELEMENTO/produto (dispositivo, objeto, símbolo visual do recurso/função) ou os DOIS juntos — escolha o que "
                  "MELHOR ilustra ESTE conteúdo; NÃO force pessoa se a cena não pede. Recorte nítido, separação clara do fundo. ")
    return (
        "IMAGEM PUBLICITÁRIA premium para Instagram, nível AGÊNCIA de propaganda — estética de CAMPANHA, "
        "NÃO foto de banco de imagem, NÃO cara de IA/cartoon/render barato. Vertical 4:5, altíssima produção. "
        f"Marca: {brand}. " + dna + " " + grade + ". "
        "ILUMINAÇÃO dramática e direcional (rim light, contraluz, glow), PROFUNDIDADE real em camadas e TEXTURA "
        "rica (partículas, bokeh, atmosfera) — nada de fundo chapado. " + protag + "Composição premium, contraste alto. "
        f"COMPOSIÇÃO OBRIGATÓRIA: deixe a região {empty} como ESPAÇO TOTALMENTE VAZIO — superfície simples e mais "
        f"escura (parede, sombra ou bokeh), com ABSOLUTAMENTE nenhum rosto, nenhuma pessoa, nenhuma mão e nenhum "
        f"objeto. O sujeito fica INTEIRO {subject}, sem invadir o lado vazio. Regra RÍGIDA (o texto entra no lado vazio). "
        "PROIBIDO em QUALQUER lugar: texto, letra, número, palavra, legenda, marca d'água, logo ou símbolo de marca. "
        "Telas (TV/celular/notebook) só com brilho ABSTRATO — sem interface legível, sem ícone de app, sem logo. "
        "Linguagem visual e clima coesos entre as telas (cara de campanha), mas CADA tela com composição própria. "
        + (f"Cena base (REINTERPRETE com a personalidade acima, não literal): {visual}. " if visual else "")
        + "Acabamento de revista: foco nítido, grão fino, micro-contraste — zero aspecto amador."
    )


@router.get("/image-templates")
def list_image_templates(request: Request, company_id: str = "", type: str = "carrossel"):
    """Padrões (templates) de imagem do tipo p/ o cliente: default + os salvos."""
    err = _api_key_required(request)
    if err:
        return err
    from ..services.ai import image_templates
    co = company_get(company_id) if company_id else None
    return {"templates": image_templates(co, type or "carrossel")}


@router.post("/save-template")
async def save_image_template(request: Request):
    """Salva um padrão de imagem no cliente (creative_config.templates[type]). 'Gostei → virar template'."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company = company_get(body.get("company_id"))
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    _dscope = __cad__(request, company.get("id"))
    if _dscope:
        return _dscope
    ctype = (body.get("type") or "carrossel").strip()
    name = (body.get("name") or "").strip()
    structure = (body.get("structure") or "").strip()
    if not name or not structure:
        return JSONResponse({"detail": "name e structure são obrigatórios"}, status_code=422)
    import re as _re
    from ..db_companies import brand_kit_upsert
    tid = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or _uuid.uuid4().hex[:8]
    cc = (company.get("brand_kit") or {}).get("creative_config") or {}
    templates = cc.get("templates") or {}
    lst = [t for t in (templates.get(ctype) or []) if t.get("id") != tid]
    lst.append({"id": tid, "name": name, "variant": (body.get("variant") or "escuro"), "structure": structure})
    templates[ctype] = lst
    cc["templates"] = templates
    brand_kit_upsert(company["id"], {"creative_config": cc})
    return {"ok": True, "id": tid, "type": ctype}


@router.post("/delete-template")
async def delete_image_template(request: Request):
    """Exclui um perfil salvo do cliente (não mexe nos defaults). Maleável: criar/editar/excluir."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company = company_get(body.get("company_id"))
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    _dscope = __cad__(request, company.get("id"))
    if _dscope:
        return _dscope
    from ..db_companies import brand_kit_upsert
    ctype = (body.get("type") or "carrossel").strip()
    tid = (body.get("id") or "").strip()
    cc = (company.get("brand_kit") or {}).get("creative_config") or {}
    templates = cc.get("templates") or {}
    templates[ctype] = [t for t in (templates.get(ctype) or []) if t.get("id") != tid]
    cc["templates"] = templates
    brand_kit_upsert(company["id"], {"creative_config": cc})
    return {"ok": True}


def _resolve_render_mode(body: dict) -> str:
    """Modo de render EXPLÍCITO (anti-P6: o legacy fica ISOLADO atrás de flag, não some por acidente).
      • photo_ai_composer (padrão): a IA gera SÓ a foto; o código desenha texto/logo/barra/rodapé.
      • composer_only: só tipografia (grátis, sem IA).
      • legacy_ai_full_art: a IA desenha a arte inteira; o código só carimba logo (modo antigo, isolado).
    Compat: se render_mode não vier, deriva de model + composer (comportamento atual)."""
    rm = (body.get("render_mode") or "").strip().lower()
    if rm in ("photo_ai_composer", "composer_only", "legacy_ai_full_art", "reference_full"):
        return rm
    model = (body.get("model") or "").strip()
    # ══ ESTÚDIO IA É O PADRÃO DO MOTOR ══ (identidade REAL do cadastro: logos/manual/referências/KB —
    # validado em CARIAP, Sant' Beauty e iFibra). O motor antigo (caixa editorial/foto+card) SÓ roda se
    # for pedido EXPLICITAMENTE: render_mode acima ou model == "editorial". Sem checkbox, sem parâmetro.
    if model.lower() == "editorial":
        # Editorial grátis explícito. Influencer selecionado força o caminho de foto (senão seria pulado).
        if body.get("use_influencer") and (body.get("influencer_id") or "").strip():
            return "photo_ai_composer"
        return "composer_only"
    return "reference_full"


def _format_event_info(ev: dict) -> str:
    """Delega pra FONTE ÚNICA (ai.event_cta_info) — render e plano usam a MESMA verdade do cadastro."""
    from ..services.ai import event_cta_info
    return event_cta_info(ev)


def _load_upload_bytes(url: str):
    """Carrega bytes de um arquivo já servido (url começa com UPLOAD_URL_PREFIX) → caminho em UPLOAD_DIR.
    Usado pelo CACHE de foto: re-render da arte reusa a base salva, sem repagar a IA."""
    try:
        if not url:
            return None
        rel = url.split(UPLOAD_URL_PREFIX, 1)[-1].lstrip("/")
        p = os.path.join(UPLOAD_DIR, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


def _render_public_base() -> str:
    """Base PÚBLICA p/ montar URL de foto que o kie consegue baixar (image-edit). Override via setting."""
    return (get_setting("render.public_base") or "https://caripost.cariap.com.br").rstrip("/")


@router.post("/animate-art")
async def animate_art(request: Request):
    """ANIMAR IMAGEM: {company_id, url, motion?} — transforma a arte pronta num clipe curto (grok i2v),
    mantendo textos/logo estáveis. Débito em créditos da empresa."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = (body.get("company_id") or "").strip()
    url = (body.get("url") or "").strip()
    if not (company_id and url):
        return JSONResponse({"detail": "company_id e url são obrigatórios"}, status_code=422)
    _d = __cad__(request, company_id)
    if _d:
        return _d
    from ..services.billing import check_credits, log_usage as _bl3, get_features as _gf3
    if not (_gf3(company_id).get("animar", True)):
        return JSONResponse({"detail": "Função não liberada no seu plano. Chame o seu consultor de vendas.",
                             "error": "feature_blocked"}, status_code=403)
    _deny = check_credits(company_id)
    if _deny:
        return JSONResponse({"detail": _deny, "error": "no_credits"}, status_code=402)
    pub = (_render_public_base() + url) if url.startswith("/") else url
    motion = (body.get("motion") or "").strip() or (
        "Anime esta arte com elegância sutil: leve zoom-in cinematográfico, brilho suave percorrendo os elementos, "
        "partículas discretas. Mantenha TODOS os textos e a logo perfeitamente legíveis e estáveis. "
        "SEM fala — apenas trilha/ambiente suave.")

    def _run():
        import time as _t
        import httpx as _hx
        from ..services.ai import _kie_key, _KIE_BASE, _kie_record, _kie_result_urls
        key = _kie_key()
        r = _hx.post(_KIE_BASE + "/jobs/createTask",
                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                     json={"model": "grok-imagine/image-to-video",
                           "input": {"image_urls": [pub], "prompt": motion}}, timeout=30)
        tid = ((r.json() or {}).get("data") or {}).get("taskId")
        if not tid:
            raise ValueError("provedor não aceitou: " + r.text[:120])
        for _ in range(90):
            _t.sleep(4)
            d = _kie_record(tid)
            st = (d.get("state") or "").lower()
            if st == "success":
                u2 = (_kie_result_urls(d) or [""])[0]
                if u2:
                    return _hx.get(u2, timeout=180).content, float(d.get("creditsConsumed") or 0)
                break
            if st == "fail":
                raise ValueError("animação falhou: " + str(d.get("failMsg") or "")[:120])
        raise ValueError("animação não concluiu a tempo")
    try:
        data, kie_credits = await asyncio.to_thread(_run)
    except Exception as e:
        return JSONResponse({"detail": str(e)[:200]}, status_code=502)
    import uuid as _uuid
    subdir = os.path.join(UPLOAD_DIR, company_id, "edits")
    os.makedirs(subdir, exist_ok=True)
    fn = f"{_uuid.uuid4().hex}.mp4"
    with open(os.path.join(subdir, fn), "wb") as f:
        f.write(data)
    est = kie_credits * 0.005            # 1 crédito kie ≈ $0,005
    _bl3(company_id, "animate", est, provider="kie", model="grok-imagine/i2v", meta={"src": url[:120]})
    return {"ok": True, "url": f"{UPLOAD_URL_PREFIX}/{company_id}/edits/{fn}", "cost_usd": round(est, 4)}


@router.post("/edit-art")
async def edit_art(request: Request):
    """EDITAR COM IA: {company_id, url, instruction} — edita a arte preservando todo o resto
    (mesma técnica validada no chat: arte como referência + instrução cirúrgica)."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = (body.get("company_id") or "").strip()
    url = (body.get("url") or "").strip()
    instruction = (body.get("instruction") or "").strip()
    if not (company_id and url and instruction):
        return JSONResponse({"detail": "company_id, url e instruction são obrigatórios"}, status_code=422)
    _dscope = __cad__(request, company_id)
    if _dscope:
        return _dscope
    from ..services.billing import check_credits, log_usage as _blog2, feature_enabled as _fe2, get_features as _gf2
    if not (_gf2(company_id).get("editar_arte", True)):
        return JSONResponse({"detail": "Função não liberada no seu plano. Chame o seu consultor de vendas.", "error": "feature_blocked"}, status_code=403)
    _deny = check_credits(company_id)
    if _deny:
        return JSONResponse({"detail": _deny, "error": "no_credits"}, status_code=402)
    img = _load_upload_bytes(url)
    if not img:
        return JSONResponse({"detail": "Arte não encontrada"}, status_code=404)
    prompt = ("EDITE a arte fornecida na imagem de referência. Aplique SOMENTE esta mudança: "
              + instruction[:800] +
              ". NÃO altere absolutamente mais NADA: mantenha idênticos os textos, tipografia, logo, cores, "
              "layout, foto e proporção. Devolva a MESMA arte com apenas a mudança pedida.")
    try:
        out, cost = await asyncio.to_thread(generate_image_reference_full, prompt, [img])
    except Exception as e:
        return JSONResponse({"detail": str(e)[:200]}, status_code=502)
    import uuid as _uuid
    subdir = os.path.join(UPLOAD_DIR, company_id, "edits")
    os.makedirs(subdir, exist_ok=True)
    fn = f"{_uuid.uuid4().hex}.png"
    with open(os.path.join(subdir, fn), "wb") as f:
        f.write(out)
    new_url = f"{UPLOAD_URL_PREFIX}/{company_id}/edits/{fn}"
    _blog2(company_id, "image_edit", cost or 0.0, model="openai/gpt-5.4-image-2", meta={"src": url[:120]})
    return {"ok": True, "url": new_url, "cost_usd": round(cost or 0.0, 4)}


@router.post("/render-carousel")
async def render_carousel(request: Request):
    """Renderiza um conjunto de TELAS (vindas do plano do briefing) em imagens, com a identidade
    da marca. model vazio/'editorial' = só tipografia (grátis); senão gera um fundo por IA (híbrido)."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    company = company_get(company_id) if company_id else None
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    _dscope = __cad__(request, company_id)
    if _dscope:
        return _dscope

    telas = body.get("telas") or []
    if not telas:
        return JSONResponse({"detail": "Sem telas para renderizar (gere o plano no Briefing)."}, status_code=422)
    model = (body.get("model") or "").strip()
    # BILLING/ACESSO por empresa (Marco 4): trava por saldo (só com billing.enforce ligado) + feature flag
    from ..services.billing import check_credits, feature_enabled, log_usage as _blog
    _deny = check_credits(company_id)
    if _deny:
        return JSONResponse({"detail": _deny, "error": "no_credits"}, status_code=402)
    if not feature_enabled(company, "generate"):
        return JSONResponse({"detail": "Geração de conteúdo bloqueada para esta empresa.", "error": "feature_blocked"}, status_code=403)
    render_mode = _resolve_render_mode(body)            # photo_ai_composer | composer_only | legacy_ai_full_art
    ai_bg = render_mode in ("photo_ai_composer", "legacy_ai_full_art", "reference_full")
    use_composer = render_mode == "photo_ai_composer"
    ref_full = render_mode == "reference_full"   # ESTÚDIO IA: arte inteira guiada por referências do CADASTRO
    # CACHE: base_urls (1 por tela, alinhado por índice) → reusa a foto salva e NÃO chama a IA (custo 0).
    reuse_bases = body.get("base_urls") if isinstance(body.get("base_urls"), list) else []
    if ai_bg and not get_image_config():
        return JSONResponse({"detail": "Geração de imagem não configurada."}, status_code=400)
    try:
        import asyncio
        from ..services.template_composer import compose_carousel_slide, compose_card_slide
        colors = (company.get("brand_kit") or {}).get("colors") or {}
        co_logos = _all_raster_logos(asset_list_logos(company_id))   # todas as variantes da marca
        co_logo = co_logos[0] if co_logos else None                  # primária (p/ legacy/cta_footer)
        site = company.get("website") or ""
        handle = ((company.get("socials") or {}).get("instagram") or "").strip().lstrip("@").rstrip("/").split("/")[-1]
        hexid = _uuid.uuid4().hex
        subdir = os.path.join(UPLOAD_DIR, company_id, "carousel", hexid)
        os.makedirs(subdir, exist_ok=True)
        total = len(telas)
        # FORMATO: carrossel/post = 4:5 (1080×1350); story = 9:16 (1080×1920). Define o canvas do composer + o aspecto da IA.
        fmt = (body.get("format") or body.get("formato") or "carrossel").strip().lower()
        canvas_size = (1080, 1920) if fmt == "story" else (1080, 1350)
        img_size = "1024x1792" if fmt == "story" else "1024x1536"
        # Mapa nome do app (minúsculo) -> logo OFICIAL cadastrada (carimbada por código).
        app_logos = {}
        for p in (product_list(company_id) or []):
            lps = _all_raster_logos(asset_list_logos(company_id, p["id"]))   # variantes do app
            if lps:
                app_logos[(p.get("name") or "").strip().lower()] = lps
        brand_color = colors.get("accent") or colors.get("primary") or "#ED5E1F"
        from ..services.template_composer import compose_logos_only, compose_cta_footer
        from ..services.ai import image_template_get
        tmpl = image_template_get(company, "carrossel", (body.get("template_id") or "").strip()) if body.get("template_id") else None
        structure = (tmpl or {}).get("structure")
        phone = (company.get("phone") or "").strip()
        design_ov = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("design")
        base = str(request.base_url).rstrip("/")

        def _logo_url(assets):
            for a in (assets or []):
                u = (a.get("url") or "")
                if u and u.lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp"):
                    return (base + u) if u.startswith("/") else u
            return None
        company_logo_url = _logo_url(asset_list_logos(company_id))
        app_logo_urls = {}
        for p in (product_list(company_id) or []):
            u = _logo_url(asset_list_logos(company_id, p["id"]))
            if u:
                app_logo_urls[(p.get("name") or "").strip().lower()] = u
        # Token moldável: app_logo.on_all → repete a logo do app em TODAS as telas (carrossel de marca
        # única). Default off. Escolhe o app mais citado; se nenhum e só há 1 produto com logo, usa ele.
        on_all_apps = bool((design_ov or {}).get("app_logo", {}).get("on_all"))
        primary_app_variants = None
        if on_all_apps:
            from collections import Counter
            tagged = Counter((t.get("app") or "").strip().lower() for t in telas if (t.get("app") or "").strip())
            if tagged:
                primary_app_variants = app_logos.get(tagged.most_common(1)[0][0])
            elif len(app_logos) == 1:
                primary_app_variants = next(iter(app_logos.values()))
        out, total_cost, fails, bases = [], 0.0, [], []
        # TRANSBORDO: registro de modelos (1x) + provedores mortos compartilhados entre as telas + nota de transbordos.
        img_registry = image_models_registry() if ai_bg else []
        dead_providers, spillovers = set(), []
        # INFLUENCER (OPT-IN): só entra se o briefing pediu (use_influencer). Compõe SÓ na CAPA e no CTA (nano-banana). @ p/ collab.
        # ── ESTÚDIO IA (reference_full): junta as REFERÊNCIAS do CADASTRO (estrutural, sem regra hardcoded) ──
        ref_ctx = {"logos": [], "arts": [], "logo_urls": [], "art_urls": [], "kb": {}, "brand": ""}
        if ref_full:
            try:
                for _lp in (co_logos or [])[:4]:                      # TODAS as versões da logo (modelo escolhe)
                    try:
                        ref_ctx["logos"].append(open(_lp, "rb").read())
                    except Exception:
                        pass
                try:                                                  # URLs PÚBLICAS das logos (p/ Estúdio via kie image-edit)
                    from ..db_companies import asset_list_logos as _allg
                    for _la in (_allg(company_id) or [])[:4]:
                        _lu = _la.get("url") or ""
                        if _lu:
                            ref_ctx["logo_urls"].append((_render_public_base() + _lu) if _lu.startswith("/") else _lu)
                except Exception:
                    pass
                from ..db_companies import asset_list as _alist
                for _ra in (_alist(company_id, role="brand_reference") or [])[:3]:   # artes de referência do cliente
                    _ru = _ra.get("url") or ""
                    _b = _load_upload_bytes(_ru)
                    if _b:
                        ref_ctx["arts"].append(_b)
                        if _ru:                                       # URL pública p/ o kie image-edit
                            ref_ctx["art_urls"].append((_render_public_base() + _ru) if _ru.startswith("/") else _ru)
                bk_ = company.get("brand_kit") or {}
                _palette = ", ".join(f"{k} {v}" for k, v in ((bk_.get("colors") or {}).items()) if v)
                _site_c = (company.get("website") or "").replace("https://", "").replace("http://", "").strip("/")
                _fone_c = (company.get("phone") or "").strip()
                _ig_c = ((company.get("socials") or {}).get("instagram") or "").strip()
                ref_ctx["contact"] = " · ".join(x for x in [
                    (f"WhatsApp {_fone_c}" if _fone_c else ""),
                    (_site_c or ""),
                    (("@" + _ig_c.lstrip("@")) if _ig_c else "")] if x)
                ref_ctx["brand"] = (
                    f"IDENTIDADE DA MARCA {company.get('name','')} (siga à risca): {(bk_.get('visual_prompt_base') or '').strip()} "
                    + (f"PALETA OFICIAL: {_palette}. " if _palette else "")
                    + (f"REGRAS DA MARCA: {(bk_.get('client_rules') or '').strip()} " if (bk_.get('client_rules') or '').strip() else ""))
                _rp = ((bk_.get("extras") or {}).get("reference_profile") or {})
                if _rp.get("status") == "ready":
                    _rp_parts = [
                        ("composição " + str(_rp.get("layout_direction"))) if _rp.get("layout_direction") else "",
                        ("tipografia " + str(_rp.get("typography"))) if _rp.get("typography") else "",
                        ("assinatura institucional preferida em " + str(_rp.get("logo_position")))
                        if _rp.get("logo_position") not in (None, "", "unknown") else "",
                        ("uso de cor " + str(_rp.get("color_usage"))) if _rp.get("color_usage") else "",
                    ]
                    ref_ctx["brand"] += (
                        " PERFIL EXTRAÍDO DAS ARTES DE REFERÊNCIA (serve para layout/estilo; nunca substitui "
                        "a logo nem a paleta oficial da empresa): " + "; ".join(x for x in _rp_parts if x) + "."
                    )
                try:
                    from ..db_companies import product_list as _plist2
                    for _p in (_plist2(company_id) or []):
                        _nm = (_p.get("name") or "").strip()
                        if _nm:
                            _fns3 = _p.get("functions") or []
                            if isinstance(_fns3, str):
                                try:
                                    import json as _j3; _fns3 = _j3.loads(_fns3)
                                except Exception:
                                    _fns3 = [_fns3] if _fns3 else []
                            _kbtxt = " | ".join(x for x in [(_p.get("description") or "").strip(),
                                                            (_p.get("objective") or "").strip(),
                                                            ("Inclui: " + "; ".join(str(f) for f in _fns3[:8]) if _fns3 else ""),
                                                            (_p.get("knowledge") or "")[:700].strip()] if x)
                            if _kbtxt:
                                ref_ctx["kb"][_nm.lower()] = _kbtxt
                except Exception:
                    pass
            except Exception:
                pass
        influencer, inf_photos, inf_photo_urls, inf_handle, used_inf_idx = None, [], [], "", set()
        if ai_bg and (use_composer or ref_full) and body.get("use_influencer"):
            try:
                from ..db_companies import influencer_list, influencer_get
                iid = (body.get("influencer_id") or "").strip()
                if iid:
                    _one = influencer_get(iid)
                    _infs = [_one] if (_one and (_one.get("photos") or [])) else []
                else:
                    _infs = [x for x in (influencer_list(company_id) or []) if (x.get("photos") or [])]
                if _infs:
                    influencer = _infs[0]
                    _pairs = [(_load_upload_bytes(p.get("url")), (p.get("url") or "")) for p in influencer["photos"]]
                    _pairs = [(b, u) for (b, u) in _pairs if b]
                    inf_photos = [b for (b, u) in _pairs]
                    inf_photo_urls = [u for (b, u) in _pairs]   # URLs públicas p/ o kie image-edit (compose_person_scene)
                    inf_handle = (influencer.get("handle") or "").strip()
                    # VARIEDADE (evita repetir as MESMAS 2 fotos entre posts): semeia used_inf_idx com as
                    # fotos RECÉM-USADAS deste influencer (persistido), deixando >=2 frescas p/ capa+CTA.
                    try:
                        import json as _json
                        _recent = _json.loads(get_setting("influencer.recent." + (influencer.get("id") or "")) or "[]")
                        used_inf_idx = set(i for i in _recent if isinstance(i, int) and 0 <= i < len(inf_photos))
                    except Exception:
                        used_inf_idx = set()
            except Exception:
                influencer = None
        # EVENTO: logos (carimba na capa/CTA) + info REAL (datas/local/stand do cadastro) que o CÓDIGO injeta no CTA.
        event_logo_variants = []
        event_cta_info = ""
        _event = None   # evento carregado (usado no prompt do influencer p/ ambientar)
        _eid = (body.get("event_id") or "").strip()
        if _eid:
            try:
                from ..db_companies import event_get, organizer_get
                _ev = event_get(_eid); _event = _ev
                _eassets = list((_ev or {}).get("logos") or [])
                if _ev and _ev.get("organizer_id"):
                    _org = organizer_get(_ev["organizer_id"])
                    if _org:
                        _eassets += list(_org.get("logos") or [])
                _epaths = []
                for _a in _eassets:
                    _u = _a.get("url") or ""
                    if _u.startswith(UPLOAD_URL_PREFIX):
                        _pp = os.path.join(UPLOAD_DIR, _u[len(UPLOAD_URL_PREFIX):].lstrip("/"))
                        if os.path.exists(_pp):
                            _epaths.append(_logo_path_cutout(_pp))   # remove o FUNDO BRANCO (a caixa) da logo do evento
                event_logo_variants = _epaths or _all_raster_logos(_eassets)
                if _ev:
                    event_cta_info = _format_event_info(_ev)   # REAL — substitui o que a IA tiver inventado
                    # SANEIA TODAS as telas (datas/stand inventados em qualquer campo, incl. visual) ANTES do render E da legenda.
                    from ..services.ai import sanitize_event_plan
                    telas = sanitize_event_plan(_ev, telas)
            except Exception:
                event_logo_variants = []
        # ESTILO do texto por CARROSSEL (variedade entre temas, coeso dentro do carrossel; configurável por empresa).
        import hashlib as _hl
        _styles = ["glass", "solid", "scrim", "outline"]
        _ds = (design_ov or {}).get("text_style") if isinstance(design_ov, dict) else None
        _seed = int(_hl.md5(((telas[0].get("title") if telas else "") + str(company_id)).encode("utf-8", "ignore")).hexdigest(), 16)
        carousel_style = (_ds or _styles[_seed % len(_styles)])
        async def _render_tela(i, s, _anchor_url=None):
            # PARALELO (fim dos 24min/8 artes): corpo de UMA tela. A tela 1 roda PRIMEIRO (é a âncora da
            # família visual); as demais rodam SIMULTÂNEAS (teto = setting render.parallel, default 4;
            # 1 = fila antiga, rollback sem deploy). Agregadores são LOCAIS (sombra dos de fora) e o
            # driver abaixo soma tudo NA ORDEM das telas.
            total_cost, fails, spillovers, bases = 0.0, [], [], []
            app_name = (s.get("app") or "").strip().lower()
            # MALEÁVEL: coleta TODOS os apps relevantes da tela (taguead​o + citados no título/corpo),
            # não só um. O nº de logos por tela é limitado pelo token app_logo.max_per_slide no composer.
            tl = ((s.get("app") or "") + " " + (s.get("title") or "") + " " + (s.get("body") or "")).lower()
            slide_app_logos, _seen = [], set()
            for nm in ([app_name] if app_name else []) + list(app_logos.keys()):
                if nm and nm in app_logos and nm not in _seen and (nm == app_name or nm in tl):
                    _seen.add(nm); slide_app_logos.append(app_logos[nm])
            if not slide_app_logos and on_all_apps and primary_app_variants:
                slide_app_logos = [primary_app_variants]
            if event_logo_variants and (s.get("type") or "").lower() in ("cover", "cta"):
                slide_app_logos = [event_logo_variants] + slide_app_logos   # LOGO DO EVENTO na capa e no CTA
            app_variants = slide_app_logos[0] if slide_app_logos else []   # 1º app (p/ legacy/compat)
            is_cta = (s.get("type") == "cta")
            _dg = "".join(ch for ch in phone if ch.isdigit())
            phone_fmt = (f"({_dg[:2]}) {_dg[2:7]}-{_dg[7:]}" if len(_dg) == 11
                         else f"({_dg[:2]}) {_dg[2:6]}-{_dg[6:]}" if len(_dg) == 10 else phone)
            slide_for_render = {**s, "phone": phone_fmt, "text_style": carousel_style}   # composer desenha contato + estilo
            # (datas/local/stand reais já foram saneados em TODAS as telas por sanitize_event_plan acima — render+legenda)
            # photo_ai_composer: a IA gera SÓ a foto (_photo_only_prompt); o código desenha o resto.
            # legacy: a IA desenha a arte inteira (_full_slide_prompt) e o código só carimba logo/rodapé.
            if use_composer:
                prompt = _photo_only_prompt(s, company.get("name", ""), (tmpl or {}).get("variant"), brand_color, design_ov, palette=_palette_str(colors))
            elif s.get("free_text"):
                _pal = ", ".join(str(v) for v in (colors or {}).values() if v) or brand_color
                _dna = _product_dna((s.get("app") or "").strip() or company.get("name", ""), design_ov)
                prompt = _creative_full_prompt(s, brand_color, company.get("name", ""), _pal, _dna)   # IA arquiteta na identidade
            else:
                prompt = _full_slide_prompt(s, brand_color, company.get("name", ""), structure, (tmpl or {}).get("variant"), _palette_str(colors))
            app_legacy = app_variants[0] if app_variants else None   # legacy usa 1 só
            img_ok, img_err, png, img, used_model = False, "", None, None, model
            # 1) GERAÇÃO da foto — do CACHE (base salva, custo 0) OU da IA com TRANSBORDO inteligente.
            reuse_url = reuse_bases[i - 1] if i - 1 < len(reuse_bases) else None
            if ai_bg and reuse_url:
                img = _load_upload_bytes(reuse_url)            # CACHE: reusa a foto, NÃO paga IA
                img_ok = img is not None
            # INFLUENCER na CAPA/CTA: compõe a pessoa real na cena (nano-banana), em vez da cena vazia.
            stype = (s.get("type") or "").lower()
            # ── ESTÚDIO IA (reference_full): a IA arquiteta a ARTE INTEIRA da tela, guiada pelas referências
            # do cadastro (logos, artes de referência, manual, KB) + a IDEIA DO CLIENTE (enriquece, não substitui).
            if ref_full and img is None:
                _refs = list(ref_ctx["logos"]) + list(ref_ctx["arts"])
                # PRIORIDADE nas URLs — o caminho kie CORTA em 5: âncora + marca (2) + logos de PRODUTO
                # entram ANTES das artes de referência. Antes as logos de produto caíam fora do corte e o
                # modelo desenhava o produto DE MEMÓRIA (Deezer com identidade antiga) mesmo cadastrado.
                _ref_urls = list((ref_ctx.get("logo_urls") or [])[:2])
                _ref_urls_tail = list(ref_ctx.get("art_urls") or [])
                _extra = []
                if ref_ctx["arts"]:
                    _extra.append("As artes de REFERÊNCIA do cliente definem a FAMÍLIA VISUAL — siga esse estilo "
                                  "mantendo a identidade da marca.")
                if influencer and inf_photos and stype in ("cover", "cta"):
                    _pi = await asyncio.to_thread(pick_influencer_photo, inf_photos, s.get("title", ""), stype, used_inf_idx)
                    used_inf_idx.add(_pi)
                    _refs.append(inf_photos[_pi])
                    _extra.append("Uma das referências é a FOTO REAL da pessoa (influencer): use ESTA pessoa EM DESTAQUE "
                                  "na composição (é a capa/CTA), rosto e expressão 100% FIÉIS — não redesenhe o rosto, "
                                  "não troque a pessoa, integre-a como protagonista da cena.")
                if _anchor_url and i > 1:
                    _prev = _load_upload_bytes(_anchor_url) if isinstance(_anchor_url, str) else None
                    if _prev:
                        _refs.append(_prev)
                        _ref_urls.insert(0, (_render_public_base() + _anchor_url) if _anchor_url.startswith("/") else _anchor_url)
                        _extra.append("Uma das referências é a PRIMEIRA tela desta MESMA peça: mantenha EXATAMENTE "
                                      "a mesma família visual (layout, tipografia, paleta, tom).")
                _kb = ref_ctx["kb"].get(((s.get("app") or "").strip().lower()), "")
                _apnm = ((s.get("app") or "").strip().lower())
                # ── LOGOS DE PRODUTO: TODOS os produtos citados na tela (app + título + texto + CTA), não só
                # o primeiro. Cada logo entra em BYTES (openrouter/comet) E em URL PÚBLICA (o caminho kie SÓ
                # recebe URLs — era o buraco: a logo ia só em bytes, o modelo nunca a via e desenhava a logo
                # DE MEMÓRIA, ex.: Deezer com a identidade antiga). Instrução NOMEIA cada produto.
                _blob = " ".join([(s.get("app") or ""), (s.get("title") or ""),
                                  (s.get("body") or s.get("subtitle") or ""), (s.get("cta") or "")]).lower()
                _prod_logos, _seen_p = [], set()
                try:
                    from ..db_companies import company_list as _clist3, product_list as _plist3
                    # a PRÓPRIA empresa primeiro (a logo cadastrada dela vence a do catálogo comum)
                    for _co3 in ([{"id": company_id}] + [c for c in (_clist3() or []) if c["id"] != company_id]):
                        for _p3 in (_plist3(_co3["id"]) or []):
                            _n3 = (_p3.get("name") or "").strip().lower()
                            if not _n3 or _n3 in _seen_p or not (_n3 == _apnm or _n3 in _blob):
                                continue
                            _as3 = asset_list_logos(_co3["id"], _p3["id"])
                            _lg3 = _all_raster_logos(_as3)
                            if not _lg3:
                                continue
                            _u3 = next((a.get("url") for a in (_as3 or [])
                                        if (a.get("url") or "").lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp")), "")
                            _seen_p.add(_n3)
                            _prod_logos.append(((_p3.get("name") or "").strip(), _lg3[0], _u3 or ""))
                except Exception:
                    pass
                for _pn, _lp2, _pu in _prod_logos[:3]:
                    try:
                        _refs.append(open(_lp2, "rb").read())
                        if _pu:
                            _ref_urls.append((_render_public_base() + _pu) if _pu.startswith("/") else _pu)
                        _extra.append("Uma das referências é a LOGO OFICIAL ATUAL de " + _pn + " — aplique EXATAMENTE "
                                      "esta versão (formas, cores e letras); é PROIBIDO desenhar a logo de " + _pn +
                                      " de memória ou usar identidade/versão antiga dela.")
                    except Exception:
                        pass
                _ref_urls += _ref_urls_tail                 # artes de referência POR ÚLTIMO (são as 1ªs a cair no corte)
                # ── TEXTO EXATO (fix estrutural anti-erro de PT/acento): o modelo NÃO escreve o que "acha",
                # ele COPIA estas strings verbatim. Separa o que é TEXTO-A-RENDERIZAR do que é direção visual.
                _txt_items = [("TÍTULO", (s.get('title') or '').strip()),
                              ("TEXTO", (s.get('body') or s.get('subtitle') or '').strip()),
                              ("BOTÃO/CTA", (s.get('cta') or '').strip())]
                _txt_items = [(rot, v) for rot, v in _txt_items if v]
                _exact = ((
                    "TEXTO DA ARTE — REGRA ABSOLUTA E INEGOCIÁVEL:\n"
                    "1) Os ÚNICOS textos que podem aparecer na arte são as strings entre «» abaixo. NÃO escreva "
                    "NENHUM outro texto, palavra, número, item, legenda, rótulo, detalhe de oferta ou frase que não "
                    "esteja listado aqui.\n"
                    "2) Copie cada string CARACTERE POR CARACTERE, com acentos e pontuação IDÊNTICOS "
                    "(á é í ó ú â ê ô ã õ ç à ü, e as vírgulas, pontos, travessões e dois-pontos). É PROIBIDO "
                    "traduzir, parafrasear, corrigir, abreviar, completar ou inventar.\n"
                    "3) NUNCA quebre nem corte uma palavra no meio: se não couber, reduza a fonte ou quebre a linha "
                    "ENTRE palavras — jamais dentro de uma palavra, e jamais trunque com reticências.\n"
                    "4) As aspas «» são APENAS marcadores que delimitam início e fim de cada texto — NÃO as desenhe "
                    "na arte; renderize somente o conteúdo entre elas.\n"
                    "Renderize EXATAMENTE estes textos e mais nenhum:\n"
                    + "\n".join(f"  {rot}: «{v}»" for rot, v in _txt_items) + "\n"
                ) if _txt_items else "")
                _visual = (f"Direção de CENA (isto NÃO é texto — não escreva na arte, use só como referência visual): "
                           f"{(s.get('visual') or '').strip()}. " if s.get('visual') else "")
                _logo_rule = ("A LOGO entra como IMAGEM de referência — aplique-a EXATAMENTE como está (mesmas letras, "
                              "mesmas cores); é PROIBIDO redesenhar, reescrever, traduzir ou alterar o texto da logo. ")
                if total > 1:
                    _papel = ("CAPA do carrossel: gancho forte e visual de abertura, título dominante — convida a arrastar"
                              if i == 1 else
                              ("TELA FINAL (CTA): fechamento com chamada para ação clara e destacada"
                               if (i == total or stype == "cta") else
                               f"tela de CONTEÚDO {i}/{total}: desenvolve o assunto com hierarquia clara, sem vender"))
                    _estrutura = (f"É um CARROSSEL — respeite a ESTRUTURA de carrossel: esta tela é a {_papel}. "
                                  "Mantenha EXATAMENTE a mesma família visual entre as telas (a tela 1 é a âncora). ")
                else:
                    _estrutura = ("É um POST ÚNICO — composição LIVRE e criativa: você decide o layout com ousadia "
                                  "(sem estrutura de carrossel, sem padrão repetido), mantendo a identidade da marca. ")
                _rprompt = (
                    f"Crie a ARTE COMPLETA e FINAL da tela {i}/{total} de um {('carrossel' if total > 1 else 'post')} "
                    f"de Instagram vertical 4:5 para a marca {company.get('name','')}. Você é o diretor de arte: "
                    "arquitete o LAYOUT (posição/hierarquia/estilo de logo, título, textos, elementos, CTA) com "
                    "sofisticação de agência — mas o CONTEÚDO DE TEXTO é fixo e você só o posiciona/estiliza, não o reescreve. "
                    + _estrutura
                    + _exact                                    # regra forte de texto verbatim (logo no início do conteúdo)
                    + _visual
                    + _logo_rule
                    + ref_ctx["brand"]
                    + (f"CONTEXTO da oferta (use SÓ para entender o tema e compor a CENA/clima — NÃO renderize este "
                       f"texto na arte, NÃO escreva estes detalhes como legenda; o texto visível é apenas o listado "
                       f"acima): {_kb}. " if _kb else "")
                    + "TIPOGRAFIA: use a identidade tipográfica da MARCA (das referências/manual) — NUNCA fonte genérica de IA. "
                    + "As imagens de referência incluem as VERSÕES OFICIAIS da logo — ESCOLHA a versão que melhor se "
                      "integra ao fundo da sua composição e aplique-a LIMPA, sem faixa/painel/retângulo atrás. "
                    + ((f"CONTATO REAL da empresa — inclua INTEGRADO com elegância no rodapé/CTA da arte (tipografia "
                        f"da marca, legível), copiando EXATAMENTE: {ref_ctx['contact']}. NUNCA invente números, site ou @. "
                        ) if (ref_ctx.get("contact") and (total == 1 or i == total or stype == "cta")) else
                       (f"Assinatura discreta opcional no rodapé, copiada exatamente: {ref_ctx['contact'].split(' · ')[-1]}. NUNCA invente contato. "
                        if ref_ctx.get("contact") else ""))
                    + " ".join(_extra) + " Sem marca d'água.")
                # JUIZ DE TEXTO (2 instâncias): a IA cria LIVRE; o OCR LOCAL (grátis, determinístico, nunca
                # recusa) lê a arte; reprovou → a VISÃO confirma (paga só na suspeita). TOLERÂNCIA ZERO:
                # 1 palavra quebrada já reprova ('bawo' em vez de 'baixo' NUNCA passa). A regeração leva
                # FEEDBACK com a palavra errada SOLETRADA → converge, não repete o erro. Guarda a melhor e,
                # se todas quebrarem, entrega a menos ruim com aviso (nunca trava o lote). Sem template.
                _expect = [x for x in [(s.get('title') or '').strip(),
                                       (s.get('body') or s.get('subtitle') or '').strip(),
                                       (s.get('cta') or '').strip()] if x]
                if ref_ctx.get("contact") and (total == 1 or i == total or stype == "cta"):
                    _expect.append(ref_ctx["contact"])   # rodapé exigido no prompt também é julgado (fone/site errado = quebra)
                _best_img, _best_miss = None, None
                try:                                            # uma tentativa paga por padrão; o usuário pode regerar
                    _max_rf = max(1, int(get_setting("judge.max_attempts") or 1))
                except Exception:
                    _max_rf = 1
                if not _expect:
                    _max_rf = 1                                 # sem texto → não precisa reprovar por texto
                _fb = ""
                for _att_rf in range(_max_rf):
                    try:
                        _cand, _rc = await asyncio.to_thread(
                            generate_image_reference_full, _rprompt + _fb, _refs,
                            ("1024x1536" if fmt != "story" else "1024x1536"),
                            None, "medium", _ref_urls)
                        total_cost += (_rc or 0.0)
                    except Exception as _re:
                        img_err = ("estúdio: " + str(_re))[:180]
                        if _att_rf == _max_rf - 1 and _best_img is None:
                            fails.append(img_err)
                        continue
                    _miss, _jc = await asyncio.to_thread(judge_art_text, _cand, _expect)
                    total_cost += (_jc or 0.0)
                    if not _miss:                              # tolerância ZERO — texto 100% certo ou regenera
                        img, img_ok, used_model = _cand, True, get_image_ref_model()
                        break
                    if _best_img is None or len(_miss) < len(_best_miss):
                        _best_img, _best_miss = _cand, _miss    # guarda a menos quebrada
                    if _att_rf < _max_rf - 1:
                        _fb = text_fix_feedback(_miss, _expect)
                        spillovers.append((i, "texto saiu quebrado (" + ", ".join(_miss[:3]) + ") → regenerando com correção soletrada"))
                if not img_ok and _best_img is not None:        # todas quebraram → menos ruim + aviso honesto
                    img, img_ok, used_model = _best_img, True, get_image_ref_model()
                    fails.append("tela " + str(i) + ": texto pode ter erro (" + ", ".join(_best_miss[:3]) + ") — clique regerar")
            if ai_bg and not ref_full and img is None and influencer and inf_photos and stype in ("cover", "cta"):
                # EMOÇÃO + VARIAÇÃO: a IA (visão) escolhe do PORTFÓLIO a foto cuja expressão combina com o texto da tela;
                # exclui as já usadas (capa e CTA pegam fotos diferentes → não fica repetitivo).
                _pi = await asyncio.to_thread(pick_influencer_photo, inf_photos, s.get("title", ""), stype, used_inf_idx)
                used_inf_idx.add(_pi)
                try:   # persiste rotação: marca ESTA foto como recém-usada → próximos posts usam OUTRAS (variedade)
                    import json as _json
                    from ..db import settings_set as _ss
                    from datetime import datetime as _dt, timezone as _tz
                    _rk = "influencer.recent." + (influencer.get("id") or "")
                    _keep = max(0, len(inf_photos) - 2)
                    _rc = ([x for x in _json.loads(get_setting(_rk) or "[]") if x != _pi] + [_pi])[-_keep:] if _keep else []
                    _ss(key=_rk, value=_json.dumps(_rc), updated_at=_dt.now(_tz.utc).isoformat())
                except Exception:
                    pass
                person = inf_photos[_pi]
                _purl = inf_photo_urls[_pi] if _pi < len(inf_photo_urls) else ""
                _ppub = (_render_public_base() + _purl) if _purl.startswith("/") else _purl   # kie edit baixa a foto real
                _scene = (s.get("visual") or "").strip()
                _evt_amb = bool(_event and _scene and stype in ("cover", "cta"))
                pprompt = (
                    "Integre ESTA pessoa real (a foto enviada) numa arte publicitária premium da marca " + company.get("name", "") + ". "
                    "ROSTO — REGRA ABSOLUTA: mantenha o rosto e a EXPRESSÃO 100% IDÊNTICOS à foto; NÃO redesenhe, NÃO suavize, "
                    "NÃO altere traço, formato, barba ou pele. É a MESMA pessoa — o rosto NÃO muda. "
                    "RECORTE: contorno LIMPO e perfeito da pessoa, sem rebarba/serrilhado. NENHUMA outra pessoa na cena (só ela). "
                    "FUNDO (consistência da marca, IGUAL às outras telas): grafite escuro cinematográfico próximo de #141418, "
                    "com glow SUTIL na cor da marca " + brand_color + " e leve textura/profundidade — MESMA paleta e temperatura "
                    "das telas de conteúdo (clima escuro premium). NÃO use fundo claro nem cena realista clara de feira. "
                    + ("Pode SUGERIR sutilmente um ambiente de evento/estande ao fundo, mas SEMPRE nesse tratamento escuro cinematográfico. " if _evt_amb else "")
                    + "COMPOSIÇÃO: deixe ~15% do TOPO totalmente livre (faixa da logo/barra). Pessoa de UM lado; do lado oposto, "
                    "ESPAÇO NEGATIVO escuro pro texto — o texto NUNCA fica sobre a pessoa. "
                    "Vertical " + ("9:16" if fmt == "story" else "4:5") + ", fotográfico premium, alta produção. SEM texto, SEM logo na imagem.")
                _same = False
                try:
                    for _att in range(3):   # o modelo às vezes GERA pessoa genérica em vez de usar a foto → verifica e regenera
                        img, _pc = await asyncio.to_thread(compose_person_scene, person, pprompt, _ppub)
                        total_cost += (_pc or 0.0)
                        _same, _vc = await asyncio.to_thread(verify_same_person, person, img)
                        total_cost += (_vc or 0.0)
                        if _same:
                            break
                        spillovers.append((i, "influencer: rosto genérico → regerando (" + str(_att + 1) + ")"))
                    if not _same:
                        raise ValueError("rosto do influencer não bateu após 3 tentativas")
                    img_ok = True
                    spillovers.append((i, "influencer: " + (influencer.get("name") or "")))
                except Exception as pe:
                    img = None   # DESCARTA o composite com rosto errado (nunca publica pessoa genérica)
                    img_err = ("influencer: " + str(pe))[:160]
                    prompt = _photo_only_prompt(s, company.get("name", ""), (tmpl or {}).get("variant"), brand_color, design_ov, avoid_people=True, palette=_palette_str(colors))
                    spillovers.append((i, "influencer falhou → cena SEM pessoa (não inventa rosto)"))
            if ai_bg and not ref_full and img is None:
                # TRANSBORDO: retry no mesmo modelo p/ erro transitório; se o provedor morreu (saldo/cota),
                # pula pra um modelo EQUIVALENTE de OUTRO provedor (grátis 1º). dead_providers é compartilhado
                # entre as telas → não insiste num provedor morto. Editorial só se a cadeia INTEIRA falhar.
                try:
                    img, cost, used_model = await asyncio.to_thread(
                        generate_image_resilient, prompt, img_size, None, model, None, dead_providers, img_registry)
                    img_ok = True
                    total_cost += (cost or 0.0)
                    if used_model and used_model != model:
                        spillovers.append((i, used_model))     # transbordou nesta tela (modelo diferente do pedido)
                except Exception as ie:
                    img_err = str(ie)[:180]
                    fails.append(img_err)
            # 1b) JUIZ POR VISÃO: confirma a metade LIVRE de pessoa p/ o texto; se NENHUMA, regenera (teto 1).
            #     Só no modo card e com foto NOVA (não no cache). Define text_side; em erro cai pra heurística.
            if img is not None and use_composer and reuse_url is None:
                for _regen in range(3):                       # até 3 fotos até achar um lado LIMPO (vale p/ QUALQUER IA)
                    cs = ""
                    for _vtry in range(2):                    # juiz com 1 retry — cobre erro transitório da visão (não cai cego na heurística)
                        cs, vcost = await asyncio.to_thread(vision_clear_side, img)
                        total_cost += (vcost or 0.0)
                        if cs:
                            break
                    if cs in ("left", "right"):
                        slide_for_render["text_side"] = cs
                        break
                    if _regen < 2:                            # none/sem resposta → gera OUTRA foto (o texto não pode cobrir pessoa/objeto)
                        try:
                            img, _vc, _vm = await asyncio.to_thread(generate_image_resilient, prompt, img_size, None, model, None, dead_providers, img_registry)
                            total_cost += (_vc or 0.0)
                            spillovers.append((i, "regerada: sem lado limpo"))
                        except Exception:
                            break
            # 2) COMPOSIÇÃO (separada da geração; erro aqui degrada pro editorial, nunca derruba o lote).
            if img is not None:
                try:
                    if ref_full:       # ESTÚDIO IA: a arte já vem COMPLETA da IA (logo escolhida, texto, CTA) — sem carimbo
                        png = img
                    elif use_composer:   # Marco 3: foto da IA + CARD de vidro (nível agência, texto legível, logo intacta)
                        png = await asyncio.to_thread(compose_card_slide, slide_for_render, i, total, colors, co_logos, site, handle, img, None, design_ov, slide_app_logos, canvas_size)
                    else:              # legacy ISOLADO: IA já desenhou a arte → carimba logo (+ rodapé de contato no CTA e na ARTE CRIATIVA)
                        png = await asyncio.to_thread(compose_logos_only, img, co_logo, app_legacy, colors, bool(s.get("free_text")))
                        if is_cta or s.get("free_text"):
                            png = await asyncio.to_thread(compose_cta_footer, png, co_logo, site, phone, colors)
                except Exception as ce:
                    img_err = ("compose: " + str(ce))[:180]
                    png = None
            # 3) SALVA a base (foto) p/ CACHE futuro — a base NUNCA entra em carousel_urls (não publica).
            base_out = None
            if img is not None:
                try:
                    bfn = f"{i:02d}_base.png"
                    with open(os.path.join(subdir, bfn), "wb") as bf:
                        bf.write(img)
                    base_out = f"{UPLOAD_URL_PREFIX}/{company_id}/carousel/{hexid}/{bfn}"
                except Exception:
                    base_out = reuse_url
            bases.append(base_out)
            # 4) FALLBACK editorial (grátis) — SÓ no modo composer_only/legado. No ESTÚDIO, falha NUNCA vira
            #    template velho (o cliente receberia a caixa antiga): a tela é reportada e o usuário regenera.
            if png is None and ref_full:
                fails.append(f"tela {i}: Estúdio falhou — gere novamente (não caiu no template antigo)")
                return {"i": i, "slide": None, "base": base_out, "cost": total_cost, "fails": fails, "spills": spillovers}
            if png is None:
                try:
                    png = await asyncio.to_thread(compose_carousel_slide, slide_for_render, i, total, colors, co_logos, site, handle, None, None, design_ov, slide_app_logos)
                except Exception as fe:
                    fails.append(("editorial: " + str(fe))[:180])
                    return {"i": i, "slide": None, "base": base_out, "cost": total_cost, "fails": fails, "spills": spillovers}
            fn = f"{i:02d}.png"
            with open(os.path.join(subdir, fn), "wb") as f:
                f.write(png)
            return {"i": i, "base": base_out, "cost": total_cost, "fails": fails, "spills": spillovers,
                    "slide": {"url": f"{UPLOAD_URL_PREFIX}/{company_id}/carousel/{hexid}/{fn}",
                              "type": s.get("type"), "title": s.get("title", ""), "app": s.get("app") or "",
                              "prompt": prompt, "image_ok": img_ok, "image_error": img_err, "base_url": base_out,
                              "model_used": used_model}}

        # DRIVER: tela 1 primeiro (âncora da família), demais em PARALELO com teto configurável.
        try:
            _par = max(1, int(get_setting("render.parallel") or 4))
        except Exception:
            _par = 4
        _anchor_on = (get_setting("render.anchor") or "1") != "0"   # 0 = TUDO paralelo (sem tela-âncora; +rápido, família via referências)
        _sem = asyncio.Semaphore(_par)

        async def _guarded(_gi, _gs, _au):
            async with _sem:
                return await _render_tela(_gi, _gs, _au)

        if _anchor_on and len(telas) > 1:
            _r1 = await _render_tela(1, telas[0])               # âncora primeiro; demais SIMULTÂNEAS com a base dela
            _tela_res = [_r1] + list(await asyncio.gather(
                *[_guarded(_gi, _gs, _r1.get("base")) for _gi, _gs in enumerate(telas[1:], 2)]))
        else:
            _tela_res = list(await asyncio.gather(
                *[_guarded(_gi, _gs, None) for _gi, _gs in enumerate(telas, 1)]))
        for _tr in _tela_res:                       # agrega NA ORDEM das telas (slides/base_urls alinhados)
            total_cost += _tr["cost"]
            fails += _tr["fails"]
            spillovers += _tr["spills"]
            bases.append(_tr["base"])
            if _tr["slide"] is not None:
                out.append(_tr["slide"])
        # Persiste o carrossel como POST DRAFT (não some ao navegar; aparece em Arquivos/Acervo).
        post_id = None
        if out:
            # LEGENDA (copy + hashtags) p/ publicar no Instagram COM texto, não só imagem.
            cap_copy, cap_tags = "", ""
            try:
                from ..services.ai import generate_carousel_caption
                _cap = await asyncio.to_thread(generate_carousel_caption, company, telas, (telas[0].get("title") if telas else ""))
                cap_copy, cap_tags = _cap.get("copy", ""), _cap.get("hashtags", "")
            except Exception:
                pass
            try:
                _p = post_create({
                    "company_id": company_id, "status": "DRAFT",
                    "title": (telas[0].get("title") if telas else "Carrossel") or "Carrossel",
                    "copy": cap_copy, "hashtags": cap_tags,
                    "networks": ["instagram"], "media_url": out[0]["url"],
                    "meta": {"content_type": ("carousel" if fmt == "carrossel" else ("story" if fmt == "story" else "image")),
                             "fmt": fmt, "carousel_urls": [o["url"] for o in out],
                             "base_urls": bases, "render_mode": render_mode,
                             "model": model or "editorial", "template_id": (tmpl or {}).get("id"),
                             "collab_handle": (inf_handle or "").lstrip("@")},   # @ do influencer p/ collab na publicação
                })
                post_id = _p.get("id")
            except Exception:
                pass
        resp_caption = {"copy": cap_copy, "hashtags": cap_tags} if out else {}
        try:
            from ..db_companies import cost_log_add
            cost_log_add(company_id, "carrossel:" + fmt, model or "editorial", total_cost)
        except Exception:
            pass
        resp = {"model": model or "editorial", "render_mode": render_mode,
                "credits_debited": _blog(company_id, "image", total_cost, model=str(body.get("model") or ""), meta={"mode": render_mode, "telas": total}),
                "cost": usd_to_brl(total_cost), "cost_usd": round(total_cost, 4),
                "currency": "BRL", "count": total, "slides": out, "base_urls": bases, "post_id": post_id,
                "caption": resp_caption}
        if spillovers:   # transbordou: alguma tela usou um modelo diferente do pedido (provedor sem saldo/erro)
            ups = ", ".join(f"tela {idx}→{m}" for idx, m in spillovers[:5])
            resp["spillover"] = (f"{len(spillovers)} tela(s) transbordaram p/ outro modelo (o pedido falhou/sem saldo): "
                                 f"{ups}. Você não perdeu o carrossel — saiu com imagem real.")
        if ai_bg and fails:
            resp["warning"] = (f"O modelo de imagem FALHOU em {len(fails)}/{total} telas mesmo após o transbordo "
                               f"(todos os provedores caíram) → saiu o editorial nessas. Motivo: {fails[0]}")
        return resp
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/kie-recover")
async def kie_recover(request: Request):
    """RESGATE de artes PAGAS na kie: repesca resultados por taskId — do LEDGER em disco (gravado na
    criação de cada task, v1.27.102+) ou de ids colados do painel da kie — baixa as imagens e salva
    como post DRAFT no Acervo da empresa. Plataforma travar/reiniciar ≠ dinheiro perdido."""
    err = _api_key_required(request)
    if err:
        return err
    import asyncio
    import json as _json
    import time as _tm
    body = await request.json()
    company_id = (body.get("company_id") or "").strip()
    if not company_get(company_id):
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    ids = [str(x).strip() for x in (body.get("task_ids") or []) if str(x).strip()]
    minutes = int(body.get("minutes") or 180)
    if not ids:
        led = os.path.join(os.path.dirname(os.environ.get("ADULT_META_DB_PATH", "/data/runs.db")), "kie_tasks.jsonl")
        try:
            cut = _tm.time() - minutes * 60
            with open(led) as f:
                for ln in f:
                    try:
                        d = _json.loads(ln)
                        if float(d.get("ts") or 0) >= cut and d.get("task_id"):
                            ids.append(d["task_id"])
                    except Exception:
                        pass
        except Exception:
            pass
    ids = list(dict.fromkeys(ids))[-40:]
    if not ids:
        return JSONResponse({"detail": "Sem taskIds. Cole os ids do painel da kie em task_ids "
                                       "(o ledger automático só cobre tasks criadas da v1.27.102 em diante)."},
                            status_code=422)
    from ..services.ai import kie_fetch_result
    saved, misses, n = [], [], 0
    hexid = _uuid.uuid4().hex
    subdir = os.path.join(UPLOAD_DIR, company_id, "carousel", hexid)
    os.makedirs(subdir, exist_ok=True)
    for tid in ids:
        try:
            png = await asyncio.to_thread(kie_fetch_result, tid)
        except Exception as e:
            misses.append(tid[:14] + ": " + str(e)[:60])
            continue
        if not png:
            misses.append(tid[:14] + ": sem resultado (ainda processando ou task falhou)")
            continue
        n += 1
        fn = f"{n:02d}.png"
        with open(os.path.join(subdir, fn), "wb") as f:
            f.write(png)
        saved.append(f"{UPLOAD_URL_PREFIX}/{company_id}/carousel/{hexid}/{fn}")
    post_id = None
    if saved:
        try:
            _p = post_create({"company_id": company_id, "status": "DRAFT",
                              "title": "Resgate kie — " + str(len(saved)) + " arte(s) recuperada(s)",
                              "networks": ["instagram"], "media_url": saved[0],
                              "meta": {"content_type": "carousel", "carousel_urls": saved, "recovered": True}})
            post_id = _p.get("id")
        except Exception:
            pass
    return {"ok": True, "recovered": len(saved), "urls": saved, "post_id": post_id, "misses": misses}


@router.post("/ai-models")
async def set_ai_model(request: Request):
    """Set the default image model (and provider) used for generation."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from datetime import datetime, timezone
    from ..db import settings_set
    now = datetime.now(timezone.utc).isoformat()
    if "image_model" in body:
        m = (body.get("image_model") or "").strip()
        settings_set(key="image.model", value=m, updated_at=now)
        # prefixo decide o provedor: kie:/omni:/cometapi:/piapi:; slug com "/" → OpenRouter; senão OpenAI
        settings_set(key="image.provider",
                     value=("kie" if m.startswith("kie:")
                            else "omniroute" if m.startswith("omni:")
                            else "cometapi_gemini" if m.startswith("cometapi-gemini:")
                            else "cometapi" if m.startswith("cometapi:")
                            else "piapi" if m.startswith("piapi:")
                            else ("openrouter" if "/" in m else "openai")),
                     updated_at=now)
    if "video_model" in body:
        vm = (body.get("video_model") or "").strip()
        settings_set(key="video.model", value=vm, updated_at=now)
        # 'cometapi:' → CometAPI · slug com '/' → OpenRouter · senão OpenAI (Sora)
        settings_set(key="video.provider",
                     value=("kie" if vm.startswith("kie:")
                            else "omniroute" if vm.startswith("omni:")
                            else "cometapi" if vm.startswith("cometapi:")
                            else ("openrouter" if "/" in vm else "openai")),
                     updated_at=now)
    if "image_ref_model" in body:                                 # ESTÚDIO IA (motor de arte) — escolha do provedor
        rm = (body.get("image_ref_model") or "").strip()
        settings_set(key="image_ref.model", value=rm, updated_at=now)
        settings_set(key="image_ref.provider",
                     value=("kie" if rm.startswith("kie:")
                            else "omniroute" if rm.startswith("omni:")
                            else "cometapi" if rm.startswith("cometapi:")
                            else "openrouter"),
                     updated_at=now)
    return {"ok": True, "image_current": get_setting("image.model"), "video_current": get_setting("video.model"),
            "image_ref_current": get_setting("image_ref.model")}


@router.post("/generate-video")
async def generate_post_video(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company_id = body.get("company_id")
    if not company_id:
        return JSONResponse({"detail": "company_id é obrigatório"}, status_code=422)
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    provider_config = get_video_config((body.get("model") or "").strip() or None)
    if not provider_config:
        return JSONResponse({"detail": "Geração de vídeo não configurada (chave OpenAI)."}, status_code=400)
    theme = (body.get("theme") or body.get("briefing") or "").strip()
    video_prompt = (body.get("video_prompt") or body.get("visual_prompt") or "").strip()
    scenes = max(1, min(int(body.get("scenes") or 3), 6))      # nº de clipes a juntar
    seconds = str(body.get("seconds") or "8")                  # duração de cada clipe
    size = body.get("size") or "720x1280"
    try:
        import asyncio
        try:
            per_seconds = max(1, int(float(seconds)))
        except Exception:
            per_seconds = 8
        storyboard = await asyncio.to_thread(
            build_video_storyboard, company, theme, video_prompt, scenes * per_seconds, scenes, per_seconds
        )
        prompts = [s.get("prompt") for s in (storyboard or []) if isinstance(s, dict) and s.get("prompt")]
        prompts = prompts[:scenes] or [build_video_prompt(company, theme, video_prompt)]
        jobs = []
        for sp in prompts:
            j = await asyncio.to_thread(
                create_video_job, sp, seconds, size, None, provider_config.get("model"),
                "9:16", None, provider_config,
            )
            jid = j.get("id") or j.get("job_id") or j.get("task_id")
            if jid:
                jobs.append(jid)
        if not jobs:
            return JSONResponse({"detail": "Não consegui criar os clipes de vídeo."}, status_code=502)
        return {"jobs": jobs, "count": len(jobs), "scenes": len(prompts)}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


def _video_job_dir(company_id: str) -> str:
    d = os.path.join(UPLOAD_DIR, company_id, "video")
    os.makedirs(d, exist_ok=True)
    return d


def _video_status_write(path: str, payload: Dict[str, Any]) -> None:
    """Publica status atomicamente; o polling nunca enxerga JSON pela metade."""
    tmp = path + ".tmp-" + _uuid.uuid4().hex
    try:
        import json as _json
        with open(tmp, "w") as f:
            _json.dump(payload, f)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _render_branded_video_job(company_id: str, jid: str, scene_prompts: list, seg_secs: list,
                              cta: dict, colors: dict, co_logos, site: str, handle: str, base_url: str,
                              audio_plan: dict = None, app_logos: dict = None,
                              carousel_first_frame_url: Optional[str] = None,
                              target_total_seconds: Optional[int] = None,
                              provider_config: Optional[Dict[str, Any]] = None) -> None:
    """BACKGROUND: gera as cenas EM SEQUÊNCIA com continuidade (último frame → first_frame da próxima),
    baixa, e monta o vídeo branded. Escreve o progresso/custo num .json. SÓ roda quando o usuário confirma.
    carousel_first_frame_url → apenas na cena 1, herda a identidade visual da capa do carrossel aprovado
    do mesmo app (Frente 4). target_total_seconds → duração total alvo (best-effort, repassado a provedores
    que suportam campo distinto de por-clipe)."""
    import json as _json, time as _time
    from ..services.ai import (create_video_job, get_video_job, download_video, get_video_config,
                               video_model_id_from_config, video_estimated_clip_cost)
    from ..services.video_composer import compose_branded_video, last_frame_png
    jdir = _video_job_dir(company_id)
    sp_path = os.path.join(jdir, jid + ".json")

    def _w(d):
        try:
            _video_status_write(sp_path, d)
        except Exception:
            pass

    def _pub(p):
        return base_url + UPLOAD_URL_PREFIX + p[len(UPLOAD_DIR):]

    total = len(scene_prompts)
    clips, cost, usage_cost, first_frame_url = [], 0.0, 0.0, None
    credits_used = 0.0                                        # kie.ai cobra em créditos (somados das cenas)
    cost_source = "provider_usage"
    try:
        provider_config = dict(provider_config or get_video_config() or {})
        provider_name = provider_config.get("provider") or "video"
        provider_model_id = video_model_id_from_config(provider_config)
        max_polls = 120 if provider_name == "cometapi" else 60

        def _usage_or_estimated(payload, sec):
            nonlocal cost_source
            raw = (payload.get("usage") or {}).get("cost") if isinstance(payload, dict) else None
            try:
                val = float(raw or 0)
            except Exception:
                val = 0.0
            if val > 0:
                return val, "provider_usage"
            est = video_estimated_clip_cost(provider_model_id, sec)
            if est > 0:
                cost_source = "catalog_estimate"
            return est, "catalog_estimate"

        for i, sp in enumerate(scene_prompts):
            # segundos POR CLIPE (video_segment_plan agora devolve a lista). Fallback ao último/8.
            cur_sec = seg_secs[i] if (isinstance(seg_secs, list) and i < len(seg_secs)) else \
                ((seg_secs[-1] if (isinstance(seg_secs, list) and seg_secs) else (seg_secs or 8)))
            # cena 1: usa a capa do carrossel aprovado do mesmo app (P-D visão) quando disponível;
            # demais cenas: continuidade normal (último frame da anterior). NUNCA combina os dois.
            scene_first_frame = (carousel_first_frame_url if i == 0 else None) or first_frame_url
            _w({"status": "generating", "scene": i + 1, "total": total, "provider": provider_name,
                "provider_model": provider_model_id, "cost_usd": round(cost, 2), "cost_source": cost_source})
            job = create_video_job(
                sp, str(cur_sec or ""), "720x1280", scene_first_frame, provider_config.get("model"),
                target_seconds=target_total_seconds, config_override=provider_config,
            )
            jid2 = job.get("id") or job.get("job_id") or job.get("task_id")
            if not jid2:
                raise ValueError(f"sem job id na cena {i + 1}")
            status0 = str(job.get("status") or "").lower()
            _w({"status": "generating", "scene": i + 1, "total": total, "provider": provider_name,
                "provider_job_id": jid2, "provider_status": status0 or "created",
                "provider_progress": job.get("progress"), "provider_model": provider_model_id,
                "cost_usd": round(cost, 2), "cost_source": cost_source})
            done = status0 in ("completed", "succeeded", "success", "done")
            if done:
                scene_cost, src = _usage_or_estimated(job, cur_sec)
                cost += scene_cost
                if src == "provider_usage":
                    usage_cost += scene_cost
            else:
                for _ in range(max_polls):                       # OpenRouter ~15min; CometAPI pode demorar mais
                    _time.sleep(15)
                    st = get_video_job(jid2, provider_config)
                    status = str(st.get("status") or "").lower()
                    _w({"status": "generating", "scene": i + 1, "total": total, "provider": provider_name,
                        "provider_job_id": jid2, "provider_status": status,
                        "provider_progress": st.get("progress"), "provider_model": provider_model_id,
                        "cost_usd": round(cost, 2), "cost_source": cost_source})
                    if status in ("completed", "succeeded", "success", "done"):
                        scene_cost, src = _usage_or_estimated(st, cur_sec)
                        cost += scene_cost
                        if src == "provider_usage":
                            usage_cost += scene_cost
                        try:
                            credits_used += float(st.get("creditsConsumed") or 0)   # kie: crédito real da cena
                        except Exception:
                            pass
                        done = True; break
                    if status in ("failed", "error", "canceled", "cancelled"):
                        raise ValueError(f"cena {i + 1} falhou no provedor")
            if not done:
                raise ValueError(f"cena {i + 1} demorou demais")
            cp = os.path.join(jdir, f"{jid}_c{i}.mp4")
            with open(cp, "wb") as f:
                f.write(download_video(jid2, provider_config))
            try:
                clip_seconds = max(1.0, float(cur_sec or 0))
            except Exception:
                clip_seconds = 0.0
            clips.append({"path": cp, "seconds": clip_seconds})
            lf = os.path.join(jdir, f"{jid}_f{i}.png")           # último frame → first_frame da próxima (continuidade)
            first_frame_url = _pub(lf) if last_frame_png(cp, lf) else None
        _w({"status": "composing", "scene": total, "total": total,
            "cost_usd": round(cost, 2), "cost_source": cost_source})
        out = os.path.join(jdir, jid + ".mp4")
        # CENAS: o que o modelo gerou (imagem + áudio do modelo), sem overlay/legenda/grade da IA.
        # CTA FIXO no fim: card APROVADO (imagem, NÃO gerada por IA) — determinístico, igual pra todo vídeo.
        clip_paths = [c.get("path") for c in clips if c.get("path") and os.path.exists(c.get("path"))]
        if not clip_paths:
            raise ValueError("nenhum clipe gerado")
        # ── CTA POR EMPRESA ── fonte: setting 'video.cta_card_url.<company_id>' (por cliente) → setting global
        # 'video.cta_card_url' → asset commitado video_cta.png (que é o card da CARIAP — SÓ pra CARIAP, nunca
        # vaza pra outro cliente). Vazio/falha → vídeo SEM CTA (não quebra a entrega).
        try:
            import httpx as _hx
            from ..services.ai import get_setting as _gs
            from ..services.video_composer import cta_endcard_clip
            _src = ((_gs("video.cta_card_url." + company_id) or "").strip()
                    or (_gs("video.cta_card_url") or "").strip())
            _cta_img = None
            if _src.startswith("http"):
                _r = _hx.get(_src, timeout=_hx.Timeout(30.0, connect=10.0))
                if _r.status_code < 400 and _r.content:
                    _cta_img = os.path.join(jdir, jid + "_ctacard.png")
                    with open(_cta_img, "wb") as _cf:
                        _cf.write(_r.content)
            elif _src and os.path.exists(_src):
                _cta_img = _src
            else:
                _is_cariap = False
                try:
                    from ..db_companies import company_get as _cg
                    _is_cariap = ((_cg(company_id) or {}).get("name") or "").strip().upper() == "CARIAP"
                except Exception:
                    pass
                _def = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "video_cta.png")
                _cta_img = _def if (_is_cariap and os.path.exists(_def)) else None
            if _cta_img:
                _cta_mp4 = os.path.join(jdir, jid + "_cta.mp4")
                if cta_endcard_clip(_cta_img, _cta_mp4, 3.0) and os.path.exists(_cta_mp4):
                    clip_paths.append(_cta_mp4)
        except Exception:
            pass
        from ..services.video_composer import concat_raw_clips
        if not concat_raw_clips(clip_paths, out):
            raise ValueError("falha ao entregar o vídeo")
        # DUBLAGEM pt-BR: o modelo às vezes fala INGLÊS/pt-PT. Substitui o áudio do modelo pela NARRAÇÃO TTS
        # pt-BR do briefing (audio_plan.script) — voz consistente e SEMPRE pt-BR. _mux_audio mapeia só [a] novo
        # (descarta o áudio do modelo). Sem script/falha → mantém o áudio do modelo (não quebra a entrega).
        try:
            _ap = audio_plan or {}
            _script = (_ap.get("script") or "").strip()
            if _ap.get("mode") in ("narration", "both") and _script:
                from ..services.ai import tts_synthesize
                from ..services.video_composer import _mux_audio
                _narr = os.path.join(jdir, jid + "_narr.mp3")
                if tts_synthesize(_script, _narr, (_ap.get("voice") or "onyx")) and os.path.exists(_narr):
                    _dub = os.path.join(jdir, jid + "_dub.mp4")
                    if _mux_audio(out, _dub, _narr, None) and os.path.exists(_dub):
                        os.replace(_dub, out)            # entrega com a locução pt-BR no lugar do inglês do modelo
        except Exception:
            pass
        try:                                          # APRENDE o preço real (usage.cost/cena) p/ a próxima previsão bater
            if total and usage_cost > 0:
                from ..services.ai import get_setting as _gs
                from ..db import settings_set as _ss
                from datetime import datetime, timezone
                _m = _gs("video.model") or ""
                if _m:
                    _ss(key="video.price." + _m, value=str(round(usage_cost / total, 4)),
                        updated_at=datetime.now(timezone.utc).isoformat())
        except Exception:
            pass
        _w({"status": "done", "url": _pub(out), "cost_usd": round(cost, 2),
            "cost_source": cost_source, "scenes": total,
            "is_credits": provider_name == "kie", "credits_used": round(credits_used, 1)})
    except Exception as e:
        _w({"status": "error", "detail": str(e)[:300],
            "cost_usd": round(cost, 2), "cost_source": cost_source})



def _render_studio_video_job(company_id: str, jid: str, theme: str, video_prompt: str,
                             target_seconds: int, base_url: str) -> None:
    """ESTÚDIO VÍDEO (receita validada v5-v7): roteiro simples → keyframes com identidade (reference_full)
    → Veo3 anima (voz nativa, enableTranslation OFF) → crossfade. REGRAS DE OURO: toda a FALA numa cena só
    (voz única); demais cenas = b-roll sem voz; ZERO overlay de código (identidade vem dos keyframes)."""
    import json as _json
    import math as _math
    import time as _time
    import httpx as _hx
    from ..services.ai import (generate_image_reference_full, cheap_text_config, get_ai_config,
                               complete_ai, extract_json, _kie_key, _KIE_BASE, get_setting as _gs)
    from ..services.video_composer import _ff
    from ..db_companies import product_list as _pl, company_list as _cl, company_get as _cg
    jdir = _video_job_dir(company_id)
    sp_path = os.path.join(jdir, jid + ".json")

    def _w(d):
        try:
            _video_status_write(sp_path, d)
        except Exception:
            pass

    def _pub(pth):
        return base_url + UPLOAD_URL_PREFIX + pth[len(UPLOAD_DIR):]

    try:
        company = _cg(company_id) or {}
        bk = company.get("brand_kit") or {}
        pal = ", ".join(f"{k} {v}" for k, v in ((bk.get("colors") or {}).items()) if v)
        n = max(1, min(4, _math.ceil((target_seconds or 15) / 8.0)))
        _w({"status": "generating", "scene": 0, "total": n, "provider": "estudio", "note": "roteiro"})
        # 1) ROTEIRO simples: 1 fala completa + cenas visuais (pedido do usuário é a estrela)
        cfg = cheap_text_config(get_ai_config())
        _kb = ""
        try:
            _tl = (theme or "").lower()
            for _co in (_cl() or []):
                for _p in (_pl(_co["id"]) or []):
                    _nm = (_p.get("name") or "").strip()
                    if _nm and _nm.lower() in _tl:
                        _kb += f" [{_nm}] " + (_p.get("description") or "") + " " + (_p.get("objective") or "")
        except Exception:
            pass
        sysm = "Você é diretor de comerciais curtos. Responda SÓ JSON válido pt-BR."
        usr = (f"Empresa: {company.get('name','')} ({(company.get('segment') or '').strip()}). "
               f"Público: {(bk.get('audience') or '')[:200]}. PEDIDO DO CLIENTE (respeite e enriqueça): {theme}. "
               + (f"Contexto real: {_kb[:800]}. " if _kb.strip() else "")
               + (f"Direção extra: {video_prompt}. " if video_prompt else "")
               + f'Monte um comercial de {n} cenas de 8s. Formato: {{"fala":"depoimento/locução COMPLETA em 1-2 frases '
                 f'curtas (cabe em 7s falado), pt-BR","persona":"quem aparece (pessoa realista OU mascote/personagem '
                 f'3D estilizado — escolha o que combina com a marca)","cenas":[{{"kf":"descrição do frame de abertura '
                 f'da cena","mov":"o que acontece/câmera"}}]}} com EXATAMENTE {n} cenas.')
        data = extract_json(complete_ai(cfg, sysm, usr, 1400)) or {}
        fala = (data.get("fala") or theme or "").strip()
        persona = (data.get("persona") or "pessoa condizente com a marca").strip()
        cenas = [c for c in (data.get("cenas") or []) if isinstance(c, dict)][:n]
        while len(cenas) < n:
            cenas.append({"kf": f"cena da marca {company.get('name','')} sobre {theme}", "mov": "câmera suave"})
        # 2) REFERÊNCIAS: logos da empresa + logos de produtos citados (catálogo compartilhado)
        refs = []
        for _lp in (_all_raster_logos(asset_list_logos(company_id)) or [])[:3]:
            try:
                refs.append(open(_lp, "rb").read())
            except Exception:
                pass
        try:
            _tl = (theme or "").lower()
            for _co in (_cl() or []):
                for _p in (_pl(_co["id"]) or []):
                    _nm = (_p.get("name") or "").strip().lower()
                    if _nm and _nm in _tl:
                        for _lp in (_all_raster_logos(asset_list_logos(_co["id"], _p["id"])) or [])[:1]:
                            refs.append(open(_lp, "rb").read())
        except Exception:
            pass
        IDENT = (f"Identidade da marca {company.get('name','')}: {(bk.get('visual_prompt_base') or '').strip()} "
                 + (f"Paleta oficial: {pal}. " if pal else "")
                 + f"Personagem: {persona} (o MESMO em todas as cenas). "
                 "As LOGOS das referências aparecem INTEGRADAS à cena de forma natural (telão/painel/ambiente) — nunca "
                 "carimbo artificial. Vertical 9:16 cinematográfico, frame de abertura de vídeo, alta qualidade.")
        # 3) KEYFRAMES consistentes (kf N referencia o anterior)
        kf_urls = []
        prev = None
        for i, c in enumerate(cenas, 1):
            _w({"status": "generating", "scene": i, "total": n, "provider": "estudio", "note": f"keyframe {i}/{n}"})
            kf, _ = generate_image_reference_full(IDENT + " Cena " + str(i) + ": " + (c.get("kf") or ""),
                                                  refs + ([prev] if prev else []), size="1024x1536")
            fp = os.path.join(jdir, f"{jid}_kf{i}.png")
            with open(fp, "wb") as f:
                f.write(kf)
            prev = kf
            kf_urls.append(_pub(fp))
        # 4) VEO3 anima cada cena (fala SÓ na cena 1 = voz única; tradução OFF = fala literal)
        key = _kie_key()
        H = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        clips = []
        for i, c in enumerate(cenas, 1):
            _w({"status": "generating", "scene": i, "total": n, "provider": "veo3", "note": f"animando cena {i}/{n}"})
            if i == 1:
                mprompt = (f"{persona} olha para a câmera e fala TODA a frase com voz natural em português do Brasil: "
                           f"'{fala}'. {c.get('mov') or ''} Som ambiente discreto, trilha leve.")
            else:
                mprompt = (f"B-roll SEM NENHUMA fala e SEM voz: {c.get('mov') or c.get('kf') or ''}. "
                           "Áudio: APENAS trilha musical, sem vozes.")
            r = _hx.post("https://api.kie.ai/api/v1/veo/generate", headers=H,
                         json={"prompt": mprompt, "model": "veo3_fast", "aspectRatio": "9:16",
                               "imageUrls": [kf_urls[i - 1]], "enableTranslation": False}, timeout=30)
            tid = ((r.json() or {}).get("data") or {}).get("taskId")
            if not tid:
                raise ValueError("veo não aceitou a cena " + str(i) + ": " + r.text[:120])
            ok_clip = None
            for _ in range(150):
                _time.sleep(6)
                d = ((_hx.get(f"https://api.kie.ai/api/v1/veo/record-info?taskId={tid}", headers=H,
                              timeout=25).json() or {}).get("data") or {})
                fl = d.get("successFlag")
                if fl in (1, "1"):
                    urls = (d.get("response") or {}).get("resultUrls") or []
                    if isinstance(urls, str):
                        try:
                            urls = _json.loads(urls)
                        except Exception:
                            urls = [urls]
                    if urls:
                        cp = os.path.join(jdir, f"{jid}_c{i}.mp4")
                        with open(cp, "wb") as f:
                            f.write(_hx.get(urls[0], timeout=180).content)
                        ok_clip = cp
                    break
                if fl in (2, "2", 3, "3"):
                    raise ValueError("veo falhou na cena " + str(i) + ": " + str(d.get("errorMessage") or "")[:120])
            if not ok_clip:
                raise ValueError("veo timeout na cena " + str(i))
            clips.append(ok_clip)
        # 5) MONTAGEM: crossfade progressivo (fala→trilha; sem overlay de código)
        _w({"status": "composing", "scene": n, "total": n, "note": "montagem"})
        import subprocess as _sub

        def _dur(pth):
            o = _sub.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", pth],
                         capture_output=True, text=True)
            try:
                return float(o.stdout.strip() or 0)
            except Exception:
                return 8.0
        cur = clips[0]
        for k, nxt in enumerate(clips[1:], 1):
            outp = os.path.join(jdir, f"{jid}_x{k}.mp4")
            d1 = _dur(cur)
            fc = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v0];"
                  "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v1];"
                  f"[v0][v1]xfade=transition=fade:duration=0.9:offset={max(0.1, d1 - 0.9):.2f}[vout];"
                  "[0:a][1:a]acrossfade=d=1.2:c1=tri:c2=tri[aout]")
            if not _ff(["-i", cur, "-i", nxt, "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", outp], timeout=300):
                raise ValueError("falha na montagem (xfade)")
            cur = outp
        final = os.path.join(jdir, jid + ".mp4")
        os.replace(cur, final)
        est = float(_gs("video.est_usd_per_scene") or 0.15) * n
        try:
            from ..services.billing import log_usage as _bl
            _bl(company_id, "video", est, provider="kie", model="veo3_fast", meta={"scenes": n, "engine": "estudio"})
        except Exception:
            pass
        _w({"status": "done", "url": _pub(final), "cost_usd": round(est, 2), "scenes": n,
            "engine": "estudio", "fala": fala[:160]})
    except Exception as e:
        _w({"status": "error", "detail": str(e)[:300], "engine": "estudio"})


@router.post("/generate-branded-video")
async def generate_branded_video(request: Request):
    """Dispara (em background) a geração de um vídeo BRANDED com continuidade. Retorna o job + preflight de custo.
    A geração só roda após o usuário confirmar (o front mostra o preflight antes)."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    company = company_get(body.get("company_id"))
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    _dscope = __cad__(request, company.get("id"))
    if _dscope:
        return _dscope
    from ..services.ai import (get_video_config, build_video_storyboard, build_video_audio_plan,
                               video_model_max_seconds, video_scene_count, video_segment_plan,
                               video_model_id_from_config)
    requested_model = (body.get("model") or "").strip() or None
    _provider_config = dict(get_video_config(requested_model) or {})
    if not _provider_config:
        return JSONResponse({"detail": "Escolha o modelo de vídeo no painel de IA antes."}, status_code=400)
    _selected_model_id = requested_model or video_model_id_from_config(_provider_config)
    cid = company["id"]
    theme = (body.get("theme") or body.get("briefing") or "").strip()
    video_prompt = (body.get("video_prompt") or body.get("visual_prompt") or "").strip()
    # DURAÇÃO É A RÉGUA MESTRA (8/15/30/60). Define segundos POR CLIPE + nº de cenas → custo BOUNDED (clipes × per).
    # MESMA lógica do video-preflight. NUNCA manda o total como duração de cada clipe (era o bug que multiplicava o custo).
    import math as _math
    try:
        # total escolhido pelo usuário (0 = livre). "scene_seconds" é só hint de UI;
        # nunca use segundos por cena como duração total, senão 15/30/60s descartam cenas.
        target = int(float(body.get("target_seconds") if body.get("target_seconds") is not None else body.get("seconds") or 0))
    except Exception:
        target = 0
    # ── ENGINE ESTÚDIO (default): pedido simples + duração → receita validada (keyframes com identidade +
    # Veo3 voz nativa + crossfade). Legado disponível via setting video.engine=legacy.
    from ..services.billing import feature_enabled as _fe
    if not _fe(company, "video"):
        return JSONResponse({"detail": "Função não liberada no seu plano. Chame o seu consultor de vendas.", "error": "feature_blocked"}, status_code=403)
    # O motor Estúdio/Veo é uma receita fixa e só pode ser usado quando o admin
    # o escolheu explicitamente. O antigo default "estudio" ignorava por completo
    # o modelo selecionado pelo usuário.
    if not requested_model and (get_setting("video.engine") or "selected").strip().lower() == "estudio":
        from ..services.billing import check_credits as _ck
        _dn = _ck(cid)
        if _dn:
            return JSONResponse({"detail": _dn, "error": "no_credits"}, status_code=402)
        import uuid as _uuid
        jid = _uuid.uuid4().hex
        _n_est = max(1, min(4, _math.ceil((target or 15) / 8.0)))
        _burl = _render_public_base()   # base PÚBLICA (kie precisa baixar os keyframes; request.base_url pode ser localhost)
        import threading as _th2
        _th2.Thread(target=_render_studio_video_job,
                    args=(cid, jid, theme, video_prompt, target or 15, _burl), daemon=True).start()
        return {"job": jid, "scenes": _n_est, "engine": "estudio"}
    mx = video_model_max_seconds(_selected_model_id)          # máx de segundos POR CLIPE do modelo confirmado
    n_hint = video_scene_count(target, mx, ai_count=max(0, len(body.get("storyboard") or []))) if target > 0 else 0
    per_hint = max(1, min(mx, round(target / n_hint))) if n_hint else (mx or 8)
    _edited = [d for d in (body.get("scene_descs") or []) if isinstance(d, str) and d.strip()]
    if _edited:                                               # usuário editou o roteiro por cena → usa os prompts como estão (já completos)
        prompts = [d.strip() for d in _edited]
    else:
        prompts = [p for p in (body.get("storyboard") or []) if isinstance(p, str) and p.strip()]
        if not prompts:
            try:                                              # roteiro CASADO com a duração
                sb = await asyncio.to_thread(build_video_storyboard, company, theme, video_prompt, target, n_hint, per_hint, (body.get("style") or "").strip())
            except Exception:
                sb = []
            prompts = [s.get("prompt") for s in (sb or []) if s.get("prompt")]
    segs_per_cli = [mx or 8]                                  # default (livre): 1 clipe no máx do modelo
    if target > 0:                                            # respeita o nº de cenas do roteiro; segundos somam ≈ duração travada
        k, segs = video_segment_plan(target, mx, len(prompts))
        prompts = (prompts or [video_prompt or theme or f"Cena da marca {company.get('name','')}"])[:k]
        # NÃO duplica mais prompts[0] (bug do "3 cenas viram 1"): respeita o que a IA gerou;
        # se vieram MENOS cenas que o mínimo, redistribuía duração dentro do que veio (sem inventar cena).
        segs_per_cli = segs[:len(prompts)] if len(prompts) <= len(segs) else segs
        if len(segs_per_cli) < len(prompts):                  # segurança: completa só com segs válidos
            segs_per_cli = list(segs) + [segs[-1]] * (len(prompts) - len(segs))
    else:
        prompts = prompts[:8] or [video_prompt or theme or f"Cena da marca {company.get('name','')}"]
        segs_per_cli = [mx or 8] * len(prompts)
    n = len(prompts)                                          # nº de clipes que serão gerados (= caixas do roteiro)
    if not isinstance(segs_per_cli, list):                   # blindagem: aceita int legado
        segs_per_cli = [segs_per_cli] * n
    segs_per_cli = (segs_per_cli + [segs_per_cli[-1] if segs_per_cli else (mx or 8)] * n)[:n] or [mx or 8]  # 1 seg por clipe
    # ÁUDIO ditado pelo BRIEFING (modo + roteiro de locução + vibe da trilha). Custo-seguro: falha → mudo.
    try:
        audio_plan = await asyncio.to_thread(build_video_audio_plan, company, theme, video_prompt, max(1, sum(segs_per_cli)))
    except Exception:
        audio_plan = {"mode": "none"}
    colors = (company.get("brand_kit") or {}).get("colors") or {}
    co_logos = _all_raster_logos(asset_list_logos(cid)) or []        # TODAS as variantes da marca (motor escolhe por fundo)
    # APP EM FOCO = o que o usuário marcou (body.apps) OU o app citado no TEMA (ex.: deezer). NUNCA pega
    # arbitrário (era o bug que carimbava e-saúde). Se nada casar → sem logo de app (não inventa).
    import unicodedata as _ud
    def _norm(s):
        s = _ud.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _ud.combining(c)).replace(" ", "").replace("-", "")
    _focus_names = [a.strip() for a in (body.get("apps") or []) if (a or "").strip()]
    _tn = _norm(theme)
    _prods = product_list(cid) or []
    if _focus_names:
        _match = [p for p in _prods if (p.get("name") or "").strip().lower() in {a.lower() for a in _focus_names}]
    else:
        _match = [p for p in _prods if _norm(p.get("name")) and _norm(p.get("name")) in _tn]
    app_logos = {}
    for _p in _match[:1]:                                            # SÓ o app em foco → nunca carimba app errado
        _lps = _all_raster_logos(asset_list_logos(cid, _p["id"]))
        if _lps:
            app_logos[(_p.get("name") or "").strip().lower()] = _lps
    site = (company.get("website") or "").strip()
    handle = ((company.get("socials") or {}).get("instagram") or "").strip()
    phone_raw = "".join(ch for ch in (company.get("phone") or "") if ch.isdigit())
    phone = (f"({phone_raw[:2]}) {phone_raw[2:7]}-{phone_raw[7:]}" if len(phone_raw) == 11 else (company.get("phone") or "")).strip()
    # CTA determinístico: vídeo não deixa CTA/copy final na mão da IA. O código desenha o card,
    # carimba logo oficial e usa CTA do estado do cliente quando existir.
    _app_focus = (_match[0].get("name") or "").strip() if _match else ""
    _cta_btn = (body.get("cta") or "").strip() or "Fale com a gente"
    _brand = (company.get("name") or "a gente").strip()
    cta = {"eyebrow": (_app_focus or company.get("segment") or "").strip(),
           "title": f"Fale com a {_brand}" if _brand.lower() not in ("a gente", "gente") else "Fale com a gente",
           "subtitle": (f"Leve {_app_focus} para sua base de clientes." if _app_focus else ""),
           "cta": _cta_btn}
    if body.get("cta_title"):
        cta["title"] = str(body.get("cta_title")).strip()
    if body.get("cta"):
        cta["cta"] = str(body.get("cta")).strip()
    cta["phone"] = phone
    jid = _uuid.uuid4().hex
    base_url = str(request.base_url).rstrip("/")
    # Os provedores de vídeo (OpenRouter/Comet) BAIXAM o frame de continuidade por HTTP externo.
    # Atrás do traefik, request.base_url volta http:// e o /uploads só responde em https → 404 no fetch
    # do frame → a cena falha mas a anterior já gerou e COBROU. Força https (exceto host local de dev).
    if base_url.startswith("http://") and not any(h in base_url for h in ("localhost", "127.0.0.1", "0.0.0.0")):
        base_url = "https://" + base_url[len("http://"):]
    # Frente 4 — capa do carrossel APROVADO do mesmo app como first_frame da cena 1 (herda identidade visual).
    # Knob on/off: setting 'video.use_carousel_ref' (default ON). Salva em uploads/company/video/jid_cover.png.
    carousel_first_frame_url: Optional[str] = None
    # kie IGNORA first_frame (no-op) → nem busca a capa nesse provedor; a identidade vem da VISÃO no roteiro.
    # Snapshot imutável: este render inteiro usa exatamente o modelo confirmado
    # no preflight, mesmo se outro usuário mudar o default enquanto ele roda.
    _vprov = _provider_config.get("provider") or ""
    try:
        if _vprov != "kie" and (get_setting("video.use_carousel_ref") or "1") != "0":
            from ..services.ai import _video_find_approved_carousel_images
            covers = _video_find_approved_carousel_images(company, theme, limit=1)
            if covers:
                _jdir = _video_job_dir(cid)
                _cover_path = os.path.join(_jdir, jid + "_cover.png")
                with open(_cover_path, "wb") as _f:
                    _f.write(covers[0])
                carousel_first_frame_url = base_url + UPLOAD_URL_PREFIX + _cover_path[len(UPLOAD_DIR):]
    except Exception:
        carousel_first_frame_url = None
    import threading as _th
    _th.Thread(target=_render_branded_video_job,
               args=(cid, jid, prompts, segs_per_cli, cta, colors, co_logos, site, handle, base_url, audio_plan, app_logos,
                     carousel_first_frame_url, (target or None), _provider_config),
               daemon=True).start()
    return {"job": jid, "scenes": n, "provider": _vprov,
            "model": video_model_id_from_config(_provider_config)}


@router.post("/video-preflight")
async def video_preflight(request: Request):
    """Monta o ROTEIRO (o BRIEFING decide quantas cenas/segundos) e devolve o custo estimado — SEM gerar vídeo.
    O usuário NÃO escolhe a duração: o briefing dita. POST p/ não cair na rota coringa /{post_id}."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..services.ai import (build_video_storyboard, get_video_config, get_setting,
                               video_model_max_seconds, _video_catalog_entry, usd_to_brl, video_clip_price,
                               video_price_per_second, video_scene_count, video_segment_plan)
    _requested_model = (body.get("model") or "").strip()
    if not get_video_config(_requested_model or None):
        return {"configured": False}
    company = company_get(body.get("company_id"))
    theme = (body.get("theme") or "").strip()
    vp = (body.get("video_prompt") or "").strip()
    import math as _math
    try:
        target = int(body.get("seconds") or 0)        # >0 = usuário TRAVOU a duração; 0 = livre (IA decide)
    except Exception:
        target = 0
    mx = video_model_max_seconds(_requested_model or None)
    n_hint = video_scene_count(target, mx) if target > 0 else 0   # palpite determinístico (só p/ fallback/áudio; NÃO trava o nº)
    per_hint = max(1, min(mx, round(target / n_hint))) if n_hint else mx
    sb = []
    # REUSO do roteiro do BRIEFING: se o front mandou o storyboard que o briefing JÁ gerou, usa ELE —
    # determinístico e SEM custo (não re-gera). Era o bug: a criação re-gerava e colapsava pra 1 cena.
    _given = [p for p in (body.get("storyboard") or []) if isinstance(p, str) and p.strip()]
    if _given:
        prompts = _given
        _gd = [d for d in (body.get("scene_descs") or []) if isinstance(d, str)]
        descs = _gd[:len(prompts)] if len(_gd) >= len(prompts) else (_gd + prompts[len(_gd):])
        char_lock = (body.get("character") or "").strip()
    else:                                                                            # sem briefing → gera agora
        try:
            sb = await asyncio.to_thread(build_video_storyboard, company, theme, vp, target, n_hint, per_hint, (body.get("style") or "").strip()) if company else []
        except Exception:
            sb = []
        prompts = [s.get("prompt") for s in (sb or []) if s.get("prompt")]
        descs = [(s.get("desc") or "") for s in (sb or []) if s.get("prompt")]       # roteiro legível por cena (editável no front)
        char_lock = next((s.get("character_map") for s in (sb or []) if (s.get("character_map") or "").strip()), "")
    if target > 0:                                            # TRAVADA → nº de caixas = exatamente as cenas que a IA gerou (NÃO inventa caixa vazia)
        if not prompts:
            prompts = [vp or theme or "cena da marca"]; descs = [""]
        k, seg_secs = video_segment_plan(target, mx, len(prompts))   # respeita ai_count; distribui segs p/ somar ≈ duração
        if not isinstance(seg_secs, list):                   # blindagem: aceita int legado
            seg_secs = [seg_secs] * len(prompts)
        # SEM pad de duplicação: as caixas do roteiro são as cenas que a IA devolveu. UI mostra exatamente isso.
        secs = (list(seg_secs) + [seg_secs[-1] if seg_secs else mx] * len(prompts))[:len(prompts)] or [mx]
    else:                                                      # LIVRE → a IA decide
        prompts = prompts[:8] or [vp or theme or "cena"]
        secs = [min(int(s.get("seconds") or 8), mx) for s in (sb or [])][:len(prompts)] or [mx]
    if len(descs) < len(prompts):                             # alinha descs ao tamanho final de prompts
        descs += [descs[-1] if descs else ""] * (len(prompts) - len(descs))
    descs = descs[:len(prompts)]
    n = len(prompts)
    _vm = _requested_model or get_setting("video.model") or ""
    ent = _video_catalog_entry(_vm)
    name = ent[2] if ent else (_vm or "modelo")
    total_s = sum(secs)
    persec = video_price_per_second(_vm)           # preço REAL por segundo (OpenRouter) → custo bate 100%
    if persec > 0:
        total_usd = round(persec * total_s, 2)
        price = round(persec * (secs[0] if secs else 8), 2)
        real = True
    else:
        price = video_clip_price(_vm)
        total_usd = round(price * n, 2)
        real = bool(get_setting("video.price." + _vm))
    # kie.ai cobra em CRÉDITOS (não R$): mostra crédito/clipe (aprendido por uso, senão default por tier) × nº de cenas
    kie_credits = kie_credits_per_clip = 0.0
    is_credits = _vm.startswith("kie:")
    if is_credits:
        from ..services.ai import _KIE_BY_MODEL
        mdl = _vm[len("kie:"):]
        learned = get_setting("kie.credits." + mdl)
        tier = (_KIE_BY_MODEL.get(mdl) or ("", "", "medium", 8))[2]
        kie_credits_per_clip = float(learned) if learned else {"top": 90, "medium": 30, "fast": 15}.get(tier, 30)
        kie_credits = round(kie_credits_per_clip * n, 1)
        name = name + (" · " + tier.upper())
    return {"configured": True, "model": name, "scenes": n, "total_seconds": total_s,
            "seconds_per_scene": (secs[0] if secs else 8), "scene_seconds": secs,
            "price_per_clip_usd": price, "total_usd": total_usd, "total_brl": round(usd_to_brl(total_usd), 2),
            "price_real": real, "is_credits": is_credits, "credits_per_clip": kie_credits_per_clip,
            "total_credits": kie_credits, "credits_learned": bool(get_setting("kie.credits." + _vm[len("kie:"):]) if is_credits else False),
            "storyboard": prompts, "scene_descs": descs, "character": char_lock}


@router.post("/video-styles")
async def video_styles(request: Request):
    """Fase 3: lista de estilos virais p/ o seletor da UI (defaults + overrides da empresa).
    POST (não GET) p/ não cair na rota coringa GET /{post_id}."""
    err = _api_key_required(request)
    if err:
        return err
    from ..services.ai import video_styles_list
    try:
        body = await request.json()
    except Exception:
        body = {}
    cid = (body.get("company_id") or "").strip()
    company = company_get(cid) if cid else None
    return {"styles": video_styles_list(company)}


@router.post("/video-scene-regen")
async def video_scene_regen(request: Request):
    """Fase 3 (gate por cena): regenera UMA cena do roteiro mantendo continuidade com as outras + personagem +
    estilo. Custo = 1 chamada de texto barata. Devolve {desc}. Falha → devolve a cena atual (custo-seguro)."""
    err = _api_key_required(request)
    if err:
        return err
    body = await request.json()
    from ..services.ai import cheap_text_config, get_ai_config, complete_ai, extract_json, video_style_directive
    company = company_get(body.get("company_id"))
    theme = (body.get("theme") or "").strip()
    descs = [d for d in (body.get("scene_descs") or []) if isinstance(d, str)]
    try:
        idx = int(body.get("index"))
    except Exception:
        idx = -1
    if not (0 <= idx < len(descs)):
        return JSONResponse({"detail": "index inválido"}, status_code=422)
    cfg = cheap_text_config(get_ai_config())
    if not cfg:
        return {"desc": descs[idx]}
    char = (body.get("character") or "").strip()
    style = video_style_directive(company, (body.get("style") or "").strip())
    others = "\n".join(f"Cena {i + 1}: {d}" for i, d in enumerate(descs) if i != idx) or "(nenhuma)"
    system = ("Você é diretor de vídeo. Reescreva UMA cena de um reel trazendo uma VARIAÇÃO melhor, mantendo "
              "continuidade (mesmo universo e mesma pessoa) com as outras cenas. SÓ a cena fotográfica em movimento — "
              "PROIBIDO texto, legenda, número, logo, marca, preço. " + (style + " " if style else "")
              + 'Responda SOMENTE JSON: {"desc":"sujeito/elemento + contexto + 1 ação + 1 movimento de câmera + luz/clima + emoção"}')
    user = (f"Tema: {theme}. " + (f"Personagem fixo (mantenha igual): {char}. " if char else "")
            + f"Reescreva a cena {idx + 1} (atual: \"{descs[idx]}\"). Outras cenas (NÃO repita, mantenha continuidade):\n{others}")
    try:
        p = extract_json(await asyncio.to_thread(complete_ai, cfg, system, user, 320)) or {}
        nd = (p.get("desc") or "").strip()
        return {"desc": nd or descs[idx]}
    except Exception:
        return {"desc": descs[idx]}


@router.post("/branded-video-status")
async def branded_video_status(request: Request):
    err = _api_key_required(request)
    if err:
        return err
    import json as _json, time as _time
    body = await request.json()
    p = os.path.join(UPLOAD_DIR, body.get("company_id") or "", "video", (body.get("job") or "") + ".json")
    if not os.path.exists(p):
        return {"status": "unknown"}
    try:
        with open(p) as f:
            data = _json.load(f)
        state = str(data.get("status") or "").lower()
        final = os.path.splitext(p)[0] + ".mp4"
        if state in ("queued", "generating", "composing") and os.path.exists(final) and os.path.getsize(final) > 1000:
            data.update({"status": "done", "url": f"{UPLOAD_URL_PREFIX}/{body.get('company_id')}/video/{os.path.basename(final)}"})
            _video_status_write(p, data)
            return data
        # Thread de background morre num restart/deploy. Antes o JSON ficava
        # eternamente em "composing" e a UI contava tempo para sempre.
        if state in ("queued", "generating", "composing") and (_time.time() - os.path.getmtime(p)) > 1200:
            data.update({"status": "error", "detail": "A geração foi interrompida por uma reinicialização do servidor. Gere novamente."})
            _video_status_write(p, data)
        return data
    except Exception:
        return {"status": "unknown"}


def _stitch_videos(paths, out_path) -> bool:
    """Concatenate clips into one mp4 via ffmpeg (copy, falling back to re-encode)."""
    import subprocess
    import shutil
    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return True
    listf = out_path + ".txt"
    with open(listf, "w") as f:
        for p in paths:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))
    try:
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", out_path],
                           capture_output=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out_path],
                           capture_output=True, timeout=600)
    except Exception:
        return False
    finally:
        try:
            os.remove(listf)
        except Exception:
            pass
    return os.path.exists(out_path) and os.path.getsize(out_path) > 1000


@router.get("/video-status")
async def video_status(request: Request, jobs: str = "", company_id: str = ""):
    """Poll one or more Sora jobs; when ALL are done, stitch them into one video."""
    err = _api_key_required(request)
    if err:
        return err
    ids = [j for j in (jobs or "").split(",") if j.strip()]
    if not ids:
        return JSONResponse({"detail": "jobs é obrigatório"}, status_code=422)
    try:
        import asyncio
        states = await asyncio.gather(*[asyncio.to_thread(get_video_job, i) for i in ids])
        norm = [(s.get("status") or s.get("state") or "").lower() for s in states]
        if any(n in ("failed", "error", "canceled", "cancelled") for n in norm):
            return {"status": "failed", "error": "Um dos clipes falhou no provedor de vídeo."}
        done = [n in ("completed", "succeeded", "success", "done") for n in norm]
        if not all(done):
            return {"status": "processing", "done": sum(done), "total": len(ids)}
        if not company_id:
            return {"status": "completed", "detail": "informe company_id para salvar"}
        # download all clips then stitch into one
        import tempfile
        tmp = tempfile.mkdtemp(prefix="sora_")
        paths = []
        for i in ids:
            data = await asyncio.to_thread(download_video, i)
            cp = os.path.join(tmp, f"{i}.mp4")
            with open(cp, "wb") as f:
                f.write(data)
            paths.append(cp)
        subdir = os.path.join(UPLOAD_DIR, company_id, "generated")
        os.makedirs(subdir, exist_ok=True)
        filename = f"{_uuid.uuid4().hex}.mp4"
        final = os.path.join(subdir, filename)
        ok = await asyncio.to_thread(_stitch_videos, paths, final)
        if not ok:
            return JSONResponse({"detail": "Falha ao juntar os clipes."}, status_code=502)
        return {"status": "completed", "url": f"{UPLOAD_URL_PREFIX}/{company_id}/generated/{filename}", "clips": len(ids)}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


# ─────────────────────────────────────────────────────────────────────────────
# Trends (via companies)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trends/{company_id}")
def get_trends(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    report = report_get_latest(company_id, "TRENDS")
    return {"report": report, "ai_enabled": is_ai_enabled()}


@router.post("/trends/{company_id}/generate")
async def generate_trends_report(company_id: str, request: Request):
    err = _api_key_required(request)
    if err:
        return err
    company = company_get(company_id)
    if not company:
        return JSONResponse({"detail": "Empresa não encontrada"}, status_code=404)
    if not is_ai_enabled():
        return JSONResponse({"detail": "IA não configurada — adicione sua chave em Configurações."}, status_code=400)
    try:
        payload = generate_trends(company)
        report = report_create(company_id, "TRENDS", payload)
        return {"report": report}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)
