#!/usr/bin/env bash
# Run the DroneDream worker entrypoint locally.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV="worker/.venv"
if [[ ! -d "$VENV" ]]; then
  echo "[dev-worker] creating virtualenv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install -e worker
fi

cd worker
exec "../$VENV/bin/python" -m app.main
