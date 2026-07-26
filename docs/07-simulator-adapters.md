# Simulator Adapters

DroneDream uses a pluggable simulator interface in `backend/app/simulator/`.

## Adapter contract

- `base.py`: shared adapter protocol and result schema.
- `factory.py`: selects the per-job adapters (`mock` / `real_cli`). The internal
  `real_stub` path exists only for automated tests and is rejected outside
  `APP_ENV=test`; it is not a deployable simulator backend.

## Implemented adapters

### `mock`

- Deterministic/local simulation for fast CI and API validation.
- No PX4/Gazebo runtime dependency.
- Best for unit/integration tests and frontend development.

### `real_cli`

- Calls external scripts (PX4/Gazebo tooling) and ingests normalized artifacts/metrics.
- Used for real SITL-style execution when environment is prepared.
- Artifact payload format documented in [REAL_CLI artifact schema](./REAL_CLI_ARTIFACT_SCHEMA.md).
- Scenario effects use the request/evidence boundary documented in
  [DroneDream Harness Engineering](./17-harness-engineering.md).

## Current capabilities

- Runtime backend selection per job.
- Compatible with the optimizer strategies documented in
  `09-optimizer-guide.md`.
- Real adapter outputs are consumed by existing report + artifact API flow.

## Limitations / roadmap

- Real adapter requires environment bootstrapping and external dependencies.
- Static obstacle injection has a verified bundled implementation in source.
- Constant horizontal wind for the bundled `x500` family has a verified source
  implementation: a Trial-local world/model overlay enables link wind,
  publishes the compiled vector, and retains exact `wind_info` plus expanded
  runtime-SDF read-back evidence. The dedicated WSL Runtime smoke passed against
  pinned PX4 commit `6ea3539157ca358c70a515878b77077af7d4611d` and Gazebo
  8.14.0; it is not a released customer capability until the rebuilt,
  installer-delivered Runtime passes the same gate.
- Gust/turbulence, sensor degradation, GPS dropout, battery, payload, and
  actuator effects remain explicit Runtime extensions until their application
  and read-back evidence are implemented and pass that gate.
