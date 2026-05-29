# Documentacao completa do sistema de legendas

Ultima revisao: 2026-05-15
Versao do app na revisao: v1.17.2
Escopo: transcricao, limpeza, edicao SRT, traducao, preview e queima de legenda no video.

## 1. Visao geral

O sistema de legendas do MetaPorn tem cinco etapas principais:

1. O video original entra no sistema por upload, arquivo local ou arquivo do servidor.
2. A transcricao gera texto, segmentos com tempo e SRT.
3. A legenda fica salva no `run` dentro de `request_json.transcript`.
4. O usuario revisa/edita o SRT na aba Criacao.
5. O backend queima a legenda no video com FFmpeg, opcionalmente junto com logos.

Fluxo resumido:

```text
video_object_key
  -> POST /transcribe
  -> transcript.text + transcript.segments + transcript.srt
  -> PUT /runs/{run_id}/transcript
  -> editor SRT / preview / traducao
  -> POST /api/burn-subtitles
  -> burns/.../legendado_*.mp4
```

## 2. Arquivos principais

Backend:

```text
app/main.py
```

Funcoes e endpoints principais:

```text
TranscribeRequest
Transcript
TranscriptSegment
POST /transcribe
GET /runs/{run_id}/srt
PUT /runs/{run_id}/transcript
POST /api/translate-srt
POST /api/burn-subtitles
GET /api/burn-subtitles/status/{job_id}
POST /api/burn-subtitles/cancel/{job_id}
GET /api/burn-subtitles/queue
_format_srt
_format_srt_premium
_parse_srt_to_segments
_clean_transcript_segments
_transcribe_local
_transcribe_premium
_transcribe_assemblyai
_transcribe_openrouter_stt
_burn_subtitles_worker
```

Frontend:

```text
app/ui/index.html
app/ui/app.js
```

Funcoes principais:

```text
transcribeAnalyzeSelected
reTranscribe
onTranslateLangChange
saveTranscript
_saveTranscriptData
_srtEditorInit
_srtQuickFix
updateSubtitlePreview
burnSubtitles
_pollBurnJob
```

## 3. Modelo de dados da legenda

### 3.1 Segmento de transcricao

Cada segmento representa um trecho falado com inicio, fim e texto:

```json
{
  "start": 12.34,
  "end": 15.80,
  "text": "Ai, que delicia."
}
```

Campos:

```text
start: tempo inicial em segundos, float
end: tempo final em segundos, float
text: texto do trecho
```

Alguns providers podem incluir metadados extras antes da limpeza, como:

```text
confidence
avg_logprob
no_speech_prob
compression_ratio
premium_mode
```

Esses metadados nao sao obrigatorios no formato final salvo.

### 3.2 Objeto transcript

O formato salvo no run e retornado pela API segue esta estrutura:

```json
{
  "provider": "openrouter_stt",
  "tried": ["groq"],
  "lang": "pt",
  "source_lang": "pt",
  "target_lang": "",
  "translated": false,
  "text": "Texto completo concatenado...",
  "srt": "1\n00:00:12,340 --> 00:00:15,800\nAi, que delicia.\n",
  "segments": [
    {
      "start": 12.34,
      "end": 15.80,
      "text": "Ai, que delicia."
    }
  ],
  "cleanup": {
    "removed_count": 0,
    "kept_count": 1,
    "reason_counts": {},
    "expected_lang": "pt",
    "detected_lang": "pt"
  },
  "provider_meta": {},
  "adult_mode": true,
  "include_vocalizations": true,
  "enhance_audio": true
}
```

Campos importantes:

```text
provider: provider vencedor da transcricao.
tried: lista de candidatos tentados.
lang: idioma final da legenda, depois de traducao se houver.
source_lang: idioma detectado ou informado para a fala original.
target_lang: idioma de destino quando houve traducao.
translated: true quando a API traduziu os segmentos.
text: texto completo.
srt: legenda pronta em formato SubRip.
segments: lista estruturada com timestamps.
cleanup: resumo dos filtros aplicados.
provider_meta: metadados especificos do provider.
adult_mode: flag operacional para conteudo adulto.
include_vocalizations: indica se vocalizacoes claras devem ser preservadas.
enhance_audio: indica se pre-processamento de audio foi usado.
```

### 3.3 Onde fica salvo

A legenda fica salva no banco dentro do JSON do run:

