"""Pós-produção de VÍDEO com IDENTIDADE DA MARCA (determinístico, R$0): normaliza 9:16, rodapé da marca
(logo + site), LEGENDA estilo tech (gradiente, sem caixa) por cena, e card de CTA renderizado pelo MESMO
motor do carrossel (compose_card_slide) → identidade IDÊNTICA à arte. ffmpeg + PIL.

A IA só fotografa a cena; o CÓDIGO desenha marca/legenda/CTA — igual ao carrossel.
"""
import io
import os
import subprocess
import tempfile
from typing import List, Dict, Any, Optional

from PIL import Image, ImageDraw, ImageFilter

from .template_composer import _font, _hex, ORANGE, WHITE, compose_card_slide

VW, VH = 1080, 1920   # 9:16


def _ff(args: List[str], timeout: int = 240) -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                           capture_output=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def _logo_img(logo_path: Optional[str], target_w: int) -> Optional[Image.Image]:
    if not logo_path or not os.path.exists(logo_path):
        return None
    try:
        im = Image.open(logo_path).convert("RGBA")
        r = target_w / max(1, im.width)
        return im.resize((target_w, max(1, int(im.height * r))), Image.LANCZOS)
    except Exception:
        return None


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    out, line = [], ""
    for w in (text or "").split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) <= max_w or not line:
            line = t
        else:
            out.append(line); line = w
    if line:
        out.append(line)
    return out


