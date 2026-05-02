# Hosted B Single-Tenant Deployment

This document describes B: a single-tenant hosted deployment.

Not SaaS: no billing, no multi-tenant account system, no autoscaling.

Quick start:
1. Checkout `feature/hosted-b-single-tenant`.
2. Run `scripts/hosted-b/init-env.sh`.
3. Edit `deploy/hosted-b/.env`.
4. Run `scripts/hosted-b/up.sh`.
5. Open `http://localhost:8080`.
6. Enter shared token if enabled.
7. Submit job in New Job page.
8. Run `scripts/hosted-b/smoke.sh`.

Default mode uses `real_cli` dry run (`PX4_GAZEBO_DRY_RUN=true`) and headless mode. noVNC is off by default.

For real PX4/Gazebo: set `PX4_GAZEBO_DRY_RUN=false`, keep `PX4_GAZEBO_HEADLESS=true`, configure `PX4_AUTOPILOT_DIR`, `PX4_GAZEBO_LAUNCH_COMMAND`, `PX4_MAKE_TARGET`, `PX4_TELEMETRY_MODE`. Optional `worker-px4` profile is heavier.

OpenAI:
- BYOK per-job key.
- Hosted server-key mode with `OPENAI_API_KEY`, `HOSTED_ALLOW_SERVER_OPENAI_KEY=true`, and `APP_SECRET_KEY`.

Auth: `demo_token` is only a single-tenant shared access gate. Rotate by updating `.env` and restarting.

Artifacts: default local volume, S3/MinIO optional future work.

Troubleshooting: check `/health`, web->API proxy, 401 token mismatch, `docker compose logs worker`, DB URL, artifact mounts, APP_SECRET_KEY for GPT, adapter unavailable, PX4 timeouts, smoke failures.
