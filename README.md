# MetaPorn

Plataforma operacional para agencia de criadores adultos. O projeto centraliza ingestao de midia, analise por IA, transcricao, legendas, aplicacao de logo, criacao de publicacoes, calendario editorial, gestao financeira, DMCA, portal do criador e automacoes de distribuicao.

> Status: aplicacao privada em evolucao ativa. Nao publique `.env`, bancos, arquivos de midia, tokens ou dados de clientes neste repositorio.

## Visao Geral

O MetaPorn foi desenhado como um painel SaaS interno: rapido para operar, com filas visiveis, logs de processamento, historico de criacoes e controles de seguranca para nao perder rastreabilidade.

Principais capacidades:

- Upload e catalogo de videos, imagens e assets de criadores.
- Criacao de posts a partir de videos brutos, com legenda, logo, teaser e metadados.
- Transcricao PT-BR com edicao de SRT, traducao e queima de legendas via FFmpeg.
- Aplicacao de logos com preview e burn mantendo proporcao visual.
- Exclusao de runs/criacoes com limpeza de jobs, registros relacionados e arquivos seguros.
- AutoEditor, Video Enhancer, publicador, calendario, tendencias, financeiro e DMCA.
- Portal React/Vite para criadores acompanharem conteudo, ganhos, perfil e calendario.

## Arquitetura

| Camada | Stack | Caminhos principais |
| --- | --- | --- |
| Backend | FastAPI, SQLite, FFmpeg, boto3 | `app/main.py`, `app/db.py`, `app/services/`, `app/routers/` |
| Admin UI | HTML/CSS/JavaScript vanilla | `app/ui/index.html`, `app/ui/app.js`, `app/ui/style*.css` |
| Portal | React, Vite | `frontend-portal/` |
| Deploy | Docker, Docker Swarm | `Dockerfile`, `deploy.sh`, `stack.example.yml`, `stack.portal.yml` |
| Operacao | Shell scripts | `scripts/` |

## Estrutura

```text
app/
  main.py                 API principal e endpoints legados
  db.py                   Persistencia SQLite e helpers de limpeza
  routers/                Modulos REST por dominio
  services/               Pipelines de IA, publicacao, calendario, DMCA e video
  ui/                     Painel admin
frontend-portal/          Portal do criador
scripts/                  Ferramentas administrativas
*.md                      Documentacao tecnica e instrucoes operacionais
```

## Rodar Localmente

Backend:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Portal:

```bash
cd frontend-portal
npm install
npm run dev
```

Smoke test:

```bash
bash scripts/smoke.sh
```

## Deploy

Use `stack.example.yml` como base sanitizada. Variaveis reais devem ficar fora do Git, em `.env`, secret manager, configuracao de Swarm ou painel de ambiente.

Fluxo recomendado:

```bash
docker build -t adult-meta:latest .
docker service update --force metaporn_adult-meta
```

Depois do deploy, valide a versao exposta pelo app e o status do container:

```bash
curl -s https://metaporn.com.br/ | grep -o "v1\\.[0-9][0-9]\\.[0-9][0-9]" | sort -u
docker ps --filter name=adult-meta
```

## Versao, Changelog e Git

Toda alteracao entregue no app deve manter estes pontos sincronizados:

- `app/main.py`: `FastAPI(... version="X.Y.Z")`
- `app/ui/index.html`: versao visivel na sidebar
- `app/ui/index.html`: `version-badge`
- `app/ui/index.html`: cache bust do script `app.js?v=...`
- `app/ui/app.js`: entrada no `CHANGELOG`
- `CHANGELOG.md`: resumo publico da entrega
- GitHub: commit e push para o branch correto depois de validar

As instrucoes completas para agentes de IA ficam em `AGENTS.md` e `DEV_INSTRUCTIONS.md`.

## Documentacao Tecnica

- `DEV_INSTRUCTIONS.md`: regras obrigatorias antes de mexer no codigo.
- `AGENTS.md`: instrucao operacional para IA/dev manter versao, changelog e Git.
- `AUTOEDITOR_TECNICO.md`: detalhes do AutoEditor.
- `DOCUMENTACAO_LEGENDAS.md`: fluxo de transcricao, SRT e burn.
- `INFRA_OPENROUTER_TRANSCRICAO.md`: infraestrutura de STT via OpenRouter.
- `PROMPTS_TRANSCRICAO_LEGENDAS.md`: prompts e criterios de limpeza.
- `DEPLOY_DIAGNOSTICO.md`: diagnosticos de deploy.
- `DESCRICAO_PROJETO.md` e `PROJETO.md`: contexto de produto.

## Seguranca

Nao versionar:

- `.env`, `stack.yml`, credenciais e tokens.
- `data/`, bancos SQLite, logs e arquivos gerados.
- Midias brutas, legendadas, previews, teasers ou backups.

Configure em producao:

- `ADULT_META_API_KEY`
- `AUTH_SESSION_SECRET`
- `PORTAL_JWT_SECRET`
- `ADULT_META_MEDIA_URL_SECRET`
- credenciais S3/MinIO e tokens de IA via ambiente ou storage seguro.

## Licenca

Projeto privado. Uso, copia, distribuicao e deploy dependem de autorizacao do proprietario do repositorio.
