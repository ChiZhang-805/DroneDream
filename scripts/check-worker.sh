#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

WORKER_PYTHON="${WORKER_PYTHON:-worker/.venv/bin/python}"
if ! "$WORKER_PYTHON" -c "import sys; raise SystemExit(0)" >/dev/null 2>&1; then
  echo "Worker virtualenv not found at $WORKER_PYTHON." >&2
  echo "Run: python3 -m venv worker/.venv && worker/.venv/bin/pip install -e backend && worker/.venv/bin/pip install -e 'worker[dev]'" >&2
  exit 1
fi

"$WORKER_PYTHON" -m ruff check worker
"$WORKER_PYTHON" -m mypy --config-file worker/pyproject.toml worker/drone_dream_worker
"$WORKER_PYTHON" -m pytest worker
