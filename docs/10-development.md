# Development Guide

## Local setup

### Backend

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -e "backend[dev]"
```

### Worker

```bash
python -m venv worker/.venv
worker/.venv/bin/pip install --upgrade pip
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"
```

### Frontend

```bash
cd frontend
npm ci
```

## Run services

```bash
# terminal 1
cd backend
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# terminal 2
cd worker
.venv/bin/python -m drone_dream_worker.main

# terminal 3
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

## Quality gates

Use existing scripts (recommended):

- `./scripts/check-backend.sh`
- `./scripts/check-worker.sh`
- `./scripts/check-frontend.sh`
- `./scripts/check-all.sh`

Equivalent manual commands:

```bash
ruff check backend
mypy backend/app
pytest backend
cd frontend && npm run typecheck && npm run lint && npm run build && npm test
```

## Current capabilities

- Backend includes SQLite lightweight migration logic for additive columns.
- Batch APIs and frontend pages are covered by backend/frontend tests.

## Limitations / roadmap

- No Alembic migration chain yet.
- CI bootstrap remains multi-step (no single `make dev` entrypoint yet).
