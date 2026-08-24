"""Runtime ownership registry for every public Model + Harness domain.

The workflow compiler is a proposal boundary, not an executor.  This module
makes the next boundary explicit: every supported operation names the concrete
runtime that owns it, while unavailable or authority-bearing operations fail
closed with a stable refusal code.  Callers therefore never infer execution
support from the mere presence of a planning contract.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.model_harness.domains import (
    MODEL_HARNESS_DOMAIN_VALUES,
    ModelHarnessDomain,
)

RUNTIME_REGISTRY_SCHEMA_VERSION: Final = "dronedream.model-harness-runtime-registry.v1"

RuntimeOperationStatus = Literal["available", "delegated", "refused"]
RuntimeBoundary = Literal[
    "public_backend",
    "managed_cloud",
    "private_agent_core",
    "not_integrated",
]


class HarnessRuntimeUnavailable(RuntimeError):
    """Stable fail-closed signal for an operation with no integrated owner."""

    def __init__(self, operation: HarnessRuntimeOperation) -> None:
        if operation.status != "refused" or operation.refusal_code is None:
            raise ValueError("HarnessRuntimeUnavailable requires a refused operation")
        self.domain_operation_id = operation.operation_id
        self.refusal_code = operation.refusal_code
        super().__init__(operation.refusal_code)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HarnessRuntimeOperation(_StrictModel):
    """One runtime operation with either a real owner or an explicit refusal."""

    operation_id: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_.-]+$",
    )
    status: RuntimeOperationStatus
    execution_state: Literal["not_invoked", "refused"]
    boundary: RuntimeBoundary
    handler_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_.:/-]+$",
    )
    api_path: str | None = Field(default=None, max_length=240)
    refusal_code: str | None = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )
    requires_receipts: tuple[str, ...] = Field(default=(), max_length=16)
    may_perform_physical_action: Literal[False] = False

    @model_validator(mode="after")
    def _validate_runtime_owner(self) -> HarnessRuntimeOperation:
        if self.status == "refused":
            if self.boundary != "not_integrated" or self.refusal_code is None:
                raise ValueError("refused operations require a stable not-integrated code")
            if self.handler_id is not None or self.api_path is not None:
                raise ValueError("refused operations cannot advertise a runtime entrypoint")
            if self.execution_state != "refused":
                raise ValueError("refused operation requires refused execution state")
        else:
            if self.boundary == "not_integrated" or self.handler_id is None:
                raise ValueError("runnable operations require a concrete runtime owner")
            if self.refusal_code is not None:
                raise ValueError("runnable operations cannot carry a refusal code")
            if self.execution_state != "not_invoked":
                raise ValueError("runtime availability never proves an invocation occurred")
        return self


class HarnessRuntimeHandler(_StrictModel):
    """Complete runtime disposition for one responsibility domain."""

    schema_version: Literal["dronedream.model-harness-runtime-registry.v1"] = (
        RUNTIME_REGISTRY_SCHEMA_VERSION
    )
    domain: ModelHarnessDomain
    operations: tuple[HarnessRuntimeOperation, ...] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def _validate_operation_coverage(self) -> HarnessRuntimeHandler:
        operation_ids = [operation.operation_id for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("runtime operation IDs must be unique within a domain")
        if "compile_workflow_gate" not in operation_ids:
            raise ValueError("every domain requires the product-owned workflow gate")
        if all(operation.operation_id == "compile_workflow_gate" for operation in self.operations):
            raise ValueError("a domain must declare its post-compile runtime disposition")
        return self


def _available(
    operation_id: str,
    handler_id: str,
    api_path: str,
    *,
    receipts: tuple[str, ...] = (),
) -> HarnessRuntimeOperation:
    return HarnessRuntimeOperation(
        operation_id=operation_id,
        status="available",
        execution_state="not_invoked",
        boundary="public_backend",
        handler_id=handler_id,
        api_path=api_path,
        requires_receipts=receipts,
    )


def _delegated(
    operation_id: str,
    handler_id: str,
    boundary: Literal["managed_cloud", "private_agent_core"],
    *,
    receipts: tuple[str, ...] = (),
) -> HarnessRuntimeOperation:
    return HarnessRuntimeOperation(
        operation_id=operation_id,
        status="delegated",
        execution_state="not_invoked",
        boundary=boundary,
        handler_id=handler_id,
        requires_receipts=receipts,
    )


def _refused(operation_id: str, refusal_code: str) -> HarnessRuntimeOperation:
    return HarnessRuntimeOperation(
        operation_id=operation_id,
        status="refused",
        execution_state="refused",
        boundary="not_integrated",
        refusal_code=refusal_code,
    )


_WORKFLOW_GATE: Final = _available(
    "compile_workflow_gate",
    "app.task_workflows.compile_task_workflow",
    "/api/v1/task-workflows/compile",
    receipts=("validated-harness-input", "control-plane-receipt"),
)


RUNTIME_HANDLERS: Final[dict[ModelHarnessDomain, HarnessRuntimeHandler]] = {
    "optimization.control_tuning": HarnessRuntimeHandler(
        domain="optimization.control_tuning",
        operations=(
            _WORKFLOW_GATE,
            _available(
                "compile_model_draft",
                "app.experiment_assistant.compile_experiment_turn",
                "/api/v1/experiment-assistant/turn",
                receipts=("validated-harness-output",),
            ),
            _available(
                "submit_optimization",
                "app.services.jobs.create_job",
                "/api/v1/jobs",
                receipts=("job-contract", "provider-budget"),
            ),
            _refused(
                "apply_parameters_to_hardware",
                "PARAMETER_WRITE_AUTHORITY_NOT_INTEGRATED",
            ),
        ),
    ),
    "autonomy.mission": HarnessRuntimeHandler(
        domain="autonomy.mission",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "dronedream.agent-core.mission-service",
                "private_agent_core",
                receipts=("planner-artifact", "asset-binding"),
            ),
            _available(
                "compile_mission_contract",
                "app.autonomy.service.compile_autonomy_mission",
                "/api/v1/autonomy/compile",
                receipts=("qualified-vehicle", "qualified-map", "planner-artifact"),
            ),
            _available(
                "supervise_simulation",
                "app.autonomy.runtime.runtime_sessions.create",
                "/api/v1/autonomy/runtime/sessions",
                receipts=("qualified-assets", "simulation-plan"),
            ),
            _refused("dispatch_hardware", "LIVE_FLIGHT_AUTHORITY_NOT_INTEGRATED"),
        ),
    ),
    "asset.qualification": HarnessRuntimeHandler(
        domain="asset.qualification",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.asset-qualification",
                "managed_cloud",
            ),
            _available(
                "admit_map_asset",
                "app.autonomy.qualification.map_asset_admissions.admit",
                "/api/v1/autonomy/map-assets/admit",
                receipts=("source-content-sha256",),
            ),
            _available(
                "qualify_bundled_asset",
                "app.autonomy.qualification.qualify_map_pack",
                "/api/v1/autonomy/map-packs/qualify",
                receipts=("asset-admission", "deterministic-qualification"),
            ),
            _refused(
                "qualify_arbitrary_external_asset",
                "EXTERNAL_ASSET_RUNTIME_QUALIFICATION_NOT_INTEGRATED",
            ),
        ),
    ),
    "experiment.simulation": HarnessRuntimeHandler(
        domain="experiment.simulation",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.simulation-experiment",
                "managed_cloud",
            ),
            _refused(
                "submit_simulation_job",
                "SIMULATION_JOB_DOMAIN_HANDOFF_NOT_INTEGRATED",
            ),
            _available(
                "execute_qualified_simulation",
                "app.autonomy.simulation_execution.simulation_executions.start",
                "/api/v1/autonomy/runtime/simulation-executions",
                receipts=("qualified-assets", "simulation-plan"),
            ),
        ),
    ),
    "workflow.cross_edition": HarnessRuntimeHandler(
        domain="workflow.cross_edition",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.cross-edition-workflow",
                "managed_cloud",
            ),
            _refused(
                "promote_cross_edition",
                "CROSS_EDITION_PROMOTION_RUNTIME_NOT_INTEGRATED",
            ),
        ),
    ),
    "validation.hardware": HarnessRuntimeHandler(
        domain="validation.hardware",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.hardware-validation",
                "managed_cloud",
            ),
            _refused(
                "execute_hardware_validation",
                "LIVE_HARDWARE_VALIDATION_AUTHORITY_NOT_INTEGRATED",
            ),
        ),
    ),
    "calibration.system": HarnessRuntimeHandler(
        domain="calibration.system",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.system-calibration",
                "managed_cloud",
            ),
            _refused("apply_calibration", "CALIBRATION_WRITE_RUNTIME_NOT_INTEGRATED"),
        ),
    ),
    "transfer.sim_to_real": HarnessRuntimeHandler(
        domain="transfer.sim_to_real",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.sim-to-real",
                "managed_cloud",
            ),
            _refused("promote_to_hardware", "SIM_TO_REAL_PROMOTION_RUNTIME_NOT_INTEGRATED"),
        ),
    ),
    "transfer.real_to_sim": HarnessRuntimeHandler(
        domain="transfer.real_to_sim",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.real-to-sim",
                "managed_cloud",
            ),
            _refused(
                "mutate_validated_simulation_baseline",
                "REAL_TO_SIM_BASELINE_WRITE_NOT_INTEGRATED",
            ),
        ),
    ),
    "operations.field": HarnessRuntimeHandler(
        domain="operations.field",
        operations=(
            _WORKFLOW_GATE,
            _delegated(
                "compile_model_plan",
                "assistant-orchestrator.field-task",
                "managed_cloud",
            ),
            _refused("dispatch_hardware", "FIELD_EXECUTION_AUTHORITY_NOT_INTEGRATED"),
        ),
    ),
}


def runtime_handler(domain: ModelHarnessDomain) -> HarnessRuntimeHandler:
    """Return the exhaustive runtime disposition for one Harness domain."""

    try:
        return RUNTIME_HANDLERS[domain]
    except KeyError as exc:  # pragma: no cover - literal typing guards normal callers
        raise ValueError("unsupported Model + Harness runtime domain") from exc


def runtime_operation(
    domain: ModelHarnessDomain,
    operation_id: str,
) -> HarnessRuntimeOperation:
    """Resolve one operation, failing closed instead of guessing an executor."""

    handler = runtime_handler(domain)
    for operation in handler.operations:
        if operation.operation_id == operation_id:
            return operation
    raise ValueError("unsupported Model + Harness runtime operation")


def require_runnable_operation(
    domain: ModelHarnessDomain,
    operation_id: str,
) -> HarnessRuntimeOperation:
    """Resolve a runnable owner or reject with the operation's stable code.

    Runtime adapters should call this guard before dispatch.  A workflow plan,
    domain catalog, or delegated planner artifact is never treated as proof
    that the requested operation is executable.
    """

    operation = runtime_operation(domain, operation_id)
    if operation.status == "refused":
        raise HarnessRuntimeUnavailable(operation)
    return operation


def runtime_catalog() -> dict[str, object]:
    return {
        "schema_version": RUNTIME_REGISTRY_SCHEMA_VERSION,
        "domains": {
            domain: runtime_handler(domain).model_dump(mode="json")
            for domain in MODEL_HARNESS_DOMAIN_VALUES
        },
    }


if set(RUNTIME_HANDLERS) != set(MODEL_HARNESS_DOMAIN_VALUES):  # pragma: no cover
    raise RuntimeError("Model + Harness runtime registry does not cover every domain")


__all__ = [
    "HarnessRuntimeHandler",
    "HarnessRuntimeOperation",
    "HarnessRuntimeUnavailable",
    "RUNTIME_HANDLERS",
    "RUNTIME_REGISTRY_SCHEMA_VERSION",
    "runtime_catalog",
    "runtime_handler",
    "runtime_operation",
    "require_runnable_operation",
]
