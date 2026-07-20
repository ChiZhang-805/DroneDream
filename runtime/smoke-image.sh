#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
image=${1:?usage: smoke-image.sh IMAGE [REPORT_JSON]}
report=${2:-"$root/runtime/out/smoke-report.json"}
container="dronedream-runtime-smoke-$RANDOM-$$"
work=$(mktemp -d)
mkdir -p "$(dirname "$report")"

cleanup() {
  docker exec "$container" /usr/bin/rm -rf -- \
    /var/lib/dronedream/runtime-smoke >/dev/null 2>&1 || true
  docker rm --force "$container" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

docker run --detach --name "$container" --privileged --cgroupns=host \
  --tmpfs /run --tmpfs /run/lock \
  --volume /sys/fs/cgroup:/sys/fs/cgroup:rw \
  "$image" >/dev/null

docker exec "$container" /usr/bin/install -d -m 0750 \
  -o dronedream -g dronedream /var/lib/dronedream/runtime-smoke
runtime_initialized=false
for _ in $(seq 1 60); do
  if docker exec "$container" /usr/bin/systemctl is-active --quiet \
    dronedream-runtime-init.service; then
    runtime_initialized=true
    break
  fi
  sleep 1
done
if [[ "$runtime_initialized" != true ]]; then
  echo "runtime systemd initializer did not become active" >&2
  exit 1
fi

# Keep these values synchronized with dronedream-worker.service. The contract
# test fails if a worker sandbox property changes without updating this list.
sandbox_properties=(
  "User=dronedream"
  "Group=dronedream"
  "UMask=0027"
  "NoNewPrivileges=true"
  "PrivateTmp=true"
  "ProtectSystem=strict"
  "ProtectHome=read-only"
  "ProtectKernelTunables=true"
  "ProtectKernelModules=true"
  "ProtectControlGroups=true"
  "LockPersonality=true"
  "RestrictSUIDSGID=true"
  "ReadWritePaths=/var/lib/dronedream /opt/PX4-Autopilot/build /home/dronedream /tmp"
)

checks=(
  component_versions
  python_imports
  valkey_ping
  api_worker_heartbeat
  real_cli_dry_run
  px4_gazebo_headless
  parameter_readback
)
status_file="$work/status.tsv"
all_passed=true
for check in "${checks[@]}"; do
  started=$(date +%s)
  log="$work/$check.log"
  check_timeout=300
  if [[ "$check" == px4_gazebo_headless ]]; then
    check_timeout=1800
  fi
  unit="dronedream-smoke-${check}-${RANDOM}-$$"
  systemd_args=(
    --quiet
    --wait
    --pipe
    --collect
    "--unit=$unit"
    --working-directory=/opt/dronedream/source
  )
  for property in "${sandbox_properties[@]}"; do
    systemd_args+=(--property "$property")
  done
  if timeout --signal=KILL "$((check_timeout + 60))s" \
    docker exec "$container" /usr/bin/systemd-run "${systemd_args[@]}" \
      /usr/bin/timeout --signal=TERM --kill-after=30 "${check_timeout}s" \
      /usr/lib/dronedream/runtime-check.sh "$check" \
      >"$log" 2>&1; then
    passed=true
  else
    passed=false
    all_passed=false
  fi
  duration=$(( $(date +%s) - started ))
  printf '%s\t%s\t%s\n' "$check" "$passed" "$duration" >>"$status_file"
  sed "s/^/[$check] /" "$log"
done

docker cp "$container:/opt/dronedream/runtime-manifest.json" "$work/manifest.json"
runtime_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtimeId"])' "$work/manifest.json")
image_id=$(docker image inspect --format '{{.Id}}' "$image")
python3 - "$status_file" "$report" "$runtime_id" "$image_id" <<'PY'
import datetime
import json
import pathlib
import sys

status_path, report_path, runtime_id, image_id = sys.argv[1:]
checks = []
for line in pathlib.Path(status_path).read_text(encoding="utf-8").splitlines():
    name, passed, duration = line.split("\t")
    checks.append({"name": name, "passed": passed == "true", "durationSeconds": int(duration)})
payload = {
    "mode": "runtime-image",
    "runtimeId": runtime_id,
    "imageId": image_id,
    "passed": all(item["passed"] for item in checks),
    "completedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "checks": checks,
}
pathlib.Path(report_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "smoke report: $report"
[[ "$all_passed" == true ]]
