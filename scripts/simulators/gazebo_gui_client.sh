#!/usr/bin/env bash
set -uo pipefail

export DISPLAY="${DISPLAY:-:99}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_X11_NO_MITSHM="${QT_X11_NO_MITSHM:-1}"

GAZEBO_GUI_COMMAND="${PX4_GAZEBO_RAW_GUI_COMMAND:-gz sim -g}"
WINDOW_TITLE="${PX4_GAZEBO_GUI_WINDOW_TITLE:-Gazebo Sim}"
WINDOW_MODE="${PX4_GAZEBO_GUI_WINDOW_MODE:-fill}"
WINDOW_GEOMETRY="${PX4_GAZEBO_GUI_WINDOW_GEOMETRY:-fill}"
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
  local desktop_width="$1"
  local desktop_height="$2"

  local x=$(( (desktop_width - WINDOW_WIDTH) / 2 ))
  local y=$(( (desktop_height - WINDOW_HEIGHT) / 2 ))

  if (( x < 0 )); then x=0; fi
  if (( y < 0 )); then y=0; fi

  echo "0,${x},${y},${WINDOW_WIDTH},${WINDOW_HEIGHT}"
}

validate_window_mode() {
  local mode="$1"
  case "${mode}" in
    fill|center|geometry)
      echo "${mode}"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_window_mode_and_geometry() {
  local requested_mode="${WINDOW_MODE,,}"
  local requested_geometry="${WINDOW_GEOMETRY//[[:space:]]/}"
  local desktop_width="$1"
  local desktop_height="$2"

  if [[ "${requested_geometry}" == "fill" ]]; then
    requested_mode="fill"
  elif [[ "${requested_geometry}" == "center" ]]; then
    requested_mode="center"
  elif [[ "${requested_geometry}" =~ ^[0-9]+,[0-9]+,[0-9]+,[0-9]+,[0-9]+$ ]]; then
    requested_mode="geometry"
  elif [[ -n "${requested_geometry}" ]]; then
    echo "[gazebo_gui_client] WARNING: invalid PX4_GAZEBO_GUI_WINDOW_GEOMETRY=${WINDOW_GEOMETRY}; fallback to fill" >&2
    requested_mode="fill"
    requested_geometry="fill"
  fi

  if ! validate_window_mode "${requested_mode}" >/dev/null 2>&1; then
    echo "[gazebo_gui_client] WARNING: invalid PX4_GAZEBO_GUI_WINDOW_MODE=${WINDOW_MODE}; fallback to fill" >&2
    requested_mode="fill"
  fi

  local resolved_geometry=""
  case "${requested_mode}" in
    fill)
      resolved_geometry="0,0,0,${desktop_width},${desktop_height}"
      ;;
    center)
      resolved_geometry="$(build_centered_wmctrl_geometry "${desktop_width}" "${desktop_height}")"
      ;;
    geometry)
      if [[ "${requested_geometry}" =~ ^[0-9]+,[0-9]+,[0-9]+,[0-9]+,[0-9]+$ ]]; then
        resolved_geometry="${requested_geometry}"
      else
        echo "[gazebo_gui_client] WARNING: geometry mode requested but no valid wmctrl geometry provided; fallback to fill" >&2
        requested_mode="fill"
        resolved_geometry="0,0,0,${desktop_width},${desktop_height}"
      fi
      ;;
  esac

  echo "${requested_mode}|${resolved_geometry}"
}

DESKTOP_SIZE="$(detect_display_size)"
read -r DESKTOP_WIDTH DESKTOP_HEIGHT <<<"${DESKTOP_SIZE}"
RESOLUTION_RESULT="$(resolve_window_mode_and_geometry "${DESKTOP_WIDTH}" "${DESKTOP_HEIGHT}")"
RESOLVED_WINDOW_MODE="${RESOLUTION_RESULT%%|*}"
RESOLVED_WINDOW_GEOMETRY="${RESOLUTION_RESULT#*|}"
WMCTRL_EXISTS="false"
if command -v wmctrl >/dev/null 2>&1; then
  WMCTRL_EXISTS="true"
fi

echo "[gazebo_gui_client] DISPLAY=${DISPLAY}"
echo "[gazebo_gui_client] GAZEBO_GUI_COMMAND=${GAZEBO_GUI_COMMAND}"
echo "[gazebo_gui_client] WINDOW_TITLE=${WINDOW_TITLE}"
echo "[gazebo_gui_client] WINDOW_MODE=${WINDOW_MODE}"
echo "[gazebo_gui_client] WINDOW_GEOMETRY=${WINDOW_GEOMETRY}"
echo "[gazebo_gui_client] WINDOW_WIDTH=${WINDOW_WIDTH}"
echo "[gazebo_gui_client] WINDOW_HEIGHT=${WINDOW_HEIGHT}"
echo "[gazebo_gui_client] RESOLVED_WINDOW_MODE=${RESOLVED_WINDOW_MODE}"
echo "[gazebo_gui_client] RESOLVED_WINDOW_GEOMETRY=${RESOLVED_WINDOW_GEOMETRY}"
echo "[gazebo_gui_client] detected desktop size=${DESKTOP_WIDTH}x${DESKTOP_HEIGHT}"
echo "[gazebo_gui_client] wmctrl_exists=${WMCTRL_EXISTS}"
echo "[gazebo_gui_client] WINDOW_DELAY_SECONDS=${WINDOW_DELAY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_RETRY_SECONDS=${WINDOW_RETRY_SECONDS}"
echo "[gazebo_gui_client] WINDOW_ENFORCE_SECONDS=${WINDOW_ENFORCE_SECONDS}"

bash -lc "${GAZEBO_GUI_COMMAND}" &
GUI_PID=$!

sleep "${WINDOW_DELAY_SECONDS}"

if [[ "${WMCTRL_EXISTS}" != "true" ]]; then
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
    echo "[gazebo_gui_client] found ${WINDOW_TITLE}; enforcing ${RESOLVED_WINDOW_MODE} mode"
    enforce_deadline=$((SECONDS + WINDOW_ENFORCE_SECONDS))

    while (( SECONDS <= enforce_deadline )); do
      case "${RESOLVED_WINDOW_MODE}" in
        fill)
          wmctrl -r "${WINDOW_TITLE}" -e "${RESOLVED_WINDOW_GEOMETRY}" || true
          wmctrl -r "${WINDOW_TITLE}" -b add,maximized_vert,maximized_horz || true
          ;;
        center|geometry)
          wmctrl -r "${WINDOW_TITLE}" -b remove,maximized_vert,maximized_horz || true
          wmctrl -r "${WINDOW_TITLE}" -e "${RESOLVED_WINDOW_GEOMETRY}" || true
          ;;
      esac
      sleep 1
    done

    echo "[gazebo_gui_client] resized ${WINDOW_TITLE} with mode=${RESOLVED_WINDOW_MODE} geometry=${RESOLVED_WINDOW_GEOMETRY}"
    resized=1
    break
  fi

  sleep 1
done

if [[ "${resized}" != "1" ]]; then
  echo "[gazebo_gui_client] WARNING: did not find window title ${WINDOW_TITLE}"
fi

wait "${GUI_PID}"
