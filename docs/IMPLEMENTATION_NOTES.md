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

These will be introduced as typed enums in a later phase (when the backend
requires them); they are listed here so reviewers see the full vocabulary up
front.

## Phase plan

This plan follows the canonical execution plan in
[`docs/07_EXECUTION_PLAN.md`](./07_EXECUTION_PLAN.md) (§3.2). The ordering —
frontend skeleton first, then real backend, then async worker framework, then
simulator adapter, then optimization loop — is the product's "close the loop
first, replace mocks later" strategy and must not be reshuffled.

- **Phase 0 — Repo Bootstrap (this PR).**
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
  `CREATED → QUEUED → RUNNING → AGGREGATING → COMPLETED` from the backend,
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
  Drive every acceptance rule green: failed jobs show user-readable failure
  info, rerun creates a new job and preserves the original, invalid input is
  rejected on both frontend and backend, terminal jobs are not cancellable
  again, charts render from persisted metrics (no mock fallback). Add CI
  workflow, tighten error codes, and close out the MVP against
  [`docs/06_ACCEPTANCE_CRITERIA.md`](./06_ACCEPTANCE_CRITERIA.md).

Later phases preserve the API contract (constraint #10). No real PX4/Gazebo
integration in the MVP (constraint #1). Optional LLM result-summary text, if
added, is a post-Phase-7 enhancement and is limited to explanation only —
it must not generate flight control commands or bypass the optimizer /
simulator boundaries (constraint #9).

## Known limitations at Phase 0

- No database, no models, no migrations (land in Phase 2).
- No `/api/v1/*` routes beyond what `/health` demonstrates (land in Phase 2).
- Frontend pages are empty placeholders under React Router (fleshed out with
  mock data in Phase 1).
- Worker does not consume or produce any work — it only logs start/stop
  (trial execution lands in Phase 3, routed through the adapter in Phase 4).
- No authentication layer.
- No CI workflow yet (added in Phase 7).
