#!/usr/bin/env bash
set -Eeuo pipefail

check=${1:-}
manifest=/opt/dronedream/runtime-manifest.json
venv=/opt/dronedream/venv
source_root=/opt/dronedream/source
engine_root=/opt/dronedream/engine/current
smoke_root=/var/lib/dronedream/runtime-smoke
mkdir -p "$smoke_root"

case "$check" in
  component_versions)
    "$venv/bin/python" "$source_root/runtime/tools/runtime_manifest.py" validate \
      --manifest "$manifest"
    test -x /opt/PX4-Autopilot/build/px4_sitl_default/bin/px4
    test -x /usr/bin/gz
    test -x /usr/local/bin/valkey-server
    test "$(git -C /opt/PX4-Autopilot rev-parse HEAD)" = \
      "$($venv/bin/python -c 'import json; print(json.load(open("/opt/dronedream/runtime-manifest.json"))["componentDetails"]["px4"]["commit"])')"
    gz sim --versions
    valkey-server --version
    "$venv/bin/pip" check
    ;;
  python_imports)
    PYTHONPATH="$engine_root/backend:$engine_root/worker" "$venv/bin/python" -c \
      'import app, cryptography, drone_dream_worker, mavsdk, pyulog, redis, sqlalchemy'
    ;;
  valkey_ping)
    for _ in $(seq 1 30); do
      if [[ "$(valkey-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null || true)" == PONG ]]; then
        exit 0
      fi
      sleep 1
    done
    echo "Valkey did not become ready" >&2
    exit 1
    ;;
  api_worker_heartbeat)
    for _ in $(seq 1 60); do
      if curl --fail --silent --show-error http://127.0.0.1:8000/health/ready \
        >"$smoke_root/health-ready.json"; then
        exit 0
      fi
      sleep 2
    done
    echo "API and worker did not become ready" >&2
    exit 1
    ;;
  account_session_api)
    "$venv/bin/python" - "$smoke_root/account-session-api.json" <<'PY'
import hashlib
import hmac
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

output = pathlib.Path(sys.argv[1])
values = {}
with open("/etc/dronedream/runtime.env", "r", encoding="utf-8") as source:
    for raw in source:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

with open("/opt/dronedream/runtime-manifest.json", "r", encoding="utf-8") as source:
    manifest = json.load(source)

runtime_id = values.get("DRONEDREAM_RUNTIME_ID", "")
secret = values.get("APP_SECRET_KEY", "")
if runtime_id != manifest.get("runtimeId") or len(secret.encode("utf-8")) < 32:
    raise SystemExit("Runtime bridge identity is unavailable")

method = "GET"
path = "/api/v1/session"
session_id = str(uuid.uuid4())
nonce = str(uuid.uuid4())
timestamp = str(int(time.time()))
body_sha256 = hashlib.sha256(b"").hexdigest()
authorization_sha256 = hashlib.sha256(b"").hexdigest()
derived_key = hmac.new(
    secret.encode("utf-8"),
    b"dronedream-desktop-bridge-v2",
    hashlib.sha256,
).digest()
canonical = "\n".join(
    (
        "DD-BRIDGE-V2",
        runtime_id,
        session_id,
        timestamp,
        nonce,
        method,
        path,
        body_sha256,
        authorization_sha256,
        "",
        "",
    )
).encode("utf-8")
signature = hmac.new(derived_key, canonical, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8000" + path,
    method=method,
    headers={
        "Accept": "application/json",
        "X-DroneDream-Bridge-Version": "DD-BRIDGE-V2",
        "X-DroneDream-Runtime-Id": runtime_id,
        "X-DroneDream-Session-Id": session_id,
        "X-DroneDream-Timestamp": timestamp,
        "X-DroneDream-Nonce": nonce,
        "X-DroneDream-Body-Sha256": body_sha256,
        "X-DroneDream-Signature": signature,
    },
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status = response.status
        body = response.read(16_385)
except urllib.error.HTTPError as error:
    status = error.code
    body = error.read(16_385)

if len(body) > 16_384:
    raise SystemExit("Account-session response exceeded the smoke limit")
try:
    payload = json.loads(body)
except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit("Account-session response was not JSON") from error
if (
    status != 401
    or payload.get("success") is not False
    or not isinstance(payload.get("error"), dict)
    or payload["error"].get("code") != "UNAUTHORIZED"
):
    raise SystemExit("Signed account-session route contract is unavailable")

# Keep only non-sensitive proof. The bridge key, signatures, and nonces never
# leave this process or enter smoke evidence.
output.write_text(
    json.dumps({"path": path, "status": status, "errorCode": "UNAUTHORIZED"}),
    encoding="utf-8",
)
PY
    ;;
  real_cli_dry_run)
    "$venv/bin/python" - "$smoke_root" <<'PY'
