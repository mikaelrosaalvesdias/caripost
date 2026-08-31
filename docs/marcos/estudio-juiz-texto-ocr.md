# Estúdio IA — Juiz de Texto OCR (v1.27.92 → v1.27.96)

## v1.27.96 — logo de produto nunca mais de memória

Feedback do teste do usuário (Gironetfibra): texto perfeito, arte linda, mas o **Deezer saiu com a
identidade ANTIGA** (barras coloridas) em vez da cadastrada (coração roxo). Duas causas em
`posts.py` (bloco reference_full):

1. Só a logo de UM produto era anexada (`break` no primeiro match — ExitLag ganhou, Deezer ficou fora).
2. Pro caminho kie (default `kie:chatgpt/gpt-5.4-image-2`), as referências vão por **URL pública**
   (`_ref_urls`) — e a logo de produto ia só em **bytes** (`_refs`): o modelo NUNCA a viu e desenhou
   de memória.

Fix: TODOS os produtos citados na tela (app + título + texto + CTA; cap 3; produto da própria empresa
vence o do catálogo comum) entram em bytes E em URL pública, cada um com instrução NOMEADA: "logo
OFICIAL ATUAL de {produto} — PROIBIDO desenhar de memória ou usar versão antiga".

---


## v1.27.95 — validação em prod + refinamentos do teste real

