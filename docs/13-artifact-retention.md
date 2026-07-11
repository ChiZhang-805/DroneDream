# Local Artifact Capacity and Retention

DroneDream can enforce a bounded lifecycle for files stored by the local
artifact backend. The feature is deliberately disabled by default. S3/MinIO
deployments should use a private bucket lifecycle policy instead.

## Safety contract

Cleanup scans only these managed subtrees:

- `<ARTIFACT_ROOT>/jobs`
- `<REAL_SIMULATOR_ARTIFACT_ROOT>/jobs`

It does not scan the configured parent directory, follow symlinked directories,
or touch `mock://`, `s3://`, paths outside those subtrees, or textual paths that
contain `..`.

The following invariants apply:

1. Active jobs are never cleaned, including old unreferenced files inside an
   active job directory.
2. The newest configured number of terminal jobs is always retained.
3. Size-based eviction also respects a configurable minimum age.
4. Before a referenced file is removed, its `Artifact` rows and an
   `artifact_retention_cleanup` JobEvent are committed. Only then is the file
   unlinked.
5. If unlinking fails, the API no longer advertises the file and the remaining
   file becomes a retryable orphan. A later pass can remove it.
6. Immediately before unlinking, cleanup re-reads Artifact paths. A newly
   registered reference protects the file and defers deletion.
7. Internal artifact writers lock the owner Job and refuse registration after
   its first committed retention event. Cleanup takes the same Job lock.
8. On POSIX/WSL, deletion opens the managed root and every parent with
   `O_DIRECTORY|O_NOFOLLOW`, verifies the scanned device/inode, and calls
   dir-fd-relative unlink. Platforms without those primitives fail closed in
   apply mode; they may still run dry-run scans. The desktop runtime is expected
   to apply cleanup inside its WSL environment, not from native Windows Python.

These rules favor consistency over hitting the byte cap exactly. The reported
`capacity_excess_bytes` can remain non-zero when active/recent jobs or the
minimum-age floor protect all remaining candidates.

## Configuration

| Variable | Default | Meaning |
| --- | ---: | --- |
| `ARTIFACT_CLEANUP_ENABLED` | `false` | Enables periodic local scans. Required before `--apply`. |
| `ARTIFACT_CLEANUP_DRY_RUN` | `true` | Plans and logs cleanup without changing DB/files. |
| `ARTIFACT_CLEANUP_INTERVAL_SECONDS` | `3600` | API housekeeping interval, 60-86400 seconds. |
| `ARTIFACT_RETENTION_MAX_TOTAL_BYTES` | `0` | Best-effort maximum managed bytes; `0` disables it. |
| `ARTIFACT_RETENTION_MAX_AGE_SECONDS` | `0` | Remove eligible referenced artifacts older than this; `0` disables it. |
| `ARTIFACT_RETENTION_MIN_AGE_SECONDS` | `86400` | Capacity eviction cannot remove newer artifacts. |
| `ARTIFACT_RETENTION_KEEP_RECENT_TERMINAL_JOBS` | `20` | Most recent terminal jobs protected from every policy. |
| `ARTIFACT_ORPHAN_GRACE_SECONDS` | `86400` | Minimum age for unreferenced files or stale missing-file metadata. |

The maximum age is an explicit retention deadline and is independent of the
capacity minimum-age floor. Recent-job protection still takes precedence.

## Preview and apply

Run from `backend/` with the same environment and database as the API:

```bash
python -m app.storage.cleanup
```

This command always performs a dry-run and prints deterministic JSON statistics,
including scanned bytes, protected files, planned reasons, projected bytes,
row/event counts, and errors.

To enable periodic dry-run scans first:

```dotenv
ARTIFACT_CLEANUP_ENABLED=true
ARTIFACT_CLEANUP_DRY_RUN=true
ARTIFACT_RETENTION_MAX_TOTAL_BYTES=53687091200
ARTIFACT_RETENTION_MAX_AGE_SECONDS=2592000
ARTIFACT_RETENTION_KEEP_RECENT_TERMINAL_JOBS=20
```

Review several cycles. To apply exactly the configured policy, set
`ARTIFACT_CLEANUP_DRY_RUN=false`, restart the API, or run an explicit pass:

```bash
python -m app.storage.cleanup --apply
```

`--apply` refuses to run unless `ARTIFACT_CLEANUP_ENABLED=true`.

## Suggested profiles

Ordinary development should retain the default disabled policy. Developers can
still run the manual dry-run while disabled.

A future desktop runtime should calculate its cap from the selected disk. The
current desktop prerequisite therefore requires at least 52 GiB free before
installation: roughly 8 GiB for the download, 24 GiB for the installed runtime,
and 20 GiB of immediate post-install reserve. For the current 80.5 GiB target
disk, a conservative first profile is 12 GiB (`12884901888` bytes), a
30-day maximum age, a one-day capacity floor and orphan grace, and 10 protected
recent terminal jobs. These are explicit installer recommendations, not silent
desktop defaults; the installer should recalculate and show the result whenever
the selected disk changes.

The packaged runtime separately caps persistent systemd journals at 512 MiB
and raw PX4 ULogs at 4 GiB/14 days. Those limits are documented with the WSL
runtime in [`runtime/README.md`](../runtime/README.md#local-storage-policy).

For multi-node production, use S3-compatible storage and lifecycle rules. Local
cleanup intentionally returns `unsupported_storage_backend` for S3 so it cannot
compete with bucket retention or delete objects outside the local host.
