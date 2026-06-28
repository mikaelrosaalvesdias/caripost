# Fluxo Social Standalone + Conexões Composio + Identidade Multi-Produto

**Data:** 2026-06-20
**Status:** Aprovado (desenho). Implementação só após comando "implementa".
**Cliente-referência:** Cariap (agência, 12+ produtos).

---

## 1. Contexto e problema

A plataforma (Caripost OS — shell estilo desktop com janelas/apps) hoje coloca **todo** o
trabalho social dentro do detalhe de cada cliente (`apps-clientes.jsx` → abas Fluxo / Gerar
Conteúdo). Dores levantadas pelo usuário:

1. **Fluxo preso dentro do cliente.** Briefing → criação → aprovação → agendamento estão
   dentro de `CompanyDetail`. Precisa virar um **fluxo standalone** (igual ao "auto"/
   `auto-wizard.jsx`: passos no topo, full-screen), sem mudar a identidade visual.
2. **Redes sociais não conectam (503).** `POST /api/social/connect` →
   `composio_provider._auth_config_id(platform)` exige um `auth_config_id` por plataforma vindo
   de env var/Settings; quando falta, levanta **503**. O usuário só colocou a API key do
   Composio. O código **nunca cria** o auth config.
3. **`POST /api/social/brands/{id}/analyze` retorna 500.** Tudo embrulhado em `try/except` →
   qualquer falha (provável a chamada de IA) vira 500 genérico, sem expor o erro real.
4. **Sem lugar pra múltiplos logos** da empresa principal e **sem catálogo de produtos**
   (cada produto tem logo/cores/site/IG próprios), que devem servir de **fonte** pra geração.

### Verdito Composio (validado em docs.composio.dev)
- O fluxo "clicar no ícone da rede → conectar só com a API key" **é possível** via
  **managed auth**: `auth_configs.create(toolkit, {type: use_composio_managed_auth})` usa o
  OAuth do próprio Composio (não precisa registrar app). Guarda-se o `auth_config_id`.
- Conexão: `connected_accounts.link(user_id, auth_config_id, callback_url)` → retorna
  `redirect_url` (o código já usa `/connected_accounts/link`, endpoint correto; `initiate()`
  está sendo aposentado pra OAuth gerenciado).
- **Ressalva Meta:** managed auth cobre "a maioria dos apps OAuth2", mas Instagram/Facebook
  (Meta) podem exigir app próprio (`use_custom_auth`) por política. → decisão: **tenta
  managed; se falhar, instrui** (sem campo de credenciais agora).

---

## 2. Decisões de produto (travadas)

### Estrutura geral
- **Fluxo = app próprio no desktop**, full-screen, mesmo visual do `auto-wizard.jsx`
  (`wiz-steps`/`wstep`). Sai 100% de dentro do cliente.
- Hierarquia **Cliente → Produto → Solução** (aninhada). Produto/solução são **fonte de
  conteúdo** pro briefing, **não** seletor de geração. **Seleciona-se só o cliente.**
- Produto/solução guarda: nome + descrição, site/links, @ das redes (referência), imagens/
  logos + cores.

### Tela 0 — Seleção de cliente
Lista de clientes com **busca** + **status das conexões sociais** + **histórico de posts
recentes** + **atalho pra editar dados/produtos** do cliente.

### Tela 1 — Briefing
- Modo **auto OU manual** (escolho a cada vez).
- Auto usa **todas** as fontes: estratégia social do cliente, tendências + concorrentes,
  produtos/soluções, datas comemorativas/calendário.
- Busca de conteúdo **automática, com revisão**: o sistema acha as fontes e eu marco/
  desmarco antes de gerar.
- Campos editáveis: texto do briefing, objetivo + tom de voz, rede(s) alvo, CTA + link.

### Tela 2 — Criação
- Tipos: **imagem fixa, carrossel, vídeo curto (Reels/TikTok), stories, só legenda**.
- Quantidade: **IA sugere, eu ajusto** (qualquer número por tipo).
- Interação **híbrida**: gera rascunhos de uma vez + **chat de ajuste por peça**.
- Por peça: editar copy + hashtags, regenerar/trocar mídia, **variações A/B**, aplicar
  logo/cores da marca (overlay).
- **Imagens:** IA gera (text-to-image).
- **Vídeos:** pipeline interno (auto-editor/cortes/teaser) + IA text-to-video + upload pronto
  com marca + imagens viram vídeo (slideshow).
- **Copy adaptada por rede** (IG ≠ TikTok, respeita estilo/limites).
- Preview: **mockup no formato da rede** + **player de vídeo**.

### Tela 3 — Aprovação
- **Por etapas**: interno → cliente externo.
- Notifica por: **e-mail, WhatsApp, link público de aprovação**.
- Aprovador pode: comentar/pedir ajuste, aprovar/reprovar por peça, editar a copy direto,
  aprovar em lote.
- Aprovado → **fila "aprovados"** (não vai direto pro agendamento).

