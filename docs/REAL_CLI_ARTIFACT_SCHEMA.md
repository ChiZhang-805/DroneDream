# real_cli artifact contract

This document is the stable boundary between a DroneDream worker and an
external PX4/Gazebo runner. Paths may be absolute or relative to the Trial run
directory; the backend accepts only files below its configured artifact roots.

## Trial result envelope

The command receives `--input <trial_input.json> --output <trial_result.json>`
and must atomically publish an output object with this shape:

```json
{
  "schema_version": "dronedream.trial_result.v2",
  "execution_identity": {
    "trial_id": "trial-uuid",
    "job_id": "job-uuid",
    "candidate_id": "candidate-uuid",
    "seed": 42,
    "attempt_count": 1
  },
  "success": true,
  "backend": "px4_gazebo",
  "metrics": {
    "rmse": 0.42,
    "max_error": 1.21,
    "overshoot_count": 1,
    "completion_time": 32.8,
    "score": 0.73,
    "crash_flag": false,
    "timeout_flag": false,
    "final_error": 0.08,
    "pass_flag": true,
    "instability_flag": false,
    "raw_metric_json": {}
  },
  "artifacts": []
}
```

A failed run sets `success=false`, omits `metrics`, and supplies
`failure: {"code": "...", "reason": "..."}`. `log_excerpt` is optional in
both cases.

The external `failure.code` is a bounded diagnostic claim, not a trusted
taxonomy decision. The adapter persists the canonical
`UNVERIFIED_SIMULATOR_FAILURE` code for every producer-reported failure and
keeps the claimed code only inside its sanitized reason. Missing, malformed,
identity-mismatched, or inconsistent result envelopes become
`INVALID_SIMULATOR_RESULT`. A wall-clock process kill observed by the adapter
becomes `SIMULATOR_EXECUTION_TIMEOUT`. None of these nonphysical outcomes may
teach either the numerical or GPT parameter optimizer.

`success` and all metric flags are strict JSON booleans, not strings or
integers. Metric numbers must be finite; error/time metrics are non-negative,
and `overshoot_count` is a non-negative integer. A successful result is
accepted only when the command exits with code `0`. `trial_result.json` is
limited to 10 MiB.

`raw_metric_json` must remain a JSON object containing only finite JSON values;
it is limited to 20 nested levels and 10,000 total nodes. This includes numbers
inside nested arrays/objects (`1e999` is rejected even though some decoders turn
it into infinity).

The worker writes `dronedream.trial_input.v2` with the same
`execution_identity`. New runners must echo that object exactly. Identity-free
v1 output remains readable for old custom launchers, but any identity field
that is present is validated. Retries use an attempt-specific directory so a
late or stale process cannot overwrite the current attempt.

## Artifact metadata

Each `artifacts[]` item contains:

- `artifact_type`: stable machine name;
- `display_name`: user-facing name;
- `storage_path`: path below an allowed artifact root;
- `mime_type`: media type;
- `file_size_bytes`: optional size.

Known JSON artifacts are validated before persistence:

- `telemetry_json`: object containing `samples[]` with timestamps and vehicle
  positions;
- `reference_track_json`: object/array containing the commanded path;
- `trajectory_plot`: PNG, SVG, or another browser-renderable plot;
- `worker_log`: UTF-8 text;
- `px4_parameter_evidence_json`: one of the parameter transaction records
  described below.
- `scenario_config_json`, `controller_parameters_json`,
  `px4_parameters_input_json`, and `simulator_launch_config_json`: the complete
  input/launch evidence needed to reproduce an environment.
- `scenario_effect_request_json` and `scenario_effect_evidence_json`: the
  normalized physical-effect request and the launcher's validated application
  evidence. Static box/cylinder obstacles have a bundled Gazebo EntityFactory
  path; other requested effects require a site Runtime extension and fail
  closed without evidence.
- `simulator_runtime_manifest_json`: attempt identity plus requested/observed
  firmware, scenario-effect support, simulator profile, and timeout evidence.

Known telemetry/reference JSON artifacts are read through a 16 MiB validation
fence. An oversized or malformed known artifact is dropped instead of being
loaded without bound into worker memory. Legacy custom-runner metrics may
remain readable without that optional artifact. A successful result declaring
`backend=px4_gazebo` is stricter: dropping either the telemetry or reference
track invalidates the complete Trial result.

## PX4 telemetry semantic evidence

Every successful bundled PX4/Gazebo result uses
`dronedream.telemetry.v2` and exactly one `telemetry_json` plus one
`reference_track_json`. The telemetry contains a content-addressed
`dronedream.telemetry-semantic-contract/v1` that freezes:

- metres, metres/second, radians, and seconds as the position, velocity,
  attitude, and time units;
- `dronedream_local_cartesian_z_up` as the normalized coordinate frame and
  `relative_to_source_start` as the time origin;
- source kind, pre-normalization source SHA-256/byte count, extraction
  revision, normalized-sample SHA-256, and synthetic/physical status;
- sample count, start/end/duration, median interval, maximum gap, gap limit,
  and sampling coverage;
