# Análise do SPEC (logo/briefing/geração) — meu parecer honesto

**Pedido:** avaliar se o spec faz sentido. NÃO executei nada.

## Veredito

O spec está **certo** e é a arquitetura correta pra escalar sem quebrar marca:
> IA gera só o cenário. Código monta a peça com assets aprovados. Marca blindada.

Concordo com 90% dele. Mas tem **1 trade-off grande** que muda o produto, e ele precisa
da sua decisão antes de eu tocar em qualquer coisa.

---

## ⚠️ O trade-off que você PRECISA saber (o ponto central)

O spec diz: **a IA NÃO desenha texto nenhum** (nem headline, nem benefícios) — só o fundo.
O **código desenha todo o texto**.

Mas as imagens que você chamou de **"linda, perfeita"** (a do riverflow/5.4.2) foram a
**IA compondo tudo**: o headline, os cards de benefício, o mockup do app, o layout. Se eu
mandar a IA gerar **só o fundo** e o código escrever o texto, a gente **perde esse charme**
e volta pro **template fixo** — que você odiou antes ("não é algo fixo", "8 ou 80").

Resumindo a tensão:
- **Spec completo** = confiável, marca blindada, texto sempre perfeito → porém **mais
  templated/rígido** (menos a mágica que você acabou de amar).
- **O que temos hoje** (IA compõe + código carimba logo/rodapé) = premium e variado →
  porém a IA às vezes erra logo/texto.

**Não dá pra ter os dois 100%.** Ou a IA tem liberdade (varia, mas erra), ou o código
controla (confiável, mas repete). O spec escolhe controle. Você precisa confirmar se topa
perder um pouco da variação em troca de confiabilidade.

---

## Onde concordo 100% (ganho puro, sem perder nada)

Independente da decisão acima, estes pontos do spec são **só vantagem** e eu faria já:

1. **Remover o painel automático atrás da logo** (o "fundinho" — é regra minha, bug).
2. **logo_clara / logo_escura por produto** + escolha automática por luminância (sem painel).
3. **Carry-over briefing → criação** (usar os apps selecionados no briefing, não marcar todos).
4. **Bloquear** geração se faltar logo aprovada (em vez de inventar/baixar da net).
5. **Nunca** baixar logo da internet e usar direto em produção.
6. **Telefone/site sempre por código** (nunca a IA escreve — evita o "(11) 114210-1788" torto).

Esses 6 resolvem 80% da sua dor de HOJE **sem** mexer no que você gostou.

---

## Onde o spec é "norte", mas é semanas de trabalho (não dá pra fazer tudo agora)

- Compositor completo por camadas (headline auto-fit, subhead max-lines, cards de benefício
  com ícones aprovados, CTA componente).
- Biblioteca de templates (4 layouts), scoring de posição de logo, varredura de região limpa.
- Asset Registry com estados (missing/pending/approved/rejected/deprecated).
- Validação visual automática + retry loop + relatório por arte.
- Ranking de modelos por taxa de aprovação.

Tudo certo, tudo bom — mas é um **produto** (tipo "Canva blindado"), não um ajuste. Fazer
isso de uma vez = parar tudo por dias/semanas. Recomendo fazer por fases.

---

## Respostas às perguntas do spec (seção 16) — sobre a NOSSA stack

**Stack**
1. Compositor = **Pillow (Python)**. Arquivo: `app/services/template_composer.py`.
2. `_stamp_app_logo` está em `app/services/template_composer.py`.
3. Projeto = **Python/FastAPI** (backend) + **JSX via Babel no browser** (frontend) + Docker Swarm.
4. Artes exportadas no **backend** (`POST /api/posts/generate-image` → Pillow → salva PNG).
5. Geração é **síncrona** (`asyncio.to_thread`), **sem fila**.

**Assets**
6. Logos em `/media/<company_id>/logos/` e `/products/<product_id>/`, registradas na tabela `assets`.
7. Sim, há `product_id` + url da logo nos assets.
8. Sim, diferencia logo do app (asset com `product_id`) da Cariap (logo da company).
9. **Não existe status de aprovação** de asset hoje. (precisa criar)
10. **Não** suporta mais de uma versão por produto hoje. (precisa criar light/dark)
11. Transparência: os PNGs têm alpha, mas **não há metadado/validação** disso.
12. **Não** existe validação pra impedir JPG como logo.

**Briefing**
13. Seleção de apps do briefing fica em `ContState` (estado no browser, por empresa).
14. A Criação recarrega os apps no `useEffect` e **marca todos** (`s[p.id]=true`).
15. A função é o `useEffect` do `StepCriacao` (em `apps-conteudo.jsx`).
16. **Não** passa `briefing_id`/seleção — a Criação ignora o que foi marcado no briefing.
17. Criação usa **estado local** (React) + `ContState`.

**Geração**
18. O prompt hoje **ainda deixa a IA escrever o headline** (texto). (o spec quer proibir todo texto)
19. O prompt **já proíbe logos** (mudei isso).
20. O modelo **não** recebe a logo como referência (só refs de estilo do mood board, se houver).
21. Sim, há negative ("não desenhe logotipos/marcas").
22. **Não** valida se a imagem veio com texto embutido.

**Layout/Validação**
23–34. Hoje: **sem templates fixos**, **sem zonas seguras**, rodapé é **fixo por código**,
telefone/site **por código**, **sem auto-fit**, **sem validação de colisão**, **sem retry
de composição**, base e final **não** são salvas separadas.

---

## Minha recomendação (faseada)

**FASE 1 — agora (horas, ganho puro, NÃO perde o charme):**
- Remover painel automático da logo.
- Carry-over briefing → criação.
- logo_clara/logo_escura por produto + escolha por luminância (sem painel).
- Bloquear se faltar logo aprovada; nunca baixar da net.
- Telefone/site sempre por código (já é).
- **Manter a IA compondo o design** (headline etc.) — você gostou. Só os logos passam a ser limpos.

**FASE 2 — quando você decidir o trade-off (dias):**
- Se escolher **controle total**: migro pro compositor por camadas (IA = só fundo, código
  desenha headline/benefícios/CTA com auto-fit + templates). Aí entra o resto do spec.

**FASE 3 — escala (semanas):** asset registry, validação automática, retry, ranking de modelos.

---

## A decisão que eu preciso de você (só isso, hoje)

**Pergunta 1:** Faço a **FASE 1** agora (resolve sua dor de hoje, mantém o charme da IA)? [sim/não]

**Pergunta 2 (pode deixar pra depois):** No futuro, você quer **controle total** (código
desenha TODO o texto, mais confiável porém mais templated) ou **manter a IA compondo**
(mais bonito/variado, porém com risco de erro que o código corrige só nos logos)?

Não vou executar nada até você responder a Pergunta 1.
