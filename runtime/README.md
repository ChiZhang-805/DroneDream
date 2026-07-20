# DroneDreamRuntime WSL2 rootfs

This directory is the release skeleton for a self-contained, headless
DroneDream runtime. It builds an Ubuntu 24.04 `linux/amd64` image containing
the API, worker, Valkey, PX4 SITL, Gazebo Harmonic, MAVSDK and pyulog, then
exports that image as a WSL2 rootfs tar only after real smoke tests pass.

The scripts do **not** install, unregister, move, or modify any WSL
distribution on the developer's Windows machine.

## Release guarantees

- Ubuntu is selected by an immutable OCI digest; PX4 and Valkey use full Git
  commit IDs; Gazebo's metapackage and the Python dependency closure use exact
  versions from `pins.env` and `locks/python-requirements.lock`.
- The desktop-facing manifest contract remains `schemaVersion: 1`, a string
  `version`, a string map containing `backend`, `px4`, and `gazebo`, and the
  three booleans `px4Sitl`, `gazebo`, and `parameterReadback`.
- A freshly built image always contains all three smoke booleans as `false`.
  Only `export-rootfs.sh` can place a promoted manifest in a release tar, and
  it accepts only a successful report bound to the same runtime ID and Docker
  image ID.
- The smoke harness starts systemd, verifies API/worker/Valkey readiness, runs
  a `real_cli` adapter dry run, launches a real headless PX4 SITL + Gazebo
  x500 session, writes and reads back `MPC_XY_P`, and restores its old value.
- Release tars larger than 12 GiB are deleted and rejected.
- Long-running API, worker, and Valkey services run as unprivileged users.
  The only root service is a short one-shot initializer that creates private
  directories and a valid Fernet application key.

This is source-level reproducibility, not yet byte-for-byte reproducibility.
Ubuntu and OSRF apt repositories can change their transitive package
resolution even though the base image and Gazebo metapackage are pinned. Each
build records the observed apt and pip closures under `/opt/dronedream/runtime`.
A byte-identical release process should additionally mirror or snapshot apt
repositories and retain the resulting image by digest.

## Build on an Ubuntu builder

Requirements: Git, Python 3.12, Docker with Buildx, `linux/amd64` support, and
a clean committed worktree. A native Ubuntu builder or an adequately sized
WSL2 Ubuntu builder is recommended; the full PX4/Gazebo build is intentionally
not run on a normal GitHub-hosted runner.

```bash
bash runtime/build-rootfs.sh
```

The default image is `dronedream/runtime:0.1.0`. Override it consistently:

```bash
IMAGE=ghcr.io/example/dronedream-runtime:0.1.0 bash runtime/build-rootfs.sh
```

The build refuses modified **and untracked** files because the manifest must
not claim a Git commit while packaging different source bytes. The dedicated
Docker ignore file also excludes desktop, frontend, Rust `target`, virtual
environments, and other unrelated or generated content from the build context.

## Run the real smoke gate

The harness uses a privileged temporary Docker container so systemd and the
headless simulator can run. It deletes the container when complete.

```bash
bash runtime/smoke-image.sh \
  dronedream/runtime:0.1.0 \
  runtime/out/smoke-report.json
```

A failure still writes a diagnostic report but returns nonzero. It cannot be
used to export a publishable rootfs.

## Export the WSL2 artifact

```bash
bash runtime/export-rootfs.sh \
  dronedream/runtime:0.1.0 \
  runtime/out/smoke-report.json \
  runtime/out/DroneDreamRuntime-0.1.0-amd64.tar
```

Successful export also produces a SHA-256 sidecar and the promoted manifest.
The script rechecks every smoke result, runtime ID, image ID, and the 12 GiB
hard cap before returning success. Do not publish an image or tar that has not
passed this command.

## Optional manual WSL verification

These commands are documentation only; none of the build scripts invoke them.
Choose a new empty install directory and distribution name:

```powershell
wsl.exe --import DroneDreamRuntime D:\WSL\DroneDreamRuntime `
  .\DroneDreamRuntime-0.1.0-amd64.tar --version 2
wsl.exe -d DroneDreamRuntime -u root -- systemctl is-active `
  dronedream-api.service dronedream-worker.service valkey.service
Invoke-WebRequest http://127.0.0.1:8000/health/ready
```

