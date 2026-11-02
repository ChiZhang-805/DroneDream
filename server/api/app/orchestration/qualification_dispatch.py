"""Server-authoritative binding of candidates to sealed screening dispatches."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models, schemas
from app.optimization.scenarios import ScenarioRun
from app.orchestration.qualification import (
    QUALIFICATION_CONTRACT_SCHEMA,
    QUALIFICATION_RULE_SHA256,
    QUALIFICATION_RULE_VERSION,
    RULE_V1,
    SEALED_QUALIFICATION_POLICY_VERSION,
    QualificationContractError,
    SealedQualificationHoldoutContractV1,
    compile_sealed_qualification_contract,
    sealed_qualification_contract_sha256,
)

_LEGACY_HOLDOUT_POLICIES = frozenset(
    {
        "legacy-visible-v0",
        "continuation-independent-holdout-v1",
    }
)


class QualificationDispatchError(QualificationContractError):
    """Raised when a Job/Candidate cannot enter the sealed screening gate."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sealed_contract_for_job(
    job: models.Job,
) -> SealedQualificationHoldoutContractV1 | None:
    """Return an exact sealed contract, preserving explicitly-known legacy Jobs."""

    policy = job.holdout_policy_version
    if policy in _LEGACY_HOLDOUT_POLICIES:
        return None
    if policy != SEALED_QUALIFICATION_POLICY_VERSION:
        raise QualificationDispatchError("Job uses an unknown holdout policy")
    if not isinstance(job.holdout_contract_json, dict):
        raise QualificationDispatchError("sealed Job is missing its holdout contract")
    if not isinstance(job.scenario_suite_json, dict):
        raise QualificationDispatchError("sealed Job is missing its scenario suite")
    try:
        persisted = SealedQualificationHoldoutContractV1.model_validate(job.holdout_contract_json)
        suite = schemas.ScenarioSuiteConfig.model_validate(job.scenario_suite_json)
        compiled = compile_sealed_qualification_contract(suite)
    except (TypeError, ValueError, ValidationError) as exc:
        raise QualificationDispatchError("sealed Job holdout contract is invalid") from exc
    if persisted != compiled:
        raise QualificationDispatchError(
            "sealed Job holdout contract diverges from its scenario suite"
        )
    return persisted


def candidate_selection_snapshot_sha256(
    *,
    candidate: models.CandidateParameterSet,
    holdout_contract_sha256: str,
) -> str:
    """Bind selection to server dispatch order and the exact parameter snapshot."""

    ordinal = candidate.dispatch_ordinal
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise QualificationDispatchError(
            "sealed screening requires a server candidate dispatch ordinal"
        )
    return _sha256(
        {
            "job_id": candidate.job_id,
            "candidate_id": candidate.id,
            "generation_index": candidate.generation_index,
            "dispatch_ordinal": ordinal,
            "source_type": candidate.source_type,
            "is_baseline": candidate.is_baseline,
            "parameter_json": candidate.parameter_json,
            "holdout_contract_sha256": holdout_contract_sha256,
        }
    )


