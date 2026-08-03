#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
image=${1:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
report=${2:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
output=${3:?usage: export-rootfs.sh IMAGE SMOKE_REPORT OUTPUT_TAR}
max_bytes=$((12 * 1024 * 1024 * 1024))
work=$(mktemp -d)
container=
partial="$output.partial"
checksum="$output.sha256"
checksum_partial="$checksum.partial"
manifest="$output.manifest.json"
manifest_partial="$manifest.partial"

# Release artifacts are immutable.  Refuse stale or operator-supplied paths
# before Docker is touched; silently replacing a tarball or one of its
# integrity sidecars could make smoke evidence describe different bytes.
for artifact in \
  "$output" "$partial" \
  "$checksum" "$checksum_partial" \
  "$manifest" "$manifest_partial"; do
  if [[ -e "$artifact" || -L "$artifact" ]]; then
    echo "release export refuses to overwrite existing path: $artifact" >&2
    exit 2
  fi
done

cleanup() {
  if [[ -n "$container" ]]; then
    docker rm --force "$container" >/dev/null 2>&1 || true
  fi
  committed=false
  if [[ -e "$output" && -e "$partial" && "$output" -ef "$partial" ]]; then
    committed=true
  fi
  if [[ "$committed" != true ]]; then
    if [[ -e "$checksum" && -e "$checksum_partial" \
      && "$checksum" -ef "$checksum_partial" ]]; then
      rm -f -- "$checksum" || true
    fi
    if [[ -e "$manifest" && -e "$manifest_partial" \
      && "$manifest" -ef "$manifest_partial" ]]; then
      rm -f -- "$manifest" || true
    fi
  fi
  rm -f -- "$partial" "$checksum_partial" "$manifest_partial" || true
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
docker export --output "$partial" "$container"
bytes=$(stat --format='%s' "$partial")
if (( bytes > max_bytes )); then
  echo "release rootfs is $bytes bytes; hard limit is $max_bytes bytes (12 GiB)" >&2
  exit 1
fi
digest=$(sha256sum "$partial" | cut -d ' ' -f 1)
[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "release rootfs checksum is malformed" >&2
  exit 1
}
printf '%s  %s\n' "$digest" "$(basename "$output")" >"$checksum_partial"
cp "$work/promoted.json" "$manifest_partial"

# Publish the two integrity sidecars first and the rootfs last.  The final
# rootfs path is the commit signal: whenever it exists, both sidecars already
# exist.  Same-filesystem hard links are atomic, never replace a competing
# path, and leave an inode-identical staging name so cleanup can prove which
# files belong to this process even if it is interrupted between commands.
ln -- "$checksum_partial" "$checksum"
ln -- "$manifest_partial" "$manifest"
ln -- "$partial" "$output"
echo "exported $output ($bytes bytes)"
