"""Closed Trial outcome taxonomy for optimizer-learning boundaries."""

from __future__ import annotations

from typing import Literal

from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_ARTIFACT_PERSISTENCE,
    FAILURE_CANCELLED,
    FAILURE_EXECUTION_TIMEOUT,
    FAILURE_INPUT_EVIDENCE_DRIFT,
    FAILURE_INVALID_PARAMETERS,
    FAILURE_INVALID_RESULT,
    FAILURE_OUTCOME_CONTRACT_DRIFT,
    FAILURE_RESULT_PERSISTENCE,
    FAILURE_SCENARIO_CONTRACT_DRIFT,
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

_TERMINAL_TRIAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_OPTIMIZER_LEARNING_OUTCOMES = frozenset({"success", "domain_failure"})
_OPTIMIZER_LEARNING_FAILURES = frozenset({"domain_failure"})

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
        FAILURE_INPUT_EVIDENCE_DRIFT,
        FAILURE_OUTCOME_CONTRACT_DRIFT,
        FAILURE_SCENARIO_CONTRACT_DRIFT,
        FAILURE_UNVERIFIED_REPORT,
    }
)


def classify_trial_outcome(
    *,
    status: object,
    failure_code: object,
    usable_metric: bool,
) -> TrialOutcomeClass:
    """Classify one Trial through a fail-closed optimizer trust boundary.

    Only a ``FAILED`` Trial carrying one of the canonical, trusted domain
    failure codes can teach the numerical optimizer that a physical parameter
    region is unsafe. Unknown producer claims, malformed records, inconsistent
    status/metric combinations, infrastructure failures, and cancellations
    remain non-successes for completion and acceptance, but cannot poison
    optimizer learning.

    ``status`` and ``failure_code`` intentionally arrive as ``object`` because
    this function also seals persisted and external evidence. Normalizing them
    before membership checks makes the taxonomy total: malformed list/dict
    values classify conservatively instead of raising ``TypeError``.
    """

    normalized_status = status if isinstance(status, str) else None
    normalized_failure_code = failure_code if isinstance(failure_code, str) else None

    if normalized_status not in _TERMINAL_TRIAL_STATUSES:
        return "unknown_failure"
    if not isinstance(usable_metric, bool):
        return "invalid_evidence"
    has_usable_metric = usable_metric
    if normalized_status == "CANCELLED":
        return "cancelled"
    if normalized_status == "COMPLETED":
        if has_usable_metric and normalized_failure_code is None:
            return "success"
        return "invalid_evidence"

    # From here on the only valid terminal status is FAILED. A failed Trial
    # carrying a supposedly usable metric is internally contradictory, so its
    # evidence is quarantined regardless of any accompanying producer code.
    if has_usable_metric:
        return "invalid_evidence"
    if normalized_failure_code == FAILURE_CANCELLED:
        return "cancelled"
    if normalized_failure_code in INFRASTRUCTURE_FAILURE_CODES:
        return "infrastructure_failure"
    if normalized_failure_code in INVALID_EVIDENCE_FAILURE_CODES:
        return "invalid_evidence"
    if normalized_failure_code in DOMAIN_FAILURE_CODES:
        return "domain_failure"
    return "unknown_failure"


def is_optimizer_learning_outcome(value: object) -> bool:
    """Return whether an outcome may enter optimizer observations."""

    return isinstance(value, str) and value in _OPTIMIZER_LEARNING_OUTCOMES


def is_optimizer_learning_failure(value: object) -> bool:
    """Return whether a trusted physical failure may teach the optimizer."""

    return isinstance(value, str) and value in _OPTIMIZER_LEARNING_FAILURES


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
