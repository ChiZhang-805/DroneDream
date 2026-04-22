#!/usr/bin/env bash
# Aggregate quality gate: run available linters, type-checkers, tests, and builds.
# Individual checks are skipped if their toolchain isn't installed, so this
# script is safe to run in minimal environments.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

status=0
section() { echo; echo "==> $*"; }

run_or_skip() {
  local label="$1"
  shift
  if "$@"; then
    echo "[check] $label: OK"
  else
    echo "[check] $label: FAILED" >&2
    status=1
  fi
}

# ---- Backend ----
if [[ -x backend/.venv/bin/python ]]; then
  section "Backend: ruff"
  run_or_skip "ruff" backend/.venv/bin/ruff check backend
  section "Backend: mypy"
  run_or_skip "mypy" backend/.venv/bin/mypy backend/app
  section "Backend: pytest"
  run_or_skip "pytest" backend/.venv/bin/pytest backend
else
  echo "[check] backend venv not found — skipping backend checks (run scripts/dev-backend.sh once to bootstrap)"
fi

# ---- Worker ----
if [[ -x worker/.venv/bin/ruff ]]; then
  section "Worker: ruff"
  run_or_skip "ruff" worker/.venv/bin/ruff check worker
else
  echo "[check] worker ruff not installed — skipping worker lint (run 'pip install -e worker[dev]')"
fi

# ---- Frontend ----
if [[ -d frontend/node_modules ]]; then
  section "Frontend: typecheck"
  (cd frontend && run_or_skip "typecheck" npm run -s typecheck)
  section "Frontend: lint"
  (cd frontend && run_or_skip "lint" npm run -s lint)
  section "Frontend: build"
  (cd frontend && run_or_skip "build" npm run -s build)
else
  echo "[check] frontend node_modules not found — run 'cd frontend && npm install' first"
fi

exit "$status"
