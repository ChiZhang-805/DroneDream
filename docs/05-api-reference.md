# 05-api-reference.md

> This is a human-readable guide to the public contract. The live
> `/api/v1/openapi.json` document and strict Pydantic schemas are authoritative
> for the complete field-level contract.

## 1. Document info

- **Document Title**: DroneDream API Specification
- **Version**: v1.1
- **API Namespace**: `/api/v1`
- **Audience**: API consumers, frontend engineers, backend engineers, QA.
- **Purpose**: Summarize the DroneDream API contract — request/response
  shape, status codes, error codes, and deployment boundary.

---

## 2. API Design Principles

- REST-style HTTP.
- JSON only.
- Every response uses the same envelope (§4).
- Every error uses the same structured error object (§4, §5).
- Job creation endpoints are **asynchronous**: they return immediately with a
  `QUEUED` job record. See §7 for the response contract.
- `/api/v1` is a fixed version prefix; breaking changes require a new major
  version (`/api/v2`).

---

## 3. Common Conventions

- `Content-Type: application/json` on every request and response body.
- Timestamps are ISO 8601 UTC strings (e.g. `2026-04-22T19:39:00Z`).
- Status enums are fixed (§3.1). Do not rename.
- IDs are opaque strings (`job_<hex>`, `cand_<hex>`, `tri_<hex>`,
  `usr_<hex>`). Treat them as strings on the client side.

### 3.1 Enums (locked)

- **Job status**: `CREATED | QUEUED | RUNNING | AGGREGATING | FINALIZING | COMPLETED | FAILED | CANCELLED`
- **Trial status**: `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`
- **Report status**: `PENDING | READY | FAILED`
- **Track type**: `circle | u_turn | lemniscate | custom`
- **Sensor noise**: `low | medium | high`
- **Objective profile**: `stable | fast | smooth | robust | custom`
- **Scenario type** (trial-level): `nominal | noise_perturbed |
  wind_perturbed | combined_perturbed | turbulence | gps_dropout |
  payload_changed | battery_degraded | actuator_delay | custom`

---

## 4. Standard Response Format

### Success

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

### Error

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Invalid request payload",
    "details": null
  }
}
```

### Paginated list payload

```json
{
  "success": true,
  "data": {
    "items": [],
    "page": 1,
    "page_size": 20,
    "total": 0
  },
  "error": null
}
```

---

## 5. Standard Error Codes

Every error response sets `error.code` to one of the following values. HTTP
status codes are advisory — clients should branch on `error.code`.

### 5.1 Public API envelope codes

| Code | HTTP | Meaning |
|---|---|---|
| `INVALID_INPUT` | 422 | Missing, malformed, or out-of-range field on the request body or query string. |
| `JOB_NOT_FOUND` | 404 | No job matches `{job_id}`. |
| `TRIAL_NOT_FOUND` | 404 | No trial matches `{trial_id}`. |
| `JOB_NOT_RUNNABLE` | 409 | Cannot rerun / cancel this job from its current state. |
| `JOB_ALREADY_COMPLETED` | 409 | Cancel was called on a job already in `COMPLETED`. |
| `JOB_ALREADY_CANCELLED` | 409 | Cancel was called on a job already in `CANCELLED`. |
| `JOB_FAILED` | 409 | Report was requested for a job in the terminal `FAILED` state. `error.details.failure_code` gives the job-level cause (see §5.2). |
| `JOB_CANCELLED` | 409 | Report was requested for a job in the terminal `CANCELLED` state. |
| `REPORT_NOT_READY` | 409 | Report was requested while the job is still `CREATED / QUEUED / RUNNING / AGGREGATING / FINALIZING`. |
| `INTERNAL_ERROR` | 500 | Unhandled server error. Always includes a request-scoped message; `details` may be `null`. |

### 5.2 Job-level failure codes

These **do not** appear as `error.code` on the envelope. They appear on the
job object itself under `job.latest_error.code` (and in report error details
as `details.failure_code`) after a job has transitioned to `FAILED`:

| Code | Meaning |
|---|---|
| `ALL_TRIALS_FAILED` | Every trial attempted for the job failed. |
| `BASELINE_FAILED` | The baseline candidate's trials all failed. |

### 5.3 Trial-level failure codes

These appear on individual `Trial` rows under `trial.failure_code` (never as
`error.code` on the envelope):

| Code | Meaning |
|---|---|
| `ADAPTER_UNAVAILABLE` | The requested simulator adapter is unavailable, disabled for the current environment, or missing its executable command. The internal `real_stub` adapter is test-only and is rejected outside `APP_ENV=test`. |
| `SIMULATION_FAILED` | The adapter raised an error during execution. |
| `WORKER_TIMEOUT` | The trial exceeded its per-trial budget. |

---

## 6. Public API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/jobs` | Create a job (returns immediately with `QUEUED`). |
| `GET` | `/api/v1/jobs` | List jobs for Dashboard / History. Supports `?status=<enum>&page=&page_size=`. |
| `GET` | `/api/v1/jobs/{job_id}` | Job detail including progress and latest error. |
| `POST` | `/api/v1/jobs/{job_id}/rerun` | Clone config as a new `QUEUED` job. |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Cancel a non-terminal job. |
| `PATCH` | `/api/v1/jobs/{job_id}` | Update mutable job metadata. |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete an eligible owned job. |
| `GET` | `/api/v1/jobs/{job_id}/trials` | Per-job trial summaries. |
| `GET` | `/api/v1/jobs/{job_id}/candidates` | Candidate history, feasibility, Pareto front, and recommendations. |
| `POST` | `/api/v1/jobs/compare` | Compare owned experiments as JSON. |
| `GET` | `/api/v1/jobs/compare.csv` | Download an owned experiment comparison as CSV. |
| `GET` | `/api/v1/trials/{trial_id}` | Trial detail (metrics, failure reason, artifacts). |
| `GET` | `/api/v1/jobs/{job_id}/report` | Job report (requires job in `COMPLETED`). |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | Artifact metadata list. |
| `GET` | `/api/v1/artifacts/{artifact_id}/download` | Authorized local/S3 artifact download. |
| `POST/GET` | `/api/v1/batches` | Create or list batches. |
| `GET` | `/api/v1/batches/{batch_id}` | Batch detail. |
| `GET` | `/api/v1/batches/{batch_id}/jobs` | Jobs in a batch. |
| `POST` | `/api/v1/batches/{batch_id}/cancel` | Cancel active jobs in a batch. |
| `GET/POST` | `/api/v1/parameter-catalog/*` | Catalog discovery, presets, and selection validation. |
| `GET` | `/api/v1/capabilities` | Advisory runtime/optimizer capability discovery. |

