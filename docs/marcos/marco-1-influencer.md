# Marco 1 — Influencer usado bem + variedade + arte livre

**Versão:** v1.27.42 · **Serviço:** `metaporn-new_adult-meta` (no ar) · **Data:** 2026-07-01

## Objetivo
O influencer cadastrado (Clientes → Influencer) não estava sendo usado; quando usado, mal usado (rosto errado). E a arte livre/criativa vinha com caixa/padrão editorial engessado.

## O que mudou (técnico)

### 1. Influencer VOLTA A SER USADO — `app/routers/posts.py`
- **Gating (`_resolve_render_mode`):** selecionar um influencer (`use_influencer` + `influencer_id`) agora FORÇA `photo_ai_composer`. Antes o modo Editorial grátis caía em `composer_only` e PULAVA o influencer (bug "não usado").

### 2. Composição que PRESERVA o rosto — `compose_person_scene` (`app/services/ai.py`)
- A composição usava nano-banana via **CometAPI (sem saldo)** → falhava → cena sem pessoa ("mal usado"). Agora usa **kie image-edit** (`google/nano-banana-edit`): baixa a **foto pública real** (`image_urls`) e a edita na cena preservando rosto/expressão. CometAPI vira fallback. `posts.py` monta a URL pública via `_render_public_base()` (setting `render.public_base`). ~30s–3min por foto (créditos kie). Validado pelo usuário: rosto nítido.

### 3. VARIEDADE — fim do "só 2 fotos" — `app/routers/posts.py`
- `pick_influencer_photo` era determinístico → sempre índices 0/1. Agora `used_inf_idx` é semeado com as fotos RECÉM-USADAS (persistido em `influencer.recent.<id>`, deixando ≥2 frescas p/ capa+CTA). Posts consecutivos usam OUTRAS fotos → gira o portfólio inteiro. Testado: 10 fotos rodam [0,1]→[2,3]→…→[8,9]→recicla.
- A visão que casa emoção↔foto (`pick_influencer_photo`) escolhe entre as fotos FRESCAS → variedade + expressão certa. Isso cumpre o objetivo de "casar emoção" (acontece no render, por tela).

### 4. CometAPI despriorizado (sem saldo) — `app/services/ai.py`
- Todas as visões (verify/pick/clear-side) tentam **OpenRouter primeiro**; CometAPI só se recarregar.

### 5. ARTE LIVRE sem caixa/padrão — `app/services/template_composer.py`
- Novo modo `free_text`: arte criativa (intent=criativo, single) usa **texto solto** — só o gancho grande (+1 linha) com contorno escuro p/ legibilidade, SEM caixa/pílula-CTA/telefone/site (o padrão corporativo). `generate_carousel` seta `s0["free_text"]=True` no modo criativo; propaga via `slide_for_render`.

## Segurança
`regressao_check.py` OK antes/depois (as 5 telas do carrossel golden batem — o modo criativo/free_text não afeta o carrossel aprovado).

## Como validar (usuário)
1. **Influencer nítido + variado:** gere 2–3 carrosséis seguidos com o influencer marcado → cada um traz rostos/fotos DIFERENTES (capa+CTA), sempre nítidos.
2. **Arte livre:** modo "Criativo livre (meme/data)" + formato Post → o texto sai SOLTO (sem caixa/pílula/telefone), o gancho grande. Comparar com um Post em modo Produtos (que mantém o padrão corporativo).

## Superado do plano original
"Influencer antes do briefing" — o casamento emoção↔foto já acontece no render (por tela, `pick_influencer_photo` escolhe a expressão que combina com o texto). Não precisa antecipar pro briefing.
