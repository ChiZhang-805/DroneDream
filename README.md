<p align="center">
  <img src="docs/assets/drone-dream-icon.png" alt="DroneDream icon" width="220" />
</p>

<h1 align="center">🚁 DroneDream Local Version</h1>

<p align="center">
  Local PX4/Gazebo + noVNC + DroneDream web platform for automatic drone parameter tuning.
</p>

---

## 1. What this branch is

`Local_Version` is the local self-hosted version of DroneDream.

It is designed for running DroneDream on a local Ubuntu machine with:

- real PX4/Gazebo SITL;
- Gazebo GUI visible in the browser through noVNC;
- Docker Compose services for frontend, backend, worker, and Postgres;
- `real_cli` meaning real PX4/Gazebo, not dry-run;
- `mock` still available for quick deterministic testing.

The main website runs at:

```text
http://localhost:8080
```

The Gazebo/noVNC viewer runs at:

```text
http://localhost:8080/gazebo/vnc.html?path=gazebo/websockify&resize=scale
```

---

## 2. Required environment

Recommended host system:

```text
Ubuntu 22.04 or Ubuntu 24.04
Docker Engine + Docker Compose plugin
Git
Internet connection
Enough disk space for PX4, Docker images, and Gazebo
```

This local version expects the following directory layout:

```text
~/workspace/DroneDream
~/PX4-Autopilot
```

Do **not** put `PX4-Autopilot` inside the DroneDream repository.

---

## 3. Install Docker

Check whether Docker is already available:

```bash
docker --version
docker compose version
```

If either command fails, install Docker Engine and the Docker Compose plugin for Ubuntu. After installation, allow your user to run Docker:

```bash
sudo usermod -aG docker "$USER"
newgrp docker

docker run hello-world
docker compose version
```

---

## 4. Clone DroneDream Local Version

Fresh clone:

```bash
mkdir -p ~/workspace
cd ~/workspace

git clone -b Local_Version https://github.com/ChiZhang-805/DroneDream.git
cd DroneDream
```

If you already cloned the repo:

```bash
cd ~/workspace/DroneDream

git fetch origin
git switch Local_Version
git pull origin Local_Version
```

Confirm:

```bash
git branch --show-current
```

Expected:

```text
Local_Version
```

---

## 5. Clone PX4-Autopilot

Clone PX4 with submodules:

```bash
cd ~

git clone https://github.com/PX4/PX4-Autopilot.git --recursive
```

If the repository already exists, restore submodules:

```bash
cd ~/PX4-Autopilot

git submodule sync --recursive
git submodule update --init --recursive --jobs 4
```

Confirm:

```bash
ls ~/PX4-Autopilot
git -C ~/PX4-Autopilot rev-parse --verify HEAD
```

---

## 6. Install PX4 host dependencies

Run PX4's Ubuntu setup script on the host:

```bash
cd ~

bash ./PX4-Autopilot/Tools/setup/ubuntu.sh
```

After it finishes, reboot:

```bash
sudo reboot
```

After reboot, optionally verify PX4 manually on the host:

```bash
cd ~/PX4-Autopilot

make px4_sitl gz_x500
```

If Gazebo opens, stop it with:

```text
Ctrl+C
```

Important:

```text
Do not run `make distclean` during DroneDream setup.
```

If you need to clean the PX4 build cache, use:

```bash
sudo chown -R "$USER:$USER" ~/PX4-Autopilot
rm -rf ~/PX4-Autopilot/build/px4_sitl_default*
```

If you already ran `make distclean`, recover with:

```bash
cd ~/PX4-Autopilot

git submodule sync --recursive
git submodule update --init --recursive --jobs 4
```

---

## 7. Initialize DroneDream environment

Create the Hosted B local `.env` file:

```bash
cd ~/workspace/DroneDream

scripts/hosted-b/init-env.sh
```

Then configure it for strict real PX4/Gazebo mode:

