# DroneDream Flight Agent Core

Public autonomy core for DroneDream's five-product suite. It contains the
orchestration, structured contracts, safety gates, ROS 2 integration,
PX4/Gazebo execution adapter, and acceptance evidence without duplicating the
shared product shell in `frontend/`, `desktop/`, and `backend/`.

This is not a toy simulator and it has no mock model path. The verified milestone
uses real provider calls, ROS 2 Jazzy, `ros_gz_bridge`, Gazebo Sim physics, PX4 SITL,
and MAVSDK offboard control against the qualified School Map world.

## What is implemented

- Multi-call workflow: intent extraction, intent critique, task decomposition,
  route planning, plan critique, runtime checkpoint assessment, and completion review.
- Strict Pydantic input/output at every model, tool, process, and evidence boundary.
- Bounded propose/critique/repair loops for intent and planning.
- Two-tier plugin system: 105 first-party implementations across 38 typed slots and
  10 atomic persona profiles, plus transactional user ZIP/MCP tools and certified ROS 2
  `pluginlib`/Lifecycle capabilities. Harness hooks cover prompts, context, planning,
  tools, runtime decisions, simulation campaigns, evidence, evaluation, and staged asset
  conversion with schemas, permissions, dependency guards, hot-swap policies, rollback,
  quarantine, and task-bound plugin snapshots.
- Durable conversation and mission context with bounded compaction.
- Stable task-thread identity with parent-linked plan revisions and a unique execution ID
  for every confirmed launch.
- Deterministic safety gates that a model cannot bypass.
- Segment-boundary runtime checkpoints while PX4 holds position in the real simulator.
- Execution-time user-message ingress inside the 20 Hz PX4 loop: freeze the old track,
  inhibit semantic side effects, establish a telemetry-gated hover, then call the model.
- Append-only hash-linked evidence and immutable-run re-verification.
- Explicit mission-contract confirmation before any execution process is launched.
- Evidence-bound default `School Map` and `My Drone` bundles that seed the desktop map
  and vehicle repositories idempotently on first launch.

The model advises mission-level decisions. It never receives raw actuator authority;
the 20 Hz offboard loop, coordinate conversion, collision gates, and safety exits remain
deterministic code.

## Current verified milestone

The current end-to-end acceptance is `execution-interrupt-10`. A real user-style
Chinese request produced a new five-call structured plan for `School Map` and
`My Drone`. During real PX4/Gazebo execution, a second user message cancelled the
destination and requested an immediate safe return to the third-floor office pad:

- the 20 Hz executor detected the message in 14 ms and established stable hover in
  1.099 s before the model call;
- DeepSeek classified the amendment in 25.028 s while deterministic code held position
  and inhibited old-plan side effects;
- code resolved the natural-language destination to `verified-000`, built a new
  continuously clearance-checked three-node route, and accepted it only after nine
  replacement gates and a hash-bound executor adoption receipt passed;
- the durable lifecycle automatically resumed from `holding` to `executing`, PX4 landed
  `ON_GROUND`, all nine runtime gates passed, the completion model accepted the evidence,
  and the task ended in `completed`;
- the 20,919,357-byte PX4 ULog and all compact evidence hashes are recorded in
  [`evidence/user-closed-loop-20260819.json`](evidence/user-closed-loop-20260819.json).

The earlier checkpoint-only acceptance remains useful historical evidence:

The recorded checkpoint acceptance evidence shows:

- 10 real DeepSeek calls: 5 planning, 4 in-flight checkpoints, 1 completion review;
- 4/4 checkpoint decisions accepted and independently authorized by code;
- 19,685 Gazebo poses and 6,092 ROS observations;
- minimum goal distance 0.229 m and final PX4 state `ON_GROUND`;
- 91,268,217-byte PX4 ULog with a recorded SHA-256;
- all binding, process, timing, goal, landing, and safety gates passed.

See [`evidence/verified-simulation-run.json`](evidence/verified-simulation-run.json)
for the portable evidence manifest. Large generated run artifacts and flight logs stay
outside Git; the manifest binds their immutable hashes and locations.

The recorded negative-path runtime-interruption acceptance injected a real user message while
the aircraft was tracking. The executor detected it in 43 ms, reached stable hover in
1.617 s, held throughout a 28.272 s real DeepSeek classification, then landed with PX4
state `ON_GROUND`. The original mission was correctly recorded as failed/superseded, not
as a false success. See
[`evidence/runtime-interruption-acceptance.json`](evidence/runtime-interruption-acceptance.json).

## Repository map

