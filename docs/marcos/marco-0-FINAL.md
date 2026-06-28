# Marco 0 — FINALIZADO E APROVADO ✅ · v1.25.92

Aprovado pelo dono: "passou, todas as mudanças foram positivas". Ponto de restauração travado em
`docs/marcos/backups/marco-0/` (template_composer.py, ai.py, posts.py) + golden em `golden.json`.

## O que o Marco 0 entregou (muito além do spike inicial)

**Arquitetura (a virada):** a IA gera SÓ a foto (`_photo_only_prompt`); o código desenha 100% do
texto/logo/barra/rodapé (`compose_carousel_slide` com `bg_bytes`). Provado determinístico (mesmo
input → bytes idênticos).

**Texto/layout:**
- Posição do texto TRAVADA (número/título/corpo, mesma régua em todas as telas) — config `content.align`.
- **Acentos corrigidos:** o OmniRoute removia acento; texto movido pro **CometAPI** (preserva). Briefing volta com acento.
- Limites/robustez de wrap; rodapé com degradação graciosa.

**Logos (estrutural + maleável):**
- Escolhe a **variante de melhor contraste** (branca/escura) por fundo — fim da caixa cinza.
- **Multi-app por tela:** 1..N logos, conforme a tela trata; token `app_logo.max_per_slide` (default 3).
- Briefing tagueia o app por tela a partir dos **apps reais cadastrados** (dinâmico) + match no texto.
- Posição/contraste/colisão = código determinístico.

**CTA:** botão laranja da marca + contato empilhado (telefone destaque, site menor), sem "·".

**Provedores de IA (registro único, fim da churn):**
- Imagem: OmniRoute (grátis), **CometAPI** (gpt-image/seedream + nano-banana via generateContent), PiAPI, OpenRouter. GPT-direto fora.
- Texto: CometAPI (Claude/GPT/Gemini/DeepSeek) — preserva acento.
- Seletor **provedor+modelo** agrupado na criação; página "Provedor de IA" nas Configurações.

**Rede de segurança:** `docs/marcos/regressao_check.py` (golden determinístico) roda antes/depois de
mexer no motor; backup por marco aprovado. Tudo em `/opt/caripost/CLAUDE.md`.

## Mapa dos problemas originais do dono → resolvidos no Marco 0
P1 (sem padrão) ✅ · P3 (logo quebra) ✅ · P4 (coesão fonte/tamanho/posição) ✅ · P6 (arruma um quebra outro) ✅ (golden).
Pendente p/ próximos marcos: P2 (qualidade "agência" = tipografia fina, Marco 3) · P5 (custo/cache, Marco 4) · coesão de FOTO entre telas (Marco 5).
