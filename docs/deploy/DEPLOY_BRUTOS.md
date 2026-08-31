# 🚀 Deploy Caripost — Brutos-Server (Rocky Linux 9.6)

> **Contexto pré-confirmado pelo diagnóstico:**
> - Rocky Linux 9.6 | Apache HTTPD nas portas 80/443 | Docker NÃO instalado
> - Certbot 3.1.0 instalado | 34 domínios SSL já ativos | mod_proxy/ssl/rewrite ✅
> - ssl.conf global está desabilitado — cada domínio tem seu próprio bloco SSL ✅
> - Projeto copiado via rsync do servidor de origem (213.199.32.244)
> - **Migração com dados** — banco SQLite (76MB) copiado de `/tmp/caripost_runs_backup.db`
>
> **Estratégia:** Docker Swarm single-node + container porta 8765 (127.0.0.1 apenas) + VirtualHost Apache proxy

---

## PRÉ-REQUISITO — Executado no servidor de ORIGEM (213.199.32.244)

> ⚠️ Estes comandos são executados NO SERVIDOR ANTIGO, não no Brutos-Server.
> Confirme com o humano se já foram executados antes de avançar para a Fase 1.

```bash
# Copiar projeto
rsync -avz --exclude='.git' --exclude='__pycache__' \
  /root/clawd/caripost/ \
  root@177.104.176.165:/root/caripost/

# Backup e envio do banco SQLite
cp /var/lib/docker/volumes/caripost_caripost_data/_data/runs.db /tmp/caripost_runs_backup.db
scp /tmp/caripost_runs_backup.db root@177.104.176.165:/tmp/

echo "✅ Pronto para continuar no Brutos-Server"
```

---

## FASE 1 — Instalar Docker

> **Pré-condição:** humano autorizou instalação do Docker.
>
> **Nota sobre firewalld:** Docker cria regras iptables próprias. Como o container só expõe
> a porta 8765 em 127.0.0.1, não há risco para os serviços existentes (Apache/nginx/MariaDB).

```bash
# 1.1 Repositório oficial Docker para CentOS/Rocky Linux
dnf install -y yum-utils
yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# 1.2 Instalar Docker Engine
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 1.3 Iniciar e habilitar no boot
systemctl enable --now docker

# 1.4 Verificar instalação
docker version
docker info | grep -E "Server Version|Operating System|Total Memory|CPUs"
```

**Verificação:**
```bash
docker run --rm hello-world 2>&1 | grep -E "Hello|Error"
```
→ Deve imprimir `Hello from Docker!`. Se der erro, PARE e reporte.

---

## FASE 2 — Inicializar Docker Swarm

```bash
# 2.1 Inicializar Swarm single-node
docker swarm init --advertise-addr 177.104.176.165

# 2.2 Verificar
docker node ls
docker info | grep -A3 "Swarm"
```

→ Deve mostrar 1 nó com status `Leader`.

---

## FASE 3 — Verificar projeto copiado

```bash
# Verificar integridade dos arquivos (rsync já foi feito no servidor de origem)
ls -la /root/caripost/
test -f /root/caripost/Dockerfile && echo "✅ Dockerfile OK" || echo "❌ Dockerfile ausente"
test -f /root/caripost/app/main.py && echo "✅ app/main.py OK" || echo "❌ main.py ausente"
test -f /tmp/caripost_runs_backup.db && echo "✅ Banco SQLite recebido ($(du -sh /tmp/caripost_runs_backup.db | cut -f1))" || echo "❌ Banco não encontrado em /tmp/"
```

Se algum arquivo estiver ausente, PARE e reporte. O rsync do servidor de origem precisa ser refeito.

---

## FASE 4 — Criar stack.yml adaptado (sem Traefik)

```bash
cat > /root/caripost/deploy/stack.brutos.yml << 'EOF'
version: '3.8'

volumes:
  caripost_data:

services:
  caripost:
    image: adult-meta:latest
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - caripost_data:/data
    environment:
      S3_ENDPOINT_URL: "https://s3.n8nmikael.com.br"
      S3_ACCESS_KEY_ID: "0e1fb1161ed4f7c0a41b0fa7"
      S3_SECRET_ACCESS_KEY: "64ac389164e77eb46ef7bc9bb3791fd5a0803abdb51cc52a"
      S3_BUCKET: "caripost"
      S3_PUBLIC_BASE_URL: "https://s3.n8nmikael.com.br"
      BURN_MAX_PARALLEL: "1"
      FFMPEG_BURN_THREADS: "0"
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
EOF

echo "✅ deploy/stack.brutos.yml criado"
cat /root/caripost/deploy/stack.brutos.yml
```

