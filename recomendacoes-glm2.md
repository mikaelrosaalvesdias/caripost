# Parecer GLM-2 — Plano v3 Caripost

## Veredito
**Aprovo sem reservas.** v3 incorporou formalmente, como blocos "Aceite" em cada marco, os 6 detalhes que apontei na v2. Plano pronto para execução.

## Modo de operação agora
Plano v3 aprovado e em implantação pela Claude Code. Meu papel nesta fase: **acompanhar a codagem ao vivo e apontar erros para corrigir depois**. Este arquivo funciona como **log vivo de issues encontrados durante a implementação**.

## Flags de execução (critérios de aceite silenciosos)
1. **Parser JSON do LLM (1A)**: fallback escalonado — nunca 500.
2. **`meta.carousel_slides` crescendo (2/3)**: se inflar, partir pra tabela filha.
3. **Fixtures do `regressao_check.py`**: `flow_id`/`layout_variant` pré-setados no **setup**.
4. **Lock de migrations (0)**: `flock`/sentinel ou `schema_migrations` com `BEGIN IMMEDIATE` — **não** `PRAGMA locking_mode`.

---

## Log de issues (vivo)

### 2026-06-30 · issue #1 — Snapshot do WIP em andamento (informativo, NÃO conclusão)
**Nota**: a codificadora **ainda está codando**. Este snapshot é do meio do trabalho, não do fim. Conclusões abaixo são provisórias e serão revisitadas quando ela parar/commitar.

**O que está no working tree até agora** (branch `caripost-conteudo-evento`, ahead 4, 12 arquivos modificados):

- **Marco 0 parcial**: `_audit_open_access()` em `app/main.py:5320-5340` (auditoria read-only de quem usa o acesso aberto antes de fechar). ✅ Correto e bem feito (gated no log, não bloqueia, registra UA/IP/rota). **Ainda não**: runner de migrations. `app/db.py` imodificado desde 15/jun; sem rastro de `schema_migrations`/`migrate()` em `app/`. **Provavelmente ela ainda vai chegar nisso** — não é "faltou", é "ainda não chegou".
- **Trabalho de vídeo v1.27.24** dominando o WIP (sprint paralela ao plano):
  - `ai.py`: gerador de imagem kie.ai (`generate_image_kie`, `kie_image_models`, 5 modelos em `CURATED_IMAGE_KIE`).
  - `video_composer.py`: CTA endcard + dublagem pt-BR (TTS sobre áudio do modelo).
  - `posts.py`: per-clip seconds, `carousel_first_frame_url` na cena 1, `target_total_seconds`, endpoint `image-providers`.
  - `apps-manage.jsx`: `UsersPanel` (CRUD de usuários) e `ImageProvidersPanel`.
- **A confirmar com a codificadora**: a ordem dela é (a) fechar vídeo v1.27.24 primeiro, depois entrar no plano v3, ou (b) está mesclando? Se (a), tudo OK — só precisa commitar vídeo separado antes de iniciar Marco 0. Se (b), risco de Marco 0 nunca fechar sem separação clara de commits.

**Sugestão quando ela parar**: antes de commitar, separar em 2 commits limpos — (1) "feat(v) v1.27.24: extras de vídeo + kie imagem + users panel" e (2) "feat(marco-0): runner de migrations + fechar dev-mode". Sem isso, histórico fica misturado e difícil de reverter se um dos dois quebrar.

### 2026-06-30 · issue #2 — INCONSISTÊNCIA DE VERSÃO (alta severidade · viola AGENTS.md/CLAUDE.md)
A regra "bumpar versão nas 5+ strings" está quebrada no WIP atual. Snapshot:

| Local | Valor |
|---|---|
| `app/main.py:74` `version=` | **1.27.30** |
| `app/os/apps-manage.jsx:3` `MP_OS_VERSION` | **v1.27.23** (nem no 24!) |
| `app/os/index.html` cache-bust `?v=` | **12730** |
| `app/os/shell.jsx:202` `boot-ver` | **v1.27.24** |
| `app/ui/index.html` 3 spots (`sidebar-version`, `os-tray-pill`, `version-badge`) + `app.js?v=` | **v1.27.24** + `?v=12724` |
| `app/ui/app.js:537` `CHANGELOG[0]` | **v1.27.24** |
| `CHANGELOG.md:5` topo | **v1.27.24** |

Mistura 23/24/30 no mesmo deploy. Década de quebração: browser vai cachear JS velho (cache-bust 12730 puxa apps-manage que ainda se anuncia v1.27.23 no `MP_OS_VERSION`), usuário vê badge "v1.27.24" numa API que se diz 1.27.30.

