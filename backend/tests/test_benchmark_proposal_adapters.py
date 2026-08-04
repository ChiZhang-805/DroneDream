from __future__ import annotations

from copy import deepcopy

import pytest

from app.benchmarking.adapters import (
    BenchmarkAdapterError,
    native_optimizer_request_from_observation,
)
from app.benchmarking.contracts import (
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    BenchmarkProposalAdapter,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.benchmarking.numeric_landscapes import DeterministicConstrainedLandscapeV1
from app.benchmarking.registry import (
    BENCHMARK_ADAPTER_REGISTRY,
    create_benchmark_adapter,
)
from app.optimization.domain import ParameterDomain, SearchSpace


def _domain() -> list[dict[str, object]]:
    return [
        {
            "name": "kp_xy",
            "baseline": 1.5,
            "minimum": 0.5,
            "maximum": 2.5,
            "step": None,
            "scale": "linear",
            "value_type": "float",
            "choices": [],
            "enabled": True,
            "locked": False,
        },
        {
            "name": "kd_xy",
            "baseline": 0.3,
            "minimum": 0.05,
            "maximum": 1.0,
            "step": 0.01,
            "scale": "linear",
            "value_type": "float",
            "choices": [],
            "enabled": True,
            "locked": False,
        },
        {
            "name": "ki_xy",
            "baseline": 0.08,
            "minimum": 0.01,
            "maximum": 0.3,
            "step": None,
            "scale": "log",
            "value_type": "float",
            "choices": [],
            "enabled": True,
            "locked": False,
        },
        {
            "name": "mode",
            "baseline": 1.0,
            "minimum": 0.0,
            "maximum": 2.0,
            "step": None,
            "scale": "linear",
            "value_type": "enum",
            "choices": [0.0, 1.0, 2.0],
            "enabled": True,
            "locked": False,
        },
    ]


def _observation(
    *,
    adapter_id: str,
    ordinal: int = 1,
    history: list[BenchmarkHistoryItemV2] | None = None,
) -> BenchmarkObservationV2:
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id=adapter_id.replace("/", "-"),
        generation_index=1,
        next_dispatch_ordinal=ordinal,
        algorithm_seed=20260804,
        simulator_seed_block_id="crn-block-1",
        parameter_domain=_domain(),
        objectives=[{"name": "tracking_error", "direction": "minimize"}],
        constraints=[{"name": "safety", "operator": "le", "threshold": 0.0}],
        history=history or [],
        failure_semantics={
            "unsafe": "constraint-only",
            "timeout": "terminal-failure",
        },
        simulator_budget_remaining=32,
        wall_time_remaining_ms=60_000,
    )


@pytest.mark.parametrize("adapter_id", ("random_search/v1", "seeded_halton/v1"))
def test_implemented_adapters_are_deterministic_bounded_and_protocol_conformant(
    adapter_id: str,
) -> None:
    adapter = create_benchmark_adapter(adapter_id)
    observation = _observation(adapter_id=adapter_id)

    first = adapter.propose(observation)
    second = adapter.propose(observation)

    assert isinstance(adapter, BenchmarkProposalAdapter)
    assert first == second
    assert first.proposal_receipt["observation_sha256"] == canonical_sha256(observation)
    assert first.proposal_receipt["adapter_id"] == adapter_id
    assert set(first.parameters) == {item["name"] for item in _domain()}
    assert 0.5 <= first.parameters["kp_xy"] <= 2.5
    assert 0.05 <= first.parameters["kd_xy"] <= 1.0
    assert 0.01 <= first.parameters["ki_xy"] <= 0.3
    assert first.parameters["mode"] in {0.0, 1.0, 2.0}


@pytest.mark.parametrize("adapter_id", ("random_search/v1", "seeded_halton/v1"))
def test_adapters_skip_a_previously_dispatched_candidate(adapter_id: str) -> None:
    adapter = create_benchmark_adapter(adapter_id)
    initial = _observation(adapter_id=adapter_id)
    first = adapter.propose(initial)
    history = [
        BenchmarkHistoryItemV2(
            candidate_ref=first.candidate_ref,
            generation_index=1,
            dispatch_ordinal=1,
            parameters=first.parameters,
            screening_status="passed",
            outcome=BenchmarkOptimizerOutcomeV1(
                role="objective",
                loss=0.25,
                objectives={"tracking_error": 0.25},
                objective_directions={"tracking_error": "minimize"},
                constraint_violations={"safety": 0.0},
                feasible=True,
                failure_rate=0.0,
                completed=True,
            ),
        )
    ]

    next_proposal = adapter.propose(_observation(adapter_id=adapter_id, ordinal=2, history=history))

    assert next_proposal.parameters != first.parameters
    assert next_proposal.candidate_ref != first.candidate_ref


