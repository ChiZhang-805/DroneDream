#!/usr/bin/env bash
set -euo pipefail

: "${VNC_PASSWORD:?VNC_PASSWORD is required}"

export PATH="/opt/venv/bin:${PATH}"
export DISPLAY="${DISPLAY:-:99}"
export NOVNC_PORT="${NOVNC_PORT:-6080}"
export VNC_PORT="${VNC_PORT:-5900}"
export QT_X11_NO_MITSHM="${QT_X11_NO_MITSHM:-1}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"

if [[ -n "${PX4_AUTOPILOT_DIR:-}" && -d "${PX4_AUTOPILOT_DIR}" ]]; then
  git config --global --add safe.directory '*' || true

  if [[ -f "${PX4_AUTOPILOT_DIR}/Tools/setup/requirements.txt" ]]; then
    if [[ ! -f /opt/venv/.px4_requirements_installed ]]; then
      echo "Installing PX4 Python requirements from ${PX4_AUTOPILOT_DIR}/Tools/setup/requirements.txt"
      python -m pip install --no-cache-dir -r "${PX4_AUTOPILOT_DIR}/Tools/setup/requirements.txt"
      python -m pip install --no-cache-dir pyros-genmsg catkin_pkg rospkg
      touch /opt/venv/.px4_requirements_installed
    fi

    python - <<'PY'
import genmsg
import kconfiglib
print("PX4 Python deps OK: genmsg=", genmsg.__file__)
PY
  fi
fi

/app/scripts/run-gazebo-vnc.sh &
VNC_PID=$!

cleanup() {
  kill -TERM "$VNC_PID" 2>/dev/null || true
  [[ -n "${WORKER_PID:-}" ]] && kill -TERM "$WORKER_PID" 2>/dev/null || true
  [[ -n "${MAXIMIZER_PID:-}" ]] && kill -TERM "$MAXIMIZER_PID" 2>/dev/null || true
  wait || true
}
trap cleanup SIGINT SIGTERM EXIT

for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${NOVNC_PORT}/vnc.html" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

/app/scripts/hosted-b/maximize-gazebo-window.sh &
MAXIMIZER_PID=$!

drone-dream-worker &
WORKER_PID=$!
wait "$WORKER_PID"
