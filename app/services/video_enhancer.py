from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from ..db import async_job_get, async_job_put

logger = logging.getLogger("video_enhancer")

ASYNC_KIND = "video_enhancer"

_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm"}
_MAX_SIZE_BYTES_DEFAULT = int(os.environ.get("VIDEO_ENHANCER_MAX_SIZE_MB", "4096")) * 1024 * 1024

# ── Env config ─────────────────────────────────────────────────────────────
VIDEO2X_PATH = os.environ.get("VIDEO2X_PATH", "video2x")
VIDEO_OUTPUT_RESOLUTION = os.environ.get("VIDEO_OUTPUT_RESOLUTION", "720p")

_RESOLUTION_SCALE = {
    "720p":  {"height": 720,  "scale": 2},
    "1080p": {"height": 1080, "scale": 4},
}

_STORAGE_ROOT: Optional[str] = None


def _storage_root() -> str:
    global _STORAGE_ROOT
    if _STORAGE_ROOT:
        return _STORAGE_ROOT
    base = os.environ.get("VIDEO_STORAGE_PATH") or ""
    if not base:
        media_root = os.environ.get("LOCAL_MEDIA_ROOT", "/media")
        base = os.path.join(media_root, "enhancer")
    _STORAGE_ROOT = base
    return _STORAGE_ROOT


