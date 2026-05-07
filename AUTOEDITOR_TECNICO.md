# AutoEditor — Detalhamento Técnico

## Fluxo Principal (`run_auto_editor_job`)

```
[1]  Preparação de fontes
      ↓
[2]  Vision Analysis (Grok Vision) — por source
      ↓
[3]  Detecção de cenas (ffmpeg scene detection, 360p)
      ↓
[4]  Build de candidatos (_build_scene_candidates)
      ↓
[5]  Enriquecimento com Vision (_enrich_candidates_with_vision)
      ↓
[6]  Perfil do canal do criador (Xvideos scraping)
      ↓
[7]  Seleção heurística (fallback) + Grok LLM
      ↓
[8]  Coverage fix (garante todos os source_index)
      ↓
[9]  Filtro de equipamento (_filter_equipment_scenes)
      ↓
[10] Planejamento de transições (_plan_scene_transitions)
      ↓
[11] Extração paralela de clips (ffmpeg, Semaphore=3)
      ↓
[12] Timelapse opener (_build_timelapse_opener)
      ↓
[13] Concatenação (copy stream ou xfade reencode)
      ↓
[14] Store no MinIO/local
```

---

## Etapa por Etapa

### [1] Preparação de Fontes

Para cada `source_key`:
- Se `local:` → resolve path direto no filesystem
- Se S3/MinIO → faz download para `/tmp`
- Roda `ffprobe` em cada arquivo: duração, resolução, fps, `color_transfer`, `color_primaries`, `pix_fmt`
- Os campos HDR são armazenados no `input_probe.sources` para uso no recut

---

### [2] Vision Analysis (`_run_embedded_vision_analysis`)

Executado **por source** individualmente:

1. Detecta cenas a 360p com ffmpeg `select='gt(scene,threshold)'`
2. Extrai keyframes em JPEG (480p) — batch único ffmpeg via `select='between(t,...)'`
3. Envia frames para **Grok Vision** com prompt em PT-BR
4. Retorna:
   - `vision_analysis` — categorias, descrição, cenas detectadas, performers
   - `raw_cut_points` — timestamps de corte reutilizados na etapa [3]
   - `frame_timestamps` — timestamps dos keyframes extraídos

> **Nota:** Esta etapa consome a maior parte do tempo (~2h para 11 vídeos 4K). O Re-cut a pula completamente, reutilizando os dados do job original.

---

### [3] Detecção de Cenas (`_detect_scene_timestamps`)

```bash
ffmpeg -vf "scale=-2:360:flags=bilinear,select='gt(scene,0.32)',showinfo"
```

- Roda a **360p** (~5-8× mais rápido que 4K)
- Retorna lista de timestamps onde há mudança de cena
- Threshold padrão: `0.25` (reduzido de 0.32 — menos cortes detectados → cenas naturalmente mais longas)

---

### [4] Build de Candidatos (`_build_scene_candidates`)

- Cada segmento entre dois cortes = 1 candidato
- **Mínimo:** 12s (`_HARD_MIN`) — segmentos menores são descartados
- **Máximo:** se `> max_scene_duration`, trima do centro
- Fallback: candidatos espaçados uniformemente se `< 6` detectados

**Score por candidato:**
```
score = (duration_score × 0.70) + (center_score × 0.15) - edge_penalty(0.15)
```
- `duration_score` — proximidade da duração ideal (`min(30s, max_duration × 0.3)`)
- `center_score` — favorece cenas no meio do vídeo
- `edge_penalty` — penaliza cenas nos primeiros/últimos 5s

---

### [5] Enriquecimento com Vision (`_enrich_candidates_with_vision`)

Para cada candidato, encontra o frame Vision mais próximo temporalmente:
- Adiciona `vision_relevance` (0–0.35 de boost no score)
- Adiciona `vision_excerpt` (descrição textual do que Grok viu naquele momento)

---

### [6] Perfil do Canal do Criador

Scraping do canal Xvideos do criador para determinar categoria dominante:
`anal / oral / vaginal / threesome / lesbian / squirt / solo`

Esse perfil é passado ao Grok como contexto adicional para calibrar a seleção.

---

### [7] Seleção por LLM (`_llm_select_scenes_grok`)

**Pre-filter:** top 15 candidatos por `source_index` (garante que todos os vídeos sejam representados)

**Marcação especial:** `is_gozada_candidate=True` nos candidatos dos últimos 90s do último source

**Payload enviado ao Grok (por cena):**
```json
{
  "scene_index": 12,
  "source_index": 2,
  "source_time_start": 142.5,
  "source_time_end": 198.0,
  "duration": 55.5,
  "score": 0.82,
  "vision_relevance": 0.28,
  "is_gozada_candidate": false,
  "vision_excerpt": "Penetração vaginal com a mulher por cima..."
}
```

**Prompt:** lido do banco de dados SQLite (`settings` → key `ae_narrative_rules`). Editável diretamente na UI sem necessidade de redeploy.

**Parâmetros Grok:** `temperature=0.2`, `max_tokens=2400`

**Resposta esperada:**
```json
{"scenes_to_keep": [1, 4, 7, 12], "reason": "..."}
```

---

### [8] Coverage Fix

