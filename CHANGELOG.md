# Changelog

Todas as mudancas relevantes deste projeto devem ser registradas aqui e tambem no `CHANGELOG` interno em `app/ui/app.js` quando forem visiveis no app.

## v1.27.111 - 2026-07-30

- **fix(clientes): identidade institucional separada de produtos/parceiros.** O importador agora ranqueia candidatos por nome da empresa, cabecalho e marcadores de marca; logos de ESPN, Premiere, HBO e outras ofertas exibidas no site sao rejeitadas. Assets WEB antigos sem evidencia institucional sao removidos no proximo enriquecimento, e suas cores nao contaminam mais a paleta oficial.
- **feat(clientes): referencias viraram perfil visual.** Uploads de artes extraem paleta auxiliar, composicao, tipografia e posicao recorrente da assinatura institucional. O Estudio recebe esse perfil como direcao de layout/estilo, sem permitir que ele substitua a logo ou a paleta oficial.
- **feat(clientes): enriquecimento automatico completo.** Site, Instagram e Facebook agora disparam a montagem de identidade tanto no cadastro quanto quando qualquer uma dessas fontes e adicionada ou alterada depois.
- **fix(clientes): todas as variantes institucionais.** A foto de perfil do Instagram pode ser salva como variante mesmo quando o site ja forneceu uma logo, sem duplicar a origem em novos enriquecimentos.
- Versao: main.py/UI/OS 1.27.111, cache bust `app.js?v=127111` e OS `v=127111`.

## v1.27.110 - 2026-07-29

- **fix(clientes): logo em 2 VERSOES — transparente (primaria) + fundo do site.** A captura via Playwright saia com o fundo da pagina colado e era versao unica. Agora: CSS zera os fundos → screenshot com ALFA real (descartado se sair vazio, ex.: logo por CSS-background) + a versao no fundo original; as duas viram assets de logo (o Estudio ja escolhe entre variantes).
- Versao: main.py 1.27.110 (backend-only).

## v1.27.109 - 2026-07-29

- **feat(clientes): BOTAO "⬇ Puxar do site AGORA"** em destaque na tela do cliente (acima da Analise automatica): le o site e preenche cores, voz, segmento, LOGO e planos (~1 min), com feedback de progresso e aviso quando o proxy corta antes do fim (processo segue no servidor). O automatico do cadastro continua; o botao e o plano B visivel.
- Versao: main.py 1.27.109, OS cache bust v=127109.

## v1.27.108 - 2026-07-29

- **feat(clientes): enrich automatico TAMBEM no update.** Site adicionado DEPOIS do cadastro (perfil ainda vazio) → monta sozinho, igual ao create. Perfil ja preenchido nunca e sobrescrito pelo robo. Zero botao em qualquer caminho.
- Versao: main.py 1.27.108 (backend-only).

## v1.27.107 - 2026-07-29

- **fix(clientes): logo sem corte** — recorte da pagina com FOLGA (30% da altura + margem) em vez do screenshot seco do elemento; o wordmark que vazava do box nao e mais clipado.
- Versao: main.py 1.27.107 (backend-only).

## v1.27.106 - 2026-07-29

- **fix(clientes): logo capturada NITIDA e inteira.** Screenshot em 3x (device_scale_factor) + prioriza o CONTAINER da logo (icone+texto completos, com trava anti-wrapper gigante) — a 1ª captura da kpsfibra saiu 42px e cortada.
- Versao: main.py 1.27.106 (backend-only).

## v1.27.105 - 2026-07-29

- **feat(clientes): AUTO-ENRICH no cadastro.** Empresa criada com site → o perfil (cores, voz, LOGO, planos) monta SOZINHO em background (~30-60s), sem cacar o botao "Puxar do site" em outra aba. Botao continua para re-puxar. (Caso real: kpsfibra cadastrada e nada preenchido — o botao visivel era o de Instagram/estrategia, que bate na parede de login do IG.)
- **fix(clientes): logo SVG INLINE capturada.** Site sem `<img>` de logo (logo desenhada em `<svg>` no header — caso kpsfibra) → Playwright fotografa o ELEMENTO (`[class*=logo] svg`, `header svg`) e vira PNG transparente. Antes: 0 logos mesmo com enrich funcionando.
- Versao: main.py 1.27.105 (backend-only).

## v1.27.104 - 2026-07-29

- **fix(kie): ledger movido pro volume /data.** O varredor de temporarios de `/media/_tmp` APAGOU o ledger de taskIds (flagrado em prod: arquivo sumiu minutos depois de criado). Agora grava em `/data/kie_tasks.jsonl` (junto do runs.db, ninguem varre). Resgate validado ao vivo: arte "Menos ping. Mais vitoria." recuperada por taskId e salva no Acervo.
- Versao: main.py/UI 1.27.104, cache bust `app.js?v=127104`.

## v1.27.103 - 2026-07-29

- **fix(kie): arte pronta volta imediatamente para a plataforma.** O parser aceita `resultJson` serializado, URL unica e resultados aninhados em `response`/`output`; polling tolera oscilacao curta e uma tarefa concluida sem URL termina com erro claro.
- **fix(video): modelo confirmado = modelo usado.** Front envia o modelo em cada preflight/geracao; backend resolve uma configuracao por request e a congela para criacao, polling e download de todas as cenas. O motor `veo3_fast` fixo deixou de ser o default oculto.
- **fix(video): fim do processamento infinito apos restart/deploy.** Status e gravado atomicamente, MP4 pronto e recuperado e job interrompido encerra com mensagem explicita.
- Versao: main.py/UI 1.27.103, cache bust `app.js?v=127103`.

## v1.27.102 - 2026-07-29

- **feat(kie): LEDGER + RESGATE — arte paga NUNCA mais se perde.** Todo taskId kie e gravado EM DISCO no momento da criacao (`/media/_tmp/kie_tasks.jsonl`). Novo endpoint `POST /api/posts/kie-recover` {company_id, task_ids?} repesca resultados pagos (ledger ou ids colados do painel kie), baixa as imagens e salva como post DRAFT no Acervo.
- Versao: main.py 1.27.102, OS cache bust v=127102.

## v1.27.101 - 2026-07-29

- **fix(judge): PORTAO GLOBAL de OCR — CPU nao satura mais com telas em paralelo.** Flagrado em prod: 4 juizes × 4 workers = 16 tesseracts nos 8 nucleos (CPU 787%) → arte PRONTA da kie ficava minutos presa no juiz ("kie gerou tudo e a plataforma rodando rodando"). Semaforo global limita a metade dos nucleos (2-4 tesseracts no processo inteiro); juizes se revezam e cada passe volta a ser rapido.
- **perf(judge): passe 2x REMOVIDO** — tesseract em 2048x3072 e brutal em CPU e toda quebra real foi detectada em resolucao nativa.
- Versao: main.py 1.27.101, OS cache bust v=127101.

## v1.27.100 - 2026-07-29