def test_random_and_halton_receive_identical_information_and_budget() -> None:
    random_observation = _observation(adapter_id="random_search/v1")
    halton_payload = random_observation.model_dump(mode="json")
    halton_payload["benchmark_arm_id"] = "seeded-halton-v1"
    halton_observation = BenchmarkObservationV2.model_validate(halton_payload)

    random = create_benchmark_adapter("random_search/v1").propose(random_observation)
    halton = create_benchmark_adapter("seeded_halton/v1").propose(halton_observation)

    random_view = random_observation.model_dump(mode="json")
    halton_view = halton_observation.model_dump(mode="json")
    random_view.pop("benchmark_arm_id")
    halton_view.pop("benchmark_arm_id")
    assert random_view == halton_view
    assert "holdout" not in str(random_view).lower()
    assert (
        random.proposal_receipt["adapter_contract_id"]
        == halton.proposal_receipt["adapter_contract_id"]
    )


def test_adapters_fail_closed_on_bad_domain_or_exhausted_budget() -> None:
    bad_payload = _observation(adapter_id="random_search/v1").model_dump(mode="json")
    bad_payload["parameter_domain"][0]["unreviewed_hint"] = 1
    bad = BenchmarkObservationV2.model_validate(bad_payload)
    with pytest.raises(BenchmarkAdapterError, match="unsupported parameter-domain"):
        create_benchmark_adapter("random_search/v1").propose(bad)

    no_budget_payload = _observation(adapter_id="random_search/v1").model_dump(mode="json")
    no_budget_payload["simulator_budget_remaining"] = 0
    no_budget = BenchmarkObservationV2.model_validate(no_budget_payload)
    with pytest.raises(BenchmarkAdapterError, match="budget is exhausted"):
        create_benchmark_adapter("random_search/v1").propose(no_budget)


def test_registry_never_mislabels_product_inspired_code_as_a_reference() -> None:
    assert BENCHMARK_ADAPTER_REGISTRY["random_search/v1"].availability == "implemented"
    assert BENCHMARK_ADAPTER_REGISTRY["seeded_halton/v1"].availability == "implemented"
    assert BENCHMARK_ADAPTER_REGISTRY["bipop_cma_es/v1"].availability == "contract_only"
    assert BENCHMARK_ADAPTER_REGISTRY["reference_scbo/v1"].availability == "contract_only"
    assert (
        BENCHMARK_ADAPTER_REGISTRY["repo_constrained_mobo/v1"].method_classification
        == "product_native"
    )
    assert BENCHMARK_ADAPTER_REGISTRY["repo_constrained_mobo/v1"].availability == "implemented"
    assert BENCHMARK_ADAPTER_REGISTRY["optimizer_portfolio/v1"].availability == "implemented"
    with pytest.raises(ValueError, match="not implemented"):
        create_benchmark_adapter("reference_scbo/v1")


def _history_item(
    *,
    candidate_ref: str,
    dispatch_ordinal: int,
    parameters: dict[str, float],
    outcome: BenchmarkOptimizerOutcomeV1,
    screening_status: str = "passed",
    strategy: str = "constrained_mobo",
    adapter_id: str = "repo_constrained_mobo/v1",
    metadata: dict[str, object] | None = None,
) -> BenchmarkHistoryItemV2:
    return BenchmarkHistoryItemV2.model_validate(
        {
            "candidate_ref": candidate_ref,
            "generation_index": 0,
            "dispatch_ordinal": dispatch_ordinal,
            "parameters": parameters,
            "screening_status": screening_status,
            "proposal_context": {
                "proposal_adapter_id": adapter_id,
                "reason_code": "history-fixture",
                "proposal_receipt_sha256": "1" * 64,
                "optimizer_strategy": strategy,
                "optimizer_metadata": metadata or {},
            },
            "outcome": outcome.model_dump(mode="json"),
        }
    )


