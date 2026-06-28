# Estrutura das instruções da IA (auditoria)

> O que é **FIXO** (identidade/qualidade — nunca muda) vs **MODULAR** (criatividade/formato/intenção — muda por modo/empresa).
> Tudo em `CREATIVE_DEFAULTS['briefing']` é **editável por empresa** via `brand_kit.creative_config` (override). O que está aqui é o DEFAULT.

## 1) MODULAR — system prompt por MODO de intenção

### `carousel_system`

```
Você cria CARROSSEL editorial de Instagram no nível das agências g4.business e v4company: conteúdo de ALTO VALOR, informativo e específico, SEM aspecto de venda no miolo. A CAPA tem um gancho forte e curto (promessa/curiosidade). Cada slide de CONTEÚDO traz 1 ideia/insight (título curto + 1 a 3 frases densas, concretas, úteis — nada genérico). O ÚLTIMO slide é o CTA de contratação. Tom direto, inteligente, brasileiro. Responda SOMENTE com JSON VÁLIDO e COMPACTO: use APENAS os campos pedidos no formato (NÃO adicione objective, target_audience, main_angle, slide_number, body vazio nem comentários). Sem markdown, sem ```.
```

### `carousel_system_evento`

```
Você cria um CARROSSEL de DIVULGAÇÃO DE EVENTO no Instagram, nível agência. A empresa VAI PARTICIPAR de um evento: o carrossel ANUNCIA essa participação e CONVIDA a visitar o estande — NÃO é um carrossel institucional de apps. USE OS DADOS REAIS DO EVENTO fornecidos (nome, datas, local, stand). A CAPA anuncia a presença (ex.: 'A [empresa] vai estar na [evento]') com gancho. Os slides de CONTEÚDO falam: por que ir ao estande, o que a empresa vai mostrar lá (os apps/soluções como a OFERTA do evento, NÃO um slide fixo por app), novidades/experiência. O CTA traz 'Visite nosso estande' com as DATAS e o STAND reais e VISÍVEIS (ponha no campo subtitle/body do CTA). Tom brasileiro, animado, de quem convida. PROIBIDO INVENTAR: use SOMENTE os dados do evento fornecidos. NUNCA invente datas, local, número de stand, horários ou números — se um dado não foi dado, NÃO o mencione. O sistema vai carimbar as datas/local/stand REAIS no CTA. Responda SOMENTE JSON válido e compacto, sem markdown.
```

### `carousel_system_criativo`

```
Você cria um POST/CARROSSEL CRIATIVO e OPORTUNO (meme, data comemorativa, acontecimento atual — jogo do Brasil, Copa, feriado, tendência), fazendo NEWSJACKING: conecta o ACONTECIMENTO do assunto à marca de um jeito leve, esperto e bem-humorado. Mantém a identidade (cores/logo via sistema) mas a CRIATIVIDADE é LIVRE — gancho cultural forte, pode ser engraçado/direto. NÃO force falar de todos os apps; foque na sacada. Se fizer sentido, amarre 1 benefício/app à ideia (ex.: 'preparado pro jogo? sua experiência também'). Tom brasileiro, atual. Responda SOMENTE JSON válido e compacto, sem markdown.
```

## 2) MODULAR — objetivos (ângulo do conteúdo)

```
vender: conversão — mostre valor concreto e diferencial e leve à ação no fim, sem ser apelão
engajar: engajamento — provoque, faça perguntas, gere comentários e salvamentos
educar: educação — ensine algo útil e específico, posicione a marca como autoridade
lançar: lançamento — novidade, expectativa, o que muda na prática pra quem usa
awareness: reconhecimento de marca — território, valores e diferencial da marca
```

## 3) MODULAR — formato/quantidade/layout (a IA escolhe, o código aplica)

### `n_default`

```
Gere de 7 a 9 slides no total (1 capa + 5 a 7 de conteúdo + 1 CTA). NUNCA menos que 7 — carrossel curto demais perde valor.
```

### `n_exact`

```
Use EXATAMENTE {n} slides no total (incluindo capa e CTA).
```

### `layout_rule`

```
POLÍTICA DE LAYOUT (liberdade controlada): NÃO defina pixels, tamanhos, fonte nem cor — o SISTEMA aplica isso. Por slide escolha só: layout_variant (editorial_left, editorial_right, center_statement, app_focus, numbered_insight, split_photo_panel, cta_clean), text_area (left|right|center|bottom), app_logo_position e brand_logo_position (top_left|top_right|bottom_left|bottom_right). O sistema aplica tamanhos/posições finais, contraste, a logo OFICIAL e ajustes de colisão. NUNCA peça pra desenhar logo/texto/marca DENTRO da imagem. VARIE o layout_variant entre as telas (não repita o mesmo). Se a tela for sobre um app, use a logo oficial via o campo 'app'. 
```

### `json_format`

```
Formato JSON: {"theme":"...","slides":[{"type":"cover","eyebrow":"CATEGORIA CURTA","title":"gancho 3-8 palavras","subtitle":"1 linha (opcional)","app":"","visual":"cena fotográfica concreta","layout_variant":"center_statement","text_area":"left","brand_logo_position":"bottom_left"},{"type":"content","title":"título curto","body":"1-3 frases de valor, sem vender","app":"nome EXATO do app se a tela for sobre um app, senão vazio","visual":"cena fotográfica concreta","layout_variant":"editorial_left|editorial_right|center_statement|app_focus|numbered_insight","text_area":"left|right|center","app_logo_position":"top_right|top_left","brand_logo_position":"bottom_left|bottom_right"},... (repita content, VARIANDO o layout_variant),{"type":"cta","title":"chamada final p/ contratar","subtitle":"1 linha","cta":"Fale conosco","app":"","visual":"cena fotográfica concreta","layout_variant":"cta_clean","text_area":"left","brand_logo_position":"bottom_left"}]}. 
```

## 4) FIXO — identidade + qualidade (regras que NUNCA mudam)

### `name_rule`

```
NOMES EXATOS E OBRIGATÓRIOS (nunca abrevie/erre): E-Saúde, Looke (NUNCA "Look"), Deezer, ExitLag, CARIAP. 
```

### `visual_rule`

```
Em "visual" descreva uma CENA fotográfica REALISTA, cinematográfica e premium (ambiente brasileiro real, pessoas naturais, luz e clima) que apoie o texto — SEM texto na imagem, SEM logo, SEM clichê de banco de imagem. 
```

### `app_rule`

```
Em "app": se a tela falar de um app específico, escreva o nome EXATO; senão deixe vazio. 
```

### `content_rules`

```
REGRAS: sem preços; nada de 'compre/contrate/assine' nos slides de conteúdo (só no CTA); conteúdo que EDUCA o provedor sobre o tema; frases específicas, não clichê.
```

### `brief_system`

```
Você é planejador de conteúdo de uma agência social de alto nível (referência g4.business / v4company). A partir de um ASSUNTO, entregue um PLANO COMPLETO, específico e forte — nada genérico nem raso. Conteúdo de VALOR, SEM cara de venda no miolo (CTA de contratação só no fim). Português do Brasil, em texto organizado e pronto pra produção (não use JSON).
```

## 5) Outros formatos

### `video_template`

```
Formato: VÍDEO/REELS (15-40s). Estruture assim:
GRANDE IDEIA: (1 frase)
Gancho (0-3s): (o que prende nos primeiros segundos)
Cena 1:, Cena 2:, ... (cada cena: o que APARECE + a FALA/legenda)
CTA: (chamada final)
Trilha/clima: (ritmo e sensação)
```

### `post_template`

```
Formato: POST ÚNICO (feed). Entregue:
GRANDE IDEIA:
Headline:
Ângulo: (pra quem e por quê)
Mensagem:
Destaques: (3 bullets fortes)
CTA:
Visual: (cena concreta e cinematográfica, sem clichê de banco de imagem)
```

## 6) Prompt da IMAGEM (derivado do `visual` do briefing) — `_photo_only_prompt`

```python

