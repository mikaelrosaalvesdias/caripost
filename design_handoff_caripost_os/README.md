# Handoff: Caripost OS — Frontend Desktop (pronto e funcionando)

## ⚡ TL;DR (leia isto primeiro)

Este pacote contém o **frontend completo do Caripost OS, já funcionando**. Não é pra recriar do zero.
A integração anterior quebrou porque foi **reescrita**. Aqui a ordem é: **servir como está + ligar ao backend.**

1. Abra `Caripost-OS-REFERENCIA-standalone.html` no navegador. **Tudo funciona** (menu, janelas, notificações, ações de vídeo). Esse é o alvo: tem que continuar assim.
2. Dê o arquivo **`CLAUDE.md`** para o Claude Code. Ele tem as regras e o mapa de integração. **A regra nº 1 é: não reescreva os botões.**
3. Os arquivos-fonte editáveis estão em **`app/`**.

---

## Visão geral

Caripost OS é um **sistema operacional de desktop no navegador** para a operação da agência:
ingestão de mídia, AutoEditor (cortes com Grok Vision), legenda, logo, teaser, thumbnail,
publicação, Telegram, gestão de criadores, financeiro e DMCA — cada função abre como um
"app" em janela própria, com barra de tarefas, menu Iniciar, notificações e um Modo Automático
em tela cheia.

## Sobre os arquivos deste pacote

Os arquivos em `app/` são uma **implementação de referência em HTML/CSS/React** — um protótipo
de alta fidelidade que demonstra o visual **e o comportamento finais**. Diferente de um mock
estático, **ele é interativo e funcional**: o gerenciador de janelas, o menu de ações do vídeo,
o tour, as notificações e o Modo Automático já estão implementados em React.

Você tem dois caminhos válidos:

- **Caminho A — servir como está (mais rápido, menor risco).** O app é 100% client-side
  (React 18 via CDN + Babel). Sirva a pasta `app/` no seu servidor e ele roda. Seu trabalho
  passa a ser só **ligar os dados/ações ao backend** (ver `CLAUDE.md`).
- **Caminho B — portar para o seu stack.** Se você precisa do Caripost OS dentro de um app
  React/Vue/etc já existente, **recrie tela a tela usando os arquivos como referência exata**,
  mantendo classes/estrutura. Mais trabalho, mais risco de quebrar — só faça se necessário.

