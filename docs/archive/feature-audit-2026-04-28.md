# Main branch feature audit (2026-04-28)

This note records the verification run requested by the user to ensure `main` includes post-Phase-8 features.

## Confirmed features present on `main`

- custom track / `reference_track`
- 3D trajectory replay
- real_cli artifact v1 schema
- artifact download router (`/api/v1/artifacts/{artifact_id}/download`)
- `cma_es` optimizer
- trial leasing / multi-worker safety
- S3/MinIO artifact storage
- optional demo token auth
- advanced scenario config
- job compare
- reproducibility manifest
- enhanced PDF report generation
- batch jobs
- refreshed docs and runbooks

## Closure-critical checks

- `backend/app/main.py` includes `artifacts_router` and mounts it under `/api/v1`.
- `backend/app/routers/artifacts.py` implements download rules for mock/s3/local storage.
- `backend/app/config.py` keeps both artifact roots and `allowed_artifact_roots`.
- `frontend/src/api/client.ts` exposes `artifactDownloadUrl` + `fetchArtifactJson`.
- Trial/Job detail replay + artifact panels and related tests are present.

## Validation commands executed

- `ruff check backend`
- `mypy backend/app`
- `pytest backend`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- `cd frontend && npm test`

## 2026-04-28 re-verification in this workspace

- Current branch is `work` (no local `main` branch exists in this clone).
- `git remote -v` returned no remotes, so pushing/merging to public GitHub cannot be performed from this environment.
- Re-ran full backend/frontend/script acceptance checks successfully in this workspace.
