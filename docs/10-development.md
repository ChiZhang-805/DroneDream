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

### Runtime contract tooling

```bash
python -m venv runtime/.venv
runtime/.venv/bin/pip install \
  -r runtime/locks/release-tools-requirements.lock \
  ruff==0.15.21
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
- `./scripts/check-runtime.sh`
- `./scripts/check-frontend.sh`
- `./scripts/check-all.sh`

`check-all.sh` is the portable service-layer aggregate. The Windows Desktop
application is an explicit platform gate because Tauri, WebView2, and NSIS
require a Windows toolchain; a portable aggregate must not silently present a
skipped Desktop build as a full-product pass.

Equivalent service-layer manual commands:

```bash
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m mypy backend/app
backend/.venv/bin/python -m pytest backend
worker/.venv/bin/python -m ruff check worker
worker/.venv/bin/python -m mypy --config-file worker/pyproject.toml worker/drone_dream_worker
worker/.venv/bin/python -m pytest worker
RUNTIME_PYTHON=runtime/.venv/bin/python ./scripts/check-runtime.sh
cd frontend && npm run typecheck && npm run lint && npm run build && npm test
```

Run the Windows Desktop gate separately from PowerShell:

```powershell
npm --prefix desktop audit --audit-level=high
npm --prefix desktop run verify:release-source
cargo fmt --all --manifest-path desktop/src-tauri/Cargo.toml -- --check
cargo clippy --locked --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml --all-targets
./desktop/scripts/verify-nsis-template.ps1
```

## Current capabilities

- Backend ships an Alembic migration chain for reviewed schema upgrades.
- Batch compatibility APIs are covered by backend tests; the retired batch pages are not part of the frontend bundle.

## Limitations / roadmap

- CI bootstrap remains multi-step (no single `make dev` entrypoint yet).
