# REAL_CLI Artifact Schema

This document defines the JSON contract for artifacts returned by the `real_cli` simulator adapter.

## Output JSON (high-level)

The simulator command writes an output JSON file with:

- `success` (boolean)
- `metrics` (object)
- `artifacts` (array)
- optional `failure` object for unsuccessful runs

## Artifact item schema

Each artifact item in `artifacts` should include:

- `artifact_type` (string): logical type, e.g. `telemetry_json`, `reference_track_json`, `stdout_log`, `stderr_log`
- `storage_path` (string): absolute path to file on disk
- `mime_type` (optional string): content type (e.g. `application/json`, `text/plain`)
- `metadata` (optional object)

## Telemetry JSON schema

Telemetry artifact payload should follow:

- `schema_version`: `dronedream.telemetry.v1`
- `samples`: array of points containing at least `t`, `x`, `y`, `z`

## Reference track JSON schema

Reference-track artifact payload should follow:

- `schema_version`: `dronedream.reference_track.v1`
- `reference_track`: array of waypoints with `x`, `y`, optional `z`

## Validation behavior

- Malformed artifact payloads are treated as warnings when the simulator run itself succeeded.
- Missing artifact files or unreadable paths can be surfaced as adapter errors depending on context.

## Notes

- This schema is intentionally minimal and compatibility-oriented.
- Additional artifact types may be added over time without breaking older consumers.
