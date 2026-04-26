# DroneDream

A web-based drone track simulation and automatic parameter tuning platform.
Users configure a track, start point, altitude, wind, sensor noise, and
optimization objective. The backend creates an asynchronous job, runs a
baseline and optimizer candidate trials, aggregates results, selects the best
parameter set, and surfaces baseline-vs-optimized metrics, best parameters,
charts, summary text, failure details, rerun, and job history in the UI.

> **Status:** Phase 8 — real simulator adapter + iterative GPT parameter
> tuning, layered on top of the Phase 7 MVP. Phase 7 behaviour is
> unchanged: mock + heuristic jobs still run baseline + optimizer trials
> end-to-end and emit a READY `JobReport`. New in Phase 8: per-job
> `simulator_backend` (`mock` or `real_cli`), per-job `optimizer_strategy`
> (`heuristic` or `gpt`), acceptance criteria, an iterative
> simulate-analyze-retune loop, and an OpenAI-backed parameter proposer
> whose API key is stored encrypted and used **server-side only**. See
> [`docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md`](docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md)
> for the full Phase 8 spec (adapter protocol, acceptance logic, env vars,
> demos) and [`docs/ACCEPTANCE_REPORT.md`](docs/ACCEPTANCE_REPORT.md) for
> the Phase 7 acceptance coverage. Auth/login, real drone hardware,
> production multi-worker scaling, and the advanced track editor remain
> explicitly out of scope. PDF job reports are implemented as
> backend-generated downloadable artifacts. Real PX4/Gazebo SITL is
> supported through the `real_cli` + `px4_gazebo_runner` path when an
> external PX4/Gazebo environment is configured.

## Repo layout

```
DroneDream/
  frontend/     # React + TypeScript + Vite app — Dashboard, New Job,
                #   Job Detail, Trial Detail, History / Reports, all
                #   wired to the real backend via TanStack Query.
  backend/      # FastAPI /api/v1 job/trial/report/artifact APIs backed
                #   by SQLAlchemy persistence + standard response
                #   envelope + orchestration package used by the worker.
  worker/       # Database-backed polling worker. Dispatches baseline
                #   and optimizer trials through the SimulatorAdapter
                #   layer; drives the job state machine to COMPLETED
                #   (or FAILED) and writes the JobReport.
  docs/         # Product and engineering documentation
  scripts/      # Dev / check helper scripts
  .env.example  # Environment template
  README.md
```

## Prerequisites

- Node.js ≥ 20 and npm ≥ 10
- Python ≥ 3.11
- (recommended) A virtual environment tool such as `venv` or `uv`

## Setup

```bash
# Clone
git clone https://github.com/ChiZhang-805/DroneDream.git
cd DroneDream

# Copy environment template
cp .env.example .env

# Frontend deps
cd frontend && npm install && cd ..

# Backend deps
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e backend[dev]

# Worker deps. The worker re-uses the backend's ORM models and orchestration
# package, so both are installed editable into the worker venv.
python3 -m venv worker/.venv
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e 'worker[dev]'
```

## Running locally

Open three terminals (or use the helper scripts in `scripts/`).

**Backend** — FastAPI on `http://127.0.0.1:8000`:

```bash
./scripts/dev-backend.sh
# or:
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

Verify the health endpoint:

```bash
curl http://127.0.0.1:8000/health
# {"success":true,"data":{"status":"ok",...},"error":null}
```

**Worker** — polls the DB, runs baseline trials, drives job state machine:

```bash
./scripts/dev-worker.sh
# or:
cd worker && ../worker/.venv/bin/python -m drone_dream_worker.main
```

### Shared local database

The backend and the worker must point at the **same** SQLite DB or the
worker will never see jobs that the backend creates. Both read
`DATABASE_URL` from the environment; when unset, both
`scripts/dev-backend.sh` and `scripts/dev-worker.sh` pin it to an absolute
path under the repo root:

```
DATABASE_URL=sqlite:///<repo-root>/drone_dream.db
```

Both scripts also auto-source the repo-root `.env`, so any `DATABASE_URL=`
you put there is honoured by both processes. The worker no longer
`cd`s into `worker/` before launch, so the default relative SQLite path
also resolves to the same file.

**Smoke check** — after starting both scripts in separate terminals:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"track_type":"circle","altitude_m":5,"sensor_noise_level":"medium","objective_profile":"robust","start_point":{"x":0,"y":0},"wind":{"north":0,"east":0,"south":0,"west":0}}' \
  | tee /tmp/job.json
JOB_ID=$(python3 -c "import json; print(json.load(open('/tmp/job.json'))['data']['id'])")
# Within a few seconds you should see RUNNING (worker picked it up) then
# AGGREGATING -> COMPLETED.
for _ in $(seq 1 30); do
  curl -sS http://127.0.0.1:8000/api/v1/jobs/$JOB_ID | python3 -c \
    'import json,sys;d=json.load(sys.stdin)["data"];print(d["status"],d.get("completed_trial_count"))'
  sleep 1
done
```

