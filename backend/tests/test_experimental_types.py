from __future__ import annotations

import pytest

from app.optimization.experimental_types import OptimizerObservation


def _observation(**overrides: object) -> OptimizerObservation:
    values: dict[str, object] = {
        "candidate_id": "candidate-1",
        "generation_index": 1,
        "parameters": {"gain": 0.5},
        "unit_vector": (0.5,),
        "loss": 0.25,
    }
    values.update(overrides)
    return OptimizerObservation(**values)  # type: ignore[arg-type]


def test_historical_incomplete_observation_normalizes_to_pending_reservation() -> None:
    observation = _observation(loss=None, completed=False)

    assert observation.role == "pending_reservation"
    assert observation.completed is False


def test_explicit_completed_pending_reservation_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="pending reservations must be incomplete",
    ):
        _observation(
            loss=None,
            completed=True,
            role="pending_reservation",
        )


def test_constraint_only_observation_rejects_objective_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="constraint-only observations cannot contain objective values",
    ):
        _observation(role="constraint_only")