```bash
cd ~/workspace/DroneDream

python3 - <<'PY'
from pathlib import Path
import secrets

env_path = Path("deploy/hosted-b/.env")
if not env_path.exists():
    raise SystemExit("Missing deploy/hosted-b/.env. Run scripts/hosted-b/init-env.sh first.")

updates = {
    "HOSTED_REAL_CLI_REQUIRES_PX4": "true",
    "SIMULATOR_BACKEND": "",
    "REAL_SIMULATOR_COMMAND": "python scripts/simulators/px4_gazebo_runner.py",
    "REAL_SIMULATOR_WORKDIR": "/app",
    "REAL_SIMULATOR_TIMEOUT_SECONDS": "900",
    "REAL_SIMULATOR_ARTIFACT_ROOT": "/artifacts",
    "REAL_SIMULATOR_KEEP_RUN_DIRS": "true",
    "PX4_GAZEBO_DRY_RUN": "false",
    "PX4_GAZEBO_HEADLESS": "false",
    "PX4_AUTOPILOT_HOST_DIR": str(Path.home() / "PX4-Autopilot"),
    "PX4_AUTOPILOT_DIR": "/opt/PX4-Autopilot",
    "PX4_GAZEBO_LAUNCH_COMMAND": "python3 /app/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}",
    "PX4_MAKE_TARGET": "gz_x500",
    "PX4_RUN_SECONDS": "90",
    "PX4_TELEMETRY_MODE": "ulog",
    "PX4_ULOG_ROOT": "/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log",
    "VITE_GAZEBO_VIEWER_URL": "/gazebo/vnc.html?path=gazebo/websockify&resize=scale",
    "NOVNC_PORT": "6080",
    "VNC_PORT": "5900",
    "DISPLAY": ":99",
    "PX4_GAZEBO_DISPLAY": ":99",
}

lines = env_path.read_text().splitlines()
seen = set()
out = []

for line in lines:
    if "=" not in line or line.strip().startswith("#"):
        out.append(line)
        continue

    key, value = line.split("=", 1)
    key = key.strip()

    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    elif key == "VNC_PASSWORD":
        if value.strip():
            out.append(line)
        else:
            out.append(f"VNC_PASSWORD=dronedream-vnc-{secrets.token_urlsafe(12)}")
        seen.add(key)
    else:
        out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

if "VNC_PASSWORD" not in seen:
    out.append(f"VNC_PASSWORD=dronedream-vnc-{secrets.token_urlsafe(12)}")

env_path.write_text("\n".join(out) + "\n")
print("Updated", env_path)
PY
```

Check important values:

```bash
grep -E "HOSTED_REAL_CLI_REQUIRES_PX4|SIMULATOR_BACKEND=|PX4_GAZEBO_DRY_RUN|PX4_GAZEBO_HEADLESS|PX4_AUTOPILOT_HOST_DIR|PX4_AUTOPILOT_DIR|PX4_GAZEBO_LAUNCH_COMMAND|PX4_TELEMETRY_MODE|VNC_PASSWORD|VITE_GAZEBO_VIEWER_URL|PX4_GAZEBO_DISPLAY" deploy/hosted-b/.env
```

Expected important values:

```text
HOSTED_REAL_CLI_REQUIRES_PX4=true
PX4_GAZEBO_DRY_RUN=false
PX4_GAZEBO_HEADLESS=false
PX4_AUTOPILOT_HOST_DIR=/home/<your-user>/PX4-Autopilot
PX4_AUTOPILOT_DIR=/opt/PX4-Autopilot
VITE_GAZEBO_VIEWER_URL=/gazebo/vnc.html?path=gazebo/websockify&resize=scale
```

Never commit:

```text
deploy/hosted-b/.env
```

It contains local paths, generated tokens, and the VNC password.

---

## 8. Preflight check

Run:

```bash
cd ~/workspace/DroneDream

scripts/hosted-b/check-real-px4-config.sh
```

Expected:

```text
HOSTED_REAL_CLI_REQUIRES_PX4=true
PX4_GAZEBO_DRY_RUN=false
PX4_GAZEBO_LAUNCH_COMMAND=configured
PX4_AUTOPILOT_HOST_DIR=/home/<your-user>/PX4-Autopilot
PX4_AUTOPILOT_DIR=/opt/PX4-Autopilot
```

If it says `PX4_AUTOPILOT_HOST_DIR does not exist`, fix the path in:

```text
deploy/hosted-b/.env
```

---

## 9. Build and start DroneDream

Start the real PX4/Gazebo profile:

```bash
cd ~/workspace/DroneDream

scripts/hosted-b/up-real-px4.sh
```

The first build can take a long time because the worker image includes noVNC, Gazebo runtime dependencies, and PX4-related Python packages.

