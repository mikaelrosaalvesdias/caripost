# Entregável 0 — fundação MOLDÁVEL + conserto do CTA · v1.25.80

Atende seu ponto: construir LÓGICA configurável, não travar design (é SaaS multi-empresa). E feito
com a rede de segurança (golden) provando que não quebrou o que já estava aprovado.

## O que mudou

### 1. Layout virou DESIGN TOKENS (moldável por empresa) — `template_composer.py`
O que estava hardcodado agora é token no `EDITORIAL_DESIGN`, com **default = o visual aprovado**,
**sobrescrevível por empresa** via `creative_config.design` (o motor já fazia o merge em `_design`):
- `content.align`: `left` (padrão) | `center` | `right` — alinhamento do texto, **igual em todas as
  telas da empresa** (consistência), mas configurável por cliente.
- `app_logo.pos`: `top_right` (padrão) | `top_left`; `app_logo.on_all`: `false` (padrão).
- `footer.logo_pos`: `bottom_left` (padrão) | `bottom_right` | `bottom_center`;
  `footer.logo_contrast`: `auto`; `footer.show_handle`/`show_counter`: `true`.

Princípio: **mesmo motor, config por empresa**. Empresa A molda do jeito A, B do jeito B, cada uma
coesa internamente. Nada travado.

### 2. Conserto do CTA (slide 7) — logo da marca não some mais
`_place_brand_logo` com contraste **auto**: mede a luminância do fundo atrás da logo e, se o
contraste for baixo em **qualquer cor** (ex.: logo laranja sobre CTA laranja), põe um **backing
suave borrado** (sem caixa dura) pra logo aparecer. Resolve o "logo ausente" do slide 7.

### 3. Toggle "app em todas as telas" — `posts.py`
`app_logo.on_all=true` repete a logo do app em todas as telas (carrossel de marca única). Default
off (logo só nas telas que citam o app, como hoje).

## Rede de segurança — PROVA de que não quebrei o aprovado
Rodei `docs/marcos/regressao_check.py` depois de TODA a refatoração: as **4 telas aprovadas
continuaram com hash IDÊNTICO** (`143c2d35…`, `4b555c0d…`, `78d70125…`, `152a946b…`); só entrou o
caso novo `cta_laranja`. Baseline travado com `--update`. Backup do código em
`docs/marcos/backups/`.

## Deployado — v1.25.80 NO AR (`?v=12580`)

### Como testar
1. Caripost → **Conteúdo → Carrossel** → CARIAP + tema → renderizar.
2. Avalie: **slide CTA** com a logo da CARIAP **visível** (mesmo no fundo laranja); resto coeso.
3. (Opcional, p/ ver moldável) dá pra setar `creative_config.design` da empresa, ex.:
   `{"content":{"align":"center"},"footer":{"logo_pos":"bottom_right"}}` → muda o layout SEM tocar
   no código, igual em todas as telas.

### Ainda fora deste entregável
Coesão/mesma família das fotos (Marco 3/5); copy longa/telefone estrito (Marco 4); editor visual
desses tokens na UI (futuro).
