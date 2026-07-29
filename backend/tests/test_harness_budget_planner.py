"""Contract tests for bounded multi-tool planning and the optional second turn."""

from __future__ import annotations

import json
import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.orchestration.harness_budget_planner import (
    HarnessGenerationPlan,
    HarnessPlanUncertainty,
    HarnessStopRecommendation,
    HarnessToolAllocation,
    build_budget_opportunity,
    build_budget_plan_messages,
    build_plan_revision_messages,
    compile_generation_plan,
    deterministic_fallback_plan,
    deterministic_revision_fallback,
    generation_plan_schema,
    plan_revision_schema,
    proposal_summary,
    validate_generation_plan,
    validate_plan_revision,
)


def _opportunity(**overrides: object):
    values = {
        "generation": 4,
        "remaining_trials": 48,
        "full_trials_per_candidate": 8,
        "candidate_capacity": 4,
        "allowed_tools": (
            "constrained_mobo",
            "turbo",
            "bipop_cma_es",
            "optimizer_portfolio",
        ),
        "stop_reasons": ("converged", "budget_efficiency_stalled"),
    }
    values.update(overrides)
    return build_budget_opportunity(**values)  # type: ignore[arg-type]


def _valid_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "decision": "continue",
        "generation_goal": "Pair constraint recovery with bounded local refinement.",
        "tool_calls": [
            {
                "tool_id": "turbo",
                "allocation": 2,
                "fidelity_mode": "force_full",
                "focus": ["local_improvement"],
            },
            {
                "tool_id": "constrained_mobo",
                "allocation": 1,
                "fidelity_mode": "auto",
                "focus": ["constraints"],
            },
        ],
        "stop": {"recommended": False, "reason_code": None},
        "uncertainty": {
            "level": "medium",
            "missing_evidence": ["local_curvature"],
        },
    }


def test_opportunity_bounds_capacity_by_remaining_full_trial_budget() -> None:
    opportunity = _opportunity(
        remaining_trials=18,
        full_trials_per_candidate=8,
        candidate_capacity=8,
    )

    assert opportunity.candidate_capacity == 2
    assert opportunity.discretionary_candidates == 2
    assert all(item.maximum_allocation <= 2 for item in opportunity.tool_budgets)
    assert opportunity.stop_eligible is True
    assert opportunity.accepted_stop_reasons == (
        "converged",
        "budget_efficiency_stalled",
    )


def test_tool_execution_rejects_proposals_above_compiled_allocation(
    monkeypatch,
) -> None:
    from app.orchestration import job_manager
    from app.orchestration.harness_budget_planner import HarnessCompiledToolCall
    from app.orchestration.optimizer import CandidateProposal

    proposal = CandidateProposal(
        generation_index=4,
        label="overflow",
        strategy="test",
        parameters={"MPC_XY_P": 1.0},
    )
    monkeypatch.setattr(
        job_manager,
        "execute_prepared_experimental_generation",
        lambda _prepared: [proposal, proposal],
    )
    prepared = job_manager._PreparedHarnessToolCall(
        call=HarnessCompiledToolCall(
            call_id="call_" + "a" * 24,
            ordinal=0,
            tool_id="turbo",
            allocation=1,
            fidelity_mode="auto",
            parallel_safe=True,
            latency_budget_ms=10_000,
            cpu_budget_ms=10_000,
            projected_trial_upper_bound=4,
        ),
        prepared=None,  # type: ignore[arg-type]
    )

    result = job_manager._run_harness_tool_call(prepared)

    assert result.status == "tool_error"
    assert result.proposals == ()
    assert result.error_type == "ProposalCountExceeded"


