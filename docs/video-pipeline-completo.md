# Pipeline de criação de criativos de VÍDEO — documentação completa

> Como o Caripost gera um reel/story 9:16 "branded" de ponta a ponta: do assunto digitado
> até o `.mp4` final com legenda, logo, CTA e áudio. Estado real do código em **v1.27.13**.
> Arquivos-chave: `app/os/apps-conteudo.jsx` (UI), `app/routers/posts.py` (endpoints/orquestração),
> `app/services/ai.py` (roteiro/áudio/CTA/chamada ao provedor), `app/services/video_composer.py`
> (camada de marca via ffmpeg/PIL).

---

## 0. Filosofia (a regra que explica TODO o resto)

**O modelo de vídeo só entrega a CENA em movimento. Tudo que é identidade — texto, legenda,
logo, CTA e áudio — é desenhado/montado DEPOIS, pelo nosso código, de forma determinística.**

Por quê:
- Modelos de vídeo "queimam" texto torto/errado nos frames e inventam voz garbled. Então pedimos
  `generate_audio=False` e proibimos texto na cena (`build_video_prompt`).
- Assim a marca fica **consistente e controlável** (mesma cor, fonte, layout, logo por contraste),
  igual ao carrossel — e não na mão da IA.

Consequência prática: um clipe do modelo tem teto de segundos (ex.: Veo = 8s). Para um reel de 15s,
o sistema gera **2 cenas** com continuidade e concatena. Não existe "1 clipe de 15s".

---

## 1. Os 5 passos da UI (app "Conteúdo")