---

## FASE 5 — Build da Imagem Docker

> O build instala ffmpeg, Python deps e leva ~5–10 min na primeira vez.

```bash
cd /root/caripost
docker build -t adult-meta:latest . 2>&1 | tee /tmp/docker-build.log
echo "Exit code do build: $?"
docker images | grep caripost
```

Se falhar:
```bash
tail -40 /tmp/docker-build.log
```

---

## FASE 6 — Deploy do Stack

```bash
cd /root/caripost

# 6.1 Deploy
docker stack deploy -c deploy/stack.brutos.yml caripost

# 6.2 Aguardar inicialização
sleep 35

# 6.3 Status
docker service ls
docker service ps metaporn_adult-meta
docker ps --filter name=metaporn_adult-meta
```

**Teste direto (sem Apache):**
```bash
curl -s http://127.0.0.1:8765/health
```
→ Deve retornar `{"status":"ok"}`.

Se retornar erro ou timeout:
```bash
docker service logs metaporn_adult-meta --tail 30
```
PARE e reporte. Não avance para a Fase 7 sem este teste passar.

---

## FASE 7 — Migração do Banco SQLite

> **Esta fase é MIGRAÇÃO** — os dados do servidor antigo serão importados.
> Execute com o container rodando normalmente (não precisa parar).

```bash
# 7.1 Encontrar o mountpoint do volume criado pelo deploy
VOLUME_PATH=$(docker volume inspect caripost_caripost_data --format '{{.Mountpoint}}' 2>/dev/null)
echo "Volume path: $VOLUME_PATH"

# Se o nome estiver diferente, buscar:
docker volume ls | grep caripost
```

```bash
# 7.2 Parar container para substituir banco sem corrupção
docker service scale metaporn_adult-meta=0
sleep 8

# 7.3 Fazer backup do banco vazio (criado no deploy) por segurança
cp "$VOLUME_PATH/runs.db" "$VOLUME_PATH/runs.db.empty_backup" 2>/dev/null || echo "Banco vazio não encontrado (ok)"

# 7.4 Copiar banco do servidor de origem
cp /tmp/caripost_runs_backup.db "$VOLUME_PATH/runs.db"
ls -lh "$VOLUME_PATH/runs.db"

# 7.5 Restart do container
docker service scale metaporn_adult-meta=1
sleep 20

# 7.6 Verificar que subiu e leu o banco
curl -s http://127.0.0.1:8765/health
docker service logs metaporn_adult-meta --tail 10
```

→ Deve subir sem erros e retornar `{"status":"ok"}`.

---

## FASE 8 — Configurar VirtualHost Apache

> **Pré-condição:** Fase 6 concluída e `/health` retornando OK.
> Este passo cria um NOVO arquivo `/etc/httpd/conf.d/caripost.conf`.
> **Nenhum arquivo existente será modificado.**

### 8.1 Verificar módulos (confirmação final)
```bash
httpd -M | grep -E "proxy_module|proxy_http_module|ssl_module|rewrite_module"
```
→ Todos devem aparecer. Se faltar algum, PARE.

### 8.2 Criar VirtualHost HTTP (sem SSL por enquanto)
```bash
cat > /etc/httpd/conf.d/caripost.conf << 'EOF'
<VirtualHost *:80>
    ServerName caripost.n8nmikael.com.br

    ProxyPreserveHost On
    ProxyPass        / http://127.0.0.1:8765/
    ProxyPassReverse / http://127.0.0.1:8765/
    ProxyTimeout 600

    # Upload de vídeos sem limite
    LimitRequestBody 0

    # SSE / streaming
    SetEnv proxy-sendchunks 1
    SetEnv proxy-sendcl 0
</VirtualHost>
EOF

echo "✅ VirtualHost criado"
```

### 8.3 Validar sintaxe (não recarrega ainda)
```bash
httpd -t 2>&1
```
→ Deve retornar `Syntax OK`. Se der erro, PARE e reporte — não execute o reload.

### 8.4 Reload Apache
```bash
systemctl reload httpd
echo "Reload: $?"
```

### 8.5 Teste local (sem precisar mudar DNS)
```bash
curl -s -H "Host: caripost.n8nmikael.com.br" http://127.0.0.1/health
```
→ Deve retornar `{"status":"ok"}`. Se retornar 404 ou HTML do Apache, verifique o VirtualHost.

---

