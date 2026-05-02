#!/usr/bin/env bash
set -euo pipefail

: "${VNC_PASSWORD:?VNC_PASSWORD is required}"
export DISPLAY="${DISPLAY:-:99}"
export NOVNC_PORT="${NOVNC_PORT:-6080}"

scripts/run-gazebo-vnc.sh &
VNC_PID=$!

cleanup() {
  kill -TERM "$VNC_PID" 2>/dev/null || true
  [[ -n "${WORKER_PID:-}" ]] && kill -TERM "$WORKER_PID" 2>/dev/null || true
  wait || true
}
trap cleanup SIGINT SIGTERM EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${NOVNC_PORT}/vnc.html" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

drone-dream-worker &
WORKER_PID=$!
wait "$WORKER_PID"
