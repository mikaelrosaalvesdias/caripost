# Plano — Vídeo Caripost (planejar antes de gastar)

> Regra de ouro: **nada de teste pago até cada peça estar planejada e o passo anterior validado.** Vídeo é o módulo mais caro e mais frágil. Aqui está o mapa honesto: o que sabemos, os problemas duros, a arquitetura, as decisões que preciso de você, e as fases — cada uma com um gate de validação **barato** antes de avançar.

---

## 1. Objetivo e régua (o que vale tudo)

- **Briefing dita a duração** (ex.: 30s) → a IA cumpre montando **N cenas** coladas num vídeo único.
- **Continuidade** entre cenas (o medo real): não pode parecer 4 vídeos aleatórios.
- **Identidade da marca** (cores, clima, logo, legendas no padrão) — igual fizemos no carrossel.
- **Custo sob controle**: estimar ANTES, teto duro, e validar barato antes de escalar.
- **Multi-empresa (SaaS)**: tudo configurável (modelo, duração, formato), defaults bons.

---

## 2. Realidade técnica (o que JÁ existe e o que falta)

**Já existe:**
- Catálogo de modelos com preço e `max_seconds` ([ai.py `CURATED_VIDEO`/`CURATED_VIDEO_COMET`], 14 OpenRouter + 14 CometAPI) + seletor de modelo padrão no painel.
- Roteiro em cenas ([ai.py `build_video_storyboard`]) e prompt por cena ([`build_video_prompt`]).
- Geração **só Sora (OpenAI)**: `create_video_job` → `/v1/videos` (job async), `get_video_job` (poll), `download_video` (`/content`).
- Fluxo async: `/generate-video` (N cenas) + `/video-status` (poll) que **junta os clipes** com ffmpeg ([posts.py `_stitch_videos`]).

**Falta (o trabalho de verdade):**
- **Roteamento por provedor**: `create_video_job` está **fixo no Sora**. OpenRouter e CometAPI têm APIs de vídeo **diferentes** (endpoints, formato de request, polling, download). Cada família (veo, kling, seedance, runway) pode ter shape próprio na Comet. → **maior incerteza; pesquisa read-only primeiro (grátis).**
- **Continuidade** (last-frame chaining) — não existe.
- **Identidade da marca** no vídeo (intro/outro, logo, legendas) — não existe.
- **Áudio** (locução/música) — não existe (e Sora gera áudio nativo, os outros não → decisão).
- **Dimensionamento por duração** (briefing 30s → nº de clipes pelo `max_seconds`) — não existe.
- **Preflight de custo** (mostrar "30s ≈ 4 clipes ≈ R$X" antes de gerar) — não existe.

---

## 2.5 — FASE 0 FEITA (R$0, só docs): de-risca o medo da continuidade

Li a doc de vídeo da OpenRouter. Descobertas que mudam tudo:

- **API única e assíncrona:** `POST /api/v1/videos` (manda prompt → recebe job id → faz polling → baixa). UMA API cobre veo, seedance, wan, sora-2-pro. → resolve quase todo o **P2 (roteamento)**: foco no **OpenRouter como provedor primário**; Comet vira fallback (APIs por família, mais bagunçadas).
- **CONTINUIDADE É SUPORTADA NATIVAMENTE:** a API aceita `frame_images` com `frame_type` = `first_frame` **ou** `last_frame`. → o *last-frame chaining* que eu propus **funciona via API**: pego o **último frame** do clipe N e mando como **`first_frame`** do clipe N+1. Não é gambiarra — é recurso oficial. **Isso de-risca o P1 (o seu medo).**
- **`input_references`:** imagens de referência de estilo/conteúdo (guia visual, não frame exato) → ajuda a **segurar a pessoa/identidade** nas cenas-chave (decisão "misto").
- **Filtro de modelo:** cada modelo expõe `supported_frame_images` → só ofereço continuidade nos modelos que aceitam frame. 
- **Hospedagem do frame:** a imagem inicial precisa ser URL pública, limpa (sem cookie/redirect). O app já serve `/uploads` assim → compatível.

**RECOMENDAÇÃO DE MODELO (decisões travadas: áudio nativo + misto + 9:16):**
- **veo-3.1 (Google) via OpenRouter** — áudio NATIVO + image-to-video (frame) + 8s/clipe + qualidade Top. **É o melhor encaixe.** 
- Fallback: **sora-2-pro** (áudio nativo + frame + 12s → menos emendas pros 30s, porém mais caro/lento).

→ Com isso, **P1 e P2 saem de "incerto" pra "viável e oficial".** O risco residual é só a *qualidade* da continuidade (o frame ajuda muito, mas o modelo ainda pode derivar no meio do clipe) — isso só o teste barato da Fase 2 decide.

## 3. Os problemas DUROS (cada um, como atacar, e o que é incerto)

### P1 — Continuidade entre cenas (o medo)
**Ataque:** *last-frame chaining* — gera a cena 1, extrai o **último frame** (ffmpeg), usa como **imagem inicial** (image-to-video) da cena 2. Cada cena "continua" a anterior. + roteiro coerente (mesmo personagem/cenário/clima, escrito pelo motor de briefing).
**Incerto:** nem todo modelo/provedor aceita frame inicial do mesmo jeito; a continuidade é **boa, não perfeita** (pode derivar). Precisa testar por modelo qual sustenta melhor. **Risco real — é o coração do módulo.**

