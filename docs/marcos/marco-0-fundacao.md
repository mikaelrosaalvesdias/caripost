# Marco 0 — Fundação: runner de migrations + fechar dev-mode

**Versão:** v1.27.32 · **Deploy:** `metaporn-new:1.27.32` no serviço `metaporn-new_adult-meta` (convergido) · **Data:** 2026-07-01

> Revisão pós-auditoria do Codex: adicionado **auth fail-closed** (v1.27.32) — ver seção 3.

## Objetivo
Preparar a base para os marcos seguintes (que vão adicionar colunas `flow_id`, `layout_variant`, depois `company_credits`/`usage_log`) e fechar o acesso aberto que expunha a API em qualquer demo externa. Sem isso, mexer no banco em produção era frágil e a plataforma ficava sem auth.

## O que mudou (técnico)

### 1. Runner único de migrations — `app/migrations.py` (novo)
- **`schema_lock()`**: lock **entre processos** via `fcntl.flock` num sentinel (`data/.schema-migrate.lock`). Serializa réplicas do swarm no startup, para que os `ALTER TABLE ... ADD COLUMN` guardados em `init_db()`/`init_companies_db()` nunca corram entre réplicas.
- **`run_migrations()`**: aplica migrations numeradas e idempotentes, registrando cada uma na tabela-ledger `schema_migrations`. Cada migração roda em `BEGIN IMMEDIATE` (segunda camada de serialização no nível do DB — **não** `PRAGMA locking_mode`, que só isola dentro de uma conexão). Re-rodar é no-op.
- **`ensure_column()` / `ensure_index()`**: helpers idempotentes que os próximos marcos usam para adicionar colunas/índices. `ensure_column` tolera a corrida de "duplicate column name" defensivamente.
- **Único padrão de schema**: cobre o mesmo `runs.db` usado por `db.py` **e** `db_companies.py` (não cria dois padrões). Migrations são **só-crescentes** (SQLite não tem `DROP COLUMN` fácil) — rollback de marco ruim = drop manual, então validar antes de deployar.
- Registry atual: `[(1, "baseline")]` — prova o runner ponta-a-ponta; Marco 2 anexa `flow_id`, Marco 3 `layout_variant`.

### 2. Wiring no boot — `app/main.py` `_startup()`
As três inits (`init_db`, `init_agency_db`, `init_companies_db`) passaram a rodar **dentro de `schema_lock()`**, seguidas de `run_migrations(_locked=True)`. Uma só aquisição de lock por boot; sem self-deadlock.

### 3. Dev-mode fechado — agora **fail-closed** (v1.27.32)
`ADULT_META_API_KEY` setado no serviço via `docker service update --env-add`. Ambas as funções de auth (`_require_api_key` main.py, `require_api_key` main_utils.py) **aceitam `X-Session-Token`** → sessões logadas e o OS seguem funcionando sem mudança no front.

**Correção crítica (auditoria Codex):** antes, sem `ADULT_META_API_KEY` o código **abria** a API (`return None`) — se um redeploy dropasse o env, a plataforma reabria sozinha. Agora é **fail-closed**: sem chave e sem sessão válida → **rejeita**; acesso aberto só com opt-in explícito `ALLOW_OPEN_ACCESS=1` (dev). Sessão válida sempre passa (checada antes). Endpoints públicos legítimos (`/health`, `/runs/{id}/light`, OAuth `social /callback`) são **isentos** (não chamam a função de auth) → seguem abertos. Verificado no ar: `/runs/{id}/light` responde 200 sem chave; `/runs` sem chave → `unauthorized`, com chave → 200.

## Auditoria (gate antes de fechar)
Evidência empírica do `/data/open_access_audit.log` no container: **2 entradas** (1 browser + 1 teste curl manual). **Nenhuma integração automática** dependia do acesso aberto. Serviços internos (scheduler, publish-pipeline) usam chamadas **in-process** (sem HTTP); n8n é **outbound**; `/health` é isento. Risco de fechar: ~zero.

## Como foi testado
- **Runner (local, temp DB):** idempotência (run#1→`[1]`, run#2→`[]`, ledger com 1 linha); `ensure_column` idempotente + tolerante a duplicate-column; **concorrência cross-process** (8 processos → exatamente 1 aplicou, ledger com 1 linha, zero erro).
- **Produção (no ar):** `/health` = `1.27.31`; `schema_migrations` = `[(1,'baseline',...)]` (migração rodou no boot real); sem chave → payload `unauthorized` (dado retido); com chave → 200 com dado; OS público serve `?v=12731`.

## Limitação conhecida (não é bug de segurança)
Endpoints de `main.py` que usam `_require_api_key` devolvem o erro `unauthorized` com **HTTP 200** (a função retorna um dict e o endpoint o retorna direto), em vez de 401. O acesso **é** negado (o dado não é retornado); só o status code é inconsistente. Corrigir tocaria 86 call-sites → fora do escopo do Marco 0.

## Próximo
Marco 1A — mover seleção do influencer para antes do briefing (contexto leve, JSON estruturado).
