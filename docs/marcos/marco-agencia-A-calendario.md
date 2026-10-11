# Marco A — Agência automática: calendário editorial do mês (ideias + legendas)

**Versão:** v1.27.134 → v1.27.136 · **Plano:** `/root/.claude/plans/cara-esse-drive-das-bubbly-falcon.md`

## Objetivo do marco
Substituir a 1ª metade do trabalho da agência (Agência November): **planejar o mês do @cariap.com.br** com ~22 peças (14 posts, 6 carrosséis, 2 reels) com ideia, legenda pronta, hashtags e direção de arte/roteiro, e deixar o dono **aprovar/reprovar/refazer** cada ideia. A produção das artes e a publicação automática são o Marco B.

## O que mudou
- **Banco (`app/migrations.py`, migration 8):**
  - `editorial_plans` guarda o mês, o status (gerando/ideias/erro) e a config usada.
  - `editorial_items` guarda cada peça: data/hora, formato, pilar, produto, data comemorativa, título, ângulo, legenda, hashtags, direção de arte e etapa (`idea` / `idea_ok` / `idea_rejected`).
  - As ideias **não** viram posts. Assim não poluem Aprovação e Arquivos; o post só nasce com a arte (Marco B).
- **`app/services/agency.py`:**
  - `build_slots` monta, de forma determinística, os dias seg–sáb às 18h e espalha carrosséis e reels. Garante peça nas datas comemorativas e nos eventos cadastrados.
  - `month_dates` junta datas fixas e móveis (Carnaval, Mães, Pais, Black Friday, Dia da Internet Segura) de `app/services/datas_comemorativas.json` com os eventos da empresa.
  - A IA preenche os slots **em lotes de 6** (abaixo do timeout do provedor), usando:
    - uma cadeia de modelos configurável (`agency.models`). O padrão é `cx/gpt-5.5` (assinatura Codex, a melhor redação nos testes) → Sonnet → Opus, e por último `kie/claude-sonnet-4-6`, **pago em créditos kie**, a única conta com saldo;
    - o rodízio de produtos (máx. 2 por produto no mês);
    - cada lote só "vê" as datas dos próprios slots (evita repetir data em outro dia);
    - lista anti-repetição dos meses anteriores e fatos reais do catálogo.
  - Tolerância a 429 do provedor: espera progressiva. Se um lote falhar de vez, as peças dele entram vazias com "Refazer".
- **`app/routers/agency.py`** (`/api/agency/...`): config da agência por empresa, gerar mês (job em segundo plano, o front faz polling), ver/excluir calendário, aprovar todas, editar peça e refazer peça com comentário.
- **Config por empresa** (`creative_config.agency`, nada fixo no código): mix, horário, dias, pilares e pesos, CTA, WhatsApp, hashtags-base, estilo. A CARIAP recebeu pilares e estilo extraídos dos calendários da November (Educação SVA/tributário 35%, Produto 35%, Datas/Eventos 15%, Autoridade/Mercado 15%) e o WhatsApp comercial (11) 97445-1971.
- **App novo "Agência"** (`app/os/apps-agencia.jsx`, fixado na barra), com:
  - seletor de empresa, calendário e mês, e o botão "Gerar calendário";
  - contadores do mix e das aprovações, e a lista de datas do mês;
  - filtros e um card por peça: Aprovar, Reprovar com comentário, Refazer com instrução, e legenda, hashtags e arte editáveis.

## Como atinge o objetivo
O calendário sai no mesmo formato do PDF da November (data, formato, pilar, título, legenda com CTA e hashtags) e com mais volume (22 em vez de 15). O dono aprova as ideias antes de gastar qualquer centavo com arte.

## Testes feitos (produção, CARIAP, novembro/2026)
- Calendário com 22 peças (14 posts, 6 carrosséis, 2 reels) gerado em cerca de 2–3 min.
- Todos os apps do catálogo aparecem pelo menos uma vez. As datas (21/11 Dia da TV → Zapping, 22/11 Dia do Músico → Deezer, 27/11 Black Friday) caem só nos dias certos.
- Reels saem com 5 cenas e falas; carrosséis, com as telas listadas.
- "Aprovar" e "Refazer com instrução" foram testados pela tela. O refazer obedece a instrução e evita repetir o produto das peças vizinhas.
- Problemas encontrados e corrigidos durante o marco:
  - repetição de datas e produtos entre lotes;
  - cópia literal de títulos da November;
  - 429 e 500 do OmniRoute (Opus fora; Sonnet com limite) → cadeia de modelos com GPT-5.5 primeiro;
  - a mensagem "Montando…" não sumia ao terminar.

## Pendências para os próximos marcos
- **B:** produzir as artes das ideias aprovadas, aprovar a arte e agendar/publicar sozinho (Instagram da CARIAP precisa ser reconectado: conta Composio EXPIRED).
- **C:** visão de calendário mensal.
- **D:** geração automática no dia 20 + avisos por WhatsApp.