- **fix(kie): polling NAO desiste antes da fila da conta.** Com telas em PARALELO a fila da conta kie estica cada task; o polling desistia em 3-5min → a kie terminava DEPOIS (pagava e jogava fora) e a tela ficava vazia com R$0. Janelas: gpt 5.3→10min, edit 4.5→10min, market 3→6min.
- **fix(kie): fallback dedup por MODELO, nao por provedor.** Modelo quebrado (seedream-edit) descartava o nano-banana como reserva do MESMO kie e derrubava a cadeia inteira.
- **fix(estudio): logos de PRODUTO dentro do corte de 5 URLs do kie.** Prioridade: ancora + marca (2) + produtos ANTES das artes de referencia — o Deezer errado da 2ª vez era o corte, nao o cadastro. Ancora (tela 1) agora tambem vai por URL pro kie (familia visual real no caminho kie).
- Revertido `image_ref.model` p/ `kie:chatgpt/gpt-5.4-image-2` (A/B seedream-v4-edit FALHOU na kie e o autor desta versao derrubou a geracao por ~20min — desculpa registrada; a troca de modelo do Estudio agora so com validacao antes).
- Versao: main.py 1.27.100, OS cache bust v=127100.

## v1.27.99 - 2026-07-29

- **perf(ui): dropdown de modelos INSTANTANEO.** `/ai-models` consultava a API de CADA provedor ao vivo a cada clique (segundos de espera → usuario clicava varias vezes achando que travou). Cache de 5min no servidor; settings continuam lidos na hora.
- **fix(ui): opcao Estudio mostra O MODELO fixado** ("🎨 Estudio IA — kie · chatgpt/gpt-5.4-image-2 (padrao)") + placeholder "carregando modelos…" enquanto a lista nao chegou.
- **perf(judge): tentativas default 3→2** (setting `judge.max_attempts`; a 3ª regeracao raramente salva e custa 3-4min de modelo).
- **feat(render): ancora desligavel** (setting `render.anchor`=0 → TODAS as telas em paralelo, familia visual so pelas referencias; mais rapido).
- Versao: main.py 1.27.99, OS cache bust v=12799.

## v1.27.98 - 2026-07-29

- **perf(render): TELAS EM PARALELO — fim dos 30min por carrossel.** Provado nos timestamps de prod: o motor gerava UMA tela por vez (~5min20/tela × N, fila). Agora a tela 1 roda primeiro (ancora da familia visual) e as demais rodam SIMULTANEAS com teto configuravel (setting `render.parallel`, default 4; =1 restaura a fila antiga sem deploy). 8 telas: ~30min → ~6-8min.
- **perf(judge): OCR paralelo + saida rapida.** Passes do Tesseract em 4 workers, ordenados por utilidade, com EXIT no instante em que TODAS as palavras esperadas foram lidas — arte limpa (caso comum) julga em ~6s (antes ~30-40s). So 'por' no lang (metade do tempo, le nomes EN bem). Arbitragem por recorte enxuta (psm 7, 2 polaridades).
- Versao: main.py 1.27.98, OS cache bust v=12798.

## v1.27.97 - 2026-07-28

- **fix(billing): custo kie REAL.** Toda geração kie (market t2i, gpt4o-image, nano-banana-edit, influencer edit) retornava custo 0.0 → billing/UI mostravam "grátis" pra geração PAGA em créditos. Agora `_kie_cost_usd()` converte o `creditsConsumed` do recordInfo em USD (setting `kie.credit_usd`, default 0.005 = $5/1000cr), APRENDE `kie.credits.<model>` (a lista de modelos passa a mostrar o preço real sem "~") e cai pro aprendido/default do tier quando o kie não reporta. Debita os créditos internos da empresa corretamente.
- **fix(ui): seletor de IA não buga mais.** Causa: valor SALVO no projeto (ex.: 'editorial' ou modelo de provedor escondido no admin) ficava fora da lista → select travado. Saneamento: escolha morta volta pro 🎨 Estúdio IA (padrão). Opção "Editorial — só tipografia (grátis)" REMOVIDA do seletor. Label do provedor kie na lista ("kie.ai (créditos)"). O admin (Provedores) continua mandando: só kie habilitado = só modelos kie aparecem.
- **feat(admin): PROVEDOR+MODELO FIXOS com escolha OPCIONAL (modular).** Novo interruptor em Settings → Provedores: "Permitir que o usuário escolha o modelo" (setting `image.choice.enabled`). Desligado → o seletor SOME da Criação e toda arte usa o modelo FIXADO no "Motor de arte — Estúdio IA" (`image_ref.model`); versões existentes são normalizadas pro fixo. Ligado → usuário escolhe entre os modelos dos provedores habilitados. Client users continuam sempre sem escolha.
- **feat(aprovacao): tela por RUN.** A Aprovação mostra SÓ as peças produzidas neste projeto/produção (artes geradas + rascunhos enviados nesta sessão), cada post 1x — sem a pilha de aprovados/reprovados antigos. Toggle "Histórico completo" pra quem quiser ver tudo. "Enviar link" e "Aprovar tudo" também escopados ao run (link do cliente não arrasta post velho).
- Versao: main.py 1.27.97, OS cache bust v=12797.

## v1.27.96 - 2026-07-28

- **fix(estudio): logo de produto NUNCA mais desenhada de memoria.** Feedback do usuario (arte Gironetfibra linda, texto perfeito, mas Deezer saiu com a identidade ANTIGA): (1) o fluxo anexava logo de UM produto so (`break` no primeiro match — ExitLag ganhou, Deezer ficou de fora); (2) pro caminho kie (default atual) as referencias vao por URL PUBLICA e a logo de produto ia so em BYTES — o modelo nunca a via. Agora TODOS os produtos citados na tela (app + titulo + texto + CTA, cap 3, empresa propria vence catalogo) entram em bytes E em URL publica, com instrucao NOMEADA ("logo OFICIAL ATUAL de Deezer — PROIBIDO desenhar de memoria/versao antiga").
- Versao: main.py 1.27.96, OS cache bust v=12796.

## v1.27.95 - 2026-07-28

- **VALIDADO EM PROD (teste real v1.27.94): o juiz pegou a arte quebrada, regenerou com soletracao e avisou com honestidade quando o modelo falhou 3/3** — nunca mais quebra silenciosa. Dois refinamentos a partir desse teste:
- **fix(judge): candidato fraco nao condena.** "garantida" estava pintada CERTA mas o OCR nao a leu (laranja sobre fundo quente = contraste baixo em cinza) e o recorte de um token errado cravava "broken" — falso positivo que ainda poluia o feedback dos retries ("conserte garantida" pra palavra certa). Agora so candidato FORTE (ratio >=0.7, versao mutilada da palavra) pode condenar; sem candidato forte → "unknown" → visao decide.
- **feat(ocr): passes por CANAL DE COR (R/B).** Texto colorido some no cinza; no canal azul o laranja fica preto (contraste alto). Recupera leitura que o cinza perde.
- Versao: main.py 1.27.95, OS cache bust v=12795.

## v1.27.94 - 2026-07-28

