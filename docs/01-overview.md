# DroneDream — Implementation Notes

This document complements the product docs in [`docs/`](./). It captures the
engineering stack, local commands, and phase plan.

## Stack

| Layer     | Choice                                                                 | Rationale                                                                 |
|-----------|------------------------------------------------------------------------|---------------------------------------------------------------------------|
| Frontend  | React 18 + TypeScript + Vite + React Router + TanStack Query           | Fast dev loop, strong typing, idiomatic routing and server-state caching. |
| Backend   | Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy 2                     | Async-friendly API, typed request/response models, ORM ready for Postgres.|
| Database  | SQLite for local development; PostgreSQL + Alembic for deployment      | Zero-config local loop with a reviewed production migration path.         |
| Worker    | Python process claiming DB-backed work with renewable leases           | Keeps orchestration separate from the API; Valkey supplies presence/readiness signals. |
| Charts    | Recharts                                                               | Simple React chart primitives, good DX.                                   |
| Tests     | `pytest` (backend), Vitest + React Testing Library + `tsc --noEmit` + ESLint (frontend), `ruff` (backend + worker), `mypy` (backend) | Focused, fast feedback; each layer has its own gate. |
| CI        | GitHub Actions under `.github/workflows/`                              | Verifies the Windows installer and signed runtime contracts/releases; local aggregate gates live under `scripts/`. |

## Monorepo layout

```
DroneDream/
  frontend/     # React + TS + Vite app. Renders Dashboard, New Job,
                #   Job Detail, Trial Detail, History / Reports against
                #   the real backend via TanStack Query. Vitest + RTL
                #   regression tests under src/__tests__/.
  backend/      # FastAPI /api/v1 APIs (jobs, trials, report, artifacts),
                #   SQLAlchemy models, response envelope helpers, and the
                #   orchestration package (job manager, trial executor,
                #   aggregator, optimizer, report generator) shared with
                #   the worker process.
  worker/       # Database-backed polling worker. Dispatches baseline +
                #   optimizer trials via the SimulatorAdapter, aggregates
                #   per-candidate scores, writes the JobReport, and drives
                #   the job state machine to COMPLETED or FAILED.
  docs/         # Product docs + this file
  scripts/      # Dev/check helper scripts
  .env.example  # Environment variable template
  README.md     # How to set up and run the project locally
```

## Local commands

