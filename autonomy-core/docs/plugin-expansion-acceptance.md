# Plugin expansion acceptance matrix

This matrix is an implementation gate, not a feature wish list. A row is complete only
when its contract, runtime wiring, failure behavior, evidence, tests, and user-facing
configuration are present. Declaring a capability kind or showing a switch is not enough.

## Immutable kernel

- [x] Mission/thread ownership, contract confirmation, plugin snapshot, and evidence hashes stay core-owned.
- [x] Route clearance, emergency hold/land, actuator authorization, and secret values cannot be relaxed by plugins.
- [x] Package signature, publisher trust, exact-package revocation, permission enforcement, and resource limits are core-owned.
- [x] Safety extensions can tighten a gate but cannot remove a mandatory core gate.

## Harness graph

- [x] Typed DAG contract with dependency-cycle and required-input validation.
- [x] Bounded execution with parallel layers, timeout, retry, fallback, isolation, cache, and circuit breaker.
- [x] Hash-bound node and stage receipts.
- [x] Balanced, committee, and rapid-safe topology alternatives.
- [x] Selected topology is resolved from the plugin snapshot and enforced by mission preparation stages.
- [x] Scheduler, retry, timeout, budget, fallback, cache, event-bus, and observer policy slots are runtime-wired.
- [x] Ten Harness profiles atomically select topology and all managed policy plugins.
- [x] External plugin suites can expose multiple independently permissioned Hooks and tools.

## Input and domains

- [x] Text, voice, camera, API/webhook, and scheduled input channel slots.
- [x] PDF, Office Open XML, image/OCR/VLM metadata, video, ROS bag, point cloud, GeoJSON, BIM/IFC, and CAD decoders.
- [x] Locale/dialect and map-entity resolution pipelines.
- [x] Namespaced action packs have typed inputs, preconditions, completion evidence, fallback, and executor identifiers.
- [x] Delivery, inspection, survey, emergency, maintenance, and core-flight action packs.
- [x] The action catalog and its hash are frozen into each mission contract and validated before planning/execution.

## Models and context

- [x] Provider discovery, official identity/icon metadata, and OpenAI-compatible custom adapters are plugins.
- [x] Per-role model routing supports independently selected primary, critic, safety, and perception connections.
- [x] Consensus/debate, fallback, circuit-breaker, latency, cost, and privacy policies are selectable.
- [x] Multimodal preprocessors, structured-output guards/repair, and token/credit meters are runtime-wired.
- [x] Context store, retrieval, compaction, summarization, and retention policy slots are runtime-wired.
- [x] Connector plugins receive scoped opaque credential references; the core vault never returns raw values to the UI or unrelated plugins.

## Planning, tools, and runtime amendments

- [x] Semantic, temporal, global/local, indoor/outdoor, dynamic-obstacle, energy, link, payload, and regulatory planning specialists.
- [x] Constraint gates, multi-objective ranking, plan alternatives, explanation evidence, and visualization data.
- [x] Tool discovery, permission, bounded parallel execution, cache, retry, provenance, and result fusion.
- [x] Weather, GIS/BIM, QR/RFID/custody, logistics, fleet/ERP, camera/payload, and alert connector contracts are present; account-backed connectors remain disabled until configured.
- [x] Redirect, speed, pause/resume, return, safe-land, return-point, coverage, camera, payload, avoidance, follow, and authenticated takeover amendments.
- [x] Every amendment first enters deterministic hold, inhibits old-plan side effects, is revalidated, and receives core authorization before execution.

## Assets and simulation

- [x] Map format/frame/semantic/seam/intersection/material/physics/navigability/export validators.
- [x] Vehicle CAD/URDF/SDF, mass/inertia, motor/propeller, battery, sensor, controller, payload, and flight-envelope validators.
- [x] Qualified status is produced from immutable check receipts, never a manually trusted flag.
- [x] Gazebo/PX4 is a real runtime adapter; Gazebo, Isaac Sim, AirSim, and Webots have selectable typed descriptors and fail-closed runtime-probe requirements.
- [x] Physics, sensor/noise, weather/light, crowd/traffic, fault, scenario, seed, clock, Monte Carlo, and evaluation slots.

Only Gazebo/PX4 is operationally certified in this repository. The other three
simulator descriptors are deliberately not reported as runnable adapters until their
external runtimes and bridges are installed and a real evidence run passes.

## Native ROS 2 and safety

- [x] Native pluginlib ABI exposes typed configure, observe, propose, execute, hold, health, and evidence methods.
- [x] PX4 transport and the safe-hold control path are operational; telemetry, state estimation, GNSS/VIO/SLAM/UWB, perception, controller, payload/gimbal, and black-box capability contracts are frozen into missions.
- [x] The native watchdog enforces startup and airborne real-time deadlines and publishes a contract-bound fail-closed transition.
- [x] Native changes require verified publishers, certified installation policy, and certified-update activation.

ArduPilot and non-PX4 native capabilities remain certified-disabled descriptors until
their drivers, target hardware, and positive readback tests are available. A descriptor
is not counted as flight authority.

## Isolation, trust, UI, and ecosystem

- [x] Filesystem, network, process, CPU, memory, payload-size, and deadline capability broker with Windows AppContainer/Job Object isolation.
- [x] Persistent MCP sessions support progress, cancellation, resources, subscriptions, heartbeat, and per-capability permission checks.
- [x] Ed25519 package signatures, publisher trust, provenance, exact-package revocation, update rings, quarantine, and rollback.
- [x] JSON Schema generates typed forms; permissions, publisher identity, and trust are shown before activation.
- [x] Declarative panels support bounded forms, actions, data binding, logs, metrics, replay, and telemetry without arbitrary plugin JavaScript.
- [x] Developer SDK, contract tests, local sandbox runner, validation CLI, and official signed publishing flow.
- [x] Marketplace index, tenant allowlists, enterprise deployment policy, audit, and usage/budget views.

## Catalog audit

- [x] `scripts/audit_plugin_catalog.py` validates cardinality, activation modes, capability kinds, and enabled defaults.
- [x] Current audit: 208 total packages including the official external verification package, 89 slots, 19 categories, 150 enabled packages, and 53 slots with alternatives.
- [x] Runtime kinds: 203 built-in Python, four model providers, and one persistent MCP-stdio package.

## Final delivery gates

- [x] Python tests and lint pass.
- [x] Frontend tests, typecheck, and production build pass.
- [x] Official external plugin verification and quarantine tests pass inside the packaged OS isolator.
- [x] ROS 2 native probe, DDS, Gazebo observation, lifecycle/watchdog, and fail-closed actuator tests pass in the provisioned runtime.
- [x] Real configured model calls exercise all seven managed models without exposing credentials.
- [x] Real Gazebo + PX4 user-style closed loops cover plan revision and a TRACK-phase runtime amendment.
- [x] Windows installer builds, installs, launches, and passes rendered desktop QA; the installed sidecar reports ready, renders the qualified default assets, loads all 208 packaged plugins, reads the authenticated avatar and Pro allowance, and shuts down without orphaned core processes.
