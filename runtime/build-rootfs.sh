#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "$root/runtime/pins.env"
image=${IMAGE:-"dronedream/runtime:${DRONEDREAM_RUNTIME_VERSION}"}
supabase_url=${VITE_SUPABASE_URL:-}

command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }
[[ "$supabase_url" == https://* ]] || {
    echo "VITE_SUPABASE_URL must be a public HTTPS project URL" >&2
    exit 2
}
oidc_issuer="${supabase_url%/}/auth/v1"
oidc_jwks_url="${supabase_url%/}/auth/v1/.well-known/jwks.json"
model_gateway_base_url="${supabase_url%/}/functions/v1/model-gateway"
if [[ -n "$(git -C "$root" status --porcelain=v1 --untracked-files=all)" ]]; then
    echo "refusing to build a release from a dirty worktree (including untracked files)" >&2
    exit 2
fi
source_commit=$(git -C "$root" rev-parse --verify HEAD)
source_date_epoch=$(git -C "$root" show -s --format=%ct "$source_commit")
python3 "$root/runtime/tools/runtime_manifest.py" validate-config \
  --pins "$root/runtime/pins.env" \
  --python-lock "$root/runtime/locks/python-requirements.lock"

docker buildx build --load --platform linux/amd64 --provenance=false \
  --file "$root/runtime/Dockerfile" \
  --tag "$image" \
  --build-arg "UBUNTU_BASE_IMAGE=$UBUNTU_BASE_IMAGE" \
  --build-arg "DRONEDREAM_SOURCE_COMMIT=$source_commit" \
  --build-arg "DRONEDREAM_SOURCE_DATE_EPOCH=$source_date_epoch" \
  --build-arg "PX4_VERSION=$PX4_VERSION" \
  --build-arg "PX4_GIT_URL=$PX4_GIT_URL" \
  --build-arg "PX4_GIT_COMMIT=$PX4_GIT_COMMIT" \
  --build-arg "GAZEBO_METAPACKAGE=$GAZEBO_METAPACKAGE" \
  --build-arg "GAZEBO_METAPACKAGE_VERSION=$GAZEBO_METAPACKAGE_VERSION" \
  --build-arg "GAZEBO_APT_KEY_URL=$GAZEBO_APT_KEY_URL" \
  --build-arg "GAZEBO_APT_KEY_SHA256=$GAZEBO_APT_KEY_SHA256" \
  --build-arg "VALKEY_VERSION=$VALKEY_VERSION" \
  --build-arg "VALKEY_GIT_URL=$VALKEY_GIT_URL" \
  --build-arg "VALKEY_GIT_COMMIT=$VALKEY_GIT_COMMIT" \
  --build-arg "PYTHON_VERSION=$PYTHON_VERSION" \
  --build-arg "BACKEND_VERSION=$BACKEND_VERSION" \
  --build-arg "WORKER_VERSION=$WORKER_VERSION" \
  --build-arg "MAVSDK_VERSION=$MAVSDK_VERSION" \
  --build-arg "PYULOG_VERSION=$PYULOG_VERSION" \
  --build-arg "OIDC_ISSUER=$oidc_issuer" \
  --build-arg "OIDC_JWKS_URL=$oidc_jwks_url" \
  --build-arg "MODEL_GATEWAY_BASE_URL=$model_gateway_base_url" \
  "$root"

echo "built $image from $source_commit"
