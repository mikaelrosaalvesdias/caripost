# fix v1.27.10 — duração do vídeo no briefing (era cache, não lógica)

## Sintoma
Usuário trava 15s (e escreve "15 segundos" no assunto), mas o construtor de briefing
de vídeo entrega **"Roteiro p/ ~8s · 1 cena(s)"** — força 8s/1 cena.

## Causa-raiz (NÃO era o código do briefing)
O fix de fato já existia em **v1.27.9** (commit 4904ee3), provado correto:
- backend `generate_briefing(..., seconds=15)` → 2 cenas (16s) ao vivo;
- front `apps-conteudo.jsx` passou a mandar `seconds: _vsecEff` (vsec || ContState.videoSeconds || 0) e a persistir `videoSeconds`.

**Mas o v1.27.9 esqueceu de subir o cache-bust token do arquivo alterado.**
`index.html` referencia cada `.jsx` com `?v=NNNNN`. O v1.27.9 subiu a maioria pra `12790`,
mas deixou **`apps-conteudo.jsx?v=12702`** (e `apps-manage.jsx`, `shell.jsx`) no valor antigo.
Como a URL não mudou, o navegador continuou servindo o **JSX velho em cache** (sem o fix) —
por isso o botão ainda aparecia "Gerar roteiro do assunto" **sem** o sufixo "· 15s" que o v1.27.9 adicionou.

## O que mudou em v1.27.10
- `app/os/index.html`: **todos** os 10 `?v=` unificados em `12710` (mata o drift de uma vez — nunca mais um arquivo alterado ficar com token velho).
- `app/main.py`: `version="1.27.10"`.
- `app/os/apps-manage.jsx`: `MP_OS_VERSION = 'v1.27.10'`.
- Nenhuma mudança de lógica/motor. Só cache-busting + versão.

## Deploy (no ar)
- Build overlay `FROM metaporn-new:1.27.9` + `COPY app /app/app` → `metaporn-new:1.27.10` (evita 429 do Docker Hub).
- `docker service update --image metaporn-new:1.27.10 --update-order start-first metaporn-new_adult-meta` → **converged**.
- Verificado ao vivo: `caripost.cariap.com.br/os/index.html` serve `apps-conteudo.jsx?v=12710`,
  e esse arquivo contém `const _vsecEff = ...` + label "· 15s". Zero tokens 12702/12790 sobrando.

## Como testar
1. Abra `caripost.cariap.com.br/os/` (Ctrl+Shift+R uma vez, pra garantir o index.html novo).
2. Conteúdo → Briefing → Formato **Vídeo** → trave **15s**.
3. O botão deve mostrar **"Gerar roteiro do assunto · 15s"** (essa é a prova visual de que o JS novo carregou).
4. Gere: o briefing deve vir **"Roteiro p/ ~15s · 2 cena(s)"** (2 cenas de 8s), não mais 8s/1 cena.

## Lição (pra não repetir)
Sempre que mexer num `*.jsx`, subir o `?v=` **daquele arquivo** no `index.html`.
A partir de agora os tokens estão unificados — basta subir todos juntos a cada release.
