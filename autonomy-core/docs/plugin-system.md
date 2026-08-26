# Plugin system

DroneDream AUTONOMY uses two plugin tiers around an immutable mission and safety kernel.
The desktop tier accepts user-installed ZIP bundles and runs executable tools and
Harness Hooks through MCP stdio subprocesses that receive no model keys. The runtime
tier uses ROS 2 `pluginlib` inside a `LifecycleNode`; only capabilities delivered by the
certified installer enter that native control-policy boundary.

The design borrows three ideas from Cordis without taking a runtime dependency on it:

- a context owns a capability and its cleanup scope;
- registration creates a reversible effect represented by lifecycle receipts, process
  teardown, and version activation records;
- withdrawal blocks new calls and drains existing consumers before disposal.

## Package contract

Every bundle contains `plugin.json` plus every file named in `file_sha256`. The manifest
declares one immutable plugin ID/version, runtime, capabilities, JSON input/output
schemas, permissions, dependencies, conflicts, configuration schema, removal policy,
failure policy, swap policy, and UI placement.

Placement assigns every plugin to a typed slot:

- `single` has exactly one active implementation. Enabling an alternative first blocks
  new calls to the old implementation, drains old calls, enforces its swap policy, and
  commits both lifecycle changes in one SQLite transaction.
- `multiple` keeps independent implementations active together.
- `pipeline` topologically orders enabled stages using `runs_after`, `runs_before`, and
  `pipeline_order`. Ordering cycles and mixed activation modes are rejected.

The importer rejects traversal paths, symlinks, undeclared files, hash drift, invalid
JSON Schema, unsupported app versions, missing dependencies, uncertified actuator
authority, and reused versions with different bytes. An update is staged beside the
active version rather than overwriting it. Rollback follows the same drain-and-activate
path. Enabled reverse dependencies prevent unsafe withdrawal.

Route, clearance, PX4-track, simulator, and safe-hold are protected slots. The first
three expose certified first-party alternatives; simulator and safe-hold remain
non-disableable until another certified implementation exists. User bundles cannot claim
protected slots or actuator authority.

## Lifecycle and hot swap

The durable states are:

```text
discovered → staged → installed → starting → healthy
                                     │          │
                                     └→ quarantined
healthy → draining → disabled → uninstalled
                   ↘ activate/rollback → starting
```

Every transition writes a `PluginLifecycleReceipt`. Every prepared mission stores a
`PluginSnapshot` containing plugin ID, version, package hash, manifest hash,
configuration hash, exact capability IDs, immutable manifest, and installed bundle
location. First-party definitions are rebuilt from code. Imported MCP tools and Harness
Hooks are rebuilt from the snapshot only after every declared file hash is rechecked.
Tool and Hook receipts repeat the supplying plugin and package hash.

Disabling changes the next catalog without corrupting an in-flight snapshot. Swap
policies are enforced as follows:

- `anytime`: future resolutions stop using the plugin immediately;
- `next-mission`: a running mission keeps its frozen instance;
- `safe-hold`: affected missions must acknowledge deterministic hover before commit;
- `restart` and `certified-update`: change is rejected while an affected mission runs.

Uninstall is stronger than disable and is rejected while an active mission still owns
the bundle. Failed single-slot swaps and failed persona changes restore the previous
catalog atomically. A crash, timeout, malformed response, schema mismatch, or file drift
quarantines the executable plugin rather than silently falling through to another one.

## Desktop MCP boundary

MCP executables must live inside their bundle. The host resolves the executable under
the bundle root, strips the environment to a small allowlist, never passes provider
keys, uses bounded startup/call deadlines, limits protocol messages and tool payloads,
and terminates the process after health checks and calls. `tools/list` must exactly match
the manifest IDs and schemas.

Imported plugins may expose a related suite of ordinary tools and multiple Harness Hook
capabilities. Every capability has its own schema and least-privilege permission scope,
even when the capabilities share one persistent MCP session. Supported Hooks cover
request enrichment, structured intent, task graphs, semantic and track
optimization, role routing, Prompt packs, context compaction/enrichment, output guards,
plan scoring and validation, tool routing/middleware/fusion, checkpoints, anomaly
detection, online-replan anchor choice, campaign definitions, preflight/runtime
evaluation, evidence export, plan notifications, and staged asset conversion. Every call
rechecks the exact bundle bytes and the declared input/output Schemas. Pipeline Hooks
return a structured `value` envelope; invalid output follows the slot's `fail-closed`,
`isolate`, or `advisory` policy.

The model sees a structured optional-tool catalog only after the mission contract is
frozen. Workflow plugins set bounded routing rounds, planning loops, and maximum plugin
calls inside hard core caps. Tool results are evidence for later reasoning; they cannot
change the confirmed contract, issue controls, or replace deterministic route,
clearance, PX4-track, and completion gates.

Map and vehicle converters use a narrower protocol. A selected external converter gets
the source archive and one host-created output path. It may write a canonical candidate
only to that staging path and must return its SHA-256. The host verifies the digest and
then runs DroneDream's own asset qualification/importer. The plugin never receives the
asset database object and cannot bypass qualification.

## Categories and slots

The current first-party catalog contains 207 implementations in 88 slots across 18
categories. One hundred fifty conservative stages are enabled by default; alternatives
remain visible and can be selected directly or through an atomic Harness profile. The
verification catalog additionally imports the signed Mission Evidence Gate MCP package,
bringing the resolved catalog to 208 plugins in 89 slots and 19 categories without
changing the default enabled count.