- **fix(judge): LLM nao pode ser o arbitro que APROVA — arbitragem agora e DETERMINISTICA por recorte.** Teste real da v1.27.93 provou: a visao (Haiku) auto-corrige o typo ATE soletrando letra a letra ("Famâlia" pintado → soletrou "F-a-m-í-l-i-a") e aprovou arte quebrada. Novo `_ocr_crop_confirm`: o token do OCR mais parecido com a palavra suspeita da a CAIXA na arte → recorta, amplia 4x, RELE com Tesseract. Releu exata = ruido de leitura, passa; continua diferente = pintada errada, REPROVA. Sem IA no caminho de aprovacao.
- **fix(ocr): binarizacao 150/200 (± invertida) nos passes** — mata a cegueira em texto branco sobre pilula colorida (o "Saiba mais" que o OCR nao lia e virava suspeita eterna).
- **fix(judge): visao rebaixada a 3a instancia** — so decide palavra que o OCR NEM VIU; prompt endurecido ("teste de erro de pintura: copiar o erro e a resposta certa"); indisponivel → falha fechada (quebra → regenera).
- Validado contra as DUAS artes reais quebradas de prod: v92 ("segurenca/entrenitemento/portoflio") e v93 ("Famâlia/garant da/entrentenimento") — ambas reprovadas com as palavras exatas, custo de visao ZERO (arbitragem 100% local, ~40s de CPU). Arte limpa segue custo 0 (~6s).
- Versao: main.py 1.27.94, OS cache bust v=12794.

## v1.27.93 - 2026-07-28

- **fix(judge): calibracao com arte REAL derrubou o fuzzy.** Teste em producao provou: erro PINTADO de 1 letra ("segurenca", "bacio", "portoflio") da similaridade 0.80-0.92 — a MESMA faixa do ruido de leitura do OCR — entao o fuzzy >=0.8 do v1.27.92 aprovava quebra real. Fuzzy de aprovacao REMOVIDO: so match exato aprova.
- **feat(judge): arbitragem LETRA-A-LETRA (`vision_spell_words`).** Palavra suspeita → a visao copia como ela esta PINTADA, letra por letra, e o CODIGO compara. Transcricao livre nao serve de juiz: o modelo "conserta" o typo ao ler ("entrenitemento"→"entretenimento") e aprovava arte quebrada.
- **fix(judge): FALHA FECHADA.** Visao indisponivel/recusou → suspeita conta como quebra e regenera. O juiz nunca mais aprova cego (era o buraco original).
- **feat(judge): rodape julgado.** O contato exigido no prompt (CTA/post unico) entra no julgamento — telefone/site pintado errado tambem reprova.
- Validado contra a arte real quebrada de producao: pega "segurenca/entrenitemento/portoflio", inocenta "saiba" (OCR nao leu a pilula, mas esta pintada certa), arte correta segue custo 0.
- Versao: main.py 1.27.93, OS cache bust v=12793.

## v1.27.92 - 2026-07-28

- **fix(estudio): JUIZ DE TEXTO que nunca fica cego — texto quebrado NAO passa mais.** O juiz antigo dependia so de IA de visao: quando ela recusava/ficava sem saldo, devolvia vazio e a arte quebrada era APROVADA. Agora a 1a instancia e OCR LOCAL (tesseract por+eng, gratis, deterministico, nunca recusa, custo 0); a visao vira 2a instancia e so e chamada quando o OCR desconfia (palavra quebrada de verdade reprova nos DOIS; divergencia = ruido de leitura, nao queima credito regenerando arte boa).
- **fix(estudio): tolerancia ZERO.** Antes `len(miss) < 2` deixava passar arte com 1 palavra quebrada ("bawo" no lugar de "baixo" era APROVADO — a raiz da reclamacao). Agora qualquer palavra quebrada reprova e regenera.
- **feat(estudio): regeneracao com CORRECAO SOLETRADA.** O retry nao e mais moeda-ao-ar: o prompt da nova tentativa recebe a palavra que saiu errada na grafia original, soletrada letra a letra («baixo», B-A-I-X-O) — converge no erro em vez de repeti-lo. Criatividade intacta: a IA segue desenhando a arte inteira.
- **fix(judge): fuzzy de leitura.** Palavra conta como presente se aparecer no fluxo continuo (cobre "bai xo" dividido pelo leitor) ou com similaridade >=0.8 num token ("balxo" lido = ruido do OCR, passa; "bawo" desenhado = quebra real, reprova).
- fix(deps): `eaf_base_api` pinado em 3.3.2 — a 3.3.4 removeu `setup_logger` de `base_api.base` e derrubava o boot do container (dep transitiva do `xvideos_api`, sem pin ate hoje).
- Dockerfile: `tesseract-ocr` + `tesseract-ocr-por`; requirements: `pytesseract`.
- Versao: main.py 1.27.92, OS cache bust v=12792.

## v1.27.86 - 2026-07-17

- fix(imagem): kie `google/imagen4`/`imagen4-fast` estao QUEBRADOS no servidor da kie ("Internal Error" com input valido, testado ate com 1:1) — e `image.model` default era justamente `kie:google/imagen4`, por isso post fixo/carrossel falhava MESMO com 110 creditos na kie. Default trocado (setting) p/ `kie:bytedance/seedream-v4-text-to-image` (validado ao vivo).
- fix(imagem): `generate_image_resilient` SEM override agora passa o modelo da config pela MESMA cadeia de transbordo — default quebrado nunca mais para a geracao (validado: sem override e com imagen4 explicito, ambos sairam via seedream).

## v1.27.85 - 2026-07-17

- fix(imagem): transbordo agora conhece as DUAS carteiras da PiAPI (`piapi_llm` = LLM API em $; `piapi` = creditos da Task API). Antes, um 403 de saldo na LLM API (gpt-image-2/chatgpt-hifi) matava o provedor "piapi" inteiro e pulava os modelos Gemini da Task API.
- fix(imagem): modelos kie entram no registro de transbordo (`image_models_registry` + cadeia). Modelo PiAPI sem saldo agora cai sozinho pra kie (creditos) e a arte SAI — validado em prod: `piapi:gpt-image-2` -> `kie:bytedance/seedream-v4-text-to-image`.
- fix(imagem): `_model_provider` reconhece prefixo `kie:` (antes classificava como "openrouter" e uma falha kie matava o openrouter no transbordo).
- fix(ux): erro de saldo no transbordo agora inclui a mensagem REAL do provedor (ex.: PiAPI `insufficient_user_quota, saldo -$0.007`) em vez do generico "sem saldo/cota".

## v1.27.47 - 2026-07-01

- **fix(video-template): qualidade visual calibrada pelas artes aprovadas.** O render de video por template deixa de usar card branco gigante; CTA vira pilula laranja, logo vai para o rodape, progresso vai para o topo e os textos passam a encolher dinamicamente por area/linhas.
- **fix(video-template): hierarquia mais proxima do carrossel aprovado.** Blocos de texto ficam mais compactos, com mais respiro e menos escala exagerada em titulo/logo/CTA.
- Versao: main.py 1.27.47, OS + legacy cache bust v=12747.

## v1.27.46 - 2026-07-01

