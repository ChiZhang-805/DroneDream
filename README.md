<p align="center">
  <img src="docs/assets/drone-dream-icon.png" alt="DroneDream icon" width="220" />
</p>

<h1 align="center">🚁 DroneDream</h1>
<p align="center">Auto Drone Control Parameters Tuning Platform</p>

## 项目简介

DroneDream 是一个面向 PX4/Gazebo 的 Web 端无人机自动调参平台，支持多样化仿真任务配置、高级赛道编辑、异步优化执行、实时 gazebo 窗口观测、 artifacts 管理、2D/3D Trajectory Replay 和 PDF 版报告导出。

## 核心能力

- `real_cli` 接入 PX4/Gazebo SITL。
- 启发式与 GPT 两类参数提议策略。
- noVNC/Gazebo GUI 可视化与回放。
- 产物下载与报告生成。

## 文档导航

- [Docs 总览](./docs/README.md)
- [01 Overview](./docs/01-overview.md)
- [02 Architecture](./docs/02-architecture.md)
- [03 Runpod Setup](./docs/03-runpod-setup.md)
- [04 Local Setup](./docs/04-local-setup.md)
- [05 API Reference](./docs/05-api-reference.md)
- [06 Data Model](./docs/06-data-model.md)
- [07 Simulator Adapters](./docs/07-simulator-adapters.md)
- [08 PX4 Gazebo](./docs/08-px4-gazebo.md)
- [09 Optimizer Guide](./docs/09-optimizer-guide.md)
- [10 Development](./docs/10-development.md)
- [11 Operations](./docs/11-operations.md)

## Runpod 快速复现（精简版）

### 1) Pod 配置

- 镜像：Ubuntu 22.04 / PyTorch CUDA（示例：`runpod/pytorch:2.4.0-py3.11-cuda12.4.1-ubuntu22.04`）
- Volume：`/workspace`，建议 100GB
- 端口：`5173, 8000, 6080, 8888`

noVNC URL 示例（统一使用）：

```text
https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=scale&view_clip=0
```

### 2) 克隆仓库

```bash
cd /workspace
git clone https://github.com/ChiZhang-805/DroneDream.git
git clone https://github.com/PX4/PX4-Autopilot.git
```

### 3) 安装系统依赖

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y sudo curl xz-utils lsof \
  xvfb x11vnc fluxbox novnc websockify \
  wmctrl xdotool x11-utils \
  x11-apps mesa-utils libgl1-mesa-dri libglx-mesa0 libegl1 libglu1-mesa
```

### 4) 安装 PX4 venv

```bash
cd /workspace/PX4-Autopilot
python3.11 -m venv .venv || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r Tools/setup/requirements.txt
pip install mavsdk
```

### 5) 安装 backend / worker / frontend

```bash
cd /workspace/DroneDream
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"

python3.11 -m venv worker/.venv || python3 -m venv worker/.venv
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"

cd frontend
npm install
```

### 6) 写入 `.env`

```env
cat << 'EOF' > .env
DISPLAY=:99
GEOMETRY=1600x900x24
PX4_GAZEBO_VNC_DESKTOP_GEOMETRY=1600x900x24

PX4_GAZEBO_HEADLESS=false
PX4_GAZEBO_LAUNCH_GUI_CLIENT=true

PX4_GAZEBO_GUI_COMMAND=
PX4_GAZEBO_RAW_GUI_COMMAND="gz sim -g"

PX4_GAZEBO_GUI_WINDOW_TITLE="Gazebo Sim"
PX4_GAZEBO_GUI_WINDOW_MODE=fill
PX4_GAZEBO_GUI_WINDOW_GEOMETRY=fill
PX4_GAZEBO_GUI_WINDOW_WIDTH=1280
PX4_GAZEBO_GUI_WINDOW_HEIGHT=720
PX4_GAZEBO_GUI_WINDOW_DELAY_SECONDS=8
PX4_GAZEBO_GUI_WINDOW_RETRY_SECONDS=20
PX4_GAZEBO_GUI_WINDOW_ENFORCE_SECONDS=30
EOF
```

### 7) 写入 `frontend/.env.local`

```env
cat << 'EOF' > frontend/.env.local
VITE_GAZEBO_VIEWER_URL=https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=scale&view_clip=0
EOF
```

### 8) 启动 noVNC

```bash
cd /workspace/DroneDream
bash scripts/run-gazebo-vnc.sh
```

### 9) 启动 backend / worker / frontend

```bash
cd /workspace/DroneDream
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

```bash
cd /workspace/DroneDream
worker/.venv/bin/python -m drone_dream_worker.main
```

```bash
cd /workspace/DroneDream/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

### 10) 在 Web UI 创建任务

- 范例1： `real_cli + heuristic` 任务验证链路。
- 范例2： 创建 `real_cli + gpt` 任务。
- 范例3： 切回 headless 正式优化模式（`PX4_GAZEBO_HEADLESS=true`）。
