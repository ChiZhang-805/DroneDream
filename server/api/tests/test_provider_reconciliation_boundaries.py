"""Pure accounting boundary tests; no cloud account, provider or database is contacted."""

from types import SimpleNamespace

import pytest

from app.benchmarking.provider_usage_reconciliation import (
    BenchmarkProviderUsageBlocked,
    _attempt_counts,
    _validate_observed_outcome,
)


def _outcome(**changes):
    """Supply a complete known receipt, changing one accounting field at a time."""
    return SimpleNamespace(
        **(
            {
                "output_utf8_bytes": 20,
                "latency_ms": 10,
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
                "provider_cost_microusd": 4,
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "field",
    [
        "output_utf8_bytes",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "provider_cost_microusd",
    ],
)
@pytest.mark.parametrize("value", [-1, True, 1.2, "20", float("inf")])
def test_each_observed_quantity_must_be_nonnegative_integer(field, value):
    with pytest.raises(BenchmarkProviderUsageBlocked) as failure:
        _validate_observed_outcome(_outcome(**{field: value}))
    assert failure.value.code == "benchmark_provider_outcome_usage_invalid"


@pytest.mark.parametrize(
    "changes",
    [{"total_tokens": 19}, {"total_tokens": 21}, {"output_tokens": None, "total_tokens": 11}],
)
def test_total_cannot_disagree_with_known_components(changes):
    with pytest.raises(BenchmarkProviderUsageBlocked) as failure:
        _validate_observed_outcome(_outcome(**changes))
    assert failure.value.code == "benchmark_provider_outcome_usage_inconsistent"


def test_unreported_quantities_are_allowed_as_unknown_not_filled_in():
    outcome = _outcome(
        input_tokens=None, output_tokens=None, total_tokens=None, provider_cost_microusd=None
    )
    _validate_observed_outcome(outcome)
    assert outcome.total_tokens is None


def test_attempt_partition_retains_missing_and_indeterminate_work():
    counts = _attempt_counts([None, "indeterminate", "succeeded", "provider_failed"])
    assert counts.attempted == 4
    assert counts.indeterminate == 2
    assert counts.succeeded == 1
    assert counts.failed == 1