- for ULog extraction, the original ULog SHA-256/byte count, extractor
  revision, `PX4_LOCAL_NED` origin frame, and the explicit NED-to-z-up
  transform.

Physical metric-bearing telemetry needs at least two strictly timed samples,
must satisfy the frozen maximum-gap and minimum-coverage rules, and cannot use
the synthetic single-sample exception. The metric evaluation window is checked
again after takeoff/landing trimming. If a physical run cannot establish its
trusted flight window, it fails instead of using all samples as an ordinary
fallback.

RMSE and full-log RMSE use trapezoidal time integration, so inserting dense
zero-error samples cannot dilute a long error interval. `raw_metric_json`
binds its integration rule and sampling evidence to the telemetry contract.
Before accepting a bundled PX4 result, `real_cli` reloads the retained
telemetry, independently revalidates its contract and samples, and compares
all of those bindings. Missing, duplicate, mutated, or mismatched evidence
invalidates the Trial.

Every bundled result also carries
`dronedream.px4-evaluation-policy/v1` and
`dronedream.px4-evaluation-window-evidence/v1`. The policy freezes the pass,
coverage, takeoff-entry, near-track, consecutive-sample, and altitude-collapse
thresholds under a content address. From the retained telemetry, reference
track, optional `offboard_timing_json`, and that policy, the backend independently
repeats the ordered projection and derives the trusted evaluation window. The
offboard timing file is only a broad candidate; telemetry must still establish
the consecutive altitude-and-near-track entry and the landing trim. A missing
physical window fails closed, while the all-samples exception remains explicitly
synthetic. The runner's raw window fields, frozen policy, and content-addressed
window evidence must all match the backend result.

Every bundled result also carries
`dronedream.px4-core-metric-evidence/v1`. From the retained telemetry and
reference track—not from the runner's reported metric values—the backend
independently repeats the bounded ordered three-dimensional segment projection,
uses its independently derived evaluation sample indices, and recomputes time-weighted
evaluation/full-log RMSE, maximum error, completion duration, final endpoint
error, tracking-error peak count, evaluation sampling, and the maximum-error
sample. The content-addressed evidence and top-level/raw metric projections
must all match exactly.

Every bundled result also carries `dronedream.px4-outcome-policy/v1` and
`dronedream.px4-outcome-evidence/v1`. The backend independently derives:

- telemetry crash flags and in-window altitude collapse;
- position-speed and track-error instability;
- continuous directed arc coverage, backward travel, projection
  discontinuities, and start/endpoint reachability;
- scenario-effect readiness from the retained request and optional executor
  evidence;
- the final pass verdict and the frozen RMSE, maximum-error, duration, and
  penalty score components.

A successful metric-bearing result cannot claim a timeout: launcher or adapter
timeouts are terminal failed Trials before metric acceptance. The outcome
policy, evidence, raw projections, top-level flags, and score must all match the
backend compilation. The trusted scenario-effect request must also match the
single retained request artifact. Known JSON evidence is read with a strict byte
limit and nesting failures are rejected rather than escaping the validation
boundary.

Together these contracts prove the semantics, geometric measurements, and
current verdict/score of the retained normalized telemetry. When
`source_kind=px4_ulog`, a successful bundled Trial also requires exactly one
`px4_ulog` Artifact with `application/octet-stream`. The local wrapper copies
the source into the Trial run directory before extraction, and `real_cli`
streams the retained bytes through SHA-256 while enforcing the 1 GiB limit. The
digest and byte count must match the telemetry origin provenance exactly.
Cross-Trial artifact paths, missing/duplicate origin artifacts, empty ULogs, and
mutated bytes fail closed. SQL and object-store publication atomicity plus an
operational WORM retention policy remain separate deployment boundaries.

## PX4 parameter evidence

When real PX4 parameters are requested, the runner must emit all three files
before metrics are accepted:

1. `px4_parameters.requested.json` — normalized requested values;
2. `px4_parameters.before.json` — values observed before mutation or launch
   overrides;
3. `px4_parameters.applied.json` — firmware readback after application.

The applied record has `verification.verified=true`, contains the exact
requested parameter names, and includes any mismatches. A missing or mismatched
record invalidates the Trial; a dry-run record is explicitly marked
`status=simulated` so it cannot be mistaken for physical firmware evidence.

## Safety and isolation

The adapter rejects traversal and files outside configured roots. Production
workers upload accepted files under deterministic
`jobs/<job>/trials/<trial>/...` object keys. API downloads re-check the owning
Job's user before returning bytes or a temporary object-store URL.

The external command receives a least-privilege environment, not the worker's
complete `os.environ`. OS/Python and explicitly named PX4/Gazebo/ROS runtime
variables are retained; database URLs, S3/cloud/OIDC/LLM credentials, and every
variable whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, or
`CREDENTIAL` are removed before trial context is injected.

Timeout and cancellation terminate the complete simulator process tree. When
`REAL_SIMULATOR_KEEP_RUN_DIRS=false`, successful transient run directories are
removed only after the Trial executor has durably copied/uploaded every
artifact; failed runs are retained for diagnosis.
