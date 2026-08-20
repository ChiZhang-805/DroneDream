<p align="center">
  <img src="brand/commercial/universal-lockup.png" alt="DroneDream" width="640" />
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

## 🧩 Five products, one shared core

| Product or track | Purpose | Branch |
| --- | --- | --- |
| Universal | Unified modeling, orchestration, and presentation-only switching across SIM, LAB, FIELD, and AUTONOMY. | [`codex/software`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software) |
| SIM | Simulation-only Model + Harness workflows for PX4 SITL, Gazebo, repeatable experiments, and evidence. | [`codex/software-sim`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software-sim) |
| LAB | Bidirectional simulation and hardware validation, including Sim-to-Real and Real-to-Sim workflows. | [`codex/software-lab`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software-lab) |
| FIELD | Fail-closed real-device discovery, bounded tuning, preflight, operations, and rollback. | [`codex/software-field`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software-field) |
| AUTONOMY | Natural-language missions, structured plans, repeated Model + Harness loops, pluginized tools, safe interruption, and replanning. | `codex/software-autonomy` |
| Website | The public product story, manuals, pricing, community, download experience, and shared static-release contract for global and mainland delivery. | [`codex/website`](https://github.com/ChiZhang-805/DroneDream/tree/codex/website) |
| Technical report | The AURORA paper, figures, claim ledger, evidence references, and publication validation pipeline. | [`codex/technical-report`](https://github.com/ChiZhang-805/DroneDream/tree/codex/technical-report) |

`main` is the protected integration branch. These seven long-lived delivery
branches plus `main` are the repository's complete eight-branch topology.
Feature branches are temporary: their reviewed work must be merged before the
branch is removed. The five applications share one authoritative core while
each product branch preserves its own capability boundary and release evidence.

The promoted [`autonomy-core/`](autonomy-core/) component supplies the shared
natural-language mission Harness: versioned structured contracts, multi-call
planning and critique loops, plugin slots and isolated plugin processes, safe
hold/interruption/replan logic, ROS 2 interfaces, and PX4/Gazebo evidence. The
five product shells select different capabilities and authority policies from
that shared core; the language model never receives direct actuation authority.

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
