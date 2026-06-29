# Changelog

Todas as mudancas relevantes deste projeto devem ser registradas aqui e tambem no `CHANGELOG` interno em `app/ui/app.js` quando forem visiveis no app.

## v1.27.13 - 2026-06-29

- **fix: Duração real do vídeo.** O front envia `target_seconds` para o backend e não usa mais segundos por cena como duração total.
- **fix: Corte pós-provedor.** O compositor corta cada clipe no tempo planejado antes de montar o vídeo final, impedindo que modelos como Omni devolvam 10s/20s quando o app pediu menos.
- **fix: Omni 8s em uma cena.** `cometapi:omni-fast` não divide mais um pedido de 8s em duas cenas de 4s antes do envio ao provedor.
- **fix: Áudio e CTA controlados pelo sistema.** O compositor descarta áudio nativo do provedor e o CTA final passa a ser determinístico da marca/CTA do cliente, sem copy final gerada por IA.
- **teste: Sem custo de IA.** O smoke de vídeo cria um clipe local de 10s e prova que o output final fica em ~2s + CTA.
- Versão: main.py 1.27.13, OS/UI cache bust v=12713.

## v1.27.12 - 2026-06-29

- **fix: Briefing adaptativo de vídeo.** O `video_storyboard_system` padrão passa a herdar a régua editorial do carrossel: dor real, crença errada, mudança de visão, benefício concreto, regras específicas para provedores/SVAs e bloqueio de b-roll genérico.
- **fix: Prompt final de vídeo por cena.** `VIDEO_GEN` agora compila cada cena como shot canônico com sujeito/elemento, contexto, uma ação, um movimento de câmera, luz/clima e proibição dura de texto/logo/UI dentro do clipe.
- **teste: Validação sem custo.** O smoke de prompts/preços agora prova os defaults de vídeo e os overrides por cliente sem chamar OpenRouter/CometAPI para geração paga.
- Versão: main.py 1.27.12, OS/UI cache bust v=12712.

## v1.27.11 - 2026-06-29

- **feat: Prompts modulares por cliente.** A aba Cliente > Criação agora expõe os prompts efetivos de briefing/roteiro de vídeo e de imagem/vídeo por cliente; `build_video_storyboard`, `build_video_prompt` e `build_image_prompt` consomem `brand_kit.creative_config`.
- **fix: Preços de imagem com origem.** Modelos de imagem passam a marcar preço `real`, `catálogo` ou `estimado`; CometAPI usa `pricing.per_request` quando o catálogo expõe e OpenAI-compat aprende `usage.cost` por modelo após geração.
- **fix: Transparência de custo na UI.** Seletores de imagem/vídeo mostram a origem do preço para não confundir estimativa com custo real.
- Versão: main.py 1.27.11, OS/UI cache bust v=12711.

## v1.27.2 - 2026-06-29

- **fix: Progresso de geração de vídeo.** A animação de carregamento agora usa `provider_progress` dentro da cena e um avanço conservador por tempo quando o provedor ainda está em fila, evitando ficar travada em 5% em vídeos de uma cena.
- **fix: ETA do vídeo.** Como o percentual passa de 10% mesmo antes da cena terminar, o modal volta a mostrar estimativa de tempo restante durante jobs longos da OpenRouter/CometAPI.
- **fix: Texto de custo.** Quando o provedor não devolve `usage.cost`, a UI mostra custo estimado pelo catálogo em vez de chamar esse valor de custo real, e usa a mesma conversão BRL do preflight.
- Versão: main.py 1.27.2, OS/UI cache bust v=12702.

## v1.27.1 - 2026-06-29

- **fix: Custo de vídeo CometAPI entregue.** Quando a CometAPI conclui o vídeo mas não devolve `usage.cost`, o job agora registra o custo pelo catálogo/preflight (`per_second` ou `per_request`) em vez de finalizar como `0.0`.
- **fix: Download com provedor congelado.** O download final também usa a configuração congelada do job ao buscar a URL pronta, evitando dependência do modelo global durante jobs longos.
- Versão: main.py 1.27.1, OS/UI cache bust v=12701.

## v1.27.0 - 2026-06-29

- **fix: Jobs de vídeo com provedor congelado.** O background captura a configuração do provedor no início e usa a mesma base/key para criar, pollar e baixar, evitando quebra se o usuário trocar modelo enquanto o job roda.
- **fix: Observabilidade do provedor.** O status do vídeo agora grava `provider`, `provider_job_id`, `provider_status` e `provider_progress`, permitindo depurar jobs lentos da CometAPI sem perder o ID remoto.
- **fix: Timeout realista para CometAPI.** Comet ganha janela maior de polling no backend, e a UI aguarda jobs longos sem declarar timeout antes da plataforma.
- Versão: main.py 1.27.0, OS/UI cache bust v=12700.

