# DroneDream distribution contracts

This directory owns source-level contracts shared by the Sim, Lab, and Field
editions and by versioned Vehicle Packs. It does not create separate product
codebases. The three editions must continue to consume the same reviewed core,
and Vehicle Packs must be data and signed assets rather than long-lived source
branches.

## E0 upstream audit

`upstream-sources.v1.json` is the machine-readable source and license audit for
the dependencies that are already in the Runtime Base and for adapters being
evaluated for later editions. The inventory distinguishes:

- `current` or `transitive`: already selected by reviewed Runtime Base pins;
- `evaluated`: an integration boundary has been reviewed but no code or binary
  is bundled;
- `planned`: a future adapter contract only, with no executable capability;
- `integrated-contract`: current build and verification contracts exist, which
  is not a claim that every vehicle or real-airframe combination is validated;
- `contract-only` and `legal-review-required`: must never be presented as an
  installed, runnable, or validated capability.

Every immutable license URL with a recorded SHA-256 was fetched from the named
official repository at the exact commit. Aggregate distributions such as
Ubuntu and Gazebo Harmonic intentionally use `NOASSERTION`: their generated
binary-package closure and package-specific copyright files are authoritative.

The inventory is evidence, not legal advice. Any later decision to copy,
modify, link, bundle, or redistribute a dependency requires a new review of
the exact files and artifact closure. In particular:

- QGroundControl remains an external-launch/config-export integration unless
  its dual-license and binary closure are reviewed;
- ArduPilot and its Gazebo plugin remain separate contract-only families;
- Crazyflie remains contract-only because the official repository currently
  exposes conflicting top-level GPL and README LGPL declarations;
- a simulator model or configuration is not `validated` without a frozen
  execution receipt for that exact Runtime Base, Engine Pack, Vehicle Pack,
  firmware, controller, scenario, and target.

Future E1/E4 contracts will live beside this audit and will bind edition,
capability, Vehicle Pack, composite installation, promotion, rollback, and
download-catalog manifests to one common core source.

## E1 capability and edition contracts

`capabilities/core-capabilities.v1.json` is authoritative for the distinction
between simulated targets, HITL targets, and real hardware. Simulated arming
and parameter writes are deliberately different capabilities from physical
arming and writes. A UI flag is never authority: safety-critical hardware
actions require backend, Runtime, and native enforcement, and an unknown target
is denied. The LLM remains at generation boundaries while PX4 or the selected
vehicle autopilot owns the high-frequency control loop.

The three files under `editions/` describe one common-source product:

- Sim includes the full simulation Runtime profile and forbids physical/HITL
  capabilities;
- Lab declares the combined capability set but remains `contract-only` until
  the hardware bridge and safety fences pass E5;
- Field omits the large simulation module and consumes a compatible trusted
  qualification receipt or performs the prescribed hardware preflight. Its
  lightweight Runtime profile is also still `contract-only`.

All three release branches remain `planned-not-created`. They may be created
only after promotion and branch-protection contracts are validated and the
governance owner explicitly approves creation.

Validate the contracts without installing dependencies:

```powershell
python distribution/tools/distribution_contract.py upstream `
  distribution/upstream-sources.v1.json

python distribution/tools/distribution_contract.py editions `
  --policy distribution/capabilities/core-capabilities.v1.json `
  distribution/editions/sim.v1.json `
  distribution/editions/lab.v1.json `
  distribution/editions/field.v1.json
