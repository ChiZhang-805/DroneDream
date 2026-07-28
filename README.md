<p align="center">
  <img src="docs/assets/brand/drone-dream-lockup-primary.png" alt="DroneDream" width="640" />
</p>

<p align="center">
  <strong>Technical-report track · The research case for evidence-gated agentic tuning.</strong>
</p>

<p align="center">
  <img alt="XeLaTeX publication" src="https://img.shields.io/badge/XeLaTeX-publication-7C3AED?style=for-the-badge&logo=latex&logoColor=white" />
  <img alt="Thirteen-page report" src="https://img.shields.io/badge/Report-13%20pages-2563EB?style=for-the-badge" />
  <img alt="Claim-evidence ledger" src="https://img.shields.io/badge/Claims-evidence%20ledger-8B5CF6?style=for-the-badge" />
  <img alt="SHA-256 validation receipts" src="https://img.shields.io/badge/Validation-SHA--256%20receipts-EC4899?style=for-the-badge" />
</p>

<p align="center">
  <a href="technical-report/output/DroneDream_AURORA_Technical_Report.pdf">Read the PDF</a> ·
  <a href="technical-report/README.md">Report provenance</a> ·
  <a href="https://github.com/ChiZhang-805/DroneDream/tree/codex/software">Software evidence source</a>
</p>

## 📄 The report track

This branch owns the publication source and validation boundary for
**“AURORA: Agentic UAV Refinement through Optimization, Reflection, and
Assurance.”** The publication-style report explains the system, experiments,
evidence limits, reliability model, and reproducibility ledger behind
DroneDream’s agentic optimization harness.

The report is not a second software tree. It reads frozen software and website
evidence by commit and hash, while keeping its LaTeX, figures, claim ledger,
reference manifest, audits, and finished PDF under `technical-report/`.

## ❓ The question it investigates

Controller tuning is often described as a search for better gains. The report
asks a harder question: how can an agent coordinate optimization tools while
keeping every decision bounded by tool eligibility, scenario identity,
failure semantics, provenance, holdout separation, and evidence that another
reviewer can inspect?

AURORA’s answer is a closed, phase-aware model decision surface around
deterministic numerical optimizers and an evidence verifier. The model may
select and reflect within that surface, but it cannot redefine the simulator,
silently weaken policy, or promote unverified outcomes.

## 🧩 What the report contains

The paper moves from product scope and related work into the AURORA system
design, then evaluates several distinct evidence classes:

- archived development routing and a deterministic routing-policy holdout;
- source-contract ablations and fail-closed fallback equivalence;
- optimizer tool-use patterns and offline component interventions;
- synthetic integration and scenario-wise proxy behavior;
- the present PX4/Gazebo physical-scenario evidence boundary;
- product reliability, release contracts, limitations, and next experiments.

Architecture and data figures are generated or verified from bound source
artifacts rather than being treated as untracked illustrations.

## 🔐 How evidence is governed

Every material claim is mapped through a claim-evidence ledger to a frozen
source in the evidence-reference manifest. The validation pipeline checks
commits, file hashes, JSON assertions, figure inputs, report text, PDF layout,
links, warnings, and the final source-tree digest.

Software-owned evidence stays on the software line; website validation stays on
the website line. The report records their paths, commits, and hashes instead
of copying and silently modifying the underlying evidence.

## ⚖️ What the results do—and do not—show

The report supports conclusions about policy eligibility, fail-closed behavior,
reproducible routing measurements, synthetic optimizer integration, and the
traceability of the release and evidence pipeline.

It does not turn deterministic mock campaigns into flight evidence, treat a
small development corpus as a universal model-quality result, or claim that
unverified wind, sensor, battery, payload, or actuator effects were physically
applied. Broader provider comparisons and full scenario-complete PX4/Gazebo
campaigns remain future experimental gates.

## 📖 Read the report

- Open the
  [DroneDream AURORA Technical Report](technical-report/output/DroneDream_AURORA_Technical_Report.pdf).
- Review [report provenance and validation](technical-report/README.md).
- Inspect the
  [claim-evidence ledger](technical-report/claim-evidence-ledger.json) and
  [evidence-reference manifest](technical-report/evidence-reference-manifest.json).
- Visit the
  [software branch](https://github.com/ChiZhang-805/DroneDream/tree/codex/software)
  for the implementation that produces the frozen evidence.

Build and audit commands remain in the report-owned documentation so this page
can stay focused on the paper’s purpose, contents, and evidentiary boundaries.
Release trust is documented in the
[Code signing policy](CODE_SIGNING_POLICY.md) and [Privacy policy](PRIVACY.md).
