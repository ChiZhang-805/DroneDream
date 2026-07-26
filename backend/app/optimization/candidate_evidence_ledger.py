"""Append-only relational ledger for Candidate outcome/report evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app import models
from app.optimization.outcome_evidence import (
    CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA,
    CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA,
    CandidateOutcomeEvidenceV3,
    CandidateReportEvidenceV3,
    verify_candidate_outcome_evidence,
    verify_candidate_report_evidence,
)

CANDIDATE_EVIDENCE_RECEIPT_SCHEMA: Literal[
    "dronedream.candidate-evidence-receipt/v1"
] = "dronedream.candidate-evidence-receipt/v1"

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(ge=1)]
NonnegativeInt = Annotated[int, Field(ge=0)]


class CandidateEvidenceLedgerError(ValueError):
    """Raised when an append-only Candidate evidence chain diverges."""


class CandidateEvidenceReceiptV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.candidate-evidence-receipt/v1"] = (
        "dronedream.candidate-evidence-receipt/v1"
    )
    evidence_id: Sha256Id
    candidate_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    revision: PositiveInt
    previous_evidence_id: Sha256Id | None
    generation_index: NonnegativeInt
    parameter_sha256: Sha256Id
    aggregate_sha256: Sha256Id
    outcome_evidence_schema: Literal[
        "dronedream.candidate-outcome-evidence/v3"
    ] = "dronedream.candidate-outcome-evidence/v3"
    outcome_evidence_id: Sha256Id
    training_trial_evidence_sha256: Sha256Id
    training_accepted_attempt_count: NonnegativeInt
    report_evidence_schema: Literal[
        "dronedream.candidate-report-evidence/v3"
    ] = "dronedream.candidate-report-evidence/v3"
    report_evidence_id: Sha256Id
    report_trial_evidence_sha256: Sha256Id
    report_accepted_attempt_count: NonnegativeInt

    @model_validator(mode="after")
    def _validate_chain_position(self) -> CandidateEvidenceReceiptV1:
        if (self.revision == 1) != (self.previous_evidence_id is None):
            raise ValueError(
                "Candidate evidence revision one alone has no predecessor"
            )
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _validated_v3_evidence(
    *,
    candidate: models.CandidateParameterSet,
    aggregate: Mapping[str, Any],
) -> tuple[CandidateOutcomeEvidenceV3, CandidateReportEvidenceV3]:
    outcome = verify_candidate_outcome_evidence(
        aggregate.get("candidate_outcome_evidence")
    )
    report = verify_candidate_report_evidence(
        aggregate.get("candidate_report_evidence")
    )
    if (
        not isinstance(outcome, CandidateOutcomeEvidenceV3)
        or not isinstance(report, CandidateReportEvidenceV3)
        or outcome.schema_id != CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA
        or report.schema_id != CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA
        or report.candidate_outcome_evidence_id != outcome.evidence_id
        or outcome.candidate_id != candidate.id
        or outcome.generation_index != candidate.generation_index
        or outcome.parameter_sha256 != _sha256_id(candidate.parameter_json)
        or aggregate.get("candidate_outcome_evidence_required") is not True
        or aggregate.get("candidate_report_evidence_required") is not True
    ):
        raise CandidateEvidenceLedgerError(
            "Candidate receipt requires current linked v3 outcome/report evidence"
        )
    return outcome, report


def compile_candidate_evidence_receipt(
    *,
    candidate: models.CandidateParameterSet,
    aggregate: Mapping[str, Any],
    revision: int,
    previous_evidence_id: str | None,
) -> CandidateEvidenceReceiptV1:
    outcome, report = _validated_v3_evidence(
        candidate=candidate,
        aggregate=aggregate,
    )
    payload: dict[str, Any] = {
        "schema_id": CANDIDATE_EVIDENCE_RECEIPT_SCHEMA,
        "candidate_id": candidate.id,
        "job_id": candidate.job_id,
        "revision": revision,
        "previous_evidence_id": previous_evidence_id,
        "generation_index": candidate.generation_index,
        "parameter_sha256": outcome.parameter_sha256,
        "aggregate_sha256": _sha256_id(aggregate),
        "outcome_evidence_schema": outcome.schema_id,
        "outcome_evidence_id": outcome.evidence_id,
        "training_trial_evidence_sha256": outcome.trial_evidence_sha256,
        "training_accepted_attempt_count": outcome.accepted_attempt_count,
        "report_evidence_schema": report.schema_id,
        "report_evidence_id": report.evidence_id,
        "report_trial_evidence_sha256": report.report_trial_evidence_sha256,
        "report_accepted_attempt_count": report.accepted_attempt_count,
    }
    return CandidateEvidenceReceiptV1.model_validate(
        {"evidence_id": _sha256_id(payload), **payload}
    )


def verify_candidate_evidence_receipt(
    value: object,
) -> CandidateEvidenceReceiptV1 | None:
    try:
        receipt = CandidateEvidenceReceiptV1.model_validate(value)
    except ValidationError:
        return None
    payload = receipt.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    return receipt if evidence_id == _sha256_id(payload) else None


def _verified_receipt_row(
    row: models.CandidateEvidenceReceipt,
) -> CandidateEvidenceReceiptV1 | None:
    receipt = verify_candidate_evidence_receipt(row.evidence_json)
    outcome = verify_candidate_outcome_evidence(row.outcome_evidence_json)
    report = verify_candidate_report_evidence(row.report_evidence_json)
    if (
        receipt is None
        or not isinstance(outcome, CandidateOutcomeEvidenceV3)
        or not isinstance(report, CandidateReportEvidenceV3)
        or row.receipt_schema != receipt.schema_id
        or row.evidence_id != receipt.evidence_id
        or row.candidate_id != receipt.candidate_id
        or row.job_id != receipt.job_id
        or row.revision != receipt.revision
        or row.previous_evidence_id != receipt.previous_evidence_id
        or row.aggregate_sha256 != receipt.aggregate_sha256
        or row.outcome_evidence_id != receipt.outcome_evidence_id
        or row.report_evidence_id != receipt.report_evidence_id
        or outcome.evidence_id != receipt.outcome_evidence_id
        or report.evidence_id != receipt.report_evidence_id
        or report.candidate_outcome_evidence_id != outcome.evidence_id
        or outcome.trial_evidence_sha256
        != receipt.training_trial_evidence_sha256
        or outcome.accepted_attempt_count
        != receipt.training_accepted_attempt_count
        or report.report_trial_evidence_sha256
        != receipt.report_trial_evidence_sha256
        or report.accepted_attempt_count
        != receipt.report_accepted_attempt_count
    ):
        return None
    return receipt


def _ordered_receipts(
    candidate: models.CandidateParameterSet,
) -> list[models.CandidateEvidenceReceipt]:
    return sorted(
        list(candidate.evidence_receipts),
        key=lambda row: (row.revision, row.id),
    )


def record_candidate_evidence_receipt(
    *,
    candidate: models.CandidateParameterSet,
    aggregate: Mapping[str, Any],
) -> models.CandidateEvidenceReceipt:
    candidate.evidence_ledger_required = True
    rows = _ordered_receipts(candidate)
    previous_id: str | None = None
    for expected_revision, row in enumerate(rows, start=1):
        receipt = _verified_receipt_row(row)
        if (
            receipt is None
            or receipt.revision != expected_revision
            or receipt.previous_evidence_id != previous_id
        ):
            raise CandidateEvidenceLedgerError(
                "existing Candidate evidence chain is invalid"
            )
        previous_id = receipt.evidence_id

    revision = len(rows) + 1
    compiled = compile_candidate_evidence_receipt(
        candidate=candidate,
        aggregate=aggregate,
        revision=revision,
        previous_evidence_id=previous_id,
    )
    if rows:
        latest = _verified_receipt_row(rows[-1])
        if latest is not None and latest.aggregate_sha256 == compiled.aggregate_sha256:
            return rows[-1]

    outcome = verify_candidate_outcome_evidence(
        aggregate.get("candidate_outcome_evidence")
    )
    report = verify_candidate_report_evidence(
        aggregate.get("candidate_report_evidence")
    )
    if not isinstance(outcome, CandidateOutcomeEvidenceV3) or not isinstance(
        report,
        CandidateReportEvidenceV3,
    ):
        raise CandidateEvidenceLedgerError(
            "Candidate receipt lost its verified v3 evidence"
        )
    row = models.CandidateEvidenceReceipt(
        id="cer_" + compiled.evidence_id.removeprefix("sha256:")[:32],
        candidate_id=candidate.id,
        job_id=candidate.job_id,
        revision=compiled.revision,
        previous_evidence_id=compiled.previous_evidence_id,
        receipt_schema=compiled.schema_id,
        evidence_id=compiled.evidence_id,
        aggregate_sha256=compiled.aggregate_sha256,
        outcome_evidence_id=compiled.outcome_evidence_id,
        report_evidence_id=compiled.report_evidence_id,
        outcome_evidence_json=outcome.model_dump(mode="json"),
        report_evidence_json=report.model_dump(mode="json"),
        evidence_json=compiled.model_dump(mode="json"),
    )
    candidate.evidence_receipts.append(row)
    return row


def candidate_evidence_receipt_required(
    candidate: object,
) -> bool:
    if getattr(candidate, "evidence_ledger_required", False) is True:
        return True
    try:
        if list(candidate.evidence_receipts):  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    aggregate = getattr(candidate, "aggregated_metric_json", None)
    if not isinstance(aggregate, Mapping):
        return False
    outcome = aggregate.get("candidate_outcome_evidence")
    report = aggregate.get("candidate_report_evidence")
    return (
        (
            isinstance(outcome, Mapping)
            and outcome.get("schema_id") == CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA
        )
        or (
            isinstance(report, Mapping)
            and report.get("schema_id") == CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA
        )
    )


def candidate_evidence_chain_matches_current(
    candidate: models.CandidateParameterSet,
    aggregate: object | None = None,
) -> bool:
    raw_aggregate = (
        candidate.aggregated_metric_json
        if aggregate is None
        else aggregate
    )
    if not isinstance(raw_aggregate, Mapping):
        return False
    try:
        rows = _ordered_receipts(candidate)
        if not rows:
            return False
        previous_id: str | None = None
        latest: CandidateEvidenceReceiptV1 | None = None
        for expected_revision, row in enumerate(rows, start=1):
            receipt = _verified_receipt_row(row)
            if (
                receipt is None
                or receipt.revision != expected_revision
                or receipt.previous_evidence_id != previous_id
                or receipt.candidate_id != candidate.id
                or receipt.job_id != candidate.job_id
                or receipt.generation_index != candidate.generation_index
                or receipt.parameter_sha256
                != _sha256_id(candidate.parameter_json)
            ):
                return False
            previous_id = receipt.evidence_id
            latest = receipt
        assert latest is not None
        outcome, report = _validated_v3_evidence(
            candidate=candidate,
            aggregate=raw_aggregate,
        )
        return (
            latest.aggregate_sha256 == _sha256_id(raw_aggregate)
            and latest.outcome_evidence_id == outcome.evidence_id
            and latest.report_evidence_id == report.evidence_id
            and rows[-1].outcome_evidence_json
            == outcome.model_dump(mode="json")
            and rows[-1].report_evidence_json
            == report.model_dump(mode="json")
        )
    except (TypeError, ValueError):
        return False


def authorize_candidate_evidence_deletion(
    db: Session,
    *,
    receipt: models.CandidateEvidenceReceipt,
    reason: str,
) -> None:
    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 64:
        raise CandidateEvidenceLedgerError(
            "Candidate evidence deletion requires a bounded reason"
        )
    existing = db.get(models.CandidateEvidenceDeleteAuthorization, receipt.id)
    if existing is not None:
        if existing.reason != normalized_reason:
            raise CandidateEvidenceLedgerError(
                "Candidate evidence deletion already has another reason"
            )
        return
    db.add(
        models.CandidateEvidenceDeleteAuthorization(
            receipt_id=receipt.id,
            reason=normalized_reason,
        )
    )


def current_candidate_evidence_receipt(
    candidate: models.CandidateParameterSet,
) -> CandidateEvidenceReceiptV1 | None:
    rows = _ordered_receipts(candidate)
    if not rows:
        return None
    if not candidate_evidence_chain_matches_current(candidate):
        return None
    return _verified_receipt_row(rows[-1])


__all__ = [
    "CANDIDATE_EVIDENCE_RECEIPT_SCHEMA",
    "CandidateEvidenceLedgerError",
    "CandidateEvidenceReceiptV1",
    "authorize_candidate_evidence_deletion",
    "candidate_evidence_chain_matches_current",
    "candidate_evidence_receipt_required",
    "compile_candidate_evidence_receipt",
    "current_candidate_evidence_receipt",
    "record_candidate_evidence_receipt",
    "verify_candidate_evidence_receipt",
]
