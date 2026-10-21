# DroneDream implementation overview

DroneDream combines a React interface, Tauri desktop shell, FastAPI service,
background worker, PX4/Gazebo Runtime, and shared release contracts. The
repository is organized by ownership so a path reveals whether code belongs to
an application, service, platform component, release tool, shared contract, or
document.

## Main components

| Area | Location | Responsibility |
| --- | --- | --- |
| Web and product UI | `apps/frontend` | React, TypeScript, Vite, public pages, and desktop UI |
| Desktop editions | `apps/desktop` | Tauri host, Windows installers, updates, and edition packaging |
| API | `services/backend` | FastAPI, persistence, mission planning, simulation coordination, and reports |
| Worker | `services/worker` | Queued mission and experiment execution |
| Cloud data | `services/supabase` | Database migrations and edge functions |
| Runtime | `platform/runtime` | WSL image, services, PX4/Gazebo dependencies, and lifecycle scripts |
| Engine Pack | `platform/engine-pack` | Versioned service, simulator, and contract payload |
| Product contracts | `release/distribution` | Editions, vehicles, capabilities, installer metadata, and update families |
| Deployments | `release/deploy`, `release/website` | Containers and static-site publication |
| Shared assets | `shared` | Brand files and cross-component contracts |

## Local commands

```bash
# Frontend
npm ci --prefix apps/frontend
npm --prefix apps/frontend run dev

# Backend
python -m venv services/backend/.venv
services/backend/.venv/Scripts/python -m pip install -e "services/backend[dev]"
services/backend/.venv/Scripts/python -m uvicorn app.main:app --reload --app-dir services/backend

# Worker
python -m venv services/worker/.venv
services/worker/.venv/Scripts/python -m pip install -e services/backend -e "services/worker[dev]"
services/worker/.venv/Scripts/python -m drone_dream_worker.main

# Desktop
npm ci --prefix apps/desktop
npm --prefix apps/desktop run dev
```

On Linux or macOS, replace `Scripts` with `bin` and use `python3` when
required.

## Mission flow

1. The operator chooses a map and aircraft and states a goal.
2. Agent Core interprets the goal and calls route and mission tools.
3. The operator reviews the plan before execution.
4. The backend and worker run the mission through the selected simulator or
   connected runtime.
5. Telemetry and terminal state update while the task runs.
6. A completed mission is saved to history with its project context.

The API uses a consistent response envelope:

```json
{"success": true, "data": {}, "error": null}
```

Errors use the same structure with `success: false`, `data: null`, and a typed
error object.

## Development checks

Use `tools/check-repository.py` for repository structure and links. Component
tests live beside their owners: Python tests under `services`, `platform`,
`release`, and `shared`; frontend tests under `apps/frontend`; Rust tests under
`apps/desktop/src-tauri`.

Generated output belongs in the managed workspace build and test roots, not in
new directories at the root of `Q:\` or inside source folders.
