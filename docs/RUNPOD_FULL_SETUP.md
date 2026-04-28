# Runpod Full Setup

For full long-form workflows, keep using:

- [DroneDream Runpod Gazebo GUI workflow](./DroneDream_Runpod_Gazebo_GUI_Workflow.md)
- [DroneDream local Gazebo GUI workflow](./DroneDream_Local_Gazebo_GUI_Workflow.md)

This page is an index + quick checklist for the production-like Runpod path.

## Quick checklist

1. Prepare ports/volume (recommended ports: `5173`, `8000`, `6080`, optional `8888`).
2. Clone `DroneDream` and `PX4-Autopilot` into `/workspace`.
3. Install system GUI/noVNC + PX4 dependencies.
4. Create Python venvs for backend + worker (+ PX4 env if required).
5. Start backend (`uvicorn`), worker, and frontend (`vite`).
6. Validate `real_cli + heuristic` first, then `real_cli + gpt`.

## Environment placeholders

Use placeholders only (no real values in docs):

- `OPENAI_API_KEY=<OPENAI_API_KEY>`
- `APP_SECRET_KEY=<APP_SECRET_KEY>`
- `DATABASE_URL=<DATABASE_URL>`

## Current capabilities

- Runpod noVNC + Gazebo GUI integration is documented in existing workflow docs.
- Real simulator adapter can be exercised through UI/API jobs.

## Limitations / roadmap

- Setup is still multi-step and environment-dependent.
- Automation for one-command Runpod bootstrap is not complete yet.