def test_valid_multi_tool_plan_is_costed_and_compiled_in_canonical_order() -> None:
    opportunity = _opportunity()

    plan, report = validate_generation_plan(_valid_plan(), opportunity)

    assert plan is not None
    assert report.accepted is True
    assert report.projected_candidate_count == 3
    assert report.projected_trial_upper_bound == 24
    assert report.projected_serial_latency_budget_ms == 6_450
    assert report.projected_critical_path_latency_budget_ms == 3_250
    assert report.projected_cpu_budget_ms == 6_450

    compiled = compile_generation_plan(plan, opportunity)
    assert [item.tool_id for item in compiled.calls] == [
        "constrained_mobo",
        "turbo",
    ]
    assert [item.allocation for item in compiled.calls] == [1, 2]
    assert len({item.call_id for item in compiled.calls}) == 2
    assert compiled.plan_sha256 == compile_generation_plan(plan, opportunity).plan_sha256

    permuted = _valid_plan()
    permuted_calls = permuted["tool_calls"]
    assert isinstance(permuted_calls, list)
    permuted["tool_calls"] = list(reversed(permuted_calls))
    permuted_plan, permuted_report = validate_generation_plan(permuted, opportunity)
    assert permuted_plan is not None and permuted_report.accepted
    assert compile_generation_plan(permuted_plan, opportunity).plan_sha256 == (
        compiled.plan_sha256
    )


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda payload: payload["tool_calls"].append(  # type: ignore[union-attr]
                {
                    "tool_id": "turbo",
                    "allocation": 1,
                    "fidelity_mode": "auto",
                    "focus": [],
                }
            ),
            "duplicate_or_ineligible_tool",
        ),
        (
            lambda payload: payload["tool_calls"][0].update(  # type: ignore[index,union-attr]
                {"tool_id": "saasbo"}
            ),
            "duplicate_or_ineligible_tool",
        ),
        (
            lambda payload: payload["tool_calls"][0].update(  # type: ignore[index,union-attr]
                {"allocation": 4}
            ),
            "allocation_exceeds_budget",
        ),
    ],
)
def test_plan_validator_rejects_unauthorized_or_oversized_allocations(
    mutator: Callable[[dict[str, object]], None],
    expected_code: str,
) -> None:
    payload = _valid_plan()
    mutator(payload)

    plan, report = validate_generation_plan(payload, _opportunity())

    assert plan is None
    assert report.accepted is False
    assert expected_code in {item.code for item in report.rule_results if not item.passed}


def test_plan_validator_rejects_latency_and_cpu_budget_overruns() -> None:
    opportunity = _opportunity(
        generation_latency_budget_ms=3_000,
        generation_cpu_budget_ms=6_000,
    )

    plan, report = validate_generation_plan(_valid_plan(), opportunity)

    assert plan is None
    assert {item.code for item in report.rule_results if not item.passed} == {
        "latency_budget_exceeded",
        "cpu_budget_exceeded",
    }


def test_schema_and_decision_shapes_fail_closed_without_repair() -> None:
    payload = _valid_plan()
    payload["unexpected"] = "not allowed"
    plan, report = validate_generation_plan(payload, _opportunity())
    assert plan is None
    assert report.rule_results[0].code == "invalid_schema"

    payload = _valid_plan()
    payload["decision"] = "stop"
    plan, report = validate_generation_plan(payload, _opportunity())
    assert plan is None
    assert report.rule_results[0].code == "invalid_schema"


def test_stop_recommendation_requires_deterministic_policy_authority() -> None:
    payload = {
        "schema_version": "1.0",
        "decision": "stop",
        "generation_goal": "Stop after verified convergence.",
        "tool_calls": [],
        "stop": {"recommended": True, "reason_code": "converged"},
        "uncertainty": {"level": "low", "missing_evidence": []},
    }

    accepted, accepted_report = validate_generation_plan(payload, _opportunity())
    rejected, rejected_report = validate_generation_plan(
        payload,
        _opportunity(stop_reasons=()),
    )

    assert accepted is not None and accepted.decision == "stop"
    assert accepted_report.accepted is True
    assert rejected is None
    assert "stop_not_authorized" in {
        item.code for item in rejected_report.rule_results if not item.passed
    }


def test_deterministic_fallback_uses_portfolio_without_model_attribution() -> None:
    compiled = deterministic_fallback_plan(_opportunity())

    assert len(compiled.calls) == 1
    assert compiled.calls[0].tool_id == "optimizer_portfolio"
    assert compiled.calls[0].allocation == 4
    assert compiled.projected_trial_upper_bound == 32


def test_dynamic_schemas_are_closed_and_request_scoped() -> None:
    opportunity = _opportunity()
    first_schema = generation_plan_schema(opportunity)
    tool_item = first_schema["properties"]["tool_calls"]["items"]  # type: ignore[index]
    assert first_schema["additionalProperties"] is False
    assert tool_item["additionalProperties"] is False
    assert tool_item["properties"]["tool_id"]["enum"] == [  # type: ignore[index]
        "constrained_mobo",
        "turbo",
        "bipop_cma_es",
        "optimizer_portfolio",
    ]

    _, user = build_budget_plan_messages(
        evidence_snapshot={"safe": True},
        opportunity=opportunity,
        tool_manifest={"tools": []},
    )
    payload = json.loads(user)
    assert payload["budget_opportunity"]["remaining_trials"] == 48
    assert "job_id" not in user
    assert "api_key" not in user


