# DroneDream Runpod 操作流程（默认开启 Gazebo GUI、noVNC、地面赛道 marker、Trajectory replay、PDF）

> 适用场景：Runpod 上从零启动 DroneDream，并默认开启完整可视化链路：PX4/Gazebo 真实仿真、noVNC 网页窗口、Gazebo GUI 自动打开、地面参考赛道 marker、前端 Trajectory replay、Artifacts、PDF 报告下载。  
> 推荐流程：先跑 `real_cli + heuristic` 小任务验证 GUI 与 marker，再跑 `real_cli + GPT`。

---

## 0. Runpod Pod 配置

建议在创建 Pod 时一次性暴露端口，避免后续 Edit Pod 导致 reset。

```text
Network volume mount path: /workspace
Network volume size: 200GB 推荐，100GB 是下限
Container disk: 50GB+
HTTP ports: 8888,5173,8000,6080
Image: Ubuntu 22.04 / PyTorch CUDA devel 类镜像，例如 runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
```

端口含义：

```text
5173  Vite frontend
8000  FastAPI backend
6080  noVNC / Gazebo live view
8888  optional notebook / debugging
```

---

## 1. 初始化目录与基础检查

```bash
cd /workspace
mkdir -p /workspace/tmp /workspace/dd_artifacts /workspace/logs
export TMPDIR=/workspace/tmp

df -h /workspace
free -h
nproc
python3 --version
git --version
```

---

## 2. 克隆最新代码

```bash
cd /workspace

git clone https://github.com/ChiZhang-805/DroneDream.git
git clone https://github.com/PX4/PX4-Autopilot.git
```

如果目录已存在：

```bash
cd /workspace/DroneDream
git checkout main
git pull origin main

cd /workspace/PX4-Autopilot
git pull
```

检查关键文件：

```bash
cd /workspace/DroneDream
git rev-parse --short HEAD

test -f scripts/simulators/px4_gazebo_runner.py && echo "px4_gazebo_runner.py OK"
test -f scripts/simulators/local_px4_launch_wrapper.py && echo "local_px4_launch_wrapper.py OK"
test -f scripts/simulators/px4_offboard_track_executor.py && echo "px4_offboard_track_executor.py OK"
test -f scripts/simulators/gazebo_track_marker.py && echo "gazebo_track_marker.py OK"
test -f scripts/run-gazebo-vnc.sh && echo "run-gazebo-vnc.sh OK"
test -f backend/app/services/pdf_report.py && echo "PDF service OK"
test -f backend/app/routers/artifacts.py && echo "artifact download router OK"
test -f frontend/src/components/TrajectoryReplay.tsx && echo "TrajectoryReplay OK"
test -f frontend/src/components/GazeboLivePanel.tsx && echo "GazeboLivePanel OK"
```

---

## 3. 安装系统依赖

基础依赖：

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y sudo curl xz-utils lsof \
  xvfb x11vnc fluxbox novnc websockify \
  wmctrl xdotool \
  x11-apps mesa-utils libgl1-mesa-dri libglx-mesa0 libegl1 libglu1-mesa
```

PX4/Gazebo 依赖：

```bash
cd /workspace/PX4-Autopilot
DEBIAN_FRONTEND=noninteractive bash ./Tools/setup/ubuntu.sh
echo $?
```

如果出现 `/dev/mem: No such file or directory`，通常不是致命错误；关键看退出码是否为 `0`。

---

## 4. PX4 Python venv

```bash
cd /workspace/PX4-Autopilot
python3.11 -m venv .venv || python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -r Tools/setup/requirements.txt
pip install mavsdk
```

验证：

```bash
cd /workspace/PX4-Autopilot
source .venv/bin/activate

python - <<'PY'
from pyulog import ULog
import mavsdk
print("PX4 venv OK")
PY
```

---

## 5. DroneDream backend / worker venv

Backend：

```bash
cd /workspace/DroneDream
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip setuptools wheel
backend/.venv/bin/pip install -e "backend[dev]"
```

Worker：

```bash
cd /workspace/DroneDream
python3.11 -m venv worker/.venv || python3 -m venv worker/.venv
worker/.venv/bin/pip install --upgrade pip setuptools wheel
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"
```

验证：

```bash
cd /workspace/DroneDream
backend/.venv/bin/python - <<'PY'
from cryptography.fernet import Fernet
import fastapi
import sqlalchemy
print("backend venv OK")
PY

