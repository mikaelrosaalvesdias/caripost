# Contribuindo

Projeto privado e operacional: uma marca real publica a partir dele todo dia. Toda mudança prioriza
**estabilidade, rastreabilidade e segurança de dados** — nessa ordem.

## Antes de alterar

- Leia [`AGENTS.md`](AGENTS.md) e [`docs/engenharia/DEV_INSTRUCTIONS.md`](docs/engenharia/DEV_INSTRUCTIONS.md).
- Entenda os arquivos afetados antes de editar; escopo pequeno e ligado ao pedido.
- Nunca inclua dados reais, mídia, bancos, logs ou secrets no commit.

## Rede de segurança do motor criativo

Mexeu em [`app/services/template_composer.py`](app/services/template_composer.py) ou
[`app/routers/posts.py`](app/routers/posts.py)?

```bash
python3 docs/marcos/regressao_check.py   # antes  → tem que dar OK
# ... sua mudança ...
python3 docs/marcos/regressao_check.py   # depois → só podem mudar as telas que você quis mudar
```

Tela que mudou sem você ter tocado nela é regressão: corrija antes de qualquer deploy.

Construa **lógica configurável, não opção travada**: posição, tamanho, alinhamento e rodapé viram
design tokens com bom default e override por empresa (`creative_config.design`) — é SaaS
multi-empresa, nada de hardcode.

## Checklist de entrega

- [ ] Três strings de versão em sincronia: `app/main.py` (`version=`),
      `app/os/apps-manage.jsx` (`MP_OS_VERSION`) e `?v=` em `app/os/index.html`.
      O CI valida com `.github/scripts/check_version_sync.py`.
- [ ] Cache-bust do `.jsx` alterado subido no `index.html` — sem isso o navegador serve JSX antigo.
- [ ] Changelog interno em `app/ui/app.js` atualizado.
- [ ] [`CHANGELOG.md`](CHANGELOG.md) atualizado quando a mudança for entregue.
- [ ] `python3 -m compileall app` limpo e testes relevantes executados.
- [ ] Deploy feito e confirmado no ar **antes** de pedir teste para alguém.

## Deploy

Só por atualização de imagem do serviço — redeploy de stack não carrega as chaves setadas com
`--env-add` e reabre a plataforma:

```bash
docker build -t caripost:<versão> .
docker service update --image caripost:<versão> metaporn-new_adult-meta
```

Confirme no ar (`https://caripost.cariap.com.br/os/index.html` com o novo `?v=`) antes de anunciar.

## Nomes de infra

Serviço `metaporn-new_adult-meta`, imagem `adult-meta`, bucket `metaporn`, envs `ADULT_META_*` e
`METAPORN_ENCRYPTION_KEY` são **identificadores reais de produção**, herdados do nome antigo do
projeto. Não renomeie sem uma migração planejada: o código já lê `CARIPOST_*` e
[`app/__init__.py`](app/__init__.py) faz o espelhamento.

## Commits

Formato `tipo(escopo): resumo no imperativo` — `feat`, `fix`, `chore`, `docs`, `refactor`, `test`.
Um assunto por commit; o corpo explica o porquê e o que foi verificado.

## Pull requests

Use o template. Descreva **o que mudou**, **como foi validado** e **o risco em produção**.
