# 🔍 Diagnóstico Pré-Deploy — MetaPorn (adult-meta)

> Execute todos os blocos abaixo **antes de qualquer deploy**. Não modifique nada na máquina. Apenas leia, inspecione e reporte. O objetivo é mapear se este ambiente suporta o projeto sem conflitar com o que já está rodando.

---

## 1. Identidade da Máquina

```bash
uname -a
hostname
cat /etc/os-release
uptime
date
```

---

## 2. Recursos de Hardware

```bash
# CPU
nproc
lscpu | grep -E "Model name|CPU\(s\)|Thread|Core"

# RAM
free -h

# Disco (verificar espaço livre — imagens Docker + volume SQLite + vídeos MinIO local se houver)
df -h

# Carga atual
top -bn1 | head -20
```

---

## 3. Docker — Instalação e Versão

```bash
docker version
docker info | grep -E "Server Version|Storage Driver|Cgroup|Swarm|Operating System|Total Memory|CPUs"
docker compose version 2>/dev/null || docker-compose version 2>/dev/null || echo "docker compose não encontrado"
```

---

## 4. Docker Swarm — Status

```bash
# Verificar se Swarm está ativo nesta máquina
docker info | grep -A5 "Swarm"

# Listar nós do swarm (se for manager)
docker node ls 2>/dev/null || echo "Não é manager do Swarm ou Swarm não ativo"

# Listar stacks existentes
docker stack ls 2>/dev/null || echo "Sem stacks"

# Listar todos os serviços rodando
docker service ls 2>/dev/null || echo "Sem serviços"
```

**O que esperamos:** Swarm ativo com pelo menos 1 nó manager. Se não estiver ativo, precisamos inicializar com `docker swarm init` antes do deploy.

---

## 5. Redes Docker Existentes

```bash
# Listar todas as redes
docker network ls

# Verificar se a rede 'n8nmikaelnet' existe (CRÍTICO)
docker network inspect n8nmikaelnet 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    n = data[0]
    print(f'REDE ENCONTRADA: {n[\"Name\"]}')
    print(f'  Driver: {n[\"Driver\"]}')
    print(f'  Scope: {n[\"Scope\"]}')
    print(f'  Subnet: {n[\"IPAM\"][\"Config\"]}')
    conts = n.get(\"Containers\", {})
    print(f'  Containers conectados: {len(conts)}')
    for cid, c in list(conts.items())[:10]:
        print(f'    - {c[\"Name\"]} ({c[\"IPv4Address\"]})')
except Exception as e:
    print(f'ERRO: {e}')
" 2>/dev/null || echo "⚠️  REDE n8nmikaelnet NÃO EXISTE — precisa ser criada ou o stack.yml precisa ser adaptado"
```

**O que esperamos:** Rede `n8nmikaelnet` com driver `overlay` e scope `swarm`. Se não existir, o deploy vai falhar.

---

## 6. Traefik — Existe e Está Configurado?

```bash
# Verificar se Traefik está rodando como serviço
docker service ls | grep -i traefik || echo "⚠️  Traefik não encontrado como serviço Docker"

# Verificar se há container Traefik
docker ps | grep -i traefik || echo "⚠️  Nenhum container Traefik rodando"

# Inspecionar labels de roteamento do Traefik
docker service inspect $(docker service ls -q --filter name=traefik) 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    s = data[0]
    spec = s.get('Spec', {})
    labels = spec.get('Labels', {})
    print('Labels Traefik:')
    for k, v in labels.items():
        if 'traefik' in k.lower():
            print(f'  {k} = {v}')
    # Verificar entrypoints disponíveis
    env = spec.get('TaskTemplate', {}).get('ContainerSpec', {}).get('Env', [])
    for e in env:
        if 'ENTRYPOINT' in e.upper() or 'ACME' in e.upper() or 'CERT' in e.upper():
            print(f'  ENV: {e}')
except Exception as e:
    print(f'Erro ao inspecionar: {e}')
" 2>/dev/null

# Verificar config do Traefik
docker config ls 2>/dev/null
docker secret ls 2>/dev/null
```

**O que verificar:**
- Traefik está rodando na rede `n8nmikaelnet`?
- O entrypoint `websecure` (porta 443) existe?
- O certresolver `letsencrypt` está configurado?
- Traefik tem acesso ao socket Docker?

---

## 7. Portas em Uso

```bash
# Verificar se porta 8765 está livre (porta interna do container)
ss -tlnp | grep 8765 || echo "Porta 8765 livre (interno)"

# Verificar portas 80 e 443 (Traefik)
ss -tlnp | grep -E ':80 |:443 '

# Todas as portas TCP em uso
ss -tlnp | grep LISTEN
```

**O que esperamos:** Porta 8765 livre no host (só será usada internamente pelo container). Portas 80/443 ocupadas pelo Traefik (normal).

---

## 8. Volumes Docker Existentes

```bash
# Listar volumes
docker volume ls

# Verificar se já existe o volume do projeto
docker volume inspect adult_meta_data 2>/dev/null && echo "✅ Volume já existe (dados preservados)" || echo "Volume adult_meta_data não existe (será criado no deploy)"
```

---

## 9. Imagens Docker Existentes

```bash
# Verificar se a imagem já foi buildada
docker images | grep adult-meta || echo "Imagem adult-meta:latest não encontrada — precisa fazer build"

# Espaço total de imagens
docker system df
```

---

## 10. Conectividade — MinIO / S3