- **feat(video-template): Video Studio Template no fluxo de Conteudo.** O formato `Video` agora abre um studio de templates como caminho padrao, com escolha de template, campos editaveis, sugestao criativa por IA de texto e render MP4 sem token de video/imagem.
- **feat(video-template): catalogo ampliado.** Templates: `Brand Pulse`, `Oferta Snap`, `Prova Social`, `Meme VS`, `Story Cinematico` e `Beneficios em Pilha`, todos usando cores/logo do cliente.
- **fix(video-template): duracao real do MP4.** Frame count e FPS agora batem com `duration_sec`; manifest registra `fps`, `frame_count`, `template` e `variant`.
- **feat(video-template): aprovacao.** Video renderizado pode ser enviado para o workflow de aprovacao como post de video.
- Versao: main.py 1.27.46, OS + legacy cache bust v=12746.

## v1.27.45 - 2026-07-01

- **feat(video-template): motor experimental de video por template em paralelo.** Novo endpoint `/api/template-video/render` monta videos deterministicos com marca, logo, CTA e timing controlado, sem chamar IA no render (`token_cost=0`). Entrega GIF animado + frames PNG sempre, e MP4 quando `ffmpeg` estiver instalado no servidor.
- **feat(video-template): catalogo inicial de templates.** Novo endpoint `/api/template-video/templates` lista `brand_pulse_15s` e `meme_vs_10s` para validar custo baixo, velocidade e consistencia de marca antes de mexer no fluxo atual de video IA.
- Versao: main.py 1.27.45, OS + legacy cache bust v=12745.

## v1.27.43 - 2026-07-01

- **revert(arte livre): desfeitas as tentativas de free_text.** O texto-com-contorno e o "IA desenha o texto" (legacy_ai_full_art) estavam errados. Volta ao motor seguro (regressão OK). A arte criativa correta — **mantendo fontes/cores/logo da marca, mas variando posição/formato/fundo de forma criativa e NÃO repetitiva** — é o **Marco 3 (motor de criatividade)**, a implementar com amostras pra aprovação ANTES de deployar.
- Versão: main.py 1.27.43, cache bust v=12743.

## v1.27.42 - 2026-07-01

- **feat(arte livre): modo criativo sem caixa/padrão editorial.** Post/story no modo Criativo agora usa `free_text` no motor — texto SOLTO (gancho grande + 1 linha, com contorno p/ legibilidade), SEM caixa/pílula-CTA/telefone/site. `generate_carousel` marca `free_text` no modo criativo; `template_composer` desenha o modo livre. Regressão golden do carrossel OK (não afeta o aprovado). Fecha o **Marco 1**.
- Versão: main.py 1.27.42, OS + legacy cache bust v=12742.

## v1.27.41 - 2026-07-01

- **fix(influencer variedade): acaba o "só 2 fotos repetindo".** `pick_influencer_photo` era determinístico e, com a visão caindo no fallback, escolhia sempre os índices 0/1 → as mesmas 2 fotos em todo post. Agora: (1) `used_inf_idx` é semeado com as fotos RECÉM-USADAS deste influencer (persistido em `influencer.recent.<id>`, deixando ≥2 frescas) → posts consecutivos usam OUTRAS fotos, girando o portfólio inteiro. (2) A visão que casa emoção↔foto agora tenta **OpenRouter PRIMEIRO** (CometAPI está sem saldo).
- **chore: CometAPI despriorizado em todas as visões** (verify/pick/clear-side) — OpenRouter primeiro; CometAPI só como último recurso quando recarregar.
- Versão: main.py 1.27.41, OS + legacy cache bust v=12741.

## v1.27.40 - 2026-07-01

- **feat(Marco 1A — influencer USADO): o influencer cadastrado volta a ser composto na arte.** (1) Bug do "não usado": selecionar um influencer agora FORÇA o caminho de foto (`photo_ai_composer`) — antes o modo Editorial grátis caía em `composer_only` e pulava o influencer. (2) Bug do "mal usado / não compõe": a composição da pessoa usava **nano-banana via CometAPI, que está SEM SALDO** → falhava e caía pra cena sem pessoa. Agora `compose_person_scene` usa **kie image-edit** (`nano-banana-edit`, baixa a foto pública real e preserva rosto) como caminho primário, com CometAPI de fallback. Testado gerando com a foto real do influencer.
- Regressão golden OK (telas sem influencer idênticas).
- Versão: main.py 1.27.40, OS cache bust v=12740.

## v1.27.39 - 2026-07-01

- **fix: versão VISÍVEL da UI legada alinhada.** Os 3 badges de `app/ui/index.html` (sidebar/tray/version-badge) mostravam v1.27.24 → agora v1.27.39 (AGENTS.md exige a versão visível, não só o cache-bust).
- Versão: main.py 1.27.39, OS + legacy cache bust v=12739.

## v1.27.38 - 2026-07-01

- **fix(consistência): /ai-models e roteamento alinhados.** `/ai-models` reportava `openrouter` como default de imagem sem setting → agora `omniroute` (bate com o backend). `cometapi-gemini:` (nano-banana PRO da CometAPI) passou a ser reconhecido em `get_image_config` e no save de modelo (antes caía como openai/openrouter).
- **fix: UI legada alinhada** — `app.js?v=12738` + changelog interno com entrada nova (não começa mais em v1.27.24).
- **doc: default de imagem esclarecido** — no AR (setting do banco) = **kie Seedream 4.0** (escolha do usuário: realista, créditos). No CÓDIGO (deploy limpo/banco novo) = **OmniRoute grátis** (fallback seguro, sem gasto surpresa). Diferentes de propósito.
- Versão: main.py 1.27.38, OS cache bust v=12738.

## v1.27.37 - 2026-07-01

- **fix(imagem): `get_image_config` agora roteia `kie:`/`cometapi:`/`piapi:` certo.** Antes qualquer id com "/" (ex.: `kie:google/imagen4-ultra`) caía no ramo openrouter. Agora o prefixo decide o provedor no caminho padrão (sem override).
- **chore: default de imagem = kie Seedream 4.0** (fotorrealista, funciona). A linha **Imagen 4 do kie está retornando "Internal Error" (indisponível no lado do kie)** — quando voltar, é só escolher Imagen 4 Ultra no seletor. Código continua com fallback grátis OmniRoute se o banco estiver limpo.
- Versão: main.py 1.27.37, OS cache bust v=12737.

## v1.27.36 - 2026-07-01

- **fix(robustez): defaults de IA agora vivem no CÓDIGO, não só no banco.** `get_image_config` default virou **omniroute** (era openrouter); `get_ai_config` omniroute default virou **cc/claude-opus-4-8** (era high-availability). Deploy limpo/banco novo já sobem no provedor grátis certo.
- **fix: endpoint que salva modelo de imagem classificava errado.** `omni:`/`kie:`/`cometapi:`/`piapi:` caíam como openrouter/openai. Agora o prefixo decide o provider (posts.py).
- **feat(kie imagem): catálogo ampliado e bem descrito.** De 5 → **8 modelos** com IDs REAIS validados ao vivo (Seedream 4.0, Imagen 4 Ultra/4/Fast, Nano-Banana, Qwen-Image 2, Grok Imagine, Qwen-Image) + descrição clara do que cada um é. Corrigido o `_kie_build_image_input`: imagen4/grok/qwen2 exigem `aspect_ratio` (grok usa 2:3 no retrato) — antes só mandava prompt e quebrava (422).
- Legacy UI cache-bust alinhado (app.js?v=12735).
- Versão: main.py 1.27.36, OS cache bust v=12736.

