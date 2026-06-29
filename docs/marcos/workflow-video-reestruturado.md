# Workflow de VÍDEO reestruturado — o método para chegar no resultado

> Documento PRESCRITIVO. Define como usar o material de referência (NotebookLM "Infraestrutura v2.0" +
> "5 Níveis de Domínio") junto do estado atual (v1.27.13) para **reestruturar todo o nosso fluxo de
> vídeo** e bater o resultado que precisamos. Liga-se a: `video-pipeline-completo.md` (atual),
> `video-pipeline-roadmap-v2.md` (gap), `plano-video-v2.md` (fases).

---

## 0. O RESULTADO que precisamos (definição de sucesso)

Um reel/story de marca que **parece feito por agência**, não por IA solta. Concretamente:

1. **Mesmo personagem** do início ao fim (rosto, roupa, acessório) — não "pessoas diferentes a cada cena".
2. **Produto real e fiel** (a IA descreve o item de verdade, não alucina).
3. **Linguagem cinematográfica** (enquadramento, movimento de câmera e estilo escolhidos de propósito).
4. **Marca impecável** (logo, legenda, CTA, cor) — sempre por código, nunca queimada na cena.
5. **Áudio que vende** (narração no tom da marca + trilha, sincronizados com a duração).
6. **Custo previsível** e **configurável por empresa** (SaaS multi-cliente).

**Por que hoje NÃO chega lá:** o pipeline já garante 4 (marca) e 6 (custo). Falha em **1, 2, 3 e 5
(parcial)** — é exatamente onde os documentos de referência mandam atacar.

---

## 1. Princípio operante (a régua que não se quebra)

**A IA entrega só a CENA EM MOVIMENTO. Identidade (texto/logo/CTA/legenda/áudio) entra na pós, por
código, determinístico.** Os "5 Níveis de Domínio" entram assim no nosso fluxo:

| Nível | O que é | Onde vive no nosso workflow |
|---|---|---|
| 1 Ideia | assunto solto | campo "Assunto" do Briefing |
| 2 Estruturado | prompt em JSON (sujeito/câmera/estilo) | **novo** roteiro estruturado (Estágio B) |
| 3 Referência | imagem/último-frame guia | continuidade (já temos) + **vision do produto** (novo) |
| 4 Alavancagem | agentes/guia de modelos | nossos prompts-sistema + catálogo de modelos |
| 5 Pipeline | storyboard+11Labs+FFmpeg | nossa orquestração + pós (parte nova: voz premium) |

---

## 2. O WORKFLOW REESTRUTURADO — 6 estágios

```
A. ENTRADA & CONHECIMENTO  →  B. ROTEIRO ESTRUTURADO  →  C. TRAVAS (personagem+produto)
        →  D. APROVAÇÃO (gate, sem gasto)  →  E. GERAÇÃO (cenas+continuidade)
        →  F. PÓS (marca+áudio) & QA
```

### A. Entrada & Conhecimento
Assunto + apps em foco + **fatos do produto**: KB/funções/web_brief (texto, já temos) **+ imagem real do
produto analisada por vision** (novo). Saída: um "dossiê de fatos imutáveis" do que o vídeo pode afirmar.

### B. Roteiro estruturado (Nível 2)
`build_video_storyboard` deixa de devolver prosa e passa a devolver **JSON cinematográfico por cena**:
`{subject, environment, action, camera_framing, camera_movement, visual_style, seconds}`. A duração
(régua mestra) decide o nº de cenas (15s→2, etc.). Saída: storyboard editável e legível.

### C. Travas de consistência
- **Mapa de Personagem** gerado 1× (físico + idade + **acessório-âncora** + vestuário + altura) e
  **re-injetado em TODAS as cenas**. É o que garante "a mesma pessoa".
- **Trava de Produto**: os fatos do dossiê (A) entram em cada cena/narração — proibido inventar recurso.

### D. Aprovação (gate de qualidade, custo ZERO)
Preflight mostra **cenas + custo**. Usuário pode **editar/regerar cada cena** antes de gastar. Só passa
adiante com confirmação explícita. (Hoje há confirm de custo; falta a edição por cena.)

### E. Geração (cenas em sequência + continuidade)
`create_video_job` por cena, `generate_audio=False`, 9:16, 720p; **último frame → first_frame da
próxima** (mesmo cenário/personagem no tempo). Polling de status. Custo aprende preço real/seg.

### F. Pós (marca + áudio) & QA
- **Marca**: overlay (grade de cor da marca + rodapé logo/site por contraste) + **card de CTA** pelo
  motor do carrossel (logo do app carimbada).
