# Marcos B, C e D — Agência automática: artes, calendário do mês, piloto automático e multi-cliente

**Versões:** v1.27.144 → v1.27.147 · continuação do `marco-agencia-A-calendario.md`

## O que entrega
- **B (artes + agendamento):**
  - "Gerar artes (N)" produz em segundo plano a arte de cada ideia aprovada, pelo mesmo caminho da tela Conteúdo: `generate-briefing` → Estúdio IA (`render-carousel`, `reference_full`). Carrossel sai com várias telas; post com 1; reels com a capa 9:16.
  - A capa usa o título aprovado e a legenda aprovada substitui a gerada.
  - Por peça: "Aprovar e agendar", "Refazer arte" com instrução, "Reprovar arte".
  - Ao aprovar, o post vira APPROVED com a data do calendário e cria o agendamento social; o cron `social_publish_scheduled` publica. Sem Instagram conectado, a peça fica "Arte aprovada — aguardando o Instagram" e o tick agenda sozinho quando a conta conectar.
- **C (visão de mês):** grade do mês com as peças por dia, miniatura da arte, cor por formato e datas comemorativas; clicar leva ao card.
- **D (piloto automático):**
  - Job `agency_monthly` (09h de Brasília) gera o calendário do mês seguinte no dia configurado (padrão 20) para cada cliente com a agência ligada e avisa no WhatsApp.
  - Job `agency_tick` (a cada 3 min):
    - retoma a fila de artes depois de um reinício;
    - agenda as aprovadas e sincroniza publicado/falhou, avisando no WhatsApp;
    - manda lembrete de arte pendente a 48h da data;
    - marca como "pulada" a peça que passou da data sem aprovação, nunca publicada sem OK.
- **Multi-cliente (pedido: "não só CARIAP, qualquer cliente registrado"):**
  - Painel "Clientes da agência" com o estado do mês de cada cliente, respeitando o escopo de cada usuário.
  - "Configurar agência do cliente": piloto, dia, WhatsApp de avisos, volume por formato, horário, dias, pilares e pesos, CTA, WhatsApp comercial, hashtags, estilo, e botão "Sugerir com IA".
  - No 1º calendário de um cliente sem linha editorial, a IA monta pilares, estilo, CTA e hashtags sob medida a partir do cadastro (`ensure_tailored_config`, dentro do job). Testado com a V8 Fibra (B2C): pilares próprios e conteúdo para o consumidor.
  - O app não abre mais na CARIAP: lembra o último cliente escolhido.

## Correções feitas no caminho
- **Revisor de acentuação central** (`fix_accents_telas` em `ai.py`, aplicado no `generate-briefing`): alguns modelos devolviam PT sem acento e a arte copiava. Corrige só os acentos e confere que nenhuma outra letra mudou.
- **Modelos de texto:**
  - a conta Codex não aceita mais `gpt-5.5` (400) → cadeias usam `cx/gpt-5.6-sol` / `cx/gpt-5.6-luna`;
  - o `antigravity/claude-sonnet-4-6` vive em 429; o `cc/claude-sonnet-4-6` devolve resposta vazia → o transbordo trata 400 e vazio como falha;
  - o modelo rápido do OmniRoute passou a ser `cx/gpt-5.6-sol`.
- O gerador de telas às vezes devolve JSON quebrado → a produção tenta 3 vezes.

## Testes (produção)
- **CARIAP:** 2 ideias aprovadas → "Gerar artes".
  - Post pronto em ~3 min.
  - Carrossel de 6 telas em ~9 min, depois da correção de novas tentativas. Tudo pelo Luna (assinatura, R$ 0).
  - "Aprovar e agendar" criou o agendamento social certo (02/11 18:00 −03:00). **Cancelado em seguida**: a CARIAP não vai usar e a conexão dela consta como ativa.
- **V8 Fibra:** linha editorial sob medida criada sozinha; calendário de 22 peças em 4min37, nenhuma vazia.
- **Tick e painel:** tick pela API ok; painel multi-cliente na tela ok.

## Pendente
- Conectar o Instagram de cada cliente que for publicar (ação do usuário).
- Avisos no WhatsApp só saem com "WhatsApp para avisos" preenchido na configuração do cliente.
