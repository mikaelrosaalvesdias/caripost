# Contribuindo

Este projeto e privado e operacional. Toda contribuicao deve priorizar estabilidade, rastreabilidade e seguranca de dados.

## Antes de Alterar

- Leia `AGENTS.md` e `DEV_INSTRUCTIONS.md`.
- Entenda os arquivos afetados antes de editar.
- Mantenha o escopo pequeno e ligado ao pedido.
- Nao inclua dados reais, midias, bancos, logs ou secrets.

## Checklist de Entrega

- Versao atualizada em `app/main.py` e `app/ui/index.html`.
- Cache bust de `app.js` atualizado.
- Changelog interno atualizado em `app/ui/app.js`.
- `CHANGELOG.md` atualizado quando a mudanca for entregue.
- Validacoes executadas e registradas.
- Commit claro e push para o branch correto.

## Validacoes Recomendadas

```bash
python -m py_compile app/db.py app/main.py
node --check app/ui/app.js
git diff --check
```

Para mudancas de API/UI, valide tambem o fluxo real com `curl`, navegador ou container.

## Padrao de Commit

Use mensagens curtas e objetivas:

```text
feat: add run deletion cleanup
fix: preserve logo aspect ratio on burn
docs: improve repository instructions
```
