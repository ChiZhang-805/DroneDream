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
  legal/          Privacy policy and terms of service
  release/        Signing and versioning policies
  report/         Technical report source and generated publication
tools/            Repository checks, development helpers, and simulators
```

This is the complete product source layout on `main`; the five desktop editions
do not get separate source directories. Edition differences stay in manifests,
branding, capability policy, installer identity, and update configuration.
Generated builds, release staging,
and test results live outside the checkout under
`Q:\DroneDream-Workspace\Build` and `Q:\DroneDream-Workspace\TestRuns` on the
managed Windows workspace. Repository-local `artifacts/` output is ignored and
must not be committed.

## Start locally

Frontend:

```bash
npm ci --prefix apps/web
npm --prefix apps/web run dev
```

Backend:

```bash
python -m venv server/api/.venv
server/api/.venv/Scripts/python -m pip install -e "server/api[dev]"
server/api/.venv/Scripts/python -m uvicorn app.main:app --reload --app-dir server/api
```

Worker:

```bash
python -m venv server/worker/.venv
server/worker/.venv/Scripts/python -m pip install -e server/api -e "server/worker[dev]"
server/worker/.venv/Scripts/python -m drone_dream_worker.main
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
python -m pytest server/api/tests -q
python -m pytest shared/brand/tests release/desktop/tests runtime/engine/tests runtime/tests -q
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web run test
npm --prefix apps/web run build
```

The complete Windows installer, Runtime image, and deployment checks run in
GitHub Actions. Local details are in the
[engineering guides](docs/README.md),
[desktop guide](apps/desktop/README.md), and
[Runtime release guide](docs/development/14-runtime-release.md).

## Source branch

`main` is the only permanent branch and the authoritative source for Universal,
SIM, LAB, FIELD, AGENT, and the website. Temporary feature branches may be used
for review, but they must return to `main` and be removed after merging. Editions
remain separate build outputs, not separate source trees.

DroneDream is licensed under the [MIT License](LICENSE). Do not place
credentials, user projects, generated installers, Runtime images, or local
experiment data in the repository.

Release and user-data requirements are documented in the
[Code signing policy](docs/release/code-signing.md) and
[Privacy policy](docs/legal/privacy.md). Contribution and vulnerability
reporting guidance lives in GitHub's standard `.github` directory.
