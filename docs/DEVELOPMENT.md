# Development Guide

## Python venv setup

Backend:

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
```

Worker:

```bash
python -m venv worker/.venv
worker/.venv/bin/pip install -e backend
worker/.venv/bin/pip install -e "worker[dev]"
```

## Frontend setup

```bash
cd frontend
npm ci
```

## Local checks

Scripts:

- `./scripts/check-backend.sh`
- `./scripts/check-frontend.sh`
- `./scripts/check-worker.sh`
- `./scripts/check-all.sh`

Manual commands:

```bash
ruff check backend
mypy backend/app
pytest backend
cd frontend && npm run typecheck && npm run lint && npm run build && npm test
```

## CI local reproduction

Run the same lint/type/test command groups above in a clean environment with fresh virtualenv/node_modules.

## Roadmap

- Add one-command dev bootstrap script for backend + worker + frontend.