```bash
# Frontend
cd frontend
npm ci
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

# Worker (installs the backend editable into the worker venv first,
# because the worker reuses the backend ORM + orchestration packages).
python3 -m venv worker/.venv
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e 'worker[dev]'
worker/.venv/bin/python -m drone_dream_worker.main
worker/.venv/bin/ruff check worker
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

- **Job status:** `CREATED | QUEUED | RUNNING | AGGREGATING | FINALIZING | COMPLETED | FAILED | CANCELLED`
- **Trial status:** `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`
- **Track type:** `circle | u_turn | lemniscate | custom`
- **Sensor noise:** `low | medium | high`
- **Objective profile:** `stable | fast | smooth | robust | custom`

These are now live as Pydantic `Literal` types in
[`backend/app/schemas.py`](../backend/app/schemas.py) and the matching
TypeScript unions in [`frontend/src/types/`](../frontend/src/types). Do
not rename them casually — downstream tests, docs, and the UI assume the
exact spelling above.

## Historical implementation milestones

The MVP followed the historical phase ordering preserved below: frontend
skeleton first, then real backend, then async worker framework, then simulator
adapter, then optimization loop. This was the product's "close the loop first,
replace mocks later" strategy. The former archive was intentionally removed
from the trimmed documentation tree, so this section is now the surviving phase
summary. The code-level milestones below were completed, but they are not a
claim that clean-machine Windows delivery, every advanced Gazebo effect, or
real-flight acceptance is complete. Current implementation and
environment-dependent gates live in the product documents linked from
`docs/README.md`.

- **Phase 0 — Repo Bootstrap.**
  Monorepo skeleton, runnable frontend/backend/worker, docs, env template,
  quality-gate scripts. No domain logic, no data model, no API beyond
  `/health`.
- **Phase 1 — Frontend Skeleton + Mock Data.**
  Build out all five required pages (Dashboard, New Job, Job Detail, Trial
  Detail, History) and the shared component kit (Status Badge, Metric Card,
  Section Card, Data Table, Alert/Notice, Loading/Empty/Error) driven by
  **mock data only**. Page routes, form validation, loading/empty/error
  states, and the New Job form defaults must all be complete; the backend is
  not required to be real yet. Mock field names and status enums must match
  the locked API/enum contract so there is nothing to rename in Phase 2.
- **Phase 2 — Real Backend + Persistence.**
  Land the full `/api/v1` surface (`POST /jobs`, `GET /jobs`,
  `GET /jobs/{id}`, `POST /jobs/{id}/rerun`, `POST /jobs/{id}/cancel`,
  `GET /jobs/{id}/trials`, `GET /trials/{id}`, `GET /jobs/{id}/report`,
  `GET /jobs/{id}/artifacts`) on SQLAlchemy models for `User`, `Job`,
  `CandidateParameterSet`, `Trial`, `TrialMetric`, `JobReport`, `Artifact`
  (and ideally `JobEvent`) — all persisted as separate tables per constraints
  #5 and #6. Switch the frontend from mock data to the real API. Endpoints
  may return empty lists or `REPORT_NOT_READY`, but the response shape is
  authoritative.
- **Phase 3 — Async Job / Queue / Worker Framework.**
  `POST /api/v1/jobs` returns immediately with `{job_id, status: QUEUED}`
  (constraint #3); job manager drives
  `CREATED → QUEUED → RUNNING → AGGREGATING → FINALIZING → COMPLETED` from the backend,
  never from the frontend (constraints #4, #7). Worker consumes trial rows
  only (constraint #8), updates status, and writes back mock metrics.
  Baseline candidate is auto-created per job. Minimum closed loop: user
  creates job → baseline trials run → job reaches `COMPLETED` or `FAILED`.
- **Phase 4 — Simulator Adapter Layer.**
  Introduce a `SimulatorAdapter` abstraction with a `MockSimulatorAdapter`
  (primary MVP path, supports baseline / optimized / nominal / perturbed
  scenarios and failure injection) and a `RealSimulatorAdapterStub`
  interface shell for future PX4/Gazebo work. Worker routes all trial
  execution through the adapter — no simulation logic baked into worker code.
  Real PX4/Gazebo integration stays out of the MVP (constraint #1).
- **Phase 5 — Optimization Loop.**
  Generate optimizer candidates in addition to baseline, evaluate each across
  multiple trials (different seeds/scenarios), aggregate trial metrics into a
  candidate score, and select the best candidate. Write best params into the
  job/report. Keep the optimizer simple (e.g. perturbation sampling + sort)
  for MVP; advanced BO/CMA-ES and LLM-driven parameter search are out of
  scope (constraint #9 limits LLM use to result explanation text).
- **Phase 6 — Results / Reporting / Visualization.**
  Turn persisted trial metrics into the Job Detail experience: baseline vs.
  optimized metric cards, comparison charts (Recharts), best params panel,
  trial summary table, failure diagnostics, report state machine
  `PENDING → READY` with not-ready surfaced as a structured error. History /
  Reports page reads the same real data.
- **Phase 7 — Hardening and Acceptance Pass.**
  Drove every acceptance rule green: failed jobs show user-readable failure
  info, rerun creates a new job and preserves the original, invalid input is
  rejected on both frontend and backend, terminal jobs are not cancellable
  again, charts render from persisted metrics (no mock fallback).
  Acceptance behavior was captured in the automated backend and frontend
  regression suites.
- **Post-Phase-7 hardening.**
  Documentation drift corrected, `POST /api/v1/jobs` response contract
  clarified (full `Job` object plus a backward-compatible `job_id` alias),
  GitHub Actions CI wired up, and a minimal Vitest + React Testing Library
  regression suite added on the frontend.

The API contract was preserved across these historical phases. Real
PX4/Gazebo and external LLM integration were outside the original MVP; both
now exist behind explicit adapters and safety boundaries described by the
current product documents.

## Current status and boundaries

This file retains the original implementation history and should not duplicate
fast-moving release claims. See `12-phase-status.md` for implemented versus
environment-dependent acceptance work, `DEPLOYMENT.md` for the PostgreSQL,
authentication, storage, and worker topology, and `14-runtime-release.md` for
the signed Windows runtime delivery boundary.