```text
runs.request_json.transcript
```

O endpoint usado para salvar uma edicao e:

```http
PUT /runs/{run_id}/transcript
```

Body:

```json
{
  "transcript": {
    "srt": "1\n00:00:00,000 --> 00:00:02,000\nTexto...\n",
    "text": "Texto...",
    "segments": []
  }
}
```

## 4. Formato SRT

O app usa SRT/SubRip como formato editavel e baixavel.

Exemplo:

```srt
1
00:00:12,340 --> 00:00:15,800
Ai, que delicia.

2
00:00:16,100 --> 00:00:18,500
Isso, vai.
```

Regras:

```text
Indice numerico em ordem.
Timestamp no formato HH:MM:SS,mmm.
Separador obrigatorio: -->
Texto em uma ou mais linhas.
Linha em branco entre blocos.
```

Conversao interna:

```text
segments -> _format_srt -> srt
srt -> _parse_srt_to_segments -> segments
```

## 5. Prioridade ao buscar uma legenda

Quando o backend precisa de uma legenda para download ou burn, ele tenta nesta ordem:

1. `transcript.srt`
2. `transcript.segments`, convertido por `_format_srt`
3. `transcript.text`, quebrado em blocos artificiais como fallback

Fallback de texto puro:

```text
chunk_size: 12 palavras
words_per_sec: 2.5
```

Esse fallback existe para nao perder uma transcricao antiga que so tinha texto, mas nao deve ser considerado ideal. O ideal e sempre salvar `srt`.

## 6. Endpoints de legenda

### 6.1 Transcrever

```http
POST /transcribe
```

Body:

```json
{
  "video_object_key": "local:uploads/2026/05/12/video.mp4",
  "language": "pt-BR",
  "translate_to": "",
  "provider": "premium",
  "adult_mode": true,
  "include_vocalizations": true,
  "enhance_audio": true
}
```

Providers aceitos:

```text
auto
assemblyai
groq
openrouter
openai
local
premium
```

Observacao importante:

```text
provider=groq hoje funciona como alias historico para OpenRouter STT.
Ele usa token:openrouter, nao token:groq.
```

Resposta de sucesso:

```json
{
  "ok": true,
  "transcript": {
    "provider": "faster_whisper_large-v3",
    "text": "...",
    "srt": "...",
    "segments": []
  },
  "probe": {
    "duration_seconds": 123.4,
    "width": 3840,
    "height": 2160,
    "has_audio": true
  }
}
```

Erros comuns:

```text
missing_video_object_key
invalid_video_object_key
storage_get_failed
missing_audio_stream
ffmpeg_failed
empty_transcript
transcript_filtered
missing_openrouter_token
missing_openai_token
missing_assemblyai_token
audio_too_large
```

### 6.2 Baixar SRT do run

```http
GET /runs/{run_id}/srt
```

Retorna:

```text
Content-Type: text/plain; charset=utf-8
Content-Disposition: attachment; filename="legenda_{run_id}.srt"
```

### 6.3 Salvar SRT editado

```http
PUT /runs/{run_id}/transcript
```

Body:

```json
{
  "transcript": {
    "srt": "conteudo srt",
    "text": "conteudo texto",
    "segments": []
  }
}
```

### 6.4 Traduzir SRT

```http
POST /api/translate-srt
```

Body:

```json
{
  "srt": "1\n00:00:00,000 --> 00:00:02,000\nTexto\n",
  "target_lang": "en"
}
```

Resposta:

```json
{
  "ok": true,
  "srt": "SRT traduzido mantendo timestamps",
  "segments_count": 12
}
```

### 6.5 Queimar legenda no video

```http
POST /api/burn-subtitles
```

Body principal:

```json
{
  "run_id": "uuid",
  "video_object_key": "local:uploads/...",
  "font_size": 22,
  "font_color": "white",
  "sub_delay_secs": 0,
  "output_crf": 26,
  "max_height": 1080,
  "x264_preset": "ultrafast",
  "skip_subtitles": false
}
```

Resposta:

```json
{
  "job_id": "uuid"
}
```

Depois consultar:

```http
GET /api/burn-subtitles/status/{job_id}
```

Cancelar:

```http
POST /api/burn-subtitles/cancel/{job_id}
```

Ver fila:

```http
GET /api/burn-subtitles/queue
```

