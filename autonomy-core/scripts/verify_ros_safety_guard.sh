#!/usr/bin/env bash
set -eo pipefail

runtime_root="${HOME}/.local/share/dronedream-autonomy/v0.1.0"
source /opt/ros/jazzy/setup.bash
source "${runtime_root}/ros_ws/install/setup.bash"
set -u
export ROS_DOMAIN_ID=76
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS2_DISABLE_DAEMON=1
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

temporary_root="$(mktemp -d -t dronedream-safety-guard-XXXXXX)"
abort_file="${temporary_root}/live_abort.request.json"
guard_log="${temporary_root}/guard.log"
guard_pid=""
host_pid=""
cleanup() {
  if [[ -n "${host_pid}" ]]; then
    kill "${host_pid}" 2>/dev/null || true
    wait "${host_pid}" 2>/dev/null || true
  fi
  if [[ -n "${guard_pid}" ]]; then
    kill "${guard_pid}" 2>/dev/null || true
    wait "${guard_pid}" 2>/dev/null || true
  fi
  if [[ "${temporary_root}" == /tmp/dronedream-safety-guard-* ]]; then
    rm -rf -- "${temporary_root}"
  fi
}
trap cleanup EXIT

ros2 run dronedream_agent_ros safety_event_guard --ros-args \
  -p contract_id:=safety-guard-contract \
  -p abort_file:="${abort_file}" >"${guard_log}" 2>&1 &
guard_pid=$!

sleep 1
ros2 topic pub --once /dronedream/safety_event \
  dronedream_agent_msgs/msg/SafetyEvent \
  "{contract_id: wrong-contract, observation_sequence: 7, severity: 3, action: safe_hold_then_land, issue_codes: [WATCHDOG_DEADLINE]}" \
  >/dev/null
sleep 1
if [[ -e "${abort_file}" ]]; then
  echo "SAFETY_GUARD_FAILED mismatched-contract-was-authorized" >&2
  exit 2
fi

ros2 topic pub --once /dronedream/safety_event \
  dronedream_agent_msgs/msg/SafetyEvent \
  "{contract_id: safety-guard-contract, observation_sequence: 8, severity: 3, action: safe_hold_then_land, issue_codes: [WATCHDOG_DEADLINE]}" \
  >/dev/null
for _ in $(seq 1 50); do
  [[ -f "${abort_file}" ]] && break
  sleep 0.1
done
test -f "${abort_file}"
"${runtime_root}/venv/bin/python" - "${abort_file}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
assert payload["reason"] == "NATIVE_RUNTIME_SAFETY_EVENT"
assert payload["contract_id"] == "safety-guard-contract"
assert payload["action"] == "safe_hold_then_land"
assert payload["severity"] == 3
assert payload["observation_sequence"] == 8
assert payload["issue_codes"] == ["WATCHDOG_DEADLINE"]
print(
    "ROS_SAFETY_GUARD_READY "
    f"contract_rejection=ok authorized_abort=ok sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"
)
PY

kill "${guard_pid}" 2>/dev/null || true
wait "${guard_pid}" 2>/dev/null || true
guard_pid=""
abort_file="${temporary_root}/watchdog-abort.request.json"
host_log="${temporary_root}/capability-host.log"
ros2 run dronedream_agent_ros safety_event_guard --ros-args \
  -p contract_id:=watchdog-contract \
  -p abort_file:="${abort_file}" >>"${guard_log}" 2>&1 &
guard_pid=$!
sleep 1
ros2 run dronedream_agent_plugin_api capability_host --ros-args \
  -p contract_id:=watchdog-contract \
  -p watchdog_deadline_ms:=100 \
  -p watchdog_startup_deadline_ms:=1000 >"${host_log}" 2>&1 &
host_pid=$!
for _ in $(seq 1 50); do
  [[ -f "${abort_file}" ]] && break
  sleep 0.1
done
test -f "${abort_file}"
test "$(grep -c 'forced fail-closed hold' "${host_log}")" -eq 1
"${runtime_root}/venv/bin/python" - "${abort_file}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["contract_id"] == "watchdog-contract"
assert payload["action"] == "safe_hold_then_land"
assert payload["issue_codes"] == ["WATCHDOG_HEALTH_OR_DEADLINE_FAILURE"]
print("ROS_WATCHDOG_ABORT_READY single_fail_closed_event=ok executor_abort_gate=ok")
PY
