#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

RUNTIME_PYTHON="${RUNTIME_PYTHON:-runtime/.venv/bin/python}"
if ! "$RUNTIME_PYTHON" -c "import sys; raise SystemExit(0)" >/dev/null 2>&1; then
  echo "Runtime virtualenv not found at $RUNTIME_PYTHON." >&2
  echo "Run: python3 -m venv runtime/.venv && runtime/.venv/bin/pip install -r runtime/locks/release-tools-requirements.lock ruff==0.15.21 pytest==9.1.1" >&2
  exit 1
fi

"$RUNTIME_PYTHON" -m ruff check runtime/tools runtime/tests runtime/scripts scripts/simulators
"$RUNTIME_PYTHON" -m ruff check runtime/tools runtime/scripts scripts/simulators --select S
"$RUNTIME_PYTHON" -m ruff format --check \
  runtime/tools runtime/tests runtime/scripts scripts/simulators
"$RUNTIME_PYTHON" -m compileall -q \
  runtime/tools runtime/tests runtime/scripts scripts/simulators
"$RUNTIME_PYTHON" runtime/tools/runtime_manifest.py validate-config \
  --pins runtime/pins.env \
  --python-lock runtime/locks/python-requirements.lock
"$RUNTIME_PYTHON" -m pytest runtime/tests -q

mapfile -d '' shell_scripts < <(find runtime scripts -type f -name '*.sh' -print0)
if (( ${#shell_scripts[@]} == 0 )); then
  echo "No Runtime shell scripts were found." >&2
  exit 1
fi
for script in "${shell_scripts[@]}"; do
  bash -n "$script"
done
