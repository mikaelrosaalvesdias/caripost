#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl is required" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is required" >&2
  exit 1
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8765}"
API_KEY="${API_KEY:-}"

AUTH_ARGS=()
if [[ -n "$API_KEY" ]]; then
  AUTH_ARGS=(-H "X-API-Key: $API_KEY")
fi

usage() {
  cat <<'EOF'
Uso:
  scripts/storage_admin.sh list [prefix]
  scripts/storage_admin.sh validate <object_key> [--delete]
  scripts/storage_admin.sh delete <object_key>
  scripts/storage_admin.sh scan-invalid [prefix] [--delete]

Exemplos:
  scripts/storage_admin.sh list uploads
  scripts/storage_admin.sh validate 'uploads/2026/03/17/video.mp4'
  scripts/storage_admin.sh validate 'uploads/2026/03/17/video.mp4' --delete
  scripts/storage_admin.sh scan-invalid uploads --delete

Env opcionais:
  BASE_URL=http://127.0.0.1:8765
  API_KEY=...
EOF
}

api_get() {
  local path="$1"
  curl -fsS "${AUTH_ARGS[@]}" "$BASE_URL$path"
}

api_post_json() {
  local path="$1"
  local payload="$2"
  curl -fsS "${AUTH_ARGS[@]}" -H 'content-type: application/json' -X POST "$BASE_URL$path" -d "$payload"
}

api_post_json_with_status() {
  local path="$1"
  local payload="$2"
  local body_file
  body_file="$(mktemp)"
  local status
  status="$(curl -sS "${AUTH_ARGS[@]}" -H 'content-type: application/json' -X POST "$BASE_URL$path" -d "$payload" -o "$body_file" -w '%{http_code}')"
  printf '%s\n' "$status"
  cat "$body_file"
  rm -f "$body_file"
}

api_delete() {
  local path="$1"
  curl -fsS "${AUTH_ARGS[@]}" -X DELETE "$BASE_URL$path"
}

is_probably_video_key() {
  local lower
  lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    *.mp4|*.mov|*.m4v|*.mkv|*.webm|*.avi|*.wmv|*.mpg|*.mpeg)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_and_print() {
  local object_key="$1"
  local delete_flag="$2"
  local raw status body
  raw="$(api_post_json_with_status "/uploads/validate" "$(jq -n --arg object_key "$object_key" --argjson delete_if_invalid "$delete_flag" '{object_key:$object_key, delete_if_invalid:$delete_if_invalid}')")"
  status="$(printf '%s\n' "$raw" | head -n1)"
  body="$(printf '%s\n' "$raw" | tail -n +2)"

  if [[ "$status" == "200" || "$status" == "422" || "$status" == "404" ]]; then
    printf '%s\n' "$body" | jq .
    return 0
  fi

  if printf '%s' "$body" | jq . >/dev/null 2>&1; then
    printf '%s\n' "$body" | jq .
  else
    printf '%s\n' "$body"
  fi
  return 1
}

cmd="${1:-}"
case "$cmd" in
  list)
    prefix="${2:-uploads}"
    api_get "/uploads/list?prefix=$(python3 - <<'PY' "$prefix"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
)" | jq '{ok, count: (.items | length), items: [.items[] | {object_key, storage_kind, storage_path, size_mb, last_modified}]}'
    ;;
  validate)
    object_key="${2:-}"
    if [[ -z "$object_key" ]]; then
      usage
      exit 1
    fi
    delete_flag=false
    if [[ "${3:-}" == "--delete" ]]; then
      delete_flag=true
    fi
    validate_and_print "$object_key" "$delete_flag"
    ;;
  delete)
    object_key="${2:-}"
    if [[ -z "$object_key" ]]; then
      usage
      exit 1
    fi
    encoded_key="$(python3 - <<'PY' "$object_key"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
)"
    api_delete "/uploads/object?object_key=${encoded_key}" | jq
    ;;
  scan-invalid)
    prefix="uploads"
    delete_flag=false
    valid_count=0
    invalid_count=0
    missing_count=0
    skipped_count=0
    error_count=0
    if [[ $# -ge 2 && "${2:-}" != "--delete" ]]; then
      prefix="${2:-uploads}"
    fi
    if [[ "${2:-}" == "--delete" || "${3:-}" == "--delete" ]]; then
      delete_flag=true
    fi
    mapfile -t keys < <(api_get "/uploads/list?prefix=$(python3 - <<'PY' "$prefix"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
    )" | jq -r '.items[].object_key')
    for key in "${keys[@]}"; do
      [[ -z "$key" ]] && continue
      if ! is_probably_video_key "$key"; then
        echo "== $key"
        echo '{"ok":true,"skipped":true,"detail":"Ignorado: arquivo não parece ser vídeo."}' | jq .
        skipped_count=$((skipped_count + 1))
        continue
      fi
      echo "== $key"
      if output="$(validate_and_print "$key" "$delete_flag" 2>&1)"; then
        printf '%s\n' "$output"
        if printf '%s\n' "$output" | jq -e '.valid == true' >/dev/null 2>&1; then
          valid_count=$((valid_count + 1))
        elif printf '%s\n' "$output" | jq -e '.error == "object_not_found"' >/dev/null 2>&1; then
          missing_count=$((missing_count + 1))
        else
          invalid_count=$((invalid_count + 1))
        fi
      else
        printf '%s\n' "$output"
        error_count=$((error_count + 1))
      fi
    done
    echo "--"
    jq -n \
      --arg prefix "$prefix" \
      --argjson valid "$valid_count" \
      --argjson invalid "$invalid_count" \
      --argjson missing "$missing_count" \
      --argjson skipped "$skipped_count" \
      --argjson errors "$error_count" \
      '{ok:true, prefix:$prefix, summary:{valid:$valid, invalid:$invalid, missing:$missing, skipped:$skipped, errors:$errors}}'
    ;;
  *)
    usage
    exit 1
    ;;
esac
