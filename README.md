<p align="center">
  <img src="docs/assets/brand/drone-dream-lockup-primary.png" alt="DroneDream" width="640" />
</p>

<p align="center">
  <strong>Software track · A complete workspace for evidence-driven PX4 tuning.</strong>
</p>

<p align="center">
  <img alt="AURORA · closed-tool Harness" src="https://img.shields.io/badge/AURORA-closed--tool%20Harness-7C3AED?style=for-the-badge" />
  <img alt="Python and FastAPI" src="https://img.shields.io/badge/Python-FastAPI-2563EB?style=for-the-badge&logo=python&logoColor=white" />
  <img alt="Rust and Tauri" src="https://img.shields.io/badge/Rust-Tauri-8B5CF6?style=for-the-badge&logo=rust&logoColor=white" />
  <img alt="React and TypeScript" src="https://img.shields.io/badge/React-TypeScript-EC4899?style=for-the-badge&logo=react&logoColor=white" />
</p>

<p align="center">
  <a href="https://getdronedream.com/">Product website</a> ·
  <a href="https://github.com/ChiZhang-805/DroneDream/releases">Windows releases</a> ·
  <a href="docs/README.md">Engineering documentation</a>
</p>

## 🧰 The software track

This branch owns the DroneDream product: the React experiment workspace, Tauri
Windows application, FastAPI service, background worker, WSL2 Runtime,
PX4/Gazebo adapters, optimization engines, and the evidence contracts that join
them together.
Its goal is not simply to search for a lower error value. It turns controller
tuning into a reviewable engineering process in which the task, parameter
space, scenarios, budget, execution history, and final recommendation remain
connected.

## 🧭 What a researcher can do

DroneDream supports two ways to begin: describe a study to the Tuning Chat, or
build it manually through the five-step experiment flow. Users can then:

- choose a vehicle, PX4 version, Gazebo world, objective profile, and track;
- select catalog-backed PX4 parameters with bounded ranges and coupling checks;
- separate search scenarios from holdout scenarios and define robust
  acceptance criteria;
- run asynchronous candidate and trial campaigns through deterministic mock or
  external PX4/Gazebo execution;
- monitor progress, compare runs, inspect trials and failures, replay 2D/3D
  trajectories, and download retained artifacts and reports.

Chinese and English interfaces cover the same product workflow, including the
desktop setup and recovery experience.

## 🧠 AURORA and the optimization engine

**AURORA — Agentic UAV Refinement through Optimization, Reflection, and
Assurance —** is the software’s agentic core. It compiles a closed, versioned
decision context, exposes only eligible optimizer tools, records bounded
reflection from verified outcomes, and falls back to deterministic behavior
when provider output is unavailable or invalid.
Its tool surface includes constrained MOBO, multi-fidelity MOBO, TuRBO, SAASBO,
surrogate-assisted CMA-ES, BIPOP-CMA-ES, and an adaptive optimizer portfolio.
Fair seed matrices, robust multi-objective scoring, feasibility gates, Pareto
selection, and holdout isolation keep numerical search and final judgment
separate.

## ⚙️ Runtime and product architecture

The user-facing console communicates with a FastAPI backend that persists Jobs,
Candidates, Trials, reports, events, and artifacts. A lease-aware worker claims
work, dispatches optimizers, invokes the selected simulator adapter, and drives
each experiment to a terminal state.
On Windows, the Tauri application manages an isolated, manifest-signed WSL2
Runtime containing the API, worker, Valkey, PX4 SITL, Gazebo, MAVSDK, and
supporting tools. Guided prerequisite checks, installation planning, repair,
updates, health probes, and exit protection make that environment part of the
product rather than a hidden prerequisite.

## 🛡️ Evidence and safety boundaries

Candidate inputs, execution attempts, telemetry semantics, artifact digests,
optimizer provenance, winner selection, and report projections can be bound to
content-addressed receipts. The system rejects stale leases, mutated evidence,
unverified winner changes, holdout feedback leakage, unsafe parameter values,
and unsupported physical-effect claims.
The deterministic mock simulator is useful for workflow and regression
evidence; it is not physical-flight evidence. Real PX4/Gazebo runs must retain
the expected identity, parameter readback, scenario-effect, telemetry, and
artifact chain. Hardware use remains outside DroneDream’s automated authority.

## 📚 Where to look next

- [Product and architecture notes](docs/01-overview.md)
- [Optimizer and experiment guide](docs/09-optimizer-guide.md)
- [PX4/Gazebo runner contract](docs/08-px4-gazebo.md)
- [AURORA Harness engineering](docs/17-harness-engineering.md)
- [DroneDreamRuntime release model](runtime/README.md)
- [Windows desktop delivery](desktop/README.md)

Detailed setup, API, testing, and release instructions live in those focused
documents so this page can remain a clear introduction to the software itself.
Release trust is documented in the
[Code signing policy](CODE_SIGNING_POLICY.md) and [Privacy policy](PRIVACY.md).
