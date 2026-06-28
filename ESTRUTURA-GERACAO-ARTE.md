# Estrutura de geração de arte — híbrido profissional (para o Codex avaliar)

**Status:** implementado e no ar (v1.25.29). Render validado (E-Saúde).
**Pedido ao Codex:** avaliar a arquitetura abaixo, apontar riscos, bugs e melhorias.

## Decisão de arquitetura (escolhida pelo dono)

> **A IA gera SÓ o fundo (cenário) e escreve os textos como DADOS.**
> **O CÓDIGO desenha headline, subtítulo, benefícios, CTA, logo do app, logo Cariap e rodapé.**
> A IA NUNCA renderiza texto ou logo dentro da imagem final.

Motivo: a IA acerta cenário mas erra logo/texto (ortografia, telefone, logo da Deezer
viajada, fundo preto atrás de logo). Separar **geração criativa** de **composição
controlada** blinda a marca sem perder o cenário bonito.

## Pipeline atual

```
Briefing (StepBriefing)
  └─ gera 1 ideia por app marcado (generate_post_copy) — confiável, com retry
Criação (StepCriacao)
  ├─ carrega a MESMA seleção de apps do briefing (carry-over via ContState.sources)
  ├─ por app: quantidade + modelo por variação (seletor com qualidade+preço)
  └─ por variação:
       1) generatePostAI  -> copy ESTRUTURADA {headline, subheadline, benefits[3], cta, ...}
       2) generatePostImage(model, headline, subheadline, benefits, cta, product)
            └─ backend:
               a) build_image_prompt -> pede SÓ o fundo (assunto à direita, esquerda+rodapé
                  limpos, PROIBIDO texto/logo/rodapé)
               b) generate_image_with_cost(model_override) -> OpenRouter Image API
                  (aspect 4:5, retry 3x p/ modelos 'pro' como riverflow)
               c) compose_branded_post(...) -> CÓDIGO desenha tudo por cima
               d) salva PNG, retorna {url, cost, model}
```

## Arquivos e funções-chave

| Arquivo | Função | Papel |
|---|---|---|
| `app/services/ai.py` | `generate_post_copy` | Agora retorna `headline`, `subheadline`, `benefits[3]`, `cta` além de title/copy. |
| `app/services/ai.py` | `build_image_prompt` | Pede **só o fundo**: assunto à direita, esquerda/rodapé limpos, **proíbe** texto/logo/rodapé/telefone/site. |
| `app/services/ai.py` | `generate_image_openrouter` | POST OpenRouter Image; aspect_ratio via gcd (4:5); `resolution`; **retry 3x** (timeout/5xx/429); 4xx não repete. |
| `app/services/ai.py` | `generate_image_with_cost(model_override)` | Roteia pelo modelo escolhido (slug com "/" = OpenRouter). Confirma que o modelo escolhido é o usado. |
| `app/services/ai.py` | `openrouter_image_models` / `openrouter_video_models` | Top-10 curados (slugs REAIS do OpenRouter, sem renomear). |
| `app/services/template_composer.py` | `compose_branded_post` | **Compositor por camadas** (ver abaixo). |
| `app/routers/posts.py` | `POST /api/posts/generate-image` | Gera fundo + compõe + salva. Passa headline/subheadline/benefits/cta. |
| `app/routers/posts.py` | `GET /api/posts/ai-models` | Lista modelos (movido p/ ANTES de `/{post_id}` — antes dava 404 por captura de rota). |
| `app/os/apps-conteudo.jsx` | `StepCriacao` | Seletor por app (qtd + modelo por variação), carry-over do briefing, passa copy estruturada. |

## Compositor por camadas (`compose_branded_post`)

Entrada: `post_bytes` (fundo da IA), `headline`, `subheadline`, `benefits[]`, `cta`,
`company_logo_path`, `app_logo_path`, `site`, `phone`.

