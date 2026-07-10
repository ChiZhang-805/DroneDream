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
- `PX4_GAZEBO_TIMEOUT_SECONDS` (default `300`; the launcher wall-clock budget
  at `simulation_speed_factor=1`)
- `PX4_GAZEBO_HEADLESS` (default `true`)
- `PX4_GAZEBO_KEEP_RAW_LOGS` (default `true`)
- `PX4_GAZEBO_DRY_RUN` (default `false`)
- `PX4_GAZEBO_PASS_RMSE` (default `0.75`)
- `PX4_GAZEBO_PASS_MAX_ERROR` (default `2.0`)
- `PX4_GAZEBO_MIN_TRACK_COVERAGE` (default `0.9`)
- `PX4_GAZEBO_EVAL_ALTITUDE_FRACTION` (default `0.9`)
- `PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M` (default `1.5`)
- `PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES` (default `5`)
- `PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION` (default `0.5`)

Optional:

- `PX4_GAZEBO_VEHICLE`
- `PX4_GAZEBO_WORLD`
- `PX4_GAZEBO_EXTRA_ARGS`
- `PX4_GAZEBO_TELEMETRY_FORMAT` (default `json`)
- `PX4_GAZEBO_ALLOW_CSV_TELEMETRY` (default `false`)
- `DRONEDREAM_PX4_EXECUTABLE` / `DRONEDREAM_GAZEBO_EXECUTABLE` (required only
  when the corresponding executable template token below is used)
- `PX4_FIRMWARE_COMMIT_OBSERVED` (optional full 40-character SHA evidence for
  a custom/remote launcher that has no local `PX4_AUTOPILOT_DIR` checkout)

Per-job `vehicle_profile` may override `headless` and may supply
`simulation_speed_factor` (`0.1 <= value <= 100`) and `instance_id` (`0..255`).
The runner exports these as the official PX4 `PX4_SIM_SPEED_FACTOR`, plus
`PX4_INSTANCE`, and records them in `launch_config.json`. Worker defaults remain
compatible when those fields are absent.

For `simulation_speed_factor < 1`, both the outer `real_cli` adapter and this
runner increase their wall-clock timeout by `1 / simulation_speed_factor`.
Faster-than-real-time settings do not shrink the baseline, and user-controlled
slowdown can increase it by at most `10x`. The base/effective values are
recorded in `launch_config.json` and `simulator_runtime_manifest.json`.

`instance_id` is an advanced, operator-managed override, not an automatic port
allocator. The bundled wrapper still defaults MAVSDK to `udp://:14540`. Until a
host-level instance/port lease allocator is configured, run at most **one
`real_cli` trial per host**. Setting a unique `instance_id` alone is not enough;
the operator must also configure matching PX4/Gazebo/MAVSDK ports.

---

## 4) Lower-level launch command contract

`PX4_GAZEBO_LAUNCH_COMMAND` can include template tokens:

- `{run_dir}`
- `{trial_input}`
- `{trial_output}`
- `{params_json}`
- `{px4_params_json}`
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
- `{scenario_config_json}`
- `{instance_id}`
- `{simulation_speed_factor}`
- `{px4_executable}`
- `{gazebo_executable}`

If tokens are present, the runner substitutes and executes.
If no token is present, it appends:

- `--input <trial_input>`
- `--output <trial_output>`
- `--params <params_json>`
- `--track <track_json>`
- `--telemetry <telemetry_json>`

The lower-level launcher is responsible for starting PX4/Gazebo and writing
telemetry in the expected schema.

Substitution is performed after command tokenization, so input/artifact paths
containing spaces stay a single argv item. `{extra_args}` is the only token
that intentionally expands to multiple arguments. The launcher also receives
`PX4_TRIAL_SEED`, `PX4_TRIAL_ATTEMPT`, `PX4_TRIAL_SCENARIO_TYPE`,
`PX4_TRIAL_SCENARIO_CONFIG_PATH`, `PX4_TRIAL_WIND_JSON`, and
`PX4_TRIAL_SENSOR_NOISE_LEVEL` for deterministic world/sensor integration.

The outer adapter does not pass the worker's complete environment to this
command. It preserves OS/Python/PX4/Gazebo/ROS runtime variables through an
allowlist and always removes names containing `KEY`, `TOKEN`, `SECRET`,
`PASSWORD`, or `CREDENTIAL`, plus database, S3, cloud, OIDC and LLM credentials.
Pass non-sensitive custom settings as command arguments or use a documented
`PX4_*`, `GZ_*`, or `DRONEDREAM_RUNTIME_*` variable.

`PX4_GAZEBO_VEHICLE`, `PX4_GAZEBO_WORLD`, `PX4_GAZEBO_HEADLESS`, and
`PX4_GAZEBO_EXTRA_ARGS` can be consumed either directly from environment
variables by your launcher script, or passed through the command template
tokens above.

