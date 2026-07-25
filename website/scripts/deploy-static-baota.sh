#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 8 ]]; then
  echo "usage: $0 ARCHIVE VERSION INSTALLER_SHA256 STAGING_CONF PUBLIC_CONF PUBLIC_HOST PUBLIC_SCHEME VHOST_MODE" >&2
  exit 64
fi

archive=$1
version=$2
expected_installer_sha=${3,,}
staging_config=$4
public_config=$5
public_host=$6
public_scheme=$7
vhost_mode=$8

if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "invalid release version: $version" >&2
  exit 64
fi
if [[ ! $expected_installer_sha =~ ^[0-9a-f]{64}$ ]]; then
  echo "invalid installer SHA-256" >&2
  exit 64
fi
if [[ ! $public_host =~ ^[0-9A-Za-z.-]+$ ]]; then
  echo "invalid public host" >&2
  exit 64
fi
if [[ $public_scheme != http && $public_scheme != https ]]; then
  echo "invalid public scheme: $public_scheme" >&2
  exit 64
fi
if [[ $vhost_mode != install && $vhost_mode != preserve ]]; then
  echo "invalid vhost mode: $vhost_mode" >&2
  exit 64
fi
if [[ $vhost_mode == install && $public_scheme != http ]]; then
  echo "the repository-managed vhost is HTTP preview-only" >&2
  exit 64
fi
if [[ $vhost_mode == preserve && $public_scheme != https ]]; then
  echo "preserved production vhosts must be verified over HTTPS" >&2
  exit 64
fi
for required_file in "$archive" "$staging_config"; do
  if [[ ! -f $required_file ]]; then
    echo "missing deployment input: $required_file" >&2
    exit 66
  fi
done
if [[ $vhost_mode == install && ! -f $public_config ]]; then
  echo "missing deployment input: $public_config" >&2
  exit 66
fi
for command_name in awk curl find flock grep install mv nginx python3 readlink rm \
  sha256sum systemctl tar tr; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required deployment command is unavailable: $command_name" >&2
    exit 69
  fi
done

base=/www/wwwroot/dronedream
releases=$base/releases
current=$base/current
candidate=$base/candidate
public_vhost=/www/server/panel/vhost/nginx/dronedream.conf
staging_vhost=/www/server/panel/vhost/nginx/dronedream-staging.conf
release_id="${version}-$(date -u +%Y%m%dT%H%M%SZ)"
upload_dir="$releases/.${release_id}.uploading"
release_dir="$releases/$release_id"
next_link="$base/.current-${release_id}"
candidate_link="$base/.candidate-${release_id}"
config_backup=""
installer_name_file=""
had_public_config=0
previous_target=""
public_config_changed=0
nginx_dump_file=""

# Serialize releases so two operators or CI retries cannot delete or activate
# each other's candidate directories during the rollback window.
install -d -m 0755 "$base"
exec 9>"$base/.deploy.lock"
if ! flock -n 9; then
  echo "another DroneDream deployment is already running" >&2
  exit 75
fi

cleanup_temp_files() {
  if [[ -n $config_backup ]]; then
    rm -f -- "$config_backup"
  fi
  if [[ -n $installer_name_file ]]; then
    rm -f -- "$installer_name_file"
  fi
  if [[ -n $nginx_dump_file ]]; then
    rm -f -- "$nginx_dump_file"
  fi
}
trap cleanup_temp_files EXIT

if [[ -L $current ]]; then
  previous_target=$(readlink "$current")
elif [[ -e $current ]]; then
  echo "$current exists but is not a symbolic link" >&2
  exit 65
fi
if [[ -e $candidate ]]; then
  echo "$candidate already exists; refusing to replace an unknown staging target" >&2
  exit 73
fi
if [[ -e $staging_vhost ]]; then
  echo "$staging_vhost already exists; remove the stale DroneDream staging vhost first" >&2
  exit 73
fi
if [[ $vhost_mode == preserve && ! -f $public_vhost ]]; then
  echo "the production BaoTa vhost is missing: $public_vhost" >&2
  exit 66
fi
if [[ $vhost_mode == install && -e $public_vhost ]]; then
  config_backup=$(mktemp /tmp/dronedream-nginx-backup.XXXXXX)
  cp -a "$public_vhost" "$config_backup"
  had_public_config=1
