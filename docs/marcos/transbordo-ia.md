# Transbordo inteligente de imagem · v1.25.98 (anti "editorial em tudo")

Problema relatado: numa rodada (4 versões × 6 telas), a CometAPI ficou **sem saldo** no meio
(`用户额度不足, 剩余额度: $-0.007`). O sistema (que eu PROIBI de transbordar no Marco 0) despejou **editorial em
5/6 telas** — depois de já ter pago as que passaram. Dinheiro perdido + entrega sem qualidade.

## Solução (ai.py + posts.py)
`generate_image_resilient(prompt, size, ref, model, ref_urls, dead_providers, registry)`:
1. Tenta o modelo PEDIDO. Erro **transitório** (timeout/5xx) → 1 retry no mesmo modelo.
2. Erro de **PROVEDOR MORTO** (saldo/cota/auth — `_err_provider_dead`, reconhece PT/EN/**CN**) → marca o provedor
   como morto e **pula pra um modelo EQUIVALENTE de OUTRO provedor** (`_image_fallback_chain`): pedido →
   +1 do mesmo provedor → o MELHOR de cada outro (OmniRoute grátis primeiro, depois PiAPI/OpenRouter).
3. `dead_providers` é um set **compartilhado entre as telas**: provedor que caiu na tela 5 **não é tentado de
   novo** na 6 (não desperdiça tempo nem dinheiro).
4. **Editorial só se a cadeia INTEIRA falhar** (todos os provedores caídos).

CometAPI e CometAPI-Gemini contam como o MESMO provedor (mesma conta/saldo). Vale no carrossel E no post único.

## Resposta da API
- `model_used` por tela (qual modelo realmente desenhou).
- `spillover`: "N telas transbordaram p/ outro modelo (o pedido falhou/sem saldo) … Você não perdeu o carrossel".
- `warning` (editorial) só quando TUDO cai.

## Provado por mim
- Cadeia p/ `cometapi:gpt-image-2` = `[cometapi:gpt-image-2, cometapi:gpt-image-1.5, omni(grátis), piapi, reve]`.
- Erro CN `用户额度不足` → classificado **provedor morto**; timeout → transitório.
- Simulei CometAPI morta → **pulou os 2 modelos CometAPI e entregou imagem REAL (1.95 MB) de outro provedor** (~$0.038),
  **zero editorial**. Golden verde, determinismo intacto.