def _proposal_summaries():
    return (
        proposal_summary(
            proposal_ref="proposal_0",
            tool_id="constrained_mobo",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.25,
        ),
        proposal_summary(
            proposal_ref="proposal_1",
            tool_id="turbo",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.1,
        ),
        proposal_summary(
            proposal_ref="proposal_2",
            tool_id="turbo",
            tool_candidate_ordinal=1,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.15,
        ),
    )


def test_second_turn_selects_only_bounded_typed_proposal_references() -> None:
    proposals = _proposal_summaries()
    raw = {
        "schema_version": "1.0",
        "decision": "dispatch",
        "selected_proposal_refs": ["proposal_1", "proposal_0"],
        "rationale": "Preserve complementary local and constrained candidates.",
    }

    revision, report = validate_plan_revision(
        raw,
        proposals=proposals,
        maximum_dispatch_candidates=2,
    )

    assert revision is not None
    assert report.accepted is True
    assert report.selected_proposal_refs == ("proposal_1", "proposal_0")
    schema = plan_revision_schema(proposals, maximum_dispatch_candidates=2)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["selected_proposal_refs"]["items"]["enum"] == [  # type: ignore[index]
        "proposal_0",
        "proposal_1",
        "proposal_2",
    ]


@pytest.mark.parametrize(
    ("selected", "expected_code"),
    [
        (["proposal_9"], "unknown_proposal_reference"),
        (["proposal_0", "proposal_1", "proposal_2"], "dispatch_capacity_exceeded"),
    ],
)
def test_second_turn_rejects_unknown_or_over_budget_references(
    selected: list[str],
    expected_code: str,
) -> None:
    revision, report = validate_plan_revision(
        {
            "schema_version": "1.0",
            "decision": "dispatch",
            "selected_proposal_refs": selected,
            "rationale": "bounded",
        },
        proposals=_proposal_summaries(),
        maximum_dispatch_candidates=2,
    )

    assert revision is None
    assert report.accepted is False
    assert report.rejection_code == expected_code


def test_second_turn_abandon_requires_policy_and_invalid_response_falls_back() -> None:
    proposals = _proposal_summaries()
    abandoned, rejected = validate_plan_revision(
        {
            "schema_version": "1.0",
            "decision": "abandon",
            "selected_proposal_refs": [],
            "rationale": "No candidate is sufficiently distinct.",
        },
        proposals=proposals,
        maximum_dispatch_candidates=2,
        allow_abandon=False,
    )
    assert abandoned is None
    assert rejected.rejection_code == "abandon_not_authorized"

    fallback = deterministic_revision_fallback(
        proposals,
        maximum_dispatch_candidates=2,
        rejection_code="invalid_schema",
    )
    assert fallback.accepted is True
    assert fallback.fallback_used is True
    assert fallback.selected_proposal_refs == ("proposal_0", "proposal_1")


def test_revision_prompt_contains_no_raw_parameter_values_or_stable_ids() -> None:
    opportunity = _opportunity()
    plan, report = validate_generation_plan(_valid_plan(), opportunity)
    assert plan is not None and report.accepted
    compiled = compile_generation_plan(plan, opportunity)

    _, user = build_plan_revision_messages(
        compiled_plan=compiled,
        proposals=_proposal_summaries(),
        maximum_dispatch_candidates=2,
    )

    payload = json.loads(user)
    assert payload["compiled_plan_sha256"] == compiled.plan_sha256
    assert all("parameters" not in item for item in payload["proposals"])
    assert "candidate_id" not in user
    assert "job_id" not in user


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True])
def test_proposal_summary_rejects_nonfinite_or_boolean_values(value: object) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        proposal_summary(
            proposal_ref="proposal_0",
            tool_id="turbo",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=value,  # type: ignore[arg-type]
        )


def test_strict_models_reject_post_construction_mutation() -> None:
    plan = HarnessGenerationPlan(
        decision="continue",
        generation_goal="bounded",
        tool_calls=(
            HarnessToolAllocation(
                tool_id="turbo",
                allocation=1,
                fidelity_mode="auto",
            ),
        ),
        stop=HarnessStopRecommendation(recommended=False, reason_code=None),
        uncertainty=HarnessPlanUncertainty(level="low"),
    )

    with pytest.raises(ValidationError):
        plan.generation_goal = "mutated"  # type: ignore[misc]
