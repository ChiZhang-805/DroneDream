# Local Implementation Status (Phases 0-6)

This document separates locally implemented code from deployment and real-SITL
acceptance work.

## Phase 0 - Baseline and safety: complete locally

- Repository baseline, backend/frontend tests, build flow, and migration path audited.
- Strict request validation, production configuration guards, structured errors, and
  secret redaction are in place.
- Existing API clients retain a legacy six-parameter compatibility path.

## Phase 1 - PX4 parameter engine: complete locally

- Versioned bilingual 45-parameter multicopter catalog with control-loop grouping, hard/safe
  bounds, risk notes, dependencies, defaults, and tuning order.
- User-selectable real PX4 parameter domains with validation for continuous and
  discrete values.
- Parameters flow from candidate to `real_cli`, are applied before flight, read back,
  and persisted as requested/before/applied evidence.

The curated catalog is intentionally smaller than the full PX4 parameter universe;
new entries can be added without changing the experiment contract.

## Phase 2 - Experiment builder: complete locally

- Five-step basic/advanced/expert wizard with gated navigation and automatic draft persistence.
- Vehicle/PX4 profile, multi-objective definition, parameter selection, explicitly
  selectable search/holdout scenario matrix, XY/XZ/YZ/3D waypoint editor, optimizer/provider
  choice, validation, review, and drafts.
- Chinese/English application shell and responsive experiment UI.

## Phase 3 - Optimization and orchestration: complete locally

- Keyless deterministic design, generic CMA-ES, provider-neutral LLM proposals,
  and seven experimental accuracy-first engines: constrained MOBO,
  multi-fidelity MOBO, TuRBO, SAASBO, surrogate-assisted CMA-ES,
  BIPOP-CMA-ES, and an adaptive optimizer portfolio.
- Linear/log/stepped/integer/boolean/enum projection.
- Fixed scenario matrices, common random numbers, two-level case/seed weighted
  rates, worst-max-error acceptance, hard/soft constraints, budget enforcement,
  renewable trial leases, cancellable finalization leases, and fencing.
- Holdout scenarios are excluded from optimizer training, acquisition feedback,
  early stopping, candidate-history feedback, and LLM prompts. When a suite
  includes holdout cases, a candidate must nevertheless complete them and pass
  holdout validation before it is eligible for the final recommendation.

## Phase 4 - Results and visualization: complete locally

- Generation trend, candidate comparison, feasibility, Pareto front, representative
  recommendations, trajectory replay, artifact access, and report APIs.
- Gazebo/noVNC live viewing remains available when the runtime exposes a viewer URL.

## Phase 5 - Multi-user and deployment foundation: complete locally

- Demo-token and OIDC/JWKS authentication modes with issuer/subject user isolation.
- PostgreSQL/Alembic, S3-compatible artifact storage, atomic job claims, worker
  heartbeat/readiness, Dockerfiles, Compose topology, and deployment guidance.
- Regional deployment cells can share product conventions while keeping simulation
  workers and data in-region.

## Phase 6 - Acceptance: partially environment-dependent

Locally complete:

- Backend unit/integration suite, frontend tests/typecheck/build, schema migration
  checks, dry-run runner protocol, parameter evidence checks, timeout/process cleanup,
  and per-job vehicle/world launch configuration.

Requires a Linux PX4/Gazebo host:

- Build the exact PX4 version/commit and selected Gazebo models/worlds.
- Run a real write/readback/takeoff/track/land smoke test.
- Validate wind/gust, sensor/GPS degradation, payload/battery, and actuator
  effects for each site-specific world/plugin. Static box/cylinder obstacle
  injection is implemented in the bundled runner source and still requires a
  released Runtime plus real-host smoke evidence for customer acceptance.
- Unsupported requested effects fail closed. The bundled single-host real
  runner also runs at most one real trial at a time.
- Load-test the intended worker count and tune CPU/RAM/queue limits before public use.

Server provisioning and public DNS/TLS are deliberately deferred until the real-SITL
acceptance image is selected.
