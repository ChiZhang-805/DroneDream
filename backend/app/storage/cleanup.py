"""Conservative lifecycle management for locally stored artifacts.

The cleanup order is intentionally asymmetric:

1. scan only ``<configured artifact root>/jobs`` without following symlinks;
2. protect every active job and the configured number of recent terminal jobs;
3. for referenced files selected by age/capacity, delete Artifact rows and
   commit an audit JobEvent *before* unlinking any file;
4. re-check references, then unlink files. A failed unlink is therefore a
   harmless orphan that a later pass can retry, never a dangling API row.

S3-compatible storage is outside this module; operators should use bucket
lifecycle policies for that backend.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class _ManagedFile:
    path: Path
    size_bytes: int
    modified_at: datetime
    device: int
    inode: int


SafeArtifactRemover = Callable[[_ManagedFile, list[Path]], None]


class SafeArtifactRemovalUnsupported(RuntimeError):
    """Raised when this platform cannot provide no-follow unlink semantics."""


@dataclass(slots=True)
class ArtifactCleanupResult:
    """Serializable scan, plan, and deletion statistics."""

    status: str
    enabled: bool
    dry_run: bool
    storage_backend: str
    managed_roots: list[str]
    max_total_bytes: int
    max_age_seconds: int
    min_age_seconds: int
    orphan_grace_seconds: int
    keep_recent_terminal_jobs: int
    scanned_files: int = 0
    bytes_before: int = 0
    referenced_files: int = 0
    orphan_files: int = 0
    protected_active_job_files: int = 0
    protected_recent_job_files: int = 0
    skipped_recent_orphans: int = 0
    skipped_unsafe_references: int = 0
    missing_referenced_files: int = 0
    planned_files: int = 0
    planned_bytes: int = 0
    planned_artifact_rows: int = 0
    planned_by_reason: dict[str, int] = field(default_factory=dict)
    projected_bytes_after: int = 0
    capacity_excess_bytes: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0
    deleted_artifact_rows: int = 0
    audit_events_created: int = 0
    skipped_new_references: int = 0
    bytes_after: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_under(path: Path, roots: list[Path]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _managed_files(roots: list[Path]) -> tuple[list[_ManagedFile], list[str]]:
    files: list[_ManagedFile] = []
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        if not root.is_dir() or root.is_symlink():
            errors.append(f"managed root is not a regular directory: {root}")
            continue
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            directory_names[:] = sorted(
                name for name in directory_names if not (directory_path / name).is_symlink()
            )
            for name in sorted(file_names):
                candidate = directory_path / name
                try:
                    if candidate.is_symlink():
                        continue
                    file_stat = candidate.stat(follow_symlinks=False)
                    if not stat.S_ISREG(file_stat.st_mode):
                        continue
                    resolved = candidate.resolve()
                    if not resolved.is_relative_to(root):
                        errors.append(f"file escaped managed root: {candidate}")
                        continue
                    files.append(
                        _ManagedFile(
                            path=resolved,
                            size_bytes=int(file_stat.st_size),
                            modified_at=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                            device=int(file_stat.st_dev),
                            inode=int(file_stat.st_ino),
                        )
                    )
                except OSError as exc:
                    errors.append(f"failed to inspect {candidate}: {exc}")
    files.sort(key=lambda item: str(item.path))
    return files, errors


def platform_supports_safe_artifact_unlink() -> bool:
    """Return whether no-follow, dir-fd-relative unlink is available."""

    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.unlink in os.supports_dir_fd
    )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_NOFOLLOW", 0))
        | int(getattr(os, "O_CLOEXEC", 0))
    )


def _open_absolute_directory_no_follow(path: Path) -> int:
    if not path.is_absolute():
        raise SafeArtifactRemovalUnsupported("managed root must be absolute")
    anchor = Path(path.anchor)
    flags = _directory_open_flags()
    descriptor = os.open(str(anchor), flags)
    try:
        for component in path.relative_to(anchor).parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _unlink_managed_file_posix(item: _ManagedFile, roots: list[Path]) -> None:
    """Unlink by directory descriptor without following replaced parents."""

    if not platform_supports_safe_artifact_unlink():
        raise SafeArtifactRemovalUnsupported(
            "platform lacks O_DIRECTORY/O_NOFOLLOW dir-fd unlink support"
        )
    containing_roots = [root for root in roots if item.path.is_relative_to(root)]
    if not containing_roots:
        raise ValueError("file is outside managed artifact roots")
    root = max(containing_roots, key=lambda candidate: len(candidate.parts))
    relative = item.path.relative_to(root)
    if not relative.parts:
        raise ValueError("refusing to unlink a managed root")

    directory_fd = _open_absolute_directory_no_follow(root)
    try:
        flags = _directory_open_flags()
        for component in relative.parts[:-1]:
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        leaf = relative.parts[-1]
        current = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode):
            raise ValueError("artifact leaf is no longer a regular file")
        if int(current.st_dev) != item.device or int(current.st_ino) != item.inode:
            raise ValueError("artifact identity changed after cleanup scan")
        os.unlink(leaf, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def _job_terminal_at(job: models.Job) -> datetime:
    for value in (
        job.completed_at,
        job.failed_at,
        job.cancelled_at,
        job.updated_at,
        job.created_at,
    ):
        if value is not None:
            return _as_utc(value)
    return datetime.min.replace(tzinfo=timezone.utc)


def _job_id_for_owner(
    artifact: models.Artifact,
    trial_to_job: dict[str, str],
) -> str | None:
    if artifact.owner_type == "job":
        return artifact.owner_id
    if artifact.owner_type == "trial":
        return trial_to_job.get(artifact.owner_id)
    return None


def _job_id_for_file(path: Path, roots: list[Path]) -> str | None:
    for root in roots:
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root)
        return relative.parts[0] if relative.parts else None
    return None


def _resolved_local_path(storage_path: str) -> Path | None:
    if storage_path.startswith(("mock://", "s3://")):
        return None
    try:
        return Path(storage_path).resolve()
    except (OSError, RuntimeError):
        return None


def cleanup_local_artifacts(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    dry_run: bool | None = None,
    force_scan: bool = False,
    safe_remover: SafeArtifactRemover | None = None,
    before_unlink_check: Callable[[Path], None] | None = None,
) -> ArtifactCleanupResult:
    """Scan and optionally enforce local artifact retention.

    ``force_scan`` exists for the manual dry-run command. It never authorizes
    deletion while ``ARTIFACT_CLEANUP_ENABLED`` is false. Callers that apply
    changes must use a dedicated Session because referenced-row removal is
    committed before physical deletion by design.
    """

    config = settings or get_settings()
    effective_dry_run = config.artifact_cleanup_dry_run if dry_run is None else dry_run
    roots = config.managed_artifact_roots
    result = ArtifactCleanupResult(
        status="disabled",
        enabled=config.artifact_cleanup_enabled,
        dry_run=effective_dry_run,
        storage_backend=config.artifact_storage_backend,
        managed_roots=[str(root) for root in roots],
        max_total_bytes=config.artifact_retention_max_total_bytes,
        max_age_seconds=config.artifact_retention_max_age_seconds,
        min_age_seconds=config.artifact_retention_min_age_seconds,
        orphan_grace_seconds=config.artifact_orphan_grace_seconds,
        keep_recent_terminal_jobs=config.artifact_retention_keep_recent_terminal_jobs,
    )
    if config.artifact_storage_backend != "local":
        result.status = "unsupported_storage_backend"
        return result
    if not config.artifact_cleanup_enabled and not force_scan:
        return result
    if not config.artifact_cleanup_enabled and not effective_dry_run:
        result.status = "disabled_apply_refused"
        return result

    current_time = _as_utc(now or datetime.now(timezone.utc))
    files, scan_errors = _managed_files(roots)
    result.errors.extend(scan_errors)
    result.scanned_files = len(files)
    result.bytes_before = sum(item.size_bytes for item in files)
    files_by_path = {item.path: item for item in files}

    jobs = list(db.scalars(select(models.Job)))
    jobs_by_id = {job.id: job for job in jobs}
    terminal_job_ids = {job.id for job in jobs if job.status in schemas.JOB_TERMINAL_STATUSES}
    active_job_ids = set(jobs_by_id) - terminal_job_ids
    recent_terminal_job_ids = {
        job.id
        for job in sorted(
            (job for job in jobs if job.id in terminal_job_ids),
            key=lambda job: (_job_terminal_at(job), job.id),
            reverse=True,
        )[: config.artifact_retention_keep_recent_terminal_jobs]
    }
    trial_to_job: dict[str, str] = {
        trial_id: job_id
        for trial_id, job_id in db.execute(select(models.Trial.id, models.Trial.job_id)).all()
    }
    artifact_rows = list(db.scalars(select(models.Artifact)))

    references_by_path: dict[Path, list[models.Artifact]] = {}
    protected_reference_paths: set[Path] = set()
    for artifact in artifact_rows:
        resolved = _resolved_local_path(artifact.storage_path)
        if resolved is None or not _is_under(resolved, roots):
            continue
        # Even a malformed textual path protects its resolved target from
        # orphan deletion. It is never eligible for automatic row/file removal.
        if ".." in Path(artifact.storage_path).parts:
            protected_reference_paths.add(resolved)
            result.skipped_unsafe_references += 1
            continue
        references_by_path.setdefault(resolved, []).append(artifact)

    result.referenced_files = sum(
        1
        for path in files_by_path
        if path in references_by_path or path in protected_reference_paths
    )
    orphan_paths = {
        path
        for path in files_by_path
        if path not in references_by_path and path not in protected_reference_paths
    }
    result.orphan_files = len(orphan_paths)
    for path in files_by_path:
        job_id = _job_id_for_file(path, roots)
        if job_id in active_job_ids:
            result.protected_active_job_files += 1
        elif job_id in recent_terminal_job_ids:
            result.protected_recent_job_files += 1

    selected_paths: dict[Path, str] = {}
    selected_reference_rows: dict[Path, list[models.Artifact]] = {}
    orphan_cutoff = current_time - timedelta(seconds=config.artifact_orphan_grace_seconds)
    minimum_age_cutoff = current_time - timedelta(seconds=config.artifact_retention_min_age_seconds)
    maximum_age_cutoff = current_time - timedelta(seconds=config.artifact_retention_max_age_seconds)

    for path in sorted(orphan_paths, key=str):
        item = files_by_path[path]
        job_id = _job_id_for_file(path, roots)
        if job_id in active_job_ids:
            continue
        if job_id in recent_terminal_job_ids:
            continue
        if item.modified_at > orphan_cutoff:
            result.skipped_recent_orphans += 1
            continue
        selected_paths[path] = "orphan"

    def references_are_expirable(rows: list[models.Artifact]) -> bool:
        for artifact in rows:
            job_id = _job_id_for_owner(artifact, trial_to_job)
            if job_id is None or job_id not in terminal_job_ids:
                return False
            if job_id in recent_terminal_job_ids:
                return False
        return True

    def newest_reference_time(path: Path, rows: list[models.Artifact]) -> datetime:
        timestamps = [_as_utc(artifact.created_at) for artifact in rows]
        managed_file = files_by_path.get(path)
        if managed_file is not None:
            timestamps.append(managed_file.modified_at)
        return max(timestamps)

    # Remove stale metadata for already-missing files only after the same
    # terminal-owner and grace protections used for physical orphans.
    for path, rows in sorted(references_by_path.items(), key=lambda item: str(item[0])):
        if path in files_by_path or not references_are_expirable(rows):
            continue
        result.missing_referenced_files += 1
        if newest_reference_time(path, rows) <= orphan_cutoff:
            selected_reference_rows[path] = rows

    if config.artifact_retention_max_age_seconds > 0:
        for path, rows in sorted(references_by_path.items(), key=lambda item: str(item[0])):
            if path not in files_by_path or not references_are_expirable(rows):
                continue
            if newest_reference_time(path, rows) <= maximum_age_cutoff:
                selected_paths[path] = "max_age"
                selected_reference_rows[path] = rows

    projected_bytes = result.bytes_before - sum(
        files_by_path[path].size_bytes for path in selected_paths
    )
    max_total = config.artifact_retention_max_total_bytes
    if max_total > 0 and projected_bytes > max_total:
        capacity_candidates: list[tuple[datetime, str, Path, list[models.Artifact]]] = []
        for path, rows in references_by_path.items():
            if path in selected_paths or path not in files_by_path:
                continue
            if not references_are_expirable(rows):
                continue
            newest = newest_reference_time(path, rows)
            if newest > minimum_age_cutoff:
                continue
            capacity_candidates.append((newest, str(path), path, rows))
        capacity_candidates.sort(key=lambda item: (item[0], item[1]))
        for _created_at, _path_text, path, rows in capacity_candidates:
            if projected_bytes <= max_total:
                break
            selected_paths[path] = "max_total_bytes"
            selected_reference_rows[path] = rows
            projected_bytes -= files_by_path[path].size_bytes

    selected_existing_paths = set(selected_paths)
    selected_row_objects = {
        artifact.id: artifact for rows in selected_reference_rows.values() for artifact in rows
    }
    result.planned_files = len(selected_existing_paths)
    result.planned_bytes = sum(files_by_path[path].size_bytes for path in selected_existing_paths)
    result.planned_artifact_rows = len(selected_row_objects)
    for reason in selected_paths.values():
        result.planned_by_reason[reason] = result.planned_by_reason.get(reason, 0) + 1
    missing_path_count = sum(1 for path in selected_reference_rows if path not in files_by_path)
    if missing_path_count:
        result.planned_by_reason["missing_file_metadata"] = missing_path_count
    result.projected_bytes_after = max(0, result.bytes_before - result.planned_bytes)
    result.capacity_excess_bytes = (
        max(0, result.projected_bytes_after - max_total) if max_total > 0 else 0
    )

    if effective_dry_run:
        result.status = "dry_run"
        result.bytes_after = result.bytes_before
        return result

    effective_remover = safe_remover
    if effective_remover is None:
        if not platform_supports_safe_artifact_unlink():
            result.status = "safe_unlink_unsupported"
            result.bytes_after = result.bytes_before
            result.errors.append(
                "non-dry-run cleanup requires POSIX dir-fd O_NOFOLLOW unlink support"
            )
            return result
        effective_remover = _unlink_managed_file_posix

    # Reference rows and their audit events become durable before any unlink.
    # If commit fails, no file operation is attempted.
    audit_rows_by_job: dict[str, list[models.Artifact]] = {}
    audit_reasons_by_job: dict[str, set[str]] = {}
    audit_file_count_by_job: dict[str, int] = {}
    for artifact in selected_row_objects.values():
        job_id = _job_id_for_owner(artifact, trial_to_job)
        if job_id is None or job_id not in terminal_job_ids:
            raise RuntimeError("artifact cleanup plan contains an unowned or non-terminal artifact")
        audit_rows_by_job.setdefault(job_id, []).append(artifact)
    for path, rows in selected_reference_rows.items():
        reason = selected_paths.get(path, "missing_file_metadata")
        for artifact in rows:
            job_id = _job_id_for_owner(artifact, trial_to_job)
            if job_id is None or job_id not in terminal_job_ids:
                raise RuntimeError(
                    "artifact cleanup audit references an unowned or non-terminal artifact"
                )
            audit_reasons_by_job.setdefault(job_id, set()).add(reason)
    for path, reason in selected_paths.items():
        job_id = _job_id_for_file(path, roots)
        if job_id in terminal_job_ids:
            audit_reasons_by_job.setdefault(job_id, set()).add(reason)
            audit_file_count_by_job[job_id] = audit_file_count_by_job.get(job_id, 0) + 1

    audit_job_ids = sorted(audit_reasons_by_job)
    if audit_job_ids:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(
                update(models.Job)
                .where(models.Job.id.in_(audit_job_ids))
                .values(updated_at=models.Job.updated_at)
                .execution_options(synchronize_session=False)
            )
            locked_jobs = list(
                db.scalars(select(models.Job).where(models.Job.id.in_(audit_job_ids)))
            )
        else:
            locked_jobs = list(
                db.scalars(
                    select(models.Job).where(models.Job.id.in_(audit_job_ids)).with_for_update()
                )
            )
        locked_by_id = {job.id: job for job in locked_jobs}
        if any(
            job_id not in locked_by_id
            or locked_by_id[job_id].status not in schemas.JOB_TERMINAL_STATUSES
            for job_id in audit_job_ids
        ):
            db.rollback()
            raise RuntimeError("artifact cleanup owner changed from terminal state")

    # Do not mark rows for deletion until owner locks and terminal-state checks
    # are established; otherwise an autoflush from the locking query could
    # expose deletion before serialization.
    for artifact in selected_row_objects.values():
        db.delete(artifact)

    for job_id in audit_job_ids:
        rows = audit_rows_by_job.get(job_id, [])
        db.add(
            models.JobEvent(
                job_id=job_id,
                event_type="artifact_retention_cleanup",
                payload_json={
                    "artifact_count": len(rows),
                    "artifact_ids": sorted(row.id for row in rows),
                    "file_count": audit_file_count_by_job.get(job_id, 0),
                    "reasons": sorted(audit_reasons_by_job[job_id]),
                },
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    result.deleted_artifact_rows = len(selected_row_objects)
    result.audit_events_created = len(audit_job_ids)

    for path in sorted(selected_existing_paths, key=str):
        try:
            if before_unlink_check is not None:
                before_unlink_check(path)
            # Serialize local SQLite writers and lock the owning Job on
            # row-locking databases. Internal artifact registration takes the
            # same Job lock and refuses registration after the durable cleanup
            # event committed above.
            db.commit()
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            job_id = _job_id_for_file(path, roots)
            if job_id is not None:
                owner_job = db.scalar(
                    select(models.Job).where(models.Job.id == job_id).with_for_update()
                )
                if owner_job is not None and owner_job.status not in schemas.JOB_TERMINAL_STATUSES:
                    result.protected_active_job_files += 1
                    db.commit()
                    continue

            # This is deliberately the final operation before safe unlink.
            # Resolve every stored spelling so aliases cannot evade the check.
            has_reference = False
            for storage_path in db.scalars(select(models.Artifact.storage_path)):
                if _resolved_local_path(storage_path) == path:
                    has_reference = True
                    break
            if has_reference:
                result.skipped_new_references += 1
                db.commit()
                continue
            size = files_by_path[path].size_bytes
            effective_remover(files_by_path[path], roots)
            result.deleted_files += 1
            result.deleted_bytes += size
            db.commit()
        except FileNotFoundError:
            db.rollback()
        except (OSError, RuntimeError, ValueError) as exc:
            db.rollback()
            result.errors.append(f"failed to delete {path}: {exc}")

    result.bytes_after = max(0, result.bytes_before - result.deleted_bytes)
    result.capacity_excess_bytes = max(0, result.bytes_after - max_total) if max_total > 0 else 0
    result.status = "completed_with_errors" if result.errors else "completed"
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or apply DroneDream local artifact retention."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply the configured policy. Requires ARTIFACT_CLEANUP_ENABLED=true; "
            "without this flag the command is always a dry-run."
        ),
    )
    args = parser.parse_args()
    settings = get_settings()
    if args.apply and not settings.artifact_cleanup_enabled:
        parser.error("--apply requires ARTIFACT_CLEANUP_ENABLED=true")

    from app.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        result = cleanup_local_artifacts(
            db,
            settings=settings,
            dry_run=not args.apply,
            force_scan=True,
        )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.errors else 0


if __name__ == "__main__":  # pragma: no cover - exercised by operator CLI
    raise SystemExit(_main())


__all__ = ["ArtifactCleanupResult", "cleanup_local_artifacts"]