If the worker never logs `start_job`, check `DATABASE_URL` in both
terminals — they must match.

### End-to-end demo (happy path)

With the backend and worker running in separate terminals (mock simulator is
the default):

```bash
# Create a job — returns immediately with status=QUEUED.
curl -sS -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"track_type":"circle","altitude_m":5,"sensor_noise_level":"medium","objective_profile":"robust","start_point":{"x":0,"y":0},"wind":{"north":0,"east":0,"south":0,"west":0}}' \
  | tee /tmp/job.json

JOB_ID=$(python3 -c "import json; print(json.load(open('/tmp/job.json'))['data']['id'])")

# Watch progress — transitions QUEUED -> RUNNING -> AGGREGATING -> COMPLETED.
watch -n 1 "curl -sS http://127.0.0.1:8000/api/v1/jobs/$JOB_ID | python3 -m json.tool | grep -E 'status|completed_trials|total_trials'"

# After COMPLETED, the report is ready — baseline vs optimized metrics,
# comparison points, best parameters, and a human-readable summary.
curl -sS http://127.0.0.1:8000/api/v1/jobs/$JOB_ID/report | python3 -m json.tool
```

Or open the frontend at http://localhost:5173 and use the **New Job** form —
the Job Detail page polls every 4 s while the job is active and renders the
baseline metrics, optimized metrics, comparison chart, best parameters, and
summary text once it reaches `COMPLETED`.

### End-to-end demo (failed path)

Restart the worker with the real-simulator stub backend to force every trial
to fail with `ADAPTER_UNAVAILABLE`. The job manager then transitions the job
to `FAILED` with `latest_error.code=ALL_TRIALS_FAILED` and the frontend
renders the structured failure summary on Job Detail.

```bash
SIMULATOR_BACKEND=real_stub ./scripts/dev-worker.sh
# Create a job exactly as above; the Job Detail page shows FAILED with
# per-trial ADAPTER_UNAVAILABLE failure rows.
```

`GET /api/v1/jobs/{job_id}/report` returns a 409 with `error.code=JOB_FAILED`
and `details.failure_code=ALL_TRIALS_FAILED` for failed jobs, so the
frontend never renders a half-filled report.

### End-to-end demo (Phase 8: real_cli + heuristic)

For normal use, leave `SIMULATOR_BACKEND` **unset** (the default in the
shipped `.env.example`) so the per-job selection from the New Job UI is
respected. Only set `REAL_SIMULATOR_COMMAND` / `REAL_SIMULATOR_ARTIFACT_ROOT`
so the `real_cli` adapter has a simulator to invoke:

```bash
export REAL_SIMULATOR_COMMAND="$(which python) $(pwd)/scripts/simulators/example_real_simulator.py"
export REAL_SIMULATOR_ARTIFACT_ROOT="$(pwd)/.artifacts"
# Do NOT export SIMULATOR_BACKEND — that would globally override the UI
# selection. Only set it (e.g. SIMULATOR_BACKEND=real_cli) when you
# intentionally want every job to use a specific backend regardless of
# what the New Job form specifies.
./scripts/dev-worker.sh
```

Then in the **New Job** form pick `Simulator Backend = real_cli` (default
optimizer strategy is `gpt` with default `max_iterations=20`). Heuristic jobs keep the Phase 7 batch
behaviour — baseline and all heuristic optimizer candidates are dispatched
up front, then acceptance criteria annotate `optimization_outcome`. Only
GPT jobs (`optimizer_strategy=gpt`) use the iterative one-proposal-per-
generation loop described in
[`docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md`](docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md).

### PX4/Gazebo runner (real_cli target)