## v1.27.35 - 2026-07-01

- **feat(IA texto): catálogo de provedores curado.** Removidos **Anthropic e OpenAI diretos** — texto agora só via gateways unificados: **OmniRoute, OpenRouter, CometAPI**. (kie.ai ficou de fora: não faz texto LLM, só imagem/vídeo via jobs async.) Cada gateway traz uma lista curada ~5 Claude + 5 OpenAI + 5 Grok + 5 diversos (Gemini/GLM/DeepSeek/Qwen) com IDs REAIS validados ao vivo. OmniRoute lista só os mirrors grátis das assinaturas que respondem de fato (cc/claude-*, cgpt-web/gpt-*).
- **fix(IA texto): default saiu do drift e foi pro grátis que FUNCIONA.** Estava em `openrouter / deepseek-r1-distill-llama-70b` (fraco pra copy). Novo default **OmniRoute + cc/claude-opus-4-8** (grátis via assinaturas, preserva acentos, aguenta o JSON pesado do carrossel; briefing usa Sonnet como cheap). CometAPI foi descartado como default por estar **sem saldo**. `get_ai_config` default de provider virou `omniroute`.
- Frontend: dropdown de provedor de texto atualizado (OmniRoute grátis primeiro · OpenRouter · CometAPI).
- Versão: main.py 1.27.35, OS cache bust v=12735.

## v1.27.33 - 2026-07-01

- **fix(imagem): seedream-4.5 voltou a gerar (não cai mais no editorial).** O modelo exige `size` grande (≥ 3.686.400 px) e rejeitava aspecto pequeno com HTTP 400. `generate_image_openrouter` agora **escalona o payload** em vez de morrer no 1º 400 de schema: (1) aspect_ratio+resolution → (2) `size` grande no mesmo aspecto (≈4:5 1832×2288) → (3) só model+prompt (default do modelo). Confirmado no ar: seedream-4.5 → HTTP 200. Isso evita o "transbordo esgotado → arte editorial".
- **fix(briefing): modo Criativo agora é FIEL ao assunto.** O user-prompt hardcodava "empresa vende SVAs para provedores / fale COM o provedor" em TODOS os modos, esmagando memes/datas em pauta institucional de ISP. Agora o user-prompt é **intent-aware**: em `criativo` a CENA/IDEIA do usuário é a estrela (newsjacking, marca só como assinatura/CTA leve); `produtos`/`evento` seguem o enquadramento aprovado (intactos).
- Versão: main.py 1.27.33, OS cache bust v=12733.

## v1.27.32 - 2026-07-01

- **Marco 0 — Fundação: runner de migrations versionado + dev-mode fail-closed.**
- **feat: runner único de migrations** (`app/migrations.py`), idempotente/versionado, com ledger `schema_migrations`, lock cross-process (`fcntl.flock`) + `BEGIN IMMEDIATE` para serializar réplicas do swarm no boot. Helpers `ensure_column`/`ensure_index` que os próximos marcos usam (flow_id, layout_variant), evitando ALTER ad-hoc. Wired em `main.py` `_startup()` sob o lock.
- **fix(sec): auth fail-CLOSED por padrão.** Sem `ADULT_META_API_KEY` a API não fica mais aberta — rejeita (sessão válida sempre passa). Acesso aberto agora exige opt-in explícito `ALLOW_OPEN_ACCESS=1` (só dev). Fecha o risco de um redeploy que dropa o env reabrir a plataforma silenciosamente.
- **chore(sec): dev-mode fechado em produção** (`ADULT_META_API_KEY` + `AUTH_SESSION_SECRET` setados no serviço `metaporn-new_adult-meta`). Deployar SÓ via `docker service update` (stack redeploy sem as chaves reabriria — agora mitigado pelo fail-closed).
- Versão: main.py 1.27.32, OS cache bust v=12732. (Observação: 1.27.25–1.27.31 são trabalho de vídeo/briefing ainda não commitado no worktree; não backfilados aqui.)

## v1.27.24 - 2026-06-30

- **fix: 4 frentes de conhecimento do app chegam ao storyboard de vídeo.** A IA agora recebe dados reais do produto (base local + web cache + site/Instagram como fallback + referência visual do carrossel aprovado do mesmo app) e para de alucinar nome de app/jogo/filme/música. Era o bug do "Deezer virar Creezer" — o briefing já tinha a peça (`_video_brief_context`) mas ela só ia para o áudio/CTA, não para as cenas enviadas ao modelo.
- **fix: Duração respeita o roteiro, sem duplicar cenas.** `video_segment_plan` agora devolve LISTA de segundos por clipe somando ≈ duração-alvo (antes eram só `per` único). O pad que duplicava `prompts[0]` quando a IA devolvia menos cenas que o mínimo foi removido — respeita-se o nº de cenas do roteiro; o tempo é redistribuído. 15s com 3 cenas viram 3 clipes de 5s.
- **fix: Caixinhas do roteiro não aparecem mais vazias.** Preflight respeita as cenas que a IA devolveu, e `build_video_storyboard` força o nº de cenas no `user` + 2ª chamada de correção (texto barato) quando a IA devolve nº errado.
- **fix: pt-BR travado incondicionalmente.** Cada prompt por cena recebe "Brazilian Portuguese, never European" sem depender de `dialogue_ptBR` estar preenchido.
- **fix: LEI DO REALISMO DE PRODUTO no system prompt.** Proibido inventar produto que não está no brief (resolvia Deezer→"Creezer", citação de jogos/filmes que não pertencem ao app). Obrigatório desenhar a SENSAÇÃO dos recursos reais (sem renderizar logo/UI).
- **feat: Capa do carrossel aprovado como first_frame da cena 1.** Herda identidade visual do carrossel já aprovado pelo cliente para aquele app. Knob on/off: setting `video.use_carousel_ref` (default ON).
- Versão: main.py 1.27.24, OS/UI cache bust v=12724.

## v1.27.13 - 2026-06-29

- **fix: Duração real do vídeo.** O front envia `target_seconds` para o backend e não usa mais segundos por cena como duração total.
- **fix: Corte pós-provedor.** O compositor corta cada clipe no tempo planejado antes de montar o vídeo final, impedindo que modelos como Omni devolvam 10s/20s quando o app pediu menos.
- **fix: Omni 8s em uma cena.** `cometapi:omni-fast` não divide mais um pedido de 8s em duas cenas de 4s antes do envio ao provedor.
- **fix: Áudio e CTA controlados pelo sistema.** O compositor descarta áudio nativo do provedor e o CTA final passa a ser determinístico da marca/CTA do cliente, sem copy final gerada por IA.
- **teste: Sem custo de IA.** O smoke de vídeo cria um clipe local de 10s e prova que o output final fica em ~2s + CTA.
- Versão: main.py 1.27.13, OS/UI cache bust v=12713.

## v1.27.12 - 2026-06-29

