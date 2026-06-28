# Correções (sem redesenhar UI) — Logo, Conexão, Geração de imagem

**Data:** 2026-06-21 · Escopo: consertar o que já existe dentro do Cliente. NÃO redesenhar.

## 0. Servidor
`ERR_CONNECTION_REFUSED` em /products e /brand-kit era **transitório** (rollover dos meus
redeploys 1.23.1→1.23.3). Serviço `metaporn-new_adult-meta` está `Up healthy`. Produtos/brand-kit
voltam a responder. Confirmar no browser após estabilizar.

## 1. Logo (aba Identidade Visual → componente `CompanyLogos` em `app/os/apps-clientes.jsx`)
Problema: tem seletor "Fundo claro/escuro", checkbox "principal" e preview com fundo escuro —
o usuário quer **só subir a logo e pronto**, sem descrição/variante.
- Remover o `<select>` de variante e o checkbox "principal". Upload direto ao escolher arquivo
  (já é assim — só tirar os controles). Manter listagem + botão excluir.
- Tirar o fundo escuro do preview (`background: ... '#111'`). Usar fundo neutro/transparente.
- Backend já salva via `POST /api/companies/{id}/logos` (variant default "light", primeira vira
  primária). Manter; só simplificar a UI.
- **IA usar a logo na geração de imagem:** ao montar o prompt de imagem (item 3), incluir a(s)
  logo(s) da empresa (`asset_list_logos`) como referência/overlay. Marcar no meta que é logo de marca.

## 2. Conexão mostra "não conectado" + "Testar" não funciona
Causa (em `app/social/service.py`):
- `connect_account` grava a conexão com `composio_connection_id = result.connected_account_id`,
  que no fluxo de link **vem vazio** (o id só chega no callback) → linha fica `status='pending'`.
- `handle_connection_callback` (callback GET `?status=success&connected_account_id=ca_…`) tenta
  achar a linha por `social_connection_get_by_composio(ca_…)` — não acha (a pendente tinha id
  vazio) → não religa à marca. Brand continua `pending` → UI mostra "não conectado".

Fix:
- No `connect_account`: guardar `alias = "{brand_id}-{platform}"` e o `link_token` no metadata
  (já guarda). 
- No `handle_connection_callback`: quando não achar por composio id, **religar pela conexão
  pendente mais recente** da marca/plataforma (buscar `social_connection_list` com status pending
  e casar por alias/brand+platform), setar `composio_connection_id` e `status='connected'`.
- Adicionar endpoint **refresh real**: `POST /api/social/accounts/refresh?brandId=` que chama o
  Composio (`GET /connected_accounts?user_id=&toolkit=`) e atualiza status local. Ligar o botão
  **Testar** (em `CompanyConexoes`) nesse refresh em vez de só `load()`.
- Arquivos: `app/social/service.py`, `app/routers/social.py`, `app/os/api.js` (novo
  `socialRefresh`), `app/os/apps-clientes.jsx` (`CompanyConexoes.load`/Testar).

## 3. Post não gera IMAGEM (nem vídeo) — só texto
Causa: `app/routers/posts.py /generate-ai` → `generate_post_copy` (texto). Sem geração de imagem.

Fix (barato, reusando config `image.*` que já existe):
- **Nova `generate_post_image(company, prompt, size="1024x1024")` em `app/services/ai.py`:**
  usar `get_image_config()` (provider openai → `gpt-image-1`), chamar a API de imagens, salvar o
  arquivo em `UPLOAD_DIR/{company_id}/generated/` e retornar a URL pública (`/uploads/...`).
  Incluir no prompt: tema do briefing/ideia + cores da marca + instrução de deixar espaço pra
  logo. (Opcional v2: compor a logo por cima reusando `_prepare_logo_overlay_image` do main.py.)
- **Endpoint** `POST /api/posts/generate-image` `{company_id, prompt}` → `{url}`.
- **Wire no fluxo** (`app/os/apps-conteudo.jsx` `StepCriacao`): para tipo imagem/carrossel, após
  a copy, chamar generate-image e setar `media_url` no draft; mostrar no preview (já tem `<img>`).
  Para vídeo: usar pipeline interno existente (fase 2). Respeitar a quantidade.
- Modelo de imagem fica no **bom** (gpt-image-1) — é onde o usuário quer investir. Texto segue
  no barato (gpt-4.1-mini, já feito).
- Arquivos: `app/services/ai.py`, `app/routers/posts.py`, `app/os/api.js` (`generatePostImage`),
  `app/os/apps-conteudo.jsx`.

## Ordem
1) Logo (rápido, UI) → 2) Conexão (linkagem + refresh) → 3) Imagem no post (maior).
Cada um: editar → `docker build -t metaporn-new:<v> .` → `docker service update --image metaporn-new:<v> metaporn-new_adult-meta` → testar.
