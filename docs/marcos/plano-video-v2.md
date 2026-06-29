# Plano de evolução do VÍDEO IA — cobrir todas as deficiências (v2)

> O que entendi dos dois documentos de visão + o que vou aplicar, fase a fase, dentro do processo de
> marcos do projeto (testar eu mesmo → versão → deploy real → .md de entrega → teste simples).
> Base do estado atual: `docs/video-pipeline-completo.md`. Gap: `docs/video-pipeline-roadmap-v2.md`.

---

## Parte 1 — O que entendi (síntese)

Os docs convergem numa tese: **vídeo de marca profissional = IA faz só a CENA; o resto é determinístico**.
Isso o Caripost **já faz**. O que falta pra sair de "cena bonita genérica" para "anúncio coeso" são
**5 deficiências**:

1. **Personagem não é o mesmo entre cenas** — o last-frame ajuda, mas não trava físico/roupa/acessório.
2. **Prompt de cena é prosa, não estruturado** — sem controle explícito de câmera/movimento/estilo.
3. **Produto é descrito só por texto** — a IA não "vê" o item real (sem vision do produto).
4. **Voz é TTS básico (CometAPI), sem lip sync** — falta voz premium e sincronia labial.
5. **Sem biblioteca de estilos virais** nem gate de aprovação por cena antes do gasto.

Princípios que TODA mudança vai respeitar (CLAUDE.md): **configurável por empresa** (design tokens em
`creative_config`, nunca hardcode), **custo-seguro** (falha de IA nunca quebra o vídeo), **determinismo
da marca**, e **rede de segurança** (vídeo não tem golden → testo gerando 1 clipe real antes de pedir avaliação).

---

## Parte 2 — O que vou aplicar (fases = marcos)

### FASE 1 — Roteiro estruturado + Personagem consistente  ⟵ começar aqui
**Cobre deficiências #1 e #2 (acopladas: o mapa do personagem vive dentro da cena estruturada).**

**Mudança técnica:**
- `build_video_storyboard` (ai.py:1995) passa a pedir à IA um JSON mais rico:
  ```json
  {
    "character": { "present": true, "physical": "...", "anchor_accessory": "...",
                   "wardrobe": "...", "age": "...", "height": "1,75m" },
    "scenes": [ { "desc": "...", "subject":"...", "environment":"...", "action":"...",
                  "camera_framing":"close-up|wide|medium", "camera_movement":"slow push-in|tracking",
                  "visual_style":"35mm granulado|clean", "seconds": 8 } ]
  }
  ```
- O **bloco `character` é gerado 1× e RE-INJETADO em TODAS as cenas** (na montagem do prompt), forçando
  o mesmo físico/acessório/roupa em cada clipe. É a "ancoragem por acessório" dos docs.
- `build_video_prompt` (ai.py:1916) ganha um **template estruturado** (subject/environment/action +
  framing + movement + style + character) — tudo via `creative_config.video` (override por empresa), com
  fallback pro template atual. Mantém a proibição dura de texto/logo.
- Continua produzindo a **string final** que o provedor consome (nada muda em `create_video_job`).

**Por que atinge o objetivo:** o mesmo personagem com o mesmo brinco/roupa em 2–8 cenas = anúncio coeso,
não clipes soltos. Estrutura de câmera/estilo = salto "amador → cinematográfico".

**Custo/risco:** só prompt (sem novo provedor, sem UI, sem gasto extra). Risco baixo. Não toca no motor
de imagem → `regressao_check.py` intacto. Teste: gero 1 reel de 15s (2 cenas) e confiro se é a mesma pessoa.

---

### FASE 2 — Vision do produto real
**Cobre deficiência #3.**

**Mudança técnica:**
- Produto ganha **banco de imagem** (hoje só influencer/evento têm — reaproveitar `company_assets`):
  `db_companies` + UI de upload na ficha do produto (`apps-*` de produtos).
- `_video_brief_context` (ai.py:1945) passa a, quando houver imagem do produto, fazer **1 chamada vision
  gpt-4o** (reaproveitando a régua de `vision_clear_side`/face-match já existente) para extrair **fatos
  visuais imutáveis** do item (cor, formato, material, detalhes) e injetar junto dos fatos de texto.
- Custo-seguro: sem imagem ou falha de vision → segue como hoje (texto).

**Por que atinge:** cena e narração param de "alucinar" o produto; descrevem o item de verdade.

**Custo/risco:** +1 chamada vision (~centavos) só quando há imagem. Mexe em DB + UI → marco próprio.

---

### FASE 3 — Estilos virais + gate de aprovação por cena
**Cobre deficiência #5 e o "Nível de aprovação antes do gasto".**

**Mudança técnica:**
- Biblioteca de **estilos** selecionável (product reveal / CGI city / unboxing luxo / slow-mo tech) como
  presets em `creative_config.video.styles` → entram como `visual_style`/`camera_movement` no prompt
  estruturado da Fase 1. Default = atual.
- **Gate de roteiro**: na tela de Criação, antes do `confirm()` de custo, permitir **editar/regerar cena
  a cena** (o storyboard já volta por cena no preflight; falta só a UI de edição). Zero gasto até confirmar.

**Custo/risco:** UI + config. Sem gasto de IA novo. Risco baixo.

---

### FASE 4 — Voz premium (ElevenLabs) + lip sync
**Cobre deficiência #4.**

**Mudança técnica:**
- Provedor de TTS plugável: `tts_synthesize` (ai.py:2064) ganha backend **ElevenLabs** além do CometAPI,
  escolhido por `settings`/`creative_config` (voz da marca). Fallback pro CometAPI.
- **Lip sync** opcional quando a cena tem rosto falando (provedor de lip sync sobre o clipe + narração).

**Custo/risco:** novo provedor + custo maior + mais lento. **Última prioridade** (maior complexidade,
menor retorno imediato vs. coesão visual).

---

## Parte 3 — Ordem e entrega

| Fase | Deficiência | Esforço | Gasto novo | Mexe em |
|---|---|---|---|---|
| 1 — Roteiro estruturado + personagem | #1, #2 | baixo | não | só prompts (ai.py) |
| 2 — Vision do produto | #3 | médio | vision (~centavos) | DB + UI + ai.py |
| 3 — Estilos + gate de aprovação | #5 | médio | não | UI + config |
| 4 — Voz premium + lip sync | #4 | alto | TTS premium + lip sync | ai.py + novo provedor |

**Cada fase é 1 marco isolado**, entregue pelo ritual do projeto: eu testo gerando 1 clipe real → bumpo as
3 strings de versão → faço build overlay + `docker service update` no `metaporn-new_adult-meta` → confirmo
no ar → escrevo `docs/marcos/marco-<fase>.md` → te explico como testar **só o que aquela fase entrega**.

**Recomendação:** começar pela **Fase 1** — ataca as duas deficiências que os docs mais cobram
(personagem + estrutura cinematográfica), com risco e custo mínimos, e prepara o terreno pras fases 2–4.

> Nada foi codificado ainda. Aguardo teu "vai" pra executar a Fase 1 (ou reordenar).
