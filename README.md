<p align="center">
  <img src="docs/assets/drone-dream-icon.png" alt="DroneDream icon" width="220" />
</p>

<h1 align="center">🚁 DroneDream</h1>
<p align="center">Auto Drone Control Parameters Tuning Platform</p>

## 项目简介

DroneDream 是一个面向 PX4/Gazebo 的 Web 端无人机自动调参平台，支持多样化的仿真任务配置、高级赛道编辑、异步优化执行、实时 gazebo 窗口观测、 artifacts 管理、2D/3D Trajectory Replay 和 PDF 版报告导出。

## 核心能力

- `real_cli` 接入 PX4/Gazebo SITL。
- 启发式与 GPT 两类参数提议策略。
- noVNC/Gazebo GUI 可视化与回放。
- 产物下载与报告生成。

---

# DroneDream Runpod 完整操作流程

## 0. Pod 配置

端口：

```text
5173  frontend
8000  backend
6080  noVNC
8888  Runpod Jupyter Notebook
```

目录：

```text
/workspace/DroneDream
/workspace/PX4-Autopilot
/workspace/nodejs
/workspace/dd_artifacts
```

---

## 1. 安装 sudo 和系统依赖

PX4 的 `Tools/setup/ubuntu.sh` 会调用 `sudo`，所以必须先装。

```bash
cd /workspace

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  sudo git curl ca-certificates xz-utils lsof \
  build-essential pkg-config \
  xvfb x11vnc fluxbox novnc websockify \
  wmctrl xdotool x11-utils \
  x11-apps mesa-utils libgl1-mesa-dri libglx-mesa0 libegl1 libglu1-mesa \
  python3 python3-venv python3-pip python3-dev
```

确认：

```bash
which sudo
sudo --version | head -1
```

如果这一步没过，不要继续 PX4 setup。

---

## 2. 安装 Node

```bash
cd /workspace
rm -rf /workspace/nodejs
mkdir -p /workspace/nodejs
NODE_VERSION=22.12.0
curl -fSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
tar --no-same-owner -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" \
  -C /workspace/nodejs \
  --strip-components=1
cat > /workspace/load-node.sh <<'EOF'
export PATH=/workspace/nodejs/bin:$PATH
hash -r
EOF
source /workspace/load-node.sh
which node
which npm
node -v
npm -v
```

把它写进 shell 启动文件，避免新终端忘记 source：

```bash
grep -q "/workspace/load-node.sh" ~/.bashrc || echo 'source /workspace/load-node.sh' >> ~/.bashrc
source ~/.bashrc
```

---

## 3. 克隆代码

```bash
cd /workspace
git clone https://github.com/ChiZhang-805/DroneDream.git
git clone https://github.com/PX4/PX4-Autopilot.git
```

---

## 4. 安装 PX4 / Gazebo 依赖

现在已经有 `sudo`，可以跑 PX4 setup。

```bash
cd /workspace/PX4-Autopilot
DEBIAN_FRONTEND=noninteractive bash ./Tools/setup/ubuntu.sh
```

---

## 5. PX4 Python venv

```bash
cd /workspace/PX4-Autopilot
python3.11 -m venv .venv || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r Tools/setup/requirements.txt
pip install mavsdk pyulog
```

确认：

```bash
/workspace/PX4-Autopilot/.venv/bin/python - <<'PY'
import mavsdk
from pyulog import ULog
print("PX4 venv OK: mavsdk + pyulog")
PY
```

---

## 6. 安装 DroneDream backend / worker / frontend

### 6.1 Backend

```bash
cd /workspace/DroneDream
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip setuptools wheel
backend/.venv/bin/pip install -e "backend[dev]"
```

### 6.2 Worker

```bash
cd /workspace/DroneDream
python3.11 -m venv worker/.venv || python3 -m venv worker/.venv
worker/.venv/bin/pip install --upgrade pip setuptools wheel
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"
```

### 6.3 Frontend：必须先 source Node

```bash
source /workspace/load-node.sh
cd /workspace/DroneDream/frontend
which node
node -v
npm -v
rm -rf node_modules package-lock.json
npm install
npm run build
```

