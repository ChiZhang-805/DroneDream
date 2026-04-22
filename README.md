# DroneDream

A web-based drone track simulation and automatic parameter tuning platform.
Users configure a track, start point, altitude, wind, sensor noise, and
optimization objective. The backend creates an asynchronous job, runs a
baseline and optimizer candidate trials, aggregates results, selects the best
parameter set, and surfaces baseline-vs-optimized metrics, best parameters,
charts, summary text, failure details, rerun, and job history in the UI.

> **Status:** Phase 7 — MVP acceptance ready. Creating a job persists a
> `QUEUED` record; a separate worker process picks it up, dispatches baseline
> + optimizer trials, runs deterministic mock simulations, aggregates
> metrics into a `READY` `JobReport` with baseline-vs-optimized comparison
> + summary text, and moves the job to `COMPLETED` (or `FAILED`). The
> frontend renders the full flow end-to-end against the real backend. Real
> PX4/Gazebo integration remains out of scope — see
> [`docs/ACCEPTANCE_REPORT.md`](docs/ACCEPTANCE_REPORT.md) for the full
> acceptance coverage and demo walkthrough.

## Repo layout

```
DroneDream/
  frontend/     # React + TypeScript + Vite app shell
  backend/      # FastAPI app (health endpoint + response envelope)
  worker/       # Python worker entrypoint (logs start/stop only)
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

**Frontend** — Vite dev server on `http://localhost:5173`:

```bash
./scripts/dev-frontend.sh
# or:
cd frontend && npm run dev
```

## Quality checks

```bash
# Frontend: type-check + build + lint
cd frontend && npm run typecheck && npm run lint && npm run build

# Backend: lint + type-check + tests
backend/.venv/bin/ruff check backend
backend/.venv/bin/mypy backend/app
backend/.venv/bin/pytest backend

# Aggregate check (runs the above when tools are available):
./scripts/check.sh
```

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
