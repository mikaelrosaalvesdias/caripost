# MetaPorn - Prompts Otimizados para Transcricao de Conteudo Adulto

**Versao operacional aplicada**
**Data:** 15 de maio de 2026
**Objetivo:** Maximizar qualidade de transcricao em videos adultos brasileiros com fala baixa, repeticoes, vocalizacoes, dirty talk e ruido de fundo ocasional em servidor CPU-only.

## 1. Objetivo Geral

Criar um pipeline de transcrição que:

- Reduza drasticamente alucinações em inglês, como "Thank you Tommy", "What's your password?", "Hi Hi Hi".
- Preserve ao maximo vocalizacoes, repeticoes reais e dirty talk.
- Mantenha timestamps precisos.
- Use faster-whisper local em CPU/int8 e pós-processamento Grok-3 via `token:grok`.

## 2. Prompt do faster-whisper premium

Usado em: `_transcribe_premium()`

Observação técnica: este prompt fica propositalmente só como contexto/vocabulário. Não colocamos JSON, persona longa nem regras de resposta dentro do `initial_prompt`, porque Whisper pode vazar instruções como legenda.

```text
Português brasileiro de putaria raiz, cena de sexo real amador ou profissional. Fala suja, gemidos altos e baixos, respiração pesada, tapa, repetições constantes e dirty talk explícito. Vocabulário esperado: ai ai ai, ahhh, aah, ah, hum hum hum, hmm, ui, oi, vai vai vai, isso isso isso, mete, mete forte, mete devagar, entra, mais fundo, goza, goza pra mim, me enche de leite, porra, caralho, buceta molhada, pau, pica grossa, cu, chupa gostoso, delícia, gostosa, safada, filha da puta, tesão, que delícia, que gostoso, me fode, squirt, creampie. Mantenha repetições reais, gemidos e fala baixa; não invente inglês, nomes ou spam.
```

## 3. Prompt system do Grok-3 para pós-processamento

Usado em: `_post_process_with_llm()`

Objetivo: limpar alucinacoes claras sem traduzir, censurar, suavizar ou reescrever conteudo sexual real.

```text
Você é revisor técnico de transcrição ASR para pornografia adulta explícita em português brasileiro. Sua única missão é limpar a transcrição mantendo o máximo possível de fala real, gemidos, repetições e dirty talk pesado. Remova SOMENTE alucinações claras do ASR: inglês inventado, spam de legenda, nomes aleatórios, frases impossíveis em silêncio/gemidos e lixo tipo 'Thank you Tommy', 'What's your password?', 'Hi Hi Hi', 'sadamsakumesama'. Mantenha TODO dirty talk, palavrão, termo sexual explícito, gemido escrito e repetição real como 'ai ai ai', 'vai vai vai', 'hum hum hum', 'isso isso', 'me enche de leite porra'. Não censure, não traduza, não suavize, não melhore gramática e não deixe linguagem corporativa. Se estiver em dúvida se é alucinação ou fala real de sexo, mantenha o texto original. Retorne somente JSON válido no formato {"segments":[{"index":0,"text":"..."}]}.
```

## 4. Payload enviado ao Grok-3

Usado em: `_post_process_with_llm()`

Objetivo: enviar os segmentos com timestamps e regras rígidas para manter contagem, ordem e sincronização.

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
      "text": "texto original do segmento"
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

## 5. Prompt opcional de tradução de legenda

Usado em: `_translate_segments_llm()`

Objetivo: traduzir legendas quando o usuário pedir tradução, mantendo tom explícito e natural.

```text
Você é tradutor especialista em legendas de pornografia adulta explícita. Você receberá segmentos separados pelo delimitador '|||SEG|||'. Traduza cada segmento de {source_lang} para {target_lang}, mantendo tom safado, natural, palavrões, gemidos, repetições e dirty talk. Não suavize, não censure e não use linguagem corporativa. Retorne APENAS os segmentos traduzidos separados pelo mesmo delimitador '|||SEG|||', na mesma ordem e quantidade exata. Sem explicação.
```

## 6. Configuração aplicada no pipeline

- Modelo premium: `large-v3` por padrão neste servidor, com suporte a `large-v3-turbo` via `ADULT_META_PREMIUM_WHISPER_MODEL`.
- Device: CPU.
- Compute type: `int8`.
- `language="pt"`.
- `condition_on_previous_text=False`.
- `word_timestamps=True`.
- VAD ativo com `threshold` entre `0.35` e `0.40`, conforme tentativa.
- Fluxo: transcrição -> limpeza local -> pós-processamento Grok-3 -> limpeza local final -> SRT/segments.

## 7. Observações técnicas

- AssemblyAI e OpenRouter STT não usam prompt textual próprio neste projeto; recebem áudio, idioma e parâmetros.
- O prompt do Whisper local padrão continua vazio de propósito, porque prompts longos podem vazar como texto da legenda.
- O pós-processamento Grok é conservador: se houver dúvida, mantém o segmento original.
- Logs do pós-processamento mostram `status`, `model`, `removed`, `changed` e `reason`.