**Correção sugerida**: antes de qualquer commit/deploy, alinhar **todas** as 6+ strings num valor único. Se a entrega real do WIP é "extras v1.27.24", alinhar em `1.27.24` (reverter `main.py` e `os/index.html` para `12724`). Se é novo marco, alinhar em `1.27.30` (bumpar `MP_OS_VERSION`, `shell.jsx`, `app.js CHANGELOG`, `ui/index.html` 3 spots, `CHANGELOG.md`).

### 2026-06-30 · issue #3 — `_audit_open_access` em RAM (baixa severidade · robustez)
`_OPEN_ACCESS_SEEN: set` em `app/main.py:5319` é **por-processo**. Em swarm com N réplicas, cada uma tem sua seen-set → log vira duplicado entre elas (mesma sig registra N vezes, 1 por réplica). Não quebra a auditoria (é só ruído no log) mas diminui a utilidade do critério de aceite "rodar 1 ciclo e ver quem usa".

**Correção sugerida**: subs por `INSERT OR IGNORE` numa tabela `open_access_seen(route, ua_prefix)` -- idempotente跨-réplicas e vira query-friendly. Ou, mais simples: aceitar a duplicação e dedup no relatório (`sort -u` no `open_access_audit.log`).

### 2026-06-30 · issue #4 — Caminho do log hardcoded (baixa severidade)
`_audit_open_access` escreve direto em `/data/open_access_audit.log` (`app/main.py:5339`). Se `/data` não existir no container, `open(... 'a')` levanta — capturado pelo `except Exception: pass`, mas aí a auditoria fica muda silenciosamente. O `getattr` em `app/main_utils.py:18-40` é referenciado no plano mas não foi tocado.

**Correção sugerida**: garantir `os.makedirs("/data", exist_ok=True)` no startup (antes do `_audit_open_access` rodar) ou cair num fallback `os.path.join(os.getcwd(), "open_access_audit.log")`. Auditar silenciosamente sem salvar não cumpre o aceite do Marco 0.

### 2026-06-30 · issue #5 — Esconda UsersPanel do Marco 4 prematuro (alta · escopo)
`UsersPanel` (`app/os/apps-manage.jsx:769-816`) chama `/auth/users`, `/auth/me`, `/auth/users/:id` (CRUD). O plano coloca auth real + papéis em **Marco 4** (multi-cliente). Expor esse painel agora, **com dev-mode aberto**, é perigoso: qualquer um cria usuário admin no sistema sem chave. O endpoint `/auth/users` provavelmente já exige role=admin no backend — confirmar; se não, é falha de segurança ativa.

**Correção sugerida**: (a) confirmar que `/auth/users` exige role=admin e rejeita se `CARIPOST_API_KEY` vazio; (b) se não, **não subir** `UsersPanel` antes do Marco 0 fechar dev-mode; (c)理想 só revelar a aba "Usuários" no Settings quando `whoami().role === 'admin'` (já tem `meId`, falta checar role).

### 2026-06-30 · issue #6 — `kie.credits` aprendido mas sem enforcement (média · coleta de débito)
`generate_image_kie` (`ai.py`) aprende o custo real (`kie.credits.<model>`) e salva no `settings`. Bom. Mas o plano explicita: "**Billing com enforcement antes da geração, não só log de custo**". Hoje `generate_image_with_cost` chama `generate_image_kie` sem checar saldo — apenas aprende o custo depois. Não débita, não bloqueia. Isso é exatamente o que o plano avisa como futuro débito no Marco 4, mas o código está cimentando o padrão "log-only" que terá que ser refatorado depois.

**Correção sugerida**: isolar a chamada kie por trás de um `spend_credits(company_id, cost, kind)` (mesmo que hoje só valide `company_id > 0` e decremente se saldo existir). Quando Marco 4 chegar, só pluga o `usage_log` + `company_credits`. Evita refatoração em Y.

### 2026-06-30 · issue #7 — `_kie_SEEDREAM_SIZE` aspects duvidosos (baixa · bug silencioso)
`_KIE_SEEDREAM_SIZE` (`ai.py:994`) mapeia `2:3` e `3:4` ambos para `portrait_4_3`, e `3:2`/`4:3` para `landscape_4_3`. Aspect 2:3 (proporção selfie vertical longa) virando 4:3 (mais quadrado) vai achatar a composição. Seedream vai gerar imagem com aspecto errado — usuário pede 9:16 e recebe algo próximo de 4:3.

**Correção sugerida**: validar no catálogo da Seedream os enums reais (provável: `portrait_16_9` para 9:16/2:3). Não推测 — checar a doc do provedor antes de commitar o mapeamento. Senão, a primeira arte kie vai sair com crop errado e ninguém vai entender por quê.