`GET /health`, `/health/live`, and `/health/ready` live **outside** `/api/v1`.

List endpoints are bounded. `GET /api/v1/batches` accepts `page` (default 1)
and `page_size` (default 100, maximum 200), and returns `items`, `page`,
`page_size`, and `total`. `GET /api/v1/jobs/{job_id}/trials` keeps its array
response for compatibility, accepts `page` (default 1) and `page_size`
(default 200, maximum 500), and reports `X-Total-Count`, `X-Page`, and
`X-Page-Size` response headers. Those headers are CORS-exposed.

---

## 7. Job APIs

### 7.1 `POST /api/v1/jobs`

Minimal compatibility request (advanced experiment fields below are optional):

```json
{
  "track_type": "circle",
  "start_point": {"x": 0, "y": 0},
  "altitude_m": 5.0,
  "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
  "sensor_noise_level": "medium",
  "objective_profile": "robust"
}
```

**Optimization fields** (see [`09-optimizer-guide.md`](09-optimizer-guide.md) for
the full advanced experiment contract):

```json
{
  "simulator_backend": "mock",
  "optimizer_strategy": "heuristic",
  "max_iterations": 20,
  "trials_per_candidate": 3,
  "acceptance_criteria": {
    "target_rmse": 0.5,
    "target_max_error": 1.5,
    "min_pass_rate": 0.8
  }
}
```

- `simulator_backend`: `"mock"` (default) or `"real_cli"`.
- `optimizer_strategy`: `"heuristic"` (API default), `"none"`, `"cma_es"`,
  `"gpt"`, `"llm_harness"`, or one of the seven experimental strategies:
  `"constrained_mobo"`, `"multi_fidelity_mobo"`, `"turbo"`, `"saasbo"`,
  `"surrogate_cma_es"`, `"bipop_cma_es"`, and `"optimizer_portfolio"`.
- New clients should send provider credentials in `llm`; legacy `openai` remains accepted.
- An API key is required when `optimizer_strategy` is `"gpt"` or
  `"llm_harness"`;
  the server stores it encrypted (Fernet via `APP_SECRET_KEY`) and never
  returns it in any response.
- `vehicle_profile`, `parameter_space`, `objective_config`, `scenario_suite`, and
  `max_total_trials` define the reproducible advanced experiment. See
  [`09-optimizer-guide.md`](09-optimizer-guide.md).
- Acceptance criteria fields are all optional; `null` disables that check.

The job response echoes these fields (with every API key redacted):
`simulator_backend_requested`, `optimizer_strategy`, `max_iterations`,
`trials_per_candidate`, `acceptance_criteria`, `current_generation`,
`optimization_outcome`, provider/model metadata, and the advanced experiment config.

