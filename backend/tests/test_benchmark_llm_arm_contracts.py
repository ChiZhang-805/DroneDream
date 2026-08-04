from __future__ import annotations

import json

import pytest

from app.benchmarking.contracts import BenchmarkObservationV2
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES,
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    BENCHMARK_LLM_MAX_RESPONSE_BYTES,
    BENCHMARK_LLM_MAX_TURNS_PER_GENERATION,
    BenchmarkLLMContractError,
    assert_unique_turn_bindings,
    build_llm_turn_request,
    fair_provider_evidence,
    parse_bounded_json_response,
    proposal_response_schema,
    require_llm_arm_policy,
    selection_response_schema,
    tool_action_response_schema,
    validate_proposal_response,
    validate_selection_response,
    validate_tool_action_response,
)


def _observation(adapter_id: str, *, run_id: str = "run-1") -> BenchmarkObservationV2:
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id=run_id,
        benchmark_arm_id=adapter_id.replace("/", "-"),
        generation_index=1,
        next_dispatch_ordinal=1,
        algorithm_seed=20260804,
        simulator_seed_block_id="paired-crn-1",
        parameter_domain=[
            {
                "name": "kp",
                "baseline": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "value_type": "float",
                "scale": "linear",
            },
            {
                "name": "mode",
                "baseline": 1.0,
                "minimum": 0.0,
                "maximum": 2.0,
                "value_type": "enum",
                "choices": [0.0, 1.0, 2.0],
                "scale": "linear",
            },
        ],
        objectives=[{"name": "rmse", "direction": "minimize"}],
        constraints=[{"name": "max_error", "operator": "le", "threshold": 1.0}],
        history=[],
        failure_semantics={"unsafe": "constraint-only", "timeout": "terminal"},
        simulator_budget_remaining=16,
        wall_time_remaining_ms=30_000,
    )


def test_five_llm_policies_have_bounded_preregistered_turn_semantics() -> None:
    assert set(BENCHMARK_LLM_ARM_POLICIES) == {
        "llm_direct/v1",
        "llm_react/v1",
        "llambo_uav/v1",
        "dronedream_fixed_two_turn/v1",
        "dronedream_adaptive_1_4/v1",
    }
    assert len(BENCHMARK_LLM_ARM_POLICIES_SHA256) == 64
    assert BENCHMARK_LLM_ARM_POLICIES["llm_direct/v1"].maximum_turns_per_generation == 1
    assert (
        BENCHMARK_LLM_ARM_POLICIES["dronedream_fixed_two_turn/v1"].maximum_turns_per_generation == 2
    )
    assert (
        BENCHMARK_LLM_ARM_POLICIES["dronedream_adaptive_1_4/v1"].maximum_turns_per_generation
        == BENCHMARK_LLM_MAX_TURNS_PER_GENERATION
    )
    assert all(policy.provider_retry_cap == 0 for policy in BENCHMARK_LLM_ARM_POLICIES.values())


def test_provider_view_is_identical_across_arm_run_and_campaign_identifiers() -> None:
    direct = _observation("llm_direct/v1", run_id="direct-run")
    adaptive_payload = direct.model_dump(mode="json")
    adaptive_payload.update(
        {
            "campaign_id": "another-campaign",
            "run_id": "adaptive-run",
            "benchmark_arm_id": "dronedream-adaptive-1-4-v1",
        }
    )
    adaptive = BenchmarkObservationV2.model_validate(adaptive_payload)

    assert fair_provider_evidence(direct) == fair_provider_evidence(adaptive)
    serialized = json.dumps(fair_provider_evidence(direct), sort_keys=True).lower()
    assert "holdout" in serialized
    assert "false" in serialized
    assert "direct-run" not in serialized
    assert "llm_direct" not in serialized


def test_turn_request_binds_prompt_evidence_schema_and_tool_outputs_without_receipt_text() -> None:
    observation = _observation("llm_direct/v1")
    policy = require_llm_arm_policy("llm_direct/v1")
    request = build_llm_turn_request(
        policy=policy,
        observation=observation,
        model_snapshot="fixture-model-v1",
        turn_index=1,
        turn_role="direct_proposal",
        response_schema=proposal_response_schema(observation),
    )
    receipt = request.receipt_payload()

    assert len(request.binding_sha256) == 64
    assert len(request.prompt_sha256) == 64
    assert "system" not in receipt
    assert "user" not in receipt
    assert "response_schema" not in receipt
    assert "provider_request_id" not in str(receipt)
    assert policy.adapter_id not in request.user
    assert_unique_turn_bindings((request,))
    with pytest.raises(BenchmarkLLMContractError, match="duplicate"):
        assert_unique_turn_bindings((request, request))


