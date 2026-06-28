# Caripost — Visão geral + plano novo de geração de imagem

## 1. O que a aplicação é (visão geral)
Caripost = ferramenta da **agência Cariap**. Estrutura:
- **Cliente (empresa)** → tem **apps/produtos** (E-Saúde, Looke, Deezer, ExitLag…) + **identidade** (cores, logo, fonte, voz).
- **Conteúdo**: Briefing (IA escreve) → **Criação** (gera a arte: post / carrossel / vídeo) → Aprovação → Publicação (Composio).
- **IA**: texto via OmniRoute (sua assinatura, grátis); imagem via provedor de imagem.

## 2. O que FUNCIONAVA no início (e por quê)
No começo, a geração de **post único** dava certo: a IA gerava a arte e respeitava razoavelmente a marca. Era basicamente **a IA criando a imagem** com um bom prompt — pouca interferência de código.

## 3. O que QUEBROU quando entrou o carrossel
Eu introduzi um **"designer" em código (PIL)**: tipografia, layout_variant, bbox, quality_guard, design system. Isso deixou tudo com **cara de template institucional/IA** — rígido, sem alma. E pra "consertar", testei **modelos/rotas errados** (PiAPI nano-banana por URL, que não respeita logo). Resultado: feio + dinheiro gasto à toa.

**Lição:** código desenhando a arte = ruim. A IA tem que criar; código só no que a IA não dá conta (logo perfeita, quando exigido).

## 4. Arquitetura NOVA (a recomendação)
**Um modelo que cria a arte INTEIRA, recebendo a logo como ARQUIVO (modo edição) — igual você faz no ChatGPT.**

Por peça (post ou slide de carrossel):
1. **Texto/conceito** → Claude Opus (OmniRoute, grátis): headline, mensagem, qual app, ideia visual.
2. **Arte** → **gpt-image-1 via PiAPI** (seu saldo PiAPI, **NÃO** a chave da empresa) em **modo edição**:
   - Entra: **logo oficial do app** (arquivo) quando a peça é de um app + (opcional) logo da empresa.
   - Prompt: "crie uma arte bonita, criativa, premium; cores da marca = X; mensagem = '…'; **use a logo fornecida no tamanho/posição que ficar melhor**; nada de cara de IA institucional genérica."
   - Sai: a arte COMPLETA, com a logo real, cores certas, criativa.
3. **Código não desenha nada** (no máximo um recorte 4:5). A IA decide tamanho/posição da logo.

Por que resolve o que você pediu: criativo + não-institucional (IA livre) · logo certa no tamanho que ela escolhe (logo como arquivo) · identidade (cores + logo) · qualidade (gpt-image-1). É o **híbrido de verdade** — IA cria, marca é respeitada.

## 5. Controle de CUSTO (regra de ouro)
- **gpt-image-1 ≈ R$ 0,20/img** (PiAPI). Carrossel de 8 = ~R$ 1,60. **Sempre mostrar o custo e confirmar antes.**
- **Rascunho barato**: gerar 1 peça por vez pra aprovar o conceito; só depois gerar o resto.
- **Nunca** gerar 6×2=12 de uma vez sem confirmação.
- **Fallback grátis** (editorial PIL) só se você escolher — não é mais o padrão.
- Modelos baratos (Flux ~R$0,02) pra testar enquadramento; gpt-image-1 só no final.

## 6. O que eu removo/desligo
- O "designer" em código como padrão (layout_variant, bbox, quality_guard, tipografia PIL).
- PiAPI nano-banana por URL como caminho de logo (não respeita).
- Uso da chave OpenAI da empresa (passa a ser gpt-image-1 **pela PiAPI**).

## 7. Próximos passos (quando você topar — sem gastar até lá)
1. Carrossel + post passam a usar **gpt-image-1 via PiAPI, modo edição, com a logo do app como arquivo**.
2. Botão "Gerar 1 (preview)" antes de gerar o carrossel inteiro, com custo em R$.
3. Você testa **1 imagem** → se ficar bom (vai ficar perto do seu ChatGPT), escala.