### 2026-06-30 · issue #8 — `video_segment_plan` retorno quebrou contrato (média · compat)
Antes: `Tuple[int, int]` (n_cenas, per). Agora: `Tuple[int, List[int]]` (n_cenas, lista_segs). Qualquer chamador antigo que faça `k, per = video_segment_plan(...)` e use `per` como int vai quebrar (recebe `List[int]`, itera, soma errado). Os callers dentro do diff foram migrados, mas **callers externos/legados** precisam ser auditados.

**Correção sugerida**: rodar `grep -rn "video_segment_plan" app/` e confirmar todos os callers. Se houver legado, ou migrar junto, ou fazer o retorno compatível (`per` continua int quando lista tem 1 elemento, lista quando >1) — mas isso é tech debt pior. Melhor migrar todos.

---

## Resumo do momento (WIP em andamento — atualizar quando ela parar/commitar)
- **Marco 0**: ~30% no working tree (auditoria). Runner de migrations e fechar dev-mode ainda não chegaram — provavelmente ela ainda vai codar.
- **Vídeo v1.27.24**: sprint paralela dominando o WIP — confirmar com ela se é ordem "vídeo primeiro, plano depois" ou mescla.
- Demais marcos do plano v3: aguardando.
- Versão quebrada entre 1.27.23 / 1.27.24 / 1.27.30 nas 6 strings — **válida como issue mesmo em WIP**, pois configura risco de deploy acidental.
- Risco a confirmar: `UsersPanel` + dev-mode aberto — checar se `/auth/users` exige role=admin.

## Status do acompanhamento
**Continuo monitorando.** Próxima passada: quando ela commitar ou avisar que parou._issues #2-#8 (versão, lock set em RAM, log hardcoded, UsersPanel gating, kie sem enforcement, mapeamento Seedream, contrato `video_segment_plan`) permanecem **válidas como observações técnicas** independentes de a codificação ter terminado ou não — todas serão revalidadas quando ela fechar.

---

## Atualização 2026-07-01 · Marco 0 aparentemente FECHADO

**Bom sinal**: `app/migrations.py` (145 linhas, novo) está ** CORRETO** e segue o plano à risca:
- Lock entre processos via `fcntl.flock` em sentinel `data/.schema-migrate.lock` (não PRAGMA — acertou na primeira).
- `BEGIN IMMEDIATE` como 2ª camada de serialização no DB.
- Registry `MIGRATIONS = [(1, "baseline")]` append-only; idempotente (`INSERT OR IGNORE` + verificação por `version`).
- `ensure_column`/`ensure_index` helpers prontos para os Marcos 2/3 — e tolerante a "duplicate column name" (defensivo contra race residual).
- Completou o doc `docs/marcos/marco-0-fundacao.md` descrevendo testes de idempotência e concorrência cross-process (8 processos → 1 aplica).
- Wiring no `_startup()` em app/main.py:5449 — `init_db/init_agency_db/init_companies_db` rodam **dentro** de `schema_lock()`, depois `run_migrations(_locked=True)` (uma só aquisição de lock, sem self-deadlock). ✅
- Doc afirma deploy real (`caripost-new:1.27.31`, serviço `metaporn-new_adult-meta`) e validação in-prod (`/health=1.27.31`, `schema_migrations=[(1,'baseline')]`, sem chave → `unauthorized` com dado retido).

### issue #9 — Versão UI NÃO foi bumpada em todos os pontos (alta · viola AGENTS.md/CLAUDE.md)
Apesar do doc de Marco 0 afirmar deploy em 1.27.31 e `main.py`/`apps-manage.jsx`/`os/index.html` estarem em 12731, **três grupos continuam em 1.27.24**:

| Local | Valor | Deveria ser |
|---|---|---|
| `app/os/shell.jsx:202` `boot-ver` | `v1.27.24 · vídeo com identidade real do produto` | `v1.27.31 · Marco 0 fundação` |
| `app/ui/index.html:5717` `sidebar-version` | `v1.27.24` | `v1.27.31` |
| `app/ui/index.html:7274` `os-tray-pill` | `v1.27.24` | `v1.27.31` |
| `app/ui/index.html:7279` `version-badge` | `v1.27.24` | `v1.27.31` |
| `app/ui/index.html:7348` `app.js?v=12724` | `12724` | `12731` |
| `app/ui/app.js:537` `CHANGELOG[0]` | `v1.27.24` | `v1.27.31` (entrada do Marco 0) |
| `CHANGELOG.md:5` topo | `v1.27.24 - 2026-06-30` | `1.27.31 - 2026-07-01 · Marco 0` |

