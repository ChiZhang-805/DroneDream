"""Insert-once persistence boundary for final winner-selection evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.optimization.winner_evidence import (
    WinnerSelectionEvidenceV1,
    verify_winner_selection_evidence,
)

WINNER_FREEZE_RECEIPT_SCHEMA = "dronedream.winner-freeze-receipt/v1"


class WinnerFreezeError(ValueError):
    """Raised when a winner receipt is missing, late, or inconsistent."""


def _receipt_matches(
    receipt: models.WinnerFreezeReceipt,
    evidence: WinnerSelectionEvidenceV1,
) -> bool:
    persisted = verify_winner_selection_evidence(receipt.evidence_json)
    return (
        receipt.receipt_schema == WINNER_FREEZE_RECEIPT_SCHEMA
        and persisted is not None
        and persisted == evidence
        and receipt.evidence_id == evidence.evidence_id
        and receipt.outcome_contract_id == evidence.outcome_contract_id
        and receipt.baseline_candidate_id
        == evidence.baseline_candidate_id
        and receipt.winner_candidate_id == evidence.winner_candidate_id
    )


def require_winner_freeze_receipt(
    receipt: models.WinnerFreezeReceipt,
    *,
    job: models.Job | None = None,
    evidence: object | None = None,
) -> WinnerSelectionEvidenceV1:
    """Return verified evidence only when every receipt binding still matches."""

    verified = verify_winner_selection_evidence(receipt.evidence_json)
    if verified is None or not _receipt_matches(receipt, verified):
        raise WinnerFreezeError(
            "winner freeze receipt is internally inconsistent"
        )
    if job is not None and (
        receipt.job_id != job.id
        or receipt.winner_candidate_id != job.best_candidate_id
        or receipt.baseline_candidate_id != job.baseline_candidate_id
    ):
        raise WinnerFreezeError(
            "winner freeze receipt does not match current Job selection"
        )
    if evidence is not None:
        expected = verify_winner_selection_evidence(evidence)
        if expected is None or expected != verified:
            raise WinnerFreezeError(
                "winner freeze receipt does not match expected evidence"
            )
    return verified


def freeze_winner_selection(
    db: Session,
    *,
    job: models.Job,
    evidence: WinnerSelectionEvidenceV1 | dict[str, object],
) -> models.WinnerFreezeReceipt:
    """Insert one exact winner receipt or return the identical prior receipt.

    A new receipt may be created only while the Job owns the FINALIZING lease.
    Re-entry is idempotent only when every persisted scalar and the complete
    content-addressed evidence envelope still match.
    """

    verified = verify_winner_selection_evidence(evidence)
    if verified is None:
        raise WinnerFreezeError(
            "winner freeze requires verified selection evidence"
        )
    if (
        verified.winner_candidate_id != job.best_candidate_id
        or verified.baseline_candidate_id != job.baseline_candidate_id
    ):
        raise WinnerFreezeError(
            "winner freeze evidence does not match current Job selection"
        )

    existing = db.scalars(
        select(models.WinnerFreezeReceipt).where(
            models.WinnerFreezeReceipt.job_id == job.id
        )
    ).first()
    if existing is not None:
        try:
            require_winner_freeze_receipt(
                existing,
                job=job,
                evidence=verified,
            )
        except WinnerFreezeError as exc:
            raise WinnerFreezeError(
                "existing winner freeze receipt is not an exact evidence match"
            ) from exc
        return existing

    if job.status != "FINALIZING":
        raise WinnerFreezeError(
            "a new winner freeze receipt may be created only during FINALIZING"
        )

    receipt = models.WinnerFreezeReceipt(
        id=f"wfr_{uuid4().hex[:12]}",
        job_id=job.id,
        receipt_schema=WINNER_FREEZE_RECEIPT_SCHEMA,
        evidence_id=verified.evidence_id,
        outcome_contract_id=verified.outcome_contract_id,
        baseline_candidate_id=verified.baseline_candidate_id,
        winner_candidate_id=verified.winner_candidate_id,
        evidence_json=verified.model_dump(mode="json"),
        frozen_at=datetime.now(timezone.utc),
    )
    receipt.job = job
    db.add(receipt)
    return receipt


__all__ = [
    "WINNER_FREEZE_RECEIPT_SCHEMA",
    "WinnerFreezeError",
    "freeze_winner_selection",
    "require_winner_freeze_receipt",
]
