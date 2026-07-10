# Optimizer and Experiment Guide

DroneDream treats tuning as a reproducible experiment rather than a sequence of
manual PX4 edits. Every candidate is evaluated on the same scenario/seed matrix,
then ranked from training scenarios. Holdout scenarios are reported separately and
never influence candidate ranking, early stopping, or LLM feedback.

## Strategies

- `none`: evaluate the baseline only.
- `heuristic`: keyless deterministic Halton search; this is the API and UI default.
- `cma_es`: population-based search over every enabled numeric parameter domain.
- `gpt`: provider-neutral LLM proposals with deterministic fallback. Supported
  configurations include OpenAI, Qwen, DeepSeek, and an explicitly allowlisted
  OpenAI-compatible endpoint.

All strategies project proposals back into the declared parameter domain. Integer,
boolean, enum, stepped, log-scaled, locked, and disabled parameters are handled by
the shared search-space layer.

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

The LLM sees parameter domains and training feedback only. Invalid, duplicate, or
out-of-domain output is rejected/projected; a deterministic proposal path remains
available when the provider response is unusable.

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
PX4/Gazebo assets and a real SITL smoke test. The bundled real runner currently
fails closed for non-nominal or advanced effects; use its nominal-only wizard
profile or a custom launcher that emits truthful applied-effect evidence.
