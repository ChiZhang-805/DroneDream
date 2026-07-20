"""Serialization guard between artifact registration and retention cleanup."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models


class ArtifactRegistrationClosed(RuntimeError):
    """Raised after retention has closed a terminal job's artifact set."""


def _owner_job_id(db: Session, *, owner_type: str, owner_id: str) -> str:
    if owner_type == "job":
        return owner_id
    if owner_type == "trial":
        job_id = db.scalar(select(models.Trial.job_id).where(models.Trial.id == owner_id))
        if job_id is not None:
            return job_id
    raise ArtifactRegistrationClosed(
        f"Artifact owner does not resolve to a persisted job: {owner_type}/{owner_id}"
    )


def guard_artifact_registration(
    db: Session,
    *,
    owner_type: str,
    owner_id: str,
) -> models.Job:
    """Lock the owner Job and reject registration after retention starts.

    Report/trial writers call this before creating or replacing files. On
    databases with row-level locks, it serializes with cleanup's lock on the
    same Job. The durable cleanup event closes the artifact set after the lock
    is released, preventing a late writer from recreating a deleted reference.
    """

    job_id = _owner_job_id(db, owner_type=owner_type, owner_id=owner_id)
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores SELECT FOR UPDATE. A no-op write obtains its RESERVED
        # lock before the caller creates/replaces any file, serializing with
        # cleanup's BEGIN IMMEDIATE transaction without changing job data.
        db.execute(
            update(models.Job)
            .where(models.Job.id == job_id)
            .values(updated_at=models.Job.updated_at)
            .execution_options(synchronize_session=False)
        )
        job = db.scalar(select(models.Job).where(models.Job.id == job_id))
    else:
        job = db.scalar(
            select(models.Job).where(models.Job.id == job_id).with_for_update()
        )
    if job is None:
        raise ArtifactRegistrationClosed(f"Artifact job does not exist: {job_id}")
    cleanup_started = db.scalar(
        select(models.JobEvent.id)
        .where(models.JobEvent.job_id == job_id)
        .where(models.JobEvent.event_type == "artifact_retention_cleanup")
        .limit(1)
    )
    if cleanup_started is not None:
        raise ArtifactRegistrationClosed(
            f"Artifact retention has closed terminal job {job_id}"
        )
    return job


__all__ = ["ArtifactRegistrationClosed", "guard_artifact_registration"]
