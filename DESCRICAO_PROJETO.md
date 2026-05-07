# Adult Meta - Documentacao Tecnica do Projeto

## 1. Resumo
O **Adult Meta** e uma plataforma web interna para operacao de conteudo adulto, cobrindo o fluxo completo de:

1. upload de video,
2. transcricao,
3. analise automatica,
4. busca de referencias no XVideos,
5. geracao/edicao de metadados,
6. comparacao de LLMs,
7. processamento de video (legenda, logo, teaser),
8. criacao e agendamento de posts.

A aplicacao e composta por backend em FastAPI, frontend em HTML/CSS/JavaScript (sem framework), banco SQLite e armazenamento S3-compativel (MinIO).

---

## 2. Linguagens e Tecnologias

### Linguagens de programacao
- Python 3.12 (backend e scripts)
- JavaScript ES2022+ (frontend)
- HTML5
- CSS3
- Bash (scripts utilitarios)

### Backend (Python)
- FastAPI `0.133.1`
- Uvicorn `0.41.0`
- Pydantic `>=2,<3`
- httpx `0.28.1`
- sse-starlette `3.2.0`
- boto3 `1.40.32`
- python-multipart `0.0.9`
- faster-whisper `1.1.1`
- xvideos_api `1.8.3`
- beautifulsoup4 `4.14.3`
- lxml `6.0.0`

### Frontend
- SPA sem build step
- Arquivos principais: `app/ui/index.html`, `app/ui/app.js`, `app/ui/style.css`

### Banco e Storage
- SQLite (`data/runs.db`) para runs, settings e posts agendados
- MinIO / S3 compativel para videos e artefatos de processamento

### Infra e softwares
- Docker (`python:3.12-slim`)
- Docker Swarm (`stack.yml`)
- Traefik (roteamento HTTPS)
- ffmpeg + ffprobe (transcodificacao, legenda, teaser, metadados)
- libgomp1 (suporte runtime para componentes nativos como whisper)

---

## 3. APIs e Integracoes

### APIs externas de IA
- OpenAI (chat completions e Whisper)
- Groq (Whisper)
- xAI/Grok (chat/vision)
- DeepSeek (OpenAI-compatible)
- Google Gemini (endpoint OpenAI-compatible)
- OpenRouter (endpoint OpenAI-compatible)
- Ollama local (via `OLLAMA_BASE_URL`)

### Fonte externa de referencia
- XVideos (via biblioteca `xvideos_api` + parsing complementar)

### API interna (REST)
A API principal esta em `app/main.py` e expoe rotas para:
- healthcheck
- busca XVideos
- analise do video
- historico de runs
- transcricao
- comparacao de LLMs
- upload/listagem/download no S3
- burn de legenda
- geracao de teaser
- criacao/agendamento de post
- gerenciamento de tokens

---

## 4. Arquitetura de Pastas

```text
adult-meta/
├── app/
│   ├── main.py            # API FastAPI e regras de negocio
│   ├── db.py              # Camada SQLite
│   ├── llm.py             # Integracao multi-provider de LLM (stream e nao-stream)
│   ├── xvideos_source.py  # Busca e normalizacao de dados do XVideos
│   └── ui/
│       ├── index.html     # Estrutura da interface web
│       ├── app.js         # Logica SPA
│       └── style.css      # Estilos auxiliares
├── data/
│   └── runs.db            # Banco local
├── scripts/
│   ├── smoke.sh           # Teste de fumaca da API
│   ├── fix_cors.py        # Ajuste de CORS no bucket
│   └── test_upload_public.py
├── Dockerfile
├── requirements.txt
├── stack.yml
└── run.sh
```

---

## 5. Funcionalidades do Projeto

### 5.1 Referencias XVideos
- Top videos (`/xvideos/top`)
- Busca geral (`/xvideos/search`)
- Busca por pornstar (`/xvideos/pornstar`)
- Busca por canal/studio (`/xvideos/channel`)
- Filtros de duracao, views e likes (parte nativa + pos-filtro)

### 5.2 Upload de video
- Upload chunked multipart para arquivos grandes:
  - `POST /uploads/chunk/init`
  - `POST /uploads/chunk/part`
  - `POST /uploads/chunk/complete`
- Upload proxy backend:
  - `GET/POST /uploads/proxy`
- Listagem de objetos:
  - `GET /uploads/list`
- Presign para upload direto:
  - `POST /uploads/presign`

