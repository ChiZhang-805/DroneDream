#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

WORKER_PYTHON="${WORKER_PYTHON:-server/worker/.venv/bin/python}"
if [[ ! -x "$WORKER_PYTHON" ]]; then
  echo "Worker virtualenv not found at $WORKER_PYTHON." >&2
  echo "Run: python3 -m venv server/worker/.venv && server/worker/.venv/bin/pip install -e server/api && server/worker/.venv/bin/pip install -e 'server/worker[dev]'" >&2
  exit 1
fi

"$WORKER_PYTHON" -m ruff check server/worker
