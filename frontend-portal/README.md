# Caripost Creator Portal

Portal separado para criadores, feito em React + Vite + Tailwind.

## Desenvolvimento

```bash
cd frontend-portal
npm install
npm run dev
```

Opcionalmente defina a URL da API:

```bash
cp .env.example .env
```

## Build

```bash
cd frontend-portal
npm run build
```

## Docker

```bash
docker build \
  --build-arg VITE_CARIPOST_API_BASE=https://caripost.n8nmikael.com.br \
  -t frontend-portal:latest \
  ./frontend-portal
```

## Rotas

- `/` Dashboard
- `/videos` Meus vídeos
- `/ganhos` Ganhos
- `/tendencias` Tendências
- `/upload` Upload
- `/agenda` Agenda