def _brand_bg_bytes(colors: Dict[str, Any]) -> bytes:
    """Fundo escuro da marca 1080x1920 (grafite + glow na cor de acento) — base do card de CTA."""
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    base = Image.new("RGB", (VW, VH), (18, 16, 22))
    glow = Image.new("L", (VW, VH), 0)
    ImageDraw.Draw(glow).ellipse([VW // 2 - 560, VH // 2 - 700, VW // 2 + 560, VH // 2 + 700], fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(200))
    tint = Image.new("RGB", (VW, VH), acc)
    out = Image.composite(tint, base, glow.point(lambda x: int(x * 0.45)))
    b = io.BytesIO(); out.save(b, "PNG"); return b.getvalue()


def _clip_overlay_png(caption: str, colors: Dict[str, Any], logo_path: Optional[str], site: str, path: str) -> None:
    """Overlay transparente 1080x1920 p/ cada clipe: LEGENDA tech (gradiente, sem caixa) + RODAPÉ da marca
    (logo embaixo à esquerda + site à direita) — igual à arte do carrossel."""
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    canvas = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    # 1) gradiente suave de baixo p/ cima (legibilidade SEM caixa) — só o terço inferior
    grad = Image.new("L", (1, VH), 0)
    gp = grad.load()
    for y in range(VH):
        f = max(0.0, (y - VH * 0.52) / (VH * 0.48))     # começa a escurecer em ~52% da altura
        gp[0, y] = int(min(1.0, f) ** 1.3 * 235)
    grad = grad.resize((VW, VH))
    dark = Image.new("RGBA", (VW, VH), (8, 7, 11, 255)); dark.putalpha(grad)
    canvas.alpha_composite(dark)
    d = ImageDraw.Draw(canvas)
    # 2) legenda: barra de acento + texto bold branco (estilo reels premium)
    cap = (caption or "").strip()
    if cap:
        f = _font(60, weight="extrabold")
        inner = VW - 130
        lines = _wrap(d, cap, f, inner)[:3]
        lh = int(f.size * 1.12)
        by = VH - 250 - len(lines) * lh
        d.rounded_rectangle([65, by - 6, 65 + 90, by + 4], 4, fill=acc)   # tracinho de acento em cima
        ty = by + 22
        for ln in lines:
            # sombra sutil + texto (sem caixa)
            d.text((66, ty + 3), ln, font=f, fill=(0, 0, 0, 170))
            d.text((64, ty), ln, font=f, fill=WHITE)
            ty += lh
    # 3) rodapé da marca: logo embaixo à esquerda + site à direita
    lg = _logo_img(logo_path, 230)
    if lg:
        canvas.alpha_composite(lg, (60, VH - lg.height - 70))
    st = (site or "").replace("https://", "").replace("http://", "").strip("/")
    if st:
        sf = _font(34, weight="semibold")
        sw = d.textlength(st, font=sf)
        d.text((VW - 60 - sw, VH - 96), st, font=sf, fill=(255, 255, 255, 225))
    canvas.save(path)


def _cta_card_png(cta: Dict[str, Any], colors: Dict[str, Any], logo_path: Optional[str],
                  site: str, handle: str, path: str) -> None:
    """Card de CTA 9:16 desenhado direto em PIL no ESTILO da arte (eyebrow + título + botão + contato +
    logo embaixo à esquerda). Controle total → sem resquício de carrossel, sempre 9:16."""
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    canvas = Image.open(io.BytesIO(_brand_bg_bytes(colors))).convert("RGBA")
    d = ImageDraw.Draw(canvas)
    eyebrow = (cta.get("eyebrow") or "").strip().upper()
    title = (cta.get("title") or "Fale com a gente").strip()
    btn = (cta.get("cta") or "Fale com a gente").strip()
    phone = (cta.get("phone") or "").strip()
    st = (site or "").replace("https://", "").replace("http://", "").strip("/")
    M = 90
    inner = VW - 2 * M
    tf = _font(96, weight="extrabold")
    tl = _wrap(d, title, tf, inner)[:4]
    # altura do bloco p/ centralizar verticalmente
    bh = (56 if eyebrow else 0) + len(tl) * int(tf.size * 1.05) + 56 + 110 + (78 if phone else 0) + (56 if st else 0)
    ty = max(260, (VH - bh) // 2 - 60)
    if eyebrow:
        d.text((M, ty), eyebrow, font=_font(40, weight="extrabold"), fill=acc); ty += 56
    for k, ln in enumerate(tl):
        if k == len(tl) - 1 and " " in ln:                 # última palavra em ACC
            pre, last = ln.rsplit(" ", 1)
            d.text((M, ty), pre + " ", font=tf, fill=WHITE)
            d.text((M + d.textlength(pre + " ", font=tf), ty), last, font=tf, fill=acc)
        else:
            d.text((M, ty), ln, font=tf, fill=WHITE)
        ty += int(tf.size * 1.05)
    ty += 30
    bf = _font(50, weight="extrabold")
    bw = d.textlength(btn, font=bf)
    d.rounded_rectangle([M, ty, M + int(bw + 110), ty + 100], 50, fill=acc)
    d.text((M + 55, ty + 24), btn, font=bf, fill=WHITE); ty += 138
    if phone:
        d.text((M, ty), phone, font=_font(58, weight="extrabold"), fill=acc); ty += 78
    if st:
        d.text((M, ty), st, font=_font(42, weight="semibold"), fill=(255, 255, 255, 230))
    # logo embaixo à esquerda (igual ao rodapé da arte)
    lg = _logo_img(logo_path, 300)
    if lg:
        canvas.alpha_composite(lg, (M, VH - lg.height - 90))
    canvas.convert("RGB").save(path)


def compose_branded_video(clips: List[Dict[str, Any]], out_path: str,
                          colors: Dict[str, Any], logo_path: Optional[str],
                          cta: Dict[str, Any], site: str = "", handle: str = "") -> bool:
    """clips=[{'path','caption'}] (já gerados) → 1 vídeo 9:16 branded (rodapé+legenda) + card de CTA. R$0."""
    tmp = tempfile.mkdtemp(prefix="vid_")
    segs = []
    for i, c in enumerate(clips):
        cp = c.get("path")
        if not cp or not os.path.exists(cp):
            continue
        ov = os.path.join(tmp, f"ov{i}.png")
        _clip_overlay_png(c.get("caption") or "", colors, logo_path, site, ov)
        seg = os.path.join(tmp, f"seg{i}.mp4")
        fc = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v];"
              "[v][1:v]overlay=0:0[vout]")
        ok = _ff(["-i", cp, "-i", ov, "-filter_complex", fc, "-map", "[vout]", "-map", "0:a?",
                  "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                  "-ar", "44100", "-shortest", seg])
        if ok:
            segs.append(seg)
    if not segs:
        return False
    cta_png = os.path.join(tmp, "cta.png")
    _cta_card_png(cta, colors, logo_path, site, handle, cta_png)
    cta_mp4 = os.path.join(tmp, "cta.mp4")
    if _ff(["-loop", "1", "-i", cta_png, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2.6", "-vf", "scale=1080:1920,setsar=1", "-r", "30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cta_mp4]):
        segs.append(cta_mp4)
    n = len(segs)
    inputs = []
    for s in segs:
        inputs += ["-i", s]
    streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    fc = f"{streams}concat=n={n}:v=1:a=1[v][a]"
    return _ff(inputs + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out_path],
               timeout=300)
