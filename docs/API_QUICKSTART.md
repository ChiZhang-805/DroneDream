# API Quickstart

Base URL: `http://127.0.0.1:8000/api/v1`

## Create job

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
    "optimizer_strategy": "heuristic",
    "simulator_backend": "mock"
  }'
```

## List jobs

```bash
curl 'http://127.0.0.1:8000/api/v1/jobs?page=1&page_size=20'
```

## Get job

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>
```

## List trials

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/trials
```

## Get report

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/report
```

## Download artifact

```bash
curl -L http://127.0.0.1:8000/api/v1/artifacts/<artifact_id>/download -o artifact.bin
```

## Cancel / rerun job

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs/<job_id>/cancel
curl -X POST http://127.0.0.1:8000/api/v1/jobs/<job_id>/rerun
```

## Batch APIs

- `POST /batches`
- `GET /batches`
- `GET /batches/{batch_id}`
- `GET /batches/{batch_id}/jobs`
- `POST /batches/{batch_id}/cancel`
