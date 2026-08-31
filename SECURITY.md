# Seguranca

Este repositorio nao deve receber credenciais, bancos, arquivos de midia ou dados reais de clientes/criadores.

## Reporte

Reporte vulnerabilidades diretamente ao proprietario do repositorio por canal privado. Nao abra issue publica com tokens, URLs assinadas, dumps, logs sensiveis ou dados de usuarios.

## Secrets

Mantenha fora do Git:

- `.env`
- `stack.yml` real
- tokens de IA
- credenciais S3/MinIO
- chaves de sessao/JWT
- bancos SQLite e backups
- videos, imagens, legendas, burns e previews

Variaveis obrigatorias em producao devem ser configuradas no ambiente ou em secret manager:

- `CARIPOST_API_KEY`
- `AUTH_SESSION_SECRET`
- `PORTAL_JWT_SECRET`
- `CARIPOST_MEDIA_URL_SECRET`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_ENDPOINT_URL`

## Antes de Publicar

Execute uma varredura basica:

```bash
rg -n "(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE KEY|BEGIN RSA|BEGIN OPENSSH|sk-|ghp_)" \
  --glob '!data/**' --glob '!*.db' --glob '!*.sqlite*' --glob '!node_modules/**' .
```

Placeholders e nomes de variaveis sao esperados. Valores reais devem ser removidos antes do commit.