Check running services:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 ps
```

Expected services:

```text
postgres
backend
web
worker-real-px4-vnc
```

Check worker logs:

```bash
docker compose --env-file .env --profile real-px4 logs worker-real-px4-vnc --tail=120
```

Expected signals:

```text
noVNC listening on 0.0.0.0:6080
drone-dream-worker ... starting
```

---

## 10. Open the website and noVNC

Open DroneDream:

```text
http://localhost:8080
```

Find the demo token:

```bash
grep '^DRONEDREAM_DEMO_TOKEN=' ~/workspace/DroneDream/deploy/hosted-b/.env
```

Paste that token into the top-right access-token field in the web app.

Open noVNC directly:

```text
http://localhost:8080/gazebo/vnc.html?path=gazebo/websockify&resize=scale
```

Find the VNC password:

```bash
grep '^VNC_PASSWORD=' ~/workspace/DroneDream/deploy/hosted-b/.env
```

Use the explicit `path=gazebo/websockify` URL. Without it, the noVNC page may load but fail to connect.

---

## 11. Manual PX4/Gazebo validation inside the worker container

Before submitting a DroneDream job, validate that PX4/Gazebo can start inside the same worker container.

Open a shell:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 exec worker-real-px4-vnc bash
```

Inside the container:

```bash
git config --global --add safe.directory '*'

export PATH="/opt/venv/bin:$PATH"
export DISPLAY="${DISPLAY:-:99}"

python - <<'PY'
import genmsg
import kconfiglib
print("genmsg OK:", genmsg.__file__)
print("kconfiglib OK:", kconfiglib.__file__)
PY

echo "DISPLAY=$DISPLAY"
echo "PX4_AUTOPILOT_DIR=$PX4_AUTOPILOT_DIR"

cd "$PX4_AUTOPILOT_DIR"

rm -rf build/px4_sitl_default*

make px4_sitl gz_x500
```

If successful, Gazebo should appear in the noVNC desktop.

Stop the manual PX4/Gazebo run with:

```text
Ctrl+C
```

Do this before submitting a DroneDream web job, otherwise manual PX4/Gazebo and the worker job may compete for ports.

---

## 12. Gazebo window sizing

The real PX4/Gazebo worker includes a helper that maximizes Gazebo windows inside the noVNC desktop.

If Gazebo opens but does not fill the noVNC window, run this from the host:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 exec worker-real-px4-vnc bash -lc '
apt-get update >/dev/null
apt-get install -y wmctrl xdotool x11-utils >/dev/null

export DISPLAY="${DISPLAY:-:99}"

read W H < <(xdpyinfo | awk "/dimensions:/ {split(\$2,a,\"x\"); print a[1], a[2]; exit}")
echo "Desktop size: ${W}x${H}"

wmctrl -l || true

for id in $(xdotool search --name "Gazebo" 2>/dev/null); do
  echo "Maximizing Gazebo window id=$id"
  xdotool windowactivate "$id" || true
  xdotool windowmove "$id" 0 0 || true
  xdotool windowsize "$id" "$W" "$H" || true
  wmctrl -ir "$id" -b add,maximized_vert,maximized_horz || true
done
'
```

---

## 13. Submit a DroneDream job

In the web UI:

```text
New Job
```

Start with this minimal real test:

```text
Simulator Backend: real_cli
Optimizer Strategy: heuristic
Track: circle
Altitude: 3
Wind: 0 / 0 / 0 / 0
Max iterations: 1 or low value
Trials per candidate: 1
```

Do not start with GPT. GPT may fail because of OpenAI rate limits or missing API key, which can hide PX4/Gazebo problems.

Expected behavior:

- job enters `RUNNING`;
- worker launches PX4/Gazebo;
- Gazebo appears in noVNC;
- trials take noticeably longer than mock or dry-run;
- artifacts/logs are created under the hosted artifact volume.

---

## 14. Logs and diagnostics

Container status:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 ps
```

Worker logs:

```bash
docker compose --env-file .env --profile real-px4 logs worker-real-px4-vnc --tail=300
```

Backend logs:

```bash
docker compose --env-file .env --profile real-px4 logs backend --tail=120
```

Find runner logs:

```bash
docker compose --env-file .env --profile real-px4 exec worker-real-px4-vnc bash -lc '
find /artifacts/jobs -type f \( -name "runner.log" -o -name "stdout.log" -o -name "stderr.log" -o -name "trial_result.json" \) | sort | tail -50
'
```

