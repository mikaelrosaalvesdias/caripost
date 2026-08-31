# Marco A — Tenancy real: usuário → empresa (produto vendável)

**Versão:** v1.27.71 · **Data:** 2026-07-05 · **Migração:** m3 (`app_users.company_id` + índice)

## O que mudou
1. **`app_users.company_id`** (m3, runner de migrations). NULL = super-admin/staff da agência.
2. **Role `owner`** (dono de empresa cliente) com abas de cliente (`ROLE_DEFAULTS["owner"]` em auth.py:
   conteudo, acervo, aprovacao, calendar, clientes, publisher, notificacoes, consumo).
3. **Token carrega `company_id`** (claims em `_make_token`, login em auth.py).
4. **Middleware de tenancy** (`main.py _tenant_scope_guard`): usuário escopado →
   (a) `/api/companies/{outra}` → 403; (b) recursos de agência bloqueados (/auth/users, /runs, /api/creators,
   /api/dmca, /api/trends, /api/financial, /settings/tokens, /api/ai-settings, /api/billing/credits|features…).
5. **Guards por endpoint** (company no body/query): posts list (força escopo), render-carousel,
   generate-briefing/preflight/branded-video (4 endpoints via anchor comum), edit-art, social workspace,
   billing balance/summary (força a própria). `companies` list filtrada pelo escopo.
6. **Helpers** em `main_utils.py`: `scoped_company_id(request)` + `company_access_denied(request, cid)`.
7. **Shell**: usuário cliente vê só os apps de cliente (`CLIENT_APPS` em shell.jsx + `window.__mpUser` via api.js).
8. **Criar acesso**: `POST /auth/users {username, password, role:"owner", company_id}` (admin only).

## Testes executados (in-container, API real)
| Teste | Resultado |
|---|---|
| Criar owner santbeauty | 200, role owner, company amarrada |
| Login owner → token com company_id | ✅ |
| GET /api/companies (owner) | 200 → **só ['santbeauty']** |
| GET empresa alheia (iFibra) | **403** |
| GET posts de empresa alheia | **403** |
| GET billing alheio | **403** |
| GET /auth/users (admin-only) | **403** |
| POST recarga de créditos | **403** |
| Admin lista empresas | 200 → as 3 |
| Regressão golden | OK |

## Usuário de teste criado
`dona@santbeauty.com` / `SantB2026!` (owner da santbeauty) — usar pra validar a UI.

## Próximo
Marco B — Mercado Pago (planos + recarga + webhook).
