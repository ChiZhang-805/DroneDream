"""Read-only guard connecting persisted Jobs to their frozen outcome contract."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.optimization.outcome_contract import (
    OptimizationOutcomeContractV1,
    compile_job_outcome_contract,
)
from app.orchestration.constants import SCORE_WEIGHTS


class OutcomeContractDriftError(ValueError):
    """Raised before dispatch when a recorded contract no longer matches."""


@dataclass(frozen=True)
class OutcomeContractCheck:
    contract: OptimizationOutcomeContractV1
    recorded_contract_id: str | None
    valid: bool


def check_job_outcome_contract(
    db: Session,
    job: models.Job,
) -> OutcomeContractCheck:
    """Compile current semantics and compare the latest creation-time contract."""

    contract = compile_job_outcome_contract(
        job,
        failed_trial_weight=SCORE_WEIGHTS["failed_trial"],
    )
    event = db.scalars(
        select(models.JobEvent)
        .where(
            models.JobEvent.job_id == job.id,
            models.JobEvent.event_type
            == "optimization_outcome_contract_compiled",
        )
        .order_by(
            models.JobEvent.created_at.desc(),
            models.JobEvent.id.desc(),
        )
        .limit(1)
    ).first()
    if event is None:
        return OutcomeContractCheck(
            contract=contract,
            recorded_contract_id=None,
            valid=True,
        )
    payload = event.payload_json
    recorded_contract_id = (
        payload.get("contract_id") if isinstance(payload, dict) else None
    )
    return OutcomeContractCheck(
        contract=contract,
        recorded_contract_id=(
            recorded_contract_id
            if isinstance(recorded_contract_id, str)
            else None
        ),
        valid=recorded_contract_id == contract.contract_id,
    )


__all__ = [
    "OutcomeContractCheck",
    "OutcomeContractDriftError",
    "check_job_outcome_contract",
]