### 5.3 Transcricao
- `POST /transcribe`
- Providers suportados no endpoint:
  - `local` (faster-whisper)
  - `openai`
  - `groq`
- Gera texto + segmentos + SRT

### 5.4 Analise principal
- `POST /analyze`
- Consolida:
  - metadados do video (ffprobe)
  - analise de frames (vision)
  - transcricao
  - referencias XVideos
  - prompt markdown para geracao de conteudo
- Persiste resultado em `runs`

### 5.5 Runs (historico)
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/srt`
- `PUT /runs/{run_id}/transcript`
- `POST /runs/{run_id}/reprompt`
- `POST /runs/{run_id}/fetch-refs`

### 5.6 Comparacao de LLMs
- Streaming SSE: `POST /llm/compare/stream`
- Resultado consolidado: `POST /llm/compare`
- Ate 2 providers por chamada

### 5.7 Processamento de video
- Burn de legenda + logo (job assinc):
  - `POST /api/burn-subtitles`
  - `GET /api/burn-subtitles/status/{job_id}`
- Teaser automatico (job assinc):
  - `POST /api/teaser/generate`
  - `GET /api/teaser/status/{job_id}`
- Concatenacao teaser + principal:
  - `POST /api/teaser/prepend`

### 5.8 Screenshot vision
- `POST /api/screenshot/analyze`
- Envia imagem base64 para analise visual

### 5.9 Criacao e agendamento de post
- Geracao de post:
  - `POST /api/create-post`
- Agendamento:
  - `POST /api/scheduled-posts`
  - `GET /api/scheduled-posts`
  - `PATCH /api/scheduled-posts/{post_id}`

### 5.10 Settings e seguranca
- Lista tokens cadastrados (sem revelar valor):
  - `GET /settings/tokens`
- Grava token:
  - `POST /settings/tokens`
- Autenticacao opcional por `X-API-Key` (controlada por `ADULT_META_API_KEY`)

---

## 6. Frontend (Paginas e Modulos)
A interface SPA (arquivo unico) possui abas:
- Analyze
- Compare
- Runs
- Criacao
- Referencia
- Settings

Recursos principais da UI:
- upload chunked com progresso
- transcricao automatica pos-upload
- renderizacao de resultado por tabs (Prompt/SRT/Vision/JSON)
- comparacao de LLM em streaming
- selecao de referencias para reprompt
- editor de SRT
- geracao de video legendado
- geracao de teaser e concat
- mock de preview de post
- agendamento de posts

---

## 7. Banco de Dados (SQLite)
Tabelas criadas em `init_db()`:
- `runs`
  - `id`, `created_at`, `source`, `request_json`, `result_json`, `error`
- `settings`
  - `key`, `value`, `updated_at`
- `scheduled_posts`
  - `id`, `run_id`, `post_data`, `schedule_at`, `status`, `created_at`

---

## 8. Variaveis de Ambiente Principais
- `ADULT_META_API_KEY`
- `ADULT_META_DB_PATH`
- `S3_ENDPOINT_URL`
- `S3_REGION`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`
- `S3_PUBLIC_BASE_URL`
- `OLLAMA_BASE_URL`

---

## 9. Execucao

### Local
1. Criar/ativar virtualenv
2. Instalar deps: `pip install -r requirements.txt`
3. Configurar variaveis de ambiente
4. Rodar: `./run.sh` (ou `uvicorn app.main:app --host 0.0.0.0 --port 8765`)

### Docker
- Build via `Dockerfile`
- Deploy via Swarm usando `stack.yml`
- Porta interna da API: `8765`

---

## 10. Pontos de Atencao Tecnicos
- `POST /settings/tokens` atualmente aceita apenas `openai`, `deepseek` e `openrouter`, embora a UI mostre outros provedores.
- Tokens sao armazenados em texto puro no SQLite (ha TODO no codigo para criptografia at-rest).
- O estado de jobs assinc (`_burn_jobs`, `_teaser_jobs`) e em memoria de processo.
- CORS da app esta aberto (`allow_origins=["*"]`) e a autenticacao depende da configuracao de `ADULT_META_API_KEY`.

---

## 11. Arquivos de Referencia para manutencao
- Backend API: `app/main.py`
- Integracao LLM: `app/llm.py`
- Scraping XVideos: `app/xvideos_source.py`
- Persistencia: `app/db.py`
- Frontend: `app/ui/index.html` + `app/ui/app.js`
- Dependencias: `requirements.txt`
- Container: `Dockerfile`
- Orquestracao: `stack.yml`

