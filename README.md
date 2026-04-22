# DroneDream

A web-based drone track simulation and automatic parameter tuning platform.
Users configure a track, start point, altitude, wind, sensor noise, and
optimization objective. The backend creates an asynchronous job, runs a
baseline and optimizer candidate trials, aggregates results, selects the best
parameter set, and surfaces baseline-vs-optimized metrics, best parameters,
charts, summary text, failure details, rerun, and job history in the UI.

> **Status:** Phase 0 — repo bootstrap only. Frontend, backend, and worker are
> runnable skeletons. Real job creation, simulator logic, and optimization are
> not yet implemented.

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

# Worker deps (separate venv keeps worker deployable independently)
python3 -m venv worker/.venv
worker/.venv/bin/pip install -e worker
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

**Worker** — polling stub, logs startup/shutdown only:

```bash
./scripts/dev-worker.sh
# or:
worker/.venv/bin/python -m app.main
```

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
