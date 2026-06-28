# Caripost — Pipeline de Produção de Arte (ponta a ponta)

> Documento fiel ao código em produção (deploy **v1.25.76**). Cobre TODA a lógica e TODOS os prompts/regras
> usados para gerar briefing → arte (post/carrossel) → compositing → persistência → publicação.
> Arquivos: `app/services/ai.py`, `app/routers/posts.py`, `app/services/template_composer.py`, `app/os/apps-conteudo.jsx`.

---

## 0. Modelos e custo

**Texto (briefing/carrossel/copy):** OmniRoute (gateway OpenAI-compat, grátis via assinatura do user).
- Default: `provider=omniroute`, `model=cc/claude-opus-4-8`.
- Chamada em `complete_ai()` → `_call_openai_compat()` com `stream:false` + `resp.json()` (UTF-8 ok).
- OmniRoute **preserva acentos** (testado). Quando o briefing sai sem acento é **variância do modelo**, não do gateway.

**Imagem:** **PiAPI apenas** (4 modelos no seletor). Chave PiAPI criptografada nos settings.
`_CURATED_PIAPI` (id → nome → preço USD):
| id | modelo | USD/img |
|---|---|---|
| `piapi:gpt-image-2` | gpt-image-2 (medium) | 0.04 |
| `piapi:chatgpt-hifi` | ChatGPT Image high-fidelity | 0.08 |
| `piapi:gemini-3-pro-2k` | Gemini 3 Pro Image (2K) | 0.06 |
| `piapi:nano-banana-2` | Gemini 3.1 Flash (nano-banana-2) | 0.04 |

`_PIAPI_MODELS` (roteamento interno):
```
gpt-image-2     -> ('gpt-image-2','medium','openai')      # LLM API  /v1/images/generations
chatgpt-hifi    -> ('chatgpt-image-latest-high-fidelity',None,'openai')
gemini-3-pro-2k -> ('gemini','nano-banana-pro','gemini')  # TASK API create->poll
nano-banana-2   -> ('gemini','nano-banana-2','gemini')    # TASK API create->poll
```
- **kind=openai** → `generate_image_openai_direct(base="https://api.piapi.ai/v1", quality=arg2)` síncrono (`/images/generations`). gpt-image-2 ~55s.
- **kind=gemini** → TASK API assíncrona (`model="gemini"`, `task_type=...`, poll ~300s). nano-banana-2 ~30s, mais robusto pra carrossel grande.
- Roteador: `generate_image_with_cost(prompt, size, ref_images, model_override)` → se `model_override` começa com `piapi:` chama `generate_image_piapi`.
- Tamanho enviado ao modelo: **`"1024x1536"`**. Canvas final do compositor: **1080×1350 (4:5)**.
- Custo em BRL: `usd_to_brl(usd)` lê `fx.usd_brl`. Mostrado como R$.

---

## 1. ETAPA 1 — Briefing (texto)

`generate_briefing(company, theme, objetivo, formato, n_telas)` e, para carrossel, `generate_carousel(company, theme, n_slides)`.
Config aberta por cliente em `ai.BRIEFING_GEN` (override em `brand_kit.creative_config`).