def _ensure_dirs() -> Dict[str, str]:
    root = _storage_root()
    dirs = {
        "original":  os.path.join(root, "original"),
        "processed": os.path.join(root, "processed"),
        "temp":      os.path.join(root, "temp"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def _patch(job_id: str, data: Dict[str, Any]) -> None:
    current = async_job_get(kind=ASYNC_KIND, job_id=job_id) or {}
    current.update(data)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    async_job_put(kind=ASYNC_KIND, job_id=job_id, payload=current)


# ── Video2X availability check ──────────────────────────────────────────────
def check_video2x() -> tuple[bool, str]:
    """Return (available, version_or_error)."""
    binary = VIDEO2X_PATH
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        out = (result.stdout + result.stderr).strip()
        if result.returncode == 0 or out:
            return True, out.split("\n")[0][:80]
        return False, "video2x retornou código de saída não-zero sem output"
    except FileNotFoundError:
        return False, (
            f"'{binary}' não encontrado. "
            "Instale: pip install video2x  "
            "ou defina VIDEO2X_PATH para o binário correto."
        )
    except Exception as e:
        return False, str(e)


# ── Validation ──────────────────────────────────────────────────────────────
def validate_input(
    file_path: str,
    max_size_bytes: int = _MAX_SIZE_BYTES_DEFAULT,
) -> Optional[str]:
    """Return error string or None if valid."""
    if not os.path.exists(file_path):
        return f"Arquivo não encontrado: {file_path}"
    ext = Path(file_path).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return f"Formato não permitido: '{ext}'. Permitidos: {', '.join(_ALLOWED_EXTENSIONS)}"
    size = os.path.getsize(file_path)
    if size == 0:
        return "Arquivo vazio."
    if size > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        return f"Arquivo muito grande: {size // (1024*1024)}MB (máximo {max_mb}MB)"
    return None


# ── Core runner ─────────────────────────────────────────────────────────────
def _build_video2x_cmd(
    input_path: str,
    output_path: str,
    resolution: str,
) -> list[str]:
    cfg = _RESOLUTION_SCALE.get(resolution) or _RESOLUTION_SCALE["720p"]
    scale = cfg["scale"]
    binary = VIDEO2X_PATH
    # v6.x: video2x -i in -o out -s N -p realesrgan
    return [
        binary,
        "-i", input_path,
        "-o", output_path,
        "-s", str(scale),
        "-p", "realesrgan",
    ]


def _build_ffmpeg_upscale_cmd(
    input_path: str,
    output_path: str,
    resolution: str,
) -> list[str]:
    """CPU fallback using ffmpeg lanczos upscale when no GPU/Vulkan available."""
    cfg = _RESOLUTION_SCALE.get(resolution) or _RESOLUTION_SCALE["720p"]
    height = cfg["height"]
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"scale=-2:{height}:flags=lanczos",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-movflags", "+faststart",
        "-c:a", "copy",
        output_path,
    ]


def _vulkan_available() -> bool:
    """Quick check: try video2x --list-devices, returns True if Vulkan works."""
    try:
        r = subprocess.run(
            [VIDEO2X_PATH, "--list-devices"],
            capture_output=True, text=True, timeout=10,
        )
        out = (r.stdout + r.stderr).lower()
        return "failed" not in out and r.returncode == 0
    except Exception:
        return False


async def run_enhance_job(job_id: str) -> None:
    job = async_job_get(kind=ASYNC_KIND, job_id=job_id)
    if not job:
        return

    input_path  = str(job.get("input_path") or "")
    output_path = str(job.get("output_path") or "")
    resolution  = str(job.get("resolution") or VIDEO_OUTPUT_RESOLUTION)

    logger.info("[video_enhancer] job=%s início input=%s resolution=%s", job_id, input_path, resolution)
    _patch(job_id, {"status": "running", "detail": "Iniciando processamento…", "progress_pct": 5})

    # Validate Video2X
    available, msg = check_video2x()
    if not available:
        logger.error("[video_enhancer] job=%s video2x indisponível: %s", job_id, msg)
        _patch(job_id, {"status": "error", "detail": f"Video2X não instalado: {msg}", "progress_pct": 0})
        return

    # Validate input
    err = validate_input(input_path)
    if err:
        logger.error("[video_enhancer] job=%s validação falhou: %s", job_id, err)
        _patch(job_id, {"status": "error", "detail": err, "progress_pct": 0})
        return

    use_gpu = _vulkan_available()
    if use_gpu:
        cmd = _build_video2x_cmd(input_path, output_path, resolution)
        method = f"Video2X RealESRGAN ({resolution})"
    else:
        cmd = _build_ffmpeg_upscale_cmd(input_path, output_path, resolution)
        method = f"ffmpeg lanczos CPU ({resolution}) — sem GPU Vulkan detectada"

    logger.info("[video_enhancer] job=%s method=%s cmd: %s", job_id, method, " ".join(cmd))
    _patch(job_id, {"status": "running", "detail": f"Executando {method}…", "progress_pct": 10, "command": " ".join(cmd), "method": method})

    try:
        dirs = _ensure_dirs()
        err_log = os.path.join(dirs["temp"], f"{job_id}.err")
        with open(err_log, "wb") as ferr:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=ferr,
            )
            await proc.wait()
        rc = proc.returncode if proc.returncode is not None else -1
    except Exception as exc:
        logger.exception("[video_enhancer] job=%s subprocess falhou", job_id)
        _patch(job_id, {"status": "error", "detail": f"Erro ao executar Video2X: {exc}", "progress_pct": 0})
        return

    if rc != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        try:
            with open(err_log, "r", errors="replace") as f:
                err_txt = f.read()[-400:]
        except Exception:
            err_txt = "(sem log)"
        logger.error("[video_enhancer] job=%s falhou rc=%d err=%s", job_id, rc, err_txt[-200:])
        _patch(job_id, {"status": "error", "detail": f"Video2X falhou (rc={rc}): {err_txt[-200:]}", "progress_pct": 0})
        return

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    logger.info("[video_enhancer] job=%s concluído output=%s size=%.1fMB", job_id, output_path, size_mb)

    media_root = os.environ.get("LOCAL_MEDIA_ROOT", "/media")
    rel = os.path.relpath(output_path, media_root)
    output_object_key = f"local:{rel}" if not rel.startswith("..") else ""

    _patch(job_id, {
        "status": "done",
        "detail": f"✓ Vídeo melhorado ({resolution}). {size_mb:.1f}MB",
        "progress_pct": 100,
        "output_path": output_path,
        "output_object_key": output_object_key,
        "output_size_mb": round(size_mb, 2),
    })