@pytest.mark.parametrize(
    ("adapter_id", "strategy"),
    (
        ("repo_constrained_mobo/v1", "constrained_mobo"),
        ("optimizer_portfolio/v1", "optimizer_portfolio"),
    ),
)
def test_product_native_adapters_use_the_same_v2_observation_contract(
    adapter_id: str,
    strategy: str,
) -> None:
    observation = _observation(adapter_id=adapter_id)
    adapter = create_benchmark_adapter(adapter_id)

    first = adapter.propose(observation)
    second = adapter.propose(observation)

    assert first == second
    assert first.proposal_receipt["method_classification"] == "product_native"
    assert first.proposal_receipt["native_strategy"] == strategy
    assert first.proposal_receipt["observation_sha256"] == canonical_sha256(observation)
    assert set(first.parameters) == {item["name"] for item in _domain()}


def test_native_history_translation_preserves_failures_and_quarantines_indeterminate() -> None:
    space = SearchSpace(
        tuple(
            ParameterDomain(
                name=str(item["name"]),
                baseline=float(item["baseline"]),
                minimum=float(item["minimum"]),
                maximum=float(item["maximum"]),
                step=None if item["step"] is None else float(item["step"]),
                scale=str(item["scale"]),
                value_type=str(item["value_type"]),
                choices=tuple(float(value) for value in item["choices"]),
            )
            for item in _domain()
        )
    )
    baseline = space.baseline()
    unsafe_parameters = space.from_unit_vector((0.95, 0.95, 0.95, 0.95))
    quarantined_parameters = space.from_unit_vector((0.2, 0.2, 0.2, 0.2))
    history = [
        _history_item(
            candidate_ref="objective-1",
            dispatch_ordinal=1,
            parameters=baseline,
            outcome=BenchmarkOptimizerOutcomeV1(
                role="objective",
                loss=0.25,
                objectives={"tracking_error": 0.25},
                objective_directions={"tracking_error": "minimize"},
                constraint_violations={"safety": 0.0},
                feasible=True,
                failure_rate=0.0,
                completed=True,
            ),
            metadata={"optimizer_generated_by": "constrained_mobo"},
        ),
        _history_item(
            candidate_ref="unsafe-2",
            dispatch_ordinal=2,
            parameters=unsafe_parameters,
            screening_status="unsafe",
            outcome=BenchmarkOptimizerOutcomeV1(
                role="constraint_only",
                loss=None,
                objectives={},
                objective_directions={},
                constraint_violations={"safety": 1.0},
                feasible=False,
                failure_rate=1.0,
                completed=True,
            ),
        ),
        _history_item(
            candidate_ref="indeterminate-3",
            dispatch_ordinal=3,
            parameters=quarantined_parameters,
            screening_status="indeterminate",
            outcome=BenchmarkOptimizerOutcomeV1(
                role="quarantined",
                loss=None,
                objectives={},
                objective_directions={},
                constraint_violations={},
                feasible=False,
                failure_rate=1.0,
                completed=True,
            ),
        ),
    ]
    request = native_optimizer_request_from_observation(
        _observation(adapter_id="repo_constrained_mobo/v1", history=history),
        strategy="constrained_mobo",
    )

    assert [item.candidate_id for item in request.observations] == ["objective-1", "unsafe-2"]
    assert request.observations[0].loss == 0.25
    assert request.observations[0].role == "objective"
    assert request.observations[0].optimizer_metadata["optimizer_generated_by"] == (
        "constrained_mobo"
    )
    assert request.observations[1].loss is None
    assert request.observations[1].objectives == {}
    assert request.observations[1].role == "constraint_only"
    assert request.observations[1].failure_rate == 1.0
    assert request.objective_weights == (("tracking_error", 1.0),)
    assert request.objective_normalizations == (("tracking_error", 1.0),)


