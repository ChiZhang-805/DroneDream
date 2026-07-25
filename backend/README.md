# DroneDream Backend

FastAPI app for DroneDream. Ships the `/api/v1` experiment, trial, report,
artifact, catalog, capability, and compatibility surfaces backed by SQLAlchemy, plus
the standard response envelope helpers and the orchestration package the
worker uses to dispatch and finalize jobs.

## What lives here

- `app/main.py` — FastAPI application factory, CORS, exception handlers,
  router registration.
- `app/routers/` — HTTP surface:
  - `health` — public `GET /health`, `/health/live`, and `/health/ready`
    outside `/api/v1`.
  - `jobs` — create/list/detail/update/delete, rerun/cancel, bounded trials and
    candidates, report/artifacts, and JSON/CSV experiment comparison.
  - `trials` — `GET /api/v1/trials/{trial_id}`.
  - `artifacts` — authorized managed-local download or owned S3 redirect.
  - `batches` — compatibility-only create/list/detail/jobs/cancel API. The
    desktop batch pages are retired and redirect to the overview.
  - `parameter_catalog` — versioned PX4 multicopter parameter metadata,
    compatibility filters, guided presets, and server-side search-space validation.
  - `capabilities` — advisory worker/simulator/optimizer readiness used by the
    experiment wizard before dispatch (job creation remains authoritative).
  - `session` — authenticated identity probe used by the packaged desktop
    startup gate before it can report 100% ready.
- `app/schemas.py` — Pydantic v2 request/response models + enum literals.
- `app/models.py` — SQLAlchemy ORM models including `User`, `BatchJob`, `Job`,
  `JobSecret`, `CandidateParameterSet`, `Trial`, `TrialMetric`, `JobReport`,
  `Artifact`, and `JobEvent`.
- `app/services/` — request-safe business logic (create / list / rerun /
  cancel / serialize). Never runs a trial.
- `app/orchestration/` — worker-side job manager, trial executor,
  aggregator, optimizer, report generator. Shared with the worker
  process via an editable install.
- `app/simulator/` — `SimulatorAdapter` base, `MockSimulatorAdapter`
  (synthetic test/demo path), the subprocess-isolated `RealCliSimulatorAdapter`, and
  PX4 parameter application/readback evidence helpers.
- `app/response.py` — `ok(data)` / `err(code, message, details)` helpers
  that emit the standard response envelope.

## PX4 parameter catalog contract

The read-only catalog is available at `GET /api/v1/parameter-catalog`. It contains
45 curated PX4 parameters across angular-rate, attitude, thrust/authority,
filtering, horizontal/vertical position, and motion-limit groups. Every entry
includes units, PX4 hard bounds, conservative DroneDream bounds, step/default,
risk and bilingual guidance, control-loop/axis metadata, apply policy, supported
PX4/vehicle/airframe contexts, dependencies, evidence metrics, and supported
application interfaces (`mavsdk` and `px4_startup_env`).

The live MAVSDK transaction refuses every `requires_reboot`/`apply_policy=reboot`
parameter because its get/set-only client cannot restart PX4 safely. Apply those
values as `PX4_PARAM_*` startup overrides to a fresh SITL process and verify the
post-start readback before flight; the environment transport implements that
evidence path.

`recommended_metrics` is deliberately limited to metrics the current trial
contract can aggregate (`rmse`, `max_error`, `overshoot_count`,
`completion_time`, flags, score, and final error). PX4/uORB signals that a
future runner should capture for deeper loop analysis are listed separately as
`evidence_signals`, so clients do not mistake unavailable telemetry for a valid
optimization objective.

Useful catalog operations:

- Filter `GET /api/v1/parameter-catalog` with `px4_version`, `vehicle_type`,
  `airframe`, `group`, `control_loop`, `axis`, or `risk`.
- Read the inside-out workflow and preconditions from
  `GET /api/v1/parameter-catalog/groups`.
- Start from the eight ordered workflows returned by
  `GET /api/v1/parameter-catalog/presets`.
- Validate selected bounds, catalog identity, type/step, compatibility, baseline,
  and executable cross-parameter constraints with
  `POST /api/v1/parameter-catalog/validate`.

