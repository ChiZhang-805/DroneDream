# Phase 8 — Real Simulator Adapter + Iterative GPT Parameter Tuning

Phase 8 extends the Phase 7 MVP with two coordinated capabilities:

1. A **real external simulator adapter** (`real_cli`) that shells out to any
   external drone simulator binary over a small, well-defined JSON CLI
   protocol. The built-in `mock` adapter is unchanged.
2. A **simulate-analyze-retune loop** driven by a new server-side **GPT
   parameter proposer** that calls OpenAI to suggest the next generation of
   candidates. The existing deterministic heuristic optimizer is still
   supported (but is not the default UX), and it continues to use
   the Phase 7 **batch** dispatch — baseline + all heuristic candidates up
   front, one generation only. Iterative generation-by-generation dispatch
   applies to `optimizer_strategy="gpt"` jobs only. See
   §3. Iterative job flow for the exact semantics.

The loop repeats until a candidate passes the configured acceptance criteria
or until `max_iterations` / `max_total_trials` is reached.

**Out of scope (intentionally unchanged):** auth/login, advanced
track editor, real drone hardware, production multi-worker scaling, any
client-side call to OpenAI. Only the server ever sees the OpenAI API key.

---

## 1. Per-job configuration

`POST /api/v1/jobs` accepts these new optional fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `simulator_backend` | `"mock" \| "real_cli"` | `"mock"` | Which adapter to run trials against. |
| `optimizer_strategy` | `"heuristic" \| "gpt"` | `"gpt"` | Source of candidate proposals. |
| `max_iterations` | int 1–20 | `20` | Max generations after baseline. |
| `trials_per_candidate` | int 1–10 | `3` | Scenarios evaluated per candidate. |
| `acceptance_criteria.target_rmse` | float \| null | `null` | Skip if `null`. |
| `acceptance_criteria.target_max_error` | float \| null | `null` | Skip if `null`. |
| `acceptance_criteria.min_pass_rate` | float 0–1 | `0.8` | Fraction of trials that must finish. |
| `openai.api_key` | string | — | **Required** only when `optimizer_strategy = "gpt"`. |
| `openai.model` | string \| null | env `OPENAI_MODEL` or `"gpt-4.1"` | Optional. |

The API **never** returns `openai.api_key`. The key is encrypted via
`cryptography.fernet.Fernet` using `APP_SECRET_KEY` and stored in a
`JobSecret` row scoped to the job. When the job reaches a terminal state the
row is soft-deleted (`deleted_at` is set).

`APP_SECRET_KEY` / `DRONEDREAM_SECRET_KEY` is the server-side encryption key;
it is **not** the user's OpenAI API key.

**`APP_SECRET_KEY` (or `DRONEDREAM_SECRET_KEY`) must be visible to both the
backend process and the worker process.** The backend uses it at job
creation to encrypt the submitted key; the worker uses it later to decrypt
the key before calling OpenAI. Recommended local setup: put it in the
root-level `.env` (both `scripts/dev-backend.sh` and `scripts/dev-worker.sh`
source it automatically), or export it in each terminal before launching
the backend and the worker.

If `optimizer_strategy = "gpt"` and no `APP_SECRET_KEY` is configured on the
**backend** process, job creation fails with `INVALID_INPUT`
(`details.reason = "server_secret_key_not_configured"`). If the worker does
not see the same `APP_SECRET_KEY`, an already-submitted GPT job transitions
to `FAILED` with `optimization_outcome = "llm_failed"`.

The job response additionally echoes `simulator_backend_requested`,
`optimizer_strategy`, `max_iterations`, `trials_per_candidate`,
`acceptance_criteria`, `current_generation`, `optimization_outcome`, and
`openai_model` (never the key).

---

## 2. Real simulator adapter (`real_cli`)

### 2.1 Protocol

