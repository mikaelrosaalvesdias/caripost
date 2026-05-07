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
VIDEO_FILE="${VIDEO_FILE:-}"
OPENAI_TOKEN="${OPENAI_TOKEN:-}"

AUTH_ARGS=()
if [[ -n "$API_KEY" ]]; then
  AUTH_ARGS=(-H "X-API-Key: $API_KEY")
fi

api_get() {
  local path="$1"
  curl -sS "${AUTH_ARGS[@]}" "$BASE_URL$path"
}

api_post_json() {
  local path="$1"
  local payload="$2"
  curl -sS "${AUTH_ARGS[@]}" -H 'content-type: application/json' -X POST "$BASE_URL$path" -d "$payload"
}

echo "== Health"
health_json="$(api_get /health)"
echo "$health_json" | jq
if [[ "$(echo "$health_json" | jq -r '.ok // false')" != "true" ]]; then
  echo "health check failed" >&2
  exit 1
fi

if [[ -n "$OPENAI_TOKEN" ]]; then
  echo "== Saving OpenAI token"
  api_post_json /settings/tokens "$(jq -n --arg provider openai --arg api_key "$OPENAI_TOKEN" '{provider:$provider, api_key:$api_key}')" | jq
fi

object_key=""
public_url=""
transcript_text=""

if [[ -n "$VIDEO_FILE" ]]; then
  echo "== Presign"
  presign_payload="$(jq -n --arg filename "$(basename "$VIDEO_FILE")" --arg ct "video/mp4" '{filename:$filename, content_type:$ct}')"
  presign_json="$(api_post_json /uploads/presign "$presign_payload")"
  echo "$presign_json" | jq

  upload_url="$(echo "$presign_json" | jq -r '.upload_url // empty')"
  object_key="$(echo "$presign_json" | jq -r '.object_key // empty')"
  public_url="$(echo "$presign_json" | jq -r '.public_url // empty')"
  signed_ct="$(echo "$presign_json" | jq -r '.required_headers["Content-Type"] // empty')"

  if [[ -z "$upload_url" || -z "$object_key" ]]; then
    echo "presign failed (missing upload_url/object_key)" >&2
    exit 1
  fi

  echo "== PUT upload"
  if [[ -n "$signed_ct" ]]; then
    curl -sS -X PUT "$upload_url" -H "Content-Type: $signed_ct" --upload-file "$VIDEO_FILE" >/dev/null
  else
    curl -sS -X PUT "$upload_url" --upload-file "$VIDEO_FILE" >/dev/null
  fi
  echo "upload ok"

  echo "== Transcribe"
  transcribe_json="$(api_post_json /transcribe "$(jq -n --arg key "$object_key" '{video_object_key:$key, language:"auto"}')")"
  echo "$transcribe_json" | jq
  transcript_text="$(echo "$transcribe_json" | jq -r '.transcript.text // empty')"
fi

echo "== Analyze"
analyze_payload="$(jq -n \
  --arg object_key "$object_key" \
  --arg public_url "$public_url" \
  --arg transcript_text "$transcript_text" \
  '{
    video_object_key: (if $object_key == "" then null else $object_key end),
    video_url: (if $public_url == "" then null else $public_url end),
    video_metadata: {probe: {duration_seconds: 0, width: 0, height: 0, fps: 0}},
    transcript: (if $transcript_text == "" then null else {provider:"openai_whisper", lang:"auto", text:$transcript_text, segments:[]} end),
    limit: 20
  }')"

analyze_json="$(api_post_json /analyze "$analyze_payload")"
echo "$analyze_json" | jq '{run_id, created_at, prompt_present: (.grok.markdown_prompt_ptbr_keep_original != null), transcript_present: .inputs.transcript_present, source_keys: (.sources | keys)}'

echo "smoke test completed"
