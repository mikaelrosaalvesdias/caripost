# Marco 0 — A hora da verdade (spike) · v1.25.77

**Objetivo do marco:** ver, uma vez, se "foto da IA + texto desenhado por código" fica bom junto — antes de construir qualquer robustez. Ataca P5 (parar de gastar à toa).

## O que foi alterado tecnicamente

Tudo num arquivo de backend: **`app/routers/posts.py`**.

1. **Nova função `_photo_only_prompt(s, brand, variant)`** ([posts.py:514](../../app/routers/posts.py#L514))
   - Pede à IA **só a fotografia** de fundo: cena realista/cinematográfica, ambiente brasileiro, luz quente.
   - **Proíbe** qualquer texto, letra, número, logo, marca ou símbolo na imagem.
   - Telas de TV/celular só com **interface abstrata/desfocada** (mata o "Movie en movie"/gibberish das amostras antigas).
   - Pede **espaço negativo** no lado onde o texto vai entrar (derivado de `layout_variant`/`text_area`) e posiciona o sujeito no lado oposto — para o recorte não cortar gente.

2. **Inversão de papéis no endpoint `render-carousel`** ([posts.py:687-690](../../app/routers/posts.py#L687-L690))
   - Antes: IA desenhava a arte **inteira** (`_full_slide_prompt`) e o código só carimbava a logo (`compose_logos_only`).
   - Agora (padrão): a foto da IA entra como **`bg_bytes`** no `compose_carousel_slide`, e o **código desenha 100%** do texto/título/corpo/barra/contador/logo/rodapé.
   - **Escape para comparar:** mandar `"composer": false` no corpo do request volta ao comportamento legado (IA desenha tudo). Default é o novo.
   - Telefone do CTA é formatado antes de ir pro composer, pra não aparecer cru (a formatação estrita definitiva é Marco 4).

3. **Bump de versão** → `v1.25.77` (`app/main.py`, `apps-manage.jsx`, `index.html ?v=12577`).

## Como isso atinge o objetivo

A pergunta do Marco 0 é "foto IA + texto código fica bom junto?". Com a inversão, é exatamente o que o `render-carousel` passa a produzir. O `_photo_only_prompt` garante que a IA entregue foto limpa (sem texto pra alucinar), e o composer determinístico desenha o resto.

## Teste que EU já fiz (antes de te pedir teste) — grátis, sem IA

Rodei o `compose_carousel_slide` localmente (PIL 10.2.0) com uma **foto placeholder** como `bg_bytes`, nos **3 tipos** de slide (capa, conteúdo, CTA):

```
slide 1 [cover  ] (1080, 1350) 61KB  OK
slide 2 [content] (1080, 1350) 70KB  OK
slide 3 [cta    ] (1080, 1350) 59KB  OK
RESULTADO: OK — composer renderiza os 3 tipos com bg_bytes
```

Olhei o slide de conteúdo: **acentos corretos** ("preço", "experiência"), hierarquia limpa (número 01 laranja / título branco bold / corpo cinza), barra de progresso e rodapé `@cariap 2/3` no lugar. Sintaxe (`py_compile`) OK nos 3 arquivos.

PNGs de prova em: `scratchpad/marco0/01_cover.png`, `02_content.png`, `03_cta.png`.

**Honesto:** isto prova **determinismo e texto limpo**, não a beleza final. O scrim está pesado (com placeholder escuro fica quase preto; com foto quente real aparece mais). O acabamento "de agência" é o **Marco 3**.

## Deployado — v1.25.77 NO AR (confirmado `?v=12577`)

`docker build` + `docker service update --image metaporn-new:1.25.77 metaporn-new_adult-meta` → serviço convergiu → site live serve `?v=12577`.

### Como testar (avalie SÓ o que o Marco 0 entrega)
1. Abre o Caripost → **Conteúdo → Carrossel** → escolhe **CARIAP** e um tema.
2. Gera o briefing e manda **renderizar** com o modelo de imagem (nano-banana).
3. Avalie **apenas**:
   - O **texto** está limpo, legível e **no mesmo lugar/padrão** em todas as telas? (era a IA desenhando torto; agora é o código)
   - A **logo da marca** fica na **mesma posição** entre as telas?
   - As telas têm a **mesma régua** (barra de progresso, número, rodapé `@handle x/y`)?

**NÃO avaliar agora** (não é deste marco): mesma família/pessoas e coesão entre as fotos (Marco 3/5); acabamento fino de agência (Marco 3); logo sumindo por cor de fundo (Marco 2); telefone/copy longa (Marco 4).