`CONT_STEPS` em [apps-conteudo.jsx](app/os/apps-conteudo.jsx#L161): **Cliente → Briefing → Criação →
Aprovação → Agendamento**. O vídeo usa dois deles:

- **Briefing** (`StepBriefing`): escolhe formato **Vídeo**, **trava a duração** (`Livre/8/15/30/60s`),
  escreve o assunto e gera o **roteiro** (texto que mostra as cenas + narração). Nada custa aqui.
- **Criação** (`VideoCreator`, [linha 59](app/os/apps-conteudo.jsx#L59)): escolhe o **modelo de vídeo**,
  vê o **custo estimado automático** (preflight), confirma e dispara a geração real (que gasta dinheiro).

A duração escolhida vive no estado `videoSeconds` (persistido em `ContState`) e é a **régua mestra**
que atravessa todo o pipeline.

---

## 2. Catálogo de modelos e provedores

Em [ai.py](app/services/ai.py#L613): duas listas `(slug, nome, qualidade, preço_usd, max_seconds)`:

- **`CURATED_VIDEO`** → OpenRouter (ex.: `google/veo-3.1` 8s, `openai/sora-2-pro` 12s, `veo-3.1-lite` 8s $0.18).
- **`CURATED_VIDEO_COMET`** → CometAPI (rota documentada `POST/GET /v1/videos`). Kling/Runway/xAI
  ficam de fora porque usam rotas próprias (listá-los cobrava em endpoint errado).

O modelo ativo fica em `settings["video.model"]`. Funções de catálogo:
`video_model_max_seconds()` (máx s/clipe, default 8), `_video_catalog_entry()` (preço+máx+nome),
`video_clip_price()` e `video_price_per_second()` (preço, com **aprendizado de preço real** — ver §9).

Provedor efetivo resolvido em `get_video_config()` → `{provider, apiKey, model, base}`.

---

## 3. A régua mestra: duração → nº de cenas (determinístico)

Mesma matemática em **3 lugares** (preflight, generate-briefing, generate-branded-video):

```
target = segundos escolhidos (0 = LIVRE)
mx     = video_model_max_seconds()           # máx por clipe do modelo
se target > 0:                               # TRAVADO
    per    = max(1, min(mx, target, 12))     # segundos POR CLIPE (nunca > máx do modelo, nunca > 12)
    n_want = max(1, min(8, ceil(target/per)))# nº de cenas — TETO 8 = trava de custo
senão:                                       # LIVRE
    per, n_want = mx, 0                       # a IA decide nº de cenas (preflight/briefing usam n_want=0)
```

Exemplos com Veo (mx=8): 8s→1 cena; **15s→2 cenas**; 30s→4; 60s→8. O teto de 8 cenas impede
explosão de custo. **Nunca** se manda o total como duração de cada clipe (foi um bug que multiplicava custo).

`video_scene_count()` em [ai.py:1806](app/services/ai.py#L1806) encapsula a mesma conta.

---

## 4. Roteiro em cenas — `build_video_storyboard`

[ai.py:1995](app/services/ai.py#L1995). Recebe `(company, theme, video_prompt, target, n_scenes, per)`
e devolve `[{prompt, seconds, desc}]`.

- **Travado** (`n_scenes>0`): pede à IA EXATAMENTE `n_scenes` cenas distintas e sequenciais (com
  continuidade), cada uma com `per` segundos. "NÃO repita cenas — cada uma avança a narrativa."
- **Livre** (`n_scenes=0`): a IA decide a duração ideal (15–60s) e quebra em cenas.
- Cada `seconds` da IA é **snapado** para `{4, 8, 12}` (`min(allowed, key=…)`).
- O `prompt` de cada cena passa por **`build_video_prompt`** ([ai.py:1916](app/services/ai.py#L1916)):
  prompt **SÓ-CENA** premium, com **grade de cor puxando a cor da marca** e **proibição dura de
  texto/logo** ("o código desenha marca/legenda/CTA depois").
- **Ancoragem no produto real**: `_video_brief_context` ([ai.py:1945](app/services/ai.py#L1945)) lê
  `product_list` (funções/objetivo/knowledge/web_brief) filtrado pelos apps citados no tema e injeta
  "use SÓ estes fatos, não invente". Faz cena+narração falarem do app de verdade. Sem produto → segue genérico.
- Fallback custo-seguro: sem IA configurada → 1 cena com o prompt base.

---

## 5. Plano de áudio — `build_video_audio_plan`

[ai.py:2132](app/services/ai.py#L2132). **Quem manda no áudio é o BRIEFING.** A IA (diretor de áudio)
lê o briefing e devolve JSON `{mode, script, music, voice}`:

- `mode ∈ {none, music, narration, both}`. Briefing **omisso → `music`** (reel mudo performa mal).
- `script`: locução PT-BR com teto de `~2.3 palavras/seg × duração` (casa com o tempo; proíbe ler
  preço/soletrar URL).
- `music`: descrição da vibe (instrumental, sem vocais).

Geração real (best-effort, **nunca quebra o vídeo**):
- **Narração** → `tts_synthesize` ([ai.py:2064](app/services/ai.py#L2064)): CometAPI `/v1/audio/speech`
  (OpenAI-compat), mp3, ~$0.01.
- **Trilha** → `music_generate` ([ai.py:2086](app/services/ai.py#L2086)): CometAPI **Suno**
  (`/suno/submit/music` → poll `/suno/fetch/{id}` → baixa), instrumental forçado, timeout ~150s.

---

## 6. CTA do vídeo

Dois caminhos (o ativo é o do endpoint):
- `build_video_cta` ([ai.py:2173](app/services/ai.py#L2173)): IA gera `{eyebrow,title,subtitle,cta}`
  ancorado no produto/evento (proíbe inventar preço/data).
- No `generate-branded-video` ([posts.py:1417](app/routers/posts.py#L1417)) o CTA é montado
  **determinístico**: app em foco como eyebrow, "Fale com a {marca}", subtítulo "Leve {app} para sua
  base", telefone formatado, override por `body.cta`/`body.cta_title`. Vídeo não deixa o copy final na mão da IA.

---

## 7. Preflight de custo — `/video-preflight`

[posts.py:1445](app/routers/posts.py#L1445). Roda **automático** quando muda modelo/duração
([apps-conteudo.jsx:82](app/os/apps-conteudo.jsx#L82)). Monta o storyboard (mesma matemática da §3),
calcula custo **sem gerar vídeo** e devolve `{scenes, total_seconds, seconds_per_scene, scene_seconds,
total_usd, total_brl, price_real, storyboard}`.

Preço (ordem de preferência):
1. **`video_price_per_second`** (preço REAL por segundo do catálogo do provedor) → `persec × total_s` (bate 100%).
2. **`video_clip_price`** (preço aprendido OU catálogo) × nº de cenas.

`price_real`/`price_learned` sinaliza se já é preço real ou estimativa.

---

## 8. Disparo da geração — `/generate-branded-video`

[posts.py:1341](app/routers/posts.py#L1341). A UI confirma o custo, manda `{theme, storyboard,
target_seconds, seconds, scene_seconds, cta, apps}` e o endpoint:

1. Recalcula `per`/`n_want` (§3). **TRAVA o nº de cenas**: corta o que sobra, completa o que falta →
   custo previsível.
2. Monta `audio_plan` (§5) com `total = n × per`.
3. Resolve **logos**: `co_logos` = todas as variantes da marca (motor escolhe por contraste);
   `app_logos` = SÓ o app em foco (marcado em `body.apps` OU citado no tema, normalizado sem
   acento/espaço). Nunca carimba app arbitrário (era o bug do "e-saúde").
4. Monta o CTA determinístico (§6).
5. **Força `https` no `base_url`** ([posts.py:1436](app/routers/posts.py#L1436)): atrás do traefik o
   `request.base_url` volta `http://`, mas o provedor baixa o frame de continuidade por HTTP externo e
   `/uploads` só responde em https → sem isso a cena falha **depois** de já ter cobrado a anterior.
6. Dispara `_render_branded_video_job` numa **thread daemon** e retorna `{job, scenes}`.

A UI então faz polling em `/branded-video-status` a cada 6s e anima o `ProcessModal`.

---

## 9. Orquestração em background — `_render_branded_video_job`

[posts.py:1208](app/routers/posts.py#L1208). Gera as cenas **EM SEQUÊNCIA com continuidade**:

```
para cada cena i:
    create_video_job(prompt_i, per, "720x1280", first_frame_url, …)   # first_frame = último frame da cena i-1
    poll get_video_job a cada 15s (até 60 polls OpenRouter / 120 CometAPI)
    ao concluir: soma custo (usage.cost real → senão estimativa de catálogo)
    download_video → {jid}_c{i}.mp4
    last_frame_png({jid}_c{i}.mp4) → {jid}_f{i}.png  → vira o first_frame_url da PRÓXIMA cena (CONTINUIDADE)
escreve progresso/custo num {jid}.json a cada passo (status: generating→composing→done|error)
gera narração (TTS) + trilha (Suno) conforme o plano
compose_branded_video(...)  → {jid}.mp4
APRENDE o preço real: settings["video.price.<modelo>"] = usage_cost/nº_cenas   # próxima previsão bate
```

A **continuidade** (último frame de uma cena = primeiro frame da próxima) é o que faz N clipes curtos
parecerem 1 vídeo contínuo. O custo é **bounded** (nº de cenas travado) e **converge pro real** após o
1º uso de cada modelo.

### Chamada ao provedor — `create_video_job` ([ai.py:2208](app/services/ai.py#L2208))
- **OpenRouter**: `POST /videos` JSON, `generate_audio=False`, `aspect_ratio="9:16"` (sem isso o Veo
  sai 16:9), `resolution="720p"`, `duration=min(seconds, máx_do_modelo)`, e `frame_images=[{type:
  image_url, frame_type: first_frame}]` para a continuidade.
- **CometAPI**: `POST /videos` multipart (model/prompt/seconds/aspect_ratio/resolution).
- **OpenAI**: `POST /v1/videos` (sora).
- Download: `_video_url_from_job` cobre `unsigned_urls/signed_urls` (OpenRouter) e vários formatos;
  `_download_video_url` só manda auth para hosts openrouter/cometapi.

---

## 10. Camada de marca — `compose_branded_video`

[video_composer.py:279](app/services/video_composer.py#L279). Transforma os clipes crus em 1 reel
branded. **O áudio nativo do provedor é descartado** (voz/trilha tem que ser controlada pelo sistema).

Por clipe:
1. `_clip_overlay_png` ([video_composer.py:136](app/services/video_composer.py#L136)): PNG transparente
   1080×1920 com gradiente sutil só na BASE (legibilidade) + **rodapé da marca** (`_brand_frame`:
   logo embaixo-esquerda escolhida por contraste + site embaixo-direita). O MEIO fica livre.
2. ffmpeg: `scale=1080:1920 + crop` (preenche 9:16), aplica **`_grade_filter`** (grade de cor da marca,
   determinística via `colorbalance/eq`), faz `overlay` do PNG, injeta **faixa silenciosa**
   (`anullsrc`) para o concat casar.

Depois:
3. `_cta_card_png` ([video_composer.py:155](app/services/video_composer.py#L155)): card de CTA 9:16
   pelo **MESMO motor do carrossel** (`compose_card_slide` → cor/fonte/layout idênticos), com logo da
   marca por contraste + **logo do app em foco** carimbada na área central-baixa. Vira um clipe de 2.6s.
4. **Concatena** todos os segmentos + o card de CTA (`concat`).
5. **`_mux_audio`** ([video_composer.py:243](app/services/video_composer.py#L243)): mixa **narração em
   volume cheio + trilha "ducked"** (`volume=0.16`) por cima da faixa silenciosa; `-c:v copy` (não
   re-encoda o vídeo). Sem áudio → copia a base.

Resultado: `{jid}.mp4` 9:16, 30fps, H.264, faststart, publicado em `/uploads/.../video/`.

---

## 11. Configuração / design tokens (SaaS multi-empresa)

Nada é hardcode de empresa. Tudo sai de `company.brand_kit`:
- `colors.accent/primary` → grade de cor, glow do CTA, destaque do título.
- `voice/persona`, `audience`, `client_rules`, `visual_prompt_base` → tom/regras do roteiro e do áudio.
- Logos por `asset_list_logos` (variantes da marca + por app) → escolha por contraste.
- `creative_config` pode sobrescrever os templates de prompt de vídeo (`creative_cfg(company).video`).
- `strength` da grade é design token (default sutil; pode ir pra `creative_config.design`).

---

## 12. Custo — resumo

- **Bounded** pela trava de nº de cenas (teto 8). Preview mostra estimativa; final mostra **custo REAL**
  quando o provedor devolve `usage.cost`.
- **Aprende preço real** por modelo (`video.price.<modelo>`) → a previsão passa a bater após o 1º uso.
- Conversão BRL via `usd_to_brl` (a UI deriva a taxa do próprio preflight).
- Áudio: TTS ~$0.01; Suno best-effort (não bloqueia).

---

## 13. Limitações e armadilhas conhecidas

- **Teto de segundos por clipe** (Veo 8s): 15/30/60s viram 2/4/8 cenas. Não há "1 clipe longo".
- **Cache-bust do front**: ao mexer em qualquer `.jsx`, subir o `?v=` daquele arquivo em
  `app/os/index.html`, senão o browser serve JSX velho (foi a causa do "duração 8s travada" no v1.27.9 →
  corrigido no v1.27.10 unificando os tokens). Ver `docs/marcos/fix-v1.27.10-cachebust-duracao-video.md`.
- **base_url https**: obrigatório atrás do traefik p/ a continuidade não falhar cobrando.
- **Modo LIVRE** (duração 0): nº de cenas fica a cargo da IA — custo menos previsível que o travado.
- **Geração é lenta** (minutos por cena): OpenRouter ~15min, CometAPI pode mais; UI faz polling longo.

---

## 14. Mapa rápido de funções

| Etapa | Função | Arquivo |
|---|---|---|
| UI roteiro | `StepBriefing` / `gerarAuto` | apps-conteudo.jsx |
| UI geração | `VideoCreator` / `gerar` | apps-conteudo.jsx |
| Roteiro (texto) | `generate_briefing` (ramo vídeo) | ai.py:2719* |
| Cenas | `build_video_storyboard` | ai.py:1995 |
| Prompt só-cena | `build_video_prompt` | ai.py:1916 |
| Contexto produto | `_video_brief_context` | ai.py:1945 |
| Áudio | `build_video_audio_plan` / `tts_synthesize` / `music_generate` | ai.py:2132/2064/2086 |
| Duração→cenas | `video_scene_count` / `video_model_max_seconds` | ai.py:1806/1793 |
| Custo | `video_cost_estimate` / `video_price_per_second` / `video_clip_price` | ai.py:1894/1843/1827 |
| Chamada provedor | `create_video_job` / `get_video_job` / `download_video` | ai.py:2208/2271/2310 |
| Preflight | `/video-preflight` | posts.py:1445 |
| Disparo | `/generate-branded-video` | posts.py:1341 |
| Orquestração | `_render_branded_video_job` | posts.py:1208 |
| Status | `/branded-video-status` | posts.py:1505 |
| Composição | `compose_branded_video` + helpers | video_composer.py:279 |

\* linhas aproximadas (mudam a cada versão).
