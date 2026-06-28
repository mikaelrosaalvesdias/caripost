# Entregável 0 — COMPLETO (texto + logo + rodapé) · v1.25.79

Fecha o Entregável 0 juntando o texto travado (que ficou bom) com o que faltava de logo/rodapé,
trazendo a abordagem do código antigo que funcionava (painel/halo + posição fixa).

## O que foi alterado (tudo em `app/services/template_composer.py`)

1. **`_load_logo` agora corta a moldura transparente** (`getchannel("A").getbbox()` → `trim_alpha`).
   Era a causa da logo sair **minúscula**: o asset tem muito espaço transparente em volta e o
   código encolhia a moldura inteira. Agora a logo é cortada no tamanho real antes de redimensionar.

2. **Logo do app: caixa cinza → HALO suave.** Trocado `_paste_logo_chip` (que punha uma caixa
   sempre) por `_stamp_app_logo`, que analisa o fundo e, só quando a logo fosse sumir, põe um
   **glow borrado da cor oposta** atrás (sem caixa visível). É o "não funcionava → funciona".

3. **Rodapé determinístico.** A logo da empresa deixou de ser posicionada por um sistema de
   colisão que a jogava pro centro/minúscula. Agora: **logo à esquerda (posição FIXA), contador
   à direita**, sobre a parte mais escura do scrim (legível em qualquer foto). Tamanho subido de
   150×46 → 200×60. Sem logo transparente usável, cai pro @handle (degradação graciosa).

4. **Texto mantido travado** (Marco 1) — número/título/corpo sempre à esquerda, mesma régua.

## Provas que EU fiz antes de te entregar (grátis, sem IA)
- **Determinismo:** mesmo slide + mesma foto renderizado 3× = **bytes idênticos** (md5 igual).
  O composer NÃO sorteia — a única coisa que muda entre gerações é a foto da IA.
- **3 tipos** (capa/conteúdo/CTA) renderizam sem erro e determinísticos.
- **Olhei** o conteúdo sobre foto clara E escura: logo do app sem caixa (glow), logo da empresa
  fixa e legível no canto, texto na mesma posição.
- *Ressalva honesta:* testei com logos **sintéticas** (texto chapado). Com os assets REAIS da
  CARIAP/Deezer fica melhor — ou pode revelar problema no próprio arquivo (sem transparência).
  O teste de verdade é gerar no ar com os assets reais.

## Deployado — v1.25.79 NO AR (`?v=12579`)

### Como testar
1. Caripost → **Conteúdo → Carrossel** → CARIAP + tema → renderizar (nano-banana).
2. Avalie o Entregável 0 inteiro: **texto na mesma posição** em todas as telas; **logo da CARIAP
   no rodapé** legível e no mesmo canto; **logo do app sem caixa feia**; tudo coeso entre as telas
   (só a foto muda).

### Ainda fora do Entregável 0 (próximos marcos)
Coesão/mesma família das fotos (Marco 3/5); copy longa/telefone estrito (Marco 4); versão
clara/escura dos assets de logo se o glow não bastar em algum caso (Marco 2 fino).