## v1.26.99 - 2026-06-29

- **fix: Preços reais no vídeo.** O seletor e o preflight agora consultam catálogos dos provedores quando disponíveis: OpenRouter `/api/v1/videos/models` (`pricing_skus`) e CometAPI `/api/models` (`pricing.per_second`/`per_request`), com cache em settings.
- **fix: Duração cobrada/gerada.** Quando o usuário trava uma duração menor que o máximo do modelo, o backend usa a duração escolhida por cena em vez de sempre usar o máximo do modelo.
- **fix: Catálogo CometAPI.** Adicionado `viduq3-turbo` e corrigidos preços fallback dos modelos Comet compatíveis com `/v1/videos`.
- Versão: main.py 1.26.99, OS/UI cache bust v=12699.

## v1.26.98 - 2026-06-29

- **fix: Vídeo OpenRouter sem cobrança por payload inválido.** `create_video_job` agora manda `duration` inteiro, `resolution`, `aspect_ratio` e `frame_images` no schema oficial (`type=image_url`, `image_url.url`, `frame_type`), eliminando o erro Zod em `frame_images[0].type`.
- **fix: Vídeo CometAPI pelo contrato documentado.** Comet volta para `POST /v1/videos` com `multipart/form-data`, polling em `GET /v1/videos/{id}` e download por `video_url` ou `/content`; modelos Comet com rotas próprias foram removidos do seletor genérico para evitar tentativa cobrada em endpoint errado.
- **fix: Fluxo branded/legado de vídeo.** O frontend envia segundos por cena do preflight, o backend aceita `task_id`, centraliza o download e o endpoint legado passa prompt string para o provider.
- **teste: Validação sem custo.** Adicionado `scripts/test_video_providers_no_api.py`, que intercepta HTTP e prova os payloads de OpenRouter/Comet sem chamar APIs reais.
- Versão: main.py 1.26.98, OS/UI cache bust v=12698.

## v1.26.61 - 2026-06-28

- **fix: Rollback da engine visual recente.** Revertidos os commits do motor de proteção/recorte que deixaram post fixo com caixa de carrossel e reduziram criatividade visual.
- **fix: Post fixo criativo por padrão.** O endpoint de post fixo com IA volta a usar o modo antigo em que a IA desenha a peça inteira; o compositor com caixa/card fica apenas opt-in por `render_mode`.
- Versão: main.py 1.26.61, OS/UI cache bust v=12661.

## v1.23.4 - 2026-06-22

- **fix: Instagram/publicação pela plataforma.** URLs completas HTTPS (ex.: `https://caripost.n8nmikael.com.br/uploads/...`) agora são corretamente resolvidas para o caminho local no disco antes do re-host no tmpfiles.org. Antes o re-host falhava silenciosamente e o post nunca era publicado.
- **fix: Logo com cutout suave.** O novo `_logo_cutout` usa alpha gradiente por distância de cor (não flood-fill). Remove fundos sólidos sem pixelar bordas nem cortar letras. Fundos com photo/textura são preservados intactos.
- Versão: main.py 1.23.4, OS/UI cache bust v=12334.

## v1.23.3 - 2026-06-22

- **fix: Publicação Instagram funcionando end-to-end.** Imagem é re-hosteada em tmpfiles.org (upload anônimo, sem auth), `ig_user_id` incluído no passo de publish, formato `arguments` corrigido para API v3.1 do Composio. Testado e confirmado: post publicado com sucesso no Instagram.
- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill) que destruía o logo na sobreposição da imagem gerada por IA.
- **fix: Erros de publicação logados.** `asyncio.create_task` agora tem `add_done_callback` que captura exceções e grava log no banco.
- Versão: main.py 1.23.3, OS/UI cache bust v=12333.

## v1.23.2 - 2026-06-22

