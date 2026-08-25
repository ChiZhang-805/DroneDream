#!/usr/bin/env bash
set -euo pipefail

# LEGACY: this targets the generic /var/www layout, not the active BaoTa host.
# Current releases must use deploy-static-baota.ps1/deploy-static-baota.sh.
echo "warning: deploy-static.sh is the legacy generic-Nginx workflow" >&2

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 user@server" >&2
  exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
site_directory="$repository_root/frontend/site-dist"
remote="$1"
ssh_options=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15)
metadata_file="$site_directory/downloads/latest.json"
integrity_manifest="$site_directory/SHA256SUMS"

if [[ ! $remote =~ ^[A-Za-z_][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
  echo "Remote must use the safe user@host form (no SSH options or paths)." >&2
  exit 2
fi

if [[ ! -f "$site_directory/index.html" || ! -f "$metadata_file" ||
      ! -f "$integrity_manifest" ]]; then
  echo "Run website/scripts/build-release-site.ps1 before deployment." >&2
  exit 1
fi

mapfile -t release_metadata < <(node -e '
  const release = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
  const products = {
    universal: "DroneDream-Universal",
    sim: "DroneDream-Sim",
    lab: "DroneDream-Lab",
    field: "DroneDream-Field",
    autonomy: "DroneDream-Agent",
  };
  const hasEdition = Object.hasOwn(release, "edition");
  const hasBuildNumber = Object.hasOwn(release, "buildNumber");
  if (hasEdition !== hasBuildNumber) process.exit(2);
  const expectedName = hasEdition
    ? `${products[release.edition] ?? ""}-${release.version}.exe`
    : `DroneDream_${release.version}_x64-setup.exe`;
  if (hasEdition && (!Object.hasOwn(products, release.edition) ||
      !Number.isSafeInteger(release.buildNumber) || release.buildNumber <= 0)) process.exit(2);
  if (release.fileName !== expectedName) process.exit(2);
  console.log(release.version, release.fileName, release.sha256);
' "$metadata_file" | tr ' ' '\n')

version="${release_metadata[0]:-}"
installer_name="${release_metadata[1]:-}"
expected_sha256="${release_metadata[2]:-}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
   [[ ! "$installer_name" =~ ^DroneDream[-_][A-Za-z0-9._-]+\.exe$ ]] ||
   [[ ! "$expected_sha256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "latest.json contains invalid release metadata." >&2
  exit 1
fi

# Reject a stale or partially generated local release before any network write.
(cd "$site_directory" && sha256sum --check SHA256SUMS)

release_id="${version}-$(date -u +%Y%m%dT%H%M%SZ)"
releases_root="/var/www/dronedream-releases"
upload_directory="$releases_root/${release_id}.uploading"
release_directory="$releases_root/$release_id"
current_link="/var/www/dronedream-current"

ssh "${ssh_options[@]}" "$remote" "set -eu; mkdir -p '$upload_directory'; if [ -e '$current_link' ] && [ ! -L '$current_link' ]; then echo '$current_link must be a symlink' >&2; exit 1; fi"
rsync -e "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15" \
  -az --delete --delay-updates \
  --exclude '.well-known/' \
  "$site_directory/" "$remote:$upload_directory/"

ssh "${ssh_options[@]}" "$remote" "set -eu; cd '$upload_directory'; sha256sum --check SHA256SUMS; actual=\$(sha256sum 'downloads/$installer_name' | awk '{print \$1}'); test \"\$actual\" = '$expected_sha256'; cd /; mv '$upload_directory' '$release_directory'; ln -sfn '$release_directory' '${current_link}.next'; mv -Tf '${current_link}.next' '$current_link'"

echo "Activated DroneDream $version at $remote:$release_directory"
