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

from .template_composer import _font, _hex, ORANGE, WHITE, compose_card_slide, _pick_logo_variant

VW, VH = 1080, 1920   # 9:16


def _ff(args: List[str], timeout: int = 240) -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                           capture_output=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def concat_raw_clips(paths: List[str], out_path: str) -> bool:
    """Junta os clipes CRUS do modelo SEM reprocessar (stream copy) — preserva exatamente imagem e áudio gerados.
    1 clipe = copia direto. Se o stream-copy falhar (params diferentes), reencoda só pra juntar, SEM corte/grade."""
    import shutil
    paths = [p for p in (paths or []) if p and os.path.exists(p)]
    if not paths:
        return False
    if len(paths) == 1:
        try:
            shutil.copy(paths[0], out_path)
            return True
        except Exception:
            return False
    lst = tempfile.mktemp(suffix=".txt")
    try:
        with open(lst, "w") as f:
            for p in paths:
                f.write("file '%s'\n" % os.path.abspath(p).replace("'", "'\\''"))
        if _ff(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out_path], timeout=300):
            return True
        # fallback: reencoda concatenando (sem mexer no enquadramento) quando o stream-copy não casa
        inputs = []
        for p in paths:
            inputs += ["-i", p]
        n = len(paths)
        fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        return _ff(inputs + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out_path], timeout=420)
    finally:
        try:
            os.remove(lst)
        except Exception:
            pass


