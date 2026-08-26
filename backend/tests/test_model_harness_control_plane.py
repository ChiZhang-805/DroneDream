from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.model_harness.control_plane import (
    HarnessControlPlaneReceipt,
    HarnessInputEnvelope,
    HarnessOutputEnvelope,
    PluginSelection,
    canonical_contract_json_schemas,
    canonical_domain_policy_contract,
    compile_control_plane_receipt,
    control_plane_catalog,
    validate_output_against_control_plane,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def plugin(
    capability: str,
    plugin_id: str,
    *,
    trust: str = "signed",
) -> PluginSelection:
    return PluginSelection.model_validate(
        {
            "slot": capability,
            "plugin_id": plugin_id,
            "version": "1.0.0",
            "content_sha256": "a" * 64,
            "trust": trust,
        }
    )


def test_control_plane_is_domain_not_edition_scoped() -> None:
    receipt = compile_control_plane_receipt("autonomy.mission")

    assert receipt.domain == "autonomy.mission"
    assert receipt.readable_memory_domains == ("account.shared", "autonomy.mission")
    assert receipt.writable_memory_domain == "autonomy.mission"
    assert "identity_and_tenant_boundary" in receipt.fixed_kernel_responsibilities
    assert "structured_io_validation" in receipt.fixed_kernel_responsibilities
    assert "safety_policy" in receipt.fixed_kernel_responsibilities
    assert receipt.plugin_selection_effect == "contract_only"
    assert receipt.plugin_runtime_receipt_ids == ()


def test_plugin_order_does_not_change_selection_receipt() -> None:
    left = plugin("planner", "dronedream.route-planner")
    right = plugin("critic", "dronedream.safety-critic")

    first = compile_control_plane_receipt(
        "autonomy.mission",
        (left, right),
        selection_authority="agent_harness_designer",
    )
    second = compile_control_plane_receipt(
        "autonomy.mission",
        (right, left),
        selection_authority="agent_harness_designer",
    )

    assert first.selection_sha256 == second.selection_sha256
    assert first.selected_plugins == second.selected_plugins


def test_selection_hash_uses_utf8_canonical_json_for_non_ascii_metadata() -> None:
    localized_provider = plugin(
        "model_provider",
        "dronedream.localized-provider",
    ).model_copy(update={"version": "版本-α"})
    receipt = compile_control_plane_receipt(
        "autonomy.mission",
        (localized_provider,),
        selection_authority="account_configurable",
    )
    utf8_hash = hashlib.sha256(
        json.dumps(
            receipt.selection_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    escaped_ascii_hash = hashlib.sha256(
        json.dumps(
            receipt.selection_payload(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert receipt.selection_sha256 == utf8_hash
    assert receipt.selection_sha256 != escaped_ascii_hash
    assert (
        HarnessControlPlaneReceipt.model_validate(receipt.model_dump(mode="json")).selection_sha256
        == utf8_hash
    )


def test_single_slot_rejects_multiple_providers() -> None:
    with pytest.raises(ValueError, match="accepts only one"):
        compile_control_plane_receipt(
            "autonomy.mission",
            (
                plugin("model_provider", "dronedream.openai"),
                plugin("model_provider", "dronedream.deepseek"),
            ),
            selection_authority="account_configurable",
        )


def test_explicit_selection_requires_declared_authority() -> None:
    with pytest.raises(ValueError, match="declared selection authority"):
        compile_control_plane_receipt(
            "autonomy.mission",
            (plugin("model_provider", "dronedream.openai"),),
        )


def test_multi_slot_accepts_multiple_planners_for_fusion() -> None:
    receipt = compile_control_plane_receipt(
        "autonomy.mission",
        (
            plugin("planner", "dronedream.topology-planner"),
            plugin("planner", "dronedream.local-trajectory-planner"),
        ),
        selection_authority="agent_harness_designer",
    )

    assert [item.plugin_id for item in receipt.selected_plugins if item.slot == "planner"] == [
        "dronedream.local-trajectory-planner",
        "dronedream.topology-planner",
    ]


def test_domain_rejects_an_unrelated_capability() -> None:
    with pytest.raises(ValueError, match="is not allowed"):
        compile_control_plane_receipt(
            "validation.hardware",
            (plugin("asset_adapter", "dronedream.blender-import"),),
            selection_authority="product_managed",
        )


def test_untrusted_development_plugin_is_not_admitted_to_managed_flow() -> None:
    with pytest.raises(ValueError, match="trust"):
        compile_control_plane_receipt(
            "autonomy.mission",
            (plugin("planner", "developer.unsigned-planner", trust="local_development"),),
            selection_authority="agent_harness_designer",
        )


def test_plugin_identity_and_digest_are_strict() -> None:
    with pytest.raises(ValidationError):
        plugin("planner", "../../untrusted.py")
    with pytest.raises(ValidationError):
        PluginSelection.model_validate(
            {
                "slot": "planner",
                "plugin_id": "dronedream.route-planner",
                "version": "1.0.0",
                "content_sha256": "not-a-digest",
                "trust": "signed",
            }
        )


def test_catalog_exposes_fixed_and_replaceable_boundaries() -> None:
    catalog = control_plane_catalog()
    mission = catalog["domains"]["autonomy.mission"]
    slots = {item["capability"]: item for item in mission["plugin_slots"]}

    assert catalog["structured_input_schema_version"].endswith(".v1")
    assert catalog["structured_output_schema_version"].endswith(".v1")
    assert "acceptance_and_evidence" in catalog["fixed_kernel_responsibilities"]
    assert "memory_governance" in catalog["fixed_kernel_responsibilities"]
    assert "plugin_trust_and_lifecycle" in catalog["fixed_kernel_responsibilities"]
    assert slots["model_provider"]["cardinality"] == "one"
    assert slots["planner"]["cardinality"] == "many"
    assert slots["planner"]["swap_boundary"] == "safe_hold_only"
    assert slots["planner"]["selection_authority"] == "agent_harness_designer"
    assert slots["planner"]["exposure"] == "agent_harness_designer"
    assert slots["model_provider"]["selection_authority"] == "account_configurable"
    assert slots["model_provider"]["exposure"] == "account_settings"
    assert slots["validator"]["failure_mode"] == "fail_closed"
    assert slots["validator"]["selection_authority"] == "product_managed"
    assert slots["validator"]["exposure"] == "internal"
    assert catalog["memory_retrieval_policy"]["semantic_retrieval"] == "secondary_advisory"
    assert catalog["memory_retrieval_policy"]["may_supply_execution_authority"] is False
    assert catalog["learning_promotion_policy"]["online_policy_updates_allowed"] is False
    assert "holdout_regression" in catalog["learning_promotion_policy"]["promotion_gates"]
    assert catalog["plugin_lifecycle_policy"]["dependency_missing"] == "dispose_dependents"
    assert catalog["plugin_lifecycle_policy"]["unsigned_production_plugins_allowed"] is False


def test_structured_input_is_owner_tenant_and_thread_bound() -> None:
    receipt = compile_control_plane_receipt("experiment.simulation")
    envelope = HarnessInputEnvelope.model_validate(
        {
            "request_id": "request-0001",
            "task_id": "task-0001",
            "thread_id": "thread-0001",
            "owner_binding_sha256": "1" * 64,
            "tenant_binding_sha256": "2" * 64,
            "source_edition": "sim",
            "domain": "experiment.simulation",
            "control_plane_selection_sha256": receipt.selection_sha256,
            "current_request": {"goal": "compare two controllers"},
            "session_context": {"world": "School Map"},
            "memory_record_ids": ["memory-account", "memory-domain"],
        }
    )

    assert envelope.source_edition == "sim"
    assert envelope.domain == "experiment.simulation"
    assert envelope.memory_record_ids == ("memory-account", "memory-domain")


def test_output_budget_and_evidence_are_fixed_kernel_checks() -> None:
    receipt = compile_control_plane_receipt("autonomy.mission")
    valid = HarnessOutputEnvelope.model_validate(
        {
            "request_id": "request-0001",
            "task_id": "task-0001",
            "domain": "autonomy.mission",
            "control_plane_selection_sha256": receipt.selection_sha256,
            "input_envelope_sha256": "0" * 64,
            "status": "closed",
            "structured_result": {"plan_id": "plan-0001"},
            "model_call_count": receipt.effective_maximum_model_calls,
            "repair_cycle_count": receipt.effective_maximum_repair_cycles,
            "validation_receipt_ids": ["validation-0001"],
            "evidence_receipt_ids": ["evidence-0001"],
        }
    )
    validate_output_against_control_plane(receipt, valid)

    over_budget = valid.model_copy(
        update={"model_call_count": receipt.effective_maximum_model_calls + 1}
    )
    with pytest.raises(ValueError, match="model-call budget"):
        validate_output_against_control_plane(receipt, over_budget)

    without_evidence = valid.model_copy(update={"evidence_receipt_ids": ()})
    with pytest.raises(ValueError, match="evidence receipt"):
        validate_output_against_control_plane(receipt, without_evidence)


def test_output_schema_cannot_claim_a_physical_action() -> None:
    receipt = compile_control_plane_receipt("operations.field")
    with pytest.raises(ValidationError):
        HarnessOutputEnvelope.model_validate(
            {
                "request_id": "request-0001",
                "task_id": "task-0001",
                "domain": "operations.field",
                "control_plane_selection_sha256": receipt.selection_sha256,
                "input_envelope_sha256": "0" * 64,
                "status": "draft",
                "structured_result": {},
                "model_call_count": 1,
                "repair_cycle_count": 0,
                "physical_action_performed": True,
            }
        )


def test_required_slots_receive_content_bound_product_managed_defaults() -> None:
    first = compile_control_plane_receipt("experiment.simulation")
    second = compile_control_plane_receipt("experiment.simulation")
    by_slot = {selection.slot: selection for selection in first.selected_plugins}

    assert set(by_slot) == {"model_provider", "simulator_adapter", "validator"}
    assert all(selection.source == "product_managed_default" for selection in by_slot.values())
    assert all(selection.trust == "managed" for selection in by_slot.values())
    assert all(len(selection.content_sha256) == 64 for selection in by_slot.values())
    for slot, selection in by_slot.items():
        manifest = (
            REPOSITORY_ROOT
            / "contracts"
            / "model_harness"
            / "managed_plugins"
            / f"{slot}.manifest.json"
        ).read_bytes()
        assert selection.content_sha256 == hashlib.sha256(manifest).hexdigest()
    assert first.selected_plugins == second.selected_plugins
    assert first.selection_sha256 == second.selection_sha256


def test_managed_manifest_bytes_change_selection_hash_and_bind_source(tmp_path: Path) -> None:
    source_root = REPOSITORY_ROOT / "contracts" / "model_harness" / "managed_plugins"
    manifest_root = tmp_path / "managed_plugins"
    shutil.copytree(source_root, manifest_root)
    baseline = compile_control_plane_receipt(
        "experiment.simulation",
        managed_plugin_manifest_root=manifest_root,
    )

    provider_path = manifest_root / "model_provider.manifest.json"
    provider = json.loads(provider_path.read_text(encoding="utf-8"))
    provider["api_contract"]["contract_id"] = "dronedream.managed.model-provider.v2"
    provider_path.write_text(
        json.dumps(provider, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    changed = compile_control_plane_receipt(
        "experiment.simulation",
        managed_plugin_manifest_root=manifest_root,
    )
    assert changed.selection_sha256 != baseline.selection_sha256

    provider["implementation"]["source_sha256"] = "0" * 64
    provider_path.write_text(
        json.dumps(provider, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="source digest mismatch"):
        compile_control_plane_receipt(
            "experiment.simulation",
            managed_plugin_manifest_root=manifest_root,
        )


def test_explicit_required_plugin_replaces_default_and_is_hash_bound() -> None:
    baseline = compile_control_plane_receipt("autonomy.mission")
    selected = compile_control_plane_receipt(
        "autonomy.mission",
        (plugin("model_provider", "dronedream.openai-compatible"),),
        selection_authority="account_configurable",
    )

    providers = [item for item in selected.selected_plugins if item.slot == "model_provider"]
    assert [item.plugin_id for item in providers] == ["dronedream.openai-compatible"]
    assert providers[0].source == "explicit"
    assert selected.selection_sha256 != baseline.selection_sha256

    changed_content = plugin("model_provider", "dronedream.openai-compatible").model_copy(
        update={"content_sha256": "b" * 64}
    )
    changed = compile_control_plane_receipt(
        "autonomy.mission",
        (changed_content,),
        selection_authority="account_configurable",
    )
    assert changed.selection_sha256 != selected.selection_sha256

    tampered = selected.model_dump(mode="json")
    tampered["selected_plugins"][0]["content_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="does not bind"):
        HarnessControlPlaneReceipt.model_validate(tampered)


def test_user_facing_selection_authorities_cannot_replace_internal_harness_slots() -> None:
    with pytest.raises(ValueError, match="not selectable by account_configurable"):
        compile_control_plane_receipt(
            "experiment.simulation",
            (plugin("validator", "customer.validator"),),
            selection_authority="account_configurable",
        )
    with pytest.raises(ValueError, match="not selectable by agent_harness_designer"):
        compile_control_plane_receipt(
            "experiment.simulation",
            (plugin("planner", "customer.experiment-planner"),),
            selection_authority="agent_harness_designer",
        )

    mission = compile_control_plane_receipt(
        "autonomy.mission",
        (plugin("planner", "customer.mission-planner"),),
        selection_authority="agent_harness_designer",
    )
    selected_planner = next(item for item in mission.selected_plugins if item.slot == "planner")
    assert selected_planner.selected_by == "agent_harness_designer"


def test_effective_budget_is_distinct_from_hard_cap_and_is_enforced() -> None:
    receipt = compile_control_plane_receipt(
        "autonomy.mission",
        effective_maximum_model_calls=2,
        effective_maximum_repair_cycles=1,
    )
    assert receipt.hard_maximum_model_calls == 48
    assert receipt.effective_maximum_model_calls == 2
    assert receipt.hard_maximum_repair_cycles == 6
    assert receipt.effective_maximum_repair_cycles == 1

    output = HarnessOutputEnvelope(
        request_id="request-0001",
        task_id="task-0001",
        domain="autonomy.mission",
        control_plane_selection_sha256=receipt.selection_sha256,
        input_envelope_sha256="0" * 64,
        status="draft",
        structured_result={},
        model_call_count=3,
        repair_cycle_count=0,
    )
    with pytest.raises(ValueError, match="effective model-call budget"):
        validate_output_against_control_plane(receipt, output)

    with pytest.raises(ValueError, match="immutable hard cap"):
        compile_control_plane_receipt(
            "autonomy.mission",
            effective_maximum_model_calls=49,
        )


def test_receipt_and_output_disclaim_execution_authority_enforcement() -> None:
    receipt = compile_control_plane_receipt("operations.field")
    output = HarnessOutputEnvelope(
        request_id="request-0001",
        task_id="task-0001",
        domain="operations.field",
        control_plane_selection_sha256=receipt.selection_sha256,
        input_envelope_sha256="0" * 64,
        status="blocked",
        structured_result={},
        model_call_count=0,
        repair_cycle_count=0,
    )

    assert receipt.execution_authority_enforcement == "not_integrated"
    assert receipt.grants_execution_authority is False
    assert output.execution_authority_enforcement == "not_integrated"
    assert output.grants_execution_authority is False


def test_compile_only_output_cannot_claim_model_or_tool_execution() -> None:
    receipt = compile_control_plane_receipt("experiment.simulation")
    with pytest.raises(ValidationError, match="compile-only"):
        HarnessOutputEnvelope(
            request_id="request-0001",
            task_id="task-0001",
            domain="experiment.simulation",
            control_plane_selection_sha256=receipt.selection_sha256,
            input_envelope_sha256="0" * 64,
            status="draft",
            lifecycle_stage="compile_only",
            structured_result={},
            model_call_count=1,
            repair_cycle_count=0,
        )


def test_refused_and_execute_lifecycle_stages_require_terminal_evidence() -> None:
    receipt = compile_control_plane_receipt("operations.field")
    with pytest.raises(ValidationError, match="refused output"):
        HarnessOutputEnvelope(
            request_id="request-0001",
            task_id="task-0001",
            domain="operations.field",
            control_plane_selection_sha256=receipt.selection_sha256,
            input_envelope_sha256="0" * 64,
            status="draft",
            lifecycle_stage="refused",
            structured_result={},
            model_call_count=0,
            repair_cycle_count=0,
        )
    with pytest.raises(ValidationError, match="execute output"):
        HarnessOutputEnvelope(
            request_id="request-0001",
            task_id="task-0001",
            domain="operations.field",
            control_plane_selection_sha256=receipt.selection_sha256,
            input_envelope_sha256="0" * 64,
            status="closed",
            lifecycle_stage="execute",
            structured_result={},
            model_call_count=0,
            repair_cycle_count=0,
            validation_receipt_ids=("validation-0001",),
        )


def test_checked_in_json_schemas_match_runtime_pydantic_models() -> None:
    contract_root = REPOSITORY_ROOT / "contracts" / "model_harness"
    generated = canonical_contract_json_schemas()

    assert set(generated) == {
        "control-plane-receipt.v1.schema.json",
        "harness-input.v1.schema.json",
        "harness-output.v1.schema.json",
        "managed-plugin-manifest.v1.schema.json",
    }
    for filename, schema in generated.items():
        checked_in = json.loads((contract_root / filename).read_text(encoding="utf-8"))
        assert checked_in == schema
        assert checked_in["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_checked_in_domain_policy_matches_python_authority() -> None:
    checked_in = json.loads(
        (REPOSITORY_ROOT / "contracts" / "model_harness" / "domain-policy.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert checked_in == canonical_domain_policy_contract()
    assert set(checked_in["tasks"]) == {
        "control_tuning",
        "mission_autonomy",
        "asset_import_qualification",
        "simulation_experiment",
        "cross_edition_workflow",
        "hardware_validation",
        "calibration",
        "sim_to_real",
        "real_to_sim",
        "field_task",
    }
    assert set(checked_in["domains"]) == set(checked_in["memory_namespaces"]) - {"account.shared"}
    for task_policy in checked_in["tasks"].values():
        domain_policy = checked_in["domains"][task_policy["domain"]]
        managed = task_policy["managed_assistant"]
        assert managed["effective_maximum_model_calls"] <= domain_policy["hard_maximum_model_calls"]
        assert (
            managed["effective_maximum_repair_cycles"]
            <= domain_policy["hard_maximum_repair_cycles"]
        )
        assert domain_policy["readable_memory_domains"] == [
            "account.shared",
            task_policy["domain"],
        ]
        assert domain_policy["writable_memory_domain"] == task_policy["domain"]
        assert any(
            slot["capability"] == "model_provider"
            and slot["required"] is True
            and slot["failure_mode"] == "fail_closed"
            for slot in domain_policy["plugin_slots"]
        )