## 7. Providers de transcricao

### 7.1 Auto estrito

Provider:

```text
auto
```

Comportamento:

```text
Usa local strict.
Prioriza nao inventar fala.
Melhor retornar vazio do que transformar gemido/ruido em frase.
```

Uso recomendado:

```text
Quando o audio tem muita respiracao, gemido, musica ou fala pouco clara.
```

### 7.2 Local

Provider:

```text
local
```

Implementacao:

```text
faster-whisper small
CPU
strict=True
VAD ativo
```

Vantagens:

```text
Nao depende de API externa.
Mais conservador.
Bom para evitar alucinacao.
```

Limitacoes:

```text
Menos preciso em fala baixa.
Pode retornar pouco texto.
```

### 7.3 Premium

Provider:

```text
premium
```

Implementacao:

```text
faster-whisper large-v3
CPU
WAV 24 kHz
VAD relaxado
```

Configuracao importante:

```text
O fallback no_vad_rescue NAO roda por padrao.
Ele so roda se ADULT_META_PREMIUM_NO_VAD_RESCUE=true.
```

Motivo:

```text
Sem VAD, o modelo tenta interpretar gemidos e silencio como frases.
Isso gerava lixo como "I don't know what to do", "Amen", etc.
```

Uso recomendado:

```text
Fala baixa mas compreensivel.
Trechos com dialogo real em portugues.
```

### 7.4 AssemblyAI

Provider:

```text
assemblyai
```

Implementacao:

```text
API AssemblyAI /v2/upload
API AssemblyAI /v2/transcript
speech_models: universal-3-pro, universal-2
```

Token:

```text
token:assemblyai
```

Configuracoes relevantes:

```text
filter_profanity: false
punctuate: true
format_text: true
disfluencies: depende de include_vocalizations
speech_threshold: 0.20
language_code: definido pelo idioma escolhido quando existir
```

Keyterms:

```text
Em pt-BR, keyterms sao PT-BR/adulto.
Em ingles, keyterms sao ingles.
Em espanhol, keyterms sao espanhol.
```

Motivo:

```text
Nao empurrar o ASR em portugues para inventar frases em ingles.
```

Limitacao:

```text
AssemblyAI e generico. Em gemidos/silencio pode misturar idioma e inventar palavras.
O filtro PT-BR remove blocos classicos de alucinacao depois da transcricao.
```

### 7.5 OpenRouter STT

Providers:

```text
groq
openrouter
```

Observacao:

```text
groq e alias historico no frontend/backend.
Hoje ele usa OpenRouter STT com token:openrouter.
```

Endpoint:

```text
https://openrouter.ai/api/v1/audio/transcriptions
```

Token:

```text
token:openrouter
```

Modelo padrao:

```text
openai/whisper-large-v3
```

Variavel de ambiente:

```text
OPENROUTER_STT_MODEL
```

Audio:

```text
WAV base64
Fatia audio longo em chunks
```

### 7.6 OpenAI Whisper

Provider:

```text
openai
```

Endpoint:

```text
https://api.openai.com/v1/audio/transcriptions
```

Modelo:

```text
whisper-1
```

Token:

```text
token:openai
```

Audio:

```text
AAC 32 kbps
Limite pratico: 25 MB
```

Erro comum:

```text
audio_too_large
```

## 8. Pre-processamento de audio

Antes da transcricao, o backend baixa o video para temporario e extrai o audio.

### 8.1 WAV standard

Usado por:

```text
local
openrouter
```

Parametros:

```text
mono
16 kHz
pcm_s16le
```

### 8.2 WAV premium

Usado por:

```text
premium
```

Parametros:

```text
mono
24 kHz
pcm_s16le
```

### 8.3 AAC para APIs

Usado por:

```text
assemblyai
openai
```

Parametros:

```text
AAC
32 kbps
```

### 8.4 Realce de fala baixa

Quando `enhance_audio=true`, o FFmpeg aplica filtros para levantar fala e reduzir ruido.

Standard:

```text
highpass=f=65
lowpass=f=7800
afftdn
dynaudnorm
loudnorm
```

Premium:

```text
highpass=f=65
lowpass=f=11000
afftdn
dynaudnorm
loudnorm
```

Se o realce falhar, o backend tenta extracao simples.

## 9. Limpeza anti-alucinacao

Funcao central:

```text
_clean_transcript_segments
```

