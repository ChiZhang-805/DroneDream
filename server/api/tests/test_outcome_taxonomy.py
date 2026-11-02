"""Regression tests for the optimizer outcome trust boundary."""

from __future__ import annotations

import pytest

from app.optimization.outcome_taxonomy import (
    classify_trial_outcome,
    is_optimizer_learning_failure,
    is_optimizer_learning_outcome,
)
from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_CANCELLED,
    FAILURE_INVALID_RESULT,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
)


@pytest.mark.parametrize(
    ("status", "failure_code", "usable_metric", "expected"),
    [
        ("COMPLETED", None, True, "success"),
        ("COMPLETED", FAILURE_TIMEOUT, True, "invalid_evidence"),
        ("COMPLETED", None, False, "invalid_evidence"),
        ("FAILED", FAILURE_TIMEOUT, False, "domain_failure"),
        ("FAILED", FAILURE_SIMULATION, False, "domain_failure"),
        ("FAILED", FAILURE_UNSTABLE, False, "domain_failure"),
        ("FAILED", FAILURE_ADAPTER_UNAVAILABLE, False, "infrastructure_failure"),
        ("FAILED", FAILURE_INVALID_RESULT, False, "invalid_evidence"),
        ("FAILED", FAILURE_CANCELLED, False, "cancelled"),
        ("FAILED", "SELF_REPORTED_CRASH", False, "unknown_failure"),
        ("FAILED", None, False, "unknown_failure"),
        ("FAILED", FAILURE_TIMEOUT, True, "invalid_evidence"),
        ("CANCELLED", FAILURE_TIMEOUT, False, "cancelled"),
        ("RUNNING", FAILURE_TIMEOUT, False, "unknown_failure"),
    ],
)
def test_taxonomy_requires_consistent_terminal_evidence(
    status: object,
    failure_code: object,
    usable_metric: bool,
    expected: str,
) -> None:
    assert (
        classify_trial_outcome(
            status=status,
            failure_code=failure_code,
            usable_metric=usable_metric,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("status", "failure_code", "usable_metric"),
    [
        ({"status": "FAILED"}, FAILURE_TIMEOUT, False),
        ("FAILED", {"code": FAILURE_TIMEOUT}, False),
        ("FAILED", [FAILURE_TIMEOUT], False),
        ("FAILED", FAILURE_TIMEOUT, 1),
    ],
)
def test_taxonomy_is_total_for_malformed_untrusted_values(
    status: object,
    failure_code: object,
    usable_metric: object,
) -> None:
    assert (
        classify_trial_outcome(
            status=status,
            failure_code=failure_code,
            usable_metric=usable_metric,  # type: ignore[arg-type]
        )
        in {
            "invalid_evidence",
            "unknown_failure",
        }
    )


@pytest.mark.parametrize(
    "outcome",
    [
        "infrastructure_failure",
        "cancelled",
        "invalid_evidence",
        "unknown_failure",
    ],
)
def test_nonphysical_or_untrusted_failures_never_teach_optimizer(
    outcome: str,
) -> None:
    assert is_optimizer_learning_outcome(outcome) is False
    assert is_optimizer_learning_failure(outcome) is False


def test_only_success_and_verified_domain_failure_enter_optimizer_learning() -> None:
    assert is_optimizer_learning_outcome("success") is True
    assert is_optimizer_learning_failure("success") is False
    assert is_optimizer_learning_outcome("domain_failure") is True
    assert is_optimizer_learning_failure("domain_failure") is True


@pytest.mark.parametrize("value", [{"outcome": "domain_failure"}, ["domain_failure"]])
def test_learning_predicates_are_total_for_malformed_values(value: object) -> None:
    assert is_optimizer_learning_outcome(value) is False
    assert is_optimizer_learning_failure(value) is False
