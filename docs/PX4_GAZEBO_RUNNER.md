# PX4/Gazebo Runner for DroneDream `real_cli`

## 1) Purpose

`scripts/simulators/px4_gazebo_runner.py` is a DroneDream-facing wrapper that
implements the existing `real_cli` JSON file protocol:

- reads `trial_input.json`
- launches a simulator command (or dry-run fixture path)
- computes DroneDream trial metrics
- writes `trial_result.json`

It does **not** redesign backend architecture. It is a drop-in
`REAL_SIMULATOR_COMMAND` target.

> Important: this repository does **not** ship a full PX4/Gazebo workspace,
> world assets, ROS contracts, or telemetry exporters. Real execution requires
> local environment setup by the operator.

---

## 2) CLI usage

```bash
python scripts/simulators/px4_gazebo_runner.py --input trial_input.json --output trial_result.json
```

- `--input` and `--output` are required.
- Expected simulator failures are emitted as structured JSON (`success=false`)
  and exit code `0`.
- Non-zero exit should only happen for true script-level crashes (rare).

---

## 3) Environment variables

Required for real mode:

- `PX4_GAZEBO_LAUNCH_COMMAND`

Core options:

- `PX4_GAZEBO_WORKDIR`
- `PX4_GAZEBO_TIMEOUT_SECONDS` (default `300`)
- `PX4_GAZEBO_HEADLESS` (default `true`)
- `PX4_GAZEBO_KEEP_RAW_LOGS` (default `true`)
- `PX4_GAZEBO_DRY_RUN` (default `false`)
- `PX4_GAZEBO_PASS_RMSE` (default `0.75`)
- `PX4_GAZEBO_PASS_MAX_ERROR` (default `2.0`)
- `PX4_GAZEBO_MIN_TRACK_COVERAGE` (default `0.9`)

Optional:

- `PX4_GAZEBO_VEHICLE`
- `PX4_GAZEBO_WORLD`
- `PX4_GAZEBO_EXTRA_ARGS`
- `PX4_GAZEBO_TELEMETRY_FORMAT` (default `json`)
- `PX4_GAZEBO_ALLOW_CSV_TELEMETRY` (default `false`)

---

## 4) Lower-level launch command contract

`PX4_GAZEBO_LAUNCH_COMMAND` can include template tokens:

- `{run_dir}`
- `{trial_input}`
- `{trial_output}`
- `{params_json}`
- `{track_json}`
- `{telemetry_json}`
- `{trajectory_json}`
- `{stdout_log}`
- `{stderr_log}`
- `{job_id}`
- `{trial_id}`
- `{candidate_id}`
- `{seed}`
- `{scenario_type}`
- `{vehicle}`
- `{world}`
- `{headless}`
- `{extra_args}`

If tokens are present, the runner substitutes and executes.
If no token is present, it appends:

- `--input <trial_input>`
- `--output <trial_output>`
- `--params <params_json>`
- `--track <track_json>`
- `--telemetry <telemetry_json>`

The lower-level launcher is responsible for starting PX4/Gazebo and writing
telemetry in the expected schema.

`PX4_GAZEBO_VEHICLE`, `PX4_GAZEBO_WORLD`, `PX4_GAZEBO_HEADLESS`, and
`PX4_GAZEBO_EXTRA_ARGS` can be consumed either directly from environment
variables by your launcher script, or passed through the command template
tokens above.

---

## 5) Files produced per trial

The runner writes these files in the run directory (the parent of output file,
normally the `real_cli` trial directory):

- `controller_params.json`
- `reference_track.json`
- `telemetry.json`
- `trajectory.json`
- `stdout.log`
- `stderr.log`
- `runner.log`
- `trial_result.json`

Artifacts are returned in `trial_result.json` metadata for at least telemetry,
trajectory (`artifact_type=trajectory_json`), and logs.

---

## 6) Canonical reference track assumptions

Track generator is deterministic and reused in dry-run + metrics:

- `circle`: fixed 5m radius around `start_point`
- `u_turn`: straight lane + semicircle turn + return lane
- `lemniscate`: fixed-scale figure-eight around `start_point`

`altitude_m` anchors `z` for generated reference points.

---

## 7) Telemetry schema

Preferred `telemetry.json`:

