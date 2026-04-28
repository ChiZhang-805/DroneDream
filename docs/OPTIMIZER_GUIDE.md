# Optimizer Guide

## Supported strategies

- `heuristic`: built-in baseline iterative search.
- `gpt`: LLM-assisted proposal loop.
- `cma_es`: evolutionary optimizer.

## Request fields (job create)

- `optimizer_strategy`
- `max_iterations`
- `trials_per_candidate`
- `max_total_trials`
- `acceptance_criteria` (`target_rmse`, `target_max_error`, `min_pass_rate`)
- `openai` (`api_key`, optional `model`) when `optimizer_strategy=gpt`

## GPT strategy notes

- API key is required on create/rerun request body for GPT jobs.
- API key is stored in encrypted form and not returned in responses.
- Use placeholders in docs/scripts only, e.g. `<OPENAI_API_KEY>`.

## Current capabilities

- End-to-end loop from candidate proposal -> trials -> aggregation -> report.
- Generation index and optimization outcome surfaced in job detail.
- Compare API can summarize completed jobs (including batch child jobs).

## Limitations / roadmap

- No UI-side optimizer debugger per generation yet.
- Batch-level optimizer policy templates are not yet implemented (batch currently reuses per-job payloads).
