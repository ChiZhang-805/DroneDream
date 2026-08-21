<p align="center">
  <img src="docs/assets/brand/drone-dream-lockup-primary.png" alt="DroneDream" width="640" />
</p>

<p align="center">
  <strong>Simulation-first PX4 and Gazebo tuning, from intent to evidence.</strong>
</p>

<p align="center">
  <img alt="AURORA · evidence-gated" src="https://img.shields.io/badge/AURORA-evidence--gated-7C3AED?style=for-the-badge" />
  <img alt="PX4 and Gazebo · simulation-first" src="https://img.shields.io/badge/PX4%20%2B%20Gazebo-simulation--first-2563EB?style=for-the-badge" />
  <img alt="Windows desktop and WSL2 Runtime" src="https://img.shields.io/badge/Windows-Desktop%20%2B%20WSL2-8B5CF6?style=for-the-badge&logo=windows11&logoColor=white" />
  <img alt="Receipted evidence" src="https://img.shields.io/badge/Evidence-receipted-EC4899?style=for-the-badge" />
</p>

<p align="center">
  <a href="https://getdronedream.com/">Website</a> ·
  <a href="https://github.com/ChiZhang-805/DroneDream/releases">Releases</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="https://github.com/ChiZhang-805/DroneDream/blob/codex/technical-report/technical-report/output/DroneDream_AURORA_Technical_Report.pdf">Technical report</a>
</p>

## ✦ What DroneDream is

DroneDream is an engineering workspace for designing, running, and explaining
PX4 controller-tuning experiments in Gazebo. It brings flight-task definition,
bounded parameter search, scenario design, asynchronous optimization,
trajectory review, artifacts, and experiment reports into one product. 
The project is built around a simple principle: an attractive result is not
enough. Every recommendation should remain connected to the experiment that
produced it, the evidence that supports it, and the limits that still apply.

## 🧭 One continuous experiment journey

Users can begin with a natural-language tuning conversation or configure a
study manually. DroneDream turns that intent into a reviewable five-step
experiment, evaluates candidate parameter sets on controlled scenario and seed
matrices, and presents the resulting metrics, trajectories, failures, artifacts,
and comparisons in one workspace.
The Windows application adds guided setup for its isolated WSL2 Runtime, while
the browser console and public website extend the same visual and product
language across the rest of the experience.

## 🧩 The project in three focused tracks