def test_turn_role_and_cap_are_fail_closed() -> None:
    observation = _observation("llm_direct/v1")
    policy = require_llm_arm_policy("llm_direct/v1")
    with pytest.raises(BenchmarkLLMContractError, match="not allowed"):
        build_llm_turn_request(
            policy=policy,
            observation=observation,
            model_snapshot="fixture-model-v1",
            turn_index=1,
            turn_role="critic",
            response_schema=proposal_response_schema(observation),
        )
    with pytest.raises(BenchmarkLLMContractError, match="turn cap"):
        build_llm_turn_request(
            policy=policy,
            observation=observation,
            model_snapshot="fixture-model-v1",
            turn_index=2,
            turn_role="direct_proposal",
            response_schema=proposal_response_schema(observation),
        )

    fixed_policy = require_llm_arm_policy("dronedream_fixed_two_turn/v1")
    with pytest.raises(BenchmarkLLMContractError, match="must use role revision"):
        build_llm_turn_request(
            policy=fixed_policy,
            observation=observation,
            model_snapshot="fixture-model-v1",
            turn_index=2,
            turn_role="plan",
            response_schema=proposal_response_schema(observation),
        )


def test_proposal_validation_rejects_extra_missing_nonfinite_and_out_of_bounds_values() -> None:
    observation = _observation("llm_direct/v1")
    valid = {
        "schema_version": "1.0",
        "decision": "propose",
        "parameters": {"kp": 1.25, "mode": 2},
    }
    assert validate_proposal_response(valid, observation) == {"kp": 1.25, "mode": 2.0}

    for invalid in (
        {**valid, "extra": True},
        {**valid, "parameters": {"kp": 1.25}},
        {**valid, "parameters": {"kp": float("nan"), "mode": 1}},
        {**valid, "parameters": {"kp": 9.0, "mode": 1}},
    ):
        with pytest.raises(BenchmarkLLMContractError):
            validate_proposal_response(invalid, observation)


def test_tool_and_selection_schemas_allow_only_preregistered_existing_refs() -> None:
    policy = require_llm_arm_policy("dronedream_fixed_two_turn/v1")
    schema = tool_action_response_schema(policy)
    assert "optimizer_portfolio/v1" in str(schema)
    assert validate_tool_action_response(
        {
            "schema_version": "1.0",
            "decision": "act",
            "tool_adapter_ids": ["optimizer_portfolio/v1"],
        },
        policy,
    ) == ("act", ("optimizer_portfolio/v1",))
    with pytest.raises(BenchmarkLLMContractError, match="unreviewed"):
        validate_tool_action_response(
            {
                "schema_version": "1.0",
                "decision": "act",
                "tool_adapter_ids": ["shell/v1"],
            },
            policy,
        )

    refs = ("proposal_0", "proposal_1")
    assert "proposal_0" in str(selection_response_schema(refs))
    assert (
        validate_selection_response(
            {
                "schema_version": "1.0",
                "decision": "dispatch",
                "selected_proposal_ref": "proposal_1",
            },
            refs,
        )
        == "proposal_1"
    )
    with pytest.raises(BenchmarkLLMContractError, match="unknown"):
        validate_selection_response(
            {
                "schema_version": "1.0",
                "decision": "dispatch",
                "selected_proposal_ref": "proposal_9",
            },
            refs,
        )


def test_response_parser_has_a_hard_utf8_cap_and_rejects_nonfinite_json() -> None:
    assert parse_bounded_json_response('{"ok":true}') == {"ok": True}
    with pytest.raises(BenchmarkLLMContractError, match="finite JSON"):
        parse_bounded_json_response('{"value":NaN}')
    with pytest.raises(BenchmarkLLMContractError, match="exceeds"):
        parse_bounded_json_response("x" * (BENCHMARK_LLM_MAX_RESPONSE_BYTES + 1))
