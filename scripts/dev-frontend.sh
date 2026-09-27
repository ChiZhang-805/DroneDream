#!/usr/bin/env bash
# Run the Vite dev server for the frontend.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/frontend"

if [[ ! -d node_modules ]]; then
  echo "[dev-frontend] installing npm dependencies"
  npm install
fi

exec npm run dev