---

## 5) Files produced per trial

The runner writes these files in the run directory (the parent of output file,
normally the `real_cli` trial directory):

- `controller_params.json`
- `px4_parameters.input.json`
- `scenario_config.json`
- `reference_track.json`
- `telemetry.json`
- `trajectory.json`
- `offboard_timing.json` (when offboard executor is enabled)
- `stdout.log`
- `stderr.log`
- `runner.log`
- `launch_config.json` (includes advanced scenario config passthrough)
- `simulator_runtime_manifest.json` (execution identity, requested/observed
  firmware identity, simulator profile, and effective timeout)
- `trial_result.json`

Artifacts are returned in `trial_result.json` metadata for telemetry,
trajectory (`artifact_type=trajectory_json`), logs, and offboard timing
(`artifact_type=offboard_timing_json`) when present. Parameter input, scenario,
controller, and launch-configuration JSON are also returned as reproducibility
artifacts.

---

## 6) Canonical reference track assumptions

Track generator is deterministic and reused in dry-run + metrics:

- `circle`: fixed 5m radius around `start_point`
- `u_turn`: straight lane + semicircle turn + return lane
- `lemniscate`: fixed-scale figure-eight around `start_point`

`altitude_m` anchors `z` for generated reference points.

Custom tracks may vary `z` point by point. Tracking error and track progress are
computed against the nearest ordered **3D polyline segment**, so vertical error
and projected reference altitude are included instead of being silently
reduced to XY.

Dry-run disturbance samples are generated from the Trial seed. Repeating the
same seed/configuration produces identical telemetry, while distinct seeds
produce distinct but reproducible noise. This preserves common-random-number
comparisons between candidates.

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
Telemetry JSON/CSV is limited to 16 MiB and 50,000 samples per trial. Oversized
outputs fail as `SIMULATION_FAILED` before normalization; launchers should
downsample high-rate streams deterministically before emitting this contract.

---

## 8) Metric definitions

Computed against ordered 3D segment projection onto the reference path, using an
**evaluation window** focused on track-following (not preflight/takeoff/landing):

Window selection order:

1. `offboard_timing.json` `track_start_t`/`track_end_t` is treated as a **broad
   candidate** only (never trusted blindly).
2. Candidate is refined using telemetry:
   - start at first index with `N` consecutive samples satisfying both:
     - `z >= EVAL_ALTITUDE_FRACTION * projected_reference_z`
     - nearest ordered-track 3D segment error `<= EVAL_NEAR_TRACK_THRESHOLD_M`
   - end just before the first `N`-sample run below each sample's projected
     reference-altitude threshold
3. Telemetry-derived candidate/refinement with the same rules
4. Altitude-only fallback (`N` consecutive samples above altitude threshold, then trimmed before landing)
5. All-samples fallback (conservative behavior)

- `rmse`: RMS tracking error over evaluation window
- `max_error`: max tracking error over evaluation window
- `completion_time`: `t_end - t_start`
- `final_error`: final sample to final reference point
- `overshoot_count`: deterministic local-peak heuristic over 3D cross-track error
- `crash_flag`:
  - refined windows: true only for telemetry `crashed=true` inside the refined
    window, or altitude collapse (consecutive drop below
    `max(0.2, EVAL_COLLAPSE_ALTITUDE_FRACTION * target_altitude)`) after stable altitude
    has been reached in-window
  - all-samples fallback: conservative low-altitude detection remains enabled
- `timeout_flag`: launcher timeout hit
- `instability_flag`: non-finite/implausible jumps/divergence
- `pass_flag`: healthy trial + thresholds + minimum **evaluation** track coverage
- `score` (lower is better): weighted error/time + penalties
- `raw_metric_json`: mode/coverage/threshold metadata, including:
  - `evaluation_window_source`
  - `evaluation_window_raw_source`
  - `raw_track_start_t`
  - `raw_track_end_t`
  - `evaluation_start_t`
  - `evaluation_end_t`
  - `evaluation_sample_count`
  - `total_sample_count`
  - `evaluation_start_reason`
  - `evaluation_trimmed_takeoff_samples`
  - `evaluation_trimmed_landing_samples`
  - `evaluation_min_z`
  - `evaluation_max_z`
  - `evaluation_max_error_sample`
  - `crash_reason`
  - `evaluation_track_coverage`
  - full-log diagnostic fields (`full_log_rmse`, `full_log_max_error`)
  - `track_length_3d_m`, `track_projection`, and `coverage_basis`

Coverage is the union of continuous, forward traversed polyline arc-length
intervals, not the count of nearest waypoint indices. Subdividing the same
geometric path into more points does not alter coverage. Reverse motion,
excessive backtracking, large progress jumps, failure to start near the path
origin, or failure to reach the endpoint makes the progress contract fail even
when samples remain geometrically close to the path.

