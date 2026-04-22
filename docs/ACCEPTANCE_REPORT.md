# DroneDream MVP — Phase 7 Acceptance Report

- **Scope**: DroneDream MVP end-to-end acceptance against the Master
  Directive + Phase 7 checklist.
- **Stack**: FastAPI backend + SQLite + mock simulator, Python polling
  worker, React/TypeScript/Vite frontend.
- **Simulator**: mock adapter is the default (`SIMULATOR_BACKEND=mock`).
  A real-simulator stub (`real_stub`) is wired through the same adapter
  selection surface so the failure flow is demonstrable without PX4/Gazebo.

## 1. Executive summary

The MVP passes the Phase 7 acceptance checklist. A user can create a job
from the UI, observe it transition through `QUEUED → RUNNING → AGGREGATING
→ COMPLETED`, and inspect baseline metrics, optimized metrics, best
parameters, a baseline-vs-optimized comparison chart, summary text, full
job history, per-trial details, and rerun. A failed job surfaces a
user-readable failure summary on Job Detail with the underlying
per-trial `failure_code` rows. All state transitions are driven by
backend logic (job manager + worker + aggregation); no frontend fake
timers exist. All API responses use the standard envelope; all enums
match the spec; all required endpoints are present.

## 2. What passes

### 2.1 Product-level

| Criterion                                                    | Status |
| ------------------------------------------------------------ | :----: |
| User can create a job from the New Job page                  |   ✅   |
| Job is persisted in SQLite                                   |   ✅   |
| Job enters `QUEUED` immediately, then `RUNNING` via backend  |   ✅   |
| User can observe job progress (polling every 4 s)            |   ✅   |
| Completed job shows baseline metrics                         |   ✅   |
| Completed job shows optimized metrics                        |   ✅   |
| Completed job shows best parameters                          |   ✅   |
| Completed job shows baseline-vs-optimized comparison chart   |   ✅   |
| Completed job shows summary text (locally generated)         |   ✅   |
| Failed job shows readable failure summary + per-trial reason |   ✅   |
| User can rerun a job; original preserved (`source_job_id`)   |   ✅   |
| Dashboard and History both list previous jobs                |   ✅   |

### 2.2 Page-level

- **Dashboard** — title, `+ New Job` CTA, status-summary metric cards,
  recent-jobs table, loading/empty/error states.
- **New Job** — all required fields with documented defaults, client-side
  + backend validation, submit flow preserves user input on failure, error
  surfaced via `Alert`.
- **Job Detail** — renders all job statuses: `CREATED` (transient),
  `QUEUED`, `RUNNING`, `AGGREGATING`, `COMPLETED`, `FAILED`, `CANCELLED`.
  Polls every 4 s while active. Rerun + cancel actions honour terminal
  states.
- **Trial Detail** — metadata, metrics, failure reason + log excerpt when
  failed, linked artifact metadata.
- **History / Reports** — filterable job list with direct links to Job
  Detail.

### 2.3 API-level

All endpoints live under `/api/v1`, use the standard envelope, and reject
extra fields.

| Endpoint                                    | Verified |
| ------------------------------------------- | :------: |
| `POST   /api/v1/jobs`                       |    ✅    |
| `GET    /api/v1/jobs` (+ `status=` filter)  |    ✅    |
| `GET    /api/v1/jobs/{job_id}`              |    ✅    |
| `POST   /api/v1/jobs/{job_id}/rerun`        |    ✅    |
| `POST   /api/v1/jobs/{job_id}/cancel`       |    ✅    |
| `GET    /api/v1/jobs/{job_id}/trials`       |    ✅    |
| `GET    /api/v1/trials/{trial_id}`          |    ✅    |
| `GET    /api/v1/jobs/{job_id}/report`       |    ✅    |
| `GET    /api/v1/jobs/{job_id}/artifacts`    |    ✅    |

Structured errors:

- `JOB_NOT_FOUND` (404), `TRIAL_NOT_FOUND` (404),
  `REPORT_NOT_READY` (409), `JOB_FAILED` (409), `JOB_CANCELLED` (409),
  `JOB_ALREADY_CANCELLED` (409), `JOB_ALREADY_COMPLETED` (409),
  `JOB_NOT_RUNNABLE` (409), `INVALID_INPUT` (422).