```

## E1 Vehicle Pack contract

`schemas/vehicle-pack-manifest.schema.json` defines a single versioned pack
format with separate `sim`, `hardware`, `sensors`, and `validation` components.
Every component binds reviewed upstream source IDs, immutable artifact hashes,
license/NOTICE records, a capability-policy hash, and bounded controller
parameters. `sourceBindings.pinSha256` is the deterministic canonical-JSON hash
of the matching E0 inventory `pin` object, so a plausible-looking arbitrary
hash cannot hide source drift. A pack may be `planned` or `contract-only`
without a signature, but it cannot claim a validated tier until a detached
Ed25519 signature and at least
one validation artifact exist. Self-declaring `signature.state=verified` is not
enough: the validator requires the independently verified payload SHA (the
RFC8785-JCS payload excludes the `integrity` envelope) to match. The default CLI
therefore fails closed on validated packs until E4 supplies the cryptographic
verifier. Hardware validation additionally requires an included hardware
component and an explicitly listed controller.

The JSON file under `tests/fixtures/` is deliberately synthetic, unsigned, and
contract-only. It is not a distributable Vehicle Pack and must never appear in
the download catalog.

`vehicle-packs/registry.v1.json` is the first reviewed catalog of eight pack
contracts. It binds every entry to the exact manifest-file SHA-256 and keeps
mutable product availability separate from software validation. The official
store or documentation URLs are observation evidence dated 2026-08-05; stock
can change and never proves compatibility. Three entries are `goldenCandidate`
only to define the next validation order: PX4 Gazebo X500 reference, Holybro
X500 v2, and Holybro S500 v2. This label is not a validation tier.

At this checkpoint there are zero validated packs. Five packs are
`contract-only`; Amovlab P450, Amovlab MFP450, and Bitcraze Crazyflie 2.1+
remain `planned`. The parameter bounds in every unsigned/unvalidated pack are
provisional contract envelopes and cannot authorize hardware writes, arming,
or flight. Existing X500 receipts predate this signed-pack contract and cannot
be reused to upgrade the X500 reference pack.

`tools/verify_vehicle_pack_jcs.mjs` independently recomputes each payload hash
using the same RFC8785-JCS test vector as the Rust Runtime verifier. It excludes
the complete `integrity` envelope from the signed payload. Signature issuance
and native E4 verification are still pending; a correct payload hash alone is
not a signature.

```powershell
python distribution/tools/distribution_contract.py vehicle-packs `
  --inventory distribution/upstream-sources.v1.json `
  --policy distribution/capabilities/core-capabilities.v1.json `
  distribution/tests/fixtures/vehicle-pack-contract-only.v1.json

$packs = Get-ChildItem distribution/vehicle-packs/*.json |
  Where-Object Name -ne 'registry.v1.json'
node distribution/tools/verify_vehicle_pack_jcs.mjs $packs.FullName

$registryArgs = foreach ($pack in $packs) { '--vehicle-pack'; $pack.FullName }
python distribution/tools/distribution_contract.py vehicle-pack-registry `
  --inventory distribution/upstream-sources.v1.json `
  --policy distribution/capabilities/core-capabilities.v1.json `
  @registryArgs `
  distribution/vehicle-packs/registry.v1.json
```

## E1 composite installation contract

`schemas/composite-installation-manifest.schema.json` binds one product source
and common-core hash to the exact edition manifest, desktop, Runtime Base,
Engine Pack, Vehicle Pack manifests and payloads, module set, capability set,
resource estimate, and license notice. Desktop and Engine Pack must match the
common source commit; a stable Runtime Base may use a different commit only when
its own version, build ID, manifest, artifact hash, size, signature state, and
validation tier are explicit.

A planned composite must list blockers. It cannot become `installable` while
the edition is contract-only, a Vehicle Pack is unvalidated/unsigned, or the
Runtime Base/Engine Pack signature is unverified. The fixture is intentionally
planned and uses nonexistent tiny artifacts; it is not a build or release.

```powershell
python distribution/tools/distribution_contract.py composite `
  --edition distribution/editions/sim.v1.json `
  --policy distribution/capabilities/core-capabilities.v1.json `
  --inventory distribution/upstream-sources.v1.json `
  --vehicle-pack distribution/tests/fixtures/vehicle-pack-contract-only.v1.json `
  --expected-source 6b50f86ed80c190b816f19d06de143a328bda7e2 `
  distribution/tests/fixtures/composite-sim-planned.v1.json
```

