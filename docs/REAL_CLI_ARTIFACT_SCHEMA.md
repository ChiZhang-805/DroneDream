# DroneDream real_cli Artifact Schema v1

This document defines the stable contract between:

- external simulator runners (for example PX4/Gazebo),
- backend `real_cli` artifact registration/parsing, and
- frontend Trial Detail artifact + trajectory replay consumers.

## `trial_result.json` top-level schema

`trial_result.json` **must** be a JSON object with:

- `success`: `boolean`
- `metrics`: `object` (required on successful trials)
- `artifacts`: `array`
- `log_excerpt`: `string` (optional)
- `failure`: `object` (optional; expected when `success=false`)

The backend tolerates extra fields.

## Artifact metadata contract

Each `artifacts[]` item is a JSON object with:

- `artifact_type`: `string`
- `storage_path`: `string`
- `display_name`: `string` (recommended)
- `mime_type`: `string` (recommended)
- `file_size_bytes`: `number` (optional)

If `mime_type` is omitted, backend infers defaults for known types:

- `telemetry_json` / `reference_track_json`: `application/json`
- `worker_log` / `simulator_stdout` / `simulator_stderr`: `text/plain`

## `telemetry_json` artifact

- `artifact_type = "telemetry_json"`
- `mime_type = "application/json"`

JSON body:

```json
{
  "schema_version": "dronedream.telemetry.v1",
  "samples": [
    {
      "t": 0.0,
      "x": 0.0,
      "y": 0.0,
      "z": 3.0,
      "vx": 0.0,
      "vy": 0.0,
      "vz": 0.0,
      "roll": 0.0,
      "pitch": 0.0,
      "yaw": 0.0,
      "reference_x": 0.0,
      "reference_y": 0.0,
      "reference_z": 3.0
    }
  ]
}
```

Minimum per-sample required fields are `t/x/y/z` (numeric).

## `reference_track_json` artifact

- `artifact_type = "reference_track_json"`
- `mime_type = "application/json"`

JSON body:

```json
{
  "schema_version": "dronedream.reference_track.v1",
  "reference_track": [
    { "x": 0.0, "y": 0.0, "z": 3.0 }
  ]
}
```

## Text/log artifacts

- `worker_log`: worker/runner log text (`text/plain`)
- `simulator_stdout`: simulator stdout stream (`text/plain`)
- `simulator_stderr`: simulator stderr stream (`text/plain`)

## Path safety requirements

All artifact `storage_path` values must resolve under backend allowed artifact roots (`REAL_SIMULATOR_ARTIFACT_ROOT` / `ARTIFACT_ROOT`-derived roots). Paths that escape allowed roots are rejected for download and ignored by the adapter.
