"""Reject ambiguous JSON and mutated contracts at the final Harness boundary."""

import hashlib
import json

import pytest

from app.model_harness.control_plane import (
    HarnessControlPlaneReceipt,
    HarnessInputEnvelope,
    HarnessOutputEnvelope,
    PluginSelection,
    compile_control_plane_receipt,
    harness_input_sha256,
    validate_output_against_control_plane,
)


def _input(receipt):
    """Build a valid owner/task binding without opening a cloud session."""
    return HarnessInputEnvelope(
        request_id="request-boundary",
        task_id="task-boundary",
        thread_id="thread-boundary",
        owner_binding_sha256="1" * 64,
        tenant_binding_sha256="2" * 64,
        source_edition="autonomy",
        domain=receipt.domain,
        control_plane_selection_sha256=receipt.selection_sha256,
        current_request={"goal": "inspect the route"},
    )


def _output(receipt):
    """Use a proposal so these checks never imply an executed physical action."""
    return HarnessOutputEnvelope(
        request_id="request-boundary",
        task_id="task-boundary",
        domain=receipt.domain,
        control_plane_selection_sha256=receipt.selection_sha256,
        input_envelope_sha256="0" * 64,
        status="draft",
        structured_result={},
        model_call_count=0,
        repair_cycle_count=0,
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1: "ambiguous"}, b"bytes"])
@pytest.mark.parametrize("direction", ["input", "output"])
def test_nested_non_json_values_are_rejected(bad, direction):
    receipt = compile_control_plane_receipt("autonomy.mission")
    envelope = _input(receipt) if direction == "input" else _output(receipt)
    payload = envelope.model_dump(mode="python")
    field = "current_request" if direction == "input" else "structured_result"
    payload[field] = {"nested": [bad]}
    with pytest.raises(ValueError):
        type(envelope).model_validate(payload)


@pytest.mark.parametrize("bad", [True, 1.0, "1"])
@pytest.mark.parametrize("field", ["model_call_count", "repair_cycle_count"])
def test_execution_counters_are_exact_integers(bad, field):
    receipt = compile_control_plane_receipt("autonomy.mission")
    payload = _output(receipt).model_dump(mode="python")
    payload[field] = bad
    with pytest.raises(ValueError):
        HarnessOutputEnvelope.model_validate(payload)


def test_modified_receipt_cannot_raise_an_already_bound_budget():
    receipt = compile_control_plane_receipt(
        "autonomy.mission", effective_maximum_model_calls=1
    )
    output = _output(receipt)
    output.model_call_count = 2
    receipt.effective_maximum_model_calls = 2
    with pytest.raises(ValueError, match="does not bind"):
        validate_output_against_control_plane(receipt, output)


def test_modified_output_cannot_bypass_its_schema():
    receipt = compile_control_plane_receipt("autonomy.mission")
    output = _output(receipt)
    output.model_call_count = -1
    with pytest.raises(ValueError):
        validate_output_against_control_plane(receipt, output)


def test_input_hash_revalidates_nested_mutable_state():
    receipt = compile_control_plane_receipt("autonomy.mission")
    envelope = _input(receipt)
    envelope.current_request["reading"] = float("nan")
    with pytest.raises(ValueError):
        harness_input_sha256(envelope)


def test_self_consistent_hash_cannot_replace_the_products_hard_cap():
    receipt = compile_control_plane_receipt("autonomy.mission")
    receipt.hard_maximum_model_calls = 999
    receipt.selection_sha256 = hashlib.sha256(
        json.dumps(
            receipt.selection_payload(), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="product policy"):
        HarnessControlPlaneReceipt.model_validate(receipt.model_dump(mode="python"))


def test_many_slot_rejects_repeated_plugin_identity():
    selection = PluginSelection(
        slot="planner", plugin_id="test.route-planner", version="1.0.0",
        content_sha256="a" * 64, trust="signed",
    )
    with pytest.raises(ValueError, match="duplicate plugin identity"):
        compile_control_plane_receipt(
            "autonomy.mission", (selection, selection),
            selection_authority="agent_harness_designer",
        )


def test_deep_json_rejection_does_not_leak_recursion_error():
    receipt = compile_control_plane_receipt("autonomy.mission")
    payload = _input(receipt).model_dump(mode="python")
    nested = {"leaf": 1}
    for _ in range(100):
        nested = {"child": nested}
    payload["current_request"] = nested
    with pytest.raises(ValueError, match="depth"):
        HarnessInputEnvelope.model_validate(payload)
