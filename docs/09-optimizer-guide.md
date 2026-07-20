# Optimizer and Experiment Guide

DroneDream treats tuning as a reproducible experiment rather than a sequence of
manual PX4 edits. Every candidate is evaluated on the same scenario/seed matrix,
then scored from training scenarios. Holdout results never train the optimizer
or influence its acquisition function, but a candidate must pass its configured
holdout matrix before DroneDream can publish it as the final recommendation.

## Strategies

- `none`: evaluate the baseline only.
- `heuristic`: keyless deterministic Halton search.
- `cma_es`: population-based search over every enabled numeric parameter domain.
- `gpt`: provider-neutral LLM proposals. Supported
  configurations include OpenAI, Qwen, DeepSeek, and an explicitly allowlisted
  OpenAI-compatible endpoint.

Seven accuracy-first engines are available as an experimental group. New wizard
experiments default to the adaptive portfolio, while API clients may select any
engine explicitly:

- `constrained_mobo`: Matérn-5/2 ARD Gaussian processes, a learned feasibility
  probability, and constrained random-scalarization log expected improvement.
- `multi_fidelity_mobo`: the same constrained multi-objective model with
  cost-aware scenario/seed coverage. Partial-fidelity points train the model but
  cannot win; final verification runs at full fidelity.
- `turbo`: a TuRBO-inspired local GP trust region reconstructed from measured
  progress, useful when one global surrogate becomes unreliable. It is an
  explicit native approximation rather than the full reference implementation.
- `saasbo`: a 12-member strongly shrunk sparse-axis GP ensemble for wider
  parameter spaces. This native implementation is SAAS-inspired and is not
  presented as fully Bayesian MCMC SAAS.
- `surrogate_cma_es`: full-covariance CMA-ES with an RBF surrogate used to
  prescreen a larger offspring pool before expensive simulation.
- `bipop_cma_es`: full-covariance CMA-ES with a deterministic BIPOP-inspired
  alternating small/large restart schedule and stagnation recovery. This is
  not presented as the original BIPOP evaluation-budget balancing policy.
- `optimizer_portfolio`: allocates each generation across the six engines above
  using measured improvement, recent improvement, feasibility, and an
  exploration bonus. Every proposal records its child engine.

These implementations deliberately use honest backend names in candidate
metadata. For example, `constrained_mobo` does not claim to be qLogNEHVI,
`turbo` records its native trust-region approximation, and `saasbo` records
`fully_bayesian=false`. Crashed or missing-metric simulations
are retained as feasibility observations instead of being assigned a fabricated
large loss. See the
[experimental optimizer benchmark](./16-experimental-optimizer-benchmark.md)
for the shared synthetic regression campaign and its real-PX4 limitations.

The native exact-GP implementation also records `gp_training_set` in proposal
metadata. Histories of up to 160 usable observations per scalar GP are fitted
without thinning. Above that size, DroneDream uses an accuracy-first,
deterministic active set because the dependency-free dense Cholesky solver has
cubic runtime and quadratic memory. Each objective and the feasibility model
receive their own active set, retaining global elites, recent observations,
failures, parameter-space boundaries, and deterministic farthest-point spatial
coverage. This is an explicit active-set approximation of the full history, not
a claim that all historical rows were included in the exact posterior.

All strategies project proposals back into the declared parameter domain. Integer,
boolean, enum, stepped, log-scaled, locked, and disabled parameters are handled by
the shared search-space layer. Experimental proposals additionally persist the
algorithm, true proposal generator, child algorithm, random seed, fidelity,
acquisition/backend details, and generation in the candidate history and
reproducibility manifest. CMA proposals additionally persist distribution and
cohort identity, position, latent update vector, restart index, and update
eligibility so a replay cannot mix offspring from different distributions.

## Parameter space

Read the versioned catalog before creating an experiment:

```http
GET /api/v1/parameter-catalog?px4_version=v1.16
POST /api/v1/parameter-catalog/validate
```

Each `parameter_space` item declares a real PX4 name, baseline and search range:

```json
{
  "name": "MPC_XY_P",
  "baseline": 0.95,
  "minimum": 0.6,
  "maximum": 1.3,
  "step": 0.05,
  "scale": "linear",
  "value_type": "float",
  "enabled": true,
  "locked": false
}
```