---

## 9) Advanced scenario config support level

`advanced_scenario_config` is accepted from backend `trial_input.json` and is:

- persisted to `launch_config.json` for downstream launch wrappers/scripts,
- propagated to `raw_metric_json.advanced_scenario_summary`,
- checked before the PX4/Gazebo process starts.

Current PX4/Gazebo integration status in this repo:

- wind gusts / sensor degradation / battery / obstacles have no verified
  physics implementation in the bundled launcher;
- no full world/physics mutation is enforced by default scripts;
- requesting any non-default effect fails fast with
  `UNSUPPORTED_SCENARIO_EFFECT` by default;
- an operator may explicitly set
  `PX4_GAZEBO_ALLOW_UNVERIFIED_ADVANCED_EFFECTS=true` for metadata-only
  passthrough, but `applied_effects` remains empty, `unsupported_effects` lists
  every request, and `pass_flag` is forced to `false`.

A site-specific custom simulator can implement these effects, but it must emit
its own truthful applied-effect evidence rather than relying on the bundled
runner's passthrough mode.

The same fail-closed rule applies in real mode to non-`nominal`
`scenario_type`, `scenario_config.wind_mps`, non-zero job wind, and non-default
sensor-noise profiles: the bundled local wrapper does not inject them into
Gazebo. Dry-run records these supported fixture perturbations as
`application_mode=dry_run_surrogate`; it never labels them as real physics.

---

## 10) Failure mapping

- Launch command missing/not executable: `ADAPTER_UNAVAILABLE`
- Subprocess timeout: `TIMEOUT`
- Telemetry missing/malformed/empty/non-finite/oversized: `SIMULATION_FAILED`
- Unverified advanced physics request: `UNSUPPORTED_SCENARIO_EFFECT`
- Requested `vehicle_profile.firmware_commit` unavailable or different from
  the observed PX4 Git HEAD: `SIMULATION_FAILED` before launch
- Other unexpected runner exceptions: `SIMULATION_FAILED`

Runner favors predictable JSON output over hard crashes.

---

## 11) Dry-run mode

When `PX4_GAZEBO_DRY_RUN=true`:

- no external PX4/Gazebo process is launched
- deterministic fixture telemetry is generated from trial input
- the same ingestion + metric path is used
- full artifacts + `trial_result.json` are written

This mode exists for CI and developer machines without Gazebo.

---

## 12) Known limitations

- No bundled PX4 workspace, ROS launch files, world assets, or telemetry export stack.
- Real deployments must provide a valid `PX4_GAZEBO_LAUNCH_COMMAND` and any
  local dependencies (source scripts, environment, binaries, plugin paths).
- The runner standardizes contract + metric computation; it does not encode
  site-specific PX4/Gazebo startup logic.
- Bundled real runs are nominal-only until a site launcher implements and
  reports verified disturbance injection. The experiment wizard provides a
  one-click nominal search plus independent nominal-holdout matrix.
- A host-level PX4/Gazebo/MAVSDK port allocator is not bundled; keep real
  simulator concurrency at one trial per host unless the operator configures
  every instance and port consistently.


## 13) Site-specific local wrapper (`local_px4_launch_wrapper.py`)

Use `scripts/simulators/local_px4_launch_wrapper.py` as the lower-level command
behind `px4_gazebo_runner.py`. This repository does **not** bundle PX4-Autopilot
or Gazebo assets; users must install those locally.

Example:

```bash
export REAL_SIMULATOR_COMMAND="python3 /abs/path/scripts/simulators/px4_gazebo_runner.py"
export PX4_GAZEBO_DRY_RUN=false
export PX4_GAZEBO_LAUNCH_COMMAND='python3 /abs/path/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --px4-params {px4_params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}'
export PX4_AUTOPILOT_DIR=/home/chi/PX4-Autopilot
export PX4_SETUP_COMMANDS='source /opt/ros/humble/setup.bash'
# Optional fixed override; leave unset to use each job's simulator model.
unset PX4_MAKE_TARGET
```

Wrapper env vars (with defaults):

- `PX4_AUTOPILOT_DIR` (required in real mode unless custom launch template is provided)
- `PX4_FIRMWARE_COMMIT_OBSERVED` (full SHA fallback only when a custom launcher
  cannot expose a local checkout)
- `PX4_SETUP_COMMANDS` (optional semicolon-separated shell setup commands)
- `PX4_LAUNCH_COMMAND_TEMPLATE` (optional full shell command template)
- `PX4_MAKE_TARGET` (optional site override; ignored unless
  `PX4_FORCE_MAKE_TARGET=true`)
