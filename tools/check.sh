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

# ---- Repository-owned source and documentation ----
if command -v python3 >/dev/null 2>&1; then
  section "Repository: encoding, JSON, and Markdown links"
  run_or_skip "repository hygiene" python3 tools/check-repository.py
else
  missing "repository hygiene" "install Python 3"
fi

# ---- Backend ----
if [[ -x services/backend/.venv/bin/python ]]; then
  section "Backend: ruff"
  run_or_skip "ruff" services/backend/.venv/bin/ruff check services/backend
  section "Backend: mypy"
  run_or_skip "mypy" services/backend/.venv/bin/mypy services/backend/app
  section "Backend: pytest"
  run_or_skip "pytest" services/backend/.venv/bin/pytest services/backend
else
  missing "backend" "run 'python3 -m venv services/backend/.venv && services/backend/.venv/bin/pip install -e services/backend[dev]'"
fi

# ---- Worker ----
if [[ -x services/worker/.venv/bin/ruff ]]; then
  section "Worker: ruff"
  run_or_skip "ruff" services/worker/.venv/bin/ruff check services/worker
else
  missing "worker ruff" "run 'python3 -m venv services/worker/.venv && services/worker/.venv/bin/pip install -e services/backend && services/worker/.venv/bin/pip install -e services/worker[dev]'"
fi

# ---- Frontend ----
if [[ -d apps/frontend/node_modules ]]; then
  section "Frontend: typecheck"
  run_or_skip "typecheck" npm --prefix apps/frontend run -s typecheck
  section "Frontend: lint"
  run_or_skip "lint" npm --prefix apps/frontend run -s lint
  section "Frontend: build"
  run_or_skip "build" npm --prefix apps/frontend run -s build
  section "Frontend: test"
  run_or_skip "test" npm --prefix apps/frontend run -s test
else
  missing "frontend" "run 'cd apps/frontend && npm install'"
fi

exit "$status"