Consequência: usuário do OS público (`app/ui/`) e do shell de boot verá v1.27.24, mas a API se anuncia 1.27.31 e o `apps-manage.jsx` do OS interno diz v1.27.31 — **inconsistência visível**. Pior: `app.js?v=12724` no `ui/index.html` faz cache-bust com número velho, então se ela já re-deployou com `?v=12731` no `os/index.html` mas esqueceu de tocar `ui/index.html`, o app público pode estar servindo JS stale do cache do browser.

**Correção sugerida** (rápida, <2min): bumpar as 7 ocorrências acima para 1.27.31 e adicionar entrada no `CHANGELOG[0]` e no `CHANGELOG.md` topo:
```
## v1.27.31 - 2026-07-01 · Marco 0 — fundação
- **feat: runner único de migrations** (`app/migrations.py`) — `schema_lock()` (fcntl.flock) + `BEGIN IMMEDIATE`, idempotente, cross-process. Base para `flow_id`/`layout_variant`/`company_credits`/`usage_log`.
- **feat: dev-mode fechado** — `CARIPOST_API_KEY` setado no serviço; sem chave → dado retido.
- **fix: auditoria de acesso aberto** (read-only) em `/data/open_access_audit.log` (mantida p/ diagnóstico).
- Versão: main.py 1.27.31, OS/UI cache bust v=12731.
```

### issue #10 — Limitação do HTTP 200 no `unauthorized` (média · documentada, rastreável)
Doc do marco reconhece: `_require_api_key` retorna dict (vira HTTP 200) em vez de 401, em 86 call-sites. Acesso **é** negado, mas status code engana proxy/monitor/AKimbo. É dívida conhecida — não bloqueia Marco 0, mas precisa virar issue tracking para non-migration quando third-party (n8n, monitoring de cliente) fizer retry baseado em 401/N-401 e receber 200 silencioso.

**Correção sugerida** (longo prazo): encapsular `_require_api_key` num decorator que `raise HTTPException(401)` ou, no mínimo, expor um helper `_api_key_required_or_401(request)` que retorna `JSONResponse(..., 401)` e migrar endpoint-a-endpoint. Não entrar no Marco 0.

### issue #11 — `_OPEN_ACCESS_SEEN` por-processo (revisita issue #3)
A issue #3 que levantei antes se mantém válida agora que dev-mode fechou: a set em RAM só dedupe dentro de 1 réplica. Em swarm com N réplicas, mesmo sig aparece N vezes no `/data/open_access_audit.log`. **Como o doc do marco diz que só 2 entradas foram observadas em prod**, deve ser swarm de 1 réplica hoje — mas isso muda se escalar. Não é bloqueador; só registrar no Marco 0 que o log pode ficar ruidoso em futuro multi-réplica e considerar `INSERT OR IGNORE` numa `open_access_seen` quando virar relatório de diagnóstico real.

### issue #12 — Branch ainda "ahead 4" sem commit do Marco 0
`git status` mostra working tree com 12 arquivos modificados + 3 não-rastreados (`migrations.py`, `marco-0-fundacao.md`, `app/assets/`). Doc de Marco 0 afirma deploy feito, mas **o commit do marco não foi feito** (`git log` para em `e0e70fd feat(video) v1.27.23`). Risco: se outro dev/replica reiniciar o container, sobe código sem migrations → boot quebra (`from .migrations import schema_lock` falha em ImportError).

**Correção sugerida** (alta prioridade): commitar Marco 0 **agora**, separado do WIP de vídeo:
```
git add app/migrations.py app/main.py docs/marcos/marco-0-fundacao.md
# + bump de versão das 7 strings da issue #9
git commit -m "feat(marco-0) v1.27.31: runner de migrations + fechar dev-mode"
git push
```
O restante (WIP de vídeo kie/users/dublagem/CTA) fica noutro commit ou stash.

## Resumo do momento (atualizado)
- **Marco 0**: implementação **correta e completa** (runner + wiring + dev-mode + auditoria + doc + deploy). Falta: bump das 7 strings UI + commit/push.
- **Vídeo v1.27.24**: sprint paralela ainda no working tree, não commitada.
- Demais marcos: aguardando.
- Risco de segurança confirmado no Marco 0 doc: `UsersPanel` continua exposto? Precisa checar se `/auth/users` rejeita sem role=admin mesmo em dev-mode agora fechado (a auditoria mostrou 2 entradas só —istério usuário único admin logado, mas UsersPanel aparece pro não-admin?).

## Recomendação imediata ao usuário
1. **Commitar Marco 0 isolado** (com bump de versão nas 7 strings pendentes) antes de qualquer outro passo.
2. Verificar se `/auth/users` POST/PUT/DELETE rejeita quando `_require_api_key` não retorna user com role=admin — senão, esconder `UsersPanel` do OS até o Marco 4 real.
3. Stash / commit separado do WIP de vídeo v1.27.24 para desfazer o entulho.
4. Só então iniciar Marco 1A.