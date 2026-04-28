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

在仓库根目录运行（脚本会自动切换到仓库根目录）：

- `./scripts/check-backend.sh`：执行 `ruff check backend`、`mypy backend/app`、`pytest backend`
- `./scripts/check-worker.sh`：执行 `ruff check worker`
- `./scripts/check-frontend.sh`：执行 frontend 的 `typecheck/lint/build/test`
- `./scripts/check-all.sh`：按顺序执行 backend、worker、frontend 三组检查
- `./scripts/check.sh`：兼容入口（保留）

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
