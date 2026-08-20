#!/usr/bin/env bash

set -eo pipefail
source /opt/ros/jazzy/setup.bash
set -u

output_dir="${1:-/tmp/dronedream-ros2-dds}"
mkdir -p "$output_dir"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-71}"
export ROS2_DISABLE_DAEMON=1
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

cleanup() {
  if [[ -n "${publisher_pid:-}" ]]; then
    kill "$publisher_pid" 2>/dev/null || true
    wait "$publisher_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

ros2 topic pub --rate 5 /dronedream_dds_smoke std_msgs/msg/String \
  '{data: dronedream-dds-alive}' >"$output_dir/publisher.log" 2>&1 &
publisher_pid=$!
sleep 3

if ! kill -0 "$publisher_pid" 2>/dev/null; then
  tail -80 "$output_dir/publisher.log" >&2
  exit 30
fi

if ! timeout 20 ros2 topic echo --no-daemon --spin-time 2 --once \
  /dronedream_dds_smoke std_msgs/msg/String \
  >"$output_dir/subscriber.yaml" 2>"$output_dir/subscriber.log"; then
  tail -80 "$output_dir/publisher.log" >&2
  tail -80 "$output_dir/subscriber.log" >&2
  exit 31
fi

grep -q 'dronedream-dds-alive' "$output_dir/subscriber.yaml"
printf 'ROS2_DDS_ACCEPTED domain=%s output=%s\n' "$ROS_DOMAIN_ID" "$output_dir/subscriber.yaml"
