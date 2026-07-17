#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

apply=0
if [[ ${1:-} == "--apply" ]]; then
  apply=1
  shift
fi

base=/www/wwwroot/dronedream
releases=$base/releases
if [[ ! -d $base || ! -d $releases ]]; then
  echo "the DroneDream release root is missing: $releases" >&2
  exit 66
fi
for command_name in flock readlink; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required prune command is unavailable: $command_name" >&2
    exit 69
  fi
done

# Use the exact deployment lock so pruning cannot remove a candidate while a
# release is being verified, activated, or rolled back.
exec 9>"$base/.deploy.lock"
if ! flock -n 9; then
  echo "another DroneDream deployment or prune is already running" >&2
  exit 75
fi

current=$(readlink -f "$base/current" || true)
if [[ -z $current || $(dirname "$current") != "$releases" || ! -d $current ]]; then
  echo "the live DroneDream release is not a valid child of $releases" >&2
  exit 65
fi

declare -A keep
keep["$current"]=1
for release_id in "$@"; do
  if [[ ! $release_id =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}T[0-9]{6}Z$ ]]; then
    echo "invalid retained release id: $release_id" >&2
    exit 64
  fi
  target=$(readlink -f "$releases/$release_id" || true)
  if [[ -z $target || $(dirname "$target") != "$releases" || ! -d $target ]]; then
    echo "retained release is missing or unsafe: $release_id" >&2
    exit 65
  fi
  keep["$target"]=1
done

for path in "$releases"/* "$releases"/.*.uploading; do
  [[ -d $path ]] || continue
  resolved=$(readlink -f "$path")
  name=$(basename "$resolved")
  if [[ $(dirname "$resolved") != "$releases" ]]; then
    echo "refusing to prune outside $releases: $resolved" >&2
    exit 65
  fi
  if [[ ! $name =~ ^\.?[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}T[0-9]{6}Z(\.uploading)?$ ]]; then
    echo "refusing to prune an unexpected release name: $name" >&2
    exit 65
  fi
  if [[ -n ${keep[$resolved]:-} ]]; then
    echo "KEEP $name"
    continue
  fi
  if [[ $apply -eq 1 ]]; then
    rm -rf -- "$resolved"
    echo "REMOVED $name"
  else
    echo "WOULD_REMOVE $name"
  fi
done
