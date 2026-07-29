# DroneDream 1.0 technical report and evaluation contract

## Purpose

The technical report is an engineering evidence document for DroneDream's
evidence-gated UAV simulation auto-tuning Harness. It is not a generic language
model leaderboard and it must not turn unit-test counts, mock simulations, or
development prompts into physical-flight performance claims.

Working title:

> **DroneDream 1.0: Evidence-Gated Autonomous Tuning for UAV Simulation**

The visual identity follows the approved bright purple-pink-blue product
language under the name **Dreamline Prism**:

- primary electric violet `#684BFF`;
- light violet `#9B72FF`;
- gradient magenta `#F166D8`;
- rising-wing coral `#FF4E70`;
- verification blue `#3A74FF`;
- night-flight ink `#171225`;
- print-safe heading violet `#684BFF`;
- pale lavender `#EEE9FF`;
- verified green `#22C55E`.

The title-page lockup uses the fixed approved brand asset rather than rebuilding
the icon or wordmark inside Word. White-page headings use electric violet with
magenta reserved for secondary emphasis. Charts may add coral and flight blue
to the ordered violet-pink palette, but also carry direct labels, markers,
hatching, or line styles; color never replaces an evidence-class label,
confidence interval, or status.

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

`backend/scripts/export_technical_report_evidence.py` remains the historical
v9 metric exporter. The current
`backend/scripts/export_technical_report_evidence_v10.py` exact-byte verifies
that immutable base and adds newer evidence classes without rewriting them. It
recomputes online routing grades, multi-tool budget/accounting summaries, and
the advanced-physics capability closure while refusing to relabel mock evidence,
effect application, or focused tests as broader performance/release evidence.

The historical report-line handoff is
`dronedream.technical-report-evidence.v6`, with
`source_commit=0429b4244fc1fd912bd211e80821ebdbabb8ae5d` and
`generated_at=2026-07-28T04:59:08Z`. The exporter requires both values instead
of consulting the wall clock, validates their syntax, and includes them in the
canonical bundle hash. With unchanged inputs and explicit metadata,
regeneration is byte-verifiable.
`artifacts/technical-report/evidence.manifest.json` lists every report source
and SHA-256, including the 554-Trial component-ablation JSON, CSV, and
preregistration manifest plus the 1,139-test backend receipt.
The canonical bundle SHA-256 is
`bd99720f50a63d282287b7ed2ee7b4692e416bc00db218a864ebc462f8298258`;
the manifest and `evidence.sha256` bind the generated files without changing
the software source commit.

The historical non-overwriting
`dronedream.technical-report-evidence.v8` successor at
`artifacts/technical-report/evidence-v8.json`. It binds
`source_commit=65a33bbd70f999962afd1bea1e374dcd5e9de460`,
`generated_at=2026-07-28T12:58:32Z`, the then-current Evidence 2.7 / Prompt 1.6
24/24 provider freeze, both v2 Harness ablations, the reflection trigger and
long-horizon stress sources, and the exact-commit 1,164-test receipt. Its
canonical bundle SHA-256 is
`2dad5492c8e8bd1d91a06db8b6a87c978e45cc139e83e53cf73634324ee9b3d4`;
the JSON file SHA-256 is
`d1b8c1931b64ca5df971e24e34c03f4f202585b852612b11458abeb57a70dd07`,
and the manifest file SHA-256 is
`6bd08f15b034dccf3922b4ccd95a5e1368dde79a49719dede1e628a002a3dafc`.

The historical v9 handoff is
`artifacts/technical-report/evidence-v9.json`. It binds
`source_commit=c1222c9215e01a56351f6588af0d2b8694bca831`,
`generated_at=2026-07-28T15:44:30Z`, the then-current Evidence 2.8 cross-Job
memory contract, the explicitly archived Evidence 2.7 / Prompt 1.6 provider
and component/stress freezes, and the exact-commit 1,204-test receipt plus its
28-test focused supplement. Its canonical bundle SHA-256 is
`d33c308ce3b47138572c86bf7f45aa8e4a37901a0248a5d5e0d3cd71ce2bfa8a`;
the JSON file SHA-256 is
`a2bed29533b321fa00086bf901f7c5ebbf35ab503e50cde4de568b3420e0a08a`,
and the manifest file SHA-256 is
`3bc7bd0eac65cf5e8f9ef7e05c0f5e62403a7cf23c5be4f0905ae4b503847fc9`.
The v6, v7, v8, and v9 bundles remain immutable historical freezes.