import json
import os
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
payload = {
    "trial_id": "runtime-smoke-trial",
    "job_id": "runtime-smoke-job",
    "candidate_id": "runtime-smoke-candidate",
    "seed": 42,
    "attempt_count": 1,
    "execution_identity": {
        "trial_id": "runtime-smoke-trial",
        "job_id": "runtime-smoke-job",
        "candidate_id": "runtime-smoke-candidate",
        "seed": 42,
        "attempt_count": 1,
    },
    "scenario_type": "nominal",
    "scenario_config": {},
    "job_config": {
        "track_type": "circle",
        "start_point": {"x": 0.0, "y": 0.0},
        "altitude_m": 3.0,
        "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
        "sensor_noise_level": "medium",
        "objective_profile": "robust",
    },
    "parameters": {
        "kp_xy": 1.0,
        "kd_xy": 0.2,
        "ki_xy": 0.05,
        "vel_limit": 5.0,
        "accel_limit": 4.0,
        "disturbance_rejection": 0.5,
    },
    "output_path": str(root / "dry-run-output.json"),
}
input_path = root / "dry-run-input.json"
input_path.write_text(json.dumps(payload), encoding="utf-8")
environment = os.environ.copy()
environment["PX4_GAZEBO_DRY_RUN"] = "true"
result = subprocess.run(
    [
        "/opt/dronedream/venv/bin/python",
        "/opt/dronedream/engine/current/scripts/simulators/px4_gazebo_runner.py",
        "--input",
        str(input_path),
        "--output",
        payload["output_path"],
    ],
    check=False,
    env=environment,
)
output = json.loads(pathlib.Path(payload["output_path"]).read_text(encoding="utf-8"))
if result.returncode or output.get("success") is not True:
    raise SystemExit("real_cli dry-run did not produce a successful result")
PY
    ;;
  px4_gazebo_headless)
    "$venv/bin/python" /usr/lib/dronedream/px4-gazebo-smoke.py
    ;;
  parameter_readback)
    "$venv/bin/python" - "$smoke_root/parameter-readback.json" <<'PY'
import json
import math
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("parameter") != "MPC_XY_P":
    raise SystemExit("unexpected PX4 parameter readback marker")
if not all(
    math.isfinite(float(payload[key]))
    for key in ("original", "written", "readBack", "restored")
):
    raise SystemExit("non-finite PX4 parameter value")
if not 0.0 <= float(payload["written"]) <= 2.0:
    raise SystemExit("PX4 smoke value is outside the safe [0, 2] range")
if math.isclose(float(payload["original"]), float(payload["written"]), abs_tol=1e-6):
    raise SystemExit("PX4 smoke did not use a distinct parameter value")
if abs(float(payload["written"]) - float(payload["readBack"])) > 1e-4:
    raise SystemExit("PX4 parameter write/readback mismatch")
if abs(float(payload["original"]) - float(payload["restored"])) > 1e-4:
    raise SystemExit("PX4 parameter restore mismatch")
PY
    ;;
  *)
    echo "usage: $0 {component_versions|python_imports|valkey_ping|api_worker_heartbeat|account_session_api|real_cli_dry_run|px4_gazebo_headless|parameter_readback}" >&2
    exit 2
    ;;
esac
