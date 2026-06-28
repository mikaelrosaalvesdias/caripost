# AGENTS.md

Escopo: todo o repositorio.

Este arquivo e a instrucao principal para qualquer IA ou desenvolvedor que atualize o MetaPorn.

## Regra Central

Nao faca mudancas amplas sem necessidade. Leia os arquivos afetados, entenda o fluxo existente e preserve as funcoes que nao fazem parte do pedido.

## Fluxo Obrigatorio

Para qualquer alteracao de app que sera entregue ou deployada:

1. Ler os arquivos envolvidos antes de editar.
2. Implementar somente o necessario para o pedido.
3. Rodar validacoes compativeis com a mudanca.
4. Atualizar a versao do app.
5. Atualizar o changelog dentro do app.
6. Atualizar o changelog do repositorio quando a entrega for relevante.
7. Conferir que nao ha secrets, bancos, midias ou arquivos locais no staging.
8. Fazer commit claro.
9. Fazer push para o GitHub no branch correto depois da validacao.

## Versao Obrigatoria

Sempre que atualizar o app, mude a versao nestes pontos:

- `app/main.py`: `FastAPI(... version="X.Y.Z")`
- `app/ui/index.html`: versao visivel da sidebar
- `app/ui/index.html`: `version-badge`
- `app/ui/index.html`: query/cache bust do script `app.js?v=...`

Tambem atualize:

- `app/ui/app.js`: adicionar entrada no topo do `CHANGELOG`
- `CHANGELOG.md`: registrar o resumo da entrega, quando houver mudanca entregue

Comando util para conferir:

```bash
rg -n "version=|v1\\.|app\\.js\\?v=" app/main.py app/ui/index.html app/ui/app.js CHANGELOG.md
```

## Git Obrigatorio

Depois de validar uma entrega:

```bash
git status -sb
git diff --check
git add <arquivos-intencionais>
git commit -m "descricao curta"
git push
```

Se o push falhar por autenticacao, informe claramente o bloqueio e deixe o commit local pronto.

## Protecao de Dados

Nunca coloque no Git:

- `.env`, `stack.yml` real ou arquivos de configuracao do servidor
- bancos SQLite, `data/`, logs, PIDs e backups
- videos, imagens, legendas geradas, burns, teasers e previews
- tokens de IA, S3/MinIO, Telegram, sessoes ou chaves privadas

Antes de commitar, rode uma varredura basica:

```bash
rg -n "(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE KEY|BEGIN RSA|BEGIN OPENSSH|sk-|ghp_)" \
  --glob '!data/**' --glob '!*.db' --glob '!*.sqlite*' --glob '!node_modules/**' .
```

Resultados com nomes de variaveis e placeholders sao aceitaveis. Valores reais nao sao.

## Validacoes Minimas

Use validacoes proporcionais ao risco:

```bash
python -m py_compile app/db.py app/main.py
node --check app/ui/app.js
git diff --check
```

Quando alterar endpoints ou UI de producao, validar tambem com `curl`, container, browser ou fluxo real aplicavel.

## Estilo de Mudanca

- Siga os padroes existentes do projeto.
- Prefira alteracoes pequenas e rastreaveis.
- Nao renomeie IDs, rotas ou `data-route` sem verificar o JavaScript.
- Nao remova compatibilidade de endpoints antigos sem migracao clara.
- Em limpeza/exclusao de registros, proteja referencias compartilhadas antes de apagar arquivos.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
