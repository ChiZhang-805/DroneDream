# DroneDream 1.0 technical report and evaluation contract

## Purpose

The technical report is an engineering evidence document for DroneDream's
evidence-gated UAV simulation auto-tuning Harness. It is not a generic language
model leaderboard and it must not turn unit-test counts, mock simulations, or
development prompts into physical-flight performance claims.

Working title:

> **DroneDream 1.0: Evidence-Gated Autonomous Tuning for UAV Simulation**

The visual identity follows DroneDream's purple-pink product language under
the name **Dreamline Violet**:

- primary violet `#6D28D9`;
- gradient magenta `#C026D3`;
- highlight rose `#FB7185`;
- night-flight plum `#0B0614`;
- print-safe heading violet `#5B21B6`;
- pale lavender `#C4B5FD`;
- verified green `#22C55E`.

Cover pages and architecture figures use a restrained
`#6D28D9 → #C026D3 → #FB7185` gradient over night-flight plum. White-page
headings use print-safe violet rather than bright blue. Charts reuse the same
ordered palette and also carry direct labels, markers, hatching, or line styles;
color never replaces an evidence-class label, confidence interval, or status.

## Claim classes

Every result, table, and figure carries one of these labels:

| Label | Permitted claim | Forbidden upgrade |
| --- | --- | --- |
| `SOURCE_VERIFIED` | Code path and automated contract tests exist | Customer Runtime or physical outcome |
| `SOURCE_ABLATION` | Constructed probes compare a shipped guard with an intentionally weakened software-contract comparator | Causal component contribution, optimizer quality, simulation outcomes, or safety |
| `POLICY_HOLDOUT` | Exact production tool-eligibility sets on the separate hash-locked deterministic policy corpus | LLM routing quality, simulator outcomes, or permanent blindness |
| `DEV_ROUTING` | Acceptable tool selection on the versioned development corpus | Simulator quality, general reasoning, or unseen-case accuracy |
| `SYNTHETIC_MOCK` | Deterministic search, aggregation, and holdout logic on the named mock landscape | PX4/Gazebo physics or real-flight improvement |
| `PX4_GAZEBO` | Repeated, provenance-complete results from the pinned Runtime | Real-aircraft safety or transfer |
| `USER_STUDY` | Measured task/UX outcomes under a declared protocol | Algorithmic superiority without an algorithm experiment |

`backend/scripts/export_technical_report_evidence.py` is the single exporter
for chart-ready evidence already present in the repository. It validates
provenance, recomputes headline metrics, emits hashes, and refuses to relabel a
mock campaign as physical evidence.

`backend/scripts/evaluate_harness_ablations.py` independently reproduces the
source-contract ablation JSON, CSV, and file-hash manifest. Its comparator is
not a product mode: it intentionally removes one named guard at a time so the
contract probe can demonstrate what that guard rejects or preserves.

`backend/scripts/evaluate_harness_outcome_campaign.py` runs a separate
outcome-level fallback-equivalence campaign. It uses temporary SQLite
databases, `MockSimulatorAdapter`, five fixed seed blocks, and three
matched-budget arms: direct portfolio, provider-error fallback, and
invalid-response fallback. It makes no network call and persists no real
credential. Each arm installs a runtime guard that blocks and counts
`socket.connect`, `socket.connect_ex`, and `socket.create_connection`; a
single attempt fails the campaign. The fake clients enter only through an
in-process test override that is absent from `JobCreateRequest` and cannot be
submitted through the production API. Its `--check` mode reruns all 15 arms
before comparing the deterministic JSON, CSV, and SHA-256 manifest.

## Report modules

1. **Executive abstract and claim ledger** — product scope, strongest verified
   findings, and explicit non-claims.
2. **Problem definition** — why manual multi-parameter tuning is expensive and
   how DroneDream confines automation to reviewable simulation campaigns.
3. **System architecture** — desktop, local Runtime, backend orchestration,
   evidence store, model gateway/BYOK boundary, and failure domains.
