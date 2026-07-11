# DroneDream deployment guide

This repository ships a production-shaped local stack with five independent
roles:

- `frontend`: static React application behind Nginx;
- `api`: FastAPI control plane and Alembic migration runner;
- `worker`: job dispatcher, simulator executor, and report finalizer;
- `postgres`: durable transactional state;
- `valkey` and `minio`: worker-presence signals and private artifact storage.

The bundled worker image is intentionally a control/runtime image. It runs the
deterministic `mock` backend immediately and can invoke `real_cli`, but it does
not install PX4 or Gazebo. Build a site-specific worker image on top of the
`worker` target when real simulation is enabled, pinning the required PX4,
Gazebo, MAVSDK, graphics, and vehicle assets.

## Local container stack

Requirements: Docker Engine with Compose v2 and at least 8 GB of available
memory for the application stack. Real Gazebo simulation needs substantially
more CPU and memory.

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`,
   `DEMO_AUTH_TOKENS`, and `VITE_DEMO_AUTH_TOKEN`. The demo token presented by
   the frontend must match one token in `DEMO_AUTH_TOKENS`.
3. If GPT optimization is enabled, set a Fernet `APP_SECRET_KEY` shared by API
   and worker.
4. Start the stack:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

5. Open `http://localhost:8080`. Inspect readiness at
   `http://localhost:8080/health/ready`.

The API container runs `alembic upgrade head` before Uvicorn. Its Compose
healthcheck uses `/health/live`, allowing the worker to start without a
dependency cycle. External load balancers should use `/health/ready`, which
requires PostgreSQL, MinIO, Valkey, and a fresh worker signal.

To stop without deleting data:

```powershell
docker compose down
```

To delete the local Postgres, Valkey, and MinIO volumes as well:

```powershell
docker compose down --volumes
```

## Database migrations

Production must set `DATABASE_AUTO_CREATE=false`. Apply migrations as a
one-shot release task before starting new API/worker replicas:

```powershell
docker compose run --rm api alembic -c alembic.ini upgrade head
```

Create and review future revisions from `backend/`:

```powershell
alembic -c alembic.ini revision --autogenerate -m "describe change"
alembic -c alembic.ini upgrade head
```

Never run multiple independent migration tasks concurrently. Back up Postgres
and MinIO before applying a destructive migration.

## Concurrency and recovery guarantees

- A queued Job is claimed with `UPDATE ... WHERE status='QUEUED'` in the same
  transaction that creates its candidates and trials. A crash rolls the whole
  dispatch back; a competing worker cannot create duplicates.
- A Trial claim increments `attempt_count` and carries a renewable lease.
  Heartbeats use a separate short transaction while PX4/Gazebo is running.
- Result persistence is fenced by `(trial_id, lease_owner, attempt_count)`.
  If an expired Trial has been reclaimed, an old simulator process may finish
  but its stale metrics and artifacts are discarded.
- Job finalization uses a committed, time-bounded `FINALIZING` lease. The
  database transaction is released before report storage or LLM network I/O;
  cancellation is fenced before any new generation/terminal commit, and a
  crashed worker's stale lease can be reclaimed. One job's finalization error
  is isolated and cannot stop other ready jobs.
- Artifact object keys are deterministic per Job/Trial/type/name. Retrying
  after an object-upload/database boundary overwrites the same private object
  rather than creating an unbounded duplicate.

Set `WORKER_LEASE_SECONDS` longer than expected transient database outages,
and keep `WORKER_LEASE_HEARTBEAT_SECONDS` comfortably below one third of the
lease. The code clamps an oversized heartbeat interval at runtime.

## Scaling for the initial 20-user service

Start with one API replica and one simulation worker on a 16-core/32-GB host.
The current worker process executes one Trial at a time. For the mock backend,
additional worker replicas can drain independent trials:

```powershell
docker compose up -d --scale worker=3
```

PostgreSQL conditional claims make database work ownership safe, but the bundled
PX4/Gazebo wrapper still defaults MAVSDK to UDP 14540 and does not allocate a
complete per-instance port set. Therefore run at most **one `real_cli` trial per
host**. Do not use `--scale worker=3` for real simulations on one host until an
operator supplies a matching PX4/Gazebo/MAVSDK instance-and-port allocator.
For higher real load, place one worker on each compute node with the same
database, Valkey, and S3-compatible endpoints. Measure CPU, peak RSS,
simulation wall time, object volume, and failure recovery before increasing the
fleet.

## Production checklist

- Use `AUTH_MODE=oidc_jwt` before public launch and configure
  `OIDC_ISSUER`, `OIDC_AUDIENCE`, and the HTTPS `OIDC_JWKS_URL`. The API pins
  asymmetric algorithms, validates issuer/audience/expiry/subject, and keys
  user ownership by `(issuer, subject)` rather than mutable email. Demo tokens
  remain an interim staging mechanism; production refuses anonymous
  `AUTH_MODE=disabled`.
- Terminate TLS at the load balancer or reverse proxy and restrict Postgres,
  Valkey, MinIO API, and the MinIO console to private networks.
- Use managed secrets, unique high-entropy credentials, bucket encryption,
  versioning/lifecycle rules, and database/object-store backups.
- Keep the bucket private. S3 storage exposes short-lived presigned download
  capability; local storage continues to use API streaming for compatibility.
- Local-only installations can use the opt-in, DB-safe capacity policy in
  [Local Artifact Capacity and Retention](./13-artifact-retention.md). S3/MinIO
  deployments should keep cleanup disabled and configure bucket lifecycle rules.
- Pin and scan all images. The Compose tags are a tested baseline, not an
  automatic upgrade policy.
- Send structured logs and metrics off-host. Alert on `/health/ready`, queue
  age, missing worker heartbeat, expired/reclaimed leases, failed Trials,
  PostgreSQL saturation, and MinIO capacity.
- Do not expose the MinIO console port or the development demo token on an
  Internet-facing deployment.

## Region layout

For an initial China/US audience, run a single control-plane region and keep
simulation asynchronous. When measured latency or residency requirements
justify expansion, deploy separate regional cells (database, Valkey, bucket,
and workers per cell) and assign each project a home region. Avoid stretching
one transactional database across China and the US.
