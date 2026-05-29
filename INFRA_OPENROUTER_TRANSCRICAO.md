# Infraestrutura da Transcrição via OpenRouter STT

Documento técnico sobre a opção **OpenRouter STT** usada na plataforma MetaPorn para transcrição de vídeos adultos em português brasileiro.

## Resumo Executivo

A opção OpenRouter é hoje a que mais chega perto do vocabulário real de cenas adultas, especialmente em falas curtas, repetições, gemidos claros e dirty talk em português. O ponto fraco é estrutural: o fluxo atual recebe principalmente texto transcrito por chunk, não timestamps reais palavra-a-palavra. Por isso a sincronia é estimada e pode ficar distante do áudio real.

Outro problema importante: por ser um modelo de transcrição/IA permissivo e contextual, ele pode alucinar palavras quando o áudio tem gemido, respiração, música, ruído, fala baixa ou silêncio. Na prática, ele tenta “entender” o que ouviu e às vezes completa lacunas com texto inventado.

## Onde Fica no Código

Arquivos principais:

- `app/main.py`
- `app/ui/app.js`
- `app/ui/index.html`

Funções principais no backend:

- `_transcribe_openrouter_stt()`
- `_openrouter_stt_request()`
- `_split_audio_for_openrouter_stt()`
- `_clean_transcript_segments()`
- `_post_process_with_llm()`
- endpoint `POST /transcribe`

Botões principais no frontend:

- Na aba de criação, o botão **OpenRouter STT** chama `reTranscribe('groq')`.
- Apesar do nome histórico `groq`, hoje esse caminho usa `token:openrouter`.

## Fluxo Atual

1. O usuário clica em **OpenRouter STT** na etapa de legenda.
2. O frontend chama:

```http
POST /transcribe
```

com payload semelhante a:

```json
{
  "video_object_key": "local:uploads/...",
  "provider": "groq",
  "language": "pt",
  "adult_mode": true,
  "include_vocalizations": true,
  "enhance_audio": true
}
```

3. O backend resolve o vídeo no storage local/S3.
4. O áudio é extraído para WAV.
5. Se o áudio for longo ou grande, ele é dividido em chunks.
6. Cada chunk é enviado para:

```text
https://openrouter.ai/api/v1/audio/transcriptions
```

7. O modelo padrão atual é:

```text
openai/whisper-large-v3
```

Configurável por variável:

```text
OPENROUTER_STT_MODEL
```

8. O texto retornado é convertido em segmentos.
9. Como o OpenRouter STT não retorna timestamps reais confiáveis nesse fluxo, o sistema distribui o texto dentro da duração do chunk com timing sintético.
10. O resultado passa pela limpeza local anti-alucinação.
11. Em modo adulto/PT-BR, pode passar por pós-processamento LLM via Grok/OpenRouter.
12. O sistema gera `text`, `segments` e `srt`.

## Configurações Atuais

Token:

```text
token:openrouter
```

Fallback por ambiente:

```text
OPENROUTER_API_KEY
```

Modelo STT:

```text
OPENROUTER_STT_MODEL=openai/whisper-large-v3
```

Tamanho dos chunks:

```text
OPENROUTER_STT_CHUNK_SECONDS=120
```

Limites aplicados no código:

- mínimo: 60 segundos
- máximo: 300 segundos
- padrão: 120 segundos

Formato enviado:

- WAV
- mono
- 16 kHz
- PCM 16-bit
- base64 dentro de JSON

Headers enviados:

```http
Authorization: Bearer {token}
Content-Type: application/json
HTTP-Referer: https://metaporn.com.br/
X-Title: MetaPorn Admin
```

## Prompt Usado

Quando o idioma normalizado é `pt`, o backend envia o prompt adulto otimizado:

```text
PORN_BR_WHISPER_INITIAL_PROMPT
```

Esse prompt orienta o modelo a:

- manter português brasileiro;
- aceitar contexto adulto;
- preservar repetições reais;
- preservar gemidos claros quando configurado;
- evitar inglês inventado;
- evitar nomes aleatórios;
- não censurar dirty talk.

## Todos os Prompts Usados no Fluxo de Transcrição/OpenRouter

