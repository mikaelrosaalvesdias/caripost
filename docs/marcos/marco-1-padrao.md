# Marco 1 — PADRÃO (posição travada) · v1.25.78

**Objetivo:** resolver P1 ("sem padrão") e P6 ("arruma um, quebra outro") — toda tela de conteúdo nasce da mesma régua. Este incremento entrega o item mais visível: **a posição do texto parou de variar**.

## O que foi alterado tecnicamente

Arquivo: **`app/services/template_composer.py`**, em `compose_carousel_slide`.

1. **Alinhamento travado** (antes ~linha 404): o `c_align` deixou de ser derivado do `layout_variant`/`text_area` (que mudava o texto de canto a cada slide) e passou a ser **sempre `"left"`** para conteúdo.

2. **Régua vertical travada** (ramo `content`): removida a variação por `layout_variant` (`center_statement` subia o título, `app_focus` deslocava, alguns slides escondiam o número). Agora **todo slide de conteúdo** desenha: número (top-left) → título (em `title_y`) → corpo (logo abaixo), **na mesma posição**. Só a foto muda.

Causa do problema: o `generate_carousel` varia o `layout_variant` por slide e o composer honrava isso → cada tela em um canto. O sistema agora **governa a consistência**, não o modelo.

## Como isso atinge o objetivo

P1/P6: com a posição fixa, 5 telas de conteúdo têm título/corpo/número **no mesmo lugar**; mexer numa não muda a outra. A variedade fica por conta da foto (Marco 3/5), não da posição do texto.

## Teste que EU já fiz (grátis, sem IA)

Rodei 4 telas de conteúdo com `layout_variant` **diferentes** (`editorial_left`, `editorial_right`, `center_statement`, `app_focus`) e `text_area` alternado. **Olhei** `editorial_right` e `app_focus`: ambos saíram com número top-left + título/corpo à esquerda na **mesma posição**. Antes, `editorial_right` iria pra direita e `app_focus` subiria o título. `py_compile` OK. PNGs em `scratchpad/marco1/`.

## Deployado — v1.25.78 NO AR (confirmado `?v=12578`)

### Como testar (avalie SÓ o que ESTE marco entrega)
1. Caripost → **Conteúdo → Carrossel** → CARIAP + um tema → renderizar (nano-banana).
2. Avalie **apenas**: o **texto** (número/título/corpo) está **na mesma posição** em todas as telas de conteúdo? A régua é a mesma?

**NÃO é deste incremento:** logo Deezer com caixa preta (Marco 2); coesão/mesma família das fotos (Marco 3/5); copy longa/telefone (Marco 4).

## Ainda pendente DENTRO do Marco 1 (próximo incremento)
- `render_mode` explícito + isolar legado (anti-P6, rollback).
- `base.png`/`final.png` separados + `carousel_urls` só-final + cache.
- Rodapé/telefone com degradação graciosa.
- Aceite final do Marco 1: render 3× com texto congelado → layout idêntico por bbox.