### Tela 4 — Agendamento/Publicação
- Quando: data/hora manual, melhor horário (IA), publicar agora, plano recorrente.
- Multi-rede: **escalonado por rede** (horários diferentes).
- Visão: **calendário mês/semana + arrastar pra remarcar + filtros cliente/rede + lista**.
- Publicação: **automática via Composio** na data.

### Conexões de redes (Composio)
- Ícones **no cadastro do cliente** (cada cliente tem suas redes).
- Redes nesta fase: **Instagram + Facebook**.
- Connect via **managed auth** (cria/reusa `auth_config` sozinho); se Meta não suportar
  managed, **instrui o que fazer** (sem campo de credenciais agora).
- Painel: status por rede, reconectar 1-clique, aviso antes de expirar, testar conexão.

### Identidade da empresa
- **Multi-logo**: principal + variações livres, versão clara/escura, formatos
  (quadrado/horizontal/story), **e logos por produto**.

### Notificações
- Canais: **e-mail + WhatsApp** (provedor de WhatsApp a definir na implementação).
- Destinatários: contatos do cliente + equipe interna + definir por envio.
- Gatilhos: **enviado pra aprovação** e **conexão expira/falha**.

### Papéis
- Fixos: **admin** (cria/agenda), **aprovador interno**, **cliente externo** (só link).

### Histórico/Biblioteca (acervo)
- Itens: uploads por cliente, peças geradas salvas, pastas/tags + busca, reusar em novo post.
- Origem: gerados pela IA (auto-save), saídas do pipeline de vídeo, upload manual.
  **(Sem Google Drive nesta fase.)**

### Config de IA
- Escopo: **global + override por cliente**.
- Ajustes: modelo por tarefa (texto/imagem/vídeo), templates/prompts editáveis, voz/regras
  da marca por cliente, guard-rails (palavras/claims proibidos).

### Dashboard inicial
- Visão **agência (todos os clientes)**.
- Mostra: pendências de aprovação, agendados + publicados, métricas rápidas, conexões com
  problema.

### Página pública de aprovação
- **Preview fiel + player**, aprovar/reprovar (lote + individual), comentar/pedir ajuste,
  **white-label** (marca).
- Segurança: **token único + expira**.

### Analytics pós-publicação
- Alcance/impressões, engajamento, crescimento de seguidores, insights de melhor
  post/horário (puxado via Composio quando disponível).

### Concorrentes + Tendências
- Alimentam o briefing auto, sugerem temas/datas, geram alertas, e há comparativo
  cliente vs concorrentes.

---

## 3. Arquitetura técnica

### 3.1 Camada Composio (`app/social/composio_provider.py`)
- Novo `ensure_auth_config(platform) -> str`:
  1. Lê id cacheado em Settings (`composio.authConfig.<platform>`).
  2. Senão, **lista** auth configs do toolkit (`GET /api/v3/auth_configs?toolkit=<TOOLKIT>`),
     reusa o primeiro ativo e cacheia.
  3. Senão, **cria** managed (`POST /api/v3/auth_configs` com `use_composio_managed_auth`) e
     salva o id em Settings.
- `connect_account` passa a chamar `ensure_auth_config` em vez de levantar 503.
- Se a criação managed falhar (ex.: Meta), devolve erro **claro e acionável** (o que
  configurar), status 422/502 — não 503 silencioso.
- **Validação na implementação:** confirmar o **base path REST v3** (`/api/v3/...`) — os
  paths atuais (`/connected_accounts/link`) podem estar incompletos → 404. Sondar com a API
  key real antes de finalizar. Confirmar slugs de toolkit (`INSTAGRAM`, `FACEBOOK`).

### 3.2 Fix do `analyze` 500 (`app/routers/social.py`)
- Logar traceback completo; devolver a mensagem real (502 pra falha de provider/IA, 422 pra
  dados faltando) em vez de 500 genérico engolido. O `analyze` deixa de ser porta de entrada
  da geração — vira só "gerar estratégia/insights" usado como fonte do briefing auto.

### 3.3 Modelo de dados (`app/db_companies.py`)
Tabelas existentes a estender via `_ensure_column` (migrations idempotentes já usadas):
- `products`: + `description`, `site_url`, `instagram`, `links` (JSON). Já tem `colors`,
  `company_id`, slug.
- **Nova `solutions`**: `id, product_id, name, description, links, created_at` (Cliente →
  Produto → Solução).
- `company_assets` (já tem `product_id`, `role`): usar `role` pra `logo` (variações),
  `logo_dark`, `logo_format:<fmt>`, `brand_reference`. Suporta multi-logo da empresa e por
  produto.
- **Nova `content_drafts`** (peças do fluxo): `id, company_id, run_id, type (image/carousel/
  video/story/caption), network, copy, hashtags, media_url, variants (JSON), status
  (DRAFT/REVIEW/CHANGES/APPROVED/SCHEDULED/PUBLISHED/FAILED), created_at, updated_at`.
