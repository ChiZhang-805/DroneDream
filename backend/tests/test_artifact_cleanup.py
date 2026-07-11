from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.db import Base
from app.storage.cleanup import (
    ArtifactCleanupResult,
    cleanup_local_artifacts,
    platform_supports_safe_artifact_unlink,
)
from app.storage.registration import (
    ArtifactRegistrationClosed,
    guard_artifact_registration,
)


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _settings(root: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "artifact_storage_backend": "local",
        "artifact_root": str(root),
        "real_simulator_artifact_root": str(root),
        "artifact_cleanup_enabled": True,
        "artifact_cleanup_dry_run": False,
        "artifact_retention_max_total_bytes": 0,
        "artifact_retention_max_age_seconds": 0,
        "artifact_retention_min_age_seconds": 0,
        "artifact_retention_keep_recent_terminal_jobs": 0,
        "artifact_orphan_grace_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _test_safe_remover(item: Any, roots: list[Path]) -> None:
    current = item.path.stat(follow_symlinks=False)
    assert any(item.path.is_relative_to(root) for root in roots)
    assert int(current.st_dev) == item.device
    assert int(current.st_ino) == item.inode
    item.path.unlink()


def _cleanup(db: Session, **kwargs: Any) -> ArtifactCleanupResult:
    return cleanup_local_artifacts(db, safe_remover=_test_safe_remover, **kwargs)


def _job(
    job_id: str,
    *,
    status: str,
    timestamp: datetime,
) -> models.Job:
    terminal = status in {"COMPLETED", "FAILED", "CANCELLED"}
    return models.Job(
        id=job_id,
        track_type="circle",
        altitude_m=5.0,
        sensor_noise_level="low",
        objective_profile="stable",
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        completed_at=timestamp if status == "COMPLETED" else None,
        failed_at=timestamp if status == "FAILED" else None,
        cancelled_at=timestamp if status == "CANCELLED" else None,
        current_phase=None if terminal else "trial_execution",
    )


def _file(root: Path, job_id: str, name: str, size: int, timestamp: datetime) -> Path:
    path = root / "jobs" / job_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    epoch = timestamp.timestamp()
    os.utime(path, (epoch, epoch))
    return path.resolve()


def _artifact(
    artifact_id: str,
    *,
    job_id: str,
    path: Path,
    created_at: datetime,
) -> models.Artifact:
    return models.Artifact(
        id=artifact_id,
        owner_type="job",
        owner_id=job_id,
        artifact_type="telemetry_json",
        storage_path=str(path.resolve()),
        file_size_bytes=path.stat().st_size if path.exists() else None,
        created_at=created_at,
    )


def test_disabled_default_and_manual_dry_run_never_delete(tmp_path: Path, db: Session) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    root = tmp_path / "artifacts"
    orphan = _file(root, "deleted_job", "orphan.bin", 7, now - timedelta(days=2))
    unrelated = root / "do-not-manage.txt"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text("user data", encoding="utf-8")
    settings = _settings(root, artifact_cleanup_enabled=False, artifact_cleanup_dry_run=True)

    disabled = _cleanup(db, settings=settings, now=now)
    assert disabled.status == "disabled"
    assert disabled.scanned_files == 0

    preview = _cleanup(
        db, settings=settings, now=now, dry_run=True, force_scan=True
    )
    assert preview.status == "dry_run"
    assert preview.planned_files == 1
    assert preview.planned_bytes == 7
    assert preview.deleted_files == 0
    assert orphan.exists()
    assert unrelated.exists()


def test_age_cleanup_commits_rows_and_event_before_unlink_and_protects_jobs(
    tmp_path: Path, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    root = tmp_path / "artifacts"
    old_time = now - timedelta(days=10)
    recent_time = now - timedelta(hours=1)
    active = _job("job_active", status="RUNNING", timestamp=old_time)
    old_terminal = _job("job_old", status="COMPLETED", timestamp=old_time)
    recent_terminal = _job("job_recent", status="COMPLETED", timestamp=recent_time)
    db.add_all([active, old_terminal, recent_terminal])
    active_file = _file(root, active.id, "active.bin", 5, old_time)
    active_orphan = _file(root, active.id, "active-orphan.bin", 3, old_time)
    old_file = _file(root, old_terminal.id, "old.bin", 11, old_time)
    recent_file = _file(root, recent_terminal.id, "recent.bin", 13, old_time)
    db.add_all(
        [
            _artifact("art_active", job_id=active.id, path=active_file, created_at=old_time),
            _artifact(
                "art_old", job_id=old_terminal.id, path=old_file, created_at=old_time
            ),
            _artifact(
                "art_recent",
                job_id=recent_terminal.id,
                path=recent_file,
                created_at=old_time,
            ),
        ]
    )
    db.commit()

    original_unlink = Path.unlink

    def guarded_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.resolve() == old_file:
            assert db.get(models.Artifact, "art_old") is None
            event = db.scalar(
                select(models.JobEvent).where(
                    models.JobEvent.job_id == old_terminal.id,
                    models.JobEvent.event_type == "artifact_retention_cleanup",
                )
            )
            assert event is not None
        original_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    result = _cleanup(
        db,
        settings=_settings(
            root,
            artifact_retention_max_age_seconds=24 * 3600,
            artifact_retention_keep_recent_terminal_jobs=1,
        ),
        now=now,
    )

    assert result.status == "completed"
    assert result.deleted_artifact_rows == 1
    assert result.audit_events_created == 1
    assert not old_file.exists()
    assert db.get(models.Artifact, "art_old") is None
    assert active_file.exists() and active_orphan.exists()
    assert recent_file.exists()
    assert db.get(models.Artifact, "art_active") is not None
    assert db.get(models.Artifact, "art_recent") is not None
    assert result.protected_active_job_files >= 1
    assert result.protected_recent_job_files >= 1


def test_capacity_removes_oldest_eligible_terminal_jobs_deterministically(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    root = tmp_path / "artifacts"
    rows: list[models.Artifact] = []
    paths: list[Path] = []
    for index, (age_days, size) in enumerate(((30, 10), (20, 20), (10, 30)), start=1):
        timestamp = now - timedelta(days=age_days)
        job = _job(f"job_capacity_{index}", status="COMPLETED", timestamp=timestamp)
        path = _file(root, job.id, "payload.bin", size, timestamp)
        db.add(job)
        rows.append(
            _artifact(
                f"art_capacity_{index}",
                job_id=job.id,
                path=path,
                created_at=timestamp,
            )
        )
        paths.append(path)
    db.add_all(rows)
    db.commit()

    result = _cleanup(
        db,
        settings=_settings(root, artifact_retention_max_total_bytes=35),
        now=now,
    )

    assert result.bytes_before == 60
    assert result.planned_by_reason == {"max_total_bytes": 2}
    assert result.deleted_bytes == 30
    assert result.bytes_after == 30
    assert result.capacity_excess_bytes == 0
    assert not paths[0].exists() and not paths[1].exists()
    assert paths[2].exists()
    assert db.get(models.Artifact, "art_capacity_1") is None
    assert db.get(models.Artifact, "art_capacity_2") is None
    assert db.get(models.Artifact, "art_capacity_3") is not None


def test_shared_active_reference_blocks_capacity_eviction(tmp_path: Path, db: Session) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    active = _job("job_shared_active", status="RUNNING", timestamp=old_time)
    terminal = _job("job_shared_terminal", status="COMPLETED", timestamp=old_time)
    path = _file(root, active.id, "shared.bin", 100, old_time)
    db.add_all([active, terminal])
    db.add_all(
        [
            _artifact(
                "art_shared_active", job_id=active.id, path=path, created_at=old_time
            ),
            _artifact(
                "art_shared_terminal",
                job_id=terminal.id,
                path=path,
                created_at=old_time,
            ),
        ]
    )
    db.commit()

    result = _cleanup(
        db,
        settings=_settings(root, artifact_retention_max_total_bytes=1),
        now=now,
    )

    assert path.exists()
    assert result.deleted_files == 0
    assert result.deleted_artifact_rows == 0
    assert result.capacity_excess_bytes == 99
    assert db.get(models.Artifact, "art_shared_active") is not None
    assert db.get(models.Artifact, "art_shared_terminal") is not None


def test_unlink_failure_leaves_retryable_orphan_without_database_reference(
    tmp_path: Path, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_unlink_failure", status="COMPLETED", timestamp=old_time)
    path = _file(root, job.id, "payload.bin", 9, old_time)
    db.add(job)
    db.add(
        _artifact("art_unlink_failure", job_id=job.id, path=path, created_at=old_time)
    )
    db.commit()
    settings = _settings(root, artifact_retention_max_age_seconds=3600)

    original_unlink = Path.unlink
    with monkeypatch.context() as context:
        context.setattr(
            Path,
            "unlink",
            lambda _path, *args, **kwargs: (_ for _ in ()).throw(
                PermissionError("locked")
            ),
        )
        failed = _cleanup(db, settings=settings, now=now)

    assert failed.status == "completed_with_errors"
    assert failed.deleted_artifact_rows == 1
    assert failed.deleted_files == 0
    assert db.get(models.Artifact, "art_unlink_failure") is None
    assert path.exists()

    # The next pass sees a managed orphan and can finish physical cleanup.
    monkeypatch.setattr(Path, "unlink", original_unlink)
    retried = _cleanup(db, settings=settings, now=now)
    assert retried.planned_by_reason == {"orphan": 1}
    assert retried.deleted_files == 1
    assert not path.exists()


def test_terminal_missing_file_metadata_is_removed_but_active_metadata_is_kept(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=2)
    root = tmp_path / "artifacts"
    terminal = _job("job_missing_terminal", status="FAILED", timestamp=old_time)
    active = _job("job_missing_active", status="RUNNING", timestamp=old_time)
    terminal_path = root / "jobs" / terminal.id / "missing.bin"
    active_path = root / "jobs" / active.id / "missing.bin"
    db.add_all([terminal, active])
    db.add_all(
        [
            models.Artifact(
                id="art_missing_terminal",
                owner_type="job",
                owner_id=terminal.id,
                artifact_type="worker_log",
                storage_path=str(terminal_path.resolve()),
                created_at=old_time,
            ),
            models.Artifact(
                id="art_missing_active",
                owner_type="job",
                owner_id=active.id,
                artifact_type="worker_log",
                storage_path=str(active_path.resolve()),
                created_at=old_time,
            ),
        ]
    )
    db.commit()

    result = _cleanup(
        db,
        settings=_settings(root, artifact_orphan_grace_seconds=3600),
        now=now,
    )

    assert result.missing_referenced_files == 1
    assert result.deleted_artifact_rows == 1
    assert result.deleted_files == 0
    assert db.get(models.Artifact, "art_missing_terminal") is None
    assert db.get(models.Artifact, "art_missing_active") is not None


def test_trial_owned_artifact_resolves_terminal_job_and_audits_that_job(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_trial_owner", status="COMPLETED", timestamp=old_time)
    candidate = models.CandidateParameterSet(
        id="candidate_trial_owner",
        job_id=job.id,
        generation_index=0,
        source_type="baseline",
        parameter_json={},
    )
    trial = models.Trial(
        id="trial_owner",
        job_id=job.id,
        candidate_id=candidate.id,
        seed=1,
        scenario_type="nominal",
        status="COMPLETED",
    )
    path = _file(root, job.id, "trials/trial_owner/telemetry.json", 17, old_time)
    artifact = models.Artifact(
        id="art_trial_owner",
        owner_type="trial",
        owner_id=trial.id,
        artifact_type="telemetry_json",
        storage_path=str(path),
        file_size_bytes=17,
        created_at=old_time,
    )
    db.add_all([job, candidate, trial, artifact])
    db.commit()

    result = _cleanup(
        db,
        settings=_settings(root, artifact_retention_max_age_seconds=3600),
        now=now,
    )

    assert result.deleted_artifact_rows == 1
    assert not path.exists()
    assert db.get(models.Artifact, artifact.id) is None
    event = db.scalar(
        select(models.JobEvent).where(
            models.JobEvent.job_id == job.id,
            models.JobEvent.event_type == "artifact_retention_cleanup",
        )
    )
    assert event is not None
    assert event.payload_json is not None
    assert event.payload_json["artifact_ids"] == [artifact.id]


def test_dry_run_does_not_change_referenced_rows_files_or_events(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_dry_run", status="COMPLETED", timestamp=old_time)
    path = _file(root, job.id, "payload.bin", 19, old_time)
    artifact = _artifact("art_dry_run", job_id=job.id, path=path, created_at=old_time)
    db.add_all([job, artifact])
    db.commit()

    result = _cleanup(
        db,
        settings=_settings(root, artifact_retention_max_age_seconds=3600),
        now=now,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.planned_files == 1
    assert result.planned_artifact_rows == 1
    assert result.deleted_files == 0
    assert result.deleted_artifact_rows == 0
    assert path.exists()
    assert db.get(models.Artifact, artifact.id) is not None
    assert db.scalar(select(models.JobEvent).where(models.JobEvent.job_id == job.id)) is None


def test_symlink_and_traversal_style_reference_never_escape_managed_root(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_path_safety", status="COMPLETED", timestamp=old_time)
    managed = _file(root, job.id, "guarded.bin", 23, old_time)
    traversal_text = str(managed.parent / "unused" / ".." / managed.name)
    outside = tmp_path / "outside-user-file.bin"
    outside.write_bytes(b"never delete")
    db.add(job)
    db.add(
        models.Artifact(
            id="art_traversal_text",
            owner_type="job",
            owner_id=job.id,
            artifact_type="worker_log",
            storage_path=traversal_text,
            created_at=old_time,
        )
    )
    db.commit()

    link = root / "jobs" / job.id / "outside-link.bin"
    symlink_created = False
    try:
        link.symlink_to(outside)
        symlink_created = True
    except OSError:
        # Windows hosts without Developer Mode may reject unprivileged
        # symlinks. The traversal-form reference still exercises the same
        # cleanup fence on every platform.
        pass

    result = _cleanup(
        db,
        settings=_settings(root, artifact_retention_max_age_seconds=3600),
        now=now,
    )

    assert result.skipped_unsafe_references == 1
    assert managed.exists()
    assert outside.read_bytes() == b"never delete"
    assert db.get(models.Artifact, "art_traversal_text") is not None
    if symlink_created:
        assert link.is_symlink()


def test_new_reference_committed_just_before_unlink_is_rechecked_and_protected(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_late_reference", status="COMPLETED", timestamp=old_time)
    path = _file(root, job.id, "late.bin", 29, old_time)
    db.add(job)
    db.commit()
    inserted = False

    def register_late_reference(candidate: Path) -> None:
        nonlocal inserted
        if inserted or candidate != path:
            return
        inserted = True
        # Deliberately bypass the production guard to simulate a stale/rogue
        # writer that committed after the cleanup plan and audit transaction.
        db.add(
            models.Artifact(
                id="art_late_reference",
                owner_type="job",
                owner_id=job.id,
                artifact_type="worker_log",
                storage_path=str(path),
                created_at=now,
            )
        )
        db.commit()

    result = cleanup_local_artifacts(
        db,
        settings=_settings(root),
        now=now,
        safe_remover=_test_safe_remover,
        before_unlink_check=register_late_reference,
    )

    assert inserted is True
    assert result.skipped_new_references == 1
    assert result.deleted_files == 0
    assert path.exists()
    assert db.get(models.Artifact, "art_late_reference") is not None
    with pytest.raises(ArtifactRegistrationClosed):
        guard_artifact_registration(db, owner_type="job", owner_id=job.id)
    db.rollback()


def test_parent_directory_symlink_replacement_cannot_redirect_unlink(
    tmp_path: Path, db: Session
) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    old_time = now - timedelta(days=10)
    root = tmp_path / "artifacts"
    job = _job("job_parent_swap", status="COMPLETED", timestamp=old_time)
    path = _file(root, job.id, "nested/payload.bin", 31, old_time)
    db.add(job)
    db.commit()
    settings = _settings(root)

    if not platform_supports_safe_artifact_unlink():
        result = cleanup_local_artifacts(db, settings=settings, now=now)
        assert result.status == "safe_unlink_unsupported"
        assert result.deleted_files == 0
        assert path.exists()
        return

    original_parent = path.parent
    moved_parent = original_parent.with_name("nested-before-swap")
    outside_parent = tmp_path / "outside-parent"
    outside_parent.mkdir()
    outside_payload = outside_parent / path.name
    outside_payload.write_bytes(b"outside must survive")
    swapped = False

    def replace_parent(candidate: Path) -> None:
        nonlocal swapped
        if swapped or candidate != path:
            return
        swapped = True
        original_parent.rename(moved_parent)
        original_parent.symlink_to(outside_parent, target_is_directory=True)

    result = cleanup_local_artifacts(
        db,
        settings=settings,
        now=now,
        before_unlink_check=replace_parent,
    )

    assert swapped is True
    assert result.deleted_files == 0
    assert result.status == "completed_with_errors"
    assert outside_payload.read_bytes() == b"outside must survive"
    assert (moved_parent / path.name).exists()


def test_sqlite_registration_guard_holds_reserved_writer_lock(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'registration-lock.db'}",
        connect_args={"timeout": 0.05},
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    with Session(engine) as setup:
        setup.add(_job("job_registration_lock", status="COMPLETED", timestamp=now))
        setup.commit()

    with Session(engine) as writer, Session(engine) as cleanup:
        guard_artifact_registration(
            writer, owner_type="job", owner_id="job_registration_lock"
        )
        with pytest.raises(OperationalError):
            cleanup.execute(text("BEGIN IMMEDIATE"))
        cleanup.rollback()
        writer.rollback()

        # Releasing the registration transaction makes the cleanup lock
        # immediately acquirable again.
        cleanup.execute(text("BEGIN IMMEDIATE"))
        cleanup.rollback()
    engine.dispose()