The current non-overwriting software handoff is
`dronedream.technical-report-evidence.v10` at
`artifacts/technical-report/evidence-v10.json`. It binds software subject
`97492448c36bef240e468a0cd53c3ba198cb6aae`, generation time
`2026-07-28T23:54:28Z`, and evidence freeze
`a1f091f2edf1ae43233cd01e483bc3990c9aa279`. Its 39-source inventory
re-verifies the full v9 lineage, including the 1,651,339-byte 554-Trial
component-ablation blob, then adds the Evidence 2.8 / Prompt 1.7 online routing
freeze, Evidence 2.9 offline equal-budget multi-tool evidence, and nine-category
advanced-physics closure. The internal bundle SHA-256 is
`df6ef5e898519150dd306fa9550526a5c16b1b19bb5e1c2e67b3a9e5048d9e5b`;
the JSON file SHA-256 is
`27b6b1c96524dec4a48a553d19fb2c3844724597fa797dda11d6bf594a23bd89`,
and the manifest file SHA-256 is
`134d1ae0f0a96b7999755b0b2e4352c0ce1388bddc4f5f0adc9eb744cc302d4a`.
It explicitly reports `release_ready=false`.

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

`backend/scripts/evaluate_harness_component_ablations.py` runs the separate
four-arm **AURORA component outcome ablation**. It uses the same production
Job/Candidate/Trial orchestration, a shared service baseline, five fixed seed
blocks, one common train/holdout scenario matrix, the same two-generation and
40-Trial ceilings, and the same terminal accounting in every arm. The arms are
full AURORA, no decision memory, no observed-outcome reflection, and the fixed
deterministic optimizer portfolio. No online model is involved: a
preregistered local router consumes the exact production provider payload and
selects only from the current eligible-tool manifest.

The component intervention is measured before each local routing call. The
no-memory arm empties `decision_memory`; the no-reflection arm preserves the
decision receipt while replacing verified reflection with `unavailable` and
removing `observed_outcome`. The result artifact records how many provider
inputs changed, the actual tool sequence, holdout loss, optimizer feasibility,
Trials to a preregistered five-percent training-loss target or its
right-censoring count, total Trials, terminal failures, recovered Trials, and
evidence completeness. JSON, CSV, a separate preregistration manifest, and a
SHA-256 file manifest are frozen together. `--check` reruns all 20 Jobs before
independently recomputing metrics, comparisons, and hashes.

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

- 23/24 acceptable choices on eight three-case routing categories from the
  latest retained Evidence 2.8 / Prompt Template 1.7 provider freeze, compared
  with a best constant policy of 14/24 and a uniform-random expectation of
  5.625/24. `tight_budget_expensive_matrix` is the retained failure; all
  qualification thresholds still pass. The Artifact file SHA-256 is
  `d2359e0540aa284cd84262ec4c378369bc3fbab856d8384c3eff56738ef225c4`.
  Earlier Prompt 1.5/1.6 runs scored 19/24, 21/24, and 24/24. This is
  `DEV_ROUTING` qualification for the frozen 2.8 contract, not current Evidence
  2.9 validation, a causal prompt comparison, or a simulator-quality claim.
- the offline Evidence 2.9 multi-tool budget protocol contains three matched
  seed blocks and six complete arms. Configured two-generation/40-Trial budgets
  match in 3/3 blocks; the scripted arm has six verified generations, exercises
  multi-tool execution in 3/3 blocks, and records 12 schema-valid local decision
  calls with zero provider/network calls or real credentials. This is
  `SYNTHETIC_MOCK` dispatcher/provenance/accounting evidence, not an LLM-quality
  or causal-benefit result.
