# Patch de padrão visual do Caripost OS — v1.27.123

Aplicação do `caripost-patch` (Claude Designer) em `app/os/`. **Nada foi redesenhado**: o
design aprovado continua igual; o patch faz as telas que fugiam dele obedecerem ao padrão.

## O que mudou tecnicamente

### Base (passos 1–3 do LEIA-ME)

| Arquivo | Mudança | Por quê |
| --- | --- | --- |
| `app/os/os.css` | `os-patch.css` anexado ao final (+361 linhas) | `.hint` e `.row` eram usadas em centenas de pontos e **não existiam** — texto auxiliar saía como parágrafo preto e linhas de botões empilhavam. Entram também `.mp-modal*`, `.callout`, `.rev*`, `.idea*`, `.offer*`, `.cost*`, `.ov-btn`, `.empty`, `.sk-*`, `.segmented`. |
| `app/os/ui-modals.jsx` | **novo** (427 linhas) | Componentes canônicos: `Modal`, `Confirm`, `Lightbox`, `EmptyState`, `SkeletonRows`, `Callout`, `Segmented`, `CostConfirm`, `OfferPick`, `ReviewCard`, `ArtCard`, `FlowHead`, `IdeaInput`, `ProcessModal`, `AnalyzeLoadingModal`, `RingLoader`. Todos em `window`. |
| `app/os/index.html` | carrega `ui-modals.jsx` **depois** de `icons.jsx` e **antes** dos `apps-*.jsx`; todos os `?v=` → `127123` | `ui-modals` depende de `Icon`/`Pill` e não pode ser sobrescrito por ninguém. Sem o cache-bust o navegador serve JSX velho. |
| `app/os/apps-core.jsx` | apagadas `ProcessModal`, `AnalyzeLoadingModal` e `formatAnalyzeEta` (118 linhas) e `ProcessModal` saiu do `Object.assign` | As versões antigas carregam **depois** e sobrescreveriam as novas — o modal continuaria escuro e o anel rosa `#fb2f68` continuaria aparecendo. |

### Telas (passos 4–8)

- **7 modais com scrim preto → `<Modal>` / `<Lightbox>`**
  `apps-clientes.jsx`: `CatalogLinkModal` (`icon="link"`), `CopyProductsModal` (`icon="copy"`), detalhe do post.
  `apps-conteudo.jsx`: viewer do carrossel (→ `<Lightbox>`, mantendo navegação anterior/próxima e a instrução enviada ao modelo), preview e detalhe.
  `apps-dist.jsx`: detalhe do post agendado.
- **6 `window.confirm` → `<CostConfirm>` / `<Confirm>`.** Onde havia gasto real, o padrão virou
  `pedirGerar()` (abre a confirmação) + `gerar()` (executa): vídeo (`kind="credits"` quando
  `pf.is_credits`) e artes (`est >= 1.5`). Exclusões de projeto e de peça usam `<Confirm>`.
  O `window.prompt` da edição de arte com IA virou modal com `<Field>` + textarea.
- **Tema escuro residual → `<Callout>`.** Os blocos `#3a2f10`/`#ffd479` (devolutiva do cliente,
  aviso de composição) e o `.err` com `✕` viraram callouts claros.
- **Fila de aprovação → `<ReviewCard>`**, com trilha de status por estado
  (aguardando / com ressalvas / reprovado / aprovado) e `<Segmented>` no lugar do toggle `◉ / ○`.
- **Briefing:** produtos viram `<OfferPick>` + `.offer-count`, cabeçalho `<FlowHead>` e o novo
  **`<IdeaInput>`** — o operador escreve a ideia em texto livre e a IA transforma em briefing,
  que segue editável.
- **Emoji de controle → ícones** (`↻ ✏️ 🎞️ ✕ 🎬 ✂️`) e o anel rosa `#fb2f68` do upload
  (`api.js`) passou a usar `#ed5f02`, da paleta.

## Desvios conscientes

1. `ReviewCard` usa `<Pill>` — confirmado que existe em `icons.jsx` antes de ligar.
2. O backend **ignora** `idea`: o endpoint lê `request.json()` cru, então campo extra não quebra.
   Para o botão funcionar hoje, a ideia entra como `theme` quando não há assunto escolhido e vai
   também como `idea` no payload, para o backend priorizá-la quando passar a lê-la.

## Como foi verificado

Chromium headless sobre o `index.html` **real** (local e depois em produção):

- 14 arquivos carregam 200, incluindo `ui-modals.jsx`;
- 19 componentes disponíveis como função e `StepBriefing/StepCriacao/StepAprovacao/StepAgenda` parseados;
- `svgsVazios: 0` (nenhum `<Icon name>` inexistente), `scrimPreto: 0`, **0 erros de JS**;
- `StepBriefing` + `StepAprovacao` renderizados com API mockada: 2 `ReviewCard` com estados
  `changes`/`rejected` e clique em excluir abre `<Confirm>` — **nenhum diálogo nativo**;
- produção: `/health` → `{"ok":true,"version":"1.27.123"}`, `?v=127123` único no `index.html`.

`docs/marcos/regressao_check.py` acusa 5 telas divergentes, mas o mesmo teste num worktree limpo
do HEAD dá **os mesmos hashes** — divergência pré-existente do golden, não deste patch. O motor
criativo (`template_composer.py`, `posts.py`) não foi tocado.

## Como testar

1. Abra `https://caripost.cariap.com.br/os/index.html` e recarregue com Ctrl+Shift+R.
2. **Clientes** → um cliente → *Vincular oferta* e *Copiar produtos*: janela branca, scrim claro.
3. **Conteúdo → Briefing**: o campo "Qual é a ideia?" com sugestões clicáveis; escreva e use
   *Transformar em briefing*; os produtos aparecem como cartões selecionáveis.
4. **Criação**: gere artes com custo acima de R$ 1,50 → a confirmação de gasto é uma janela do app
   com valor e quebra de custo, não o diálogo do navegador. Passe o mouse sobre uma arte: os três
   botões são ícones. Clique na arte: visualizador com *Anterior*/*Próxima*.
5. **Aprovação**: a fila mostra cartões com faixa colorida por status; *Excluir* abre confirmação
   dentro do app.
