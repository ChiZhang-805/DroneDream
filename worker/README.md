# DroneDream Worker

Background worker for DroneDream. It polls the DB-backed queue, claims jobs and
trials with renewable leases, runs the selected simulator/optimizer loop, and
finalizes reports and artifacts. The backend package is installed into the same
environment because orchestration and ORM code are shared.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ../backend
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m drone_dream_worker.main
# or, after install:
.venv/bin/drone-dream-worker
```

The worker preserves the `CREATED -> QUEUED -> RUNNING -> AGGREGATING ->
FINALIZING -> terminal` state contract. Leases fence stale workers, and
`FINALIZING` remains cancellable and reclaimable while reports and LLM summaries
are produced outside a long database transaction.

`mock` is synthetic workflow evidence. `real_cli` executes the external
PX4/Gazebo artifact contract and, in the bundled single-host configuration,
runs at most one real trial at a time because PX4/Gazebo share ports and process
state. Static obstacle injection has a verified bundled path; unsupported
wind/gust, sensor/GPS, battery, payload, and actuator-delay effects fail closed.
The internal `real_stub` adapter is test-only.

```bash
.venv/bin/ruff check .
.venv/bin/mypy drone_dream_worker
.venv/bin/pytest
```

Press `Ctrl+C` to stop; the worker logs a clean shutdown message.
