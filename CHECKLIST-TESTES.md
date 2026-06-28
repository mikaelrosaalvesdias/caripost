# Checklist de testes — Caripost (sessão completa)

**Versão atual:** confira em `https://caripost.n8nmikael.com.br/health` → deve mostrar **1.25.34**.
**Antes de testar:** dê **refresh forte** (Ctrl+Shift+R). Settings mostra a versão (depende do refresh); o `/health` é a verdade.

Formato: **[ ] Item — Como testar → Resultado esperado.**

---

## 1. Infra / Versão
- [ ] **Versão confiável** — abra `/health` → `{"ok":true,"version":"1.25.34"}`.
- [ ] **Settings** — após refresh forte, mostra `v1.25.34` (igual ao /health).

## 2. IA / Modelos (OpenRouter + Reve)
- [ ] **Tudo OpenRouter** — gere qualquer post; texto e imagem saem sem usar OpenAI. Pode manter a OpenAI revogada.
- [ ] **Seletor de modelo de imagem** — Criação → marca um app → em cada variação tem dropdown com ~11 modelos (gpt-5.4-image-2, gemini-3-pro-image (nano-banana-pro), seedream-4.5, flux.2-pro, riverflow-v2.5-pro, **reve-2.0**…), com qualidade + preço/img.
- [ ] **Modelo escolhido = usado** — escolha riverflow-v2.5-pro numa variação e gpt noutra → cada card mostra o modelo que realmente gerou.
- [ ] **reve-2.0** — aparece no seletor (porque a key está configurada). Ao gerar com ela: **se der "budget exhausted", é falta de saldo na Reve** (adicione fundos no API Budget da Reve). Qualquer outro erro me avise.
- [ ] **Estimativa de custo** — antes de "Gerar", mostra "N peças · estimativa ≈ $X"; se ≥ $0,30, pede confirmação.

## 3. Clientes → Produtos
- [ ] **Enrich do produto** — Clientes → Cariap → Produtos → num produto, cole **site + @Instagram** → "Puxar do site/Instagram" → preenche descrição, objetivo, funções, à la carte, cores do logo. **Sem preço.** (testa E-Saúde: deve vir "telemedicina", não "cookie").
- [ ] **À la carte** — seção "À la carte (entregue junto)" com add/excluir (ex.: Zap → Telecine).
- [ ] **Excluir logo do produto** — cada logo tem botão **X**.
- [ ] **Excluir produto / empresa** — botão Excluir no produto; "Excluir empresa" no topo da empresa.

## 4. Empresa (Voz & Persona)
- [ ] **Enrich da empresa** — Voz & Persona → "Puxar do site/Instagram da empresa" → preenche tom de voz, persona, público/modelo, base visual (usa o site/IG de Dados Gerais).

## 5. Briefing
- [ ] **Confiável** — Conteúdo → Briefing → marca apps em "Apps que viram ideias" → "Gerar briefing com IA" → vem 1 ideia por app marcado, **nunca cai em vazio** ("Estratégia gerada" sem nada não acontece mais).
- [ ] **Respeita seleção** — desmarque um app → ele NÃO entra nas ideias.
- [ ] **Carry-over** — vá pra Criação → vêm marcados **os mesmos apps** do briefing (não todos).

## 6. Criação (núcleo)
- [ ] **Por app: qtd + modelo por variação** — marca app → define Qtd → um dropdown de modelo por v1/v2/v3.
- [ ] **Institucional** — existe a opção "Institucional (Cariap)" na lista.
- [ ] **Híbrido profissional (arte)** — gere com **riverflow-v2.5-pro**. Esperado: a IA faz **só o fundo**; o **código desenha** headline + subtítulo + 3 benefícios (bullets laranja) + CTA + **logo real do app** (sem fundo preto) + **rodapé Cariap** (logo + CARIAP.COM.BR + FALE CONOSCO).
- [ ] **Sem corte** — o headline aparece inteiro (não cortado nas laterais).
- [ ] **Sem logo viajada** — não inventa Deezer/logo falso; usa a cadastrada.
- [ ] **Falha de composição avisa** — se a composição falhar, o card mostra ⚠ "composição da marca falhou (saiu só o fundo)" + botão "Tentar de novo" (não fica silencioso).
- [ ] **Comparar e apagar** — gere 3 variações, apague as piores (lixeira), fique com a melhor.

