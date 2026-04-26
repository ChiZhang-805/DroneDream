# Runpod Gazebo Visualization (PR5)

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
PX4_GAZEBO_LAUNCH_GUI_CLIENT=true
PX4_GAZEBO_GUI_COMMAND="gz sim -g"
PX4_GAZEBO_DRAW_TRACK_MARKER=true
PX4_GAZEBO_TRACK_MARKER_Z_OFFSET=0.03
PX4_GAZEBO_TRACK_MARKER_COLOR="0 0.8 1 1"
PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH=0.08
LIBGL_ALWAYS_SOFTWARE=1
QT_X11_NO_MITSHM=1
```

Then restart frontend (and backend/worker when needed) so env changes take effect.

Open JobDetail/TrialDetail to view the iframe panel.

> noVNC/Xvfb only gives you a virtual desktop. To see Gazebo in that desktop,
> the Gazebo GUI client must also run. PR5 adds wrapper-side auto-launch for
> `gz sim -g` when GUI mode is explicitly enabled.

## 4) Draw reference track in Gazebo

When `PX4_GAZEBO_DRAW_TRACK_MARKER=true`, DroneDream draws the current
trial's `reference_track.json` into Gazebo after world/PX4 readiness and before
offboard execution starts.

- The marker is projected onto the ground plane (`z = PX4_GAZEBO_TRACK_MARKER_Z_OFFSET`,
  default `0.03`) so the path is visible as a ground guide line.
- `circle` tracks appear as closed loops; `u_turn` / `lemniscate` render their
  own shapes from the generated reference points.
- This mode is intended for GUI demo/debug workflows, not large-scale headless
  GPT optimization batches.
- Marker failure is non-fatal by default. Set `PX4_GAZEBO_REQUIRE_TRACK_MARKER=true`
  only when you want missing markers to fail the trial.

If Gazebo shows `x500_0` but no track marker, inspect:

- `track_marker_stdout.log`
- `track_marker_stderr.log`
- `launch_config.json` (`track_marker_enabled` should be `true`)

### 3.5 Manual fallback verification

If you need to verify GUI attach manually in a terminal:

```bash
export DISPLAY=:99
export LIBGL_ALWAYS_SOFTWARE=1
export QT_X11_NO_MITSHM=1
gz sim -g
```

## 5) Warnings / limitations

- Runpod noVNC proxy is public if exposed; control access yourself.
- Use this mode for demo/debug only.
- GUI mode may reduce PX4/Gazebo performance.
- `LIBGL_ALWAYS_SOFTWARE=1` forces software rendering and can increase CPU usage significantly.
- Avoid enabling GUI during expensive batch tuning unless visualization is intentionally required.
- Recommended batch optimization path: keep headless mode on and use trajectory replay artifacts.
- Multi-worker concurrent visualization is not supported in this PR.