- **fix: Composio/Instagram payload format.** API v3.1 exige que os parâmetros da tool vão dentro de `arguments`, não como campos top-level. Corrigido em todos os pontos de chamada.
- **fix: ig_user_id automático.** O ID do Instagram Business/Creator é obtido via `INSTAGRAM_GET_USER_INFO` e cacheado no metadata da conexão — não precisa mais configurar manualmente.
- **fix: Re-host de imagem em URL pública.** Imagens geradas são re-hosteadas no Imgur antes de enviar ao Instagram, porque os crawlers do Meta não conseguem buscar de URLs internas/privadas. Requer `IMGUR_CLIENT_ID` env ou setting `imgur.clientId`.
- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill) que destruía o logo na sobreposição da imagem gerada por IA.
- **fix: Erros de publicação logados.** `asyncio.create_task` agora tem `add_done_callback` que captura exceções e grava log no banco.
- Versão: main.py 1.23.2, OS/UI cache bust v=12332.

## v1.23.1 - 2026-06-22

- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill com thresh=70) que destruía o logo na hora de sobrepor na imagem gerada por IA. O logo agora é aplicado como-is, preservando o alpha original do PNG. PNGs com transparência continuam funcionando; logos opacos mantêm o fundo intacto em vez de ficar pixelados/quebrados.
- **fix: Publicação Instagram via Composio reescrita.** O `publish_post` não envia mais texto livre para um tool genérico. Agora faz 2 chamadas estruturadas com parâmetros nomeados: `INSTAGRAM_POST_IG_USER_MEDIA` (cria container com `image_url`/`video_url` + `caption`) → `INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH` (publica com `creation_id` + `max_wait_seconds`). Slugs podem ser sobrescritos via env `COMPOSIO_TOOL_INSTAGRAM_CREATE_MEDIA` / `COMPOSIO_TOOL_INSTAGRAM_PUBLISH_MEDIA`.
- **fix: Erros de publicação não são mais silenciados.** `asyncio.create_task(publish_social_post(...))` agora tem `add_done_callback` que captura exceções e grava log no banco (`social_post_logs`) e no logger `caripost.social`.
- Versão: main.py 1.23.1, OS/UI cache bust v=12331.

## v1.22.3 - 2026-06-20

- Settings ganhou suporte para salvar `Composio API` e Auth Configs de Instagram/Facebook/TikTok/YouTube.
- Provider Composio agora lê token salvo no banco (`token:composio` ou `social.apiKey.composio`) antes de depender de `COMPOSIO_API_KEY`.
- `/api/social/config` agora reflete configuração Composio salva no app.
- Versão: main.py 1.22.3, OS/UI cache bust v=12230.

## v1.22.2 - 2026-06-20

- Clientes ganhou aba `Fluxo` como caminho principal: Instagram da empresa, conexão Composio, concorrentes, análise, ideias, aprovação, criação de mídia e publicação.
- Backend social ganhou workspace por empresa, análise estratégica via Composio/IA e geração de rascunhos a partir das ideias.
- Análise social agora pode atualizar identidade de marca com posicionamento, voz, persona, visual prompt base e cores sugeridas.
- Ideias da estratégia viram posts em `REVIEW`, preservando aprovação antes de publicar.
- Versão: main.py 1.22.2, OS/UI cache bust v=12220.

## v1.22.1 - 2026-06-20

- Social Integration Layer via Composio/provider isolado para conectar contas, criar posts, publicar/agendar, consultar status e métricas.
- Rotas novas em `/api/social` para contas, posts, worker, concorrentes e referências.
- Banco: tabelas novas `social_connections`, `social_posts`, `social_post_channels`, `social_post_assets` e `social_post_logs`.
- Worker APScheduler separado para posts sociais agendados, com logs por canal e bloqueio de conteúdo não aprovado.
- Publicar OS ganhou canais conectados, publicação social, concorrentes e referências sem mexer em upload, storage ou processamento de vídeo.
- Docs e smoke test mock em `docs/composio-social-integration.md` e `scripts/social_smoke.py`.
- Versão: main.py 1.22.1, OS/UI cache bust v=12210.

## v1.22.0 - 2026-06-20

- Módulo de Clientes: CRUD de empresas, brand kit (logo, cores, voz, persona), mood board e concorrentes.
- Central de Aprovação: workflow DRAFT -> REVIEW -> APPROVED -> SCHEDULED com transições validadas.
- Inteligência de Concorrentes: benchmark cross-empresa com visão consolidada.
- IA de texto (Anthropic/OpenAI/OpenRouter) integrada: geração de copy de posts e briefings de tendências.
- Tendências atualizadas: briefing por empresa via IA, sem dependência de scraping de plataformas adultas.
- Configurações de IA na página de Settings: provedor, modelo, API key e teste de conexão.
- Limpeza de referências de plataformas adultas na view de Tendências.
- Backend: 6 tabelas novas (companies, brand_kits, competitors, posts, research_reports, company_assets).
- Backend: 3 routers novos (companies, posts, ai_settings) + módulo services/ai.py.
- Versão: main.py 1.22.0, index.html v1.22.0, app.js cache bust v=12200.