For each trial, the adapter creates a run directory at
`$REAL_SIMULATOR_ARTIFACT_ROOT/jobs/{job_id}/trials/{trial_id}/`, writes
`trial_input.json`, invokes the configured command, and reads
`trial_result.json`.

**Command configuration:**

```bash
export REAL_SIMULATOR_COMMAND='python /path/to/example_real_simulator.py'
export REAL_SIMULATOR_ARTIFACT_ROOT=/var/lib/drone_dream/artifacts
export REAL_SIMULATOR_TIMEOUT_SECONDS=300
export REAL_SIMULATOR_KEEP_RUN_DIRS=true
```

If the command string contains the tokens `{input}` and `{output}` they are
substituted with the paths of `trial_input.json` and `trial_result.json`
respectively. Otherwise, the adapter appends
`--input trial_input.json --output trial_result.json` to the command.

### 2.2 `trial_input.json` (written by the adapter)

The track / scenario fields are emitted **twice**: once as the grouped
`job_config` object (canonical) and once as top-level aliases (convenience
for wrapper authors who prefer a flat shape). The two forms always hold
identical values — wrapper authors may read either. Only `job_config` is
guaranteed to exist in future protocol revisions; the top-level aliases are
an additive convenience.

```json
{
  "trial_id": "trial_...",
  "job_id": "job_...",
  "candidate_id": "cand_...",
  "seed": 42,
  "scenario_type": "nominal",
  "scenario_config": {},

  "job_config": {
    "track_type": "circle",
    "start_point": {"x": 0.0, "y": 0.0},
    "altitude_m": 3.0,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust"
  },

  "track_type": "circle",
  "start_point": {"x": 0.0, "y": 0.0},
  "altitude_m": 3.0,
  "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
  "sensor_noise_level": "medium",
  "objective_profile": "robust",

  "parameters": {
    "kp_xy": 1.0, "kd_xy": 0.2, "ki_xy": 0.05,
    "vel_limit": 5.0, "accel_limit": 4.0, "disturbance_rejection": 0.5
  },
  "output_path": "trial_result.json"
}
```

### 2.3 `trial_result.json` (written by the external simulator)

**Success:**

```json
{
  "success": true,
  "metrics": {
    "rmse": 0.32, "max_error": 0.9, "overshoot_count": 1,
    "completion_time": 12.4, "crash_flag": false, "timeout_flag": false,
    "score": 0.76, "final_error": 0.12, "pass_flag": true,
    "instability_flag": false,
    "raw_metric_json": {"simulator": "px4_gazebo", "details": {}}
  },
  "artifacts": [
    {
      "artifact_type": "trajectory_plot",
      "display_name": "Trajectory Plot",
      "storage_path": "/abs/or/relative/path/to/trajectory.png",
      "mime_type": "image/png",
      "file_size_bytes": 12345
    }
  ],
  "log_excerpt": "short user-readable log"
}
```

**Failure:**

```json
{
  "success": false,
  "failure": {"code": "SIMULATION_FAILED", "reason": "PX4 did not arm"},
  "artifacts": [],
  "log_excerpt": "…"
}
```

### 2.4 Failure mapping

| Condition | `failure_code` |
|---|---|
| `REAL_SIMULATOR_COMMAND` unset or binary missing | `ADAPTER_UNAVAILABLE` |
| Subprocess exceeded `REAL_SIMULATOR_TIMEOUT_SECONDS` | `TIMEOUT` |
| Output file missing, unreadable, or not a JSON object | `SIMULATION_FAILED` |
| `success: false` with a structured failure | `failure.code` (e.g. `SIMULATION_FAILED`) |

### 2.5 Reference external simulator

`scripts/simulators/example_real_simulator.py` is a deterministic
reference implementation used by the test suite and the real_cli demo. It
supports per-scenario / per-noise penalties and `inject_failure` for
controlled failure testing — **it is not** the mock adapter.

### 2.6 PX4/Gazebo-oriented real_cli runner