Validation errors:

- model-guided strategy (`"gpt"` or `"llm_harness"`) without `llm.api_key` (legacy
  `openai.api_key` is also accepted) →
  `INVALID_INPUT`.
- model-guided strategy without server-side `APP_SECRET_KEY` →
  `INVALID_INPUT` (`details.reason = "server_secret_key_not_configured"`).

Success response — the full `Job` object with a backward-compatible
`job_id` alias (equal to `id`):

```json
{
  "success": true,
  "data": {
    "id": "job_abc123",
    "job_id": "job_abc123",
    "status": "QUEUED",
    "track_type": "circle",
    "start_point": {"x": 0, "y": 0},
    "altitude_m": 5.0,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "progress": {"total_trials": 0, "completed_trials": 0, "phase": "queued"},
    "latest_error": null,
    "source_job_id": null,
    "created_at": "2026-04-22T19:39:00Z",
    "updated_at": "2026-04-22T19:39:00Z",
    "completed_at": null
  },
  "error": null
}
```

Notes:

- Clients may read either `data.id` or `data.job_id`. They are always
  identical for create/rerun responses; `id` is the canonical field and
  `job_id` is preserved as a convenience alias to avoid breaking older
  scripts that expected the original spec wording.
- The request returns immediately — simulation work is performed later by
  the worker.

### 7.2 `GET /api/v1/jobs`

Returns a paginated list for Dashboard / History. Query parameters:

- `status` — optional job-status enum (e.g. `COMPLETED`). Filters results.
- `page` — 1-indexed page number, default `1`.
- `page_size` — default `20`, max `100`.

### 7.3 `GET /api/v1/jobs/{job_id}`

Returns the full `Job` object including:

- Input config (`track_type`, `start_point`, `altitude_m`, `wind`,
  `sensor_noise_level`, `objective_profile`).