## E1/E4 release promotion contract

`schemas/release-promotion-manifest.schema.json` defines the evidence required
before an edition may be promoted to `codex/release-sim`,
`codex/release-lab`, or `codex/release-field`. A promotion binds the product
source and common-core hash to one reviewed edition and composite installation,
the exact Runtime Base, Engine Pack, Vehicle Packs, capabilities, NOTICE,
installer bytes, validation tier, superseded assets, and rollback target.

Release channels are PR-only and force-push is forbidden. A branch head may be
the exact product source or a later commit containing only allowlisted edition
metadata. The latter classification is not accepted from self-reported paths:
the caller must supply the paths observed from the Git diff, and E4 will also
compare the proposed head with the independently observed remote branch head.
The three promotion manifests must share one `sourceCommit`, one
`commonCoreHash`, and one displayed product version. A planned promotion must
retain blockers; `promotable` requires an installable composite, an approved or
existing protected branch, a non-empty artifact, and a verified updater
signature. Authenticode may honestly remain `not-signed` for the current
closed-beta policy.

The fixture is synthetic, planned, and contains no installer. It does not
authorize direct branch mutation. SIM, LAB, FIELD, and AUTONOMY promote through
their protected long-lived product branches only after complete artifact
evidence and explicit governance approval.

```powershell
python distribution/tools/distribution_contract.py promotion `
  --edition distribution/editions/sim.v1.json `
  --policy distribution/capabilities/core-capabilities.v1.json `
  --inventory distribution/upstream-sources.v1.json `
  --vehicle-pack distribution/tests/fixtures/vehicle-pack-contract-only.v1.json `
  --composite distribution/tests/fixtures/composite-sim-planned.v1.json `
  --expected-source 6b50f86ed80c190b816f19d06de143a328bda7e2 `
  distribution/tests/fixtures/release-promotion-sim-planned.v1.json
```

## E4 unified edition build planner

`build-planning/e4-request.v1.json` is the reviewed input to the deterministic
plan-only coordinator in `tools/edition_build_planner.py`. The planner binds
one clean product source and one Git-derived common-core hash to the SIM, LAB,
FIELD, and AUTONOMY edition manifests, exact component contracts, selected Vehicle Pack
manifests/controllers, resource ceilings, NOTICE inputs, artifact names,
rollback policy, and the four independently observed product-branch heads.

The planner deliberately has no output-file or build option. It writes a JSON
plan to stdout only after confirming that the source tree is clean and that
`codex/software-sim`, `codex/software-lab`, `codex/software-field`, and
`codex/software-autonomy` exist on the observed remote with valid heads. It never runs Tauri, NSIS, Runtime migration,
PX4, Gazebo, an installer, a release API, or a branch mutation. Every generated
edition and precombined bundle therefore remains `planned-not-built`, with
`sha256=null` and `bytes=null`.

The full-simulation Runtime Base is an exact, verified reuse reference to the
existing beta.2 handoff. The current desktop, Engine Pack, lightweight Field
Runtime, all four installers, and all precombined bundles remain unbuilt.
Resource values are planning upper bounds, not observed artifact sizes. The
existing Runtime NOTICE is bound for planning, but each future binary must
regenerate and verify its own exact dependency/NOTICE closure.

There are still zero validated Vehicle Packs. Sim has no physical authority;
Lab and Field remain contract-only and cannot arm, write hardware parameters,
or fly. The planner's execution flags are all false and cannot create a
release branch or promote an artifact.

Generate a plan from an exact clean checkpoint:

```powershell
python distribution/tools/edition_build_planner.py `
  distribution/build-planning/e4-request.v1.json
```

After a plan-only receipt is committed under `distribution/build-plans/`, its
source may remain the preceding implementation commit. Validation permits only
that receipt-only suffix and rejects any other post-source change:

```powershell
python distribution/tools/edition_build_planner.py `
  distribution/build-planning/e4-request.v1.json `
  --validate distribution/build-plans/<plan>.json
```
