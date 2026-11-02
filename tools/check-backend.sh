#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PYTHON="${BACKEND_PYTHON:-server/api/.venv/bin/python}"
if [[ ! -x "$BACKEND_PYTHON" ]]; then
  echo "Backend virtualenv not found at $BACKEND_PYTHON." >&2
  echo "Run: python3 -m venv server/api/.venv && server/api/.venv/bin/pip install -e 'server/api[dev]'" >&2
  exit 1
fi

"$BACKEND_PYTHON" tools/check-repository.py
"$BACKEND_PYTHON" -m ruff check --config server/api/pyproject.toml server/api tools/simulators
"$BACKEND_PYTHON" -m compileall -q tools/simulators
"$BACKEND_PYTHON" -m mypy --config-file server/api/pyproject.toml server/api/app
"$BACKEND_PYTHON" -m pytest server/api