Esta seção lista os prompts e instruções reais relacionados à infraestrutura de transcrição. Alguns são usados diretamente pelo OpenRouter STT; outros são usados no pós-processamento LLM ou na tradução de legenda.

## Prompt 1 — Prompt Inicial do Whisper/OpenRouter STT

Nome no código:

```text
PORN_BR_WHISPER_INITIAL_PROMPT
```

Onde é usado:

- `_transcribe_local()`
- `_premium_vad_attempts()`
- `_transcribe_premium()`
- `_openrouter_stt_request()`, quando `language` normalizado é `pt`

Texto atual:

```text
Português brasileiro de putaria raiz, cena de sexo real amador ou profissional. Fala suja, gemidos altos e baixos, respiração pesada, tapa, repetições constantes e dirty talk explícito. Vocabulário esperado: ai ai ai, ahhh, aah, ah, hum hum hum, hmm, ui, oi, vai vai vai, isso isso isso, mete, mete forte, mete devagar, entra, mais fundo, goza, goza pra mim, me enche de leite, porra, caralho, buceta molhada, pau, pica grossa, cu, chupa gostoso, delícia, gostosa, safada, filha da puta, tesão, que delícia, que gostoso, me fode, squirt, creampie. Mantenha repetições reais, gemidos e fala baixa; não invente inglês, nomes ou spam.
```

Payload OpenRouter STT onde esse prompt entra:

```json
{
  "model": "openai/whisper-large-v3",
  "temperature": 0,
  "input_audio": {
    "data": "{audio_base64}",
    "format": "wav"
  },
  "language": "pt",
  "prompt": "Português brasileiro de putaria raiz, cena de sexo real amador ou profissional. Fala suja, gemidos altos e baixos, respiração pesada, tapa, repetições constantes e dirty talk explícito. Vocabulário esperado: ai ai ai, ahhh, aah, ah, hum hum hum, hmm, ui, oi, vai vai vai, isso isso isso, mete, mete forte, mete devagar, entra, mais fundo, goza, goza pra mim, me enche de leite, porra, caralho, buceta molhada, pau, pica grossa, cu, chupa gostoso, delícia, gostosa, safada, filha da puta, tesão, que delícia, que gostoso, me fode, squirt, creampie. Mantenha repetições reais, gemidos e fala baixa; não invente inglês, nomes ou spam."
}
```

Observação importante: esse campo `prompt` em modelos Whisper funciona mais como contexto anterior/vocabulário esperado do que como instrução rígida. Se o texto for muito instrucional, pode vazar para a legenda. Por isso ele precisa ser curto e direto.

## Prompt 2 — Prompt Padrão de Transcrição do Request

Nome no código:

```text
_default_transcribe_prompt()
```

Texto atual retornado:

```text

```

Ou seja: vazio.

Motivo técnico:

```text
Whisper prompt fields are previous-transcript context, not instructions. Long instructions leak into subtitles.
```

No endpoint `/transcribe`, o projeto também evita repassar `req.prompt` diretamente para o motor de transcrição:

```text
Whisper "prompt"/faster-whisper "initial_prompt" is previous transcript context, not a system instruction. Passing instructions here makes the model leak the prompt into subtitles, so we intentionally do not forward req.prompt to the transcription engine.
```

Esse ponto existe justamente por causa de bugs anteriores em que instruções como “Capture low-volume speech” apareciam repetidas na legenda.

## Prompt 3 — System Prompt do Pós-Processamento LLM

Nome no código:

```text
system_msg em _post_process_with_llm()
```

Providers tentados:

- xAI direto via `token:grok`
- OpenRouter via `token:openrouter`

Modelos atuais:

```text
grok-3-latest
grok-4.3
grok-4
grok-3-fast
x-ai/grok-4.3
x-ai/grok-3-fast
```

Texto atual:

