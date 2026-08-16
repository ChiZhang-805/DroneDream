# DroneDream Engine Pack

The Engine Pack is the frequently updated application layer that runs inside
`DroneDreamRuntime`. It deliberately excludes Ubuntu, PX4, Gazebo, Valkey, and
the shared Python dependency environment. Those remain in the comparatively
stable Runtime Base.

An Engine Pack contains only production application sources:

- `backend/app` and Alembic migrations;
- `worker/drone_dream_worker`;
- `scripts/simulators`;
- the package metadata required to identify those sources.

`tools/engine_pack.py build` produces a deterministic `tar.gz`, an internal
manifest, and an external bundle descriptor. The descriptor binds the archive
hash and the manifest hash. The archive is intended to be carried by the
signed DroneDream desktop updater, so users still install one product update.

The Runtime Base installs each pack below
`/opt/dronedream/engine/releases/<pack-id>` and atomically switches
`/opt/dronedream/engine/current` only after validation and health checks.
Persistent jobs and artifacts remain below `/var/lib/dronedream` and are not
part of the pack.

Build and verify locally:

```powershell
python engine-pack/tools/engine_pack.py build `
  --repository-root . `
  --output-directory engine-pack/out `
  --source-commit (git rev-parse HEAD)

python engine-pack/tools/engine_pack.py verify `
  --descriptor engine-pack/out/engine-pack-bundle.json `
  --archive engine-pack/out/DroneDreamEnginePack.tar.gz
```