**System (carrossel) — `carousel_system`:**
```
Você cria CARROSSEL editorial de Instagram no nível das agências g4.business e v4company: conteúdo de ALTO
VALOR, informativo e específico, SEM aspecto de venda no miolo. A CAPA tem um gancho forte e curto
(promessa/curiosidade). Cada slide de CONTEÚDO traz 1 ideia/insight (título curto + 1 a 3 frases densas,
concretas, úteis — nada genérico). O ÚLTIMO slide é o CTA de contratação. Tom direto, inteligente, brasileiro.
Responda SOMENTE com JSON VÁLIDO e COMPACTO: use APENAS os campos pedidos no formato (NÃO adicione objective,
target_audience, main_angle, slide_number, body vazio nem comentários). Sem markdown, sem ```.
```

**User montado:** Empresa + público (`brand_kit.audience`) + tema + (n_exact OU n_default) + (client_rules) + as regras abaixo concatenadas:

- **n_exact:** `Use EXATAMENTE {n} slides no total (incluindo capa e CTA).`
- **n_default:** `Gere de 7 a 9 slides no total (1 capa + 5 a 7 de conteúdo + 1 CTA). NUNCA menos que 7 — carrossel curto demais perde valor.`
- **json_format:**
```json
{"theme":"...","slides":[
 {"type":"cover","eyebrow":"CATEGORIA CURTA","title":"gancho 3-8 palavras","subtitle":"1 linha (opcional)","app":"","visual":"cena fotográfica concreta","layout_variant":"center_statement","text_area":"left","brand_logo_position":"bottom_left"},
 {"type":"content","title":"título curto","body":"1-3 frases de valor, sem vender","app":"nome EXATO do app se a tela for sobre um app, senão vazio","visual":"cena fotográfica concreta","layout_variant":"editorial_left|editorial_right|center_statement|app_focus|numbered_insight","text_area":"left|right|center","app_logo_position":"top_right|top_left","brand_logo_position":"bottom_left|bottom_right"},
 ... (repita content, VARIANDO o layout_variant),
 {"type":"cta","title":"chamada final p/ contratar","subtitle":"1 linha","cta":"Fale conosco","app":"","visual":"cena fotográfica concreta","layout_variant":"cta_clean","text_area":"left","brand_logo_position":"bottom_left"}]}
