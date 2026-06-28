# O problema da logo — análise e ideias (vamos decidir juntos)

## O que está acontecendo (sem enrolação)

1. **O "fundinho" preto atrás da logo é REGRA MINHA (código), não do modelo.**
   Meu código (`template_composer._stamp_app_logo`) coloca um painel atrás da logo
   **quando acha que ela sumiria** (logo branca em fundo claro). O modelo não tem nada
   a ver com isso. Por isso:
   - No 5.4.2 ficou "bonito" → o fundo do post combinou e o painel não atrapalhou.
   - No 5.4 normal ficou feio → o modelo desenhou o **título naquele canto**, e o meu
     painel **sobrepôs a letra**. Mesma regra, resultado ruim.

2. **A logo cadastrada já é um PNG transparente perfeito.** Eu não deveria adicionar fundo
   nenhum — deveria só **posicionar** ela bem. O erro é meu: "resolvi" contraste com um
   painel, e o painel é o problema.

3. **Por que não deixar a IA desenhar a logo?** Porque ela acerta umas (E-Saúde, ExitLag,
   Looke) e **erra outras** (Deezer vira borrão). Não dá pra confiar — é loteria.

## A raiz do problema de contraste

Logo transparente + fundo variável = às vezes some:
- Logo **branca** em fundo **claro** → invisível.
- Logo **escura** em fundo **escuro** → invisível.
- Em fundo de cor parecida → some.

Forçar um painel resolve o "sumir" mas cria o "fundo feio". É um beco sem saída SE só
existir **uma** versão da logo.

## As opções reais

### Opção A — Duas versões da logo (claro/escuro) + escolha automática ⭐ (recomendada)
Toda marca séria tem **2 versões**: uma **clara** (pra fundo escuro) e uma **escura**
(pra fundo claro). Cadastramos as duas por app. O código:
1. amostra a luminância do fundo no canto onde vai a logo;
2. **escolhe a versão que contrasta** (fundo claro → logo escura; fundo escuro → logo clara);
3. coloca **sem painel nenhum** (no máximo uma sombra suave quase invisível).
- ✅ Logo sempre nítida, **zero fundo**, visual de agência.
- ✅ É exatamente como agência real faz.
- ⚠️ Precisa cadastrar 2 versões por app (você tem nos kits de marca).

### Opção B — Reservar um "selo" limpo no design e a IA respeitar
Mando a IA deixar um retângulo/círculo **liso de cor sólida** no canto (parte do design
dela), e eu coloco a logo dentro. O "fundo" vira intencional, não carimbo.
- ✅ Fica integrado.
- ⚠️ Depende da IA obedecer (nem sempre obedece) → inconsistente.

### Opção C — Nome do app como TIPOGRAFIA, não logo
A IA renderiza muito bem **texto** ("E-Saúde 24h" saiu perfeito). Em vez de logo, usar o
**nome estilizado** (laranja, bold). Identidade vem do nome + cores.
- ✅ Acaba o problema de logo de vez (pra apps cujo forte é o nome).
- ⚠️ Apps com logo marcante (Deezer, Looke) perdem o símbolo.

### Opção D — Colocação inteligente (achar o canto mais limpo)
Em vez de fixar no canto superior esquerdo, o código **varre a imagem**, acha a região
mais lisa (menos detalhe) e coloca a logo lá, já com a versão que contrasta (junta com A).
- ✅ Nunca cai em cima de texto/rosto.
- ⚠️ Mais código, mas factível.

## Minha recomendação

**A + D:** cadastrar **logo clara e logo escura** por app, e o código escolher a versão
certa + a posição mais limpa, **sem nenhum painel forçado**. Fallback: se só houver 1
versão, uso ela com uma sombra suave (não um box). Se nenhuma servir, uso o nome em texto
(Opção C) como rede de segurança.

## O que eu preciso de você (pra fechar de vez)

- Cadastrar, por app, **2 versões da logo**: uma **clara** (fundo transparente, pra fundo
  escuro) e uma **escura** (pra fundo claro). Eu adiciono um seletor "logo clara / logo
  escura" no cadastro do produto. Você sobe as duas → o sistema escolhe sozinho na hora.

## Bônus — bug que você achou (briefing → criação)
No Briefing você desmarca apps e gera certo, mas na tela de **Criação** ele volta a puxar
**todos** os apps. Tem que **carregar a mesma seleção** do briefing. É um ajuste simples:
passar a seleção de apps do briefing pra Criação (em vez de marcar todos de novo).

---
**Pergunta pra você:** topa a Opção A+D (cadastrar 2 versões de logo por app)? Se sim, eu:
1. adiciono "logo clara/escura" no cadastro do produto;
2. troco o carimbo pra escolher a versão certa + posição limpa, **sem painel**;
3. corrijo o carry-over briefing→criação.
Se preferir, começo já pela Opção C (nome em texto) que não precisa cadastrar nada.