O sistema limpa por segmento antes de salvar/retornar.

### 9.1 O que remove

```text
segmentos vazios
scripts inesperados para idioma latino
spam conhecido de legendas
vazamento de prompt
frases classicas de ASR inventado
blocos claramente em idioma errado quando o idioma esperado e pt-BR
tokens longos sem sinal linguistico confiavel
```

Exemplos removidos em pt-BR:

```text
What's your password?
Thank you, Tommy.
Please support.
sadamsakumesama
MUSICA
subtitles by
subscribe
se inscreva no canal
```

### 9.2 O que deve preservar

Repeticao e vocalizacao real de conteudo adulto nao sao removidas por repeticao.

Exemplos preservados:

```text
vai vai vai
ai ai ai
hum hum hum
que delicia
caralho
me enche de leite
isso, mete
```

### 9.3 Por que repeticao nao e removida

Em conteudo adulto, repeticao pode ser fala real. O sistema nao classifica repeticao sozinha como alucinacao.

Funcao relacionada:

```text
_transcript_repetition_reason
```

Hoje ela retorna vazio de proposito.

### 9.4 Quando retorna transcript_filtered

Se o provider retorna segmentos, mas todos sao removidos pela limpeza, a API retorna:

```json
{
  "error": "transcript_filtered",
  "detail": "A transcricao gerada parecia alucinada ou em idioma incorreto..."
}
```

Isso e melhor do que salvar uma legenda completamente inventada.

## 10. Traducao de legenda

A traducao trabalha em cima do SRT existente.

Fluxo:

```text
SRT -> _parse_srt_to_segments -> _translate_segments_llm -> _format_srt
```

A traducao preserva:

```text
numero de segmentos
start/end de cada segmento
ordem dos blocos
```

Providers de traducao:

```text
Grok/xAI quando token:grok existe
OpenRouter quando token:openrouter existe
OpenAI quando token:openai existe
```

Na UI:

```text
Se o usuario muda "Traduzir legenda para" e ja existe SRT, o editor traduz imediatamente.
Se ainda nao existe SRT, a proxima transcricao ja pede traducao.
```

## 11. Editor SRT na aba Criacao

Local:

```text
Criacao -> Passo 2 - Gerar Video Legendado
```

Elementos:

```text
transcribeSourceLang: idioma falado no video
transcribeLang: idioma para traducao
transcriptSrtEdit: textarea do SRT
transcriptStatus: status operacional
srtStats: segmentos, palavras, caracteres
srtCursor: linha e coluna
```

### 11.1 Botoes de transcricao

```text
Auto estrito -> provider auto
AssemblyAI -> provider assemblyai
OpenRouter STT -> provider groq
OpenAI -> provider openai
Local -> provider local
```

Na aba Analyze tambem existe:

```text
Premium -> provider premium
```

### 11.2 Ferramentas do editor

```text
Buscar / Substituir
Substituir atual
Substituir tudo
Match case
Whole word
F3 / Shift+F3 para navegar
Fillers
Espacos
Renumerar
Salvar SRT
Baixar SRT
```

### 11.3 Quick fixes

Fillers remove termos como:

```text
uh
um
ah
eh
hmm
ne
tipo
assim
af
```

Atencao:

```text
Em videos adultos, "ah", "hmm" e similares podem ser conteudo real.
Use Fillers com cuidado.
```

## 12. Preview da legenda

O preview fica na aba Criacao, Passo 2.

Campos:

```text
burnFontSize
burnFontColor
burnSubDelay
subtitlePreviewScreen
subtitlePreviewText
```

Preview visual:

```text
usa frame selecionado quando disponivel
usa gradiente se nao tiver frame
posiciona texto no rodape
simula tamanho/cor antes do burn
```

Importante:

```text
O preview e aproximacao visual em CSS.
A queima final e feita pelo FFmpeg/ASS.
```

## 13. Queima da legenda no video

Endpoint:

```http
POST /api/burn-subtitles
```

Worker:

```text
_burn_subtitles_worker
```

### 13.1 Entrada

O worker recebe:

```text
job_id
run_id
video_object_key opcional
srt_content
req_data
logos/logo_b64
font_size
font_color
sub_delay_secs
output_crf
max_height
x264_preset
skip_subtitles
```

### 13.2 Fonte do video

Prioridade:

```text
video_object_key enviado no body
req_data.video_object_key salvo no run
req_data.video_url como fallback antigo
```

### 13.3 Fonte do SRT

Prioridade:

```text
transcript.srt
transcript.segments convertido para SRT
transcript.text quebrado em blocos artificiais
```

Se nao houver SRT e `skip_subtitles=false`, retorna:

```text
no_transcript
```

### 13.4 Delay da legenda

Campo:

```text
sub_delay_secs
```

Comportamento:

```text
positivo: atrasa a legenda
negativo: adianta a legenda
```

Funcao:

```text
_shift_srt
```

### 13.5 Estilo ASS usado na queima

O FFmpeg usa o filtro `subtitles` com `force_style`.

Base:

```text
FontName=Arial
FontSize={font_size}
PrimaryColour={cor}
OutlineColour=&H00000000
Bold=1
Outline=2
Shadow=1
```

Cores:

```text
white  -> &H00FFFFFF
yellow -> &H0000FFFF
cyan   -> &H00FFFF00
orange -> &H000080FF
black  -> &H00000000
```

Observacao:

```text
O filtro nao define Alignment/MarginV explicitamente.
O comportamento visual final segue o renderer ASS/FFmpeg, normalmente rodape central.
```

### 13.6 FFmpeg sem logo

Quando nao ha logo:

```text
-vf "scale...,subtitles=legenda.srt:charenc=utf-8:force_style='...'"
```

ou, sem escala:

```text
-vf "subtitles=legenda.srt:charenc=utf-8:force_style='...'"
```

### 13.7 FFmpeg com logo

Quando ha logo:

```text
video -> escala opcional -> overlays de logo -> subtitles -> format=yuv420p
```

Se `skip_subtitles=true`:

```text
video -> escala opcional -> overlays de logo -> format=yuv420p
```

### 13.8 Saida

Video final:

```text
libx264
AAC 128k
movflags +faststart
```

Configuracoes:

```text
output_crf: 18 a 35
max_height: 0 original, ou 720/1080/2160 etc.
x264_preset: ultrafast, superfast, veryfast, faster, fast, medium
threads: FFMPEG_BURN_THREADS, padrao 0 auto
```

## 14. Burn sem legenda

O mesmo endpoint serve para queimar apenas logo:

```json
{
  "run_id": "uuid",
  "skip_subtitles": true,
  "logos": []
}
```

Com `skip_subtitles=true`:

```text
nao exige transcript
nao aplica filtro subtitles
pode aplicar logo(s)
recodifica o video final
```

## 15. Fila e status do burn

O burn roda em background.

Status possiveis:

```text
pending
running
done
error
cancelled
```

Mensagens comuns:

```text
Aguardando fila de processamento...
Baixando video...
Analisando video...
Validando midia original...
Processando ffmpeg... 37%
Salvando video queimado...
```

O frontend faz polling em:

```http
GET /api/burn-subtitles/status/{job_id}
```

## 16. Estado da UI relacionado a legenda

Principais campos em `criacaoState`:

```text
transcriptDraft: SRT atual no editor
hasTranscript: indica se existe SRT/transcricao
transcribeSourceLang: idioma falado
transcribeTargetLang: idioma de traducao
transcribeAdultMode: flag adulto
transcribeIncludeVocalizations: preservar vocalizacoes claras
burnFontSize: tamanho da fonte
burnFontColor: cor da legenda
burnSubDelay: delay em segundos
burnSkipSubtitles: queimar sem legenda
burnedQuality: CRF escolhido
burnedResolution: altura maxima escolhida
burnedPreset: preset x264
activeBurnJobId: job de burn em andamento
burnedObjectKey: object_key do video final
burnedVideoUrl: URL de stream do video final
burnedFilename: nome exibido/baixado
```

## 17. Aba Analyze vs aba Criacao

### 17.1 Analyze

Uso:

```text
analise inicial
transcricao sob demanda
texto bruto
SRT gerado
download SRT
entrada para POST /analyze
```

Campos:

```text
anTranscript
anSrt
anLang
anIncludeVocalizations
anTranscribeEnhanceAudio
```

Funcao:

```text
transcribeAnalyzeSelected(provider)
```

### 17.2 Criacao

Uso:

```text
retranscrever run existente
editar SRT
traduzir
preview
salvar
queimar no video
continuar para teaser
```