def ensure_candidate_screening_qualification(
    db: Session,
    *,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> tuple[
    models.CandidateQualification | None,
    SealedQualificationHoldoutContractV1 | None,
]:
    """Create the insert-once screening row for a sealed Job candidate."""

    contract = sealed_contract_for_job(job)
    if contract is None:
        return None, None
    if candidate.job_id != job.id:
        raise QualificationDispatchError("candidate belongs to another Job")
    contract_sha256 = sealed_qualification_contract_sha256(contract)
    selection_sha256 = candidate_selection_snapshot_sha256(
        candidate=candidate,
        holdout_contract_sha256=contract_sha256,
    )

    existing = candidate.qualification
    if existing is not None:
        if (
            existing.job_id != job.id
            or existing.candidate_id != candidate.id
            or existing.contract_schema != QUALIFICATION_CONTRACT_SCHEMA
            or existing.rule_version != QUALIFICATION_RULE_VERSION
            or existing.rule_sha256 != QUALIFICATION_RULE_SHA256
            or existing.holdout_contract_sha256 != contract_sha256
            or existing.selection_snapshot_sha256 != selection_sha256
        ):
            raise QualificationDispatchError("candidate qualification binding is insert-once")
        return existing, contract

    qualification = models.CandidateQualification(
        id=f"qlf_{uuid4().hex[:12]}",
        job_id=job.id,
        candidate_id=candidate.id,
        contract_schema=QUALIFICATION_CONTRACT_SCHEMA,
        rule_version=QUALIFICATION_RULE_VERSION,
        rule_sha256=QUALIFICATION_RULE_SHA256,
        holdout_contract_sha256=contract_sha256,
        selection_snapshot_sha256=selection_sha256,
        state="screening",
        state_revision=1,
        screening_required=RULE_V1.screening_required,
        qualification_initial_required=RULE_V1.qualification_initial_required,
        qualification_extended_required=RULE_V1.qualification_extended_required,
        direct_pass_min=RULE_V1.direct_pass_min,
        extension_trigger_passes=RULE_V1.extension_trigger_passes,
        extended_pass_min=RULE_V1.extended_pass_min,
        max_candidates_per_run=RULE_V1.max_candidates_per_run,
    )
    qualification.candidate = candidate
    qualification.job = job
    db.add(qualification)
    return qualification, contract


def screening_runs(
    contract: SealedQualificationHoldoutContractV1,
) -> tuple[ScenarioRun, ...]:
    """Project the immutable screening contract into executable ScenarioRuns."""

    return tuple(
        ScenarioRun(
            case_id=item.case_id,
            scenario_type=item.scenario_type,
            seed=item.seed,
            weight=item.weight,
            holdout=False,
            config=item.config_dict(),
        )
        for item in contract.screening
    )


def qualification_runs(
    contract: SealedQualificationHoldoutContractV1,
    *,
    start_ordinal: int = 1,
    end_ordinal: int = 10,
) -> tuple[ScenarioRun, ...]:
    """Return one bounded, preregistered holdout slice without revealing outcomes."""

    if (
        isinstance(start_ordinal, bool)
        or not isinstance(start_ordinal, int)
        or isinstance(end_ordinal, bool)
        or not isinstance(end_ordinal, int)
        or start_ordinal < 1
        or end_ordinal > 20
        or start_ordinal > end_ordinal
    ):
        raise QualificationDispatchError("qualification ordinal slice is invalid")
    selected = contract.qualification[start_ordinal - 1 : end_ordinal]
    if len(selected) != end_ordinal - start_ordinal + 1:
        raise QualificationDispatchError("qualification contract slice is incomplete")
    return tuple(
        ScenarioRun(
            case_id=item.case_id,
            scenario_type=item.scenario_type,
            seed=item.seed,
            weight=item.weight,
            holdout=True,
            config=item.config_dict(),
        )
        for item in selected
    )


def qualification_trial_binding(
    *,
    qualification: models.CandidateQualification,
    phase: str,
    ordinal: int,
) -> dict[str, Any]:
    """Return the exact ORM fields required by Trial check constraints."""

    valid = (phase == "screening" and 1 <= ordinal <= 4) or (
        phase == "qualification" and 1 <= ordinal <= 20
    )
    if not valid:
        raise QualificationDispatchError("qualification Trial phase/ordinal is invalid")
    return {
        "qualification_id": qualification.id,
        "evaluation_phase": phase,
        "qualification_ordinal": ordinal,
    }


__all__ = [
    "QualificationDispatchError",
    "candidate_selection_snapshot_sha256",
    "ensure_candidate_screening_qualification",
    "qualification_runs",
    "qualification_trial_binding",
    "screening_runs",
    "sealed_contract_for_job",
]
