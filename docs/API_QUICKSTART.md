# API Quickstart

Base URL: `http://127.0.0.1:8000/api/v1`

## 1) Create a single job

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "track_type": "circle",
    "start_point": {"x": 0, "y": 0},
    "altitude_m": 5,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic"
  }'
```

## 2) Batch create (1~50 child jobs)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/batches \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "sweep-a",
    "description": "batch experiment",
    "jobs": [
      {
        "track_type": "circle",
        "start_point": {"x": 0, "y": 0},
        "altitude_m": 4,
        "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
        "sensor_noise_level": "medium",
        "objective_profile": "robust",
        "simulator_backend": "mock",
        "optimizer_strategy": "heuristic"
      },
      {
        "track_type": "u_turn",
        "start_point": {"x": 0, "y": 0},
        "altitude_m": 6,
        "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
        "sensor_noise_level": "medium",
        "objective_profile": "fast",
        "simulator_backend": "mock",
        "optimizer_strategy": "heuristic"
      }
    ]
  }'
```

> If any child is invalid, API returns `422` and creates nothing.

## 3) Query batch and child jobs

```bash
curl http://127.0.0.1:8000/api/v1/batches
curl http://127.0.0.1:8000/api/v1/batches/<batch_id>
curl http://127.0.0.1:8000/api/v1/batches/<batch_id>/jobs
```

## 4) Cancel a batch

```bash
curl -X POST http://127.0.0.1:8000/api/v1/batches/<batch_id>/cancel
```

Behavior:
- Non-terminal child jobs are moved to `CANCELLED`.
- Terminal child jobs remain unchanged.
- Batch detail status is aggregated from child statuses.

## 5) Common job endpoints

```bash
curl 'http://127.0.0.1:8000/api/v1/jobs?page=1&page_size=20'
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/trials
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/report
curl -X POST http://127.0.0.1:8000/api/v1/jobs/<job_id>/cancel
curl -X POST http://127.0.0.1:8000/api/v1/jobs/<job_id>/rerun
```

## Current capabilities

- End-to-end job lifecycle API.
- Batch API for grouped experiment submission and management.
- Artifact list/download endpoints.

## Limitations / roadmap

- Batch comparison/filter APIs are not yet separate endpoints (frontend reuses existing compare endpoint with completed child job IDs).
