# Marco 2 — LOGO · v1.25.95 (resolve P3)

Honestidade: o grosso do P3 já caiu no Marco 0 (variante por contraste, halo, multi-app, `trim_alpha`, sem caixa
cinza). O Marco 2 fez o que faltava: **auditar o asset REAL** e fechar a ponta que ainda quebrava.

## Auditoria dos assets reais (CARIAP)
Olhei arquivo por arquivo (tamanho, modo, alfa, padding, fundo):
- Marca CARIAP / ExitLag / E-Saúde: PNG/webp limpos, alfa de verdade. OK.
- Looke: alfa ok mas **padding 41–80%** (logo pequena num canvas grande) → o `trim_alpha` recorta no render. OK.
- **Deezer: 3 `.gif` (modo P, SEM alfa, fundo PRETO) misturados com 4 PNGs limpos.** ⚠️ Esse era o estrago:
  se o seletor pegasse um GIF, carimbava um **retângulo preto** com a logo dentro, sobre a foto.

## Correção
`_logo_is_clean(path)` + saneamento em `_all_raster_logos` (posts.py): se o app tem variante COM RECORTE
(fundo transparente), usa **só essas** e **descarta as de fundo assado**. Se TODAS forem assadas, degrada com o
que há (não esconde logo). Fica FORA do motor (`template_composer.py`) → golden intacto, zero risco no Marco 0/1.

Detecção: sem canal alfa = fundo sólido; ou alfa com ≥2 cantos opacos = retângulo assado.

## Provado por mim
- Saneamento por app: Deezer **descartou os 3 GIFs**, manteve os 4 PNGs; demais apps: nada descartado.
- Render real de tela Deezer sobre foto escura: **logo branca limpa no topo-direita, ZERO caixa preta** (olhei a imagem).
- Golden verde (motor intacto). Determinismo do Marco 1 intacto.

## Como testar
Gere um carrossel que cite **Deezer** (e outros apps). As logos saem **limpas, sem caixa/retângulo**, na mesma
posição/escala em todas as telas — inclusive o Deezer, que antes podia sair como um bloco preto.

## Extra (v1.25.96) — cobertura de apps no briefing
Bug relatado: tema citando 4 apps (Deezer/Looke/E-Saúde/ExitLag) saía com 3 — **E-Saúde dropado** (saúde não
"encaixava" no tema frio), e o CTA recapitulava só 3. Causa: o prompt mandava "distribuir" mas não EXIGIA
cobertura total nem garantia telas suficientes (5 telas = 3 de conteúdo = 3 apps).
Correção em `generate_carousel` (ai.py): detecta os apps CITADOS no tema, põe **piso de telas** = capa + 1 por app
+ CTA (teto 10 = limite do IG; sobe a contagem sozinho) e instrução de **COBERTURA OBRIGATÓRIA** (cada app citado
tem ≥1 slide + aparece no CTA; achar o ângulo até pro menos óbvio, ex.: telemedicina E-Saúde no frio).
Provado: tema dos 4 apps com n=5 → subiu p/ 6 telas, **cobertura deezer/looke/e-saúde/exitlag = ✓✓✓✓**, cada um
taguead​o na sua tela (a marcação tag→logo confirmada funcionando).

## Fronteira honesta (não inflei)
"Logo faltando → mostrar nome do app em Poppins" (item do plano) é guarda pra um app SEM nenhuma logo cadastrada —
hoje **não acontece** (todos os apps da CARIAP têm logo). Não toquei no motor por um caso que não existe; é um
add de ~10 min se algum dia registrarem um app sem logo. Me avisa se quiser já deixar pronto.
