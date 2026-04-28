#!/usr/bin/env bash
set -uo pipefail

export DISPLAY="${DISPLAY:-:99}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_X11_NO_MITSHM="${QT_X11_NO_MITSHM:-1}"

WINDOW_TITLE="${PX4_GAZEBO_GUI_WINDOW_TITLE:-Gazebo Sim}"
WINDOW_GEOMETRY="${PX4_GAZEBO_GUI_WINDOW_GEOMETRY:-center}"
WINDOW_WIDTH="${PX4_GAZEBO_GUI_WINDOW_WIDTH:-1280}"
WINDOW_HEIGHT="${PX4_GAZEBO_GUI_WINDOW_HEIGHT:-720}"
WINDOW_DELAY_SECONDS="${PX4_GAZEBO_GUI_WINDOW_DELAY_SECONDS:-3}"
WINDOW_RETRY_SECONDS="${PX4_GAZEBO_GUI_WINDOW_RETRY_SECONDS:-90}"
WINDOW_ENFORCE_SECONDS="${PX4_GAZEBO_GUI_WINDOW_ENFORCE_SECONDS:-30}"

parse_geometry_resolution() {
  local geometry="$1"
  if [[ "${geometry}" =~ ^([0-9]+)x([0-9]+)(x[0-9]+)?$ ]]; then
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

detect_display_size() {
  local size=""
  if command -v xdpyinfo >/dev/null 2>&1; then
    size="$(xdpyinfo -display "${DISPLAY}" 2>/dev/null | awk '/dimensions:/ {print $2; exit}')"
  fi

  if [[ -z "${size}" ]] && command -v xrandr >/dev/null 2>&1; then
    size="$(xrandr --display "${DISPLAY}" 2>/dev/null | awk '/\*/ {print $1; exit}')"
  fi

  if [[ -z "${size}" ]]; then
    size="${PX4_GAZEBO_VNC_DESKTOP_GEOMETRY:-${GEOMETRY:-}}"
  fi

  if ! parse_geometry_resolution "${size}" >/dev/null 2>&1; then
    size="1600x900"
  fi

  parse_geometry_resolution "${size}"
}

build_centered_wmctrl_geometry() {
  local display_size
  display_size="$(detect_display_size)"
  local desktop_width desktop_height
  read -r desktop_width desktop_height <<<"${display_size}"

  local x=$(( (desktop_width - WINDOW_WIDTH) / 2 ))
  local y=$(( (desktop_height - WINDOW_HEIGHT) / 2 ))

  if (( x < 0 )); then x=0; fi
  if (( y < 0 )); then y=0; fi

  echo "0,${x},${y},${WINDOW_WIDTH},${WINDOW_HEIGHT}"
}

resolve_window_geometry() {
  local requested="$1"
  local normalized="${requested//[[:space:]]/}"

  if [[ -z "${normalized}" || "${normalized}" == "center" ]]; then
    build_centered_wmctrl_geometry
    return 0
  fi

  if [[ "${normalized}" =~ ^[0-9]+,[0-9]+,[0-9]+,[0-9]+,[0-9]+$ ]]; then
    echo "${normalized}"
    return 0
  fi

  echo "[gazebo_gui_client] WARNING: invalid PX4_GAZEBO_GUI_WINDOW_GEOMETRY=${requested}; fallback to center" >&2
  build_centered_wmctrl_geometry
}

RESOLVED_WINDOW_GEOMETRY="$(resolve_window_geometry "${WINDOW_GEOMETRY}")"

echo "[gazebo_gui_client] DISPLAY=${DISPLAY}"
echo "[gazebo_gui_client] WINDOW_TITLE=${WINDOW_TITLE}"
echo "[gazebo_gui_client] WINDOW_GEOMETRY=${WINDOW_GEOMETRY}"
echo "[gazebo_gui_client] WINDOW_WIDTH=${WINDOW_WIDTH}"
echo "[gazebo_gui_client] WINDOW_HEIGHT=${WINDOW_HEIGHT}"
echo "[gazebo_gui_client] RESOLVED_WINDOW_GEOMETRY=${RESOLVED_WINDOW_GEOMETRY}"
echo "[gazebo_gui_client] WINDOW_DELAY_SECONDS=${WINDOW_DELAY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_RETRY_SECONDS=${WINDOW_RETRY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_ENFORCE_SECONDS=${WINDOW_ENFORCE_SECONDS}"

gz sim -g &
GUI_PID=$!

sleep "${WINDOW_DELAY_SECONDS}"

if ! command -v wmctrl >/dev/null 2>&1; then
  echo "[gazebo_gui_client] WARNING: wmctrl not found; skipping resize"
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
      wmctrl -r "${WINDOW_TITLE}" -e "${RESOLVED_WINDOW_GEOMETRY}" || true
      sleep 1
    done

    echo "[gazebo_gui_client] resized ${WINDOW_TITLE} to ${RESOLVED_WINDOW_GEOMETRY}"
    resized=1
    break
  fi

  sleep 1
done

if [[ "${resized}" != "1" ]]; then
  echo "[gazebo_gui_client] WARNING: did not find window title ${WINDOW_TITLE}"
fi

wait "${GUI_PID}"
