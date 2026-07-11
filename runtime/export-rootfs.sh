#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
image=${1:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
report=${2:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
output=${3:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
max_bytes=$((12 * 1024 * 1024 * 1024))
work=$(mktemp -d)
container=

cleanup() {
  if [[ -n "$container" ]]; then
    docker rm --force "$container" >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

test -f "$report" || { echo "smoke report does not exist: $report" >&2; exit 2; }
docker image inspect "$image" >/dev/null
container=$(docker create "$image" /bin/true)
docker cp "$container:/opt/dronedream/runtime-manifest.json" "$work/unpromoted.json"

image_id=$(docker image inspect --format '{{.Id}}' "$image")
python3 - "$report" "$work/unpromoted.json" "$image_id" <<'PY'
import json
import pathlib
import sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
manifest = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
if report.get("passed") is not True:
    raise SystemExit("release export refused: smoke report did not pass")
if report.get("mode") != "runtime-image":
    raise SystemExit("release export refused: wrong smoke report mode")
if report.get("runtimeId") != manifest.get("runtimeId"):
    raise SystemExit("release export refused: runtime identity mismatch")
if report.get("imageId") != sys.argv[3]:
    raise SystemExit("release export refused: smoke report belongs to another image")
PY

python3 "$root/runtime/tools/runtime_manifest.py" promote-smoke \
  --manifest "$work/unpromoted.json" --report "$report" --output "$work/promoted.json"
python3 "$root/runtime/tools/runtime_manifest.py" validate \
  --manifest "$work/promoted.json" --require-smoke-passed
docker cp "$work/promoted.json" "$container:/opt/dronedream/runtime-manifest.json"

mkdir -p "$(dirname "$output")"
partial="$output.partial"
rm -f "$partial"
docker export --output "$partial" "$container"
bytes=$(stat --format='%s' "$partial")
if (( bytes > max_bytes )); then
  rm -f "$partial"
  echo "release rootfs is $bytes bytes; hard limit is $max_bytes bytes (12 GiB)" >&2
  exit 1
fi
mv "$partial" "$output"
sha256sum "$output" >"$output.sha256"
cp "$work/promoted.json" "$output.manifest.json"
echo "exported $output ($bytes bytes)"