Camadas (1080×1350, Pillow):
1. Fundo da IA (`_cover`, corta preservando o topo).
2. **Scrim creme** à esquerda (gradiente: opaco ~72% e some) → legibilidade garantida do texto.
3. **Logo do app** (cadastrada, **SEM painel**): clara → topo direito (sobre a foto);
   escura/colorida → topo esquerdo (sobre o scrim). Decisão por `_logo_is_light`.
4. **Headline** auto-fit (encolhe a fonte até caber ≤4 linhas) + barra de acento laranja.
5. **Subtítulo** (cinza, máx 3 linhas).
6. **Benefícios** (3 bullets laranja).
7. **CTA** (pill laranja).
8. **Rodapé creme**: logo Cariap + `CARIAP.COM.BR` + `FALE CONOSCO: (telefone formatado)` + faixa laranja.

Se a composição falhar, salva o fundo puro **MAS retorna alerta explícito** no response
(`composed: false` + `warning: "Imagem gerada, mas a composição da marca falhou…"`). O
frontend mostra o aviso ⚠ no card + botão "Tentar de novo". **Não é mais silencioso.**

## O que foi RESOLVIDO

- ✅ Logo nunca mais inventada (a IA não desenha logo; código usa a cadastrada).
- ✅ Fundo preto atrás da logo REMOVIDO (regra do `_stamp_app_logo` desativada).
- ✅ Texto nunca cortado nas laterais (gera em 4:5; corte vertical preserva o topo).
- ✅ Telefone/site/headline sempre por código (sem erro de IA).
- ✅ Modelo escolhido = modelo usado (confirmado no backend; antes parecia "não bater"
  por causa do riverflow falhar sem retry).
- ✅ Riverflow com retry (intermitência resolvida).
- ✅ Carry-over briefing → criação (usa os apps marcados, não todos).
- ✅ Rota `/ai-models` 404 corrigida.

## PENDENTE / RISCOS (avaliar, Codex)

1. **Logo clara/escura por produto**: hoje só 1 logo cadastrada. Falta UI no cadastro do
   produto p/ `logo_light` e `logo_dark` + escolha automática por luminância da região.
   Hoje uso heurística simples (logo clara→direita, escura→esquerda).
2. **Posição da logo é fixa por contraste** (topo esq/dir), **não** varre a imagem
   procurando a região mais limpa (o SPEC pedia scoring de posição). Risco: logo cair
   sobre rosto/detalhe no lado escolhido.
3. **Scrim assume assunto à direita** — depende da IA obedecer "assunto à direita". Se
   ela puser o assunto à esquerda, o scrim cobre parte dele (texto continua legível, mas
   o visual perde). Sem validação de layout.
4. **Sem validação automática** pré-export (colisão texto×logo, contraste, margem).
5. **Sem templates múltiplos** — é 1 layout (scrim esquerda). Falta variar diagramação.
6. **Sem bloqueio** se faltar logo aprovada (gera mesmo assim, sem logo do app).
7. **Sem asset registry / status de aprovação** (missing/pending/approved).
8. **Fontes**: só DejaVu/Liberation no container (sem Montserrat). Tipografia limitada.
9. **gpt-image** retorna 2:3 (não 4:5) → corte vertical (preserva topo, mas perde fundo).
   riverflow é 4:5 nativo (ideal).
10. **Vídeo**: 10 modelos listados na API, mas a GERAÇÃO de vídeo ainda usa o caminho
    antigo (Sora/OpenAI), não OpenRouter.

## Perguntas pro Codex

1. A separação geração×composição está correta e robusta? Algum furo?
2. O scrim fixo à esquerda é boa ideia ou melhor detectar a região limpa (custo×benefício)?
3. Vale implementar o scoring de posição de logo agora ou é over-engineering pro estágio?
4. A heurística logo-clara→direita / escura→esquerda é aceitável até ter light/dark cadastrados?
5. Faltou algum check de validação crítico antes de exportar?
6. O retry 3x no OpenRouter é suficiente ou precisa backoff/fila?
7. Próximo passo de maior ROI: templates múltiplos, validação, ou light/dark logo?
