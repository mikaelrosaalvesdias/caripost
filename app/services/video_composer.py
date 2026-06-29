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


def _logo_h(logo_path: Optional[str], target_h: int) -> Optional[Image.Image]:
    """Logo escalada por ALTURA (p/ casar com o tamanho do texto do site)."""
    if not logo_path or not os.path.exists(logo_path):
        return None
    try:
        im = Image.open(logo_path).convert("RGBA")
        r = target_h / max(1, im.height)
        return im.resize((max(1, int(im.width * r)), target_h), Image.LANCZOS)
    except Exception:
        return None


def _brand_frame(canvas: Image.Image, d: ImageDraw.ImageDraw, colors: Dict[str, Any],
                 logo_path: Optional[str], site: str) -> None:
    """Marca CONSISTENTE em toda tela (clipe/capa/CTA): logo pequeno (~tamanho do site) no TOPO-esquerda +
    site embaixo-esquerda. MESMO tamanho e posição em todas as telas → transição limpa entre elas."""
    lg = _logo_h(logo_path, 56)
    if lg:
        canvas.alpha_composite(lg, (60, 64))
    st = (site or "").replace("https://", "").replace("http://", "").strip("/")
    if st:
        d.text((60, VH - 98), st, font=_font(44, weight="semibold"), fill=(255, 255, 255, 235))


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
    canvas = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    # gradiente sutil só no TOPO e na BASE (legibilidade da marca); MEIO fica livre — o texto da mensagem
    # fica por conta da IA (não trava posição).
    grad = Image.new("L", (1, VH), 0)
    gp = grad.load()
    for y in range(VH):
        f = max((200 - y) / 200.0, (y - (VH - 200)) / 200.0, 0.0)
        gp[0, y] = int(min(1.0, f) * 150)
    grad = grad.resize((VW, VH))
    dark = Image.new("RGBA", (VW, VH), (8, 7, 11, 255)); dark.putalpha(grad)
    canvas.alpha_composite(dark)
    _brand_frame(canvas, d, colors, logo_path, site)   # MESMA marca da capa/CTA
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
    # MESMA marca dos clipes (logo topo + site embaixo) → transição limpa entre cena e CTA
    _brand_frame(canvas, d, colors, logo_path, site)
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