def cta_endcard_clip(image_path: str, out_path: str, seconds: float = 3.0,
                     width: int = 1080, height: int = 1920, bg: str = "0x0d1117") -> bool:
    """CTA FIXO (imagem aprovada, NÃO gerada por IA) → clipe de end-card 9:16 com áudio mudo, pronto pra
    concatenar no FIM de todo vídeo. A imagem (qualquer proporção, ex. card 4:5) entra centralizada com PAD
    na cor de fundo (sem distorcer). Mesma receita do compositor, isolada. True/False; nunca levanta."""
    if not image_path or not os.path.exists(image_path):
        return False
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1,fade=t=in:st=0:d=0.45")
    return _ff(["-loop", "1", "-i", image_path, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(max(1.0, float(seconds))), "-vf", vf, "-r", "30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                "-movflags", "+faststart", out_path], timeout=180)


def last_frame_png(clip_path: str, out_path: str) -> bool:
    """Extrai o ÚLTIMO frame do clipe → PNG. Vira o first_frame da próxima cena (CONTINUIDADE). True/False.
    O PNG precisa ficar numa URL pública (sem cookie/redirect) p/ a OpenRouter baixar."""
    if not clip_path or not os.path.exists(clip_path):
        return False
    return _ff(["-sseof", "-0.2", "-i", clip_path, "-vframes", "1", "-q:v", "2", out_path]) and os.path.exists(out_path)


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


def _grade_filter(colors: Dict[str, Any], strength: float = 0.30) -> str:
    """Grade de cor da MARCA p/ TODO clipe (ffmpeg, determinístico): empurra sombras/midtones pra cor de acento
    + leve punch (contraste/saturação). Dá identidade de cor consistente mesmo com footage variado do modelo.
    'strength' é design token (default sutil); dá pra mover pra creative_config.design depois."""
    r, g, b = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    rm = round((r / 255.0 - 0.5) * strength, 3)
    gm = round((g / 255.0 - 0.5) * strength, 3)
    bm = round((b / 255.0 - 0.5) * strength, 3)
    rs, gs, bs = round(rm * 0.6, 3), round(gm * 0.6, 3), round(bm * 0.6, 3)
    return ("eq=contrast=1.05:saturation=1.10,"
            f"colorbalance=rs={rs}:gs={gs}:bs={bs}:rm={rm}:gm={gm}:bm={bm}")


def _fit_title(d: ImageDraw.ImageDraw, text: str, max_w: int, max_lines: int,
               start: int, weight: str, min_size: int):
    """Maior tamanho de fonte em que o título cabe em <= max_lines (auto-shrink). Nunca deixa o texto
    estourar/quebrar o card, qualquer que seja o tamanho do texto."""
    size = start
    while size >= min_size:
        f = _font(size, weight=weight)
        lines = _wrap(d, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
        size -= 6
    f = _font(min_size, weight=weight)
    return f, _wrap(d, text, f, max_w)[:max_lines]


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
                 co_logos, site: str) -> None:
    """Rodapé da marca: logo embaixo-ESQUERDA + site embaixo-DIREITA, alinhados. co_logos = LISTA de variantes;
    escolhe a de MELHOR contraste com o fundo escuro (igual carrossel: branca em fundo escuro)."""
    fc = VH - 96                                                  # centro vertical do rodapé
    lg = None
    try:
        _paths = co_logos if isinstance(co_logos, list) else ([co_logos] if co_logos else [])
        if _paths:
            lg = _pick_logo_variant(_paths, 28, 240, 56)          # fundo escuro (gradiente do rodapé) → variante clara
    except Exception:
        lg = None
    if lg is None:                                                # fallback: 1ª logo crua
        _p0 = (co_logos[0] if isinstance(co_logos, list) and co_logos else co_logos)
        lg = _logo_h(_p0, 56)
    if lg:
        canvas.alpha_composite(lg, (60, fc - lg.height // 2))     # embaixo-esquerda, centrado em fc
    st = (site or "").replace("https://", "").replace("http://", "").strip("/")
    if st:
        d.text((VW - 60, fc), st, font=_font(44, weight="semibold"),
               fill=(255, 255, 255, 235), anchor="rm")            # embaixo-direita, centrado em fc (alinhado)


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


def _clip_overlay_png(caption: str, colors: Dict[str, Any], co_logos, site: str, path: str) -> None:
    """Overlay transparente 1080x1920 p/ cada clipe: LEGENDA tech (gradiente, sem caixa) + RODAPÉ da marca
    (logo de melhor contraste + site) — igual à arte do carrossel. co_logos = LISTA de variantes."""
    canvas = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    # gradiente sutil só no TOPO e na BASE (legibilidade da marca); MEIO fica livre — o texto da mensagem
    # fica por conta da IA (não trava posição).
    grad = Image.new("L", (1, VH), 0)
    gp = grad.load()
    for y in range(VH):
        f = max((y - (VH - 280)) / 280.0, 0.0)        # só a BASE (legibilidade do rodapé logo+site)
        gp[0, y] = int(min(1.0, f) * 175)
    grad = grad.resize((VW, VH))
    dark = Image.new("RGBA", (VW, VH), (8, 7, 11, 255)); dark.putalpha(grad)
    canvas.alpha_composite(dark)
    _brand_frame(canvas, d, colors, co_logos, site)   # MESMA marca da capa/CTA (variante por fundo)
    canvas.save(path)


def _cta_card_png(cta: Dict[str, Any], colors: Dict[str, Any], co_logos,
                  site: str, handle: str, path: str, app_logos=None) -> None:
    """CTA 9:16. PRIMEIRO tenta o MESMO motor do carrossel (compose_card_slide → identidade IDÊNTICA: cor, fonte,
    layout editorial, eyebrow+headline+subtítulo+botão, LOGO por contraste + LOGO DO APP carimbada).
    co_logos = LISTA de variantes da marca; app_logos = dict {nome:[variantes]}. Só cai no PIL se o motor falhar."""
    try:
        from .template_composer import compose_card_slide
        slide = {"type": "cta", "eyebrow": (cta.get("eyebrow") or "").strip(),
                 "title": (cta.get("title") or "Fale com a gente").strip(),
                 "subtitle": (cta.get("subtitle") or "").strip(),
                 "cta": (cta.get("cta") or "Fale com a gente").strip()}
        png = compose_card_slide(slide, 1, 1, colors, co_logos, site, handle,
                                 _brand_bg_bytes(colors), None, None, app_logos, (VW, VH))
        if png and len(png) > 2000:
            # O motor NÃO carimba logo de app no slide tipo 'cta' → carimbo aqui a logo do app EM FOCO (ex.: Deezer)
            # na área central-baixa (mostra o app + preenche o 9:16). Variante por contraste com o fundo escuro.
            try:
                variants = next((v for v in (app_logos or {}).values() if v), None)
                if variants:
                    im = Image.open(io.BytesIO(png)).convert("RGBA")
                    alg = _pick_logo_variant(variants, 30, 520, 230)     # fundo escuro → variante clara/colorida
                    if alg:
                        im.alpha_composite(alg, ((VW - alg.width) // 2, int(VH * 0.60)))
                    b = io.BytesIO(); im.convert("RGB").save(b, "PNG"); png = b.getvalue()
            except Exception:
                pass
            with open(path, "wb") as f:
                f.write(png)
            return
    except Exception:
        pass
    acc = _hex((colors or {}).get("accent") or (colors or {}).get("primary"), ORANGE)
    _p0 = (co_logos[0] if isinstance(co_logos, list) and co_logos else co_logos)   # fallback PIL: 1ª variante
    canvas = Image.open(io.BytesIO(_brand_bg_bytes(colors))).convert("RGBA")
    d = ImageDraw.Draw(canvas)
    eyebrow = (cta.get("eyebrow") or "").strip().upper()
    title = (cta.get("title") or "Fale com a gente").strip()
    btn = (cta.get("cta") or "Fale com a gente").strip()
    phone = (cta.get("phone") or "").strip()
    st = (site or "").replace("https://", "").replace("http://", "").strip("/")
    M = 90
    inner = VW - 2 * M
    tf, tl = _fit_title(d, title, inner, 3, 96, "extrabold", 52)
    # logo GRANDE (~tamanho do texto) ACIMA do título + bloco centralizado verticalmente
    big = _logo_h(_p0, 120)
    bh = ((big.height + 44) if big else 0) + len(tl) * int(tf.size * 1.05) + 30 + 110 + (78 if phone else 0)
    ty = max(180, (VH - bh) // 2 - 40)
    if big:
        canvas.alpha_composite(big, (M, ty)); ty += big.height + 44
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
    # rodapé igual ao do clipe (logo embaixo-esq + site embaixo-dir alinhados) → transição limpa + 2ª logo (a grande no topo)
    _brand_frame(canvas, d, colors, co_logos, site)
    canvas.convert("RGB").save(path)


def _has_audio(path: str) -> bool:
    """True se o arquivo tem faixa de áudio (p/ preservar o áudio NATIVO do clipe, ex.: trilha da Comet)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=20)
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def _media_dur(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nk=1:nw=1", path], capture_output=True, text=True, timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _mux_audio(base_path: str, out_path: str, narration_path: Optional[str],
               music_path: Optional[str]) -> bool:
    """Mixa o áudio final sobre o vídeo (que já tem faixa silenciosa): narração (volume cheio) + trilha (bed
    abaixado = duck). Sem áudio → copia o base. -c:v copy (não re-encoda vídeo). Determinístico."""
    import shutil
    has_n = bool(narration_path and os.path.exists(narration_path))
    has_m = bool(music_path and os.path.exists(music_path))
    if not has_n and not has_m:
        try:
            shutil.copy(base_path, out_path); return True
        except Exception:
            return False
    dur = _media_dur(base_path)
    if dur <= 0:
        try:
            shutil.copy(base_path, out_path); return True
        except Exception:
            return False
    args = ["-i", base_path]
    if has_n:
        args += ["-i", narration_path]
    if has_m:
        args += ["-stream_loop", "-1", "-i", music_path]
    n_idx = 1 if has_n else None
    m_idx = (2 if has_n else 1) if has_m else None
    if has_n and has_m:
        fc = (f"[{n_idx}:a]volume=1.0,apad[n];[{m_idx}:a]volume=0.16[m];"
              "[n][m]amix=inputs=2:duration=longest:dropout_transition=0,volume=1.5[a]")
    elif has_n:
        fc = f"[{n_idx}:a]volume=1.0,apad[a]"
    else:
        fc = f"[{m_idx}:a]volume=0.5[a]"
    return _ff(args + ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-t", f"{dur:.2f}",
                       "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", out_path], timeout=300)


def compose_branded_video(clips: List[Dict[str, Any]], out_path: str,
                          colors: Dict[str, Any], co_logos,
                          cta: Dict[str, Any], site: str = "", handle: str = "",
                          narration_path: Optional[str] = None, music_path: Optional[str] = None,
                          app_logos=None) -> bool:
    """clips=[{'path','caption','seconds'}] (já gerados) → 1 vídeo 9:16 branded (rodapé+legenda) + card de CTA
    + ÁUDIO do briefing. Áudio nativo do provedor é descartado: voz/trilha precisa ser consistente e controlada pelo
    sistema, não pelo modelo de vídeo."""
    tmp = tempfile.mkdtemp(prefix="vid_")
    segs = []
    for i, c in enumerate(clips):
        cp = c.get("path")
        if not cp or not os.path.exists(cp):
            continue
        ov = os.path.join(tmp, f"ov{i}.png")
        _clip_overlay_png(c.get("caption") or "", colors, co_logos, site, ov)
        seg = os.path.join(tmp, f"seg{i}.mp4")
        try:
            target_seconds = float(c.get("seconds") or 0)
        except Exception:
            target_seconds = 0.0
        trim = f"trim=duration={target_seconds:.3f},setpts=PTS-STARTPTS," if target_seconds > 0 else ""
        fc = (f"[0:v]{trim}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
              f"{_grade_filter(colors)}[v];[v][1:v]overlay=0:0[vout]")
        cmd = ["-i", cp, "-i", ov, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
               "-filter_complex", fc, "-map", "[vout]", "-map", "2:a"]
        ok = _ff(cmd + ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-ar", "44100", "-shortest", seg])
        if ok:
            segs.append(seg)
    if not segs:
        return False
    cta_png = os.path.join(tmp, "cta.png")
    _cta_card_png(cta, colors, co_logos, site, handle, cta_png, app_logos)
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
    base = os.path.join(tmp, "base.mp4")
    if not _ff(inputs + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", base],
               timeout=300):
        return False
    # áudio do briefing por cima do vídeo (que já tem faixa silenciosa): narração/trilha mixados
    return _mux_audio(base, out_path, narration_path, music_path)
