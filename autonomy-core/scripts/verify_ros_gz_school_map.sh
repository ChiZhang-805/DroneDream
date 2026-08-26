#!/usr/bin/env bash

set -eo pipefail

if [[ -f /opt/ros/jazzy/setup.bash ]]; then
  # ROS setup scripts are not compatible with nounset while they are being sourced.
source /opt/ros/jazzy/setup.bash
else
  printf 'ROS 2 Jazzy is not installed at /opt/ros/jazzy\n' >&2
  exit 20
fi
set -u

# ROS vendors Gazebo Transport and prepends a reduced `gz` command catalog.
# Retain that ABI-compatible catalog while making the system Gazebo Sim command
# available to the same process.
export GZ_CONFIG_PATH="/usr/share/gz:${GZ_CONFIG_PATH:-}"
gz_binary="/usr/bin/gz"
export GZ_SIM_RESOURCE_PATH="/opt/PX4-Autopilot/Tools/simulation/gz/models:${GZ_SIM_RESOURCE_PATH:-}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-72}"
export ROS2_DISABLE_DAEMON=1
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

world_path="${1:?usage: verify_ros_gz_school_map.sh WORLD_SDF VEHICLE_SDF [OUTPUT_DIR]}"
vehicle_path="${2:?usage: verify_ros_gz_school_map.sh WORLD_SDF VEHICLE_SDF [OUTPUT_DIR]}"
output_dir="${3:-/tmp/dronedream-ros-gz-acceptance}"
partition="dronedream_ros_gz_${$}"

if [[ ! -f "$world_path" ]]; then
  printf 'School Map world does not exist: %s\n' "$world_path" >&2
  exit 21
fi
if [[ ! -f "$vehicle_path" ]]; then
  printf 'Qualified vehicle does not exist: %s\n' "$vehicle_path" >&2
  exit 28
fi

mkdir -p "$output_dir"
export GZ_PARTITION="$partition"

terminate_group() {
  local process_group="$1"
  kill -TERM -- "-$process_group" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! pgrep -g "$process_group" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done
  kill -KILL -- "-$process_group" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! pgrep -g "$process_group" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done
  printf 'Process group %s survived cleanup\n' "$process_group" >&2
}

cleanup() {
  if [[ -n "${bridge_pid:-}" ]]; then
    terminate_group "$bridge_pid"
  fi
  if [[ -n "${gz_pid:-}" ]]; then
    terminate_group "$gz_pid"
  fi
}
trap cleanup EXIT

setsid "$gz_binary" sim -r -s -v 2 "$world_path" >"$output_dir/gazebo.log" 2>&1 &
gz_pid=$!

for _ in $(seq 1 60); do
  if "$gz_binary" topic -l 2>/dev/null | grep -qx '/clock'; then
    break
  fi
  if ! kill -0 "$gz_pid" 2>/dev/null; then
    tail -80 "$output_dir/gazebo.log" >&2
    exit 22
  fi
  sleep 1
done

if ! "$gz_binary" topic -l 2>/dev/null | grep -qx '/clock'; then
  printf 'Gazebo did not expose /clock within 60 seconds\n' >&2
  exit 23
fi

"$gz_binary" topic -l | sort >"$output_dir/gazebo-topics.txt"

spawn_request="sdf_filename: \"$vehicle_path\" name: \"my_drone\" pose { position { x: -42.25 y: 15.3 z: 7.487 } } allow_renaming: false"
if ! "$gz_binary" service -s /world/school_map_world/create \
  --reqtype gz.msgs.EntityFactory --reptype gz.msgs.Boolean \
  --timeout 5000 --req "$spawn_request" \
  >"$output_dir/vehicle-spawn.txt" 2>"$output_dir/vehicle-spawn.log"; then
  cat "$output_dir/vehicle-spawn.log" >&2
  exit 29
fi
if ! grep -q 'data: true' "$output_dir/vehicle-spawn.txt"; then
  cat "$output_dir/vehicle-spawn.txt" >&2
  exit 30
fi
if ! timeout 20 "$gz_binary" topic -e -n 1 \
  -t /world/school_map_world/dynamic_pose/info \
  >"$output_dir/gazebo-dynamic-pose.txt"; then
  printf 'Gazebo did not publish a dynamic vehicle pose\n' >&2
  exit 31
fi
grep -q 'name: "my_drone"' "$output_dir/gazebo-dynamic-pose.txt"

setsid ros2 run ros_gz_bridge parameter_bridge \
  '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock' \
  '/world/school_map_world/dynamic_pose/info@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V' \
  >"$output_dir/ros-gz-bridge.log" 2>&1 &
bridge_pid=$!

sleep 2
if ! kill -0 "$bridge_pid" 2>/dev/null; then
  tail -80 "$output_dir/ros-gz-bridge.log" >&2
  exit 24
fi

# `ros2 topic list` uses the long-lived ROS daemon and can hang when a WSL
# network interface changes. Direct subscription exercises DDS and the bridge
# without accepting daemon discovery as evidence.
if ! timeout 30 ros2 topic echo --no-daemon --spin-time 2 --once \
  /clock rosgraph_msgs/msg/Clock >"$output_dir/ros-clock.yaml"; then
  tail -80 "$output_dir/ros-gz-bridge.log" >&2
  printf 'ROS 2 did not receive a Gazebo clock sample\n' >&2
  exit 26
fi

if ! timeout 30 ros2 topic echo --no-daemon --spin-time 2 --once \
  /world/school_map_world/dynamic_pose/info tf2_msgs/msg/TFMessage \
  >"$output_dir/ros-world-poses.yaml"; then
  tail -80 "$output_dir/ros-gz-bridge.log" >&2
  printf 'ROS 2 did not receive a Gazebo world pose sample\n' >&2
  exit 27
fi
test -s "$output_dir/ros-world-poses.yaml"

python3 - "$world_path" "$vehicle_path" "$output_dir/acceptance.json" <<'PY'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

world_path = Path(sys.argv[1])
vehicle_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
payload = {
    "schema_version": "dronedream.ros-gz-acceptance.v1",
    "accepted": True,
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "world_path": str(world_path),
    "world_sha256": hashlib.sha256(world_path.read_bytes()).hexdigest(),
    "vehicle_path": str(vehicle_path),
    "vehicle_sha256": hashlib.sha256(vehicle_path.read_bytes()).hexdigest(),
    "observed_entity": "my_drone",
    "gazebo_topic": "/clock",
    "ros_topic": "/clock",
    "gazebo_pose_topic": "/world/school_map_world/dynamic_pose/info",
    "ros_pose_topic": "/world/school_map_world/dynamic_pose/info",
    "bridge": "ros_gz_bridge/parameter_bridge",
}
output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

printf 'ROS_GZ_SCHOOL_MAP_ACCEPTED output=%s\n' "$output_dir/acceptance.json"
