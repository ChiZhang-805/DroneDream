# Simulator Adapters

DroneDream uses a pluggable simulator interface in `backend/app/simulator/`.

## Adapter contract

- `base.py`: shared adapter protocol and result schema.
- `factory.py`: selects adapter by `simulator_backend` (`mock` / `real_cli`).

## Implemented adapters

### `mock`

- Deterministic/local simulation for fast CI and API validation.
- No PX4/Gazebo runtime dependency.
- Best for unit/integration tests and frontend development.

### `real_cli`

- Calls external scripts (PX4/Gazebo tooling) and ingests normalized artifacts/metrics.
- Used for real SITL-style execution when environment is prepared.
- Artifact payload format documented in [REAL_CLI artifact schema](./REAL_CLI_ARTIFACT_SCHEMA.md).

## Current capabilities

- Runtime backend selection per job.
- Compatible with heuristic/GPT/CMA-ES optimization loops.
- Real adapter outputs are consumed by existing report + artifact API flow.

## Limitations / roadmap

- Real adapter requires environment bootstrapping and external dependencies.
- Adapter health/preflight endpoint is still minimal; failures are mainly surfaced as job/trial error states.
