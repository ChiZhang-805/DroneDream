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
