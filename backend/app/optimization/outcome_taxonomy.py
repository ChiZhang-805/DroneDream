"""Closed Trial outcome taxonomy for optimizer-learning boundaries."""

from __future__ import annotations

from typing import Literal

from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_ARTIFACT_PERSISTENCE,
    FAILURE_CANCELLED,
    FAILURE_EXECUTION_TIMEOUT,
    FAILURE_INVALID_PARAMETERS,
    FAILURE_INVALID_RESULT,
    FAILURE_RESULT_PERSISTENCE,
    FAILURE_SIM_ERROR,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
    FAILURE_UNVERIFIED_REPORT,
)

TRIAL_OUTCOME_TAXONOMY_SCHEMA = "dronedream.trial-outcome-taxonomy/v1"

TrialOutcomeClass = Literal[
    "success",
    "domain_failure",
    "infrastructure_failure",
    "cancelled",
    "invalid_evidence",
    "unknown_failure",
]
TRIAL_OUTCOME_CLASSES: tuple[TrialOutcomeClass, ...] = (
    "success",
    "domain_failure",
    "infrastructure_failure",
    "cancelled",
    "invalid_evidence",
    "unknown_failure",
)

DOMAIN_FAILURE_CODES = frozenset(
    {
        FAILURE_TIMEOUT,
        FAILURE_SIMULATION,
        FAILURE_UNSTABLE,
    }
)
INFRASTRUCTURE_FAILURE_CODES = frozenset(
    {
        FAILURE_SIM_ERROR,
        FAILURE_ADAPTER_UNAVAILABLE,
        FAILURE_ARTIFACT_PERSISTENCE,
        FAILURE_RESULT_PERSISTENCE,
        FAILURE_EXECUTION_TIMEOUT,
    }
)
INVALID_EVIDENCE_FAILURE_CODES = frozenset(
    {
        FAILURE_INVALID_PARAMETERS,
        FAILURE_INVALID_RESULT,
        FAILURE_UNVERIFIED_REPORT,
    }
)


def classify_trial_outcome(
    *,
    status: object,
    failure_code: object,
    usable_metric: bool,
) -> TrialOutcomeClass:
    """Classify one terminal Trial without forgiving unknown failures.

    Unknown codes remain an explicit conservative failure class and are
    included in optimizer-learning failure rates. Infrastructure, cancellation,
    and invalid-evidence outcomes still block completion and acceptance but do
    not teach the numerical optimizer that the physical parameter region is
    unsafe.
    """

    if status == "COMPLETED" and usable_metric:
        return "success"
    if status == "CANCELLED" or failure_code == FAILURE_CANCELLED:
        return "cancelled"
    if failure_code in INFRASTRUCTURE_FAILURE_CODES:
        return "infrastructure_failure"
    if failure_code in INVALID_EVIDENCE_FAILURE_CODES:
        return "invalid_evidence"
    if failure_code in DOMAIN_FAILURE_CODES:
        return "domain_failure"
    if status == "COMPLETED":
        return "invalid_evidence"
    return "unknown_failure"


def is_optimizer_learning_outcome(value: TrialOutcomeClass) -> bool:
    return value in {
        "success",
        "domain_failure",
        "unknown_failure",
    }


def is_optimizer_learning_failure(value: TrialOutcomeClass) -> bool:
    return value in {
        "domain_failure",
        "unknown_failure",
    }


__all__ = [
    "DOMAIN_FAILURE_CODES",
    "INFRASTRUCTURE_FAILURE_CODES",
    "INVALID_EVIDENCE_FAILURE_CODES",
    "TRIAL_OUTCOME_TAXONOMY_SCHEMA",
    "TRIAL_OUTCOME_CLASSES",
    "TrialOutcomeClass",
    "classify_trial_outcome",
    "is_optimizer_learning_failure",
    "is_optimizer_learning_outcome",
]
