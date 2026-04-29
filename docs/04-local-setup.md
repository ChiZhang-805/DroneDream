# DroneDream 本地操作流程（默认开启 Gazebo GUI、地面赛道 marker、Trajectory replay、PDF）

> 适用场景：在本地 Linux 工作站或本地服务器运行 DroneDream。默认开启 Gazebo GUI 窗口、地面 reference-track marker、前端 Trajectory replay、Artifacts、PDF 报告下载。  
> 如果本地机器有图形桌面，直接使用本机 `DISPLAY`；如果是无头服务器，可采用 Xvfb + noVNC，流程与 Runpod 类似。

---

## 0. 本地前提

推荐系统：Ubuntu 22.04。

需要：

```text
Python >= 3.11
Node.js >= 20
PX4-Autopilot
Gazebo Sim 8 / PX4 setup 脚本安装的依赖
浏览器
可用 X11 / XWayland DISPLAY，或 Xvfb + noVNC
```

推荐目录：

```text
~/DroneDream
~/PX4-Autopilot
~/dd_artifacts
```

---

## 1. 安装系统依赖

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git curl xz-utils lsof \
  xvfb x11vnc fluxbox novnc websockify \
  wmctrl xdotool \
  x11-apps mesa-utils libgl1-mesa-dri libglx-mesa0 libegl1 libglu1-mesa
```

---

## 2. 克隆代码

```bash
cd ~
git clone https://github.com/ChiZhang-805/DroneDream.git
git clone https://github.com/PX4/PX4-Autopilot.git
```

如果已有目录：

```bash
cd ~/DroneDream
git checkout main
git pull origin main

cd ~/PX4-Autopilot
git pull
```

检查关键文件：

```bash
cd ~/DroneDream

test -f scripts/simulators/px4_gazebo_runner.py && echo OK
test -f scripts/simulators/local_px4_launch_wrapper.py && echo OK
test -f scripts/simulators/px4_offboard_track_executor.py && echo OK
test -f scripts/simulators/gazebo_track_marker.py && echo OK
test -f backend/app/services/pdf_report.py && echo OK
test -f frontend/src/components/TrajectoryReplay.tsx && echo OK
```

---

## 3. 安装 PX4/Gazebo 依赖

```bash
cd ~/PX4-Autopilot
sudo DEBIAN_FRONTEND=noninteractive bash ./Tools/setup/ubuntu.sh
```

重启 shell 后继续。

PX4 venv：

```bash
cd ~/PX4-Autopilot
python3.11 -m venv .venv || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r Tools/setup/requirements.txt
pip install mavsdk
```

验证：

```bash
cd ~/PX4-Autopilot
source .venv/bin/activate
python - <<'PY'
from pyulog import ULog
import mavsdk
print('PX4 venv OK')
PY
```

---

## 4. 安装 DroneDream backend / worker / frontend

Backend：

```bash
cd ~/DroneDream
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip setuptools wheel
backend/.venv/bin/pip install -e "backend[dev]"
```

Worker：

```bash
cd ~/DroneDream
python3.11 -m venv worker/.venv || python3 -m venv worker/.venv
worker/.venv/bin/pip install --upgrade pip setuptools wheel
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"
```

Frontend：

```bash
cd ~/DroneDream/frontend
npm install
```

---

## 5. 选择本地图形模式

### 模式 A：本地桌面原生 Gazebo GUI（推荐）

如果你在本机桌面环境运行，通常已经有：

```bash
echo $DISPLAY
```

例如：

```text
:0
:1
```

不要强制改成 `:99`。使用当前桌面的 `DISPLAY`。

### 模式 B：本地服务器 / 无头机器 noVNC

如果没有桌面，使用 Xvfb + noVNC：

```bash
cd ~/DroneDream
chmod +x scripts/run-gazebo-vnc.sh

export VNC_PASSWORD='你自己的临时强密码'
export GEOMETRY='1600x900x24'
./scripts/run-gazebo-vnc.sh
```

浏览器打开：

```text
http://localhost:6080/vnc.html?autoconnect=1&resize=remote
```

如果通过远程服务器访问，需要 SSH tunnel 或反向代理。

---

## 6. 写入本地 `.env`（默认显示 Gazebo GUI + marker）

```bash
cd ~/DroneDream
test -f .env || cp .env.example .env
```

下面脚本默认按 **本地桌面模式** 配置。如果你用 noVNC/Xvfb，把 `DISPLAY_VALUE` 设成 `:99`。

```bash
cd ~/DroneDream

