#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="deploy/hosted-b/.env"
COMPOSE_FILE="deploy/hosted-b/docker-compose.yml"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  key="$(echo "$key" | xargs)"
  [[ -z "$key" ]] && continue
  export "$key=$value"
done < "${ENV_FILE}"

echo "PX4_GAZEBO_DRY_RUN=${PX4_GAZEBO_DRY_RUN:-}"
echo "REAL_SIMULATOR_COMMAND=${REAL_SIMULATOR_COMMAND:-}"
echo "PX4_GAZEBO_LAUNCH_COMMAND=${PX4_GAZEBO_LAUNCH_COMMAND:+configured}${PX4_GAZEBO_LAUNCH_COMMAND:-}"
echo "PX4_AUTOPILOT_HOST_DIR=${PX4_AUTOPILOT_HOST_DIR:-}"
echo "PX4_AUTOPILOT_DIR=${PX4_AUTOPILOT_DIR:-}"
echo "PX4_MAKE_TARGET=${PX4_MAKE_TARGET:-}"
echo "PX4_TELEMETRY_MODE=${PX4_TELEMETRY_MODE:-}"
echo "PX4_ULOG_ROOT=${PX4_ULOG_ROOT:-}"

status=0
if [[ "${REAL_SIMULATOR_COMMAND:-}" != *"px4_gazebo_runner.py"* ]]; then
  echo "ERROR: REAL_SIMULATOR_COMMAND must point to px4_gazebo_runner.py"
  status=1
fi

if [[ "${PX4_GAZEBO_DRY_RUN:-true}" == "false" ]]; then
  [[ -n "${PX4_GAZEBO_LAUNCH_COMMAND:-}" ]] || { echo "ERROR: PX4_GAZEBO_LAUNCH_COMMAND is required"; status=1; }
  [[ -n "${PX4_AUTOPILOT_DIR:-}" ]] || { echo "ERROR: PX4_AUTOPILOT_DIR is required"; status=1; }
  [[ -n "${PX4_AUTOPILOT_HOST_DIR:-}" ]] || { echo "ERROR: PX4_AUTOPILOT_HOST_DIR is required for compose real-px4 profile"; status=1; }
fi
if [[ -n "${PX4_AUTOPILOT_HOST_DIR:-}" && ! -d "${PX4_AUTOPILOT_HOST_DIR}" ]]; then
  echo "ERROR: PX4_AUTOPILOT_HOST_DIR does not exist on host: ${PX4_AUTOPILOT_HOST_DIR}"
  status=1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker detected; container env snapshots (when running):"
  for svc in worker worker-real-px4; do
    cid=$(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps -q "$svc" 2>/dev/null || true)
    if [[ -n "$cid" ]]; then
      echo "--- $svc ---"
      docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T "$svc" sh -lc 'env | grep -E "PX4_GAZEBO_DRY_RUN|REAL_SIMULATOR_COMMAND|PX4_GAZEBO_LAUNCH_COMMAND|PX4_AUTOPILOT_HOST_DIR|PX4_AUTOPILOT_DIR|PX4_MAKE_TARGET|PX4_TELEMETRY_MODE|PX4_ULOG_ROOT"' || true
    else
      echo "--- $svc not running ---"
    fi
  done
fi

exit "$status"
