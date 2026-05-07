# MetaPorn — Documentação do Projeto

> Ferramenta interna de automação de conteúdo adulto: desde a pesquisa de referências no XVideos até a geração de texto com IA, edição de vídeo e agendamento de publicação.

---

## Visão Geral

O MetaPorn é uma aplicação web full-stack que centraliza o fluxo de criação de conteúdo adulto. Ele integra scraping de vídeos de referência, geração de textos/metadados por IA, transcrição de áudio, edição de vídeo (legendas, logo, teaser), armazenamento em nuvem e agendamento de posts.

**URL de produção:** `https://metaporn.n8nmikael.com.br`

---

## Stack de Tecnologias

### Back-end

| Tecnologia | Versão | Papel |
|---|---|---|
| **Python** | 3.12 | Linguagem principal do servidor |
| **FastAPI** | 0.133.1 | Framework HTTP / API REST |
| **Uvicorn** | 0.41.0 | Servidor ASGI (WSGI async) |
| **Pydantic** | v2 | Validação de modelos de dados |
| **SQLite** | — | Banco de dados local (runs, settings, posts agendados) |
| **boto3** | 1.40.32 | Cliente AWS S3 / MinIO (armazenamento de objetos) |
| **httpx** | 0.28.1 | Requisições HTTP assíncronas (chamadas a LLMs externos) |
| **sse-starlette** | 3.2.0 | Server-Sent Events (streaming de respostas de IA) |
| **faster-whisper** | 1.1.1 | Transcrição local de áudio/vídeo (modelo `small`, ~465 MB, roda em CPU) |
| **xvideos-api** | 1.8.3 | Lib Python para scraping estruturado do XVideos |
| **BeautifulSoup4** | 4.14.3 | Parsing HTML para scraping adicional |
| **lxml** | 6.0.0 | Parser XML/HTML de alta performance |

### Front-end

| Tecnologia | Papel |
|---|---|
| **HTML5 / CSS3** | Interface SPA (Single Page App) sem framework extra |
| **JavaScript (ES2022+)** | Lógica da UI: roteamento, fetch, polling de jobs, player de vídeo |
| **Vanilla JS** | Sem React, Vue ou Angular — UI leve e sem build step |

### Infraestrutura / DevOps