def test_portfolio_native_metadata_round_trips_into_the_next_generation() -> None:
    adapter = create_benchmark_adapter("optimizer_portfolio/v1")
    first_observation = _observation(adapter_id="optimizer_portfolio/v1")
    first = adapter.propose(first_observation)
    native_metadata = dict(first.proposal_receipt["native_metadata"])
    child_strategy = str(native_metadata.get("child_strategy") or "optimizer_portfolio")
    history = [
        _history_item(
            candidate_ref=first.candidate_ref,
            dispatch_ordinal=1,
            parameters=first.parameters,
            outcome=BenchmarkOptimizerOutcomeV1(
                role="objective",
                loss=0.25,
                objectives={"tracking_error": 0.25},
                objective_directions={"tracking_error": "minimize"},
                constraint_violations={"safety": 0.0},
                feasible=True,
                failure_rate=0.0,
                completed=True,
            ),
            strategy=child_strategy,
            adapter_id="optimizer_portfolio/v1",
            metadata=native_metadata,
        )
    ]
    second_payload = _observation(
        adapter_id="optimizer_portfolio/v1",
        ordinal=2,
        history=history,
    ).model_dump(mode="json")
    second_payload["generation_index"] = 2
    second = adapter.propose(BenchmarkObservationV2.model_validate(second_payload))

    assert second.parameters != first.parameters
    assert second.proposal_receipt["native_strategy"] == "optimizer_portfolio"
    assert second.proposal_receipt["native_metadata"]["strategy"] == "optimizer_portfolio"


def test_numeric_landscape_is_deterministic_and_keeps_failures_in_the_denominator() -> None:
    space = SearchSpace(
        tuple(
            ParameterDomain(
                name=str(item["name"]),
                baseline=float(item["baseline"]),
                minimum=float(item["minimum"]),
                maximum=float(item["maximum"]),
                step=None if item["step"] is None else float(item["step"]),
                scale=str(item["scale"]),
                value_type=str(item["value_type"]),
                choices=tuple(float(value) for value in item["choices"]),
            )
            for item in _domain()
        )
    )
    evaluator = DeterministicConstrainedLandscapeV1(space)
    proposal = create_benchmark_adapter("random_search/v1").propose(
        _observation(adapter_id="random_search/v1")
    )

    first = evaluator.evaluate(proposal)
    second = evaluator.evaluate(deepcopy(proposal))

    assert first == second
    assert first.attempted_trials == 1
    assert first.completed_trials == 1
    assert first.status in {"passed", "failed", "unsafe"}
    assert len(first.evidence_sha256) == 64

    unsafe = evaluator.evaluate(
        BenchmarkProposalV1(
            candidate_ref="known-unsafe-candidate",
            parameters={"kp_xy": 2.5, "kd_xy": 1.0, "ki_xy": 0.3, "mode": 2.0},
            reason_code="negative-fixture",
        )
    )
    assert unsafe.status == "unsafe"
    assert unsafe.attempted_trials == 1
    assert unsafe.completed_trials == 1
    assert unsafe.safety_gates_passed is False
    assert unsafe.failure_code == "synthetic-unsafe-region"

    constrained_failure = evaluator.evaluate(
        BenchmarkProposalV1(
            candidate_ref="known-constraint-failure",
            parameters={"kp_xy": 0.5, "kd_xy": 0.05, "ki_xy": 0.01, "mode": 0.0},
            reason_code="negative-fixture",
        )
    )
    assert constrained_failure.status == "failed"
    assert constrained_failure.attempted_trials == 1
    assert constrained_failure.safety_gates_passed is True
    assert constrained_failure.failure_code == "synthetic-constraint-violation"


def test_numeric_landscape_rejects_partial_or_unknown_parameter_sets() -> None:
    space = SearchSpace((ParameterDomain("x", 0.5, 0.0, 1.0),))
    evaluator = DeterministicConstrainedLandscapeV1(space)
    proposal = create_benchmark_adapter("random_search/v1").propose(
        BenchmarkObservationV2(
            campaign_id="campaign-1",
            run_id="run-1",
            benchmark_arm_id="random-search",
            generation_index=1,
            next_dispatch_ordinal=1,
            algorithm_seed=1,
            simulator_seed_block_id="crn-1",
            parameter_domain=[{"name": "x", "baseline": 0.5, "minimum": 0.0, "maximum": 1.0}],
            objectives=[{"name": "loss", "direction": "minimize"}],
            constraints=[],
            failure_semantics={},
            simulator_budget_remaining=1,
            wall_time_remaining_ms=1,
        )
    )
    mutated = proposal.model_copy(update={"parameters": {"unknown": 0.5}})
    with pytest.raises(ValueError, match="parameter set differs"):
        evaluator.evaluate(mutated)