`scripts/simulators/px4_gazebo_runner.py` is an environment-driven wrapper
that targets the same `real_cli` contract while making room for real
PX4/Gazebo stacks when available locally.

It intentionally does **not** claim the repo already contains a complete PX4
workspace or launch graph. Instead:

- `PX4_GAZEBO_DRY_RUN=true` provides deterministic fixture telemetry for CI/dev.
- real mode requires `PX4_GAZEBO_LAUNCH_COMMAND`; if missing/unexecutable the
  runner emits `ADAPTER_UNAVAILABLE`.
- the lower-level site-specific launcher must write telemetry artifacts the
  runner can ingest.

See `docs/PX4_GAZEBO_RUNNER.md` for env vars, command template tokens,
telemetry schema, metric formulas, and failure mappings.

---

## 3. Iterative optimization loop

1. Job creation dispatches only the baseline candidate (`current_generation=0`,
   `current_phase="baseline"`).
2. When all baseline trials are terminal, the baseline is aggregated and
   evaluated against the acceptance criteria.
   - **Pass** → mark baseline as best, generate report, `status=COMPLETED`,
     `optimization_outcome="success"`.
   - **Fail** → propose generation 1 (heuristic or GPT), dispatch its trials,
     increment `current_generation`.
3. Each subsequent generation repeats step 2. If the best candidate so far
   still fails after `current_generation == max_iterations` or after
   `total_trials >= max_total_trials`, the job terminates with:
   - `optimization_outcome = "max_iterations_reached"` and
     `status = COMPLETED` (or `optimization_outcome = "no_usable_candidate"`).
   - A best-so-far report is still generated whenever at least one candidate
     produced usable metrics, and the UI renders it.
4. If the GPT proposer fails, the job transitions to
   `optimization_outcome="llm_failed"` with an `llm_proposal_failed` event on
   the timeline.

**Heuristic mode retains Phase 7 batch semantics** — when
`optimizer_strategy="heuristic"`, `start_job()` dispatches the baseline
**and all heuristic optimizer candidates** up front in a single batch, the
worker processes them, and aggregation emits a READY report. The acceptance
evaluator still annotates `optimization_outcome` (`success` vs
`no_usable_candidate`) on the job, but heuristic jobs **do not generate
later generations after failure** — there is only one generation of
candidates beyond the baseline.

**Only GPT jobs** use the iterative generation-by-generation dispatcher
described above: baseline first, evaluate, propose exactly one new generation
candidate from the LLM, dispatch, repeat until pass / `max_iterations` / `max_total_trials`.

---

## 4. GPT parameter proposer

* `backend/app/orchestration/llm_parameter_proposer.py` calls OpenAI
  **server-side only** using the official `openai` SDK and the
  `chat.completions` API with a strict JSON-schema response format.
* Input to the model includes: objective profile, track/altitude/wind/noise,
  safe parameter ranges, previous candidate parameters, aggregated metrics,
  trial failure summaries, and the acceptance criteria.
* Output is validated, clamped to `PARAMETER_SAFE_RANGES`, deduplicated, and
  checked for NaN / Inf. `proposal.label` and `proposal.rationale` are
  persisted on `CandidateParameterSet.proposal_reason`.
* Emits `llm_proposal_started`, `llm_proposal_completed`, and
  `llm_proposal_failed` `JobEvent` rows on the audit trail.
* Per-job override: `app.orchestration.aggregation.set_llm_client_override()`
  installs a deterministic fake OpenAI client (used by the test suite).

### 4.1 Proposal JSON schema