> Independente do caminho: o comportamento descrito ("botões funcionando", "clicar no vídeo
> abre as ações") **já está pronto nos arquivos**. Não recrie a lógica de eventos do zero.

## Fidelidade

**Alta fidelidade (hi-fi) + interativa.** Cores, tipografia, espaçamento e interações são finais.
Recrie/integre pixel-a-pixel. Não improvise estilo novo.

## Telas / Apps (22)

Cada um é um componente React em `app/apps-*.jsx`. Todos abrem em janela própria.

**Inteligência e Mídia** — `apps-core.jsx`, `apps-studio.jsx`
- **Analyze** — upload, transcrição (6 motores STT), filtros de referência, abas Prompt/SRT/Visão IA/JSON.
- **Compare** — mesmo prompt em vários LLMs, com custo/tempo/tokens lado a lado.
- **Runs** — histórico técnico de execuções (frames, metadados, prompt).
- **Arquivos** — file manager. **Clicar num vídeo abre a tela de ações** (ver abaixo). Botão direito = menu rápido.
- **Referência** — pesquisa/benchmark XVideos.
- **AutoEditor** — núcleo: multi-fonte → Grok Vision → cenas → transições → render. Vídeo grande + opções reais.
- **Video Enhancer** — upscale (RealESRGAN).

**Edição & Conteúdo** — `apps-edit.jsx`
- **Legenda** — transcrição, editor SRT, estilo, queima (FFmpeg).
- **Logo** — studio de marca d'água arrastável (posição/tamanho/opacidade).
- **Teaser** — corte curto vertical dos melhores momentos.
- **Thumbnail** — capa por IA a partir dos frames + título.

**Operação e Distribuição** — `apps-dist.jsx`, `apps-studio.jsx`
- **Criação** — monta o post (capa, título, descrição, tags, logo).
- **Telegram** — fila de disparos, grupos/canais.
- **Publicar** — distribuição nas plataformas.
- **Calendário** — agendamento editorial.

**Gestão de Agência** — `apps-manage.jsx`
- **Criadores** — perfis, contas, receita por criador.
- **Tendências** — radar + briefing por criador (Grok).
- **Financeiro** — receita/payout por plataforma e criador.
- **DMCA** — varredura de pirataria + takedowns.
- **Settings** — tokens de IA, integrações, usuários, preferências.

**Fluxo / Shell** — `auto-wizard.jsx`, `shell.jsx`
- **Modo Automático** — pipeline em tela cheia (Upload→Vision→Detecção→Seleção Grok→Corte→Legenda→Logo→Render→Publicar) com %, ETA, log e prévia ao vivo.
- **Assistente** — fluxo passo a passo.
- **Shell** — boot, desktop, janelas arrastáveis (mover/min/max/fechar), barra de tarefas, menu Iniciar, Central de Tarefas, Notificações, Tour guiado.

## Interação-chave: Arquivos → ações do vídeo

1. Abrir **Arquivos** → grade de vídeos com filtros (Todos/Originais/Queimados/Teasers/AutoEditor).
2. **Clique** num vídeo → tela de detalhe: prévia grande + metadados + painel **"O que deseja fazer com este vídeo?"** com 9 ações (AutoEditor, Legenda, Logo, Teaser, Thumbnail, Melhorar, Criar Post, Publicar, Telegram).
3. Cada ação chama `window.__mpOpen('<appId>')` e **abre o app correspondente**.
4. **Botão direito** num vídeo → menu de contexto com as mesmas ações + Baixar/Renomear/Copiar key/Excluir.

## Como um app abre outro

`shell.jsx` expõe `window.__mpOpen(appId)`. IDs = chaves do objeto `APPS` em `shell.jsx`
(`autoeditor`, `analyze`, `legenda`, `logo`, `teaser`, `thumbnail`, `enhancer`, `criacao`,
`media`, `compare`, `runs`, `referencia`, `telegram`, `publisher`, `calendar`, `creators`,
`trends`, `financial`, `dmca`, `settings`, `wizard`, e `auto` para o Modo Automático).

## Design tokens (em `app/os.css`, no `:root`)

- **Cores:** vermelho `--pri #ff1744` / `--pri2 #cc1038`; violeta `--violet #7c3aed`; ciano `--cyan #20d5ff`; ok `--good #00e676`; alerta `--warn #ffab00`.
- **Fundos:** `--bg #0a0a14`, `--bg2 #111120`, `--solid #13132a`, vidro `--glass rgba(19,19,42,.82)`.
- **Texto:** `--text #edecff`, `--text2 #c4c4dc`, `--muted #7c7c98`.
- **Raios:** `--r-sm 9px` · `--r 13px` · `--r-lg 18px` · `--r-xl 24px`.
- **Tipografia:** títulos `Space Grotesk`; texto `Inter`; mono `JetBrains Mono`.
- **Sombras/curvas:** `--sh`, `--sh-lg`, `--sh-win`; `--ease`, `--spring`.

## Estado / dados

Cada app guarda estado local com `useState` (abas, seleção, sliders). Os dados de exibição
são **constantes de exemplo no topo de cada arquivo** (ex.: `MEDIA_ITEMS` em `apps-core.jsx`).
Para integrar: substitua o conteúdo dessas constantes pelo retorno da API, **mantendo os nomes
dos campos**. Progresso/log/pipeline já existem visualmente — alimente com o status real (polling/websocket).

## Assets

Sem imagens externas. Ícones são SVG inline (`app/icons.jsx`). As prévias de vídeo são
placeholders estilizados (`Media` / `VStage`) — troque pelo `<video>`/thumbnail real do storage.
Fontes vêm do Google Fonts (já no `<head>` do `index.html`).

## Arquivos deste pacote

```
design_handoff_caripost_os/
├── README.md                              ← este arquivo
├── CLAUDE.md                              ← REGRAS p/ o Claude Code (dê este a ele)
├── Caripost-OS-REFERENCIA-standalone.html ← abra no navegador: prova que tudo funciona (offline)
└── app/                                   ← FONTE editável (sirva esta pasta)
    ├── index.html      ← carrega tudo na ordem certa
    ├── os.css          ← todo o visual + tokens
    ├── icons.jsx       ← ícones + componentes base (Icon, VStage, ProgressBar, …)
    ├── apps-core.jsx   ← Analyze, Compare, Runs, Arquivos
    ├── apps-edit.jsx   ← Legenda, Logo, Teaser, Thumbnail
    ├── apps-studio.jsx ← AutoEditor, Enhancer, Criação, Referência
    ├── apps-dist.jsx   ← Telegram, Publicar, Calendário
    ├── apps-manage.jsx ← Criadores, Tendências, Financeiro, DMCA, Settings
    ├── auto-wizard.jsx ← Modo Automático + Assistente
    └── shell.jsx       ← boot, janelas, barra, menu, notificações, tour (orquestrador)
```

## Produção (única mudança técnica permitida)

`index.html` usa Babel no navegador (rápido pra rodar, lento pra produção). **Opcional:**
pré-compile os `.jsx` com Vite/esbuild e troque as tags `text/babel` por JS compilado —
**sem alterar o conteúdo dos componentes.** Em dúvida, sirva como está: funciona igual.
