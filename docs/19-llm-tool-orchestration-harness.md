# LLM Tool-Orchestrated Optimization Harness

Status: approved target design; compatibility execution slice and evidence-v2 router diagnostics implemented, hardened target gated<br>
Audience: backend, optimization, simulation, security, evaluation, and course-review stakeholders<br>
Scope: DroneDream's automated PX4/Gazebo tuning loop<br>
Last reviewed: 2026-07-26

## 1. Executive decision

DroneDream should not make a large language model another optimizer beside CMA-ES,
TuRBO, SAASBO, or constrained MOBO. It should make the model a bounded
**optimization orchestrator** above those algorithms:

1. deterministic code builds an evidence snapshot from verified search observations
   and policy-authorized validation aggregates;
2. the LLM chooses which approved proposal tools to use and how much of the next
   generation's budget each tool receives;
3. pure proposal tools generate candidate parameter sets;
4. deterministic validators enforce the parameter domain, coupling rules, safety
   policy, fidelity policy, scenario contract, and remaining trial budget;
5. only the existing server-side dispatcher may create trials;
6. PX4/Gazebo supplies execution artifacts, while a signed secretless verifier and
   deterministic acceptance/final-test policies remain the measurement authority;
7. every model decision, tool call, validation result, fallback, physical simulator
   attempt, artifact digest, metric observation, and final-test verdict is recorded for
   replay and evaluation.

This is deliberately a **bounded agentic workflow**, not an unconstrained autonomous
agent. The LLM supplies semantic judgment and adaptive tool selection. It never
receives a shell, database write access, simulator control, credentials, or the
authority to waive a safety or budget rule.

The initial implementation should make one orchestration decision at each generation
boundary. It should not call an LLM for every seed, scenario, or trial. A later
version may add a bounded second decision after proposal tools return, but only if
evaluation proves that the extra call improves optimization outcomes enough to
justify its cost, latency, and larger failure surface.

## 2. Why this change is necessary

### 2.1 The current code makes GPT and numerical optimizers mutually exclusive

The current API expresses a job with one `optimizer_strategy`. In
`backend/app/schemas.py`, `gpt`, `cma_es`, the experimental optimizers, and
`optimizer_portfolio` are sibling values. In
`backend/app/orchestration/aggregation.py`, continuation dispatch is an exclusive
branch:

- `gpt` calls `dispatch_next_llm_generation`;
- `cma_es` calls `dispatch_next_cma_es_generation`;
- an experimental strategy calls `dispatch_next_experimental_generation`.

That structure answers “which optimizer runs?” but cannot answer “which tool should
the LLM use now?” Selecting a numerical algorithm removes the LLM from the loop;
selecting GPT removes the specialized algorithms from the loop.

### 2.2 The current LLM is a direct one-candidate proposer

`backend/app/orchestration/llm_parameter_proposer.py` asks an OpenAI-compatible
model to produce exactly one next-generation parameter set. It already has useful
engineering controls:

- a JSON schema;
- response-size, depth, and node limits;
- parameter-domain validation;
- bounded provider URL handling;
- explicit failure rather than a silently relabeled deterministic proposal.

Those controls should be retained. The missing layer is a tool registry and an
orchestration protocol. The model currently proposes raw controller gains; it
cannot allocate work to the existing numerical optimizers or explain why a tool
fits the observed evidence.

### 2.3 DroneDream already has most of the “hands”

The six-child deterministic portfolio in
`backend/app/optimization/portfolio_optimizer.py` already exposes the right
algorithmic substrate:

- constrained multi-objective Bayesian optimization;
- multi-fidelity Bayesian optimization;
- TuRBO;
- SAAS-inspired Bayesian optimization;
- surrogate-assisted CMA-ES;
- BIPOP-CMA-ES.

It also records child ownership, fidelity, fallback provenance, exploration roles,
and per-child statistics. These implementations should become versioned proposal
tools. The new work is primarily a reliable “brain-to-hands” contract, durable
decision state, and evaluation, rather than a rewrite of the optimizers.

### 2.3.1 The current database-to-numerics adapter has legacy semantics

`backend/app/orchestration/experimental_optimizer.py` already performs deterministic
candidate ordering, search-space projection, direction-aware constraint extraction,
pending-candidate reservation, fidelity extraction, and history-derived seeding.
That logic is valuable, but several backward-compatibility paths cannot remain
silent in the new control plane:

- a historical row that cannot project into the current search space is skipped;
- malformed effective/requested fidelity may be normalized to a low default, while
  absent legacy fidelity is interpreted as full requested fidelity;
- a missing aggregate feasibility marker may be interpreted as feasible;
- a missing unpenalized `scalar_loss` may fall back to `aggregated_score`;
- optimizer ownership is reconstructed from untyped metadata strings.

The target adapter must not rewrite old rows, but it must emit an explicit
`DataQualityReport` for every inclusion, exclusion, and legacy inference. New
LLM-harness rows require complete typed fields and relational provenance; legacy
coercion is read-only compatibility, never the schema for new evidence.

### 2.4 “LLM present” is not itself a contribution

Keeping deterministic and fixed-algorithm modes is essential. They are the
baselines needed to determine whether LLM orchestration actually improves:

- sample efficiency;
- final feasible objective value;
- robustness;
- recovery from optimizer stagnation;
- correct fidelity escalation;
- wall-clock time;
- total model and simulation cost.

The course-aligned claim must be empirical: an LLM can inspect structured evidence
and choose among specialized tools more effectively for some tuning regimes. The
claim must not be “the product uses an LLM somewhere.”

### 2.5 The course contribution is a compound engineering system

The proposed contribution is not a chat box attached to an optimizer. It is a
compound system in which the model performs the part that benefits from semantic
judgment—interpreting typed failure patterns, comparing tool capabilities, and
forming a bounded search plan—while deterministic software performs the parts that
require authority, repeatability, and measurement. The course-relevant research
question is therefore:

> Under a frozen experiment contract and equal simulation budget, when does an LLM
> selecting among trusted optimization tools outperform a strong deterministic
> portfolio, and what harness controls are required for that advantage to be safe,
> attributable, and reproducible?

This framing keeps the LLM causally central without manufacturing a reason for it to
touch every trial. The ablations in Section 22 separate the value of model planning,
the tool implementations, the deterministic fallback, and the execution harness.

## 3. Research-derived design principles

The architecture in this document adopts the following conclusions from primary or
official sources.

### 3.1 Prefer a simple, composable workflow before open-ended autonomy

Anthropic distinguishes predefined workflows from agents that dynamically direct
their own tool use, and recommends starting with the simplest solution that meets
the need. DroneDream therefore uses a deterministic outer state machine with one
bounded model decision per generation, not a free-running conversation loop.

Source: [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

### 3.2 A tool is an agent-facing contract, not a thin API wrapper

Tool quality depends on clear purpose, non-overlapping names, meaningful and
token-efficient results, precise descriptions, and evaluation with the target
models. DroneDream tools should expose optimization capabilities and evidence
summaries, not every internal repository method.

Source: [Anthropic, Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents).

### 3.3 Use strict schemas, then validate semantics in application code

Schema-constrained function calling prevents malformed structures but cannot prove
that a choice is safe, useful, or consistent with the experiment. Every tool call
must use strict input/output schemas when the provider supports them. The server
must still perform semantic validation after parsing.

Sources:

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling);
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs);
- [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

### 3.4 Constrain data flow, not only the prompt

Untrusted labels, notes, imported JSON, simulator text, and tool output must never
be interpolated into high-authority instructions. Data should cross model/tool
boundaries through typed fields. Model output is data to validate, never executable
instructions.

Sources:

- [OpenAI safety in building agents](https://developers.openai.com/api/docs/guides/agent-builder-safety);
- [OWASP LLM06: Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/);
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/).

### 3.5 Separate creative proposal from automated verification

FunSearch and AlphaEvolve pair LLM-generated ideas with objective automated
evaluators and iterative selection. DroneDream has an unusually strong fit for this
pattern: controller proposals can be judged by repeatable simulator runs, a pinned
metric contract, and explicit acceptance criteria. The LLM may decide what to try; it
does not decide whether a Trial passed, and the simulator runner does not self-author
the accepted verdict.

Sources:

- [Google DeepMind, FunSearch](https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/);
- [Google DeepMind, AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/);
- [Microsoft Research, OptiGuide](https://www.microsoft.com/en-us/research/project/optiguide-genai-for-supply-chain-optimization/publications/).

### 3.6 Evaluate the harness and model together

An agent evaluation measures the model, instructions, tool interface, state
handling, and environment as a combined system. It must grade both the trajectory
and the real final state. DroneDream needs optimization outcomes, decision
validity, and trace review—not “the explanation sounded reasonable.”

Sources:

- [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents);
- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

### 3.7 Durable execution requires checkpoints and idempotent effects

Any operation after a crash may be repeated. Provider calls, proposal generation,
candidate insertion, and trial dispatch need stable idempotency keys and durable
intent/result rows. No network call should occur inside a long database transaction.

Source: [LangGraph durable execution guidance](https://langchain-ai.github.io/langgraph/how-tos/review-tool-calls-functional/).

### 3.8 Traces must join model, tool, and simulation operations

Traces should causally join bounded decision, model, validation, tool, dispatch,
simulation, and aggregation stages. They must not keep one process-local span open
across a long Job: asynchronous/restarted stages create bounded traces linked through
durable ledger references. Raw prompt/tool content, exception text, IDs, and content
hashes are excluded by default because they can carry secrets, sensitive experiment
data, or stable correlators. The official OpenAI Agents SDK likewise traces
generations, tool calls, guardrails, and custom events, while documenting that its
hosted tracing is unavailable under Zero Data Retention. DroneDream therefore treats
its local decision ledger as the canonical audit record and any vendor trace exporter
as an optional, lossy projection.

Sources:

- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/);
- [OpenAI Agents Python tracing, official GitHub repository](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md).

### 3.9 Tool selection ability must be measured, not assumed

The ICLR MetaTool benchmark separates deciding whether a tool is needed from
selecting among similar, unreliable, or multiple tools, and reports that tested
models still struggle with these choices. DroneDream must therefore evaluate
near-duplicate optimizer descriptions, unavailable tools, multi-tool plans, and
tool-order permutations. A polished rationale is not evidence of correct selection.

Source: [MetaTool Benchmark, ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/bc12914d66b41b6bfc2d3a5decdb498b-Abstract-Conference.html).

### 3.10 Stopping is an optimization policy, not a linguistic judgment

Research on Bayesian-optimization stopping criteria derives stopping decisions from
measured expected-regret gaps rather than prose confidence. DroneDream does not
require that specific criterion for every optimizer, but adopts the architectural
lesson: a model may recommend stopping; a versioned deterministic policy must decide
whether the recommendation is admissible.

Source: [Ishibashi et al., AISTATS 2023](https://proceedings.mlr.press/v206/ishibashi23a.html).

### 3.11 A number is evidence only under a measurement contract

NIST treats a measurement result as a value of an adequately described quantity with
its unit. Coordinate and time conventions are equally semantic: REP-103 defines ENU
and NED differently, while PX4 local position is NED. DroneDream therefore cannot
accept a finite `rmse=0.3` without the metric formula, SI unit, coordinate frame, time
axis, source-artifact digest, coverage rules, and verifier revision that make the
number comparable.

W3C PROV's entity/activity/agent and usage/generation/derivation relations provide a
useful minimum provenance model. DroneDream uses that structure to bind Trial input,
source ULog, canonical telemetry, verifier execution, and accepted metric observation
without requiring a model to inspect raw artifacts.

Sources:

- [NIST SP 330 §2](https://www.nist.gov/pml/special-publication-330/sp-330-section-2);
- [Open Robotics REP-103](https://reps.openrobotics.org/rep-0103/);
- [PX4 `VehicleLocalPosition`](https://docs.px4.io/main/en/msg_docs/VehicleLocalPosition);
- [W3C PROV Data Model](https://www.w3.org/TR/prov-dm/).

### 3.12 A test set consulted during selection becomes development data

Google's training/validation/test guidance and scikit-learn's nested-validation example
describe the same leakage mechanism: repeatedly selecting hyperparameters on test
outcomes yields an optimistic estimate. In DroneDream, controller gains, optimizer
tools, prompts, stopping rules, and promotion thresholds are selected
hyperparameters. Any scenario/seed suite run for every Candidate is therefore
validation, whatever its field name says.

The target materializes a sealed controller final test only after one winner and every
policy are frozen, and separately protects the Harness research campaign's locked test
bank. A disappointing test verdict creates a new future campaign; it never authorizes
another Candidate from the same search.

Sources:

- [Google: Training, validation, and test sets](https://developers.google.com/machine-learning/crash-course/overfitting/dividing-datasets);
- [scikit-learn: Nested versus non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).

## 4. Terminology and authority boundaries

DroneDream currently uses “harness” for its broader PX4/Gazebo execution and
evidence system. This document splits that concept into two cooperating layers:

| Term | Responsibility | Authority |
| --- | --- | --- |
| Execution and evidence harness | runs scenarios, captures artifacts, computes metrics, applies acceptance rules | authoritative |
| LLM decision harness | packages evidence, exposes approved tools, asks for a bounded plan, records the trace | advisory |
| Proposal tool | returns candidate parameter sets and optimizer metadata without dispatching trials | advisory |
| Plan validator | checks schemas, capabilities, budget, safety, fidelity, uniqueness, and state version | authoritative |
| Dispatcher | creates candidates/trials after a plan is accepted | authoritative |
| Final-test verifier | materializes sealed cases only after winner freeze and evaluates that one Candidate | authoritative |

No model message, rationale, confidence score, or tool annotation can override an
authoritative component.

## 5. Target architecture

```text
                         immutable experiment contract
                                      |
                                      v
                         +--------------------------+
                         | Evidence snapshot builder|
                         | search/validation only   |
                         +------------+-------------+
                                      |
                          snapshot + tool manifest
                                      |
                                      v
 +----------------+       +--------------------------+       +------------------+
 | Model provider |<----->| LLM decision harness     |------>| Decision ledger  |
 | adapter        |       | one strict plan call     |       | trace + hashes   |
 +----------------+       +------------+-------------+       +------------------+
                                      |
                              declarative tool calls
                                      |
                                      v
                         +--------------------------+
                         | Trusted proposal tools   |
                         | BO / CMA / diagnostics   |
                         +------------+-------------+
                                      |
                                candidate batch
                                      |
                                      v
                         +--------------------------+
                         | Deterministic plan gate  |
                         | safety + budget + CAS    |
                         +------------+-------------+
                                      |
                                      v
                         +--------------------------+
                         | Existing trial dispatcher|
                         +------------+-------------+
                                      |
                                      v
                         +--------------------------+
                         | PX4 / Gazebo workers     |
                         +------------+-------------+
                                      |
                                      v
                         +--------------------------+
                         | Metrics + acceptance +   |
                         | failures + artifacts     |
                         +------------+-------------+
                                      |
                           next training generation
```

The model does not call PX4/Gazebo. In Version 1 it submits one declarative plan
that selects proposal tools from a trusted registry. The harness executes those
pure tools only after the plan passes validation. In a later interactive profile,
the model may call read-only diagnostic or proposal tools and inspect their results,
but the deterministic gate and dispatcher still own every side effect.

## 6. Product-level orchestration modes

`optimizer_strategy` currently combines two independent choices. Split it into:

### 6.1 `orchestration_mode`

| Mode | Behavior | Requires model access |
| --- | --- | --- |
| `fixed_algorithm` | one selected proposal algorithm receives every generation | no |
| `deterministic_portfolio` | the current deterministic heuristic portfolio allocates the batch; it is not presented as a calibrated UCB policy | no |
| `llm_harness` | the LLM chooses among an allowlisted tool set at generation boundaries | yes |

### 6.2 `fixed_algorithm`

This field is required only when `orchestration_mode=fixed_algorithm`. It uses the
existing algorithm identifiers and may include `direct_llm_proposal` as an explicit
experimental baseline. Direct LLM proposal must not be the default meaning of
`llm_harness`.

### 6.3 `fallback_policy`

| Policy | Intended use |
| --- | --- |
| `fail_closed` | course evaluation and debugging; exposes model/harness reliability |
| `deterministic_portfolio` | normal product use; preserves progress during provider failure |
| `pause_for_user` | high-cost or manually supervised experiments |

Fallbacks must appear in the job result, event stream, report, and trace. A
deterministic fallback must never be reported as an LLM-selected decision.

### 6.4 Backward compatibility

During migration:

- legacy `gpt` maps to `fixed_algorithm + direct_llm_proposal`;
- legacy `optimizer_portfolio` maps to `deterministic_portfolio`;
- every other optimizer maps to `fixed_algorithm + <legacy value>`.

New writes use the split fields. Old fields remain readable for one schema version
and are then removed through an explicit migration.

## 7. Generation-boundary decision protocol

### 7.1 Two distinct transport profiles

The domain decision is always a `GenerationPlan`. Provider APIs may transport it in
two ways:

| Profile | Model interaction | Status |
| --- | --- | --- |
| `declarative_plan_v1` | the model calls exactly one strict `submit_generation_plan` function whose arguments contain all selected tool invocations | required first implementation |
| `native_optimizer_calls_eval` | the provider exposes each eligible optimizer as a separate native function and the model may emit zero or more optimizer function calls in one response | evaluation-only transport |
| `interactive_tools_v2` | the model calls bounded read-only/proposal tools, observes typed results, then submits a final plan | deferred experiment |

`declarative_plan_v1` is an **indirect meta-tool routing** protocol. The model selects
versioned optimizer tool IDs and supplies their bounded arguments inside one
plan-submission function; the optimizer implementations are not themselves exposed as
separate provider-native functions. The harness executes the selected optimizer tools
only after validation. This is still model-directed tool selection at the domain
layer, but it must not be described in papers, UI copy, traces, or course claims as
evidence that the model directly invoked several native optimizer functions.

The meta-tool is the Version 1 product default because it gives the control plane one
atomic object to validate before any proposal computation or simulation dispatch.
That safety and recovery advantage is a design choice, not proof that this transport
produces the best routing behavior. `native_optimizer_calls_eval` therefore remains a
required comparison profile wherever a provider can return several strict function
calls without executing them immediately. Its calls are also treated as proposals,
compiled into the same `GenerationPlan`, and held behind the same durable gate.

This profile resolves an important API constraint: a model cannot normally inspect
a function result without a subsequent model request. Claiming both “one model
turn” and “the model observes tool results” would be incorrect. Version 1 chooses
one turn and no intermediate observation.

### 7.2 Version 1: one bounded model turn

At the end of a completed training generation:

1. acquire a short per-job orchestration lease;
2. verify that no unfinished trials exist for the generation;
3. compute the remaining candidate and trial budget;
4. apply hard deterministic completion, cancellation, and zero-discretionary-budget
   rules before spending a model call;
5. build and persist an immutable `EvidenceSnapshot`;
6. persist a `REQUESTED` optimization decision with an idempotency key;
7. release the database transaction;
8. call the provider with the snapshot, eligible-tool catalog, and one strict
   `submit_generation_plan` function;
9. persist the raw provider envelope after redaction and size enforcement;
10. parse the single `submit_generation_plan` call into a `GenerationPlan`;
11. run the deterministic plan validator;
12. compile and persist an immutable `CompiledGenerationPlan`;
13. execute accepted pure proposal tools from the compiled plan;
14. validate and deduplicate the consolidated candidate batch;
15. atomically reserve budget and insert candidates/trials;
16. mark the decision `DISPATCHED`;
17. let the existing workers and aggregation loop continue.

The LLM is allowed to choose tools, allocations, fidelity intent, and a stopping
recommendation. It is not allowed to create arbitrary parameter names, scenario
seeds, commands, URLs, or trial rows. `parallel_tool_calls` is disabled because the
only model-visible function is the atomic plan submission.

### 7.2.1 Deterministic cold start

`llm_harness` does not imply a model call before useful evidence exists. The immutable
job contract defines `model_activation_policy`, initially:

- a minimum number of completed, informative observations;
- a minimum number of represented parameter-space regions;
- whether at least one feasible full-fidelity incumbent is required;
- a maximum deterministic warm-up generation count.

Before activation, the existing deterministic coverage design or portfolio owns the
batch and events label it `deterministic_warmup`, not LLM fallback. Once activation
conditions hold, the model receives the first evidence snapshot. If they never hold
because every warm-up trial fails, the job follows an explicit infrastructure or
feasibility policy rather than asking a model to infer from empty evidence.

The evaluation campaign freezes this policy and reports warm-up simulation cost. A
separate ablation may call the model from generation zero, but the product default
should not pay for semantic routing when the snapshot contains no discriminating
evidence.

### 7.2.2 Exploration floor and allocation authority

After cold start, giving every slot to the model can create a self-confirming loop:
an early-selected tool receives more observations, while an ignored tool has no
opportunity to demonstrate improvement. Version 1 therefore divides the generation
capacity before the model call:

```text
generation capacity
  = policy-reserved exploration/coverage slots
  + model-discretionary slots
  + unallocated safety margin
```

The immutable `ExplorationPolicy` computes any reserved calls and exposes them in the
snapshot. The model allocates only the discretionary count. A default policy may
reserve roughly 10–20% after warm-up, but the exact cadence and minimum sample rule
are frozen per campaign rather than buried in prompt prose. No reserved slot is
created when it would violate a hard budget, tool eligibility, or final-verification
rule.

Every consolidated tool call records `allocation_authority` as `policy`, `model`, or
`fallback`. The UI and evaluation report must not describe a policy-reserved call as
an LLM choice. The plan validator rejects discretionary allocations that consume
reserved capacity; it does not silently shrink them.

The model is not called when zero discretionary slots remain. If the model recommends
stop or pause, reserved calls are not executed until that recommendation is
authoritatively resolved. A rejected stop/pause follows its frozen fallback policy;
the harness does not reinterpret an empty model plan as permission to spend the
reserved slots.

Evaluation reports two comparisons. The product comparison leaves the current
deterministic portfolio's own exploration behavior intact. A routing-isolation
ablation externalizes the same frozen exploration floor for both arms and compares
only their discretionary allocation. Additional ablations compare no floor, matched
floor, and the current portfolio policy.

### 7.3 Why tool execution is deferred

Native tool calling often executes each tool as soon as the model requests it. For
DroneDream, dispatching simulation from a tool would make partial or duplicated
plans expensive and difficult to recover. Instead:

- the model receives precomputed Version 1 evidence in the snapshot;
- proposal tools execute only after the complete plan is parsed and validated;
- simulation dispatch happens only after the whole generation plan passes.

This gives the model real tool choice without giving each tool side-effect authority.

### 7.4 Version 2: optional bounded inspect-and-select turn

An optional later protocol may:

1. let the model allocate proposal tools;
2. execute proposal tools without simulation;
3. return compact proposal diagnostics;
4. let the model select a final batch.

It has a hard maximum of two model calls, a maximum number of tool calls, and a
transcript byte limit. It must be compared against Version 1 under identical
simulation budgets. It is out of scope until Version 1 has decision and outcome
evals.

## 8. Evidence snapshot

The LLM should receive a compact, immutable, versioned summary rather than ORM
objects or the full event log.

```json
{
  "schema_version": "1.0",
  "generation_index": 4,
  "state_version": 17,
  "experiment_contract_hash": "sha256:...",
  "parameter_space": {
    "dimension": 8,
    "domains": [],
    "coupling_rule_ids": [],
    "restart_required_parameter_count": 0
  },
  "outcome_contract": {
    "contract_hash": "sha256:...",
    "profile_id": "robust-v1",
    "objective_representation": "registered_scalar_preference",
    "scenario_estimand": "fixed_search_suite",
    "risk_measure": "registered_cvar",
    "constraint_precedence": "lexicographic_feasibility_first"
  },
  "scenario_contract": {
    "search_case_count": 3,
    "search_seed_count": 3,
    "search_matrix_size": 9,
    "search_seed_schedule_hash": "sha256:...",
    "validation_summary_available": true,
    "sealed_final_test_redacted": true
  },
  "budget": {
    "remaining_trials": 72,
    "max_candidates_this_generation": 4,
    "allowed_fidelities": [0.35, 0.65, 1.0],
    "model_call_budget_remaining": 7
  },
  "best_search_candidate": {},
  "recent_generations": [],
  "failure_summary": {},
  "routing_evidence_summary": [],
  "exploration_policy": {
    "revision": "explore-v1",
    "reserved_allocations": [],
    "model_discretionary_candidates": 3
  },
  "stagnation": {},
  "data_quality": {
    "included_verified_observations": 24,
    "included_pending_reservations": 0,
    "excluded_invalid_search_space_rows": 0,
    "legacy_loss_fallback_rows": 0,
    "legacy_feasibility_inference_rows": 0,
    "legacy_fidelity_inference_rows": 0,
    "unknown_or_missing_fields": [],
    "normalizer_revision": "observation-normalizer-v1"
  },
  "excluded_information": [
    "sealed final-test definitions, seeds, and outcomes",
    "secrets",
    "raw simulator logs",
    "unbounded user text"
  ]
}
```

### 8.1 Snapshot invariants

- It contains verified search evidence plus only the checkpointed validation aggregate
  authorized by the frozen promotion policy. Final-test definitions, seeds, rows, and
  outcomes do not exist in the ordinary snapshot query.
- The provider-visible canonical content omits user IDs, job IDs, candidate IDs,
  database keys, local paths, and artifact URLs. The database relates the snapshot
  to its job outside the model payload, while evidence references use bounded
  ordinal paths.
- Every numeric aggregate is recomputable from persisted candidates, trials, and
  metrics.
- Missing data is explicit; it is never silently replaced by zero.
- Legacy inference and excluded-row counts are explicit and link to a private
  exclusion report; the model sees bounded counts/reasons, not database IDs.
- It records effective as well as requested fidelity.
- Failure counts separate verified domain constraints/censoring from infrastructure,
  evidence-contract, policy-rejection, cancellation, and superseded outcomes.
- Every `routing_evidence_summary` entry is a deterministic bounded projection of
  immutable routing opportunities, exact proposal sources, Candidate outcome
  envelopes, routing reward events, and complete incurred cost. It reports eligible
  opportunities, reserved/discretionary allocation, allocated/produced/accepted
  counts, pending/unobserved/ineligible rewards, fidelity-equivalent Trial cost,
  delay, and current availability/circuit state under one frozen window.
- The summary never substitutes the current portfolio's generation-best loss,
  moving normalization, strategy-string ownership, or provider rationale for reward.
  A tool with no eligible resolved reward is shown as `insufficient_evidence`, not
  zero. Any interval or uncertainty label must name its registered estimator and
  effective sample count; otherwise only raw bounded counts are shown.
- Tool entries are ordered canonically, receive the same field/detail budget, and
  use a window defined by eligible routing opportunities rather than “the second
  half” of uneven observations. This prevents richer history, longer text, or missing
  rows from silently biasing model attention.
- Policy-reserved exploration and discretionary capacity are distinct. The model
  may allocate only the latter, cannot close/open a circuit, and cannot reinterpret
  an offline policy estimate as observed online performance.
- It never includes prior model rationale, free-form “memory,” or raw imported
  text. Prior decisions appear only as typed selections and measured outcomes.
- User-controlled strings are represented as data fields and length-limited.
- The canonical JSON bytes are hashed and stored before the provider call.

### 8.2 Context budgeting

The snapshot builder has a fixed token-independent byte budget. It uses:

- fixed recent-generation windows;
- top/bottom candidate summaries;
- aggregate parameter movement rather than every vector;
- enumerated failure codes rather than raw logs;
- pagination for opt-in diagnostic tools;
- a deterministic truncation report.

The trace records omitted sections so a small prompt cannot masquerade as complete
evidence.

### 8.3 Current Trial-to-evidence audit

The current repository is materially stronger than a thin “simulator returned a
number” prototype:

- `px4_gazebo_runner.py` bounds telemetry bytes and sample count, rejects
  non-finite values, requires strictly increasing timestamps, projects samples onto
  the 3-D reference polyline, records evaluation-window details, and computes the
  primary metrics from telemetry;
- `real_cli.py` bounds and parses the result JSON, rejects non-finite JSON constants,
  checks typed metrics, sanitizes artifacts, and validates a complete
  `execution_identity` for `trial_result.v2`;
- `trial_executor.py` fences persistence with `(trial_id, worker_id, attempt_count)`,
  so an obsolete lease holder cannot commit over a reclaimed attempt;
- `aggregation.py` recomputes case-weighted training rates, keeps failed dispatched
  seeds in denominators, and, for jobs with a current `objective_config`, overwrites
  the historical all-trial RMSE/error fields with training-only values before
  acceptance.

Those are useful foundations, but they are not yet a trustworthy Harness evidence
contract. The code audit found the following gaps:

| Current behavior | Why it is insufficient for Harness evidence |
| --- | --- |
| `trial_result.v1` may omit all identity fields | a legacy result can be accepted without proving which Trial, Candidate, seed, or attempt produced it |
| `final_error` defaults to `0.0` and several flags default to `false` when absent | absence can become a deceptively good observation rather than a schema failure |
| the result supplies already-computed metrics and `pass_flag` | the external runner is allowed to assert both the measurement and its verdict |
| telemetry has `x/y/z/t` but no mandatory unit, coordinate-frame, time-base, source-log digest, or extraction revision | finite values can still be semantically incomparable or transformed incorrectly |
| RMSE is `sqrt(sum(error²) / sample_count)` | irregular or selectively dense sampling changes the weight of a time interval |
| strictly increasing timestamps have no maximum-gap, expected-duration, or dropout-coverage requirement | a short or sparse trace can remain numerically valid |
| an `all_samples_fallback` evaluation window can still produce ordinary metrics | failure to identify the intended flight interval is annotation rather than evidence ineligibility |
| `overshoot_count` counts local peaks in absolute track error over a fixed `0.25 m` prominence | this is a tracking-error peak count, not yet a controller-overshoot measurand |
| all non-completed Trials count as candidate failures | adapter, port, storage, worker, and database failures can penalize controller parameters |
| the external simulator can return an arbitrary cleaned failure-code string | an untrusted producer can influence retry/evidence classification |
| only the latest Trial state and one `trial_metrics` row are relationally retained | retries, rejected outputs, verifier failures, and accepted-attempt provenance are not an immutable attempt ledger |
| artifact storage metadata records path and size but not a mandatory content digest or attempt identity | replay cannot prove which bytes a metric used |
| configured holdout runs are dispatched for each Candidate, and holdout pass is part of Candidate publishability | the “holdout” influences selection and is therefore a validation set, not an untouched final test |
| legacy aggregation initially mixes all metrics and only the modern objective path replaces key fields with training values | compatibility paths remain too easy to use as if they had the same isolation guarantees |
| rate parsing clamps values into `[0, 1]` | corrupted persisted evidence can be silently normalized instead of stopping the decision |
| completed metrics are rounded before durable aggregation | display precision and evidence precision are conflated |

The target therefore treats **evidence compilation** as a first-class trusted stage,
not as a few additional fields on `TrialMetric`.

### 8.4 Closed trial-outcome taxonomy

A physical simulation attempt has exactly one outcome class from a closed enum. A
free-form runner failure code is diagnostic text and never selects the class.

| Outcome class | Meaning | Optimizer dataset | Candidate completeness | Retry policy |
| --- | --- | --- | --- | --- |
| `valid_observation` | complete, verified telemetry produced every required measurand | objective and constraint observations | counts complete | no automatic repeat |
| `domain_constraint_failure` | the run reached the frozen evaluation phase and verified evidence proves crash, instability, safety violation, or other candidate-dependent infeasibility | typed constraint/failure observation; no invented objective | counts complete only for tools that declare this observation type | no infrastructure retry |
| `domain_right_censored` | verified flight evidence proves the candidate failed to finish by the experiment deadline | typed censored duration and failure constraint only | counts complete only for censor-aware tools | no ordinary retry |
| `policy_rejection` | candidate failed the deterministic parameter/coupling/safety gate before simulator launch | feasibility label associated with the proposal, not a simulator metric | no Trial slot should have been committed | never run |
| `infrastructure_failure` | runtime, PX4/Gazebo launch, port, worker, storage, database, or trusted service failed without proving a candidate outcome | excluded from parameter evidence; retained in health/reliability ledger | incomplete | exact Trial/seed retry within infrastructure budget |
| `evidence_contract_failure` | identity, digest, unit, frame, telemetry, schema, verifier, or provenance checks failed | excluded and quarantined | incomplete | retry only after trusted fault classification; trip circuit breaker on repetition |
| `cancelled` | user/system cancellation won the state transition before evidence acceptance | excluded | neither pass nor fail | no retry unless explicit resume policy creates one |
| `superseded` | stale fenced attempt completed after a newer owner or terminal state | excluded, bytes retained only under forensic policy | no effect | never retry because of this result |

Timeout is not one universal failure code:

1. queue expiration, PX4 boot timeout, Gazebo readiness timeout, missing offboard
   handshake, port conflict, lost worker, and persistence timeout are infrastructure;
2. a frozen flight-completion deadline is `domain_right_censored` only when signed
   phase evidence proves that the intended controller, scenario, reference, and
   evaluation interval were active;
3. an ambiguous wall-clock kill without that phase proof is an
   `evidence_contract_failure` or `infrastructure_failure`, never a synthetic bad
   RMSE.

The classifier is a versioned trusted function over phase evidence, process exit
facts, and verifier output. It does not trust the runner's chosen label. Every code
maps to one class and one retryability; unknown codes fail closed.

This distinction is necessary because crash-constrained optimization can learn from
a genuine candidate-dependent crash even when no objective value exists, while
infrastructure loss contains no information about the parameter vector. Research on
[robot learning with crash constraints](https://arxiv.org/abs/2010.08669) and
[Bayesian optimization with censored responses](https://arxiv.org/abs/1310.1947)
supports representing those observations explicitly rather than fabricating a
normal objective value.

### 8.5 `TrialAttemptEvidenceEnvelopeV3`

Harness-mode real simulation accepts only a complete Version 3 envelope. Versions 1
and 2 remain readable for old reports but are ineligible for new Harness decisions.

```json
{
  "schema_version": "dronedream.trial_attempt_evidence.v3",
  "execution_identity": {
    "job_id": "job_...",
    "candidate_id": "cand_...",
    "trial_id": "tri_...",
    "attempt_count": 2,
    "scenario_instance_id": "scenario_...",
    "capacity_slot_id": "slot_...",
    "capacity_slot_fence": 41
  },
  "input_binding": {
    "trial_input_hash": "sha256:...",
    "experiment_contract_hash": "sha256:...",
    "parameter_vector_hash": "sha256:...",
    "scenario_contract_hash": "sha256:...",
    "seed_derivation_manifest_hash": "sha256:...",
    "seed_binding_evidence_hash": "sha256:...",
    "reference_track_hash": "sha256:...",
    "runtime_manifest_digest": "sha256:..."
  },
  "execution": {
    "backend_id": "px4_gazebo",
    "backend_revision": "sha256:...",
    "px4_commit": "40-hex...",
    "gazebo_version": "...",
    "started_monotonic_ns": 0,
    "finished_monotonic_ns": 0,
    "process_exit_kind": "exited",
    "process_exit_code": 0,
    "repeatability_class": "rerun_metric_tolerance",
    "randomness_capabilities": [
      {
        "domain": "simulator.physics",
        "component": "gz-sim",
        "state": "verified_bound",
        "delivered_seed_sha256": "sha256:...",
        "binding_evidence_sha256": "sha256:..."
      }
    ],
    "phase_timeline": []
  },
  "artifacts": [
    {
      "role": "source_ulog",
      "content_sha256": "...",
      "size_bytes": 0,
      "media_type": "application/octet-stream"
    },
    {
      "role": "canonical_telemetry",
      "content_sha256": "...",
      "size_bytes": 0,
      "media_type": "application/json"
    }
  ],
  "telemetry_contract": {
    "schema_version": "dronedream.telemetry.v2",
    "position_frame": "dronedream_local_neu_v1",
    "position_unit": "m",
    "velocity_unit": "m/s",
    "time_axis": "vehicle_boot_monotonic",
    "time_unit": "s",
    "sample_count": 0,
    "evaluation_sample_count": 0,
    "observed_duration_s": 0,
    "expected_duration_s": 0,
    "maximum_gap_s": 0,
    "gap_coverage_fraction": 0
  },
  "verification": {
    "verifier_id": "dronedream_metric_verifier",
    "verifier_revision": "sha256:...",
    "metric_contract_hash": "sha256:...",
    "status": "verified",
    "outcome_class": "valid_observation",
    "outcome_reason_code": "complete_track",
    "metric_observation_hash": "sha256:..."
  }
}
```

Required bindings are exact, not best effort. The Runtime rejects:

- a missing field or unsupported enum;
- a mismatch with the claimed Trial lease/fence;
- an input, parameter, scenario, seed-derivation, seed-evidence, reference, Runtime, or
  artifact hash mismatch;
- an artifact without an immutable digest;
- a result whose source ULog and extracted telemetry relationship was not verified;
- a `verified_bound` randomness capability without target-component identity,
  pre-initialization delivery, and request-bound readback/attestation;
- an unsigned/unmanifested verifier revision;
- a telemetry or metric contract not allowed by the frozen experiment contract;
- a second accepted envelope for the same logical Trial.

The provenance graph follows the useful subset of the
[W3C PROV model](https://www.w3.org/TR/prov-dm/): Trial input, ULog, canonical
telemetry, and metric observation are immutable entities; simulation, extraction,
and verification are activities; the signed runner/verifier revisions are software
agents. DroneDream need not serialize full PROV-O, but its relational links must be
losslessly projectable to entity/activity/agent, usage, generation, and derivation
relations.

### 8.6 Trusted metric compiler

The external simulator process produces execution facts and raw artifacts. It does
not author the accepted score or `pass_flag`. A separate secretless metric-verifier
executable from the signed Harness Runtime:

1. receives read-only descriptors for the frozen input contract, source ULog, and
   canonical telemetry;
2. verifies identities, hashes, schema, units, frame, time base, and coverage;
3. deterministically recomputes registered measurands;
4. derives typed domain constraints and the outcome class;
5. emits a canonical verifier envelope;
6. has no provider credentials, database write access, network egress, or authority
   to dispatch another Trial.

The parent accepts the verifier result with the same lease, capacity-fence,
state-version, and input-hash compare-and-swap used for Trial completion. A successful
simulator exit is not a successful Trial until this acceptance commits.

The metric registry is closed and versioned. Each entry defines:

- metric ID and semantic version;
- measurand in plain language;
- SI unit and physical dimension;
- canonical coordinate frame and time axis;
- required source fields and artifacts;
- evaluation-window algorithm;
- exact formula and numerical integration rule;
- valid range, missing-data policy, and coverage gates;
- whether a domain failure produces a constraint label, censored value, or no value;
- aggregation estimator, seed pairing, uncertainty summary, and display precision;
- compatible optimizer observation types.

NIST emphasizes that a reported measurement needs an adequately described quantity
and a unit, not a unitless number with an implied meaning
([NIST SP 330 §2](https://www.nist.gov/pml/special-publication-330/sp-330-section-2)).
DroneDream therefore uses SI symbols such as `m`, `s`, `m/s`, and `rad`, and never
accepts an unlabelled “RMSE” from a plug-in.

#### 8.6.1 Coordinate and time contract

The current DroneDream mapping is **not ENU**:

```text
PX4 NED north  -> DroneDream x
PX4 NED east   -> DroneDream y
PX4 NED down   -> DroneDream -z
```

The compatible canonical name is `dronedream_local_neu_v1`: x North, y East, z Up,
right-handed only after the complete documented transform is applied consistently.
It must never be labelled “ENU-like.” Open Robotics REP-103 defines geographic ENU
as x East, y North, z Up, while PX4 documents `vehicle_local_position.x` as North in
the NED frame
([REP-103](https://reps.openrobotics.org/rep-0103/),
[PX4 VehicleLocalPosition](https://docs.px4.io/main/en/msg_docs/VehicleLocalPosition)).

For Version 1 compatibility, reference tracks and canonical telemetry remain NEU.
All PX4 boundaries perform the exact NED↔NEU transform. A future move to standard
ENU requires a new frame ID and explicit migration; it cannot silently swap existing
X/Y values. Yaw is stored as `yaw_ned_rad` until a tested NEU/ENU angular convention
is frozen, rather than retaining an ambiguous field named `yaw`.

Time is `vehicle_boot_monotonic` seconds derived from the source log. Wall-clock
timestamps are provenance only and never enter RMSE or completion-time formulas.
Samples require strictly increasing time, a frozen maximum gap, minimum duration,
minimum sample count, and minimum valid evaluation coverage. Reordered, duplicate,
excessively gapped, or selectively truncated logs are evidence-contract failures.

#### 8.6.2 Tracking metrics

For irregular samples `(t_i, e_i)`, Version 1 tracking RMSE is time-weighted:

```text
integral_e2 = sum(0.5 * (e_i^2 + e_(i+1)^2) * (t_(i+1) - t_i))
tracking_rmse_m = sqrt(integral_e2 / (t_last - t_first))
```

This is the composite trapezoidal rule with the actual sample positions, matching
the distinction in the
[SciPy sampled-data integration API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.trapezoid.html)
between supplied `x` values and assumed equal spacing. The verifier also records the
unweighted legacy RMSE for report migration, but no Harness tool consumes it.

Other initial metrics are:

| Metric | Target definition |
| --- | --- |
| `tracking_rmse_m` | time-weighted 3-D point-to-polyline distance over the verified evaluation interval |
| `tracking_max_error_m` | maximum of the same verified error series, with source sample/projection reference |
| `completion_time_s` | duration from frozen track-entry event to verified completion; absent and right-censored on non-completion |
| `endpoint_error_m` | endpoint distance only when the endpoint contract is reached; never defaults to zero |
| `track_coverage_fraction` | directed traversed polyline arc-length fraction under the frozen proximity/continuity rules |
| `tracking_error_peak_count` | the current prominence-based local-error peak count under an explicit name |
| `crash_constraint` | deterministic bool/reason derived from source status plus the frozen altitude-collapse rule |
| `instability_constraint` | deterministic bool/reason derived from the frozen kinematic/control rules |
| `pass` | derived by the acceptance policy from verified metrics/constraints; not supplied as a measurement |

The UI may continue to label `tracking_error_peak_count` as “Overshoot count” only
with a compatibility warning. A true overshoot metric requires a signed reference
signal, response channel, crossing definition, settling band, and event-merging
rule; otherwise the term is misleading.

Evaluation-window fallback is also closed:

- `offboard_timing_verified` is preferred;
- a telemetry-derived interval may be accepted only when it meets the same
  pre-registered entry/exit and coverage constraints;
- `altitude_only` is diagnostic unless the experiment contract explicitly approved
  it before the campaign;
- `all_samples_fallback` is never eligible for Harness objective evidence.

Metrics are stored at verifier precision. Rounding belongs to API/UI rendering and
does not rewrite evidence. Seed-level distributions, effective sample size,
quantiles, and intervals are reported separately; DroneDream does not claim that
simulation repeatability is physical-world measurement uncertainty.

#### 8.6.3 Raw metric extensions

`raw_metric_json` is not an implicit objective namespace. A numeric key cannot become
optimizer input merely because it is finite. Extensions must be registered with a
metric ID, unit, formula/verifier revision, allowed source, range, missing-data
policy, and optimizer compatibility. Unknown keys remain diagnostic and are omitted
from both `OptimizerDatasetSnapshot` and provider evidence.

Persisted rates outside `[0, 1]`, counts inconsistent with the frozen matrix, or a
metric/unit/frame revision mismatch are integrity errors. They are never clamped,
defaulted, or silently recomputed under the latest policy.

### 8.7 Infrastructure exclusion and exact retry

Infrastructure health and candidate quality are two separate products:

- `OptimizerDatasetSnapshot` contains verified objective values, domain constraints,
  and explicitly supported censored observations;
- `EvidenceSnapshot.failure_summary` gives bounded aggregate infrastructure health
  by stage/code but does not attach infrastructure failures to parameter vectors;
- circuit breakers and pause policy consume infrastructure health;
- candidate ranking, surrogate fitting, tool attribution, and acceptance do not.

An infrastructure retry reuses the exact Trial, Candidate, seed, scenario, input
hash, Runtime slot class, and metric contract. It creates a new immutable physical
attempt with a new attempt fence. It does not create an apparently independent
Candidate observation. At most one physical attempt is accepted for a logical Trial.

After the bounded retry budget:

- the Candidate remains incomplete and cannot be ranked or published;
- the generation pauses/fails with an infrastructure reason rather than assigning a
  bad objective value;
- a confirmatory evaluation records this as arm-level non-success under the frozen
  intention-to-run rule, separately from conditional performance of completed
  campaigns.

Genuine domain failures stay in the paired seed/case matrix as typed constraints.
They are not dropped simply because they lack ordinary objective values. A proposal
tool that cannot consume constraints/censoring is ineligible whenever those records
are present; the adapter may not manufacture a large finite loss unless that
transformation is explicitly pre-registered and evaluated as a distinct tool.

### 8.8 Three-way scenario isolation

The current `holdout=true` cases are operationally a **validation suite** because
every Candidate is dispatched against them and publishability checks the result.
Renaming alone is insufficient; dispatch and database access must change.

Harness scenarios have three disjoint roles:

| Role | May influence model/tools? | When materialized | Purpose |
| --- | --- | --- | --- |
| `search` | yes | throughout optimization | fit optimizers and choose proposals |
| `validation` | yes, through typed aggregate only | at frozen promotion checkpoints | tune stopping/promotion policy without spending final test |
| `final_test` | no | only after one winner and all policies are frozen | one confirmatory verdict |

The final-test case definitions, seeds, and outcomes are absent from model snapshots,
optimizer datasets, tool processes, ordinary Candidate rows, and pre-freeze events.
The Trial rows do not exist before winner freeze. A narrow final-verification service
materializes them from a sealed contract after atomically recording:

- winning Candidate hash;
- search/validation evidence hashes;
- stopping/promotion/compiler/policy versions;
- remaining final-test budget;
- `winner_frozen_at` and final-test contract commitment.

Only the frozen Candidate is tested. If it fails, the campaign reports final-test
failure. DroneDream must not test the next-best Candidate against the same final set,
change thresholds, or resume search after seeing the outcome. Any revised design is
a new campaign with a new sealed final-test contract.

Repeated use of a test set to guide hyperparameter choices leaks information and
creates optimistic selection bias; this is the same structural problem described by
[Google's training/validation/test guidance](https://developers.google.com/machine-learning/crash-course/overfitting/dividing-datasets)
and the
[scikit-learn nested-validation example](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).
The analogy applies directly: controller parameter vectors and Harness policies are
the selected hyperparameters, and scenario/seed outcomes are the evaluation data.

### 8.9 Randomness, seed effect, and repeatability

A seed is not evidence that a stochastic component used that seed. The current code
demonstrates the distinction:

- `real_cli.py` exports `DRONEDREAM_TRIAL_SEED`;
- `px4_gazebo_runner.py` validates it and forwards `PX4_TRIAL_SEED`;
- deterministic dry-run telemetry uses `random.Random(seed)`;
- the bundled `local_px4_launch_wrapper.py` never reads `PX4_TRIAL_SEED`, does not
  launch Gazebo with `gz sim --seed`, and emits no seed-effect readback; and
- the bundled scenario-effect capability contract can physically apply only static
  obstacles. Wind, gust, sensor noise/degradation, probabilistic GPS dropout,
  battery state/sag, payload mass, and actuator delay fail closed as
  `requires_runtime_extension`.

Consequently, current real PX4/Gazebo Trials may record an intended seed but must not
claim that the seed controls physics, wind, sensor noise, PX4 scheduling, or the
offboard executor. An environment variable inherited by a child process is only
transport evidence.

#### 8.9.1 Closed randomness domains

Harness Version 1 uses separate, named domains rather than passing one integer to every
component:

| Domain | What it may control | May be shared across Candidate arms? |
| --- | --- | --- |
| `campaign.schedule` | blocked run-order randomization | yes, as a frozen schedule |
| `orchestrator.policy` | deterministic portfolio tie-breaking/exploration | no |
| `tool.<tool_id>.proposal` | optimizer initialization and proposal sampling | no |
| `scenario.case` | identity of a search/validation/final-test replicate | yes |
| `simulator.physics` | Gazebo global physics/random stream | yes, within a declared common-random-number block |
| `scenario.wind` | wind/gust stochastic process | yes, if effect binding is verified |
| `sensor.<sensor_id>.noise` | model/SDF/plugin noise stream | yes, if the plugin proves control |
| `scenario.dropout` | precomputed dropout event schedule | yes |
| `executor.schedule` | any intentionally randomized waypoint/timing schedule | yes |

No component may consume another domain's seed. In particular, a numerical optimizer
must not inherit the scenario seed, and a physical retry must not advance a proposal
generator.

`SeedDerivationManifestV1` stores a 128-bit campaign entropy value and derives children
with a frozen domain-separated algorithm:

```text
child_seed_256 =
  SHA-256(
    "DroneDreamSeed/v1\0" ||
    uint128_be(campaign_entropy) ||
    lp_utf8(domain_name) ||
    lp_bytes(scenario_instance_sha256) ||
    uint64_be(replicate_index)
  )
```

`lp_*` means an unsigned big-endian length followed by exact bytes. Each adapter
declares how many leading bits it consumes and the legal integer encoding. The
manifest records the full 256-bit result, delivered value, adapter/version, target
component, and derivation input hashes. Names, encodings, and truncation are part of
the signed Harness runtime manifest. This follows the same design purpose as NumPy's
official `SeedSequence` guidance—reproducibly deriving separate, very probably
non-overlapping child streams—without making DroneDream's cross-language contract
depend on an unstated library default:
[NumPy parallel random generation](https://numpy.org/doc/stable/reference/random/parallel.html).

Candidate identity is deliberately absent from physical scenario domains when a
campaign uses common random numbers. The same scenario replicate can then expose
different parameter vectors to a matched disturbance realization. Candidate identity
is present in tool-proposal domains so two tools cannot accidentally share optimizer
state. Retry/attempt identity is absent from the intended physical substreams: an exact
retry requests the same treatment, while the immutable attempt row separately records
the new execution and any uncontrolled variation.

#### 8.9.2 Seed-binding evidence

Every component reports one of these capability states:

| State | Meaning |
| --- | --- |
| `verified_bound` | exact derived seed was set before initialization and independently read back or attested |
| `configured_unverified` | a seed input was supplied, but effective use cannot be proved |
| `not_seedable` | versioned component has no supported seed control |
| `nondeterministic_uncontrolled` | relevant randomness/timing remains outside the contract |
| `not_stochastic` | component and selected configuration have no declared stochastic behavior |

`verified_bound` requires more than process environment capture. The evidence envelope
must bind the component binary/image digest, configuration/SDF/plugin hashes, exact
seed adapter, pre-initialization command or API acknowledgement, bounded readback/log
artifact, and observed component/version. For Gazebo versions that support it, the
server command uses the official `gz sim --seed <value>` option; the Gazebo project
introduced that CLI specifically to set the simulator random generator and tests for
the startup acknowledgement:
[Gazebo Sim seed CLI change](https://github.com/gazebosim/gz-sim/pull/1618).

That acknowledgement proves only the Gazebo global seed path. It does not prove that a
site-specific sensor, wind, or failure plugin consumes that global stream. Each plugin
therefore needs its own versioned capability record and either a documented seed
inheritance contract plus regression test, or explicit seed/readback. Sensor SDF/model
bytes and world bytes are hashed because changing a noise distribution while retaining
the same integer is a different treatment.

Wind evidence is similarly physical rather than declarative. Gazebo's official
`WindEffects` system adds filtered, sinusoidal, and noise terms and publishes
ground-truth wind on `/world/{world_name}/wind_info`:
[Gazebo WindEffects API](https://gazebosim.org/api/sim/9/classgz_1_1sim_1_1systems_1_1WindEffects.html).
A supported adapter hashes the world/plugin configuration, sets the derived wind
stream before the server starts, and retains bounded `wind_info` observations across
the evaluation interval. A service acknowledgement that merely changed a requested
mean is insufficient when the stochastic realization itself matters.

Probabilistic dropout is compiled into a finite event schedule before simulation where
possible. The compiler uses `scenario.dropout`, persists the schedule hash and event
count, and the runtime reports applied event identities/times. This is stronger and
easier to audit than asking a mutable plugin to hide an unobservable Bernoulli stream.
If a plugin must generate events internally, its seed binding and applied-event log
are mandatory.

#### 8.9.3 Time and host effects

`PX4_SIM_SPEED_FACTOR` controls intended simulation speed, not randomness or fidelity.
PX4's Gazebo documentation states that host I/O/CPU can limit achieved speed and that
the bridge synchronizes PX4 time to Gazebo simulation steps:
[PX4 Gazebo simulation speed and synchronization](https://docs.px4.io/v1.17/en/sim_gazebo_gz/index#change-simulation-speed).
The Trial therefore records:

- requested speed factor;
- Gazebo simulation start/end time and iteration count;
- wall-clock start/end time and achieved real-time factor;
- maximum/quantiles of simulation-step and telemetry gaps;
- pause/reset/time-jump observations;
- Runtime slot, host/WSL kernel, CPU model, logical-core count, memory pressure class,
  and renderer/headless mode;
- executor monotonic-clock and PX4/Gazebo time-base mappings.

Host load and process scheduling are nuisance factors even in synchronized simulation.
They are blocked/randomized and analyzed, not mislabeled as a seeded disturbance.
NIST's experimental-design guidance treats known nuisance variation through blocking
and randomizes within blocks:
[NIST randomized blocking](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3333.htm).

#### 8.9.4 Repeatability classes and gates

Each accepted attempt receives the lowest applicable class:

1. `artifact_replay_exact`: retained source bytes reproduce the canonical telemetry,
   metrics, outcome, and envelope hashes under the pinned verifier;
2. `rerun_bitwise`: an independently launched treatment reproduces all declared raw
   stochastic artifacts byte-for-byte;
3. `rerun_metric_tolerance`: repeated treatments satisfy pre-registered per-metric and
   trajectory tolerances;
4. `statistical_repeatable`: replicate distributions satisfy a frozen equivalence or
   variance contract, but individual trajectories differ;
5. `uncontrolled`: at least one outcome-relevant randomness/time source is unbound.

These are not interchangeable. Artifact replay can be exact even when a new physical
simulation is not. “Same seed” is prohibited in UI/report language unless all
outcome-relevant domains are `verified_bound` or `not_stochastic`. A campaign containing
`configured_unverified`, `not_seedable`, or `nondeterministic_uncontrolled` may still be
scientifically useful, but it must use replication, record the uncontrolled component
as a block/covariate where possible, and report the weaker class.

Common-random-number comparisons are allowed only when both arms have identical
scenario-instance, substream-manifest, component/version/configuration, and
seed-binding-evidence hashes. Otherwise the UI says “matched requested seed” or
“unmatched stochastic execution,” never “same disturbance.” A pre-release A/A suite
runs identical parameter vectors with same and different physical substreams across
supported host profiles, estimates within/between-seed variance, and verifies that
changing each declared seed domain has an observable effect. A seed input that never
changes its target evidence is treated as disconnected and blocks Harness release.

### 8.10 Objective, estimand, risk, and selection contract

The metric compiler answers “what was measured.” It does not by itself answer “what
quantity is being optimized.” Before a Job can call an LLM or numerical tool, DroneDream
must compile one immutable `OptimizationOutcomeContractV1`. That contract defines the
estimand, hierarchy of randomness, treatment of non-success, objective representation,
constraint authority, normalization, and final selection rule. The same compiled bytes
must drive aggregation, tool adapters, Pareto views, acceptance, reports, replay, and the
sealed final verifier.

This separation follows the structure used in risk-aware optimization. Cakmak et al.
write the uncertain response as \(F(x,W)\), where \(x\) is the design and \(W\) is an
environmental random variable, and optimize a declared risk measure of that response
rather than silently replacing \(W\) with an arbitrary completed-run average:
[Bayesian Optimization of Risk Measures](https://proceedings.neurips.cc/paper/2020/hash/e8f2779682fd11fa2067beffc27a9192-Abstract.html).
For DroneDream, \(x\) is the compiled PX4 parameter vector; scenario case, physical
substream, repeat, runtime block, and any supported fidelity are named dimensions of
\(W\). NIST likewise treats repeated measurements nested within a higher-level factor
as a hierarchical structure with distinct sources of variation:
[NIST two-level nested design](https://www.itl.nist.gov/div898/handbook/mpc/section5/mpc5321.htm).
Flattening all rows first changes the question being answered.

#### 8.10.1 Baseline objective-pipeline audit

The following table captured the advanced path before Outcome Contract V1 and
Selection Key 1.0. Addressed rows are retained as regression requirements; the
remaining rows continue to define the next contract revisions:

| Current behavior | Why it is insufficient |
| --- | --- |
| `ObjectiveSpec` validates finite positive weights/scales and unique objective names | names are still free strings; a raw adapter number becomes an objective without a registered unit, direction, provenance, valid range, or dependency declaration |
| the UI emits fixed normalizations `1`, `10`, `5`, and `1` for RMSE, completion time, overshoot count, and pass flag | these are undocumented scale constants, not a versioned physical or statistical contract; changing track duration or scenario suite changes their meaning |
| one global `robust_aggregation` is applied to every objective | RMSE, binary pass, duration, energy, and worst excursion need not share the same estimand or risk operator |
| result constraints always use the worst completed sample | this ignores configured scenario weights and cannot express a universal safety assertion, a chance constraint, a case-level threshold, and an aspiration target as different policies |
| completed seed rows were flattened and received `case_weight / dispatched_seed_count` | Outcome Contract compiler 1.2 now applies the declared within-case estimator to usable replicates and then applies each case's full frozen weight across the suite; a dispatched case with no usable metric fails scalar objective construction instead of renormalizing surviving cases |
| `failed_trial` is added as a weighted rate penalty | the coefficient is not derived from the objective unit or a declared composite outcome, so changing it changes the optimization problem |
| the prior path added `1_000_000 + 1_000 × total_violation` for hard infeasibility | replaced by Selection Key 1.0; this row remains as the regression that the new contract must never reintroduce |
| violation is divided by `max(1, abs(threshold))` | thresholds below one use absolute units while larger thresholds use relative units; a zero threshold silently selects a scale of one |
| the prior `constraint_values` map was keyed only by metric name | replaced by full metric/operator/threshold IDs so multiple bounds retain separate observations |
| `target` creates a one-sided hinge and zero loss after the aspiration is met | this is valid only if satisficing is intended; otherwise distinct Pareto-superior candidates become tied with no declared secondary rule |
| constrained MOBO, multi-fidelity MOBO, TuRBO, and the SAAS-inspired tool previously mixed objective-vector EI with derivative scalar-loss EI | Outcome Contract compiler 1.1 selects exactly one representation per call: complete joint objective vectors for Bayesian multi-objective acquisition, declared scalar loss as its fallback, and scalar loss only for TuRBO/CMA-family state |
| Bayesian objective utilities previously rescaled each metric by its observed min/max span | Outcome Contract compiler 1.6 passes the frozen Job normalization scale into every production Bayesian vector model; observed extrema no longer change relative objective scale |
| random scalarizations previously ignored the user's configured weights | Outcome Contract compiler 1.6 uses one fixed configured weight vector for production Bayesian acquisition; requests without a Job preference contract retain an explicitly labeled deterministic benchmark fallback only |
| CMA-family tools consume only scalar loss | the same Job therefore means a Pareto-vector problem to one tool and a weighted single-objective problem to another |
| optimizer feasibility additionally requires `failure_rate < 0.5` | the threshold remains a compatibility policy, but is now one named constant serialized into Outcome Contract V1 rather than four hidden literals |
| acceptance previously read rounded compatibility RMSE and max-error fields | Outcome Contract compiler 1.3 adds one versioned unrounded promotion projection: hierarchical fixed-suite mean RMSE, worst usable-seed max error, and dispatched-seed case-weighted pass/completion rates |
| holdout promotion requires every holdout Trial to complete and pass | this can be a defensible release rule, but it is currently separate from `min_pass_rate`, objective constraints, and the reported estimand |
| a derived `score` may be selected with any of its component metrics | without a metric-dependency graph, RMSE, duration, failure terms, and their composite can be counted twice |

The problem is not merely that some constants are imperfect. There are currently
several different optimization problems: the UI profile, robust evaluator, public
`aggregated_score`, each numerical adapter, acceptance evaluator, holdout gate, and
report. A Harness cannot reason reliably when “better” changes at each boundary.

#### 8.10.2 `OptimizationOutcomeContractV1`

The source request is compiled into canonical JSON with at least:

```json
{
  "schema": "dronedream.optimization-outcome/v1",
  "contract_id": "content-addressed-id",
  "metric_registry_digest": "sha256:...",
  "metric_dependency_graph_digest": "sha256:...",
  "scenario_population": {
    "case_semantics": "fixed_suite",
    "case_weight_semantics": "decision_priority",
    "weight_normalization": "sum_to_one_decimal",
    "replicate_semantics": "random_within_case",
    "runtime_block_policy": "blocked_not_pooled"
  },
  "objectives": [
    {
      "objective_id": "tracking_rmse_risk",
      "metric_id": "track.rmse.euclidean_neu.v1",
      "direction": "minimize",
      "unit": "m",
      "within_case_estimator": {
        "kind": "mean",
        "missing_policy": "not_imputed"
      },
      "across_case_estimator": {
        "kind": "priority_weighted_mean"
      },
      "preference": {
        "kind": "aspiration_deviation",
        "target_decimal": "0.500",
        "scale": {
          "kind": "fixed_meaningful_difference",
          "value_decimal": "0.250",
          "unit": "m"
        },
        "weight_decimal": "1.0"
      },
      "minimum_evidence": {
        "required_cases": "all",
        "replicates_per_case": 3
      }
    }
  ],
  "outcome_constraints": [],
  "domain_failure_contract": {},
  "selection_policy": {
    "representation": "scalar_preference",
    "precedence": [
      "evidence_complete",
      "hard_feasible",
      "domain_reliability",
      "preference_loss",
      "stable_tiebreak"
    ]
  },
  "final_promotion_policy": {},
  "compiler_revision": "..."
}
```

The example is illustrative, not a default recommendation. Its important property is
that every transformation is named, typed, unit-bearing, versioned, and frozen before
the first proposal. Decimal strings are compiled to exact fixed-scale integers or
rationals. Binary float is an execution encoding, not the canonical identity of a
weight, threshold, target, or scale.

`case_semantics` must be one of:

- `fixed_suite`: conclusions apply only to the named cases; weights express decision
  priority and cannot be described as real-world probabilities;
- `sampled_population`: cases are sampled from a versioned population/distribution;
  weights are probability or importance weights with a recorded sampling design; or
- `adversarial_suite`: cases are specifications to survive, normally combined by
  maximum, lexicographic limits, or coverage rules rather than a probability mean.

One weight field cannot simultaneously mean probability, UI importance, inverse
sampling probability, and safety criticality. The compiler rejects an unspecified
meaning.

#### 8.10.3 Registered metric algebra

Every objective and result constraint references a `MetricDefinitionV1`, not a free
JSON key. The definition contains:

- stable metric ID and revision;
- quantity kind, canonical unit, direction, valid numerical domain, and precision;
- trusted compiler output field and source-evidence requirements;
- whether the metric is per Trial, per case, per Candidate, or campaign-level;
- whether higher/lower is physically meaningful across its entire domain;
- allowed transforms and risk estimators;
- parent metric IDs and exact derivation expression;
- monotonicity and overlap annotations; and
- whether the metric is permitted for optimization, reporting only, hard outcome
  constraints, or final verification.

The dependency graph is a directed acyclic graph. A compiler rejects a preference
function that includes both a composite and an ancestor unless the author explicitly
declares and signs intentional overlap. For example, a legacy `score` derived from
RMSE, maximum error, completion time, crash, timeout, instability, and failure rate
cannot silently coexist with those components. The same rule detects aliases such as
`failure_rate` and `failed_trial_rate`.

An adapter-provided extension is first registered with a schema, unit, bounds,
extractor/verifier revision, test vectors, and collision-resistant namespace. A finite
number inside `raw_metric_json` is report data until that registration exists; it is
never promoted to an optimization objective merely because the client supplied its
name.

#### 8.10.4 Hierarchical scenario and replicate estimand

For Candidate \(x\), metric \(m\), case \(c\), and accepted replicate \(r\), retain the
atomic observation \(Y_{m,c,r}(x)\). Aggregation is explicitly nested:

```text
case_value[m, c, x] =
  WithinCaseEstimator_m({Y[m, c, r, x] : accepted domain outcomes})

candidate_value[m, x] =
  AcrossCaseEstimator_m({
    case_id,
    case_value[m, c, x],
    configured_case_weight[c],
    case_evidence_state[c]
  })
```

The within-case estimator describes stochastic repeatability under one case. The
across-case estimator describes the population or decision suite. Mean-over-all-rows
is legal only when the contract proves that rows are exchangeable and their sampling
probabilities justify it. Different seed counts must not accidentally change case
importance.

Runtime blocks remain a third dimension. They are used for pairing, nuisance adjustment,
or variance reporting; they do not become extra “good” observations. The evidence
bundle reports within-case dispersion, between-case dispersion, block effects, effective
sample size, and missingness separately. NIST's DOE glossary emphasizes that replication
estimates random error and that nested factors have a hierarchical relationship:
[NIST DOE terminology](https://www.itl.nist.gov/div898/handbook/pri/section7/pri7.htm).

For Version 1, DroneDream supports a conservative, small set of combinations:

| Within case | Across cases | Permitted meaning |
| --- | --- | --- |
| mean | fixed priority-weighted mean | average repeat behavior over a fixed decision suite |
| upper/lower tail CVaR | fixed priority-weighted mean | tail sensitivity within each declared case |
| mean | worst case | expected repeat behavior of the weakest named case |
| maximum/minimum | worst case | observed universal stress gate; report sample coverage, never population guarantee |
| binary rate plus confidence bound | all-case threshold or worst case | domain failure/pass chance contract |

Arbitrary “CVaR over all case/seed rows” is not enabled in Version 1 because it mixes
two uncertainty sources and makes its probability measure depend on UI weights.

#### 8.10.5 Non-success, missing metrics, and censoring

An absent metric is not zero, infinity, a bad score, or a row to drop without a trace.
The closed Trial taxonomy from Section 8.4 determines one of three statistical paths:

1. **accepted domain outcome**: all required metric evidence is present and may enter
   the declared estimand;
2. **domain non-success**: the treatment genuinely crashed, violated a boundary, timed
   out under a domain deadline, or otherwise produced a pre-registered product outcome;
   it enters the domain reliability/constraint contract; or
3. **infrastructure, evidence, cancellation, or supersession outcome**: it is not a
   sample of controller quality and cannot enter objective or domain-failure estimates.

For each domain non-success the contract chooses one policy before execution:

- `separate_chance_constraint`: optimize observed performance among valid metric
  outcomes while separately requiring an upper confidence bound on domain-failure
  probability;
- `composite_bounded_loss`: assign a pre-registered, unitless terminal loss that is
  semantically part of the product objective, not an emergency implementation constant;
  or
- `metric_censored`: preserve a censoring bound and use only a tool whose signed adapter
  declares support for that censoring type.

Version 1 permits the first two and disables `metric_censored` for all six existing
numerical tools. It never converts infrastructure failure into product failure. If a
case lacks the minimum accepted evidence after bounded exact retries, the Candidate is
`EVIDENCE_INCOMPLETE` and cannot be ranked, even if its surviving Trials look excellent.

The metric estimand and reliability estimand are always reported together. “RMSE 0.31 m”
must state whether it is conditional on a 100%, 90%, or unknown domain-completion rate.
This prevents survivor bias from making fragile candidates look precise.

#### 8.10.6 Risk estimators and finite-sample evidence

`mean`, `worst`, `percentile`, and `CVaR` are different claims. The contract records:

- tail orientation after objective direction is applied;
- whether `alpha` means retained tail mass or quantile confidence level;
- weighted empirical-distribution semantics;
- ordering/tie/atom behavior;
- minimum case and replicate counts;
- effective tail mass and effective sample size;
- estimator revision and numerical precision; and
- uncertainty interval or an explicit `insufficient_evidence` state.

DroneDream names the field `tail_mass_decimal` for the fraction averaged in the bad
tail. It does not expose an ambiguous `cvar_alpha`. For a minimizing loss, tail mass
`0.20` means average the worst upper 20% of the declared distribution. The empirical
estimator admits fractional mass at the boundary so probability atoms are handled
deterministically. Rockafellar notes that CVaR/superquantile tail definitions require
care around an atom at the quantile boundary:
[Coherent Approaches to Risk in Optimization Under Uncertainty](https://sites.math.washington.edu/~rtr/papers/rtr206-RiskTutorial_INFORMS2007.pdf).

A one-observation “worst 20% CVaR” may be numerically defined but is not strong tail
evidence. The compiler therefore requires:

```text
effective_tail_observations =
  tail_mass × Kish_effective_sample_size

effective_tail_observations >= policy.minimum_effective_tail_observations
```

The default release policy requires at least three effective tail observations for an
optimization risk estimate and more for any public statistical claim; exact thresholds
are chosen by the pre-registered campaign, not inferred from observed results. Binary
pass/failure constraints use an exact or validated Wilson/Clopper-Pearson bound rather
than a bare point rate when sample sizes are small. NIST documents these interval
families for binary responses:
[NIST Technical Note 2119](https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2119.pdf).

Risk is computed at the evidence level before acquisition. A future risk-aware Bayesian
tool may instead model \(F(x,W)\) and propagate posterior uncertainty into the risk
measure, as described by Cakmak et al. and BoTorch's official risk-objective tutorial:
[BoTorch risk-averse optimization](https://botorch.org/docs/v0.15.1/tutorials/risk_averse_bo_with_input_perturbations/).
Such a tool needs a new adapter contract; it must not be substituted behind the same
tool revision.

Multi-objective robustness is not equivalent to applying scalar CVaR after the fact.
Daulton et al. formulate a multivariate value-at-risk target for uncertain objectives
and use a specifically derived random-scalarization method:
[Robust Multi-Objective Bayesian Optimization Under Input Noise](https://proceedings.mlr.press/v162/daulton22a.html).
DroneDream therefore does not label a scalar-risk wrapper around the current
multi-objective adapter “robust MOBO.” It must either expose the registered scalar
preference honestly or implement and evaluate a separate multivariate-risk tool.

#### 8.10.7 Constraint classes and deterministic precedence

DroneDream separates:

1. **parameter constraints**: executable restrictions on \(x\), compiled and enforced
   before dispatch by Section 12;
2. **evidence constraints**: minimum coverage, integrity, and precision required before
   an outcome is comparable;
3. **domain outcome constraints**: expensive observed quantities such as crash
   probability, maximum excursion, or pass probability;
4. **resource constraints**: budget, wall time, fidelity, and capacity; and
5. **promotion constraints**: independent validation/final-test conditions.

This matches BoTorch's official distinction between parameter constraints, which
restrict generated inputs, and outcome constraints, which are modeled black-box
outputs:
[BoTorch constraints](https://botorch.org/docs/constraints).

Each outcome constraint has a stable `constraint_id`; metric/unit; operator; threshold;
within/across-case estimator; confidence-bound direction; evidence minimum; severity
tier; and scale for ordering violations. A satisfied constraint remains present with
its signed margin. Multiple constraints on one metric remain distinct.

Hard ordering is lexicographic, never simulated by a large additive constant:

```text
rank_key(candidate) = (
  evidence_rank,             # complete before incomplete
  hard_feasibility_rank,     # feasible before infeasible
  violated_severity_tier,    # safety before performance
  normalized_violation_vector,
  domain_reliability_rank,
  preference_or_pareto_rank,
  uncertainty_rank,
  stable_candidate_digest
)
```

Only candidates in the same preceding tier are compared by the next field. Soft
constraints may enter a declared preference function, but their dimensionless
violation scale is explicit—meaningful tolerance, fixed standard, or pre-registered
engineering range—not `max(1, abs(threshold))`.

For probabilistic outcome constraints, acquisition may multiply positive utility by a
modeled probability of feasibility only when the adapter documents the model and
independence/correlation treatment. Gardner et al. formulate constrained BO by placing
models on both objective and constraint functions:
[Bayesian Optimization with Inequality Constraints](https://proceedings.mlr.press/v32/gardner14.html).
The deterministic Candidate promotion gate still evaluates observed evidence; a
surrogate probability never certifies safety.

#### 8.10.8 One objective representation per tool call

Every tool revision declares exactly one `objective_representation`:

| Representation | Tool receives | Permitted examples |
| --- | --- | --- |
| `scalar_preference` | one frozen dimensionless loss plus separate constraint/reliability evidence | CMA-ES, scalar TuRBO adapter |
| `objective_vector` | registered oriented objective vector, fixed transforms, outcome constraints, and Pareto/reference policy | constrained MOBO, qNParEGO-like adapter |
| `risk_function` | atomic \(F(x,W)\) evidence and a frozen risk functional | future risk-aware BO |
| `lexicographic_vector` | ordered tiers and per-tier quantities | deterministic selector or explicitly supporting optimizer |

A tool call never receives both `objective_vector` and a scalar loss derived from the
same metrics unless the scalar is a separately registered, non-overlapping outcome.
Outcome Contract compiler 1.1 removes the former 70/30 and 65/35 double use.
User preference weights belong
either in the scalar-preference compiler or in a documented Pareto recommendation
step—not in both.

BoTorch's official multi-objective documentation defines MOBO as learning the Pareto
front and describes qNParEGO as using a new random scalarization for each candidate:
[BoTorch multi-objective optimization](https://botorch.org/docs/v0.16.0/multi_objective).
The tutorial further notes that qNEHVI directly targets Pareto-front improvement while
qNParEGO relies on random scalarizations:
[BoTorch qEHVI/qNEHVI/qNParEGO tutorial](https://botorch.org/docs/v0.17.2/tutorials/multi_objective_bo).
Therefore an adapter must honestly say whether it searches a Pareto set, a user utility,
or a random family of utilities.

Initial tool bindings are:

- `surrogate_cma_es` and `bipop_cma_es`: `scalar_preference`;
- `turbo`: `scalar_preference` in Version 1 unless a separately reviewed multi-output
  implementation is registered;
- `constrained_mobo`: `objective_vector`, with no duplicate scalar-loss GP;
- `multi_fidelity_mobo`: `objective_vector` plus a physical fidelity/cost contract;
- current `saasbo`: either `scalar_preference`, or a renamed
  `sparse_axis_random_scalarized_mobo_approximation` tool with
  `objective_vector`; it cannot claim both; and
- `optimizer_portfolio`: child-specific representation, but rewards are converted by a
  common, frozen `PortfolioRewardContractV1` after comparable full-fidelity evidence.

The LLM does not alter these bindings. It chooses registered tools and budgets; the
server compiles the tool-specific view.

#### 8.10.9 Fixed transforms, targets, and Pareto references

Every objective transform is frozen from engineering meaning or development-only
calibration before the campaign:

- `identity_physical`: retain raw canonical units for a single objective;
- `fixed_meaningful_difference`: divide deviation by a pre-declared practically
  meaningful change in the same unit;
- `bounded_range`: map a physically meaningful fixed lower/upper range;
- `baseline_ratio` or `baseline_difference`: compare with a separately measured,
  frozen baseline estimate and carry its uncertainty; or
- `aspiration_deviation`: zero after a declared target, with an explicit secondary
  rule for ties.

Observed campaign min/max is prohibited as a preference scale because future evidence
would retroactively change every candidate's tradeoff. Model-standardization for
numerical conditioning is allowed inside an adapter, but it must be invertible,
fit only on allowed training evidence, recorded per generation, and not mistaken for
the product preference.

Pareto/hypervolume tools freeze objective orientation, reference-point policy, and
reference point before candidate selection. BoTorch states that an EHVI reference
point is the lower bound used for hypervolume and suggests domain knowledge or a
declared dynamic strategy:
[BoTorch multi-objective tutorial reference point](https://botorch.org/docs/v0.17.2/tutorials/multi_objective_bo#reference-point).
DroneDream Version 1 uses a fixed domain-informed reference point committed in the
outcome contract; any dynamic-reference experiment is a separate tool revision and
ablation.

Aspiration targets are not acceptance criteria by accident. The contract says whether
a target:

- merely shapes utility;
- defines hard feasibility;
- triggers early-stop eligibility;
- participates in validation promotion; or
- applies only in the sealed final test.

One threshold may fill several roles only through explicit shared references to the
same canonical quantity. Compatibility `target_rmse`, `target_max_error`, and
`min_pass_rate` columns become projections of the compiled contract, never independent
authorities.

#### 8.10.10 Candidate outcome envelope and replay

Aggregation emits `CandidateOutcomeEvidenceV1`:

```json
{
  "candidate_digest": "sha256:...",
  "outcome_contract_digest": "sha256:...",
  "evidence_role": "search",
  "checkpoint_digest": "sha256:...",
  "accepted_trial_attempt_hashes": ["sha256:..."],
  "case_results": [],
  "objective_results": [
    {
      "objective_id": "tracking_rmse_risk",
      "raw_value_decimal": "0.4312",
      "unit": "m",
      "oriented_value_decimal": "0.4312",
      "preference_value_decimal": "0",
      "evidence_state": "sufficient",
      "uncertainty": {}
    }
  ],
  "constraint_results": [],
  "domain_reliability": {},
  "selection_representation": {},
  "rank_key": {},
  "compiler_revision": "...",
  "canonical_sha256": "..."
}
```

The envelope preserves more precision than UI projections and includes all satisfied
and violated constraints. Ranking uses canonical values, not rounded display fields.
Reports render raw unit-bearing values, transformed preference values, uncertainty,
sample hierarchy, and non-success counts without implying that a weight is a physical
unit.

One envelope has exactly one `evidence_role`: `search`, `validation`, or
`final_test`, and one role-specific checkpoint/cell manifest. Search and validation
metrics are never pooled into one estimator merely because they belong to the same
Candidate. Proposal adapters consume only accepted search envelopes. The bounded
model snapshot may additionally expose a frozen validation-checkpoint projection
under an explicit validation role. A final-test envelope is produced only after
winner freeze and is terminal report evidence; it cannot enter ranking, routing
reward, another EvidenceSnapshot, or an optimizer dataset.

The model-visible `EvidenceSnapshot` receives a bounded derivative:

- objective values in raw units and the tool's declared representation;
- evidence sufficiency and uncertainty class;
- separate domain-reliability and infrastructure counts;
- constraint margins by stable ID;
- case-level summaries without hidden final-test material; and
- immutable outcome-contract and candidate-envelope hashes.

The LLM never receives a mutable formula string, unregistered raw metric, or a rounded
leaderboard score as the sole account of performance.

#### 8.10.11 Outcome-contract verification gates

Before Harness live dispatch, tests must prove:

1. permuting Trial, case, constraint, or objective order does not change canonical
   outcomes or rank;
2. duplicating seeds inside one case cannot change that case's configured population
   weight;
3. a missing/infrastructure Trial cannot improve a Candidate and cannot be relabeled
   as domain failure;
4. incomplete minimum evidence produces `EVIDENCE_INCOMPLETE`, not a finite rank;
5. satisfied and violated constraints survive replay under distinct stable IDs;
6. hard-feasible candidates always outrank hard-infeasible candidates for every finite
   objective magnitude;
7. display rounding cannot cross an acceptance or selection boundary;
8. metric aliases/composite ancestors cannot be double counted;
9. every tool consumes exactly its declared representation;
10. objective-vector tools receive no derived scalar preference duplicate;
11. scalar tools reproduce the exact fixed-scale preference compiler;
12. case/replicate nesting, tail orientation, atom handling, and effective tail count
    match golden vectors;
13. acceptance, validation promotion, Pareto view, report, and optimizer replay
    resolve the same outcome-contract digest;
14. search, validation, and final-test rows cannot be mixed into one envelope, and
    only search-role envelopes can train a proposal adapter or resolve online routing
    reward; and
15. changing any metric, scale, weight, estimator, missingness rule, threshold,
    reference point, or tie policy changes the digest and requires a new experiment.

### 8.11 Tool credit, exploration, and routing-policy evaluation

The outcome contract determines whether one evaluated Candidate is good. It does not
determine which proposal tool deserves credit for finding it, how much future budget
that tool should receive, or whether a new LLM routing policy is better than the policy
that generated the logs. Those are separate adaptive-decision problems. Combining them
in one informal `score` creates a self-confirming loop: early noise changes allocation,
allocation changes which actions receive evidence, and the resulting selective evidence
is then presented as proof that the allocation was correct.

Portfolio methods are legitimate when their reward and feedback assumptions match the
implementation. The GP-Hedge work explicitly frames acquisition-function selection as
a hierarchical bandit portfolio:
[Portfolio Allocation for Bayesian Optimization](https://www.ora.ox.ac.uk/objects/uuid%3A8ab87685-4c62-4daf-9f1f-e59366cc4fa3).
DroneDream's six children are more heterogeneous than acquisition functions sharing one
GP: they have different cold starts, internal state, batch semantics, fidelity support,
failure modes, and computational costs. The design therefore does not borrow the word
“UCB” or “Hedge” as assurance. It records the exact reward process and evaluates the
complete routing policy.

#### 8.11.1 Current portfolio and credit audit

The current deterministic portfolio is useful as a baseline, but its allocation score
is an engineering heuristic:

| Current behavior | Harness risk |
| --- | --- |
| ownership is inferred from `optimizer_strategy` string equality/suffix/substrings and the first matching child wins | renamed/composite strategies can be misattributed; relational multi-source provenance is not the reward identity |
| reward eligibility defaults from optimizer metadata and excludes only named Halton fallback | a stale/mutated metadata envelope can change credit; seeded-random fallback and future fallbacks need a closed source-role policy |
| “comparable” means completed, requested full fidelity, metadata-eligible | accepted evidence, effective fidelity, scenario coverage, outcome-contract hash, validation role, and application/verifier integrity are not part of comparability |
| feasibility requires `feasible` and `failure_rate < 0.5` | the compatibility boundary is now one named constant sealed into Outcome Contract V1; calibration and cost-sensitive replacement remain future work |
| one best loss per generation is retained | discards batch cost, allocation count, uncertainty, failures, and non-best contributions; larger batches get more chances to win |
| the common baseline is the earliest generation's best loss among all matching observations | it is not a randomized/common Candidate evaluated under every tool; tools entering later inherit a selectively improved baseline |
| improvement is divided by `max(abs(baseline), abs(best))` | the reward scale changes with observed outcomes and may not represent a meaningful engineering difference |
| “recent” means the second half of a tool's observed generations | calendar/generation delay, unequal exposure, restarts, and regime changes are conflated |
| the score uses coefficients `1.7`, `1.1`, `0.25`, `0.65`, and cold-start `0.35` | these are unregistered product choices, not calibrated bandit confidence bounds |
| exploration denominator counts eligible Candidate observations while improvement keeps one best per generation | the exposure unit and reward unit do not match |
| lower-fidelity observations are excluded from allocation statistics | screening value, promotion quality, and cost savings are not credited despite a comment implying a safety signal |
| a duplicate projected vector keeps only one source; higher requested fidelity can replace the earlier proposal | credit depends on iteration and replacement order; agreement between tools is lost |
| a projected child proposal remains child-owned | a materially changed vector could reward a tool for a Candidate it did not propose |
| an unavailable child receives an ineligible fallback and remains at zero eligible observations | cold-start coverage can repeatedly spend slots on a broken tool unless availability is a separate state |
| spare capacity is assigned to the highest heuristic score but filled by reward-ineligible fallback | planned allocation, actual source, incurred cost, and observed reward diverge |

These facts do not make the current portfolio unusable. They mean its output must be
reported as `deterministic_portfolio_heuristic_vCurrent`, not as a statistically
calibrated UCB policy. It remains a baseline until the following contracts exist.

#### 8.11.2 Three ledgers, not one score

Version 1 separates:

1. **proposal provenance**: which exact tool-call outputs independently contained the
   accepted exact Candidate before the batch gate;
2. **online routing feedback**: the frozen rule that converts completed search evidence
   and incurred cost into future policy state; and
3. **policy evaluation evidence**: an end-to-end campaign comparing frozen routing
   policies under equal budgets and independent problem replicates.

Proposal provenance is factual; online reward is a product policy; campaign performance
is the scientific endpoint. A provenance share is not automatically a causal
contribution, an online reward is not an unbiased estimate of a tool's counterfactual
value, and a policy's own adaptive history is not a matched comparison against another
policy.

#### 8.11.3 Immutable routing opportunity and action

Before allocation, persist a `RoutingOpportunityV1`:

```json
{
  "schema": "dronedream.routing-opportunity/v1",
  "job_id_hash": "support-reference",
  "generation_index": 7,
  "state_version": 31,
  "model_evidence_snapshot_hash": "sha256:...",
  "optimizer_dataset_snapshot_hash": "sha256:...",
  "outcome_contract_hash": "sha256:...",
  "tool_registry_hash": "sha256:...",
  "eligible_actions": [
    {
      "tool_id": "optimizer.propose_turbo",
      "tool_version": "1.0.0",
      "objective_adapter_hash": "sha256:...",
      "availability": "eligible",
      "maximum_allocation": 4,
      "cost_upper_bound": {
        "proposal_cpu_ms": 5000,
        "full_trial_slots": 4
      }
    }
  ],
  "policy_reserved_allocation": {},
  "discretionary_capacity": 4,
  "routing_policy_id": "llm-harness-v1",
  "routing_policy_revision": "sha256:..."
}
```

The action is the accepted `CompiledGenerationPlan` plus the model-attempt and
deterministic-policy provenance already defined. Action identity includes tool and
adapter version, requested/effective fidelity policy, allocation count, slot role,
objective representation, and cost ceiling. “TuRBO” alone is not an action when any of
those differ.

Availability is closed and independent of reward:

- `eligible`;
- `cold_start_eligible`;
- `temporarily_unavailable` with retry deadline;
- `circuit_open`;
- `incompatible_outcome_contract`;
- `insufficient_evidence`;
- `disabled_by_kill_switch`; or
- `retired`.

A tool with import, containment, capability, manifest, or repeated typed failures opens
a versioned circuit and stops consuming exploration slots. It does not remain “untried”
merely because its fallback results were reward-ineligible. Recovery occurs through a
bounded health probe or operator action, not a simulated Candidate.

#### 8.11.4 `PortfolioRewardContractV1`

The Job pins a reward contract before the first opportunity. The initial contract is
deliberately conservative:

```json
{
  "schema": "dronedream.portfolio-reward/v1",
  "source_outcome_contract_hash": "sha256:...",
  "eligible_evidence_role": "search",
  "reward_checkpoint": "candidate_search_envelope_complete",
  "attribution": "pre_outcome_equal_multi_source_share",
  "primary_endpoint": {
    "kind": "feasibility_first_incumbent_improvement",
    "meaningful_scale_hash": "sha256:..."
  },
  "cost_denominator": {
    "components": [
      "proposal_cpu_ms",
      "physical_trial_slots",
      "fidelity_equivalent_cost"
    ],
    "catalog_hash": "sha256:..."
  },
  "delay_policy": "credit_when_complete_no_retroactive_action_mutation",
  "duplicate_policy": "one_candidate_outcome_split_across_exact_sources",
  "bounds": {
    "minimum_decimal": "-1.000000",
    "maximum_decimal": "1.000000"
  }
}
```

Reward is derived only from an accepted `CandidateOutcomeEvidenceV1` under the same
outcome contract. Evidence-incomplete Candidates produce `pending` until a frozen
deadline and then `unobserved`, not zero quality. Infrastructure/evidence/cancellation
outcomes produce no parameter reward but retain incurred operational cost and
availability evidence. Domain infeasibility cannot earn positive objective-improvement
credit; feasibility transition and objective improvement are separate registered
components combined lexicographically or by a fixed bounded product policy.

The initial endpoint compares the Candidate with the incumbent that was frozen before
the opportunity. It does not use a future best result, the best member of an unequally
sized batch without correction, or an observed-value normalization. Improvement is
divided by the outcome contract's fixed meaningful-difference scale. All allocated
slots—including invalid proposals, duplicates, unavailable-tool calls, filtered
candidates, fallbacks, proposal compute, and physical evaluations—remain in the cost
ledger even when no positive reward is eligible.

Reward updates occur only at declared checkpoints. A late result can update future
routing state after its accepted evidence fence, but it cannot rewrite the action
probability, eligibility set, context, or plan that preceded it. Search outcomes may
inform routing. Validation can inform model/tool diagnostics only under a separately
frozen policy and never resume or retune a search campaign. Sealed final-test evidence
never becomes online reward.

#### 8.11.5 Multi-source duplicates and transformed proposals

Before outcomes are known, the batch gate groups exact parameter-lattice vector,
effective fidelity contract, scenario role, and outcome-contract hash. Every exact tool
source is retained. Credit shares are assigned by a frozen, order-independent rule:

```text
eligible_exact_sources = unique(
  tool_call_id,
  output_candidate_ordinal,
  exact_pre_gate_candidate_hash
)

source_share = 1 / count(eligible_exact_sources)
```

The deterministic primary source remains useful for display and foreign-key
compatibility, but does not receive all reward. If two calls from the same tool emit the
same Candidate, its duplicate calls do not multiply the tool's total share. A future
causal or Shapley-style scheme would require counterfactual evidence and is not claimed.

A material gate projection is rejected under Section 12. If a legacy compatibility
path changes a Candidate, the resulting Candidate records
`reward_eligible=false` for the original source because the evaluated treatment was not
its exact output. A higher-fidelity replacement does not erase the lower-fidelity
source; it creates an explicit promotion/replacement edge and distinct cost/outcome
eligibility. Tool iteration order never determines ownership.

#### 8.11.6 Exploration is product policy, not LLM discretion

The deterministic compiler partitions each generation:

- mandatory contract-coverage slots;
- policy-reserved exploration slots;
- recovery or validation-promotion slots;
- LLM-discretionary slots; and
- unused capacity when no safe eligible action exists.

The LLM may allocate only discretionary capacity. It cannot waive the minimum exposure,
maximum-share, circuit breaker, cooldown, cost, or fairness rules. Exploration uses a
schedule frozen for the Job and keyed to actual eligible opportunity exposure, not to
the absence of a positive reward. A newly enabled tool receives bounded coverage; a
broken tool does not receive endless cold starts. Every tool has a maximum rolling
allocation share so one early winner cannot monopolize evidence before the minimum
cross-tool coverage gate.

Version 1 does not perform online parameter learning of the routing policy. The model
receives bounded compiled performance summaries, but provider weights remain external
and fixed; the deterministic portfolio's reward state is versioned application data.
Changing the prompt, model binding, summary compiler, reward contract, exploration
schedule, or tool registry creates a new routing-policy revision and normally a new
evaluation arm.

#### 8.11.7 Logged probability and the off-policy boundary

Historical routing logs reveal outcomes only for executed actions. They do not reveal
what an unchosen optimizer would have proposed or how those unevaluated Candidates
would have performed. Contextual-bandit off-policy evaluation formalizes this selected
feedback problem. Wang, Agarwal, and Dudík show that IPS/DR estimation depends on the
logging and target policies and can have difficult finite-sample bias/variance
tradeoffs:
[Optimal and Adaptive Off-policy Evaluation in Contextual Bandits](https://www.microsoft.com/en-us/research/publication/optimal-adaptive-off-policy-evaluation-contextual-bandits/).
Dudík, Langford, and Li likewise distinguish reward-model bias from propensity-based
variance:
[Doubly Robust Policy Evaluation and Learning](https://www.microsoft.com/en-us/research/?p=580345).

DroneDream's setting is harder than a one-step contextual bandit because tools are
stateful, their actions are batches of new Candidate generators, rewards are delayed,
the context is changed by earlier actions, and the objective landscape differs by Job.
The project therefore adopts the following boundary:

- a logged exact action probability is stored only when DroneDream itself sampled from
  a fully enumerated, normalized randomized policy;
- LLM token probabilities, undocumented provider randomness, temperature, or repeated
  prompts are not action propensities;
- a deterministic route records probability one for the chosen action and zero
  elsewhere, which provides no off-policy support for alternatives;
- IPS, DR, SWITCH, or similar estimators are not reported unless action support,
  context/action identity, reward consistency, delay/censoring policy, and effective
  sample size pass a pre-registered validator;
- clipping or rejecting large importance weights and any reward model are declared
  parts of the estimator, with sensitivity and uncertainty; and
- unsupported historical logs can be used for replay, diagnostics, and hypothesis
  generation, not an unbiased counterfactual performance claim.

The default confirmatory comparison remains end-to-end blocked randomized campaigns
from Section 22. Offline policy evaluation is an optional later analysis, not a shortcut
around matched evaluation.

#### 8.11.8 Routing-policy evaluation unit

The primary routing endpoint belongs to the complete Job/campaign, not an individual
Candidate. Compare frozen policies on independent problem-instance × orchestration-
replicate units under equal:

- parameter/scenario/outcome contracts;
- simulator and provider budgets;
- initial designs and accepted common-random blocks where justified;
- Runtime/tool/model versions;
- infrastructure non-success rules; and
- stopping, promotion, and final-selection policies.

Report best feasible validation outcome at budget, feasibility and completion,
time-to-threshold, physical and fidelity-equivalent simulations, proposal compute,
provider cost, fallback/circuit rate, tool exposure, allocation entropy, and evidence
completeness. A policy that wins only by spending more, using larger batches, receiving
more valid tool availability, or selecting from more replicate noise is not better
under an equal-budget claim.

Candidate-level reward is useful for online allocation diagnostics, but inferential
uncertainty clusters by problem replicate and policy run. Generations, tools,
Candidates, duplicate sources, Trial seeds, and delayed reward rows are not independent
policy outcomes.

#### 8.11.9 Machine-checkable credit invariants

The reward compiler and routing ledger enforce:

1. every reward references one immutable opportunity, action, Candidate outcome
   envelope, outcome contract, reward contract, and cost ledger;
2. the incumbent comparison point predates the opportunity;
3. exact eligible source shares sum to one per Candidate, independent of tool order;
4. one tool cannot multiply credit by emitting duplicates;
5. rejected/materially transformed/fallback Candidates cannot receive positive
   proposal credit unless their source role explicitly allows it;
6. infrastructure/evidence/cancelled/superseded outcomes never become negative
   parameter-quality reward, but their operational cost and availability effect remain;
7. infeasible or evidence-incomplete Candidates never receive feasible-objective
   improvement credit;
8. final-test evidence cannot appear in a routing reward or context;
9. delayed reward cannot mutate its historical action, probability, eligible set, or
   context;
10. allocation exposure, produced candidates, accepted exact candidates, physical
    evaluations, completed outcome envelopes, and rewarded outcomes reconcile
    separately;
11. a circuit-open/incompatible tool consumes no exploration allocation;
12. a named bandit/OPE estimator is emitted only with its validated assumptions,
    support diagnostics, effective sample size, uncertainty, and estimator revision;
13. reward state is replayable from immutable envelopes and cost rows; and
14. changing any outcome, reward, exploration, attribution, availability, or OPE rule
    changes the routing-policy revision.

## 9. Tool registry

### 9.1 Registry record

Every tool is registered from trusted application code with:

```json
{
  "tool_id": "optimizer.propose_turbo",
  "tool_version": "1.0.0",
  "implementation_revision": "git:...",
  "description": "Propose a local trust-region batch when evidence suggests local progress.",
  "input_schema": {},
  "output_schema": {},
  "capabilities": {
    "constraints": true,
    "multi_objective": false,
    "multi_fidelity": false,
    "mixed_variables": false,
    "accepted_objective_representations": [
      "scalar_preference"
    ],
    "accepted_estimators": [
      "weighted_scenario_mean"
    ],
    "accepted_risk_measures": [
      "none"
    ],
    "observation_types": [
      "objective_observation",
      "constraint_observation"
    ],
    "right_censoring": "unsupported",
    "missing_objective_policy": "exclude_from_objective_fit",
    "pending_policy": "deduplicate_only"
  },
  "limits": {
    "min_batch": 1,
    "max_batch": 8,
    "max_dimension": 40,
    "timeout_ms": 5000
  },
  "effects": {
    "read_only": true,
    "side_effect_free": true,
    "idempotent": true,
    "parallel_safe": true,
    "open_world": false
  },
  "outcome_contract": {
    "schema_version": "1.0",
    "requires_registered_metrics": true,
    "requires_complete_candidate_outcome_envelope": true,
    "allows_observed_range_normalization": false,
    "allows_duplicate_scalar_and_vector_utility": false
  },
  "failure_policy": "return_typed_error"
}
```

MCP-compatible names, JSON Schemas, output schemas, and effect vocabulary are
useful, but DroneDream trusts only its local registry. A provider- or server-supplied
annotation is not a security decision.

The objective fields are executable compatibility claims, not documentation. A tool
that accepts `scalar_preference` cannot be called with an `objective_vector`; a tool
that accepts a scenario-weighted mean cannot silently flatten case-by-replicate rows;
and a tool that does not list a risk measure cannot receive a precomputed tail score
under a generic `loss` name. Registry eligibility is evaluated against the immutable
`OptimizationOutcomeContractV1` before the tool appears in the model-visible allowlist.
The adapter then receives exactly one objective representation and the matching
`CandidateOutcomeEvidenceV1` hashes. This prevents a wrapper from fitting both a
multi-objective vector and a scalar derived from that same vector, which would count
the same preference twice.

The official MCP Python SDK validates structured results against output schemas and
also supports client-only `_meta` that is not exposed to the model. DroneDream uses
the same separation even though Version 1 tools are internal, not remote MCP
servers: schema-valid does not imply model-visible, and private provenance never
becomes prompt content merely because it is JSON.

Source: [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

### 9.2 Initial proposal tools

| Tool ID | Best fit | Version 1 objective adapter | Current backend state requirement or behavior |
| --- | --- | --- | --- |
| `optimizer.propose_constrained_mobo` | constrained, multi-objective global search | registered Pareto vector plus separately registered outcome-constraint vector; no derivative scalar loss in the same fit | model-based after at least `max(4, 2d)` informative full-fidelity observations; otherwise deterministic cold start |
| `optimizer.propose_multi_fidelity_mobo` | expensive scenario matrices with staged fidelity | registered Pareto vector plus fidelity/cost coordinate and separately registered constraints; no scalar double-count | model-based after at least `max(4, d+2)` informative observations; otherwise screening cold start at the resolved required/default level |
| `optimizer.propose_turbo` | local improvement after a credible incumbent exists | one registered scalar-preference value with feasibility supplied separately | trust-region model after at least `max(3, d+1)` valid feasible full-fidelity observations; radius reconstructed from owned generations |
| `optimizer.propose_saasbo` | higher-dimensional spaces with sparse active effects | registered Pareto vector only after the current mixed vector/scalar utility is removed; otherwise ineligible | current backend is a SAAS-inspired 12-member strongly-shrunk sparse-axis GP ensemble, not fully Bayesian SAASBO; model-based after `max(6, 2d)` informative full-fidelity observations |
| `optimizer.propose_surrogate_cma_es` | continuous evolution with RBF screening | one registered scalar-preference value with feasibility supplied separately | full-fidelity cohort state; population is `4 + floor(3 ln(max(2,d)))`; may return a partial allocation when only some cohort positions remain |
| `optimizer.propose_bipop_cma_es` | restart/diversity response to stagnation | one registered scalar-preference value with feasibility supplied separately | full-fidelity BIPOP cohort/restart state; may return a partial allocation when the open cohort has fewer unfilled positions |

Here `d` is the tunable parameter dimension. These thresholds describe the current
backend revision, not timeless algorithm truth. The registry stores them as tested
capability policy and exposes an `operating_mode` such as `cold_start`,
`model_based`, `open_cohort`, or `restart`. The model must not infer from the tool
name that a backend is using a canonical external package or a fully Bayesian method.
Reports use the honest display name and backend revision.

These adapter declarations do not let a tool recompute the Job's scenario estimand,
missingness, censoring, risk, or preference semantics. The trusted outcome compiler
produces the registered scalar or Pareto coordinates from immutable
`CandidateOutcomeEvidenceV1`; an adapter consumes exactly those coordinates and the
separate feasibility state. If a tool requires a different representation, lacks the
requested constraint semantics, or would mix a vector with a scalar derived from the
same metrics, its eligibility report is `objective_contract_unsupported`. The Harness
does not silently scalarize, drop a constraint, or substitute the current
`aggregated_score`.

Eligibility is computed before the model call from versioned policy:

- installed backend and dependency availability;
- parameter dimension and value types;
- constraint and multi-objective support;
- accepted tagged observation types, missing-objective behavior, censoring support,
  and cohort/state-update semantics;
- minimum usable observation count;
- fidelity support;
- remaining candidate/trial/time budget;
- experiment-level allowlist;
- rollout feature flags.

The decision persists a `ToolEligibilityReport` containing every registered tool,
whether it was exposed, and typed inclusion/exclusion reasons. The model sees only
eligible tools and cannot override exclusions. Thresholds such as minimum
observations or maximum dimension live in the registry/policy revision and are
evaluated, not embedded as mutable prompt prose.

Eligibility and operating mode are different. A tool may be eligible while running
its deterministic cold-start path, but the catalog must say so. An allocation that
cannot be fulfilled because a CMA cohort is nearly complete returns `partial`; the
harness never claims the requested count was realized.

Each tool returns candidates, optimizer-native scores, warnings, backend provenance,
requested/effective fidelity, and a typed status. It cannot insert rows or schedule
trials.

The existing direct LLM parameter proposer remains a separate
`fixed_algorithm + direct_llm_proposal` comparison arm. It is not in the Version 1
LLM-harness allowlist: wrapping it as an optimizer tool would create an unobserved
nested model call, separate provider semantics, and extra model cost. A future
nested-model tool would need its own explicit protocol and budget evaluation.

All proposal adapters implement one internal contract. The model never constructs
this full request; the harness combines validated plan fields with authoritative
server fields:

```json
{
  "schema_version": "1.0",
  "tool_id": "optimizer.propose_turbo",
  "tool_version": "1.0.0",
  "job_id": "job_...",
  "generation_index": 4,
  "allocation": 2,
  "fidelity_mode": "force_full",
  "resolved_required_fidelity": 1.0,
  "focus": ["local_improvement"],
  "search_space_revision": "sha256:...",
  "optimizer_dataset_snapshot_hash": "sha256:...",
  "server_random_seed": 918273645,
  "time_limit_ms": 5000
}
```

The server derives `server_random_seed` from a versioned hash over the immutable
experiment contract, optimizer dataset snapshot, generation, tool ID/version,
allocation, resolved fidelity mode, and any registry-declared semantic tool
arguments. It explicitly excludes provider call IDs, model array order, rationale,
generation goal, and evidence-reference order. The model cannot supply or alter the
seed directly, and changing prose alone cannot perturb numerical proposals. A tool
that uses randomized numerical methods is reproducible for the canonical request or
declares a hard conformance failure.

`fidelity_mode` is an enum exposed by each tool, not an arbitrary number. The
initial modes are `tool_default`, `screen_low`, `screen_medium`, and `force_full`;
the per-decision tool manifest contains only modes that the tool and immutable
scenario contract support. The server resolves the selected mode through the
job's fidelity mapping. In the current implementation, TuRBO, SAAS-inspired BO,
constrained MOBO, surrogate CMA-ES, and BIPOP-CMA-ES operate at full requested
fidelity. Only multi-fidelity MOBO may choose or be constrained to a screening
level. A model cannot make a full-fidelity optimizer cheap by relabeling it.

The result contract is:

```json
{
  "schema_version": "1.0",
  "status": "ok",
  "tool_id": "optimizer.propose_turbo",
  "tool_version": "1.0.0",
  "backend_revision": "git:...",
  "candidates": [
    {
      "ordinal": 0,
      "parameters": {},
      "requested_fidelity": 1.0,
      "effective_fidelity": 1.0,
      "native_scores": {},
      "metadata": {}
    }
  ],
  "warnings": [],
  "error": null
}
```

`status` is one of `ok`, `partial`, `ineligible`, `unavailable`, `timeout`, or
`internal_error`. Errors are typed objects with a stable code and bounded safe
message; exceptions and logs are not returned to the model. `partial` is never
silently treated as full success.

### 9.3 Adapter reality check and internal data snapshot

The existing optimization code is a strong starting point, but it is not already a
formal tool registry. Verified properties of the current implementation are:

- `OptimizerRequest` and `OptimizerObservation` are frozen generation-level
  contracts with bounded numeric validation;
- Bayesian policies derive deterministic local RNGs from request seed, generation,
  and strategy;
- the portfolio derives a distinct deterministic seed per child;
- TuRBO reconstructs its trust-region radius from full-fidelity outcomes owned by
  prior TuRBO generations;
- surrogate and BIPOP CMA-ES reconstruct distribution/cohort state from
  full-fidelity history and persisted proposal metadata;
- the portfolio performs additional child fallback, cross-child deduplication,
  ownership tagging, and reward eligibility that individual child functions do not
  provide.

Therefore, “wrap six functions” is insufficient as an implementation plan. The
adapter layer must preserve child ownership and all state-reconstruction metadata,
standardize typed errors, and move fallback/deduplication policy into explicit
harness stages. CMA cohort identifiers, distribution hashes, offspring positions,
restart indices, and update-eligibility flags are required state, not optional
debug metadata.

The model-facing `EvidenceSnapshot` is not the same object that proposal tools
consume. Pure tools require an internal immutable `OptimizerDatasetSnapshot` with:

- the exact validated `SearchSpace`;
- every eligible **search-role** tagged observation, including stable internal
  Candidate identity, accepted Trial-attempt evidence hashes, one reconciled
  `CandidateOutcomeEvidenceV1`, and complete optimizer provenance;
- objective directions, constraints, requested/effective fidelity, and completion
  status;
- scenario/fidelity mapping;
- canonical sort order, schema version, source revision, and content hash;
- an inclusion/exclusion and legacy-inference report whose counts reconcile to the
  source candidate revision.

Validation Trial rows and per-case values are never optimizer training observations.
The model may receive only the frozen promotion-checkpoint aggregate allowed by
Section 8.8, with its role and checkpoint explicit; this makes validation an admitted
selection input rather than disguising it as an untouched test. Proposal adapters
receive neither that aggregate nor validation rows. Final-test definitions and
outcomes are inaccessible to both projections. A query or cache that mixes scenario
roles fails snapshot construction instead of filtering after serialization.

The current `OptimizerObservation` is a useful frozen numerical object, but its
`completed`, optional `loss`, `feasible`, and aggregate `failure_rate` fields overload
scientifically different states. The Harness dataset uses a closed tagged algebra
before any tool-specific adaptation:

```text
ObjectiveObservation {
  candidate, verified_objectives, verified_constraints, fidelity, evidence_hashes
}
ConstraintObservation {
  candidate, domain_constraint_ids, violation_margins, fidelity, evidence_hashes
}
RightCensoredObservation {
  candidate, metric_id, lower_bound_or_censor_time, domain_constraints, evidence_hashes
}
PendingReservation {
  candidate, parameter_hash, fidelity, proposal_state
}
```

`PendingReservation` is a separate collection, not an “observation with
completed=false.” `InfrastructureFailure`, `EvidenceContractFailure`, cancellation,
and supersession are absent from the numerical dataset and reconcile only in its
exclusion/health report. A domain constraint never becomes `failure_rate=1`, and a
censored completion time never becomes a large finite loss.

Each adapter declares accepted tags and transformations in the signed registry:

| Initial tool | Objective observation | Constraint-only observation | Right-censored observation | Pending reservation |
| --- | --- | --- | --- | --- |
| constrained MOBO | yes, including multiple registered objectives | yes through the feasibility model | no in the current numerical core | deduplication only |
| multi-fidelity MOBO | yes with requested/effective fidelity | yes through the feasibility model | no in the current numerical core | deduplication/fidelity reservation only |
| TuRBO-inspired | yes for credible full-fidelity incumbents | yes for feasibility, not trust-region success | no | deduplication and owned-state exclusion only |
| SAAS-inspired sparse-axis ensemble | yes | yes for feasibility | no | deduplication only |
| surrogate-assisted CMA-ES | yes for objective surrogate/ranking | yes for feasibility/ranking and completed cohort position | no | preserves unfilled cohort positions only |
| BIPOP-CMA-ES | yes for completed full-fidelity cohorts | yes for cohort ranking/stagnation under a frozen rule | no | preserves cohort/restart state only |

“Yes” describes the target adapter supported by current numerical behavior, not proof
that all scientific semantics are already tested. Constraint-only conformance must
show that missing objectives are skipped rather than imputed and that CMA state updates
remain deterministic. Since no current core implements a censored likelihood or
survival model, the Version 1 registry marks `domain_right_censored` unsupported for
all six tools. A Job whose frozen endpoint requires censor-aware learning must use a
separately implemented/evaluated adapter or pause; the Harness cannot silently convert
the record.

This internal snapshot never crosses the provider boundary. The model sees compact
aggregates and ordinal evidence references; the adapter resolves a persisted dataset
hash to the complete typed input. Tool execution fails if the hash, source revision,
or search-space revision no longer matches.

Pending Candidates appear only as `PendingReservation` and cannot train objective or
feasibility models. A new-format row with a missing tag, metric/constraint provenance,
fidelity, accepted evidence relation, or source relation fails snapshot construction.
A legacy row may pass through the versioned normalizer into a legacy-only comparison
snapshot, but it cannot acquire v3 evidence status and every inference flag remains
attached to downstream reports.

Each adapter receives both global observations and tool-owned state observations.
Global observations may train a surrogate or feasibility model. Trust-region,
cohort, restart, and child-reward state uses relational proposal provenance, not
substring matching on a legacy `optimizer_strategy` string. During migration, the
adapter can verify the old string against the new relation, but disagreement is an
integrity error. Fallback candidates and projected-baseline candidates remain visible
as evidence while being ineligible for optimizer reward or state updates.

The plan validator permits at most one call per tool ID in a generation. Repeated
entries are rejected rather than executed with overlapping seeds or CMA cohort
positions; the model expresses a larger allocation by increasing the single call's
bounded allocation.

### 9.4 Initial diagnostic tools

These are reserved for `interactive_tools_v2`; Version 1 precomputes the equivalent
fields in its evidence snapshot. Keep the future set small and non-overlapping:

- `evidence.get_failure_modes`;
- `evidence.get_parameter_sensitivity`;
- `evidence.get_tool_history`;
- `evidence.get_budget_projection`.

Most information should already be in the snapshot. A diagnostic tool exists only
when deferred detail measurably improves decisions without bloating every prompt.

Every future interactive result has two projections:

- `private_result`: full candidate parameters, internal identifiers, optimizer
  metadata, hashes, and diagnostics for the host;
- `model_projection`: call ID, candidate ordinals, fidelity, typed warning codes,
  feasibility precheck, acquisition rank, diversity summary, and bounded evidence
  references.

The model may select candidate ordinals in Version 2; it still does not need raw
controller gains, file paths, exception text, or database identifiers. Output-schema
validation applies independently to both projections, and the model projection is
generated by trusted code rather than by deleting keys from an arbitrary result.

### 9.5 No simulator tool in Version 1

Do not expose `run_simulation`, `execute_px4`, `write_parameters`, or a generic
Python/shell tool. They combine excessive functionality, permission, and autonomy.
The dispatcher already knows how to run the experiment safely.

### 9.6 Proposal-tool execution containment

Side-effect-free does not mean resource-free. The current implementation calls
`propose_bayesian_candidates`, `propose_evolutionary_candidates`, and the CMA helper
synchronously inside the main orchestration worker. There is no proposal-specific
process boundary, wall deadline, memory ceiling, BLAS-thread ceiling, or per-call
resource accounting. The production Compose worker also has no CPU, memory, or PID
limit. Existing simulator process-tree containment is useful prior art, but it does
not contain numerical proposal code executing in the worker itself.

The Harness must therefore introduce a dedicated **proposal-tool executor**. The
orchestrator never imports or calls numerical tool implementations directly. It sends
one canonical, length-bounded request over a local authenticated Unix-domain socket;
the executor broker starts one fresh child process for that call, waits for a
length-bounded result, and destroys the complete child process tree on timeout,
cancellation, protocol violation, or broker shutdown. The long-lived broker may pool
startup metadata, but Python interpreter and numerical-library state are not reused
between mutually independent tool calls until a soak test proves reuse safe.

The request contains only:

- decision/tool-call IDs and the compiled-plan hash;
- a fixed registry tool ID plus exact implementation revision;
- canonical dataset-snapshot bytes or a read-only content-addressed snapshot handle;
- bounded tool arguments and deterministic seeds;
- wall, CPU, memory, process, thread, input, and output limits.

It never contains a module path, command, URL, database credential, provider secret,
simulator credential, or arbitrary environment variable. The executor resolves a
tool ID through its own signed/frozen registry and rejects any registry-hash mismatch.
It has no database, Redis, artifact-store, provider, or simulator client.

The result protocol is an envelope with `succeeded`, `invalid_input`, `timeout`,
`cpu_limit`, `memory_limit`, `process_limit`, `cancelled`, `tool_error`,
`executor_protocol_error`, or `executor_unavailable`. It includes bounded proposals,
warning codes, wall/CPU duration, peak resident memory, observed process/thread
counts, exit cause, effective numerical-thread settings, executor/runtime hash, and
result hash. Exception chains are converted to stable error codes in the child;
tracebacks and native crash text never cross into the model context.

#### 9.6.1 IPC identity, framing, and replay resistance

“Local socket” is not authentication by itself. Use a pathname Unix-domain socket,
not the abstract namespace, inside a root-owned runtime directory. The directory and
socket have explicit owner/group/mode; only the orchestration-worker service identity
may connect, and only the executor identity may bind/replace the socket. Startup fails
if the path is a symlink, has unexpected ownership/mode/type, or an unowned stale
listener is present.

On Linux the broker verifies kernel-reported peer credentials (`SO_PEERCRED` or
`SCM_CREDENTIALS`) and, where available, the expected service cgroup/security label.
It does not trust a UID/PID claimed inside the message. The WSL2 systemd deployment
uses distinct non-login UIDs and a dedicated socket group containing only the
orchestration worker. The Compose deployment mounts the socket volume only into the
orchestration-worker and executor containers, assigns fixed distinct numeric UIDs/GIDs,
drops credential-changing capabilities, and never mounts the Docker socket. The API,
provider gateway, simulator worker, frontend, and tool child cannot open the executor
socket.

The protocol is one request and one response per connection:

```text
magic | protocol_version | message_type | body_length | canonical_body | body_hash
```

`body_length` is checked before allocation; unknown versions/types, trailing bytes,
duplicate keys, non-canonical encoding, compression, ancillary data not expected by
the message type, and partial/extra frames close the connection. The broker applies
connection, frame, request-rate, concurrent-child, and per-peer quotas before starting
a child. Caller-supplied CPU/memory/output limits can only narrow an administrator
profile; they can never widen its hard ceiling.

Every request binds:

- `tool_call_id`, Decision state/attempt fence, and a 256-bit single-use request nonce;
- compiled-plan, input-snapshot, registry, implementation, and runtime hashes;
- tool ID, bounded arguments, deterministic seed, and resource-profile revision;
- request expiry derived from a monotonic deadline.

The response repeats all bindings plus broker boot ID, child invocation ID, terminal
code, output length/hash, and measured resources. The orchestrator verifies them before
the database compare-and-swap. A reused nonce with different canonical bytes is a
security failure. An exact in-flight duplicate is coalesced or returns
`already_running`; a completed duplicate may return the same bounded cached envelope
only within that broker boot and only if every hash matches. Broker restart may lose
this cache, but the durable ToolCall attempt/state fence still prevents a late or
recomputed result from dispatching twice.

Dataset transfer never accepts an arbitrary filesystem path:

- for ordinary bounded inputs, send canonical bytes in the frame;
- for larger local inputs, pass a read-only sealed file descriptor over the authenticated
  socket and verify its length/content hash before parsing; or
- if a deployment cannot pass descriptors, resolve a fixed-format content address
  beneath the executor-owned snapshot root with no symlink, magic-link, mount, or
  `..` traversal and verify the opened file after resolution.

The child receives an already-open descriptor/bytes, not a path to reopen. Cancellation
uses the same authenticated peer and exact call/attempt/nonce binding. There is no
generic “kill PID,” “load file,” “select module,” or “set environment” IPC method.

The Linux kernel validates credentials attached to Unix sockets, while restricted path
resolution is required to avoid symlink/mount traversal:

- [Linux `unix(7)`: peer credentials and Unix-socket permissions](https://www.man7.org/linux/man-pages/man7/unix.7.html);
- [Linux kernel pathname lookup restrictions](https://docs.kernel.org/filesystems/path-lookup.html).

#### 9.6.2 Numerical-thread and concurrency contract

NumPy/SciPy operations may enter OpenBLAS, MKL, BLIS, or OpenMP pools even when
Python code creates no thread. Before the child imports NumPy, SciPy, scikit-learn, or
an optimizer module, the launcher sets at least:

```text
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
BLIS_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

The child then uses `threadpoolctl` to inspect and, where supported, hold native
thread pools to the compiled per-call limit. A mismatch between requested and
effective thread counts is a typed containment failure, not an informational warning.
The default is one native numerical thread per tool child. Higher values require a
profile revision and a benchmark showing that they improve end-to-end latency without
oversubscription.

Concurrency is admitted twice: the Decision reserves logical tool calls, and the
executor enforces a machine-wide semaphore. The default desktop limit is one proposal
child; a hosted worker may use more only when `concurrent_children × per_child_limit`
fits inside the executor's cgroup/container ceiling. Provider parallel-tool settings
do not change executor concurrency.

#### 9.6.3 Supported platform boundaries

| Deployment | Required containment | Honest support statement |
| --- | --- | --- |
| packaged Windows application | the backend actually runs inside the DroneDream WSL2 Linux runtime; a separate `dronedream-tool-executor.service` receives local Unix-socket requests, has `MemoryMax`, `MemorySwapMax`, `CPUQuota`, and `TasksMax`, denies IP networking, and gives each call a fresh process group plus POSIX resource limits | Windows Job Objects in Tauri do not contain the Python optimizer because it runs in WSL2; the Linux service/cgroup is the authoritative boundary |
| hosted Linux Compose | a dedicated read-only `tool-executor` container with no network, dropped capabilities, `no-new-privileges`, PID/memory/CPU limits, bounded tmpfs, no secrets, and a shared Unix-socket volume; the API/worker containers cannot execute tool modules | ordinary Docker isolation is not a resource limit; the Compose file must set and test explicit limits |
| developer Linux without systemd/container isolation | functional tests may run an executor child with process-group, `setrlimit`, timeout, and thread controls | labeled `containment_degraded`; real Harness jobs are blocked unless the user explicitly runs evaluation-only mock mode |
| future native Windows backend | a suspended child is assigned before resume to a Job Object with kill-on-close, job memory, active-process, and CPU/time limits; IPC is single-use and bounded | disabled until network denial and descendant containment are independently tested; plain `multiprocessing.terminate()` is insufficient |

For the WSL2 runtime, the executor service receives no network address families beyond
local IPC and no writable path except a small private runtime directory. The main
worker cannot ask systemd to widen those permissions. For hosted Compose, the
executor communicates through a bind-mounted socket directory rather than joining the
application network. Neither boundary makes arbitrary downloaded Python safe; only
trusted, packaged tool entry points are eligible.

The Windows-native fallback cannot treat `Process.terminate()` as a tree kill: Python's
official multiprocessing documentation notes that descendants survive and shared
queues/pipes may be corrupted. The design therefore uses an OS process-tree primitive
and one-shot framed IPC or an atomic bounded result file; a killed channel is never
returned to a pool.

#### 9.6.4 Deadline, cancellation, and result linearization

The executor starts the child only after the ToolCall row is durably `RUNNING` with an
attempt number and lease. A monotonic wall deadline is enforced outside the child;
CPU and address-space limits are also applied inside the child where the platform
supports them. On cancellation or deadline:

1. close the call's input channel;
2. request cooperative shutdown only for a short fixed grace period;
3. terminate the complete process group/cgroup/Job Object;
4. wait for confirmed exit and discard any late result;
5. atomically compare the ToolCall attempt/lease before persisting the typed terminal
   result.

No proposal is accepted merely because bytes arrived before the kill completed. The
parent verifies the frame length, schema, decision/tool/runtime hashes, result count,
non-finite-value ban, and attempt fence first. A stale or superseded process can never
dispatch candidates.

Stdout/stderr are redirected away from inherited worker pipes to size-limited private
files or disabled. This prevents a chatty native library from blocking the child on a
full pipe. Diagnostic excerpts are allowlisted, redacted, and truncated before
persistence; full raw output is not part of replay evidence.

#### 9.6.5 Capacity and failure tests

Containment is a release gate, not a deployment note. Tests must include tools that:

- spin forever, allocate past the limit, fork children, create excess threads, write
  unlimited output, crash in native code, ignore graceful termination, and return
  oversized or hash-mismatched frames;
- attempt DNS, TCP, loopback, filesystem, subprocess, database, Redis, and environment
  secret access;
- race cancellation, lease expiry, broker restart, worker restart, and a late valid
  result;
- connect from the wrong UID/GID/cgroup/container, race stale-socket replacement, reuse
  a nonce with same/different bytes, spoof IDs inside the frame, widen resource limits,
  send malformed/trailing/oversized/partial frames, and forge a response binding;
- supply absolute/relative/`..`/symlink/magic-link/bind-mount snapshot paths, swap a
  file around resolution/open, mutate an unsealed descriptor, and mismatch length/hash;
- invoke BLAS under several executor children to verify the measured thread total and
  absence of oversubscription;
- exhaust the executor service/container while proving the API, database, simulator
  worker, and already-running trial leases remain healthy.

The registry points only to trusted packaged entry points. Process isolation is
defense in depth against accidental hangs, native dependency faults, and resource
exhaustion; it is not a claim that arbitrary untrusted Python becomes safe.

## 10. Model-visible decision contract

The provider adapter must require either:

1. native strict function calling; or
2. an explicitly marked schema-emulated tool-call response.

There is no free-text parser fallback.

For native function calling, the only Version 1 function is:

```json
{
  "name": "submit_generation_plan",
  "description": "Submit one complete bounded plan for the next DroneDream optimization generation.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "schema_version": {"type": "string", "enum": ["1.0"]},
      "decision": {"type": "string", "enum": ["continue", "stop", "pause"]},
      "generation_goal": {"type": "string"},
      "tool_calls": {"type": "array"},
      "stop": {"type": "object"},
      "uncertainty": {"type": "object"}
    },
    "required": [
      "schema_version",
      "decision",
      "generation_goal",
      "tool_calls",
      "stop",
      "uncertainty"
    ],
    "additionalProperties": false
  }
}
```

The production schema expands every nested object with required fields and
`additionalProperties: false`; the abbreviated form above only shows the transport
shape. The `tool_id` enum is generated from the eligible registry subset for that
specific decision. Length and collection limits are rechecked in application code
because strict-schema feature subsets differ by provider. Refusal, truncation, zero
calls, multiple plan calls, an
assistant text answer instead of a call, or a provider-declared non-strict call are
typed protocol failures.

```json
{
  "schema_version": "1.0",
  "decision": "continue",
  "generation_goal": "restore diversity while preserving one local refinement slot",
  "tool_calls": [
    {
      "tool_id": "optimizer.propose_bipop_cma_es",
      "allocation": 2,
      "fidelity_mode": "force_full",
      "focus": ["stagnation", "feasibility"],
      "evidence_refs": ["stagnation.window_3", "failure_summary.constraint"]
    },
    {
      "tool_id": "optimizer.propose_turbo",
      "allocation": 2,
      "fidelity_mode": "force_full",
      "focus": ["local_improvement"],
      "evidence_refs": ["best_training_candidate", "recent_generations.3"]
    }
  ],
  "stop": {
    "recommended": false,
    "reason_code": null
  },
  "uncertainty": {
    "level": "medium",
    "missing_evidence": []
  }
}
```

### 10.1 Required constraints

- `decision` is `continue`, `stop`, or `pause`.
- Every `tool_id` must be in the per-request allowlist.
- A tool ID appears at most once; allocations are consolidated in the plan, not by
  issuing duplicate calls.
- Allocations are positive integers and their sum is within the generation cap.
- Evidence references must resolve to fields in the persisted snapshot.
- Fidelity mode must be allowed by both the tool and experiment; the server resolves
  it to requested/effective fidelity.
- `reason_code` is an enum, not arbitrary control text.
- Explanations are length-limited audit text and have no control effect.
- The model cannot set a seed, parameter value, URL, command, database ID, or secret.
- The model cannot select, rewrite, normalize, scalarize, or threshold an objective,
  metric, risk measure, scenario population, missingness rule, or acceptance policy.
  It can route only among tools already compatible with the frozen outcome contract.

### 10.2 Parallel execution is a server concern

Version 1 permits exactly one native call: `submit_generation_plan`. Its arguments
may contain several declarative tool invocations. After validation, the server may
execute independent proposal tools concurrently when every selected registry entry
is `parallel_safe`. Provider-side parallel tool calling remains disabled.

The provider result is a `GenerationPlan`, never an execution command. Only the
deterministic compiler in Section 11.1 may create an executable tool request.

### 10.3 Exact `continue`, `stop`, and `pause` semantics

These values are not equally authoritative:

| Model decision | Required plan shape | Authoritative application behavior |
| --- | --- | --- |
| `continue` | one or more tool calls; stop fields empty | validate, execute pure tools, gate the batch, then atomically dispatch |
| `stop` | no tool calls; enumerated stop reason and evidence references | evaluate the recommendation with the frozen deterministic stopping policy |
| `pause` | no tool calls; enumerated missing-evidence or operator reason | pause only if the job's immutable pause policy permits it |

A stop recommendation cannot, by itself, terminate search or materialize the sealed
final test. The
`StoppingPolicy` is fixed at job creation and records:

- minimum completed generations and minimum valid observations;
- hard budget exhaustion rules;
- objective/acceptance thresholds;
- stagnation or convergence predicates appropriate to the active tools;
- whether model-recommended futility may be considered;
- whether a human confirmation is required;
- the exact policy and implementation revision.

The stop evaluator returns `accepted`, `rejected_continue`, or
`rejected_pause_for_user`, with one result per predicate. When it accepts, the server
freezes the winner from verified search/validation evidence before the final-test
verifier is allowed to create any Trial. When it rejects, the application follows a
predeclared policy; it does not ask the model to argue with the rule.

A pause recommendation transitions to `AWAITING_USER` only after a deterministic
policy check. It reserves no new simulation budget, creates no trials, and never
resumes merely because a timeout elapsed. The immutable job contract defines whether
timeout means remain paused, cancel, or use the deterministic portfolio. The UI must
show the reason, remaining budget, and the exact action that would resume the job.

Contradictory shapes—`stop` with tool calls, `continue` with no tool calls, or
`pause` with allocations—are schema or semantic failures. The model's uncertainty
field is evidence for audit and evaluation, never an authority signal.

## 11. Deterministic plan validator

The validator produces an immutable report with one result for every rule:

1. decision schema and version supported;
2. job is still in the expected generation and state version;
3. evidence snapshot matches the experiment and immutable optimization-outcome
   contracts, including metric-DAG, estimand, risk, constraint, transform, reference,
   and promotion-policy digests;
4. tool is present as eligible in the immutable routing opportunity and its signed
   objective adapter is compatible with the parameter, outcome, observation-tag,
   estimand, risk, constraint, and fidelity contracts;
5. model allocation touches only discretionary capacity; merged policy-reserved plus
   discretionary allocation satisfies per-tool/global, minimum-exposure, maximum-share,
   availability/circuit, fairness, and cost limits;
6. total projected scenarios fit the remaining trial budget;
7. fidelity is supported and cannot weaken final verification;
8. stop/pause recommendation has the required empty allocation and passes the
   versioned product policy;
9. routing opportunity, eligible-action-set, incumbent, policy, registry, model
   binding, reward, exploration, and state-version hashes still match;
10. no unresolved previous decision owns the generation;
11. no sealed final-test reference is present;
12. no unknown evidence reference is present;
13. provider response and rationale are within size limits.

There is no automatic “repair” that changes tool identity, allocation, or fidelity.
Version 1 does not ask the model to correct malformed formatting because that would
be a second semantic turn capable of changing the plan. A schema or semantic
rejection follows the configured fallback policy and is recorded.

### 11.1 Deterministic plan compiler

For an accepted `continue` plan, the compiler creates and persists a
`CompiledGenerationPlan` before any tool starts. It:

1. merges policy-reserved and model-discretionary allocations;
2. canonicalizes tool order independent of provider array order;
3. binds exact tool and implementation versions;
4. binds the routing-opportunity/action, outcome-contract, objective-adapter,
   reward/exploration/attribution, registry, model-binding, and runtime-manifest hashes;
5. resolves fidelity modes through the frozen scenario mapping;
6. binds the model-evidence and optimizer-dataset snapshot hashes;
7. derives server seeds from semantic inputs;
8. assigns stable server call IDs and allocation authority;
9. calculates upper-bound candidate, scenario, trial, token-independent tool, and
   wall-clock cost;
10. records the validator and policy revisions;
11. emits canonical bytes and a compiled-plan hash.

The compiler does not invent a different optimizer or reduce an allocation to make a
bad plan fit. Such changes are fallback decisions and receive separate provenance.
Tool workers accept only a compiled call bearing the expected plan hash; they never
accept a raw provider call ID or JSON object. Crash recovery reuses the same compiled
bytes.

## 12. Candidate batch gate

After tools run, the batch gate:

- compiles values through the pinned exact-domain/lattice implementation, records any
  representation-only wire conversion, and rejects material projection;
- validates physical and controller coupling constraints;
- rejects non-finite values and unsupported types;
- deduplicates within the batch and against prior candidates;
- preserves tool and decision provenance;
- rejects candidates whose projection materially changes the tool's proposal unless
  the tool contract explicitly allows projection;
- calculates exact scenario/trial cost;
- enforces remaining budget again under a row lock;
- assigns seeds only from the experiment's deterministic seed schedule;
- inserts candidates and trials atomically.

Parallel completion order must not affect the candidate batch. Consolidation sorts by
compiled-call ordinal, then tool-result candidate ordinal, then canonical parameter
hash. Deduplication and deterministic fill use that order; wall-clock tool completion
order is trace data only.

When several tools propose the same canonical parameter/fidelity pair, the gate
creates one dispatchable candidate group and attaches every eligible proposal source.
The deterministic primary source is the minimum canonical tuple of tool ID, tool
version, call ID, and candidate ordinal—not the fastest worker or model list order.
The batch report records the collision even though only one trial set is dispatched.
This prevents output ordering from fabricating tool success.

Credit assignment is versioned and separate from provenance. The gate freezes exact
order-independent source groups and pre-outcome rational shares under Section 8.11. It
does not calculate quality reward before Candidate evidence exists. Low-fidelity
screening, promotions, deterministic fill, emergency fallback, transformed/rejected/
undispatched proposals, and exact duplicates retain their own source role, parent edge,
eligibility, and complete incurred cost. The append-only reward compiler later applies
the pinned `PortfolioRewardContractV1`; a display-primary source never receives all
credit merely because it sorts first.

The evidence snapshot records the attribution/reward/window revisions used to produce
`routing_evidence_summary` strictly from immutable opportunity/source/outcome/reward/
cost rows. Offline reports may calculate alternate attribution policies, but
they are labeled exploratory/non-causal, cannot rewrite the online evidence seen by a
completed decision, and cannot support off-policy claims without Section 8.11.7 gates.

If fewer candidates survive than planned, the gate may:

- dispatch the valid remainder when `minimum_dispatch_count` is met;
- ask the deterministic portfolio for explicitly labeled fill candidates; or
- reject the decision.

It must not ask the LLM to improvise an unbounded repair after partial insertion.

### 12.1 Current parameter-contract audit

The present code has several useful controls that should be retained:

- Job creation resolves a catalog alias to a canonical identifier and rejects a
  version-mismatched `px4-v1.16`/`px4-v1.17` alias;
- active hard-dependency companions must be enabled or locked in the same Job;
- every Candidate generated through `SearchSpace` contains locked domains, is projected,
  and is passed to the Job-specific concrete-value validator;
- real SITL startup can use the official `PX4_PARAM_<name>` session overrides and then
  read the requested values back through MAVSDK before flight;
- the live MAVSDK path reads the old values, writes sequentially, reads back, and makes a
  best-effort reverse-order rollback when a write or verification fails; and
- reboot-required parameters are rejected from that live-write path and accepted only
  through fresh-process startup overrides.

Those controls do **not** yet make the parameter treatment immutable or transactional:

1. `dronedream.px4.multicopter.2026-07-r1`, `builtin-v1`, `px4-v1.16`,
   `px4-v1.17`, and `px4-main` all resolve to the current `2026-07-r2` bytes. Persisting
   the resolved `r2` identifier avoids falsely preserving the alias, but an old catalog
   cannot be replayed once its bytes are gone.
2. Nearly every entry claims compatibility with all three PX4 lines. Only three
   parameters receive release-specific overrides, while the source link points to a
   moving documentation page and has no upstream content digest.
3. A requested firmware commit is compared with the checkout's Git HEAD. That does not
   prove that the launched `build/px4_sitl_default` binary came from that clean commit,
   build configuration, compiler, generated parameter metadata, or airframe.
4. `validate_parameter_values` skips a hard relation when the companion is absent.
   The Job service closes that gap for normal Job creation, but the lower-level function
   and startup/MAVSDK helpers remain valid public call paths with a weaker contract.
5. `validate_parameter_values` checks bounds and choices but not the declared step
   lattice. `ParameterDomain.project` uses binary floating point, Python `round`, and
   the user-selected search minimum as an implicit grid origin.
6. The upstream PX4 `increment` is metadata used by generated references and ground
   stations; it is not proof that a `FLOAT` parameter rejects every other representable
   value. Calling the projected value “firmware-valid” conflates transport type,
   experiment resolution, and DroneDream's safety policy.
7. `apply_policy="disarmed"` is metadata only in the live path. The code rejects
   `reboot`, but the parameter client has no arming-state method and can write a
   high-risk `disarmed` parameter without proving the vehicle is disarmed.
8. Multiple MAVSDK writes are a compensating transaction, not an atomic transaction.
   A coupled controller can observe an intermediate vector, and rollback can itself
   fail. Iteration order is request order rather than a verified safe transition plan.
9. Readback accepts a float difference up to `step / 10`. That tolerance is unrelated
   to MAVLink/PX4 `float32` representation and can accept a value that is not the
   intended experiment lattice point.
10. The default launcher starts every trial from the same PX4 checkout and its shared
    SITL rootfs. It starts a fresh process, but it does not create a per-attempt
    copy-on-write parameter store or prove a complete reset. Because PX4 parameters are
    normally saved, the current evidence cannot rule out unselected-parameter state
    leaking between attempts.

PX4's official parameter documentation supports a stronger target contract. The
[parameter reference](https://docs.px4.io/main/en/advanced_config/parameter_reference)
is generated from version-specific source metadata and exposes type, minimum, maximum,
increment, default, unit, read-only, and reboot facts. The
[parameter-system guide](https://docs.px4.io/main/en/advanced/parameters_and_configurations)
distinguishes `param load` from merging `param import`, documents automatic persistence
and read-only locking, and states that component metadata can publish the metadata JSON
associated with the running firmware. The
[simulation guide](https://docs.px4.io/main/en/simulation/) calls
`PX4_PARAM_<name>` a session override. MAVSDK's official
[Param API](https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_param.html)
also exposes explicit `ReadOnly`, `TypeMismatch`, read-failure, and component-selection
results. The Harness must preserve those distinctions rather than reducing them to one
float dictionary.

### 12.2 Immutable firmware-bound parameter bundle

Harness mode does not accept a friendly alias as the executable parameter contract.
Before admission, a trusted compiler produces `ParameterContractBundleV1` with:

- exact PX4 source commit and dirty-tree rejection;
- PX4 binary/image SHA-256, board/SITL target, airframe and model identifiers, build
  configuration, compiler/toolchain identity, and build-provenance subject digest;
- generated upstream parameter-metadata bytes and SHA-256 from that exact build;
- observed runtime component metadata digest, component/system IDs, protocol version,
  and the closed set of readable/writable parameter names and reported types;
- a DroneDream catalog-overlay ID/hash containing only explicitly reviewed safety
  envelopes, experiment grids, coupling constraints, and application policy;
- one immutable entry per parameter with upstream type/unit/min/max/default/increment/
  enum/read-only/reboot facts, overlay facts, source provenance, and compatibility
  predicates; and
- canonical bundle bytes/hash, schema version, compiler/verifier revisions, and signed
  Harness Runtime-manifest identity.

Version aliases remain a UI/input convenience only. They resolve through a signed
alias table to one content-addressed bundle digest, and every previously released
digest remains available for the advertised retention period. An alias never points an
existing Job at different bytes. Unknown, unavailable, or metadata-mismatched firmware
fails admission; it does not inherit `main`.

The runtime handshake compares the build-time metadata digest with component metadata
from the running PX4 process. Missing component metadata is an explicit degraded
capability, not permission to claim exact compatibility. A release may allow an
audited fallback export for a specific firmware digest, but the fallback bytes and
reason are themselves pinned. A Git checkout path or semantic version string alone is
never a parameter-catalog proof.

DroneDream's `safe_bounds` must be renamed in the executable contract to
`reviewed_experiment_envelope`. It is a conservative product policy, not a PX4
certificate and not evidence that every interior combination is dynamically stable.
Reports show upstream hard metadata and the DroneDream envelope separately, including
who/what generated each, review date, validation campaign, applicable
firmware/airframe/model, and residual limitations.

### 12.3 Exact domain and projection contract

Each active parameter has three non-interchangeable domains:

1. **transport domain**: PX4 `INT32` or `FLOAT`, enum/read-only status, and upstream
   min/max metadata for the running build;
2. **experiment domain**: explicit choices or an exact decimal/rational lattice within
   user bounds; and
3. **reviewed experiment envelope**: the narrower DroneDream policy applicable to this
   firmware/airframe/scenario class.

The experiment domain stores `grid_origin_decimal`, `quantum_decimal`, inclusive
integer-index bounds, and canonical numeric-encoding revision. A value is
`origin + k * quantum`; user search bounds must themselves resolve to declared lattice
indices. No grid is implicitly re-anchored when the user changes `search_min`.
Decimal/rational arithmetic determines the index, with no binary-float rounding or
banker's-rounding dependence.

Before transmission, the compiler deterministically converts the exact experiment
value to PX4's reported wire type. For `FLOAT`, it records the canonical IEEE-754
binary32 bit pattern and decimal rendering. Readback compares the returned binary32
value with that expected representation under a protocol-specific ULP rule, not
`catalog_step / 10`. An integer or enum must match exactly.

Proposal tools may work in normalized unit coordinates, but only the candidate compiler
materializes a physical vector. Its report preserves:

- raw tool proposal and hash;
- exact lattice index/vector before wire conversion;
- projected wire vector and per-field reason;
- normalized and physical displacement;
- constraint result and contract digest; and
- acceptance/rejection code.

Clamping a materially out-of-domain proposal is a rejection unless the tool's signed
contract explicitly permits a bounded projection policy. Silent projection must not
make an optimizer appear to have proposed a safe or successful point it did not
produce. Locked/fixed companions are always part of the compiled full vector, even
though only tunable coordinates are visible to the optimizer.

### 12.4 Closed executable constraint graph

Pairwise `<=` and `>=` metadata is too weak for controller configuration. The bundle
contains a closed, versioned expression graph—never executable Python or model-authored
code—with typed nodes for:

- bound and finite-value checks;
- enum membership and read-only constraints;
- pairwise order, equality, ratio, sum, and difference bounds;
- conditional implications controlled by mode/enum/airframe;
- required companion and locked-baseline presence;
- unit/dimension compatibility;
- tuning-stage and downstream-loop readiness prerequisites; and
- application-state predicates such as disarmed, rebooted, estimator-ready, landed,
  or unavailable-in-this-build.

The compiler requires a **complete active vector**: tunable values plus every locked,
fixed, derived, and referenced companion. Missing context is `UNKNOWN`, never
implicitly valid. It evaluates the same canonical graph at Job admission, baseline
capture, every proposed Candidate, before parameter delivery, after readback, and
before Trial acceptance. Each evaluation emits rule IDs and operands under the pinned
graph hash.

Human-readable descriptions remain UI copy and cannot substitute for executable rules.
“Tune the inner loop first,” for example, becomes either a measurable prerequisite
with a referenced accepted evidence artifact or an advisory label that carries no
enforcement claim. The Harness must not promote advisory prose to a safety guarantee.

### 12.5 Clean-start parameter application protocol

The preferred real-SITL treatment is one fresh, content-addressed runtime slot and one
copy-on-write PX4 rootfs/parameter store per physical attempt:

1. create the attempt row and immutable input/parameter-contract hashes;
2. materialize a pristine baseline snapshot from the verified Runtime image;
3. apply the complete compiled vector through startup overrides before flight;
4. start the pinned PX4/Gazebo binaries under the attempt-specific process and storage
   namespace;
5. query component identity, runtime metadata, arming/landed state, and all
   treatment/referenced companion values;
6. compare exact wire values and evaluate the full constraint graph;
7. hash a complete control-relevant runtime parameter snapshot—not only requested
   names—and bind it to the attempt;
8. arm and execute only after the verifier emits `PARAMETER_TREATMENT_VERIFIED`; and
9. destroy the writable overlay after content-addressed evidence retention.

The attempt-specific baseline includes the full control-relevant parameter set and
hash. Catalog defaults are not treated as observed baseline values; airframe scripts,
board defaults, persisted storage, startup overrides, and firmware changes can all
alter them. A clean-start A/B test must prove that an attempt with no overrides returns
the same baseline digest after a prior extreme-but-valid treatment.

Live MAVSDK application is a separate, lower-assurance profile and is disabled for the
initial Harness release. If introduced later, it requires:

- authenticated selection of the expected autopilot component;
- positive disarmed, landed, and mode-state evidence when any rule requires it;
- a graph-derived safe transition sequence whose every intermediate full vector is
  valid, or refusal when no such sequence exists;
- explicit per-write result classification, readback, timeout, and protocol identity;
- reverse transition with verified rollback on failure;
- module-update/reboot acknowledgement where the running controller requires it; and
- quarantine plus process teardown after ambiguous write acknowledgement or failed
  rollback.

It must be called a **compensating write protocol**, never atomic application. Coupled
sets that cannot safely traverse intermediate states use clean startup only. No flight
continues after an ambiguous or partially rolled-back parameter write.

`ParameterApplicationEvidenceV2` binds the attempt, complete Candidate vector, contract
bundle, firmware binary, Runtime, baseline and final parameter-snapshot hashes,
transport/component/protocol identities, requested/exact-wire/readback values,
application state and transition, constraint reports, timestamps, rollback facts, and
all source artifacts. The evidence verifier—not the launcher that performed the
writes—decides whether the treatment is admissible. A Trial with missing or rejected
parameter evidence is an infrastructure/evidence outcome, not a poor Candidate score.

### 12.6 Reference orchestration pseudocode

```python
def continue_generation(job_id: str) -> DispatchResult:
    intent = prepare_decision_intent(job_id)
    # prepare_decision_intent uses a short transaction to:
    # - lock the job
    # - verify the generation boundary
    # - reconcile/compile every newly complete CandidateOutcomeEvidenceV1
    # - append any newly resolvable delayed routing reward/cost events
    # - build/reuse an immutable model-facing evidence snapshot
    # - build/reuse a full internal optimizer dataset snapshot
    # - create/reuse the immutable RoutingOpportunityV1 containing the exact
    #   eligible/excluded actions, incumbent, contracts, reserved exploration,
    #   discretionary capacity, availability/circuits, and cost ceilings
    # - create/reuse the idempotent REQUESTED decision
    # - release the lock

    if intent.has_terminal_result:
        return intent.terminal_result

    envelope = model_gateway.decide(
        evidence=intent.model_evidence_snapshot,
        eligible_tools=intent.routing_opportunity.eligible_tool_catalog,
        function=submit_generation_plan_schema(
            intent.routing_opportunity.eligible_tool_catalog
        ),
        idempotency_key=intent.provider_idempotency_key,
    )
    persist_provider_envelope(intent.decision_id, envelope)

    plan = parse_exactly_one_plan(envelope)
    plan_report = plan_validator.validate(plan, intent)
    if not plan_report.accepted:
        return apply_explicit_fallback(intent, plan_report)

    execution_plan = compile_and_persist_generation_plan(
        decision_id=intent.decision_id,
        validated_plan=plan_report.normalized_plan,
        reserved=intent.routing_opportunity.policy_reserved_allocations,
        discretionary_capacity=intent.routing_opportunity.discretionary_capacity,
        dataset=intent.optimizer_dataset_snapshot,
        registry=intent.pinned_tool_registry,
        outcome_contract=intent.optimization_outcome_contract,
    )
    results = execute_pure_proposal_tools(
        execution_plan,
        dataset=intent.optimizer_dataset_snapshot,
        registry=intent.pinned_tool_registry,
    )
    batch_report = candidate_batch_gate.validate(results, intent)
    if not batch_report.accepted:
        return apply_explicit_fallback(intent, batch_report)

    # A second short transaction locks the current job revision, rechecks
    # the budget and generation, inserts provenance-linked candidates/trials,
    # exact order-independent proposal-source associations, full allocated
    # cost obligations, and marks the decision DISPATCHED.
    return reserve_and_dispatch_atomically(intent, batch_report)
```

`prepare_decision_intent`, `persist_provider_envelope`, fallback application, and
atomic dispatch are individually retryable. A provider response is never allowed
to cross directly into candidate insertion.

## 13. Durable state machine

Do not overload the public job status with every internal step. Add a separate
optimization-decision state:

```text
REQUESTED
    |
    v
MODEL_RUNNING -----> MODEL_FAILED
    |
    v
PLAN_RECEIVED -----> PLAN_REJECTED
    |
    v
PLAN_COMPILED
    |
    v
TOOLS_RUNNING -----> TOOLS_FAILED
    |
    v
BATCH_VALIDATING --> BATCH_REJECTED
    |
    v
DISPATCHING
    |
    v
DISPATCHED

PLAN_RECEIVED may also branch to:

  STOP_RECOMMENDED --> STOP_ACCEPTED --> WINNER_FROZEN
                   \-> STOP_REJECTED

  PAUSE_RECOMMENDED --> PAUSED
                    \-> PAUSE_REJECTED

Any terminal failure may lead to FALLBACK_DISPATCHED or PAUSED according to policy.
Cancellation may move any non-dispatched decision to CANCELLED. A late result for a
superseded attempt moves to SUPERSEDED and can never dispatch.
```

Runtime dependency health is a separate operational state, never a Candidate/tool
quality score:

```text
CLOSED --qualifying window threshold--> OPEN_UNTIL
  ^                                      |
  |                                      v
  +--one successful fenced probe-- HALF_OPEN_PROBE
                         |
                         +--qualifying failure--> OPEN_UNTIL
```

Only the gateway/executor state service may perform these compare-and-swap
transitions. A credential error, malformed model plan, poor proposal, Candidate
failure, cancellation, or stale fence cannot trip the shared dependency circuit.

Decision state is only one axis. A logical Trial and each physical attempt use a
separate evidence state machine:

```text
logical Trial:  PENDING -> CLAIMED -> EVIDENCE_ACCEPTED
                    ^          |
                    |          +-> RETRY_PENDING       (infrastructure/evidence fault)
                    |          +-> DOMAIN_COMPLETED    (constraint/censored observation)
                    |          +-> CANCELLED

physical attempt:
  RESERVED -> RUNNING -> ARTIFACTS_PERSISTED -> VERIFYING -> ACCEPTED
       |          |              |                  |
       +----------+--------------+------------------+-> REJECTED
                                                     -> SUPERSEDED
                                                     -> QUARANTINED
```

`RETRY_PENDING` keeps the same logical Trial/Candidate/scenario/seed/input identity and
creates a new physical attempt/fence. It is not a loop that mutates an old attempt.
`EVIDENCE_ACCEPTED` requires a complete v3 envelope and atomically binds the one
accepted attempt. Domain completion is terminal scientific evidence only under a
compatible frozen constraint/censoring contract.

Candidate-outcome and routing-reward states are also durable and independent. Each
Candidate-outcome machine belongs to exactly one evidence role and checkpoint:

```text
Candidate outcome (search | validation | final_test, one checkpoint):
  AWAITING_EXPECTED_CELLS -> READY_TO_COMPILE -> COMPILING -> ACCEPTED
             |                                      |
             +-> EVIDENCE_INCOMPLETE                 +-> REJECTED

Routing reward:
  PENDING -> ELIGIBLE
          -> UNOBSERVED
          -> INELIGIBLE
          -> SUPERSEDED
```

`ACCEPTED` Candidate evidence is content-addressed to one role, checkpoint, source
revision, and immutable outcome contract. New Trial evidence produces a later envelope;
it does not mutate an envelope consumed by a prior Decision. Search, validation, and
final-test cells cannot be reconciled by the same compiler claim. A reward may resolve
after later generations,
but the append-only event references its historical opportunity/action and cannot
change that opportunity's eligible set, action probability, incumbent, or compiled
plan. Restart recovery claims both compilers through their own leases and idempotency
keys; no in-memory callback is the sole owner of delayed credit.

Winner promotion has no edge back from the sealed final test:

```text
SEARCHING <-> VALIDATION_CHECKPOINT
    |
    v
WINNER_FREEZE_PENDING -> WINNER_FROZEN
                              |
                              v
                    FINAL_TEST_MATERIALIZING
                              |
                              v
                       FINAL_TEST_RUNNING
                          /           \
                         v             v
                FINAL_TEST_PASSED  FINAL_TEST_FAILED
                         \             /
                          v           v
                       REPORT_FINALIZING
```

The transition into `WINNER_FROZEN` commits the Candidate, search/validation evidence,
policy/compiler/verifier hashes, and final-test budget/contract commitment in one
transaction. Only the narrow final-test service can perform the next transition. A
failed final test is a reportable terminal verdict, not permission to unfreeze, inspect
the next Candidate, change thresholds, or dispatch more search.

### 13.1 Concurrency controls

- One unresolved decision per `(job_id, generation_index)`.
- A partial unique index on `(job_id, generation_index) WHERE terminal_at IS
  NULL` enforces that identity while retaining resolved attempts. The predicate
  is based on a nullable terminal timestamp, not an evolving list of status
  strings.
- A lease contains `lease_owner`, `lease_expires_at`, and `attempt`.
- State transitions use compare-and-swap on `state_version`.
- Budget reservation and candidate/trial insertion occur in one short transaction.
- PostgreSQL workers may use row locks or queue-appropriate `SKIP LOCKED`; SQLite
  development mode uses a single local orchestrator. The final SQLite dispatch
  gate begins an explicit `BEGIN IMMEDIATE` transaction before re-reading job
  state and budget; it never tries to emulate row locks that SQLite does not
  provide.

Both supported databases can enforce the required partial unique indexes:
[PostgreSQL documents unique partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html),
and [SQLite supports unique indexes over a predicate](https://www.sqlite.org/partialindex.html).
This does not make SQLite a multi-orchestrator backend. SQLite permits multiple
readers but only one simultaneous writer, so provider/tool work remains outside
the transaction and the packaged desktop runtime keeps one orchestration writer.

### 13.2 Idempotency keys

| Operation | Key |
| --- | --- |
| Candidate outcome envelope | candidate + source evidence revision + optimization-outcome-contract hash |
| routing reward event | opportunity + candidate + exact source + checkpoint + reward-contract hash |
| evidence snapshot | contract hash + generation + evidence revision |
| routing opportunity | job + generation + state/evidence revision + routing-policy hash |
| logical provider decision | job + generation + orchestration-contract revision + snapshot hash |
| physical provider attempt | decision + attempt ordinal + canonical request hash |
| provider idempotency header, when proven supported | stable logical decision key reused across eligible physical retries |
| tool execution | decision + call ID + tool version + canonical args hash |
| candidate insert | decision + tool call + candidate ordinal + parameter hash |
| trial dispatch | candidate + scenario contract revision + seed |

Re-execution returns the stored result for the same key. A key collision with
different canonical input is a hard integrity error.

### 13.3 External-call rule

The provider call and optimizer computation occur outside a database transaction.
Durable intent is committed before the call and the result is committed afterward.
This prevents a slow provider from holding locks and makes recovery explicit.

### 13.4 Machine-checkable invariants

The following are database or property-test invariants, not documentation wishes:

- `active_decisions(job, generation) <= 1`;
- `sum(reserved_trial_cost) <= job.max_total_trials`;
- every LLM-harness candidate references a dispatched decision and at least one
  successful proposal source;
- every LLM-harness candidate has exactly one deterministic primary proposal source;
- every duplicate proposal source is retained even when only one candidate is
  dispatched;
- every accepted Candidate outcome envelope reconciles the complete expected
  case/replicate cell manifest and one immutable optimization-outcome contract;
- optimizer rank, portfolio reward, acceptance, promotion, winner freeze, and report
  projections reference the same accepted Candidate outcome envelope rather than
  independently recomputed scores;
- every routing action references one immutable pre-action opportunity containing the
  exact eligible/excluded action set, incumbent, contracts, availability/circuits,
  policy-reserved allocation, discretionary capacity, and cost ceilings;
- exact reward-eligible proposal-source shares sum to one per Candidate and are
  independent of tool iteration/completion order; same-tool duplicates cannot multiply
  a tool's aggregate share;
- every reward event references an opportunity/action that predates its Candidate
  outcome; delayed reward cannot mutate the historical action, context, probability,
  or eligible set;
- every allocated proposal slot and physical/fidelity/compute cost is reconciled even
  when its result is invalid, duplicate, fallback, incomplete, infrastructure-failed,
  or reward-ineligible;
- every dispatched tool call's argument and result hashes match canonical content;
- every tool call references one persisted compiled plan and exact compiled-call
  hash;
- raw provider output can never be a tool-worker input;
- no evidence snapshot source revision includes a final-test Trial;
- a final winner and all search/validation policies are frozen before any final-test
  Trial is created;
- an accepted plan references the exact snapshot and tool registry hashes it saw;
- a completed decision cannot transition back to a running state;
- the same idempotency key cannot resolve to different canonical input or output;
- every physical provider request is represented by exactly one attempt row and
  references one logical decision; unknown usage remains explicit rather than being
  silently zeroed;
- every physical simulator execution is represented by exactly one immutable
  `trial_execution_attempts` row bound to one logical Trial and exact input/Runtime
  hashes;
- at most one physical attempt is accepted for a logical Trial, and its v3 envelope,
  artifact digests, verifier revision, metric observation, and outcome class agree;
- `infrastructure_failure` and `evidence_contract_failure` attempts are absent from
  optimizer datasets and Candidate-quality aggregates, while exact retries preserve
  Trial/Candidate/scenario/seed/input identity;
- a final-test Trial cannot exist before the winning Candidate and
  search/validation/policy evidence hashes atomically enter `WINNER_FROZEN`;
- sum of confirmed cost plus unresolved attempt upper bounds never exceeds the
  reserved model-currency budget;
- at most one provider attempt is accepted as the plan source for a decision;
- a cancelled, paused, stopped, or otherwise terminal job cannot reserve new budget;
- cancellation requested before the dispatch commit wins over every provider or tool
  result that has not already committed;
- `WINNER_FROZEN` precedes every final-test Trial and references only verified
  search/validation evidence;
- only the deterministic stop evaluator can create `STOP_ACCEPTED`;
- a pause never resumes without a versioned operator or fallback transition.

CI should generate random valid and invalid histories and assert these invariants
after retries, cancellation, stale writes, and injected process termination.

### 13.5 Cancellation, process exit, and late responses

`cancel_requested_at` is authoritative job state, not a best-effort UI event. The
orchestrator checks it:

1. before creating a decision intent;
2. immediately before a provider request;
3. after a provider response and before accepting a plan;
4. before each proposal tool begins;
5. inside the final locked dispatch transaction.

If cancellation wins any check, no new candidates or trials are inserted. A provider
request may be impossible to revoke; its late response is redacted, metered, and
stored as `SUPERSEDED`, but never parsed into an executable plan. Tool workers use
cooperative cancellation, while the final transaction remains the last authority
boundary.

Closing the desktop application is not implicitly the same as cancelling a running
experiment. An unexpected process exit is treated as a crash: durable job and
decision rows survive, leases expire, and restart recovery either resumes an
idempotent phase or marks a non-replayable external attempt for operator review.
Discarding an unfinished experiment-builder draft is a separate frontend lifecycle
rule and must not delete or cancel an experiment that was already created.

If a cancel request races with a dispatch transaction, the row lock establishes one
linear order. A committed dispatch may cancel still-pending trials through the
existing job cancellation path; an uncommitted dispatch loses to cancellation.

### 13.6 Integration with the current polling runner

The current worker tick starts queued jobs, claims one pending Trial, and then calls
`finalize_ready_jobs()`. That finalizer selects `RUNNING`/`AGGREGATING` jobs, or a
stale `FINALIZING` lease, and today performs aggregation plus the next optimizer/LLM
proposal. Merely adding a Harness call inside that function would create two bugs:

1. a Job represented as top-level `RUNNING` but `optimization_paused` would be
   selected again and unintentionally resumed;
2. a long provider/tool phase could outlive the existing Job `updated_at` finalizing
   lease and be reclaimed even though its Decision lease is still authoritative.

Refactor the tick into five independently restartable stages:

```text
start_queued_jobs
claim_and_run_one_pending_trial
aggregate_ready_generation_and_create_decision_intent
advance_one_optimization_decision
finalize_stopped_or_exhausted_job
```

`aggregate_ready_generation_and_create_decision_intent` runs one short transaction.
It compiles/reconciles newly complete immutable Candidate outcome envelopes, appends
resolvable delayed reward/cost events, freezes both snapshot intents and the routing
opportunity, inserts the unique unresolved Decision, and sets
`current_phase=optimization_deciding`. It never calls a provider or proposal tool.

`advance_one_optimization_decision` claims the Decision's own lease and advances one
durable phase. Provider/tool work occurs outside transactions under that lease.
Dispatch returns the Job to `current_phase=trial_execution`; stop acceptance hands it
to final report construction. The old Job finalization lease remains for report
finalization but is not reused as a model/tool lease.

Eligibility queries must explicitly exclude a Job that:

- has an unresolved Decision already;
- has `current_phase=optimization_paused`;
- has `cancel_requested_at` set;
- is terminal.

Version 1 permits pause only at a generation boundary, after all trials in the
generation are terminal and before new reservations are committed. Therefore a
paused Job has no pending/running Trial. The Trial claim query still joins or
rechecks the owning Job as defense in depth so no future code path can execute a
Trial for a paused, cancelled, or terminal Job.

Resume is an explicit endpoint with an expected Decision `state_version` and, when
needed, a fresh non-secret session credential reference that is exchanged into a new
Job binding:

```text
POST /api/v1/jobs/{job_id}/optimization/resume
```

It clears the pause phase and requeues the same Decision or creates the precisely
specified fallback transition; it does not create a second unresolved Decision.
Repeated resume requests are idempotent. A pause timeout is evaluated by a separate
policy transition and never by treating an old `updated_at` value as consent to
resume.

### 13.7 Admission, backpressure, fairness, and queue lanes

The current runtime does not use Valkey as a durable task broker. Valkey publishes
worker presence; SQL Job and Trial rows are the actual queue of record. Each current
tick starts up to ten queued Jobs, each initialization can insert a generation of
Trials, the same process then executes at most one globally oldest pending Trial, and
only afterward attempts finalization. This creates three concrete risks:

1. Job initialization can create pending work faster than one local simulator consumes
   it;
2. one large, older Job can place many older Trial rows ahead of a small, newer Job;
3. slow provider, proposal, aggregation, or report work in one polling loop can cause
   head-of-line blocking for unrelated stages.

The target keeps SQL as the canonical durable queue and uses Valkey only for
best-effort wakeups and liveness. Losing a wakeup may add polling latency but cannot
lose, duplicate, or authorize work. Do not introduce a second message-queue truth that
must be reconciled with Decision/Trial state.

#### 13.7.1 Separate bounded work lanes

Each existing domain row is its own durable work item:

| Lane | Queue-of-record row | Capacity unit | External side effect |
| --- | --- | --- | --- |
| admission/initialization | `jobs` | initialized Jobs and pending generation rows | none |
| evidence/Decision creation | `jobs` + `optimization_decisions` | aggregation CPU/DB slot | none |
| provider | `optimization_decisions` provider-call intent; `optimization_model_attempts` only after slot acquisition | provider request + token/currency ceiling | one provider request |
| proposal | `optimization_tool_calls` | executor child CPU/memory slot | one pure tool child |
| simulation | `trials` | host/instance/port/work-directory slot | one simulator process tree |
| report | `job_reports`/Job report intent | report CPU/artifact slot | bounded artifact writes |

Every lane has release-configured:

- maximum active leases;
- maximum ready rows globally and per Job/user;
- maximum request/input/output bytes;
- queue-age and execution deadlines;
- maximum infrastructure attempts;
- a documented overload response;
- a finite priority-class catalog and fairness-policy revision.

These limits are server/runtime policy and cannot be raised by a Job, model plan, tool
argument, or provider response. There is no unbounded Python queue, thread-pool queue,
socket backlog, SDK retry queue, or in-memory callback list hidden behind the durable
rows. The proposal broker and provider gateway use small bounded accept backlogs and
return typed `executor_busy`/`gateway_busy` without starting work.

One process may host several lane pollers in development, but each poller has an
independent concurrency semaphore, health signal, and crash boundary. Production WSL2
uses separate services or supervised processes for orchestration advancement,
simulation, and reporting; provider and proposal execution already have their
dedicated gateway/executor boundaries. A slow provider does not consume a simulation
slot, and a long simulator does not prevent cancellation, health, or Decision
reconciliation.

#### 13.7.2 Admission and bounded debt

Job creation computes both algorithmic worst-case budgets and **operational admission
cost**. The latter includes at least the first generation's maximum pending Trial rows,
snapshot bytes, unresolved Decisions, proposal calls, provider calls, and artifact
reservation. Future generations are not pre-created merely because the Job budget
allows them. They are materialized one bounded generation/window at a time after the
previous generation is terminal and the next capacity reservation succeeds.

The API accepts a Job only if its immutable contract is valid and the bounded durable
queue can hold it:

- `202 Accepted` means a durable Job/admission sequence exists;
- `429 Too Many Requests` means the authenticated user's configured queued/running
  quota is exhausted;
- `503 Service Unavailable` means the local/global Runtime is beyond its tested
  admission envelope;
- both overload responses include a bounded `Retry-After` and a stable reason code,
  but no client automatically retries without jitter and an idempotency key.

An accepted Job may wait, but it has `admitted_at`, `ready_at`, `queue_deadline_at`,
`not_before`, and queue-reason fields. Expired work is not executed merely to clear the
backlog. A queued Job whose user-visible objective is still meaningful may remain
pending; an expired provider/tool attempt is reconciled to a typed outcome and a fresh
attempt requires policy authorization. Queue limits are determined by load tests at
and beyond the throughput knee, not by arbitrary large defaults.

Budget reservation and capacity reservation are different:

- simulation/model budgets authorize total experiment spend;
- capacity leases authorize temporary use of a worker, child process, provider
  connection, or simulator instance;
- waiting for capacity consumes neither a physical provider attempt nor a Trial
  attempt;
- a worker acquires capacity before changing a row to externally running, and never
  holds an SQL transaction while waiting for a slot.

#### 13.7.3 Fairness and starvation resistance

Global oldest-row FIFO is insufficient. It lets a large Job monopolize the simulator
because all its generation rows may precede another Job. The scheduler uses a
versioned two-level policy:

1. select an eligible priority class fixed by trusted product/evaluation policy, never
   by prompt text;
2. within the class, perform deficit round-robin or equivalent virtual-finish-time
   scheduling across users and then Jobs, with a per-Job active-slot cap and bounded
   aging.

One scheduling quantum is a normalized resource unit, not simply one row: a long
full-SITL Trial, cheap mock Trial, provider request, and proposal child have different
configured costs and separate lanes. A Job cannot gain priority by splitting work,
creating more candidates, retrying, or choosing a slower tool. Cancellation,
credential expiry, emergency revocation, and health probes have a narrow control lane
that remains serviceable under data-plane saturation, but control work cannot dispatch
new optimization work.

The scheduler records `scheduler_policy_version`, class, admission sequence, virtual
finish/deficit before and after, selected capacity slot, queue delay, and skip reason.
This record is operational provenance, not model evidence. Confirmatory evaluation
uses its frozen block/randomization schedule above product fairness, logs all queue
delay separately from algorithm time, and never changes arm ordering adaptively after
seeing outcomes.

#### 13.7.4 Capacity leases and simulator identity

Add a small `runtime_capacity_slots` table. A configured row represents one trusted
resource such as:

- provider-call concurrency for a profile;
- proposal-child concurrency for an executor/runtime;
- one simulator host/instance with its PX4 instance ID, MAVLink/GCS ports, Gazebo
  partition/world identity, work directory, and artifact namespace;
- one report-build slot.

A slot stores resource class/key, immutable capability/runtime hashes, slot index,
owner kind/ID/attempt fence, lease owner/expiry, acquired/released timestamps, and
terminal release reason. Unique/check constraints prevent one live owner from holding
two copies of the same attempt and one slot from having two owners. The current
capability endpoint already admits that the local endpoint supports at most one
concurrent host workload without an instance allocator; Version 1 therefore creates
one real-SITL slot unless the explicit allocator and port/workdir isolation suite
passes.

Trial claiming is one short transaction that:

1. selects one fair eligible Job/Trial;
2. rechecks Job/Decision/cancellation eligibility;
3. conditionally acquires a compatible capacity slot;
4. increments the attempt fence and commits Trial ownership.

If no slot exists, the Trial remains pending and receives a bounded `not_before`; it is
not marked running while sitting in another queue. Lease heartbeat and stale-result
fencing remain as currently implemented. Provider and proposal lanes follow the same
shape, while their own gateway/executor still enforce independent hard concurrency and
resource ceilings.

#### 13.7.5 Retry delay, dead work, and shutdown

Retryable infrastructure failures set a durable `next_eligible_at` using capped
exponential backoff with jitter derived from the attempt id and policy revision. A
worker never sleeps while holding a Decision, Trial, slot, or database lock. Provider
`Retry-After` is treated as a lower bound only within the Job deadline and rate/cost
policy; many Jobs do not synchronize on one retry instant.

Per-attempt limits are not enough when many Jobs share one provider or executor.
Each remote provider profile/fingerprint and proposal-executor Runtime therefore has
a durable aggregate retry budget plus a versioned operational circuit:

- `closed` admits calls under lane capacity;
- `open_until` fails new acquisitions immediately with a typed dependency state;
- `half_open_probe` admits exactly one fenced call while all other work remains
  waiting or follows its pre-frozen fallback;
- a successful probe closes the circuit; a qualifying failure reopens it with a
  bounded cooldown.

The policy names its rolling window, minimum sample count, failure classes, thresholds,
cooldown schedule, and maximum aggregate retries. Provider authentication errors pause
only the affected credential binding; schema/semantic plan rejection is a model or
contract outcome, not provider-health evidence; user cancellation and stale fences are
not dependency failures; `429` follows the bounded `Retry-After`/rate-limit state.
Tool Candidate quality and routing reward never change an operational circuit.
Transitions are transactional, append a bounded event, and are visible to admission,
readiness, and the next immutable routing opportunity. The model cannot open, close,
probe, or override a circuit.

This distinction follows Microsoft's official guidance that retry handles transient
faults while a circuit breaker stops calls likely to keep failing, and that a
service-wide retry budget is needed because small per-request retry counts can still
form a retry storm:
[Circuit Breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
and
[Transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults).

After the frozen infrastructure-attempt limit, work reaches a typed terminal failure
such as `PROVIDER_RETRY_EXHAUSTED`, `EXECUTOR_UNAVAILABLE`, or
`SIMULATOR_INFRASTRUCTURE_FAILED`. It stays in the domain ledger and contributes to
intention-to-run evaluation. There is no anonymous dead-letter queue that loses Job,
budget, attempt, or provenance context. An operator re-drive creates a new audited
attempt under the same immutable Job contract and current remaining budget; it never
changes a terminal row back to “never happened.”

Graceful shutdown first stops admission and new claims, then marks lane health
`draining`, propagates cancellation to owned children, waits only for a configured
grace, persists ambiguous external-call state, and lets remaining leases expire for
fenced recovery. Startup reconciles expired slots before claiming work. A service does
not advertise ready merely because its process is alive: readiness requires database,
verified runtime, required lane capacity, and gateway/executor dependencies to be
within their tested operating envelope.

#### 13.7.6 Lock order and dialect behavior

No transaction locks more than one Job. When rows must be locked, every path uses:

```text
Job → Decision → ModelAttempt/ToolCall/Candidate/Trial → RuntimeDependencyState
    → CapacitySlot → Event sequence
```

Cancellation, dispatch, completion, retry, and lease-recovery code obey the same
order. External I/O, child waits, sleeps, hashing large artifacts, and report rendering
occur after commit. PostgreSQL consumers may use `FOR UPDATE SKIP LOCKED` only on
queue-like eligibility reads and must still apply the conditional update/fence; it is
not used to obtain a consistent analytical view. SQLite uses short conditional
updates, the configured busy timeout, small claim batches, and a single-writer-aware
capacity ceiling. Both dialects must produce the same legal state transitions, even
though their contention strategies differ.

Sources:

- [AWS Builders' Library: Avoiding insurmountable queue backlogs](https://d1.awsstatic.com/builderslibrary/pdfs/avoiding-insurmountable-queue-backlogs.pdf)
- [AWS Builders' Library: Using load shedding to avoid overload](https://builder.aws.com/content/3Eun1EEyX6p2e3VYNyRLSJzLuMV/using-load-shedding-to-avoid-overload)
- [Google SRE: Queue management and load shedding](https://sre.google/sre-book/addressing-cascading-failures/)
- [PostgreSQL: `SKIP LOCKED` for queue-like tables](https://www.postgresql.org/docs/current/sql-select.html)

## 14. Data model

The ten new Harness-domain tables, one immutable Trial-attempt evidence table, and
one generic API-idempotency table are additive, but the existing `jobs`, `trials`,
`trial_metrics`, `artifacts`, `job_events`, and `candidate_parameter_sets` tables
also need columns. Add to `jobs`:

- `orchestration_schema_version`, `orchestration_mode`, `fixed_algorithm_id`, and
  `fallback_policy`;
- immutable redacted `orchestration_config_canonical_json` and its hash;
- immutable routing-policy, exploration-policy, attribution-policy, tool-availability,
  and `PortfolioRewardContractV1` revisions/hashes;
- immutable `optimization_outcome_contract_canonical_json` and hash, including the
  registered metric dependency graph, scenario population/weight semantics,
  case-within-replicate aggregation order, non-success/missingness/censoring rules,
  risk estimators, outcome constraints, objective representation, fixed transforms,
  scalarization or Pareto-reference policy, tie-breaking, acceptance projection,
  validation promotion, and final-selection rules;
- `max_model_calls`, fixed-scale `max_model_cost`, and optional fixed-scale
  `max_fidelity_cost`;
- `admitted_at`, monotonic `admission_sequence`, `ready_at`, `not_before`,
  `queue_deadline_at`, finite `scheduler_priority_class`, `scheduler_policy_version`,
  virtual-finish/deficit state, `last_served_at`, and current queue-reason code;
- immutable `model_binding_canonical_json`/hash (requested alias/snapshot, observed
  identity/fingerprint, normalized generation settings, profile/SDK/adapter revisions,
  capability-probe reference, and reproducibility class), provider-profile and
  tool-allowlist snapshot hashes, plus a mutable current non-secret
  `active_job_credential_binding_id`, `credential_binding_revision`, and
  `credential_binding_changed_at`; no session reference, raw credential, or bearer
  token;
- immutable `harness_runtime_manifest_digest`, verified release-manifest/signature
  identity, build-provenance attestation digest, activated runtime slot ID, and
  registry/prompt/compiler/policy digests resolved from that manifest rather than from
  client input;
- immutable `parameter_contract_bundle_digest`, exact PX4 binary/image and generated
  upstream-metadata digests, DroneDream catalog-overlay/constraint-graph/domain-compiler
  digests, firmware build-provenance subject, observed component-metadata digest,
  baseline-profile digest, and parameter-isolation/application-policy revisions;
- search/validation/final-test contract commitments, sealed final-test reference,
  frozen-winner Candidate/hash, `winner_frozen_at`, and final-verification terminal
  state, plus the frozen winner's `CandidateOutcomeEvidenceV1` ID/hash and
  lexicographic selection-key hash under the search/validation selection checkpoint,
  and a distinct terminal final-test outcome-envelope ID/hash written only by the
  sealed verifier; the ordinary orchestration worker never receives the sealed
  final-test material;
- immutable search/validation seed-derivation contract/hash, random-domain registry
  hash, campaign scheduling-seed commitment, and repeatability policy; final-test
  entropy/substreams remain inside the sealed final-test contract and are disclosed
  only to the narrow materializer after winner freeze;
- `cancel_requested_at`;
- `next_event_sequence`;
- a compatibility-derived `optimizer_strategy` value retained for old filters and
  exports.

These fields make cancellation, budgets, compatibility mapping, and event cursors
durable. They are not reconstructed from the latest Settings UI after a restart.

Add to `trials` the compatible capacity-slot ID/fence, `ready_at`,
`next_eligible_at`, `queue_deadline_at`, queue-attempt count, normalized scheduler
cost, queue/skip/overload reason codes, scenario role, scenario-instance ID/hash,
seed-derivation-manifest hash, intended common-random-number block ID, accepted
physical-attempt ID, closed outcome class/reason, and evidence-acceptance
timestamp/hash. Also add the complete compiled parameter-vector/lattice-index hash,
parameter contract bundle digest, intended baseline-profile digest, and required
application profile; the immutable optimization-outcome-contract digest,
scenario-population cell ID, replicate/block ID, expected metric roles, and intended
contribution to the hierarchical estimand. Existing
`queued_at`, worker/lease, `attempt_count`, and status fields remain authoritative for
logical work. A waiting Trial has no capacity slot and does not increment
`attempt_count`; the atomic claim writes both.

Add to `trial_metrics` the accepted physical-attempt ID, metric-contract ID/hash,
verifier ID/revision, canonical unit/frame/time-axis IDs, canonical observation JSON
and hash, telemetry/source-artifact hashes, coverage report, and evidence precision.
Each row names one registered atomic metric node and its dependency-input hashes; it
does not store an optimizer-specific normalized value, penalty, or scalarization.
The existing scalar columns remain indexed compatibility projections of the accepted
observation; a database trigger or application reconciliation verifies they equal the
canonical envelope. Remove all missing-field defaults from the Harness write path.

Add to `artifacts` a physical-attempt foreign key, immutable content SHA-256,
source-role enum, media-type revision, verification state, and retention class.
Durable object keys include the attempt ID and content digest. Size/path alone are
not evidence identity, and one attempt never overwrites another attempt's bytes.

### 14.1 `optimization_decisions`

Recommended fields:

- `id`, `job_id`, `generation_index`, `attempt`;
- `status`, `orchestration_mode`, `fallback_policy`;
- `state_version`, `state_version_before`, `state_version_after`;
- `model_evidence_snapshot_id`, `model_evidence_snapshot_hash`;
- `optimizer_dataset_snapshot_id`, `optimizer_dataset_snapshot_hash`;
- `tool_registry_version`, `tool_registry_hash`;
- provider-profile/model-binding hash, requested alias/snapshot, returned model
  identity/fingerprint, and approved origin;
- normalized model request configuration, endpoint API family, capability-probe ID/hash,
  probe expiry, and reproducibility class;
- `prompt_template_version`, `prompt_hash`;
- `accepted_model_attempt_id`, `accepted_provider_response_hash`;
- `normalized_plan_json`, `validator_report_json`;
- `compiled_plan_json`, `compiled_plan_hash`, `compiler_revision`;
- immutable routing-opportunity ID/hash, routing-policy revision, selected-action hash,
  logged-action-probability state/value when valid, and policy/exploration/discretionary
  allocation summary;
- `physical_trial_slots_reserved`, `fidelity_cost_reserved`,
  `physical_trial_slots_committed`, and `fidelity_cost_committed`;
- aggregate `input_tokens`, `output_tokens`, `cached_tokens`, `estimated_cost`;
- `latency_ms`, `error_code`, `fallback_reason`;
- `lease_owner`, `lease_expires_at`;
- current lane, `ready_at`, `next_eligible_at`, queue deadline, queue-attempt count,
  queue/overload reason, and last capacity-acquisition outcome;
- `terminal_at` and other timestamps.

Use an ordinary unique constraint on `(job_id, generation_index, attempt)` and a
partial unique index on `(job_id, generation_index) WHERE terminal_at IS NULL`.
The latter is the actual protection against two live orchestration decisions.
`attempt >= 1`, non-negative token/cost fields, and legal terminal timestamp/status
combinations are named check constraints.

### 14.2 `optimization_model_attempts`

One logical decision may have more than one physical provider attempt only for a
transport retry of the exact same canonical request. Store:

- `id`, `decision_id`, and `attempt_ordinal`;
- request, prompt, function-schema, snapshot, and tool-registry hashes;
- requested model alias, requested immutable snapshot when available, provider-returned
  model identifier, observed model/system fingerprint when exposed, and the
  capability-probe record/hash authorizing this attempt;
- non-secret Job credential-binding ID and revision, launch/tenant binding hash,
  provider-profile hash, and model-binding hash used for this physical attempt;
- random gateway attempt nonce, gateway consumption state, and the exact
  state-fence value asserted by the orchestration worker;
- stable logical provider-idempotency key, gateway request ID, and provider request ID
  when returned on success or error;
- request reservation, transmission-start, response-header, response-complete, and
  terminal timestamps;
- capacity-slot reference/fence and provider-lane queue delay captured when the
  physical attempt is reserved;
- `status`, HTTP status, retry classifier, finish reason, refusal/protocol/error code;
- redacted response hash and optional bounded encrypted debug envelope;
- input, output, cached, and reasoning token counts when available;
- `usage_confidence` (`provider_reported`, `estimated`, or `unknown`), estimated lower
  and upper token/currency cost, price-catalog revision, and reconciliation state;
- request/response byte counts, retry delay, endpoint-address-set hash, and gateway
  transport revision;
- start/end timestamps and latency;
- `accepted_as_plan_source` and `superseded_reason`.

Unique constraints cover `(decision_id, attempt_ordinal)` and a provider request ID
when one is guaranteed unique. Every physical network request is accounted for
exactly once, but the design does not falsely claim that every failure was billed or
that its usage is known. A complete provider usage object records
`provider_reported`; a deterministic tokenizer/price estimate records `estimated`;
a post-send timeout/disconnect without usage records `unknown` and retains its
conservative reserved upper bound. Rate-limit and other error responses record zero
cost only when the provider contract or returned usage proves zero rather than from
an HTTP-status assumption.

Exactly one attempt may be marked accepted; zero is valid when the decision falls
back or pauses. “At most one accepted” is enforced with a partial unique index on
`(decision_id) WHERE accepted_as_plan_source`; the state transition that accepts it
also stores the matching foreign key and response hash on the decision in the same
transaction.

### 14.3 `optimization_tool_calls`

- `id`, `decision_id`, `call_id`;
- `compiled_plan_hash`, `compiled_call_hash`, `allocation_authority`;
- `tool_id`, `tool_version`, `implementation_revision`;
- optimization-outcome-contract hash, tool-objective-adapter revision/hash, selected
  objective-representation enum, compatible estimand/risk/constraint capability
  report, and the exact input **search-role** `CandidateOutcomeEvidenceV1` set hash;
- `arguments_json`, `arguments_hash`;
- `status`, `attempt_ordinal`, `lease_owner`, `lease_expires_at`,
  `result_json`, and `result_hash`;
- `ready_at`, `next_eligible_at`, queue deadline, queue-attempt count, capacity-slot
  reference/fence, and queue/overload reason code;
- executor/runtime hash, wall and CPU duration, peak resident memory, observed process
  and thread counts, effective native-thread settings, exit cause, and `error_code`;
- `candidate_count`, `candidate_ids_json`;
- `idempotency_key`;
- timestamps.

Unique constraints: `(decision_id, call_id)` and `idempotency_key`.

### 14.4 `evidence_snapshots`

- `id`, `job_id`, `snapshot_kind`, and optional `paired_snapshot_id`;
- canonical bounded snapshot JSON for `model_evidence`, or canonical complete
  optimizer input for `optimizer_dataset`;
- `provider_visible`, which is true only for `model_evidence`;
- schema version;
- source maximum trial/event revision;
- experiment contract hash;
- optimization-outcome-contract hash, metric-DAG hash, and the ordered
  `CandidateOutcomeEvidenceV1` ID/hash set used to compile this view;
- content hash;
- truncation report;
- source-row reconciliation and data-quality report;
- creation timestamp.

Every decision references both snapshot kinds from the same source revision. The
paired hashes prevent a compact model view from being combined with a different
internal optimizer history after restart. `provider_visible` is redundant with the
kind by design and protected by a check constraint; it gives provider-boundary code
a fail-closed predicate instead of relying on a caller to remember naming
conventions. The paired snapshots need not contain the same role set: the optimizer
dataset contains search-role envelopes only, while the model view may add the one
policy-authorized validation-checkpoint projection. Their reconciliation report names
this deliberate difference; final-test evidence is illegal in both.

### 14.5 Candidate provenance

Add nullable foreign keys from `candidate_parameter_sets` to:

- `optimization_decision_id`;
- `primary_optimization_tool_call_id`.

Also add the immutable `current_search_outcome_evidence_id`/hash, outcome-contract
hash, objective-representation enum, registered raw/derived metric envelope hash,
feasibility-vector hash, risk-estimate hash, lexicographic selection-key hash, and
selection status. These are search-role compiler outputs. Validation-promotion and
final-test records reference their own exact role-specific envelope rather than
overwriting this pointer or a generic “current outcome.” No value can be authored by
an optimizer adapter or recomputed from whatever metrics happen to exist at report
time.

Persist the full envelope in `candidate_outcome_evidence`:

- `id`, `job_id`, `candidate_id`, evidence role (`search`, `validation`, or
  `final_test`), role-specific checkpoint/commitment digest,
  generation/source-revision fence, schema version, optimization-outcome-contract
  hash, and compiler/verifier revision;
- ordered expected, accepted, excluded, censored, and missing case-replicate cell
  manifests with reason codes and source Trial-attempt/metric-observation hashes;
- registered atomic metrics, dependency-DAG results, within-case estimators,
  across-case estimators, uncertainty/effective-sample evidence, risk estimates,
  outcome-constraint vector, objective representation, fixed transform inputs/outputs,
  and lexicographic selection key;
- the role-legal acceptance, promotion, or terminal final-verdict projection derived
  from that same canonical evidence rather than independently recomputed booleans;
- canonical envelope JSON/hash, input-reconciliation report, status, and timestamps.

Use a content-unique constraint on `(candidate_id, evidence_role,
checkpoint_digest, source_revision, optimization_outcome_contract_hash)` and require
the Candidate's `current_search_outcome_evidence_id` to match an accepted
**search-role** envelope for the same Candidate/Job/contract. Each validation-promotion
or final-test record likewise points to an accepted envelope of its required role.
Recompilation after new Trial evidence creates a new immutable row; it never
overwrites the envelope an earlier Decision consumed. Compatibility columns such as
displayed RMSE or `pass_rate` are projections with reconciliation checks, not
alternate sources of truth.

Add `candidate_proposal_sources`:

- `candidate_id`, `optimization_tool_call_id`, and result `candidate_ordinal`;
- canonical parameter/fidelity group hash;
- `is_primary`, `reward_eligible`, and credited reward share;
- optional `promotion_parent_candidate_id`;
- source/result hashes and timestamps.

Unique constraints cover `(candidate_id, optimization_tool_call_id,
candidate_ordinal)`. A partial unique index on `(candidate_id) WHERE is_primary`
enforces **at most one** primary source. SQL cannot express “every harness candidate
has at least one matching association row” as that index alone, so the atomic batch
gate inserts the candidate and all source rows together, selects the deterministic
primary, and refuses commit if the count is not exactly one. A reconciliation test
and startup audit detect any historical violation. Retain `optimizer_metadata_json`
for optimizer-native details, but do not make it the only relational provenance.
Retain `llm_response_json` only for backward compatibility and migrate bounded
provider envelopes to the decision table.

#### 14.5.1 `routing_opportunities`

One row is created before each generation allocation:

- `id`, `job_id`, `decision_id`, generation/state/source-revision fences;
- model and optimizer snapshot hashes, outcome/reward/exploration/attribution contract
  hashes, tool registry/runtime manifest hashes, and routing-policy/model-binding hash;
- canonical ordered eligible-action set with tool/adapter/fidelity/allocation/cost
  capabilities and a typed exclusion or availability state for every registered tool;
- policy-reserved allocation, discretionary capacity, total cost ceiling, and current
  incumbent Candidate/outcome-envelope hash;
- selected compiled-action hash, action-probability provenance/value when a validated
  DroneDream randomized policy produced it, or an explicit
  `deterministic_or_unknown_no_ope_support` state;
- canonical opportunity/action JSON and hashes, validator report, timestamps.

The row is immutable after action commit. Tool health changes create a later opportunity
or a separately ordered availability event; they never alter which actions were
available to an earlier policy.

#### 14.5.2 `routing_reward_events`

Reward is append-only and may arrive after later generations:

- `id`, opportunity/action/decision/tool-call/Candidate/source IDs;
- outcome-contract, Candidate-outcome-envelope, reward-contract, cost-catalog, and
  attribution-policy hashes;
- exact pre-outcome source-set hash, source-share rational, source role, planned and
  realized allocation role, requested/effective fidelity, and material-transform flag;
- reward state (`pending`, `eligible`, `unobserved`, `ineligible`, or `superseded`) and
  typed reason;
- feasibility transition, fixed-scale incumbent improvement, reliability, uncertainty,
  and bounded final reward components, without an opaque unregistered score;
- proposal CPU/memory, allocated/produced/accepted Candidate counts, physical Trial and
  fidelity-equivalent cost, provider cost when applicable, queue delay, and completion
  delay;
- reward checkpoint/source revision, canonical JSON/hash, compiler revision, and
  timestamps.

Unique constraints prevent duplicate reward for the same
`(opportunity, candidate, source, reward_checkpoint, reward_contract)`. Reconciliation
proves exact eligible source shares sum to one per Candidate and that all allocated
cost remains represented even when reward is absent. A separate materialized policy
summary may accelerate UI reads, but it is rebuilt from these events and never becomes
the audit source.

### 14.6 Runtime dependency state and capacity slots

#### 14.6.1 `runtime_dependency_states`

One Runtime-owned row represents the aggregate operational gate for a remote provider
profile/fingerprint or proposal-executor Runtime:

- `id`, deployment profile, finite dependency kind, stable resource key, provider
  profile/fingerprint or executor Runtime-manifest digest;
- circuit/retry-budget policy ID/hash and monotonic state version;
- state (`closed`, `open_until`, or `half_open_probe`), reason, opened/closed time,
  cooldown deadline, consecutive-open count, and last transition sequence;
- frozen rolling-window bounds plus qualifying success/failure counts by closed
  operational class; semantic-plan rejection, Candidate quality, cancellation, and
  stale work are not qualifying dependency failures;
- aggregate retry-budget capacity, replenishment revision, spent/reserved tokens, and
  next replenishment boundary;
- optional half-open owner kind/ID/attempt fence, lease owner/expiry, and the exact
  request/tool Runtime hash authorized as the sole probe;
- canonical transition input/output JSON and hashes, source-attempt sequence watermark,
  reconciliation status, and timestamps.

A unique constraint covers `(deployment_profile, dependency_kind, resource_key,
runtime_or_fingerprint_digest)`. Named checks require the half-open owner/lease fields
together only in `half_open_probe`, require an open deadline only in `open_until`, and
keep all counters non-negative. Acquiring a provider/executor capacity slot and
reserving a retry token rechecks this row under the same short transaction. A probe
result uses its fence and compare-and-swap; a late result can be audited but cannot
close a newer circuit epoch.

The current row is a mutable operational projection, while every transition remains
an append-only bounded event and every contributing physical ModelAttempt/ToolCall is
immutable. Startup rebuild/reconciliation replays attempts up to the stored watermark
and refuses readiness if the projection disagrees. It never infers a provider outage
from one user's invalid credential, and never converts a circuit transition into
optimizer reward or Candidate evidence.

#### 14.6.2 `runtime_capacity_slots`

Capacity rows are Runtime-owned infrastructure state, not Job-owned business rows.
Recommended fields:

- `id`, finite `resource_class`, trusted `resource_key`, `host_id`, and `slot_index`;
- capability, resource-profile, and Harness runtime-manifest hashes;
- optional typed simulator instance/port/partition/workdir identity;
- `status` (`available`, `leased`, `draining`, `disabled`, `quarantined`);
- polymorphic `owner_kind`, `owner_id`, `owner_attempt_fence`;
- `lease_owner`, `lease_expires_at`, `acquired_at`, `released_at`, and release reason;
- monotonic `slot_version`, health epoch, and timestamps.

Unique constraints cover `(resource_class, resource_key, host_id, slot_index)`. Named
checks require all owner/fence/lease fields together only while leased and forbid an
expired timestamp on a newly available row. An owner tuple is unique while live.
Because the owner may be a ModelAttempt, ToolCall, Trial, or report intent, release
uses the typed capacity service rather than an unsafe polymorphic cascade. Deleting a
Job first releases/quarantines its slots through the same authorized deletion
transaction; a startup reconciliation returns an expired slot only after verifying
that its fenced external process/request cannot still commit.

Static slot configuration is regenerated from the verified Runtime and operator
capacity policy. A model or API request cannot insert a larger slot. Dynamic hosted
workers may register slots only through authenticated worker identity and a
capability-attestation path; unverified heartbeats are advisory and never create
capacity.

### 14.7 `trial_execution_attempts`

This table records every physical attempt, including rejected, superseded, failed,
and accepted outputs. It is the missing bridge between the current logical `Trial`
row and reproducible evidence.

Recommended fields:

- `id`, `trial_id`, positive `attempt_count`, worker identity, lease fence,
  capacity-slot ID/fence, Runtime slot and manifest digest;
- exact Trial input, experiment, Candidate parameter, scenario, reference-track,
  metric-contract, simulator-adapter, seed-derivation-manifest, random-domain-registry,
  and requested repeatability-policy hashes;
- exact parameter-contract bundle, PX4 binary/image, generated and observed
  parameter-metadata, complete compiled parameter vector, baseline profile,
  application-policy, and constraint-graph hashes;
- scenario role (`search`, `validation`, `final_test`);
- scenario-instance and common-random-number block IDs; one typed binding record per
  outcome-relevant random domain with derived-seed hash, delivered value/hash,
  component/version/configuration identity, capability state, and request-bound
  readback/attestation hash;
- attempt status, closed outcome class/reason, trusted failure-classifier revision,
  retryability, and retry-parent attempt ID;
- process/phase start/end facts, simulation/wall time mapping, requested and achieved
  real-time factor, host/runtime nuisance-factor record, repeatability class,
  exit kind/code, cancellation and supersession facts;
- bounded canonical `TrialAttemptEvidenceEnvelopeV3` and hash;
- source ULog, canonical telemetry, artifact-set, verifier request, verifier output,
  and accepted metric-observation hashes;
- telemetry schema/unit/frame/time-axis IDs, sample/coverage/gap report, PX4/Gazebo
  identity, runner/extractor/verifier revisions;
- pristine writable-overlay identity, observed full control-relevant baseline/final
  parameter-snapshot hashes, component/system/protocol identities, arming/landed/mode
  state evidence, application transition/report hash, exact wire/readback values, and
  `ParameterApplicationEvidenceV2` hash;
- `verifier_status`, evidence rejection code, quarantine reason;
- `accepted_for_trial`, `accepted_at`, and terminal timestamps.

Unique constraints cover `(trial_id, attempt_count)` and the attempt-envelope hash.
A partial unique index on `(trial_id) WHERE accepted_for_trial` enforces at most one
accepted physical result. The parent transition inserts/finishes the attempt,
persists content-addressed artifacts, writes the accepted metric, and updates the
logical Trial in one fenced transaction. SQL cannot prove that the Trial's
`accepted_attempt_id` points back to the same Trial, so the service verifies it and
the startup reconciliation scans it.

An infrastructure retry creates another row under the same logical Trial. A stale
attempt remains immutable and cannot become accepted later. Deletion follows the
Job retention policy, but a report/export that claims reproducibility pins the
accepted attempt, source artifacts, verifier envelope, and Runtime manifest
together.

Seed-delivery, seed-readback, world/SDF/plugin configuration, realized wind/dropout
trace, and simulation-time-map artifacts use explicit source-role enums and immutable
digests. They are not buried in an untyped stdout blob. The service refuses a
`verified_bound` row unless the corresponding artifact set and target-component
identity are complete.

### 14.8 `api_idempotency_records`

This generic table closes the lost-response/restart gap at the user API boundary. It
is not a queue and does not replace domain uniqueness or state-version checks.
Recommended fields:

- `id`, `principal_type`, `principal_id`, optional `tenant_id`, finite `route_id`, and
  finite `operation`;
- a bounded idempotency-key hash, canonical request hash, request schema version, and
  optional target resource ID/expected state version;
- `status` (`in_progress`, `committed`, `rejected`, `reconciliation_required`);
- response schema/status/body hash plus a bounded canonical safe response or the
  authoritative created/changed resource reference;
- transaction owner/fence, `created_at`, `committed_at`, `expires_at`, and last exact
  replay time/count;
- Runtime/manifest and deployment-profile identifiers; no desktop launch key, bearer
  token, provider credential, raw debug export, or arbitrary header.

A unique constraint on `(principal_type, principal_id, route_id,
idempotency_key_hash)` gives one logical mutation. In one short transaction the API
inserts or locks the row, compares request hash and expected state, performs the
domain mutation, records the bounded result, and commits. An exact concurrent/retried
request waits/coalesces or returns the committed result. Changed bytes with the same
key fail `409`; an abandoned `in_progress` row is reconciled against domain state
before it can be retried and is never treated as permission to repeat an external
effect.

The table is principal-owned for authorization/retention but deliberately does not
cascade with a deleted Job: a short-lived tombstone must still answer an exact retry
of `DELETE` or prevent a duplicated create after its target row is gone. Cleanup uses
an explicit bounded retention policy after terminal reconciliation. Route-specific
domain constraints remain authoritative if this cache is unavailable.

### 14.9 Physical types, ownership, and deletion

The ledger must not rely on backend-specific JSON behavior for replay:

- canonical request, snapshot, plan, argument, and result payloads are stored as
  canonical UTF-8 `TEXT` plus SHA-256, even if a derived JSON column is later added
  for operator queries;
- high-value filter/join fields remain typed relational columns rather than JSON
  paths;
- token counters and byte counts use `BIGINT`; currency estimates use a fixed-scale
  decimal, not binary floating point;
- timestamps are UTC, but ordering and fencing rely on ordinals and `state_version`,
  never wall-clock equality;
- every constraint and index has a stable explicit name so SQLite batch recreation
  and PostgreSQL inspection produce reviewable schemas.

Ownership foreign keys for new rows use database `ON DELETE CASCADE` on:

- Job -> evidence snapshots and decisions;
- Decision -> provider attempts and tool calls;
- Job -> routing opportunities;
- Candidate -> candidate proposal sources and Candidate outcome evidence;
- Routing opportunity -> routing reward events;
- Trial -> physical Trial-attempt evidence.

Cross-reference foreign keys that preserve audit meaning use `RESTRICT`, including a
candidate's decision/tool provenance, a decision's paired snapshots, an opportunity's
committed decision/action, a reward event's Candidate/source/outcome-envelope/tool-call
references, and an accepted logical Trial's physical-attempt pointer. An owned row may
therefore have one cascading parent and several restricting audit references; the
authorized deletion service must remove the cross-reference leaves in a deterministic
order before it removes the owner.

Corresponding ORM relationships use `delete-orphan` only for the same single-owner
edges and are tested together with database cascades. SQLAlchemy distinguishes ORM
delete cascades from database `ON DELETE` actions, and database cascades require
explicit foreign-key enforcement; the current SQLite engine already enables
`PRAGMA foreign_keys=ON` on every connection. See the official
[SQLAlchemy cascade guidance](https://docs.sqlalchemy.org/en/20/orm/cascades.html)
and [SQLite foreign-key actions](https://www.sqlite.org/foreignkeys.html).

The current schema is not yet uniformly database-cascading: its existing foreign
keys omit `ON DELETE`, Job-owned collections mostly rely on ORM `delete-orphan`, and
artifacts use validated polymorphic ownership rather than a foreign key. Therefore
Version 1 does **not** claim that an arbitrary `DELETE FROM jobs` is sufficient. The
authorized job-deletion service first blocks new claims and fences all live work,
releases or quarantines Runtime slots, freezes an audit deletion manifest, and then
deletes in this logical order:

1. report/export pins and polymorphic artifact references;
2. routing reward events and Candidate-source cross-reference leaves;
3. Candidate outcome evidence, accepted-attempt pointers, metric observations, and
   physical Trial-attempt rows;
4. tool calls, model attempts, decisions, routing opportunities, snapshots, and
   Candidates/Trials;
5. the Job and then its unpinned content-addressed artifacts.

The transaction records the expected and actual count by table, while file/blob
cleanup is a separately idempotent, digest-addressed post-commit operation with a
tombstone. It never deletes a shared content-addressed blob while another retained
artifact reference exists. Short-lived API idempotency tombstones survive the Job as
described above. Runtime dependency-state rows survive Job deletion because their
window and circuit protect other Jobs; deletion only releases a half-open probe owned
by the deleted Job under its attempt fence. A completed deletion verifies that no
decision, model attempt,
tool-call, snapshot, Candidate-source, Candidate-outcome, routing-opportunity,
routing-reward, physical-attempt, metric, event, or live-capacity ownership row
remains. Direct standalone deletion of append-only ledger rows is not an application
operation.

### 14.10 SQLite and PostgreSQL migration plan

Current repository facts constrain the rollout:

- local/test defaults use SQLite, `DATABASE_AUTO_CREATE=true`, `create_all()`, and a
  small hand-written SQLite `ALTER TABLE` compatibility function;
- deployed PostgreSQL sets `DATABASE_AUTO_CREATE=false`, and the API image runs
  `alembic upgrade head` before Uvicorn;
- Alembic is already configured with `render_as_batch=True` for SQLite because
  non-trivial SQLite alterations require table move-and-copy;
- the current migration test covers a fresh SQLite upgrade to head and selected
  lightweight column additions, but not an upgrade from a populated release database
  containing the Harness tables, PostgreSQL parity, downgrade, or crash recovery.

The Harness schema is too interdependent for another hand-written lightweight
migration. It requires reviewed Alembic revisions:

1. create the ten Harness-domain tables, immutable `trial_execution_attempts`,
   artifact/registered-metric provenance, `api_idempotency_records`, named checks,
   ownership/cross-reference foreign keys, and ordinary indexes;
2. add nullable candidate provenance columns through `batch_alter_table`;
3. create dialect-specific partial unique indexes with equivalent
   `sqlite_where` and `postgresql_where` predicates;
4. leave historical candidates nullable and mark them `legacy_unattributed` in the
   versioned normalizer rather than inventing tool provenance;
5. deploy dual-read code before new-mode writes, then enable shadow writes, run
   reconciliation, and only then enable `llm_harness`;
6. remove legacy fields only in a later release after replay/export compatibility has
   been measured.

Alembic's official guidance explains that SQLite batch migration recreates a table,
copies its rows, drops the old table, and renames the replacement; it also warns that
enforced referencing foreign keys require special care during that workflow. The
revision must therefore be exercised against an actual populated prior-release
SQLite file, not only an empty database. See [Alembic batch migrations](https://alembic.sqlalchemy.org/en/latest/batch.html).

Packaged desktop releases must stop using `create_all()` as their upgrade mechanism.
Before the backend starts, a single migration launcher:

1. obtains an application-wide database lock and confirms no worker is running;
2. creates a consistent backup with Python/SQLite's online backup API rather than
   copying only the main file while a WAL may contain committed pages;
3. records the source Alembic revision and backup hash;
4. runs `alembic upgrade head` once;
5. runs `PRAGMA foreign_key_check`, an integrity check, schema inspection, and Harness
   invariant queries;
6. restores the backup and blocks startup if any gate fails.

Python documents that `sqlite3.Connection.backup()` produces a consistent backup
even while other clients access the database. For this release path, the launcher
still quiesces DroneDream first so it can also guarantee that no orchestration state
changes between backup and migration. PostgreSQL deployment keeps a separate
operator backup and one-shot migration task before new API/worker replicas; API
startup may verify the expected revision but must not let multiple replicas race to
migrate.

Required migration tests cover:

- fresh SQLite and PostgreSQL creation;
- populated current-release -> Harness-head upgrade on both backends;
- desktop backup, forced mid-migration failure, restore, and successful retry;
- all named checks, foreign keys, partial unique indexes, and query plans;
- old rows remaining readable without fabricated provenance;
- new rows rejecting two unresolved decisions, two accepted attempts, two primary
  sources, duplicate Candidate-outcome envelopes for one role/checkpoint, a Candidate
  search pointer aimed at validation/final-test evidence, duplicate routing rewards
  for one checkpoint, invalid source-share sums, orphan references, and mismatched
  snapshot, opportunity/action, Candidate/source/outcome, or Trial/attempt pairs;
- Runtime dependency state rejecting two half-open probes, negative retry/circuit
  counters, stale probe-fence closure, or a projection that cannot replay from the
  contributing physical-attempt watermark;
- service-level job deletion leaving zero owned Harness rows, zero live Runtime-slot
  or half-open probe ownership, zero dangling audit references, retained Runtime
  dependency/circuit state and idempotency tombstones, and no premature deletion of a
  shared content-addressed artifact;
- `alembic check`/metadata comparison after upgrade and a documented forward-fix
  path when downgrade would discard audit data.

### 14.11 Events

Continue using append-only `job_events` for polling-compatible UI diagnostics and
operational history. The current product does not have an event stream endpoint:
`GET /api/v1/jobs/{job_id}` embeds only the newest 25 events, newest first, and the
frontend treats each payload as opaque JSON. The Harness must not silently describe
that mechanism as streaming.

Add a non-null per-job `event_sequence`, allocated atomically from a
`jobs.next_event_sequence` counter in the same transaction as the state transition,
plus a unique `(job_id, event_sequence)` index. Backfill existing rows in stable
`(created_at, id)` order. New events use discriminated, versioned payload schemas
rather than an arbitrary dictionary, and contain references rather than full model
or tool content:

- `optimization_decision_requested`;
- `optimization_model_attempt_completed`;
- `optimization_plan_accepted`;
- `optimization_plan_rejected`;
- `optimization_routing_opportunity_frozen`;
- `optimization_tool_availability_changed`;
- `optimization_tool_completed`;
- `candidate_outcome_evidence_accepted`;
- `optimization_routing_reward_resolved`;
- `optimization_fallback_used`;
- `optimization_batch_dispatched`;
- `optimization_stop_recommended`;
- `optimization_stop_accepted`;
- `optimization_pause_requested`;
- `optimization_decision_cancelled`;
- `optimization_decision_superseded`;
- `trial_physical_attempt_started`;
- `trial_randomness_binding_verified`;
- `trial_randomness_binding_degraded`;
- `trial_physical_attempt_rejected`;
- `trial_evidence_accepted`;
- `validation_checkpoint_completed`;
- `optimization_winner_frozen`;
- `final_test_materialized`;
- `final_test_completed`.

Pre-freeze events contain no final-test case, seed, count, ID, or schedule. Final-test
events expose only the committed contract hash, aggregate terminal verdict, and
authorized audit references; they do not become model or optimizer input.

The existing `recent_events` field remains as a bounded compatibility view. A new
cursor endpoint reads by sequence:

```text
GET /api/v1/jobs/{job_id}/events?after_sequence=123&limit=100
```

It returns `next_after_sequence`, `has_more`, and events in ascending sequence order.
Because the event row and authoritative state change commit together, polling never
requires a second message-broker write. A later SSE/WebSocket adapter may tail the
same sequence, but no push transport is required for Version 1. Clients ignore
unknown event types and rely on typed summary fields for control state; events are
diagnostic history, not commands.

### 14.12 Schema and replay compatibility

Every persisted control-plane object uses an explicit semantic schema version. The
writer emits only the current version; readers support the current and one declared
previous version during a migration window. A major-version change requires a
migration or a version-specific reader. It must never reinterpret old JSON using the
latest schema by convenience.

Replay also pins executable behavior:

- JSON Schemas and canonicalization implementation revision;
- tool adapter source commit and locked dependency manifest;
- Python/runtime, OS, numerical-library, BLAS, thread-count, and hardware metadata;
- random seed derivation revision;
- simulator/runtime image digest;
- Trial-result/telemetry schemas, coordinate/time contract, source extractor, metric
  registry/verifier, failure classifier, and scenario-role/final-test materializer
  revisions.

Outcome and routing semantics are executable history, not display metadata. Replay
therefore also pins the exact:

- `OptimizationOutcomeContractV1`, metric dependency DAG, physical-to-preference
  transforms, case/replicate estimator, missingness/censoring/risk rules,
  constraint precedence, tie-breaker, and objective-adapter revision;
- `CandidateOutcomeEvidenceV1` compiler/verifier and all referenced atomic metric
  evidence;
- `RoutingOpportunityV1` eligible-action set, tool availability/circuit states,
  policy-reserved exploration, selected action, and action-probability provenance;
- proposal-attribution, `PortfolioRewardContractV1`, cost catalog, reward checkpoint,
  and delayed-reward compiler revision;
- Runtime dependency-circuit/retry-budget policy, qualifying-failure classifier,
  physical-attempt watermark, transition sequence, and half-open probe fences needed
  to reproduce why a call was admitted or rejected.

A historical current-release loss, portfolio score, generation-best value, moving
normalization, hidden failure threshold, or inferred strategy-string ownership is
never promoted into a target Candidate outcome or routing reward. A compatibility
reader may expose it only under an explicit `legacy_*` schema and
`not_comparable_to_harness_contract` label. Missing historical opportunity sets,
source sets, propensities, costs, or outcome envelopes remain unknown; migration does
not reconstruct them from later state. Consequently, old portfolio rows cannot enter
Harness reward learning, off-policy evaluation, or a cross-version leaderboard.

Randomized adapters must pass repeatability tests in the supported environment.
Numerical libraries can still vary across hardware or thread scheduling; a tool
declares `bitwise`, `tolerance_replay`, or `non_replayable` rather than promising
determinism it cannot provide. If the historical tool/runtime is unavailable, replay
returns `historical_runtime_unavailable`; it never substitutes the newest tool under
the old provenance.

## 15. Provider-neutral model gateway

Define an internal gateway:

```python
class OrchestrationModelGateway(Protocol):
    def capabilities(self) -> ModelCapabilities: ...
    def decide(
        self,
        *,
        instructions: str,
        evidence: EvidenceSnapshot,
        tools: Sequence[ToolDefinition],
        idempotency_key: str,
        timeout_seconds: float,
    ) -> ProviderDecisionEnvelope: ...
```

`ModelCapabilities` records:

- native function calling;
- strict schema support;
- parallel-call behavior;
- model snapshot support;
- request idempotency support;
- token usage reporting;
- data-retention mode;
- maximum request/response sizes;
- streaming behavior and usage reporting completeness;
- capability-probe revision, timestamp, and endpoint/model fingerprint.

### 15.1 Capability negotiation

- Native strict function calling is preferred.
- Schema-emulated tool calling is allowed only when explicitly enabled and labeled.
- If neither strict tool calls nor strict structured output is available,
  `llm_harness` cannot start.
- There is no silent downgrade to free-form JSON.
- Provider aliases are resolved to a recorded concrete snapshot when the provider
  exposes one.
- Version 1 uses a complete non-streaming response. Partial streamed arguments never
  enter the decision parser.
- A provider idempotency header is used only when advertised and verified. Without
  it, an ambiguous post-send failure is not assumed safe to retry; compare-and-swap
  accepts at most one valid plan for the decision and stores late responses as
  superseded audit records rather than executing them.

Version 1 still has one semantic model turn: the provider never receives tool output
or a request to revise its plan. A timeout or rate-limit retry, when enabled, sends
the exact same canonical bytes and stable provider idempotency key. It is a new
physical attempt in the model ledger, not a hidden free call. Any response body that
contains a model decision ends transport retry eligibility, even if that decision
later fails schema or semantic validation.

The gateway, not a nested provider SDK loop, owns physical retries. The current
legacy proposer passes `llm_max_retries` into the OpenAI Python SDK; with its default
DroneDream value of one, a single `generate()` call can produce two network requests
while the application observes only one call boundary. The official SDK also retries
timeouts and selected HTTP statuses automatically. Harness adapters therefore set
SDK `max_retries=0` and implement each retry as a separately persisted
`optimization_model_attempts` row. If an SDK or custom transport cannot disable or
surface every physical request, it fails provider conformance.

Retry eligibility is classified before another request is reserved:

- a failure proven to occur before any request bytes were sent is recorded as
  `not_sent`; its currency reservation may be released, but any retry receives a new
  attempt ordinal so connection/DNS failures remain observable;
- an explicit 408, 409, 429, or provider-declared retryable 5xx may receive one
  bounded retry when the provider profile permits it and attempt/cost budget remains;
- a timeout, disconnect, or process loss after request transmission is
  `outcome_unknown`. It retries only when the endpoint's idempotency behavior has
  passed conformance and the same stable idempotency key is reused. Otherwise the
  immutable fallback/pause policy applies;
- authentication, authorization, invalid request, strict-schema rejection, refusal,
  completed malformed content, and semantic-plan rejection never trigger a model
  retry;
- Version 1 never hedges duplicate concurrent provider requests.

`Retry-After` is honored only within a configured ceiling and the Job's total
decision deadline. The chosen delay, response status, retry classifier, and
profile-policy revision are persisted. Cancellation, credential expiry, provider
kill-switch activation, or a stale Decision fence wins before a retry reservation.

Provider capability is established by a versioned conformance probe, not by an
endpoint's self-description or an “OpenAI-compatible” label. The probe uses
non-sensitive synthetic inputs and tests:

- exact function name and call-ID preservation;
- strict required/additional-property behavior;
- nested enum, array, null, and size-limit behavior used by the production schema;
- refusal, truncation, multiple-call, and no-call envelopes;
- usage fields, finish reasons, timeout, and idempotency behavior;
- whether requested data-retention controls are actually supported.

Results are keyed by normalized origin, endpoint API family, model identifier, and
observable provider fingerprint, with an expiry. A new or drifted fingerprint blocks
`llm_harness` until the probe passes or the job uses a deliberately labeled
schema-emulated evaluation profile. Application semantic validation remains
mandatory even after a probe passes.

The normalized request configuration records model alias/snapshot, reasoning mode or
effort, temperature/top-p/seed when supported, maximum output tokens, tool choice,
storage/retention flags, timeout, and adapter revision. Unsupported fields are
explicitly `unsupported`; defaults are not reconstructed later from provider
documentation. A provider seed is only a recorded request parameter, never a promise
of deterministic output.

Model identity is an immutable binding, not a Settings display string. At Job creation
the gateway stores a `ModelBinding` containing:

- provider-profile revision and API family;
- requested alias and requested immutable snapshot, if the provider publishes one;
- provider-returned model identifier and observable model/system fingerprint;
- reasoning/generation/retention configuration and canonical request-shape hash;
- SDK/adapter/transport revision;
- capability-probe ID, result hash, expiry, and exact production-schema hash;
- reproducibility class: `snapshot_pinned`, `fingerprint_observed`, or
  `alias_only_unpinned`.

An alias is resolved before the first Harness decision. When an immutable snapshot is
available, product and confirmatory-evaluation modes request that snapshot directly;
they do not continue sending the moving alias. Official OpenAI model pages, for
example, distinguish aliases from snapshots and describe snapshots as the mechanism
for locking behavior. A returned model ID/fingerprint is evidence to record and compare,
not proof that a third-party provider's weights are cryptographically immutable.

Every physical response is checked against the Decision's binding before its plan can
be accepted. Drift includes a changed returned model/fingerprint, lost strict-schema
capability, changed response envelope/usage semantics, probe expiry, snapshot
retirement, or an unannounced adapter/provider profile change.

- In a confirmatory campaign, any drift quarantines the affected attempt and pauses the
  campaign block; no replacement model result is merged into the same arm.
- In product mode, the immutable Job policy chooses `pause_for_rebind`,
  `deterministic_fallback`, or `fail`. A new model may be bound only at a generation
  boundary after a fresh probe and explicit operator/versioned-policy transition.
- A retry of one Decision must use the same binding. It cannot route to a different
  model, region, provider, API family, reasoning mode, or schema for availability.
- Resuming an old Job whose snapshot is retired never silently follows its alias.
  Decision replay remains possible; a model rerun reports
  `historical_model_unavailable` unless an explicitly new comparison run is created.

Capability probes have a short configured TTL and are invalidated immediately by
profile/model/SDK/schema changes or a conformance failure. They use synthetic
non-sensitive inputs and a separate administrative probe budget. Passing a probe does
not guarantee semantic quality, and failing/expiring a probe never consumes a Job's
simulation budget.

When no immutable snapshot or stable fingerprint exists, the UI/report says
`alias_only_unpinned`; the run may still serve an explicitly permitted product mode,
but it cannot claim exact model reproducibility or enter a confirmatory campaign whose
protocol requires a pinned model.

Source:
[OpenAI GPT-5.4 model snapshots](https://developers.openai.com/api/docs/models/gpt-5.4).

### 15.2 OpenAI-compatible does not mean behavior-identical

An OpenAI-shaped HTTP endpoint may differ in schema enforcement, tool-call
semantics, token reporting, retries, or data handling. The gateway probes and
records capabilities rather than assuming them from URL shape.

The current legacy GPT path is not yet this gateway. `LLMProviderConfig` accepts an
absolute HTTP or HTTPS URL, rejects embedded credentials/query/fragment, and
`services/jobs.py` can require an exact-string `LLM_ALLOWED_BASE_URLS` match. It then
passes that URL to the official OpenAI Python client. That client's default HTTPX
client enables redirect following. A hostname string allowlist therefore does not,
by itself, prove that the connection, every retry, and every redirect target remain
on the intended public origin. The current custom-endpoint adapter also begins with
`json_object` rather than the strict production schema and, after a narrowly matched
HTTP 400, issues a second request without `response_format` and parses free-form JSON
locally. Local validation limits damage, but this is a legacy compatibility fallback,
not strict Harness capability negotiation.

### 15.3 Provider-origin and egress enforcement

Version 1 treats a provider endpoint as a versioned administrator-approved profile,
not a per-Job arbitrary URL. Built-in profiles cover official providers. Adding or
changing a custom profile is a privileged Settings operation that records:

- a canonical HTTPS origin and allowlisted API path prefix;
- provider adapter/API family and concrete model policy;
- accepted port, CA trust policy, authentication header name, and retention mode;
- DNS/IP policy and whether the profile is a specially labeled loopback development
  endpoint;
- a capability-probe result and expiry;
- the profile revision and fingerprint used by each physical attempt.

Normalization uses one standards-compliant parser and rejects userinfo, query,
fragment, control characters, ambiguous encoded delimiters, non-canonical IP
spellings, and every scheme other than HTTPS. Plain HTTP is accepted only for an
explicit loopback development profile that cannot be selected by a production Job.
The request builder owns the method, endpoint path, headers, and body. Neither model
output nor Job input can add a URL, proxy, cookie, redirect rule, authentication
header, or arbitrary provider header.

Before each physical attempt, the gateway resolves every returned IPv4 and IPv6
address and rejects loopback, link-local, private/RFC1918, unique-local, unspecified,
multicast, broadcast, carrier-grade NAT, documentation/test, and cloud metadata
destinations unless the exact category is authorized by the loopback development
profile. Validation occurs again after every fresh resolution; it is not a one-time
Settings check. A production profile fails closed if any usable answer violates its
policy rather than selecting a convenient public answer from a mixed set.

The address actually connected must be one of the addresses just validated for that
physical attempt. The transport preserves the canonical hostname for TLS SNI,
certificate hostname verification, and the HTTP `Host`/`:authority` value while
pinning the connection to that checked address. Connection pooling is partitioned by
profile revision and validated address set; a connection is not reused after the
profile, DNS set, or certificate policy changes. DNS pinning reduces the
check/use gap but is not claimed to eliminate every rebinding or resolver attack, so
deny-by-default network egress remains a second boundary.

The gateway uses a security-owned HTTP transport, whether or not the higher-level
provider SDK is used:

- `follow_redirects=False`; every 3xx response becomes
  `provider_origin_redirect`, its `Location` is redacted, and credentials are never
  retransmitted to a redirect target;
- `trust_env=False`; ambient `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`,
  `.netrc`, cookies, and environment-provided CA overrides cannot silently change the
  route or credentials. A deployment that requires a proxy configures one pinned,
  audited gateway proxy explicitly;
- TLS verification is mandatory, with no HTTPS-to-HTTP downgrade and no caller
  ability to disable certificate or hostname checks;
- connect, TLS, write, first-byte, read, and total wall deadlines are all bounded;
- request bytes, response headers, decompressed response bytes, nesting depth, and
  connection concurrency are bounded before provider parsing;
- the gateway's OS firewall, service sandbox, or hosted egress proxy allows only the
  approved provider destinations and denies metadata/internal networks.

For official providers, the gateway may supply a custom HTTP client to the official
SDK only if all controls above remain enforceable and conformance-tested. If an SDK
owns retries, redirects, DNS resolution, proxy discovery, or response buffering in a
way the gateway cannot observe and fence, the adapter must use the provider's
documented HTTP API through the security-owned transport instead. The goal is not to
reimplement a vendor SDK casually; it is to ensure the credential cannot leave the
recorded provider boundary.

Custom endpoints do not inherit the current free-form fallback. If the capability
probe cannot demonstrate the exact strict function/structured-output contract,
production `llm_harness` is blocked. A schema-emulated profile may exist only in an
explicit evaluation mode, is labeled in every report, and cannot silently become a
production fallback. Error pages, redirect targets, DNS answers, and transport
exception objects are never inserted into a prompt and are persisted only as bounded,
redacted typed diagnostics.

## 16. Prompt and context contract

The stable high-authority instructions state:

- the model is an optimization tool router, not the safety authority;
- the objective and constraints are immutable;
- only listed tools exist;
- only evidence references in the snapshot are valid;
- sealed final-test information is unavailable and must not be inferred;
- exact budget, call, retry, and stopping limits;
- required decision schema;
- typed failure behavior.

Experiment names, labels, imported descriptions, and simulator messages remain
application data. They are not sent to the provider unless a trusted normalizer
turns them into an enumerated, bounded field in the evidence schema, and they are
never concatenated into developer/system instructions.

The canonical request envelope is:

1. versioned static high-authority instructions;
2. canonical `EvidenceSnapshot` JSON;
3. canonical eligible `ToolDefinition` projections in stable tool-ID order;
4. policy-reserved allocations and exact discretionary budget;
5. the single strict `submit_generation_plan` function;
6. a fixed low-authority request to submit the next plan.

There is no conversational history. UI language does not change enum values, tool
contracts, or the canonical English optimization terminology. Any few-shot example is
synthetic, versioned, contains no real user/job data, and is added only after an
evaluation shows a repeatable gain. Prompt and tool-description changes receive new
versions even when the JSON schema is unchanged.

Do not require or persist private chain-of-thought. Persist:

- concise generation goal;
- evidence references;
- typed uncertainty;
- tool selection and allocations;
- short bounded rationale where needed for audit.

These fields are sufficient to inspect a decision without depending on hidden
reasoning text.

Version 1 has no free-form long-term agent memory. A decision sees only the current
job's derived evidence snapshot and trusted static tool documentation. Cross-job
learning belongs in an offline, reviewed model/prompt/tool release process; it must
not copy one user's raw trace or artifact into another user's prompt.

Tool-performance evidence includes the frozen credit-policy revision, full-fidelity
reward, feasibility, cost, fallback, duplicate, and sample-count fields. It never
collapses one lucky candidate into an unqualified claim that an optimizer is best.

Performance summaries use shrinkage/uncertainty and show exposure counts. Observed
reward is conditional on the contexts in which a tool was selected; it is not a
causal claim that the tool would outperform alternatives on the unobserved contexts.
Policy-reserved exploration supplies comparison data, while offline matched-context
analysis tests whether apparent routing gains survive selection bias.

### 16.1 Current prompt-boundary gaps

The legacy direct-GPT proposer is bounded by bytes and recursively drops non-JSON or
non-finite values, but `_safe_prompt_value()` is a structural copier rather than a
semantic trust boundary. The current prompt includes:

- the complete `scenario_suite_json` before emergency compaction, including arbitrary
  case `config` strings and legacy holdout case definitions/seeds;
- user-supplied vehicle identity strings and objective metric strings;
- database candidate IDs;
- a prior candidate `label` that may itself have been generated by the previous LLM
  response.

It correctly excludes legacy holdout Trial outcomes from `scenario_feedback` and maps
Trial failures to codes, but the fields above still make the current direct-GPT prompt
unsuitable as the Harness evidence contract. In particular, carrying an LLM-generated
label into the next model request is a small persistent-memory channel. Exposing
legacy holdout seeds also proves those cases are not a sealed final test, even without
exposing scores. Byte limits and “ignore malicious instructions” text do not repair
either problem.

### 16.2 Field provenance and taint policy

The Harness does not pass a recursively “sanitized” application dictionary. A
dedicated evidence compiler constructs a closed DTO field by field and assigns each
source one provenance class:

| Class | Examples | Provider rule |
| --- | --- | --- |
| `trusted_instruction` | versioned static policy and the single plan schema | developer/system channel only; source-controlled and hash-pinned |
| `trusted_catalog` | tool IDs/descriptions, metric enums, parameter names, capability enums | provider-visible only from the pinned local registry, never remote metadata |
| `validated_scalar` | finite bounds, normalized aggregate values, counts, uncertainty, remaining budget | provider-visible after range, unit, missingness, and provenance checks |
| `untrusted_text` | display name, scenario config text, world/airframe free text, imported labels, model rationale, simulator/log/error text | omitted in Version 1; future use requires a separately reviewed low-authority schema |
| `private_control` | user/job/database IDs, paths, URLs, seeds, credential/profile references | omitted; related only outside the provider payload |
| `sealed_test_secret` | final-test membership, definitions, seeds, outcomes, and verifier artifacts | absent before winner freeze and inaccessible to ordinary evidence queries afterward |
| `secret` | API/storage credentials, tokens, session material | gateway-only and never present in model/process payloads |

Provider-visible vehicle/scenario identity uses server-mapped catalog enums or an
`unknown_custom_profile` capability bit, not raw display strings. Objective and
failure names resolve through an allowlisted metric/error catalog before aggregation.
Unknown names block snapshot construction rather than becoming text. Scenario details
are typed numeric/boolean/enumerated factors; custom case dictionaries, notes, case
IDs, seeds, and legacy holdout/final-test flags never cross the boundary.

Previous model output can influence later evidence only through trusted application
effects:

1. its plan is validated and compiled;
2. proposal tools produce numeric candidates;
3. the simulator and metric pipeline produce typed observations;
4. a trusted aggregator recomputes bounded statistics.

Prior rationale, labels, response text, refusal text, and provider error content do
not return to the model. Tool errors become enumerated availability/outcome codes and
bounded numeric counts. Tool definitions are static local release artifacts; a
provider, plugin, database row, or previous model cannot rewrite their descriptions.

The compiler fails on an unknown DTO key, wrong provenance class, unresolved catalog
value, provider-visible text field, sealed-test source row, or missing unit. Canonical
serialization happens only after this validation. Redaction is defense in depth for
logs; it is not the mechanism that keeps disallowed fields out of the request.

### 16.3 Injection resistance is measured, not assumed

OpenAI's agent-safety guidance recommends keeping untrusted variables out of
high-authority messages and constraining data flow with structured outputs. NIST
describes agent hijacking as malicious instructions embedded in ingested data, and
OWASP notes that prompt injection has no known foolproof prompt-only prevention.
DroneDream therefore treats the model as potentially influenced even after context
minimization. Security comes from limited authority, strict schemas, compilation,
gates, and isolated pure tools; model refusal behavior is not a security boundary.

The adversarial corpus plants unique canaries and instruction-shaped strings in every
potential source:

- Job name, vehicle/world/airframe strings, objective metric, scenario case ID/config,
  imported JSON keys/values, and custom-track metadata;
- previous model label/rationale and malformed provider envelope;
- simulator stdout/stderr, failure detail, artifact name/path/content, metric-map key,
  and tool error/diagnostic text;
- remote provider HTTP error, header, redirect location, DNS name, and capability
  probe response;
- Unicode confusables, right-to-left controls, zero-width text, markup, encoded text,
  split payloads, and deeply nested combinations.

Tests first assert at the byte level that forbidden canaries, sealed-test material,
identifiers, and secrets are absent from the canonical request. Separate repeated
model evals then measure plan validity, unauthorized-tool/allocation attempts, tool
selection shift, fallback rate, and attack success by source and attack family.
Testing multiple attempts matters because stochastic success on any attempt is
operationally relevant. A provider/model/profile is rejected when either the
deterministic byte-boundary suite fails or its measured task-specific attack rate
exceeds the frozen release threshold.

## 17. Safety and security model

### 17.1 Threats

| Threat | DroneDream example | Primary control |
| --- | --- | --- |
| goal hijack | imported track label says to ignore limits | typed data boundary; immutable instructions |
| indirect prompt injection | arbitrary scenario config, prior model label, simulator error, or provider error contains instructions | closed evidence DTO; no untrusted text; byte-canary and repeated hijack evals |
| tool misuse | model allocates an incompatible optimizer | allowlist + capability validator |
| excessive agency | model attempts to run PX4 directly | no simulator/shell/write tool |
| privilege abuse | prompt obtains API key or storage credential | secrets never enter context |
| provider-origin SSRF/credential exfiltration | a custom base URL, DNS answer, redirect, or ambient proxy routes a keyed request to an internal or attacker-controlled service | approved immutable profiles; checked-and-pinned address; redirects/proxy discovery off; deny-by-default egress |
| improper output handling | model arguments become code or SQL | strict parse + semantic validation |
| resource exhaustion | repeated calls consume budget | separate model/simulation ledgers |
| tool resource exhaustion | numerical proposal hangs or oversubscribes BLAS threads | isolated bounded worker and typed timeout |
| queue debt and starvation | Job initialization creates Trials faster than one simulator drains them, or an older large Job monopolizes global FIFO | bounded admission and lane queues; one-generation/window materialization; per-user/Job caps; fair scheduler; queue deadlines; early typed overload rejection |
| local IPC spoof/replay/path confusion | another local process connects to the executor, replays a ToolCall, forges a result, widens limits, or supplies a symlinked snapshot path | pathname-socket ACL and kernel peer credentials; fixed service identities; single-use nonce/attempt/hash binding; bounded canonical frames; sealed descriptors or beneath-root no-link resolution; parent CAS |
| provider-gateway spoof/replay | another local process registers a key, forges a heartbeat, swaps a Job binding, replays an attempt, or impersonates the gateway | separate registration/call sockets; kernel peer credentials; per-launch MAC; Job/model/profile binding; one-use request tuple; client-side gateway peer verification |
| compromised authorized orchestration worker | the legitimate worker invents an unreserved attempt or lies about current Job state | explicitly outside the Version 1 local-desktop isolation claim; durable reservation/CAS and audit detect ordinary bugs, but hosted adversarial-worker scope requires an independently signed one-use grant or read-only authorization service |
| unauthenticated loopback API / cross-origin mutation | a local process, hostile page, or DNS-rebinding page calls create/cancel/delete/resume/export endpoints because the packaged backend maps every request to the default user | no packaged-desktop `/api/v1` TCP surface; Tauri-owned typed bridge to a permission-restricted Runtime socket; launch-bound request proof; durable mutation idempotency; per-operation ownership/state authorization; exact CSP/CORS only as defense in depth |
| telemetry exfiltration/cardinality denial | auto-instrumentation exports prompt, key, stacktrace, IDs, candidate vectors, arbitrary model/URL values, or creates one metric series per Job | canonical local ledger; content off; typed allowlists; canary processors; finite metric dimensions and series budget; exporter egress isolation |
| memory poisoning | bad run text persists into later decisions | derived typed evidence, no free-form memory |
| runtime supply-chain substitution | a mutable file, dependency, prompt, registry, compiler, gateway, or tool implementation differs from the code named in a Job | CI-produced signed Harness runtime manifest; digest-pinned release artifact and build attestation; startup file verification; read-only service view; side-by-side runtime slots; Job pins the activated manifest |
| provider model drift | provider model behavior changes mid-Job despite unchanged local code | immutable model binding; per-response identity check; probe expiry; pause/fallback on drift |
| replay/duplication | retry dispatches trials twice | idempotency keys + unique constraints |
| hidden-data leakage | validation/final-test material crosses its authorized phase | separate stores/query principals plus pre-freeze non-materialization |

### 17.2 Least authority

The model may request pure calculations. The application owns:

- job lifecycle;
- budget reservation;
- parameter projection;
- trial creation;
- simulator credentials;
- artifact access;
- acceptance decisions;
- final winner publication.

### 17.3 Secrets and privacy

The current implementation is an explicit migration risk:

- `ModelAccessProvider` writes the raw API key to WebView `sessionStorage`;
- `NewJob` copies it into React form state and sends it as `llm.api_key`;
- the backend encrypts it with the runtime-wide Fernet key and persists it in
  `job_secrets` until terminal cleanup or TTL;
- the packaged runtime generates that Fernet key once and stores it in
  `/etc/dronedream/runtime.env`;
- drafts correctly blank `llm_api_key`, but that does not remove the other client,
  transport, process-memory, and database exposures.

This behavior remains supported only for already-created legacy
`optimizer_strategy=gpt` jobs. Calling `sessionStorage` “memory only” would be false:
it is browser-managed storage, survives reloads within the page session, and is
readable by same-origin JavaScript. The Harness must not put a provider key in Web
Storage, a Job request, the application database, an argv vector, an environment
variable, a log field, or a durable message queue.

#### 17.3.1 Packaged-desktop credential flow

The target desktop flow uses a local, session-scoped **provider gateway**:

1. the password input exists in the WebView only while the user edits it;
2. confirming Settings invokes a narrow Tauri command and immediately clears the
   JavaScript field after success;
3. Rust passes the bounded secret through a one-shot stdin pipe to a fixed WSL2
   credential-registration helper—never through a shell, command argument, or
   inherited environment;
4. the helper sends it over a permission-restricted Unix-domain socket to
   `dronedream-provider-gateway.service`;
5. the gateway stores the raw value only in its own memory, binds it to the Tauri
   launch session, provider origin, model policy, user, creation time, idle expiry,
   and absolute expiry, and returns a random **session reference ID** to Tauri Rust
   plus a provider-profile hash/status safe for Settings;
6. when a Job is created, the authenticated orchestration service asks the gateway to
   derive a random non-secret **Job credential binding ID** tied to that Job/user,
   launch session, provider profile, and immutable model binding; Jobs and Decisions
   persist only this derived ID and pinned hashes, never the session reference;
7. after a physical-attempt row and currency reservation commit, the orchestration
   worker sends the exact Job binding, attempt/state fence, request hash, and budget
   ceiling to the gateway; only the gateway resolves the key and opens provider egress.

The reference ID is deliberately not a bearer credential. Possessing a database row
or copied reference is insufficient: the gateway also checks the active launch
session, local service identity, job/user binding, provider-profile hash, decision
attempt fence, origin allowlist, and model/token/cost limits. A true capability token
must not be persisted under the misleading name `credential_handle`.

`dronedream-provider-gateway.service` is separate from the API, orchestration worker,
simulator, and proposal-tool executor. It has the only provider egress permission and
no database write authority. It returns bounded provider envelopes after redaction;
the raw secret never returns to a caller. The proposal-tool executor has neither the
socket permission nor network access, so a selected numerical tool cannot obtain or
use the provider credential.

Tauri sends a per-launch heartbeat and explicitly revokes the session during normal
shutdown. The gateway erases secrets after a short missed-heartbeat grace period and
an absolute maximum lifetime even if Tauri crashes. Erasure removes the map entry and
best-effort zeroizes owned buffers; the threat model does not promise recovery-proof
erasure from swap, crash dumps, allocator copies, or a machine already controlled by
the local administrator. WSL2 service restart intentionally loses every desktop
credential.

If the app or gateway restarts and the reference is unavailable, an unresolved
Decision becomes `credential_unavailable` and follows the declared pause/fallback
policy. It never silently reuses a different key, profile, provider, or user's
credential. Resume requires the user to register a new reference, and the Decision
records that reference/profile revision changed without rewriting the old attempt.

#### 17.3.2 Gateway registration and call authorization

Credential registration and model invocation use separate pathname sockets and
protocols:

| Interface | Authorized caller | Allowed operations |
| --- | --- | --- |
| registration socket | fixed WSL registration helper with expected kernel peer credentials plus per-launch proof held by Tauri Rust | create launch session, register/replace key for an approved profile, heartbeat, revoke |
| provider-call socket | orchestration-worker service UID/cgroup only | derive one Job binding, execute one already-reserved physical attempt, cancel an in-flight attempt |

The API, WebView, simulator worker, proposal executor, tool children, and ordinary
frontend processes mount/access neither socket. Both clients verify the gateway socket
owner/type/mode and kernel peer identity; the gateway verifies caller credentials. The
sockets use separate fixed service groups, bounded canonical frames, one request per
connection, protocol versions, nonces, and length/hash checks equivalent to Section
9.6.1. Neither interface accepts a shell command, environment map, arbitrary URL/header,
database query, file path, or raw logging field.

Tauri Rust creates a 256-bit launch secret and keeps it outside JavaScript. A fixed
bootstrap/registration helper receives it and the bounded provider key only through a
one-shot stdin frame to a fixed `wsl.exe --exec` target. The executable, WSL
distribution, arguments, provider-profile ID, and maximum secret length are Rust
allowlists; WebView input cannot select a binary, distro, socket, URL, or command.
Registration and heartbeat messages carry an operation nonce, monotonic sequence, and
MAC under the launch secret. The helper clears owned buffers and exits. This reduces
accidental exposure but does not claim protection against a local administrator,
debugger, memory scraper, or already-compromised Tauri/WebView process.

The session reference retained by Tauri's credential broker cannot authorize a
provider request. Settings receives only approved-profile/status/revision metadata.
During Job creation the trusted desktop bridge injects the live reference outside the
WebView-authored canonical Job body and exchanges it once, over the provider-call
socket, for a random Job binding that the gateway maps to:

- launch/session and user;
- exact Job ID and immutable experiment-contract hash;
- provider-profile/origin and `ModelBinding` hash;
- creation/idle/absolute expiry and revocation state;
- maximum per-attempt request/output/tokens/currency plus remaining session ceiling.

The session reference is not persisted in the Job. Copying a Job binding from the
database still grants nothing to another process because the gateway also requires the
authorized peer and exact bound fields.

For each provider call, one short orchestration transaction first acquires compatible
provider capacity, reserves worst-case currency, and inserts an
`optimization_model_attempts` row in `reserved` state with that slot/fence, random
attempt nonce, canonical request hash, and model-binding hash. No attempt row is
created merely to wait for capacity. The worker then issues one
`execute_reserved_attempt` message. The gateway atomically consumes the tuple
`(job_binding_id, attempt_id, attempt_ordinal, attempt_nonce, request_hash)`. Completion,
typed pre-send failure, or ambiguous post-send reconciliation releases the capacity
slot with the same fence.

- Reusing it with different bytes is a security failure.
- An exact duplicate while in flight returns the same in-flight identity rather than
  issuing a second request.
- A completed duplicate returns only the already bounded/redacted envelope during its
  short gateway cache TTL; it never repeats the network call.
- Gateway restart intentionally loses the key/cache and returns
  `credential_unavailable`; the worker does not reconstruct or substitute a key.
- A changed Job/model/profile/contract hash, expired/revoked launch, exceeded gateway
  ceiling, invalid frame/MAC, or tuple replay with changed bytes is rejected before DNS
  or request transmission.

The gateway has no general database credentials or write access. In Version 1 it trusts
the authenticated orchestration service's assertion that the durable attempt remains
reserved, the supplied state fence is current, and cancellation has not won the race.
The gateway can enforce its own binding, ceiling, expiry, and single-use state; it
cannot independently prove those database facts. It refuses all operations outside the
narrow call schema and returns the consumed attempt nonce and asserted fence in the
response. Before accepting that response or dispatching anything downstream, the
worker must execute the authoritative compare-and-swap and cancellation checks from
Sections 13.3–13.5. A later hosted multi-tenant deployment must add an independent
read-only authorization view or a signed single-use attempt grant minted only after
reservation commit before treating a compromised worker as an in-scope adversary.

The gateway process runs under a separate non-login UID, has no shell/tool/simulator
entry points, a read-only root, private bounded memory, no inherited environment
secrets, and egress only to Section 15.3-approved destinations. Registration/call
socket abuse, nonce replay, heartbeat forgery, reference swapping, worker/gateway
restart, response forgery, and attempts to widen URL/model/budget must be release-gate
tests.

These socket/UID controls distinguish services **inside an untampered Runtime**. They
must not be cited as proof against a hostile process already controlling the same
Windows user and entering WSL as `root`; Section 17.3.7 states that residual boundary.

#### 17.3.3 Browser and hosted variants

Browser-only development may register a secret through an authenticated, CSRF-safe
HTTPS endpoint backed by the same gateway and retain only the non-secret reference in
React memory. It must not fall back to Web Storage. This mode is disabled on plain
HTTP except the explicitly labeled single-user local development profile.

Hosted deployment does not reuse the desktop session broker. It resolves an
administrator-approved tenant-scoped reference from a managed secret service, with
least-privilege provider scope, rotation, revocation, access audit, and expiry. A Job
stores only the managed reference's non-secret identifier and pinned metadata; raw
keys are absent from Job rows, backups, exports, and support bundles.

For every deployment:

- Prompts, traces, events, and artifacts never contain API keys.
- Provider requests use the Section 15.3 profile, DNS/IP, redirect, proxy, TLS,
  response-bound, and deny-by-default egress controls. The current exact-string
  allowlist is a migration input, not sufficient evidence of SSRF containment.
- Raw provider envelopes are bounded and redacted before persistence.
- Sanitization covers exception messages, chained exceptions, tracebacks, request
  objects, logs, and telemetry attributes; suppressing one displayed traceback is
  not treated as redaction.
- Full prompt/result content has a documented retention period and can be disabled;
  hashes and normalized decisions remain.
- Telemetry content fields are opt-in; operational metadata is the default.

The provider payload inventory is intentionally narrower than the database record:

| Data class | Sent to model | Persisted locally | Rule |
| --- | --- | --- | --- |
| typed search/authorized-validation aggregates | yes | with job | bounded, canonical, hashed, and phase-labelled |
| eligible tool manifests | yes | with decision | only trusted local definitions |
| user/job/candidate/database identifiers | no | relational records | provider view uses ordinals and hashes |
| sealed final-test definitions, seeds, or outcomes | no | verifier-owned records created after winner freeze | absent pre-freeze and inaccessible to ordinary snapshot queries |
| API keys and credentials | no | desktop gateway memory or hosted managed secret service | never copied into Jobs, traces, events, exports, or backups |
| Job credential-binding ID/profile hash | no | Job, Decision, and attempt metadata | non-secret locator; never sufficient by itself to authorize provider use |
| raw simulator logs/artifact URLs | no | existing artifact policy | expose only typed derived evidence |
| normalized model plan | provider produces it | with decision | bounded audit record |
| raw provider request/response content | only the request is sent | off by default | optional encrypted debug trace with TTL |

Local-desktop defaults are:

- retain evidence snapshots, normalized plans, validator reports, tool results, usage,
  and provenance for the lifetime of the job;
- do not persist raw provider content unless the user enables diagnostic tracing;
- when enabled, encrypt raw content at rest, cap it by bytes, and delete it after
  seven days unless it is explicitly exported for an incident;
- delete decisions, attempts, tool calls, snapshots, proposal sources, traces, and
  decision-owned artifacts through the authorized job-deletion transaction, using
  database cascades for owned Harness edges and explicit cleanup for current
  polymorphic/cross-reference edges;
- erase session-only API keys on normal exit, heartbeat expiry, gateway restart, and
  absolute TTL; any future persistent desktop credential uses the operating-system
  credential vault with an explicit opt-in, not Web Storage or the application
  database.

During migration, `job_secrets` remains readable only for already-created legacy
`optimizer_strategy=gpt` jobs and is purged by their existing terminal cleanup.
`llm_harness` creation rejects a raw `llm.api_key` field and accepts only a live
session reference injected by an authenticated transport for one-time exchange into a
Job credential binding. The session reference is never exposed to packaged WebView
state or committed in the Job. Rerun copies provider/model policy but never copies a
credential or binding; Tauri must attach a currently live reference again.

Hosted deployment must define its own retention schedule, tenant isolation, deletion
SLA, backup-erasure behavior, and provider-side retention contract before enabling
`llm_harness`. The Settings UI must identify the provider origin and whether its
zero-retention or training opt-out mode is verified, unsupported, or unknown.

#### 17.3.4 Desktop API caller authentication

The current packaged-desktop path has a security boundary that CORS does not close:

- `runtime/config/runtime.env.default` sets `APP_ENV=desktop` and
  `AUTH_MODE=disabled`;
- `get_current_user()` consequently provisions/returns the same
  `default@drone-dream.local` identity for every request;
- Uvicorn listens on `127.0.0.1:8000`, and the WebView calls that address directly;
- the production CSP and CORS configuration use explicit local origins, which is good
  browser hardening, but a non-browser client can omit/forge `Origin`; moreover, a
  browser can send some "simple" state-changing requests even when it cannot read the
  CORS response;
- `/api/v1/capabilities` currently has no user dependency, while Job, Trial, Batch, and
  Artifact routes do call `get_current_user`; in disabled mode that distinction does
  not authenticate the caller.

OWASP explicitly warns that `Origin` can be spoofed outside a browser and that CORS
does not replace application access control. Tauri likewise describes CSP as impact
reduction for WebView vulnerabilities and capabilities as the IPC authority boundary,
not as authentication for a separate loopback HTTP service. Therefore
`AUTH_MODE=disabled + bind(127.0.0.1)` is a development convenience, not a production
desktop authentication design.

The packaged target is **not** "put a long-lived bearer token in JavaScript." It is:

1. `AUTH_MODE=desktop_bridge` is mandatory whenever `APP_ENV=desktop`; configuration
   validation rejects `desktop + disabled`, `desktop + demo_token`, and any direct
   WebView credential mode. `disabled` remains available only in explicitly named,
   isolated test/development profiles.
2. The state-changing and private `/api/v1` application surface does not listen on a
   Windows-visible TCP port. Uvicorn or a small internal ASGI broker listens on a
   pathname Unix-domain socket owned by the API service, with mode, owner, type, and
   peer-credential checks.
3. Tauri Rust launches one fixed, long-lived
   `dronedream-desktop-api-bridge` process in the dedicated distribution without a
   shell. Rust and the bridge exchange bounded canonical frames over inherited
   anonymous stdin/stdout; the bridge alone connects to the API socket under a
   dedicated client UID/cgroup.
4. The WebView calls narrow typed Tauri commands. It never receives the API session
   key, an Authorization header, an arbitrary backend URL, a generic header map, a
   filesystem path, or a generic "fetch this" capability. Rust maps a finite
   `route_id` plus typed DTO to the canonical bridge frame and performs the request.
5. Artifact/CSV downloads use separate bounded Tauri commands that stream a
   user-authorized artifact to an application-owned temporary file or save dialog.
   They do not hand an unauthenticated download URL or bearer token to an `<a>` element.
6. Direct `connect-src http://127.0.0.1:8000` and API image sources are removed from
   the packaged production CSP after migration. Development web builds retain a
   separately configured bearer/OIDC HTTP client; the noVNC/Gazebo viewer, if enabled,
   receives an exact Runtime-derived origin and a sandboxed frame policy rather than
   inheriting a wildcard local-port API exception.

Rust creates a random 256-bit launch key and 128-bit session ID only after the signed
Runtime, API socket, bridge executable, and Harness manifest have passed readiness.
The bridge registers the session over a separate fixed registration operation. The API
keeps the key only in a bounded in-memory registry containing:

- protocol and key version;
- session ID and Runtime installation-owner principal;
- Tauri launch ID, Runtime ID, Harness manifest digest, and bridge service identity;
- creation, last-use, idle-expiry, and absolute-expiry times;
- revocation state and bounded replay/idempotency-cache accounting.

The Runtime installation has one stable random `desktop_owner_id`; it becomes
`(identity_provider=urn:dronedream:desktop, external_subject=desktop_owner_id)` in the
existing user model. It is not a secret, email, Runtime build ID, provider session
reference, or authorization token. Session authentication proves the launch; the
installation owner provides stable local data ownership across launches. Neither value
is accepted from a WebView body.

The desktop API launch key is distinct from the provider-gateway launch key. Separate
HKDF context labels, protocol versions, sockets, service identities, and revocation
records prevent one bridge compromise from becoming a provider credential
registration proof. The WebView and desktop API bridge cannot call the provider
gateway; the orchestration service still uses Section 17.3.2's provider-call boundary.

#### 17.3.5 Request proof, replay, and response binding

Every desktop bridge request uses a closed frame rather than raw HTTP:

```text
DesktopApiRequestV1 {
  protocol_version,
  session_id,
  request_id,          // random 128-bit value, bounded encoding
  issued_at_ms,
  route_id,            // finite enum, not a URL
  operation,           // finite enum derived from route_id
  path_parameters,     // schema-bound IDs only
  query_dto,
  body_schema_version,
  canonical_body_sha256,
  expected_state_version?,
  idempotency_key?,    // required for mutations
  runtime_id,
  harness_manifest_digest,
  mac
}
```

The HMAC covers a domain-separation string and the length-prefixed canonical bytes of
every field, including route, operation, path/query/body hash, expected state version,
Runtime, manifest, time, session, and request ID. The API:

1. bounds the outer frame before allocation and rejects unknown/duplicate fields;
2. verifies socket type/owner/mode and kernel peer credentials;
3. resolves the in-memory session and compares Runtime/manifest/bridge identity;
4. checks HMAC in constant time, a short issue-time window, idle/absolute expiry, and
   revocation;
5. atomically consumes or coalesces the request ID;
6. recomputes canonical body bytes and hash after strict schema parsing;
7. authenticates the principal, authorizes the specific operation/resource/current
   state, and only then opens the database transaction.

This borrows the useful properties of proof-of-possession protocols without claiming
to implement OAuth DPoP: RFC 9449 binds a proof to an HTTP method/target, issue time,
unique identifier, and optional nonce, and recommends short acceptance windows plus
single-use identifier tracking for replay resistance. DroneDream additionally binds
the canonical body and state version because local Harness mutations are not ordinary
OAuth resource requests.

An exact retry with the same principal, `route_id`, idempotency key, and request hash
returns/coalesces the already committed result; it does not execute the mutation
again. Reusing a request or idempotency key with different bytes is
`409 IDEMPOTENCY_CONFLICT` and a security event. Short-lived read coalescing may stay
in memory, but every create/cancel/delete/resume/redrive/provider-binding/export
mutation uses the durable `api_idempotency_records` ledger in Section 14.7 so a lost
response or backend restart cannot duplicate an effect. Expiry never removes an
in-progress record; cleanup is bounded and applies only after the operation's
reconciliation/retention window.

Response frames carry the request ID, HTTP/application status, response schema version,
canonical body hash, Runtime/manifest identity, and a response MAC. Rust verifies all
of them before releasing a typed value to JavaScript. A truncated frame, wrong request
ID, wrong schema, changed Runtime, or forged/late response fails closed. Application
error bodies never echo the request MAC, session key, raw provider envelope, or
rejected secret-bearing input.

#### 17.3.6 Operation authorization and hosted identity

Authentication only names the caller. Every endpoint must also enforce an
operation-specific policy locally:

| Operation class | Required authorization |
| --- | --- |
| list/read Job, Decision, ToolCall, Trial, report, event, or artifact | resolve through authenticated `(tenant_id?, user_id, job_id)` ownership before child ID; return the same not-found shape for absent and foreign objects |
| create Job/Batch | authenticated owner, admitted Runtime/profile, server-derived owner/tenant, idempotency key, immutable contract/budget validation, and live credential-reference exchange only when Harness mode needs it |
| patch/cancel/resume/redrive/rerun | owner permission, allowed finite-state transition, `expected_state_version`, durable idempotency, budget/credential/capacity policy, and cancellation precedence |
| delete Job/Batch | owner permission, terminal-or-explicit-cancel policy, expected state, idempotency, artifact/ledger deletion transaction, and audit tombstone; never authorize solely from knowledge of an ID |
| raw diagnostic/audit export | explicit local user gesture, owner permission, bounded export manifest, redaction policy, short-lived native confirmation intent, and destination chosen by the Tauri save flow |
| provider profile, Runtime capacity, kill switch, retention, or tool enablement | local application-operator authority on desktop; tenant/operator role in hosted mode; never an ordinary Job-owned endpoint |
| worker/gateway/executor mutation | workload identity on its private service interface, not an end-user desktop/OIDC token |

The server derives `user_id`, `tenant_id`, role, provider binding, budgets, and current
state from trusted identity/configuration/database records. It never trusts those
fields in request JSON, headers supplied by the WebView, model output, or tool output.
Frontend step ordering is advisory; the API state machine rejects out-of-order calls.
This follows OWASP's object-level authorization guidance and its explicit warning that
each workflow endpoint must validate the current state rather than assuming the UI
performed earlier steps.

The current OIDC code already does several important things correctly: it restricts
algorithms to an asymmetric allowlist, requires and validates `exp`, `iss`, `sub`, and
`aud`, and keys the user by `(issuer, subject)` while treating email/name as mutable
display data. OpenID Connect specifies that only `(iss, sub)` is a stable user
identifier; email must not become ownership identity.

Before hosted multi-tenant use, the token profile is tightened further:

- distinguish access-token and ID-token profiles with mutually exclusive accepted
  `typ`, issuer, audience, key, and required-claim rules; do not accept any valid JWT
  "shape" interchangeably;
- validate the expected API audience and, when multiple audiences are allowed, the
  authorized-party/client binding required by the selected issuer profile;
- validate `nbf` when present, bound clock skew, token size, JWKS origin/TLS/cache
  lifetime, key rotation, and unknown-key failure without falling back to another
  issuer;
- derive tenant membership and role from server-side membership records or one
  issuer-profile allowlist; never from email domain alone or an unvalidated body/header
  tenant;
- deny by default when scope/role/action mapping is absent, and include negative
  multi-user/multi-tenant authorization tests for every nested route;
- keep access tokens in the hosted frontend's memory and use Authorization headers;
  do not move them into Web Storage or ambient cookies merely to reuse desktop code.

RFC 8725 requires explicit algorithm verification, issuer/subject/audience validation,
and mutually exclusive validation rules for different JWT kinds. RFC 9700 recommends
audience restriction to prevent a token for one resource server being reused at
another. Those are deployment-profile requirements, not optional provider quirks.

#### 17.3.7 Residual Windows/WSL boundary

The bridge materially removes the unauthenticated browser/loopback surface, but it
does **not** prove that an arbitrary hostile process already running as the same
Windows account cannot impersonate DroneDream. Microsoft documents that a Windows
caller can launch a named WSL distribution as a specified Linux user, including
`root`. Consequently, Linux UIDs, socket modes, and a launch key bootstrapped through
that same WSL interop path are not a cryptographic Windows application identity.

Version 1 therefore claims protection against hostile web origins, DNS rebinding,
cross-origin simple mutations, accidental clients, other Windows users, protocol
replay, and callers that do not control the current DroneDream/WSL launch. It does not
claim protection after malware controls the current Windows user, can invoke WSL as
root, debug/inject Tauri, scrape its memory, replace the installed Runtime, or tamper
with the kernel. Those capabilities are grouped with the local-machine compromise
limit in Section 27, not hidden under "authenticated Unix socket."

If the product later requires hostile-same-user isolation, the architecture must
change rather than add another token:

- package the UI with Windows application/package identity and evaluate an
  AppContainer trust level;
- isolate privileged Runtime mediation in a separately signed broker/service;
- authenticate IPC using package/AppContainer SID-scoped Windows objects and verify
  the broker/client process and signed image under a documented TOCTOU-resistant
  policy;
- minimize broker commands and keep WSL control outside the untrusted UI container;
- rerun updater, WebView, WSL, named-pipe, install, and recovery threat models under the
  new packaging constraints.

Microsoft notes that ordinary full-trust MSIX apps do not gain AppContainer isolation
automatically; package identity and AppContainer are separate choices. The current
NSIS/full-trust Tauri release cannot claim that stronger boundary.

### 17.4 Human approval

Version 1 proposal tools are side-effect-free, so each decision does not need a
manual approval. Approval is required if a later feature:

- changes the immutable experiment contract;
- increases a hard budget;
- introduces hardware flight;
- sends data to a new provider origin;
- enables a side-effecting/open-world tool.

### 17.5 Assurance lifecycle

Use the NIST AI RMF's govern/map/measure/manage structure as an ownership checklist:

| Function | DroneDream artifact |
| --- | --- |
| Govern | named owners for prompt, tool registry, safety policy, eval bank, and incident response |
| Map | experiment-specific threat model, data-flow diagram, provider/privacy inventory, and authority matrix |
| Measure | decision evals, optimization outcomes, adversarial tests, trace sampling, fallback and cost metrics |
| Manage | rollout gates, feature flags, kill switch, provider disablement, incident retention, and documented residual risk |

This mapping does not certify the system. It prevents technical controls from being
implemented without owners, measurement, or response procedures.

### 17.6 Operational kill switches and rollback

Rollout control has four independent switches:

1. global `LLM_HARNESS_ENABLED`;
2. provider-origin/model allowlist;
3. per-tool enablement;
4. per-experiment orchestration mode.

Disabling the global switch prevents new model decisions. It does not corrupt
already-dispatched simulations or rewrite their provenance. A per-tool disablement
removes that tool from future eligibility reports; an already accepted but
not-yet-executed plan containing it is rejected as stale policy.

Rollback from LLM orchestration to the deterministic portfolio occurs only at a
generation boundary and is recorded as a fallback transition with the old decision
preserved. There is no mid-batch child substitution. Security incidents may pause
all undecided jobs, revoke provider access, and retain redacted forensic metadata
without exposing raw prompts by default.

## 18. Budget model

Maintain separate ledgers:

1. **simulation ledger**: candidates, scenarios, trials, fidelity-equivalent cost;
2. **model ledger**: logical decisions, physical attempts, input/output tokens,
   estimated currency cost, retries;
3. **proposal-tool ledger**: allocated slots, calls, produced/invalid/duplicate/
   transformed/fallback candidates, CPU, memory, process/thread peaks, and tool-specific
   modeled cost;
4. **wall-clock ledger**: provider time, proposal time, delayed-evidence time, queue
   time, simulator time.

Routing reward never substitutes for these ledgers. `PortfolioRewardContractV1`
references their immutable rows and a fixed cost catalog; an unproductive or
reward-ineligible allocation may have zero quality credit but never zero incurred cost.

The LLM receives remaining budget but cannot edit it. The server calculates exact
cost after tool output and rejects oversubscription. Two simulation quantities are
never conflated:

- **physical trial slots** are integer Trial rows and remain bounded by the existing
  `max_total_trials`;
- **fidelity-equivalent cost** is a fixed-scale decimal used only when a tool has a
  validated lower-fidelity execution mode, and is bounded separately by
  `max_fidelity_cost` when configured.

A lower-fidelity proposal can save equivalent compute cost; it cannot create extra
physical Trial rows beyond `max_total_trials`. The dispatch transaction converts the
compiled calls into both reservations, rechecks completed/pending/reserved totals,
and converts only the committed batch from reserved to committed cost. Failed or
superseded decisions release their reservation through a versioned transition rather
than decrementing a counter ad hoc.

Token counts are primary facts. Currency cost is an estimate calculated from a
versioned price catalog and recorded with currency, catalog revision, and timestamp;
later price changes must not rewrite historical estimates.

Before sending a physical provider request, the gateway atomically reserves:

- one attempt slot;
- the request's maximum input and output token allowance;
- a conservative currency upper bound under the pinned model/price catalog;
- the remaining wall-clock slice.

On a complete response with provider-reported usage, the reservation reconciles to
that usage and releases only the proven remainder. If usage is absent but a complete
response permits a deterministic estimate, the ledger keeps both the estimate and
its confidence label. A post-send timeout, disconnect, gateway crash, or lost response
retains the full unresolved upper bound until an authenticated provider usage API
reconciles it or the Job is archived under an explicit accounting policy. It is never
released merely because the application did not receive an answer.

Another physical retry must fit alongside every confirmed charge and unresolved upper
bound. Consequently, the hard cap remains safe even if both an ambiguous first
attempt and its retry were billed. Provider-reported invoice data may later reduce an
upper bound but cannot retroactively authorize a request that exceeded the cap at
send time. The UI reports confirmed, estimated, and unresolved maximum cost
separately; one deceptively precise total is not shown.

Hard limits:

- logical model decisions per generation, fixed to one in Version 1;
- physical provider attempts per logical decision and per job;
- model tokens and estimated currency cost per decision and per job;
- tool calls per decision;
- candidates per generation;
- total physical trials and optional fidelity-equivalent cost;
- provider timeout and retry count;
- snapshot and response bytes;
- trace retention.

## 19. Failure and fallback semantics

There are two independent failure planes. A **control-plane failure** affects model
planning, tool execution, dispatch, or durable workflow progress. A **trial-outcome
class** describes what one physical simulator attempt proves about a Candidate. The
same string must never serve both purposes.

The current implementation does not yet maintain this separation completely:
`aggregation.py` counts every non-completed Trial as a Candidate failure, while
`job_manager.py` gives only a small subset of infrastructure codes a duplicate
Candidate retry. Harness mode must replace that path; it may not inherit the behavior
and then label the resulting penalty “robustness.”

Control-plane behavior is:

| Control-plane failure | Result |
| --- | --- |
| explicit retryable provider status | reserve one bounded application-owned retry with the same canonical request and proven idempotency key; otherwise configured fallback |
| pre-send transport failure | retry only when the transport proves no request bytes reached the provider |
| post-send timeout/disconnect or gateway loss | mark `outcome_unknown`, retain cost upper bound, and retry only with conformance-proven idempotency plus remaining worst-case budget; otherwise pause/fallback |
| provider authentication | pause or fail; never retry repeatedly |
| malformed schema | no model repair turn; record and apply configured fallback |
| semantic plan rejection | no repair mutation; fallback or fail closed |
| proposal backend unavailable/incompatible/circuit-open | typed availability transition, no exploration allocation until the frozen probe/cooldown policy re-enables it, and no silent child substitution |
| proposal timeout/crash/resource violation | retain incurred cost and typed ToolCall failure; update the availability circuit only through its registered rolling rule; never fabricate Candidate reward |
| too few valid candidates | explicit partial/fill/reject policy |
| Candidate-outcome or routing-reward compiler failure | pause/fail the generation boundary and quarantine the affected projection; do not build a provider snapshot or future policy state from a partial score |
| stale state version | discard result and rebuild from current evidence |
| worker crash after dispatch | existing trial lease/retry path; no new decision |
| service restart during decision | resume from durable status and idempotency key |
| sealed final-test access before authorization | security event and hard rejection |
| user cancellation before dispatch commit | mark decision cancelled; create no new candidate or trial |
| provider returns after cancellation or newer attempt | retain as superseded metered audit record; never execute |
| stop recommendation fails policy | deterministic continue/fallback or explicit pause, as frozen in job contract |
| pause timeout | apply immutable timeout policy; never silently resume |
| global kill switch activated | block new decisions and pause/fallback at generation boundary |

Trial-result behavior is:

| Attempt outcome | Parameter evidence | Workflow action |
| --- | --- | --- |
| `valid_observation` | verified registered objectives and constraints | accept the one fenced attempt and complete the logical Trial |
| `domain_constraint_failure` | typed Candidate-dependent constraint only | complete the logical Trial only for a compatible tool/contract |
| `domain_right_censored` | typed censored duration and constraint only | complete only under a frozen censor-aware contract |
| `infrastructure_failure` | none | exact logical-Trial retry as a new physical attempt; pause/fail if exhausted |
| `evidence_contract_failure` | none | quarantine bytes, trip the relevant verifier circuit breaker, and retry only after trusted fault classification |
| `cancelled` or `superseded` | none | retain the minimal audit record and never let the result advance the Candidate |

The trusted classifier uses a closed `(failure_domain, failure_stage,
reason_code, retryability)` registry. Runner-authored free text is diagnostic only.
For example, a PX4 boot timeout is infrastructure; a verified flight-completion
deadline can be domain right-censoring; an unexplained process kill is not silently
converted into either. Unknown combinations fail as `evidence_contract_failure`.

No fallback may:

- attach an infrastructure or verifier failure to a parameter vector as a bad score;
- create a replacement Candidate when the intended operation was an exact Trial retry;
- fill a missing metric, clamp an invalid rate, or reuse an old metric under a new
  contract;
- consume `final_test` material or move to the next-best Candidate after final-test
  failure;
- erase proposal/simulation/compute cost because a Candidate or reward was ineligible;
- create a positive/negative tool reward, source share, or action probability for
  missing evidence; or
- relabel LLM sampling behavior as a randomized logging policy for off-policy
  evaluation;
- erase the failed attempt, rejected decision, cost reservation, or causal provenance.

Every fallback records the failed plane and stage and preserves the original rejected
object. Product mode may continue only under its frozen policy; evaluation mode exposes
every assigned run in the intention-to-run ledger.

## 20. Observability and audit

The current repository has append-only `job_events`, ordinary application logs,
reports, and simulator artifacts, but no OpenTelemetry SDK/export pipeline. Everything
in this section is a target design. The durable SQL decision ledger remains canonical;
telemetry is a bounded operational projection that may be sampled or dropped without
changing workflow correctness.

### 20.1 Trace tree

```text
orchestrate_generation
  build_evidence_snapshot
  freeze_routing_opportunity
  chat {provider profile + model}
  validate_decision
  compile_generation_plan
  execute_tool {stable optimizer tool ID}
  execute_tool {stable optimizer tool ID}
  validate_candidate_batch
  freeze_candidate_proposal_sources
  reserve_budget_and_dispatch

trial_execution (separate asynchronous trace linked to dispatch)
  claim_trial
  apply_and_verify_parameter_contract
  run_simulator
  persist_attempt_artifacts
  compile_canonical_telemetry
  verify_trial_evidence
  accept_trial_attempt

aggregate_generation (separate restartable trace linked to completed trials)
  compile_registered_metrics
  compile_candidate_outcomes
  verify_candidate_outcome_envelopes
  resolve_due_routing_rewards
  reconcile_routing_cost_and_source_shares
  apply_acceptance_or_promotion_policy
```

Do not hold one span open for the lifetime of a Job. A tuning Job may wait for minutes
or hours, cross processes, restart, pause, and fan out into many Trials. Each durable
stage creates a bounded trace. Its start row stores the local trace/span context and the
causal ledger reference before work begins. A later stage starts a new root trace and
adds OpenTelemetry `Link`s to the dispatch/decision/trial spans it consumes. Parent-child
relationships are used only when one operation directly encloses the other in one live
execution context.

Every span name comes from a fixed catalog. It never contains a Job name, ID, parameter,
model, URL, tool argument, error message, or other runtime value. Span attributes may
record bounded enums/revisions:

- orchestration mode and stage;
- approved provider-profile ID and bounded model-family alias;
- tool ID/version and transport-profile enum;
- decision/attempt/tool/trial outcome enums and typed error code;
- Trial outcome class, failure domain/stage, result-schema version, telemetry-contract
  version, metric-contract version, verifier status, and coverage bucket;
- outcome-contract and objective-adapter versions, Candidate-outcome state,
  scenario/replicate/risk estimator enums, feasibility transition, and bounded
  effective-evidence buckets;
- routing-policy, opportunity, attribution, reward-contract, reward-state,
  allocation-role, availability/circuit, action-probability-provenance, and
  cost-completeness enums;
- confirmed/estimated/unknown usage state, bounded token counts, and cost bucket;
- latency and candidate/Trial counts;
- policy, schema, registry, simulator-image, and implementation revisions.

Exact Job/generation/decision/candidate/Trial IDs, request IDs, and content hashes remain
in the access-controlled local ledger. When cross-system troubleshooting requires a
correlator, the exporter receives a rotating, environment-scoped HMAC reference, not
the raw identifier or an unsalted hash. The HMAC key never enters telemetry and its
rotation deliberately breaks indefinite linkage.

No metric dimension may contain a Job, user, generation, decision, attempt, candidate,
Trial, request, trace, arbitrary model string, endpoint, parameter, reason text, or
content hash. Provider/model/tool dimensions are accepted only from the finite deployed
registry. Metrics with unbounded values are rejected at instrumentation tests rather
than relying on the backend to absorb cardinality.

OpenTelemetry's general error convention uses low-cardinality `error.type` to describe
an operation error. DroneDream therefore maps only bounded **operational** failures such
as `provider_timeout`, `simulator_boot_failure`, `artifact_digest_mismatch`, or
`verifier_contract_failure` to `error.type`; the raw exception or runner string remains
local. A successfully executed Trial whose verified controller behavior violates a
domain constraint is not mislabeled as an infrastructure span error. Its span can
complete normally with `trial.outcome_class=domain_constraint_failure`, while the
scientific outcome stays in the SQL evidence ledger.

### 20.2 Context propagation and trust boundaries

Only W3C trace context needed for causal tracing crosses the API, gateway, proposal
executor, or trial-worker boundary. DroneDream does not use OpenTelemetry Baggage for
user/Job IDs, credentials, provider references, prompts, parameters, or policy data.
Incoming `traceparent`/`tracestate` from an untrusted browser or provider is not allowed
to select the canonical local trace identity; the trusted API starts a fresh trace and
may retain a validated external context only as a link.

Queue/lease payloads carry a signed or database-resolved local `trace_context_ref`, not
arbitrary caller-supplied trace headers. The consumer verifies that the reference
belongs to the same Job/stage and has not expired. The provider response cannot inject
trace context into later tool or simulator calls. The networkless proposal executor
receives only the compiled-call correlation reference already allowed by its IPC
protocol.

Trace context is diagnostic, not an idempotency or authorization token. Missing,
malformed, sampled-out, or exporter-dropped context never changes state transitions,
access, retry, or candidate creation.

This fail-closed boundary follows OpenTelemetry's own warning that Baggage may be
forwarded to unintended third parties and has no built-in integrity guarantee:
[OpenTelemetry Baggage security considerations](https://opentelemetry.io/docs/concepts/signals/baggage/).

### 20.3 Content, exception, and exporter policy

Provider request/response content, prompts, tool arguments/results, evidence values,
candidate vectors, simulator output, artifact paths, SQL statements, HTTP bodies,
headers, URLs/query strings, exception messages, and stack traces are **off by default**
for spans, logs, and events. Ordinary production telemetry emits typed codes and numeric
counts only. Exact local ledger hashes are not automatically safe to export because
they can still be stable cross-run correlators or permit dictionary checks against a
small payload space.

An explicit local diagnostic capture may store selected raw content only after:

1. an operator chooses a narrow Job/stage and sees the privacy warning;
2. the secret/sealed-test/untrusted-text scrubber and byte-canary tests pass;
3. capture has a short absolute TTL, encrypted local storage, size limit, and audit row;
4. external export remains separately disabled unless the operator names the approved
   destination and retention policy.

Auto-instrumentation is not exempt. HTTP, SQLAlchemy, logging, and exception
instrumentation use explicit allowlists and processors that remove authorization,
cookie, API-key, request/response body, query, database statement, exception message,
stacktrace, and local path fields before export. A secret/canary detector runs before
the batch queue, at the Collector/export boundary, and in CI fixtures; detection fails
closed for that telemetry item and raises a local typed security event.

OpenTelemetry explicitly assigns sensitive-data identification and minimization to
the implementer, not the SDK. That is why DroneDream prevents collection at the
instrumentation boundary and treats Collector redaction only as defense in depth:
[OpenTelemetry, Handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/).

The packaged desktop default is no external exporter. A configured exporter uses a
versioned allowlisted endpoint, verified TLS, bounded local queue/batch sizes, backoff,
and its own deny-by-default egress route. Export failure drops or spools only the
non-canonical projection within a small TTL/size quota; it never blocks provider
budgeting, proposal execution, trial persistence, cancellation, or shutdown.

### 20.4 Operational metrics

- decision success/rejection/fallback rate;
- provider and tool latency percentiles;
- invalid allocation and incompatible-tool frequency;
- duplicate candidate rate;
- model tokens and cost per accepted candidate;
- simulations and wall time per feasible improvement;
- stale-decision and recovery counts;
- deterministic-warmup generations and cost;
- cross-tool duplicate rate and multi-source credit share;
- model versus policy versus fallback allocation share;
- per-tool eligible opportunities, reserved/discretionary allocations, produced/exact-
  accepted/evaluated/completed/rewarded counts, complete cost, delayed/unobserved reward,
  availability/circuit changes, allocation entropy, rolling share, and exploration debt;
- routing reward reconciliation failure, invalid action-probability/OPE-support,
  effective-sample, maximum-importance-weight, and OPE-ineligible counts; estimators and
  uncertainty stay finite typed attributes rather than dynamic metric names;
- Trial attempt counts by the closed outcome class and failure stage;
- exact infrastructure-retry count, exhausted-incomplete Candidate count, and accepted
  attempt ratio;
- evidence-envelope schema rejection, artifact-digest mismatch, coordinate/time
  contract rejection, verifier failure, and coverage-gate rejection counts;
- search-to-validation promotion count, winner-freeze count, and final-test
  materialization count;
- sealed-test boundary violations, expected to remain zero;
- telemetry queue drops, canary redactions, exporter failures, and link-resolution
  failures.

All counters/histograms use a frozen attribute allowlist and explicit maximum-series
budget. Operational dashboards link an aggregate anomaly to the local audit search
through a short-lived support reference rather than adding raw IDs to metrics.

### 20.5 Sampling, retention, and integrity

The SQL audit ledger records every decision independently of trace sampling. Metrics are
unsampled aggregates. Normal traces may use a documented sampling policy; typed
security/policy violations and rare terminal failures are retained at 100% only after
content minimization. Sampling revision and decision are attached to each retained
trace, and evaluation campaigns either use a frozen all-stage local trace policy or
report sampling gaps.

Telemetry clocks are diagnostic; state ordering comes from database revisions and
monotonic per-Job event sequence, not wall-clock timestamps. Exported spans include
service/source revision and boot/session identity so a restart and clock discontinuity
are visible. Local trace correlation rows have integrity hashes and retention tied to
the decision ledger; vendor telemetry may be deleted sooner and cannot be the only copy
of evidence needed for replay or incident review.

### 20.6 User-visible trace

The UI should show a compact factual trace:

> Generation 4: the LLM allocated two proposals to BIPOP-CMA-ES for diversity
> recovery and two to TuRBO for local refinement. All four passed validation and
> were dispatched at the recorded fidelities.

It should also label provider failure and deterministic fallback. Do not expose
private reasoning or claim that a rationale proves correctness.

The UI reads a redacted server projection from the decision ledger, not an external
telemetry backend. It never displays provider request IDs, raw rationale, diagnostic
capture content, trace headers, credentials, sealed final-test metadata, or stack
traces.

## 21. Reproducibility contract

A completed run is reproducible only when its report pins:

- source commit and schema revision;
- experiment contract hash;
- immutable `OptimizationOutcomeContractV1`, registered metric-dependency graph,
  scenario-population/replicate estimand, missingness and non-success rules, risk
  estimators, outcome constraints, fixed transforms, objective representation,
  scalarization/Pareto reference, tie-breaking, acceptance, promotion, and selection
  policy hashes;
- parameter catalog and safe-range revision;
- simulator/runtime image and manifest;
- scenario definitions, scenario-instance IDs, seed-derivation contract, named
  substream manifests, component seed adapters, seed-binding evidence, common-random
  blocks, and achieved repeatability class;
- orchestration mode and fallback policy;
- evidence snapshot hashes;
- every accepted `TrialAttemptEvidenceEnvelopeV3` hash, accepted attempt fence, source
  artifact digest, canonical-telemetry digest, metric-observation hash, and outcome
  classifier revision;
- every `CandidateOutcomeEvidenceV1` hash and its raw-metric, derived-metric,
  feasibility, risk, objective-representation, and lexicographic-selection-key hashes;
- prompt template revision;
- full model binding: provider profile, requested alias, requested snapshot, returned
  identity/fingerprint, reasoning/generation settings, adapter/SDK revision, probe hash,
  and reproducibility class;
- tool registry and implementation revisions;
- every normalized decision and tool result;
- every routing opportunity/action, eligible-action set, policy-reserved/discretionary
  allocation, valid logged action probability or explicit unsupported state,
  multi-source credit share, reward event, cost component, circuit/availability
  transition, and reward/exploration/attribution/OPE policy revision;
- candidate/trial provenance;
- telemetry/extractor, metric registry/compiler, failure classifier, acceptance,
  random-domain registry/deriver/binding verifier, validation-promotion, and
  final-test verifier revisions.

LLM outputs are nondeterministic even when these are fixed. “Replay” therefore has
two meanings:

1. **evidence replay**: use retained immutable input/artifact bytes and the pinned
   extractor/verifier to reproduce the accepted canonical telemetry, metrics, outcome
   class, and envelope hash;
2. **decision replay**: reuse recorded normalized decisions/tool results to reproduce
   downstream candidates and Trials without calling the provider; and
3. **model rerun**: call the pinned model configuration again and measure behavioral
   consistency.

Reports must distinguish them.

Evidence replay and decision replay are the only deterministic replay claims
DroneDream can make without calling the provider. Evidence replay succeeds only when
the retained `trial_execution_attempts` row, source artifacts, signed Runtime slot, and
exact verifier inputs are available; matching only a displayed score is insufficient.
Even a snapshot-pinned model rerun remains a stochastic consistency experiment, not
guaranteed byte-identical regeneration. An `alias_only_unpinned` report must state that
provider-side behavior may have changed without an observable revision and may not use
the word “reproduced” for a fresh model call.

A simulator rerun is a fourth, separate operation: it executes the frozen treatment
again under a recorded Runtime/host/randomness contract. It reports one of the
repeatability classes from §8.9 and never inherits the word “exact” from successful
artifact replay. An intended seed schedule without accepted seed-binding evidence is
insufficient to reproduce a stochastic treatment.

### 21.1 Signed Harness runtime manifest

DroneDream already has a useful release foundation:

- `runtime/tools/runtime_manifest.py` records the DroneDream/PX4/Valkey commits,
  component versions, base-image digest, and lock-file hashes;
- `runtime-release.json` binds the downloadable rootfs parts, hashes, source commit,
  and smoke report, and its detached Ed25519 signature is verified against the
  installer-embedded public keyring;
- the desktop release verifies both application and completed installer Authenticode
  signatures, writes an installer SHA-256, and pins GitHub Actions dependencies to
  full commits.

Those controls authenticate release payloads, but the current repository does not yet
generate a Harness-specific manifest or a SLSA/in-toto/GitHub build-provenance
attestation. A Git commit string inside a database row is not proof of the bytes that a
worker imported, and an unsigned registry hash computed by the same mutable process
does not establish an independent trust boundary.

CI must therefore generate a canonical `harness-runtime-manifest.v1.json` from a clean,
tracked checkout. It contains:

```json
{
  "schema_version": 1,
  "source_commit": "40-hex",
  "tool_registry_sha256": "64-hex",
  "prompt_catalog_sha256": "64-hex",
  "function_schema_catalog_sha256": "64-hex",
  "evidence_compiler_sha256": "64-hex",
  "trial_result_schema_catalog_sha256": "64-hex",
  "telemetry_schema_catalog_sha256": "64-hex",
  "telemetry_extractor_sha256": "64-hex",
  "metric_registry_sha256": "64-hex",
  "metric_dependency_graph_catalog_sha256": "64-hex",
  "metric_verifier_sha256": "64-hex",
  "optimization_outcome_contract_compiler_sha256": "64-hex",
  "objective_transform_catalog_sha256": "64-hex",
  "risk_estimator_catalog_sha256": "64-hex",
  "outcome_constraint_compiler_sha256": "64-hex",
  "tool_objective_adapter_catalog_sha256": "64-hex",
  "portfolio_reward_contract_catalog_sha256": "64-hex",
  "routing_exploration_policy_catalog_sha256": "64-hex",
  "proposal_attribution_policy_catalog_sha256": "64-hex",
  "tool_availability_circuit_policy_catalog_sha256": "64-hex",
  "runtime_dependency_circuit_policy_catalog_sha256": "64-hex",
  "aggregate_retry_budget_policy_catalog_sha256": "64-hex",
  "off_policy_estimator_catalog_sha256": "64-hex",
  "candidate_outcome_verifier_sha256": "64-hex",
  "selection_and_promotion_policy_catalog_sha256": "64-hex",
  "trial_outcome_classifier_sha256": "64-hex",
  "random_domain_registry_sha256": "64-hex",
  "seed_deriver_sha256": "64-hex",
  "seed_binding_verifier_sha256": "64-hex",
  "parameter_contract_compiler_sha256": "64-hex",
  "parameter_bundle_catalog_sha256": "64-hex",
  "parameter_domain_compiler_sha256": "64-hex",
  "parameter_constraint_graph_catalog_sha256": "64-hex",
  "parameter_application_verifier_sha256": "64-hex",
  "plan_compiler_sha256": "64-hex",
  "safety_policy_catalog_sha256": "64-hex",
  "provider_adapter_catalog_sha256": "64-hex",
  "proposal_executor_sha256": "64-hex",
  "provider_gateway_sha256": "64-hex",
  "dependency_lock_sha256": "64-hex",
  "sbom_sha256": "64-hex",
  "build_policy_id": "github-actions/runtime-release-v1",
  "files": [
    {
      "path": "opt/dronedream/...",
      "size": 123,
      "sha256": "64-hex",
      "role": "tool_implementation"
    }
  ],
  "minimum_api_contract_version": "1.0"
}
```

The file inventory is a closed role-tagged allowlist. Manifest production rejects an
untracked input, dirty source tree, duplicate or case-colliding path, absolute path,
`..`, symlink, device, socket, unexpected executable, missing catalog member, and file
whose bytes change between stat/read/hash. Every model-visible tool description is
covered because changing descriptive text can change routing behavior even when
numerical code is unchanged. Prompt templates, strict function schemas, provider
evidence compiler, Trial-result/telemetry schemas, telemetry extractor, metric
registry/dependency graph and verifier, optimization-outcome compiler, fixed objective
transforms, risk estimators, outcome-constraint compiler, tool-objective adapters,
portfolio reward contract, routing exploration and attribution policies,
tool-availability/circuit rules, Runtime dependency circuit and aggregate retry-budget
rules, off-policy estimator catalog, Candidate-outcome
verifier, selection/promotion policy,
outcome classifier, plan compiler, eligibility/stopping/exploration policies,
random-domain registry, seed deriver, seed adapters and binding verifier,
firmware-bound parameter bundles, exact-domain/constraint compilers, parameter
application verifier, provider adapters, gateway, executor, report verifier, and all
optimizer entry points are first-class subjects rather than being hidden behind one
source-commit label.

The trust links are deliberately acyclic. The inner Harness manifest covers logical
control-plane files and may be produced before packaging; it does not contain the
digest of the enclosing rootfs, outer release manifest, or an attestation whose subject
is that enclosing artifact. The outer signed Runtime release manifest records the final
rootfs digest and the extracted inner Harness-manifest digest. The separate provenance
attestation names the final release subject digest. After verifying all links, the
desktop writes an activation record containing the inner digest, outer manifest/signing
identity, final artifact digest, provenance-bundle digest, and SBOM-attestation digest.
No object hashes bytes that contain its own digest.

The desktop verifies the outer release before import and stores the expected
inner-manifest digest in its activated-runtime record. On every service start, a
minimal verifier reads the manifest and hashes the closed control-plane inventory
before starting API, orchestration, gateway, or proposal services. Services receive a
read-only view of the verified files; a mismatch blocks Harness mode and emits a local
integrity incident. Fixed legacy simulation may be offered only under an explicitly
separate degraded policy—it must not relabel an unverified runtime as Harness.

The executor does not trust a registry hash supplied by the API. It loads the registry
covered by its activated Harness manifest, reports that manifest digest during its
authenticated startup handshake, and accepts a ToolCall only when the Job, broker, and
executor all name the same digest. The gateway follows the same rule for provider
profiles, model adapters, request canonicalization, and budget enforcement. The
orchestrator obtains the activated digest from the verified local runtime service; the
frontend cannot choose or override it.

### 21.2 Build provenance, SBOM, and release identity

SLSA provenance separates build inputs from run details and builder identity. GitHub
artifact attestations can bind binaries or images to the repository, workflow, commit,
trigger, and builder, and can separately attest an SBOM. DroneDream should add a
commit-pinned `actions/attest` release step for:

- the Windows installer;
- the Runtime release manifest and the reassembled Runtime artifact digest;
- the Harness runtime manifest;
- any separately distributed gateway/executor binary;
- the SBOM describing Python, Rust, Node, OS-package, PX4, Gazebo, and native-library
  inputs that are actually shipped.

This attestation supplements rather than replaces SignPath Authenticode and the Runtime
Ed25519 signature. Authenticode answers which publisher signed the Windows bytes; the
Runtime keyring authenticates DroneDream's downloadable Runtime manifest; provenance
answers which workflow, source commit, inputs, and builder produced the subject. A
release gate verifies all three against an allowlisted repository, workflow path,
OIDC issuer, source ref/tag, commit, builder identity, and exact subject digest. It does
not merely verify “some valid Sigstore signature,” use an identity regex such as `.*`,
or disable subject-claim checking.

Archive the provenance bundle, SBOM attestation, release manifest/signature, workflow
run ID, immutable tag, source commit, dependency locks, test reports, and all subject
digests in the release evidence package. GitHub supports online and offline attestation
verification; offline evidence still requires a recorded trusted-root snapshot and a
policy for refreshing or revoking it. A deleted workflow artifact is not the long-term
audit store.

No production release may:

- build from a developer workstation and upload replacement bytes under the same tag;
- reuse a release tag, filename, or updater version for different content;
- download an unpinned prompt, registry, policy, Python module, wheel, action, script,
  or model adapter during build or Job execution;
- treat exact package versions without artifact hashes/SBOM reconciliation as complete
  dependency provenance;
- promote a shadow/evaluation build by editing database hashes after it was built;
- attest an artifact in a different job after unverified download without preserving
  its original digest and trusted build identity.

The current Runtime lock validates exact Python versions but does not record a hash for
every downloaded distribution. Before Harness release, the lock must be regenerated
with artifact hashes for the supported platform or the wheelhouse must be built,
hashed, SBOM-recorded, and used offline. OS packages and native libraries are recorded
from the final image and compared to an allowlisted release inventory; mutable package
repositories are not treated as provenance merely because a package version was
requested.

Sources:

- [SLSA v1.2 provenance](https://slsa.dev/spec/v1.2/provenance)
- [GitHub artifact and SBOM attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [Sigstore identity and subject verification](https://docs.sigstore.dev/cosign/verifying/verify/)

### 21.3 Runtime update, rollback, and historical replay

A new app or Runtime version must never mutate the code beneath an active Job. Runtime
releases install into content-addressed side-by-side slots:

```text
runtime slot = sha256(canonical signed Harness runtime manifest)
```

Activation is an atomic pointer change after download, signature/provenance,
compatibility, integrity, smoke, and migration gates pass. New Jobs use the activated
slot; queued or active Jobs retain their pinned slot. A service cannot claim work for a
Job whose slot is unavailable or whose manifest no longer verifies. Old slots are
garbage-collected only when no non-terminal Job, retained replay package, or declared
rollback window references them. If historical bytes are intentionally removed, the
report says `historical_runtime_unavailable` instead of substituting current code.

The update client persists the highest trusted metadata and activated Runtime versions,
subject digests, and trust-root version. It rejects an older version, a reused version
with different bytes, an expired/future-invalid metadata set, inconsistent manifest
and target hashes, or a mix of files from different releases. A manual recovery to an
older vulnerable Runtime is an explicit, locally authenticated maintenance operation
that records the reason and disables Harness Job creation until the operator
acknowledges the degraded state.

The Update Framework specifies separate root, targets, snapshot, and timestamp roles
to detect rollback, mix-and-match, and freeze attacks. DroneDream should use a
conforming TUF client/repository before enabling unattended Runtime/tool updates rather
than inventing a partial protocol around `latest.json`. Until then, Runtime upgrades
remain explicit signed installs with remembered monotonic version/digest state. An
offline machine may continue running an already verified slot; inability to obtain
fresh update metadata is displayed as “update freshness unknown,” not falsely as
“latest,” and does not silently authorize new unverified bytes.

Security revocation and ordinary feature availability are distinct:

- an optional feature update does not stop a healthy pinned Job;
- an expired update timestamp stops the update attempt, not an already trusted offline
  Runtime;
- a signed emergency revocation identifies exact forbidden manifest digests and the
  minimum safe Runtime, is cached durably, and blocks new Harness work on a revoked
  slot;
- an in-flight Job on a newly revoked slot follows a predeclared pause/cancel policy,
  preserving existing evidence without dispatching more provider or simulator work;
- trust-root rotation uses threshold/sequence rules and is never delivered as an
  ordinary unsigned Settings value.

Source: [The Update Framework specification](https://theupdateframework.github.io/specification/).

## 22. Evaluation plan

### 22.1 Hypotheses

H1. LLM orchestration improves feasible best objective under a fixed simulation
budget for heterogeneous tuning problems.

H2. It detects regimes where a restart, local method, global method, or fidelity
change is appropriate more often than the deterministic portfolio.

H3. Safety, schema, and budget gates prevent invalid model choices from changing the
experiment contract or exceeding resources.

H4. The value remains after accounting for model latency and cost.

### 22.2 Baselines

Run the same frozen experiment bank with:

1. fixed best individual algorithm;
2. deterministic portfolio;
3. direct LLM parameter proposer;
4. LLM tool orchestration;
5. matched-exploration deterministic router, used to isolate routing value;
6. oracle retrospective tool selector, analysis-only upper bound.

### 22.3 Fairness controls

- identical parameter spaces, baseline candidates, and acceptance criteria;
- matched scenario matrices and common-random substreams only when both arms have
  identical seed-derivation, component/configuration, and accepted seed-binding
  evidence hashes; otherwise use independently replicated stochastic blocks and label
  them unmatched;
- identical total simulation/fidelity-equivalent budget;
- frozen prompt, model snapshot, and tool registry per campaign;
- verified search evidence plus only frozen checkpoint-validation aggregates during
  optimization;
- one sealed final-test evaluation after the winner is frozen;
- multiple independently executed model replicates for nondeterministic behavior,
  while preserving the originating tuning problem as the statistical cluster;
- infrastructure failures reported separately from optimization failures;
- Runtime slot, host profile, headless/rendering mode, requested/achieved simulation
  speed, and run-order blocks balanced across arms;
- matched exploration-floor policy for the routing-isolation comparison, while the
  product comparison preserves the current portfolio policy.

Pre-register the primary endpoint, experimental unit, minimally meaningful effect,
exclusion/rerun rules, run count, stopping rule, missing-result policy, and statistical
comparison before inspecting final-test results. Prefer paired comparisons using common
random numbers, report effect sizes and cluster-aware confidence intervals, and retain
per-problem results rather than only a pooled mean. If many optimizers, models, or
endpoints are compared, label exploratory analyses and control the multiple-comparison
risk for confirmatory claims.

### 22.4 Outcome metrics

- best feasible scalar objective and Pareto quality where applicable;
- simple/cumulative regret;
- trials and fidelity-equivalent cost to threshold;
- feasibility and final-test pass rate;
- crash and hard-constraint violation rate;
- final search/validation-to-final-test gap;
- wall-clock time;
- model calls, tokens, and currency cost.

### 22.5 Decision and tool metrics

- valid-plan rate;
- correct tool-call and argument rate on curated cases;
- allocation error and budget-rejection rate;
- reserved/discretionary allocation-boundary violations;
- per-tool eligible opportunities, policy-reserved/discretionary allocations, produced
  proposals, exact accepted proposals, physical evaluations, completed Candidate
  envelopes, eligible reward events, incurred cost, availability/circuit transitions,
  and reconciliation gaps;
- allocation entropy, minimum-exposure completion, rolling maximum-share violations,
  delayed/unobserved reward rate, exact cross-tool agreement, duplicate-source credit
  conservation, and reward per fixed cost component;
- logged-action-probability support, effective sample size, maximum importance weight,
  estimator bias/variance sensitivity, and explicit OPE-ineligible rate where an
  off-policy analysis is attempted;
- evidence-reference validity;
- under-trigger/over-trigger rate for each tool;
- fallback rate;
- decision consistency across repeated model trials;
- tool response usefulness and token efficiency;
- human expert preference on paired plans, calibrated against outcomes;
- stop precision/recall against retrospective stopping labels and cost avoided;
- pause appropriateness and operator-resolution time;
- sensitivity to tool order, tool-description wording, and similar-tool distractors.

### 22.6 Evaluation datasets

Start development with 20–50 diagnostic cases drawn from:

- known optimizer failure modes;
- synthetic evidence snapshots with an unambiguous desired action;
- historical DroneDream jobs;
- adversarial labels/imported text;
- sparse cold start, stagnation, constraint failure, fidelity mismatch, near-budget
  exhaustion, provider failure, and duplicate-proposal cases;
- matched tool catalogs with permuted order, near-duplicate descriptions, deliberately
  unavailable tools, and cases where the correct action is to use no tool.

Maintain separate:

- capability suite, intentionally difficult and expected to improve;
- regression suite, previously solved and expected to remain near 100%;
- real PX4/Gazebo outcome campaign.

Read a sample of full traces after every harness or prompt change. Scores alone
cannot reveal a broken grader or an accidental information leak.

The 20–50 range is an early capability/regression corpus, not the sample-size
justification for a confirmatory optimizer comparison. A real outcome campaign uses
the pilot-and-power procedure in Section 22.9.

### 22.7 Transport-profile ablation

The first campaign must not conflate the quality of the LLM's routing judgment with
the convenience of the Version 1 meta-tool schema. Compare three transport arms:

1. `declarative_plan_v1`: one strict `submit_generation_plan` meta-tool containing
   declarative optimizer invocations;
2. `native_optimizer_calls_eval`: one native strict function definition per eligible
   optimizer, with provider-side parallel calls enabled only when strictness and the
   provider conformance probe both support it; and
3. `structured_plan_eval`: the same `GenerationPlan` schema returned as strict
   structured output with no function-call framing.

All arms receive byte-identical evidence, semantic tool descriptions, tool ordering,
allocation rules, token ceilings, and model configuration. Native optimizer calls do
not execute immediately: the adapter first normalizes all returned calls into the
same plan, and the same compiler, safety gates, deduplication, budget reservation,
and simulator path follow. This isolates transport effects without granting one arm
extra authority.

Report valid-plan rate, correct tool-set selection, argument validity, allocation
error, order/description sensitivity, latency, input/output tokens, provider retries,
fallback rate, and downstream fixed-budget optimization outcomes. A native-call arm
that cannot express an atomic stop/pause recommendation or a complete multi-tool
allocation is not silently patched; the limitation is recorded as part of the
transport result. If the meta-tool loses materially on routing or outcome quality,
Version 1 remains experimental until the protocol is revised.

This ablation follows the official function-calling distinction between a returned
function call, application-side execution, and a later model continuation with tool
results. It also tests the MCP notion of model-controlled individual tools instead of
assuming that embedding tool IDs in one function argument is behaviorally equivalent.

### 22.8 Two independent sealed-test boundaries

Do not conflate:

1. the per-Job **controller final test**, absent from search/validation data and
   materialized only after one Candidate and every promotion/acceptance policy are
   frozen; and
2. the **harness-evaluation test set**, hidden from prompt, schema, tool-description,
   and policy development until a campaign is frozen.

The existing `holdout=true` scenario role is not the first boundary: because the
current worker executes it for every Candidate and uses it in publishability, it is
validation data. Migration maps those cases to `validation` unless a new sealed
final-test contract is created. No compatibility alias may imply that legacy runs had
an untouched final test.

Decision cases are grouped by originating experiment before train/development/test
splitting so near-duplicate generations from one job cannot cross the boundary.
Prompt and tool authors may inspect training and development traces, but not the
locked evaluation cases. After a test campaign is opened, any prompt, policy,
provider, or tool-manifest change creates a new campaign rather than overwriting the
old score.

Historical jobs are de-identified before entering the case bank. Human expert labels
are useful for trajectory diagnostics but do not replace matched PX4/Gazebo outcomes.
The release report states which claims use synthetic cases, historical replay,
mock simulation, or real SITL.

### 22.9 Experimental unit, power, blocking, and randomization

The statistical unit for the primary outcome is one independently scheduled
**tuning-problem instance × orchestration replicate**. A generation, candidate, Trial,
scenario case, or simulator seed nested inside that run is not a new independent
sample. Likewise, ten decisions from one historical Job are correlated observations
from one trajectory, not ten independent examples of optimization success.

Use a two-stage design:

1. run a small, explicitly labeled pilot on development instances to estimate
   between-problem, between-replicate, and infrastructure variance;
2. before opening the evaluation test set, choose the number of problem instances and
   independent replicates by simulation-based power or confidence-interval precision
   for a pre-declared minimally meaningful effect.

Do not choose the final run count from the observed test effect, stop when significance
appears, or enlarge only the arm that looks unstable. If the available compute cannot
reach the declared precision, report an underpowered feasibility study rather than a
positive/negative product conclusion.

Treat the campaign as a randomized blocked experiment:

- pair every treatment on the same problem definition, initial design, scenario
  instances, accepted seed-substream/binding manifests when available, acceptance
  contract, simulator/runtime image, and budget;
- block on problem family and important nuisance factors such as simulator image,
  worker/host class, provider/model snapshot, and execution time window;
- randomize or interleave arm order inside each block so one arm does not systematically
  receive warmer caches, a quieter machine, a newer provider snapshot, or a different
  infrastructure period;
- use independently derived orchestration/tool randomness across replicates; use
  common simulator random numbers across matched arms only after the §8.9 seed-effect
  audit proves identical component binding, otherwise rely on balanced independent
  replication rather than a false paired-seed claim;
- reset mutable caches, registries, temporary state, and optimizer state between
  independent runs; preserve immutable images and manifests;
- record host saturation, queue delay, provider incidents, process restarts, and
  simulator outages as block/deviation data;
- freeze an A/A repeatability report for every supported Runtime/host profile, including
  same-substream and different-substream variance, achieved real-time-factor
  distribution, seed-disconnection tests, and declared repeatability class.

An outage that affects many runs is a correlated campaign incident. It is not converted
into dozens of independent Harness failures or silently removed. The analysis either
models the block, applies the pre-registered infrastructure-rerun rule to every affected
arm, or reports both intention-to-run and clean-infrastructure sensitivity results.

The primary estimator is paired at the problem-replicate level. Confidence intervals
use a hierarchical or cluster bootstrap that resamples problem families/problems before
replicates, or a pre-specified mixed-effects model with problem family and instance
effects. Candidate-, Trial-, or seed-level bootstrapping is prohibited because it would
artificially multiply the sample size.

This design applies the NIST principle to block controllable nuisance variation and
randomize the remainder, while respecting the nested data structure created by
optimization runs:

- [NIST/SEMATECH: Randomized block designs](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm);
- [Benchmarking in Optimization: Best Practice and Open Issues](https://arxiv.org/abs/2007.03488).

### 22.10 Selection leakage and the locked campaign

All components that can improve after observing scores belong to training/development,
not evaluation:

- prompt and evidence wording;
- model/provider/transport choice and generation parameters;
- tool descriptions, eligibility, ordering, and registry membership;
- exploration floor, fallback, stop/pause, deduplication, and attribution policies;
- routing opportunity/action schema, tool availability/circuit rules, reward endpoint,
  fixed improvement/cost scales, delayed/unobserved policy, action randomization and
  logged propensities, OPE estimator/clipping/support thresholds;
- optimizer hyperparameters and warm-up thresholds;
- endpoint transformations, penalties, reference points, and grader thresholds;
- the algorithm called “fixed best individual.”

The fixed-individual baseline is chosen using only the development bank, or all eligible
individual algorithms are reported. Selecting the best individual after inspecting test
results would make it an oracle, not a fair baseline. The retrospective oracle selector
in Section 22.2 remains an explicitly test-informed upper bound and cannot support a
deployable product claim.

Before test access, produce immutable, hashed artifacts:

- `eval_protocol.yaml`: hypotheses, arms, units, endpoints, estimands, power procedure,
  exclusion/rerun rules, multiplicity policy, and decision thresholds;
- `case_manifest.json`: grouped train/development/test identities and provenance;
- `arm_manifest.json`: exact Harness, prompt, policy, model, tool, optimizer, simulator,
  and environment revisions;
- `randomization_schedule.json`: blocks, arm ordering, orchestration domains, scenario
  instances, substream-manifest commitments, and planned execution slots;
- `analysis_plan.py` plus golden synthetic inputs/outputs;
- `locked_test_receipt.json`: content hash, access principals, freeze time, and first
  access time.

The evaluator grants the campaign runner opaque case handles; development users and the
provider cannot list or decode test contents. Every access is append-only audited.
Historical evidence is cut off at the simulated decision timestamp so a replay case
cannot contain later generations, final winners, future failures, or any validation or
controller-final-test result.

Once the test is opened, any change to a prompt, schema, model/provider snapshot, tool
manifest, policy, optimizer implementation, grading rule, or analysis code creates a new
campaign. The original result and deviations remain immutable. Repeatedly adapting to
the same test set turns it into development data; a later confirmatory claim requires a
new locked test bank.

### 22.11 Endpoints, non-success, and nondeterministic reliability

Use one pre-registered primary endpoint, with secondary endpoints interpreted
accordingly:

- **fixed-budget claim**: feasible objective quality at the exact shared
  fidelity-equivalent budget;
- **fixed-target claim**: cost/time to a frozen feasible threshold, with runs that never
  reach the threshold treated as right-censored or by a pre-specified unsuccessful-run
  penalty, never dropped;
- **multi-objective claim**: hypervolume or another frozen indicator whose reference
  point, normalization, and feasibility convention were set on development data.

Define the value of a run with no feasible candidate before the campaign. Report
feasibility probability separately and include non-success in the primary estimand;
computing objective quality only among successful runs rewards brittle methods. Report
medians, quantiles, per-family effects, uncertainty intervals, and full empirical
success curves in addition to any mean or rank.

For each model-dependent task, distinguish:

- `pass@1`: first-attempt plan validity/correctness, the primary product behavior;
- `pass^k`: all of `k` independently scheduled attempts succeed, a reliability measure;
- `pass@k`: at least one of `k` succeeds, reported only if the deployed product really
  makes/selects among `k` attempts and all latency, token, currency, and simulation
  costs are charged.

Never choose the best LLM replicate retrospectively. The campaign score includes every
replicate assigned by the frozen schedule. Provider retry attempts are transport events
inside a replicate, not free additional samples, and the model-plus-Harness pair is the
evaluated system. Model-only, transport-only, policy-only, and tool-registry ablations
support attribution but do not replace the end-to-end comparison.

The primary analysis is intention-to-run: every scheduled arm/problem/replicate receives
an outcome state. A per-protocol sensitivity analysis may exclude only pre-declared
infrastructure failures using symmetric rules across arms. It must publish the exclusion
ledger and cannot silently omit invalid plans, fallback runs, timeouts, crashes, or
infeasible outcomes caused by the system being evaluated.

These reliability definitions follow the task/trial and `pass@k`/`pass^k` distinction
described in
[Anthropic's agent-evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

### 22.12 Grader validity and evidence review

Prefer authoritative, deterministic graders for:

- schema, registry, allocation, budget, evidence-reference, and state-machine
  correctness;
- candidate feasibility, simulator metrics, acceptance criteria, validation outcomes,
  and sealed final-test results;
- replay hashes, leakage canaries, cost accounting, provenance, and policy violations.

Grade the engineering outcome without requiring one cosmetically preferred tool-call
sequence. A different valid plan may earn full outcome credit, but unsafe authority,
forbidden data access, budget violations, or fabricated evidence still fail explicit
trace assertions.

Model graders are supplemental and restricted to dimensions that code cannot determine,
such as whether a bounded rationale accurately summarizes the cited evidence. They use
a frozen rubric, receive blinded/randomized arm labels, may return `unknown`, and are
calibrated against blinded PX4/control-domain experts. Persist grader model/prompt/schema
revisions, pairwise-order randomization, raw grades, adjudications, agreement, and
false-positive/false-negative estimates. A model grader cannot read the treatment name,
sealed test data, or a reference answer generated by the evaluated model family.

Human review is sampled across successes, failures, fallbacks, disagreements, and every
problem family, not only impressive traces. Reviewers are blinded to arm where possible;
multi-rater items report agreement and adjudication. Each curated decision case has an
unambiguous specification and a trusted reference plan or proof that its outcome grader
accepts at least one valid solution.

Run deterministic graders and a representative trace review on every Harness change.
Run the larger capability suite regularly and the locked real-outcome campaign only
under its access protocol. New production failures enter training/development first;
they are not retroactively inserted into an already reported test score.

This follows official guidance to use task-specific held-out evaluation, continuous
evaluation, typical/edge/adversarial cases, and human calibration:

- [OpenAI: Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices);
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## 23. API and UI impact

### 23.1 Job creation

The current request has one `optimizer_strategy` enum containing `gpt` and numerical
algorithms, and its strict schema accepts a raw `llm.api_key`. Replacing that field in
place would break old clients. Add one optional, versioned object:

```json
{
  "orchestration": {
    "schema_version": "1.0",
    "mode": "llm_harness",
    "fixed_algorithm": null,
    "allowed_tool_ids": [
      "optimizer.propose_constrained_mobo",
      "optimizer.propose_turbo"
    ],
    "fallback_policy": "deterministic_portfolio",
    "max_model_calls": 12,
    "max_model_cost": "2.50",
    "outcome_profile_id": "robust-flight-v1",
    "credential_profile_id": "openai-primary",
    "provider_profile_revision": "settings-profile-hash"
  }
}
```

Validation rules:

- accept legacy `optimizer_strategy` alone and map it according to Section 6.4;
- accept `orchestration` alone and derive a compatibility `optimizer_strategy` value
  for existing filters/exports;
- when both are explicitly supplied, require an exact, documented mapping or reject
  `422 ORCHESTRATION_CONTRACT_CONFLICT`;
- `fixed_algorithm` is required only in fixed mode; `allowed_tool_ids` and an approved
  credential-profile binding are required only in Harness mode;
- in packaged desktop mode, Tauri Rust retains the live non-secret session reference
  and injects it into the authenticated bridge operation outside the WebView-authored
  canonical Job body; browser/hosted transports resolve an equivalent managed
  reference from the authenticated principal/tenant profile;
- the live session reference is consumed/exchanged during Job creation; it is excluded
  from canonical Job configuration, WebView state, responses, events, drafts, rerun
  payloads, and persistence, while only the derived Job binding ID/revision is stored;
- provider/model/base-origin configuration is resolved from the referenced Settings
  profile and snapshotted without the key at Job creation;
- the server computes a conservative upper-bound trial/model budget from the
  registry, scenario matrix, exploration floor, and fallback policy before queuing;
- the server compiles the existing objective/weight/threshold/scenario selections plus
  `outcome_profile_id` into one immutable `OptimizationOutcomeContractV1`; clients
  cannot send executable expressions, observed-range normalization, optimizer-specific
  penalties, hidden feasibility thresholds, or an alternate acceptance formula;
- every allowed tool must accept the compiled objective representation, hierarchical
  estimand, risk measures, outcome constraints, missingness rules, and observation
  tags; an incompatible tool is rejected at creation rather than adapting the meaning
  after evidence exists;
- unknown schema versions, tools, provider profiles, or fallback policies fail
  closed.

Do not require an API key for fixed or deterministic modes.

The response keeps existing fields during the compatibility window and adds:

- `orchestration_config`: immutable redacted job contract;
- `orchestration_summary`: current decision state, generation, selected/fallback
  tools, model-call/cost totals, and pause reason;
- `api_contract_version` and `legacy_mapping_applied`.

Do not add `PAUSED` to the existing top-level `JobStatus` in Version 1. Older clients
have a closed status union. A paused Harness decision keeps the Job non-terminal,
sets `current_phase=optimization_paused`, and exposes the authoritative pause in
`orchestration_summary`. Cancellation and terminal Job statuses retain their current
meaning. A future API major version may promote pause to a top-level state.

### 23.2 Deployment-profile transport and authorization

The JSON schemas stay provider-neutral, but the transport is deployment-specific:

| Profile | Client transport | Authentication |
| --- | --- | --- |
| packaged desktop | typed Tauri Rust commands -> bounded stdio bridge -> Runtime UDS | in-memory launch-bound request proof plus bridge peer identity; no direct WebView HTTP |
| browser development | explicit HTTP(S) API profile | short-lived development bearer; never `AUTH_MODE=disabled` outside isolated tests |
| hosted product | HTTPS API behind the deployment edge | issuer-profiled OIDC access token with exact audience and server-side tenant/role membership |
| worker/gateway/executor | private service socket or workload-authenticated internal route | workload identity, fences, and operation-specific schema; end-user tokens are rejected |

`/health/live` may remain an unauthenticated, rate-limited, constant-shape liveness
probe during migration. It exposes no user data, Runtime paths, queue depth, provider,
manifest inventory, or failure detail. Readiness, capabilities, private status, and
every `/api/v1` route move behind the selected profile's authenticated boundary. The
current richer `127.0.0.1` readiness probe is either reached by the Tauri bridge or
replaced with a fixed systemd/runtime probe before the direct loopback API exception is
removed.

Every mutating API takes:

- a route-specific strict body;
- an idempotency key generated once per logical user action and reused only for exact
  retries;
- `expected_state_version` or `If-Match` wherever a resource already exists;
- no caller-supplied owner, tenant, role, Runtime capacity, state, spend total, or
  service identity.

The API returns `401` for missing/invalid authentication, `403` for an authenticated
principal lacking an operation, a uniform `404` for absent/foreign object IDs, `409`
for stale state or changed-payload idempotency reuse, `412` for an explicit precondition
failure, `428` when a required precondition is omitted, and the Section 13.7 overload
responses for bounded admission. Error distinctions must not reveal whether another
user owns a guessed object.

Desktop Rust exposes finite commands such as `api_create_job_v1`,
`api_cancel_job_v1`, `api_resume_decision_v1`, `api_read_job_v1`, and
`api_save_artifact_v1`; it does not expose `api_request(url, method, headers, body)`.
Tauri capabilities are scoped to the main local WebView with no remote URL capability.
As part of this migration, `withGlobalTauri=true` is removed in favor of imported,
typed APIs where feasible, and the capability file explicitly grants only commands
used by that window. This reduces accidental surface but is not presented as an XSS
defense: script executing inside the authorized WebView can still invoke every command
that window owns.

### 23.3 Read APIs and compatibility

Keep `GET /api/v1/jobs/{job_id}` bounded. It must not embed every provider attempt,
tool result, or snapshot. Add user-authorized, paginated endpoints:

```text
GET /api/v1/jobs/{job_id}/optimization-decisions
GET /api/v1/jobs/{job_id}/optimization-decisions/{decision_id}
GET /api/v1/jobs/{job_id}/optimization-decisions/{decision_id}/tool-calls
GET /api/v1/jobs/{job_id}/optimization-decisions/{decision_id}/routing-opportunity
GET /api/v1/jobs/{job_id}/optimization-decisions/{decision_id}/routing-rewards
GET /api/v1/jobs/{job_id}/candidates/{candidate_id}/proposal-sources
GET /api/v1/jobs/{job_id}/trials/{trial_id}/attempts
GET /api/v1/jobs/{job_id}/trials/{trial_id}/evidence
GET /api/v1/jobs/{job_id}/trials/{trial_id}/randomness-bindings
GET /api/v1/jobs/{job_id}/candidates/{candidate_id}/outcome-evidence
GET /api/v1/jobs/{job_id}/events
```

Every nested lookup is scoped through `(job_id, user_id)` before resolving the child
ID. List responses expose safe summaries; full canonical payloads and encrypted
debug envelopes are absent unless an explicit local audit export is authorized.
Pagination uses opaque cursors with stable ordering and fixed maximum page sizes.

The existing newest-25 `recent_events`, create/rerun `job_id` alias, Job comparison,
and CSV columns remain intact for the compatibility window. New compare/export
fields are appended, never inserted in the middle. Rerun copies the orchestration
contract and tool allowlist but requires a fresh live session credential reference
for Harness or legacy direct-LLM modes; neither a prior session reference nor a prior
Job binding is copied.

### 23.4 Step 4 presentation

The backend distinction should appear in the experiment builder:

- **Orchestration mode**: LLM Harness, Deterministic Portfolio, Fixed Algorithm;
- **Allowed optimization tools** when LLM Harness is selected;
- **Failure policy**;
- model provider status from Settings.

The selected optimization strategy card should explain the orchestration layer and
the allowed tools, not pretend the LLM itself is a numerical optimizer.

### 23.5 Job detail and reports

Expose:

- generation decisions;
- tool allocations and provenance;
- each generation's policy-reserved versus LLM-discretionary slots, complete eligible/
  excluded tool and availability/circuit summary, actual allocation/cost exposure,
  exact multi-source proposal agreement, delayed reward state, and an explicit label
  that online reward is application policy rather than causal tool contribution;
- the immutable outcome-contract summary, registered metric dependency graph,
  objective representation, scenario/replicate estimand, risk/constraint rules, fixed
  transforms/reference values, and distinct reconciled Candidate outcome envelopes:
  search for ranking/reward/acceptance, validation for the named promotion checkpoint,
  and post-freeze final test for the terminal verdict;
- validation/fallback status;
- model/simulation cost;
- links from candidate to tool call and evidence snapshot;
- logical-Trial status, accepted physical-attempt number, evidence-contract/verifier
  status, outcome class, metric provenance, and artifact-digest verification;
- requested scenario instance, randomness capability states, binding-evidence status,
  achieved repeatability class, requested/achieved simulation speed, and whether a
  comparison is truly common-random, merely request-matched, or unmatched;
- search/validation promotion history, atomic winner-freeze receipt, and a clear
  `search`, `validation`, `final_test`, `infrastructure`, or `fallback` label;
- raw physical metric values and preference-space values side by side, with units,
  transform/reference revision, effective case/replicate/tail sample counts, excluded
  cells/reasons, uncertainty evidence, and no unexplained composite “score”;
- a final-test result shown as a terminal confirmatory verdict, never as a control that
  can select another Candidate or resume the same search.

### 23.6 Conversational experiment drafting

DroneDream must support two equal entry paths into one experiment contract:

1. **Conversational drafting** for a user who wants to describe an experiment quickly
   in ordinary language or by voice, let a configured model extract the usable facts,
   answer a small number of focused follow-up questions, and then inspect or adjust
   the result in the five-step builder.
2. **Manual drafting** for a user who prefers to create a named experiment and complete
   the existing five steps directly.

The conversation is an authoring aid, not a second Job API, an autonomous simulation
agent, or an alternate source of defaults. Both paths read and write the same
session-scoped `ExperimentDraftV3`. Opening the five-step builder from the conversation
therefore shows the exact accepted values, provenance, unresolved fields, parameter
selections, and active step that the conversation compiled. A user may move between
conversation and form without copying data or creating two drafts.

#### 23.6.1 One generated experiment field registry

Do not hand-maintain a prompt list that can drift from `NewJob.tsx` or
`JobCreateRequest`. Extract the current form types, defaults, enum domains, parameter
catalog binding, field-to-step mapping, normalization, display metadata, and final
request compiler into one versioned `ExperimentFieldRegistryV1`. Generate from it:

- the five-step form controls;
- draft validation and migration;
- the provider-facing closed JSON schema;
- allowed patch paths and value domains;
- localized labels used to show recognized and missing fields;
- the deterministic `JobCreateRequest` compiler;
- contract tests proving every provider-visible field maps to exactly one builder
  control or an explicitly server-derived value.

The model returns `ConversationExperimentPatchV1`, never a `JobCreateRequest`. Each
patch item contains a registered field ID, a typed value, a source message reference,
and one of `explicit`, `derived`, or `proposed_default`. It cannot set ownership,
status, budgets above release limits, secrets, Runtime readiness, evidence, tool
availability, Job IDs, or any server-derived field. Unknown paths, unknown enum values,
non-finite numbers, invalid units, catalog-unknown parameters, unsafe ranges, and
cross-field conflicts are rejected before they touch the draft.

The compiler records one of five states for every relevant field:

- `explicit`: the user stated a value;
- `derived`: a deterministic registered conversion produced it, such as diameter to
  radius, with the source and conversion rule visible;
- `proposed_default`: the product default is present but still reviewable;
- `missing`: creation cannot yet compile a valid request;
- `conflict`: two user statements or fields disagree and require resolution.

Absence is not permission to invent. The assistant may apply documented product
defaults as `proposed_default`, but it must not present them as user intent. It may
derive only rules registered in the compiler and must not infer high-risk controller
parameters, scenario intensity, acceptance thresholds, provider credentials, or
simulation budgets from vague prose.

#### 23.6.2 Conversation turn contract

One provider turn receives only:

- a bounded locale-aware system instruction generated from the registry;
- the latest accepted redacted draft projection;
- a bounded conversation summary and the new user message;
- the current parameter-catalog IDs and reviewed envelopes needed for validation;
- no API key, Runtime path, Job history, simulation evidence, sealed-test material,
  arbitrary imported text, or hidden product state.

The strict response contains:

```json
{
  "schema_version": "1.0",
  "experiment_summary": "Tune an x500 on a five-metre circular track...",
  "patches": [
    {
      "field_id": "track_type",
      "value": "circle",
      "provenance": "explicit",
      "source_message_id": "local-turn-id"
    }
  ],
  "parameter_intents": [],
  "questions": [
    {
      "field_ids": ["maximum_total_trials"],
      "question": "What is the maximum trial budget?"
    }
  ]
}
```

The backend parses the strict response, resolves registered conversions, validates it
against the same field registry and PX4 catalog, computes missing/conflicting fields
itself, and returns an accepted patch plus field-level rejections. Model-authored
`questions` are advisory; the backend chooses the final focused questions from
authoritative field state. A turn must never overwrite a later explicit user value
with an older inferred/default value. Merge order is deterministic:

```text
new explicit user correction
  > existing explicit user value
  > registered derivation from explicit input
  > existing derived value
  > proposed product default
```

The normal assistant response has four product-level elements only: a concise
experiment summary, recognized configuration, the smallest useful set of unresolved
questions, and an **Open experiment** action. It does not scatter explanatory
microcopy, repeat all unchanged defaults, or render the entire five-step form inside
the chat. The action becomes available once a coherent draft exists; fields that still
require review remain clearly marked inside the builder. Sending a message, opening a
draft, or accepting a patch never creates or starts a Job. Only the existing reviewed
create action can compile and submit `JobCreateRequest`.

#### 23.6.3 Model choice, cost, and credentials

The conversation model selector lists only configured, capability-probed provider
profiles. The user supplies and pays for the selected provider account. The UI shows
the selected provider/model and confirmed or estimated token usage after a turn, but
does not claim that DroneDream controls provider billing. If no compatible model or
credential is configured, the composer stays available for text drafting but sending
opens Settings instead of issuing a request.

The API key must not be stored in `localStorage`, `sessionStorage`, the conversation
draft, browser history, Job request, database, logs, traces, errors, support export, or
voice transcript metadata. The current `ModelAccessProvider` session-storage behavior
is a migration bug: until the desktop credential bridge is implemented, a development
build may retain the key only in the in-memory React provider for the lifetime of the
current process and must label custom browser-hosted provider access as development
only. Production desktop conversation calls use the Section 13 credential bridge and
provider gateway.

#### 23.6.4 Voice input and privacy

The microphone is an optional input method for the same text composer:

- no microphone API is called on page load, route entry, focus, model selection, or
  draft restore;
- only an explicit click on the microphone button may request permission;
- recording has a visible active state, a keyboard-accessible stop action, a bounded
  duration, and immediate track shutdown on stop, cancel, navigation, or unmount;
- the user reviews or edits the transcript before it is sent to the model;
- raw audio is not persisted, attached to the draft, logged, or used to start a Job;
- denial, missing device, timeout, unsupported recognition, and transcription failure
  return to ordinary typing without losing the draft;
- the interface states whether transcription is on-device or sent to a named service
  before recording begins; it never calls a browser recognition service without that
  disclosure.

`SpeechRecognition` is not a portable production foundation. Microsoft documents that
the stable Edge implementation can use Azure Cognitive Services and that captured
audio leaves the device; an enterprise policy can disable the API. The new on-device
Edge recognition path cannot be a DroneDream 1.0.0 prerequisite because Microsoft's
current instructions require Edge Canary or Dev 150 or newer plus an explicit feature
flag. The implementation may therefore use Web Speech only as a capability-detected
convenience path, with a named-service disclosure and positive confirmation before
permission is requested. The reliable future desktop path records a bounded audio
stream after `getUserMedia({audio:true})` permission and sends it through a separately
configured transcription profile; the app must not silently reuse the
experiment-reasoning model or credential for transcription. WebView2 represents
microphone capture as an explicit permission kind and reports whether a request was
initiated by a user gesture. These boundaries follow:

- [Microsoft Edge speech-recognition policy and remote-service disclosure](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/speechrecognitionenabled);
- [Microsoft Edge on-device SpeechRecognition prerequisites](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/speech-recognition-api);
- [Microsoft Edge speech-recognition privacy behavior](https://learn.microsoft.com/en-us/legal/microsoft-edge/privacy#speech-recognition);
- [Microsoft WebView2 permissions including microphone access](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/overview-features-apis);
- [WebView2 permission request user-gesture and persistence fields](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2permissionrequestedeventargs).

#### 23.6.5 Draft lifecycle and recovery

Conversation messages, accepted field provenance, and the shared experiment draft are
session-scoped. A normal application exit does not retain an unsubmitted draft. The
existing exit guard therefore treats a conversation with accepted patches exactly
like a partially completed five-step form: it warns that the draft will be discarded,
offers return/cancel-exit, and erases the conversation and form draft only after the
user confirms exit. Active submitted Jobs remain governed by the separate active-Job
warning and continue in the Runtime according to their durable state.

The default workspace route becomes the conversation page after desktop readiness is
confirmed. Dashboard remains a distinct sidebar destination after Conversation, and
**New experiment** remains available from both pages. The launcher opens Conversation,
not Dashboard. The conversation route itself does not trigger another environment
check; Runtime checks occur only in the launcher or after the explicit Settings
**Check environment** action.

## 24. Implementation plan

### Current-to-target code map

| Current area | Reuse | Required change |
| --- | --- | --- |
| `backend/app/schemas.py` | parameter, scenario, acceptance, and provider validation | split orchestration mode from fixed algorithm; add plan/evidence/tool schemas plus a closed `OptimizationOutcomeContractV1` whose metric IDs, estimators, risk measures, constraints, transforms, scalarizations, references, missingness, and selection policies are registry enums rather than executable client expressions |
| `backend/app/services/jobs.py` and `backend/app/routers/jobs.py` | strict create/rerun validation, user-scoped nested routes, bounded Job serialization, compatibility aliases | add versioned orchestration object, legacy conflict detection, redacted summaries, cursor-paginated decision/provenance/event reads, transport-injected one-time session-reference exchange, expected-state/idempotency requirements, and non-secret Job-binding rules |
| `backend/app/auth.py`, `backend/app/main.py`, `runtime/config/runtime.env.default`, and API routers | OIDC issuer/subject identity, asymmetric algorithm allowlist, required `exp`/`iss`/`sub`/`aud`, exact CORS origins, and route-level user dependencies | replace packaged `AUTH_MODE=disabled` with mandatory `desktop_bridge`; move private `/api/v1` off loopback TCP; add launch/session request-proof verification, durable mutation idempotency, operation/state authorization, authenticated capabilities/readiness, hosted token profiles, and tenant/role policy before multi-tenant use |
| `desktop/src-tauri/src/lib.rs`, `desktop/src-tauri/capabilities/default.json`, `desktop/src-tauri/tauri.conf.json`, and `frontend/src/api/client.ts` | fixed Rust commands, main-window capability, restrictive script CSP, and typed frontend API surface | add a long-lived fixed desktop API bridge and typed Rust API/download commands; keep keys/references outside JavaScript; remove generic direct WebView fetch/download URLs and production API `connect-src`; narrow global Tauri exposure and noVNC frame origin |
| `backend/app/orchestration/aggregation.py` and `acceptance.py` | generation completion, case-weighted reliability denominators, hierarchical usable-replicate means before fixed case weights, seed-level worst constraints, training-field preference, continuation boundary, and a content-addressed search-role Candidate outcome compatibility projection consumed by ranking/acceptance/optimizer learning | replace exclusive GPT/CMA/experimental continuation branches with one dispatcher; migrate the embedded projection into an append-only `CandidateOutcomeEvidenceV1` ledger; finish one shared projection for validation promotion, portfolio reward, winner freeze, and reports; remove pre-ranking rounding and alternate acceptance arithmetic |
| `backend/app/orchestration/job_manager.py` | candidate/trial creation and generation dispatch | add atomic decision-linked batch dispatch and idempotency; replace duplicate-Candidate infrastructure retry with an exact logical-Trial retry that creates an immutable physical-attempt row |
| `backend/app/orchestration/runner.py` | short-lived per-stage sessions and polling lifecycle | split bounded lane pollers; add admission, per-user/Job fair scheduling, queue deadlines/backoff, capacity-before-running claims, drain/recovery, and paused/cancelled/unresolved fences |
| `backend/app/orchestration/trial_executor.py` | renewable Trial leases and `(trial, worker, attempt)` result fencing | recheck owning Job eligibility; persist one immutable row per physical attempt and content-addressed artifacts; invoke the signed secretless telemetry/metric verifier; accept at most one envelope by lease/capacity/input hash CAS; retain rejected/superseded attempt provenance |
| `backend/app/parameters/catalog.py`, `models.py`, `validation.py`, `backend/app/optimization/domain.py`, and `backend/app/orchestration/parameter_constraints.py` | real PX4 names, types, reviewed envelopes, choices, limited release overrides, Job-level dependency completion, normalized SearchSpace, projection, and concrete-vector validation | replace moving aliases/shared hand catalog with content-addressed firmware-build bundles; separate transport metadata, exact experiment lattice, and reviewed envelope; use decimal/rational grid indices and float32 wire identity; compile a closed complete-vector constraint graph; reject missing context and material silent projection |
| `backend/app/simulator/px4_parameters.py`, `scripts/simulators/local_px4_launch_wrapper.py`, and parameter evidence in `px4_gazebo_runner.py` | official session overrides, pre-flight readback, reboot-live rejection, before/applied evidence, compensating rollback, and runner-side evidence presence checks | make clean-start per-attempt copy-on-write storage mandatory; verify binary/build/component metadata rather than Git HEAD alone; hash full control-relevant baseline/final snapshots; enforce disarmed/landed/mode predicates; bind exact wire values and application state; move acceptance to a signed independent `ParameterApplicationEvidenceV2` verifier; disable live application initially |
| `backend/app/simulator/base.py` and `real_cli.py` | bounded typed result parsing, finite-number checks, sanitized artifacts, and complete v2 execution identity | add mandatory `trial_attempt_evidence.v3`; remove metric/flag defaults and runner-authored pass authority; require unit/frame/time/artifact/verifier bindings; keep v1/v2 read-only for historical reports and reject them as Harness evidence |
| `scripts/simulators/px4_gazebo_runner.py` | bounded telemetry, monotonic timestamps, 3-D reference projection, evaluation windows, and flight diagnostics | emit raw execution facts plus source ULog/canonical telemetry, not authoritative score/pass; add frozen gap/duration/coverage contracts; move time-weighted metrics and typed outcome classification into the signed verifier; make `all_samples_fallback` ineligible |
| `scripts/simulators/px4_offboard_track_executor.py` and `local_px4_launch_wrapper.py` | the implemented PX4 NED north/east/down to DroneDream x/y/-z mapping | name and version the current frame as `dronedream_local_neu_v1`; bind units/time base and test round trips; never label it ENU; migrate to standard ENU only under a new frame ID and explicit X/Y conversion |
| `real_cli.py`, `px4_gazebo_runner.py`, `local_px4_launch_wrapper.py`, and `scenario_effects.py` | intended Trial seed transport, deterministic dry-run generator, strict effect request/evidence validation, and fail-closed unsupported-effect preflight | stop treating inherited `PX4_TRIAL_SEED` as effective control; add the signed random-domain/seed-derivation contract, standalone or otherwise proven Gazebo `--seed` launch, per-plugin seed adapters/readback, realized-effect/time-map artifacts, repeatability classification, and seed-effect A/A tests; keep wind/noise/dropout/battery/payload unavailable until each physical adapter exists |
| `backend/app/orchestration/llm_parameter_proposer.py` | current numeric-history selection, response-size/local parameter validation, and legacy direct-LLM baseline | do not reuse generic `_safe_prompt_value()` or the current prompt; replace arbitrary scenario/profile/model labels and legacy holdout seeds with the closed evidence compiler, and move strict capability negotiation, bounded transport, retries, metering, and provider-origin enforcement to the gateway |
| `backend/app/schemas.py`, `backend/app/services/jobs.py`, and `LLM_ALLOWED_BASE_URLS` | URL syntax checks and current exact-string production allowlist | migrate configured entries into versioned provider profiles; enforce HTTPS/path/DNS/IP/TLS/proxy/redirect/response rules at the actual gateway connection and add network egress confinement |
| `frontend/src/features/settings/ModelAccessProvider.tsx`, `frontend/src/pages/NewJob.tsx`, `backend/app/secrets.py`, and `job_secrets` | provider/profile UI, draft secret blanking, current provider validation, and legacy encrypted-key cleanup | remove raw keys and live references from Web Storage and Harness create/rerun payloads; keep the reference in Tauri Rust, attach it through the authenticated bridge for one-time exchange, add non-secret Job bindings, a provider gateway, heartbeat/absolute expiry, revocation, and legacy-only reads |
| `frontend/src/pages/NewJob.tsx`, `frontend/src/features/experiment/draftStorage.ts`, and the new conversation page | a complete five-step form, session-scoped draft, redaction, exit warning, parameter catalog, and request compiler | extract one generated `ExperimentFieldRegistryV1` and `ExperimentDraftV3`; make conversation and form co-edit the same field/provenance state; add deterministic patch precedence, missing/conflict computation, default-review state, and no autonomous Job submission |
| `frontend/src/router.tsx`, `AppShell.tsx`, `DesktopSetup.tsx`, and i18n/styles | desktop readiness route, sidebar shell, Dashboard/manual experiment entry, bilingual UI | make the minimal conversation page the ready workspace default; retain Dashboard and manual five-step creation as equal paths; add configured-model selection, concise usage display, and a click-only microphone control with accessible active/stop/error states |
| new `backend/app/routers/experiment_assistant.py`, schemas, registry compiler, and provider gateway adapter | strict FastAPI envelopes, provider SDK, field and parameter validation | accept bounded conversation turns, call only a configured compatible model, parse `ConversationExperimentPatchV1`, compile registered conversions, recompute missing/conflicts server-side, return accepted/rejected patches, and never create a Job or accept model-authored executable fields |
| `backend/app/optimization/experimental_types.py` and `backend/app/orchestration/experimental_optimizer.py` | frozen bounded observations/requests, deterministic ordering, parameter projection, direction-aware constraints, pending visibility, and objective/feasibility separation | replace overloaded optional-loss/completed/failure-rate adapter input with the closed tagged observation algebra and separate pending reservations; pass exactly one declared objective representation per call; prohibit simultaneous objective-vector plus derivative scalar-loss utility; fail new rows on missing evidence/provenance; exclude infrastructure/evidence failures; keep legacy coercions in explicitly legacy-only snapshots |
| `backend/app/optimization/bayesian_optimizers.py`, `cma_optimizers.py`, and their adapter boundaries | six implemented numerical search families, deterministic seeds/fallbacks, bounded domains, constraints, optimizer-native state, and Job-bound Bayesian weights/scales with incomplete-vector fallback | bind every entry point to a signed tool-objective adapter declaring accepted estimand/risk/constraint/tag semantics; add fixed Pareto/reference inputs where required; block tools that cannot represent the requested contract rather than approximating it silently |
| `backend/app/optimization/portfolio_optimizer.py` | child statistics, allocations, provenance, deterministic fallbacks | expose child algorithms through pure versioned adapters; keep portfolio as an honestly named heuristic baseline/fallback; replace string ownership, hidden feasibility, moving-baseline reward, hand-weighted pseudo-UCB, order-dependent duplicates, and endless unavailable-child cold start with immutable routing opportunities, closed availability/circuits, policy-reserved exposure, exact multi-source attribution, signed `PortfolioRewardContractV1`, complete incurred-cost accounting, and delayed append-only rewards computed from Candidate envelopes |
| current in-worker optimizer calls, `runtime/systemd/dronedream-worker.service`, and `docker-compose.yml` | trusted optimizer implementations, service sandbox precedent, and simulator process-tree tests | add a separate proposal-tool executor/broker, per-call child isolation, Linux systemd/cgroup and hosted-container limits, local framed IPC, BLAS-thread controls, and containment conformance tests |
| `backend/app/models.py` | jobs, candidates, trials, one metrics row, secrets, append-only events | add decision, model-attempt, tool-call, evidence, candidate-source, immutable `candidate_outcome_evidence`, immutable `trial_execution_attempts`, artifact digest, registered metric provenance, Runtime dependency/circuit state, and Runtime-capacity tables plus outcome-contract bindings, relational provenance, scenario/replicate cells, winner-freeze/final-test commitments, readiness/backoff, and scheduler fields |
| `backend/app/config.py`, worker presence, and capability endpoints | bounded lease/heartbeat settings and advisory local-host concurrency warning | add release-bounded lane capacities, queue/admission ceilings, fixed fairness classes, Runtime-slot health, and explicit separation between Valkey wakeups/liveness and SQL queue truth |
| `backend/app/orchestration/events.py` | UI/worker event publication | add versioned reference events without full prompt duplication |
| existing workers and simulator adapters | authoritative execution, process-tree control, retries, artifacts, and metrics | remain outside model authority, but cease treating runner metrics as accepted evidence; add trace links, decision/attempt provenance, exact retry, trusted verification, and a narrow sealed final-test materializer |

### Version 1 minimum implementable slice

This document defines the target contract, not permission to activate every mechanism
in one release. A Harness that is too broad to test is itself a safety and research
risk. Anthropic's practical agent guidance recommends starting with the simplest
solution that works and increasing agentic complexity only when it measurably improves
the outcome. DroneDream therefore uses the following executable cut line for the first
controlled Harness pilot:

| Included and mandatory | Explicitly deferred or unavailable |
| --- | --- |
| one model turn using strict `submit_generation_plan`; no model-observe-tool-result loop | Version 2 inspect-and-select, nested model tools, free-form code/shell, self-modifying prompts, and autonomous Job creation |
| one frozen scalar-preference outcome profile with registered metrics, fixed suite/replicate estimand, feasibility-first constraints, and deterministic ties | arbitrary user metric expressions, runtime-defined reward functions, unconstrained multi-objective contracts, and online changes to weights/targets/risk |
| at least two conformance-passing scalar adapters—initially TuRBO and surrogate CMA-ES—plus fixed-algorithm and current deterministic-portfolio baselines; all Bayesian adapters now enforce one objective representation per call | multi-fidelity, SAAS-inspired, or other tools until the rest of their exact adapter contract passes; any future adapter that reintroduces a Pareto vector plus derivative scalar loss |
| one local desktop deployment profile, one bounded proposal-tool child at a time, and one local SITL execution slot | hosted multi-tenant scheduling, remote third-party tools, dynamic worker registration, and live hardware flight |
| immutable decision/model/tool/snapshot/source/outcome/reward/attempt ledgers; signed Runtime manifest; content-addressed evidence; exact replay labels | reconstructing missing legacy provenance, importing legacy portfolio scores as reward, or claiming bitwise replay when a dependency only supports tolerance replay |
| deterministic reserved exploration, exact proposal-source attribution, complete cost accounting, and descriptive delayed reward ledgers | adaptive online bandit updates, provider-token “propensities,” IPS/DR/SWITCH claims, or causal tool-ranking claims |
| search/validation separation, atomic winner freeze, and a sealed final-test verifier | exposing final-test cases or results to the model/optimizer, reopening search after final test, or repeated test-set peeking |
| desktop-held provider secret reference, authenticated bridge, bounded provider profile, egress policy, idempotency, cancellation, and recovery | raw API keys in JavaScript/Web Storage/Job drafts, arbitrary base URLs, automatic retry of ambiguous external effects, and live PX4 parameter mutation |

The minimum slice is not allowed to defer the evidence boundary, authorization,
idempotency, or final-test separation; those are what make the result a Harness rather
than a prompt wrapper. It may defer algorithm breadth, online learning, hosted scale,
and optional UI analytics. The release feature manifest lists every capability as
`enabled`, `shadow_only`, `unavailable`, or `legacy_report_only`; a missing entry is
unavailable. Promotion beyond this slice requires one named hypothesis, an evaluation
showing useful gain over the simpler baseline, a failure-boundary review, and a signed
manifest revision.

### Phase 0: freeze the research contract

- approve terminology and authority boundaries;
- define outcome hypotheses and baseline campaign before implementation;
- freeze the experimental unit, minimally meaningful effect, pilot-based
  power/precision procedure, blocking/randomization schedule, non-success estimand,
  exclusion/rerun rules, grader protocol, and multiplicity policy;
- freeze Version 1 decision and tool schemas;
- freeze `OptimizationOutcomeContractV1`: registered atomic/derived metric DAG,
  physical units and directions, fixed scenario population and weight interpretation,
  replicate-within-scenario estimators, non-success/missingness/censoring rules, risk
  estimators and minimum effective-tail evidence, outcome-constraint precedence,
  exactly one objective representation per tool, fixed transforms/scalarization or
  Pareto reference, deterministic ties, and the shared acceptance/promotion/selection
  projections;
- freeze `RoutingOpportunityV1`, `PortfolioRewardContractV1`, exploration/minimum-
  exposure/maximum-share schedule, availability/circuit states, pre-outcome
  multi-source attribution, delay/unobserved rules, cost catalog, action-probability
  provenance, and the rule that unsupported logs cannot make an off-policy performance
  claim;
- freeze the evidence field/provenance catalog and adversarial canary corpus;
- freeze ADRs for the closed Trial-outcome taxonomy, exact infrastructure retry,
  `trial_attempt_evidence.v3`, the metric registry, minimum duration/gap/coverage
  thresholds, and the compatible `dronedream_local_neu_v1` coordinate/time contract;
- freeze the random-domain registry, seed derivation/encoding, common-random-number
  eligibility, component binding-evidence schemas, host/time nuisance-factor record,
  repeatability classes, and same-seed language gate;
- freeze `ParameterContractBundleV1`, exact experiment-grid encoding, closed
  complete-vector constraint language, reviewed-envelope terminology, clean-start
  baseline/isolation policy, and `ParameterApplicationEvidenceV2`; explicitly decide
  that upstream `increment` is metadata rather than an unstated firmware lattice;
- freeze three-way `search`/`validation`/`final_test` isolation, winner-freeze and
  final-test materialization rules; document that existing `holdout=true` data is
  validation rather than an untouched test;
- define the canonical Harness runtime manifest, closed control-plane file roles,
  build-provenance verification policy, SBOM format, updater trust roots, and
  side-by-side runtime-slot lifecycle;
- freeze the deployment-profile threat model and caller/action matrix, including the
  explicit hostile-same-Windows-user/WSL limit; define which health surface, if any,
  may remain unauthenticated;
- create hashed train/development/test manifests and a locked-test access receipt;
- add architecture decision records for orchestration mode split and both sealed-test
  boundaries.

Exit gate: reviewers can state exactly what the LLM may and may not do and what
evidence would be sufficient to support or reject the primary Harness claim.

### Phase 1: deterministic internal tool registry

- wrap the six existing optimizers in pure versioned tool adapters, but enable only
  TuRBO and surrogate CMA-ES for the first scalar-profile pilot; every other adapter
  remains `shadow_only` or `unavailable` until its objective contract and containment
  conformance gates pass;
- add capability metadata and strict schemas;
- require each adapter to declare the one objective representation, estimators, risk
  measures, constraints, observation tags, and pending semantics it consumes; add
  cross-adapter goldens proving the same search-role Candidate envelope has the same
  feasibility and preference meaning, and reject any adapter that double-counts an objective
  vector through a derivative scalar loss;
- preserve every exact independently proposed duplicate source before outcomes, reject
  material proposal transformations from reward, and test that registry/tool iteration
  order cannot change source shares, routing state, or future allocations;
- generate the tool registry, prompt/schema catalogs, compiler/policy inventory, and
  per-file digests in CI from a clean tracked checkout; do not let a mutable runtime
  self-declare its trusted revision;
- test deterministic outputs, limits, deduplication, and typed errors;
- implement the proposal-tool executor protocol and a fresh-child runner before an
  adapter is eligible for Harness dispatch;
- implement pathname-socket ownership/mode checks, kernel peer-credential/service
  verification, one-request framed protocol, nonce/attempt/hash response binding, and
  descriptor/content-address snapshot transfer with traversal defenses;
- add the networkless, secretless WSL2 systemd service and hosted Compose sidecar with
  explicit CPU, memory, PID, swap, writable-path, and numerical-thread bounds;
- run destructive containment tests without the API, trial worker, or database losing
  liveness;
- keep the current deterministic portfolio behavior unchanged and explicitly labeled
  as the legacy heuristic baseline.

Exit gate: the minimum enabled pair can drive candidates without an LLM, produces
complete provenance, and yields identical compiled Candidate meaning under the same
scalar outcome contract; broader adapters may be present but cannot become eligible
merely because their code exists.

### Phase 2: decision ledger, capacity, and evidence snapshots

- add the ten Harness-domain tables, immutable `trial_execution_attempts`, artifact and
  registered-metric provenance, immutable `candidate_outcome_evidence`, generic
  API-idempotency table, scheduler/readiness fields, winner-freeze/final-test
  commitments, outcome-contract hashes, and candidate foreign keys;
- implement immutable routing opportunities/actions, complete eligible/excluded tool
  snapshots, typed availability/circuit transitions, append-only delayed reward/cost
  events, exact source-share reconciliation, and policy-state replay before the LLM can
  consume tool-performance summaries;
- implement bounded admission, separate durable lanes, `runtime_capacity_slots`,
  `runtime_dependency_states`, aggregate retry budgets, fenced one-probe operational
  circuits, capacity-before-running claims, per-user/Job fair scheduling, queue
  deadlines, typed overload, and drain/recovery before introducing provider traffic;
- retain SQL as the queue of record; Valkey wakeups and worker presence may reduce
  latency but never authorize or preserve work;
- implement canonical JSON and hashes;
- implement the v3 Trial-attempt envelope, versioned NEU telemetry extractor, closed
  metric registry, time-weighted metric compiler, typed outcome classifier, and
  secretless signed verifier before optimizer snapshots can read a real Trial;
- implement the metric dependency-DAG evaluator and outcome-contract compiler that
  reconciles expected case-replicate cells, aggregates within scenario and then across
  the frozen scenario population, computes predeclared risk/uncertainty/constraint
  evidence, and emits one immutable `CandidateOutcomeEvidenceV1`; make optimizer
  datasets, acceptance, promotion, winner freeze, reports, and portfolio rewards read
  that envelope rather than recalculate their own scores;
- implement named seed substreams, immutable derivation manifests, Gazebo/component
  seed adapters, binding-evidence verification, simulation/wall-time mapping,
  realized-effect artifacts, and per-attempt repeatability classification; an
  unsupported or unverified stochastic component cannot be silently upgraded to
  matched-seed evidence;
- generate content-addressed PX4-build parameter bundles from exact generated/component
  metadata; implement decimal/rational grid compilation, complete-vector constraint
  evaluation, float32 wire identity, clean per-attempt parameter storage, full
  baseline/final snapshot hashing, and an independent parameter-application verifier;
  do not expose live MAVSDK application to Harness Jobs;
- remove missing-metric defaults, rate clamping, pre-aggregation rounding, unregistered
  `raw_metric_json` optimizer fields, and runner-authored `pass_flag` from Harness paths;
- change retry persistence from duplicate Candidate creation to a new immutable attempt
  for the exact logical Trial; prove that infrastructure/evidence failures never enter
  the parameter dataset and Candidate-dependent crashes remain typed constraints;
- implement `search`, checkpointed `validation`, atomic winner freeze, and sealed
  one-Candidate `final_test` materialization; no final-test Trial row may exist
  pre-freeze;
- implement the closed evidence DTO directly from allowlisted typed queries; prohibit
  generic application-dictionary copying and prior model/error text feedback;
- prove byte-level exclusion of all untrusted-text, identifier, seed, credential, and
  sealed-test-source canaries before a provider adapter is added;
- add lease, state-version, and idempotency constraints;
- add monotonic per-job event sequencing while preserving the newest-25
  `recent_events` compatibility view;
- replace packaged-desktop `create_all()` upgrades with a backup-gated Alembic
  launcher, while retaining `create_all()` only for isolated development/tests;
- test populated-release upgrades, dialect-equivalent partial unique indexes,
  foreign-key enforcement, deletion order, restore-on-failure, and PostgreSQL parity;
- add versioned events plus bounded per-stage traces linked through durable correlation
  rows; keep raw content off and the SQL ledger canonical.

Exit gate: crash/restart tests cannot duplicate a decision, Candidate, logical Trial,
accepted physical attempt, metric observation, or final-test materialization, and every
accepted real observation replays from immutable source artifacts under its pinned
verifier.

### Phase 3: provider gateway and shadow mode

- replace packaged `AUTH_MODE=disabled` before enabling any Harness endpoint;
- extract `ExperimentFieldRegistryV1` from the five-step builder and generate the
  provider schema, draft normalizer, localized field catalog, and request compiler
  from it; add a draft migration that preserves current session drafts without
  promoting defaults to explicit user intent;
- add the conversation endpoint in compile-only mode: it may summarize, accept
  registry-bounded patches, compute missing/conflict state, and update the shared
  draft, but it cannot create a Job, dispatch a tool, read simulation evidence, or
  trigger Runtime readiness checks;
- remove the current API-key `sessionStorage` path before enabling conversation
  provider calls; use process-memory credentials only for an explicitly development
  profile and the desktop credential bridge for packaged production;
- implement the fixed long-lived Tauri Rust -> stdio bridge -> Runtime UDS path,
  in-memory launch session registry, canonical request/response proof, typed route
  commands, durable mutation idempotency, expected-state checks, and per-operation
  ownership authorization;
- remove packaged WebView direct `/api/v1` fetch/download paths and production API
  `connect-src`; preserve only a minimal rate-limited liveness probe or move readiness
  behind the bridge;
- prove hostile-origin/simple-request/DNS-rebinding/browser, missing/wrong MAC,
  replay/changed-body, stale-state, lost-response/restart, foreign-user/child-ID, wrong
  worker-token, bridge death, Runtime change, and CSP/capability negative cases;
- retain `disabled` only in isolated test/development configuration and prove
  `APP_ENV=desktop` fails startup under any non-bridge auth profile;
- freeze hosted access-token profiles, exact audience/issuer/algorithm/JWT-kind rules,
  and server-side tenant/role membership before any hosted Harness endpoint is
  enabled;
- implement capability negotiation and strict tool calls;
- persist immutable Job `ModelBinding`s; prefer provider snapshots over moving aliases;
  compare returned identity/fingerprint on every attempt and implement
  pause/fallback/fail drift transitions;
- add the desktop session credential bridge and provider gateway before accepting a
  Harness session credential reference;
- split gateway registration from provider calls; authenticate the registration helper
  with kernel peer credentials plus a Tauri-held per-launch MAC, authenticate provider
  calls with the fixed orchestration service identity, and persist only derived
  non-secret Job binding IDs;
- replace free-form custom URLs with immutable versioned provider profiles and a
  security-owned HTTP transport;
- disable nested SDK retries; make the orchestration transaction persist and reserve
  every physical attempt before the gateway can consume its one-use tuple, then
  classify and reconcile the returned result before another attempt is authorized;
- disable redirects and ambient proxy/environment discovery; enforce canonical
  HTTPS/path, checked-and-pinned DNS/IP, TLS hostname, response-size, deadline, and
  deny-by-default network-egress controls;
- remove the current custom-endpoint `json_object`/free-form retry from every Harness
  path, retaining it only in the explicitly named legacy direct-LLM baseline;
- prove normal-exit, crash, gateway-restart, idle-expiry, absolute-expiry, revocation,
  profile-mismatch, cross-job/user reference rejection, registration/call socket
  separation, wrong-peer rejection, heartbeat forgery rejection, and exact
  duplicate-versus-changed replay behavior;
- prove redirect-to-private, DNS rebinding/TOCTOU, mixed IPv4/IPv6, alternate IP
  spelling, proxy-environment, certificate/SNI, metadata-IP, and oversized/compressed
  response rejection without credential retransmission;
- generate plans without dispatching them;
- compare shadow plans to deterministic portfolio choices for schema, allocation,
  diversity, availability, cost, and policy-rule diagnostics only; do not score the
  unexecuted alternative as if its counterfactual Candidate outcomes were observed;
- test conversation patch extraction against natural-language, correction,
  contradiction, unit-conversion, multilingual, prompt-injection, and parameter-
  hallucination corpora; keep all accepted changes attributable to exact user turns;
- build decision evals and adversarial tests.

Exit gate: caller authentication/authorization, idempotency, valid-plan, credential,
provider-origin, and network-containment suites meet thresholds; direct unauthenticated
desktop `/api/v1` is gone; capability drift fails closed; no production optimization
behavior changes.

### Phase 4: guarded live dispatch

- enable `llm_harness` behind a feature flag;
- default to a small allowlist and deterministic fallback;
- run mock and real SITL campaigns under fixed budgets;
- run evidence fault-injection and real-ULog replay campaigns before accepting the
  outcome comparison; report infrastructure, domain, censoring, and evidence-contract
  outcomes separately;
- run outcome-contract fault injection: delete one replicate, duplicate one scenario
  row, perturb scenario weights, rescale a metric, cross a constraint threshold, shrink
  a tail below its minimum evidence, swap scalar/vector adapter inputs, and alter
  normalization/reference data; require ranking, acceptance, promotion, reports, and
  replay either to remain contract-consistent or fail closed together;
- run routing-credit fault injection: reorder tools, emit exact cross-tool duplicates,
  emit same-tool duplicates, replace requested fidelity, return a materially projected
  vector, make one tool unavailable, delay or lose a Candidate outcome, vary batch
  sizes/cost, restart between opportunity and reward, and inject invalid propensities;
  require attribution/cost reconciliation, bounded exploration, circuit behavior, and
  policy replay without fabricated off-policy support;
- run same-substream/different-substream A/A campaigns across supported Runtime/host
  profiles, disconnect each seed adapter deliberately, and verify that common-random
  pairing is enabled only when all relevant binding hashes agree;
- run baseline-isolation A/B/A campaigns across every supported PX4/airframe/Runtime:
  apply an extreme reviewed-envelope treatment between two no-override starts and
  require identical full control-relevant baseline digests; corrupt binary, generated
  metadata, component metadata, lattice, disarmed-state, write-readback, and rollback
  evidence independently and prove every case fails before flight;
- open the sealed controller final test only after one winner and all policies are
  committed; a failed final test terminates that campaign rather than resuming search;
- inspect all fallback and rejected-plan traces;
- ship the global/provider/tool kill switches and rehearse generation-boundary
  rollback before enabling live decisions.

Exit gate: no budget, sealed-test, safety, or duplicate-dispatch violations; outcome
results justify continued rollout.

### Phase 5: product and course release

- expose UI configuration and decision traces;
- ship Conversation as the ready workspace default while preserving Dashboard and
  the manual five-step path; prove both paths compile byte-identical requests for the
  same explicit values and continue editing one shared draft;
- ship microphone input only after click-only permission, active/stop lifecycle,
  transcript-before-send, no-audio-retention, disclosure, unsupported-browser
  fallback, and WebView2 permission tests pass;
- publish ablations and limitations;
- retain deterministic modes;
- document provider privacy/cost requirements;
- extend the signed Runtime release with the Harness manifest; generate and verify
  commit-pinned GitHub build/SBOM attestations in addition to Runtime Ed25519 and
  Windows Authenticode signatures;
- install verified Runtime releases into content-addressed side-by-side slots, pin
  every Job to one slot, rehearse rollback/revocation, and keep unattended Runtime
  updates disabled until a TUF-conforming metadata path is deployed;
- promote only after real PX4/Gazebo evidence, not synthetic benchmark results.

## 25. Verification matrix

| Layer | Required tests |
| --- | --- |
| schema | golden valid/invalid payloads for every provider adapter; legacy/new orchestration mapping and conflict cases; nested additional-property rejection; refusal/truncation/multiple-plan cases |
| conversational draft schema and compiler | generated field-registry parity with every five-step control and `JobCreateRequest`; strict additional-property/type/enum/unit/range rejection; parameter-catalog and reviewed-envelope validation; explicit/derived/proposed-default/missing/conflict states; deterministic correction precedence; no model authority over owner/status/secret/Runtime/evidence/tool/server fields; no autonomous create/start path; byte-identical request compilation between conversational and manual drafts |
| conversational model turns | bounded message/summary/draft projection; strict structured response and refusal handling; server-recomputed missing/conflict questions; stale-turn and out-of-order-response fencing; multilingual ordinary-language, voice-transcript, correction, contradiction, vague-intent, unit-conversion, unsafe-budget, catalog-hallucination, and prompt-injection fixtures; field-level accepted/rejected provenance; no sealed-test, Job-history, arbitrary import, secret, Runtime-path, or simulation-evidence bytes in provider requests |
| conversational UI and draft lifecycle | ready launcher and browser index open Conversation; sidebar order Conversation, Dashboard, Run History, ECE498BH; manual New Experiment unchanged; model selector exposes configured compatible profiles only; unconfigured send opens Settings; accepted patch appears in the same five-step draft; navigation round-trip has no duplicate draft; exit warning covers conversational/form drafts; confirmed exit erases both; active submitted Job warning remains separate; conversation route never starts an environment check |
| voice input | zero microphone API calls before explicit click; first-use permission, deny, missing device, unsupported API, timeout, recognizer/transcriber failure, and retry states; visible recording and accessible stop; duration/size bounds; stream tracks stop on stop/cancel/navigation/unmount; transcript is editable before send; raw audio absent from draft/Web Storage/log/trace/error/support export; on-device versus named remote transcription disclosure; no silent reuse of reasoning credentials; typing fallback preserves the draft |
| snapshot | deterministic canonical bytes/hashes; missing-value semantics; byte-budget truncation; closed field/provenance catalog; mutually exclusive objective/constraint/right-censored tags; PendingReservation separation; source Candidate/Trial/accepted-attempt/evidence-hash reconciliation; infrastructure/evidence/cancelled/superseded exclusion; unknown-key/unit/name failure; byte-level canaries proving display/vehicle/scenario/model/simulator/tool/provider text, IDs, seeds, secrets, and sealed-test rows cannot enter the request |
| registry | tool ID/version uniqueness; capability and tagged-observation eligibility; explicit missing-objective, right-censoring, pending, fidelity, and state-update semantics; stable seed derivation; input/output conformance |
| routing opportunity, attribution, and reward | immutable complete eligible/excluded action set and availability/circuit reason; policy-reserved versus discretionary allocation; actual exposure reconciliation; exact Candidate/source grouping independent of tool order; same-tool duplicate share collapse; cross-tool source shares sum to one; material projection and fallback ineligibility; incumbent predates action; fixed-scale feasibility-first bounded reward; full proposal/Trial/fidelity/compute cost including invalid/duplicate/unobserved outcomes; delayed reward after restart; infrastructure exclusion without cost erasure; no validation/final-test leakage; unavailable tool cannot consume endless cold starts; rolling minimum/maximum exposure; deterministic replay; invalid/unknown/LLM-derived propensity rejection; deterministic-policy no-support state; IPS/DR/SWITCH support/effective-sample/clipping/uncertainty gates; end-to-end blocked randomized policy comparison |
| plan validator | property-based allocations, fidelities, evidence references, stale state versions, stop/pause policies, and oversubscription |
| plan compiler | golden canonical bytes; policy/model merge; order independence; seed and fidelity resolution; upper-bound cost |
| tool adapters | deterministic replay for canonical requests; objective fit skips constraint-only rows without imputation; constraint-only feasibility/ranking behavior; unsupported right-censored input blocks eligibility; pending rows deduplicate/preserve cohort state but never train models; CMA incomplete/open cohort and missing-objective deterministic behavior; typed partial/error behavior; timeout; unavailable backend; no database writes |
| Trial result and provenance | v1/v2 readable but Harness-ineligible; complete v3 identity/input/Runtime/artifact/telemetry/verifier binding; missing/defaulted/non-finite/unknown fields; attempt/fence/capacity/state mismatch; altered input/reference/parameter/scenario/source-ULog/telemetry/artifact digest; duplicate accepted envelope; changed bytes under the same hash/key; W3C-PROV lossless projection; accepted evidence replay from immutable bytes |
| telemetry and metric verifier | NED↔NEU round-trip fixtures and explicit ENU-mislabel rejection; SI unit/dimension and monotonic vehicle-time enforcement; duplicate/reordered timestamps; minimum count/duration/coverage and maximum-gap boundaries; irregular-resampling invariance of trapezoidal RMSE; analytic track-distance goldens; endpoint/non-completion/censoring cases; `all_samples_fallback` ineligibility; absent endpoint error never becomes zero; registered metric-only consumption; unknown `raw_metric_json` exclusion; corrupted rate rejection without clamping; verifier process network/secret/database denial |
| objective, estimand, risk, and selection | metric dependency-DAG acyclicity/type/unit/direction goldens; physical-value versus preference-value separation; balanced and unbalanced nested case/replicate fixtures; frozen scenario-weight interpretation; missing/excluded/censored/non-success cell manifest reconciliation; no surviving-row weight renormalization; minimum effective-tail and uncertainty evidence; mean/quantile/CVaR/chance-constraint analytical goldens; finite-sample boundary and tie cases; parameter/outcome/operational/evidence constraint precedence; fixed transform/scalarization/Pareto-reference hashes; one objective representation per ToolCall; scalar-vector double-count rejection; Candidate-envelope canonical replay; search/validation/final-test role and checkpoint non-mixing; search-only optimizer/reward eligibility; invariant feasibility/ranking/acceptance/promotion/report projections across optimizer adapters; legacy million-penalty, hidden `failure_rate < 0.5`, rounded threshold, adaptive min/max, and raw-metric regression fixtures |
| Trial outcome and retry | closed failure-domain/stage/reason mapping; unknown runner code fails closed; PX4 boot/readiness/port/storage/DB/worker failures excluded from parameter evidence; verified crash/instability retained as typed constraints; deadline with/without signed phase proof; exact logical-Trial retry creates a new attempt but no Candidate/sample; one accepted attempt maximum; stale/superseded attempt fencing; exhausted retry leaves Candidate incomplete and pauses/fails without penalty fabrication |
| randomness and time | seed-derivation byte/length/endian/domain-separation goldens across Python/Rust/launcher implementations; no cross-domain or Candidate-dependent physical substreams; same logical Trial retry preserves treatment substreams but creates a new attempt; exact Gazebo/component pre-start delivery and request-bound readback; disconnected/swapped/truncated seed rejection; plugin/version/world/SDF hash mismatch; realized wind/dropout trace evidence; simulation/wall/executor/PX4 time mapping, pause/reset/jump and achieved-speed bounds; same-substream/different-substream A/A variance across supported Runtime/host profiles; honest repeatability-class downgrade; common-random comparison disabled after any relevant binding mismatch |
| parameter contract and application | exact PX4 commit/build/binary/generated-metadata/component-metadata bundle generation; dirty/stale binary and moving-alias rejection; runtime missing/read-only/type/enum/reboot mismatch; immutable old-bundle replay; decimal/rational grid and cross-language index goldens; off-grid bounds/baselines/proposals, float32 wire/ULP and midpoint cases; complete-vector conditional/ratio/order/unit/companion graph property tests; material projection provenance; per-attempt clean rootfs/parameter store; no-override/treatment/no-override baseline-isolation A/B/A; disarmed/landed/mode predicate failures; startup readback and full snapshot hash; sequential live-write transition/ambiguous acknowledgement/rollback fault injection; evidence-verifier independence and infrastructure-outcome classification |
| scenario isolation | current `holdout=true` migration to validation; disjoint search/validation/final-test identities and query permissions; no final-test definition/seed/row/event/provider/tool byte before freeze; atomic winner/hash/policy/budget commitment; one-Candidate final-test materialization; no next-best retry, threshold change, or search resume after result; repeated test access creates a new campaign |
| tool containment | WSL2 systemd/cgroup and hosted-container conformance; native-Windows disabled/degraded labeling; network/subprocess/secret denial; process-tree kill; CPU, memory, PID, thread, output, and wall-clock bounds; BLAS oversubscription measurement; pathname-socket owner/mode/stale-path checks; wrong UID/GID/cgroup/container rejection; canonical frame/version/length/duplicate/trailing-byte corpus; nonce/attempt/input/result binding and replay/coalescing behavior across broker restart; caller resource-limit widening rejection; sealed-descriptor/content-address length/hash verification; absolute/relative/`..`/symlink/magic-link/mount/TOCTOU path corpus; stale/late result fencing; exception-chain redaction |
| supply chain | clean-checkout manifest generation; dirty/untracked input, symlink/device/socket, path traversal, case collision, duplicate, TOCTOU, and unlisted executable rejection; per-role file/hash and final-image dependency/SBOM reconciliation; full-commit action pins; artifact/SBOM attestation verification against exact repository/workflow/issuer/ref/commit/builder/subject; Authenticode + Runtime Ed25519 + provenance independence; startup integrity mismatch; registry/prompt/compiler/policy/gateway/executor cross-process manifest agreement; side-by-side activation; active-Job pinning; slot retention; tag/version/digest reuse, rollback, freeze, mix-and-match, root rotation, revocation, interrupted activation, and offline freshness cases |
| batch gate | exact lattice compilation, material-projection rejection, complete-vector constraint graph, non-finite values, duplicate vectors, exact cost, partial batches, provenance |
| persistence | ordinary and partial uniqueness constraints on SQLite/PostgreSQL; compare-and-swap; lease expiry; canonical TEXT/hash parity; restart at every state; idempotent re-entry |
| admission and scheduling | load-derived global/per-user/Job/lane caps; first-generation operational-cost estimate; bounded materialization; `202`/`429`/`503` and `Retry-After`; idempotent resubmission; fair service across one huge and many small Jobs; split/retry priority-gaming rejection; aging/starvation bound; queue deadline; deterministic jitter; no-attempt-while-waiting; provider/tool/simulator/report lane isolation; capacity-before-running; simulator instance/port/workdir uniqueness; no hidden in-memory/socket/SDK queue; per-dependency aggregate retry budget; closed/open/one-half-open-probe state transitions, stale-probe fencing, classification exclusions, projection replay, and circuit/reward separation; Valkey loss with SQL recovery; overload goodput/latency knee; control-lane responsiveness; drain and crash recovery |
| migrations | fresh and populated prior-release upgrades on SQLite/PostgreSQL; named constraints/index inspection; desktop online backup and forced-failure restore; foreign-key/integrity checks; old-row compatibility; forward-fix rehearsal |
| concurrency | two orchestrators racing for one generation; cancel/dispatch and pause/resume races; stale provider return after cancellation or another dispatch; Job-finalization lease versus Decision lease; worker restart after commit; fixed Job→child→capacity→event lock order; injected deadlock/contention; PostgreSQL `SKIP LOCKED` plus fence; SQLite single-writer saturation and busy-timeout recovery |
| provider transport | built-in/custom profile normalization; userinfo/query/fragment and encoded-delimiter rejection; HTTPS and exact path/port policy; redirect-to-public/private/metadata rejection; no credential retransmission on 3xx; DNS public-to-private and mixed-answer failure; resolution-to-connect pinning; IPv4/IPv6 and alternate-spelling corpus; TLS certificate/SNI/hostname failure; ambient proxy/CA/`.netrc` denial; connection-pool invalidation; header/compressed-body/JSON-depth bounds; per-phase/total timeouts; immutable model-binding creation; alias-to-snapshot resolution; returned identity/fingerprint match; probe TTL/invalidation and mid-Job drift/retirement transitions; alias-only reproducibility labels; strict-schema downgrade failure; SDK retries disabled; one database attempt per injected physical request; pre-send versus ambiguous post-send classification; request-ID capture on success/error; stable idempotency-key reuse; `Retry-After` ceiling; profile-wide retry-storm budget and circuit interaction; confirmed/estimated/unknown usage reconciliation and worst-case budget retention |
| provider gateway | registration/call pathname-socket owner/type/mode and wrong UID/GID/cgroup tests; client verification of gateway peer; fixed-helper/distro/argv allowlists; stdin length and zeroization best effort; launch MAC, nonce, monotonic-heartbeat, expiry, and revocation corpus; session-reference one-time exchange; Job/user/contract/model/profile binding; attempt nonce/request-hash/ceiling binding; in-flight coalescing and completed replay cache; changed-byte replay rejection; gateway/worker/Tauri restart matrix; no database credential or tool/simulator socket access; explicit proof that V1 does not claim independent database-state authorization |
| desktop caller authentication | packaged startup rejection for `disabled`/demo/OIDC profiles; no private `/api/v1` TCP listener; fixed bridge executable/distro/user/argv and bounded stdio/UDS frames; socket owner/type/mode/peer and response-peer checks; launch key separation; wrong/missing/expired/revoked session; frame/body/runtime/manifest/request/response MAC mismatch; exact replay coalescing versus changed-byte rejection; bridge/API/Tauri/Runtime restart; direct loopback, hostile-origin simple POST, preflight, DNS-rebinding, other-user, browser, arbitrary local client, and wrong-workload attempts; production CSP/capability/direct-fetch absence; explicit negative test documenting that same-Windows-user WSL-root or injected-Tauri compromise remains outside V1 |
| authorization and API idempotency | per-route caller/action matrix; owner/foreign/missing object equivalence; nested Job-child scoping; server-derived user/tenant/role; every finite-state transition and out-of-order invocation; missing/stale expected-state versions; exact concurrent/restarted mutation replay returns one result; changed payload/key conflict; crash before/after idempotency/domain commits; deletion tombstone retry; raw-export native confirmation; admin/worker/end-user token substitution; OIDC wrong issuer/audience/algorithm/JWT kind/authorized party/tenant/scope/role and JWKS rotation/failure corpus |
| security | injection corpus across Job/profile/scenario/import/model/simulator/artifact/tool/provider sources, Unicode/encoded/split/nested payloads, and repeated stochastic attack attempts; secret canaries across Web Storage, create/rerun bodies, argv/env, DB, backups, logs, traces, errors, support exports, and proposal workers; session-reference and Job-binding replay/cross-user/profile mismatch; normal/crash/TTL revocation; unknown URLs/commands, sealed-test probes, oversized output, malicious tool metadata; firewall/egress-proxy proof that desktop bridge, provider gateway, and tool executor interfaces/egress remain disjoint |
| observability | prove current deployment has no implicit “existing tracing” dependency; bounded per-stage trace creation across queue delay/restart; durable link resolution and fan-out/fan-in semantics; missing/sampled/dropped context has no control effect; fixed span-name and attribute catalogs; bounded `error.type`, Trial outcome/failure stage, schema/metric/verifier and coverage enums; domain-constraint outcome not mislabeled as infrastructure error; raw-ID-to-rotating-HMAC projection; no Baggage secrets/IDs; metric cardinality/series ceilings and explicit rejection of Candidate/parameter/attempt dimensions; HTTP/SQL/log/exception auto-instrumentation redaction; secret/final-test/content canaries before queue and exporter; external exporter allowlist/TLS/egress/queue/TTL failure tests; attempt/envelope/ledger-versus-trace completeness reconciliation |
| API compatibility | old web-development create/rerun/list/detail/compare/CSV fixtures; desktop typed-command parity for JSON/artifact/CSV flows; bounded orchestration summaries; user-scoped nested IDs; event cursor gaps/ordering; unknown event tolerance; no raw secret/session reference/provider envelope; explicit migration failure rather than silent direct-fetch fallback |
| evaluation | pilot-based power/precision calculation; problem-replicate experimental unit; family/instance/host/time blocks and randomized/interleaved arm order; common-random-number pairing only with identical accepted binding manifests; hierarchical/cluster inference; frozen non-success and censoring rules; locked train/development/test manifests and access audit; baseline selection without test leakage; intention-to-run and symmetric infrastructure sensitivity analyses; `pass@1`, `pass^k`, and deployment-faithful `pass@k`; deterministic grader goldens; blinded human/model-grader calibration; immutable statistical report generation |
| end to end | mock workflow first, then real SITL; provider outage with every fallback policy; cancellation and resumption; deliberately disconnected Gazebo/plugin seed path cannot claim or execute a common-random matched campaign |
| lifecycle | application exit during each decision state; paused Job remains unclaimable; desktop API/provider session-secret erasure; bridge disconnect/re-registration; raw-content TTL; complete service-level job deletion plus retained idempotency tombstone behavior |
| rollback | global/provider/tool kill switches; generation-boundary fallback; no mid-batch relabeling or substitution |

The crash-injection suite must terminate the process immediately before and after
each durable transition and then restart it. Passing only happy-path unit tests is
not evidence of durable execution.

## 26. Acceptance criteria

The Version 1 backend is complete only when:

- the LLM selects from versioned allowlisted proposal tools;
- the model has no simulator, shell, secret, or database-write tool;
- the canonical provider request is built from a closed provenance-aware DTO and
  contains no arbitrary Job/scenario/import/model/simulator/tool/provider text,
  identifiers, seeds, credentials, or sealed-test material;
- prior model output re-enters a later decision only through trusted compiled,
  simulated, and recomputed numeric evidence, never through label/rationale/error
  text;
- strict schemas and application semantic validation are both enforced;
- proposal workers accept only persisted compiled calls, never raw provider output;
- the optimizer dataset uses mutually exclusive objective, constraint-only, and
  right-censored tags plus separate pending reservations; infrastructure,
  evidence-contract, cancellation, and supersession records cannot be adapted into
  numerical observations;
- every proposal adapter is exposed only when its signed registry contract supports
  every observation tag present; the six initial tools do not claim right-censored
  learning, and no wrapper may substitute a large loss or an ordinary completion
  metric;
- every Job pins one `OptimizationOutcomeContractV1` that names the registered metric
  DAG, physical units/directions, scenario population and weights, nested
  replicate/scenario estimand, non-success/missingness/censoring rules, risk
  estimators, outcome constraints, fixed transforms, one objective representation,
  scalarization/Pareto reference, deterministic ties, and acceptance/promotion/final
  selection projections;
- every completed Candidate has exactly one accepted immutable
  `CandidateOutcomeEvidenceV1` for each materialized role/checkpoint; optimizer
  ranking, online portfolio reward, and search acceptance consume only the current
  search-role envelope, validation promotion consumes the exact validation-checkpoint
  envelope, and the terminal final verdict consumes only the post-freeze final-test
  envelope; no subsystem pools roles or independently recomputes a semantically
  different score;
- one ToolCall receives exactly one declared objective representation; simultaneous
  use of an objective vector and a scalar derived from that vector, adaptive
  observed-range normalization, random unregistered scalarization, hidden feasibility
  thresholds, million-scale fabricated loss, pre-decision rounding, or optimizer-only
  acceptance arithmetic fails the release suite;
- scenario replicates are aggregated within their frozen population cell before
  scenario weights are applied; missing/excluded/censored cells retain explicit
  denominator/effective-sample evidence and cannot disappear through renormalization
  of surviving rows;
- raw physical metrics, preference transforms, risk estimates, constraint values, and
  uncertainty/effective-tail evidence remain separately inspectable; a displayed
  composite score cannot replace the registered components or alter their units;
- every routing decision has an immutable pre-action opportunity containing the exact
  eligible/excluded tool set, availability/circuit states, cost ceilings, outcome and
  reward contracts, incumbent evidence, policy-reserved allocation, discretionary
  capacity, routing-policy revision, and either a validated DroneDream-sampled action
  probability or an explicit no-off-policy-support state;
- every Candidate preserves all exact pre-outcome proposal sources; cross-tool source
  shares are order-independent and sum to one, same-tool duplicates cannot multiply
  credit, material transformations and ineligible fallbacks receive no positive
  original-tool reward, and the display primary source never becomes sole causal
  attribution;
- `PortfolioRewardContractV1` derives bounded feasibility-first reward from the same
  immutable search-role Candidate envelope and a pre-action incumbent under fixed meaningful
  scales; all allocated/invalid/duplicate/fallback/physical/fidelity/compute cost
  remains charged, while missing/delayed/infrastructure evidence cannot be fabricated
  as zero or negative parameter quality;
- mandatory exploration, minimum tool exposure, rolling maximum share, availability
  circuits, cooldown, and cost/fairness limits are deterministic Job policy outside
  LLM authority; a broken/incompatible tool cannot consume repeated cold-start slots,
  and an early noisy winner cannot eliminate the frozen exploration floor;
- historical plans without validated randomized action probabilities and action
  support are never presented as an unbiased off-policy comparison; LLM token
  probabilities, temperature, or repeated prompts are not propensities, and any
  IPS/DR/SWITCH analysis reports support, effective sample size, importance weights,
  uncertainty, estimator revision, and failure gates;
- numerical proposal code cannot run in the orchestration worker, and every supported
  production deployment passes the platform-specific containment suite;
- only the authorized orchestration service can connect to the proposal executor; every
  request/result is bound to one call attempt, nonce, compiled input, registry, runtime,
  and hard resource profile, while arbitrary paths/modules/commands/environment and
  replayed/forged responses are rejected before persistence;
- every Harness Job pins one CI-produced, release-authenticated runtime manifest whose
  closed inventory covers the registry, all model-visible tool descriptions, prompts,
  function schemas, compilers, safety policies, provider adapters, gateway, executor,
  optimizer implementations, dependency lock, and SBOM;
- release and startup gates verify exact artifact digests plus Authenticode, Runtime
  signature, and build/SBOM provenance under their separate trust policies; a missing,
  altered, unlisted, rolled-back, mixed-release, or revoked control-plane byte blocks
  Harness mode rather than accepting a self-reported revision;
- Runtime activation is atomic and side-by-side: active Jobs retain their verified
  slot, new Jobs use the newly activated slot, and historical replay never substitutes
  current code for a missing pinned Runtime;
- packaged `APP_ENV=desktop` cannot start with `AUTH_MODE=disabled`, demo bearer, or a
  direct WebView credential; private/state-changing `/api/v1` traffic is absent from
  Windows-visible loopback TCP and crosses only the typed Tauri Rust -> fixed bridge ->
  Runtime UDS path;
- the packaged WebView has no API launch key, live provider session reference,
  Authorization header, generic backend URL/header command, or direct artifact/CSV
  download URL; production CSP/capabilities expose only the finite local commands and
  exact non-API viewer origin actually required;
- every desktop request/response is bound to one launch, principal, route, canonical
  body, request ID, Runtime, and Harness manifest, while expiry, revocation, replay,
  changed bytes, wrong peer, bridge death, and Runtime replacement fail closed;
- every user mutation has durable idempotency and, where a resource already exists, an
  expected state version; exact lost-response/restart retries return one committed
  result and changed-payload key reuse is rejected;
- every API operation checks owner/tenant/role, specific resource and current workflow
  state on the server; nested IDs resolve through the authorized Job, administrative
  and workload interfaces reject ordinary user tokens, and no request body can choose
  its own owner, tenant, role, spend, or state;
- hosted access tokens use mutually exclusive issuer/audience/algorithm/JWT-kind
  profiles, stable `(iss, sub)` identity, and server-side tenant/role membership before
  hosted Harness enablement;
- Harness provider keys never enter Web Storage, create/rerun payloads, Job tables,
  backups, traces, or tool executors; a live session reference is exchanged once and
  never exposed to packaged JavaScript or persisted, while non-secret Job bindings
  fail closed after session loss, profile mismatch, revocation, or cross-user/job
  replay;
- registration and provider-call interfaces are separately authenticated, every
  provider request consumes one Job/model/profile/request-bound attempt tuple, and the
  gateway cannot be reached by the WebView, API, simulator, or proposal executor;
- the Version 1 assurance statement does not claim that the gateway independently
  verifies database reservation, cancellation, or state-fence truth; those remain
  transactional worker/CAS responsibilities, and adversarial-worker deployments add a
  separate signed-grant or read-only authorization boundary;
- every Harness provider request uses an approved immutable profile and passes the
  actual-connection provider-origin suite: no redirect following, ambient proxy or
  arbitrary URL/header input; checked-and-pinned public destination; verified TLS;
  bounded response; deny-by-default egress;
- unsupported strict schema behavior blocks Harness use instead of invoking the
  legacy free-form custom-endpoint fallback;
- each Job has an immutable model binding and each accepted response matches its
  requested snapshot/observed identity/fingerprint and unexpired capability probe;
  drift or retirement pauses, falls back, or fails according to the frozen Job policy
  and never silently follows an alias;
- an alias-only provider is labeled `alias_only_unpinned`, cannot support an exact
  model-rerun claim, and is excluded from confirmatory campaigns that require a pinned
  model;
- provider SDK retries are disabled or fully surfaced; every physical request has one
  durable attempt row, and ambiguous post-send usage retains its cost upper bound
  before any retry is authorized;
- every physical simulator execution has one immutable `trial_execution_attempts` row
  bound to the exact logical Trial, attempt fence, input/parameter/scenario/reference
  hashes, Runtime manifest, artifact digests, and closed outcome class;
- every Job pins a content-addressed `ParameterContractBundleV1` that reconciles the
  exact PX4 binary/build provenance, generated upstream metadata, observed component
  metadata, DroneDream reviewed envelope, exact domain compiler, and closed constraint
  graph; aliases, semantic versions, checkout HEAD, and moving documentation links are
  never executable identity by themselves;
- every Candidate has one complete exact-lattice parameter vector including locked and
  referenced companions; grid origin/quantum/index and float32 wire representation are
  deterministic across implementations, material projection is rejected and recorded,
  and missing constraint context cannot evaluate as valid;
- every real Harness attempt starts from an isolated pristine parameter store, proves
  the full control-relevant baseline/final snapshot hashes, and is ineligible to arm
  until an independent `ParameterApplicationEvidenceV2` verifier accepts component,
  state, exact-wire readback, and constraint evidence; live sequential MAVSDK writes are
  disabled in Version 1;
- every outcome-relevant random domain has a signed adapter/capability record and an
  accepted state of `verified_bound`, `configured_unverified`, `not_seedable`,
  `nondeterministic_uncontrolled`, or `not_stochastic`; an inherited environment
  variable alone can never produce `verified_bound`;
- reports and pairwise evaluators use “same seed” or “common random numbers” only when
  scenario instance, component/version/configuration, derivation manifest, and
  request-bound seed-effect evidence hashes all match; otherwise they downgrade the
  repeatability class and require independent replication;
- the real PX4/Gazebo release gate proves that changing each declared physical seed
  domain changes its target evidence and that disconnecting an adapter blocks matched
  comparison; requested and achieved simulation speed/time mapping and host nuisance
  factors are retained for every attempt;
- Harness decisions accept only complete `TrialAttemptEvidenceEnvelopeV3`; legacy v1/v2
  results remain historical and cannot be promoted by compatibility defaults;
- the signed secretless verifier, not the external runner, derives registered metrics,
  constraints, outcome class, and pass inputs from immutable source artifacts under
  the pinned unit/frame/time/coverage contract;
- missing metrics never default, corrupt rates never clamp, evidence precision never
  rounds before persistence, and unregistered `raw_metric_json` keys never become
  optimizer or provider evidence;
- infrastructure and evidence-contract failures carry no parameter-quality evidence:
  bounded recovery retries the exact logical Trial as a new attempt, not a replacement
  Candidate, and exhaustion leaves the Candidate incomplete rather than inventing a
  penalty;
- verified Candidate-dependent crash/instability and completion deadlines are retained
  only as the frozen typed constraint/censoring observations supported by the selected
  proposal tool;
- final-test definitions, seeds, rows, events, and outcomes cannot enter any
  optimization evidence snapshot or exist before winner freeze;
- only the atomically frozen Candidate is materialized for the sealed final test; its
  failure ends the campaign and cannot select the next Candidate, change acceptance
  thresholds, or resume search;
- every generation has at most one active decision;
- restart and retry tests prove idempotent behavior;
- SQL domain rows remain the sole durable queue truth; every lane has load-tested
  global/per-user/Job limits, capacity slots, queue deadlines, typed overload
  responses, deterministic delayed retries, and no unbounded in-memory or socket
  backlog;
- fair scheduling and per-Job active caps prove that one large/old/retrying Job cannot
  starve later Jobs, while control-plane cancellation, revocation, and health remain
  responsive under saturated data lanes;
- a ModelAttempt, ToolCall, Trial, or report is never marked externally running before
  its compatible Runtime capacity slot is atomically leased, and a waiting item
  consumes neither attempt count nor provider/simulation budget;
- shutdown/restart/Valkey-loss tests drain or fence every lane without losing SQL work,
  duplicating external effects, holding locks during waits, or reviving terminal
  dead-lettered attempts;
- budget is checked before and during atomic dispatch;
- all candidates link to a decision and tool call;
- fallback is explicit in API, event, report, and trace;
- decision replay can reproduce the downstream candidate batch;
- evidence replay reproduces every accepted metric observation and outcome hash from
  the retained immutable Trial inputs/artifacts and pinned Runtime/verifier, or reports
  a typed historical-evidence-unavailable result;
- fixed, deterministic portfolio, direct LLM, and LLM-harness modes can be compared
  under identical experiment budgets;
- the confirmatory evaluation declares one problem-instance × orchestration-replicate
  unit, selects sample size from a development-only pilot and minimally meaningful
  effect, blocks/randomizes nuisance variation, and uses cluster-aware inference;
- all arms, baseline selection, endpoints, non-success/censoring rules, exclusions,
  reruns, grader revisions, multiplicity policy, and analysis code are frozen before
  locked-test access;
- no generation, candidate, Trial, scenario seed, provider retry, or repeated historical
  snapshot is counted as an independent optimization outcome;
- common-random-number pairing is used only after a frozen same/different-substream A/A
  audit supports it on the exact Runtime/host profile; unavailable binding evidence
  cannot be repaired by matching integers in the database;
- every scheduled evaluation run has an intention-to-run outcome, while infrastructure
  exclusions are symmetric, pre-declared, and published in a deviation ledger;
- first-attempt and repeated-attempt reliability are reported without retrospective
  best-replicate selection or cost-free `pass@k`;
- automated graders have deterministic goldens where possible, supplemental model
  graders are blinded and expert-calibrated, and representative traces are human
  reviewed;
- mock evidence is never presented as real SITL validation;
- the evaluation suite includes normal, edge, adversarial, and provider-failure
  cases;
- the SQL ledger remains complete when telemetry is absent, sampled, queued, dropped,
  or unavailable; bounded per-stage traces retain durable causal links after restart;
- production telemetry omits raw content, exceptions, stable IDs/hashes, paths, URLs,
  parameters, secrets, and sealed-test material by default, and metric dimensions pass
  finite-registry/cardinality tests;
- external export is disabled by default for the packaged desktop, uses an isolated
  approved route when enabled, and can fail without changing Harness state or budget;
- stop and pause recommendations cannot bypass the deterministic policy;
- cancellation and late-response race tests prove that no post-cancel dispatch can
  occur;
- old decisions either replay with their pinned implementation or report a typed
  historical-runtime failure;
- kill-switch and rollback drills complete without corrupting active trial evidence.

The Version 1 acceptance statement also names its residual platform boundary: these
controls are not evidence that NSIS/full-trust Tauri plus WSL2 can resist malware
already controlling the same Windows user, WSL root, the Tauri process, or the host
kernel. A claim covering that attacker requires the separate Windows package-
identity/AppContainer/broker architecture in Section 17.3.7.

## 27. Known limitations and deliberate non-goals

### 27.1 An LLM router may not beat a strong portfolio

The deterministic portfolio already uses measured reward, coverage, and exploration.
The LLM adds value only if semantic interpretation of failure patterns, tool
capabilities, or regime changes improves outcomes. If evaluation does not show that
value, `llm_harness` remains an educational/experimental mode rather than the
product default.

### 27.2 Rationale is not calibrated confidence

A fluent explanation is not evidence that the selected tool is correct. Outcome
metrics and repeated trials carry authority. The UI must not style rationale as a
safety approval.

### 27.3 Provider reproducibility is limited

Aliases, serving stacks, and nondeterminism can change. Pin snapshots where possible,
record full configuration, and preserve decision replay. Do not promise bitwise
model reruns.

### 27.4 Tool descriptions can overfit a model

Names and descriptions affect tool use. Evaluate changes across the supported model
set and preserve versioned tool manifests. A prompt improvement for one provider can
regress another.

### 27.5 More tools can reduce performance

The model should see only eligible tools for the current parameter space and budget.
Do not expose every diagnostic or optimizer merely because it exists.

### 27.6 Multi-agent design is not justified yet

A planner, critic, and verifier model may look sophisticated but adds cost,
coordination failure, and evaluation burden. Deterministic validators already fill
the verifier role. Add another model role only after a scoped eval demonstrates a
specific gap.

### 27.7 The Version 1 meta-tool is indirect routing

`submit_generation_plan` is a native provider function, but the optimizer choices
inside its arguments are domain-level tool references rather than separate native
function invocations. It provides atomic validation, portable provider behavior, and
durable recovery; it does not by itself demonstrate that the model can discover,
select, or sequence individually exposed optimizer functions. Any educational or
scientific claim must name the transport and report the Section 22.7 ablation.

If direct native optimizer functions consistently outperform the meta-tool without
breaking strict schemas, atomic planning, or budget safety, the product protocol
should evolve. If they do not, the meta-tool can remain the product transport while
the underlying optimizer adapters continue to be real, independently tested domain
tools.

### 27.8 The Version 1 desktop gateway trusts the authorized worker

Within an untampered Runtime, the split gateway blocks the WebView, simulator,
proposal tools, and wrong Linux service identities from using the provider key, and it
prevents accidental duplicate network calls through bound one-use tuples. It does not
make a compromised orchestration worker harmless, and it does not independently
authenticate a hostile same-Windows-user process that can enter the distribution as
root. Because the gateway intentionally lacks general database access, it also cannot
prove that an attempt is still reserved or that cancellation did not win immediately
before the request.

For the initial single-user desktop threat model, the worker is trusted code and the
database reservation/CAS path protects against crashes, races, and ordinary defects.
A hosted multi-tenant profile must not inherit that trust silently. It needs an
independent authorization signer or minimal read-only authorization service, separate
keys and identities, and tests showing that an authorized-but-malicious worker cannot
invent provider spend.

### 27.9 Signed releases do not defeat a local administrator

Manifests, signatures, attestations, read-only service mounts, and startup hashing
detect accidental corruption and many non-administrator substitutions. They do not
promise to defend a WSL2 Runtime from an administrator who can replace the desktop
binary, trust roots, verifier, kernel, service unit, process memory, or stored
activation state. The local single-user product threat model states that limit
plainly. Hosted deployments require host/image admission policy, protected workload
identity, immutable infrastructure controls, and an incident process outside the
desktop application itself.

### 27.10 Bounded queues do not create unlimited throughput

Fairness, admission, and load shedding keep the Runtime responsive and make overload
observable; they do not make one PX4/Gazebo host process Trials faster. The local
desktop starts with one real-SITL slot because its current port/instance isolation does
not justify more. Additional concurrency is enabled only after empirical capacity and
isolation tests. A long queue is shown as waiting debt, not marketed as parallel
execution.

### 27.11 Desktop bridge authentication is not a Windows sandbox

Removing the private loopback API and keeping launch keys out of JavaScript closes a
real browser/accidental-client/replay class. It does not turn the current full-trust
NSIS process and user-owned WSL distribution into mutually isolated security
principals. The same Windows account can launch the distribution as `root`; malware in
that account may also inspect/inject Tauri, replace the bridge/Runtime, or drive
authorized WebView commands.

The initial product is therefore a single-user local engineering application, not a
hostile-code execution boundary. AppContainer/package identity plus a separately
signed minimal broker is a future architecture and may conflict with required WSL,
updater, file, and simulator access. It must be prototyped and threat-modeled rather
than promised as an easy hardening flag. Code signing establishes publisher/integrity
at distribution time; it does not authenticate every runtime request or make same-user
malware harmless.

### 27.12 Verified simulator evidence is not hardware-flight evidence

Artifact hashes, a signed verifier, explicit SI units, a named frame, and deterministic
metric replay prove **which computation DroneDream performed on which retained
simulation bytes**. They do not prove that PX4/Gazebo, the airframe model, actuator
dynamics, sensor model, latency, wind, contact physics, or host timing faithfully match
the physical vehicle. A reproducible SITL result can still have model-form error.

Reports therefore label evidence as mock, replay, SITL, HITL, or physical flight and do
not collapse those levels into “verified flight.” Hardware deployment still needs an
independent safety review, bounded flight envelope, emergency control, staged
SITL/HITL/flight validation, and institution/site authorization. The Harness may help
select what to test; it does not certify airworthiness.

### 27.13 A metric contract is an engineering policy, not neutral truth

Time-weighted 3-D path RMSE, maximum error, completion, coverage, crash constraints, and
validation promotion encode choices about what matters. A different task may require
axis-specific error, phase-weighted loss, energy, settling time, attitude, control
effort, or safety margins. Signing one metric implementation makes the choice stable
and auditable; it does not make the measurand universally correct.

Metric/threshold changes are versioned experiment-contract changes and are developed on
training/validation evidence. They never reinterpret an existing observation in place
or follow a disappointing final-test result. Where the measurement model is uncertain,
DroneDream reports sensitivity across predeclared alternatives instead of choosing the
most favorable metric afterward.

### 27.14 A recorded seed does not make Gazebo deterministic

Gazebo, PX4, plugins, numerical libraries, process scheduling, logging, host load, and
external clients can introduce distinct nondeterminism. Even Gazebo's global
`--seed` does not by itself prove that every sensor/failure/site plugin uses the same
generator, nor that an asynchronously loaded component consumed it before producing
data. Lock/simulation-time synchronization prevents some clock drift but is not a
general bitwise-determinism guarantee.

DroneDream therefore does not promise identical trajectories from a repeated seed
unless the exact Runtime/profile passes the bitwise class. Most real SITL profiles are
expected to qualify at metric-tolerance or statistical repeatability, and hardware
trials are statistical. The current bundled real PX4/Gazebo path is `uncontrolled`
until it consumes and verifies component seeds; its deterministic dry-run behavior
cannot be used as evidence for the real path.

### 27.15 Parameter readback is necessary but not atomic application

Seeing requested values through MAVSDK proves only that the queried component returned
those values at that time. It does not prove that every controller module consumed one
simultaneous vector, that no intermediate coupled vector was active, that a stale build
was not launched, or that unqueried persisted parameters match the intended baseline.
A successful compensating rollback similarly does not erase any transient behavior
that already occurred.

Version 1 therefore uses fresh-process startup, isolated parameter storage, full
baseline/final snapshot hashing, application-state evidence, and a pre-arm gate. It
does not advertise a generic live flight-controller tuning transaction. Extending the
same design to hardware requires an independently reviewed operational-safety case,
physical interlocks, and operator authority outside this Harness.

### 27.16 An objective contract cannot manufacture statistical support

Making the metric algebra, estimand, risk measure, constraints, and selection key
immutable removes semantic drift; it does not make a small or biased scenario suite
represent the deployment population. A CVaR label with two effective tail
observations, a chance constraint with three replicates, or a weighted mean over
convenient cases may be perfectly reproducible and still too uncertain for the
engineering claim. Likewise, treating a fixed benchmark suite as a probability
distribution does not make its hand-authored weights empirically calibrated.

DroneDream therefore reports the scenario-population definition, effective
case/replicate/tail counts, uncertainty method, unsupported estimator state, and
sensitivity to predeclared alternatives. A tool becomes ineligible when the frozen
contract requires evidence it cannot consume, and a Candidate remains incomplete
when minimum evidence is absent. The Harness does not fill the gap with a penalty,
posterior point estimate, moving normalization range, LLM judgment, or a favorable
renormalization of surviving rows. Deployment claims still require a representative
design and enough independent evidence.

### 27.17 Online tool reward is not causal attribution

When a tool proposes the Candidate that later improves the incumbent, the ledger can
prove provenance, cost, and the frozen reward assigned by product policy. It cannot
prove that another eligible tool would not have proposed an equal or better Candidate
under the same unobserved history. Equal multi-source credit is intentionally
order-independent and auditable, but it is not a Shapley value or a causal effect.

Adaptive routing also changes its own future data distribution. Logged deterministic
LLM decisions usually provide no action support for counterfactual policies, while a
reward model trained on those selective logs can be biased. Version 1 therefore uses
online rewards only for bounded application allocation and diagnostics. Product/course
claims compare frozen routing policies end to end in independent blocked randomized
campaigns. Off-policy estimates are supplemental only after their logging
probabilities, support, delay, stationarity, reward, and uncertainty assumptions pass
the registered validator.

### 27.18 Rejected first-version architectures

| Alternative | Rejection reason |
| --- | --- |
| keep `gpt` as one optimizer beside numerical algorithms | does not let the model route among tools and preserves the current conceptual gap |
| let the model write raw gains and also choose algorithms in one response | mixes semantic routing with an avoidable high-dimensional numeric authority |
| expose a generic Python or shell tool | grants excessive functionality and makes safety, replay, and cost control substantially harder |
| let optimizer tools dispatch simulations immediately | creates partial side effects before a complete generation plan is validated |
| use free-form JSON with a repair parser | makes malformed or ambiguous output an application control path |
| rely only on provider/MCP tool annotations | annotations are descriptive hints, not a trusted authorization mechanism |
| send full logs and history on every generation | wastes context, increases injection/privacy exposure, and obscures the evidence actually used |
| introduce planner, critic, executor, and verifier agents immediately | duplicates deterministic authority and multiplies nondeterministic failure modes before a single-agent baseline exists |

## 28. Open design questions

These must be resolved with prototypes or evidence rather than preference:

1. Does one decision turn outperform a two-turn propose/select protocol?
2. Which evidence aggregates best predict the correct optimizer regime?
3. Should the model allocate candidate counts, fidelity-equivalent cost, or both?
4. What minimum observation count makes each tool eligible?
5. Should `direct_llm_proposal` remain available outside evaluation mode?
6. How should model currency cost trade against saved simulation time?
7. Which provider capability probes are reliable enough for custom endpoints?
8. What trace content retention is appropriate for local desktop versus hosted use?
9. What statistically meaningful real-SITL campaign fits the available compute?
10. At what measured fallback rate should product mode pause instead of continuing?
11. Which deterministic stopping predicates are valid across mixed optimizer tools,
    and which must remain tool-specific?
12. How much tool-description/order sensitivity is acceptable before a model/tool
    registry combination is rejected?
13. Does indirect meta-tool routing preserve the selection quality of individually
    exposed native optimizer functions across every supported provider and model?
14. Which custom provider origins justify production support after strict-schema,
    credential-boundary, DNS/IP, TLS, retention, and egress conformance costs are
    measured, rather than being restricted to evaluation/development profiles?
15. Which providers expose immutable snapshots or sufficiently stable observable
    fingerprints for confirmatory campaigns, and which must remain
    `alias_only_unpinned` product-only profiles?
16. Should DroneDream operate its own TUF repository for Runtime/tool releases or use
    an existing hosted implementation, and what offline/revocation window is acceptable
    for the approximately single-user desktop deployment versus future hosted use?
17. What measured queue and active-lane limits keep the packaged desktop on the safe
    side of its throughput/latency knee for mock and real SITL?
18. Does deficit round-robin over normalized configured costs meet product fairness and
    evaluation reproducibility, or is a simpler per-Job round-robin preferable at the
    expected small-user scale?
19. Is the persistent Tauri Rust -> stdio bridge -> Runtime UDS latency/recovery profile
    acceptable for every current JSON, artifact, CSV, and future event flow, or should
    the packaged desktop use a separately signed Windows broker earlier?
20. Does DroneDream's realistic approximately 50-user, single-user-desktop threat model
    require hostile-same-Windows-user isolation, and if so can an AppContainer UI plus
    minimal full-trust broker retain WSL2, updater, noVNC, filesystem, and simulator
    functionality without creating a broader broker?
21. Which hosted issuer, tenant-membership, role, and access-token profile will be
    supported first, and can all other JWT forms remain fail-closed until their
    negative authorization suites exist?
22. Should the first release preserve `dronedream_local_neu_v1` for compatibility, or
    introduce a separately versioned standard ENU experiment contract and an explicit
    X/Y migration before Harness evidence begins?
23. What minimum evaluation duration/sample count/track coverage and maximum telemetry
    gap are justified by measured PX4 logging behavior across supported Runtime/host
    profiles, rather than selected from one convenient trace?
24. Which proposal tools can consume typed domain constraints and right-censored
    completion observations natively, and which must be ineligible or exposed as a
    separately evaluated transformation adapter when such evidence exists?
25. At what frozen checkpoints may validation scenarios run, how many validation
    promotions are budgeted, and what final-test case/seed count gives a useful
    confirmatory decision without encouraging repeated reuse?
26. Which source ULog, canonical telemetry, rejected envelope, and verifier artifacts
    must be retained for evidence replay, and what privacy/storage policy applies when
    an individual user deletes a Job?
27. For each supported PX4/Gazebo Runtime, which physics, wind, sensor, failure,
    executor, and PX4-internal random sources can be bound and read back, and which
    remain `nondeterministic_uncontrolled`?
28. Should DroneDream move the production runner to Gazebo standalone mode so it can
    own the official `gz sim --seed` server command and startup ordering, or can the PX4
    `make px4_sitl gz_x500` path expose equally strong versioned seed binding without a
    fragile wrapper patch?
29. What same-substream/different-substream A/A tolerance and variance thresholds are
    justified for each host/Runtime profile, and when is common-random-number pairing
    statistically beneficial rather than misleading?
30. Which realized-effect artifacts—such as `wind_info`, dropout schedules, sensor
    traces, simulation-step timing, and applied failure acknowledgements—must be
    retained to prove treatment fidelity without making every Job artifact
    prohibitively large?
31. Which exact PX4 commits/build targets and airframes form the first supported
    parameter-bundle matrix, and can generated plus runtime component metadata be
    reconciled reliably for every one?
32. Which upstream `increment` values should become DroneDream experiment quanta, which
    need a finer/coarser reviewed grid, and what explicit origin preserves compatibility
    with existing 1.0.0 Jobs without treating their implicit `search_min` anchor as a
    universal rule?
33. What closed constraint-expression subset covers every selected controller coupling
    without becoming a second unsafe programming language, and which current advisory
    tuning-order notes can be promoted only after measurable prerequisites exist?
34. What is the smallest control-relevant full-parameter snapshot that detects
    cross-attempt contamination without depending on an unstable “all parameters”
    order or storing unrelated calibration/secrets?
35. Can an isolated copy-on-write SITL parameter/rootfs profile preserve acceptable
    throughput on target WSL2 machines, and what A/B/A evidence would justify any
    faster baseline-reset alternative?
36. Is each scenario suite a fixed finite benchmark population whose weights sum over
    named cases, or a sample from a broader deployment population requiring a sampling
    design and inference model; which interpretation applies to each product profile?
37. Which risk contract is the defensible default for stable, balanced, robust, and
    accuracy-first profiles—mean plus explicit chance constraints, a registered upper
    quantile/CVaR loss, or a vector/Pareto contract—and what development evidence
    justifies the choice?
38. What minimum effective case, replicate, and tail sample counts and which confidence
    or uncertainty construction are required before a quantile, CVaR, pass probability,
    or chance constraint may influence optimization or winner selection?
39. Which tools should consume a scalar preference versus an objective vector, how are
    scalarization weights or Pareto reference points fixed before evidence, and which
    deterministic rule selects one deployable Candidate from a non-dominated set?
40. Which verified domain non-successes belong in an explicit chance/outcome constraint
    and which belong in a bounded composite loss, if any; can every current crash,
    deadline, non-completion, and pass-rate use be mapped without double counting?
41. Which bounded feasibility-first Candidate reward and fixed engineering scale best
    predicts policy-level fixed-budget improvement without rewarding larger batches,
    noisier best-of-generation selection, or extra simulator/proposal cost?
42. How much deterministic randomized routing exposure can the approximately
    50-user/local product afford to log with valid action probabilities, and is its
    support/effective sample size sufficient for any useful IPS/DR analysis?
43. Which typed failures and rolling windows should open, probe, half-open, and close a
    proposal-tool circuit without confusing a hard problem instance with a broken tool
    implementation?
44. How should delayed Candidate completion and nonstationary optimizer state be
    represented in online allocation so slow tools are not unfairly starved and late
    rewards do not leak future evidence into historical decisions?
45. Is equal pre-outcome credit among exact cross-tool duplicate proposals sufficient
    for Version 1, or does development evidence justify a different order-independent
    attribution rule that remains replayable without claiming unavailable
    counterfactual causality?

## 29. Immediate next engineering artifacts

Before writing production logic, create:

1. `docs/adr/` decisions for orchestration split, authority boundary, exploration,
   compiled plans, multi-source provenance, Trial-outcome taxonomy, exact retry,
   NEU/units/time, metric registry, and search/validation/final-test isolation;
2. Pydantic models for `EvidenceSnapshot`, `OptimizerDatasetSnapshot`,
   `ToolDefinition`, `GenerationPlan`, `CompiledGenerationPlan`,
   `ToolEligibilityReport`, `StoppingPolicy`, `ValidationReport`,
   `TrialAttemptEvidenceEnvelopeV3`, and its verifier output;
3. JSON-schema golden files and cross-provider conformance tests;
4. a pure tool-adapter prototype around two contrasting algorithms, initially
   TuRBO and BIPOP-CMA-ES;
5. a replayable development corpus of 20–50 diagnostic decision cases, explicitly not
   treated as the confirmatory sample-size justification;
6. crash-injection tests for every durable state transition;
7. a threat-model test suite for injected strings, excess allocations, unknown
   evidence references, secret leakage, and sealed-test access;
8. a frozen evaluation package containing `eval_protocol.yaml`, case/arm manifests,
   block/randomization schedule, locked-test receipt, grader goldens, and executable
   analysis plan for deterministic portfolio versus LLM Harness;
9. a strict `harness-runtime-manifest.v1` schema, clean-checkout generator, signed
   fixture, startup verifier, SBOM/provenance policy, side-by-side slot prototype, and
   rollback/freeze/mix-and-match/revocation test repository;
10. a SQL-lane scheduler prototype with one real-SITL capacity slot, per-Job
    round-robin/deficit state, bounded admission, queue-deadline/backoff fixtures,
    Valkey-loss recovery, overload test driver, and SQLite/PostgreSQL contention tests.
11. a desktop caller-boundary prototype that removes private `/api/v1` loopback TCP,
    adds the fixed Tauri/stdio/UDS bridge, launch request/response proofs, typed command
    allowlist, `api_idempotency_records`, hostile-origin/replay/foreign-object tests,
    and a written WSL same-Windows-user residual-risk demonstration.
12. `trial_result.v3`, `telemetry.v2`, and metric-registry JSON schemas with canonical
    examples; a signed secretless extractor/verifier prototype; retained-ULog evidence
    replay; analytic geometry/time-integration goldens; and irregular/gapped/truncated
    telemetry fault injection.
13. a physical-attempt ledger migration and exact-retry prototype that proves
    infrastructure/evidence failures never become parameter penalties, genuine
    Candidate-dependent crashes remain typed constraints, one logical Trial accepts at
    most one fenced attempt, and stale outputs cannot overwrite it.
14. a sealed scenario-service prototype that migrates current holdouts to validation,
    atomically freezes one winner and all policy/evidence hashes, creates no final-test
    rows before that commit, materializes one Candidate only, and refuses search resume
    or next-best testing after the verdict.
15. a metric-contract calibration notebook/test package using representative PX4 ULogs
    to select duration/sample/gap/coverage thresholds on development data and compare
    legacy unweighted versus target time-weighted RMSE without changing old reports.
16. `random-domain-registry.v1`, `seed-derivation-manifest.v1`, and
    `seed-binding-evidence.v1` schemas; cross-language derivation goldens; a Gazebo
    standalone `--seed` launch/readback prototype; versioned wind/sensor/dropout
    capability probes; simulation-time/host-condition evidence; and same/different/
    disconnected-substream A/A fixtures that assign an honest repeatability class.
17. `parameter-contract-bundle.v1`, exact-domain and closed-constraint-graph schemas;
    a clean-build extractor that hashes PX4 binary/generated/runtime component metadata;
    retained old-bundle fixtures; Decimal/Rust/Python grid and float32-wire goldens; a
    per-attempt copy-on-write parameter-store prototype; full baseline/final snapshot
    verifier; disarmed/state/readback/rollback fault injection; and no-override /
    extreme-treatment / no-override A/B/A contamination tests.
18. `optimization-outcome-contract.v1`, `metric-dependency-graph.v1`,
    `candidate-outcome-evidence.v1`, and `portfolio-reward-contract.v1` schemas; a pure
    compiler with balanced/unbalanced nested-estimand, missing/excluded/censored cell,
    quantile/CVaR/chance-constraint, fixed-transform/scalarization/Pareto-reference,
    feasibility-precedence, threshold/tie, and cross-adapter goldens; and regression
    fixtures proving legacy raw metrics, moving min/max ranges, million penalties,
    hidden failure thresholds, rounding, and scalar-vector double counting cannot enter
    a Harness result.
19. `routing-opportunity.v1`, `portfolio-reward-contract.v1`,
    `routing-reward-event.v1`, tool-availability/circuit, exploration/maximum-share,
    and action-probability schemas; an order-permuted multi-source attribution corpus;
    delayed/restarted reward and complete-cost reconciliation; unavailable-tool
    cold-start tests; and an OPE validator that rejects deterministic/unknown
    propensity, missing support, low effective sample size, inconsistent rewards, and
    post-action context.

Implementation should start only after these artifacts make the proposed control
plane testable without PX4/Gazebo. Real simulator validation then tests optimization
value rather than basic orchestration correctness.

## 30. Design review ledger

This document has been reviewed against both the current repository and external
primary/official sources. Material corrections made during review are preserved here
so later edits do not reintroduce them:

| Review pass | Fault found | Design correction |
| --- | --- | --- |
| current architecture | GPT was a sibling one-candidate optimizer, not a tool router | split orchestration mode from fixed algorithm |
| tool protocol | “one model turn” conflicted with observing tool results | declarative one-turn Version 1; interactive two-turn Version 2 remains deferred |
| execution authority | raw model plan was too close to tool execution | add validated, persisted `CompiledGenerationPlan` as the only executable contract |
| fidelity audit | an example assigned 0.65 fidelity to BIPOP-CMA-ES | use registry-enumerated fidelity modes; current non-multi-fidelity tools resolve to full fidelity |
| adapter audit | “wrap six functions” ignored CMA cohort metadata and portfolio-only fallback/deduplication | add full internal dataset snapshot, relational state provenance, typed partial results, and explicit batch policy |
| cancellation audit | “durable” did not define cancel/dispatch or late-provider races | define cancellation precedence, row-lock linearization, superseded responses, and process-exit recovery |
| stop/pause audit | model recommendations had no authoritative resolution | add versioned deterministic stopping/pause policies and winner freeze boundary |
| retry audit | a schema-repair call contradicted a one-turn protocol | no model repair in Version 1; exact transport retries are separately metered physical attempts |
| privacy audit | identifiers, raw traces, and retention lacked a complete provider inventory | minimize provider view, separate private/model projections, default raw content off, and add deletion/TTL rules |
| attribution audit | one-source provenance let tool order bias credit | preserve multi-source duplicate provenance with deterministic primary source and versioned credit |
| feedback audit | unconstrained model allocation could starve tools and create self-confirming evidence | separate policy-reserved exploration from model-discretionary capacity |
| implementation naming | `saasbo` could be mistaken for a fully Bayesian implementation | report the current backend honestly as a SAAS-inspired sparse-axis GP ensemble approximation |
| database audit | “one unresolved/accepted/primary row” was described as a generic uniqueness constraint, and “cascade deletion” exceeded the current schema | specify partial unique indexes, distinguish at-most-one from exactly-one, add transactional reconciliation, document current ORM deletion, and define a backup-gated Alembic rollout for both databases |
| API/event audit | the draft called capped embedded `job_events` a stream and did not reconcile the new contract with strict legacy request/status unions | preserve legacy mappings and bounded fields, add a versioned orchestration object and user-scoped pagination, define monotonic event cursors, and keep pause out of the existing top-level status union |
| runner audit | current finalization combines aggregation, external proposal work, and report completion under a Job timestamp lease | split aggregation intent, Decision advancement, and report finalization; give Decisions their own leases and explicitly fence paused/unresolved Jobs |
| transport-claim audit | one native `submit_generation_plan` function could be mistaken for direct native invocation of each optimizer | classify Version 1 as indirect meta-tool routing, prohibit stronger product/course claims, and require a matched native-function versus meta-tool versus structured-output ablation |
| resource-containment audit | “bounded worker pool” did not identify that current optimizers execute synchronously in the main worker or define enforceable Windows/WSL2/Linux boundaries | introduce a secretless local proposal executor, fresh child per call, explicit systemd/cgroup or container limits, BLAS-thread enforcement, process-tree termination, framed IPC, and degraded-platform blocking |
| credential-lifecycle audit | the UI currently stores a raw key in `sessionStorage`, sends it in Job requests, and the backend persists encrypted per-job copies; the proposed opaque handle could itself become a persisted bearer secret | add a Tauri-to-WSL session registration path and dedicated provider gateway, persist only non-secret bound references, revoke on exit/heartbeat/TTL, isolate provider egress, and retain `job_secrets` only for legacy jobs |
| provider-egress audit | the current URL syntax/exact-string allowlist was described too broadly as SSRF protection, while the official SDK follows redirects and the custom adapter can retry without `response_format` | classify current behavior as a legacy gap; introduce immutable provider profiles, checked-and-pinned DNS/IP, redirects and ambient proxies off, verified TLS, bounded responses, network egress confinement, and fail-closed strict-schema capability probes |
| physical-request accounting audit | the current proposer passes retry count into the SDK, so one observed `generate()` call can hide multiple requests; “metered attempt” also overstated whether a timed-out request was billed | disable nested retries, persist one row per physical request, distinguish pre-send from ambiguous post-send failure, retain unknown cost upper bounds, and authorize retries only under idempotency and worst-case budget |
| prompt-boundary audit | the current generic JSON copier forwards arbitrary scenario/profile/metric text, candidate IDs, prior model labels, and normally holdout definitions/seeds even though it filters holdout outcomes | replace recursive sanitization with a closed provenance-aware evidence DTO, exclude all untrusted/model/error text and holdout sources, allow later influence only through recomputed numeric evidence, and gate releases on byte-canary plus repeated hijack evals |
| evaluation-power/leakage audit | the initial 20–50-case guidance could be mistaken for confirmatory power, and generations/Trials/seeds/retries could be pseudoreplicated; “best algorithm,” endpoint, grader, or policy selection could also inspect the test bank | reserve 20–50 cases for development diagnostics, define the problem-replicate experimental unit, use development-only pilot power/precision, blocked randomized scheduling and cluster inference, freeze non-success rules/baselines/graders/analysis before locked-test access, and report intention-to-run plus calibrated grader evidence |
| observability-boundary audit | the draft implied a single workflow trace and listed Job/decision IDs beside “low-cardinality” attributes, while the current repository has no OpenTelemetry pipeline and long Jobs cross queues, restarts, and security boundaries | state the implementation gap; make the SQL ledger canonical; create bounded stage traces with durable links; prohibit runtime values in names and IDs/content in metrics; export only finite typed attributes and rotating HMAC support references; disable content/Baggage/external export by default; make exporter loss control-neutral |
| model-drift/reproducibility audit | recording only a model alias/snapshot “when available” did not define how a long Job detects alias migration, probe expiry, fingerprint change, or snapshot retirement, and could overstate a fresh model rerun as reproducible | persist an immutable model binding, request snapshots directly when offered, compare returned identity/fingerprint on every attempt, prohibit cross-model retries, add generation-boundary pause/fallback/fail transitions, label alias-only runs honestly, and reserve exact replay claims for recorded decisions |
| executor-IPC audit | “authenticated Unix socket” did not identify the peer credential, socket ownership, replay key, framed-message rules, resource-limit authority, result binding, or safe snapshot transfer, so a local process/path race could spoof work or consume resources | require a pathname socket with service ACLs and kernel peer credentials, distinct UIDs/cgroups, one-request canonical frames, nonce/attempt/input/result hashes, hard broker ceilings, sealed descriptors or no-link beneath-root resolution, and durable parent CAS |
| provider-gateway authorization audit | a non-secret “credential reference” and “authenticated worker” did not define registration versus call identities, replay behavior, or whether the database-free gateway could truly know reservation/cancellation state | split registration and call sockets, add Tauri-held launch MAC and kernel peer checks, exchange session references into Job-bound IDs, consume request-bound attempt tuples once, keep keys and egress isolated, and explicitly leave database-state truth with worker transactions unless an independent hosted grant service is added |
| Harness supply-chain audit | release signatures and source-commit fields did not prove which registry, prompt, compiler, policy, adapter, gateway, executor, dependency, and tool bytes each Job actually executed; a mutable updater could also replace code beneath an active Job or replay old metadata | add a CI-produced signed closed-file Harness runtime manifest, independent build/SBOM provenance, startup integrity and cross-process digest agreement, content-addressed side-by-side slots, Job pinning, historical retention, and TUF-grade rollback/freeze/mix-and-match/revocation handling before unattended Runtime updates |
| queue/backpressure audit | the current DB-polling worker starts up to ten Jobs, can materialize their Trials, then runs one globally oldest Trial and finalizes in the same loop; Valkey is only presence, so adding provider/tool work would create queue debt, starvation, and head-of-line blocking | retain SQL as the only durable queue; split bounded work lanes; add load-tested admission, fair per-user/Job scheduling, queue deadlines, transient capacity leases, one real-SITL slot until allocator proof, delayed retry without held leases, typed terminal work, fixed lock order, and overload/drain/Valkey-loss tests |
| desktop API/auth audit | the packaged Runtime sets `AUTH_MODE=disabled`; direct WebView fetches reach a loopback API where every caller becomes the same default user, while CORS/CSP were being mistaken for caller authentication | remove private desktop `/api/v1` from loopback TCP; add a typed Tauri Rust/stdio/UDS bridge, launch-bound request proof, durable mutation idempotency, state/owner/action authorization, hosted token profiles, and explicit negative tests |
| Windows/WSL trust-boundary audit | the earlier gateway/bridge wording implied Linux UIDs, socket ACLs, and a Tauri-held launch MAC could distinguish every local process, but the same Windows account can launch the distribution as `root` and can potentially control Tauri | narrow the V1 claim to web-origin/accidental-client/replay/wrong-Runtime-service protection; group hostile same-user/WSL-root/Tauri/host compromise as residual risk; require package identity/AppContainer plus a separately signed broker before claiming that stronger isolation |
| Trial-evidence integrity audit | current v1 results can omit execution identity; missing metrics/flags gain favorable defaults; the runner authors metrics/pass; telemetry lacks mandatory unit/frame/time/extractor binding; sample-count RMSE is sampling-density sensitive; infrastructure failures penalize parameters; retries lack immutable attempt lineage/artifact digests; and per-Candidate “holdout” use leaks it into selection | require v3 attempt envelopes, content-addressed source artifacts, an immutable physical-attempt ledger, explicit NEU/SI/monotonic-time/coverage contracts, a signed secretless time-weighted metric verifier, closed outcome taxonomy, exact logical-Trial retry with infrastructure exclusion, registered metrics without defaults/clamping, and disjoint search/validation/sealed-final-test materialization |
| optimizer-observation audit | the current frozen `OptimizerObservation` separates optional objective loss from feasibility, and compiler 1.9 now computes a closed Trial taxonomy plus an optimizer-learning rate that excludes infrastructure, cancellation, and invalid evidence while treating unknowns conservatively; the adapter still compresses domain/unknown outcomes into one rate, and `completed`, optional `loss`, pending reservations, and all six numerical cores lack explicit tagged/right-censored learning | carry the verified taxonomy into signed per-tool adapters as objective/constraint/right-censored tags plus separate pending reservations; declare accepted tags and state-update behavior per adapter; initially mark right-censoring unsupported rather than fabricating a finite loss |
| objective/estimand/selection audit | Outcome Contract compiler 2.0 and Selection Key 1.0 now remove the hidden failure threshold, hard-penalty shortcut, multi-bound observation overwrite, simultaneous objective-vector/scalar-loss acquisition, flat seed estimator, surviving-row case-weight drift, rounded acceptance decisions, implicit adapter raw metrics, known reliability/composite overlap, observed-range Bayesian scaling, production random scalarization, whole-case omission during reduced-fidelity screening, infrastructure-to-parameter failure conflation, and same-batch exact-action source erasure; a content-addressed search projection binds candidate parameters, Trial evidence, outcome taxonomy, holdout state, objectives, constraints, selection, and acceptance, and critical readers fail closed on mutation; it remains embedded in mutable aggregate JSON rather than an append-only evidence ledger, while the registry still lacks a complete component DAG and fixed Pareto references | retain the registered-metric contract, dependency guards, hierarchical estimator, closed failure taxonomy, case-stratified fidelity, versioned promotion projection, one-representation rule, fixed Job weights/scales, verified search projection, exact-action source shares, and shared lexicographic key; complete right-censoring/risk algebra, the metric DAG, Pareto references, relational immutable `CandidateOutcomeEvidenceV1`, and one shared projection for portfolio reward, validation promotion, winner freeze, report, and replay |
| portfolio credit and policy-evaluation audit | same-batch exact action collisions now preserve unique child sources with shares summing to one; same-tool duplicates collapse, fidelity supersession removes displaced reward, emergency fallback stays ineligible, and statistics consume fractional credit; historical collisions are still dropped before an append-only action record exists, while moving baselines, hand coefficients, candidate-count exploration, incomplete cost/delay attribution, and metadata-backed eligibility remain a deterministic heuristic rather than a validated UCB/OPE policy | label the current algorithm as a deterministic heuristic baseline; add immutable routing opportunities/actions, closed availability/circuits, deterministic reserved exploration and maximum share, historical/cross-batch source reconciliation, signed bounded reward/cost/delay contract, append-only reward events, action-probability provenance, OPE fail-closed gates, and end-to-end blocked randomized routing-policy evaluation |
| seed-effect and repeatability audit | the Trial seed reaches the outer runner and controls synthetic dry-run noise, but the bundled real launcher never consumes `PX4_TRIAL_SEED`, never owns Gazebo's official `--seed` startup, and emits no seed binding; only static obstacles are physically supported while wind/noise/dropout/battery/payload requests fail closed; requested speed is not achieved-speed evidence | separate orchestration/tool/scenario/physics/plugin domains; derive named substreams; require component/version/configuration-bound delivery/readback and realized-effect artifacts; classify repeatability honestly; record simulation/wall/host nuisance factors; allow common-random pairing only for identical accepted binding manifests; add same/different/disconnected-substream A/A gates |
| PX4 parameter-contract audit | legacy/version aliases collapse into current `r2`; one mostly shared hand catalog and moving documentation links do not bind exact firmware bytes; Git HEAD does not prove the launched binary; concrete validation can omit a dependency; binary-float projection re-anchors the grid at `search_min`; upstream increment, transport legality, and safety envelope are conflated; `disarmed` is not enforced; sequential live writes are not atomic; shared SITL storage isolation is unproved | add content-addressed firmware-build bundles and component-metadata reconciliation; separate transport/experiment/envelope domains; use exact grid indices and float32 wire identity; require a closed complete-vector constraint graph; prefer per-attempt clean-start storage and full baseline/final snapshots; independently verify state/readback/application evidence; disable live writes in Version 1 |

### 30.1 Implemented compatibility slice on 2026-07-24

The repository now contains an intentionally narrow first execution slice. It proves
the product interaction without claiming that the complete hardened architecture above
already exists:

- `optimizer_strategy="llm_harness"` is accepted by the API and five-step wizard;
- after baseline evidence is aggregated, one model turn receives a compact read-only
  evidence packet and may select exactly one identifier from the closed eight-tool
  registry;
- the model receives no callable object, database session, simulator handle, shell,
  filesystem path, or credential;
- local code validates the exact response shape and tool identifier, then separately
  routes the accepted identifier into the existing CMA-ES or accuracy-first optimizer
  implementation without changing the persisted Job mode;
- provider failure, missing/expired credential, missing model, oversized prompt,
  insufficient evidence, or invalid output is recorded as a rejected decision and
  explicitly falls back to `optimizer_portfolio`;
- `harness_decision_started`, `harness_decision_accepted`,
  `harness_decision_rejected`, `harness_decision_fallback`, and
  `harness_tool_execution_result` events preserve the decision source, selected tool,
  status, and SHA-256 evidence/prompt bindings;
- the frontend requires the same in-memory model access configuration for both legacy
  direct GPT proposals and the new Harness mode; credentials remain absent from draft
  storage and are required again for a rerun;
- Settings can retain up to twelve provider/model/base-URL profiles and the
  conversation composer can select between them; only non-secret profile metadata is
  written to local storage, while every profile's API key remains process-memory-only;
- every conversational turn projects the currently selected PX4 parameter IDs,
  baselines, search ranges, and scales back to the provider under a validated 64-item
  bound; parameter patches carry the same explicit/derived/proposed-default provenance
  as ordinary fields, and a lower-authority follow-up cannot replace an explicit
  parameter choice;
- moving from conversation into the five-step builder preserves conversation state,
  while later manual field or parameter edits become explicit user provenance before
  the draft is saved; the provider is instructed to maintain a cumulative summary so
  multi-turn corrections do not depend on hidden chat history;
- the default application route is the shared-draft conversation authoring page, while
  manual five-step creation remains available as an equal path;
- the current voice convenience path calls no microphone API before a first explicit
  click, names the possible WebView2/Microsoft remote transcription before a second
  confirmation, stops its permission probe immediately, caps recognition at sixty
  seconds, aborts on unmount, and leaves the transcript editable before send; it is
  capability-detected and typing remains the fallback, so it is not yet the separate
  production transcription profile defined above; and
- an assistant-route `404` from an older Runtime is translated only after an explicit
  send into an actionable Runtime-update message; opening the workspace or conversation
  page still performs no automatic environment check.

This slice deliberately uses the existing `optimizer_strategy` column as a compatibility
transport. It does **not** yet implement the target `orchestration_mode`,
`fixed_algorithm`, policy/version tables, immutable decision ledger, model-binding
probe, signed runtime manifest, secretless executor, provider gateway, or evidence-v3
contract. The implemented model turn is indirect meta-tool routing, not unrestricted
agent autonomy and not native provider execution of the optimizer functions.

Current-code validation on 2026-07-24:

```text
backend/.venv/Scripts/python.exe -m pytest \
  backend/tests/test_bayesian_optimizers.py \
  backend/tests/test_cma_optimizers.py \
  backend/tests/test_optimizer_strategy_contracts.py -q

97 passed in 19.75s

backend/.venv/Scripts/python.exe -m pytest \
  backend/tests/test_scenario_effects.py \
  backend/tests/test_px4_gazebo_runner.py \
  backend/tests/test_local_px4_launch_wrapper.py \
  backend/tests/test_px4_offboard_track_executor.py -q

131 passed in 46.05s

backend/.venv/Scripts/python.exe -m pytest \
  backend/tests/test_parameter_catalog.py \
  backend/tests/test_px4_parameters.py \
  backend/tests/test_optimization_core.py \
  backend/tests/test_optimizer.py -q

91 passed in 7.07s

backend/.venv/Scripts/python.exe -m pytest -q

748 passed in 197.91s

backend/.venv/Scripts/python.exe -m mypy app

Success: no issues found in 72 source files

frontend: npm test -- --run

38 test files passed; 266 tests passed

backend/.venv/Scripts/python.exe -m unittest discover -s runtime/tests -v

42 tests passed; 4 POSIX-only deletion tests skipped on Windows
```

These test results support the documented facts about the existing optimizers,
scenario-effect contract, runner, bundled launcher, offboard executor, parameter
catalog/validation, parameter transport, and current optimization domain. They do not
validate the proposed seed-binding/repeatability, firmware-bound parameter bundle,
exact lattice/constraint graph, clean-start application protocol,
`OptimizationOutcomeContractV1`, `CandidateOutcomeEvidenceV1`, or the full hardened
`llm_harness` target.
In particular, passing the current optimizer tests confirms current behavior; it does
not validate hierarchical estimands, fixed objective semantics, cross-adapter rank
consistency, or unified acceptance/selection. Those schemas, tables, gateway,
compilers, verifiers, and evaluation campaign remain unimplemented.

### 30.2 Evidence-v2 context and routing diagnostics on 2026-07-26

The compatibility Harness now uses a closed, versioned
`HarnessEvidenceSnapshot` instead of constructing an untyped prompt dictionary in
the decision module. This is an incremental implementation step toward the target
control plane, not a claim that the immutable evidence-v3 or decision-ledger design
is complete.

The implemented evidence-v2 compiler:

- exposes remaining generations and Trials, per-Candidate Trial cost, parameter
  dimension, objective/constraint counts, and trusted catalog parameter names;
- derives `full_trials_per_candidate` and `remaining_full_candidate_capacity`
  through the same validated `ScenarioSuiteConfig` plus `scenario_matrix()` path
  used by the dispatcher, including enabled training and holdout seed rows;
- summarizes training and validation scenario/replicate counts without sending
  scenario IDs, seeds, arbitrary case configuration, or sealed-test material;
- computes completed/incomplete/feasible Candidate counts, measured failure rate,
  baseline-relative improvement, per-generation best score, and trailing stagnation;
- exposes only trusted training-side completion/failure/pass rates, scalar loss,
  invalid/cancelled Trial counts, feasibility observation coverage, completed
  Candidate rate, and best-to-runner-up score gaps;
- never exposes holdout status, feasibility, objective/constraint values, error
  text, or validation metrics to the adaptive router, preserving the validation
  firewall across generations;
- computes stagnation over the full history but bounds the provider-visible trend to
  the first generation plus the latest 31 generations, keeping context size constant
  for long-running Jobs;
- preserves bounded optimizer memory through per-tool Candidate, feasibility,
  failure, best-score, and last-generation statistics derived from trusted metadata;
- reads at most eight recent `harness_tool_execution_result` rows through a bounded
  SQL query and exposes only registered tool IDs, closed execution/fallback enums,
  generation numbers, and dispatched counts, so the next decision can react to
  zero-dispatch, exhausted-search, budget, and deterministic-fallback outcomes;
- selects at most twelve provider-visible Candidates while reserving representation
  for the baseline, strongest historical evidence, and the latest generations;
- rejects mappings, strings, labels, free-form diagnostics, proposal rationale,
  errors, Candidate IDs, parameter values, arbitrary JSON, and mixed numeric/text
  metric arrays at the prompt boundary;
- uses `evidence_schema_version=2.3` and `tool_registry_version=2.0` in capability
  discovery and decision/tool-execution events; and
- presents a richer static tool manifest with explicit search roles, applicability
  signals, and declared constraint, multi-objective, and multi-fidelity support.

The Harness dispatcher now performs a deterministic feasibility preflight before
contacting a provider. If the next generation exceeds `max_iterations`, or the
remaining Trial budget cannot materialize one complete Candidate under the configured
scenario matrix, it records `harness_decision_skipped` and returns the terminal
dispatch status without spending a model request.

`build_decision_messages()` is now a pure production function shared by live routing
and offline evaluation. The repository includes a 24-case, eight-category
development corpus covering cold start, local progress, stagnation, constraint
pressure, high dimension, tight budget, failure recovery, and mixed tool history.
`backend/scripts/evaluate_harness_router.py` validates that corpus, can emit the exact
secretless production messages, and grades a complete case-to-tool prediction file.
It also reports every constant-tool baseline and the uniform-random expectation,
then measures supplied predictions against both without using case categories or
grader rationale. In corpus v1 the random expectation is 23.4375%, while the best
constant policy (`optimizer_portfolio`) reaches 58.3333% (14/24); therefore raw
accuracy alone is not sufficient evidence that a router uses the supplied signals.
Evaluation Report 1.1 adds a deterministic development qualification gate: at
least 75% overall, at least 15 percentage points above the best constant policy,
and at least two of three cases passed in every category. These thresholds only
decide whether a router is worth advancing to the frozen simulator campaign.
Prediction Artifact 1.0 replaces the unaudited bare case-to-tool JSON map. A
gradeable artifact must bind the canonical corpus SHA-256, the exact production
prompt-suite SHA-256, Evidence/Tool/Prompt versions, provider, model snapshot,
sampling configuration, every selected tool, and its bounded rationale. The
loader rejects stale versions, mismatched hashes, missing/extra cases, or an
unstructured prediction file before grading.
Tests prove that case IDs, acceptable answers, grader rationale, scenario IDs,
scenario configuration, seeds, and injected text do not enter those messages.
Byte-invariance tests additionally prove that changing only untrusted display names,
Candidate labels/reasons/parameter values, scenario IDs/seed values/configuration,
event rationale/errors, or rejected metrics leaves the exact production messages
unchanged, while changing a trusted measured score changes the messages. A synthetic
1,001-Candidate history test keeps twelve Candidate rows, 32 trend rows, and a
production user message below the minimum configured 32 KiB prompt limit.
The execution-memory query deliberately avoids loading the mutable SQLAlchemy
`job.events` relationship, preventing a same-transaction relationship cache from
hiding decision events written later in the turn.

For provider calls, `harness_decision_started` now persists the complete bounded,
provider-safe Evidence 2.3 snapshot and static Tool Manifest 2.0 alongside their
SHA-256 values, the production prompt SHA-256, Prompt Template 1.0, and Decision
Trace 1.0 versions. `verify_harness_decision_trace()` validates the closed evidence
schema, rebuilds the exact production messages from the persisted snapshot and
manifest, and checks all three hashes. Tests demonstrate that a one-field evidence
mutation invalidates both the evidence and prompt hashes. This supplies
same-version reproducibility and accidental-corruption detection; it is not a
signature, append-only log, or proof against an actor who can rewrite the mutable
event row and every hash.
The read-only `scripts.verify_harness_decision_traces` command applies that
reconstruction to exported raw payloads, JSON arrays, or JSONL event envelopes
without database or provider access. It ignores unrelated event types in a full
export, emits bounded identifiers/failure codes/hashes instead of replaying the
evidence packet into CI logs, and exits nonzero for a missing, invalid, corrupted,
or current-version-incompatible trace.

This corpus is deliberately a development diagnostic, not the confirmatory
simulator campaign in Section 22. It detects prompt/tool discrimination regressions
and enables matched model comparisons, but it does not prove that an LLM router beats
the deterministic portfolio. Provider/model evaluation, blocked simulator campaigns,
the locked test bank, immutable decision/model/tool ledgers, and evidence-v3 remain
required before that stronger claim.

The older direct `gpt` parameter proposer now uses Prompt Schema 2.0 as well. Its
feedback path already excluded holdout Trial rows; it now also compiles the scenario
suite so that only training scenario enums, counts, weights, and allowlisted numeric
Runtime inputs are visible. Holdout cases expose counts only—not types, IDs, seeds,
weights, configuration, outcomes, or metrics. Vehicle identity is reduced to
catalog-backed categories, objective/constraint names are restricted to supported
Trial metrics or stable `custom_*` aliases, and Candidate IDs/labels, arbitrary
aggregate mappings, unrecognized scenario keys, and unknown failure-code strings
are excluded. Capabilities report `prompt_schema_version=2.0` for this path.

This hardening does not make the direct proposer equivalent to `llm_harness`: it
still proposes numeric parameters and therefore retains more model authority. The
closed-tool Harness plus deterministic optimizer adapters remains the preferred
architecture for continued moat development.

Outcome Contract V1 is now implemented as the first executable slice of Section
8.10. Job creation and rerun compile a content-addressed
`dronedream.optimization-outcome/v1` artifact that binds objective, constraint,
scenario/seed/weight, failure, acceptance, holdout, metric-registry, and selection
semantics. It is persisted in the Job event stream, advanced Candidate aggregates
carry its ID, and the reproducibility manifest carries the full contract.
The narrow legacy adapter labels `legacy_scenario_aliases_v1` and hashes the
original persisted suite before mapping recognized historical aliases, so report
export compatibility cannot silently rewrite old experimental intent.
Before Candidate ranking, final aggregation recompiles the contract and refuses
to proceed when its ID differs from the recorded creation event, turning
post-dispatch configuration drift into an explicit terminal failure.
Selection Key 1.0 replaces the `1_000_000 + 1_000 × violation` ranking shortcut
with a shared lexicographic order: evidence completeness, hard feasibility, hard
violation, training failure rate, objective-plus-soft-constraint loss, and a
stable tiebreak. `scalar_loss` excludes hard-constraint penalties, preventing the
experimental feasibility model from counting the same hard failure twice; CMA
centering consumes the same selection key. The previously repeated
`failure_rate < 0.5` learning rule is now one versioned constant recorded in the
failure policy, and constraint observations use their full
metric/operator/threshold ID so lower and upper bounds cannot overwrite each
other. Outcome Contract compiler 1.1 additionally forbids objective
double-counting: each numerical call selects one auditable representation,
records it in proposal metadata, and never blends raw objective-vector EI with
the scalar loss derived from the same evidence. Bayesian multi-objective tools
use the vector only when a complete joint incumbent exists, otherwise they
fall back to scalar loss; TuRBO and CMA-family state remain scalar-loss-only.
The compatibility score remains for
existing API/report consumers but is no longer the authority for hard feasibility.

Outcome Contract compiler 1.2 replaces the flat completed-seed estimator with
`within_case_estimator_then_fixed_suite`. Mean mode uses a within-case mean and
fixed case-weighted mean; worst mode uses within-case and across-case worst;
CVaR and percentile act within each case before a fixed case-weighted mean.
Each dispatched case therefore retains its full configured population weight,
while the case-weighted failure rate remains a separate reliability term. A
dispatched case with no usable metric cannot produce a scalar objective,
preventing surviving cases from silently absorbing its weight. Constraint
observations remain worst-usable-seed values, so a dangerous replicate cannot
be hidden by the case aggregate.

Outcome Contract compiler 1.3 adds
`dronedream.acceptance-projection/v1`. Promotion thresholds consume unrounded
hierarchical mean RMSE, unrounded worst-usable-seed maximum error, and
case-weighted pass/completion rates whose denominators include every dispatched
seed. Rounded `rmse` and `max_error_worst` fields remain display/report
compatibility values but no longer decide threshold boundaries.

Outcome Contract compiler 1.4 changes metric admission to
`registered_metrics_only`. Adapter `raw_metric_json` remains visible as report
evidence, but a numeric key cannot become an objective or constraint until its
source, unit, value kind, and semantics are added to the reviewed registry.
Job creation compiles this contract before persisting a Job or encrypted
provider secret and returns `INVALID_OUTCOME_CONTRACT` for an unknown metric.

Outcome Contract compiler 1.5 adds
`reject_known_alias_complement_and_composite_overlap`. The adapter-defined
composite `score` is exclusive until its component DAG is registered, and the
reliability aliases/complements `completion_rate`, `failure_rate`, and
`failed_trial_rate` cannot be combined as independent objectives or redundant
constraints. The dependency policy is included in the metric-registry hash.

Outcome Contract compiler 1.6 binds each Job's objective weights and
normalization scales to the Bayesian optimizer request. Production constrained
MOBO, multi-fidelity MOBO, and SAAS acquisition use that single fixed
preference vector and fixed scales; they no longer infer preference scaling
from observed ranges or draw new scalarization weights. The request rejects
mismatched weight/scale metric sets, and a partial observed vector cannot
silently remove an objective: it falls back to declared scalar loss or
exploration. Proposal metadata exposes the selected policy and exact inputs.

Outcome Contract compiler 1.7 adds the first executable
`dronedream.candidate-outcome-evidence/v1` slice. Aggregation canonically binds
the search-role objective/constraint values, Selection Key, acceptance
projection, candidate parameter hash, exact training-Trial evidence hash, and
holdout projection hash into one content-addressed payload. Ranking,
publishability, iterative acceptance, and numerical optimizer observations
prefer this projection and fail closed when its schema/hash or bound holdout
does not verify. Legacy aggregates without the field remain readable. This is
explicitly a migration-safe embedded compatibility layer, not yet the target
append-only relational evidence table or the final unified portfolio/report
projection.

Outcome Contract compiler 1.8 seals reduced-fidelity case coverage. Screening
first selects one deterministic replicate from every configured training case
and only then adds further replicates round-robin. Its optimizer-facing
effective fidelity is recomputed from the actual selected training matrix, so
nominal 0.25 coverage may honestly become a larger fraction when four or more
scenario cases must all remain represented. Holdout runs are never pulled into
reduced screening and still require a full-verification request.

Outcome Contract compiler 1.9 introduces
`dronedream.trial-outcome-taxonomy/v1`. Domain failures (`TIMEOUT`,
`SIMULATION_FAILED`, and `UNSTABLE_CANDIDATE`) plus unknown failure codes enter
optimizer learning, with unknowns deliberately conservative. Adapter/process,
artifact, and result-persistence failures are classified as infrastructure;
cancellation and invalid Candidate evidence are separate. Those nonphysical
outcomes are excluded only from the parameter-safety learning rate. They still
remain in dispatched denominators, block evidence completeness and public
promotion, preserve cost, and are bound into Candidate outcome evidence.

Outcome Contract compiler 2.0 introduces
`dronedream.portfolio-sources/v1`. Exact same-batch actions retain every unique
child optimizer that independently proposed the parameter/fidelity identity,
with equal reward shares summing to one; repeated proposals from one child
collapse to one source. Lower-fidelity or superseded sources remain auditable
but receive no reward, as do emergency fallback points. Portfolio statistics
consume those fractional shares. The current implementation remains an
explicit deterministic heuristic: it does not yet persist rejected historical
collisions, complete incurred cost/delay, randomized action propensities, or
an append-only routing/reward ledger.

Current focused validation:

```text
cd backend
.venv/Scripts/python.exe -m pytest -q

809 passed

.venv/Scripts/python.exe scripts/evaluate_harness_router.py

24 cases; 8 categories; 8 registered tools
uniform-random expectation: 5.625/24 (23.4375%)
best constant tool: optimizer_portfolio, 14/24 (58.3333%)
current provider-call traces: Evidence 2.3, Tool Manifest 2.0,
Prompt Template 1.0, Decision Trace 1.0
strict offline predictions: Prediction Artifact 1.0 bound to the printed
corpus_sha256 and prompt_suite_sha256
current corpus_sha256:
4968b0a9639d59474c00402dcd261a241377bdb57a6273554f4d6ad0d1172625
current prompt_suite_sha256:
38ef54d3a42700bb447fd3708588b008f3340e9170f5e16aa17ef79bf84962e5
```

## 31. Reference index

Primary and official references used for this design:

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [OpenAI: Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI: Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI: Safety in building agents](https://developers.openai.com/api/docs/guides/agent-builder-safety)
- [OpenAI: Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [OpenAI GPT-5.4: aliases and model snapshots](https://developers.openai.com/api/docs/models/gpt-5.4)
- [NIST/SEMATECH: Randomized block designs](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm)
- [NIST/SEMATECH: DOE terminology for replication and nested factors](https://www.itl.nist.gov/div898/handbook/pri/section7/pri7.htm)
- [NIST/SEMATECH: Balanced two-level nested measurements](https://www.itl.nist.gov/div898/handbook/mpc/section5/mpc5321.htm)
- [NIST Technical Note 2119: Binomial proportion intervals](https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2119.pdf)
- [Bartz-Beielstein et al.: Benchmarking in Optimization — Best Practice and Open Issues](https://arxiv.org/abs/2007.03488)
- [BoTorch: Parameter and outcome constraints](https://botorch.org/docs/constraints)
- [BoTorch: Multi-objective Bayesian optimization](https://botorch.org/docs/v0.16.0/multi_objective)
- [BoTorch: qEHVI, qNEHVI, and qNParEGO tutorial](https://botorch.org/docs/v0.17.2/tutorials/multi_objective_bo)
- [BoTorch: Risk-averse optimization with input perturbations](https://botorch.org/docs/v0.15.1/tutorials/risk_averse_bo_with_input_perturbations/)
- [Cakmak et al.: Bayesian Optimization of Risk Measures](https://proceedings.neurips.cc/paper/2020/hash/e8f2779682fd11fa2067beffc27a9192-Abstract.html)
- [Daulton et al.: Robust Multi-Objective Bayesian Optimization Under Input Noise](https://proceedings.mlr.press/v162/daulton22a.html)
- [Gardner et al.: Bayesian Optimization with Inequality Constraints](https://proceedings.mlr.press/v32/gardner14.html)
- [Rockafellar: Coherent Approaches to Risk in Optimization Under Uncertainty](https://sites.math.washington.edu/~rtr/papers/rtr206-RiskTutorial_INFORMS2007.pdf)
- [Hoffman, Brochu, and de Freitas: Portfolio Allocation for Bayesian Optimization](https://www.ora.ox.ac.uk/objects/uuid%3A8ab87685-4c62-4daf-9f1f-e59366cc4fa3)
- [Wang, Agarwal, and Dudík: Optimal and Adaptive Off-policy Evaluation in Contextual Bandits](https://www.microsoft.com/en-us/research/publication/optimal-adaptive-off-policy-evaluation-contextual-bandits/)
- [Dudík, Langford, and Li: Doubly Robust Policy Evaluation and Learning](https://www.microsoft.com/en-us/research/?p=580345)
- [Model Context Protocol: Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [OpenTelemetry: GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [OpenTelemetry: Links between asynchronous and batched spans](https://opentelemetry.io/docs/specs/otel/overview/#links-between-spans)
- [OpenTelemetry: Attribute requirement levels and high-cardinality opt-in](https://opentelemetry.io/docs/specs/semconv/general/attribute-requirement-level/)
- [OpenTelemetry: Baggage security considerations](https://opentelemetry.io/docs/concepts/signals/baggage/)
- [OpenTelemetry: Handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/)
- [SLSA v1.2: Provenance](https://slsa.dev/spec/v1.2/provenance)
- [SLSA v1.2: Build requirements](https://slsa.dev/spec/v1.2/requirements)
- [GitHub: Build and SBOM artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [GitHub: Offline artifact-attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)
- [Sigstore Cosign: Identity, subject, and attestation verification](https://docs.sigstore.dev/cosign/verifying/verify/)
- [The Update Framework specification](https://theupdateframework.github.io/specification/)
- [AWS Builders' Library: Avoiding insurmountable queue backlogs](https://d1.awsstatic.com/builderslibrary/pdfs/avoiding-insurmountable-queue-backlogs.pdf)
- [AWS Builders' Library: Using load shedding to avoid overload](https://builder.aws.com/content/3Eun1EEyX6p2e3VYNyRLSJzLuMV/using-load-shedding-to-avoid-overload)
- [Google SRE: Queue management and cascading-failure prevention](https://sre.google/sre-book/addressing-cascading-failures/)
- [Microsoft Azure Architecture Center: Circuit Breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
- [Microsoft Azure Architecture Center: Transient fault handling and aggregate retry budgets](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults)
- [PostgreSQL: `SKIP LOCKED` for queue-like tables](https://www.postgresql.org/docs/current/sql-select.html)
- [Tauri: Security model](https://v2.tauri.app/security/)
- [Tauri: Content Security Policy](https://v2.tauri.app/security/csp/)
- [Tauri: Capability/IPC authority boundaries](https://v2.tauri.app/reference/acl/capability/)
- [OWASP: HTML5/CORS security guidance](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html)
- [OWASP: REST security and workflow-state authorization](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [OWASP: Authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP: Insecure direct object reference prevention](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)
- [RFC 9449: OAuth DPoP request binding and replay resistance](https://datatracker.ietf.org/doc/rfc9449/)
- [RFC 9700: OAuth 2.0 Security Best Current Practice](https://datatracker.ietf.org/doc/html/rfc9700)
- [RFC 8725: JSON Web Token Best Current Practices](https://datatracker.ietf.org/doc/html/rfc8725)
- [OpenID Connect Core: stable issuer/subject identity](https://openid.net/specs/openid-connect-core-1_0.html)
- [Microsoft: WSL can launch a distribution as a specified user](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)
- [Microsoft: Windows AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
- [Microsoft: package identity and AppContainer are distinct](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations)
- [Microsoft: named-object and package-SID boundaries](https://learn.microsoft.com/en-us/windows/apps/develop/communication/sharing-named-objects)
- [OpenAI Agents Python tracing, official GitHub repository](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)
- [Model Context Protocol Python SDK, official GitHub repository](https://github.com/modelcontextprotocol/python-sdk)
- [MetaTool Benchmark, ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/bc12914d66b41b6bfc2d3a5decdb498b-Abstract-Conference.html)
- [Ishibashi et al.: Bayesian-optimization stopping criterion, AISTATS 2023](https://proceedings.mlr.press/v206/ishibashi23a.html)
- [NIST AI 600-1: Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)
- [OWASP: LLM06 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
- [OWASP: Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/)
- [Google DeepMind: FunSearch](https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/)
- [Google DeepMind: AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
- [Microsoft Research: OptiGuide](https://www.microsoft.com/en-us/research/project/optiguide-genai-for-supply-chain-optimization/publications/)
- [ReAct paper and project](https://react-lm.github.io/)
- [LangGraph: Durable execution and idempotency](https://langchain-ai.github.io/langgraph/how-tos/review-tool-calls-functional/)
- [SQLAlchemy: Cascades and database `ON DELETE`](https://docs.sqlalchemy.org/en/20/orm/cascades.html)
- [Alembic: Running batch migrations for SQLite](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [PostgreSQL: Partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html)
- [SQLite: Partial and unique partial indexes](https://www.sqlite.org/partialindex.html)
- [SQLite: Foreign-key actions](https://www.sqlite.org/foreignkeys.html)
- [SQLite: Transaction semantics](https://www.sqlite.org/lang_transaction.html)
- [Python: SQLite online backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
- [Microsoft: Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Microsoft: Job Object resource limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
- [Linux kernel: Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux `unix(7)`: Unix-domain socket credentials and permissions](https://www.man7.org/linux/man-pages/man7/unix.7.html)
- [Linux kernel: restricted pathname lookup](https://docs.kernel.org/filesystems/path-lookup.html)
- [Docker: Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)
- [Python: `multiprocessing` process termination warnings](https://docs.python.org/3/library/multiprocessing.html)
- [scikit-learn: Parallelism, resource management, and oversubscription](https://scikit-learn.org/stable/computing/parallelism.html)
- [NumPy: Global configuration and linear-algebra thread control](https://numpy.org/doc/stable/reference/global_state.html)
- [OWASP: Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [MDN: `sessionStorage`](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage)
- [OWASP: Server-Side Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP Top 10 A10: Server-Side Request Forgery](https://owasp.org/Top10/2021/A10_2021-Server-Side_Request_Forgery_%28SSRF%29/)
- [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP LLM05:2025 Improper Output Handling](https://genai.owasp.org/llmrisk/llm052025-improper-output-handling/)
- [NIST CAISI: Strengthening AI agent hijacking evaluations](https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations)
- [OpenAI Python SDK: default HTTPX client and redirect behavior](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- [OpenAI Python SDK: retries, timeouts, and request IDs](https://github.com/openai/openai-python#retries)
- [HTTPX: environment variables and `trust_env`](https://www.python-httpx.org/environment_variables/)
- [HTTPX: redirect behavior](https://www.python-httpx.org/compatibility/#redirects)
- [Open Robotics REP-103: SI units and coordinate-frame conventions](https://reps.openrobotics.org/rep-0103/)
- [PX4: `VehicleLocalPosition` NED coordinate semantics](https://docs.px4.io/main/en/msg_docs/VehicleLocalPosition)
- [PX4: ULog file-format specification](https://docs.px4.io/main/en/dev_log/ulog_file_format)
- [PX4: generated parameter reference and metadata fields](https://docs.px4.io/main/en/advanced_config/parameter_reference)
- [PX4: parameter subsystem, persistence, metadata, and read-only locking](https://docs.px4.io/main/en/advanced/parameters_and_configurations)
- [PX4: simulation environment and session `PX4_PARAM_<name>` overrides](https://docs.px4.io/main/en/simulation/)
- [PX4: finding parameters and firmware/build availability caveat](https://docs.px4.io/main/en/advanced_config/parameters)
- [MAVSDK: raw Param API and typed result states](https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_param.html)
- [NIST SP 330 §2: quantities, values, and units](https://www.nist.gov/pml/special-publication-330/sp-330-section-2)
- [NIST SP 811: Guide for the Use of the International System of Units](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-1-introduction)
- [NIST: Measurement uncertainty](https://physics.nist.gov/cuu/Uncertainty/)
- [W3C PROV Data Model](https://www.w3.org/TR/prov-dm/)
- [W3C PROV Primer](https://www.w3.org/TR/prov-primer/)
- [OpenTelemetry: Recording errors and `error.type`](https://opentelemetry.io/docs/specs/semconv/general/recording-errors/)
- [Google: Training, validation, and test sets](https://developers.google.com/machine-learning/crash-course/overfitting/dividing-datasets)
- [scikit-learn: Nested versus non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
- [Marco et al.: Robot Learning with Crash Constraints](https://arxiv.org/abs/2010.08669)
- [Groot et al.: Bayesian Optimization with Censored Response Data](https://arxiv.org/abs/1310.1947)
- [SciPy: Sampled-data trapezoidal integration](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.trapezoid.html)
- [Gazebo Sim: official `--seed` CLI change](https://github.com/gazebosim/gz-sim/pull/1618)
- [Gazebo Sim: WindEffects API and `wind_info` ground truth](https://gazebosim.org/api/sim/9/classgz_1_1sim_1_1systems_1_1WindEffects.html)
- [PX4 v1.17: Gazebo worlds, speed factor, and time synchronization](https://docs.px4.io/v1.17/en/sim_gazebo_gz/index)
- [NumPy: Parallel random generation and independent child streams](https://numpy.org/doc/stable/reference/random/parallel.html)
- [NumPy: `SeedSequence` reproducible entropy and spawn contract](https://numpy.org/doc/stable/reference/random/bit_generators/generated/numpy.random.SeedSequence.html)
- [NIST/SEMATECH: Blocking of factorial experiments](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3333.htm)
