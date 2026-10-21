# Development Guide

## Local setup

### Backend

```bash
python -m venv services/backend/.venv
services/backend/.venv/bin/pip install --upgrade pip
services/backend/.venv/bin/pip install -e "services/backend[dev]"
```

### Worker

```bash
python -m venv services/worker/.venv
services/worker/.venv/bin/pip install --upgrade pip
services/worker/.venv/bin/pip install -e services/backend
services/worker/.venv/bin/pip install -e "services/worker[dev]"
```

### Frontend

```bash
cd apps/frontend
npm ci
```

## Run services

```bash
# terminal 1
./tools/dev-backend.sh

# terminal 2
./tools/dev-worker.sh

# terminal 3
./tools/dev-frontend.sh
```

Launch all three commands from the repository root. The backend and worker
helpers load the same root `.env` and pin the fallback SQLite URL to the same
database file.

## Quality gates

Use existing scripts (recommended):

- `./tools/check-backend.sh`
- `./tools/check-worker.sh`
- `./tools/check-frontend.sh`
- `./tools/check-all.sh`

Equivalent manual commands:

```bash
services/backend/.venv/bin/python -m ruff check services/backend
services/backend/.venv/bin/python -m mypy services/backend/app
services/backend/.venv/bin/python -m pytest services/backend
services/worker/.venv/bin/python -m ruff check services/worker
cd apps/frontend && npm run typecheck && npm run lint && npm run build && npm test
```

### Build verification lessons

- Scope build-only `VITE_*` overrides to the individual build process. Do not
  export them into the shell that runs Vitest: URL-contract tests intentionally
  read the default test environment and will otherwise report misleading
  failures even though the product code is unchanged.
- After any build failure, run the affected test in a fresh process, identify
  whether the failure is environmental or a product defect, and remove the
  failed `dist`/`site-dist` output before rebuilding. Keep only the final
  verified bundle; do not retain numbered or abandoned build copies.

## Current capabilities

- Backend ships an Alembic migration chain for reviewed schema upgrades.
- Batch compatibility APIs are covered by backend tests; the retired batch pages are not part of the frontend bundle.

## Limitations / roadmap

- CI bootstrap remains multi-step (no single `make dev` entrypoint yet).
