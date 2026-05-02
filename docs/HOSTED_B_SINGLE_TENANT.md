# Hosted B Single-Tenant Deployment

## What Hosted B is
Hosted B is a single-tenant self-hosted deployment profile for one team/site, with one shared backend, worker, and database stack. It ships with simple shared-token access, local artifact volume storage, and defaults intended to run out-of-the-box in dry-run mode.

## What Hosted B is not
- Not multi-tenant SaaS.
- Not a billing/account platform.
- Not an autoscaling production control plane.
- Not a guaranteed full PX4/Gazebo production image when using `worker-px4`.

## Quick start
```bash
scripts/hosted-b/init-env.sh
scripts/hosted-b/up.sh
scripts/hosted-b/smoke.sh
scripts/hosted-b/down.sh
```

## Default execution mode
Default Hosted B validates the real simulator path using:
- `simulator_backend=real_cli`
- `REAL_SIMULATOR_COMMAND=python scripts/simulators/px4_gazebo_runner.py`
- `PX4_GAZEBO_DRY_RUN=true`
- `PX4_GAZEBO_HEADLESS=true`

To use a minimal subprocess simulator instead, set:
`REAL_SIMULATOR_COMMAND=python scripts/simulators/example_real_simulator.py`


## Simulator backend selection
Hosted B exposes both `real_cli` and `mock` in the New Job UI by default.

- `VITE_LOCK_SIMULATOR_BACKEND=false` keeps the frontend dropdown editable.
- `VITE_DEFAULT_SIMULATOR_BACKEND=real_cli` keeps `real_cli` as the default selection.
- `SIMULATOR_BACKEND=` leaves the worker global override unset, so each job's selected backend is respected.

Use `mock` for fast deterministic UI/workflow checks. Use `real_cli` for the hosted simulator path; the default Hosted B `real_cli` command uses `px4_gazebo_runner.py` in dry-run mode until real PX4/Gazebo is configured.

## Same-origin API routing
Frontend is built to call `/api/v1` in hosted mode. Nginx receives browser traffic and proxies `/api/*` to backend, preventing cross-origin setup for default hosted use.

## Demo token auth
Hosted B uses `AUTH_MODE=demo_token` by default.
- Token source: `DRONEDREAM_DEMO_TOKEN` in `deploy/hosted-b/.env`
- Frontend users enter token once and it is stored in localStorage
- 401 usually means missing/invalid token

## OpenAI modes
### BYOK mode (default)
Keep server-managed key disabled and provide API key per GPT job/rerun.

### Server-managed OpenAI mode
Set all of:
- `HOSTED_ALLOW_SERVER_OPENAI_KEY=true`
- `OPENAI_API_KEY=...`
- `VITE_SERVER_OPENAI_ENABLED=true`
Then rebuild web assets:
```bash
scripts/hosted-b/up.sh --build
```

## Switching from dry-run to real PX4/Gazebo
Set:
- `PX4_GAZEBO_DRY_RUN=false`
- `PX4_AUTOPILOT_DIR=...`
- `PX4_GAZEBO_LAUNCH_COMMAND=...`
- `PX4_MAKE_TARGET=...`
- `PX4_TELEMETRY_MODE=...`
Optional:
- `PX4_ULOG_ROOT=...`

noVNC remains off by default.

## Storage
Artifacts use local shared volume storage by default (`artifacts` volume).

## worker-px4 note
`docker/worker-px4.Dockerfile` is an optional starter image for experimentation. It is not guaranteed to be a complete production PX4/Gazebo image without additional site-specific dependencies/configuration.

## Troubleshooting
- frontend calls `/api/api/v1`: fix `VITE_API_BASE_URL` and rebuild frontend.
- 401 token errors: verify `DRONEDREAM_DEMO_TOKEN` and browser saved token.
- backend cannot connect to Postgres: verify DB env vars and postgres health.
- worker stuck: inspect `docker compose logs worker`.
- smoke timeout: backend/worker may not be healthy yet.
- `ADAPTER_UNAVAILABLE`: check simulator backend settings and command path.
- GPT secret errors: set `APP_SECRET_KEY` or `DRONEDREAM_SECRET_KEY`.
- artifact path/volume errors: verify `/artifacts` mount and permissions.
- PX4/Gazebo timeout: verify launch command, autopilot dir, headless/runtime constraints.
