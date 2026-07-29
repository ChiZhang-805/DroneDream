#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

python3 ./scripts/check-repository.py
./scripts/check-backend.sh
./scripts/check-worker.sh
./scripts/check-runtime.sh
./scripts/check-frontend.sh

echo
echo "Portable service checks passed."
echo "Run the separate Windows Desktop Rust/NSIS gate documented in docs/10-development.md."
