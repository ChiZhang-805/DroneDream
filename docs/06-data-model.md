# DroneDream data model

This document summarizes the persistence model used by the API and worker. It
is intentionally conceptual rather than a duplicate of every SQLAlchemy
column. The authoritative definitions are `backend/app/models.py` and the
reviewed Alembic migrations under `backend/alembic/versions/`.

## Design rules

- Keep Job, Candidate, Trial, Metric, Report, Artifact, and Event records
  separate so experiments remain auditable.
- Store frequently filtered state in typed columns; use JSON only for
  versioned or extensible experiment payloads.
- Preserve history instead of overwriting prior candidates or trials.
- Fence asynchronous work with explicit state, leases, timestamps, and
  attempt-specific evidence.
- Scope every user-owned query through the authenticated User relationship.

## Entity overview

1. `User` — local/demo/OIDC identity.
2. `BatchJob` — API compatibility container; batch pages are retired.
3. `Job` — one optimization experiment and its complete configuration/state.
4. `JobSecret` — encrypted, expiring per-job provider credential.
5. `CandidateParameterSet` — one baseline/manual/optimizer proposal.
6. `Trial` — one candidate, scenario, and seed execution attempt.
7. `TrialMetric` — one validated metric record per Trial.
8. `JobReport` — finalized comparison and recommendation.
9. `Artifact` — metadata for one Job- or Trial-owned object.
10. `ArtifactDigestReceipt` — insert-once content/ownership binding for a
    retained Artifact.
11. `JobEvent` — append-only operational/audit event.

## User and compatibility batch

`User` stores `id`, optional email/display name, `identity_provider`,
`external_subject`, and timestamps. The provider/subject pair is unique when
present.

`BatchJob` stores owner, name/description, status, timestamps, and its Jobs.
The batch HTTP contract remains for existing clients, but the desktop product
does not expose a batch creation workflow.

## Job

The legacy flat configuration remains queryable: track type, start coordinates,
altitude, four directional wind values, sensor-noise level, and objective
profile. The versioned experiment definition is stored separately:

- `reference_track_json`, `baseline_parameter_json`, and
  `advanced_scenario_config_json`;
- `vehicle_profile_json`, `parameter_catalog_version`,
  `parameter_space_json`, `objective_config_json`, and `scenario_suite_json`;
- simulator backend, optimizer strategy, iteration/trial budgets, acceptance
  thresholds, current generation, and optimization outcome; and
- provider/model metadata without the plaintext API key.

Relational pointers include owner, optional compatibility batch, baseline/best
candidate IDs, and `source_job_id` for reruns. State columns retain progress,
latest failure, current phase, and lifecycle timestamps.

Job states are:

```text
CREATED | QUEUED | RUNNING | AGGREGATING | FINALIZING |
COMPLETED | FAILED | CANCELLED
```

`FINALIZING` is a committed, cancellable, renewable lease used while reports or
LLM decisions are produced outside a long database transaction. The Job stores
an opaque `finalization_claim_token`, the exact
`finalization_claim_generation`, and `finalization_lease_expires_at`. A
heartbeat may extend only the same unexpired token and generation. Before an
aggregation, failure, next-generation dispatch, report, or terminal-state
transaction can commit, the worker must atomically renew that exact claim. This
compare-and-swap update is the write fence on both SQLite and PostgreSQL. Report
generation acquires the fence before writing immutable filesystem or object
storage and holds the Job-row lock through the terminal commit. An expired or
replaced worker rolls back its pending state/events and exits without
dispatching or publishing a report.

## JobSecret

`JobSecret` stores only the encrypted API key, provider, creation/expiry time,
and deletion time. The encryption key comes from `APP_SECRET_KEY`. Secrets are
never returned by the API, copied by rerun, or written into frontend drafts.

## CandidateParameterSet

Each Candidate belongs to one Job and stores generation/source/label,
`parameter_json`, aggregate metrics and score, counts/rank, and baseline/best
flags. Proposal provenance is preserved in `proposal_reason`,
`optimizer_metadata_json`, `parent_candidate_id`, and optional
`llm_response_json`. Experimental optimizer metadata records the actual child
algorithm and proposal backend rather than only the user-facing strategy name.

Common source types are `baseline`, `optimizer`, `manual`, and `rerun_copy`.