### P2 — Roteamento por provedor (a parte chata)
**Ataque:** uma camada `video_provider` com `create/poll/download` por provedor (OpenAI, OpenRouter, CometAPI). O `id` já carrega o provedor (`cometapi:`, slug com `/` = OpenRouter, senão OpenAI).
**Incerto:** o shape exato das APIs de vídeo da OpenRouter e da Comet (sync? job? webhook? quanto demora? aceita image-to-video?). → **Fase 0 = ler as docs (grátis), sem gerar.**

### P3 — Áudio
**Decisão de produto:** (a) usar **só modelos com áudio nativo** (Sora-2, alguns veo) — simples mas limita a escolha; ou (b) **trilha separada** = locução TTS (já temos infra de voz?) + música, dublada por cima — funciona com qualquer modelo, mais controle, mais trabalho. Áudio contínuo across cenas é outro desafio.

### P4 — Legendas + identidade da marca
**Ataque:** legendas queimadas no padrão da marca (Poppins, cor de acento) com timing por cena; intro/outro com logo; color grade leve. Determinístico (ffmpeg/PIL), igual ao carrossel — **barato e confiável**.

### P5 — Custo e tempo
**Realidade:** 30s ≈ 4 clipes × ~R$2–2,70 = **~R$8–11** e ~4× o tempo (minutos). 
**Ataque:** **preflight** (estima e pede confirmação antes), **teto de duração**, e **validação incremental** (1 clipe curto antes de qualquer 30s).

### P6 — Formato / aspecto
9:16 (reels/story) é o alvo. Confirmar que cada modelo entrega 9:16 (vertical) — alguns só 16:9. Filtrar/etiquetar no catálogo.

---

## 4. Arquitetura proposta (fluxo completo)

```
Briefing (KB+web+site) → roteiro de vídeo: GRANDE IDEIA + N cenas (fala/legenda + visual),
                         dimensionado pela duração-alvo e pelo max_seconds do modelo escolhido
        ↓ preflight: "30s = 4 cenas no veo-3.1 ≈ R$10,80 · confirmar?"
Para cada cena i:
   prompt da cena (coerente com a anterior)
   + (i>1) imagem inicial = último frame da cena i-1     ← continuidade
   → video_provider.create() → poll → download (clipe i)
        ↓
Pós: color grade da marca + legendas (timing por cena) + intro/outro com logo
        ↓
Stitch (ffmpeg concat) → 1 vídeo final 9:16 → preview mobile → publicar
```

---

## 5. Decisões (TRAVADAS pelo Igor)

1. **Áudio: SÓ modelos com áudio nativo** (Sora-2, veo). → o catálogo usável encolhe pros que geram som; sem TTS/música separada por ora. Continuidade de áudio entre cenas vira um cuidado (cortes secos, sem trilha cruzando).
2. **Visual: MISTO** — maioria b-roll (cenas/produto, fácil de colar) + **pessoa nas cenas-chave** (abertura/CTA). → só preciso segurar o rosto em 1–2 cenas, não no vídeo todo (reduz muito o risco de continuidade).
3. **Modelo de partida: eu escolho** após a Fase 0 (recomendo o melhor pra continuidade + áudio nativo + 9:16, com base nas docs).
4. **Legendas:** sempre queimadas (default) — feed roda sem som.
5. **Durações:** configurável; começo curto (6–12s) e só vou a 30s no fim.

---

## 6. Plano em FASES (cada uma com gate barato — nada caro sem validar a anterior)

- **Fase 0 — Pesquisa de API (R$0):** ler docs de vídeo da OpenRouter e CometAPI; mapear create/poll/download e **se aceitam imagem inicial** (continuidade). Entrego um doc com o shape real de cada provedor. **Sem gerar nada.**
- **Fase 1 — 1 clipe, 1 modelo (R$~2):** roteamento por provedor + gerar **1 clipe curto (6–8s)** no modelo escolhido. Você olha: qualidade, 9:16, marca. Gate humano.
- **Fase 2 — Continuidade (R$~5):** 2 cenas com last-frame chaining + stitch. Você julga **se cola sem parecer dois vídeos**. É o teste que mata (ou aprova) o medo.
- **Fase 3 — Marca (R$~5):** legendas no padrão + intro/outro com logo + color grade, sobre o vídeo da Fase 2. Determinístico.
- **Fase 4 — Áudio (custo conforme decisão):** locução/música conforme item 1 das decisões.
- **Fase 5 — Briefing-driven + preflight + UI:** duração do briefing → nº de cenas; preflight de custo; seleção de modelo na geração; teto. Aí sim 30s de verdade.

**Critério de PRONTO:** um vídeo de 15–30s, coeso, na cara da marca, gerado em poucos minutos, com custo estimado ANTES e dentro do teto. Só então vira recurso "de produção".

---

## 7. Riscos que podem mudar o plano (honesto)

- Se a API de vídeo da OpenRouter/Comet **não aceitar imagem inicial**, a continuidade fica fraca → talvez fixar nos modelos que aceitam, ou priorizar 1 clipe mais longo (12s) e menos emendas.
- Continuidade perfeita **não existe** hoje; vamos calibrar até "bom o suficiente pra postar".
- Custo escala com duração — por isso preflight + começar curto.
