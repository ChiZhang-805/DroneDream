#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
scripts/hosted-b/check-real-px4-config.sh
cd deploy/hosted-b
docker compose --env-file .env stop worker || true
docker compose --env-file .env --profile real-px4 up -d --build postgres backend web worker-real-px4-vnc
echo "Website: http://localhost:8080"
echo "noVNC: http://localhost:8080/gazebo/vnc.html"
echo "Active workers:"
docker compose --env-file .env --profile real-px4 ps worker worker-real-px4-vnc
