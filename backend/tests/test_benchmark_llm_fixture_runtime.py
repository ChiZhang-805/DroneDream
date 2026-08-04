from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from app.benchmarking.contracts import BenchmarkObservationV2, BenchmarkProposalV1
from app.benchmarking.llm_arm_contracts import BenchmarkLLMTurnRequestV1
from app.benchmarking.llm_fixture_runtime import (
    BenchmarkLLMFixtureExecutionError,
    evaluate_benchmark_adaptive_triggers,
    execute_offline_llm_arm,
)

FixtureResponse = str | Exception | Callable[[BenchmarkLLMTurnRequestV1], str]


@dataclass
class _SequenceProvider:
    responses: list[FixtureResponse]
    fixture_only: bool = True
    requests: list[BenchmarkLLMTurnRequestV1] = field(default_factory=list)

    def complete(self, request: BenchmarkLLMTurnRequestV1) -> str:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("fixture sequence exhausted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(request)
        return response


def _history_item(
    *,
    ordinal: int,
    loss: float,
    parameters: dict[str, float] | None = None,
    predicted_loss: float | None = None,
) -> dict[str, object]:
    metadata = {} if predicted_loss is None else {"predicted_loss": predicted_loss}
    return {
        "candidate_ref": f"history-{ordinal}",
        "generation_index": ordinal - 1,
        "dispatch_ordinal": ordinal,
        "parameters": parameters or {"kp": 1.0},
        "screening_status": "passed",
        "proposal_context": {
            "proposal_adapter_id": "random_search/v1",
            "reason_code": "fixture",
            "proposal_receipt_sha256": "a" * 64,
            "optimizer_metadata": metadata,
        },
        "outcome": {
            "role": "objective",
            "loss": loss,
            "objectives": {"rmse": loss},
            "objective_directions": {"rmse": "minimize"},
            "constraint_violations": {},
            "feasible": True,
            "failure_rate": 0.0,
            "completed": True,
        },
    }


def _observation(
    adapter_id: str,
    *,
    generation_index: int = 1,
    discrete: bool = False,
    stagnant: bool = False,
) -> BenchmarkObservationV2:
    domain: list[dict[str, object]]
    if discrete:
        domain = [
            {
                "name": "mode",
                "baseline": 0.0,
                "minimum": 0.0,
                "maximum": 1.0,
                "value_type": "enum",
                "choices": [0.0, 1.0],
            }
        ]
    else:
        domain = [
            {
                "name": "kp",
                "baseline": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "value_type": "float",
            }
        ]
    history_parameters = {"mode": 0.0} if discrete else {"kp": 1.0}
    history = (
        [
            _history_item(ordinal=1, loss=1.0, parameters=history_parameters),
            _history_item(ordinal=2, loss=1.0, parameters=history_parameters),
            _history_item(ordinal=3, loss=1.0, parameters=history_parameters),
        ]
        if stagnant
        else []
    )
    return BenchmarkObservationV2(
        campaign_id="campaign-fixture",
        run_id="run-fixture",
        benchmark_arm_id=adapter_id.replace("/", "-"),
        generation_index=generation_index,
        next_dispatch_ordinal=4 if stagnant else 1,
        algorithm_seed=20260804,
        simulator_seed_block_id="paired-crn-1",
        parameter_domain=domain,
        objectives=[{"name": "rmse", "direction": "minimize"}],
        constraints=[{"name": "max_error", "operator": "le", "threshold": 1.0}],
        history=history,
        failure_semantics={"unsafe": "constraint-only", "timeout": "terminal"},
        simulator_budget_remaining=16,
        wall_time_remaining_ms=30_000,
    )


def _proposal_json(*, parameter: str = "kp", value: float = 1.2) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "propose",
            "parameters": {parameter: value},
        }
    )


def _act_json(*tools: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "act",
            "tool_adapter_ids": list(tools),
        }
    )


def _stop_json() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "stop",
            "tool_adapter_ids": [],
        }
    )


def _react_act_json(*tools: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "act",
            "tool_adapter_ids": list(tools),
            "selected_proposal_ref": None,
        }
    )


def _select_first(request: BenchmarkLLMTurnRequestV1) -> str:
    payload = json.loads(request.user)
    proposal_ref = payload["tool_outputs"][0]["proposal_ref"]
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "dispatch",
            "selected_proposal_ref": proposal_ref,
        }
    )


def _react_dispatch_first(request: BenchmarkLLMTurnRequestV1) -> str:
    payload = json.loads(request.user)
    proposal_ref = payload["tool_outputs"][0]["proposal_ref"]
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "dispatch",
            "tool_adapter_ids": [],
            "selected_proposal_ref": proposal_ref,
        }
    )


def _diagnosis_keep(request: BenchmarkLLMTurnRequestV1) -> str:
    payload = json.loads(request.user)
    proposal_ref = payload["tool_outputs"][0]["proposal_ref"]
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "keep",
            "selected_proposal_ref": proposal_ref,
        }
    )