```json
{
  "samples": [
    {
      "t": 0.0,
      "x": 0.0,
      "y": 0.0,
      "z": 3.0,
      "vx": 0.0,
      "vy": 0.0,
      "vz": 0.0,
      "yaw": 0.0,
      "armed": true,
      "mode": "offboard",
      "crashed": false
    }
  ],
  "meta": {
    "simulator": "px4_gazebo",
    "vehicle": "x500",
    "world": "..."
  }
}
```

CSV fallback is supported only when `PX4_GAZEBO_ALLOW_CSV_TELEMETRY=true`.

---

## 8) Metric definitions

Computed against nearest-point XY distance to reference path:

- `rmse`: RMS tracking error
- `max_error`: max tracking error
- `completion_time`: `t_end - t_start`
- `final_error`: final sample to final reference point
- `overshoot_count`: deterministic peak/valley heuristic over radial error
- `crash_flag`: telemetry crash marker or severe altitude collapse
- `timeout_flag`: launcher timeout hit
- `instability_flag`: non-finite/implausible jumps/divergence
- `pass_flag`: healthy trial + thresholds + minimum track coverage
- `score` (lower is better): weighted error/time + penalties
- `raw_metric_json`: mode/coverage/threshold metadata

---

## 9) Failure mapping

- Launch command missing/not executable: `ADAPTER_UNAVAILABLE`
- Subprocess timeout: `TIMEOUT`
- Telemetry missing/malformed/empty/non-finite: `SIMULATION_FAILED`
- Other unexpected runner exceptions: `SIMULATION_FAILED`

Runner favors predictable JSON output over hard crashes.

---

## 10) Dry-run mode

When `PX4_GAZEBO_DRY_RUN=true`:

- no external PX4/Gazebo process is launched
- deterministic fixture telemetry is generated from trial input
- the same ingestion + metric path is used
- full artifacts + `trial_result.json` are written

This mode exists for CI and developer machines without Gazebo.

---

## 11) Known limitations

- No bundled PX4 workspace, ROS launch files, world assets, or telemetry export stack.
- Real deployments must provide a valid `PX4_GAZEBO_LAUNCH_COMMAND` and any
  local dependencies (source scripts, environment, binaries, plugin paths).
- The runner standardizes contract + metric computation; it does not encode
  site-specific PX4/Gazebo startup logic.


## 12) Site-specific local wrapper (`local_px4_launch_wrapper.py`)

Use `scripts/simulators/local_px4_launch_wrapper.py` as the lower-level command
behind `px4_gazebo_runner.py`. This repository does **not** bundle PX4-Autopilot
or Gazebo assets; users must install those locally.

Example:

```bash
export REAL_SIMULATOR_COMMAND="python3 /abs/path/scripts/simulators/px4_gazebo_runner.py"
export PX4_GAZEBO_DRY_RUN=false
export PX4_GAZEBO_LAUNCH_COMMAND='python3 /abs/path/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}'
export PX4_AUTOPILOT_DIR=/home/chi/PX4-Autopilot
export PX4_SETUP_COMMANDS='source /opt/ros/humble/setup.bash'
export PX4_MAKE_TARGET=gz_x500
```

Wrapper env vars (with defaults):

- `PX4_AUTOPILOT_DIR` (required in real mode unless custom launch template is provided)
- `PX4_SETUP_COMMANDS` (optional semicolon-separated shell setup commands)
- `PX4_LAUNCH_COMMAND_TEMPLATE` (optional full shell command template)
- `PX4_MAKE_TARGET` (default `gz_x500`)
- `PX4_RUN_SECONDS` (default `30`)
- `PX4_READY_TIMEOUT_SECONDS` (default `30`; reserved for site probes)
- `PX4_SITE_DRY_RUN` (default `false`)
- `PX4_TELEMETRY_MODE` (default `json`)
- `PX4_TELEMETRY_SOURCE_JSON` (optional file path copied/normalized to telemetry output)

Dry-run mode (`PX4_SITE_DRY_RUN=true`) produces deterministic fixture telemetry and
writes `launch_config.json`, `controller_params.used.json`, and
`reference_track.used.json` in the run directory.

Real mode (`PX4_SITE_DRY_RUN=false`) launches a site command via `bash -lc`, captures
stdout/stderr logs, enforces `PX4_RUN_SECONDS`, terminates process groups cleanly,
and fails non-zero if telemetry is missing/invalid.

Ubuntu 22.04 local sanity check for PX4/Gazebo SITL (outside DroneDream repo):

```bash
cd /path/to/PX4-Autopilot
make px4_sitl gz_x500
```

Do **not** commit PX4-Autopilot into DroneDream.