```text
Você é revisor técnico de transcrição ASR para pornografia adulta explícita em português brasileiro. Sua única missão é limpar a transcrição mantendo o máximo possível de fala real, gemidos, repetições e dirty talk pesado. Remova SOMENTE alucinações claras do ASR: inglês inventado, spam de legenda, nomes aleatórios, frases impossíveis em silêncio/gemidos e lixo tipo 'Thank you Tommy', 'What's your password?', 'Hi Hi Hi', 'sadamsakumesama'. Mantenha TODO dirty talk, palavrão, termo sexual explícito, gemido escrito e repetição real como 'ai ai ai', 'vai vai vai', 'hum hum hum', 'isso isso', 'me enche de leite porra'. Não censure, não traduza, não suavize, não melhore gramática e não deixe linguagem corporativa. Se estiver em dúvida se é alucinação ou fala real de sexo, mantenha o texto original. Retorne somente JSON válido no formato {"segments":[{"index":0,"text":"..."}]}.
```

Função desse prompt:

- remover alucinações claras;
- não corrigir estilo;
- não transformar dirty talk em texto educado;
- não traduzir;
- manter repetições;
- preservar segmentos por índice.

## Prompt 4 — User Payload do Pós-Processamento LLM

Nome no código:

```text
user_msg em _post_process_with_llm()
```

Formato atual enviado ao modelo:

```json
{
  "language": "pt-BR",
  "adult_mode": true,
  "porn_context": true,
  "include_vocalizations": true,
  "quality": {},
  "segments": [
    {
      "index": 0,
      "start": 0.0,
      "end": 1.0,
      "text": "texto do segmento"
    }
  ],
  "rules": [
    "Mantenha exatamente o mesmo número de segmentos e índices.",
    "Para remover alucinação clara, retorne text vazio.",
    "Nunca altere timestamps.",
    "Remova apenas alucinações claras em inglês ou frases impossíveis.",
    "Mantenha toda putaria, repetições, gemidos e dirty talk original.",
    "Não traduza inglês real caso o trecho seja obviamente fala inglesa; mas se for frase clássica inventada em meio a PT-BR, remova.",
    "Se tiver dúvida, mantenha o texto original."
  ]
}
```

Observação: `include_vocalizations` varia conforme a opção marcada na interface. Em conteúdo adulto, normalmente fica `true`.

## Prompt 5 — Prompt de Tradução de Legendas

Nome no código:

```text
system_msg no fluxo de tradução de segmentos
```

Esse prompt só entra quando o usuário pede tradução (`translate_to`). Ele não é a transcrição principal, mas faz parte da infraestrutura de legenda.

Template atual:

```text
Você é tradutor especialista em legendas de pornografia adulta explícita. Você receberá segmentos separados pelo delimitador '|||SEG|||'. Traduza cada segmento de {idioma_origem} para {idioma_destino}, mantendo tom safado, natural, palavrões, gemidos, repetições e dirty talk. Não suavize, não censure e não use linguagem corporativa. Retorne APENAS os segmentos traduzidos separados pelo mesmo delimitador '|||SEG|||', na mesma ordem e quantidade exata. Sem explicação, sem bloco de código, sem tags de raciocínio.
```

User message da tradução:

```text
segmento 1|||SEG|||segmento 2|||SEG|||segmento 3
```

## Prompt 6 — Instruções Implícitas da Interface

Na interface, os botões e opções passam estas decisões para o backend:

```json
{
  "adult_mode": true,
  "include_vocalizations": true,
  "enhance_audio": true,
  "language": "pt"
}
```

Elas não são prompt textual, mas alteram o comportamento do pipeline:

- `adult_mode=true`: ativa limpeza/pós-processamento adulto em PT-BR.
- `include_vocalizations=true`: preserva gemidos claros e vocalizações.
- `enhance_audio=true`: tenta melhorar áudio de fala baixa antes de transcrever.
- `language=pt`: evita autodetecção viajando para inglês/espanhol.

## Prompt 7 — Frases Bloqueadas Como Vazamento de Prompt

A limpeza remove segmentos que contenham frases conhecidas de vazamento de prompt. Lista atual:

```text
capture low-volume speech
transcribe real spoken dialogue
transcribe only real spoken dialogue
do not invent subtitles
do not translate
without censorship or moralizing
adult/pornographic content
if speech is unclear
prefer portuguese, english or spanish
```

Essas frases não deveriam aparecer na legenda. Se aparecerem, são tratadas como `prompt_leak`.

## Prompt 8 — Spam Conhecido Removido

A limpeza também remove textos clássicos de legenda automática ou spam:

