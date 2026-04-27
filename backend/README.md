# DroneDream Backend

FastAPI app for the DroneDream MVP. Ships the full `/api/v1` surface
(jobs, trials, report, artifacts) backed by SQLAlchemy persistence, plus
the standard response envelope helpers and the orchestration package the
worker uses to dispatch and finalize jobs.

## What lives here

- `app/main.py` — FastAPI application factory, CORS, exception handlers,
  router registration.
- `app/routers/` — HTTP surface:
  - `health` — `GET /health` (liveness, outside `/api/v1`).
  - `jobs` — `POST/GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`,
    `POST /api/v1/jobs/{job_id}/rerun`, `POST /api/v1/jobs/{job_id}/cancel`,
    `GET /api/v1/jobs/{job_id}/trials`,
    `GET /api/v1/jobs/{job_id}/report`,
    `GET /api/v1/jobs/{job_id}/artifacts`.
  - `trials` — `GET /api/v1/trials/{trial_id}`.
- `app/schemas.py` — Pydantic v2 request/response models + enum literals.
- `app/models.py` — SQLAlchemy ORM models: `User`, `Job`,
  `CandidateParameterSet`, `Trial`, `TrialMetric`, `JobReport`,
  `Artifact`, `JobEvent`.
- `app/services/` — request-safe business logic (create / list / rerun /
  cancel / serialize). Never runs a trial.
- `app/orchestration/` — worker-side job manager, trial executor,
  aggregator, optimizer, report generator. Shared with the worker
  process via an editable install.
- `app/simulator/` — `SimulatorAdapter` base, `MockSimulatorAdapter`
  (default MVP path), `RealSimulatorAdapterStub` (structured failure
  placeholder for future PX4/Gazebo work).
- `app/response.py` — `ok(data)` / `err(code, message, details)` helpers
  that emit the standard response envelope.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/uvicorn app.main:app --reload --app-dir . --host 127.0.0.1 --port 8000
```

## Quality checks

```bash
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest
```

## Key environment variables

- Worker lease / reclaim:
  - `WORKER_LEASE_SECONDS` (default `900`)
  - `WORKER_STALE_RUNNING_RECLAIM_ENABLED` (default `true`)
- Artifact storage backend:
  - `ARTIFACT_STORAGE_BACKEND=local|s3` (default `local`)
  - `S3_ENDPOINT_URL` (optional, for MinIO/custom endpoints)
  - `S3_REGION` (optional)
  - `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
  - `S3_PREFIX` (optional, default `dronedream/`)
- Optional auth:
  - `AUTH_MODE=disabled|demo_token` (default `disabled`)
  - `DEMO_AUTH_TOKENS` format:
    `user1@example.com:token1,user2@example.com:token2`
