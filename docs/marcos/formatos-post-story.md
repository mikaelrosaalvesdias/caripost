# Formatos no fluxo de criação — Post fixo modernizado + Story (9:16)

**Versão:** v1.26.20

## Problema
- O **carrossel** tinha o fluxo bom (modelo, versões, influencer, card de vidro, Novo/reabrir).
- O **post fixo** estava no fluxo ANTIGO (`StepCriacaoPost`, por produto) — "zoado".
- Faltava o formato **Story**.
- Cada formato tem dimensão diferente: carrossel/post **4:5** (1080×1350), story **9:16** (1080×1920).

## O que mudou (técnico)
### Motor (`template_composer.py`) — dimensão variável, SEM tocar no carrossel aprovado
- `compose_card_slide(..., canvas_size=None)` → `W_,H_ = canvas_size or (W,H)`. Todas as refs de W,H no corpo viraram W_,H_.
- `_subject_side`/`_place_y` agora usam `canvas.width/height` (não as constantes do módulo) → adaptam a qualquer canvas.
- `compose_carousel_slide` (Marco 0/1/2) **intocado** → golden segue verde.

### Endpoint (`posts.py` render-carousel)
- Lê `format` (carrossel/post/story) → `canvas_size` (story=1080×1920) + `img_size` (story `1024x1792`, resto `1024x1536`).
- Passa `canvas_size` ao `compose_card_slide`; aspecto do prompt do influencer também muda (9:16 no story).

### UI (`apps-conteudo.jsx`)
- Briefing: novo formato **Story**; post/story pedem `n_telas=1` (1 arte); story usa pauta de `post` no briefing e renderiza 9:16.
- `StepCriacao`: **carrossel, post e story** vão pro MESMO criador moderno (`CarrosselCreator`), só muda a dimensão. Vídeo segue no fluxo próprio.
- `CarrosselCreator({format})`: post/story = 1 arte (slice 1 tela); header mostra o formato; `format` no payload do render.

## Como atinge o objetivo
Post fixo e Story ganham EXATAMENTE as opções do carrossel (escolha de modelo, versões, toggle de influencer, card de vidro legível, Novo/reabrir) e cada um sai na dimensão certa do Instagram.

## Provado por mim
- `regressao_check.py`: 5/5 telas batem com o golden (carrossel não mudou).
- `compose_card_slide` renderizado em 4:5 (1080×1350) e 9:16 (1080×1920) — olhei o story, card no lado vazio + barra/numeração/logo adaptadas.
- JSX: `@babel/parser` → PARSE OK (sem erro de sintaxe).
- render-carousel `format=story` → HTTP 200, 1 arte.