fi

validate_preserved_public_vhost() {
  nginx_dump_file=$(mktemp /tmp/dronedream-nginx-dump.XXXXXX)
  nginx -T >"$nginx_dump_file" 2>&1
  python3 - "$nginx_dump_file" "$public_host" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
host = sys.argv[2]

server_blocks: list[str] = []
for match in re.finditer(r"\bserver\s*\{", text):
    depth = 1
    index = match.end()
    while index < len(text) and depth:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    if depth == 0:
        server_blocks.append(text[match.start():index])

def names(block: str) -> set[str]:
    found: set[str] = set()
    for directive in re.findall(r"(?m)^\s*server_name\s+([^;]+);", block):
        found.update(directive.split())
    return found

matching = [block for block in server_blocks if host in names(block)]
if not matching:
    raise SystemExit(f"preserved vhost does not declare server_name {host}")
if not any(
    re.search(r"(?m)^\s*listen\s+(?:[^;\s]+:)?443\b[^;]*\bssl\b[^;]*;", block)
    for block in matching
):
    raise SystemExit(f"preserved vhost for {host} does not listen on 443 with TLS")
PY
  rm -f -- "$nginx_dump_file"
  nginx_dump_file=""
}

if [[ $vhost_mode == preserve ]]; then
  validate_preserved_public_vhost
fi

rollback() {
  status=$?
  trap - ERR INT TERM
  set +e
  if [[ -n $previous_target ]]; then
    ln -s "$previous_target" "$next_link.rollback"
    mv -Tf "$next_link.rollback" "$current"
  else
    rm -f "$current"
  fi
  rm -f -- "$candidate" "$staging_vhost" "$candidate_link" "$next_link"
  rm -rf -- "$upload_dir" "$release_dir"
  if [[ $public_config_changed -eq 1 ]]; then
    if [[ $had_public_config -eq 1 ]]; then
      cp -a "$config_backup" "$public_vhost"
    else
      rm -f "$public_vhost"
    fi
  fi
  nginx -t >/dev/null 2>&1 && systemctl reload nginx
  echo "deployment rolled back after an error" >&2
  exit "$status"
}
trap rollback ERR INT TERM

curl_until_contains() {
  local needle=$1
  shift
  local attempt
  local output
  for attempt in {1..20}; do
    if output=$(curl "$@" 2>/dev/null) && grep -F "$needle" <<< "$output" >/dev/null; then
      printf '%s' "$output"
      return 0
    fi
    sleep 0.25
  done
  echo "HTTP response did not contain the expected release marker: $needle" >&2
  return 1
}

curl_until_regex() {
  local pattern=$1
  shift
  local attempt
  local output
  for attempt in {1..20}; do
    if output=$(curl "$@" 2>/dev/null) && grep -Ei "$pattern" <<< "$output" >/dev/null; then
      printf '%s' "$output"
      return 0
    fi
    sleep 0.25
  done
  echo "HTTP response did not match the expected release header: $pattern" >&2
  return 1
}

require_security_headers() {
  local headers=$1
  local quiet=${2:-}
  local normalized_headers
  local pattern
  # curl emits HTTP headers with CRLF. Normalize them before matching so the
  # health check behaves consistently on older GNU grep/Bash combinations.
  normalized_headers=$(printf '%s\n' "$headers" | tr -d '\r')
  for pattern in \
    '^x-content-type-options:[[:space:]]*nosniff' \
    '^referrer-policy:[[:space:]]*strict-origin-when-cross-origin' \
    '^x-frame-options:[[:space:]]*deny' \
    '^permissions-policy:.*camera=\(self\).*microphone=\(self\).*geolocation=\(\)' \
    "^content-security-policy:.*frame-ancestors[[:space:]]+'none'"; do
    # Do not pipe into `grep -q` while `pipefail` is active: once grep finds a
    # match it may close the pipe early, making printf report SIGPIPE and the
    # otherwise successful health check look like a failure.
    if ! grep -Eiq "$pattern" <<< "$normalized_headers"; then
      if [[ $quiet != quiet ]]; then
        echo "HTTP response is missing a required security header: $pattern" >&2
      fi
      return 1
    fi
  done
}

