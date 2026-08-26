#!/usr/bin/env bash
set -eo pipefail

runtime_root="${HOME}/.local/share/dronedream-autonomy/v0.1.0"
source /opt/ros/jazzy/setup.bash
source "${runtime_root}/ros_ws/install/setup.bash"
set -u

export ROS_DOMAIN_ID=77
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS2_DISABLE_DAEMON=1
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

temporary_root="$(mktemp -d -t dronedream-capability-shutdown-XXXXXX)"
host_log="${temporary_root}/capability-host.log"
publisher_log="${temporary_root}/publisher.log"
host_pid=""
publisher_pid=""

cleanup() {
  if [[ -n "${host_pid}" ]]; then
    kill "$host_pid" 2>/dev/null || true
    wait "$host_pid" 2>/dev/null || true
  fi
  if [[ -n "${publisher_pid}" ]]; then
    kill "$publisher_pid" 2>/dev/null || true
    wait "$publisher_pid" 2>/dev/null || true
  fi
  if [[ "${temporary_root}" == /tmp/dronedream-capability-shutdown-* ]]; then
    rm -rf -- "${temporary_root}"
  fi
}
trap cleanup EXIT

ros2 topic pub --rate 30 /dronedream/mission_observation \
  dronedream_agent_msgs/msg/MissionObservation \
  "{contract_id: shutdown-contract, segment_id: shutdown-probe, sequence: 1, battery_percent: 100.0, battery_available: true, localization_ok: true, link_ok: true, geofence_ok: true, target_reached: false, deviation_code: OK, source_topic: shutdown-probe}" \
  >"${publisher_log}" 2>&1 &
publisher_pid=$!

ros2 run dronedream_agent_plugin_api capability_host --ros-args \
  -p contract_id:=shutdown-contract \
  -p watchdog_deadline_ms:=250 \
  -p watchdog_startup_deadline_ms:=5000 >"${host_log}" 2>&1 &
host_pid=$!

for _ in $(seq 1 100); do
  grep -q 'activated plugin runtime.safe-hold' "${host_log}" && break
  sleep 0.05
done
grep -q 'activated plugin runtime.safe-hold' "${host_log}"
sleep 2

ros2 topic pub --once /dronedream/mission_lifecycle \
  dronedream_agent_msgs/msg/MissionLifecycle \
  "{contract_id: wrong-contract, terminal_state: ON_GROUND, executor_return_code: 0, landing_confirmed: true, safe_to_stop_watchdog: true}" \
  >/dev/null
sleep 0.3
if grep -q 'accepted core terminal lifecycle event' "${host_log}"; then
  cat "${host_log}" >&2
  echo "ROS_CAPABILITY_SHUTDOWN_FAILED mismatched-terminal-contract-was-accepted" >&2
  exit 42
fi

ros2 topic pub --once /dronedream/mission_lifecycle \
  dronedream_agent_msgs/msg/MissionLifecycle \
  "{contract_id: shutdown-contract, terminal_state: ON_GROUND, executor_return_code: 0, landing_confirmed: true, safe_to_stop_watchdog: true}" \
  >/dev/null
for _ in $(seq 1 50); do
  grep -q 'accepted core terminal lifecycle event' "${host_log}" && break
  sleep 0.05
done
grep -q 'accepted core terminal lifecycle event' "${host_log}"

kill "$publisher_pid" 2>/dev/null || true
wait "$publisher_pid" 2>/dev/null || true
publisher_pid=""
sleep 0.5

kill -TERM "$host_pid"
host_status=0
wait "$host_pid" || host_status=$?
host_pid=""

if [[ "$host_status" -ne 0 && "$host_status" -ne 143 ]]; then
  cat "${host_log}" >&2
  echo "ROS_CAPABILITY_SHUTDOWN_FAILED unexpected-host-status=${host_status}" >&2
  exit 41
fi

if grep -q 'forced fail-closed hold' "${host_log}"; then
  cat "${host_log}" >&2
  echo "ROS_CAPABILITY_SHUTDOWN_FAILED orderly-shutdown-triggered-watchdog" >&2
  exit 40
fi

grep -q 'activated plugin runtime.safe-hold' "${host_log}"
printf 'ROS_CAPABILITY_SHUTDOWN_READY active-observations=ok terminal-contract=bound on-ground-stop=clean sigterm=clean false-emergency=absent\n'
