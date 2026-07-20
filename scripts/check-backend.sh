#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PYTHON="${BACKEND_PYTHON:-backend/.venv/bin/python}"
if [[ ! -x "$BACKEND_PYTHON" ]]; then
  echo "Backend virtualenv not found at $BACKEND_PYTHON." >&2
  echo "Run: python3 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend[dev]'" >&2
  exit 1
fi

"$BACKEND_PYTHON" scripts/check-repository.py
"$BACKEND_PYTHON" -m ruff check --config backend/pyproject.toml backend scripts/simulators
"$BACKEND_PYTHON" -m compileall -q scripts/simulators
"$BACKEND_PYTHON" -m mypy --config-file backend/pyproject.toml backend/app
"$BACKEND_PYTHON" -m pytest backend