Se Grok ignorou algum `source_index` (vídeo inteiro sem representação):
- Injeta automaticamente os top-3 candidatos desse source por score
- Garante que **todos os vídeos** apareçam no corte final

---

### [9] Filtro de Equipamento (`_filter_equipment_scenes`)

Remove deterministicamente qualquer cena onde `vision_excerpt` contém:

```
câmera, camera, tripé, tripod, equipamento, equipment,
microfone, microphone, luz de estúdio, ring light, bastidor,
filmagem, filming setup, production crew, behind the scenes
```

Esse filtro é pós-seleção (após o Grok), então é garantido mesmo que o LLM ignore a regra.

---

### [10] Planejamento de Transições (`_plan_scene_transitions`)

Para cada par de clips consecutivos:
- Verifica se o corte coincide com um `scene_change` real (±1.5s de tolerância)
- Se sim → **hard cut** (sem transição)
- Se não → **crossfade** (suaviza a junção artificial)

---

### [11] Extração Paralela (`_extract_scene_clip`)

Roda até **3 ffmpeg simultâneos** via `asyncio.Semaphore(3)`:

```bash
ffmpeg -ss {start} -i {source} -t {duration} \
  -vf "{hdr_filter},{scale},{fps}" \
  -c:v libx264 -crf 23 -preset fast \
  -c:a aac -b:a 192k
```

**HDR → SDR (automático se detectado):**

| Tipo | Filtro |
|------|--------|
| HLG (`arib-std-b67`) | `zscale=transfer=linear:npl=100 → tonemap hable → zscale bt709 → yuv420p` |
| PQ/HDR10 (`smpte2084`) | `zscale=transfer=linear:npl=1000 → tonemap hable → zscale bt709 → yuv420p` |
| S-Log/BT.2020 | `colorspace=all=bt709:iall=bt2020:fast=1 → yuv420p` |

**Detecção HDR:**
```python
_HDR_TRANSFERS = {"arib-std-b67", "smpte2084", "slog", "slog2", "slog3", "bt2020-10", "bt2020-12"}
_HDR_PRIMARIES = {"bt2020"}
# Também detecta por pix_fmt: "10le", "10be", "12le"
```

> Sony XAVC S-I = `arib-std-b67` (HLG) → filtro zscale com `npl=100`

---

### [12] Timelapse Opener (`_build_timelapse_opener`)

Cria um teaser de abertura (~10s) com os melhores momentos em alta velocidade:

1. Seleciona top-8 cenas por `vision_relevance`
2. Extrai 2.5s do **centro** de cada cena
3. Aplica velocidade 2× (`setpts=0.5*PTS` + `atempo=2.0`)
4. Cada clip fica ~1.25s → total ~10s de teaser
5. Colocado **antes** de todos os outros clips no vídeo final

---

### [13] Concatenação

| Condição | Método | Velocidade |
|----------|--------|------------|
| Sem crossfade | `ffmpeg -f concat -c copy` | Ultrarrápido (sem reencode) |
| Com crossfade | `xfade` + `acrossfade` filter graph | Lento (reencode completo) |
| Fallback | `_concat_clips_reencode` | Médio |

---

### [14] Store

- Salva em MinIO ou storage local via `_store_local_path`
- Roda `ffprobe` no output final
- Atualiza o job com `result_video_url`, `output_probe`, `selected_scenes`

---

## Re-cut (`run_recut_job`)

Mesmo fluxo, com estas diferenças:

| Etapa | Job Normal | Re-cut |
|-------|-----------|--------|
| Vision Analysis | ✅ Executa (~2h) | ❌ Pula — reutiliza dados do job original |
| Re-probe fontes | Não necessário | ✅ Sempre re-proba (garante HDR metadata) |
| Detecção de cenas | ✅ | ✅ |
| Seleção Grok | ✅ | ✅ (novo prompt, mesma Vision) |
| Extração/concat | ✅ | ✅ |

**Tempo estimado:** 20-40 min vs 3-5h do zero.

---

## Arquivos Críticos

| Arquivo | Responsabilidade |
|---------|-----------------|
| `app/services/auto_editor_pipeline.py` | Pipeline completo (2000+ linhas) |
| `app/routers/auto_editor.py` | Endpoints REST (`/start`, `/status`, `/recut`, `/config`, `/jobs`) |
| `app/main.py` | `_probe_metadata`, `_is_hdr_source`, `_build_hdr_to_sdr_filter`, `_detect_scene_timestamps` |
| `app/db.py` | `async_job_put/get/list`, `settings_get/set` (prompt editável) |
| `app/ui/app.js` | Frontend — funções `aeStartJob`, `aeRecut`, `aeLoadPrompt`, `aeSavePrompt` |

---

## Configuração do Prompt (UI)

O prompt enviado ao Grok é **100% editável sem redeploy**:

- **Localização na UI:** AutoEditor → seção "Prompt do Grok ✎"
- **Armazenado em:** SQLite `settings` → key `ae_narrative_rules`
- **Variáveis disponíveis:** `{n_sources}` (qtd de vídeos), `{n_sources_minus1}` (índice máximo)
- **Reset:** botão "↺ Resetar padrão" restaura o prompt padrão do sistema

---

*Última atualização: v1.12.4 — abril/2026*
