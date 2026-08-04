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

```powershell
python distribution/tools/distribution_contract.py vehicle-packs `
  --inventory distribution/upstream-sources.v1.json `
  --policy distribution/capabilities/core-capabilities.v1.json `
  distribution/tests/fixtures/vehicle-pack-contract-only.v1.json
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
authorize branch creation. The three release branches remain absent until E4
adds the build planner, observed-Git checks, and governance approval.

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