Funcao de retranscricao:

```text
reTranscribe(provider)
```

Funcao de salvar:

```text
saveTranscript()
```

Funcao de burn:

```text
burnSubtitles()
```

## 18. Como uma legenda entra no Analyze

O fluxo de Analyze monta um `AnalyzeRequest` com:

```json
{
  "video_object_key": "local:uploads/...",
  "transcript": {
    "provider": "local",
    "lang": "pt",
    "text": "...",
    "segments": [],
    "srt": "..."
  }
}
```

Esse request e salvo como run. Depois a aba Criacao consegue recuperar:

```text
request_json.transcript
```

## 19. Como uma legenda e reidratada ao abrir um run

Ao abrir a Criacao, o frontend carrega o run e verifica:

```text
req_data.transcript.text
req_data.transcript.srt
req_data.transcript.segments
```

Se existir SRT:

```text
criacaoState.transcriptDraft = transcript.srt
criacaoState.hasTranscript = true
textarea transcriptSrtEdit recebe o SRT
preview e stats sao atualizados
```

## 20. Casos de falha e diagnostico

### 20.1 Transcricao inventa idioma errado

Sintomas:

```text
What's your password?
Thank you, Tommy.
Please support.
Hi! Hi! Hi!
sadamsakumesama
```

Causa:

```text
ASR tentando interpretar gemido/silencio/ruido como fala.
```

Mitigacao atual:

```text
idioma falado pt-BR
filtro anti-alucinacao PT-BR
Premium sem no_vad_rescue por padrao
AssemblyAI sem keyterms ingleses em pt-BR
```

### 20.2 empty_transcript

Sintoma:

```text
Whisper premium retornou transcricao vazia.
```

Interpretacao:

```text
O modelo nao encontrou fala confiavel.
Em trecho adulto com gemidos/silencio isso pode ser correto.
```

Acao:

```text
Testar outro provider.
Verificar se ha fala real no trecho.
Nao ativar no_vad_rescue sem revisao humana.
```

### 20.3 transcript_filtered

Sintoma:

```text
A transcricao gerada parecia alucinada ou em idioma incorreto.
```

Interpretacao:

```text
O provider retornou texto, mas o filtro removeu tudo.
Isso evita salvar lixo como legenda.
```

Acao:

```text
Confirmar idioma falado.
Testar provider local/auto.
Revisar se o trecho realmente tem fala.
```

### 20.4 no_transcript no burn

Sintoma:

```text
Este run nao tem transcricao disponivel.
```

Causa:

```text
skip_subtitles=false e nao existe transcript.srt/segments/text.
```

Acao:

```text
Transcrever ou salvar SRT.
Ou marcar "Sem legenda" para queimar so logo.
```

### 20.5 missing_audio_stream

Sintoma:

```text
O video nao possui faixa de audio.
```

Acao:

```text
Verificar o arquivo original.
Confirmar se a faixa de audio existe com ffprobe.
```

### 20.6 Audio muito grande em OpenAI

Sintoma:

```text
audio_too_large
```

Causa:

```text
OpenAI Whisper usa limite pratico de 25 MB por arquivo.
```

Acao:

```text
Usar local, premium, AssemblyAI ou OpenRouter STT.
```

### 20.7 Legenda fora de sincronia

Campo:

```text
burnSubDelay / sub_delay_secs
```

Uso:

```text
+0.5 atrasa a legenda meio segundo.
-0.5 adianta a legenda meio segundo.
```

### 20.8 Burn falha por video corrompido

O burn valida a midia antes do FFmpeg pesado. Se o video original estiver truncado/corrompido, o job pode falhar antes ou entrar em recuperacao dependendo do caso.

Mensagens relacionadas:

```text
source_media_corrupt
uploaded_media_invalid
Arquivo original corrompido
```

## 21. Recomendacoes operacionais para videos adultos

1. Nao usar idioma `auto` quando souber o idioma real. Para PT-BR, selecionar Portugues.
2. Comecar por `Auto estrito` quando o audio tiver muito gemido e pouca fala.
3. Usar `Premium` para fala baixa, mas revisar o SRT.
4. Usar `OpenRouter STT` como alternativa externa via `token:openrouter`.
5. Usar `AssemblyAI` quando quiser comparar outro ASR, mas revisar com cuidado.
6. Se o trecho tem so gemido/respiracao, o resultado correto pode ser pouca legenda ou legenda vazia.
7. Nunca confiar 100% em ASR para conteudo adulto; sempre revisar no editor SRT antes de queimar.
8. Preservar repeticoes reais: `vai vai vai`, `ai ai ai`, `hum hum hum` podem ser conteudo valido.
9. Usar o preview de fonte/cor/tamanho antes do burn.
10. Salvar o SRT antes de iniciar burn para garantir que o run persistiu a revisao.