- **fix: Briefing adaptativo de vídeo.** O `video_storyboard_system` padrão passa a herdar a régua editorial do carrossel: dor real, crença errada, mudança de visão, benefício concreto, regras específicas para provedores/SVAs e bloqueio de b-roll genérico.
- **fix: Prompt final de vídeo por cena.** `VIDEO_GEN` agora compila cada cena como shot canônico com sujeito/elemento, contexto, uma ação, um movimento de câmera, luz/clima e proibição dura de texto/logo/UI dentro do clipe.
- **teste: Validação sem custo.** O smoke de prompts/preços agora prova os defaults de vídeo e os overrides por cliente sem chamar OpenRouter/CometAPI para geração paga.
- Versão: main.py 1.27.12, OS/UI cache bust v=12712.

## v1.27.11 - 2026-06-29

- **feat: Prompts modulares por cliente.** A aba Cliente > Criação agora expõe os prompts efetivos de briefing/roteiro de vídeo e de imagem/vídeo por cliente; `build_video_storyboard`, `build_video_prompt` e `build_image_prompt` consomem `brand_kit.creative_config`.
- **fix: Preços de imagem com origem.** Modelos de imagem passam a marcar preço `real`, `catálogo` ou `estimado`; CometAPI usa `pricing.per_request` quando o catálogo expõe e OpenAI-compat aprende `usage.cost` por modelo após geração.
- **fix: Transparência de custo na UI.** Seletores de imagem/vídeo mostram a origem do preço para não confundir estimativa com custo real.
- Versão: main.py 1.27.11, OS/UI cache bust v=12711.

## v1.27.2 - 2026-06-29

- **fix: Progresso de geração de vídeo.** A animação de carregamento agora usa `provider_progress` dentro da cena e um avanço conservador por tempo quando o provedor ainda está em fila, evitando ficar travada em 5% em vídeos de uma cena.
- **fix: ETA do vídeo.** Como o percentual passa de 10% mesmo antes da cena terminar, o modal volta a mostrar estimativa de tempo restante durante jobs longos da OpenRouter/CometAPI.
- **fix: Texto de custo.** Quando o provedor não devolve `usage.cost`, a UI mostra custo estimado pelo catálogo em vez de chamar esse valor de custo real, e usa a mesma conversão BRL do preflight.
- Versão: main.py 1.27.2, OS/UI cache bust v=12702.

## v1.27.1 - 2026-06-29

- **fix: Custo de vídeo CometAPI entregue.** Quando a CometAPI conclui o vídeo mas não devolve `usage.cost`, o job agora registra o custo pelo catálogo/preflight (`per_second` ou `per_request`) em vez de finalizar como `0.0`.
- **fix: Download com provedor congelado.** O download final também usa a configuração congelada do job ao buscar a URL pronta, evitando dependência do modelo global durante jobs longos.
- Versão: main.py 1.27.1, OS/UI cache bust v=12701.

## v1.27.0 - 2026-06-29

- **fix: Jobs de vídeo com provedor congelado.** O background captura a configuração do provedor no início e usa a mesma base/key para criar, pollar e baixar, evitando quebra se o usuário trocar modelo enquanto o job roda.
- **fix: Observabilidade do provedor.** O status do vídeo agora grava `provider`, `provider_job_id`, `provider_status` e `provider_progress`, permitindo depurar jobs lentos da CometAPI sem perder o ID remoto.
- **fix: Timeout realista para CometAPI.** Comet ganha janela maior de polling no backend, e a UI aguarda jobs longos sem declarar timeout antes da plataforma.
- Versão: main.py 1.27.0, OS/UI cache bust v=12700.

## v1.26.99 - 2026-06-29

- **fix: Preços reais no vídeo.** O seletor e o preflight agora consultam catálogos dos provedores quando disponíveis: OpenRouter `/api/v1/videos/models` (`pricing_skus`) e CometAPI `/api/models` (`pricing.per_second`/`per_request`), com cache em settings.
- **fix: Duração cobrada/gerada.** Quando o usuário trava uma duração menor que o máximo do modelo, o backend usa a duração escolhida por cena em vez de sempre usar o máximo do modelo.
- **fix: Catálogo CometAPI.** Adicionado `viduq3-turbo` e corrigidos preços fallback dos modelos Comet compatíveis com `/v1/videos`.
- Versão: main.py 1.26.99, OS/UI cache bust v=12699.

## v1.26.98 - 2026-06-29

- **fix: Vídeo OpenRouter sem cobrança por payload inválido.** `create_video_job` agora manda `duration` inteiro, `resolution`, `aspect_ratio` e `frame_images` no schema oficial (`type=image_url`, `image_url.url`, `frame_type`), eliminando o erro Zod em `frame_images[0].type`.
- **fix: Vídeo CometAPI pelo contrato documentado.** Comet volta para `POST /v1/videos` com `multipart/form-data`, polling em `GET /v1/videos/{id}` e download por `video_url` ou `/content`; modelos Comet com rotas próprias foram removidos do seletor genérico para evitar tentativa cobrada em endpoint errado.
- **fix: Fluxo branded/legado de vídeo.** O frontend envia segundos por cena do preflight, o backend aceita `task_id`, centraliza o download e o endpoint legado passa prompt string para o provider.
- **teste: Validação sem custo.** Adicionado `scripts/test_video_providers_no_api.py`, que intercepta HTTP e prova os payloads de OpenRouter/Comet sem chamar APIs reais.
- Versão: main.py 1.26.98, OS/UI cache bust v=12698.

## v1.26.61 - 2026-06-28

- **fix: Rollback da engine visual recente.** Revertidos os commits do motor de proteção/recorte que deixaram post fixo com caixa de carrossel e reduziram criatividade visual.
- **fix: Post fixo criativo por padrão.** O endpoint de post fixo com IA volta a usar o modo antigo em que a IA desenha a peça inteira; o compositor com caixa/card fica apenas opt-in por `render_mode`.
- Versão: main.py 1.26.61, OS/UI cache bust v=12661.

## v1.23.4 - 2026-06-22

- **fix: Instagram/publicação pela plataforma.** URLs completas HTTPS (ex.: `https://caripost.n8nmikael.com.br/uploads/...`) agora são corretamente resolvidas para o caminho local no disco antes do re-host no tmpfiles.org. Antes o re-host falhava silenciosamente e o post nunca era publicado.
- **fix: Logo com cutout suave.** O novo `_logo_cutout` usa alpha gradiente por distância de cor (não flood-fill). Remove fundos sólidos sem pixelar bordas nem cortar letras. Fundos com photo/textura são preservados intactos.
- Versão: main.py 1.23.4, OS/UI cache bust v=12334.

## v1.23.3 - 2026-06-22

- **fix: Publicação Instagram funcionando end-to-end.** Imagem é re-hosteada em tmpfiles.org (upload anônimo, sem auth), `ig_user_id` incluído no passo de publish, formato `arguments` corrigido para API v3.1 do Composio. Testado e confirmado: post publicado com sucesso no Instagram.
- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill) que destruía o logo na sobreposição da imagem gerada por IA.
- **fix: Erros de publicação logados.** `asyncio.create_task` agora tem `add_done_callback` que captura exceções e grava log no banco.
- Versão: main.py 1.23.3, OS/UI cache bust v=12333.

