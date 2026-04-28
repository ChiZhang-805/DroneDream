# DroneDream Architecture

## Repository layout

- `frontend/`: React + TypeScript + Vite UI (job creation, history, compare, batch pages).
- `backend/`: FastAPI + SQLAlchemy REST API and artifact/report endpoints.
- `worker/`: orchestration runner polling queued jobs and executing trials.
- `scripts/`: dev checks and PX4/Gazebo simulator helper scripts.
- `docs/`: product and implementation docs.

## Job lifecycle

1. `POST /api/v1/jobs` creates a Job in `QUEUED`.
2. Worker picks queued jobs, updates state to `RUNNING`.
3. Worker creates/executess trial rows by optimizer generation.
4. Aggregation computes per-candidate and per-job metrics.
5. Report generation writes report + artifacts.
6. Job lands in terminal state (`COMPLETED` / `FAILED` / `CANCELLED`).

Current implementation keeps orchestration in `backend/app/orchestration/` and does **not** change job execution logic when using batch jobs.

## Batch layer (organization only)

Batch is a grouping model (`BatchJob`) that links many normal `Job` rows through `jobs.batch_id`.

- Batch creation validates all child job configs first.
- If any child is invalid, request is rejected and no job is created.
- Batch progress/status is aggregated from child job statuses.

## Simulator adapter architecture

Simulator abstraction is under `backend/app/simulator/`:

- `base.py`: adapter contract.
- `mock.py`: deterministic local mock.
- `real_cli.py`: integration with external PX4/Gazebo scripts.
- `factory.py`: backend selector (`mock` / `real_cli`).

## Optimizer architecture

Optimizer logic lives in `backend/app/orchestration/optimizer.py` and related modules:

- `heuristic`: built-in search.
- `gpt`: LLM-assisted proposal via secure API-key storage.
- `cma_es`: evolutionary search in `cma_es_optimizer.py`.

## Artifact/report architecture

- Artifacts metadata: `backend/app/models.py` (`Artifact`).
- Artifact storage: `backend/app/storage/` (local/S3 adapters).
- Report API: `GET /api/v1/jobs/{job_id}/report`.
- Artifact API: list via `/jobs/{job_id}/artifacts`, download via `/artifacts/{artifact_id}/download`.

## Roadmap

- Add parameter-sweep UI for batch creation (currently JSON textarea input only).
- Add richer batch analytics charts in frontend.
