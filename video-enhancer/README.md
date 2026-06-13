# Video Enhancer — Adult Meta

Módulo de melhoria de qualidade de vídeo usando [Video2X](https://github.com/k4yt3x/video2x).

---

## O que faz

Recebe um vídeo em baixa resolução e gera uma versão melhorada (upscale) em 720p ou 1080p,
usando modelos de IA (RealESRGAN, waifu2x) via Video2X.

**Não altera:**
- Áudio (mantido intacto)
- Restante do projeto
- Nenhuma funcionalidade existente

---

## Instalação do Video2X

### Python (recomendado)

```bash
pip install video2x
```

### Via conda

```bash
conda install -c conda-forge video2x
```

### Via Docker (imagem oficial)

```bash
docker pull ghcr.io/k4yt3x/video2x:latest
```

Após instalar via Docker, defina `VIDEO2X_PATH` para um wrapper script:

```bash
#!/bin/bash
docker run --rm -v /media:/media ghcr.io/k4yt3x/video2x:latest "$@"
```

---

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `VIDEO2X_PATH` | `video2x` | Caminho para o binário do Video2X |
| `VIDEO_OUTPUT_RESOLUTION` | `720p` | Resolução padrão (720p \| 1080p) |
| `VIDEO_STORAGE_PATH` | `{LOCAL_MEDIA_ROOT}/enhancer` | Raiz de armazenamento dos vídeos |
| `VIDEO_ENHANCER_MAX_SIZE_MB` | `4096` | Tamanho máximo do arquivo em MB |

### Configurar no .env ou docker-compose

```env
VIDEO2X_PATH=/usr/local/bin/video2x
VIDEO_OUTPUT_RESOLUTION=720p
VIDEO_STORAGE_PATH=/media/enhancer
VIDEO_ENHANCER_MAX_SIZE_MB=4096
```

---

## Estrutura de Pastas (criadas automaticamente)

```
{VIDEO_STORAGE_PATH}/
├── original/    ← vídeos recebidos (input)
├── processed/   ← vídeos melhorados (output)
└── temp/        ← logs de execução do Video2X
```

---

## Endpoints

### `POST /api/video-enhancer/enhance`

Envia um vídeo para melhoria. Retorna `job_id` para acompanhar o status.

**Via upload de arquivo:**

```bash
curl -s -X POST "https://caripost.n8nmikael.com.br/api/video-enhancer/enhance?resolution=720p" \
  -H "X-API-Key: secret" \
  -F "file=@/caminho/do/video.mp4"
```

**Via referência de vídeo já armazenado:**

```bash
curl -s -X POST "https://caripost.n8nmikael.com.br/api/video-enhancer/enhance" \
  -H "X-API-Key: secret" \
  -H "Content-Type: application/json" \
  -d '{"video_object_key": "local:uploads/2026/04/meu-video.mp4", "resolution": "720p"}'
```

**Resposta:**

```json
{
  "ok": true,
  "job_id": "uuid-do-job",
  "status": "queued",
  "resolution": "720p",
  "input_path": "/media/enhancer/original/uuid.mp4",
  "output_path": "/media/enhancer/processed/meu-video_720p_abc12345.mp4",
  "status_url": "/api/video-enhancer/status/uuid-do-job"
}
```

---

### `GET /api/video-enhancer/status/{job_id}`

Acompanhar o progresso do job.

```bash
curl -s "https://caripost.n8nmikael.com.br/api/video-enhancer/status/uuid-do-job" \
  -H "X-API-Key: secret"
```

**Resposta (em processamento):**

```json
{
  "status": "running",
  "detail": "Executando Video2X (720p)…",
  "progress_pct": 10,
  "command": "video2x -i /media/enhancer/original/... -o /media/enhancer/processed/..."
}
```

**Resposta (concluído):**

```json
{
  "status": "done",
  "detail": "✓ Vídeo melhorado (720p). 245.3MB",
  "progress_pct": 100,
  "output_path": "/media/enhancer/processed/meu-video_720p_abc12345.mp4",
  "output_size_mb": 245.3
}
```

---

### `GET /api/video-enhancer/jobs`

Lista os jobs recentes.

```bash
curl -s "https://caripost.n8nmikael.com.br/api/video-enhancer/jobs?limit=10" \
  -H "X-API-Key: secret"
```

---

### `GET /api/video-enhancer/check`

Verifica se o Video2X está instalado.

```bash
curl -s "https://caripost.n8nmikael.com.br/api/video-enhancer/check" \
  -H "X-API-Key: secret"
```

**Resposta (instalado):**
```json
{"ok": true, "video2x": "Video2X 6.3.0"}
```

**Resposta (não instalado):**
```json
{
  "ok": false,
  "error": "'video2x' não encontrado. Instale: pip install video2x ...",
  "install": "pip install video2x"
}
```

---

## Pipeline

```
1. POST /enhance  →  valida formato, tamanho, existência do arquivo
2. Salva em:      →  storage/videos/original/
3. Executa:       →  video2x -i input.mp4 -o output.mp4 -s 2 (720p) | -s 4 (1080p)
4. Salva em:      →  storage/videos/processed/
5. Retorna:       →  output_path + status "done"
```

---

## Resolução — Escala

| Resolução | Scale Factor | Uso de VRAM |
|-----------|-------------|-------------|
| `720p`    | 2×          | ~2GB        |
| `1080p`   | 4×          | ~4GB        |

---

## Preparado para Docker

Adicione no `Dockerfile`:

```dockerfile
RUN pip install video2x
```

Ou passe `VIDEO2X_PATH` apontando para um wrapper externo.

No `stack.yml` / `docker-compose.yml`:

```yaml
environment:
  VIDEO2X_PATH: video2x
  VIDEO_OUTPUT_RESOLUTION: 720p
  VIDEO_ENHANCER_MAX_SIZE_MB: 4096
```