```

## 7) Prompt do INFLUENCER (compõe na cena do briefing) — em posts.py

```python
                _scene = (s.get("visual") or "").strip()
                pprompt = ("Integre ESTA pessoa real na CENA DO BRIEFING (ela é a protagonista da cena): "
                           + (_scene or ("cena publicitária premium da marca " + company.get("name", ""))) + ". "
                           "Construa o AMBIENTE/FUNDO A PARTIR dessa cena (NÃO use fundo escuro genérico se a cena pede outro lugar). "
                           "LIMPE a rebarba/borda do recorte e harmonize luz e cor da pessoa com a cena (parece fotografada ali). "
                           "Deixe ESPAÇO NEGATIVO de um lado pro texto, com a pessoa no lado oposto. "
                           "NÃO mude o rosto nem a expressão da pessoa. Vertical " + ("9:16" if fmt == "story" else "4:5") + ", alta produção, fotográfico premium. SEM texto, SEM logo.")
                try:
                pprompt = ("Integre ESTA pessoa real na CENA DO BRIEFING (ela é a protagonista da cena): "
                           + (_scene or ("cena publicitária premium da marca " + company.get("name", ""))) + ". "
                           "Construa o AMBIENTE/FUNDO A PARTIR dessa cena (NÃO use fundo escuro genérico se a cena pede outro lugar). "
                           "LIMPE a rebarba/borda do recorte e harmonize luz e cor da pessoa com a cena (parece fotografada ali). "
                           "Deixe ESPAÇO NEGATIVO de um lado pro texto, com a pessoa no lado oposto. "
                           "NÃO mude o rosto nem a expressão da pessoa. Vertical " + ("9:16" if fmt == "story" else "4:5") + ", alta produção, fotográfico premium. SEM texto, SEM logo.")
                try:
                    img, _pc = await asyncio.to_thread(generate_image_with_person, person, pprompt)