## FASE 9 — Certificado SSL

> **Pré-condição:**
> 1. Fase 8 concluída e teste local passando
> 2. DNS `caripost.n8nmikael.com.br` já apontando para `177.104.176.165` (humano alterou no painel)
>
> **NÃO execute se o DNS ainda aponta para o servidor antigo (213.199.32.244).**

```bash
# 9.1 Confirmar que DNS mudou para esta máquina
DNS_IP=$(nslookup caripost.n8nmikael.com.br 2>/dev/null | grep -A1 "Name:" | grep Address | awk '{print $2}')
echo "DNS resolve para: $DNS_IP"
echo "IP desta máquina: 177.104.176.165"

if [ "$DNS_IP" = "177.104.176.165" ]; then
    echo "✅ DNS OK — pode prosseguir"
else
    echo "❌ DNS ainda não aponta para esta máquina — NÃO execute o certbot"
fi
```

```bash
# 9.2 Emitir certificado
# Nota: ssl.conf está desabilitado nesta máquina — certbot criará o bloco SSL manualmente
certbot --apache -d caripost.n8nmikael.com.br --non-interactive --agree-tos -m admin@n8nmikael.com.br

# 9.3 Verificar o que certbot criou
cat /etc/httpd/conf.d/caripost.conf
ls /etc/httpd/conf.d/ | grep caripost
ls /etc/letsencrypt/live/caripost.n8nmikael.com.br/
```

### Se certbot NÃO criou o bloco SSL automaticamente:

```bash
# Criar bloco SSL manualmente (só se necessário)
cat > /etc/httpd/conf.d/caripost-ssl.conf << 'EOF'
<VirtualHost *:443>
    ServerName caripost.n8nmikael.com.br

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/caripost.n8nmikael.com.br/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/caripost.n8nmikael.com.br/privkey.pem

    ProxyPreserveHost On
    ProxyPass        / http://127.0.0.1:8765/
    ProxyPassReverse / http://127.0.0.1:8765/
    ProxyTimeout 600
    LimitRequestBody 0

    SetEnv proxy-sendchunks 1
    SetEnv proxy-sendcl 0

    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteRule /(.*) ws://127.0.0.1:8765/$1 [P,L]
</VirtualHost>
EOF

httpd -t && systemctl reload httpd
```

---

## FASE 10 — Teste Final Completo

```bash
# 10.1 Container saudável?
docker service ps metaporn_adult-meta
docker ps --filter name=metaporn_adult-meta --format "table {{.Names}}\t{{.Status}}"

# 10.2 Porta local
curl -s http://127.0.0.1:8765/health

# 10.3 Via Apache HTTP (host header)
curl -s -H "Host: caripost.n8nmikael.com.br" http://127.0.0.1/health

# 10.4 Via HTTPS público (após DNS + certbot)
curl -sv https://caripost.n8nmikael.com.br/health 2>&1 | grep -E "SSL|HTTP|status|ok"

# 10.5 Logs sem erros?
docker service logs metaporn_adult-meta --tail 20 2>&1 | grep -Ev "GET /health|GET /ui"

# 10.6 Verificar banco migrado (deve ter registros)
VOLUME_PATH=$(docker volume inspect caripost_caripost_data --format '{{.Mountpoint}}')
docker exec $(docker ps -q --filter name=metaporn_adult-meta) \
  python3 -c "import sqlite3; c=sqlite3.connect('/data/runs.db'); print('Tabelas:', [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]); print('Runs:', c.execute('SELECT COUNT(*) FROM runs').fetchone()[0])" \
  2>/dev/null || echo "Verificar banco manualmente"
```

---

## ⚠️ Regras para o Claude que executar este deploy

1. **Execute uma fase por vez.** Reporte o resultado completo antes de avançar.
2. **PARE imediatamente** se qualquer comando retornar erro inesperado.
3. **NÃO modifique** arquivos existentes do Apache, nginx, MariaDB ou qualquer serviço ativo.
4. **NÃO altere o DNS** — isso é responsabilidade do humano no painel de domínio.
5. **NÃO faça reload do Apache** sem `httpd -t` retornar `Syntax OK` antes.
6. **NÃO execute a Fase 9 (certbot)** se o DNS ainda aponta para `213.199.32.244`.
7. **NÃO escale o serviço para 0** (Fase 7) sem avisar o humano — isso gera downtime temporário.
8. Em caso de dúvida, pergunte antes de agir.
9. Se o firewalld reclamar após instalar Docker, reporte o erro — não tente modificar regras de firewall.
