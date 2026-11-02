# DroneDream implementation overview

DroneDream combines a React interface, Tauri desktop shell, FastAPI service,
background worker, PX4/Gazebo Runtime, and shared release contracts. The
repository is organized by ownership so a path reveals whether code belongs to
an application, service, platform component, release tool, shared contract, or
document.

## Main components

| Area | Location | Responsibility |
| --- | --- | --- |
| Web and product UI | `apps/web` | React, TypeScript, Vite, public pages, and desktop UI |
| Desktop editions | `apps/desktop` | Tauri host, Windows installers, updates, and edition packaging |
| API | `server/api` | FastAPI, persistence, mission planning, simulation coordination, and reports |
| Worker | `server/worker` | Queued mission and experiment execution |
| Cloud data | `server/database` | Database migrations and edge functions |
| Runtime | `runtime/installer` | WSL image, services, PX4/Gazebo dependencies, and lifecycle scripts |
| Engine Pack | `runtime/engine` | Versioned service, simulator, and contract payload |
| Product contracts | `release/desktop/config` | Editions, vehicles, capabilities, installer metadata, and update families |
| Deployments | `release/website/config`, `apps/website` | Containers and static-site publication |
| Shared assets | `shared` | Brand files and cross-component contracts |

## Local commands

```bash
# Frontend
npm ci --prefix apps/web
npm --prefix apps/web run dev

# Backend
python -m venv server/api/.venv
server/api/.venv/Scripts/python -m pip install -e "server/api[dev]"
server/api/.venv/Scripts/python -m uvicorn app.main:app --reload --app-dir server/api

# Worker
python -m venv server/worker/.venv
server/worker/.venv/Scripts/python -m pip install -e server/api -e "server/worker[dev]"
server/worker/.venv/Scripts/python -m drone_dream_worker.main

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
`release`, and `shared`; frontend tests under `apps/web`; Rust tests under
`apps/desktop/src`.

Generated output belongs in the managed workspace build and test roots, not in
new directories at the root of `Q:\` or inside source folders.