curl_until_security_headers() {
  local attempt
  local output=""
  for attempt in {1..20}; do
    if output=$(curl "$@" 2>/dev/null) && require_security_headers "$output" quiet; then
      printf '%s' "$output"
      return 0
    fi
    # `systemctl reload nginx` can return while an old worker is still
    # accepting a few connections with the previous vhost headers.
    sleep 0.25
  done
  require_security_headers "$output"
  echo "HTTP response did not converge to the required security headers" >&2
  return 1
}

install -d -m 0755 "$releases"
# Validate both member paths and member types before extraction. GNU tar path
# checks alone do not prevent symlink/hardlink escapes, device nodes, or a tiny
# compressed archive expanding until it exhausts the server disk.
python3 - "$archive" <<'PY'
import pathlib
import sys
import tarfile

MAX_MEMBERS = 10_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024

archive_path = pathlib.Path(sys.argv[1])
seen = set()
total_size = 0
with tarfile.open(archive_path, mode="r:gz") as archive:
    members = archive.getmembers()
    if len(members) > MAX_MEMBERS:
        raise SystemExit("archive contains too many entries")
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"archive contains an unsafe path: {member.name!r}")
        normalized = str(path)
        if normalized not in {"", "."} and normalized in seen:
            raise SystemExit(f"archive contains a duplicate path: {member.name!r}")
        seen.add(normalized)
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"archive contains a forbidden member type: {member.name!r}")
        if member.size < 0:
            raise SystemExit(f"archive contains an invalid member size: {member.name!r}")
        total_size += member.size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise SystemExit("archive exceeds the uncompressed size limit")
PY
if [[ -e $upload_dir || -e $release_dir ]]; then
  echo "release destination already exists: $release_id" >&2
  exit 73
fi

install -d -m 0755 "$upload_dir"
tar --extract --gzip --file "$archive" --directory "$upload_dir" \
  --no-same-owner --no-same-permissions
test -f "$upload_dir/index.html"
test -f "$upload_dir/SHA256SUMS"
test -f "$upload_dir/downloads/latest.json"
pushd "$upload_dir" >/dev/null
sha256sum --check SHA256SUMS
popd >/dev/null

installer_name_file=$(mktemp /tmp/dronedream-installer-name.XXXXXX)
# Keep validation outside a command substitution. With `set -E`, an error
# raised inside `$(...)` inherits the ERR trap and can invoke rollback once in
# the subshell and once again in the parent shell.
if ! python3 - "$upload_dir/downloads/latest.json" "$version" "$expected_installer_sha" \
    >"$installer_name_file" <<'PY'
import json
import pathlib
import sys
from datetime import date

path = pathlib.Path(sys.argv[1])
version = sys.argv[2]
expected_sha = sys.argv[3]
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("version") != version:
    raise SystemExit("latest.json version does not match the deployment version")
if data.get("sha256") != expected_sha:
    raise SystemExit("latest.json installer SHA-256 does not match")
name = data.get("fileName")
if not isinstance(name, str) or pathlib.PurePath(name).name != name:
    raise SystemExit("latest.json contains an unsafe installer filename")
expected_name = f"DroneDream_{version}_x64-setup.exe"
if name != expected_name:
    raise SystemExit("latest.json installer filename does not match the release version")
if data.get("downloadUrl") != f"/downloads/{name}":
    raise SystemExit("latest.json contains an inconsistent installer URL")
checksum_name = f"{name}.sha256"
if data.get("checksumUrl") != f"/downloads/{checksum_name}":
    raise SystemExit("latest.json contains an inconsistent checksum URL")
installer = path.parent / name
checksum = path.parent / checksum_name
if not installer.is_file() or not checksum.is_file():
    raise SystemExit("latest.json references a missing release artifact")
size_bytes = data.get("sizeBytes")
if not isinstance(size_bytes, int) or size_bytes <= 0 or size_bytes != installer.stat().st_size:
    raise SystemExit("latest.json installer size does not match the release artifact")
checksum_fields = checksum.read_text(encoding="utf-8").strip().split()
if checksum_fields != [expected_sha, name]:
    raise SystemExit("published checksum file does not match latest.json")