4. **Harness moat** — context compiler, tool registry/router, optimizer
   portfolio, bounded execution, feedback/reflection, scenario train/holdout
   split, freeze rules, and provenance.
5. **Optimization methods** — supported search families, when each is routed,
   constraints, failures, multi-fidelity costs, and stopping rules.
6. **Physical scenario application** — PX4/Gazebo version pinning, obstacle and
   constant-wind evidence, unsupported-effect failure closure, and remaining
   Runtime gates.
7. **Experimental protocol** — tracks, scenario matrix, parameter spaces,
   budgets, seeds, blocked randomization, metrics, confidence intervals,
   failure accounting, and frozen final tests.
8. **Routing diagnostics** — development-corpus accuracy, category breakdown,
   best-constant and uniform-random baselines.
9. **Synthetic integration campaign** — ten-scenario holdout behavior,
   per-scenario losses, oracle diagnostics, and strict non-physical label.
10. **PX4/Gazebo benchmark** — fixed-budget outcome quality, robustness,
    feasibility, failure rate, wall time, and sample efficiency.
11. **Ablations** — router, portfolio, memory, reflection/recovery,
    train/holdout separation, scenario evidence gate, and failure taxonomy.
12. **UX and operations** — readiness gate, time-to-ready, entry success, safe
    exit/draft recovery, artifact completeness, cost and latency.
13. **Limitations and roadmap** — no hardware claim, supported scenario
    boundary, cloud-simulation future, external validity, and release gates.
14. **Reproducibility appendix** — manifests, hashes, seeds, schemas, commands,
    exclusions, and artifact locations.

## Figure and table register

| ID | Visual | Evidence | Status |
| --- | --- | --- | --- |
| F1 | Harness architecture flow | source and contracts | ready to draw |
| F2 | Readiness gate state machine | desktop source and tests | ready to draw |
| F3 | Routing accuracy vs baselines (bar) | `DEV_ROUTING` | exportable now |
| F4 | Routing category heat strip | `DEV_ROUTING` | exportable now |
| F5 | Tool selection distribution | `DEV_ROUTING` | exportable now |
| F6 | Ten-scenario baseline vs selected loss | `SYNTHETIC_MOCK` | exportable now |
| F7 | Scenario relative improvement heatmap | `SYNTHETIC_MOCK` | exportable now |
| F8 | Optimizer quality/sample efficiency curves | `PX4_GAZEBO` | experiment required |
| F9 | Track × scenario robustness heatmap | `PX4_GAZEBO` | experiment required |
| F10 | Failure/recovery Sankey or stacked bars | `PX4_GAZEBO` | experiment required |
| F11 | Harness guard ablations (three-line table or grouped bars) | `SOURCE_ABLATION` | exportable now |
| F12 | Fallback outcome equivalence across five seed blocks | `SYNTHETIC_MOCK` | exportable now |
| F13 | Time-to-ready and entry/exit success | `USER_STUDY` or automated UX | experiment required |
| T1 | Claim ledger | all | in progress |
| T2 | Supported capability matrix | source + Runtime acceptance | in progress |
| T3 | Experimental arms and budgets | locked protocol | designed |
| T4 | Main PX4/Gazebo outcomes with 95% CIs | `PX4_GAZEBO` | experiment required |
| T5 | Ablation outcomes | locked campaign | experiment required |

Radar charts are used only as a compact secondary view of normalized metrics.
Raw values, units, directionality, and uncertainty remain in an adjacent table.

## Locked benchmark design

The publication-grade comparison uses repeated PX4/Gazebo campaigns with the
same pinned Runtime, controller catalog, starting design, trial budget,
train/holdout scenario split, and failure thresholds.

### Arms

1. deterministic default optimizer policy;
2. fixed `cma_es`;
3. best single specialized optimizer selected before the locked run;
4. deterministic optimizer portfolio without model routing;
5. Harness routing without reflection/recovery memory;
6. full Harness.