Use `wsl.exe --unregister DroneDreamRuntime` only for a disposable verification
instance and only after confirming the distribution name. Unregistering erases
that distribution.

## Local storage policy

The runtime enables non-dry-run cleanup for its exclusively managed `jobs`
artifact subtrees with these safeguards:

- maximum managed artifacts: 12 GiB;
- maximum age: 30 days;
- preserve artifacts from the 10 most recent terminal jobs;
- never delete files younger than 24 hours, and give unreferenced files a
  24-hour grace period.

Maintain at least **20 GiB of host free-space headroom after installation** for
WSL's ext4 virtual disk growth, build/run directories, logs, and temporary
exports. The desktop prerequisite check currently requires 52 GiB free before
a fresh installation: 8 GiB for the download, 24 GiB for the estimated
installed runtime, and 20 GiB of immediate post-install reserve. Cleanup inside
Linux is not a substitute for host free space because a WSL virtual disk does
not automatically shrink after deletion.

Systemd journal storage is independently bounded so simulator stdout/stderr
cannot consume the disk indefinitely: persistent journals are capped at
512 MiB, volatile `/run` journals at 256 MiB, and entries expire after at most
14 days. Journald also keeps 20 GiB free on the persistent filesystem and
128 MiB free on its runtime filesystem; whichever size, age, or free-space
limit is reached first applies. Log rate limiting remains enabled for runaway
simulator output. These journal limits complement the 12 GiB artifact policy;
they do not replace it.

PX4's raw ULogs use a separate fixed managed directory at
`/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log`, so they cannot be
covered safely by the backend artifact cleaner. An hourly persistent systemd
timer applies a dedicated 4 GiB / 14-day ULog policy while always preserving
the 20 newest logs and every log younger than one hour. The cleaner only
considers regular `.ulg` files, never follows symlinks or deletes directories,
scans `/proc` for open file identities, and rechecks device, inode, size, and
modification time immediately before unlinking. Final deletion walks the fixed
root with POSIX `O_DIRECTORY|O_NOFOLLOW` directory descriptors and uses
dirfd-relative stat/unlink operations; platforms lacking those guarantees fail
closed. If open, recent, or changing files keep the directory above its cap, it
reports the remaining excess rather than deleting an unsafe candidate.

`SIMULATOR_BACKEND` is intentionally empty. Each job can choose `mock` or
`real_cli`; the runtime does not globally force every user's workflow into a
real simulator.

## Updating a release

1. Update reviewed values in `pins.env` and the exact Python lock together.
2. Update `DRONEDREAM_RUNTIME_VERSION` when the shipped runtime changes.
3. Run the static contract tests locally:

   ```bash
   python -m unittest discover -s runtime/tests -v
   python runtime/tools/runtime_manifest.py validate-config \
     --pins runtime/pins.env \
     --python-lock runtime/locks/python-requirements.lock
   ```

4. Commit the complete change, build from the clean commit, run the real smoke
   gate, and export. Retain the source commit, image digest, promoted manifest,
   tar SHA-256, and smoke logs with the release.

The `Runtime contract` GitHub workflow is intentionally static: it validates
contracts, pins, Python, shell syntax, and the rule that an untested manifest
cannot be released. It never labels or uploads a hosted-runner artifact as a
tested PX4/Gazebo runtime.

## Signed downloadable release

Exporting a rootfs is deliberately not the same as publishing it. The separate
`runtime/tools/runtime_release.py` tool verifies the promoted manifest and real
smoke report again, splits the uncompressed rootfs tar into 1900 MiB pieces,
records per-part and whole-artifact SHA-256 values, creates canonical release
metadata, signs it with Ed25519, and can verify/reassemble it atomically.

The private key is accepted only from an environment variable during signing;
it is never committed. The trusted public-key file is
`runtime/release-public-keys.json`; it contains the first beta public trust
anchor only. Publishing and installation fail closed for absent, malformed,
retired, or unknown signing keys.

See [the manifest-signed runtime release guide](../docs/14-runtime-release.md) for the
exact schema, one-time key setup, GitHub Release asset layout, self-hosted
workflow, and installer trust model. The workflow is manual and defaults to a
non-publishing verification run.