```text
subscribe
subtitles by
amara.org
se inscreva
inscreva-se
inscreva no canal
ative o sininho
deixe seu like
suscríbete
suscribete
subtítulos
subtitulado por
字幕
訂閱
подпис
```

Esses não são prompts enviados ao modelo, mas são padrões textuais usados como filtro anti-alucinação.

## Por Que o OpenRouter Chega Mais Perto

O OpenRouter STT com Whisper grande tende a reconhecer melhor:

- palavras explícitas;
- repetições comuns de cena adulta;
- frases curtas;
- fala emocional;
- vocabulário que outros providers filtram, suavizam ou ignoram.

Por isso ele parece melhor em conteúdo adulto do que opções mais conservadoras.

## Por Que Ainda Alucina

Ele alucina por alguns motivos:

1. O áudio adulto tem muita informação não verbal: gemido, respiração, impacto, música e ruído.
2. Muitas falas são baixas, cortadas ou sobrepostas.
3. O modelo tenta transformar som ambíguo em texto.
4. O prompt adulto ajuda no vocabulário, mas também aumenta a tendência de preencher lacunas com termos esperados.
5. Quando o chunk é longo, o modelo pode criar uma narrativa aproximada em vez de transcrever só o que foi dito.
6. Sem timestamps reais por palavra, fica mais difícil detectar onde houve invenção.

Exemplos típicos de alucinação:

- inglês aleatório;
- nomes inexistentes;
- frases completas em trechos onde só havia gemido;
- tradução automática misturada com português;
- palavras sem relação com a cena;
- repetição artificial que não estava no áudio.

## Problema Principal de Sincronia

O OpenRouter STT atual retorna texto, mas não retorna timestamps reais palavra-a-palavra no formato que o sistema precisa para legenda queimável precisa.

Por isso o backend usa:

```text
timing_source = synthetic_openrouter_chunk
```

Isso significa:

- o texto é espalhado dentro da duração do chunk;
- a legenda pode começar antes ou depois da fala real;
- pausas longas podem virar legenda “correndo”;
- falas de 30 segundos podem aparecer em outro ponto do vídeo;
- a queima da legenda pode parecer fixa, atrasada ou adiantada.

Conclusão honesta: **OpenRouter é bom para conteúdo textual, mas não é o melhor para sincronia final de SRT queimado** no estado atual.

## Campos de Diagnóstico no Retorno

Quando OpenRouter é usado, o backend preenche `provider_meta` com:

```json
{
  "openrouter_stt_model": "openai/whisper-large-v3",
  "openrouter_stt_chunks": 10,
  "openrouter_stt_chunk_fail_count": 0,
  "openrouter_stt_chunk_empty_count": 0,
  "openrouter_stt_attempts": [],
  "timing_quality": "synthetic_openrouter_chunk",
  "burn_safe": false,
  "timing_warning": "..."
}
```

Esses campos servem para saber se a legenda veio de chunks sintéticos e se é segura para queima direta.

## Limpeza Anti-Alucinação

Depois da transcrição, o sistema passa por:

```text
_clean_transcript_segments()
```

Essa etapa tenta remover:

- idioma incorreto;
- inglês inventado;
- frases impossíveis;
- spam textual;
- segmentos vazios;
- alucinações muito evidentes.

Em seguida, quando `adult_mode=true` e idioma `pt`, pode rodar:

```text
_post_process_with_llm()
```

Hoje esse pós-processamento tenta usar:

- `token:grok` direto na xAI, se existir;
- `token:openrouter` com modelo Grok via OpenRouter, se necessário.

Modelo atual de pós-processamento via OpenRouter:

```text
x-ai/grok-4.3
```

Importante: o pós-processamento deve corrigir e remover alucinações claras, mas não deve inventar falas novas.

## Pontos Fortes

- Melhor vocabulário adulto que providers muito conservadores.
- Menor censura.
- Boa tolerância a dirty talk explícito.
- Usa token OpenRouter já configurável no painel.
- Pode funcionar em servidor CPU-only porque o processamento pesado roda fora.
- Divide áudio longo em chunks para reduzir falhas por tamanho.
- Faz retry de chunks grandes em subchunks de 60s quando há erro ou vazio.

## Pontos Fracos