worker/.venv/bin/python - <<'PY'
import drone_dream_worker
print("worker venv OK")
PY
```

---

## 6. 安装 Node 到 `/workspace/nodejs`

```bash
cd /workspace
rm -rf /workspace/nodejs
mkdir -p /workspace/nodejs

NODE_VERSION=20.20.2
curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"

tar --no-same-owner -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" \
  -C /workspace/nodejs \
  --strip-components=1

cat > /workspace/load-node.sh <<'EOF'
export PATH=/workspace/nodejs/bin:$PATH
EOF

source /workspace/load-node.sh
node -v
npm -v

cd /workspace/DroneDream/frontend
npm install
```

---

## 7. 写入 `.env`（默认开启 Gazebo GUI、marker、PDF、replay 支持）

先复制模板：

```bash
cd /workspace/DroneDream
test -f .env || cp .env.example .env
```

写入 Runpod 配置：

```bash
cd /workspace/DroneDream

backend/.venv/bin/python - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet

p = Path('.env')
text = p.read_text(encoding='utf-8')

updates = {
    'BACKEND_HOST': '0.0.0.0',
    'BACKEND_PORT': '8000',
    'DATABASE_URL': 'sqlite:////workspace/DroneDream/drone_dream.db',
    'CORS_ORIGINS': 'http://localhost:5173',
    'SIMULATOR_BACKEND': '',
    'REAL_SIMULATOR_COMMAND': '"/workspace/DroneDream/backend/.venv/bin/python /workspace/DroneDream/scripts/simulators/px4_gazebo_runner.py"',
    'REAL_SIMULATOR_ARTIFACT_ROOT': '/workspace/dd_artifacts',
    'ARTIFACT_ROOT': '/workspace/dd_artifacts',
    'REAL_SIMULATOR_TIMEOUT_SECONDS': '900',
    'REAL_SIMULATOR_KEEP_RUN_DIRS': 'true',
    'PX4_GAZEBO_DRY_RUN': 'false',
    'PX4_GAZEBO_LAUNCH_COMMAND': '"/workspace/PX4-Autopilot/.venv/bin/python /workspace/DroneDream/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}"',
    'PX4_GAZEBO_TIMEOUT_SECONDS': '900',
    'PX4_GAZEBO_HEADLESS': 'false',
    'PX4_GAZEBO_KEEP_RAW_LOGS': 'true',
    'PX4_GAZEBO_VEHICLE': 'x500',
    'PX4_GAZEBO_WORLD': 'default',
    'PX4_SITE_DRY_RUN': 'false',
    'PX4_AUTOPILOT_DIR': '/workspace/PX4-Autopilot',
    'PX4_SETUP_COMMANDS': '"source /workspace/PX4-Autopilot/.venv/bin/activate"',
    'PX4_MAKE_TARGET': 'gz_x500',
    'PX4_RUN_SECONDS': '90',
    'PX4_READY_TIMEOUT_SECONDS': '30',
    'PX4_TELEMETRY_MODE': 'ulog',
    'PX4_ULOG_ROOT': '/workspace/PX4-Autopilot/build/px4_sitl_default/rootfs/log',
    'PX4_ULOG_PATH': '',
    'PX4_ENABLE_OFFBOARD_EXECUTOR': 'true',
    'PX4_OFFBOARD_EXECUTOR_COMMAND': '"/workspace/PX4-Autopilot/.venv/bin/python /workspace/DroneDream/scripts/simulators/px4_offboard_track_executor.py"',
    'PX4_OFFBOARD_CONNECTION': 'udp://:14540',
    'PX4_OFFBOARD_SETPOINT_RATE_HZ': '10',
    'PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS': '30',
    'PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS': '120',
    'PX4_OFFBOARD_LAND_AFTER': 'true',
    'PX4_OFFBOARD_DRY_RUN': 'false',
    'PX4_GAZEBO_EVAL_ALTITUDE_FRACTION': '0.9',
    'PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M': '1.5',
    'PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES': '5',
    'PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION': '0.5',
    'DISPLAY': ':99',
    'PX4_GAZEBO_LAUNCH_GUI_CLIENT': 'true',
    'PX4_GAZEBO_GUI_COMMAND': '"gz sim -g"',
    'PX4_GAZEBO_GUI_START_DELAY_SECONDS': '5',
    'PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS': '15',
    'PX4_GAZEBO_REQUIRE_GUI_CLIENT': 'false',
    'LIBGL_ALWAYS_SOFTWARE': '1',
    'QT_X11_NO_MITSHM': '1',
    'PX4_GAZEBO_DRAW_TRACK_MARKER': 'true',
    'PX4_GAZEBO_TRACK_MARKER_COMMAND': '',
    'PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS': '2',
    'PX4_GAZEBO_REQUIRE_TRACK_MARKER': 'false',
    'PX4_GAZEBO_TRACK_MARKER_Z_OFFSET': '0.03',
    'PX4_GAZEBO_TRACK_MARKER_COLOR': '"0 0.8 1 1"',
    'PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH': '0.08',
    'PX4_GAZEBO_TRACK_MARKER_MODE': 'line_strip',
    'APP_SECRET_KEY': Fernet.generate_key().decode(),
    'OPENAI_MODEL': 'gpt-4.1',
    'VITE_API_BASE_URL': 'http://127.0.0.1:8000',
    'VITE_GAZEBO_VIEWER_URL': '',
}