## v1.21.3 - 2026-06-16

- Cortes passa a indicar corretamente quando usou Vision IA/cache e quando caiu no fallback de detecção automática por falta de token/resposta de IA.

## v1.21.2 - 2026-06-16

- Cortes IA passa a enviar timestamps junto dos frames para a Vision selecionar tempos reais do vídeo.
- Cache de análise Vision agora é persistente em `cache/vision/{hash}.json`, calculado pelo hash do primeiro 1MB + tamanho do vídeo.
- Extração paralela mantém semáforo máximo 3 e atualiza o progresso conforme cada corte termina.

## v1.21.1 - 2026-06-15

- Ajuste de release para o pipeline de cortes IA com seleção por Vision, cache de análise e extração paralela.

## v1.21.0 - 2026-06-15

- Cortes com IA: Vision analisa frames e seleciona os melhores momentos automaticamente — sem sliders de minutagem.
- Extração paralela de clips com semáforo (máx 3 simultâneos) — speedup de 3x.
- Cache de análise por vídeo — mesma mídia não reanalisada pela IA.
- UI redesenhadada do Cortes: limpa, sem inputs de quantidade/duração, foco em 1 clique.
- Fallback automático para detecção clássica de cenas quando IA está indisponível.

## v1.20.27 - 2026-06-15

- Analyze passa a enviar `stt_provider: none`, pulando transcrição automática.
- Backend respeita o modo sem transcrição e continua com referências do criador, Vision IA, geração de JSON/metadados e prompt.
- OS remove a escolha de STT e a aba SRT do Analyze enquanto a etapa de legenda/transcrição estiver cortada.

## v1.20.24 - 2026-06-15

- Adiciona timeout por request no upload via XHR para partes que ficam penduradas sem disparar erro do navegador.
- Timeouts passam a entrar no retry existente, preservando o arquivo selecionado e o fluxo de upload em partes.

## v1.20.23 - 2026-06-15

- Adiciona modal de tela inteira durante uploads, com circulo de progresso, percentual, tempo restante e descricao da etapa atual.
- Mantem o fluxo existente de upload local/por partes e apenas adiciona feedback visual global.

## v1.20.22 - 2026-06-15

- Adiciona retry ao upload pequeno via `/uploads/local-stream`, reaproveitando o mesmo arquivo selecionado quando a rede oscila.
- Mantem o caminho em partes para arquivos acima de 128 MB.

## v1.20.21 - 2026-06-15

- Corrige o registro auxiliar do complete idempotente para nao transformar upload finalizado em erro 500.
- O armazenamento do resultado do complete passa a ser best effort: se falhar, o arquivo salvo ainda retorna sucesso ao navegador.

## v1.20.20 - 2026-06-15

- Troca a chamada de finalizacao de `/uploads/chunk/complete` para XHR, usando o mesmo canal que envia as partes do arquivo.
- Mantem retries e idempotencia no complete para evitar falhas no fim de uploads grandes quando o navegador derruba `fetch` depois de transferir muitos chunks.

## v1.20.19 - 2026-06-15

- Serializa a finalizacao de uploads em partes por `upload_id`, evitando corrida entre tentativas repetidas de `/uploads/chunk/complete`.
- Faz o abort aguardar a finalizacao em andamento e preservar uploads ja completados, impedindo perda do arquivo quando a rede oscila no fim do envio.

## v1.20.18 - 2026-06-15

- Reforca o upload em partes para redes instaveis: inicializacao, envio de partes e finalizacao agora fazem retry em falhas transitorias.
- Torna `/uploads/chunk/complete` idempotente: se o arquivo for salvo mas a resposta se perder, uma nova tentativa retorna o mesmo `object_key` em vez de abortar o upload.

## v1.20.17 - 2026-06-15

- Corrige uploads grandes no Caripost: arquivos acima de 128 MB passam a ser enviados em partes para `/uploads/chunk/*`, montados no storage local e validados antes de serem aceitos.
- Mantem `/uploads/local-stream` para arquivos menores e evita voltar ao fluxo antigo de PUT direto/presigned no S3.

## v1.20.16 - 2026-06-15

- Alinha as versoes publicas do Caripost OS e do painel ao backend em producao, removendo indicadores antigos e forçando novo cache bust dos assets do OS.

## v1.19.13 - 2026-06-15