def _critic_approve(request: BenchmarkLLMTurnRequestV1) -> str:
    payload = json.loads(request.user)
    selected = payload["tool_outputs"][-1]["selected_proposal_ref"]
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "approve",
            "selected_proposal_ref": selected,
        }
    )


@pytest.mark.parametrize(
    ("adapter_id", "role"),
    [
        ("llm_direct/v1", "direct_proposal"),
        ("llambo_uav/v1", "llambo_proposal"),
    ],
)
def test_single_turn_arms_produce_one_bounded_fixture_proposal(
    adapter_id: str,
    role: str,
) -> None:
    provider = _SequenceProvider([_proposal_json()])
    result = execute_offline_llm_arm(adapter_id, _observation(adapter_id), provider=provider)

    assert result.status == "proposal"
    assert result.provider_turns_attempted == result.provider_turns_succeeded == 1
    assert provider.requests[0].turn_role == role
    assert result.proposal is not None
    assert result.proposal.parameters == {"kp": 1.2}
    assert "system" not in str(result.proposal.proposal_receipt)
    assert "user" not in str(result.proposal.proposal_receipt)


def test_frozen_first_qualified_is_zero_turn_for_every_llm_arm() -> None:
    for adapter_id in (
        "llm_direct/v1",
        "llm_react/v1",
        "llambo_uav/v1",
        "dronedream_fixed_two_turn/v1",
        "dronedream_adaptive_1_4/v1",
    ):
        provider = _SequenceProvider([RuntimeError("must not be called")])
        result = execute_offline_llm_arm(
            adapter_id,
            _observation(adapter_id),
            provider=provider,
            first_qualified_frozen=True,
        )
        assert result.status == "first_qualified_stop"
        assert result.provider_turns_attempted == result.provider_turns_succeeded == 0
        assert not provider.requests


def test_react_executes_allowlisted_tool_then_dispatches_existing_proposal() -> None:
    provider = _SequenceProvider([_react_act_json("random_search/v1"), _react_dispatch_first])
    result = execute_offline_llm_arm(
        "llm_react/v1",
        _observation("llm_react/v1"),
        provider=provider,
    )

    assert result.status == "proposal"
    assert result.provider_turns_attempted == 2
    assert [request.turn_index for request in provider.requests] == [1, 2]


def test_react_can_use_full_four_turn_budget_but_cannot_act_on_last_turn() -> None:
    provider = _SequenceProvider(
        [
            _react_act_json("random_search/v1"),
            _react_act_json("seeded_halton/v1"),
            _react_act_json("repo_constrained_mobo/v1"),
            _react_dispatch_first,
        ]
    )
    result = execute_offline_llm_arm(
        "llm_react/v1",
        _observation("llm_react/v1"),
        provider=provider,
    )
    assert result.provider_turns_attempted == 4
    final_schema = provider.requests[-1].response_schema
    assert "act" not in final_schema["properties"]["decision"]["enum"]


def test_react_rejects_repeated_local_tool_without_silently_spending_more_turns() -> None:
    provider = _SequenceProvider(
        [_react_act_json("random_search/v1"), _react_act_json("random_search/v1")]
    )
    with pytest.raises(BenchmarkLLMFixtureExecutionError) as exc_info:
        execute_offline_llm_arm(
            "llm_react/v1",
            _observation("llm_react/v1"),
            provider=provider,
        )
    assert exc_info.value.code == "react_state_rejected"
    assert exc_info.value.safe_receipt["provider_turns_attempted"] == 2
    assert exc_info.value.safe_receipt["provider_turns_succeeded"] == 2


def test_fixed_two_turn_requires_plan_and_revision() -> None:
    provider = _SequenceProvider([_act_json("random_search/v1"), _select_first])
    result = execute_offline_llm_arm(
        "dronedream_fixed_two_turn/v1",
        _observation("dronedream_fixed_two_turn/v1"),
        provider=provider,
    )
    assert result.status == "proposal"
    assert result.provider_turns_attempted == 2
    assert [request.turn_role for request in provider.requests] == ["plan", "revision"]

    stopped = _SequenceProvider([_stop_json()])
    with pytest.raises(BenchmarkLLMFixtureExecutionError) as exc_info:
        execute_offline_llm_arm(
            "dronedream_fixed_two_turn/v1",
            _observation("dronedream_fixed_two_turn/v1"),
            provider=stopped,
        )
    assert exc_info.value.code == "plan_schema_rejected"


def test_adaptive_supports_one_turn_stop_and_default_two_turn_proposal() -> None:
    stopped = execute_offline_llm_arm(
        "dronedream_adaptive_1_4/v1",
        _observation("dronedream_adaptive_1_4/v1"),
        provider=_SequenceProvider([_stop_json()]),
    )
    assert stopped.status == "abandoned"
    assert stopped.provider_turns_attempted == 1

    provider = _SequenceProvider([_act_json("random_search/v1"), _select_first])
    result = execute_offline_llm_arm(
        "dronedream_adaptive_1_4/v1",
        _observation("dronedream_adaptive_1_4/v1"),
        provider=provider,
    )
    assert result.status == "proposal"
    assert result.provider_turns_attempted == 2
    assert result.trigger_decision is not None
    assert not result.trigger_decision.diagnosis_reasons
    assert not result.trigger_decision.critic_reasons


