#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"$ROOT_DIR/scripts/check-backend.sh"
"$ROOT_DIR/scripts/check-worker.sh"
"$ROOT_DIR/scripts/check-frontend.sh"
