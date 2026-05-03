#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"

echo "Gazebo window maximizer started on DISPLAY=${DISPLAY}"

while true; do
  if command -v xdpyinfo >/dev/null 2>&1 && xdpyinfo >/dev/null 2>&1; then
    read -r W H < <(xdpyinfo | awk '/dimensions:/ {split($2,a,"x"); print a[1], a[2]; exit}')

    if [[ -n "${W:-}" && -n "${H:-}" ]]; then
      ids="$(xdotool search --name "Gazebo" 2>/dev/null || true)"
      for id in $ids; do
        xdotool windowactivate "$id" >/dev/null 2>&1 || true
        xdotool windowmove "$id" 0 0 >/dev/null 2>&1 || true
        xdotool windowsize "$id" "$W" "$H" >/dev/null 2>&1 || true
        wmctrl -ir "$id" -b add,maximized_vert,maximized_horz >/dev/null 2>&1 || true
      done
    fi
  fi

  sleep 2
done
