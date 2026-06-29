"""Pós-produção de VÍDEO com IDENTIDADE DA MARCA (determinístico, R$0): normaliza 9:16, sobrepõe LOGO,
queima LEGENDA por cena e adiciona card de CTA (marca + contato + logo). Recebe clipes JÁ gerados e
devolve 1 vídeo branded. Usa ffmpeg + PIL (mesma fonte Poppins / cores do carrossel).

A IA só fotografa a cena; o CÓDIGO desenha marca/legenda/CTA — igual ao carrossel.
"""
import os
import subprocess
import tempfile
from typing import List, Dict, Any, Optional

from PIL import Image, ImageDraw, ImageFilter

from .template_composer import _font, _hex, ORANGE, WHITE

VW, VH = 1080, 1920   # 9:16


def _ff(args: List[str], timeout: int = 180) -> bool:
    """Roda ffmpeg silencioso; True se ok."""
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


def _caption_png(text: str, acc, path: str) -> None:
    """Faixa de LEGENDA (transparente, 1080x1920) — texto branco em bloco escuro no terço inferior."""
    canvas = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    f = _font(58, weight="extrabold")
    inner = VW - 160
    lines = _wrap(d, (text or "").strip(), f, inner)[:3]
    if not lines:
        canvas.save(path); return
    lh = int(f.size * 1.16)
    bh = len(lines) * lh + 56
    by = VH - bh - 230                                   # acima da área do rodapé/CTA
    # scrim arredondado escuro p/ legibilidade
    scrim = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).rounded_rectangle([60, by, VW - 60, by + bh], 28, fill=(10, 8, 12, 205))
    scrim = scrim.filter(ImageFilter.GaussianBlur(2))
    canvas.alpha_composite(scrim)
    d = ImageDraw.Draw(canvas)
    ty = by + 28
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text(((VW - tw) // 2, ty), ln, font=f, fill=WHITE)
        ty += lh
    # barra de acento embaixo
    d.rounded_rectangle([VW // 2 - 60, by + bh - 14, VW // 2 + 60, by + bh - 8], 3, fill=acc)
    canvas.save(path)


def _cta_card_png(cta: Dict[str, Any], colors: Dict[str, Any], logo_path: Optional[str], path: str) -> None:
    """Card de CTA/encerramento (1080x1920): fundo escuro da marca + glow + CTA + contato + logo."""
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    canvas = Image.new("RGB", (VW, VH), (18, 16, 22))
    # glow de marca
    glow = Image.new("L", (VW, VH), 0)
    ImageDraw.Draw(glow).ellipse([VW // 2 - 520, VH // 2 - 520, VW // 2 + 520, VH // 2 + 520], fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    tint = Image.new("RGB", (VW, VH), acc)
    canvas = Image.composite(tint, canvas, glow.point(lambda x: int(x * 0.5)))
    canvas = canvas.convert("RGBA")
    d = ImageDraw.Draw(canvas)
    title = (cta.get("title") or "Fale com a gente").strip()
    btn = (cta.get("cta") or "Fale com a gente").strip()
    phone = (cta.get("phone") or "").strip()
    site = (cta.get("site") or "").replace("https://", "").replace("http://", "").strip("/")
    tf = _font(78, weight="extrabold")
    inner = VW - 200
    tl = _wrap(d, title, tf, inner)[:4]
    total_h = len(tl) * int(tf.size * 1.08) + 60 + 96 + (70 if phone else 0) + (52 if site else 0)
    ty = (VH - total_h) // 2 - 40
    for ln in tl:
        tw = d.textlength(ln, font=tf)
        d.text(((VW - tw) // 2, ty), ln, font=tf, fill=WHITE)
        ty += int(tf.size * 1.08)
    ty += 40
    # botão
    bf = _font(46, weight="extrabold")
    bw = d.textlength(btn, font=bf)
    bx0 = (VW - int(bw + 100)) // 2
    d.rounded_rectangle([bx0, ty, bx0 + int(bw + 100), ty + 96], 48, fill=acc)
    d.text((bx0 + 50, ty + 22), btn, font=bf, fill=WHITE)
    ty += 130
    if phone:
        pf = _font(54, weight="extrabold")
        pw = d.textlength(phone, font=pf)
        d.text(((VW - pw) // 2, ty), phone, font=pf, fill=acc); ty += 70
    if site:
        sf = _font(40, weight="semibold")
        sw = d.textlength(site, font=sf)
        d.text(((VW - sw) // 2, ty), site, font=sf, fill=(255, 255, 255, 230))
    # logo no topo
    lg = _logo_img(logo_path, 320)
    if lg:
        canvas.alpha_composite(lg, ((VW - lg.width) // 2, 150))
    canvas.convert("RGB").save(path)


def compose_branded_video(clips: List[Dict[str, Any]], out_path: str,
                          colors: Dict[str, Any], logo_path: Optional[str],
                          cta: Dict[str, Any]) -> bool:
    """clips = [{'path':..., 'caption':...}, ...] (já gerados/baixados) → 1 vídeo 9:16 branded com CTA.
    Retorna True/False. NÃO gera vídeo de IA — só pós-produção determinística."""
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    tmp = tempfile.mkdtemp(prefix="vid_")
    logo = _logo_img(logo_path, 200)
    logo_png = os.path.join(tmp, "logo.png")
    if logo:
        logo.save(logo_png)
    segs = []
    for i, c in enumerate(clips):
        cp = c.get("path")
        if not cp or not os.path.exists(cp):
            continue
        cap_png = os.path.join(tmp, f"cap{i}.png")
        _caption_png(c.get("caption") or "", acc, cap_png)
        seg = os.path.join(tmp, f"seg{i}.mp4")
        # normaliza 9:16 (scale+crop) + overlay legenda + overlay logo (canto sup. esq.)
        fc = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v];"
              "[v][1:v]overlay=0:0[vc]")
        inputs = ["-i", cp, "-i", cap_png]
        if logo:
            fc += ";[vc][2:v]overlay=44:48[vout]"
            inputs += ["-i", logo_png]
        else:
            fc = fc.replace("[vc]", "[vout]")
        ok = _ff(inputs + ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a?",
                           "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                           "-ar", "44100", "-shortest", seg])
        if ok:
            segs.append(seg)
    if not segs:
        return False
    # card de CTA → clipe de 2.6s (com áudio silencioso p/ casar no concat)
    cta_png = os.path.join(tmp, "cta.png")
    _cta_card_png({**cta}, colors, logo_path, cta_png)
    cta_mp4 = os.path.join(tmp, "cta.mp4")
    if _ff(["-loop", "1", "-i", cta_png, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2.6", "-vf", "scale=1080:1920,setsar=1", "-r", "30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cta_mp4]):
        segs.append(cta_mp4)
    # concat por filtro (re-encoda → seguro p/ fontes mistas)
    n = len(segs)
    inputs = []
    for s in segs:
        inputs += ["-i", s]
    streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    fc = f"{streams}concat=n={n}:v=1:a=1[v][a]"
    return _ff(inputs + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out_path],
               timeout=300)
