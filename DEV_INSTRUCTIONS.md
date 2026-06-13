# Instruções de Desenvolvimento — Adult Meta

> Este arquivo deve ser consultado ANTES de qualquer alteração no código.

---

## 1. Antes de Alterar Qualquer Coisa

- Ler o arquivo relevante antes de editar (nunca editar de memória)
- Verificar se a função já existe antes de criar uma nova
- Entender o impacto da mudança em outros módulos que dependem do que será alterado
- Explicar ao usuário: **o que vai mudar, por que, e qual o risco**

---

## 2. Fluxo Obrigatório para Qualquer Alteração

```
1. Ler os arquivos afetados
2. Explicar a mudança (o que, por que, risco)
3. Implementar
4. Testar via curl/container antes de confirmar
5. Atualizar versão (main.py + index.html sidebar + index.html badge)
6. Atualizar CHANGELOG em app/ui/app.js
7. Atualizar cache bust do app.js em index.html (?v=XXXXX)
8. Validar que todos os 4 lugares têm a mesma versão
9. Fazer commit e push para o GitHub depois da validação
10. Só então dizer "pronto"
```

---

## 3. Atualização de Versão — 4 Lugares Obrigatórios

Toda alteração que vai para deploy **deve** atualizar todos os 4:

| Arquivo | Onde | Exemplo |
|---------|------|---------|
| `app/main.py` | `FastAPI(version="X.Y.Z")` linha ~58 | `version="1.12.5"` |
| `app/ui/index.html` | `<strong>vX.Y.Z</strong>` linha ~3269 | sidebar |
| `app/ui/index.html` | `<div class="version-badge">vX.Y.Z</div>` linha ~4494 | badge |
| `app/ui/index.html` | `app.js?v=NNNNN` linha ~4531 | cache bust |

**Validar antes do deploy:**
```bash
grep -n "version=\|v1\." app/main.py app/ui/index.html | grep -v changelog
```

---

## 4. Testar Antes de Confirmar

Nunca confirmar "está pronto" sem testar. Para endpoints de API:

```bash
# Testar GET
curl -s https://caripost.n8nmikael.com.br/api/ENDPOINT -H "X-API-Key: secret"

# Testar POST
curl -s -X POST https://caripost.n8nmikael.com.br/api/ENDPOINT \
  -H "X-API-Key: secret" \
  -H "Content-Type: application/json" \
  -d '{"campo": "valor"}'

# Verificar versão no servidor
curl -s https://caripost.n8nmikael.com.br/ | grep -o "v1\.[0-9][0-9]\.[0-9]" | sort -u

# Verificar versão no container
CONTAINER=$(docker ps --filter name=adult-meta --format '{{.ID}}' | head -1)
docker exec $CONTAINER python3 -c "from app.main import app; print(app.version)"
```

---

## 5. Deploy

O deploy **não deve ser executado automaticamente** a não ser que o usuário autorize explicitamente. Quando autorizado:

```bash
cd /var/www/adult-meta && docker build -t adult-meta:latest . && docker service update --force metaporn_adult-meta
```

Antes de buildar, validar que os 4 lugares da versão estão consistentes (ver seção 3).

---

## 6. CHANGELOG (app/ui/app.js)

Toda alteração deve ter entrada no changelog no topo do array de versões em `app/ui/app.js`:

```javascript
{
  version: 'X.Y.Z',
  date: 'YYYY-MM-DD',
  changes: [
    { type: 'feat', text: 'Descrição clara do que foi adicionado.' },
    { type: 'fix',  text: 'Descrição do bug corrigido e causa raiz.' },
    { type: 'perf', text: 'Descrição da melhoria de performance.' },
  ]
},
```

Tipos: `feat` (nova funcionalidade), `fix` (correção), `perf` (performance), `refactor` (refatoração).

---

## 7. GitHub Sempre Atualizado

Depois de validar uma entrega, manter o repositorio remoto atualizado:

```bash
git status -sb
git diff --check
git add <arquivos-intencionais>
git commit -m "descricao objetiva"
git push
```

Nunca commitar `.env`, banco, midia, logs, tokens ou arquivos locais do servidor. Se o push falhar por autenticacao, deixar o commit local pronto e informar o bloqueio.

---

## 8. Arquivos Críticos — Mapa do Projeto

| Arquivo | Responsabilidade |
|---------|-----------------|
| `app/main.py` | Endpoints principais, probe de vídeo, HDR detection, ffmpeg utils |
| `app/services/auto_editor_pipeline.py` | Pipeline completo do AutoEditor (2000+ linhas) |
| `app/routers/auto_editor.py` | Endpoints REST do AutoEditor |
| `app/db.py` | SQLite: jobs, settings, runs, multipart uploads |
| `app/ui/index.html` | Frontend HTML — versão em 3 lugares |
| `app/ui/app.js` | Frontend JS — toda a lógica de UI e CHANGELOG |
| `AUTOEDITOR_TECNICO.md` | Documentação técnica do AutoEditor |
| `DEV_INSTRUCTIONS.md` | Este arquivo |

---

## 9. Regras Gerais

- **Nunca** confirmar que algo funciona sem testar
- **Nunca** fazer deploy sem validar versão nos 4 lugares
- **Sempre** explicar o que vai mudar antes de mudar
- **Sempre** atualizar o CHANGELOG
- **Sempre** manter o GitHub atualizado depois da entrega validada
- **Sempre** ler o arquivo antes de editar
- **Sempre** consultar este arquivo antes de qualquer alteração
