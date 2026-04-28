# Simulator Adapters

## Built-in adapters

- `mock`: fast deterministic simulation for local testing.
- `real_cli`: invokes external runner tooling for PX4/Gazebo integration.

## Protocol artifacts

Current adapter protocol uses JSON files in run directories:

- `trial_input.json`: worker-generated input contract for one trial.
- `trial_result.json`: simulator output consumed by orchestration.

See also: [REAL_CLI_ARTIFACT_SCHEMA.md](./REAL_CLI_ARTIFACT_SCHEMA.md).

## Add a new simulator backend

1. Implement adapter class under `backend/app/simulator/` extending base adapter interface.
2. Register it in `backend/app/simulator/factory.py`.
3. Ensure returned result payload can be mapped to trial metrics/artifacts.
4. Add backend tests covering success + failure paths.

## Roadmap

- Standardize richer telemetry schema across all adapters.