- **Nova `approvals`**: `id, draft_id, stage (internal/client), approver, decision,
  comment, decided_at`.
- **Nova `approval_links`** (página pública): `id, run_id|company_id, token, expires_at,
  scope, created_at`.
- **Nova `notifications_log`**: `id, channel (email/whatsapp), trigger, recipient, payload,
  status, sent_at`.
- **Nova `flow_runs`** (estado do wizard / rascunhos retomáveis): `id, company_id, step,
  briefing (JSON), config (JSON), status, created_at, updated_at`.
- Reusar `posts`, `research_reports` (estratégia/concorrentes) e o agendamento via
  `calendar_scheduler`/`cron_tasks`.
- **Config de IA**: tabela/Settings `ai_config` global + override por cliente
  (`company_id` nullable): modelo por tarefa, templates de prompt, voz/regras, guard-rails.

### 3.4 Frontend (`app/os/`)
- Novo app no `APPS` de `shell.jsx`: `conteudo` (`title: 'Conteúdo'`, ícone próprio, grupo
  'op'), componente full-screen `ConteudoFlowApp`.
- Novo arquivo `app/os/apps-conteudo.jsx` com o wizard (passos 0–4) reaproveitando os
  estilos `wiz-steps`/`wstep`/`tabbar`/`sec`/`btn` (sem mudar identidade visual) e a lógica
  já existente de `AprovacaoApp`, `generatePostAI`, publisher e calendar.
- `apps-clientes.jsx`: a aba "Gerar Conteúdo" vira botão **"Criar conteúdo"** que abre o
  `conteudo` pré-selecionando o cliente. Cliente passa a ser **cadastro de dados**: Dados
  Gerais, Identidade Visual (multi-logo), **Produtos/Soluções**, Concorrentes, **Conexões**.
- Dashboard agência: novo app/tela `painel` (ou seção inicial do `conteudo`).
- Página pública de aprovação: rota servida fora do shell (white-label), consumindo
  `approval_links` por token.

### 3.5 Backend routers/services
- `app/routers/companies.py`: CRUD de produtos + **soluções** + upload multi-logo (empresa
  e por produto).
- `app/routers/social.py`: `ensure_auth_config`; endpoints de status/teste/reconnect de
  conexão; geração de drafts a partir do briefing; aprovação (interna/cliente) + link
  público; agendamento escalonado; analytics.
- `app/services/ai.py`: geração multi-peça (quantidades, variações A/B, copy por rede),
  retrieval das fontes (produtos/soluções/estratégia/tendências) com revisão.
- `app/services/` novos: `content_generator`, `approval_service`, `notifier`
  (email + whatsapp), `social_analytics`.
- Agendamento escalonado via `calendar_scheduler` + `scheduler/cron_tasks`.

---

## 4. Itens de validação técnica (resolver na implementação)
1. Base path REST v3 do Composio (`/api/v3/...`) e formato exato de `auth_configs` e
   `connected_accounts/link`.
2. Slugs de toolkit IG/FB e se o managed auth cobre Meta (senão, fallback instrutivo).
3. Provedor de WhatsApp (API oficial / Z-API / Twilio) — definir.
4. Disponibilidade de métricas (analytics) via toolkits Composio de IG/FB.

---

## 5. Plano de implementação (ordem técnica — plano único)

**Fase 1 — Destravar conexões (base de tudo).**
Composio `ensure_auth_config` + managed auth + fix do 503; fix do `analyze` 500 com erro
real; painel de Conexões no cliente (IG/FB, status/reconnect/testar). Sondagem do REST v3.

**Fase 2 — Identidade & fontes.**
Multi-logo (empresa + produto), CRUD Produtos → Soluções com campos de fonte, config de IA
(global + override), retrieval das fontes com revisão.

**Fase 3 — Fluxo standalone (app `conteudo`).**
Wizard full-screen: Tela 0 (cliente) → 1 (briefing auto/manual) → 2 (criação multi-peça,
híbrida, por rede, preview) → 3 (aprovação por etapas) → 4 (agendamento escalonado).
Mover a geração pra fora do cliente; cliente vira cadastro.

**Fase 4 — Aprovação externa & notificações.**
Página pública white-label com token, e-mail + WhatsApp, gatilhos (enviado p/ aprovação,
conexão expira/falha).

**Fase 5 — Acervo, Dashboard e Analytics.**
Biblioteca (uploads/peças/pastas/tags/reuso), Dashboard agência, Analytics pós-publicação,
comparativo concorrentes/tendências.

---

## 6. Fora de escopo (YAGNI nesta fase)
- Importar acervo do Google Drive.
- Campo de credenciais Meta próprias (só se o managed auth não cobrir Meta).
- Redes além de Instagram/Facebook (TikTok/YouTube/X/LinkedIn vêm depois).
- Templates de mensagem editáveis e Telegram nas notificações.