- Timestamps são estimados.
- Não é ideal para queima final sem revisão.
- Pode alucinar em ruído, silêncio, gemido e música.
- Pode misturar português, inglês e espanhol.
- Pode inventar palavras quando há fala baixa.
- Pode perder falas curtas se o chunk tiver muito ruído.
- Pode gerar legenda textual aceitável, mas ruim para sincronização.

## Quando Usar

Use OpenRouter STT quando o objetivo for:

- obter a melhor leitura textual aproximada;
- recuperar vocabulário adulto que outros modelos recusam;
- gerar uma primeira versão para revisão manual;
- comparar com Whisper Sync ou Deepgram.

Evite usar OpenRouter STT sozinho quando o objetivo for:

- queimar legenda final sem revisar;
- exigir sincronia precisa;
- validar fala palavra por palavra;
- gerar legenda profissional sem ajuste.

## Recomendação Operacional Atual

Fluxo recomendado para legenda final:

1. Gerar transcrição com **OpenRouter STT** para capturar vocabulário.
2. Gerar transcrição com **Whisper Sync** ou **Deepgram Sync** para capturar tempo real.
3. Usar o texto do OpenRouter como referência textual.
4. Usar os timestamps do provider com sincronização real.
5. Revisar em preview curto antes de queimar o vídeo completo.

## Plano Para Melhorar de Verdade

### 1. Separar texto bom de tempo bom

OpenRouter deve ser tratado como provider de texto, não como fonte definitiva de tempo.

Implementar um alinhador:

```text
OpenRouter texto bom + Whisper/Deepgram timestamps reais = SRT final
```

### 2. Criar alinhamento forçado

Possíveis caminhos:

- WhisperX se houver ambiente compatível;
- Montreal Forced Aligner;
- aeneas;
- Gentle;
- pipeline próprio usando segmentos curtos + VAD.

Para servidor CPU-only, a opção mais realista é um alinhamento por frases/segmentos curtos, não palavra-a-palavra perfeito.

### 3. Reduzir chunk para cenas adultas

Chunks longos aumentam alucinação. Para conteúdo adulto, testar:

```text
OPENROUTER_STT_CHUNK_SECONDS=60
```

Isso tende a:

- reduzir invenção contextual;
- melhorar localização aproximada;
- aumentar chamadas/custo;
- aumentar tempo total.

### 4. Adicionar detector de alucinação por densidade

Criar score por segmento:

- caracteres por segundo;
- presença de inglês inesperado;
- nomes próprios aleatórios;
- repetição artificial;
- texto em trecho sem energia de voz;
- divergência contra VAD.

Segmentos suspeitos devem ir para revisão, não direto para queima.

### 5. Criar modo “OpenRouter Conservador”

Esse modo deve pedir ao modelo:

- não preencher silêncio;
- retornar vazio quando não houver fala clara;
- preservar gemidos apenas quando audíveis;
- não traduzir;
- não completar frases.

### 6. Criar preview de legenda por minuto

Antes de gastar horas queimando, a plataforma deve permitir:

- escolher minuto inicial;
- gerar preview de 30s a 60s;
- verificar texto, tamanho, posição e sincronia;
- aprovar antes do burn completo.

## Variáveis Recomendadas Para Teste

Mais conservador:

```text
OPENROUTER_STT_CHUNK_SECONDS=60
OPENROUTER_STT_MODEL=openai/whisper-large-v3
OPENROUTER_TRANSCRIPT_POST_MODEL=x-ai/grok-4.3
```

Mais rápido:

```text
OPENROUTER_STT_CHUNK_SECONDS=180
```

Mais seguro para queima:

```text
Usar Whisper Sync ou Deepgram Sync para timestamps.
Usar OpenRouter apenas como referência textual.
```

## Diagnóstico Final

A opção OpenRouter não está “errada”; ela está sendo usada para duas tarefas diferentes:

1. entender o conteúdo adulto;
2. gerar legenda sincronizada.

Ela é boa na primeira e fraca na segunda.

O caminho correto é transformar OpenRouter em motor de texto e combinar com um motor/alinhador de tempo. Enquanto isso não existir, qualquer SRT do OpenRouter deve ser tratado como **rascunho forte de texto**, não como legenda final pronta para queimar.
