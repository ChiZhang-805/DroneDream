#!/usr/bin/env bash
set -uo pipefail

export DISPLAY="${DISPLAY:-:99}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_X11_NO_MITSHM="${QT_X11_NO_MITSHM:-1}"

WINDOW_TITLE="${PX4_GAZEBO_GUI_WINDOW_TITLE:-Gazebo Sim}"
WINDOW_GEOMETRY="${PX4_GAZEBO_GUI_WINDOW_GEOMETRY:-0,0,0,1600,855}"
WINDOW_DELAY_SECONDS="${PX4_GAZEBO_GUI_WINDOW_DELAY_SECONDS:-3}"
WINDOW_RETRY_SECONDS="${PX4_GAZEBO_GUI_WINDOW_RETRY_SECONDS:-90}"
WINDOW_ENFORCE_SECONDS="${PX4_GAZEBO_GUI_WINDOW_ENFORCE_SECONDS:-30}"

echo "[gazebo_gui_client] DISPLAY=${DISPLAY}"
echo "[gazebo_gui_client] WINDOW_TITLE=${WINDOW_TITLE}"
echo "[gazebo_gui_client] WINDOW_GEOMETRY=${WINDOW_GEOMETRY}"
echo "[gazebo_gui_client] WINDOW_DELAY_SECONDS=${WINDOW_DELAY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_RETRY_SECONDS=${WINDOW_RETRY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_ENFORCE_SECONDS=${WINDOW_ENFORCE_SECONDS}"

gz sim -g &
GUI_PID=$!

sleep "${WINDOW_DELAY_SECONDS}"

if ! command -v wmctrl >/dev/null 2>&1; then
  echo "[gazebo_gui_client] wmctrl not found; skipping resize"
  wait "${GUI_PID}"
  exit $?
fi

deadline=$((SECONDS + WINDOW_RETRY_SECONDS))
resized=0

while (( SECONDS <= deadline )); do
  echo "[gazebo_gui_client] current windows:"
  wmctrl -l || true

  if wmctrl -l | grep -F "${WINDOW_TITLE}" >/dev/null 2>&1; then
    echo "[gazebo_gui_client] found ${WINDOW_TITLE}; enforcing resize"
    enforce_deadline=$((SECONDS + WINDOW_ENFORCE_SECONDS))

    while (( SECONDS <= enforce_deadline )); do
      wmctrl -r "${WINDOW_TITLE}" -b remove,maximized_vert,maximized_horz || true
      wmctrl -r "${WINDOW_TITLE}" -e "${WINDOW_GEOMETRY}" || true
      sleep 1
    done

    echo "[gazebo_gui_client] resized ${WINDOW_TITLE} to ${WINDOW_GEOMETRY}"
    resized=1
    break
  fi

  sleep 1
done

if [[ "${resized}" != "1" ]]; then
  echo "[gazebo_gui_client] WARNING: did not find window title ${WINDOW_TITLE}"
fi

wait "${GUI_PID}"