- Corrige o MetaPorn OS para que o tour automatico nao intercepte cliques nas areas de upload: o tutorial continua visivel, mas o usuario consegue selecionar videos no Analyzer e nos demais fluxos com upload.
- Adiciona cache bust ao `os.css`, garantindo que a correcao do tour chegue ao navegador junto com os scripts `v=121100`.

## v1.19.12 - 2026-06-14

- Alinha os routers modulares ao login do MetaPorn OS: `app/main_utils.py` agora aceita `X-Session-Token` valido antes de exigir API key, liberando leituras autenticadas em AutoEditor, Enhancer, Publicar, Criadores, DMCA, Agenda, Tendencias e Financeiro apos login normal.

## v1.19.11 - 2026-06-14

- Corrige o upload do MetaPorn OS quando o usuario seleciona um video sem sessao valida: o overlay de login agora e aguardado e o mesmo arquivo continua o envio apos autenticar, com uma nova tentativa quando a sessao expira durante o upload.

## v1.19.10 - 2026-06-13

- Ajusta a checagem inicial de autenticacao do MetaPorn OS para preservar a abertura visual anterior: respostas `missing_or_invalid_api_key` no boot apenas marcam auth pendente, e o login aparece quando uma acao protegida exige credencial.

## v1.19.9 - 2026-06-13

- Corrige a checagem de autenticacao do MetaPorn OS: respostas JSON `missing_or_invalid_api_key` passam a ser tratadas como bloqueio de auth mesmo quando o backend retorna HTTP 200, abrindo o login antes do upload.

## v1.19.8 - 2026-06-13

- Corrige a autenticacao do upload no MetaPorn OS: o XHR para `/uploads/local-stream` passa a reutilizar a `X-API-Key` salva na sessao da UI antiga, evitando `missing_or_invalid_api_key` quando o servidor exige API key.

## v1.19.7 - 2026-06-13

- Corrige o upload do MetaPorn OS apos a migracao para CariPost: a tela nova deixa de usar PUT direto no storage por presign e passa pelo endpoint backend `/uploads/local-stream`, com a mesma validacao de video da UI funcional.

## v1.19.6 - 2026-06-10

- Corrige o carregamento das capas no gerenciador Arquivos: as primeiras thumbnails da grade agora entram na fila imediatamente, sem depender de rolagem dentro da janela do MetaPorn OS.

## v1.19.5 - 2026-06-10

- Faz o login do MetaPorn OS respeitar `/auth/check`: quando a autenticacao esta ativa, o login aparece no desktop novo e a sessao e espelhada para os modulos antigos embutidos.

## v1.19.4 - 2026-06-10

- Restaura o funcionamento real dos módulos no MetaPorn OS: cada janela do desktop novo abre a rota funcional antiga em `/ui/?embed=1`, reaproveitando handlers, uploads, runs, Criacao, burn, teaser, settings e demais fluxos existentes.
- Mantem o visual do desktop MetaPorn OS e aumenta/centraliza os icones no topo da tela.
- Espelha a sessao do login do OS para a UI antiga, evitando login duplicado dentro das janelas.

## v1.18.21 - 2026-06-02

- Corrige a tela inicial para seguir o desktop do pacote Claude Designer: boot/login MetaPorn OS, grupos de apps completos e janela oculta quando nao ha rota direta.
- Mantem rotas, endpoints, loaders e funcoes tecnicas existentes; atalhos visuais de edicao apontam para a rota real de Criacao.

## v1.18.20 - 2026-06-02

- Corrige a entrega visual do Claude Designer com login em MetaPorn OS, desktop com apps agrupados, start menu, taskbar e janela principal.
- Preserva rotas, IDs, handlers, loaders, endpoints e fluxos tecnicos existentes.

## v1.18.19 - 2026-06-02

- Aplica a reestruturacao visual MetaPorn OS recebida no pacote `Metaporn.zip`.
- Transforma o shell atual em uma experiencia visual de desktop: launcher em blocos, janela principal em vidro escuro e barra inferior de atalhos.
- Preserva rotas, IDs, handlers e fluxos tecnicos existentes.

## v1.18.18 - 2026-05-25

- Corrige o burn de logo para manter a proporcao visual do preview e evitar logo achatada no video final.
- Adiciona exclusao de run/criacao com limpeza de registros relacionados, jobs e arquivos seguros.
- Atualiza o cache bust do painel admin para forcar carregamento da UI mais recente.

## v1.18.13 - 2026-05-22

- Versao anterior diagnosticada com ausencia de exclusao de run/criacao e problema de proporcao na logo durante burn.