out = []
seen = set()
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key = line.split('=', 1)[0]
        if key in updates:
            out.append(f'{key}={updates[key]}')
            seen.add(key)
        else:
            out.append(line)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('Updated .env for Runpod GUI + marker mode')
PY
```

检查关键配置：

```bash
cd /workspace/DroneDream
grep -E 'SIMULATOR_BACKEND|REAL_SIMULATOR_COMMAND|REAL_SIMULATOR_ARTIFACT_ROOT|ARTIFACT_ROOT|APP_SECRET_KEY|PX4_GAZEBO_HEADLESS|DISPLAY|PX4_GAZEBO_LAUNCH_GUI_CLIENT|PX4_GAZEBO_DRAW_TRACK_MARKER|PX4_GAZEBO_TRACK_MARKER|LIBGL_ALWAYS_SOFTWARE|QT_X11_NO_MITSHM' .env
```

重点：

```text
SIMULATOR_BACKEND=                      # 必须为空
PX4_GAZEBO_HEADLESS=false
DISPLAY=:99
PX4_GAZEBO_LAUNCH_GUI_CLIENT=true
PX4_GAZEBO_DRAW_TRACK_MARKER=true
```

---

## 8. 启动 noVNC / Xvfb 桌面

开一个专门终端：

```bash
cd /workspace/DroneDream
chmod +x scripts/run-gazebo-vnc.sh

export VNC_PASSWORD='你自己的临时强密码'
export GEOMETRY='1600x900x24'
./scripts/run-gazebo-vnc.sh
```

保持这个终端运行。浏览器打开 6080 noVNC URL：

```text
https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=remote
```

一开始只看到桌面是正常的；Gazebo trial 启动后 GUI 会自动出现。

---

## 9. 单独测试 PX4/Gazebo GUI 能力

在另一个终端：

```bash
cd /workspace/PX4-Autopilot
source .venv/bin/activate

export DISPLAY=:99
export LIBGL_ALWAYS_SOFTWARE=1
export QT_X11_NO_MITSHM=1

HEADLESS=0 make px4_sitl gz_x500 2>&1 | tee /workspace/px4_gui_test.log
```

看到 Gazebo Sim 窗口和 `x500_0` 后按 `Ctrl+C` 停止。若窗口不合适，可安装并使用 `wmctrl`：

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y wmctrl xdotool

export DISPLAY=:99
wmctrl -l
wmctrl -r "Gazebo Sim" -b remove,maximized_vert,maximized_horz
wmctrl -r "Gazebo Sim" -e 0,0,0,1450,820
```

---

## 10. DroneDream 单 trial smoke test（带 GUI 与 marker）

