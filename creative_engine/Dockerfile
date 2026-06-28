FROM python:3.11-slim

# libs de sistema p/ opencv + mediapipe (CPU-only)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# baixa o peso do YOLO no build (evita download na 1ª request)
RUN python -c "from ultralytics import YOLO; YOLO('yolo11n-seg.pt')" || true

COPY . .
ENV YOLO_WEIGHTS=yolo11n-seg.pt
# uso: docker run --rm -v $PWD:/data img /data/in.png --config /data/blocks.json -o /data/out.png --debug
ENTRYPOINT ["python", "/app/__main__.py"]