- **Áudio**: narração (voz da marca — **ElevenLabs** no roadmap, hoje CometAPI) + trilha com **ducking**;
  lip sync quando houver rosto falando (roadmap).
- **QA automático**: checklist do §4 antes de marcar "done".

---

## 3. Mapa técnica-de-referência → estágio

| Técnica dos docs | Estágio | Status |
|---|---|---|
| Separação cena/marca (regra de ouro) | E+F | ✅ feito |
| JSON cinematográfico (sujeito/câmera/estilo) | B | ⟵ implantar |
| Mapa de personagem + acessório-âncora | C | ⟵ implantar |
| Análise de imagem do produto (vision) | A | ⟵ implantar |
| Continuidade por último frame | E | ✅ feito |
| Régua de duração → cenas | B | ✅ feito |
| Áudio TTS+trilha, ducking, ~2.3 pal/seg | F | ✅ (voz premium/lip sync = roadmap) |
| Preflight de custo + aprende preço | D | ✅ feito |
| Gate de aprovação por cena | D | ◐ parcial (falta edição por cena) |
| Estilos virais (reveal/unboxing/CGI/slow-mo) | B | ⟵ presets de `visual_style` |

---

## 4. Gates de qualidade — "resultado atingido" (checklist objetivo)

Um vídeo só é "bom" se passa em TODOS:
- [ ] É a **mesma pessoa** em todas as cenas (rosto + roupa + acessório-âncora).
- [ ] O **produto** mostrado bate com a imagem/fatos reais (nada inventado).
- [ ] Há **intenção de câmera** (não é só "pessoa parada falando").
- [ ] **Zero texto/logo queimado** na cena pela IA.
- [ ] Logo/legenda/CTA da marca **legíveis e na cor certa**.
- [ ] Narração **casa com a duração** (não corre nem sobra) e está no tom da marca.
- [ ] Custo final ≤ estimativa do preflight.

---

## 5. Antes × Depois

| | Hoje (v1.27.13) | Depois (workflow reestruturado) |
|---|---|---|
| Personagem | varia entre cenas | **travado** (mapa + acessório) |
| Produto | só texto | **texto + vision da imagem real** |
| Prompt de cena | prosa | **JSON cinematográfico** |
| Aprovação | confirm de custo | **edição/regeração por cena** |
| Voz | CometAPI TTS | **ElevenLabs** (tom da marca) + lip sync |
| Marca/custo | já impecável | mantém |

---

## 6. Como implantamos (amarrado às fases do `plano-video-v2.md`)

> Ajuste pós-validação (NotebookLM): o **Gate de Aprovação (D) é crítico** — sem editar/regerar cena a
> cena antes de gastar, B+C podem queimar crédito em gerações imperfeitas. Por isso **D entra junto da
> Fase 1** (a parte de edição/regeração por cena), não numa fase tardia. Já existe um gate básico hoje
> (briefing editável + confirm de custo); a Fase 1 adiciona a edição **por cena** sobre o roteiro estruturado.

1. **Fase 1 — Estágios B + C + D(parcial)**: roteiro estruturado (JSON) + personagem/produto travados +
   **edição/regeração por cena no gate de aprovação**. Maior impacto, só prompt+UI, **gasto só no clipe
   de teste no fim**. **Começar por aqui.**
2. **Fase 2 — Estágio A** (vision do produto): campo de imagem no produto + 1 chamada vision.
3. **Fase 3 — Estágio D(resto) + estilos**: presets de estilo viral (reveal/unboxing/CGI/slow-mo) + polimento do gate.
4. **Fase 4 — Estágio F+** (ElevenLabs + lip sync): voz premium.

Cada fase = 1 marco, entregue pelo ritual: testo gerando 1 clipe real → bumpo versão → deploy real no
`metaporn-new_adult-meta` → confirmo no ar → `marco-<fase>.md` → te explico o teste só do que a fase entrega.

---

## 7. Configurabilidade (inegociável — é SaaS multi-empresa)

Tudo via `company.brand_kit.creative_config` (defaults bons, override por cliente): templates de prompt
de vídeo, estilo padrão, voz/tom, força da grade de cor, presets de personagem. **Nada hardcode de empresa.**

> Resumo de uma frase: **a IA cria a cena; nós travamos personagem e produto, escolhemos a câmera,
> aprovamos antes de gastar, e o código aplica marca e áudio — é isso que transforma "clipe genérico" no
> resultado que precisamos.**