- `status`.
- `progress` (`total_trials`, `completed_trials`, `phase`).
- `latest_error` (`null` for non-failed jobs; populated for `FAILED`).
- `source_job_id` (populated on rerun'd jobs; points at the original).
- `created_at`, `updated_at`, `completed_at`.

### 7.4 `POST /api/v1/jobs/{job_id}/rerun`

Creates a new job by cloning the source job's configuration. Response
matches `POST /api/v1/jobs` exactly: the full new `Job` object plus the
`job_id` alias. The new job's `source_job_id` references the original.

For source jobs with `optimizer_strategy="gpt"` or `"llm_harness"`, the rerun
request must include a fresh provider configuration/key; stored credentials are
never reused:

```json
{
  "llm": {
    "provider": "openai",
    "api_key": "<API_KEY>",
    "model": "gpt-4.1"
  }
}
```

LLM reruns remain LLM-based; the previously stored encrypted job key is not reused.

### 7.5 `POST /api/v1/jobs/{job_id}/cancel`

Transitions a non-terminal job to `CANCELLED`. Rejects terminal jobs with
`JOB_ALREADY_COMPLETED` / `JOB_ALREADY_CANCELLED` / `JOB_FAILED` as
appropriate. Returns the updated `Job` object in the success envelope.

### 7.6 `POST /api/v1/experiment-assistant/turn`

Compiles one bounded ordinary-language turn into the shared five-step
experiment draft. This endpoint is draft-only: it cannot create a Job, start a
simulator, or write provider credentials to experiment storage.

The request includes the new message, locale, cumulative redacted summary,
current registered form values, explicitly confirmed field IDs, and at most 64
currently selected PX4 parameters with finite baseline and search-range
values. The selected model profile and API key are used for this call only.
Custom provider endpoints remain subject to the shared provider URL policy.

The response returns the cumulative summary; accepted and rejected field and
PX4 parameter patches; `explicit | derived | proposed_default` provenance;
server-recomputed missing/review fields; at most four focused questions; and
provider, model, and token-usage metadata.

Explicit or derived patches must reference the current message ID. Proposed
defaults cannot claim a user-message source or overwrite an explicit value.
Unknown fields, catalog-unknown parameters, non-finite values, invalid enums,
unsafe ranges, and malformed structured output are rejected. Removing the
final selected PX4 parameter leaves the draft incomplete.

---

## 8. Trial APIs

### 8.1 `GET /api/v1/jobs/{job_id}/trials`

Returns a list of trial summaries. Each item includes at least:

- `id`
- `candidate_id`
- `candidate_label`, `candidate_source_type`, `candidate_is_baseline`,
  `candidate_generation_index`
- `seed`
- `scenario_type`
- `status`
- `score` (when completed)
- `failure_code`, `failure_reason` (when failed)

### 8.2 `GET /api/v1/trials/{trial_id}`

Returns a single trial with:

- Metadata (parent job id, candidate id, seed, scenario).
- `metrics` (when completed): `overshoot_pct`, `settle_time_s`,
  `xy_rmse_m`, `max_attitude_error_deg`, `energy_proxy`, `score`.
- `failure_code`, `failure_reason`, `log_excerpt` (when failed).

---

## 9. Report and Artifact APIs

### 9.1 `GET /api/v1/jobs/{job_id}/report`

For `COMPLETED` jobs, returns:

- `report_status` (`READY`).
- `best_candidate_id`.
- `summary_text` (human-readable, produced locally — no external LLM).
- `baseline_metrics` and `optimized_metrics` (keyed metric blocks).
- `comparison` (array of `{metric, baseline, optimized, lower_is_better}`).
- `best_parameters` (flat key/value map).
- `winner_evidence_id` (content-addressed final-selection receipt for modern
  evidence-bound jobs; `null` for legacy reports).
- `winner_freeze_receipt_id` (insert-once Job-level freeze row referenced by
  modern reports; `null` for legacy reports).

For `FAILED` jobs, returns a structured error envelope with
`error.code=JOB_FAILED` and `error.details.failure_code` set to a
job-level failure code (see §5.2). For jobs still in flight, returns
`error.code=REPORT_NOT_READY`. If a modern winner-freeze receipt no longer
matches its evidence or Job selection, returns
`error.code=REPORT_EVIDENCE_INVALID`.

### 9.2 `GET /api/v1/jobs/{job_id}/artifacts`

Returns the artifact metadata list for a job. Each row includes
`artifact_type`, `display_name`, `storage_path`, `mime_type`, file size, and
timestamps. Digest-bound rows additionally expose `integrity_policy`,
`digest_evidence_id`, and `content_sha256`. Storage paths may identify mock,
managed local, or S3-compatible objects.

### 9.3 `GET /api/v1/artifacts/{artifact_id}/download`

Downloads an owned managed-local or S3-compatible artifact. When an Artifact is
digest-bound, the service reads and verifies its bytes against the insert-once
receipt before streaming; digest-bound S3 objects never use an unverified
presigned redirect. A receipt/metadata/byte mismatch returns HTTP 409 with
`error.code=ARTIFACT_INTEGRITY_INVALID`. Legacy unbound S3 objects may still
return a short-lived redirect when presigning is available. Mock artifacts are
metadata-only and return `ARTIFACT_NOT_DOWNLOADABLE`. Missing objects, paths
outside the configured artifact roots, and cross-user artifacts fail closed.

---

## 10. Input Validation Rules

Rejected by both Pydantic on the backend and by the New Job form on the
frontend before submission:

- `track_type` must be one of `circle | u_turn | lemniscate | custom`; custom
  tracks require at least two finite reference points.
- `altitude_m` must be in `[1.0, 20.0]`.
- Every `wind.*` component must be in `[-10.0, 10.0]`.
- `sensor_noise_level` must be one of `low | medium | high`.
- `objective_profile` must be one of `stable | fast | smooth | robust | custom`.
- Missing required fields are rejected with `INVALID_INPUT`.
- Unknown request fields are rejected by the strict Pydantic models; clients
  must not rely on undocumented fields.

---

## 11. Internal Service Interfaces

These are internal to the worker process and not exposed over HTTP.

### Job Manager ↔ Optimizer

- Input: `job_id`, `generation_index`, `previous_results`.
- Output: a batch of new `CandidateParameterSet` rows.

### Dispatcher ↔ Worker

- Input: trial payload — job config, candidate params, seed, scenario
  type.

### Worker → Backend

- Output: trial status, metrics, failure reason, artifact metadata.

---

## 12. Polling Expectations

- **Dashboard / History**: refresh on user action (pull-to-refresh / manual
  reload); no background polling.
- **Job Detail**: polls `GET /api/v1/jobs/{id}` every 4 s while the job is
  in `QUEUED / RUNNING / AGGREGATING / FINALIZING`; stops once the job reaches a terminal
  state.
- **Trial Detail**: polls while the trial is `PENDING / RUNNING`.

---

## 13. Implementation constraints

- Do not expose orchestration / optimizer steps as public API endpoints.
- Do not return different response shapes from the same endpoint depending
  on state — always use the standard envelope and populate the error
  object for failures.
- Error objects must remain structurally stable across releases.
- All status fields must use the locked enums from §3.1.
- The API layer must not be tightly coupled to any specific simulator
  implementation.
