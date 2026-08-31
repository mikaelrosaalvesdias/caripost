# Recomendações Codex

## Parecer sobre v1.27.39

**Veredito:** aprovado tecnicamente para seguir ao Marco 1A.

## Conferido

- `app/main.py` está em `1.27.39`.
- OS está em `v1.27.39` e cache bust `12739`.
- UI legada está com os 3 badges visíveis em `v1.27.39`.
- UI legada carrega `app.js?v=12739`.
- `app/ui/app.js` tem changelog interno `v1.27.39`.
- `CHANGELOG.md` tem entrada `v1.27.39`.
- `get_ai_config()` default: `omniroute` + `cc/claude-opus-4-8`.
- `get_image_config()` default: `omniroute`.
- `/ai-models` reporta `image_provider` default como `omniroute`.
- Prefixos de imagem tratados: `kie:`, `omni:`, `cometapi:`, `cometapi-gemini:`, `piapi:`.
- `cometapi` e `cometapi_gemini` usam a mesma chave CometAPI.
- Validações básicas passaram: `py_compile`, `node --check app/os/api.js`, `git diff --check`.

## Ressalva

- Worktree ainda está grande e misturado. Não fazer commit amplo.
- Separar commits por entrega/marco e excluir arquivos locais de recomendação, assets não intencionais e mudanças fora do escopo.

## Próxima ação

Pode seguir para o Marco 1A: influencer/foto antes do briefing.