```bash
# Testar acesso ao endpoint MinIO externo
curl -s -o /dev/null -w "HTTP %{http_code} | tempo %{time_total}s" \
  "https://s3.n8nmikael.com.br" \
  --max-time 10 || echo "⚠️  Sem acesso ao MinIO s3.n8nmikael.com.br"

# DNS funcionando?
nslookup s3.n8nmikael.com.br 2>/dev/null || host s3.n8nmikael.com.br 2>/dev/null || echo "DNS não resolveu s3.n8nmikael.com.br"
```

---

## 11. Conectividade — xAI API

```bash
# Testar conectividade com api.x.ai (necessário para análise de vídeo)
curl -s -o /dev/null -w "HTTP %{http_code} | tempo %{time_total}s" \
  "https://api.x.ai" \
  --max-time 10 || echo "⚠️  Sem acesso a api.x.ai"
```

---

## 12. DNS — Domínio do Projeto

```bash
# O domínio metaporn.n8nmikael.com.br aponta para este servidor?
curl -s -o /dev/null -w "HTTP %{http_code}" \
  "https://metaporn.n8nmikael.com.br/health" \
  --max-time 10 2>/dev/null || echo "Domínio não acessível ainda (normal antes do deploy)"

# Resolver o IP do domínio
nslookup metaporn.n8nmikael.com.br 2>/dev/null || host metaporn.n8nmikael.com.br 2>/dev/null

# IP público desta máquina
curl -s --max-time 5 https://ifconfig.me || curl -s --max-time 5 https://api.ipify.org
```

**O que verificar:** O IP resolvido para `metaporn.n8nmikael.com.br` é o IP desta máquina? Se não for, o Traefik não vai receber as requisições e o TLS não vai funcionar.

---

## 13. Ferramentas Necessárias no Host

```bash
# Git
git --version 2>/dev/null || echo "git não instalado"

# Python (para scripts auxiliares)
python3 --version 2>/dev/null || echo "python3 não instalado"

# curl / wget
curl --version 2>/dev/null | head -1
wget --version 2>/dev/null | head -1

# Espaço para o build (precisa ~2GB livres)
df -h / | tail -1
```

---

## 14. Conflitos de Nome — Stacks e Serviços

```bash
# Verificar se já existe stack 'metaporn'
docker stack ls | grep metaporn || echo "Stack 'metaporn' não existe (deploy limpo)"

# Verificar se já existe serviço com esse nome
docker service ls | grep -E "adult-meta|metaporn" || echo "Nenhum serviço adult-meta/metaporn encontrado"

# Verificar routers Traefik que podem conflitar
docker service ls --format "{{.Name}}" | while read svc; do
  docker service inspect "$svc" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for s in data:
        labels = s.get('Spec',{}).get('Labels',{})
        for k,v in labels.items():
            if 'metaporn' in v.lower() or 'adult' in v.lower():
                print(f'  CONFLITO POTENCIAL em $svc: {k}={v}')
except: pass
  " 2>/dev/null
done
echo "Verificação de conflitos concluída"
```

---

## 15. Recursos do Sistema em Tempo Real

```bash
# Uso atual de CPU e memória pelos containers Docker
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null | head -30
```

---

## 16. Logs do Traefik (verificar saúde)

```bash
# Últimas linhas dos logs do Traefik para ver se há erros
docker service logs $(docker service ls -q --filter name=traefik) --tail 20 2>/dev/null || \
docker logs $(docker ps -q --filter name=traefik) --tail 20 2>/dev/null || \
echo "Não foi possível acessar logs do Traefik"
```

---

## 17. Resumo de Decisão

Após executar todos os blocos acima, responda:

| Checklist | Status |
|---|---|
| Docker Swarm ativo e com manager? | ✅ / ❌ |
| Rede `n8nmikaelnet` existe (overlay, swarm)? | ✅ / ❌ |
| Traefik rodando com entrypoint `websecure`? | ✅ / ❌ |
| Certresolver `letsencrypt` configurado no Traefik? | ✅ / ❌ |
| Porta 8765 livre no host? | ✅ / ❌ |
| MinIO `s3.n8nmikael.com.br` acessível? | ✅ / ❌ |
| DNS `metaporn.n8nmikael.com.br` → IP desta máquina? | ✅ / ❌ |
| Volume `adult_meta_data` já existe? | ✅ / ❌ (novo) |
| Imagem `adult-meta:latest` já existe? | ✅ / ❌ (precisa build) |
| Nenhum conflito de nome de serviço/router? | ✅ / ❌ |
| Disco livre suficiente (>2GB)? | ✅ / ❌ |

**Se todos ✅:** pode prosseguir com o deploy.
**Se algum ❌:** reportar aqui o que falta antes de qualquer ação.

---

## ⚠️ Instruções ao Claude que executar este diagnóstico

1. **NÃO modifique nenhum arquivo, container, serviço ou configuração.**
2. **NÃO execute nenhum `docker stack deploy`, `docker build`, `docker service update` ou qualquer comando destrutivo.**
3. **NÃO crie volumes, redes ou secrets.**
4. Execute cada bloco acima **exatamente como está**, capture a saída e monte o relatório com a tabela de decisão preenchida.
5. Se algum comando falhar por falta de permissão, reporte isso como item crítico.
6. Ao final, sintetize em linguagem natural: **"Este ambiente está PRONTO / NÃO ESTÁ PRONTO para o deploy do MetaPorn"**, listando os blockers encontrados.