### 2.4 Data-level

- `Job`, `CandidateParameterSet`, `Trial`, `TrialMetric`, `JobReport`,
  `Artifact`, `JobEvent` all persist as separate tables and are queryable
  via the ORM.
- Job status changes persist (see `JobEvent` diagnostics panel).
- Baseline candidate exists as its own `CandidateParameterSet` row
  (`is_baseline=True`, `source_type="baseline"`).
- Optimizer candidates are independent rows (`source_type="optimizer"`,
  `generation_index` 1..N).
- Best candidate is uniquely identifiable: exactly one candidate has
  `is_best=True`, and `Job.best_candidate_id` + `JobReport.best_candidate_id`
  point to it.
- Trial records persist with `TrialMetric` rows for completed trials.
- Completed jobs have a `JobReport` with `report_status="READY"`, baseline
  + optimized aggregates, 5-point comparison list, and best-parameters map.
- Artifact metadata rows (comparison plot, trajectory plot, worker log,
  telemetry JSON) are queryable per-job.
- `JobEvent` rows cover the major lifecycle events: `job_created`,
  `job_queued`, `job_started`, `baseline_started`, `optimizer_started`,
  `optimizer_candidate_created`, `trial_dispatched`, `trial_completed`,
  `aggregation_started`, `best_candidate_selected`, `job_completed`,
  `job_cancelled`.

### 2.5 State machines

- **Job**: `CREATED → QUEUED → RUNNING → AGGREGATING → COMPLETED`,
  or `FAILED` / `CANCELLED` from any non-terminal state. Terminal states
  are `COMPLETED`, `FAILED`, `CANCELLED` and a terminal job cannot be
  cancelled again (`JOB_ALREADY_COMPLETED` / `JOB_ALREADY_CANCELLED`).
- **Trial**: `PENDING → RUNNING → COMPLETED`, or `FAILED` / `CANCELLED`.
- **Report**: `PENDING → READY`, or `FAILED` (not produced on
  `ALL_TRIALS_FAILED`).

### 2.6 Async / worker

- `POST /api/v1/jobs` returns in milliseconds with `status=QUEUED`.
- Trial execution happens entirely in the worker process
  (`drone_dream_worker.main` → `app.orchestration.runner.run_forever`).
- Worker failures persist as `Trial.status=FAILED` with structured
  `failure_code` + `failure_reason`. Adapter crashes are captured via the
  trial executor's `try/except` and mapped to `SIMULATION_FAILED`.
- Timeout / instability / adapter-unavailable are representable
  (`FAILURE_TIMEOUT`, `FAILURE_UNSTABLE`, `FAILURE_ADAPTER_UNAVAILABLE`).
- Mock simulator mode completes the full MVP flow in under 15 ticks
  (13 trials per job: 4 baseline + 3×3 optimizer).

### 2.7 Edge cases

Validation covered by schema + pytest:

- Missing required fields → defaults applied, or `INVALID_INPUT` when
  type-invalid.
- Invalid enum values (`track_type`, `sensor_noise_level`,
  `objective_profile`) → `422 INVALID_INPUT`.
- Altitude out of `[1.0, 20.0]` → `422 INVALID_INPUT`.
- Wind component out of `[-10, 10]` → `422 INVALID_INPUT`.
- Unknown field → `422 INVALID_INPUT` (schemas use `extra="forbid"`).
- Job not found → `404 JOB_NOT_FOUND` (structured).
- Trial not found → `404 TRIAL_NOT_FOUND` (structured).
- Report not ready → `409 REPORT_NOT_READY` (structured).
- Failed job report → `409 JOB_FAILED` with `details.failure_code`.
- Cancelled job report → `409 JOB_CANCELLED`.
- Page load errors render via shared `ErrorState` component with a Retry
  button.
- Form submission failure does not clear `NewJob` user input (state is
  only mutated by user typing; `submitError` is rendered alongside the
  preserved form).

## 3. How to run the demo

### 3.1 Setup

```bash
cp .env.example .env

# Backend
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'

# Worker (reuses backend models)
python3 -m venv worker/.venv
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e 'worker[dev]'

# Frontend
cd frontend && npm install && cd ..
```

### 3.2 Run the stack

Open three terminals (or use the helper scripts):

