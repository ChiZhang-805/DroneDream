# DroneDream — Implementation Notes

This document complements the product docs in [`docs/`](./). It captures the
engineering stack, local commands, and phase plan.

## Stack

| Layer     | Choice                                                                 | Rationale                                                                 |
|-----------|------------------------------------------------------------------------|---------------------------------------------------------------------------|
| Frontend  | React 18 + TypeScript + Vite + React Router + TanStack Query           | Fast dev loop, strong typing, idiomatic routing and server-state caching. |
| Backend   | Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy 2                     | Async-friendly API, typed request/response models, ORM ready for Postgres.|
| Database  | SQLite (local MVP), structured for Postgres later                      | Zero-config for MVP; switch via `DATABASE_URL`.                           |
| Worker    | Plain Python process polling a DB-backed queue                         | Simple, avoids Redis/Celery in MVP; replaceable later.                    |
| Charts    | Recharts                                                               | Simple React chart primitives, good DX.                                   |
| Tests     | `pytest` (backend), Vite build + `tsc --noEmit` + ESLint (frontend)    | Focused, fast feedback; more coverage added per phase.                    |

## Monorepo layout

```
DroneDream/
  frontend/     # React + TS + Vite app shell, router stubs for all required pages
  backend/      # FastAPI app; /health endpoint and response envelope helper
  worker/       # Python worker entrypoint (logs start/stop; no trial execution yet)
  docs/         # Product docs + this file
  scripts/      # Dev/check helper scripts
  .env.example  # Environment variable template
  README.md     # How to set up and run the project locally
```

## Local commands

```bash
# Frontend
cd frontend
npm install
npm run dev         # Vite dev server
npm run build       # type-check + bundle
npm run lint        # ESLint
npm run typecheck   # tsc --noEmit

# Backend
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e backend[dev]
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend
backend/.venv/bin/pytest backend
backend/.venv/bin/ruff check backend
backend/.venv/bin/mypy backend/app

# Worker
python3 -m venv worker/.venv
worker/.venv/bin/pip install -e worker
worker/.venv/bin/python -m app.main
```

Helper scripts in [`scripts/`](../scripts/) wrap these commands.

## Response envelope

Every `/api/v1` endpoint returns a uniform envelope:

```python
# Success
{"success": True,  "data": {...}, "error": None}

# Error
{"success": False, "data": None, "error": {
    "code": "INVALID_INPUT", "message": "...", "details": None,
}}
```

Implemented by [`backend/app/response.py`](../backend/app/response.py).
`/health` is deliberately outside `/api/v1` and returns the same shape so that
probes and future dashboards can share parsing logic.

## Enums (locked contract)

- **Job status:** `CREATED | QUEUED | RUNNING | AGGREGATING | COMPLETED | FAILED | CANCELLED`
- **Trial status:** `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`
- **Track type:** `circle | u_turn | lemniscate`
- **Sensor noise:** `low | medium | high`
- **Objective profile:** `stable | fast | smooth | robust | custom`

These will be introduced as typed enums in Phase 1; they are listed here so
reviewers see the full vocabulary up front.

## Phase plan

- **Phase 0 — Repo Bootstrap (this PR).**
  Monorepo skeleton, runnable frontend/backend/worker, docs, env template,
  quality-gate scripts. No domain logic.
- **Phase 1 — Data model & migrations.**
  SQLAlchemy models for `User`, `Job`, `CandidateParameterSet`, `Trial`,
  `TrialMetric`, `JobReport`, `Artifact`, `JobEvent`. Kept as separate tables
  per constraint #5; candidate ≠ trial (constraint #6).
- **Phase 2 — Job lifecycle API.**
  `POST /api/v1/jobs` returns immediately with `{job_id, status: QUEUED}`
  (constraint #3). `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`,
  `POST /api/v1/jobs/{id}/rerun`, `POST /api/v1/jobs/{id}/cancel`. Strict
  Pydantic validation of the New Job input (ranges, enums, defaults).
- **Phase 3 — Worker & orchestration.**
  Worker polls DB queue and executes trial-level work only (constraint #8);
  job manager handles job state transitions
  `CREATED → QUEUED → RUNNING → AGGREGATING → COMPLETED`, baseline vs.
  optimizer candidate selection, and aggregation. Mock simulator.
- **Phase 4 — Reports, trials, artifacts.**
  `GET /api/v1/jobs/{id}/trials`, `GET /api/v1/trials/{id}`,
  `GET /api/v1/jobs/{id}/report`, `GET /api/v1/jobs/{id}/artifacts`. Report
  state machine `PENDING → READY`. Not-ready → structured error.
- **Phase 5 — Frontend integration.**
  Dashboard, New Job, Job Detail, Trial Detail, History pages wired to the
  real API via TanStack Query. Shared components: Status Badge, Metric Card,
  Section Card, Data Table, Alert/Notice, Loading/Empty/Error states. No
  simulator or optimizer logic runs on the frontend (constraint #7).
- **Phase 6 — Acceptance hardening.**
  Failure surfaces, rerun creates a new job and preserves the original, invalid
  input rejected on both ends, terminal jobs not cancellable again, charts
  rendered from persisted metrics (not mocked).
- **Phase 7 — Optional LLM summary.**
  Result explanation / summary text only (constraint #9). Never issues flight
  control commands or bypasses optimizer/simulator boundaries.

Later phases preserve the API contract (constraint #10). No real PX4/Gazebo
integration in the MVP (constraint #1).

## Known limitations at Phase 0

- No database, no models, no migrations.
- No `/api/v1/*` routes beyond what `/health` demonstrates.
- Frontend pages are empty placeholders under React Router.
- Worker does not consume or produce any work — it only logs start/stop.
- No authentication layer.
- No CI workflow yet (added in a later phase).