- the advanced-physics closure exact-byte verifies nine of nine bundled
  PX4/Gazebo effect categories with no remaining Runtime extension. Five
  categories have every retained performance trial passing. GPS noise retains a
  readiness boundary; dropout/battery retains a false policy verdict despite
  verified transitions; hard actuator failure retains verified rotor behavior
  without a trusted scoring window. This is `PX4_GAZEBO` effect-application
  evidence, not universal perturbed-flight success or real-aircraft evidence.
- a 61-candidate synthetic campaign over ten named scenario types whose
  holdout loss changes from `0.82811` to `0.58525` (29.327%); all ten scenario
  losses improve. This is `SYNTHETIC_MOCK`, with
  `physical_fidelity=false`. The immutable v3 campaign also contains a
  content-addressed `seed_robustness` receipt over ten disjoint validation
  seeds. For the selected Candidate, training loss is `0.58554` and validation
  loss is `0.58525`, a signed degradation of `-0.00029` (approximately
  `-0.0495%`, meaning a small improvement). The receipt is report-only and
  cannot feed adaptive search.

The separate immutable
`scenario-generalization-mock-v1.json` campaign closes the previously
compiler-only configuration/type gap. The optimizer sees five training cases
and selects from 61 Candidates before any validation runs. The frozen
report-only matrix then evaluates five stronger configurations of known types
and five scenario types absent from training, each on a disjoint seed. The
selected Candidate is the exact finite-grid optimum on both the training and
validation aggregates: training score is `0.87340`, mixed-shift validation
score is `1.03057`, and the receipt therefore records a `17.995%` relative
train-to-validation degradation. Against the unchanged baseline, however,
validation score improves by `25.072%`, and every validation case improves.
This qualifies only `mixed_shift_robustness` on the deterministic mock
landscape. It is neither a sealed final test nor PX4/Gazebo, real-flight,
sim-to-real, or open-world evidence.

The deterministic source-contract ablation now contains 25 constructed probes
covering provider trust filtering, tool eligibility, deterministic fallback,
scenario/outcome isolation, and the Evidence 2.7 scenario-profile and planning
boundary. The
full production contracts satisfy 25/25 declared expectations; the deliberately
weakened comparators satisfy 6/25. The five scenario-profile probes cover
anonymous weighted training cases, scenario-specific perturbation allowlists,
out-of-range filtering, holdout-content noninterference, and the bounded
job-wide environment summary.
This is `SOURCE_ABLATION`: it demonstrates guard behavior on named inputs, not
causal performance lift or simulation quality.

The separate deterministic router-policy holdout contains 16 hash-locked cases
and currently passes 16/16 exact eligible-tool-set comparisons with zero online
model calls, simulator runs, or feedback writebacks. This is
`POLICY_HOLDOUT`, not an LLM or simulator benchmark; its labels are visible
after repository publication and must not be described as permanently blind.

The deterministic fallback outcome campaign contains 15 complete Job runs
and 579 persisted Trial executions: five seed blocks multiplied by the direct
portfolio, provider-error fallback, and invalid-response fallback arms. Both
fallback arms match the direct portfolio in all 10 blockwise comparisons for
normalized Candidates, Trials, budget use, winner, holdout loss, failure
count, and evidence completeness; all arms report 100% evidence completeness.
This is `SYNTHETIC_MOCK` fallback-equivalence evidence only. It is not LLM
superiority, causal Harness benefit, PX4/Gazebo performance, or flight
evidence.

The AURORA component outcome ablation contains 20 complete synthetic Jobs and
554 persisted Trials after the Evidence 2.7 receding plan: five common seed
blocks multiplied by four arms. In
every block, full AURORA routed `constrained_mobo` then `turbo`; removing all
decision memory or only verified observed outcomes routed
`constrained_mobo` then `optimizer_portfolio`; the fixed arm routed the
portfolio twice. All 20 runs made zero network calls and reached 100% evidence
completeness. The frozen landscape produced no terminal failure or retry
recovery, so those metrics remain explicit zeros rather than being dropped.

Five of the 15 full-arm comparisons show a preregistered protocol-level metric
difference and ten show no observed protocol difference. This is not a general
superiority result: holdout direction varies by seed, and the report permits no
LLM, PX4/Gazebo, physical, or generalized causal claim. Moreover, the no-memory
and no-reflection arms
are behaviorally identical in all five blocks. Because the scripted router
does not use receipt-only memory after reflection is removed, the incremental
effect of that receipt-only component is explicitly marked **inconclusive**
rather than credited with a benefit.

