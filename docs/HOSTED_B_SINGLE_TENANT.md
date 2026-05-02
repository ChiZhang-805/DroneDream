# Hosted B Single-Tenant Deployment

## What Hosted B is
Hosted B is a single-tenant self-hosted deployment profile for one team/site, with one shared backend, worker, and database stack.

## What Hosted B is not
- Not multi-tenant SaaS.
- Not a billing/account platform.
- Not an autoscaling production control plane.
- Not a guaranteed fully packaged PX4/Gazebo runtime image for every site.

## Quick start paths

### A) Mock/dev website smoke (recommended first)
1. Run `scripts/hosted-b/init-env.sh`.
2. Edit `deploy/hosted-b/.env` and set:
   - `HOSTED_REAL_CLI_REQUIRES_PX4=false`
   - `PX4_GAZEBO_DRY_RUN=true`
3. Start stack: `scripts/hosted-b/up.sh`
4. Run smoke test: `scripts/hosted-b/smoke.sh`
5. Stop stack: `scripts/hosted-b/down.sh`

### B) Real PX4/Gazebo + noVNC strict mode
1. Run `scripts/hosted-b/init-env.sh`.
2. Edit `deploy/hosted-b/.env` and set required values:
   - `HOSTED_REAL_CLI_REQUIRES_PX4=true`
   - `PX4_GAZEBO_DRY_RUN=false`
   - `PX4_GAZEBO_HEADLESS=false`
   - `PX4_AUTOPILOT_HOST_DIR=/absolute/host/path/to/PX4-Autopilot`
   - `PX4_AUTOPILOT_DIR=/opt/PX4-Autopilot`
   - `PX4_GAZEBO_LAUNCH_COMMAND=python3 /app/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --output {output_path}`
   - `VNC_PASSWORD=<set-a-real-password>`
3. Validate env: `scripts/hosted-b/check-real-px4-config.sh`
4. Start strict stack: `scripts/hosted-b/up-real-px4.sh`
5. Open `http://localhost:8080`; Job Detail should show Gazebo iframe when real mode is configured.

## Execution modes

### Hosted B strict mode
- `real_cli` means actual PX4/Gazebo + noVNC execution.
- Use `scripts/hosted-b/up-real-px4.sh`.
- Requires real env vars and PX4/Gazebo runtime dependencies at your site.

### Developer/mock mode
- `mock` is for fast deterministic testing.
- Optional `real_cli` dry-run exists only when:
  - `HOSTED_REAL_CLI_REQUIRES_PX4=false`
  - `PX4_GAZEBO_DRY_RUN=true`
- This dry-run path is not hosted production behavior.

## Runtime API source note
`/api/v1/runtime` returns safe runtime flags from the backend/shared deployment environment. It is not a live probe of every worker binary/dependency state.

## Start commands by mode
- Mock/dev mode: `scripts/hosted-b/up.sh`
- Strict real PX4/Gazebo + noVNC mode: `scripts/hosted-b/up-real-px4.sh`

`up.sh` delegates to `up-real-px4.sh` when strict mode is enabled, unless `ALLOW_STRICT_REAL_CLI_WITH_DEFAULT_WORKER=true` is explicitly set.

## Hosted B strict real_cli notes
- Required in strict mode: `PX4_GAZEBO_LAUNCH_COMMAND`, `PX4_AUTOPILOT_DIR`, `VNC_PASSWORD`.
- Strongly recommended for embedded viewer UX: `VITE_GAZEBO_VIEWER_URL`.
- `worker-real-px4-vnc` image wires worker + noVNC + DISPLAY, but full PX4/Gazebo runtime can still be site-specific.
- Validate config: `scripts/hosted-b/check-real-px4-config.sh`.
- Inspect worker: `docker compose --env-file deploy/hosted-b/.env ps` and `docker compose --env-file deploy/hosted-b/.env logs worker-real-px4-vnc --tail=200`.

## Troubleshooting
- `ADAPTER_UNAVAILABLE`: strict real_cli validation failed or simulator command misconfigured.
- `SIMULATION_FAILED`: simulator launch returned non-zero/invalid payload.
- `TIMEOUT`: launch or mission did not complete before timeout.
- Missing PX4/Gazebo dependencies: install site-specific packages/toolchains or mount prebuilt workspace.