**O teste real da v1.27.94 provou o sistema funcionando de ponta a ponta**: o juiz pegou a arte
quebrada na 1ª tentativa ("garantida, seguranca, entretenimento"), regenerou com correção soletrada,
o modelo (nano-banana-edit) falhou 3/3, e a entrega saiu COM aviso honesto no `warning` ("texto pode
ter erro — clique regerar"). Nunca mais quebra silenciosa. Dois refinamentos a partir do teste:

1. **Candidato fraco não condena** (`_ocr_crop_confirm`): "garantida" estava pintada CERTA, mas o OCR
   não a leu (laranja sobre fundo quente = contraste baixo em cinza) e o recorte de um token errado
   cravava "broken" — falso positivo que poluía o feedback dos retries. Agora só candidato FORTE
   (ratio ≥0.7 = versão mutilada da palavra) pode condenar; sem candidato forte → "unknown" → visão.
2. **Passes por canal de cor (R/B)** no `_ocr_scan`: no canal azul o laranja fica preto — recupera
   texto colorido que o cinza perde.

**Modelo**: `image_ref.model` trocado para `kie:chatgpt/gpt-5.4-image-2` (nano-banana-edit foi 0/3
em subtítulo denso pt-BR; gpt-5.4-image-2 é o modelo historicamente validado em texto/acentos pt-BR
no Estúdio). Reversível no painel admin (Motor de arte — Estúdio IA).

---


## v1.27.94 — arbitragem DETERMINÍSTICA por recorte (a lição final)

O teste real da v1.27.93 quebrou de novo ("Famâlia", "garant da", "entrentenimento") e o juiz passou.
Autópsia: **a visão (Haiku) auto-corrige o typo ATÉ soletrando letra a letra** — pintado "Famâlia",
soletrou "F-a-m-í-l-i-a". Lição de arquitetura: **LLM nunca pode ser o árbitro que APROVA texto.**

Juiz v3 (o definitivo):

1. **OCR multi-passe** (`_ocr_scan`): cinza + invertido + binarizado 150/200 (± invertido) + upscale.
   A binarização matou a cegueira em texto branco sobre pílula colorida (o "Saiba mais").
2. **Palavra suspeita → arbitragem POR RECORTE** (`_ocr_crop_confirm`, sem IA): o token do OCR mais
   parecido dá a CAIXA da palavra na arte → recorta com folga, amplia 4×, relê com Tesseract (psm 7/6,
   2 polaridades). Releu exata = ruído de leitura → passa. Continua diferente = pintada errada → REPROVA.
3. **Visão rebaixada a 3ª instância**: só palavra que o OCR NEM VIU (região estilizada); prompt
   endurecido ("teste de erro de pintura — copiar o erro é a resposta certa"); indisponível → falha
   fechada (conta como quebra).

Validação contra as DUAS artes reais quebradas de produção: ambas reprovadas com as palavras exatas,
custo de visão ZERO (100% local, ~40s de CPU em arte quebrada, ~6s em arte limpa).

Nota de escopo: acento AUSENTE puro ("familia" sem acento) ainda passa — a comparação é por letra-base
(ascii), porque o OCR não lê acento de forma confiável (mesmo passe lê "Famalia" e "Famália"). Acento
TROCADO que muda a letra-base ("Famâlia" → famalia ≠ familia) é pego. Logo redesenhada pelo modelo
(ex.: "PROVEDOD DR INTERNET" na Gironetfibra) está fora do juiz de texto (não há texto esperado da logo).

---


## v1.27.93 — calibração com arte REAL de produção (o fuzzy caiu)

O primeiro teste real (CARIAP, post fixo, Estúdio) entregou arte com "Segurença", "entrenitemento"
e "portôflio" — e o juiz v1.27.92 APROVOU. Autópsia (reproduzida localmente com a arte real):

- O OCR **leu as três quebras perfeitamente** ("segurenca", "entrenitemento", "portoflio").
- O fuzzy ≥0.8 perdoou as três: erro PINTADO de 1 letra dá similaridade 0.857–0.889 — a MESMA faixa
  do ruído de leitura do OCR. **Similaridade não separa os dois.** (Confirmado também na arte da
  Gironetfibra: "bacio" vs "baixo" = exatamente 0.80.)
- A única suspeita ("saiba", que o OCR não leu na pílula) foi pra transcrição livre da visão — que
  **auto-corrige typo ao ler** — e o juiz passou a arte limpa, sem aviso.

Correção (v1.27.93):

1. **Fuzzy de aprovação REMOVIDO** — só match exato (no fluxo contínuo) aprova no OCR.
2. **Arbitragem letra-a-letra** (`vision_spell_words`): palavra suspeita → a visão copia como ela
   está PINTADA, letra por letra, e o **código** compara. Auto-correção não engana mais.
3. **FALHA FECHADA**: visão indisponível/recusou → suspeita conta como QUEBRA e regenera. O juiz
   nunca aprova às cegas.
4. **Rodapé julgado**: o contato exigido no prompt (CTA/post único) entra no `_expect` — telefone/
   site pintado errado também reprova.

Validação: contra a arte real quebrada, o juiz v2 pega as 3 quebras, inocenta "saiba" (pintada
certa, OCR que não leu) e mantém custo 0 em arte correta.

---

# Histórico v1.27.92 (baseline)

## O problema real (por que arte quebrada estava passando)

O usuário estava certo: **não era "limite dos modelos", era buraco de engenharia**. Dois bugs no juiz antigo:

1. **Juiz cego** (`app/services/ai.py`, `text_render_issues`): o juiz dependia SÓ de IA de visão
   (`vision_read_text`). Quando a visão recusava a arte (conteúdo adulto) ou ficava sem saldo (402),
   devolvia `""` → `text_render_issues("")` retornava `[]` → **arte quebrada era APROVADA**.
2. **Tolerância errada** (`app/routers/posts.py`, loop do reference_full): `if len(_miss) < 2` —
   **1 palavra quebrada passava**. "bawo" no lugar de "baixo" era aprovado de fábrica.

## A solução (criatividade intacta — a IA segue desenhando TUDO)

### 1ª instância: OCR local — `ocr_read_text()` em `app/services/ai.py`
- Tesseract (por+eng) rodando NO container: grátis, determinístico, **nunca recusa, nunca fica sem saldo**.
- Multi-passe (cinza + invertido + upscale 2x) porque o texto vem sobre foto; junta os tokens de todos
  os passes (o juiz só checa presença).

### 2ª instância: visão — `judge_art_text()` em `app/services/ai.py`
- OCR aprovou → acabou (custo 0, caso comum).
- OCR desconfiou → a visão confirma (paga centavos SÓ na suspeita). Palavra quebrada DE VERDADE
  reprova nos dois; divergência = ruído de leitura → passa (não queima crédito regenerando arte boa).
- Um leitor indisponível → o outro decide sozinho. **O juiz nunca mais fica cego.**

### Leitura fuzzy — `text_render_issues()` reescrito
- Palavra presente se: aparece no fluxo contínuo sem espaços (cobre "bai xo" dividido pelo leitor)
  OU similaridade ≥0.8 com um token ("balxo" lido = ruído de OCR, passa; "bawo" desenhado = quebra
  real, reprova — ratio 0.67).

### Tolerância ZERO + retry com correção soletrada — `app/routers/posts.py`
- `if not _miss` — **qualquer** palavra quebrada reprova e regenera (antes: `< 2`).
- `text_fix_feedback()` injeta no prompt do retry a palavra errada na grafia ORIGINAL, soletrada:
  `«baixo» (soletrando: B-A-I-X-O)` — a regeração **converge no erro** em vez de jogar moeda de novo.
- 3 tentativas; todas quebraram → entrega a menos ruim COM aviso "clique regerar" (nunca trava o lote).

## Custo
- Caso comum (texto saiu certo): **+0 crédito, +0 chamada de IA** (OCR local aprova sozinho).
- Suspeita: 1 chamada de visão (~$0.004). Regeração só quando o texto REALMENTE quebrou — que é
  exatamente o que o usuário quer pagar pra não receber.

## Infra
- `Dockerfile`: `tesseract-ocr` + `tesseract-ocr-por`; `requirements.txt`: `pytesseract`.
- `eaf_base_api==3.3.2` pinado (3.3.4 removeu `setup_logger` e derrubava o boot — achado no deploy).

## Testado (antes de pedir teste)
- `py_compile` OK; golden `regressao_check.py` OK antes e depois (nada das telas aprovadas mudou).
- Teste funcional local (PIL, sem IA, grátis): arte com "baixo" → juiz aprova (custo 0); arte com
  "bawo" → juiz pega `['baixo']` e o feedback soletra B-A-I-X-O; "balxo" (ruído de leitura) → passa.
- Container 1.27.92 no ar: `tesseract 5.5.0` com `por`, funções do juiz importam, API `1.27.92`,
  `os/index.html?v=12792` servindo.

## Como testar (só o que ESTA entrega cobre)
1. Estúdio IA → gerar um post/carrossel normal (mesmo fluxo de sempre).
2. Avaliar UMA coisa: **o texto das artes entregues está escrito certo** (sem palavra quebrada tipo
   "bawo"). Se alguma tela vier com aviso "texto pode ter erro (…) — clique regerar", é o juiz sendo
   honesto após 3 tentativas — regere essa tela.
3. NÃO avaliar aqui: beleza/layout/família visual — isso não mudou nesta entrega.

## Follow-up conhecido (não incluído)
- Endpoint de EDIÇÃO de arte (`/edit`, posts.py:1019) ainda sem juiz — a instrução do usuário pode
  legitimamente mudar o texto, então precisa de heurística própria (comparar OCR fonte × editado
  só nas palavras que a instrução não menciona).
