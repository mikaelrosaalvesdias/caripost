# Plano: Cortes Inteligentes com IA

## Diagnóstico

O `_cortes_worker` atual (main.py:8402) é arcaico:

- **Sem IA** — usa ffmpeg `select='gt(scene,0.30)'`, detecção burra sem contexto semântico
- **Humano decide minutagem** — usuário escolhe `num_clips` e `clip_duration` sem saber o que funciona
- **Extrai N clips sequenciais** — cada um roda encode ffmpeg completo, um atrás do outro
- **Sem cache** — detecção de cena roda do zero a cada chamada, mesmo pro mesmo vídeo
- **Sem semáforo** — N jobs podem rodar simultaneamente sem limite, sobrecarregando CPU
- **Download redundante** — baixa o vídeo inteiro do S3 toda vez

O grosso do custo de servidor **não é LLM** — é ffmpeg. Cada clip roda encode x264 com escala/crop.

---

## Arquitetura Nova

```
[Usuário] → "Gerar Cortes" (sem parâmetros de minutagem)
    ↓
[Servidor] → baixa vídeo (1 vez)
    ↓
[Servidor] → extrai ~100 frames em 240p (ffmpeg rápido, <5s)
    ↓
[Servidor → API] → Vision AI (Grok/OpenRouter) analisa frames
    ↓
[API → Servidor] → retorna [{start, end, reason, score}] — IA decidiu os cortes
    ↓
[Servidor] → extrai clips em PARALELO (semáforo=3)
    ↓
[Servidor] → cacheia análise por hash do vídeo (próxima vez = 0 chamada IA)
    ↓
[Usuário] → recebe clips + preview
```

---

## Fases de Implementação

### Fase 1 — AI Decide os Cortes (substitui input humano)

Criar `_ai_select_best_clips()`:

1. Extrair ~100 frames em timestamps uniformes (1 a cada 5-10s, 240p, ffmpeg rápido)
2. Enviar para Vision AI com prompt especializado para conteúdo adulto
3. AI retorna `[{start_time, end_time, reason, quality_score}]`
4. Filtrar por score mínimo, respeitar duração total máxima

**Prompt sugerido:**

```
Analise estes frames de um vídeo adulto.
Identifique os MELHORES MOMENTOS para cortes verticais (Shorts/Reels).
Considere: ação intensa, close-ups, mudanças de posição, expressões, iluminação.
Retorne JSON com lista de {start_time, end_time, reason, quality_score(0-1)}.
Mínimo 15s por cena. Máximo 8 cortes. Priorize variedade (não todas cenas seguidas).
```

**Resultado**: usuário só clica "Gerar Cortes" — sem slider de quantidade/duração.

### Fase 2 — Extração Paralela com Semáforo

Substituir loop sequencial por `asyncio.gather` com semáforo:

```python
sem = asyncio.Semaphore(3)

async def _extract_one_clip(...):
    async with sem:
        return await _run_ffmpeg(...)

tasks = [_extract_one_clip(ts, duration) for ts in ai_clips]
outputs = await asyncio.gather(*tasks)
```

Reduz tempo total de `N × duração` para `ceil(N/3) × duração`.

### Fase 3 — Cache de Análise por Hash

- Calcular `xxh64` do primeiro 1MB do vídeo
- Salvar resultado da Vision AI em `cache/vision/{hash}.json` no storage
- Mesmo hash = pulaa chamada de IA completamente
- Cache compartilhado entre Cortes e AutoEditor

### Fase 4 — ffmpeg.wasm no Cliente (opcional, alto impacto)

Server-side só retorna timestamps + URL do vídeo. Browser faz crop/scale/encode com ffmpeg.wasm:

- Servidor processa ZERO ffmpeg
- Usuário já tem o vídeo em cache CDN
- Cortes de 20-60s são leves pra roda no browser

### Fase 5 — Profissional

- **Smart crop**: AI detecta região de interesse (rosto/pessoa) em vez de centro fixo
- **Legendas automáticas**: reusar `_transcribe_openrouter_stt` + queimar no corte
- **Hook text**: AI gera texto de hook sobreposto no início
- **Preview**: thumbnails dos cortes selecionados, usuário só confirma

---

## Comparativo Antes/Depois

| Aspecto | Hoje | Com o plano |
|---|---|---|
| Quem decide timestamps | Humano (num_clips + duration) | IA Vision |
| Precisão dos cortes | Cena aleatória | Contexto semântico |
| Carga de CPU | ffmpeg sequencial (N passes) | ffmpeg paralelo (max 3) |
| Chamadas de IA | Nenhuma | 1 análise vision por vídeo único |
| Cache | Nenhum | Hash → 0 reanálise |
| Experiência do usuário | Sliders técnicos | 1 clique |
| Qualidade do output | Genérica | Cenas de maior impacto |

---

## Roadmap

| Fase | Tempo | Impacto |
|---|---|---|
| Fase 1 — IA decide cortes | 1-2 dias | Elimina input humano, qualidade sobe |
| Fase 2 — Paralelismo | 0.5 dia | Speedup 3x na extração |
| Fase 3 — Cache | 0.5 dia | 0 reanálise do mesmo vídeo |
| Fase 4 — ffmpeg.wasm | 3-5 dias | Servidor processa 0 encode |
| Fase 5 — Smart crop/etc | 2-3 dias | Produto profissional |
