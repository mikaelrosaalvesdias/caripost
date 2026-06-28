"""
Posts router — approval workflow + AI generation.
Mirrors caripost-web's post management and approval center.
"""
from __future__ import annotations

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
    generate_image_bytes, generate_image_with_cost, generate_image_resilient, image_models_registry, vision_clear_side, generate_image_with_person, pick_influencer_photo, generate_image_edit, build_image_prompt, get_image_config,
    openrouter_image_models, openrouter_video_models, omniroute_image_models, openai_image_models, piapi_image_models, cometapi_image_models, usd_to_brl, get_setting,
    create_video_job, get_video_job, download_video, build_video_prompt, build_video_storyboard, get_video_config,
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
    def _prov(lst, p):
        for m in lst:
            m.setdefault("provider", p)
        return lst
    img = (_prov(omniroute_image_models(), "omniroute")
           + _prov(cometapi_image_models(), "cometapi")
           + _prov(piapi_image_models(), "piapi")
           + _prov(openrouter_image_models(), "openrouter"))
    vid = openrouter_video_models()
    for m in img:
        m["price_brl"] = usd_to_brl(m.get("price_per_image") or 0)
    for m in vid:
        m["price_brl"] = usd_to_brl(m.get("price_per_video") or 0)
    return {
        "image": img,
        "image_current": get_setting("image.model") or "",
        "image_provider": get_setting("image.provider") or "openrouter",
        "video": vid,
        "video_current": get_setting("video.model") or "",
        "fx_usd_brl": float(get_setting("fx.usd_brl") or 5.40),
    }


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
    prompt = _full_slide_prompt(s, brand_color, company.get("name", ""), structure, (tmpl or {}).get("variant"))
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
        # Mesmo bug do carrossel: o post único também invertia (IA desenhava tudo). Agora photo_ai_composer
        # é o padrão; o legacy (IA desenha a arte inteira) fica ISOLADO atrás de render_mode.
        rm = (body.get("render_mode") or ("legacy_ai_full_art" if body.get("composer") is False else "photo_ai_composer")).strip().lower()
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
                                      body.get("formato") or "carrossel", n, intent, event)
        return {"briefing": res.get("text", ""), "telas": res.get("telas", []), "formato": res.get("formato")}
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


def _full_slide_prompt(s: dict, color: str, brand: str, structure: str = None, variant: str = None) -> str:
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
        + f"Cores da marca: destaque {color} + escuros/neutros sofisticados. " + accents
        + "Foto/arte premium real (nada de cara de IA/cartoon/3D barato). " + logo_line + foot_line
        + (f"Cena de base: {visual}. " if visual else "") + "Sem marca d'água."
    )


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
    return _PRODUCT_DNA["cariap"]


