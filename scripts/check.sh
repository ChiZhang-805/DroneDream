#!/usr/bin/env bash
# Aggregate quality gate: run linters, type-checkers, tests, and builds.
#
# Modes:
#   (default)  — local developer mode. Individual checks are skipped if their
#                toolchain isn't installed, so this script is safe to run in
#                minimal environments.
#   CHECK_STRICT=1 (or --strict) — CI mode. Any missing toolchain is a hard
#                failure, so CI never silently passes on a partially-installed
#                environment.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

strict="${CHECK_STRICT:-0}"
for arg in "$@"; do
  case "$arg" in
    --strict) strict=1 ;;
  esac
done

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

missing() {
  local label="$1"
  local advice="$2"
  if [[ "$strict" == "1" ]]; then
    echo "[check] $label: MISSING (strict mode) — $advice" >&2
    status=1
  else
    echo "[check] $label: skipped — $advice"
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
  missing "backend" "run 'python3 -m venv backend/.venv && backend/.venv/bin/pip install -e backend[dev]'"
fi

# ---- Worker ----
if [[ -x worker/.venv/bin/ruff ]]; then
  section "Worker: ruff"
  run_or_skip "ruff" worker/.venv/bin/ruff check worker
else
  missing "worker ruff" "run 'python3 -m venv worker/.venv && worker/.venv/bin/pip install -e backend && worker/.venv/bin/pip install -e worker[dev]'"
fi

# ---- Frontend ----
if [[ -d frontend/node_modules ]]; then
  section "Frontend: typecheck"
  (cd frontend && run_or_skip "typecheck" npm run -s typecheck)
  section "Frontend: lint"
  (cd frontend && run_or_skip "lint" npm run -s lint)
  section "Frontend: build"
  (cd frontend && run_or_skip "build" npm run -s build)
  section "Frontend: test"
  (cd frontend && run_or_skip "test" npm run -s test)
else
  missing "frontend" "run 'cd frontend && npm install'"
fi

exit "$status"