| Tecnologia | Papel |
|---|---|
| **Docker** | Containerização da aplicação |
| **Docker Swarm** | Orquestração (stack `metaporn`) |
| **Traefik** | Reverse proxy + TLS automático (Let's Encrypt) |
| **MinIO** | Storage S3-compatible auto-hospedado (`s3.n8nmikael.com.br`) |
| **Debian Slim** | Base do container (`python:3.12-slim`) |
| **ffmpeg** | Processamento de vídeo (legendas, logo overlay, teaser, extração de frames) |

### APIs / Serviços Externos de IA

| Provedor | Modelos suportados | Uso |
|---|---|---|
| **OpenAI** | GPT-4o, GPT-4o-mini, etc. | Geração de texto, transcrição (Whisper API) |
| **Groq** | llama-3.3-70b-versatile, whisper-large-v3, etc. | Transcrição rápida, geração de texto |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro, etc. | Geração de texto |
| **DeepSeek** | deepseek-chat, deepseek-reasoner | Geração de texto |
| **Grok (xAI)** | grok-3, grok-3-mini | Geração de texto |
| **OpenRouter** | Qualquer modelo via proxy | Acesso agregado a múltiplos modelos |
| **Ollama** | Qualquer modelo local instalado | Execução local gratuita (ex: llama3, mistral) |

---

## Arquitetura dos Arquivos

```
adult-meta/
├── Dockerfile               # Build da imagem Docker
├── requirements.txt         # Dependências Python
├── stack.yml                # Docker Swarm stack definition
└── app/
    ├── main.py              # Servidor FastAPI — toda a API REST
    ├── db.py                # Acesso ao SQLite (runs, settings, posts)
    ├── llm.py               # Camada de abstração para LLMs (stream, multi-provider)
    ├── xvideos_source.py    # Scraping do XVideos (top, search, pornstar, channel)
    └── ui/
        ├── index.html       # SPA — HTML único com todas as páginas
        └── app.js           # Toda a lógica de front-end (roteamento, UI, fetch)
```

---

## Funcionalidades

### 1. Scraping de Referências (XVideos)

- **Pesquisa geral:** busca por termo com ordenação (views, relevância, data)
- **Por atriz/pornstar:** busca vídeos de uma modelo específica
- **Por canal/studio:** busca vídeos de um canal
- **Top vídeos:** lista os mais populares do momento
- Exibe thumbnail, título, duração, views, link direto

### 2. Geração de Conteúdo com IA (`/analyze`)

- Recebe URL de vídeo do XVideos como referência
- Gera automaticamente com IA:
  - **Título** do post
  - **Descrição** detalhada
  - **Tags** otimizadas para SEO
  - **Hashtags** para redes sociais
  - **Legenda** curta
  - **Slug** para URL amigável
  - **Imagem de capa:** captura frames do vídeo e seleciona o melhor usando análise de IA
- Suporta até **2 provedores de IA em paralelo** (comparação de resultados)
- Streaming em tempo real via SSE
- Respostas exibidas simultaneamente em colunas comparativas
- Campos de texto editáveis — o usuário pode ajustar antes de aprovar

### 3. Criação de Post — Editor Completo

#### Gerenciamento de Vídeo

- Upload de vídeo via **chunked multipart** (suporte a arquivos grandes, ex: 2 GB+)
- Upload por proxy do backend (sem exposição direta do MinIO ao browser)
- Player de vídeo embutido com preview
- Seleção de frame/thumbnail do vídeo

#### Transcrição de Áudio

- **Local (grátis):** faster-whisper rodando no servidor (sem custo de API), modelo `small`
- **OpenAI Whisper:** via API
- **Groq Whisper:** via API (rápido e econômico)
- Suporte a múltiplos idiomas
- Resultado em formato SRT editável diretamente na interface

#### Editor de Vídeo — Legendas (Burn Subtitles)

- Queima as legendas SRT diretamente no vídeo usando ffmpeg
- Configurações customizáveis:
  - Tamanho da fonte (10–72 px)
  - Cor do texto (branco, amarelo, ciano, laranja, preto)
  - Delay/avanço das legendas (em segundos)
  - Resolução de saída (1080p, 720p, original)
  - Qualidade/tamanho do arquivo (CRF 20/26/30)
- **Logo overlay:** insere logo PNG no vídeo com:
  - Slider de posição Horizontal % (0=esquerda, 100=direita)
  - Slider de posição Vertical % (0=topo, 100=base)
  - Presets de posição: ↖ ↑ ↗ ↙ ↓ ↘ (TL, TC, TR, BL, BC, BR)
  - Posicionamento via fórmula ffmpeg: `(W-w)*X/100:(H-h)*Y/100`
- Processamento em background com polling de progresso
- Download direto do vídeo processado

#### Editor de Vídeo — Teaser Automático

- Detecta automaticamente as melhores cenas do vídeo via ffmpeg scene detection (`select='gt(scene,0.30)'`)
- Extrai N clips das cenas selecionadas (configurável: 3–20 cenas)
- Duração configurável por cena (2–30 segundos)
- Concatena todos os clips em um único arquivo MP4
- Qualidade configurável (CRF 20/26/30)
- Logo overlay incluída no teaser (mesma posição configurada)
- Após geração:
  - **Baixar teaser** diretamente
  - **Incluir no vídeo:** concatena teaser + vídeo legendado (`-c copy` com fallback para re-encoding)

### 4. Análise de Screenshots

- Upload de screenshot para análise por IA
- Extrai texto/contexto da imagem
- Útil para analisar frames de vídeos externos

### 5. Agendamento de Posts

- Cria posts agendados com data/hora
- Lista posts pendentes e publicados
- Atualiza status de publicação

### 6. Comparação de LLMs

- Envia mesmo prompt para até 2 provedores diferentes
- Exibe respostas lado a lado em tempo real (SSE)
- Permite comparar qualidade e velocidade dos modelos

### 7. Gerenciamento de Arquivos (MinIO)

- Lista objetos no bucket por prefixo
- URL presignada para download com nome de arquivo customizado
- Proxy de download (sem exposição de credenciais ao browser)
- Upload multipart chunked para arquivos grandes

### 8. Configurações

- Gerenciamento de API keys por provedor (OpenAI, Groq, DeepSeek, Grok, Gemini, OpenRouter)
- API key da própria aplicação (autenticação via header `X-API-Key`)
- Settings persistidos no SQLite

---

## API REST — Endpoints Principais

### XVideos / Scraping

| Método | Rota | Descrição |
|---|---|---|
| GET | `/xvideos/top` | Vídeos mais populares |
| GET | `/xvideos/search` | Busca geral (`query`, `sort`, `limit`) |
| GET | `/xvideos/pornstar` | Vídeos de uma atriz (`name`, `limit`) |
| GET | `/xvideos/channel` | Vídeos de um canal (`name`, `limit`) |

### Análise e Geração de Conteúdo

| Método | Rota | Descrição |
|---|---|---|
| POST | `/analyze` | Gera metadados do post com IA (SSE streaming) |
| POST | `/api/screenshot/analyze` | Analisa screenshot com IA |
| POST | `/llm/compare/stream` | Compara dois LLMs em paralelo (SSE) |
| POST | `/llm/compare` | Compara dois LLMs (resposta única) |

### Runs (histórico de análises)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/runs` | Lista todos os runs |
| GET | `/runs/{id}` | Detalhes de um run |
| GET | `/runs/{id}/srt` | Arquivo SRT do run |
| PUT | `/runs/{id}/transcript` | Atualiza transcrição |
| POST | `/runs/{id}/reprompt` | Re-gera campos específicos |
| POST | `/runs/{id}/fetch-refs` | Busca referências XVideos |

### Transcrição

| Método | Rota | Descrição |
|---|---|---|
| POST | `/transcribe` | Transcreve áudio/vídeo (local, OpenAI ou Groq) |

### Editor de Vídeo

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/burn-subtitles` | Inicia job de queima de legenda + logo |
| GET | `/api/burn-subtitles/status/{job_id}` | Polling do job de legenda |
| POST | `/api/teaser/generate` | Gera teaser automático (job async) |
| GET | `/api/teaser/status/{job_id}` | Polling de job de teaser ou concat |
| POST | `/api/teaser/prepend` | Concatena teaser + vídeo principal |

### Upload / Storage

| Método | Rota | Descrição |
|---|---|---|
| POST | `/uploads/presign` | Gera URL presignada para upload (não usado — CORS MinIO) |
| POST | `/uploads/proxy` | Upload via proxy do backend |
| POST | `/uploads/chunk/init` | Inicia upload multipart |
| POST | `/uploads/chunk/part` | Envia parte do chunk |
| POST | `/uploads/chunk/complete` | Finaliza upload multipart |
| GET | `/uploads/list` | Lista objetos no MinIO |
| GET | `/api/video-download-url` | URL presignada de download |

### Posts e Agendamento

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/create-post` | Cria post com dados do run |
| POST | `/api/scheduled-posts` | Agenda um post |
| GET | `/api/scheduled-posts` | Lista posts agendados |
| PATCH | `/api/scheduled-posts/{id}` | Atualiza status do post |

### Configurações

| Método | Rota | Descrição |
|---|---|---|
| GET | `/settings/tokens` | Lista API keys configuradas |
| POST | `/settings/tokens` | Salva API key de um provedor |

---

## Padrão de Jobs Assíncronos

Tarefas pesadas (burn subtitles, teaser, concat) usam o padrão:

```
1. POST /api/xxx → retorna { job_id }
2. GET  /api/xxx/status/{job_id} → polling a cada 3s
3. Quando status = "done" → result com video_url e object_key
```

Jobs são armazenados em dicionários in-memory (`_burn_jobs`, `_teaser_jobs`) e executados com `asyncio.create_task()`.

---

## Banco de Dados (SQLite)

**Tabelas:**

| Tabela | Conteúdo |
|---|---|
| `runs` | Histórico de análises (URL, metadados gerados, transcrição, frames) |
| `settings` | Configurações chave-valor (API keys, preferências) |
| `scheduled_posts` | Posts agendados com status e data/hora |

---

## Infraestrutura de Deploy

```
Internet → Traefik (TLS/HTTPS) → Docker Swarm → Container adult-meta:latest
                                                    ↕ (S3 API)
                                               MinIO (s3.n8nmikael.com.br)
```

- **Rede Docker:** `n8nmikaelnet` (externa, compartilhada com outros serviços)
- **Volume:** `adult_meta_data` → mapeado para `/data` (SQLite + modelos Whisper)
- **Memória:** limite 2 GB, reserva 128 MB
- **Porta interna:** 8765
- **Healthcheck:** GET `/health` a cada 10s

### Comandos de Deploy

```bash
# Build
docker build -t adult-meta:latest /root/clawd/adult-meta/

# Deploy (primeira vez)
docker stack deploy -c stack.yml metaporn

# Atualizar serviço em produção
docker service update --force metaporn_adult-meta
```

---

## Processamento de Vídeo (ffmpeg)

Operações realizadas pelo ffmpeg no servidor:

| Operação | Filtro / Comando |
|---|---|
| Queima de legendas | `-vf "subtitles=file.srt,overlay_logo"` |
| Logo overlay | `scale=iw*0.20:-1,format=rgba` + `overlay=(W-w)*X/100:(H-h)*Y/100` |
| Detecção de cenas | `select='gt(scene,0.30)',showinfo` → timestamps |
| Extração de clip | `-ss {t} -t {dur} -c:v libx264 -c:a aac` |
| Concatenação (fast) | `-f concat -c copy` |
| Concatenação (fallback) | `-c:v libx264 -c:a aac` (re-encoding para compatibilidade) |
| Probe de duração | `ffprobe -v quiet -print_format json -show_format` |
| Extração de frames | `-ss {t} -vframes 1 -f image2 -vcodec png` |
| Redimensionamento | `-vf scale=-2:{max_height}` (mantém aspect ratio) |

---

## Versão Atual

- **App:** v1.7.0
- **Cache bust:** `app.js?v=46`
- **Data:** 2026-03-02