`scripts/simulators/px4_gazebo_runner.py` is a **real_cli protocol wrapper**
for PX4/Gazebo environments. It is intentionally environment-driven: this repo
does **not** include a full PX4 workspace, world assets, ROS graph contracts,
or telemetry exporters. Use it as:

```bash
export REAL_SIMULATOR_COMMAND="python3 $(pwd)/scripts/simulators/px4_gazebo_runner.py"
```

Then configure one of two modes:

1) **Dry-run mode (CI/dev, no Gazebo required):**

```bash
export PX4_GAZEBO_DRY_RUN=true
```

The runner deterministically generates fixture telemetry, computes the same
metrics pipeline used in real mode, writes trial artifacts, and returns a
normal `trial_result.json`.

2) **Real launch mode (local PX4/Gazebo installed):**

```bash
export PX4_GAZEBO_DRY_RUN=false
export PX4_GAZEBO_LAUNCH_COMMAND='bash /abs/path/launch_px4_gz.sh --telemetry {telemetry_json} --params {params_json} --track {track_json}'
```

`PX4_GAZEBO_LAUNCH_COMMAND` supports template tokens (for example
`{run_dir}`, `{trial_input}`, `{telemetry_json}`, `{stdout_log}`, `{trial_id}`,
etc.) so site-specific launchers can adapt without editing Python.

If dry-run is disabled and launch command/binaries are unavailable, the runner
returns `success=false` with `failure.code=ADAPTER_UNAVAILABLE` instead of
pretending real PX4 support is present.

For the full contract, telemetry schema, metrics, failure mapping, and
limitations, see [`docs/PX4_GAZEBO_RUNNER.md`](docs/PX4_GAZEBO_RUNNER.md).
For PR3 visualization options (browser trajectory replay + optional Runpod
noVNC iframe), see
[`docs/RUNPOD_GAZEBO_VISUALIZATION.md`](docs/RUNPOD_GAZEBO_VISUALIZATION.md).
PR5 extends this flow with optional auto-launch of the Gazebo GUI client
(`gz sim -g`) for noVNC live view when explicitly enabled.
GUI demo mode can also optionally draw the generated reference track in Gazebo
using marker artifacts; see
[`docs/RUNPOD_GAZEBO_VISUALIZATION.md`](docs/RUNPOD_GAZEBO_VISUALIZATION.md).

For real PX4 runs, metric pass/fail now uses a track-following **evaluation
window** (offboard timing metadata when available, otherwise telemetry-derived
altitude/path heuristics). Raw telemetry/trajectory artifacts still include the
full flight log (preflight, takeoff, transition, and landing), while RMSE and
max-error intentionally focus on the actual track-following interval.

For site-specific startup logic, use `scripts/simulators/local_px4_launch_wrapper.py`
as the `PX4_GAZEBO_LAUNCH_COMMAND` target. It supports `PX4_SITE_DRY_RUN=true`
for CI/dev without PX4, and real local launches when `PX4_AUTOPILOT_DIR` and
related env vars are provided. The repo does not bundle PX4/Gazebo assets; install
PX4/Gazebo locally and keep external workspaces outside this repository.

For real runs that produce PX4 ULog output, set `PX4_TELEMETRY_MODE=ulog` so the
wrapper converts `.ulg` to the expected `telemetry.json` schema. Optional env vars:
`PX4_ULOG_PATH` (exact file) and `PX4_ULOG_ROOT` (search root for newest `*.ulg`;
defaults to `$PX4_AUTOPILOT_DIR/build/px4_sitl_default/rootfs/log`). This enables
metrics from actual PX4 logs, though full track-following quality still depends on
your offboard controller/mission layer being active.

The repo now includes `scripts/simulators/px4_offboard_track_executor.py` and
`local_px4_launch_wrapper.py` can run it while PX4 SITL is alive. Enable with:

- `PX4_ENABLE_OFFBOARD_EXECUTOR=true` (default in wrapper)
- `PX4_OFFBOARD_CONNECTION=udp://:14540`
- `PX4_OFFBOARD_SETPOINT_RATE_HZ=10`
- `PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS=30`
- `PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS=120`
- `PX4_OFFBOARD_LAND_AFTER=true`
- optional `PX4_OFFBOARD_EXECUTOR_COMMAND` override