## v1.23.2 - 2026-06-22

- **fix: Composio/Instagram payload format.** API v3.1 exige que os parâmetros da tool vão dentro de `arguments`, não como campos top-level. Corrigido em todos os pontos de chamada.
- **fix: ig_user_id automático.** O ID do Instagram Business/Creator é obtido via `INSTAGRAM_GET_USER_INFO` e cacheado no metadata da conexão — não precisa mais configurar manualmente.
- **fix: Re-host de imagem em URL pública.** Imagens geradas são re-hosteadas no Imgur antes de enviar ao Instagram, porque os crawlers do Meta não conseguem buscar de URLs internas/privadas. Requer `IMGUR_CLIENT_ID` env ou setting `imgur.clientId`.
- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill) que destruía o logo na sobreposição da imagem gerada por IA.
- **fix: Erros de publicação logados.** `asyncio.create_task` agora tem `add_done_callback` que captura exceções e grava log no banco.
- Versão: main.py 1.23.2, OS/UI cache bust v=12332.

## v1.23.1 - 2026-06-22

- **fix: Logo intacto na imagem gerada.** Removido o `_logo_cutout` (flood-fill com thresh=70) que destruía o logo na hora de sobrepor na imagem gerada por IA. O logo agora é aplicado como-is, preservando o alpha original do PNG. PNGs com transparência continuam funcionando; logos opacos mantêm o fundo intacto em vez de ficar pixelados/quebrados.
- **fix: Publicação Instagram via Composio reescrita.** O `publish_post` não envia mais texto livre para um tool genérico. Agora faz 2 chamadas estruturadas com parâmetros nomeados: `INSTAGRAM_POST_IG_USER_MEDIA` (cria container com `image_url`/`video_url` + `caption`) → `INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH` (publica com `creation_id` + `max_wait_seconds`). Slugs podem ser sobrescritos via env `COMPOSIO_TOOL_INSTAGRAM_CREATE_MEDIA` / `COMPOSIO_TOOL_INSTAGRAM_PUBLISH_MEDIA`.
- **fix: Erros de publicação não são mais silenciados.** `asyncio.create_task(publish_social_post(...))` agora tem `add_done_callback` que captura exceções e grava log no banco (`social_post_logs`) e no logger `caripost.social`.
- Versão: main.py 1.23.1, OS/UI cache bust v=12331.

## v1.22.3 - 2026-06-20

- Settings ganhou suporte para salvar `Composio API` e Auth Configs de Instagram/Facebook/TikTok/YouTube.
- Provider Composio agora lê token salvo no banco (`token:composio` ou `social.apiKey.composio`) antes de depender de `COMPOSIO_API_KEY`.
- `/api/social/config` agora reflete configuração Composio salva no app.
- Versão: main.py 1.22.3, OS/UI cache bust v=12230.

## v1.22.2 - 2026-06-20

- Clientes ganhou aba `Fluxo` como caminho principal: Instagram da empresa, conexão Composio, concorrentes, análise, ideias, aprovação, criação de mídia e publicação.
- Backend social ganhou workspace por empresa, análise estratégica via Composio/IA e geração de rascunhos a partir das ideias.
- Análise social agora pode atualizar identidade de marca com posicionamento, voz, persona, visual prompt base e cores sugeridas.
- Ideias da estratégia viram posts em `REVIEW`, preservando aprovação antes de publicar.
- Versão: main.py 1.22.2, OS/UI cache bust v=12220.

## v1.22.1 - 2026-06-20

- Social Integration Layer via Composio/provider isolado para conectar contas, criar posts, publicar/agendar, consultar status e métricas.
- Rotas novas em `/api/social` para contas, posts, worker, concorrentes e referências.
- Banco: tabelas novas `social_connections`, `social_posts`, `social_post_channels`, `social_post_assets` e `social_post_logs`.
- Worker APScheduler separado para posts sociais agendados, com logs por canal e bloqueio de conteúdo não aprovado.
- Publicar OS ganhou canais conectados, publicação social, concorrentes e referências sem mexer em upload, storage ou processamento de vídeo.
- Docs e smoke test mock em `docs/composio-social-integration.md` e `scripts/social_smoke.py`.
- Versão: main.py 1.22.1, OS/UI cache bust v=12210.

## v1.22.0 - 2026-06-20

- Módulo de Clientes: CRUD de empresas, brand kit (logo, cores, voz, persona), mood board e concorrentes.
- Central de Aprovação: workflow DRAFT -> REVIEW -> APPROVED -> SCHEDULED com transições validadas.
- Inteligência de Concorrentes: benchmark cross-empresa com visão consolidada.
- IA de texto (Anthropic/OpenAI/OpenRouter) integrada: geração de copy de posts e briefings de tendências.
- Tendências atualizadas: briefing por empresa via IA, sem dependência de scraping de plataformas adultas.
- Configurações de IA na página de Settings: provedor, modelo, API key e teste de conexão.
- Limpeza de referências de plataformas adultas na view de Tendências.
- Backend: 6 tabelas novas (companies, brand_kits, competitors, posts, research_reports, company_assets).
- Backend: 3 routers novos (companies, posts, ai_settings) + módulo services/ai.py.
- Versão: main.py 1.22.0, index.html v1.22.0, app.js cache bust v=12200.

## v1.21.3 - 2026-06-16

- Cortes passa a indicar corretamente quando usou Vision IA/cache e quando caiu no fallback de detecção automática por falta de token/resposta de IA.

## v1.21.2 - 2026-06-16

- Cortes IA passa a enviar timestamps junto dos frames para a Vision selecionar tempos reais do vídeo.
- Cache de análise Vision agora é persistente em `cache/vision/{hash}.json`, calculado pelo hash do primeiro 1MB + tamanho do vídeo.
- Extração paralela mantém semáforo máximo 3 e atualiza o progresso conforme cada corte termina.

## v1.21.1 - 2026-06-15

- Ajuste de release para o pipeline de cortes IA com seleção por Vision, cache de análise e extração paralela.

## v1.21.0 - 2026-06-15

- Cortes com IA: Vision analisa frames e seleciona os melhores momentos automaticamente — sem sliders de minutagem.
- Extração paralela de clips com semáforo (máx 3 simultâneos) — speedup de 3x.
- Cache de análise por vídeo — mesma mídia não reanalisada pela IA.
- UI redesenhadada do Cortes: limpa, sem inputs de quantidade/duração, foco em 1 clique.
- Fallback automático para detecção clássica de cenas quando IA está indisponível.

## v1.20.27 - 2026-06-15

- Analyze passa a enviar `stt_provider: none`, pulando transcrição automática.
- Backend respeita o modo sem transcrição e continua com referências do criador, Vision IA, geração de JSON/metadados e prompt.
- OS remove a escolha de STT e a aba SRT do Analyze enquanto a etapa de legenda/transcrição estiver cortada.

## v1.20.24 - 2026-06-15