---

## 7. 写入 `.env`

下面脚本生成适合 Runpod 的 `.env`。默认：

- `SIMULATOR_BACKEND=real_cli`
- `optimizer_strategy=gpt` 在 UI/job 中选择
- `real_cli` 指向 `px4_gazebo_runner.py`
- 默认开启 noVNC/Gazebo GUI
- 默认真实 PX4/Gazebo：`PX4_GAZEBO_DRY_RUN=false`
- 如果你只想先验证协议，把 `PX4_GAZEBO_DRY_RUN=true`

替换你的 pod id：

```bash
POD_ID="你的pod-id"
```

例如：

```bash
POD_ID="iq4pfg76zr0jv3"
```

然后执行：

```bash
cd /workspace/DroneDream

POD_ID="0p552ixoodqm5y"
APP_SECRET="$(backend/.venv/bin/python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"

mkdir -p /workspace/dd_artifacts /workspace/DroneDream/.artifacts

cat > .env << EOF
# --- Backend ---
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
APP_ENV=development
DATABASE_URL=sqlite:////workspace/DroneDream/drone_dream.db
LOG_LEVEL=info
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://${POD_ID}-5173.proxy.runpod.net

# --- Worker ---
WORKER_POLL_INTERVAL_SECONDS=1.0
WORKER_LOG_LEVEL=info

# Force real_cli during debugging. For per-job UI selection, set blank.
SIMULATOR_BACKEND=real_cli

# --- real_cli adapter ---
REAL_SIMULATOR_COMMAND="/workspace/DroneDream/backend/.venv/bin/python /workspace/DroneDream/scripts/simulators/px4_gazebo_runner.py"
REAL_SIMULATOR_WORKDIR=/workspace/DroneDream
REAL_SIMULATOR_TIMEOUT_SECONDS=900
REAL_SIMULATOR_ARTIFACT_ROOT=/workspace/DroneDream/.artifacts
REAL_SIMULATOR_KEEP_RUN_DIRS=true
ARTIFACT_ROOT=/workspace/DroneDream/.artifacts

# --- PX4/Gazebo runner ---
PX4_GAZEBO_DRY_RUN=false
PX4_GAZEBO_LAUNCH_COMMAND="/workspace/PX4-Autopilot/.venv/bin/python /workspace/DroneDream/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}"
PX4_GAZEBO_WORKDIR=/workspace/DroneDream
PX4_GAZEBO_TIMEOUT_SECONDS=900
PX4_GAZEBO_HEADLESS=false
PX4_GAZEBO_KEEP_RAW_LOGS=true
PX4_GAZEBO_PASS_RMSE=0.75
PX4_GAZEBO_PASS_MAX_ERROR=2.0
PX4_GAZEBO_MIN_TRACK_COVERAGE=0.9
PX4_GAZEBO_VEHICLE=x500
PX4_GAZEBO_WORLD=default
PX4_GAZEBO_EXTRA_ARGS=
PX4_GAZEBO_TELEMETRY_FORMAT=json
PX4_GAZEBO_ALLOW_CSV_TELEMETRY=false

# --- local PX4 wrapper ---
PX4_AUTOPILOT_DIR=/workspace/PX4-Autopilot
PX4_SETUP_COMMANDS="source /workspace/PX4-Autopilot/.venv/bin/activate"
PX4_LAUNCH_COMMAND_TEMPLATE=
PX4_MAKE_TARGET=gz_x500
PX4_RUN_SECONDS=90
PX4_READY_TIMEOUT_SECONDS=30
PX4_SITE_DRY_RUN=false

# Telemetry: ULog mode is usually more realistic.
PX4_TELEMETRY_MODE=ulog
PX4_TELEMETRY_SOURCE_JSON=
PX4_ULOG_ROOT=/workspace/PX4-Autopilot/build/px4_sitl_default/rootfs/log
PX4_ULOG_PATH=

# Offboard executor.
PX4_ENABLE_OFFBOARD_EXECUTOR=true
PX4_OFFBOARD_EXECUTOR_COMMAND="/workspace/PX4-Autopilot/.venv/bin/python /workspace/DroneDream/scripts/simulators/px4_offboard_track_executor.py"
PX4_OFFBOARD_CONNECTION=udp://:14540
PX4_OFFBOARD_SETPOINT_RATE_HZ=10
PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS=30
PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS=120
PX4_OFFBOARD_LAND_AFTER=true
PX4_OFFBOARD_DRY_RUN=false

# --- noVNC / Gazebo GUI ---
DISPLAY=:99
GEOMETRY=1600x900x24
PX4_GAZEBO_VNC_DESKTOP_GEOMETRY=1600x900x24
PX4_GAZEBO_LAUNCH_GUI_CLIENT=true
PX4_GAZEBO_REQUIRE_GUI_CLIENT=false
PX4_GAZEBO_GUI_COMMAND=
PX4_GAZEBO_RAW_GUI_COMMAND="gz sim -g"
PX4_GAZEBO_GUI_WINDOW_TITLE="Gazebo Sim"
PX4_GAZEBO_GUI_WINDOW_MODE=fill
PX4_GAZEBO_GUI_WINDOW_GEOMETRY=fill
PX4_GAZEBO_GUI_WINDOW_WIDTH=1280
PX4_GAZEBO_GUI_WINDOW_HEIGHT=720
PX4_GAZEBO_GUI_WINDOW_DELAY_SECONDS=8
PX4_GAZEBO_GUI_WINDOW_RETRY_SECONDS=90
PX4_GAZEBO_GUI_WINDOW_ENFORCE_SECONDS=30

# Marker: enable after GUI works.
PX4_GAZEBO_DRAW_TRACK_MARKER=false
PX4_GAZEBO_TRACK_MARKER_COMMAND=
PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS=2
PX4_GAZEBO_REQUIRE_TRACK_MARKER=false
PX4_GAZEBO_TRACK_MARKER_Z_OFFSET=0.03
PX4_GAZEBO_TRACK_MARKER_COLOR="0 0.8 1 1"
PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH=0.08
PX4_GAZEBO_TRACK_MARKER_MODE=line_strip

LIBGL_ALWAYS_SOFTWARE=1
QT_X11_NO_MITSHM=1

# --- GPT ---
APP_SECRET_KEY=${APP_SECRET}
OPENAI_MODEL=gpt-4.1

# --- Frontend ---
VITE_API_BASE_URL="https://${POD_ID}-8000.proxy.runpod.net"
VITE_GAZEBO_VIEWER_URL="https://${POD_ID}-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=scale&view_clip=0"
EOF
```