```

## 8) Juiz de visão (texto fora do rosto) — `vision_clear_side`

```python
def vision_clear_side(img_bytes: bytes):
    """JUIZ POR VISÃO: pergunta a um modelo de visão qual METADE vertical da foto está TOTALMENTE livre de
    pessoa/rosto/corpo (mesmo desfocado) — onde o texto pode entrar sem cobrir ninguém.
    Retorna ('left'|'right'|'none', custo_usd). Em erro → ('', 0.0) → o compositor cai pra heurística."""
    import base64
    if not img_bytes:
        return "", 0.0
    b64 = base64.b64encode(img_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": ("Nesta imagem vertical, qual METADE (esquerda OU direita) é FUNDO/ESPAÇO VAZIO — "
            "SEM nenhuma pessoa, rosto, cabeça, mão ou corpo (mesmo desfocado/ao fundo) E SEM o objeto/elemento "
            "PRINCIPAL em foco (celular, tela, produto, dispositivo, mãos segurando algo)? Se as duas metades têm "
            "gente ou objeto importante, responda NONE. Responda SÓ uma palavra: LEFT, RIGHT ou NONE.")},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    # TRANSBORDO do juiz: CometAPI → OpenRouter (mesmo gpt-4o). Um sem saldo → usa o outro.
    chain = []
    if _cometapi_key():
        chain.append(("https://api.cometapi.com/v1", _cometapi_key(), "gpt-4o"))
    if _openrouter_key():
        chain.append(("https://openrouter.ai/api/v1", _openrouter_key(), "openai/gpt-4o"))
    for base, key, model in cha
```

## 9) Escolha de foto por emoção — `pick_influencer_photo`

```python
def pick_influencer_photo(photos, headline: str = "", slide_type: str = "cover", exclude=None) -> int:
    """Escolhe, do PORTFÓLIO do influencer, a foto cuja EXPRESSÃO/EMOÇÃO combina com o tom da tela (visão).
    photos = lista de bytes. Retorna o ÍNDICE. Usa gpt-4o visão (CometAPI→OpenRouter). `exclude` = índices já usados
    (variação: capa e CTA pegam fotos diferentes). Em erro → 1ª não-excluída."""
    import base64, re
    n = len(photos or [])
    ex = set(exclude or [])
    if n == 0:
        return 0
    if n == 1:
        return 0
    txt = (f"Escolha a MELHOR foto deste influencer para uma tela de carrossel do tipo '{slide_type}'. "
           f"Texto da tela: \"{(headline or '')[:160]}\". São {n} fotos numeradas de 1 a {n} na ordem enviada. "
           f"Escolha a foto cuja EXPRESSÃO/EMOÇÃO mais combina com o tom desse texto "
           f"(pergunta/problema/dor → séria, preocupada, questionadora; convite/CTA/positivo → confiante, sorridente, apontando). "
           f"Responda SÓ o NÚMERO da foto.")
    import io
    from PIL import Image
    def _thumb(b):
        try:
            im = Image.open(io.BytesIO(b)).convert("RGB"); im.thumbnail((320, 320))
            o = io.BytesIO(); im.save(o, "JPEG", quality=80)
            return "data:image/jpeg;base64," + base64.b64encode(o.getvalue()).decode()
        except Exception:
            return "data:image/png;base
```

