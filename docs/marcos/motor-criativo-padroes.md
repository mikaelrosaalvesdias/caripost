# Motor Criativo — BIBLIOTECA DE PADRÕES (estrutura, não arte)

> Conceito (definido pelo usuário): o motor NÃO gera "arte" solta. Ele tem uma **biblioteca de PADRÕES**.
> Cada padrão = uma **ESTRUTURA / receita de posicionamento** (onde fica logo, texto, rodapé, sujeito, fundo —
> COMO é montado). Precisa ter **VÁRIOS padrões aprovados**; o motor **sorteia** um por arte (semeado) → não
> fica repetitivo. Cada padrão é **genérico** (usa os tokens da marca: logo/cores/contato do cadastro) e vale
> pra QUALQUER empresa. "Aprovar um padrão" = validar a estrutura, não uma arte específica.

## PRINCÍPIO (o que o usuário definiu)
1. **Padrão aprovado = RÉFERÊNCIA DE QUALIDADE.** O motor NUNCA entrega abaixo do nível dos padrões aprovados —
   eles são a definição de "bom". Qualidade é garantida porque só se usa padrão aprovado.
2. **Reusável, mas NÃO universal.** Um padrão pode servir pra várias empresas; mas em certos casos não fica bom —
   aí o motor tem que ter **OUTRA opção** (outro padrão). Por isso a biblioteca precisa de VÁRIOS.
3. **Segue a qualidade, mas ESCOLHE certo — não torto, não repetitivo.** O motor seleciona o padrão que ENCAIXA
   na empresa/tema (seleção inteligente por contexto), NÃO força um padrão onde não cabe, e varia entre posts.
   Ele "monta" seguindo a referência de qualidade, sem seguir cego/torto.

## Como o motor usa
- Por arte: sorteia um padrão da lista de APROVADOS (seed determinístico → não repete entre posts).
- Preenche o padrão com: cena/foto da IA (só imagem, sem texto/logo) + tokens da marca (logo, cores, contato).
- Partes fixas (logo, rodapé, contato) = SEMPRE código, do cadastro da empresa. IA = só a cena.

---

## PADRÃO #1 — "Foto + rodapé de contato" — ✅ APROVADO (rodapé perfeito, 2026-07-01)
**Estrutura:**
- Formato 4:5 (1080x1350).
- **Fundo:** cena/foto gerada pela IA — SEM texto/logo/marca/watermark; espaço negativo; topo e base mais limpos.
- **Topo:** faixa de proteção (degradê escuro, `compose_logos_only(top_guard=True)`) que APAGA junk da IA + **LOGO oficial** centro-topo (código).
- **Rodapé:** barra de contato (`compose_cta_footer`) — logo da empresa + "FALE CONOSCO NO WHATSAPP: <phone>" (ou site se sem phone). **Dados SEMPRE de `company.website` + `company.phone`** (fonte do render real; NUNCA brand_kit/outro campo — erro já cometido).
- **Identidade:** paleta + DNA da marca injetados na instrução da cena.
- **Modelo de imagem:** `openai/gpt-5.4-image-2` (quality **medium**) — Seedream descartado pelo usuário.
- **Mensagem/título:** (próximo elemento a definir neste padrão).

**Amostras aprovadas:** `/uploads/<cariap>/test/rod_1..3.png` (rodapé idêntico e correto nas 3).

---

## PADRÕES a construir (para ter variedade — não repetir)
Cada um é uma ESTRUTURA diferente (posicionamento), aprovada 1 a 1 pelo usuário:
- **#2** — texto grande no topo / sujeito na base (invertido do editorial).
- **#3** — sujeito lateral + coluna de texto do lado oposto (respeitando espaço negativo).
- **#4** — faixa/bloco de cor da marca ancorando o texto (estilo capa de revista).
- **#5** — split (foto metade + cor sólida metade com o texto).
- (o carrossel editorial atual da plataforma = outro padrão já existente.)

Regra: só entra na biblioteca (lista de sorteio) DEPOIS de aprovado. Um padrão reprovado não é sorteado.
