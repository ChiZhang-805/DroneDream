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
> the Phase 7 acceptance coverage. Real PX4/Gazebo, auth, PDF export, and
> the advanced track editor remain explicitly out of scope.

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

```bash
export REAL_SIMULATOR_COMMAND="$(which python) $(pwd)/scripts/simulators/example_real_simulator.py"
export REAL_SIMULATOR_ARTIFACT_ROOT="$(pwd)/.artifacts"
./scripts/dev-worker.sh
```

Then in the **New Job** form pick `Simulator Backend = real_cli` (default
optimizer strategy is `heuristic`). The iterative loop runs baseline, then
heuristic generations, until acceptance or `max_iterations`.

### End-to-end demo (Phase 8: GPT parameter tuning)

```bash
export APP_SECRET_KEY="$(backend/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
./scripts/dev-worker.sh
```

In the **New Job** form pick `Optimizer Strategy = gpt` and paste your
OpenAI API key into the auto-tuning section. The key is encrypted with
`APP_SECRET_KEY`, used server-side only, and soft-deleted when the job
terminates. See
[`docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md`](docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md)
for the full protocol, env vars, and `real_cli + gpt` combined demo.

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
