#!/usr/bin/env bash
# Run the FastAPI backend locally with auto-reload.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV="backend/.venv"
if [[ ! -d "$VENV" ]]; then
  echo "[dev-backend] creating virtualenv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install -e 'backend[dev]'
fi

exec "$VENV/bin/uvicorn" app.main:app \
  --reload \
  --app-dir backend \
  --host "${BACKEND_HOST:-127.0.0.1}" \
  --port "${BACKEND_PORT:-8000}"
