# Optimizer Guide

## Supported strategies

- `heuristic`: built-in deterministic search.
- `gpt`: LLM proposes next candidates.
- `cma_es`: CMA-ES optimizer (`backend/app/orchestration/cma_es_optimizer.py`).

## Safe ranges

Input-level safety validation is enforced via request schemas (e.g. altitude, wind, pass-rate limits). Optimizer proposals are constrained by backend-side acceptance checks before use.

## Acceptance criteria

Configured in job request:

- `target_rmse`
- `target_max_error`
- `min_pass_rate`

Worker evaluates these against aggregated metrics to decide optimization outcome.

## Roadmap

- Add user-configurable per-parameter hard bounds in UI.