检查：

```bash
grep -nE "SIMULATOR_BACKEND|REAL_SIMULATOR_COMMAND|PX4_GAZEBO_DRY_RUN|PX4_GAZEBO_HEADLESS|PX4_GAZEBO_LAUNCH_GUI_CLIENT|APP_SECRET_KEY|VITE_API_BASE_URL|VITE_GAZEBO_VIEWER_URL" .env
```

---

## 8. 写入 `frontend/.env.local`

```bash
cd /workspace/DroneDream

POD_ID="0p552ixoodqm5y"

cat > frontend/.env.local << EOF
VITE_API_BASE_URL=https://${POD_ID}-8000.proxy.runpod.net
VITE_GAZEBO_VIEWER_URL=https://${POD_ID}-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=scale&view_clip=0
EOF
```

---

## 9. Smoke test 1：real_cli dry-run

这一步不启动真实 PX4/Gazebo，只验证 `real_cli` 协议和 metrics 生成。

```bash
cd /workspace/DroneDream

TMP=/tmp/dd_real_cli_dryrun_smoke
rm -rf "$TMP"
mkdir -p "$TMP"

cat > "$TMP/trial_input.json" <<'JSON'
{
  "trial_id": "tri_dryrun_smoke",
  "job_id": "job_dryrun_smoke",
  "candidate_id": "cand_dryrun_smoke",
  "seed": 101,
  "scenario_type": "nominal",
  "scenario_config": {},
  "job_config": {
    "track_type": "circle",
    "start_point": {"x": 0.0, "y": 0.0},
    "altitude_m": 3.0,
    "reference_track": [],
    "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust"
  },
  "parameters": {
    "kp_xy": 1.0,
    "kd_xy": 0.2,
    "ki_xy": 0.05,
    "vel_limit": 5.0,
    "accel_limit": 4.0,
    "disturbance_rejection": 0.5
  },
  "output_path": "/tmp/dd_real_cli_dryrun_smoke/trial_result.json"
}
JSON

set -a
source .env
set +a

PX4_GAZEBO_DRY_RUN=true \
backend/.venv/bin/python scripts/simulators/px4_gazebo_runner.py \
  --input "$TMP/trial_input.json" \
  --output "$TMP/trial_result.json"

python3 -m json.tool "$TMP/trial_result.json"
```

