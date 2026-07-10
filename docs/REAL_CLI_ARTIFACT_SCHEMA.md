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
- `simulator_runtime_manifest_json`: attempt identity plus requested/observed
  firmware, scenario-effect support, simulator profile, and timeout evidence.

Known telemetry/reference JSON artifacts are read through a 16 MiB validation
fence. An oversized or malformed known artifact is dropped instead of being
loaded without bound into worker memory; its Trial metrics may remain valid.

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