```text
src/dronedream_agent_core/
  contracts.py       Versioned structured artifacts
  model_port.py      Real OpenAI / DeepSeek / Kimi model boundary
  prompts.py         Bounded role prompts
  orchestrator.py    Multi-call planning state machine
  checkpointing.py   Live checkpoint coordinator and hard gates
  lifecycle.py       Stable task, plan-revision, and execution identities
  runtime_interrupt.py Runtime ingress and code-owned authorization
  execution.py       Contract-confirmed execution and completion review
  tools.py           Plugin registry, authority gates, and receipts
  plugin_contracts.py Versioned package, lifecycle, and snapshot contracts
  plugin_process.py  Isolated MCP stdio process boundary
  context.py         Bounded durable conversation context
  navigation.py      Generic graph routing
  collision.py       Static route-clearance validation
  px4_track.py       ENU-to-PX4 track construction
  gazebo_adapter.py  ROS 2 / Gazebo / PX4 lifecycle and evidence
  evidence.py        Append-only hash-linked ledger
ros_ws/              ROS 2 messages and the raw Gazebo observation node
official_plugins/    Source for separately packaged first-party MCP plugins
scripts/             PX4 checkpoint executor, verification, schema export
examples/            Natural-language mission requests
schemas/             Generated JSON Schema boundary definitions
docs/                Architecture and artifact-flow documentation
evidence/            Small, reviewable acceptance manifests
tests/               Pure contract, navigation, evidence, and safety tests
```

The qualified world, semantic map, vehicle, controller configuration, navigation graph,
and qualification receipts remain owned by the public repository's Map Pack, Vehicle
Pack, distribution, and Runtime contracts. This component keeps compact compiled
`School Map` and `My Drone` qualification fixtures under `assets/default` so the
acceptance checks are reproducible. They are not editable source authority: the
product shell resolves the signed, versioned Map/Vehicle Pack identities and passes
only validated asset references into the Harness.

## Development

Python 3.11-3.13 is supported.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check src tests scripts
.venv\Scripts\python.exe scripts\export_schemas.py --check
```

Provider configuration is read from environment variables only. Copy `.env.example`
for the variable names, but do not commit secrets. Planning requires a real provider;
there is intentionally no offline fallback.

Example preparation command:

```powershell
.venv\Scripts\dronedream-agent.exe prepare-mission `
  --provider deepseek `
  --model deepseek-v4-flash `
  --request examples\campus_gate_one_way.json `
  --graph <qualified-graph.json> `
  --semantic <qualified-semantic-map.json> `
  --vehicle-sdf <qualified-vehicle.sdf> `
  --output-dir artifacts\acceptance\campus-gate
```

Execution is intentionally a separate command and requires the exact generated
`contract_id` to be supplied again. Inspect `dronedream-agent --help` and
[`docs/artifact-flow.md`](docs/artifact-flow.md) before running it.

## Runtime verification

From the `DroneDreamRuntime` WSL distribution:

```bash
cd ros_ws
colcon build --symlink-install
cd ..
bash scripts/verify_ros2_dds.sh /tmp/dronedream-dds
bash scripts/verify_ros_gz_school_map.sh /path/to/world.physics.sdf /path/to/my-drone/model.sdf /tmp/dronedream-ros-gz
bash scripts/verify_ros_gz_raw_observer.sh /path/to/world.physics.sdf /path/to/my-drone/model.sdf /tmp/dronedream-observer
```

These checks exercise actual DDS discovery, the actual School Map world and vehicle,
Gazebo-to-ROS clock and dynamic-pose transport, and the repository's ROS observation node.
They are integration evidence, not substitutes for the full PX4 acceptance run.

## Boundaries

- Current scope is simulation. No physical-aircraft adapter is included yet.
- Scheduled model checkpoints remain at semantic segment boundaries. User-message
  detection and old-track inhibition now happen inside the 20 Hz control loop; model
  reasoning begins only after stable-hold evidence exists.
- Runtime destination amendments block old-plan resume, enter a bounded safe hold, resolve
  the new target against the selected map, generate a continuously clearance-checked
  replacement track from the observed hold position, and hot-swap it only after all identity
  and hash gates pass. Missing, late, ambiguous, or unsafe replacements land fail-closed.
- OpenAI, DeepSeek, and Kimi adapters are implemented; every provider still requires a
  valid account, key, and live verification in the target environment.
- Unit tests alone do not qualify an autonomy release. Promotion still requires reviewed
  simulation evidence, exact asset identity, protected repository checks, and the
  product-specific authority gates defined by Universal, SIM, LAB, FIELD, and AUTONOMY.

Read [`docs/architecture.md`](docs/architecture.md) for the authority model and safety
exits before extending the runtime.
Read [`docs/plugin-system.md`](docs/plugin-system.md) for package, lifecycle, isolation,
rollback, Cordis-inspired ownership, and ROS 2 pluginlib details.
