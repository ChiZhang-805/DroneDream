#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PYTHON="${BACKEND_PYTHON:-services/backend/.venv/bin/python}"
if [[ ! -x "$BACKEND_PYTHON" ]]; then
  echo "Backend virtualenv not found at $BACKEND_PYTHON." >&2
  echo "Run: python3 -m venv services/backend/.venv && services/backend/.venv/bin/pip install -e 'services/backend[dev]'" >&2
  exit 1
fi

"$BACKEND_PYTHON" tools/check-repository.py
"$BACKEND_PYTHON" -m ruff check --config services/backend/pyproject.toml services/backend tools/simulators
"$BACKEND_PYTHON" -m compileall -q tools/simulators
"$BACKEND_PYTHON" -m mypy --config-file services/backend/pyproject.toml services/backend/app
"$BACKEND_PYTHON" -m pytest services/backend
