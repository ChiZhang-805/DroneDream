# Real CLI Artifact Schema

This document describes the normalized artifact payload shape consumed by DroneDream when using `simulator_backend=real_cli`.

## Purpose

- Keep simulator script outputs stable for backend parsing.
- Ensure report/trial aggregation can consume real-run metrics.

## Expected top-level structure

```json
{
  "run_id": "<string>",
  "simulator_backend": "real_cli",
  "status": "COMPLETED | FAILED | CANCELLED",
  "metrics": {
    "rmse": 0.0,
    "max_error": 0.0,
    "overshoot_count": 0,
    "completion_time": 0.0,
    "score": 0.0,
    "final_error": 0.0,
    "pass_flag": true,
    "crash_flag": false,
    "timeout_flag": false,
    "instability_flag": false
  },
  "trajectory": [
    {"t": 0.0, "x": 0.0, "y": 0.0, "z": 0.0}
  ],
  "logs": {
    "stdout_excerpt": "<string>",
    "stderr_excerpt": "<string>"
  },
  "artifacts": [
    {
      "artifact_type": "<string>",
      "path": "<absolute-or-workspace-relative-path>",
      "mime_type": "<optional mime>"
    }
  ]
}
```

## Notes

- Fields may be partially omitted by external scripts, but missing metrics reduce report quality.
- Paths are resolved by backend storage pipeline; do not include secrets in artifact payloads.

## Current capabilities

- Backend can persist artifact metadata and expose download endpoint.
- Frontend can render artifact cards and trajectory replay when data exists.

## Limitations / roadmap

- Schema versioning field is recommended but not yet strictly enforced.