期望：

```json
"success": true,
"metrics": {
  "rmse": ...
}
```

如果这一步失败，不要继续。先看：

```bash
cat "$TMP/trial_result.json"
```

---

## 10. Smoke test 2：真实 PX4/Gazebo

跑 DroneDream runner 真实模式：

```bash
cd /workspace/DroneDream

TMP=/tmp/dd_real_cli_real_smoke
rm -rf "$TMP"
mkdir -p "$TMP"

cp /tmp/dd_real_cli_dryrun_smoke/trial_input.json "$TMP/trial_input.json"

python3 - <<'PY'
from pathlib import Path
p = Path("/tmp/dd_real_cli_real_smoke/trial_input.json")
s = p.read_text()
s = s.replace("dryrun", "real")
s = s.replace("/tmp/dd_real_cli_dryrun_smoke/trial_result.json", "/tmp/dd_real_cli_real_smoke/trial_result.json")
p.write_text(s)
PY

set -a
source .env
set +a

backend/.venv/bin/python scripts/simulators/px4_gazebo_runner.py \
  --input "$TMP/trial_input.json" \
  --output "$TMP/trial_result.json"

python3 -m json.tool "$TMP/trial_result.json"
```

如果失败，检查：

```bash
cat "$TMP/trial_result.json"

find /workspace/DroneDream/.artifacts -type f \
  \( -name "stdout.log" -o -name "stderr.log" -o -name "runner.log" -o -name "offboard_executor.log" -o -name "gui_stdout.log" -o -name "gui_stderr.log" \) \
  | tail -30
```

---

## 11. 启动四端

### Terminal 1：noVNC

```bash
cd /workspace/DroneDream

pkill -f "websockify" || true
pkill -f "x11vnc" || true
pkill -f "Xvfb" || true
pkill -f "fluxbox" || true

rm -f /tmp/.X99-lock
rm -rf /tmp/.X11-unix/X99

export VNC_PASSWORD='temporary-pass'
export DISPLAY=:99
export GEOMETRY=1600x900x24

bash scripts/run-gazebo-vnc.sh
```

打开：

```text
https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=scale&view_clip=0
```

### Terminal 2：backend

```bash
cd /workspace/DroneDream
./scripts/dev-backend.sh
```

### Terminal 3：worker

```bash
cd /workspace/DroneDream
./scripts/dev-worker.sh
```

### Terminal 4：frontend

```bash
source /workspace/load-node.sh

cd /workspace/DroneDream/frontend

which node
node -v

npm run dev -- --host 0.0.0.0 --port 5173
```

---

## 12. Web 验证：先小规模，不要直接 GPT 大跑

### 12.1 real_cli + heuristic

```text
Simulator Backend: real_cli
Optimizer Strategy: heuristic
Track: circle
Altitude: 3
Wind: 0/0/0/0
Target RMSE: 0.75
```

### 12.2 real_cli + gpt

```text
Simulator Backend: real_cli
Optimizer Strategy: gpt
Max Iterations: 20
Trials per Candidate: 3
Target RMSE: 0.75
Min Pass Rate: 0.8
OpenAI Model: gpt-4.1
```

---

## 13. ECE498 Final Project

pipeline 包括：

- baseline with no tool
- tool-augmented pipeline
- self-refinement with tools

ECE498 页面跑：

```text
Run Baseline (No Tool)
Run Tool-Augmented (CMA-ES)
Run Tool + Refinement (CMA-ES Loop)
```
