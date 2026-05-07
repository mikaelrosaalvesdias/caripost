# MetaPorn Agency Platform

Painel operacional para agência de criadores adultos: ingestão de vídeos, análise por IA, criação de posts, queima de legenda/logo, teasers, AutoEditor, gestão de criadores, publicação, calendário, financeiro, DMCA e portal do criador.

## Estrutura principal

- `app/main.py`: backend FastAPI principal e endpoints legados.
- `app/ui/index.html`: shell HTML do painel admin.
- `app/ui/app.js`: aplicação admin vanilla JS, roteamento por hash e lógica das telas.
- `app/ui/style.css` e `app/ui/style-new.css`: estilos do painel admin.
- `app/routers/`: módulos novos tipados por domínio.
- `app/services/`: pipelines e serviços de backend.
- `app/models/`: modelos Pydantic dos módulos.
- `frontend-portal/`: portal React/Vite do criador.
- `scripts/`: scripts administrativos seguros.
- `stack.example.yml`: exemplo sanitizado de deploy Docker Swarm.

## Brief para redesign

O objetivo visual é transformar a plataforma em um produto SaaS profissional, premium e operacionalmente claro. A referência desejada é mais próxima de um dashboard moderno de gestão, com navegação lateral, agrupamento de módulos, menos poluição no topo e telas com hierarquia visual forte.

### Onde mexer no painel admin

- Admin shell/menu: `app/ui/index.html`
- Estado, rotas e renderização: `app/ui/app.js`
- Design system atual: `app/ui/style-new.css`
- CSS legado/complementar: `app/ui/style.css`

### Onde mexer no portal do criador

- Shell: `frontend-portal/src/components/PortalShell.jsx`
- Branding por criador: `frontend-portal/src/lib/branding.js`
- Estilos globais: `frontend-portal/src/styles.css`
- Telas: `frontend-portal/src/pages/`

## Telas importantes do admin

- `#analyze`: análise/vision/transcrição.
- `#criacao`: criação de posts, logo, legenda, teaser e burn.
- `#media`: gerenciamento de arquivos.
- `#autoeditor`: edição automática.
- `#creators`: gestão de criadores.
- `#publisher`: publicação automática.
- `#trends`: radar de tendências.
- `#calendar`: calendário editorial.
- `#financial`: financeiro.
- `#dmca`: proteção/DMCA.

## Regras para redesign

- Não quebrar IDs usados por JavaScript, como `id="page-criacao"` e botões com `onclick`.
- Pode reorganizar menu e layout, mas manter `data-route` das abas.
- Priorizar navegação lateral com grupos: Produção, Mídia, Agência, Distribuição, Gestão e Sistema.
- Melhorar controles complexos, especialmente posicionamento de logos, seleção de arquivos e status de jobs.
- Usar componentes visuais consistentes: cards, badges, progress, filas, tabelas e modais.
- Evitar esconder ações críticas em menus difíceis.

## Rodar localmente

Backend:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Portal do criador:

```bash
cd frontend-portal
npm install
npm run dev
```

## Segurança

Este repositório não deve conter `.env`, banco local, mídia processada, credenciais S3/MinIO, tokens de IA, chaves Telegram ou configurações locais do servidor.