```json
{
  "type": "object",
  "properties": {
    "proposals": {
      "type": "array", "minItems": 1, "maxItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "label": {"type": "string"},
          "rationale": {"type": "string"},
          "parameters": {
            "type": "object",
            "properties": {
              "kp_xy": {"type": "number"}, "kd_xy": {"type": "number"},
              "ki_xy": {"type": "number"}, "vel_limit": {"type": "number"},
              "accel_limit": {"type": "number"},
              "disturbance_rejection": {"type": "number"}
            },
            "required": ["kp_xy","kd_xy","ki_xy","vel_limit","accel_limit","disturbance_rejection"],
            "additionalProperties": false
          }
        },
        "required": ["label","rationale","parameters"],
        "additionalProperties": false
      }
    }
  },
  "required": ["proposals"],
  "additionalProperties": false
}
```

### 4.2 Safe parameter ranges (enforced after GPT response)

| Parameter | Range |
|---|---|
| `kp_xy` | [0.3, 2.5] |
| `kd_xy` | [0.05, 0.8] |
| `ki_xy` | [0.0, 0.25] |
| `vel_limit` | [2.0, 10.0] |
| `accel_limit` | [2.0, 8.0] |
| `disturbance_rejection` | [0.0, 1.0] |

---

## 5. Running demos

### 5.1 Mock + heuristic (Phase 7 demo)

```bash
./scripts/dev-backend.sh   # or: backend/.venv/bin/uvicorn app.main:app
./scripts/dev-worker.sh    # or: worker/.venv/bin/drone-dream-worker
cd frontend && npm run dev
```

Create a job in the UI with the defaults (`simulator_backend=mock`,
`optimizer_strategy=heuristic`).

### 5.2 real_cli + heuristic

```bash
export REAL_SIMULATOR_COMMAND="$(which python) $(pwd)/scripts/simulators/example_real_simulator.py"
export REAL_SIMULATOR_ARTIFACT_ROOT="$(pwd)/.artifacts"
./scripts/dev-worker.sh
```

Create a new job in the UI with `simulator_backend=real_cli` and the default
heuristic strategy.

### 5.2.1 real_cli + PX4/Gazebo runner (dry-run validation path)

```bash
export REAL_SIMULATOR_COMMAND="$(which python) $(pwd)/scripts/simulators/px4_gazebo_runner.py"
export REAL_SIMULATOR_ARTIFACT_ROOT="$(pwd)/.artifacts"
export PX4_GAZEBO_DRY_RUN=true
./scripts/dev-worker.sh
```

This validates the full `real_cli` orchestration path without requiring a local
Gazebo installation. To switch to real execution, set
`PX4_GAZEBO_DRY_RUN=false` and provide `PX4_GAZEBO_LAUNCH_COMMAND` pointing
to your local launcher wrapper.

### 5.3 mock + GPT

```bash
export APP_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
./scripts/dev-worker.sh
```

Create a job with `optimizer_strategy=gpt` and supply an OpenAI API key in the
New Job form. The key is stored encrypted; the worker uses it to call OpenAI
until the job is terminal, then the `JobSecret` row is soft-deleted.

### 5.4 real_cli + GPT

Combine §5.2 and §5.3 — same job creation flow with both `simulator_backend`
and `optimizer_strategy` flipped.

### 5.5 Rerun behavior for GPT jobs

Rerunning a GPT job stays GPT-based. The rerun request must include a **fresh**
`openai.api_key`; previously stored encrypted keys are not reused.

---

## 6. Configuration reference

| Env var | Used by | Default |
|---|---|---|
| `APP_SECRET_KEY` / `DRONEDREAM_SECRET_KEY` | Backend secret store | (none; required for GPT jobs) |
| `OPENAI_MODEL` | LLM proposer | `gpt-4.1` |
| `REAL_SIMULATOR_COMMAND` | `real_cli` adapter | (none; ADAPTER_UNAVAILABLE if unset) |
| `REAL_SIMULATOR_WORKDIR` | `real_cli` adapter | current working directory |
| `REAL_SIMULATOR_TIMEOUT_SECONDS` | `real_cli` adapter | `300` |
| `REAL_SIMULATOR_ARTIFACT_ROOT` | `real_cli` adapter | `./artifacts` |
| `REAL_SIMULATOR_KEEP_RUN_DIRS` | `real_cli` adapter | `true` |
| `SIMULATOR_BACKEND` | Legacy override (tests) | unset (per-job setting used) |

