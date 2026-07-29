"""Content-addressed, insert-once integrity receipts for stored artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

ARTIFACT_INTEGRITY_POLICY = "sha256-v1"
ARTIFACT_DIGEST_RECEIPT_SCHEMA = "dronedream.artifact-digest-receipt/v1"


class ArtifactIntegrityError(ValueError):
    """Raised when artifact bytes or immutable receipt bindings diverge."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def artifact_content_digest(content: bytes | Path) -> tuple[str, int]:
    """Return the SHA-256 hex digest and exact byte size of artifact content."""

    digest = hashlib.sha256()
    size = 0
    if isinstance(content, bytes):
        digest.update(content)
        return digest.hexdigest(), len(content)
    with content.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _receipt_payload(
    *,
    artifact: models.Artifact,
    content_sha256: str,
    content_size_bytes: int,
) -> dict[str, object]:
    return {
        "schema_id": ARTIFACT_DIGEST_RECEIPT_SCHEMA,
        "integrity_policy": ARTIFACT_INTEGRITY_POLICY,
        "artifact_id": artifact.id,
        "owner_type": artifact.owner_type,
        "owner_id": artifact.owner_id,
        "artifact_type": artifact.artifact_type,
        "storage_path_sha256": _sha256_text(artifact.storage_path),
        "content_sha256": content_sha256,
        "content_size_bytes": content_size_bytes,
    }


def _evidence_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def require_artifact_integrity(
    artifact: models.Artifact,
    *,
    content: bytes | Path | None = None,
    content_digest: tuple[str, int] | None = None,
) -> models.ArtifactDigestReceipt | None:
    """Verify receipt identity and optionally the currently stored bytes."""

    if content is not None and content_digest is not None:
        raise ArtifactIntegrityError("artifact integrity accepts bytes or a digest, not both")
    receipt = artifact.digest_receipt
    if receipt is None:
        if artifact.integrity_policy is not None:
            raise ArtifactIntegrityError("artifact requires a missing digest receipt")
        return None
    if artifact.integrity_policy != ARTIFACT_INTEGRITY_POLICY:
        raise ArtifactIntegrityError("artifact integrity policy does not match its receipt")
    payload = _receipt_payload(
        artifact=artifact,
        content_sha256=receipt.content_sha256,
        content_size_bytes=receipt.content_size_bytes,
    )
    if (
        receipt.artifact_id != artifact.id
        or receipt.owner_type != artifact.owner_type
        or receipt.owner_id != artifact.owner_id
        or receipt.artifact_type != artifact.artifact_type
        or receipt.storage_path_sha256 != payload["storage_path_sha256"]
        or receipt.evidence_id != _evidence_id(payload)
        or artifact.file_size_bytes != receipt.content_size_bytes
    ):
        raise ArtifactIntegrityError("artifact digest receipt no longer matches metadata")
    if content is not None or content_digest is not None:
        if content is not None:
            content_sha256, content_size = artifact_content_digest(content)
        elif content_digest is not None:
            content_sha256, content_size = content_digest
        if content_sha256 != receipt.content_sha256 or content_size != receipt.content_size_bytes:
            raise ArtifactIntegrityError("artifact bytes no longer match digest receipt")
    return receipt


def bind_artifact_integrity(
    db: Session,
    *,
    artifact: models.Artifact,
    content: bytes | Path,
) -> models.ArtifactDigestReceipt:
    """Insert one receipt or accept an exact, byte-identical retry."""

    if artifact.id is None:
        artifact.id = f"art_{uuid4().hex[:12]}"
    if artifact.integrity_policy not in {
        None,
        ARTIFACT_INTEGRITY_POLICY,
    }:
        raise ArtifactIntegrityError("artifact already declares a different integrity policy")
    content_sha256, content_size = artifact_content_digest(content)
    payload = _receipt_payload(
        artifact=artifact,
        content_sha256=content_sha256,
        content_size_bytes=content_size,
    )
    expected_evidence_id = _evidence_id(payload)
    existing = db.scalars(
        select(models.ArtifactDigestReceipt).where(
            models.ArtifactDigestReceipt.artifact_id == artifact.id
        )
    ).first()
    if existing is not None:
        try:
            require_artifact_integrity(artifact, content=content)
        except ArtifactIntegrityError as exc:
            raise ArtifactIntegrityError(
                "existing artifact digest receipt is not an exact match"
            ) from exc
        if existing.evidence_id != expected_evidence_id:
            raise ArtifactIntegrityError("existing artifact digest receipt evidence ID diverged")
        return existing

    artifact.integrity_policy = ARTIFACT_INTEGRITY_POLICY
    artifact.file_size_bytes = content_size
    receipt = models.ArtifactDigestReceipt(
        id=f"adr_{uuid4().hex[:12]}",
        artifact_id=artifact.id,
        evidence_id=expected_evidence_id,
        content_sha256=content_sha256,
        content_size_bytes=content_size,
        storage_path_sha256=str(payload["storage_path_sha256"]),
        owner_type=artifact.owner_type,
        owner_id=artifact.owner_id,
        artifact_type=artifact.artifact_type,
    )
    receipt.artifact = artifact
    db.add(receipt)
    return receipt


def authorize_artifact_integrity_deletion(
    db: Session,
    *,
    artifact: models.Artifact,
    reason: str,
) -> None:
    """Authorize receipt deletion only inside an explicit lifecycle transaction.

    The authorization row is removed automatically by the Artifact foreign-key
    cascade. If the surrounding transaction fails, both the authorization and
    attempted deletion roll back together.
    """

    if artifact.digest_receipt is None:
        return
    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 64:
        raise ArtifactIntegrityError("artifact digest deletion requires a bounded reason")
    existing = db.get(
        models.ArtifactDigestDeleteAuthorization,
        artifact.id,
    )
    if existing is not None:
        if existing.reason != normalized_reason:
            raise ArtifactIntegrityError("artifact digest deletion authorization reason diverged")
        return
    db.add(
        models.ArtifactDigestDeleteAuthorization(
            artifact_id=artifact.id,
            reason=normalized_reason,
        )
    )
    db.flush()


__all__ = [
    "ARTIFACT_DIGEST_RECEIPT_SCHEMA",
    "ARTIFACT_INTEGRITY_POLICY",
    "ArtifactIntegrityError",
    "artifact_content_digest",
    "authorize_artifact_integrity_deletion",
    "bind_artifact_integrity",
    "require_artifact_integrity",
]
