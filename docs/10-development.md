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
./scripts/dev-backend.sh

# terminal 2
./scripts/dev-worker.sh

# terminal 3
./scripts/dev-frontend.sh
```

Launch all three commands from the repository root. The backend and worker
helpers load the same root `.env` and pin the fallback SQLite URL to the same
database file.

## Quality gates

Use existing scripts (recommended):

- `./scripts/check-backend.sh`
- `./scripts/check-worker.sh`
- `./scripts/check-frontend.sh`
- `./scripts/check-all.sh`

Equivalent manual commands:

```bash
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m mypy backend/app
backend/.venv/bin/python -m pytest backend
worker/.venv/bin/python -m ruff check worker
cd frontend && npm run typecheck && npm run lint && npm run build && npm test
```

## Current capabilities

- Backend ships an Alembic migration chain for reviewed schema upgrades.
- Batch compatibility APIs are covered by backend tests; the retired batch pages are not part of the frontend bundle.

## Limitations / roadmap

- CI bootstrap remains multi-step (no single `make dev` entrypoint yet).