def _photo_only_prompt(s: dict, brand: str, variant: str = None, brand_hex: str = "", design: dict = None) -> str:
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
    dna = _product_dna((s.get("app") or "").strip() or "cariap", design)
    grade = (f"Grade de cor puxando para a COR DA MARCA ({brand_hex}) " if brand_hex
             else "Grade de cor cinematográfica de campanha ")
    return (
        "IMAGEM PUBLICITÁRIA premium para Instagram, nível AGÊNCIA de propaganda — estética de CAMPANHA, "
        "NÃO foto de banco de imagem, NÃO cara de IA/cartoon/render barato. Vertical 4:5, altíssima produção. "
        f"Marca: {brand}. " + dna + " " + grade + ". "
        "ILUMINAÇÃO dramática e direcional (rim light, contraluz, glow), PROFUNDIDADE real em camadas e TEXTURA "
        "rica (partículas, bokeh, atmosfera) — nada de fundo chapado. "
        "UM sujeito humano FORTE, expressivo e art-directed (brasileiro real, olhar marcante), com RECORTE nítido "
        "e separação clara do fundo. Composição premium, contraste alto. "
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
    if rm in ("photo_ai_composer", "composer_only", "legacy_ai_full_art"):
        return rm
    model = (body.get("model") or "").strip()
    if not model or model.lower() == "editorial":
        return "composer_only"
    return "photo_ai_composer" if bool(body.get("composer", True)) else "legacy_ai_full_art"


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
    telas = body.get("telas") or []
    if not telas:
        return JSONResponse({"detail": "Sem telas para renderizar (gere o plano no Briefing)."}, status_code=422)
    model = (body.get("model") or "").strip()
    render_mode = _resolve_render_mode(body)            # photo_ai_composer | composer_only | legacy_ai_full_art
    ai_bg = render_mode in ("photo_ai_composer", "legacy_ai_full_art")
    use_composer = render_mode == "photo_ai_composer"
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
        influencer, inf_photos, inf_handle, used_inf_idx = None, [], "", set()
        if ai_bg and use_composer and body.get("use_influencer"):
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
                    inf_photos = [b for b in (_load_upload_bytes(p.get("url")) for p in influencer["photos"]) if b]
                    inf_handle = (influencer.get("handle") or "").strip()
            except Exception:
                influencer = None
        # EVENTO: logos (carimba na capa/CTA) + info REAL (datas/local/stand do cadastro) que o CÓDIGO injeta no CTA.
        event_logo_variants = []
        event_cta_info = ""
        _eid = (body.get("event_id") or "").strip()
        if _eid:
            try:
                from ..db_companies import event_get, organizer_get
                _ev = event_get(_eid)
                _eassets = list((_ev or {}).get("logos") or [])
                if _ev and _ev.get("organizer_id"):
                    _org = organizer_get(_ev["organizer_id"])
                    if _org:
                        _eassets += list(_org.get("logos") or [])
                event_logo_variants = _all_raster_logos(_eassets)
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
        for i, s in enumerate(telas, 1):
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
                prompt = _photo_only_prompt(s, company.get("name", ""), (tmpl or {}).get("variant"), brand_color, design_ov)
            else:
                prompt = _full_slide_prompt(s, brand_color, company.get("name", ""), structure, (tmpl or {}).get("variant"))
            app_legacy = app_variants[0] if app_variants else None   # legacy usa 1 só
            img_ok, img_err, png, img, used_model = False, "", None, None, model
            # 1) GERAÇÃO da foto — do CACHE (base salva, custo 0) OU da IA com TRANSBORDO inteligente.
            reuse_url = reuse_bases[i - 1] if i - 1 < len(reuse_bases) else None
            if ai_bg and reuse_url:
                img = _load_upload_bytes(reuse_url)            # CACHE: reusa a foto, NÃO paga IA
                img_ok = img is not None
            # INFLUENCER na CAPA/CTA: compõe a pessoa real na cena (nano-banana), em vez da cena vazia.
            stype = (s.get("type") or "").lower()
            if ai_bg and img is None and influencer and inf_photos and stype in ("cover", "cta"):
                # EMOÇÃO + VARIAÇÃO: a IA (visão) escolhe do PORTFÓLIO a foto cuja expressão combina com o texto da tela;
                # exclui as já usadas (capa e CTA pegam fotos diferentes → não fica repetitivo).
                _pi = await asyncio.to_thread(pick_influencer_photo, inf_photos, s.get("title", ""), stype, used_inf_idx)
                used_inf_idx.add(_pi)
                person = inf_photos[_pi]
                _scene = (s.get("visual") or "").strip()
                pprompt = ("Integre ESTA pessoa real na CENA DO BRIEFING (ela é a protagonista da cena): "
                           + (_scene or ("cena publicitária premium da marca " + company.get("name", ""))) + ". "
                           "Construa o AMBIENTE/FUNDO A PARTIR dessa cena (NÃO use fundo escuro genérico se a cena pede outro lugar). "
                           "LIMPE a rebarba/borda do recorte e harmonize luz e cor da pessoa com a cena (parece fotografada ali). "
                           "Deixe ESPAÇO NEGATIVO de um lado pro texto, com a pessoa no lado oposto. "
                           "NÃO mude o rosto nem a expressão da pessoa. Vertical " + ("9:16" if fmt == "story" else "4:5") + ", alta produção, fotográfico premium. SEM texto, SEM logo.")
                try:
                    img, _pc = await asyncio.to_thread(generate_image_with_person, person, pprompt)
                    img_ok = True; total_cost += (_pc or 0.0)
                    spillovers.append((i, "influencer: " + (influencer.get("name") or "")))
                except Exception as pe:
                    img_err = ("influencer: " + str(pe))[:160]   # falhou → cai pro fluxo normal (cena sem pessoa)
            if ai_bg and img is None:
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
                    if use_composer:   # Marco 3: foto da IA + CARD de vidro (nível agência, texto legível, logo intacta)
                        png = await asyncio.to_thread(compose_card_slide, slide_for_render, i, total, colors, co_logos, site, handle, img, None, design_ov, slide_app_logos, canvas_size)
                    else:              # legacy ISOLADO: IA já desenhou a arte → só carimba logo (+ rodapé no CTA)
                        png = await asyncio.to_thread(compose_logos_only, img, co_logo, app_legacy, colors)
                        if is_cta:
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
            # 4) FALLBACK editorial (grátis) — modo composer_only OU quando a IA/compose falha.
            if png is None:
                try:
                    png = await asyncio.to_thread(compose_carousel_slide, slide_for_render, i, total, colors, co_logos, site, handle, None, None, design_ov, slide_app_logos)
                except Exception as fe:
                    fails.append(("editorial: " + str(fe))[:180])
                    continue   # tela impossível → pula (degradação graciosa: não derruba o carrossel)
            fn = f"{i:02d}.png"
            with open(os.path.join(subdir, fn), "wb") as f:
                f.write(png)
            out.append({"url": f"{UPLOAD_URL_PREFIX}/{company_id}/carousel/{hexid}/{fn}",
                        "type": s.get("type"), "title": s.get("title", ""), "app": s.get("app") or "",
                        "prompt": prompt, "image_ok": img_ok, "image_error": img_err, "base_url": base_out,
                        "model_used": used_model})
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
        # an OpenRouter slug has a "/"; otherwise it's OpenAI
        settings_set(key="image.provider", value=("openrouter" if "/" in m else "openai"), updated_at=now)
    return {"ok": True, "image_current": get_setting("image.model")}


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
    if not get_video_config():
        return JSONResponse({"detail": "Geração de vídeo não configurada (chave OpenAI)."}, status_code=400)
    theme = (body.get("theme") or body.get("briefing") or "").strip()
    video_prompt = (body.get("video_prompt") or body.get("visual_prompt") or "").strip()
    scenes = max(1, min(int(body.get("scenes") or 3), 6))      # nº de clipes a juntar
    seconds = str(body.get("seconds") or "8")                  # duração de cada clipe
    size = body.get("size") or "720x1280"
    try:
        import asyncio
        prompts = await asyncio.to_thread(build_video_storyboard, company, theme, video_prompt, scenes)
        jobs = []
        for sp in prompts:
            j = await asyncio.to_thread(create_video_job, sp, seconds, size)
            jid = j.get("id")
            if jid:
                jobs.append(jid)
        if not jobs:
            return JSONResponse({"detail": "Não consegui criar os clipes de vídeo."}, status_code=502)
        return {"jobs": jobs, "count": len(jobs), "scenes": len(prompts)}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


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
        if any(n in ("failed", "error", "cancelled") for n in norm):
            return {"status": "failed", "error": "Um dos clipes falhou no Sora."}
        done = [n in ("completed", "succeeded", "success") for n in norm]
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
