# Caripost

Plataforma SaaS de criacao e publicacao de conteudo para redes sociais. O projeto centraliza cadastro de clientes/produtos, base de conhecimento por marca, geracao de posts, stories, carrosseis e videos com IA, agenda editorial, publicacao nas redes e acompanhamento dos resultados.

> Status: aplicacao privada em evolucao ativa. Nao publique `.env`, bancos, arquivos de midia, tokens ou dados de clientes neste repositorio.

## Visao Geral

O Caripost e um painel multi-empresa: cada cliente tem sua identidade visual, produtos, planos/subprodutos e base de conhecimento, e o motor criativo usa esses dados para gerar arte e texto no tom da marca.

Principais capacidades:

- Cadastro de empresas, produtos, planos/subprodutos, identidade visual e base de conhecimento (PDF/TXT).
- Motor criativo com IA: post, story, carrossel editorial e video, respeitando briefing e formato.
- Estudio de imagem por referencia (arte inteira pela IA) e compositor proprio em PIL.
- Upload e catalogo de midia, transcricao PT-BR, edicao de SRT, traducao e queima de legendas via FFmpeg.
- Aplicacao de logo com preview, AutoEditor e Video Enhancer.
- Agenda editorial, publicador para redes sociais, tendencias e financeiro.
- Caripost OS (`app/os/`): interface principal em JSX; `app/ui/` e o painel legado ainda embutido.
- Portal React/Vite para o cliente acompanhar conteudo, entregas e calendario.

> Heranca: o projeto nasceu como "MetaPorn/adult-meta", voltado a agencias de conteudo adulto. Nomes de infra (servico `metaporn-new_adult-meta`, imagem `adult-meta`, bucket `metaporn`, volumes e rede) e alguns modulos daquela fase (DMCA, publisher Pornhub, prompts de transcricao adulta) ainda existem e sao mantidos por compatibilidade. Variaveis `ADULT_META_*` continuam aceitas como fallback de `CARIPOST_*` (ver `app/__init__.py`).

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
curl -s https://caripost.n8nmikael.com.br/ | grep -o "v1\\.[0-9][0-9]\\.[0-9][0-9]" | sort -u
docker ps --filter name=caripost
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

- `CARIPOST_API_KEY`
- `AUTH_SESSION_SECRET`
- `PORTAL_JWT_SECRET`
- `CARIPOST_MEDIA_URL_SECRET`
- credenciais S3/MinIO e tokens de IA via ambiente ou storage seguro.

## Licenca

Projeto privado. Uso, copia, distribuicao e deploy dependem de autorizacao do proprietario do repositorio.