def test_adaptive_uses_diagnosis_as_third_turn_for_stagnation() -> None:
    provider = _SequenceProvider([_act_json("random_search/v1"), _select_first, _diagnosis_keep])
    result = execute_offline_llm_arm(
        "dronedream_adaptive_1_4/v1",
        _observation("dronedream_adaptive_1_4/v1", stagnant=True),
        provider=provider,
    )
    assert result.status == "proposal"
    assert result.provider_turns_attempted == 3
    assert [request.turn_index for request in provider.requests] == [1, 2, 3]
    assert result.trigger_decision is not None
    assert "trailing_stagnation" in result.trigger_decision.diagnosis_reasons


def test_adaptive_can_skip_t3_and_use_critic_at_turn_index_four() -> None:
    provider = _SequenceProvider([_act_json("random_search/v1"), _select_first, _critic_approve])
    result = execute_offline_llm_arm(
        "dronedream_adaptive_1_4/v1",
        _observation("dronedream_adaptive_1_4/v1", discrete=True),
        provider=provider,
    )
    assert result.status == "proposal"
    assert result.provider_turns_attempted == 3
    assert [request.turn_index for request in provider.requests] == [1, 2, 4]
    assert result.trigger_decision is not None
    assert result.trigger_decision.critic_reasons == ("hard_boundary_candidate",)


def test_adaptive_uses_all_four_turns_when_diagnosis_and_critic_trigger() -> None:
    provider = _SequenceProvider(
        [_act_json("random_search/v1"), _select_first, _diagnosis_keep, _critic_approve]
    )
    result = execute_offline_llm_arm(
        "dronedream_adaptive_1_4/v1",
        _observation("dronedream_adaptive_1_4/v1", discrete=True, stagnant=True),
        provider=provider,
    )
    assert result.status == "proposal"
    assert result.provider_turns_attempted == 4
    assert [request.turn_role for request in provider.requests] == [
        "plan",
        "revision",
        "diagnosis",
        "critic",
    ]


def test_trigger_cooldown_suppresses_same_severity_but_allows_severity_upgrade() -> None:
    observation = _observation(
        "dronedream_adaptive_1_4/v1",
        generation_index=2,
        discrete=True,
        stagnant=True,
    )
    selected = BenchmarkProposalV1(
        candidate_ref="selected",
        parameters={"mode": 0.0},
        reason_code="fixture",
    )
    decision = evaluate_benchmark_adaptive_triggers(
        observation,
        [selected],
        selected,
        previous_family_state={"progress": (1, 1), "boundary": (1, 1)},
    )
    assert "trailing_stagnation" in decision.suppressed_by_cooldown
    assert "trailing_stagnation" not in decision.diagnosis_reasons
    assert "hard_boundary_candidate" in decision.critic_reasons


def test_provider_failure_and_invalid_response_are_safe_and_counted_without_raw_text() -> None:
    provider = _SequenceProvider([RuntimeError("TOP-SECRET-PROVIDER-DETAIL")])
    with pytest.raises(BenchmarkLLMFixtureExecutionError) as failed:
        execute_offline_llm_arm(
            "llm_direct/v1",
            _observation("llm_direct/v1"),
            provider=provider,
        )
    assert failed.value.code == "fixture_provider_failed"
    assert failed.value.safe_receipt["provider_turns_attempted"] == 1
    assert failed.value.safe_receipt["provider_turns_succeeded"] == 0
    assert "TOP-SECRET" not in str(failed.value)
    assert "TOP-SECRET" not in str(failed.value.safe_receipt)

    invalid = _SequenceProvider(['{"value":NaN}'])
    with pytest.raises(BenchmarkLLMFixtureExecutionError) as rejected:
        execute_offline_llm_arm(
            "llm_direct/v1",
            _observation("llm_direct/v1"),
            provider=invalid,
        )
    assert rejected.value.code == "fixture_provider_response_invalid"
    assert rejected.value.safe_receipt["provider_turns_succeeded"] == 1
    assert len(rejected.value.safe_receipt["response_sha256"]) == 1
    assert "NaN" not in str(rejected.value.safe_receipt)


def test_non_fixture_provider_is_rejected_before_any_call() -> None:
    provider = _SequenceProvider([_proposal_json()], fixture_only=False)
    with pytest.raises(BenchmarkLLMFixtureExecutionError) as exc_info:
        execute_offline_llm_arm(
            "llm_direct/v1",
            _observation("llm_direct/v1"),
            provider=provider,
        )
    assert exc_info.value.code == "provider_is_not_offline_fixture"
    assert not provider.requests
