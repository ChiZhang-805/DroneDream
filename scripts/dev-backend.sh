#!/usr/bin/env bash
# Run the FastAPI backend locally with auto-reload.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Phase 8: auto-load repo-root .env so APP_SECRET_KEY / DATABASE_URL / etc.
# are visible to the backend. The worker script does the same so both
# processes see identical values.
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

VENV="backend/.venv"
if [[ ! -d "$VENV" ]]; then
  echo "[dev-backend] creating virtualenv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install -e 'backend[dev]'
fi

# Phase 8: pin the SQLite path to an absolute file under the repo root so
# the backend and worker (see scripts/dev-worker.sh) agree on the same DB
# regardless of whoever was launched with whichever cwd.
if [[ -z "${DATABASE_URL:-}" ]]; then
  export DATABASE_URL="sqlite:///$ROOT_DIR/drone_dream.db"
  echo "[dev-backend] DATABASE_URL not set; pinning to $DATABASE_URL"
fi

exec "$VENV/bin/uvicorn" app.main:app \
  --reload \
  --app-dir backend \
  --host "${BACKEND_HOST:-127.0.0.1}" \
  --port "${BACKEND_PORT:-8000}"
