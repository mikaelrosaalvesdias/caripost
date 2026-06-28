# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

## BLOCKED commands — do NOT attempt these

### curl / wget — BLOCKED
Any Bash command containing `curl` or `wget` is intercepted and replaced with an error message. Do NOT retry.
Instead use:
- `ctx_fetch_and_index(url, source)` to fetch and index web pages
- `ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — BLOCKED
Any Bash command containing `fetch('http`, `requests.get(`, `requests.post(`, `http.get(`, or `http.request(` is intercepted and replaced with an error message. Do NOT retry with Bash.
Instead use:
- `ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### WebFetch — BLOCKED
WebFetch calls are denied entirely. The URL is extracted and you are told to use `ctx_fetch_and_index` instead.
Instead use:
- `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Bash (>20 lines output)
Bash is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### Read (for analysis)
If you are reading a file to **Edit** it → Read is correct (Edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `ctx_execute_file(path, language, code)` instead. Only your printed summary enters context. The raw file content stays in the sandbox.

### Grep (large results)
Grep results can flood context. Use `ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `ctx_execute(language, code)` | `ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Subagent routing

When spawning subagents (Agent/Task tool), the routing block is automatically injected into their prompt. Bash-type subagents are upgraded to general-purpose so they have access to MCP tools. You do NOT need to manually instruct subagents about context-mode.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `ctx_search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `ctx_stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `ctx_doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `ctx_upgrade` MCP tool, run the returned shell command, display as checklist |

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->

## Processo de entrega de MARCOS (plano do carrossel) — OBRIGATÓRIO, NESTA ORDEM

Ao concluir CADA marco (ver `/root/.claude/plans/peaceful-juggling-donut.md`), antes de avisar o usuário:

1. **Testar eu mesmo primeiro.** `py_compile` no mínimo; quando der, executar o fluxo de verdade (ex.: `compose_carousel_slide` com foto placeholder via PIL local — grátis) e **olhar a imagem**. Nunca pedir teste de algo que eu não verifiquei.
2. **Mudar a versão do app** — as 3 strings: `app/main.py` `version=`, `app/os/apps-manage.jsx` `MP_OS_VERSION`, `app/os/index.html` `?v=`.
3. **DEPLOYAR DE VERDADE ANTES DE PEDIR TESTE.** `docker build -t metaporn-new:<v> .` + `docker service update --image metaporn-new:<v> metaporn-new_adult-meta` (NUNCA `deploy.sh`), e **confirmar no ar** (`https://caripost.cariap.com.br/os/index.html` com o novo `?v=`). É **PROIBIDO** mandar o usuário testar algo que não está aplicado no sistema. Serviço: `metaporn-new_adult-meta`.
4. **Gerar o .md de entrega** em `docs/marcos/marco-<N>-<slug>.md`: o que mudou tecnicamente (arquivos/funções/por quê) e como atinge o objetivo do marco.
5. **Explicar simples como testar** — e a avaliação pedida ao usuário deve conter **SÓ o que ESTE marco realmente entrega**. NUNCA pedir pra ele avaliar algo adiado pra um marco futuro (ex.: não pedir "mesma família/coesão de foto" num marco que não trata disso).

## Rede de segurança (NÃO estragar o que já foi aprovado) — OBRIGATÓRIO

O medo do usuário (e já aconteceu no v1.25.78): melhorar X e quebrar Y que já estava aprovado. Para evitar:

1. **ANTES de mexer no motor** (`template_composer.py`/`posts.py`): rodar `python3 docs/marcos/regressao_check.py` (golden determinístico, grátis, sem IA). Tem que dar OK.
2. **DEPOIS de mexer**: rodar de novo. **Só podem mudar as telas que eu QUIS mudar.** Se mudou uma tela que eu não toquei = regressão → corrijo antes de qualquer deploy.
3. **Quando o usuário APROVAR um marco:** (a) `cp` dos arquivos do motor pra `docs/marcos/backups/<marco>/` (ponto de restauração); (b) `python3 docs/marcos/regressao_check.py --update` pra fixar o novo golden aprovado.
4. **Construir LÓGICA CONFIGURÁVEL, não travar opções.** É SaaS multi-empresa: posição/tamanho/alinhamento/rodapé devem virar **design tokens** (defaults bons, override por empresa via `creative_config.design`), nunca hardcode. Tudo moldável.
