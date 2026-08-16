"""Canonical Trial artifact projections for Candidate evidence.

Real stored artifacts are admitted only when their immutable digest receipt
matches both the current metadata and, at compilation time, the bytes currently
held by the configured storage backend.  The synthetic mock backend is explicit:
its historical ``mock://`` rows never represented downloadable bytes, so those
rows are bound as metadata-only evidence instead of being mislabeled as sealed
content.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app import models
from app.storage.factory import get_artifact_storage
from app.storage.integrity import (
    ArtifactIntegrityError,
    require_artifact_integrity,
)

TRIAL_ARTIFACT_EVIDENCE_SCHEMA = "dronedream.trial-artifact-evidence/v1"
SEALED_ARTIFACT_EVIDENCE = "sealed-bytes"
MOCK_METADATA_ARTIFACT_EVIDENCE = "mock-metadata-only"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def candidate_trial_artifact_evidence(
    candidate: object,
    trials: Sequence[object],
    *,
    verify_bytes: bool,
) -> dict[str, dict[str, Any]] | None:
    """Return one deterministic artifact projection for every supplied Trial.

    ``None`` means the ORM state cannot be inspected and callers must fail
    closed when artifact-bound evidence is required.  Integrity divergence is
    intentionally raised: aggregation must never silently downgrade a real
    stored artifact to metadata-only evidence.
    """

    session = object_session(candidate)
    if session is None:
        return None
    trial_ids: list[str] = []
    for trial in trials:
        trial_id = getattr(trial, "id", None)
        candidate_id = getattr(trial, "candidate_id", None)
        if (
            not isinstance(trial_id, str)
            or not trial_id
            or candidate_id != getattr(candidate, "id", None)
        ):
            raise ArtifactIntegrityError(
                "artifact evidence requires Trials owned by the Candidate"
            )
        trial_ids.append(trial_id)
    if len(trial_ids) != len(set(trial_ids)):
        raise ArtifactIntegrityError(
            "artifact evidence received duplicate Trial identities"
        )

    artifact_rows = (
        list(
            session.scalars(
                select(models.Artifact)
                .where(models.Artifact.owner_type == "trial")
                .where(models.Artifact.owner_id.in_(trial_ids))
                .order_by(
                    models.Artifact.owner_id.asc(),
                    models.Artifact.artifact_type.asc(),
                    models.Artifact.id.asc(),
                )
            ).all()
        )
        if trial_ids
        else []
    )
    artifacts_by_trial: dict[str, list[dict[str, Any]]] = {
        trial_id: [] for trial_id in trial_ids
    }
    storage = get_artifact_storage() if verify_bytes else None
    for artifact in artifact_rows:
        if artifact.owner_id not in artifacts_by_trial:
            raise ArtifactIntegrityError(
                "artifact query returned a row outside the Candidate Trial set"
            )
        receipt = require_artifact_integrity(artifact)
        if receipt is None:
            if not artifact.storage_path.startswith("mock://"):
                raise ArtifactIntegrityError(
                    "real Trial artifact is missing a sealed byte receipt"
                )
            item: dict[str, Any] = {
                "artifact_id": artifact.id,
                "owner_type": "trial",
                "owner_id": artifact.owner_id,
                "artifact_type": artifact.artifact_type,
                "mime_type": artifact.mime_type,
                "content_evidence": MOCK_METADATA_ARTIFACT_EVIDENCE,
                "receipt_id": None,
                "receipt_evidence_id": None,
                "content_sha256": None,
                "content_size_bytes": None,
                "storage_path_sha256": _sha256_text(
                    artifact.storage_path
                ),
            }
        else:
            if storage is not None:
                require_artifact_integrity(
                    artifact,
                    content_digest=storage.content_digest(
                        artifact.storage_path
                    ),
                )
            item = {
                "artifact_id": artifact.id,
                "owner_type": "trial",
                "owner_id": artifact.owner_id,
                "artifact_type": artifact.artifact_type,
                "mime_type": artifact.mime_type,
                "content_evidence": SEALED_ARTIFACT_EVIDENCE,
                "receipt_id": receipt.id,
                "receipt_evidence_id": receipt.evidence_id,
                "content_sha256": receipt.content_sha256,
                "content_size_bytes": receipt.content_size_bytes,
                "storage_path_sha256": receipt.storage_path_sha256,
            }
        artifacts_by_trial[artifact.owner_id].append(item)

    result: dict[str, dict[str, Any]] = {}
    for trial_id in trial_ids:
        items = artifacts_by_trial[trial_id]
        sealed_count = sum(
            item["content_evidence"] == SEALED_ARTIFACT_EVIDENCE
            for item in items
        )
        metadata_only_count = len(items) - sealed_count
        result[trial_id] = {
            "schema_id": TRIAL_ARTIFACT_EVIDENCE_SCHEMA,
            "trial_id": trial_id,
            "artifact_count": len(items),
            "sealed_artifact_count": sealed_count,
            "metadata_only_artifact_count": metadata_only_count,
            "artifacts": items,
        }
    return result


__all__ = [
    "MOCK_METADATA_ARTIFACT_EVIDENCE",
    "SEALED_ARTIFACT_EVIDENCE",
    "TRIAL_ARTIFACT_EVIDENCE_SCHEMA",
    "candidate_trial_artifact_evidence",
]
