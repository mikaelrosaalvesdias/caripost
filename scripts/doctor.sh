#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-metaporn_adult-meta}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8765}"
MEDIA_HOST_ROOT="${CARIPOST_MEDIA_HOST_ROOT:-/var/www2/adult-meta-media}"

say() {
  printf '\n== %s ==\n' "$1"
}

container_id() {
  docker ps --filter "name=${SERVICE_NAME}" --format '{{.ID}}' | head -n1
}

say "Timestamp"
date

say "Disk"
df -h / /var/www /var/www2 2>/dev/null || df -h /

say "Docker system df"
docker system df || true

say "Service tasks"
docker service ps "$SERVICE_NAME" --no-trunc | head -20 || true

say "Running containers"
docker ps -a --filter "name=${SERVICE_NAME}" --format '{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Size}}\t{{.Names}}' || true

say "HTTP health"
curl -fsS "$BASE_URL/health" || echo "health failed"
echo

say "Burn queue"
curl -fsS "$BASE_URL/api/burn-subtitles/queue" || echo "queue failed"
echo

cid="$(container_id)"
if [[ -n "$cid" ]]; then
  say "Async jobs in DB"
  docker exec -i "$cid" python3 - <<'PY'
from app.db import get_conn
try:
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) FROM async_jobs GROUP BY status ORDER BY status").fetchall()
        print([(r[0], r[1]) for r in rows])
except Exception as exc:
    print(f"db check failed: {exc}")
PY

  say "Media usage inside container"
  docker exec "$cid" sh -lc "du -xh -d 2 /media 2>/dev/null | sort -h | tail -30" || true
fi

if [[ -d "$MEDIA_HOST_ROOT" ]]; then
  say "Media usage on host"
  du -xh -d 2 "$MEDIA_HOST_ROOT" 2>/dev/null | sort -h | tail -30 || true
fi

say "Recent service errors"
if command -v rg >/dev/null 2>&1; then
  docker service logs "$SERVICE_NAME" --since 2h 2>&1 | \
    rg -n "Traceback|ERROR:|OperationalError|database is locked|500 Internal|No space left|unhealthy|Conversion failed|Invalid NAL unit|Exception in ASGI" || \
    echo "no matching errors in last 2h"
else
  docker service logs "$SERVICE_NAME" --since 2h 2>&1 | \
    grep -En "Traceback|ERROR:|OperationalError|database is locked|500 Internal|No space left|unhealthy|Conversion failed|Invalid NAL unit|Exception in ASGI" || \
    echo "no matching errors in last 2h"
fi