## 7. Aprovação (fluxo do cliente) — NOVO
- [ ] **Peças aparecem automático COM imagem** — gere na Criação → abra a aba **Aprovação** → as peças aparecem (preview + copy) sem clicar em nada.
- [ ] **Gerar link** — "Gerar link + notificar" → cria as peças como "em revisão" e gera **1 link com TODAS**. Mostra a URL.
- [ ] **Página do cliente** — abra o link → preview estilo Instagram + 3 botões: **Aprovar 100% / Com ressalvas / Reprovar**. Ressalvas e Reprovar exigem texto.
- [ ] **Aprovado 100%** — vira APROVADO → vai pra Agendamento/Publicação.
- [ ] **Ressalvas → Revisão** — peça com ressalvas volta pra Aprovação com a tarja ⚠ + o comentário do cliente + botão **"Regenerar com o feedback"**. Clicar → gera nova imagem aplicando o pedido + reabre pra reenviar.
- [ ] **Reprovado → aprendizado** — peça reprovada mostra o motivo. **Esse motivo vira REGRA do cliente**: gere um post novo desse cliente depois → a IA deve evitar o erro reprovado (a regra entra no prompt). Confira em Voz & Persona se quiser (campo client_rules é interno).
- [ ] **Imagem na lista** — "Aguardando aprovação" mostra a imagem de cada peça.

## 8. Fim do fluxo / fixes
- [ ] **Botão "Próximo" sumiu no fim** — na última etapa (Agendamento) NÃO tem mais "Próximo"; tem **"Criar novo conteúdo"** + **"Voltar ao painel"**.
- [ ] **Publicar sem "Cariap Criador"** — app Publicar → o seletor de marca mostra só **clientes** (empresas), sem o nome antigo "Criador".
- [ ] **Menu limpo** — sem Telegram, sem Criadores. Agenda existe (restaurada).
- [ ] **Publicar só redes sociais** — destino mostra Instagram/Facebook/TikTok/YouTube, **sem plataformas adultas**.

## 9. Página de aprovação / e-mail
- [ ] **Link por WhatsApp/e-mail** — opcional, em Aprovação. (WhatsApp via Evolution — ver backlog.)

---

# BACKLOG (itens grandes do seu doc — mapeados, ainda NÃO feitos)

Cada um é um mini-projeto; faço na ordem que você priorizar.

### Prioridade 1 (bugs)
- [ ] **Painel: agendados/publicados não contam** — investigar contagem por status + filtro por empresa.
- [ ] **Evolution API não envia WhatsApp** — depurar URL/token/instância/payload/logs (mandar a doc da Evolution).
- [ ] **Concorrentes não funciona** — validar cadastro + análise + erro visual.

### Prioridade 2 (estrutura)
- [ ] **Acervos** — reestruturar em categorias (Logos, Posts gerados/aprovados/publicados, Referências, Vídeos, Imagens) + clicar pra expandir (preview Instagram) + status/data/cliente.
- [ ] **Aprovação rica** — mostrar quem aprovou, data/hora, canal, status colorido, expandir (já mostra imagem+texto+decisão; falta "quem/quando" detalhado).
- [ ] **Publicar** — ajuste de layout + vínculo com aprovado.
- [ ] **Painel: Pendências por cliente** — reorganizar (cliente / empresa / pendência / ação).
- [ ] **Criação solta no menu Agência** — avaliar remover/realocar (hoje "Criação" e "Conteúdo" coexistem).

### Prioridade 3 (produto)
- [ ] **Financeiro de custo de IA** — imagens/vídeos gerados, custo por geração, total US$/R$, por modelo/cliente/período, saldo das APIs, exportar. Remover receita/criadores.
- [ ] **Template de e-mail profissional** — logo, cores do app, botão de aprovação, preview do conteúdo.
- [ ] **Logo clara/escura por produto** — cadastrar 2 versões → escolha automática por luminância (encerra de vez o tema da logo).
- [ ] **Vídeo no OpenRouter** — os 10 modelos já estão na API; falta ligar a geração de vídeo.

---

**Como reportar:** marque [x] o que passou e me diga o número do item que falhou + o que viu. Eu corrijo na ordem que você priorizar.