| Track | Purpose | Branch |
| --- | --- | --- |
| Software | The desktop application, experiment console, backend, worker, Runtime, optimizers, simulator adapters, and evidence system. | [`codex/software`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software) |
| Website | The public product story, manuals, pricing, community, download experience, and shared static-release contract for global and mainland delivery. | [`codex/website`](https://github.com/ChiZhang-805/DroneDream/tree/codex/website) |
| Technical report | The AURORA paper, figures, claim ledger, evidence references, and publication validation pipeline. | [`codex/technical-report`](https://github.com/ChiZhang-805/DroneDream/tree/codex/technical-report) |

These tracks share the DroneDream identity and may consume frozen outputs from
one another, but each keeps authority over its own deliverables.

## One authoritative repository

This checkout is the single source authority. Its top-level directories are
responsibility boundaries, not alternate copies of the product:

| Area | Directories | Responsibility |
| --- | --- | --- |
| Product applications | `frontend/`, `backend/`, `worker/`, `desktop/`, `website/` | Browser and desktop interfaces, APIs, background execution, native shell, and public delivery experience. |
| Runtime and platform | `runtime/`, `engine-pack/`, `supabase/` | Isolated simulator/runtime contracts, versioned engine content, authentication, storage, and server-side functions. |
| Release and identity | `distribution/`, `deploy/`, `brand/` | Edition contracts, signed-delivery metadata, deployment configuration, and canonical brand sources/derived assets. |
| Verification and knowledge | `scripts/`, `docs/`, `artifacts/`, `.github/` | Reproduction tools, architecture/operations guidance, immutable receipted evidence, and CI policy. |

`artifacts/technical-report/` and `artifacts/test-runs/` contain tracked,
content-addressed evidence used by frozen claims and regression contracts; they
are not scratch output. Local job runs, databases, bytecode, test caches,
frontend build output, Cargo targets, installers, and dependency trees remain
ignored or outside the repository and must be removed when their owning task
finishes. Historical source belongs in Git history or a verified external
recovery archive, never in a second `legacy/`, `repro/`, or copied source root.

## Five desktop products

The five products share a common core but promote from separate long-lived
branches so product-specific capabilities, Runtime profiles, installers, and
release evidence remain isolated. Universal presents the four focused
workspaces without inheriting hardware authority from any of them:

| Edition | Product role | Native profile |
| --- | --- | --- |
| Universal | Complete launcher for simulation and laboratory workflows, shared account, setup, updates, and evidence navigation. | `unified-sim-lab` |
| SIM | Simulation-only workspace; it never authorizes physical hardware and requires the Runtime Base plus Engine Pack. | `sim-only` |
| LAB | Sim-to-Real and Real-to-Sim calibration/evidence workspace with hardware actions kept fail-closed. | `unified-sim-lab` |
| FIELD | Lightweight standalone real-device shell with no simulator Runtime planner or inherited Runtime installation state. | `field-lightweight` |
| AGENT | Natural-language mission planning and supervision through structured plans, repeated Model + Harness calls, plugins, safe interruption, replanning, and evidence gates. | `autonomy-full` |

Their long-lived product branches are `codex/software`,
`codex/software-sim`, `codex/software-lab`, `codex/software-field`, and
`codex/software-agent`. The internal protocol and storage key for AGENT remains
`autonomy` so existing API routes, persisted task records, and Runtime contracts
do not break during the visible product rename.

Build failures, their exact cleanup, and reusable corrections are maintained in
the single [build and cleanup experience log](docs/BUILD_AND_CLEANUP_EXPERIENCE.md).

## 🧠 AURORA, the technical core

**AURORA — Agentic UAV Refinement through Optimization, Reflection, and
Assurance —** is DroneDream’s evidence-gated optimization harness. It gives a
bounded model a closed set of eligible numerical tools, preserves deterministic
fallbacks, separates search evidence from holdout evidence, and records the
provenance needed to explain each decision.
The software also includes constrained and multi-fidelity Bayesian optimization,
TuRBO, SAASBO, surrogate-assisted and BIPOP CMA-ES, and an adaptive optimizer
portfolio. The model coordinates tools; it does not replace the simulator,
rewrite safety bounds, or independently approve a controller.

## 🛡️ Evidence before claims

DroneDream distinguishes deterministic mock campaigns, PX4/Gazebo SITL
execution, retained telemetry, source-contract checks, and publication evidence.
Unsupported physical effects fail closed, holdout results are kept out of
candidate selection, and content-addressed receipts bind important outcomes to
their source state.
The product is simulation-first. A selected parameter set is an experiment
result, not an authorization to fly real hardware; independent SITL
reproduction and engineering review remain necessary.

## 🚀 Explore DroneDream

- Visit the [product website](https://getdronedream.com/) for the public
  introduction, manuals, community, and release experience.
- Read the [software overview](https://github.com/ChiZhang-805/DroneDream/tree/codex/software)
  for the product workflow and technical moat.
- Read the [AURORA technical report](https://github.com/ChiZhang-805/DroneDream/blob/codex/technical-report/technical-report/output/DroneDream_AURORA_Technical_Report.pdf)
  for the research design, experiments, limitations, and evidence ledger.
- Use the [documentation index](docs/README.md) when implementation,
  deployment, API, or Runtime detail is needed.

DroneDream is released under the [MIT License](LICENSE). Security reports follow
the process in [SECURITY.md](SECURITY.md); release trust is documented in the
[Code signing policy](CODE_SIGNING_POLICY.md) and [Privacy policy](PRIVACY.md).