The separate reflection-trigger intervention freezes six required production
contract states and seven evaluated steps. Four steps show a direct causal
contract difference in phase, executable tool surface, and selected tool.
High-cost stagnation is a negative control: its trusted search summary remains
decision-governing after observed-outcome removal. Search-space exhaustion has
no dispatched cohort and is therefore marked
`inconclusive_intervention_not_activated`. This is source-level causal protocol
evidence, not an outcome-benefit result. The canonical artifact SHA-256 is
`cb7cc30bac7f63df4ddda84d81f881e111b6bac229eacc0b5ec5a228df3b0c38`.

The pilot-informed long-horizon stress expands the same five seed blocks and
four arms to four generations and a common 120-Trial ceiling. All 20 synthetic
Jobs complete with 1,588 persisted Trials, complete evidence, and zero network
calls. The no-reflection intervention activates and changes tool sequence and
outcome in all five primary comparisons, but neither performance direction is
consistent: full AURORA has lower holdout loss in 1/5 blocks and lower realized
Trial count in 3/5. The no-reflection arm has lower holdout loss in 4/5 and
lower Trial count in 2/5; comparison-minus-full Trial count totals `+44`.
Accordingly, the frozen artifact permits a synthetic protocol-effect statement
only and explicitly rejects general quality, cost, LLM, PX4/Gazebo, physical,
or safety benefit. Its canonical SHA-256 is
`6da3544651ee56428b6e78f1613fd520c46b789dc3e7f9d44fc8be153dd9f5b3`.

The bundled PX4/Gazebo effect-application matrix is now filled, but the repeated
comparative PX4/Gazebo **performance** main table, physical component-level
outcome ablations, multi-seed performance confidence intervals,
latency/token/cost results, and UX measurements remain unfilled until their
locked experiments run.

## Software validation and remaining gate

The latest exact-commit **full-suite** receipt included by the historical v9
bundle is `artifacts/test-runs/aurora-software-c1222c9-receipt.json`: 1,204
passes plus a 28-test focused supplement at software subject
`c1222c9215e01a56351f6588af0d2b8694bca831`. It remains valid for that
historical source only.

The v10 software subject has a narrower post-commit receipt at
`artifacts/test-runs/technical-report-evidence-v10-9749244/test-receipt.json`:
70/70 evidence-compatibility tests and 7/7 focused tamper tests. Its internal
receipt SHA-256 is
`b9407556588e5c0a65d3e93f22e29d0fdd8fd4bb57f1b5cb1c890f94c7b9d98d`.
The receipt honestly records `exact_final_commit_run=false`, because the
worktree also contained only the generated v10 outputs and recursive
exact-byte attribute rule. It is not a replacement current-head full-suite
receipt. V10 therefore marks both current-source full regression and the
Windows Rust desktop gate as not included. No final software or report
release-readiness claim follows from this focused receipt.

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
  backend\scripts\evaluate_harness_component_ablations.py

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_component_ablations.py `
  --check

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_reflection_triggers.py `
  --check `
  --allow-archived-evidence-2-7-prompt-1-6

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_reflection_outcome_stress.py `
  --check

backend\.venv\Scripts\python.exe `
  backend\scripts\evaluate_harness_cross_job_memory.py `
  --check

backend\.venv\Scripts\python.exe `
  backend\scripts\export_technical_report_evidence.py `
  --source-commit c1222c9215e01a56351f6588af0d2b8694bca831 `
  --generated-at 2026-07-28T15:44:30Z `
  --backend-test-receipt artifacts\test-runs\aurora-software-c1222c9-receipt.json `
  --output artifacts\technical-report\evidence-v9.json `
  --manifest-output artifacts\technical-report\evidence-v9.manifest.json `
  --sha256-output artifacts\technical-report\evidence-v9.sha256 `
  --csv-directory artifacts\technical-report\csv-v9

python `
  backend\scripts\export_technical_report_evidence_v10.py `
  --check
