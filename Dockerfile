FROM ubuntu:24.04 AS video2x-stage
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
    libvulkan1 libboost-program-options1.83.0 \
    libavcodec60 libavformat60 libavutil58 libavfilter9 libswscale7 libswresample4 \
  && wget -q "https://github.com/k4yt3x/video2x/releases/download/6.3.1/video2x-linux-ubuntu2404-amd64.deb" -O /tmp/video2x.deb \
  && apt-get install -y --no-install-recommends /tmp/video2x.deb \
  && rm /tmp/video2x.deb \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /video2x-deps \
  && cp /usr/bin/video2x /video2x-deps/ \
  && cp /usr/lib/libvideo2x.so /video2x-deps/ \
  && cp /usr/lib/librealesrgan-ncnn-vulkan.so /video2x-deps/ \
  && cp /usr/lib/librealcugan-ncnn-vulkan.so /video2x-deps/ \
  && cp /usr/lib/librife-ncnn-vulkan.so /video2x-deps/ \
  && ldd /usr/bin/video2x /usr/lib/libvideo2x.so \
       /usr/lib/librealesrgan-ncnn-vulkan.so \
       /usr/lib/librealcugan-ncnn-vulkan.so \
       /usr/lib/librife-ncnn-vulkan.so \
     | awk '/=> \// {print $3}' | sort -u \
     | grep -vE 'libc\.so|libpthread|libdl\.so|librt\.so|libm\.so|libgcc|ld-linux|libgomp|libstdc\+\+|libvulkan|libGL|libcrypto|libssl|libz\.so|liblzma|libbz2|libxml|libxslt' \
     | xargs -I{} cp --no-clobber {} /video2x-deps/ 2>/dev/null || true \
  && cp /usr/share/video2x /video2x-deps/share -r 2>/dev/null || true

FROM python:3.12-slim

WORKDIR /app

# System deps for lxml + media utils + Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    ffmpeg \
    libgomp1 \
    # Playwright / Chromium runtime deps
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    fonts-liberation \
    libglib2.0-0 \
    libvulkan1 \
    wget \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy Video2X binary + Ubuntu 24.04 deps — isolated to avoid conflicts with Debian libs
COPY --from=video2x-stage /video2x-deps /opt/video2x-deps
RUN mv /opt/video2x-deps/share /usr/share/video2x 2>/dev/null || true \
  && mkdir -p /opt/video2x-libs \
  && mv /opt/video2x-deps/video2x /opt/video2x-libs/video2x-bin \
  && mv /opt/video2x-deps/*.so* /opt/video2x-libs/ 2>/dev/null || true \
  && rm -rf /opt/video2x-deps \
  && printf '#!/bin/sh\nexec env LD_LIBRARY_PATH=/opt/video2x-libs:$LD_LIBRARY_PATH /opt/video2x-libs/video2x-bin "$@"\n' > /usr/local/bin/video2x \
  && chmod +x /usr/local/bin/video2x

# Install Playwright browsers (Chromium only to keep image size down)
# Set to skip if PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 for lighter builds
RUN python -m playwright install chromium 2>/dev/null || echo "[Dockerfile] Playwright browser install skipped or failed — publisher module requires manual install"

ARG CACHE_BUST=1
COPY app /app/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ADULT_META_DB_PATH=/data/runs.db \
    ADULT_META_MEDIA_ROOT=/data/media \
    TMPDIR=/media/_tmp/system \
    TEMP=/media/_tmp/system \
    TMP=/media/_tmp/system \
    OLLAMA_BASE_URL=http://172.20.0.1:11434 \
    UVICORN_WORKERS=1

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=8s --start-period=30s --retries=5 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health', timeout=7)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8765 --timeout-keep-alive 600 --workers ${UVICORN_WORKERS:-1}"]