```bash
# Terminal 1 — backend
./scripts/dev-backend.sh

# Terminal 2 — worker (mock simulator)
./scripts/dev-worker.sh

# Terminal 3 — frontend
./scripts/dev-frontend.sh
```

Then visit http://localhost:5173.

### 3.3 Trigger the successful flow

1. Open the frontend, click **+ New Job**.
2. Keep the defaults (`circle`, altitude `3.0`, zero wind, medium noise,
   `robust` objective) and submit.
3. You are redirected to Job Detail. Status flips to `RUNNING`, then
   `AGGREGATING`, then `COMPLETED` within ~10–15 seconds.
4. Job Detail renders baseline metrics, optimized metrics, the
   baseline-vs-optimized comparison chart, best parameters, and summary
   text.
5. Dashboard and History now include the job.
6. Click **Rerun** on Job Detail — a new job is created with
   `source_job_id` pointing at the original; the original still exists
   unchanged.

Equivalent API script is in [`README.md`](../README.md#end-to-end-demo-happy-path).

### 3.4 Trigger / observe the failed flow

Stop the worker (Ctrl-C) and restart it with the stub backend:

```bash
SIMULATOR_BACKEND=real_stub ./scripts/dev-worker.sh
```

Create a job from the UI as above. Every trial fails with
`ADAPTER_UNAVAILABLE`, the job manager transitions the job to `FAILED`
with `latest_error.code=ALL_TRIALS_FAILED`, and Job Detail renders:

- A top-level red alert with the failure summary.
- Per-trial failure rows with `ADAPTER_UNAVAILABLE` codes.
- A `JOB_FAILED` error banner on the Report section (since the report is
  not produced when every baseline trial fails).

`GET /api/v1/jobs/{job_id}/report` returns `409 JOB_FAILED` with
`details.failure_code=ALL_TRIALS_FAILED`.

## 4. Checks executed

Full quality gate (also runnable via `./scripts/check.sh`):

| Check                                         | Result             |
| --------------------------------------------- | ------------------ |
| `backend/.venv/bin/pytest backend`            | **78 passed**      |
| `backend/.venv/bin/ruff check backend`        | clean              |
| `backend/.venv/bin/mypy backend/app`          | clean (28 files)   |
| `worker/.venv/bin/ruff check worker`          | clean              |
| `cd frontend && npm run typecheck`            | clean              |
| `cd frontend && npm run lint`                 | clean              |
| `cd frontend && npm run build`                | clean (Vite)       |
| End-to-end mock run (`runner.tick` loop)      | `COMPLETED`, 13/13 |
| End-to-end failed run (`SIMULATOR_BACKEND=real_stub`) | `FAILED`, `ALL_TRIALS_FAILED` |

New Phase 7 regression tests added in
`backend/tests/test_orchestration.py`:

- `test_real_stub_backend_marks_job_failed_with_readable_error`
- `test_terminal_job_rejects_further_cancellation`
- `test_report_for_failed_job_returns_structured_failure`
- `test_list_jobs_filters_by_status`

## 5. What remains limited (by design)

The following are explicitly out of scope for the MVP and not regressed:

- No real PX4/Gazebo simulator — `SIMULATOR_BACKEND=real_stub` is a
  placeholder that always returns `ADAPTER_UNAVAILABLE`.
- No authentication / authorization — every request runs as a default
  user (`usr_…`) seeded on first use.
- No PDF export of the report — the frontend renders a structured HTML
  view only.
- No advanced track editor — `track_type` is a flat enum
  (`circle | u_turn | lemniscate`).
- Artifact storage is metadata-only (`storage_path` uses a `mock://`
  URI). No bytes are written.
- SQLite only; Postgres is the documented migration target but not
  wired.
- Single worker process. The trial claim uses a straightforward
  `SELECT ... ORDER BY queued_at` + `UPDATE` pattern which is safe for
  one worker against SQLite; multi-worker would need leased claims.
- LLM integration is absent entirely. The summary text is generated
  locally from structured aggregates (no external call).

## 6. Confirmation

Phase 7 hardening is complete. The MVP runs end-to-end in mock simulator
mode, the failed-flow demo is reproducible via `SIMULATOR_BACKEND=
real_stub`, all backend + worker + frontend checks pass, and the
acceptance report documents the passing surface and the limitations.