Runtime endpoint:

```bash
cd ~/workspace/DroneDream

TOKEN="$(grep '^DRONEDREAM_DEMO_TOKEN=' deploy/hosted-b/.env | cut -d= -f2-)"

curl -s \
  -H "Authorization: Bearer ${TOKEN}" \
  http://localhost:8080/api/v1/runtime | python3 -m json.tool
```

You want:

```json
"hosted_real_cli_requires_px4": true,
"px4_gazebo_dry_run": false,
"px4_gazebo_headless": false,
"real_mode_config_complete": true
```

---

## 15. Stop DroneDream

Stop the hosted stack:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 down
```

If you want to remove database and artifact volumes:

```bash
docker compose --env-file .env --profile real-px4 down -v
```

Use `down -v` carefully. It deletes persisted database/artifact volumes.

---

## 16. Troubleshooting

### `docker: command not found`

Install Docker Engine and Docker Compose plugin, then check:

```bash
docker --version
docker compose version
```

### `~/PX4-Autopilot does not exist`

Clone PX4:

```bash
cd ~
git clone https://github.com/PX4/PX4-Autopilot.git --recursive
```

### PX4 submodule errors

Run:

```bash
cd ~/PX4-Autopilot

git submodule sync --recursive
git submodule update --init --recursive --jobs 4
```

### Permission denied when deleting PX4 build files

This happens when the container root user wrote files into the mounted PX4 directory.

Fix on the host:

```bash
sudo chown -R "$USER:$USER" ~/PX4-Autopilot
rm -rf ~/PX4-Autopilot/build/px4_sitl_default*
```

### CMake cache path mismatch

Example:

```text
CMakeCache.txt directory /opt/PX4-Autopilot/... is different than /home/...
```

Fix:

```bash
sudo chown -R "$USER:$USER" ~/PX4-Autopilot
rm -rf ~/PX4-Autopilot/build/px4_sitl_default*
```

Then rebuild inside the container.

### `ninja: error: unknown target 'gz_x500'`

Usually Gazebo/GZ dependencies were not found, or the wrong worker image was built.

Check that you are using the real profile:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 ps
```

Check inside the container:

```bash
which gz
gz sim --versions
```

### `No module named genmsg`

The PX4 Python requirements are missing in the container.

Inside the worker container:

```bash
export PATH="/opt/venv/bin:$PATH"
python -m pip install -r /opt/PX4-Autopilot/Tools/setup/requirements.txt
python -m pip install pyros-genmsg catkin_pkg rospkg
```

Then retry:

```bash
cd /opt/PX4-Autopilot
rm -rf build/px4_sitl_default*
make px4_sitl gz_x500
```

### `kconfiglib is not installed` or `No module named menuconfig`

Inside the worker container:

```bash
export PATH="/opt/venv/bin:$PATH"
python -m pip install kconfiglib
```

Then retry:

```bash
cd /opt/PX4-Autopilot
rm -rf build/px4_sitl_default*
make px4_sitl gz_x500
```

### noVNC shows `502 Bad Gateway`

Use the explicit websocket path:

```text
http://localhost:8080/gazebo/vnc.html?path=gazebo/websockify&resize=scale
```

Then check worker logs:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 logs worker-real-px4-vnc --tail=200
```

### noVNC page opens but says it cannot connect

Check VNC processes inside the worker:

```bash
cd ~/workspace/DroneDream/deploy/hosted-b

docker compose --env-file .env --profile real-px4 exec worker-real-px4-vnc bash -lc '
echo "DISPLAY=$DISPLAY"
ps aux | grep -E "Xvfb|x11vnc|fluxbox|websockify" | grep -v grep || true
curl -I http://127.0.0.1:6080/vnc.html || true
'
```

### Gazebo opens but window is small

Use the maximize command in Section 12.

---

## 17. Developer notes

Do not commit:

```text
deploy/hosted-b/.env
```

Do not use `make distclean` during this setup unless you are prepared to restore all submodules.

Do not run both workers at the same time:

```text
worker
worker-real-px4-vnc
```

For true PX4/Gazebo, use:

```bash
scripts/hosted-b/up-real-px4.sh
```

For mock/dev checks only, use the normal hosted stack with `HOSTED_REAL_CLI_REQUIRES_PX4=false`.

---

## License

This project is licensed under the MIT License. See `LICENSE` for details.
