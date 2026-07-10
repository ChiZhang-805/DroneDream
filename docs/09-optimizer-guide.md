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
`minimize`/`maximize` direction, normalization, and an optional target. Constraints
support `lt`, `lte`, `gt`, `gte`, and `eq`, with hard or soft handling.

Robust aggregation modes are:

- `mean`
- `worst`
- `cvar` using `cvar_alpha`
- `percentile` using `percentile`

Hard-constraint violations make a candidate infeasible. The candidate endpoint
returns feasible state, objective values, violations, Pareto membership, and
representative recommendations (`balanced`, plus the best point for each objective).

## Fair scenario matrix

`scenario_suite.cases` defines named, weighted cases. Each case has a scenario type,
one or more seeds, arbitrary validated configuration, and a `holdout` flag. With
`common_random_numbers=true`, every candidate receives the same cases and seeds.

At least one enabled non-holdout case is required. The trial budget must cover the
whole baseline matrix and, when optimization is enabled, at least one complete
candidate matrix. Holdout metrics are persisted under the aggregate's `holdout`
section only.

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
not evidence that real PX4/Gazebo physics has passed. Production acceptance requires
a Linux worker with the selected PX4/Gazebo assets and a real SITL smoke test.
