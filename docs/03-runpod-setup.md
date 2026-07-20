# Runpod Full Setup

For the supporting long-form workflows, use:

- [Local PX4/Gazebo setup](./04-local-setup.md)
- [PX4/Gazebo runner contract](./08-px4-gazebo.md)
- [Runpod Gazebo visualization operations](./11-operations.md)

This page is an index and quick checklist for a single-operator
development/demo Runpod path. It is not a hardened public multi-user
deployment recipe.

## Quick checklist

1. Prepare ports/volume (recommended ports: `5173`, `8000`, `6080`, optional `8888`).
2. Clone `DroneDream` and `PX4-Autopilot` into `/workspace`.
3. Install system GUI/noVNC + PX4 dependencies.
4. Create Python venvs for backend + worker (+ PX4 env if required).
5. Start backend (`uvicorn`), worker, and frontend (`vite`).
6. Validate `real_cli + heuristic` first, then `real_cli + gpt`.

## Environment placeholders

Use placeholders only (no real values in docs):

- `APP_SECRET_KEY=<APP_SECRET_KEY>`
- `DATABASE_URL=<DATABASE_URL>`

Provider API keys are entered per experiment, encrypted with
`APP_SECRET_KEY`, and must not be written into the shared `.env` file.

## Current capabilities

- Runpod noVNC + Gazebo GUI integration is documented in existing workflow docs.
- Real simulator adapter can be exercised through UI/API jobs.

## Limitations / roadmap

- Setup is still multi-step and environment-dependent.
- Automation for one-command Runpod bootstrap is not complete yet.