**Leave `SIMULATOR_BACKEND` unset (blank) for normal use.** The shipped
`.env.example` ships it as `SIMULATOR_BACKEND=` (empty) so the per-job
`simulator_backend` selection from the New Job form is respected. When the
variable is non-empty, it acts as a **global override** — every job uses
that backend regardless of what the UI selected. This is intentional for
Phase 7 back-compat and for debugging (e.g. forcing all jobs to `real_stub`
to exercise the failure path). Precedence, highest first:

1. `SIMULATOR_BACKEND` env var (if non-empty)
2. Job's `simulator_backend_requested` column (Phase 8, UI selection)
3. Factory default (`mock`)

See `backend/tests/test_simulator_adapter.py::test_resolve_backend_override_*`
and `::test_env_simulator_backend_treats_blank_as_unset` for the exact
behaviour.

---

## 7. Testing & verification commands

```bash
# Backend
backend/.venv/bin/ruff check backend
backend/.venv/bin/mypy backend/app
backend/.venv/bin/pytest backend

# Worker
worker/.venv/bin/ruff check worker

# Frontend
cd frontend && npm run typecheck && npm run lint && npm run build && npm test
```

Phase 8-specific test files:

- `backend/tests/test_phase8_real_cli.py` — adapter success, timeout,
  missing command, malformed output, structured failures.
- `backend/tests/test_phase8_llm_proposer.py` — clamp, dedup, rejection of
  invalid/NaN output, event audit, secret never surfaced in responses.
- `backend/tests/test_phase8_iterative_loop.py` — baseline → GPT generation
  dispatch, max-iterations best-so-far, LLM-failure fallback, secret purge.

---

## 8. What was not changed

- Existing API envelope, job statuses, mock simulator, heuristic optimizer,
  report generation, and Phase 7 acceptance tests are unmodified. The
  Phase 7 mock+heuristic demo still passes end-to-end.
- No frontend ever calls OpenAI directly.
- GPT cannot execute simulations, control the worker, or persist arbitrary
  parameters — it only proposes candidate parameter sets as strict JSON,
  which the backend validates, clamps, and dispatches through the existing
  worker + `SimulatorAdapter` path.


---

## 9. Job PDF report artifact + secure download

After a job report is finalized, the backend now also generates a PDF report artifact server-side (never in the browser).

- Output file path: `REAL_SIMULATOR_ARTIFACT_ROOT/jobs/{job_id}/reports/{job_id} report.pdf`
- File name format is always: `{job_id} report.pdf`
- The generated PDF is paginated and is expected to include all candidate/trial rows for large jobs (no silent truncation).
- The PDF is registered as a job artifact with `artifact_type="pdf_report"` and `mime_type="application/pdf"`.
- Frontend Job Detail shows a **Download PDF report** button when this artifact exists, and the artifact row itself also exposes a Download PDF action.
- PDF generation failure records a `pdf_report_generation_failed` job event and does not fail the whole job/report pipeline.

### Security notes

- The PDF content is derived from job/candidate/trial/report data and excludes secret-like fields (OpenAI API key, app secrets, etc.).
- Artifact downloading uses `GET /api/v1/artifacts/{artifact_id}/download`.
- Download paths are validated with resolved absolute paths and must stay under configured artifact roots; paths outside allowed roots are rejected with `403`.
- `mock://` artifacts are metadata-only and are not downloadable.


## Phase 8 visualization addendum (PR3)

For browser-native trajectory replay and optional Runpod noVNC Gazebo iframe setup, see [docs/RUNPOD_GAZEBO_VISUALIZATION.md](RUNPOD_GAZEBO_VISUALIZATION.md).
