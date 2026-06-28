# Escolha inteligente de logo + retry de imagem · v1.25.81

Atende suas 2 preocupações: (1) usar a VARIANTE certa da logo (das que você cadastrou) em vez do
backing feio; (2) não deixar slide sem foto — forçar a mesma imagem antes de desistir.

## 1. Escolha inteligente de variante de logo — `template_composer.py` + `posts.py`
- `_all_raster_logos` (posts.py) passa TODAS as variantes cadastradas (branca/preta/colorida) da
  marca **e** de cada app pro compositor — antes ia só a primeira.
- `_pick_logo_variant` (composer) mede a luminância do fundo onde a logo vai e escolhe a variante
  de **melhor contraste**: branca em fundo escuro, escura/colorida em fundo claro/laranja.
- Resultado: **sem caixa/backing** quando existe variante adequada. O backing só entra como ÚLTIMO
  recurso se você só cadastrou 1 variante e ela não contrasta. Vale p/ logo da marca **e** dos apps.
- Provado (grátis): Deezer escuro limpo sobre fundo claro; CARIAP branca limpa sobre CTA laranja —
  os dois sem nenhuma caixa.

## 2. Retry da imagem (mesma, sem transbordo) — `posts.py`
- Quando a geração falha, **tenta a MESMA imagem (mesmo prompt + mesmo modelo) até 3×** antes de
  cair pro editorial. Não troca de modelo (evita custo dobrado e design inconsistente), como você pediu.
- Reduz muito o "slide sem foto".

## Rede de segurança — golden VERDE
Depois de tudo, `regressao_check.py` deu **OK nas 5 telas** (single-variant idêntico ao aprovado).
A escolha de variante só muda a saída quando há **múltiplas** variantes cadastradas (seu caso real).

## Deployado — v1.25.81 NO AR (`?v=12581`)

### Como testar
1. Garanta que a CARIAP e os apps tenham as **variantes** cadastradas (ex.: CARIAP branca + colorida;
   Deezer branca + escura). O sistema escolhe a certa por fundo.
2. Gere um carrossel: confira logo **sem caixa** em todas as telas (clara no escuro, escura no claro)
   e **menos telas sem foto**.

### Honestidade / limites
- A escolha depende das variantes existirem. Se só houver 1 e ela não contrastar num fundo, ainda
  cai no backing (último recurso) — então vale cadastrar branca+escura.
- O retry ataca o sintoma (slide sem foto). **A causa de o nano-banana falhar tanto** eu ainda não
  diagnostiquei; se falhar 3× seguidas, ainda cai pro editorial. Vale observar a taxa de falha.
- Único "transbordo" que ainda existe é a cota grátis do OmniRoute estourando dentro de
  `generate_image_with_cost` (modelo pago da mesma família). Se seu modelo é pago (nano-banana via
  PiAPI), não acontece. Posso desligar esse fallback de vez pro carrossel se você quiser.