## 22. Variaveis de ambiente relevantes

```text
OPENROUTER_STT_MODEL
ADULT_META_PREMIUM_NO_VAD_RESCUE
FFMPEG_BURN_THREADS
ADULT_META_MEDIA_ROOT
ADULT_META_MEDIA_TMP_ROOT
```

Tokens salvos em Settings:

```text
token:assemblyai
token:openrouter
token:openai
token:grok
```

Observacao:

```text
token:grok e usado em alguns fluxos LLM/traducao se configurado.
Transcricao pelo botao OpenRouter STT usa token:openrouter.
```

## 23. Exemplos de API

### 23.1 Transcrever com Premium

```bash
curl -X POST "https://metaporn.com.br/transcribe" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_KEY" \
  -d '{
    "video_object_key": "local:uploads/2026/05/12/video.mp4",
    "provider": "premium",
    "language": "pt-BR",
    "adult_mode": true,
    "include_vocalizations": true,
    "enhance_audio": true
  }'
```

### 23.2 Transcrever com OpenRouter STT

```bash
curl -X POST "https://metaporn.com.br/transcribe" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_KEY" \
  -d '{
    "video_object_key": "local:uploads/2026/05/12/video.mp4",
    "provider": "groq",
    "language": "pt-BR",
    "include_vocalizations": true,
    "enhance_audio": true
  }'
```

### 23.3 Salvar SRT editado

```bash
curl -X PUT "https://metaporn.com.br/runs/RUN_ID/transcript" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_KEY" \
  -d '{
    "transcript": {
      "srt": "1\n00:00:00,000 --> 00:00:02,000\nTexto revisado\n",
      "text": "Texto revisado",
      "segments": []
    }
  }'
```

### 23.4 Queimar legenda

```bash
curl -X POST "https://metaporn.com.br/api/burn-subtitles" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_KEY" \
  -d '{
    "run_id": "RUN_ID",
    "font_size": 22,
    "font_color": "white",
    "sub_delay_secs": 0,
    "output_crf": 26,
    "max_height": 1080,
    "x264_preset": "ultrafast"
  }'
```

## 24. Checklist antes de queimar legenda

```text
[ ] O run tem video_object_key valido.
[ ] O idioma falado esta correto.
[ ] A transcricao foi gerada pelo provider desejado.
[ ] O SRT foi revisado no editor.
[ ] O SRT foi salvo.
[ ] Tamanho/cor/delay foram conferidos no preview.
[ ] Logo(s), se usadas, foram revisadas no preview.
[ ] Resolucao/CRF/preset foram definidos.
[ ] Nao ha outro burn ativo para o mesmo run.
```

## 25. Pontos de manutencao futura

Melhorias recomendadas:

```text
Adicionar parser SRT mais tolerante a blocos sem indice.
Adicionar detector de idioma por segmento com biblioteca dedicada.
Adicionar diff visual entre SRT antes/depois da limpeza.
Adicionar modo "somente fala alta" vs "fala baixa" no frontend.
Adicionar geracao de relatorio por provider comparando quantidade de caracteres, segmentos removidos e motivos.
Adicionar opcao de exportar cleanup_meta junto com SRT.
Adicionar configuracao visual de Outline/Shadow/MarginV no preview e no burn.
```

## 26. Resumo tecnico rapido

```text
Formato canonico interno:
  transcript = { provider, lang, text, segments, srt, cleanup, provider_meta }

Formato de edicao:
  SRT no textarea transcriptSrtEdit

Formato de burn:
  SRT escrito em arquivo temporario legenda.srt
  FFmpeg subtitles filter + ASS force_style

Fonte da verdade por run:
  runs.request_json.transcript

Endpoint de salvamento:
  PUT /runs/{run_id}/transcript

Endpoint de download:
  GET /runs/{run_id}/srt

Endpoint de queima:
  POST /api/burn-subtitles
```