Job creation validates PX4 version support, catalog membership, safe bounds, step
alignment, discrete choices, duplicate names, and known cross-parameter couplings.
The runner validates concrete values again before launch and requires PX4
`requested`, `before`, and `applied/readback` evidence.

## Objectives and constraints

`objective_config.objectives` supports up to 16 weighted objectives with
`minimize`/`maximize` direction, normalization, and an optional aspiration
target. A target contributes a one-sided normalized loss: minimize values at or
below the target, and maximize values at or above the target, contribute zero;
only the unmet gap is penalized. Raw objective values are still retained for
Pareto analysis. Constraints support `lt`, `lte`, `gt`, `gte`, and `eq`, with
hard or soft handling.

Robust aggregation modes are:

- `mean`
- `worst`
- `cvar` using `cvar_alpha`
- `percentile` using `percentile`

Hard-constraint violations make a candidate infeasible. The candidate endpoint
returns feasible state, objective values, violations, Pareto membership, and
representative recommendations (`balanced`, plus the best point for each objective).

`target_max_error` is a safety threshold and is evaluated against the worst
completed training-trial maximum error. Reports preserve both
`max_error_mean` and `max_error_worst`; the headline and acceptance evidence use
the worst value so one severe excursion cannot be hidden by quieter scenarios.

## Fair scenario matrix

`scenario_suite.cases` defines named, weighted cases. Each case has a scenario type,
one or more seeds, arbitrary validated configuration, and a `holdout` flag. With
`common_random_numbers=true`, every candidate receives the same cases and seeds.

At least one enabled non-holdout case is required. The trial budget must cover the
whole baseline matrix and, when optimization is enabled, at least one complete
candidate matrix. The wizard lets users enable nominal, wind, and sensor-noise
search cases independently, plus nominal and combined-stress holdout cases.

Rates are reduced in two levels: all dispatched seeds (including failed seeds)
first contribute to their case's completion, failure, and pass rates; configured
case weights are then applied. Seed-rich cases therefore cannot drown out a
high-priority case. Holdout metrics are persisted under the aggregate's `holdout`
section with counts, weighted rates, and `passed`, `failed`, `incomplete`, or
`error` validation status. Holdout evidence never influences training selection,
but any missing/failed holdout execution prevents it from being reported feasible.

## Provider-neutral LLM configuration

Use `llm`, not the legacy `openai` field, for new clients:

```json
{
  "provider": "deepseek",
  "api_key": "<API_KEY>",
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com"
}
```

API keys are encrypted at rest, never returned by the API, and are excluded from
frontend drafts. In production, custom base URLs must exactly match
`LLM_ALLOWED_BASE_URLS` to prevent server-side request forgery.

The LLM sees parameter domains and training feedback only. Invalid, duplicate,
or out-of-domain output is rejected or projected. Provider failures are
recorded and that LLM generation fails safely; DroneDream does not silently
relabel a deterministic fallback as an LLM proposal.

## Main experiment endpoints

```text
POST /api/v1/jobs
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/candidates
GET  /api/v1/jobs/{job_id}/report
POST /api/v1/jobs/{job_id}/rerun
POST /api/v1/jobs/compare
```

Use the candidate endpoint during and after tuning to render generation history,
Pareto results, feasibility, and recommended parameter sets.

## Reproducibility boundaries

Pin `vehicle_profile.px4_version`; for strict replay also pin
`vehicle_profile.firmware_commit`. Persisted trials include case ID, seed, scenario
configuration, parameters, simulator artifacts, and parameter-application evidence.

`mock` and PX4 runner dry-run modes are deterministic development tools. They are
not evidence that real PX4/Gazebo physics has passed. Mock uses an explicitly
synthetic, lower-is-better landscape in which every catalog parameter affects the
workflow score. Production acceptance requires a Linux worker with the selected
PX4/Gazebo assets and a real SITL smoke test. The bundled runner can prove
nominal execution and static box/cylinder obstacle injection. Other requested
physical effects fail closed until a site launcher emits truthful
applied-effect evidence.