DISPLAY_VALUE="${DISPLAY:-:0}"
ARTIFACT_ROOT="$HOME/dd_artifacts"
mkdir -p "$ARTIFACT_ROOT"
export DISPLAY_VALUE ARTIFACT_ROOT

backend/.venv/bin/python - <<'PY'
from pathlib import Path
from cryptography.fernet import Fernet
import os

repo = Path.home() / 'DroneDream'
px4 = Path.home() / 'PX4-Autopilot'
artifact_root = Path(os.environ['ARTIFACT_ROOT']).resolve()
display_value = os.environ['DISPLAY_VALUE']

p = repo / '.env'
text = p.read_text(encoding='utf-8')

updates = {
    'BACKEND_HOST': '127.0.0.1',
    'BACKEND_PORT': '8000',
    'DATABASE_URL': f'sqlite:///{repo / "drone_dream.db"}',
    'CORS_ORIGINS': 'http://localhost:5173',
    'SIMULATOR_BACKEND': '',
    'REAL_SIMULATOR_COMMAND': f'"{repo}/backend/.venv/bin/python {repo}/scripts/simulators/px4_gazebo_runner.py"',
    'REAL_SIMULATOR_ARTIFACT_ROOT': str(artifact_root),
    'ARTIFACT_ROOT': str(artifact_root),
    'REAL_SIMULATOR_TIMEOUT_SECONDS': '900',
    'REAL_SIMULATOR_KEEP_RUN_DIRS': 'true',
    'PX4_GAZEBO_DRY_RUN': 'false',
    'PX4_GAZEBO_LAUNCH_COMMAND': f'"{px4}/.venv/bin/python {repo}/scripts/simulators/local_px4_launch_wrapper.py --run-dir {{run_dir}} --input {{trial_input}} --params {{params_json}} --track {{track_json}} --telemetry {{telemetry_json}} --stdout-log {{stdout_log}} --stderr-log {{stderr_log}} --vehicle {{vehicle}} --world {{world}} --headless {{headless}}"',
    'PX4_GAZEBO_TIMEOUT_SECONDS': '900',
    'PX4_GAZEBO_HEADLESS': 'false',
    'PX4_GAZEBO_KEEP_RAW_LOGS': 'true',
    'PX4_GAZEBO_VEHICLE': 'x500',
    'PX4_GAZEBO_WORLD': 'default',
    'PX4_SITE_DRY_RUN': 'false',
    'PX4_AUTOPILOT_DIR': str(px4),
    'PX4_SETUP_COMMANDS': f'"source {px4}/.venv/bin/activate"',
    'PX4_MAKE_TARGET': 'gz_x500',
    'PX4_RUN_SECONDS': '90',
    'PX4_READY_TIMEOUT_SECONDS': '30',
    'PX4_TELEMETRY_MODE': 'ulog',
    'PX4_ULOG_ROOT': str(px4 / 'build/px4_sitl_default/rootfs/log'),
    'PX4_ULOG_PATH': '',
    'PX4_ENABLE_OFFBOARD_EXECUTOR': 'true',
    'PX4_OFFBOARD_EXECUTOR_COMMAND': f'"{px4}/.venv/bin/python {repo}/scripts/simulators/px4_offboard_track_executor.py"',
    'PX4_OFFBOARD_CONNECTION': 'udp://:14540',
    'PX4_OFFBOARD_SETPOINT_RATE_HZ': '10',
    'PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS': '30',
    'PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS': '120',
    'PX4_OFFBOARD_LAND_AFTER': 'true',
    'PX4_OFFBOARD_DRY_RUN': 'false',
    'DISPLAY': display_value,
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
print('Updated local .env')
PY
```

检查：

```bash
cd ~/DroneDream
grep -E 'SIMULATOR_BACKEND|REAL_SIMULATOR_COMMAND|PX4_GAZEBO_HEADLESS|DISPLAY|PX4_GAZEBO_LAUNCH_GUI_CLIENT|PX4_GAZEBO_DRAW_TRACK_MARKER|PX4_GAZEBO_TRACK_MARKER|APP_SECRET_KEY' .env
```

---

## 7. 单独测试 PX4/Gazebo GUI

```bash
cd ~/PX4-Autopilot
source .venv/bin/activate

set -a
source ~/DroneDream/.env
set +a

HEADLESS=0 make px4_sitl gz_x500 2>&1 | tee ~/px4_gui_test.log
```

看到 Gazebo Sim 和 `x500_0` 后，`Ctrl+C` 停止。

如需调窗口：

```bash
sudo apt-get install -y wmctrl xdotool
export DISPLAY=${DISPLAY:-:0}
wmctrl -l
wmctrl -r "Gazebo Sim" -e 0,0,0,1450,820
```

---

## 8. 单 trial smoke test（带 GUI 与 marker）

```bash
cd ~/DroneDream

TMP=/tmp/dd_px4_smoke
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
  "output_path": "/tmp/dd_px4_smoke/trial_result.json"
}
JSON