```bash
cd /workspace/DroneDream

TMP=/workspace/tmp/dd_px4_smoke
rm -rf "$TMP"
mkdir -p "$TMP"

cat > "$TMP/trial_input.json" <<'JSON'
{
  "trial_id": "tri_px4_smoke",
  "job_id": "job_px4_smoke",
  "candidate_id": "cand_px4_smoke",
  "seed": 101,
  "scenario_type": "nominal",
  "scenario_config": {},
  "job_config": {
    "track_type": "circle",
    "start_point": {"x": 0.0, "y": 0.0},
    "altitude_m": 3.0,
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
  "output_path": "/workspace/tmp/dd_px4_smoke/trial_result.json"
}
JSON

set -a
source .env
set +a

/workspace/DroneDream/backend/.venv/bin/python scripts/simulators/px4_gazebo_runner.py \
  --input "$TMP/trial_input.json" \
  --output "$TMP/trial_result.json"
```

查看结果：

```bash
python3 - <<'PY'
import json
from pathlib import Path

r = json.loads(Path('/workspace/tmp/dd_px4_smoke/trial_result.json').read_text())
m = r.get('metrics', {})
raw = m.get('raw_metric_json', {})
print('success:', r.get('success'))
print('rmse:', m.get('rmse'))
print('max_error:', m.get('max_error'))
print('crash_flag:', m.get('crash_flag'))
print('pass_flag:', m.get('pass_flag'))
print('evaluation_window_source:', raw.get('evaluation_window_source'))
PY
```

检查 marker 和 GUI 日志：

```bash
find /workspace/dd_artifacts/jobs/job_px4_smoke/trials/tri_px4_smoke -maxdepth 1 -type f | sort

tail -100 /workspace/dd_artifacts/jobs/job_px4_smoke/trials/tri_px4_smoke/track_marker_stdout.log || true
tail -100 /workspace/dd_artifacts/jobs/job_px4_smoke/trials/tri_px4_smoke/track_marker_stderr.log || true
```

通过标准：

```text
success: True
pass_flag: True
Gazebo GUI 可见
x500_0 可见
地面有 circle reference track marker
```

---

## 11. 配置 Runpod 代理 URL

Runpod Connect 页面复制 5173 / 8000 / 6080 URL，然后写入：

```bash
cd /workspace/DroneDream

FRONTEND_URL="https://<pod-id>-5173.proxy.runpod.net"
BACKEND_URL="https://<pod-id>-8000.proxy.runpod.net"
GAZEBO_URL="https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=remote"

python3 - <<PY
from pathlib import Path
p = Path('.env')
text = p.read_text()
updates = {
    'VITE_API_BASE_URL': '$BACKEND_URL',
    'CORS_ORIGINS': '$FRONTEND_URL',
    'BACKEND_HOST': '0.0.0.0',
    'BACKEND_PORT': '8000',
    'VITE_GAZEBO_VIEWER_URL': '$GAZEBO_URL',
}
out = []
seen = set()
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k = line.split('=', 1)[0]
        if k in updates:
            out.append(f'{k}={updates[k]}')
            seen.add(k)
        else:
            out.append(line)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n')
PY

cat > frontend/.env.local <<EOF
VITE_API_BASE_URL=$BACKEND_URL
VITE_GAZEBO_VIEWER_URL=$GAZEBO_URL
EOF
```

---

## 12. 启动三端

Backend：

```bash
cd /workspace/DroneDream
set -a
source .env
set +a
./scripts/dev-backend.sh
```

Worker：

```bash
cd /workspace/DroneDream
set -a
source .env
set +a
./scripts/dev-worker.sh
```

Frontend：

```bash
source /workspace/load-node.sh
cd /workspace/DroneDream/frontend
npm run dev -- --host 0.0.0.0
```

打开 5173 前端 URL。

---

## 13. Web 验证：real_cli + heuristic + GUI + marker

New Job：

```text
Track Type: circle
Start X: 0
Start Y: 0
Altitude: 3.0
Wind: 0 / 0 / 0 / 0
Sensor Noise Level: medium
Objective Profile: robust
Simulator Backend: real_cli
Optimizer Strategy: heuristic
Target RMSE: 0.50
Min Pass Rate: 0.80
```

验收：