- `PX4_RUN_SECONDS` (default `30`)
- `PX4_READY_TIMEOUT_SECONDS` (default `30`; reserved for site probes)
- `PX4_SITE_DRY_RUN` (default `false`)
- `PX4_TELEMETRY_MODE` (`json` or `ulog`, default `json`)
- `PX4_TELEMETRY_SOURCE_JSON` (optional file path copied/normalized to telemetry output)
- `PX4_ULOG_ROOT` (optional ULog search root when `PX4_TELEMETRY_MODE=ulog`)
- `PX4_ULOG_PATH` (optional explicit ULog file path; overrides `PX4_ULOG_ROOT`)
- `PX4_ENABLE_OFFBOARD_EXECUTOR` (default `true`; run offboard track executor)
- `PX4_OFFBOARD_EXECUTOR_COMMAND` (optional command override; default is
  `python3 scripts/simulators/px4_offboard_track_executor.py`)
- `PX4_OFFBOARD_CONNECTION` (default `udp://:14540`)
- `PX4_OFFBOARD_SETPOINT_RATE_HZ` (default `10`)
- `PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS` (default `30`)
- `PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS` (default `120`)
- `PX4_OFFBOARD_LAND_AFTER` (default `true`)
- `PX4_OFFBOARD_DRY_RUN` (default `false`)
- `PX4_PARAMETER_TRANSPORT` (`environment` or `mavsdk`; default
  `environment`)
- `PX4_PARAMETER_CONNECTION` (default `udp://:14540`)
- `PX4_PARAMETER_TIMEOUT_SECONDS` (default `15`)
- `PX4_PARAMETER_ENFORCE_SAFE_BOUNDS` (default `true`)

Dry-run mode (`PX4_SITE_DRY_RUN=true`) produces deterministic fixture telemetry and
writes `launch_config.json`, `controller_params.used.json`, and
`reference_track.used.json` in the run directory.

Real mode (`PX4_SITE_DRY_RUN=false`) launches PX4 SITL/Gazebo in the background via
`bash -lc`, waits `PX4_READY_TIMEOUT_SECONDS` (simple fixed readiness wait), runs the
offboard executor (when enabled), then terminates the PX4 process group and finalizes
telemetry. If the executor exits non-zero, wrapper exits non-zero.

`scripts/simulators/px4_offboard_track_executor.py`:
- reads `reference_track.json` + `controller_params.json`
- performs takeoff hold then streams offboard setpoints across the path
- enforces vel/accel-limited schedule from controller params
- logs to `<run_dir>/offboard_executor.log`
- requires `mavsdk` for real execution; if missing it exits non-zero with:
  `mavsdk is required for PX4 offboard execution`

Coordinate assumption for first implementation:
- DroneDream x/y/z (z positive-up) -> PX4 NED:
  `north=x`, `east=y`, `down=-z`.
- `controller_params` are applied in the offboard executor schedule and are
  not themselves PX4 internal parameters. Separately selected catalog-backed
  PX4 parameters are transported through `px4_parameters.input.json`: startup
  environment injection plus MAVSDK readback is used for reboot-required
  values, while eligible live values may use transactional MAVSDK apply and
  readback before flight.

When `PX4_TELEMETRY_MODE=ulog`, the wrapper converts PX4 `.ulg` output to the
runner `telemetry.json` schema after the launcher exits:

- ULog selection:
  - if `PX4_ULOG_PATH` is set, that exact file is used
  - otherwise newest `*.ulg` is selected recursively under `PX4_ULOG_ROOT`
  - if `PX4_ULOG_ROOT` is unset, default root is
    `$PX4_AUTOPILOT_DIR/build/px4_sitl_default/rootfs/log`
- Required ULog dataset: `vehicle_local_position`
- Yaw fallback order:
  1. `vehicle_attitude`
  2. `vehicle_attitude_groundtruth`
  3. `vehicle_attitude_setpoint`
  4. velocity-derived yaw (`atan2(vy, vx)`)
  5. `0.0`
- NED→ENU vertical conversion:
  - `z_out = -z`
  - `vz_out = -vz`

Example real-mode config with ULog conversion:

```bash
export PX4_TELEMETRY_MODE=ulog
export PX4_ULOG_ROOT=/home/chi/PX4-Autopilot/build/px4_sitl_default/rootfs/log
```

Inspect recent SITL logs with:

```bash
find ~/PX4-Autopilot -name '*.ulg' -printf '%TY-%Tm-%Td %TH:%TM %p\n' | sort | tail -20
```

ULog conversion unblocks metrics ingestion from real PX4 logs, but meaningful
track-following performance still depends on your offboard controller/mission
stack being active in the PX4/Gazebo run.

Ubuntu 22.04 local sanity check for PX4/Gazebo SITL (outside DroneDream repo):

```bash
cd /path/to/PX4-Autopilot
make px4_sitl gz_x500
```

Do **not** commit PX4-Autopilot into DroneDream.
