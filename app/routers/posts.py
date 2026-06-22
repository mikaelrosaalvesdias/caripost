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
    generate_image_bytes, generate_image_edit, build_image_prompt, get_image_config,
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

    This drops the connected background region (black/white/colored) while
    keeping interior pixels of the same color — so the mark blends into the
    photo. If the logo already has real transparency, it's returned untouched.
    """
    try:
        from PIL import Image, ImageDraw
        logo = logo.convert("RGBA")
        if logo.getchannel("A").getextrema()[0] < 200:
            return logo  # already has transparency
        w, h = logo.size
        rgb = logo.convert("RGB")
        SENT = (1, 254, 2)  # sentinel color unlikely in a logo
        seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
        for s in seeds:
            try:
                ImageDraw.floodfill(rgb, s, SENT, thresh=70)
            except Exception:
                pass
        rp, lp = rgb.load(), logo.load()
        removed = 0
        for y in range(h):
            for x in range(w):
                if rp[x, y] == SENT:
                    r, g, b, a = lp[x, y]
                    lp[x, y] = (r, g, b, 0)
                    removed += 1
        # If almost nothing was removed, the bg wasn't a clean solid → keep original.
        if removed < (w * h) * 0.05:
            return logo
        return logo
    except Exception:
        return logo


def _overlay_logo(image_bytes: bytes, logo_path: str, position: str = "top-right", scale: float = 0.16) -> bytes:
    """Overlay the logo as-is (preserving original alpha) with a soft shadow for legibility.

    The logo is NOT background-removed here — flood-fill cutout was destroying logo
    quality (pixelated edges, eaten letters). PNGs with real transparency composite
    naturally; opaque logos keep their original background intact.
    """
    try:
        import io
        from PIL import Image, ImageFilter
        base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        target_w = max(90, int(base.width * scale))
        ratio = target_w / logo.width
        logo = logo.resize((target_w, max(1, int(logo.height * ratio))), Image.LANCZOS)
        lw, lh = logo.size
        m = int(base.width * 0.05)
        if position == "bottom-left":
            pos = (m, base.height - lh - m)
        elif position == "bottom-right":
            pos = (base.width - lw - m, base.height - lh - m)
        elif position == "top-left":
            pos = (m, m)
        else:  # top-right
            pos = (base.width - lw - m, m)
        # Soft shadow from the logo's own alpha → legibility on busy photos.
        alpha = logo.getchannel("A")
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sh = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        sh.putalpha(alpha.point(lambda a: int(a * 0.55)))
        shadow.paste(Image.new("RGBA", (lw, lh), (0, 0, 0, 255)), (pos[0] + int(lw * 0.03), pos[1] + int(lh * 0.05)), sh)
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, int(lw * 0.05))))
        base = Image.alpha_composite(base, shadow)
        base.alpha_composite(logo, pos)
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
    size = body.get("size") or "1024x1024"
    # Principle (brand manual): the AI generates ONLY a clean base scene (no text, no logo).
    # The system applies the real logo by code. We do NOT feed the logo as a reference,
    # because that makes the model draw garbled letters/fake logos.
    products = product_list(company_id) or []
    # Company logo (primary first), skipping SVG.
    company_logos = sorted(asset_list_logos(company_id) or [], key=lambda l: 0 if (l.get("meta") or {}).get("is_primary") else 1)
    logo_path = _first_raster_logo(company_logos)
    # Logo of the specific app/product the copy is about (optional).
    app_logo_path = None
    prod_name = (body.get("product") or "").strip().lower()
    if prod_name:
        match = next((p for p in products if (p.get("name") or "").strip().lower() == prod_name), None)
        if match:
            app_logo_path = _first_raster_logo(asset_list_logos(company_id, match["id"]))
    prompt = build_image_prompt(company, theme, visual_prompt, products=products, has_refs=False)
    try:
        import asyncio
        img = await asyncio.to_thread(generate_image_bytes, prompt, size)   # clean base, no text/logo
        if logo_path:
            img = await asyncio.to_thread(_overlay_logo, img, logo_path, "top-right")     # Cariap logo
        if app_logo_path:
            img = await asyncio.to_thread(_overlay_logo, img, app_logo_path, "bottom-left", 0.20)  # app logo
        subdir = os.path.join(UPLOAD_DIR, company_id, "generated")
        os.makedirs(subdir, exist_ok=True)
        filename = f"{_uuid.uuid4().hex}.png"
        with open(os.path.join(subdir, filename), "wb") as f:
            f.write(img)
        url = f"{UPLOAD_URL_PREFIX}/{company_id}/generated/{filename}"
        return {"url": url, "prompt": prompt}
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


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