Jobs must use the exact `catalog_version` returned by the API or an explicit
compatibility alias (`builtin-v1`, `px4-v1.16`, `px4-v1.17`, `px4-main`). Unknown
identifiers are rejected, and a version-specific alias must agree with
`vehicle_profile.px4_version`; this prevents an arbitrary label from silently
selecting a newer installed catalog. The immediately preceding canonical `r1`
identifier is also retained as a migration alias for already persisted jobs.
Aliases are normalized at the API boundary: every newly created job, rerun,
LLM prompt, report, and reproducibility manifest stores the canonical `r2`
identifier that actually performed validation.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/uvicorn app.main:app --reload --app-dir . --host 127.0.0.1 --port 8000
```

## Quality checks

```bash
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest
```

## Key environment variables

- Worker lease / reclaim:
  - `WORKER_LEASE_SECONDS` (default `900`)
  - `WORKER_STALE_RUNNING_RECLAIM_ENABLED` (default `true`)
  - `FINALIZATION_LEASE_SECONDS` (must cover the configured LLM timeout and
    retry window; default `900`)
- Real simulator execution:
  - `SIMULATOR_BACKEND=real_cli`
  - `REAL_SIMULATOR_COMMAND` (PX4/Gazebo runner executable plus arguments)
  - `REAL_SIMULATOR_TIMEOUT_SECONDS` (the finite positive 1x simulation budget,
    default `300`; factors from `0.1` to `<1` expand wall time by `1/factor`, up
    to `10x`)
  - `REAL_SIMULATOR_ARTIFACT_ROOT` (transient per-attempt run data)
  - `REAL_SIMULATOR_KEEP_RUN_DIRS` (failed runs are always retained; successful
    runs are removed only after artifact persistence when set to `false`)
  - simulator children receive only an OS/Python/PX4/Gazebo runtime allowlist;
    database, S3/cloud, OIDC/LLM, and `*KEY*`/`*TOKEN*`/`*SECRET*` credentials
    are never inherited
- Artifact storage backend:
  - `ARTIFACT_STORAGE_BACKEND=local|s3` (default `local`)
  - `S3_ENDPOINT_URL` (optional, for MinIO/custom endpoints)
  - `S3_REGION` (optional)
  - `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
  - `S3_PREFIX` (optional, default `dronedream/`)
  - `S3_CONNECT_TIMEOUT_SECONDS`, `S3_READ_TIMEOUT_SECONDS`,
    `S3_MAX_ATTEMPTS` bound object-storage stalls and retries
- Packaged desktop runtime readiness:
  - `DRONEDREAM_RUNTIME_ID` (canonical runtime-manifest UUID)
  - `DRONEDREAM_PX4_EXECUTABLE` (executable PX4 path)
  - `DRONEDREAM_GAZEBO_EXECUTABLE` (executable Gazebo path)
  - `REDIS_URL` plus a live worker heartbeat; worker presence becomes mandatory
    whenever `DRONEDREAM_RUNTIME_ID` is configured
- Authentication:
  - `AUTH_MODE=disabled|demo_token|oidc_jwt` (default `disabled`; production
    and packaged `APP_ENV=desktop` runtimes refuse disabled mode)
  - `DEMO_AUTH_TOKENS` format:
    `user1@example.com:token1,user2@example.com:token2`
  - OIDC mode requires `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, and
    asymmetric `OIDC_ALGORITHMS`
- LLM safety and cleanup:
  - `JOB_SECRET_TTL_SECONDS`, `JOB_SECRET_CLEANUP_INTERVAL_SECONDS`
  - `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`,
    `LLM_MAX_RESPONSE_BYTES`, `LLM_MAX_PROMPT_BYTES`

Candidate completion/pass/failure rates are scenario-case weighted, with every
dispatched seed retained in its case denominator. Acceptance uses
`max_error_worst`; reports also preserve the historical mean and explicit
holdout validation status. `FINALIZING` is a committed bounded lease so slow
LLM/report work does not hold a database transaction, remains cancellable, and
can be reclaimed after a worker crash.

The bundled real runner proves nominal execution and static box/cylinder
obstacle injection (Gazebo EntityFactory success plus generated-SDF evidence).
Wind/gust, sensor/GPS, battery, payload, actuator-delay, and other requested
physical effects fail closed until a site launcher applies them and returns
validated evidence. `real_stub` is an internal test adapter and is rejected
outside `APP_ENV=test`.
