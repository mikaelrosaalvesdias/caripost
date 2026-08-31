# Marco Fases 2–4 — Vision do produto + Estilos virais + Gate por cena + Voz premium (v1.27.16)

Fecha o roadmap de `workflow-video-reestruturado.md`. No ar em `caripost-new:1.27.16`
(`caripost.cariap.com.br/os/` em `?v=12716`, serviço converged).

## Fase 2 — Vision do produto (Estágio A)
- `vision_product_facts(img_bytes)` (ai.py): gpt-4o (CometAPI→OpenRouter) descreve os **fatos visuais
  imutáveis** do item (cor/formato/material/detalhes) — só o que vê, não inventa.
- Endpoint `POST /products/{id}/photo` (companies.py): salva a foto (role=photo) e **acumula os fatos em
  `product.knowledge`** com prefixo `[IMAGEM DO PRODUTO]`. Como o `_video_brief_context` já lê `knowledge`,
  a cena e a narração passam a **ancorar no produto real automaticamente** (zero mudança no caminho de vídeo).
- `asset_list_photos` + `photos` expostos em `GET /products`; UI de upload/preview/excluir no card do produto
  (apps-clientes.jsx). Custo-seguro: visão falha → foto salva mesmo assim.

## Fase 3 — Estilos virais + Gate por cena (Estágios B/D)
- `VIDEO_STYLES` (ai.py): presets **reveal / city_cgi / unboxing / slowmo** (+ auto), overrideáveis por
  empresa em `creative_config.video.styles`. `video_style_directive` injeta a diretiva no roteiro
  (`{style_rule}` no template). Threaded por preflight + generate (`style`).
- `POST /video-styles` → seletor na UI (VideoCreator). **POST** de propósito (GET seria engolido pela rota
  coringa `/{post_id}`).
- `POST /video-scene-regen`: **regenera UMA cena** mantendo continuidade + personagem + estilo (1 chamada de
  texto barata). UI: botão **↻ por cena** + "↻ Regerar roteiro inteiro". Completa o gate D (editar/regerar
  antes de gastar).

## Fase 4 — Voz premium (Estágio F)
- `tts_synthesize` (ai.py): backend **ElevenLabs** quando há chave (`settings['tts.elevenlabs.key']` ou env
  `ELEVENLABS_API_KEY`); voz/modelo via `tts.elevenlabs.voice|model`. **Fallback automático pro CometAPI** se
  não houver chave ou EL falhar (custo-seguro, nunca quebra o vídeo).
- **Lip sync: NÃO implementado** — precisa de um provedor/credencial definidos. Fica como próximo passo
  (hook a wirar quando você escolher o serviço).

## Compatibilidade / segurança
- Tudo **backward-compatible e gated**: sem foto → vídeo igual a antes; estilo `auto` → sem diretiva;
  sem chave EL → CometAPI. **Não toca no motor de imagem** (`regressao_check.py` intacto). Configurável por
  empresa via `creative_config.video`.

## Auto-teste (custo zero — dry-run no container 1.27.16)
- 5 estilos listados; `reveal` com diretiva, `auto` vazio.
- EL key vazio (sem chave) → cai no CometAPI (gating ok).
- `vision_product_facts` importável; storyboard com `style='reveal'` → **2 cenas, personagem nas duas**.
- Endpoints no ar: `/video-styles` 200, `/video-scene-regen` 422 (valida input).

## Como você testa (Ctrl+Shift+R em `/os/` p/ pegar o `?v=12716`)
1. **Fase 2:** Clientes → produto → **"Foto do produto"** → suba uma imagem. Aparece "✓ Foto analisada — fatos
   somados ao briefing: …". Gere um vídeo desse produto e veja se a cena/narração ficam fiéis ao item.
2. **Fase 3:** Conteúdo → Criação → **seletor "Estilo do vídeo"** (ex.: Revelação de produto) → o roteiro muda
   a linguagem. No roteiro por cena, **↻** regenera só aquela cena (sem custo).
3. **Fase 1 (já no ar):** mesma pessoa entre as cenas (acessório-âncora).

## Aviso honesto (não verificável aqui)
- **Voz ElevenLabs**: implementada e gated, mas **não testei ao vivo** (sem chave EL). Pra ativar: configure
  `tts.elevenlabs.key` (+ `tts.elevenlabs.voice`). Sem isso, segue no CometAPI como hoje.
- **Lip sync**: não entra nesta entrega.