Manual expert tuning and PX4 AutoTune may be reported only if the exact
controller/vehicle/track contract makes them comparable. Otherwise they appear
as contextual references, not ranked baselines.

### Primary outcomes

- frozen-final holdout loss;
- feasible-campaign rate;
- improvement over the common baseline;
- trials and effective-fidelity cost to first accepted candidate;
- terminal failure rate, grouped by stable failure code;
- artifact-completeness and evidence-validation rate.

Secondary outcomes include wall time, model tokens/cost, router latency,
recovery success, scenario-wise regret, and readiness/exit UX timings.

### Repetition and uncertainty

- use at least five independent campaign seeds for engineering diagnostics and
  preferably ten for report-level comparisons;
- use blocked randomization by track × scenario suite × initial design;
- report median and interquartile range for skewed latency/cost measures;
- report mean differences with bootstrap 95% confidence intervals for bounded
  aggregate scores when their distribution supports it;
- retain failures in the denominator and never impute a successful loss;
- freeze the final-test manifest before any arm observes its outcomes.

No superiority claim is published from a single seed, a single track, a
development corpus, or a hidden oracle diagnostic.

## Current verified evidence

The exporter currently produces:

- 24/24 acceptable choices on eight three-case routing categories, compared
  with a best constant policy of 14/24 and a uniform-random expectation of
  5.625/24. This is `DEV_ROUTING`, not simulator quality.
- a 61-candidate synthetic campaign over ten named scenario types whose
  holdout loss changes from `0.82811` to `0.58525` (29.327%); all ten scenario
  losses improve. This is `SYNTHETIC_MOCK`, with
  `physical_fidelity=false`.

The deterministic source-contract ablation now contains 20 constructed probes
covering provider trust filtering, tool eligibility, deterministic fallback,
and scenario/outcome isolation. The full production contracts satisfy 20/20
declared expectations; the deliberately weakened comparators satisfy 6/20.
This is `SOURCE_ABLATION`: it demonstrates guard behavior on named inputs, not
causal performance lift or simulation quality.

The separate deterministic router-policy holdout contains 16 hash-locked cases
and currently passes 16/16 exact eligible-tool-set comparisons with zero online
model calls, simulator runs, or feedback writebacks. This is
`POLICY_HOLDOUT`, not an LLM or simulator benchmark; its labels are visible
after repository publication and must not be described as permanently blind.

The deterministic fallback outcome campaign contains 15 complete Job runs
and 573 persisted Trial executions: five seed blocks multiplied by the direct
portfolio, provider-error fallback, and invalid-response fallback arms. Both
fallback arms match the direct portfolio in all 10 blockwise comparisons for
normalized Candidates, Trials, budget use, winner, holdout loss, failure
count, and evidence completeness; all arms report 100% evidence completeness.
This is `SYNTHETIC_MOCK` fallback-equivalence evidence only. It is not LLM
superiority, causal Harness benefit, PX4/Gazebo performance, or flight
evidence.

The real PX4/Gazebo main table, broader component-level outcome ablations,
multi-seed physical confidence intervals, latency/token/cost results, and UX
measurements remain unfilled until their locked experiments run.

## Reproduction

From the repository root:

```powershell
backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_ablations.py

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_ablations.py `
  --check

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_outcome_campaign.py

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_outcome_campaign.py `
  --check

backend\.venv\Scripts\python.exe `
  backend\scripts\export_technical_report_evidence.py `
  --output artifacts\technical-report\evidence.json `
  --csv-directory artifacts\technical-report\csv
```

The resulting report JSON includes SHA-256 hashes for every source artifact
and a digest over the normalized bundle. The versioned ablation JSON/CSV/hash
under `backend/evaluation_artifacts/` are source-controlled software-contract
evidence; generated files under `artifacts/technical-report/` are report build
artifacts and are not physical-performance evidence.
