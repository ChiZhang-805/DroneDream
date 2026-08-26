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

New internal manifests use `manifest.schema.json` (`schemaVersion: 2`). This
version binds the edition payload profile into the pack ID, so SIM, LAB,
Universal, and FIELD cannot silently exchange differently scoped executable
payloads. `manifest.v1.schema.json` is retained only to verify and replace
legacy unscoped packs; the builder never emits v1. The external bundle
descriptor and activation receipt remain schema v1 because their shapes did
not change.

The Runtime Base installs each pack below
`/opt/dronedream/engine/releases/<pack-id>` and atomically switches
`/opt/dronedream/engine/current` only after validation and health checks.
Persistent jobs and artifacts remain below `/var/lib/dronedream` and are not
part of the pack.

Runtime Base publishes a versioned manager-capability receipt described by
`manager-capabilities.schema.json` before the desktop attempts activation. A
Runtime that cannot read manifest v2 is treated
as requiring a one-time Runtime Base upgrade; the desktop must not defer that
incompatibility until after the user starts an Engine Pack update. A current
Runtime can read legacy v1 for migration and v2 for execution, while the
edition safety gate admits only v2 into qualified execution.

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