published_at = data.get("publishedAt")
try:
    parts = [int(part) for part in published_at.split("-")]
    parsed_date = date(*parts)
    if len(parts) != 3 or parsed_date.isoformat() != published_at:
        raise ValueError("date must use YYYY-MM-DD")
except (AttributeError, TypeError, ValueError) as exc:
    raise SystemExit("latest.json contains an invalid publication date") from exc
print(name)
PY
then
  echo "release metadata validation failed" >&2
  false
fi
installer_name=$(tr -d '\r\n' <"$installer_name_file")
rm -f -- "$installer_name_file"
installer_name_file=""

installer_path="$upload_dir/downloads/$installer_name"
test -f "$installer_path"
actual_installer_sha=$(sha256sum "$installer_path" | awk '{print $1}')
if [[ $actual_installer_sha != "$expected_installer_sha" ]]; then
  echo "installer SHA-256 does not match the expected release" >&2
  exit 65
fi

find "$upload_dir" -type d -exec chmod 0755 {} +
find "$upload_dir" -type f -exec chmod 0644 {} +
chown -R root:root "$upload_dir"
mv "$upload_dir" "$release_dir"
ln -s "$release_dir" "$candidate_link"
mv -Tf "$candidate_link" "$candidate"

# First validate the release on a loopback-only port. Nothing public changes
# unless this page, metadata, and installer all pass their health checks.
install -m 0644 "$staging_config" "$staging_vhost"
nginx -t
systemctl reload nginx
staging_page=$(
  curl_until_contains '<title>DroneDream' -fsS --max-time 10 http://127.0.0.1:18080/
)
staging_console=$(
  curl_until_contains '<title>DroneDream' -fsS --max-time 10 \
    http://127.0.0.1:18080/console/
)
staging_metadata=$(
  curl_until_contains "\"version\":  \"$version\"" -fsS --max-time 10 \
    http://127.0.0.1:18080/downloads/latest.json
)
staging_installer_headers=$(
  curl_until_regex '^content-type: application/octet-stream' -fsSI --max-time 10 \
    "http://127.0.0.1:18080/downloads/$installer_name"
)
staging_security_headers=$(
  curl_until_security_headers -fsSI --max-time 10 http://127.0.0.1:18080/
)

# Publish the candidate. Preview mode installs the repository-managed HTTP
# vhost. Production mode preserves the employee-managed BaoTa TLS vhost and
# validates it before this point.
ln -s "$release_dir" "$next_link"
mv -Tf "$next_link" "$current"
if [[ $vhost_mode == install ]]; then
  public_config_changed=1
  install -m 0644 "$public_config" "$public_vhost"
fi
nginx -t
systemctl reload nginx

public_curl_args=()
if [[ $public_scheme == https ]]; then
  public_origin="https://$public_host"
  public_curl_args=(--resolve "$public_host:443:127.0.0.1")
else
  public_origin="http://127.0.0.1"
  public_curl_args=(-H "Host: $public_host")
fi
public_page=$(
  curl_until_contains '<title>DroneDream' -fsS --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/"
)
public_console=$(
  curl_until_contains '<title>DroneDream' -fsS --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/console/"
)
public_metadata=$(
  curl_until_contains "\"version\":  \"$version\"" -fsS --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/downloads/latest.json"
)
public_installer_headers=$(
  curl_until_regex '^content-length:' -fsSI --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/downloads/$installer_name"
)
public_security_headers=$(
  curl_until_security_headers -fsSI --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/"
)
if [[ $public_scheme == https ]]; then
  curl_until_regex '^strict-transport-security:' -fsSI --max-time 10 \
    "${public_curl_args[@]}" "$public_origin/" >/dev/null
  redirect_headers=$(
    curl_until_regex '^location:[[:space:]]*https://'"$public_host"'/' \
      -fsSI --max-time 10 -H "Host: $public_host" http://127.0.0.1/
  )
fi

rm -f "$candidate" "$staging_vhost"
nginx -t
systemctl reload nginx

trap - ERR INT TERM
echo "DRONEDREAM_RELEASE=$release_id"
echo "DRONEDREAM_CURRENT=$(readlink "$current")"
echo "DRONEDREAM_INSTALLER=$installer_name"
echo "DRONEDREAM_SHA256=$actual_installer_sha"
