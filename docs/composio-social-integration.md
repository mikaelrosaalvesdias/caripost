# Integração Social Via Composio

## Visão Geral

A Social Integration Layer adiciona publicação e integração social sem mexer em vídeo, upload, cortes, transcrição ou storage. O app usa mídia já pronta apenas como URL pública.

Fluxo:

1. O usuário conecta uma conta social pelo Composio.
2. O app salva a conexão em `social_connections`.
3. O usuário cria um post social aprovado.
4. O post é publicado agora ou fica agendado.
5. O worker publica cada canal e salva status/logs.

O publicador legado em `/api/publisher` permanece separado.

## Variáveis De Ambiente

Obrigatórias para uso real:

```env
COMPOSIO_API_KEY=
COMPOSIO_BASE_URL=https://backend.composio.dev
COMPOSIO_PROJECT_ID=
COMPOSIO_WEBHOOK_SECRET=
```

Auth configs por plataforma:

```env
COMPOSIO_AUTH_CONFIG_INSTAGRAM=
COMPOSIO_AUTH_CONFIG_FACEBOOK=
COMPOSIO_AUTH_CONFIG_YOUTUBE=
COMPOSIO_AUTH_CONFIG_TIKTOK=
```

Tool slugs opcionais. Se ausentes, o provider tenta descobrir pela API de tools:

```env
COMPOSIO_TOOL_INSTAGRAM_PUBLISH=
COMPOSIO_TOOL_FACEBOOK_PUBLISH=
COMPOSIO_TOOL_YOUTUBE_PUBLISH=
COMPOSIO_TOOL_TIKTOK_PUBLISH=
```

Teste local sem API externa:

```env
SOCIAL_PROVIDER=mock
```

## Rotas

- `POST /api/social/connect`
- `POST /api/social/callback`
- `GET /api/social/accounts?brandId=...`
- `DELETE /api/social/accounts/{id}`
- `POST /api/social/posts`
- `POST /api/social/posts/{id}/publish`
- `GET /api/social/posts/{id}/status`
- `GET /api/social/posts/{id}/metrics`
- `POST /api/social/worker/run`
- `GET /api/social/competitors?brandId=...`
- `POST /api/social/competitors`
- `POST /api/social/competitors/{id}/analyze`
- `GET /api/social/references?brandId=...`
- `POST /api/social/references`

## Conectar Plataformas

No app OS, abra `Publicar`, selecione a marca/cliente e clique em Instagram, Facebook, YouTube ou TikTok. O backend chama `connected_accounts/link` do Composio e retorna a URL de autenticação.

Se aparecer erro de auth config, configure a variável correspondente, por exemplo:

```env
COMPOSIO_AUTH_CONFIG_INSTAGRAM=ac_...
```

## Publicar

Para publicar é obrigatório:

- marca/cliente existente;
- canal conectado;
- conteúdo marcado como aprovado;
- URL pública da mídia quando a plataforma exigir mídia.

O sistema não converte nem modifica arquivos. Instagram, YouTube e TikTok exigem URL pública/acessível para mídia.

## Agendamento

Posts com `scheduledAt` futuro entram como `scheduled`. O APScheduler roda o worker social a cada 3 minutos e publica posts vencidos com lock/idempotência.

## Logs

Cada tentativa gera registro em `social_post_logs` com:

- post;
- canal;
- plataforma;
- status;
- erro resumido, quando houver;
- payload sanitizado sem tokens/secrets.

## Teste Mock

```bash
python scripts/social_smoke.py
```

Esse teste cria banco temporário, conexão mock, bloqueia publicação sem aprovação, processa um agendamento e valida status/logs.

## Teste Real

1. Configure `COMPOSIO_API_KEY`.
2. Configure o auth config da plataforma.
3. Abra `/os/`.
4. Acesse `Publicar`.
5. Conecte uma conta social.
6. Crie um post aprovado com URL pública.
7. Clique em `Publicar agora`.
8. Consulte o status na própria tela ou em `/api/social/posts/{id}/status`.

## Limitações Conhecidas

- Tool slugs variam conforme o projeto Composio; use as variáveis `COMPOSIO_TOOL_*` se a descoberta automática escolher a ferramenta errada.
- Métricas e análise de concorrente dependem das permissões e ferramentas disponíveis no Composio.
- Publicação social usa mídia pronta via URL. Processamento de vídeo permanece fora desta integração.
