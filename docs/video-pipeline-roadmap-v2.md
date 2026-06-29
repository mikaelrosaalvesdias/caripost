# Vídeo IA — gap analysis: docs de referência (v2.0) × Caripost atual (v1.27.13)

> Cruzamento dos dois documentos de visão ("Infraestrutura v2.0" + "5 Níveis de Domínio")
> com o código real. Verdade técnica, sem marketing. Base: `docs/video-pipeline-completo.md`.

## Resumo
A maior parte da visão **já está implementada**. Os documentos confirmam a arquitetura atual.
Os ganhos reais estão em **4 frentes ausentes** — sendo a #1 (consistência de personagem) a que
ataca exatamente o problema que os dois textos mais enfatizam.

---

## ✅ JÁ FEITO (a visão e o código batem)

| Item dos docs | Onde no código |
|---|---|
| Regra de ouro: cena (IA) ↔ marca (código) | `build_video_prompt` proíbe texto/logo; `compose_branded_video` |
| Storyboard em cenas sequenciais | `build_video_storyboard` (ai.py:1995) |
| Régua mestra duração→cenas (15s=2 cenas) | preflight/briefing/generate (mesma conta §3) |
| Continuidade por último frame → first_frame | `last_frame_png` → `create_video_job(first_frame_url)` |
| `generate_audio=False` (sem voz/texto do modelo) | `create_video_job` (ai.py:2223) |
| Plano de áudio narração+trilha, ducking 0.16 | `build_video_audio_plan` + `_mux_audio` |
| Overlay + grade de cor + logo por contraste | `_clip_overlay_png` / `_grade_filter` / `_brand_frame` |
| Card de CTA determinístico (motor do carrossel) | `_cta_card_png` → `compose_card_slide` |
| Preflight de custo + aprende preço real/seg | `/video-preflight` + `video.price.<modelo>` |
| Polling de job + status | `_render_branded_video_job` + `/branded-video-status` |
| Ancoragem em fatos reais do produto (texto) | `_video_brief_context` (KB/funções/web_brief) |
| "Aprovação antes do gasto" | Briefing mostra o roteiro + `confirm()` de custo na Criação |

O storyboard **já é JSON internamente** (`{scenes:[{desc,seconds}]}`). O que NÃO é estruturado é o
prompt POR cena (ver gap #3).

---

## ◐ PARCIAL

- **Prompt cinematográfico**: hoje `build_video_prompt` gera uma **string** de cena premium. Os docs
  pedem campos (sujeito/ambiente/ação + enquadramento + movimento de câmera + estilo). Dá pra
  estruturar sem reescrever o pipeline.
- **Aprovação de roteiro**: existe (briefing + confirm de custo), mas não é um gate por-cena com
  editar/regerar cena antes de gastar.
- **Estilos de vídeo**: há 2 templates (`_T_VIDEO_DINAMICO`, `_T_VIDEO_CLEAN`), não os 4 estilos virais
  (product reveal / CGI city / unboxing / slow-mo tech).

---

## ✗ AUSENTE — os next steps reais (ordem de impacto)

### 1. Consistência de PERSONAGEM  ⟵ maior gap, é o tema central dos dois docs
Hoje as cenas são "distintas com continuidade", mas **nada trava o MESMO personagem** entre clipes
(só o last-frame ajuda, e ele se perde a cada nova cena). Falta um **Mapa de Características** fixo:
físico (cabelo cor/textura/corte, idade exata, etnia, formato de rosto, pele), **acessório-âncora**
(ex.: "brinco pequeno em estrela banhado a prata"), vestuário (cor/padrão/corte) e altura fictícia —
gerado **uma vez** e **repetido em TODAS as cenas** do `build_video_storyboard`.
Já existe base de vision pra rosto no fluxo de influencer (`vision_clear_side`, face-match gpt-4o) —
dá pra reaproveitar a régua. **Não existe ElevenLabs no código** (TTS é CometAPI).

### 2. VISION do produto real
`_video_brief_context` lê só **texto** (KB/funções/web_brief). Os docs pedem **analisar a imagem real
do produto** (gpt-4o vision) pra extrair fatos imutáveis e ancorar cena+narração. Produto hoje não tem
banco de imagem próprio (só influencer/evento têm). Precisa: campo de imagem no produto + 1 chamada vision.

### 3. Prompt cinematográfico ESTRUTURADO (Nível 2)
Trocar a string única por JSON de cena: `{subject, environment, action, camera_framing,
camera_movement, visual_style}` → consistência e troca rápida de variáveis (o "trocar produto, manter
iluminação" dos docs). É refactor de `build_video_prompt` + template em `creative_config.video`.

### 4. Voz premium + Lip Sync (Nível 5)
ElevenLabs no lugar/junto do TTS CometAPI; lip sync quando houver rosto falando. Custo/complexidade
maior; menor prioridade.

---

## Recomendação de sequência
1. **Personagem consistente** (Mapa de Características no storyboard) — ataca a dor #1, custo baixo (só
   prompt), sem novo provedor. Reaproveita vision do influencer.
2. **Prompt cinematográfico estruturado** — destrava câmera/estilo e prepara o terreno pro #1.
3. **Vision do produto** — precisa de UI (upload de imagem do produto) + 1 chamada vision.
4. **ElevenLabs + lip sync** — último, maior custo.

Cada frente é um marco isolado (rede de segurança: `regressao_check.py` cobre só o motor de imagem;
vídeo não tem golden — testar gerando 1 clipe real antes de pedir avaliação).
