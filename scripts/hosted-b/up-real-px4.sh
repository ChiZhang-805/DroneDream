#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../deploy/hosted-b"
docker compose --env-file .env stop worker || true
docker compose --env-file .env --profile real-px4 up -d --build postgres backend web worker-real-px4
