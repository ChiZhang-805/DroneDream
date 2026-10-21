<p align="center">
  <img src="shared/brand/icons/universal-lockup.png" alt="DroneDream" width="560" />
</p>

<p align="center">
  <strong>Natural-language missions, PX4 simulation, tuning, hardware preparation, and field operations in one workspace.</strong>
</p>

# DroneDream

DroneDream turns a flight goal into a connected workflow. An operator chooses
a map and aircraft, describes the mission in natural language, reviews the
model-planned route, runs it through PX4 and Gazebo, and keeps the completed
mission in project history. The same project can move through simulation,
tuning, laboratory hardware, and field operation without rebuilding its
context in separate tools.

This repository contains the public website, React interface, Tauri desktop
editions, backend and worker services, Runtime image, release contracts,
product documentation, and shared brand assets. The natural-language flight
core is maintained in the public
[DroneDream Agent Core](https://github.com/ChiZhang-805/DroneDream-Agent-Core)
repository and is staged into desktop releases by an explicit build step.

## Repository layout

```text
apps/
  frontend/       React, TypeScript, Vite, public website, and product UI
  desktop/        Tauri shell, Windows installers, and edition packaging
services/
  backend/        FastAPI API, mission orchestration, persistence, and reports
  worker/         Queue worker and background mission execution
  supabase/       Cloud functions and database migrations
platform/
  runtime/        Reproducible WSL Runtime image and lifecycle scripts
  engine-pack/    Versioned service, simulator, and contract payloads
release/
  distribution/   Edition, vehicle, installer, and update contracts
  deploy/         Production container definitions
  website/        Static-site build and deployment tooling
shared/
  brand/          Canonical product names, colors, and icons
  contracts/      Interfaces shared across applications and services
docs/
  guides/         Product and engineering guides
  report/         Technical report source and generated publication
artifacts/         Retained repository-specific acceptance receipts
tools/            Repository checks, development helpers, and simulators
```

Every top-level directory has one purpose. Generated builds, release staging,
and cross-worktree test results live outside the checkout under
`Q:\DroneDream-Workspace\Build` and `Q:\DroneDream-Workspace\TestRuns` on the
managed Windows workspace.

## Start locally

Frontend:

```bash
npm ci --prefix apps/frontend
npm --prefix apps/frontend run dev
```

Backend:

```bash
python -m venv services/backend/.venv
services/backend/.venv/Scripts/python -m pip install -e "services/backend[dev]"
services/backend/.venv/Scripts/python -m uvicorn app.main:app --reload --app-dir services/backend
```

Worker:

```bash
python -m venv services/worker/.venv
services/worker/.venv/Scripts/python -m pip install -e services/backend -e "services/worker[dev]"
services/worker/.venv/Scripts/python -m drone_dream_worker.main
```

Desktop:

```bash
npm ci --prefix apps/desktop
npm --prefix apps/desktop run dev
```

Use the platform-specific executable form (`python` or `python3`, `Scripts` or
`bin`) for your operating system.

## Verify a change

```bash
python tools/check-repository.py
python -m pytest services/backend/tests -q
python -m pytest shared/brand/tests release/distribution/tests platform/engine-pack/tests platform/runtime/tests -q
npm --prefix apps/frontend run typecheck
npm --prefix apps/frontend run lint
npm --prefix apps/frontend run test
npm --prefix apps/frontend run build
```

The complete Windows installer, Runtime image, and deployment checks run in
GitHub Actions. Local details are in the
[engineering guides](docs/guides/README.md),
[desktop guide](apps/desktop/README.md), and
[Runtime release guide](docs/guides/14-runtime-release.md).

## Products and branches

DroneDream ships Universal, SIM, LAB, FIELD, and AGENT editions from one source
layout. Long-lived branches are limited to `main`, `software`,
`software-agent`, `software-field`, `software-lab`, `software-sim`, `website`,
and `technical-report`. Feature work uses short-lived branches and returns to
the appropriate long-lived branch after review.

DroneDream is licensed under the [MIT License](LICENSE). Do not place
credentials, user projects, generated installers, Runtime images, or local
experiment data in the repository.

Release and user-data requirements are documented in the
[Code signing policy](CODE_SIGNING_POLICY.md) and
[Privacy policy](PRIVACY.md).