```

The v10 verifier rereads the frozen output metadata, rebuilds every current
summary, obtains historical v9 sources from their exact Git freeze blob, and
requires the JSON, manifest, checksum inventory, and three CSV exports to match
byte for byte. Versioned ablation JSON/CSV/hash files under
`backend/evaluation_artifacts/` remain source-controlled software-contract
evidence. Files under `artifacts/technical-report/` are frozen report inputs;
their evidence class is determined by their verified source, not merely by that
directory.

### Frozen Evidence 2.8 cross-Job memory contract

The v9 frozen software contract is Evidence 2.8 / Prompt Template 1.7 /
Decision Trace 1.4. Its `harness-cross-job-memory-contract-v1` bundle contains 10
deterministic in-memory SQLite cases: two compatible same-user retrievals and
eight negative isolation/lifecycle cases covering cross-user, anonymous,
task-family, catalog-version, revocation, expiry, contract-version, and
source-receipt drift. All 10 pass; provider, network, and simulator calls are
zero, and the provider projection contains no source or owner identifiers.

This result is software-contract evidence, not an optimizer-quality result. The
554-Trial component outcome ablation remains an Evidence 2.7 / Prompt 1.6
historical freeze. The latest online provider freeze is Evidence 2.8 / Prompt
1.7 and also cannot validate cross-Job memory or Evidence 2.9 planning.
Equal-configured-budget dispatcher evidence now exists, but a new real Evidence
2.9 provider run and any causal outcome-benefit comparison remain separate
gates.

### Current Evidence 2.9 multi-tool dispatcher contract

The current runtime contract is Evidence 2.9. It adds a bounded multi-tool
generation plan, one anonymous proposal-revision turn, per-tool wall/CPU
enforcement, finalization fences, and a verified de-identified
`generation_plan_history`. Every history row must recompile from the persisted
opportunity to the same plan hash and must match its revision and final tool
ledger. Orphan, duplicate, replayed, version-drifted, hash-drifted, and
cost-drifted rows are excluded instead of repaired by event adjacency.

`backend/scripts/evaluate_harness_multi_tool_budget.py` is the source-owned
offline evidence generator. It gives the direct portfolio and scripted
multi-tool arm the same configured two-generation, 40-Trial ceiling on
`MockSimulatorAdapter`; records realized Trial use plus plan, revision, tool
wall, and tool CPU measurements; verifies each multi-tool result through the
Evidence 2.9 history compiler; and blocks all network connections. The scripted
policy makes zero real provider calls and reads no credential.

This evidence is classified `SYNTHETIC_MOCK`. It can establish execution,
provenance, fail-closed history, concurrency, and accounting behavior under the
enumerated fixtures. It cannot establish LLM routing quality, optimizer
superiority, PX4/Gazebo fidelity, physical-flight improvement, safety, or causal
Harness benefit. The frozen run contains three budget-parity blocks, six arm
runs, six verified scripted generations, three multi-tool generations, and
zero real provider/network calls. The Evidence 2.8 online routing artifact and
prior component ablations remain immutable historical freezes. A real Evidence
2.9 provider campaign requires a new, single-use user approval for its stated
call count and possible cost.

### Bundled advanced-physics closure

`artifacts/technical-report/advanced-physics-closure-v2-f1e8fa8/` aggregates
four real PX4/Gazebo evidence roles and recompiles the current launcher
capability contract. Its exact-byte manifest verifies all nine bundled effect
categories and an empty Runtime-extension list. The manifest file SHA-256 is
`5345cd6b7fa78d927ee2da9491dfbfd20e8a8373593c110baa332436808bdba3`;
the 52-test compatibility receipt passes 52/52.

The closure separates physical application from policy success. Constant
wind/obstacles, gust/payload/actuator delay, and barometer/IMU noise have
retained successful flights. GPS noise retains a readiness boundary.
Dropout/battery has verified failure/restore and telemetry transitions but a
false policy verdict. Hard actuator failure has failed-rotor hard-stop and
healthy-rotor motion read-back but no trusted scoring window. The report may
claim these enumerated application/read-back facts; it may not turn them into
universal controller robustness, optimizer benefit, real-aircraft transfer, or
safety.