| Area | Composable slots | Representative implementations |
| --- | --- | --- |
| Harness | persona profile, workflow topology | balanced, indoor, payload, evaluation, field, inspection, survey, emergency, privacy, plugin developer |
| Input | request features, intent normalization | language/directive features, constraint/entity normalization |
| Models | provider, role policy, Prompt pipeline, output guards | seven managed models plus custom OpenAI-compatible models; specialist/unified/adversarial roles |
| Context | compaction and enrichment | structured window, event ledger, map ontology, identity, safety boundary |
| Planning | task/semantic/track transforms, route strategy, scorers | retry/evidence transforms, four route strategies, speed and corner envelopes, four metrics |
| Tools | professional advisors, router, middleware, fusion | energy, link, landing, payload, privacy, inspection, reproducibility; hybrid/model/safety routing |
| Validation | plan gates, clearance, interruption | route/payload/stability/energy gates, standard/conservative clearance, certified safe hold |
| Runtime | checkpoints, anomaly detectors, replan policy, track export | segment/boundary checkpoints, telemetry/tracking/battery gates, nearest/verified anchors |
| Simulation | campaign and fault-scene definitions, certified adapter | acceptance/stress matrices, wind/delay/battery/obstacle scenarios, Gazebo + PX4 SITL |
| Evidence | preflight/runtime evaluators and exporters | readiness/complexity, binding/runtime gates, JSON/CSV/GeoJSON |
| Assets and UI | map/vehicle importer, voice, notifications, panels | canonical or staged conversion, Web Speech/audio, plan/checklist/metrics notices |

The desktop reads labels, categories, ordering, activation mode, permissions, failure
mode, swap policy, versions, health, and configuration schema from manifests. It does
not maintain a second hard-coded plugin list. The page itself scrolls so the scrollbar
stays at the far-right window edge.

## Native ROS 2 boundary

`dronedream_agent_plugin_api` defines a C++ capability interface, pluginlib loader probe,
and lifecycle host. Provisioning compiles the package and requires both the loader probe
and a configure→activate→deactivate→cleanup self-test. A mission starts the host before
the executor and tears it down on every exit. The current certified plugin is the
reversible safe-hold control policy. UI imports cannot cross this boundary; native
bundles require a signed certified installer path.

The following remain intentionally non-user-hot-swappable: the 20 Hz actuator loop,
emergency stop, final collision/clearance authorization, contract confirmation, native
Gazebo/PX4 adapter, credential vault, and ROS 2 safe-hold host. These are certification
or secret-ownership boundaries rather than missing plugin slots. Plugins above them may
propose routes, policies, thresholds, and evidence, but cannot grant themselves control.

## Verification

## Developer SDK and publishing flow

The `dronedream-plugin` CLI provides one reproducible path from a new plugin to a
locally verified package. It does not copy developer keys into a bundle.

```powershell
dronedream-plugin init .\my-plugin --plugin-id example.inspector --name Inspector --publisher Example
dronedream-plugin validate .\my-plugin
# MCP scaffolds are compiled to the bundled bin/plugin.exe by build.ps1.
dronedream-plugin keygen .\publisher-key.json --key-id example.publisher.v1 --publisher Example
dronedream-plugin pack .\my-plugin --output .\dist\example.inspector.zip --signing-key .\publisher-key.json
dronedream-plugin sandbox .\dist\example.inspector.zip
```

The public `dronedream_plugin_sdk` package supplies `McpPluginServer`, `ToolSpec`, and
`ToolContext`. It implements initialization, heartbeat, exact tool catalogs, structured
results, progress and cancellation while validating both sides of every tool call with
JSON Schema. Packaging recalculates every declared file hash, emits a CycloneDX SBOM,
binds provenance to that SBOM, signs the normalized manifest with Ed25519, and creates a
ZIP with fixed member ordering and metadata. The sandbox imports the real ZIP through
the production `PluginManager`, locally approves only its exact hash, enables it, runs
the production health check, disables it, and reports lifecycle receipts or quarantine.

Private publisher keys stay outside source and packages. The public key is added through
the publisher-trust API before a signed package can be enabled without local approval.
Official publication additionally requires the repository tests, official external
plugin verification, and the relevant native certification gate for ROS 2 plugins.

`Mission Evidence Gate` is built as a separate Windows EXE and official plugin ZIP. Its
verification imports the ZIP, checks index and file hashes, starts the real MCP process,
checks the hash-bound receipt, performs repeated enable/disable cycles, and confirms a
crashing sibling is quarantined without degrading the safety kernel.

```powershell
scripts\build-official-plugins.ps1 -OutputRoot artifacts\official-plugins
.venv\Scripts\python.exe scripts\verify_official_plugin.py `
  artifacts\official-plugins `
  app\desktop\src-tauri\target\release\dronedream-plugin-isolator.exe
.venv\Scripts\python.exe scripts\audit_plugin_catalog.py `
  artifacts\verification\plugin-audit-state-v3 `
  artifacts\verification\plugin-catalog-audit-v3.json `
  --official-plugins-root artifacts\official-plugins `
  --plugin-isolator-path app\desktop\src-tauri\target\release\dronedream-plugin-isolator.exe
```

Unit and integration tests additionally cover atomic single-slot swaps, persona bundle
rollback, frozen configuration, runtime swap policies, uninstall protection, external
Hook and tool reconstruction from snapshots, per-call file/schema checks, and staged
external map/vehicle conversion.