The executor reads `reference_track.json` and `controller_params.json`,
builds a vel/accel-limited setpoint stream, performs takeoff-hold + track
following, and sends MAVSDK offboard position setpoints. `controller_params`
are applied in this executor schedule logic (not by writing PX4 internal params).
Current mapping assumption is DroneDream x/y/z (z positive-up) → PX4 local NED
north/east/down via `(north=x, east=y, down=-z)`.

Example `.env` excerpt for real PX4/Gazebo path:

```bash
REAL_SIMULATOR_COMMAND="python3 /home/chi/DroneDream/scripts/simulators/px4_gazebo_runner.py"
PX4_GAZEBO_DRY_RUN=false
PX4_GAZEBO_LAUNCH_COMMAND="/home/chi/PX4-Autopilot/.venv/bin/python /home/chi/DroneDream/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --world {world} --headless {headless}"
PX4_SITE_DRY_RUN=false
PX4_AUTOPILOT_DIR=/home/chi/PX4-Autopilot
PX4_SETUP_COMMANDS="source /home/chi/PX4-Autopilot/.venv/bin/activate"
PX4_MAKE_TARGET=gz_x500
PX4_TELEMETRY_MODE=ulog
PX4_ULOG_ROOT=/home/chi/PX4-Autopilot/build/px4_sitl_default/rootfs/log
PX4_ENABLE_OFFBOARD_EXECUTOR=true
PX4_OFFBOARD_CONNECTION=udp://:14540
```

### End-to-end demo (Phase 8: GPT parameter tuning)

`APP_SECRET_KEY` (or `DRONEDREAM_SECRET_KEY`) is used by the **backend** to
encrypt the per-job OpenAI API key at submission time, and by the
**worker** to decrypt it when calling OpenAI. Both processes must see the
same value — otherwise job creation fails with
`details.reason = "server_secret_key_not_configured"`, or the worker can't
decrypt an already-submitted key. Recommended local setup: put it in the
root-level `.env` (both dev scripts source it), or export it in each
terminal before launching `./scripts/dev-backend.sh` and
`./scripts/dev-worker.sh`.

```bash
# One-time: generate and stash in root-level .env so both scripts see it.
echo "APP_SECRET_KEY=$(backend/.venv/bin/python -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  >> .env

# Terminal A
./scripts/dev-backend.sh
# Terminal B
./scripts/dev-worker.sh
```

In the **New Job** form pick `Optimizer Strategy = gpt` and paste your
OpenAI API key into the auto-tuning section. The key is encrypted with
`APP_SECRET_KEY`, used server-side only, and soft-deleted when the job
terminates. See
[`docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md`](docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md)
for the full protocol, env vars, and `real_cli + gpt` combined demo.

When GPT search budget is exhausted, the job now completes with a best-so-far
report (`optimization_outcome=max_iterations_reached` or
`no_usable_candidate`) instead of being marked as a system failure.

**Frontend** — Vite dev server on `http://localhost:5173`:

```bash
./scripts/dev-frontend.sh
# or:
cd frontend && npm run dev
```

## Quality checks

```bash
# Frontend: type-check + lint + build + Vitest regression suite
cd frontend && npm run typecheck && npm run lint && npm run build && npm test

# Backend: lint + type-check + tests
backend/.venv/bin/ruff check backend
backend/.venv/bin/mypy backend/app
backend/.venv/bin/pytest backend

# Worker: lint
worker/.venv/bin/ruff check worker

# Aggregate check (runs the above when tools are available). Local mode
# silently skips checks whose toolchain isn't installed; CI mode treats
# missing toolchains as hard failures:
./scripts/check.sh
CHECK_STRICT=1 ./scripts/check.sh      # or: ./scripts/check.sh --strict
```

GitHub Actions runs the same commands on every PR and push to `main`
(`.github/workflows/ci.yml`).

## API conventions

All public APIs live under the `/api/v1` namespace and use a standard response
envelope:

```jsonc
// success
{ "success": true,  "data": { /* ... */ }, "error": null }

// error
{ "success": false, "data": null,
  "error": { "code": "INVALID_INPUT", "message": "...", "details": null } }
```

`GET /health` is intentionally outside `/api/v1` and used for liveness probes.

## Phase plan

See [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md) for the full
phase plan, stack rationale, and architecture notes. Product documents live in
[`docs/`](docs/) (PRD, architecture, API spec, data model, UI spec, acceptance
criteria, execution plan).
