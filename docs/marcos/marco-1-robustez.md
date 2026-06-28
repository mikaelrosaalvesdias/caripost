# Marco 1 — PADRÃO + ROBUSTEZ · v1.25.94 (resolve P1 e P6)

Feito igual ao plano `peaceful-juggling-donut.md`, sem pular nada. Tudo testado por mim antes de pedir teste;
golden verde (sem regressão no Marco 0) e determinismo 3× idêntico.

## O que mudou (técnico)

1. **`render_mode` explícito** (`_resolve_render_mode`, posts.py) — anti-P6: o modo antigo (`legacy_ai_full_art`,
   IA desenha a arte inteira) fica ISOLADO atrás de flag e não some por acidente.
   - `photo_ai_composer` (padrão): IA = só a foto, código desenha texto/logo/barra/rodapé.
   - `composer_only`: só tipografia (grátis, sem IA).
   - `legacy_ai_full_art`: modo antigo, isolado.

2. **base.png + final.png + CACHE de foto** — a foto da IA é salva como `NN_base.png`; a arte final como `NN.png`.
   `carousel_urls` (o que publica) é **só-final** — a base NUNCA publica. As bases ficam em `base_urls` (post meta).
   Re-render passando `base_urls` **reusa a foto e NÃO paga IA** (custo 0). Geração e composição foram **separadas**
   no loop (gera a foto uma vez; compõe a arte quantas vezes quiser).

3. **Botão "↻ Regerar arte (grátis)"** (apps-conteudo.jsx) — aparece nas versões feitas com IA; reusa as fotos e
   só redesenha a arte. É o "iterar arte sem pagar IA" do plano, agora visível e testável.

4. **`generate-image` invertido** (post único) — tinha o mesmo bug do carrossel (IA desenhava tudo). Agora o padrão
   é `photo_ai_composer`; o legacy fica isolado atrás de `render_mode`.

5. **Degradação graciosa** — geração e composição em try separados: 1 tela com erro cai pro editorial (grátis) e,
   no pior caso, é pulada — **nunca derruba o carrossel inteiro** (anti-P6).

## Como testar (simples)

1. **Consistência (P1):** gere um carrossel (qualquer modelo). Layout/logo/rodapé saem na mesma régua em todas as
   telas — e se gerar de novo o MESMO plano, a diagramação não "dança" (a foto muda; o resto não).
2. **Cache / custo (P5/P6):** gere uma versão com um modelo de IA → vai aparecer **"↻ Regerar arte (grátis)"**.
   Clique. Ele **reusa as mesmas fotos** e redesenha a arte com **Custo: R$ 0,00**. É a base pra iterarmos
   diagramação nos próximos marcos sem queimar dinheiro.

## Provado por mim
- `regressao_check.py`: golden verde (Marco 0 intacto).
- Determinismo: 3× o mesmo plano → bytes idênticos.
- `_resolve_render_mode` (5 casos) e `_load_upload_bytes` (hit/miss) testados no container.
