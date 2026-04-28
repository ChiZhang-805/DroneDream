#!/usr/bin/env bash
set -euo pipefail

DISPLAY="${DISPLAY:-:99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
GEOMETRY="${GEOMETRY:-1600x900x24}"
LOG_DIR="/workspace/logs"

mkdir -p "${LOG_DIR}"
XVFB_LOG="${LOG_DIR}/xvfb.log"
WM_LOG="${LOG_DIR}/window-manager.log"
X11VNC_LOG="${LOG_DIR}/x11vnc.log"
NOVNC_LOG="${LOG_DIR}/novnc.log"

require_cmd() {
  local cmd="$1"
  local hint_name="$2"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing ${hint_name}." >&2
    echo "Please install: apt-get install -y xvfb x11vnc fluxbox novnc websockify" >&2
    exit 1
  fi
}

require_cmd Xvfb "Xvfb"
require_cmd x11vnc "x11vnc"
require_cmd websockify "websockify"
require_cmd fluxbox "fluxbox"

if [[ -z "${VNC_PASSWORD:-}" ]]; then
  echo "VNC_PASSWORD is required to start noVNC." >&2
  exit 1
fi

PASS_FILE="$(mktemp)"
cleanup() {
  rm -f "${PASS_FILE}"
  for pid in "${NOVNC_PID:-}" "${X11VNC_PID:-}" "${WM_PID:-}" "${XVFB_PID:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT INT TERM

x11vnc -storepasswd "${VNC_PASSWORD}" "${PASS_FILE}" >/dev/null 2>&1

Xvfb "${DISPLAY}" -screen 0 "${GEOMETRY}" >"${XVFB_LOG}" 2>&1 &
XVFB_PID=$!

DISPLAY="${DISPLAY}" fluxbox >"${WM_LOG}" 2>&1 &
WM_PID=$!

x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -rfbauth "${PASS_FILE}" -shared -forever >"${X11VNC_LOG}" 2>&1 &
X11VNC_PID=$!

websockify --web=/usr/share/novnc/ 0.0.0.0:"${NOVNC_PORT}" 127.0.0.1:"${VNC_PORT}" >"${NOVNC_LOG}" 2>&1 &
NOVNC_PID=$!

sleep 1

for pid in "${XVFB_PID}" "${WM_PID}" "${X11VNC_PID}" "${NOVNC_PID}"; do
  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    echo "Failed to start one or more noVNC services. Check logs under ${LOG_DIR}." >&2
    exit 1
  fi
done

export PX4_GAZEBO_VNC_DESKTOP_GEOMETRY="${PX4_GAZEBO_VNC_DESKTOP_GEOMETRY:-${GEOMETRY}}"

echo "DISPLAY=${DISPLAY}"
echo "VNC_PORT=${VNC_PORT}"
echo "NOVNC_PORT=${NOVNC_PORT}"
echo "GEOMETRY=${GEOMETRY}"
echo "PX4_GAZEBO_VNC_DESKTOP_GEOMETRY=${PX4_GAZEBO_VNC_DESKTOP_GEOMETRY}"
echo "noVNC listening on 0.0.0.0:${NOVNC_PORT}"
echo "Open Runpod ${NOVNC_PORT} HTTP proxy URL."

wait "${NOVNC_PID}"
