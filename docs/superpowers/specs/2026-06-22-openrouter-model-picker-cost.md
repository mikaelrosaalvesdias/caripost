# Seletor de modelos (imagem/vídeo) + custo via OpenRouter

**Data:** 2026-06-22 · Objetivo: trocar texto pra OpenRouter e dar ao usuário, em Criação,
um **seletor de modelos** de imagem e vídeo (os do ranking) com **custo previsto** e
**custo final** mostrados na hora.

## Pré-requisito (bloqueia o teste)
- Adicionar a **API key do OpenRouter** em Settings (`ai.apiKey.openrouter`).
  Sem ela não dá pra listar modelos nem gerar/testar. O usuário disse que tem.

## Fatos da API OpenRouter (confirmados na doc)
- **Lista de modelos de imagem:** `GET https://openrouter.ai/api/v1/images/models`
  → cada item: `id` (slug), `architecture` (modalidades), `endpoints[].pricing`
  (`billable: output_image`, `unit: image|megapixel|token`, `cost_usd`, `variant` ex. 2k/4k).
- **Geração de imagem:** Image API dedicada. Params: `model`, `prompt`, `n`, `resolution`
  (`512|1K|2K|4K`), `aspect_ratio` (`1:1|9:16|16:9...`), `size`, `quality`
  (`auto|low|medium|high`), `output_format`, `input_references`. Resposta: imagens em
  base64 + **`usage` com o custo real**. (URL exata do POST a confirmar com a key viva —
  provável `/api/v1/images/generations`.)
- **Texto:** trocar `ai.provider = openrouter` (já suportado em `ai.py` via base
  `openrouter.ai/api/v1`).
- **Vídeo:** OpenRouter tem doc de Video Generation; endpoint/modelos a confirmar com a key.
  Modelos do ranking (Sora-2, Veo-3.1, Kling/Seedance, Wan, Grok-video) — ver quais o
  OpenRouter expõe via a Models API filtrando output=video.

## Modelos-alvo (do ranking enviado)
- **Imagem:** gpt-image (1/2), gemini-3-pro-image (nano-banana-pro), gemini-flash-image
  (nano-banana), flux, reve, ideogram, grok-imagine-image, etc. — **a lista real vem da
  `/images/models`** (não hardcodar; puxar ao vivo com pricing).
- **Vídeo:** sora-2 / sora-2-pro, veo-3.1, seedance, kling, wan, grok-imagine-video.

## Implementação

### Backend (`app/services/ai.py`)
1. `openrouter_image_models()` → GET `/api/v1/images/models` (header `Authorization: Bearer <key>`),
   normaliza para `[{id, name, provider, price_per_image_usd}]` (extrai `cost_usd` do
   `billable=output_image, unit=image`; quando `unit=megapixel`, calcula pelo size).
   Cacheia ~10min.
2. `generate_image_openrouter(model, prompt, size, quality)` → POST geração → retorna
   `(bytes, cost_usd)` (custo de `usage`).
3. `get_image_config()` ganha suporte a provider `openrouter` (key + base).

### Backend (`app/routers/posts.py`)
4. `GET /api/posts/image-models` → `{models: [...], default}` (OpenRouter + fallback OpenAI
   gpt-image-1/dall-e-3 com pricing conhecido). Para o seletor.
5. `POST /api/posts/generate-image` aceita `model`; roteia (OpenRouter slug → openrouter;
   senão openai). Retorna `cost_usd` real + a URL salva. Mantém overlay dos logos.
6. (v2) endpoints equivalentes de vídeo: `GET /api/posts/video-models` + `model`/custo no
   generate-video.

### Frontend (`app/os/apps-conteudo.jsx` — StepCriacao)
7. Dropdown **Modelo de imagem** (de `/image-models`, mostrando `$X/imagem`).
8. **Custo previsto** = preço/imagem × quantidade (atualiza ao mudar modelo/qtd).
9. Após gerar, **Custo final** real (soma dos `cost_usd`) por peça e total da geração.
10. (v2) Dropdown **Modelo de vídeo** + custo.

### Padronização
11. Botão "definir como padrão" no modelo escolhido → salva em Settings
    (`image.model`/`video.model`) pra usar por default.

## Ordem
1) Key do OpenRouter em Settings → 2) `/image-models` + dropdown + custo previsto →
3) gerar via OpenRouter + custo final → 4) padronizar → 5) vídeo (modelos + custo).

## Risco controlado
A geração atual (OpenAI gpt-image-1) **continua funcionando** como fallback. O OpenRouter
entra como opção; só vira default quando o usuário escolher. Assim não quebra o que funciona.