set -a
source .env
set +a

backend/.venv/bin/python scripts/simulators/px4_gazebo_runner.py \
  --input "$TMP/trial_input.json" \
  --output "$TMP/trial_result.json"
```

验证：

```bash
python3 - <<'PY'
import json
from pathlib import Path
r = json.loads(Path('/tmp/dd_px4_smoke/trial_result.json').read_text())
m = r.get('metrics', {})
print('success:', r.get('success'))
print('rmse:', m.get('rmse'))
print('max_error:', m.get('max_error'))
print('pass_flag:', m.get('pass_flag'))
print('crash_flag:', m.get('crash_flag'))
PY
```

---

## 9. 启动三端

Backend：

```bash
cd ~/DroneDream
set -a
source .env
set +a
./scripts/dev-backend.sh
```

Worker：

```bash
cd ~/DroneDream
set -a
source .env
set +a
./scripts/dev-worker.sh
```

Frontend：

```bash
cd ~/DroneDream/frontend
npm run dev -- --host 0.0.0.0
```

打开：

```text
http://localhost:5173
```

本地原生桌面模式下，`VITE_GAZEBO_VIEWER_URL` 可以为空；你会在系统桌面直接看到 Gazebo GUI 窗口。  
如果使用本地 noVNC，则设置：

```bash
cat > ~/DroneDream/frontend/.env.local <<'EOF'
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_GAZEBO_VIEWER_URL=http://localhost:6080/vnc.html?autoconnect=1&resize=remote
EOF
```

然后重启 frontend。

---

## 10. Web 验证：real_cli + heuristic

New Job：

```text
Track Type: circle
Start Point: (0, 0)
Altitude: 3
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
Job completed
Gazebo GUI 出现
x500_0 可见
地面 circle marker 可见
Trajectory replay 正常
Artifacts 正常
Download PDF report 正常
Score lower-is-better
```

---

## 11. Web 验证：real_cli + GPT

演示模式：

```text
Simulator Backend: real_cli
Optimizer Strategy: gpt
Max Iterations: 2
Trials per Candidate: 1
Target RMSE: 0.30
OpenAI API Key: 你的 key
OpenAI Model: gpt-4.1
```

正常规模：

```text
Max Iterations: 20
Trials per Candidate: 3
Target RMSE: 0.30
```

GUI + marker 可以和 GPT 同时开启，但 CPU 和稳定性压力会更大。

---

## 12. 切回 headless 正式模式

```bash
cd ~/DroneDream
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

重启 worker。

---

## 13. 故障排查

### 13.1 Gazebo 窗口不出现

```bash
ps aux | grep -E 'gz sim|px4|gazebo' | grep -v grep
grep -E 'GUI client|Launch command|HEADLESS' ~/dd_artifacts/jobs/<job_id>/trials/<trial_id>/stdout.log
```

检查：

```bash
PID=$(pgrep -f 'drone_dream_worker' | head -1)
tr '\0' '\n' < /proc/$PID/environ | grep -E 'DISPLAY|PX4_GAZEBO_HEADLESS|PX4_GAZEBO_LAUNCH_GUI_CLIENT|PX4_GAZEBO_DRAW_TRACK_MARKER'
```

### 13.2 有无人机但没有地面 marker

```bash
tail -200 ~/dd_artifacts/jobs/<job_id>/trials/<trial_id>/track_marker_stdout.log
tail -200 ~/dd_artifacts/jobs/<job_id>/trials/<trial_id>/track_marker_stderr.log
```

### 13.3 marker 太细或不明显

改：

```env
PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH=0.20
PX4_GAZEBO_TRACK_MARKER_COLOR="1 0.1 0 1"
```

重启 worker，建新 job。

### 13.4 CPU 高

GUI + software rendering 是高 CPU 模式。正式优化建议 headless + Trajectory replay。