```
- **layout_rule:** `POLÍTICA DE LAYOUT (liberdade controlada): NÃO defina pixels, tamanhos, fonte nem cor — o SISTEMA aplica isso. Por slide escolha só: layout_variant (editorial_left, editorial_right, center_statement, app_focus, numbered_insight, split_photo_panel, cta_clean), text_area (left|right|center|bottom), app_logo_position e brand_logo_position (top_left|top_right|bottom_left|bottom_right). O sistema aplica tamanhos/posições finais, contraste, a logo OFICIAL e ajustes de colisão. NUNCA peça pra desenhar logo/texto/marca DENTRO da imagem. VARIE o layout_variant entre as telas (não repita o mesmo). Se a tela for sobre um app, use a logo oficial via o campo 'app'.`
- **visual_rule:** `Em "visual" descreva uma CENA fotográfica REALISTA, cinematográfica e premium (ambiente brasileiro real, pessoas naturais, luz e clima) que apoie o texto — SEM texto na imagem, SEM logo, SEM clichê de banco de imagem.`
- **app_rule:** `Em "app": se a tela falar de um app específico, escreva o nome EXATO; senão deixe vazio.`
- **name_rule:** `NOMES EXATOS E OBRIGATÓRIOS (nunca abrevie/erre): E-Saúde, Looke (NUNCA "Look"), Deezer, ExitLag, CARIAP.`
- **content_rules:** `REGRAS: sem preços; nada de 'compre/contrate/assine' nos slides de conteúdo (só no CTA); conteúdo que EDUCA o provedor sobre o tema; frases específicas, não clichê.`

**Objetivos (`objetivos`)** ligam ao seletor Objetivo: vender / engajar / educar / lançar / awareness.

**Formatos não-carrossel** (`generate_briefing`, system `brief_system`, texto livre, sem JSON):
- **post_template:** GRANDE IDEIA / Headline / Ângulo / Mensagem / Destaques (3 bullets) / CTA / Visual.
- **video_template:** GRANDE IDEIA / Gancho (0-3s) / Cena 1..N (o que aparece + fala) / CTA / Trilha-clima.

**Pós-processamento (`generate_carousel`):** `extract_json()` (json.loads, preserva acento) → para cada slide aplica `_canon_app_names()` em title/body/subtitle/eyebrow/cta/app; numera os `content`; garante slide[0]=cover e slide[-1]=cta; valida `layout_variant` contra os permitidos; default por tipo. `max_tokens=4096`, 1 retry se vier vazio, erro se persistir.

**`_canon_app_names` / `_APP_CANON` (regex IGNORECASE):**
```
e[\s\-]?s[aáàâ]ude   -> E-Saúde
\blooke?\b           -> Looke
\bdeezer\b           -> Deezer
\bexit[\s\-]?lag\b   -> ExitLag
\bcariap\b           -> CARIAP
```
(Só troca nomes de app — NÃO mexe em acento do resto do texto.)

---

## 2. ETAPA 2 — Perfis (templates) por contexto

`ai.IMAGE_TEMPLATES` (defaults globais) + `creative_config.templates[tipo]` (salvos por cliente).
Tipos: **carrossel**, **post**, **video**. Cada perfil = `{id, name, variant(escuro|claro), structure}`.
A `structure` é injetada como diagramação TRAVADA no prompt da imagem (consistência).

CRUD (maleável, por cliente): `GET /api/posts/image-templates`, `POST /api/posts/save-template`, `POST /api/posts/delete-template`. UI: chips "Perfil visual" + botão "+ Salvar como perfil" (componente `PerfilSaver`) em Criação → Carrossel e Post.

**Estruturas default (verbatim):**

`editorial-escuro` (`_T_EDITORIAL_ESCURO`):
```
ESTRUTURA FIXA (siga EXATAMENTE, IDÊNTICA em todas as telas): fundo ESCURO (preto/grafite) com leve
brilho/textura laranja. Topo (~16% da altura): área escura sólida e LIMPA, reservada para a logo (não desenhe
nada nela). TÍTULO: grande, negrito forte, alinhado À ESQUERDA, no terço superior; palavras-chave em laranja,
o resto em branco. TEXTO DE APOIO: menor, embaixo À ESQUERDA, com uma BARRA VERTICAL laranja à esquerda.
FOTO: cena fotográfica cinematográfica realista (pessoas/ambiente brasileiro real) ocupando o lado DIREITO e a
parte de baixo, fundida ao fundo escuro com gradiente. Diagramação IGUAL em todas as telas — muda só a foto e o texto.
```

`editorial-claro` (`_T_EDITORIAL_CLARO`): idem, fundo CLARO (branco/cinza-claro), título em grafite escuro + palavras-chave laranja, luz clara.

`video` defaults: `dinamico-escuro` (`_T_VIDEO_DINAMICO`) e `clean-claro` (`_T_VIDEO_CLEAN`) — vídeo 9:16, gancho 3s, color grading, faixa topo p/ logo. *(Geração de vídeo ainda não ligada.)*

---

## 3. ETAPA 3 — Geração da ARTE (prompt da imagem)

Endpoints: `POST /api/posts/render-carousel` (uma versão = todas as telas) e `POST /api/posts/generate-image` (post único). Ambos:
1. Carregam o perfil: `tmpl = image_template_get(company, tipo, template_id)` → `structure` + `variant`.
2. Montam o prompt por tela: `_full_slide_prompt(s, brand_color, brand_name, structure, variant)`.
3. Geram com o modelo escolhido (`generate_image_with_cost(prompt,"1024x1536",None,model)`). `editorial` (sem modelo) = fallback PIL grátis.
4. Compositam logos (e rodapé no CTA). Salvam em `UPLOAD_DIR/<company>/carousel/<hex>/NN.png`.

**`_full_slide_prompt` — texto EXATO enviado ao modelo de imagem** (montado por partes):
```
Crie a ARTE COMPLETA e FINAL de UM slide de carrossel premium de Instagram, vertical 4:5 (1080x1350),
nível de agência top. Marca: {BRAND} (B2B brasileiro, SVAs para provedores de internet).
{STRUCTURE do perfil — ou, se sem perfil: "Tipografia forte, hierarquia clara, alto contraste, layout
   moderno e editorial, liberdade criativa elegante."}
{TRAVA DE FUNDO conforme variant:
   escuro -> "FUNDO OBRIGATÓRIO grafite escuro uniforme, quase preto (#141418), em TODA a arte — idêntico em
              todas as telas. Iluminação quente sutil e cinematográfica. MESMA paleta, MESMA temperatura de
              cor e MESMA grade de cor em todas as telas; MESMO enquadramento e MESMA escala dos elementos
              (não aproxime nem afaste de uma tela pra outra). "
   claro  -> "FUNDO OBRIGATÓRIO claro off-white uniforme (#F2F2F0) ... Luz natural suave e neutra. " + (mesma
              trava de paleta/temperatura/escala) }
TÍTULO em DESTAQUE, grande e perfeitamente legível: "{TITLE}".
{EXTRA: se NÃO for CTA e tiver body -> 'Texto de apoio menor (legível): "{BODY}".'
        se for CTA e tiver cta      -> 'Chamada final curta e forte no centro: "{CTA}".'}
Cores da marca: destaque {COLOR} + escuros/neutros sofisticados.
Texto em PORTUGUÊS DO BRASIL com TODOS os acentos CORRETOS (ã õ ç á é í ó ú â ê à) — NUNCA escreva palavra sem
acento (ex.: experiência, família, não, só, preço, também, música, conexão, público).
Foto/arte premium real (nada de cara de IA/cartoon/3D barato).
DEIXE a faixa do TOPO (~16% da altura) TOTALMENTE LIMPA (sem texto e sem nada) — a logo oficial é carimbada
pelo sistema. NÃO desenhe NENHUM logo, marca, símbolo, ícone de app, nem a palavra 'logo', em lugar ALGUM da arte.
{SE CTA: "DEIXE a faixa de BAIXO (~26% da altura) LIMPA, sem texto — uma barra de contato é aplicada pelo
   sistema; NÃO escreva telefone, WhatsApp, site nem 'fale conosco'. "}
Cena de base: {VISUAL}. Sem marca d'água.
```
Princípio: **a IA cria a arte INTEIRA**; topo (e base no CTA) ficam limpos; logo/rodapé entram por código.
A IA **não recebe a logo** como referência (quando recebia, inventava um placeholder "Logo").

---

## 4. ETAPA 4 — Compositing (código, PIL) — `template_composer.py`

Canvas: `W,H = 1080,1350`. `_cover()` recorta a arte da IA pro 4:5.

**`compose_logos_only(img, company_logo_path, app_logo_path, colors)`** — modo IA-livre:
- Recorta pro 4:5.
- **Logo primária** (app se a tela for de app; senão a da empresa) **PURA** (transparente, **SEM painel/fundo**), centralizada no topo (`y=52`, máx 320×104).
- Se app **E** empresa: logo da empresa pequena (máx 150×46) **PURA** no rodapé-centro.
- *(Mudança v1.25.76: removido o chip/painel atrás da logo — antes punha caixa cinza/branca que invertia de cor.)*

**`compose_cta_footer(img, company_logo_path, site, phone, colors)`** — só na tela CTA:
- Painel arredondado **OPACO** `fill=(16,15,14,255)`, contorno laranja, `bh=188, mx=48, my=48`, no rodapé.
- Logo da empresa à esquerda; à direita "FALE CONOSCO NO WHATSAPP:" + telefone em laranja.
- Telefone formatado dos dígitos: 11 díg → `(XX) XXXXX-XXXX`; 10 díg → `(XX) XXXX-XXXX`; outro tamanho → mostra cru.

**`compose_carousel_slide(...)`** — render editorial 100% PIL (Poppins embutida), **grátis**. É o fallback quando se escolhe "editorial" OU quando o modelo de imagem falha. Desenha tudo por código (título, barra laranja, foto, logo, rodapé).

Logos oficiais: `asset_list_logos(company_id[, product_id])` + `_first_raster_logo()`. App logo casa pelo campo `app` da tela (ou nome no título) → asset do produto.

---

## 5. ETAPA 5 — Persistência, Aprovação, Publicação

- **Persistência (v1.25.74):** `render-carousel` cria um **POST DRAFT** na hora (`media_url`=capa, `meta={content_type:'carousel', carousel_urls:[...], model, template_id}`) e retorna `post_id`. Garante que a arte não some + aparece em Arquivos/Aprovação. No frontend os `results` também ficam em `ContState`.
- **Aprovação:** "Enviar esta versão → Aprovação" → `transitionPost(post_id,'REVIEW')` (promove o DRAFT, sem duplicar). StepAprovação lista posts REVIEW/DRAFT.
- **Publicação (Composio):** `StepAgenda.doPublish` detecta `meta.content_type==='carousel'` → envia `carousel_urls`. `composio_provider._publish_instagram` auto-detecta `len(media_urls)>1` → cria container por slide (`is_carousel_item`) + container `CAROUSEL` + publish.

---

## 6. Fluxo no Frontend (`apps-conteudo.jsx`)

Passos: Cliente → Briefing → Criação → Aprovação → Agendamento.
- **Briefing:** chips de assunto + seletor de Formato (Carrossel/Post/Vídeo) → `generateBriefing` → guarda `{briefing, telas, formato}` em ContState.
- **Criação ADAPTA por formato:** carrossel → `CarrosselCreator` (mostra as telas do plano, sem selecionar app, seletor de modelo por versão + perfil + "Salvar como perfil"; modal estilo Instagram ◀▶). Post → `StepCriacaoPost` (apps + peças + modelo por peça + perfil).
- Custo em R$ por versão; falha de imagem retorna `warning` (nunca cai silenciosa).

---

## 7. PONTOS ABERTOS / BUGS CONHECIDOS (honesto, em 24/06/2026)

1. **Fundo cinza atrás da logo (recorrente):** resolvido no código em v1.25.76 (`compose_logos_only` agora cola a logo PURA, sem painel). Se ainda aparecer cinza, é (a) cache do bundle antigo, ou (b) a própria arte da IA com um retângulo claro no topo.
2. **Tela fora de padrão entre si (cor/temperatura/escala):** mitigado por trava de fundo+paleta+temperatura+escala no prompt (v1.25.76), mas **nano-banana-2 gera cada tela independente** → ainda há variância. Para padrão real, avaliar gerar com referência da 1ª tela ou um modelo que aceite style-lock.
3. **Rodapé só na tela de CTA (por design):** as telas de conteúdo não têm rodapé de contato — só a última (CTA). Se a regra for "rodapé em todas", precisa mudar `render-carousel` pra aplicar `compose_cta_footer`/assinatura em todas.
4. **Título sumindo no CTA:** ao reservar topo (16%) + base (26%), o modelo às vezes larga o TÍTULO da tela CTA. Pendente: forçar o título no CTA.
5. **Telefone errado no rodapé:** vem do **cadastro do cliente** (`company.phone`), que está com número torto na CARIAP. Corrigir no cadastro → formata sozinho.
6. **Acento intermitente no texto do plano:** o modelo às vezes devolve sem acento (a imagem corrige; o texto do plano não). Pendente: passe determinístico de acentuação OU 2ª chamada "corrija a acentuação".
7. **Logo de app fraca (ex.: Looke saiu pequeno):** depende do **asset cadastrado** do app — subir versão melhor.

---

## 8. Versões / Deploy

- Deploy: `docker build -t metaporn-new:<v> .` + `docker service update --image metaporn-new:<v> metaporn-new_adult-meta`. NUNCA `deploy.sh`.
- **3 strings de versão** (bump com regex que casa qualquer valor, senão falha em silêncio): `app/main.py` `version=`; `app/os/apps-manage.jsx` `MP_OS_VERSION` (aparece em Settings); `app/os/index.html` `?v=NNNNN` (cache-bust dos .jsx).
- Origem servida direto por uvicorn, `cache-control: no-cache`, **sem CDN**. Conferir pós-deploy: `GET https://caripost.cariap.com.br/os/index.html`.

---

## 9. Amostras geradas nos testes (6 imagens)

**Leva 1 — v1.25.75** (rodapé opaco + logo c/ painel de contraste + acentos; tela 3 = CTA):
1. Conteúdo 1 — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/t1_1782340110.png
2. Conteúdo 2 — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/t2_1782340110.png
3. CTA (rodapé) — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/t3_1782340110.png

**Leva 2 — v1.25.76** (logo PURA sem painel + trava de paleta/temperatura/escala + app Looke na tela 2 + CTA c/ telefone certo):
4. Conteúdo CARIAP — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/v76_1_1782341222.png
5. App Looke — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/v76_2_1782341222.png
6. CTA (rodapé) — https://caripost.cariap.com.br/uploads/e384c0d3-473b-46b0-8c10-ca5b753a09bd/preview/v76_3_1782341222.png

*(Arquivos em `UPLOAD_DIR/<company>/preview/`. Custo de cada leva ≈ R$0,62 com nano-banana-2.)*
