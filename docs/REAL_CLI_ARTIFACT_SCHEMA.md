# real_cli artifact contract

This document is the stable boundary between a DroneDream worker and an
external PX4/Gazebo runner. Paths may be absolute or relative to the Trial run
directory; the backend accepts only files below its configured artifact roots.

## Trial result envelope

The command receives `--input <trial_input.json> --output <trial_result.json>`
and must atomically publish an output object with this shape:

```json
{
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
