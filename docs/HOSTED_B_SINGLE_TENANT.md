# Hosted B Single-Tenant Deployment

## What Hosted B is
Hosted B is a single-tenant self-hosted deployment profile for one team/site, with one shared backend, worker, and database stack. It ships with simple shared-token access, local artifact volume storage, and defaults intended to run out-of-the-box in dry-run mode.

## What Hosted B is not
- Not multi-tenant SaaS.
- Not a billing/account platform.
- Not an autoscaling production control plane.
- Not a guaranteed full PX4/Gazebo production image when using `worker-px4` or `worker-real-px4`.

## Quick start
```bash
scripts/hosted-b/init-env.sh
scripts/hosted-b/up.sh
scripts/hosted-b/smoke.sh
scripts/hosted-b/down.sh
```

## Default execution mode (important)
Hosted B default `real_cli` is **dry-run** mode:
- `REAL_SIMULATOR_COMMAND=python scripts/simulators/px4_gazebo_runner.py`
- `PX4_GAZEBO_DRY_RUN=true`
- no external PX4/Gazebo process is launched

This is why Hosted B `real_cli` trials are fast and deterministic by default: the runner validates/control-flow without starting full simulator processes.

## Dry-run mode vs real PX4/Gazebo mode
### Mode 1: real_cli dry-run (default)
- `PX4_GAZEBO_DRY_RUN=true`
- Safe for smoke checks and deterministic workflow tests
- No external PX4/Gazebo launch

### Mode 2: real_cli PX4/Gazebo real mode (optional)
- `PX4_GAZEBO_DRY_RUN=false`
- Requires launch command, PX4-Autopilot path, telemetry mode, and runtime dependencies
- Not enabled by default

Merely setting `PX4_GAZEBO_DRY_RUN=false` is **not enough**.

## Confirm current mode
```bash
grep -E "PX4_GAZEBO_DRY_RUN|PX4_GAZEBO_LAUNCH_COMMAND|PX4_AUTOPILOT_DIR" deploy/hosted-b/.env

docker compose --env-file deploy/hosted-b/.env exec worker sh -lc 'env | grep -E "PX4_GAZEBO_DRY_RUN|PX4_GAZEBO_LAUNCH_COMMAND|PX4_AUTOPILOT_DIR"'
```

## Switch to real PX4/Gazebo mode
Set in `deploy/hosted-b/.env`:
- `PX4_GAZEBO_DRY_RUN=false`
- `PX4_GAZEBO_LAUNCH_COMMAND=...`
- `PX4_AUTOPILOT_DIR=...`
- `PX4_TELEMETRY_MODE=ulog` or `PX4_TELEMETRY_MODE=json`
- optionally set `PX4_MAKE_TARGET` and `PX4_ULOG_ROOT`

Then use `worker-real-px4` compose profile (or your own site-specific worker image).

## Simulator backend selection
Hosted B exposes both `real_cli` and `mock` in the New Job UI by default.

- `VITE_LOCK_SIMULATOR_BACKEND=false` keeps the frontend dropdown editable.
- `VITE_DEFAULT_SIMULATOR_BACKEND=real_cli` keeps `real_cli` as the default selection.
- `SIMULATOR_BACKEND=` leaves the worker global override unset, so each job's selected backend is respected.

Use `mock` for fast deterministic UI/workflow checks. Use `real_cli` for hosted simulator path testing.

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

## Storage
Artifacts use local shared volume storage by default (`artifacts` volume).

## Optional worker-real-px4 profile
`worker-real-px4` is optional (`--profile real-px4`). It mounts:
- artifacts volume
- optional host PX4 source: `${PX4_AUTOPILOT_HOST_DIR:-./missing-px4-autopilot}:/opt/PX4-Autopilot:ro`

Warning: this is site-specific and not guaranteed complete. You likely still need additional dependencies (mavsdk/plugins/toolchains) and launch tuning.

## Troubleshooting and likely failures in real mode
- `ADAPTER_UNAVAILABLE`: misconfigured `REAL_SIMULATOR_COMMAND` or missing runtime deps.
- `SIMULATION_FAILED`: simulator launch returned non-zero/invalid payload.
- `TIMEOUT`: launch or mission did not complete before timeout.
- missing mavsdk runtime deps in worker image.
- missing telemetry output or mismatched `PX4_TELEMETRY_MODE`.
- missing `PX4_AUTOPILOT_DIR`.
- missing `PX4_GAZEBO_LAUNCH_COMMAND`.

General checks:
- frontend calls `/api/api/v1`: fix `VITE_API_BASE_URL` and rebuild frontend.
- 401 token errors: verify `DRONEDREAM_DEMO_TOKEN` and browser saved token.
- backend cannot connect to Postgres: verify DB env vars and postgres health.
- worker stuck: inspect `docker compose logs worker`.
- smoke timeout: backend/worker may not be healthy yet.
