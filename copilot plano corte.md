# Copilot Plano Corte

## Objetivo

Criar um pipeline profissional de geração de cortes verticais (Shorts/Reels) que use IA para detectar os melhores momentos do vídeo e evite a decisão manual de minutagem pelo usuário. O foco é reduzir o uso de servidor atual com processamento desnecessário e tornar a geração de cortes mais inteligente e automatizada.

## Problemas identificados no fluxo atual

- A função atual usa apenas detecção de cena com `ffmpeg`.
- O usuário escolhe `num_clips` e `clip_duration`, o que não faz sentido para uma solução de corte automático.
- A lógica de análise e renderização está misturada no mesmo worker.
- O servidor processa o vídeo inteiro em vez de usar uma etapa leve de seleção.
- Não há uso real de IA para decidir quais momentos são mais relevantes.

## Proposta de arquitetura

### 1) Separar o pipeline em etapas

1. Pré-processamento leve
2. Seleção de cortes com IA
3. Renderização final dos clipes

Essa separação melhora a manutenção e permite usar a API da OpenAI apenas na fase de decisão.

### 2) Pré-processamento leve no servidor

O backend deve executar apenas trabalhos baratos antes de chamar a IA:

- extrair metadados e duração do vídeo
- extrair áudio reduzido ou trechos chave
- detectar cenas e pontos de corte em baixa resolução
- gerar thumbnails ou frames representativos

Assim o servidor filtra candidatos antes de renderizar em alta qualidade.

### 3) Decisão de cortes com OpenAI

Usar um prompt estruturado que receba:

- lista de segmentos candidatos com start/end aproximado
- transcrição ou resumo do áudio/palavras importantes
- descrição do objetivo: Shorts/Reels, viralidade, diálogo, ação
- restrições de formato: duração ideal, máximos, evitar repetições

O modelo deve retornar:

- trechos selecionados com start/end em segundos
- duração de cada corte
- razão do corte (ex: punchline, reação, ação)
- recomendação de número ideal de cortes

### 4) Reduzir a responsabilidade do usuário

No front-end, mudar a experiência para:

- modo `Auto` ou `IA decide`
- `Máximo de cortes` em vez de `Nº de cortes` fixo
- remover ou tornar secundário o campo `Duração por corte`
- exibir apenas: `Gerar cortes automáticos` e `Usar preferência manual`

Isso evita que o humano escolha minutagem e deixa a IA comandar a seleção.

### 5) Reduzir carga no servidor

Melhorias de eficiência:

- usar cache de análise por `video_object_key`
- processar em baixa resolução e apenas frames chave
- renderizar somente os cortes aprovados pelo modelo
- evitar múltiplas execuções FFmpeg completas desnecessárias
- usar comando `trim` ou `concat` único quando possível

### 6) Fallback local / heurístico

Quando não houver token OpenAI disponível, manter um fallback com detecção local de cenas e heurísticas.

- modo manual: continues com escolha por cenas
- modo IA: usar OpenAI quando houver token configurado

## Implementação sugerida

### Backend

- novo módulo como `app/services/cortes_ai.py`
- função `analisar_cortes_candidates(video_path)` para gerar candidatos leves
- função `prompt_openai_para_escolher_cortes(...)`
- função `renderizar_cortes(cortes_selecionados, aspect, crf)`

### Front-end

- ajustar `CortesApp` em `app/os/apps-edit.jsx`
- adicionar opção de `Auto / Manual`
- `Max de cortes` em vez de `Nº de cortes`
- permitir estilo de corte: viral, essencial, conversa, ação

### API

- manter `/api/cortes/generate`
- aceitar novos parâmetros:
  - `auto_mode: true`
  - `max_clips`
  - `target_style`
  - `quality_profile`
- adicionar fases de status que indiquem:
  - `analisando`
  - `selecionando cortes`
  - `renderizando`

## Exemplo de prompt para OpenAI

> Você é um editor de shorts. Recebe um vídeo com falas e cenas visuais. Escolha os 4 a 8 melhores trechos para Reels/Shorts, cada um entre 8 e 22 segundos. Use apenas start/end em segundos. Priorize momentos com diálogo interessante, punchlines, reações visuais e ação forte. Não peça minutagem ao humano.

## Benefícios esperados

- cortes mais profissionais e relevantes
- menor dependência de heurísticas fixas
- menos carga de CPU e I/O no servidor
- melhor UX com menos parâmetros manuais
- pipeline modular e escalável

## Próximos passos

1. implementar a separação do worker de cortes
2. criar integração com OpenAI via `app/llm.py`
3. ajustar a UI para modo automático
4. adicionar cache de análise e redução de preload do vídeo
5. testar com vídeos reais e validar a qualidade dos cortes