```text
Job COMPLETED
Artifacts 不重叠
Score lower-is-better
PDF 可下载
TrialDetail 有 Trajectory replay
Gazebo iframe 显示无人机
Gazebo 地面显示 reference track marker
```

日志验证：

```bash
cd /workspace/DroneDream
JOB_ID="job_xxx"
LATEST_TRIAL_DIR=$(find /workspace/dd_artifacts/jobs/$JOB_ID/trials -mindepth 1 -maxdepth 1 -type d | sort | tail -1)

grep -E 'Track marker|GUI client|Launch command|HEADLESS' "$LATEST_TRIAL_DIR/stdout.log" || true
python3 -m json.tool "$LATEST_TRIAL_DIR/launch_config.json" | grep -E 'headless|gui_client_enabled|track_marker_enabled|track_marker_command|track_marker_z_offset|track_marker_color|track_marker_line_width|track_marker_mode' -A2
```

---

## 14. Web 验证：real_cli + GPT + GUI + marker

可以同时开启 GPT、Gazebo GUI、marker。建议先小规模验证：

```text
Simulator Backend: real_cli
Optimizer Strategy: gpt
Max Iterations: 2
Trials per Candidate: 1
Target RMSE: 0.30 或 0.25
Min Pass Rate: 0.80
OpenAI API Key: 你的 key
OpenAI Model: gpt-4.1
```

确认没问题后再正常规模：

```text
Max Iterations: 20
Trials per Candidate: 3
Target RMSE: 0.30
```

注意：GUI + marker + 软件渲染会导致 CPU 很高。正式拿结果时可以切回 headless。

---

## 15. 切回 headless 正式优化模式

```bash
cd /workspace/DroneDream

python3 - <<'PY'
from pathlib import Path
p = Path('.env')
text = p.read_text()
updates = {
    'PX4_GAZEBO_HEADLESS': 'true',
    'PX4_GAZEBO_LAUNCH_GUI_CLIENT': 'false',
    'PX4_GAZEBO_DRAW_TRACK_MARKER': 'false',
}
out = []
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k = line.split('=', 1)[0]
        if k in updates:
            out.append(f'{k}={updates[k]}')
        else:
            out.append(line)
    else:
        out.append(line)
p.write_text('\n'.join(out) + '\n')
PY
```

重启 worker：

```bash
cd /workspace/DroneDream
set -a
source .env
set +a
./scripts/dev-worker.sh
```

---

## 16. 故障排查

### 16.1 noVNC 空桌面

```bash
ps aux | grep -E 'Xvfb|x11vnc|websockify|fluxbox' | grep -v grep
```

如果缺失，重启 noVNC。

### 16.2 Gazebo 有无人机但没有赛道线

```bash
LATEST_TRIAL_DIR=/workspace/dd_artifacts/jobs/<job_id>/trials/<trial_id>
tail -200 "$LATEST_TRIAL_DIR/track_marker_stdout.log"
tail -200 "$LATEST_TRIAL_DIR/track_marker_stderr.log"
tail -200 "$LATEST_TRIAL_DIR/stderr.log"
```

如果 `Track marker not launched`，检查 `.env` 和 worker 环境。

```bash
PID=$(pgrep -f 'drone_dream_worker' | head -1)
tr '\0' '\n' < /proc/$PID/environ | grep -E 'DISPLAY|PX4_GAZEBO_HEADLESS|PX4_GAZEBO_LAUNCH_GUI_CLIENT|PX4_GAZEBO_DRAW_TRACK_MARKER'
```

### 16.3 赛道线太细或颜色不明显

```env
PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH=0.20
PX4_GAZEBO_TRACK_MARKER_COLOR="1 0.1 0 1"
```

重启 worker，建新 job。

### 16.4 Gazebo 窗口裁切或太小

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y wmctrl xdotool
export DISPLAY=:99
wmctrl -l
wmctrl -r "Gazebo Sim" -b remove,maximized_vert,maximized_horz
wmctrl -r "Gazebo Sim" -e 0,0,0,1450,820
```

如果 `Cannot open display`，说明 `Xvfb :99` 没运行，需要重启 noVNC。

### 16.5 CPU 很高

这是 GUI + noVNC + `LIBGL_ALWAYS_SOFTWARE=1` 的预期成本。正式优化建议 headless + Trajectory replay。
