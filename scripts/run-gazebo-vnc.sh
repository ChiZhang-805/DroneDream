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
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd Xvfb
require_cmd x11vnc
require_cmd websockify
require_cmd fluxbox
require_cmd xdpyinfo
require_cmd curl

if [[ -z "${VNC_PASSWORD:-}" ]]; then
  echo "VNC_PASSWORD is required to start noVNC." >&2
  exit 1
fi

PASS_FILE="$(mktemp)"

cleanup() {
  rm -f "${PASS_FILE}" || true
  for pid in "${NOVNC_PID:-}" "${X11VNC_PID:-}" "${WM_PID:-}" "${XVFB_PID:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT INT TERM

x11vnc -storepasswd "${VNC_PASSWORD}" "${PASS_FILE}" >/dev/null 2>&1

DISPLAY_NUM="${DISPLAY#:}"
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix

echo "Starting Xvfb on DISPLAY=${DISPLAY} geometry=${GEOMETRY}"
Xvfb "${DISPLAY}" -screen 0 "${GEOMETRY}" -nolisten tcp >"${XVFB_LOG}" 2>&1 &
XVFB_PID=$!

for _ in $(seq 1 150); do
  if DISPLAY="${DISPLAY}" xdpyinfo >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "${XVFB_PID}" >/dev/null 2>&1; then
    echo "Xvfb exited before display was ready." >&2
    cat "${XVFB_LOG}" >&2 || true
    exit 1
  fi
  sleep 0.1
done

if ! DISPLAY="${DISPLAY}" xdpyinfo >/dev/null 2>&1; then
  echo "Xvfb did not become ready." >&2
  cat "${XVFB_LOG}" >&2 || true
  exit 1
fi

DISPLAY="${DISPLAY}" fluxbox >"${WM_LOG}" 2>&1 &
WM_PID=$!

sleep 0.5

x11vnc \
  -display "${DISPLAY}" \
  -rfbport "${VNC_PORT}" \
  -rfbauth "${PASS_FILE}" \
  -shared \
  -forever \
  -noxdamage \
  >"${X11VNC_LOG}" 2>&1 &
X11VNC_PID=$!

for _ in $(seq 1 150); do
  if bash -lc ":</dev/tcp/127.0.0.1/${VNC_PORT}" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "${X11VNC_PID}" >/dev/null 2>&1; then
    echo "x11vnc exited before VNC port was ready." >&2
    cat "${X11VNC_LOG}" >&2 || true
    exit 1
  fi
  sleep 0.1
done

websockify \
  --web=/usr/share/novnc/ \
  "0.0.0.0:${NOVNC_PORT}" \
  "127.0.0.1:${VNC_PORT}" \
  >"${NOVNC_LOG}" 2>&1 &
NOVNC_PID=$!

for _ in $(seq 1 150); do
  if curl -fsS "http://127.0.0.1:${NOVNC_PORT}/vnc.html" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "${NOVNC_PID}" >/dev/null 2>&1; then
    echo "websockify/noVNC exited before HTTP endpoint was ready." >&2
    cat "${NOVNC_LOG}" >&2 || true
    exit 1
  fi
  sleep 0.1
done

for pid in "${XVFB_PID}" "${WM_PID}" "${X11VNC_PID}" "${NOVNC_PID}"; do
  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    echo "Failed to start one or more noVNC services. Check logs under ${LOG_DIR}." >&2
    for f in "${XVFB_LOG}" "${WM_LOG}" "${X11VNC_LOG}" "${NOVNC_LOG}"; do
      echo "===== ${f} =====" >&2
      tail -80 "${f}" >&2 || true
    done
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
echo "Open http://localhost:8080/gazebo/vnc.html"

wait "${NOVNC_PID}"
