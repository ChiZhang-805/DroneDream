# DroneDream Architecture

## System overview

DroneDream is a three-process system:

- **Frontend (`frontend/`)**: React + TypeScript UI for creating optimization experiments, viewing progress, comparing completed jobs, and browsing artifacts/reports. The retired batch UI is intentionally not exposed.
- **Backend (`backend/`)**: FastAPI + SQLAlchemy API, persistence layer, report/artifact metadata APIs, auth envelope, and request validation.
- **Worker (`worker/`)**: async polling runner that claims queued jobs and executes trial loops via simulator + optimizer adapters.

## Runtime data flow

1. Client submits `POST /api/v1/jobs` or `POST /api/v1/batches`.
2. Backend persists `Job` (and optionally `BatchJob`) rows with initial status.
3. Worker claims queued jobs and executes orchestration in `backend/app/orchestration/`.
4. Simulator adapter returns trial telemetry.
5. Aggregation + acceptance logic picks best candidate and writes report/artifact metadata.
6. API surfaces job/trial/report state to the current frontend. Batch endpoints remain a compatibility and automation API.

## Backend layering

- **Routers**: `backend/app/routers/`
- **Services (state transitions + serialization)**: `backend/app/services/jobs.py`
- **Orchestration (worker-side lifecycle)**: `backend/app/orchestration/`
- **Simulator adapters**: `backend/app/simulator/`
- **Storage adapters**: `backend/app/storage/`
- **ORM + DB bootstrap**: `backend/app/models.py`, `backend/app/db.py`

## Data model highlights

- `Job` is the execution unit.
- `BatchJob` groups multiple `Job` rows via `jobs.batch_id`.
- Batch status is computed from child job statuses (aggregated, not independently orchestrated).
- SQLite remains convenient for local development; deployed databases use the
  reviewed Alembic migration chain under `backend/alembic/`.

## Current capabilities

- Job create/list/detail/cancel/rerun.
- Trial detail/list and report/artifact APIs.
- Batch create/list/detail/list-jobs/cancel.
- Batch creation validates all child jobs up front; invalid child rejects whole request.
- Optimizer strategies: `none`, `heuristic`, `gpt`, `cma_es`, plus the seven
  experimental engines documented in `09-optimizer-guide.md`.
- Simulator backends: `mock`, `real_cli`.

## Limitations / roadmap

- Batch endpoints remain available for compatibility and external automation, but the desktop navigation does not expose a batch-creation page.
- Batch analytics are basic counts/progress, not full statistical dashboards.
- Real PX4/Gazebo execution still requires a site runtime, and verified
  disturbance injection remains site-specific.
