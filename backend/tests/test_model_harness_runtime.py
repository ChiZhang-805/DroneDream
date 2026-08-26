from __future__ import annotations

import importlib

import pytest

from app.model_harness.domains import MODEL_HARNESS_DOMAIN_VALUES
from app.model_harness.runtime import (
    RUNTIME_HANDLERS,
    HarnessRuntimeUnavailable,
    require_runnable_operation,
    runtime_catalog,
    runtime_handler,
    runtime_operation,
)


def test_every_domain_has_a_gate_and_post_compile_runtime_disposition() -> None:
    assert set(RUNTIME_HANDLERS) == set(MODEL_HARNESS_DOMAIN_VALUES)

    for domain in MODEL_HARNESS_DOMAIN_VALUES:
        handler = runtime_handler(domain)
        operation_ids = {operation.operation_id for operation in handler.operations}
        assert "compile_workflow_gate" in operation_ids
        assert len(operation_ids) >= 2
        for operation in handler.operations:
            if operation.status == "refused":
                assert operation.boundary == "not_integrated"
                assert operation.refusal_code
                assert operation.handler_id is None
                assert operation.api_path is None
                assert operation.execution_state == "refused"
            else:
                assert operation.boundary != "not_integrated"
                assert operation.handler_id
                assert operation.refusal_code is None
                assert operation.execution_state == "not_invoked"
            assert operation.may_perform_physical_action is False


def _resolve_public_handler(handler_id: str) -> object:
    parts = handler_id.split(".")
    for boundary in range(len(parts), 0, -1):
        try:
            target: object = importlib.import_module(".".join(parts[:boundary]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[boundary:]:
            target = getattr(target, attribute)
        return target
    raise AssertionError(f"handler module is not importable: {handler_id}")


def test_every_available_public_backend_owner_resolves_to_a_real_callable() -> None:
    for handler in RUNTIME_HANDLERS.values():
        for operation in handler.operations:
            if operation.status != "available":
                continue
            assert operation.boundary == "public_backend"
            assert operation.handler_id is not None
            assert callable(_resolve_public_handler(operation.handler_id))


def test_real_execution_boundaries_are_not_inferred_from_planning_support() -> None:
    assert (
        runtime_operation("optimization.control_tuning", "submit_optimization").status
        == "available"
    )
    assert runtime_operation("autonomy.mission", "supervise_simulation").status == "available"
    simulation_handoff = runtime_operation(
        "experiment.simulation",
        "submit_simulation_job",
    )
    assert simulation_handoff.status == "refused"
    assert simulation_handoff.refusal_code == "SIMULATION_JOB_DOMAIN_HANDOFF_NOT_INTEGRATED"
    assert simulation_handoff.handler_id is None
    assert simulation_handoff.api_path is None
    assert (
        runtime_operation("validation.hardware", "execute_hardware_validation").refusal_code
        == "LIVE_HARDWARE_VALIDATION_AUTHORITY_NOT_INTEGRATED"
    )
    assert (
        runtime_operation("operations.field", "dispatch_hardware").refusal_code
        == "FIELD_EXECUTION_AUTHORITY_NOT_INTEGRATED"
    )
    assert (
        runtime_operation(
            "asset.qualification",
            "qualify_arbitrary_external_asset",
        ).refusal_code
        == "EXTERNAL_ASSET_RUNTIME_QUALIFICATION_NOT_INTEGRATED"
    )


def test_unknown_runtime_operation_fails_closed() -> None:
    with pytest.raises(ValueError, match=r"unsupported Model \+ Harness runtime operation"):
        runtime_operation("experiment.simulation", "invented.execute")


def test_runtime_dispatch_guard_returns_real_owner_or_raises_stable_refusal() -> None:
    runnable = require_runnable_operation(
        "experiment.simulation",
        "execute_qualified_simulation",
    )
    assert runnable.handler_id == ("app.autonomy.simulation_execution.simulation_executions.start")

    with pytest.raises(HarnessRuntimeUnavailable) as simulation_handoff:
        require_runnable_operation(
            "experiment.simulation",
            "submit_simulation_job",
        )
    assert simulation_handoff.value.refusal_code == "SIMULATION_JOB_DOMAIN_HANDOFF_NOT_INTEGRATED"

    with pytest.raises(HarnessRuntimeUnavailable) as captured:
        require_runnable_operation("operations.field", "dispatch_hardware")
    assert captured.value.refusal_code == "FIELD_EXECUTION_AUTHORITY_NOT_INTEGRATED"


def test_runtime_catalog_is_machine_readable_and_exhaustive() -> None:
    catalog = runtime_catalog()
    assert catalog["schema_version"] == "dronedream.model-harness-runtime-registry.v1"
    assert set(catalog["domains"]) == set(MODEL_HARNESS_DOMAIN_VALUES)
    assert catalog["domains"]["autonomy.mission"]["domain"] == "autonomy.mission"
