#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

SERVICE_NAME="${SERVICE_NAME:-metaporn_adult-meta}"
MEDIA_HOST_ROOT="${ADULT_META_MEDIA_HOST_ROOT:-/var/www2/adult-meta-media}"
MEDIA_TARGET_ROOT="${ADULT_META_MEDIA_ROOT:-/media}"
DEPLOY_MIN_FREE_MB="${DEPLOY_MIN_FREE_MB:-6144}"
DEPLOY_AUTO_PRUNE_BELOW_MB="${DEPLOY_AUTO_PRUNE_BELOW_MB:-12288}"
DEPLOY_HEALTH_TIMEOUT_SEC="${DEPLOY_HEALTH_TIMEOUT_SEC:-120}"
TMP_RETENTION_HOURS="${TMP_RETENTION_HOURS:-24}"

mkdir -p "$MEDIA_HOST_ROOT"

free_root_mb() {
  df -Pm / | awk 'NR==2 {print $4}'
}

current_container_id() {
  docker ps --filter "name=${SERVICE_NAME}" --format '{{.ID}}' | head -n1
}

cleanup_media_tmp() {
  local mode="${1:-stale}"
  local tmp_root="${MEDIA_HOST_ROOT}/_tmp"
  mkdir -p "$tmp_root"
  if [[ "$mode" == "all" ]]; then
    find "$tmp_root" -mindepth 2 -maxdepth 2 -print -exec rm -rf {} + 2>/dev/null || true
  else
    find "$tmp_root" -mindepth 2 -maxdepth 2 -mmin "+$((TMP_RETENTION_HOURS * 60))" -print -exec rm -rf {} + 2>/dev/null || true
  fi
}

cleanup_docker_space() {
  echo "[deploy] Cleaning old Docker artifacts..."
  docker container prune -f >/dev/null 2>&1 || true
  docker image prune -af >/dev/null 2>&1 || true
  docker builder prune -af >/dev/null 2>&1 || true
}

ensure_free_space() {
  local before_mb after_mb
  before_mb="$(free_root_mb)"
  if (( before_mb < DEPLOY_AUTO_PRUNE_BELOW_MB )); then
    echo "[deploy] Root free space low (${before_mb}MB). Running cleanup first..."
    cleanup_media_tmp
    cleanup_docker_space
  fi
  after_mb="$(free_root_mb)"
  if (( after_mb < DEPLOY_MIN_FREE_MB )); then
    echo "[deploy] Abort: only ${after_mb}MB free on / after cleanup. Need at least ${DEPLOY_MIN_FREE_MB}MB."
    exit 1
  fi
}

count_busy_jobs() {
  local cid
  cid="$(current_container_id)"
  if [[ -z "$cid" ]]; then
    echo 0
    return 0
  fi
  docker exec -i "$cid" python3 - <<'PY'
from app.db import get_conn
try:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM async_jobs WHERE status IN ('pending', 'running')").fetchone()
        print(int((row[0] if row else 0) or 0))
except Exception:
    print(0)
PY
}

ensure_service_mount_and_env() {
  local mount_target="$1"
  local mount_source="$2"
  local env_name="ADULT_META_MEDIA_ROOT"
  local env_value="$3"
  local -a args=()

  if ! docker service inspect "$SERVICE_NAME" --format '{{range .Spec.TaskTemplate.ContainerSpec.Mounts}}{{println .Target "|" .Source "|" .Type}}{{end}}' | grep -Fq "${mount_target} |"; then
    args+=(--mount-add "type=bind,src=${mount_source},dst=${mount_target}")
  fi

  local current_env
  current_env="$(docker service inspect "$SERVICE_NAME" --format '{{range .Spec.TaskTemplate.ContainerSpec.Env}}{{println .}}{{end}}' | grep "^${env_name}=" || true)"
  if [[ "$current_env" != "${env_name}=${env_value}" ]]; then
    if [[ -n "$current_env" ]]; then
      args+=(--env-rm "$env_name")
    fi
    args+=(--env-add "${env_name}=${env_value}")
  fi

  if (( ${#args[@]} > 0 )); then
    echo "[deploy] Ensuring service mount/env for local media..."
    docker service update "${args[@]}" "$SERVICE_NAME" >/dev/null
    sleep 2
  fi
}

ensure_service_mount_and_env "$MEDIA_TARGET_ROOT" "$MEDIA_HOST_ROOT" "$MEDIA_TARGET_ROOT"

if [[ "${ALLOW_BUSY_DEPLOY:-0}" != "1" ]]; then
  busy_jobs="$(count_busy_jobs)"
  if [[ "$busy_jobs" =~ ^[0-9]+$ ]] && (( busy_jobs > 0 )); then
    echo "[deploy] Abort: ${busy_jobs} async job(s) ainda estão pendentes/rodando. Use ALLOW_BUSY_DEPLOY=1 para forçar."
    exit 1
  fi
fi

if [[ "${ALLOW_BUSY_DEPLOY:-0}" == "1" ]]; then
  cleanup_media_tmp stale
else
  cleanup_media_tmp all
fi
ensure_free_space

echo "[deploy] Building image..."
build_args=(--build-arg "CACHE_BUST=$(date +%s)" -t adult-meta:latest .)
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  build_args=(--no-cache "${build_args[@]}")
fi
docker build "${build_args[@]}"
ensure_free_space

echo "[deploy] Forcing service update..."
docker service update --force --no-resolve-image --image adult-meta:latest "$SERVICE_NAME"

echo "[deploy] Done. Verifying..."
deadline=$((SECONDS + DEPLOY_HEALTH_TIMEOUT_SEC))
until curl -sf http://127.0.0.1:8765/health >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "[deploy] Healthcheck timeout after ${DEPLOY_HEALTH_TIMEOUT_SEC}s."
    exit 1
  fi
  sleep 2
done
echo " ✓ healthy"

cleanup_docker_space
echo "[deploy] Root free space after deploy: $(free_root_mb)MB"
