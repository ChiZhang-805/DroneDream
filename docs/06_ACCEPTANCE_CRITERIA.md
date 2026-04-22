# 06_ACCEPTANCE_CRITERIA.md

> **Note on this revision.** The previously committed copy of this file had
> every Chinese sentence truncated mid-character, rendering most prose
> unreadable. The heading structure, acceptance IDs, and checklist items
> have been preserved where they were intact; the explanatory text has
> been restored in English to match the criteria actually being enforced
> by [`docs/ACCEPTANCE_REPORT.md`](./ACCEPTANCE_REPORT.md) and the test
> suite. No acceptance requirement has been relaxed by this rewrite.

## 1. Document info

- **Document Title**: DroneDream Acceptance Criteria
- **Version**: v1.1
- **Product Stage**: MVP
- **Audience**: Devin, product owner, backend / frontend engineers, QA.
- **Purpose**: Define the DroneDream MVP acceptance criteria — functional
  completeness, edge-case behavior, and Definition of Done.

---

## 2. Acceptance Philosophy

- Acceptance is about end-to-end correctness, robustness, and contract
  stability — not pixel-perfect UI polish.
- Priority order: full happy-path flow → core features → error and edge
  cases → data traceability → forward-compatible boundaries for later
  phases.
- Pure static mockups or chart-only UIs do not count as passing visual
  acceptance.

---

## 3. Acceptance Scope

Covers:

- Product-level acceptance.
- Page-level acceptance.
- Form and interaction acceptance.
- API-level acceptance.
- Data-persistence acceptance.
- Job / Trial state machine acceptance.
- Async mock-simulator / worker loop acceptance.
- Error and edge-case acceptance.

---

## 4. Product-Level Acceptance

### AC-P1: User can create a job

**Pass condition**

- The user can navigate to the **New Job** page.
- The form renders every required field with correct defaults.
- Valid input submits successfully.
- The backend persists a real `Job` row.
- The frontend navigates to Job Detail on success.

### AC-P2: User can observe job progress

**Pass condition**

- Immediately after creation, the job is in `QUEUED` (and progresses to
  `RUNNING` once the worker picks it up).
- Job Detail shows the current status.
- The page updates via periodic polling (no frontend timer state machine).
- Phase / progress information is surfaced.

### AC-P3: User can view final results

**Pass condition**

- Completed job renders `COMPLETED`.
- Page shows baseline metrics.
- Page shows optimized metrics.
- Page shows best parameters.
- Page shows at least one comparison chart.
- Page shows a human-readable summary.

### AC-P4: User can understand failure and retry

**Pass condition**

- Failed job renders `FAILED`.
- Page shows a user-readable failure summary.
- Page offers a **Rerun** entry point.
- Rerun creates a **new** job.
- Original job history is preserved.

### AC-P5: User can review historical jobs

**Pass condition**

- Dashboard or History lists historical jobs.
- At minimum shows job id, track type, status, created-at.
- Clicking a job navigates to its detail page.

---

## 5. Page-Level Acceptance

### Dashboard

- Title and primary CTA (+ New Job).
- Recent jobs table.
- Summary cards.
- Loading / empty / error states.

### New Job

- All required fields present.
- Correct defaults.
- Client-side validation.
- Valid submit navigates to Job Detail.
- On failed submit, user input is preserved and an error is shown.

### Job Detail

- Core summary card.
- Supports `running / aggregating / completed / failed / cancelled`.
- On `COMPLETED`, shows best parameters, metric cards, baseline vs.
  optimized comparison, trial summary, summary text.

### Trial Detail

- Shows trial metadata, metrics, and failure reason (when failed).

### History / Reports

- Lists jobs.
- Supports the empty state.
- Links back into detail pages.

---

## 6. Form and Interaction Acceptance

- Required fields cannot be empty.
- Numeric fields parse correctly (non-numeric input rejected).
- `altitude_m` and every `wind.*` component are strictly range-checked.
- Enum fields accept only documented values.
- Create Job flow is complete end-to-end.
- View Job flow is complete end-to-end.
- Retry flow is complete end-to-end.

---

## 7. API-Level Acceptance

