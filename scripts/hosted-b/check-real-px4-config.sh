#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="deploy/hosted-b/.env"
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
echo "PX4_GAZEBO_LAUNCH_COMMAND=${PX4_GAZEBO_LAUNCH_COMMAND:+configured}"
echo "PX4_AUTOPILOT_DIR=${PX4_AUTOPILOT_DIR:+configured}"
echo "PX4_MAKE_TARGET=${PX4_MAKE_TARGET:-}"
echo "PX4_TELEMETRY_MODE=${PX4_TELEMETRY_MODE:-}"
if [[ -n "${PX4_ULOG_ROOT:-}" ]]; then
  echo "PX4_ULOG_ROOT=${PX4_ULOG_ROOT}"
else
  echo "PX4_ULOG_ROOT=(not set)"
fi

status=0
if [[ "${REAL_SIMULATOR_COMMAND:-}" != *"px4_gazebo_runner.py"* ]]; then
  echo "ERROR: REAL_SIMULATOR_COMMAND must point to px4_gazebo_runner.py"
  status=1
fi
if [[ "${PX4_GAZEBO_DRY_RUN:-true}" == "false" ]]; then
  if [[ -z "${PX4_GAZEBO_LAUNCH_COMMAND:-}" ]]; then
    echo "ERROR: PX4_GAZEBO_LAUNCH_COMMAND is required when PX4_GAZEBO_DRY_RUN=false"
    status=1
  fi
  if [[ -z "${PX4_AUTOPILOT_DIR:-}" ]]; then
    echo "ERROR: PX4_AUTOPILOT_DIR is required when PX4_GAZEBO_DRY_RUN=false"
    status=1
  fi
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker detected; worker env snapshot:"
  docker compose --env-file "${ENV_FILE}" -f deploy/hosted-b/docker-compose.yml exec -T worker \
    sh -lc 'env | grep -E "PX4_GAZEBO_DRY_RUN|REAL_SIMULATOR_COMMAND|PX4_GAZEBO_LAUNCH_COMMAND|PX4_AUTOPILOT_DIR|PX4_MAKE_TARGET|PX4_TELEMETRY_MODE|PX4_ULOG_ROOT"' || true
fi

exit "${status}"
