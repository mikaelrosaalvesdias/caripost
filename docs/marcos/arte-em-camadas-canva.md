# Arte em camadas + Canva (v1.27.148 → v1.27.150)

## Problema (usuário, out/2026)
1. Artes com "cara de IA": neon, brilho, muitos elementos, texto grande, tipografia repetida.
2. Precisa editar a arte movendo os elementos livremente (Canva via Composio).
3. Qualidade ruim ao exportar.

## Diagnóstico
- Qualidade: o modelo de imagem (GPT-5.6 Luna via OmniRoute) devolve no máximo ~1,5 MP (1122×1402 / 1536×1024), **ignorando o tamanho pedido**. O texto desenhado pela IA fica preso nessa resolução.
- Edição: uma imagem chapada não vira elementos editáveis no Canva. A arte precisa nascer em camadas.
- Teste A/B com o mesmo pedido: a direção "anti-IA" (foto documental + bloco de cor chapada + tipografia contida) elimina o visual de IA.

## Solução (escolhida pelo usuário: "Arte em camadas")
- **Modo `layered`** no motor (`render-carousel`, `_render_layered` em `app/routers/posts.py`):
  - a IA gera **só a foto** (documental, luz natural, sem texto/logo/neon/glow);
  - `app/services/layered_composer.py` monta título, texto, botão, logos (marca + apps citados) e contato em **2160×2700** (feed) / **2160×3840** (story), com Poppins;
  - layouts: capa (foto + bloco da marca), conteúdo (fundo claro + foto em card) e tela final (bloco da marca, centralizada);
  - cores e contraste automáticos a partir da paleta; tokens ajustáveis em `creative_config.design.layered`.
- **Padrão** em Conteúdo (seletor "Estilo da arte": Camadas | Arte livre pela IA) e na Agência (`agency.art_mode`, padrão `layered`).
- Cada tela salva `NN_layers.json` + imagens das camadas → **Editar no Canva**:
  - `layers_to_pptx` monta o PPTX (cada camada vira objeto);
  - `CANVA_POST_URL_IMPORTS` (Composio) devolve o link de edição.
- **Trazer do Canva**: `CANVA_POST_EXPORTS` (PNG) substitui as telas do post e guarda as anteriores em `pre_canva_urls`.
- **Conectar Canva**:
  - rotas `GET /api/posts/canva/status` e `POST /api/posts/canva/connect` (link OAuth da Composio);
  - na tela, "Editar no Canva" sem conta ativa oferece "Conectar Canva".
- Erros do Canva voltam com 424 (o 502 era trocado pela página HTML do Cloudflare).

## Testes
- Carrossel V8 (8 telas, pelo app) em camadas: 2160×2700, fotos pela assinatura (R$ 0), visual limpo. Capa e tela final reajustadas (título maior, tela final centralizada).
- PPTX gerado: 3 telas, ~1,2 MB.
- **Importação no Canva ainda NÃO validada:**
  - a conta Canva da Composio (`ca_1jDec7mifWk8`) está EXPIRED;
  - status e geração do link de conexão: ok.
  - Validar assim que o usuário reconectar.