- Adiciona timeout por request no upload via XHR para partes que ficam penduradas sem disparar erro do navegador.
- Timeouts passam a entrar no retry existente, preservando o arquivo selecionado e o fluxo de upload em partes.

## v1.20.23 - 2026-06-15

- Adiciona modal de tela inteira durante uploads, com circulo de progresso, percentual, tempo restante e descricao da etapa atual.
- Mantem o fluxo existente de upload local/por partes e apenas adiciona feedback visual global.

## v1.20.22 - 2026-06-15

- Adiciona retry ao upload pequeno via `/uploads/local-stream`, reaproveitando o mesmo arquivo selecionado quando a rede oscila.
- Mantem o caminho em partes para arquivos acima de 128 MB.

## v1.20.21 - 2026-06-15

- Corrige o registro auxiliar do complete idempotente para nao transformar upload finalizado em erro 500.
- O armazenamento do resultado do complete passa a ser best effort: se falhar, o arquivo salvo ainda retorna sucesso ao navegador.

## v1.20.20 - 2026-06-15

- Troca a chamada de finalizacao de `/uploads/chunk/complete` para XHR, usando o mesmo canal que envia as partes do arquivo.
- Mantem retries e idempotencia no complete para evitar falhas no fim de uploads grandes quando o navegador derruba `fetch` depois de transferir muitos chunks.

## v1.20.19 - 2026-06-15

- Serializa a finalizacao de uploads em partes por `upload_id`, evitando corrida entre tentativas repetidas de `/uploads/chunk/complete`.
- Faz o abort aguardar a finalizacao em andamento e preservar uploads ja completados, impedindo perda do arquivo quando a rede oscila no fim do envio.

## v1.20.18 - 2026-06-15

- Reforca o upload em partes para redes instaveis: inicializacao, envio de partes e finalizacao agora fazem retry em falhas transitorias.
- Torna `/uploads/chunk/complete` idempotente: se o arquivo for salvo mas a resposta se perder, uma nova tentativa retorna o mesmo `object_key` em vez de abortar o upload.

## v1.20.17 - 2026-06-15

- Corrige uploads grandes no Caripost: arquivos acima de 128 MB passam a ser enviados em partes para `/uploads/chunk/*`, montados no storage local e validados antes de serem aceitos.
- Mantem `/uploads/local-stream` para arquivos menores e evita voltar ao fluxo antigo de PUT direto/presigned no S3.

## v1.20.16 - 2026-06-15

- Alinha as versoes publicas do Caripost OS e do painel ao backend em producao, removendo indicadores antigos e forçando novo cache bust dos assets do OS.

## v1.19.13 - 2026-06-15

- Corrige o MetaPorn OS para que o tour automatico nao intercepte cliques nas areas de upload: o tutorial continua visivel, mas o usuario consegue selecionar videos no Analyzer e nos demais fluxos com upload.
- Adiciona cache bust ao `os.css`, garantindo que a correcao do tour chegue ao navegador junto com os scripts `v=121100`.

## v1.19.12 - 2026-06-14

- Alinha os routers modulares ao login do MetaPorn OS: `app/main_utils.py` agora aceita `X-Session-Token` valido antes de exigir API key, liberando leituras autenticadas em AutoEditor, Enhancer, Publicar, Criadores, DMCA, Agenda, Tendencias e Financeiro apos login normal.

## v1.19.11 - 2026-06-14

- Corrige o upload do MetaPorn OS quando o usuario seleciona um video sem sessao valida: o overlay de login agora e aguardado e o mesmo arquivo continua o envio apos autenticar, com uma nova tentativa quando a sessao expira durante o upload.

## v1.19.10 - 2026-06-13

- Ajusta a checagem inicial de autenticacao do MetaPorn OS para preservar a abertura visual anterior: respostas `missing_or_invalid_api_key` no boot apenas marcam auth pendente, e o login aparece quando uma acao protegida exige credencial.

## v1.19.9 - 2026-06-13

- Corrige a checagem de autenticacao do MetaPorn OS: respostas JSON `missing_or_invalid_api_key` passam a ser tratadas como bloqueio de auth mesmo quando o backend retorna HTTP 200, abrindo o login antes do upload.

## v1.19.8 - 2026-06-13

- Corrige a autenticacao do upload no MetaPorn OS: o XHR para `/uploads/local-stream` passa a reutilizar a `X-API-Key` salva na sessao da UI antiga, evitando `missing_or_invalid_api_key` quando o servidor exige API key.

## v1.19.7 - 2026-06-13

- Corrige o upload do MetaPorn OS apos a migracao para CariPost: a tela nova deixa de usar PUT direto no storage por presign e passa pelo endpoint backend `/uploads/local-stream`, com a mesma validacao de video da UI funcional.

## v1.19.6 - 2026-06-10

- Corrige o carregamento das capas no gerenciador Arquivos: as primeiras thumbnails da grade agora entram na fila imediatamente, sem depender de rolagem dentro da janela do MetaPorn OS.

## v1.19.5 - 2026-06-10

- Faz o login do MetaPorn OS respeitar `/auth/check`: quando a autenticacao esta ativa, o login aparece no desktop novo e a sessao e espelhada para os modulos antigos embutidos.

## v1.19.4 - 2026-06-10

- Restaura o funcionamento real dos módulos no MetaPorn OS: cada janela do desktop novo abre a rota funcional antiga em `/ui/?embed=1`, reaproveitando handlers, uploads, runs, Criacao, burn, teaser, settings e demais fluxos existentes.
- Mantem o visual do desktop MetaPorn OS e aumenta/centraliza os icones no topo da tela.
- Espelha a sessao do login do OS para a UI antiga, evitando login duplicado dentro das janelas.

## v1.18.21 - 2026-06-02

- Corrige a tela inicial para seguir o desktop do pacote Claude Designer: boot/login MetaPorn OS, grupos de apps completos e janela oculta quando nao ha rota direta.
- Mantem rotas, endpoints, loaders e funcoes tecnicas existentes; atalhos visuais de edicao apontam para a rota real de Criacao.

## v1.18.20 - 2026-06-02

- Corrige a entrega visual do Claude Designer com login em MetaPorn OS, desktop com apps agrupados, start menu, taskbar e janela principal.
- Preserva rotas, IDs, handlers, loaders, endpoints e fluxos tecnicos existentes.

## v1.18.19 - 2026-06-02

- Aplica a reestruturacao visual MetaPorn OS recebida no pacote `Metaporn.zip`.
- Transforma o shell atual em uma experiencia visual de desktop: launcher em blocos, janela principal em vidro escuro e barra inferior de atalhos.
- Preserva rotas, IDs, handlers e fluxos tecnicos existentes.

## v1.18.18 - 2026-05-25

- Corrige o burn de logo para manter a proporcao visual do preview e evitar logo achatada no video final.
- Adiciona exclusao de run/criacao com limpeza de registros relacionados, jobs e arquivos seguros.
- Atualiza o cache bust do painel admin para forcar carregamento da UI mais recente.

## v1.18.13 - 2026-05-22

- Versao anterior diagnosticada com ausencia de exclusao de run/criacao e problema de proporcao na logo durante burn.
