# CLAUDE.md — LEIA ANTES DE TOCAR EM QUALQUER COISA

Você (Claude Code) vai integrar o **MetaPorn OS** — um frontend de desktop que **JÁ ESTÁ 100% PRONTO E FUNCIONANDO**.

## ⛔ A REGRA DE OURO (o motivo de ter quebrado antes)

**NÃO REESCREVA O FRONTEND. NÃO REFAÇA OS BOTÕES. NÃO "MELHORE" NADA.**

A tentativa anterior quebrou porque alguém recriou os componentes/eventos do zero.
Os botões, o menu Iniciar, as notificações, o gerenciador de janelas, o menu de ações
do vídeo — **tudo já funciona** nos arquivos desta pasta. Seu trabalho é **só conectar
ao backend real**, trocando dados de exemplo por chamadas de API. Nada além disso.

Se você se pegar reescrevendo um `onClick`, um `useState`, ou um componente inteiro: **PARE.**
Você está prestes a quebrar de novo.

## ✅ O QUE FAZER (e só isso)

1. **Sirva os arquivos da pasta `app/` como estão.** Abra `app/index.html` — ele já roda.
2. **Troque os dados de exemplo por dados reais.** Cada app (em `apps-*.jsx`) tem arrays/constantes
   de exemplo no topo (ex: `MEDIA_ITEMS`, `MODELS`, listas de criadores). Substitua o conteúdo
   desses arrays pelo retorno da sua API. **Mantenha os mesmos nomes de campo** que os componentes já leem.
3. **Ligue as ações aos endpoints.** Os botões já chamam funções; dentro delas, adicione o `fetch()`
   para o seu backend. A estrutura de cliques NÃO muda.

## Arquitetura (para você se localizar — não para mudar)

- `index.html` — carrega React 18 (UMD) + Babel, depois os `.jsx` na ordem. **Não mude a ordem.**
- `os.css` — todo o visual (tema, janelas, barra de tarefas, aurora). Tokens no `:root`.
- `icons.jsx` — set de ícones + componentes base (`Icon`, `Pill`, `ProgressBar`, `LogLines`, `VStage`, `Media`, `Field`, `Check`, `Switch`, `Thumb`). Exportados em `window`.
- `apps-core.jsx` — Analyze, Compare, Runs, **Arquivos** (file manager c/ menu de ações + clique direito).
- `apps-edit.jsx` — Legenda, Logo, Teaser, Thumbnail.
- `apps-studio.jsx` — AutoEditor, Video Enhancer, Criação, Referência.
- `apps-dist.jsx` — Telegram, Publicar, Calendário.
- `apps-manage.jsx` — Criadores, Tendências, Financeiro, DMCA, Settings.
- `auto-wizard.jsx` — Modo Automático (pipeline em tela cheia) + Assistente.
- `shell.jsx` — boot, desktop, janelas arrastáveis, barra de tarefas, menu Iniciar, Central de Tarefas, Notificações, Tour. **É o orquestrador. Mexer aqui é o caminho mais rápido pra quebrar tudo.**

### Como um app abre outro (já implementado)
`shell.jsx` expõe `window.__mpOpen(appId)`. O menu de ações do vídeo (em `apps-core.jsx`)
já usa isso. Para abrir um app a partir de qualquer lugar: `window.__mpOpen('legenda')`.
IDs válidos: as chaves do objeto `APPS` em `shell.jsx`.

## Onde plugar o backend (mapa rápido)

| App | Constante de dados de exemplo | Endpoint que você liga |
|-----|-------------------------------|------------------------|
| Arquivos | `MEDIA_ITEMS` (apps-core.jsx) | `GET /media` |
| Analyze | textos/abas no `AnalyzeApp` | `POST /analyze`, `GET /runs/:id` |
| Compare | `models` no `CompareApp` | `POST /compare` |
| Runs | `runs` no `RunsApp` | `GET /runs` |
| AutoEditor | `scenes` no `AutoEditorApp` | `POST /autoeditor`, `GET /jobs/:id` |
| Criadores | `creators` no `CreatorsApp` | `GET /creators` |
| Financeiro | stats no `FinancialApp` | `GET /financial` |
| DMCA | `infr` no `DmcaApp` | `GET /dmca`, `POST /dmca/scan` |
| ... | (mesmo padrão nos demais) | (mesmo padrão) |

Barras de progresso (`ProgressBar`), logs (`LogLines`) e o pipeline do Modo Automático
já existem visualmente — alimente-os com o status real dos seus jobs (polling ou websocket).

## Para PRODUÇÃO (única mudança técnica permitida)

O `index.html` usa Babel no navegador (`<script type="text/babel">`), ótimo para rodar
na hora, mas lento para produção. **Opcional**: pré-compile os `.jsx` (Vite/esbuild) e troque
as tags `text/babel` por JS já compilado. **Sem mudar o conteúdo dos componentes.** Se tiver
qualquer dúvida, NÃO faça isso — sirva como está, funciona igual.

## Checklist final (faça nesta ordem)
1. [ ] `app/index.html` abre e funciona ANTES de você tocar em qualquer coisa? (deve abrir)
2. [ ] Troquei só os DADOS de exemplo por dados reais, mantendo os nomes dos campos?
3. [ ] Liguei os cliques aos endpoints SEM reescrever a estrutura dos componentes?
4. [ ] Testei: menu Iniciar abre? Notificações abrem? Clicar num vídeo nos Arquivos abre as ações? Modo Automático abre em tela cheia?
5. [ ] Se algo quebrou, eu reescrevi algo que não devia. Reverta e volte ao passo 1.
