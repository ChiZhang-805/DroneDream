#!/usr/bin/env bash
# Run the DroneDream worker entrypoint locally.
#
# Phase 3: the worker re-uses the backend's ORM models and orchestration code,
# so both packages must be installed editable into the worker venv.
#
# Phase 8: the backend and worker must point at the SAME SQLite database when
# run locally. Both read DATABASE_URL from the environment, and both default
# to ``sqlite:///./drone_dream.db`` when it is unset. Because that default is
# resolved relative to the *current* working directory, we must launch the
# worker from the repo root (not the worker/ subdirectory) so its relative
# path matches the backend's. If DATABASE_URL is unset, we additionally pin
# it to an absolute path under the repo root so nothing depends on cwd.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Phase 8: auto-load repo-root .env so APP_SECRET_KEY / DATABASE_URL / etc.
# are visible to the worker. The backend script does the same so both
# processes see identical values.
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

VENV="worker/.venv"
if [[ ! -d "$VENV" ]]; then
  echo "[dev-worker] creating virtualenv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install -e backend
  "$VENV/bin/pip" install -e worker
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  export DATABASE_URL="sqlite:///$ROOT_DIR/drone_dream.db"
  echo "[dev-worker] DATABASE_URL not set; pinning to $DATABASE_URL"
fi

exec "$VENV/bin/python" -m drone_dream_worker.main