## Trial and TrialMetric

A Trial belongs to both a Job and Candidate. It stores seed, scenario type and
configuration, worker/backend identity, status, attempt/failure data, queue and
execution timestamps, and a renewable `lease_owner`/`lease_expires_at` fence.

Trial states are:

```text
PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
```

Supported scenario values are:

```text
nominal | noise_perturbed | wind_perturbed | combined_perturbed |
turbulence | gps_dropout | payload_changed | battery_degraded |
actuator_delay | custom
```

One optional `TrialMetric` record stores RMSE, maximum/final error,
overshoots, completion time, score, crash/timeout/pass/instability flags, and
bounded `raw_metric_json`. A successful simulator process is not enough: the
worker validates identity, metric types/ranges, artifacts, parameter evidence,
and requested physical-effect evidence before committing success.

## JobReport

One Report per Job stores status, best candidate, summary text, baseline and
optimized aggregates, comparison data, best parameters, and an optional
content-addressed winner-selection evidence envelope plus a foreign key to an
insert-once `WinnerFreezeReceipt`. The receipt binds one Job, outcome contract,
baseline, winner, evidence ID, full evidence JSON, and freeze timestamp; Job
and evidence ID are unique. The envelope and receipt are required for modern
evidence-bound optimization reports and nullable only for legacy
compatibility. Supported SQLite and PostgreSQL schemas reject receipt updates
and deletes with database triggers; readers still reverify the content hash
and Job bindings. Report states are `PENDING`, `READY`, and `FAILED`.

## Artifact

Artifacts use the polymorphic pair `(owner_type, owner_id)`, where
`owner_type` is only `job` or `trial`. Metadata includes artifact type,
display name, managed storage path, MIME type, 64-bit file size, and creation
time. New retained bytes set `integrity_policy=sha256-v1` and have one
`ArtifactDigestReceipt`. That receipt binds Artifact ID, owner type/ID,
artifact type, a SHA-256 of the storage path, content SHA-256, content byte
count, and a content-addressed evidence ID.

Real Trial artifacts use attempt- and content-addressed storage keys so a retry
cannot overwrite a prior attempt:

```text
jobs/{job}/trials/{trial}/attempts/{attempt}/{type}/{sha256}-{name}
```

Generated Job artifacts are also deterministic and insert-once by content:
regeneration verifies the current stored bytes before accepting an exact retry,
and rejects changed content before writing. Authorization still rechecks the
owning Job. Digest-bound local and S3-compatible objects are read and verified
before download; only legacy unbound S3 objects may use a presigned redirect.
Legacy mock/metadata-only rows remain nullable for compatibility.

Supported SQLite and PostgreSQL schemas reject digest-receipt updates and
unauthorized deletes with database triggers. Explicit Job deletion and
retention cleanup insert a transaction-scoped
`ArtifactDigestDeleteAuthorization`; its Artifact foreign-key cascade removes
the authorization in the same transaction. This preserves normal user-data
deletion without creating a general receipt-deletion path. Object-store
retention/versioning and separation of database owner from application roles
remain deployment responsibilities.

## JobEvent

`JobEvent` is implemented, not optional. It stores `job_id`, `event_type`,
optional structured `payload_json`, and creation time. Events cover lifecycle,
candidate/trial work, retention, finalization, cancellation, and failure. There
is no separate free-form `event_message` column.

## Relationships

- User -> Jobs and compatibility BatchJobs: one-to-many.
- BatchJob -> Jobs: one-to-many.
- Job -> Candidates, Trials, Events, and Secrets: one-to-many.
- Job -> Report: one-to-one.
- Candidate -> Trials: one-to-many.
- Trial -> TrialMetric: one-to-one.
- Artifact -> Job or Trial: validated polymorphic ownership.
- Artifact -> ArtifactDigestReceipt: optional one-to-one for legacy
  compatibility, required for newly retained real bytes.

## Index and migration expectations

High-value indexes cover user/time and status Job queries, source/batch IDs,
candidate generation/best/baseline lookups, Trial job/candidate/status/lease
queries, unique Trial metrics and reports, artifact ownership, and JobEvent
time order. Artifact ID and digest evidence ID are unique in the receipt table.
Production startup must run Alembic and keep
`AUTO_CREATE_SCHEMA=false`; application startup must not silently mutate a
production schema.
