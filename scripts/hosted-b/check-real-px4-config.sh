#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/hosted-b/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/hosted-b/docker-compose.yml}"
VERBOSE="${VERBOSE:-0}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE (copy deploy/hosted-b/.env.example to deploy/hosted-b/.env and edit values)."
  exit 1
fi

eval "$(python3 - "$ENV_FILE" <<'PY'
import re
import shlex
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key_re = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
for raw in env_path.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    key = key.strip()
    if not key_re.match(key):
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    print(f"export {key}={shlex.quote(value)}")
PY
)"

status=0
req(){ [[ -n "${!1:-}" ]] || { echo "ERROR: $1 is required"; status=1; }; }

strict_mode="${HOSTED_REAL_CLI_REQUIRES_PX4:-true}"
echo "HOSTED_REAL_CLI_REQUIRES_PX4=${strict_mode}"

echo "REAL_SIMULATOR_COMMAND=${REAL_SIMULATOR_COMMAND:-}"
echo "PX4_GAZEBO_DRY_RUN=${PX4_GAZEBO_DRY_RUN:-}"
echo "PX4_GAZEBO_HEADLESS=${PX4_GAZEBO_HEADLESS:-}"
if [[ "$VERBOSE" == "1" ]]; then
  echo "PX4_GAZEBO_LAUNCH_COMMAND=${PX4_GAZEBO_LAUNCH_COMMAND:-}"
else
  echo "PX4_GAZEBO_LAUNCH_COMMAND=${PX4_GAZEBO_LAUNCH_COMMAND:+configured}"
fi
echo "PX4_AUTOPILOT_HOST_DIR=${PX4_AUTOPILOT_HOST_DIR:-}"
echo "PX4_AUTOPILOT_DIR=${PX4_AUTOPILOT_DIR:-}"

[[ "${REAL_SIMULATOR_COMMAND:-}" == *"px4_gazebo_runner.py"* ]] || { echo "ERROR: REAL_SIMULATOR_COMMAND must reference px4_gazebo_runner.py"; status=1; }

truthy(){ case "${1,,}" in 1|true|yes|on) return 0;; *) return 1;; esac; }

if truthy "$strict_mode"; then
  [[ "${PX4_GAZEBO_DRY_RUN:-false}" == "false" ]] || { echo "ERROR: PX4_GAZEBO_DRY_RUN must be false in strict mode"; status=1; }
  [[ "${PX4_GAZEBO_HEADLESS:-false}" == "false" ]] || { echo "ERROR: PX4_GAZEBO_HEADLESS must be false in strict mode"; status=1; }
  req PX4_GAZEBO_LAUNCH_COMMAND
  req PX4_AUTOPILOT_HOST_DIR
  req PX4_AUTOPILOT_DIR
  req VNC_PASSWORD
  if [[ -z "${VITE_GAZEBO_VIEWER_URL:-}" ]]; then
    echo "WARN: VITE_GAZEBO_VIEWER_URL is not configured; web iframe embedding will be unavailable."
  fi
  [[ -d "${PX4_AUTOPILOT_HOST_DIR:-/missing}" ]] || { echo "ERROR: PX4_AUTOPILOT_HOST_DIR does not exist: ${PX4_AUTOPILOT_HOST_DIR:-}"; status=1; }
else
  echo "INFO: strict mode disabled; dry-run/dev checks are relaxed."
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker available: yes"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null || status=1
  echo "Active worker services:"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps worker worker-real-px4-vnc || true
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q worker-real-px4-vnc | grep -q .; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T worker-real-px4-vnc sh -lc 'env | grep -E "DISPLAY|NOVNC_PORT|VNC_PORT|PX4_GAZEBO|PX4_AUTOPILOT_DIR|HOSTED_REAL_CLI_REQUIRES_PX4"' || true
    curl -fsS "http://localhost:${NOVNC_PORT:-6080}/vnc.html" >/dev/null || echo "WARN: noVNC endpoint not reachable yet"
  fi
  curl -fsS "http://localhost:8080/gazebo/vnc.html" >/dev/null || echo "WARN: same-origin /gazebo/vnc.html not reachable yet"
else
  echo "Docker available: no"
fi

exit "$status"
