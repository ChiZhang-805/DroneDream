# Runpod Gazebo Visualization (PR3)

## 1) Default mode (recommended)

DroneDream remains **headless by default** for real_cli + PX4/Gazebo runs.

- Keep `PX4_GAZEBO_HEADLESS=true` for normal optimization throughput.
- GPT tuning and real_cli execution do **not** require GUI.
- Frontend trajectory replay is artifact-based (post-run), so it does not change simulator runtime behavior.

## 2) Browser trajectory replay

`TrialDetail` now includes a **Trajectory replay** panel that renders JSON artifacts in-browser.

- Replay source priority: `trajectory*.json` first, then `telemetry*.json`.
- Optional reference path is rendered when a reference-track JSON artifact is available.
- Replay controls: Play/Pause, Reset, speed (0.5x/1x/2x/4x), scrubber.
- If artifacts are missing or invalid, the page shows an empty/error state instead of crashing.

## 3) Optional Gazebo live view on Runpod (demo/debug)

This mode is optional and should only be enabled when you explicitly want GUI visualization.

### 3.1 Expose Runpod HTTP port

In Runpod **Edit Pod**, expose HTTP port `6080`.

### 3.2 Install noVNC dependencies inside the container

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb x11vnc fluxbox novnc websockify
```

### 3.3 Start the helper script

```bash
export VNC_PASSWORD='<strong-password>'
./scripts/run-gazebo-vnc.sh
```

Expected output:

```text
noVNC listening on 0.0.0.0:6080
Open Runpod 6080 HTTP proxy URL.
```

### 3.4 Configure frontend + simulator env

```bash
VITE_GAZEBO_VIEWER_URL=https://<pod-id>-6080.proxy.runpod.net/vnc.html?autoconnect=1&resize=remote
PX4_GAZEBO_HEADLESS=false
DISPLAY=:99
```

Then restart frontend (and backend/worker when needed) so env changes take effect.

Open JobDetail/TrialDetail to view the iframe panel.

## 4) Warnings / limitations

- Runpod noVNC proxy is public if exposed; control access yourself.
- Use this mode for demo/debug only.
- GUI mode may reduce PX4/Gazebo performance.
- Avoid enabling GUI during expensive batch tuning unless visualization is intentionally required.
- Multi-worker concurrent visualization is not supported in this PR.
