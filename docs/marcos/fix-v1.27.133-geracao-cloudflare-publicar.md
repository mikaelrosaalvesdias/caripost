# Fix v1.27.133 — geração de imagens e publicação

## Sintoma
"Nada funciona": briefing ok, mas gerar imagens ficava em "Renderizando…" para sempre/erro; publicar no Instagram dizia "Publicado" e nada aparecia.

## Causas (comprovadas)
1. **Cloudflare 100s**: `POST /api/posts/render-carousel` era síncrono. Estúdio IA (gpt-5.4-image-2 via kie) leva 5–12 min. O Cloudflare devolve 524 em 100s; o servidor terminava (post DRAFT criado) mas o navegador nunca recebia. Prova: em 3 semanas de log não há nenhuma resposta de `render-carousel` registrada (uvicorn não loga quando o cliente já caiu), e a geração de teste gravou as 7 telas + post às 00:53:48 sem a tela receber.
2. **Rota sombreada**: `GET /{post_id}` registrada antes de `/image-templates` e `/video-status` → 404 "Post não encontrado".
3. **Publicar**: `POST /api/social/posts` publica em segundo plano e responde 200 na hora; o front marcava `PUBLISHED` sem esperar. O Instagram recusou: conta Composio `ca_5Ntwgnb-Ao99` **EXPIRED** (token expirou 02/10/2026).

## Mudanças
- `app/routers/posts.py`: `render_carousel` vira wrapper; com `async_job` cria task (`_RENDER_JOBS`) e devolve `job_id`; `GET /render-job/{job_id}` (com escopo de empresa). Lógica antiga intacta em `_render_carousel_sync`. `get_post` movido pro fim do arquivo.
- `app/os/api.js`: `renderCarousel` faz POST com `async_job` + polling a cada 5s (até 30 min). Todos os chamadores (gerar, regerar arte, regerar tela) herdam.
- `app/os/apps-conteudo.jsx` `doPublish`: espera status real do post social (até ~4 min); falha → erro visível (mensagem específica se a conexão expirou); só marca PUBLISHED se publicou.
- `app/os/apps-dist.jsx`: polling de status mostra o erro do canal.

## Verificação
- regressao_check OK antes/depois; JSX validado; deploy 1.27.133.
- E2E no navegador em produção: briefing → Gerar carrossel (Estúdio IA) → **716s** → "Concluído · 7 telas · R$ 1.49" recebido na tela.
- `image-templates` agora 200.
