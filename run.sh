#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8765}" --log-level info