- Every API response uses the standard envelope.
- Error structure is consistent (see `04_API_SPEC.md` §5).
- Status enums are stable.
- `POST /api/v1/jobs` creates a real `Job` row.
- `GET /api/v1/jobs` returns the list.
- `GET /api/v1/jobs/{job_id}` returns the full detail object.
- `POST /api/v1/jobs/{job_id}/rerun` creates a new job.
- `POST /api/v1/jobs/{job_id}/cancel` only succeeds on non-terminal jobs.
- `GET /api/v1/jobs/{job_id}/trials` returns trial summaries.
- `GET /api/v1/trials/{trial_id}` returns trial detail.
- `GET /api/v1/jobs/{job_id}/report` returns the final report when the job
  is `COMPLETED`.
- Report-not-ready and report-on-failed-job cases return explicit,
  structured error envelopes.

---

## 8. Data-Level Acceptance

- Job records persist.
- Job status transitions are durable.
- Baseline candidate exists for every job.
- Candidate records are independent rows.
- Best candidate is identifiable (`is_best=true`).
- Trial records persist per candidate.
- Trial state / execution metadata persists.
- Trial metrics persist.
- Completed jobs have a `JobReport`.
- Artifact metadata is queryable.

---

## 9. State Machine Acceptance

### Job

- `CREATED -> QUEUED -> RUNNING -> AGGREGATING -> COMPLETED`.
- Unexpected errors may transition to `FAILED`.
- User cancellation may transition to `CANCELLED`.
- `COMPLETED / FAILED / CANCELLED` are terminal and may not be re-cancelled.

### Trial

- `PENDING -> RUNNING -> COMPLETED`.
- Or `PENDING -> RUNNING -> FAILED` / `CANCELLED`.

### Report

- `PENDING -> READY`.
- Or `PENDING -> FAILED`.

---

## 10. Async Execution and Worker Acceptance

- Creating a job does not block the HTTP request until the job finishes.
- Trials are executed by the worker (or an equivalent async unit).
- Worker failures do not poison the system.
- Timeouts are clearly recorded on the trial.
- The MVP runs end-to-end under the default mock simulator.
- Mock mode honors the same contracts as the real adapter.

---

## 11. Aggregation and Result Acceptance

- Every job runs a baseline.
- Each candidate's score is the aggregate of its trials.
- Best-candidate selection logic is stable and deterministic given the
  same input trials.
- UI renders results from persisted data only — no mock fallback.

---

## 12. Error and Edge-Case Acceptance

- Missing required fields are rejected on both frontend and backend.
- Non-enum values are rejected.
- Out-of-range numeric values are rejected.
- Job not found returns `404 JOB_NOT_FOUND`.
- Trial not found returns `404 TRIAL_NOT_FOUND`.
- Report not ready returns a structured error envelope
  (`REPORT_NOT_READY`).
- Worker timeouts are recorded on the trial.
- Partial trial failure is represented coherently (per-trial failure codes
  + job-level aggregate).
- Terminal jobs cannot be re-cancelled.
- Page-load errors surface a user-readable error state.
- A failed submission does not clear user input.

---

## 13. Basic Quality Acceptance

- Terminology is consistent across UI, API, and docs.
- UI and API contracts stay in sync.
- Failures are traceable from job → candidate → trial.
- Rerun does not overwrite the source job; it creates a new row.
- History is preserved indefinitely within the database.

---

## 14. Definition of Done

The MVP is Done if **all** of the following hold:

1. Core pages are usable: Dashboard, New Job, Job Detail, Trial Detail,
   History / Reports.
2. Happy path is end-to-end live: user creates a job, watches status,
   reaches `COMPLETED` or `FAILED`, can rerun, can review history.
3. The API contract matches `04_API_SPEC.md`.
4. `Job`, `CandidateParameterSet`, `Trial`, `TrialMetric`, `JobReport` are
   persisted as real rows.
5. Job creation is asynchronous; trials run via the worker or an
   equivalent async unit.
6. Results pages render baseline, optimized, best parameters, comparison,
   and summary text.
7. Common failure scenarios are handled gracefully.
8. The MVP runs end-to-end under the default mock simulator.

---

## 15. Constraints for Devin

- Do not ship a UI-only prototype.
- Do not skip baseline execution.
- Do not merge the `Candidate` and `Trial` concepts into a single row.
- Do not silently swallow failure states.
- Do not rush polish at the expense of API-contract or enum stability.
