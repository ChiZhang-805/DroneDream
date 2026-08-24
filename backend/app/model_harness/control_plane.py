"""Product-owned control plane for every DroneDream Model + Harness flow.

The control plane is intentionally smaller and more authoritative than any
individual prompt, model adapter, or plugin runtime.  It defines which stages
the product owns, which capabilities may be supplied by plugins, and how a
plugin selection is bound into an auditable workflow contract.

No code in this module executes a plugin or a physical action.  It validates a
closed plugin manifest and returns a deterministic receipt that downstream
runtimes can require before loading capability implementations.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.model_harness.domains import (
    FIXED_KERNEL_RESPONSIBILITIES,
    MEMORY_DOMAIN_VALUES,
    MODEL_HARNESS_DOMAIN_VALUES,
    TASK_MODEL_HARNESS_DOMAINS,
    FixedKernelResponsibility,
    MemoryDomain,
    ModelHarnessDomain,
)

CONTROL_PLANE_SCHEMA_VERSION: Final = "dronedream.model-harness-control-plane.v1"
DOMAIN_POLICY_CONTRACT_SCHEMA_VERSION: Final = "dronedream.model-harness-domain-policy.v1"
STRUCTURED_INPUT_SCHEMA_VERSION: Final = "dronedream.model-harness-input.v1"
STRUCTURED_OUTPUT_SCHEMA_VERSION: Final = "dronedream.model-harness-output.v1"
MEMORY_RETRIEVAL_POLICY_VERSION: Final = "dronedream.memory-retrieval-policy.v1"
LEARNING_PROMOTION_POLICY_VERSION: Final = "dronedream.learning-promotion-policy.v1"
MANAGED_PLUGIN_MANIFEST_SCHEMA_VERSION: Final = "dronedream.managed-plugin-manifest.v1"

# The managed Supabase planner is a bounded adapter over the product-owned
# hard ceilings below.  Keeping its effective budget profile beside the
# canonical domain policies lets every runtime consume one checked-in policy
# contract instead of maintaining a second task table.
MANAGED_ASSISTANT_EFFECTIVE_LIMITS: Final[dict[str, tuple[int, int]]] = {
    "control_tuning": (1, 0),
    "mission_autonomy": (4, 3),
    "asset_import_qualification": (1, 0),
    "simulation_experiment": (1, 0),
    "cross_edition_workflow": (1, 0),
    "hardware_validation": (1, 0),
    "calibration": (1, 0),
    "sim_to_real": (1, 0),
    "real_to_sim": (1, 0),
    "field_task": (1, 0),
}
if set(MANAGED_ASSISTANT_EFFECTIVE_LIMITS) != set(TASK_MODEL_HARNESS_DOMAINS):
    raise RuntimeError("managed assistant budget profile must cover every Harness task")

HarnessLoopKind: TypeAlias = Literal[
    "single_pass",
    "plan_validate",
    "iterative_optimize",
    "observe_repair",
    "promotion_pipeline",
]
SourceEdition: TypeAlias = Literal["universal", "sim", "lab", "field", "autonomy"]
HarnessResultStatus: TypeAlias = Literal[
    "draft",
    "needs_input",
    "blocked",
    "validated_proposal",
    "closed",
]
HarnessLifecycleStage: TypeAlias = Literal[
    "compile_only",
    "proposal",
    "execute",
    "refused",
]
PluginCardinality: TypeAlias = Literal["one", "many"]
PluginTrust: TypeAlias = Literal["managed", "signed", "local_development"]
PluginSelectionSource: TypeAlias = Literal["explicit", "product_managed_default"]
PluginSelectionAuthority: TypeAlias = Literal[
    "product_managed",
    "account_configurable",
    "agent_harness_designer",
]
PluginExposure: TypeAlias = Literal[
    "internal",
    "account_settings",
    "agent_harness_designer",
]
PluginSwapBoundary: TypeAlias = Literal[
    "between_invocations",
    "safe_hold_only",
    "idle_only",
]
PluginCapability: TypeAlias = Literal[
    "model_provider",
    "intent_extractor",
    "context_enricher",
    "prompt_pack",
    "tool_provider",
    "planner",
    "optimizer",
    "critic",
    "validator",
    "memory_extractor",
    "memory_consolidator",
    "memory_retriever",
    "semantic_retriever",
    "simulator_adapter",
    "asset_adapter",
    "telemetry_adapter",
    "recovery_strategy",
    "evidence_exporter",
    "notification_adapter",
]

_PLUGIN_ID_PATTERN: Final = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])?$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_MANAGED_PLUGIN_MANIFEST_ROOT: Final = (
    _REPOSITORY_ROOT / "contracts" / "model_harness" / "managed_plugins"
)


@dataclass(frozen=True)
class PluginSlotPolicy:
    """One replaceable capability seam inside a product-owned boundary."""

    capability: PluginCapability
    cardinality: PluginCardinality
    required: bool
    hot_swappable: bool
    swap_boundary: PluginSwapBoundary
    allowed_trust: tuple[PluginTrust, ...]
    failure_mode: Literal["fail_closed", "degrade_without_capability"]
    selection_authority: PluginSelectionAuthority
    exposure: PluginExposure


@dataclass(frozen=True)
class HarnessDomainPolicy:
    """A responsibility-level Harness policy shared across product editions."""

    domain: ModelHarnessDomain
    loop_kind: HarnessLoopKind
    maximum_model_calls: int
    maximum_repair_cycles: int
    readable_memory_domains: tuple[MemoryDomain, ...]
    writable_memory_domain: MemoryDomain
    plugin_slots: tuple[PluginSlotPolicy, ...]

    def __post_init__(self) -> None:
        if self.maximum_model_calls < 1:
            raise ValueError("maximum_model_calls must be positive")
        if self.maximum_repair_cycles < 0:
            raise ValueError("maximum_repair_cycles cannot be negative")
        capabilities = [slot.capability for slot in self.plugin_slots]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("a Harness domain cannot declare a plugin slot twice")


def _slot(
    capability: PluginCapability,
    *,
    cardinality: PluginCardinality = "one",
    required: bool = False,
    hot_swappable: bool = True,
    swap_boundary: PluginSwapBoundary = "between_invocations",
    allowed_trust: tuple[PluginTrust, ...] = ("managed", "signed"),
    failure_mode: Literal[
        "fail_closed", "degrade_without_capability"
    ] = "degrade_without_capability",
    selection_authority: PluginSelectionAuthority = "product_managed",
    exposure: PluginExposure = "internal",
) -> PluginSlotPolicy:
    return PluginSlotPolicy(
        capability=capability,
        cardinality=cardinality,
        required=required,
        hot_swappable=hot_swappable,
        swap_boundary=swap_boundary,
        allowed_trust=allowed_trust,
        failure_mode=failure_mode,
        selection_authority=selection_authority,
        exposure=exposure,
    )


_COMMON_MODEL_SLOTS: Final[tuple[PluginSlotPolicy, ...]] = (
    _slot(
        "model_provider",
        required=True,
        failure_mode="fail_closed",
        selection_authority="account_configurable",
        exposure="account_settings",
    ),
    _slot("intent_extractor"),
    _slot("context_enricher", cardinality="many"),
    _slot("prompt_pack"),
    _slot("tool_provider", cardinality="many"),
    _slot("critic", cardinality="many"),
    _slot("memory_extractor"),
    _slot("memory_consolidator"),
    _slot("memory_retriever"),
    _slot("semantic_retriever"),
    _slot("evidence_exporter", cardinality="many"),
)


def _policy(
    domain: ModelHarnessDomain,
    *,
    loop_kind: HarnessLoopKind,
    maximum_model_calls: int,
    maximum_repair_cycles: int,
    extra_slots: tuple[PluginSlotPolicy, ...],
) -> HarnessDomainPolicy:
    common_slots = _COMMON_MODEL_SLOTS
    if domain == "autonomy.mission":
        designer_slots = frozenset({"critic", "tool_provider", "prompt_pack"})
        common_slots = tuple(
            replace(
                slot,
                selection_authority="agent_harness_designer",
                exposure="agent_harness_designer",
            )
            if slot.capability in designer_slots
            else slot
            for slot in _COMMON_MODEL_SLOTS
        )
    return HarnessDomainPolicy(
        domain=domain,
        loop_kind=loop_kind,
        maximum_model_calls=maximum_model_calls,
        maximum_repair_cycles=maximum_repair_cycles,
        readable_memory_domains=("account.shared", domain),
        writable_memory_domain=domain,
        plugin_slots=(*common_slots, *extra_slots),
    )


DOMAIN_POLICIES: Final[dict[ModelHarnessDomain, HarnessDomainPolicy]] = {
    "optimization.control_tuning": _policy(
        "optimization.control_tuning",
        loop_kind="iterative_optimize",
        maximum_model_calls=12,
        maximum_repair_cycles=4,
        extra_slots=(
            _slot("optimizer", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("simulator_adapter", cardinality="many"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("telemetry_adapter", cardinality="many"),
        ),
    ),
    "autonomy.mission": _policy(
        "autonomy.mission",
        loop_kind="observe_repair",
        # This is the product-owned hard ceiling. The active budget-policy
        # plugin may lower the selected limit (for example, the cost-capped
        # profile uses 16) but can never expand it beyond 48.
        maximum_model_calls=48,
        maximum_repair_cycles=6,
        extra_slots=(
            _slot(
                "planner",
                cardinality="many",
                required=True,
                swap_boundary="safe_hold_only",
                failure_mode="fail_closed",
                selection_authority="agent_harness_designer",
                exposure="agent_harness_designer",
            ),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("telemetry_adapter", cardinality="many", swap_boundary="idle_only"),
            _slot(
                "recovery_strategy",
                cardinality="many",
                swap_boundary="safe_hold_only",
                selection_authority="agent_harness_designer",
                exposure="agent_harness_designer",
            ),
            _slot("simulator_adapter", cardinality="many"),
        ),
    ),
    "asset.qualification": _policy(
        "asset.qualification",
        loop_kind="plan_validate",
        maximum_model_calls=6,
        maximum_repair_cycles=2,
        extra_slots=(
            _slot("asset_adapter", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("simulator_adapter", cardinality="many"),
        ),
    ),
    "experiment.simulation": _policy(
        "experiment.simulation",
        loop_kind="plan_validate",
        maximum_model_calls=6,
        maximum_repair_cycles=2,
        extra_slots=(
            _slot("planner"),
            _slot(
                "simulator_adapter",
                cardinality="many",
                required=True,
                failure_mode="fail_closed",
            ),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("telemetry_adapter", cardinality="many", swap_boundary="idle_only"),
        ),
    ),
    "workflow.cross_edition": _policy(
        "workflow.cross_edition",
        loop_kind="promotion_pipeline",
        maximum_model_calls=8,
        maximum_repair_cycles=2,
        extra_slots=(
            _slot("planner"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("notification_adapter", cardinality="many"),
        ),
    ),
    "validation.hardware": _policy(
        "validation.hardware",
        loop_kind="plan_validate",
        maximum_model_calls=4,
        maximum_repair_cycles=1,
        extra_slots=(
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot(
                "telemetry_adapter",
                cardinality="many",
                required=True,
                swap_boundary="idle_only",
                failure_mode="fail_closed",
            ),
        ),
    ),
    "calibration.system": _policy(
        "calibration.system",
        loop_kind="iterative_optimize",
        maximum_model_calls=8,
        maximum_repair_cycles=3,
        extra_slots=(
            _slot("optimizer", cardinality="many"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("telemetry_adapter", cardinality="many", swap_boundary="idle_only"),
        ),
    ),
    "transfer.sim_to_real": _policy(
        "transfer.sim_to_real",
        loop_kind="promotion_pipeline",
        maximum_model_calls=8,
        maximum_repair_cycles=2,
        extra_slots=(
            _slot("planner"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("simulator_adapter", cardinality="many"),
            _slot("telemetry_adapter", cardinality="many", swap_boundary="idle_only"),
        ),
    ),
    "transfer.real_to_sim": _policy(
        "transfer.real_to_sim",
        loop_kind="promotion_pipeline",
        maximum_model_calls=8,
        maximum_repair_cycles=2,
        extra_slots=(
            _slot("planner"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot("simulator_adapter", cardinality="many"),
            _slot("telemetry_adapter", cardinality="many", swap_boundary="idle_only"),
        ),
    ),
    "operations.field": _policy(
        "operations.field",
        loop_kind="observe_repair",
        maximum_model_calls=10,
        maximum_repair_cycles=3,
        extra_slots=(
            _slot("planner", swap_boundary="safe_hold_only"),
            _slot("validator", cardinality="many", required=True, failure_mode="fail_closed"),
            _slot(
                "telemetry_adapter",
                cardinality="many",
                required=True,
                swap_boundary="idle_only",
                failure_mode="fail_closed",
            ),
            _slot("recovery_strategy", cardinality="many", swap_boundary="safe_hold_only"),
            _slot("notification_adapter", cardinality="many"),
        ),
    ),
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ManagedPluginImplementation(_StrictModel):
    module: str = Field(pattern=r"^app(?:\.[a-z][a-z0-9_]*)+$")
    entrypoint: str = Field(pattern=r"^_?[a-z][a-z0-9_]*$")
    source_path: str = Field(pattern=r"^backend/app(?:/[a-z][a-z0-9_]*)+\.py$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManagedPluginApiContract(_StrictModel):
    contract_id: str = Field(pattern=r"^dronedream\.[a-z0-9._-]+\.v[0-9]+$")
    input_schema_version: Literal["dronedream.model-harness-input.v1"] = (
        STRUCTURED_INPUT_SCHEMA_VERSION
    )
    output_schema_version: Literal["dronedream.model-harness-output.v1"] = (
        STRUCTURED_OUTPUT_SCHEMA_VERSION
    )


class ManagedPluginManifest(_StrictModel):
    schema_version: Literal["dronedream.managed-plugin-manifest.v1"] = (
        MANAGED_PLUGIN_MANIFEST_SCHEMA_VERSION
    )
    slot: PluginCapability
    plugin_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])?$",
    )
    version: str = Field(min_length=1, max_length=64)
    trust: Literal["managed"] = "managed"
    implementation: ManagedPluginImplementation
    api_contract: ManagedPluginApiContract


class PluginSelection(_StrictModel):
    """A content-bound plugin selection; never an arbitrary import path."""

    slot: PluginCapability
    plugin_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])?$",
    )
    version: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    trust: PluginTrust
    source: PluginSelectionSource = "explicit"
    selected_by: PluginSelectionAuthority = "product_managed"

    @model_validator(mode="after")
    def _validate_identity(self) -> PluginSelection:
        if not _PLUGIN_ID_PATTERN.fullmatch(self.plugin_id):
            raise ValueError("plugin_id must be a stable lowercase identifier")
        if not _SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return self


class HarnessControlPlaneReceipt(_StrictModel):
    schema_version: Literal["dronedream.model-harness-control-plane.v1"] = (
        CONTROL_PLANE_SCHEMA_VERSION
    )
    structured_input_schema_version: Literal["dronedream.model-harness-input.v1"] = (
        STRUCTURED_INPUT_SCHEMA_VERSION
    )
    structured_output_schema_version: Literal["dronedream.model-harness-output.v1"] = (
        STRUCTURED_OUTPUT_SCHEMA_VERSION
    )
    domain: ModelHarnessDomain
    loop_kind: HarnessLoopKind
    hard_maximum_model_calls: int = Field(ge=1)
    hard_maximum_repair_cycles: int = Field(ge=0)
    effective_maximum_model_calls: int = Field(ge=1)
    effective_maximum_repair_cycles: int = Field(ge=0)
    fixed_kernel_responsibilities: tuple[FixedKernelResponsibility, ...]
    readable_memory_domains: tuple[MemoryDomain, ...]
    writable_memory_domain: MemoryDomain
    memory_retrieval_policy_version: Literal["dronedream.memory-retrieval-policy.v1"] = (
        MEMORY_RETRIEVAL_POLICY_VERSION
    )
    learning_promotion_policy_version: Literal["dronedream.learning-promotion-policy.v1"] = (
        LEARNING_PROMOTION_POLICY_VERSION
    )
    semantic_memory_authority: Literal["advisory_only"] = "advisory_only"
    online_policy_updates_allowed: Literal[False] = False
    execution_authority_enforcement: Literal["not_integrated"] = "not_integrated"
    grants_execution_authority: Literal[False] = False
    plugin_selection_effect: Literal["contract_only"] = "contract_only"
    plugin_runtime_receipt_ids: tuple[()] = ()
    selected_plugins: tuple[PluginSelection, ...]
    selection_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def _validate_effective_caps(self) -> HarnessControlPlaneReceipt:
        if self.effective_maximum_model_calls > self.hard_maximum_model_calls:
            raise ValueError("effective model-call cap cannot exceed the immutable hard cap")
        if self.effective_maximum_repair_cycles > self.hard_maximum_repair_cycles:
            raise ValueError("effective repair-cycle cap cannot exceed the immutable hard cap")
        if not _SHA256_PATTERN.fullmatch(self.selection_sha256):
            raise ValueError("selection_sha256 must be a lowercase SHA-256 digest")
        expected_sha256 = hashlib.sha256(
            json.dumps(
                self.selection_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.selection_sha256 != expected_sha256:
            raise ValueError("selection_sha256 does not bind the effective control plane")
        return self

    def selection_payload(self) -> dict[str, object]:
        """Return the canonical content covered by ``selection_sha256``."""

        ordered = sorted(
            self.selected_plugins,
            key=lambda item: (item.slot, item.plugin_id, item.version),
        )
        return {
            "schema_version": self.schema_version,
            "structured_input_schema_version": self.structured_input_schema_version,
            "structured_output_schema_version": self.structured_output_schema_version,
            "domain": self.domain,
            "loop_kind": self.loop_kind,
            "hard_maximum_model_calls": self.hard_maximum_model_calls,
            "hard_maximum_repair_cycles": self.hard_maximum_repair_cycles,
            "effective_maximum_model_calls": self.effective_maximum_model_calls,
            "effective_maximum_repair_cycles": self.effective_maximum_repair_cycles,
            "fixed_kernel_responsibilities": self.fixed_kernel_responsibilities,
            "readable_memory_domains": self.readable_memory_domains,
            "writable_memory_domain": self.writable_memory_domain,
            "memory_retrieval_policy_version": self.memory_retrieval_policy_version,
            "learning_promotion_policy_version": self.learning_promotion_policy_version,
            "semantic_memory_authority": self.semantic_memory_authority,
            "online_policy_updates_allowed": self.online_policy_updates_allowed,
            "execution_authority_enforcement": self.execution_authority_enforcement,
            "grants_execution_authority": self.grants_execution_authority,
            "plugin_selection_effect": self.plugin_selection_effect,
            "plugin_runtime_receipt_ids": self.plugin_runtime_receipt_ids,
            "selected_plugins": [item.model_dump(mode="json") for item in ordered],
        }

    @property
    def maximum_model_calls(self) -> int:
        """Compatibility accessor for callers that consumed the former effective cap."""

        return self.effective_maximum_model_calls

    @property
    def maximum_repair_cycles(self) -> int:
        """Compatibility accessor for callers that consumed the former effective cap."""

        return self.effective_maximum_repair_cycles


class HarnessInputEnvelope(_StrictModel):
    """Structured, owner-bound input presented to one Harness responsibility."""

    schema_version: Literal["dronedream.model-harness-input.v1"] = STRUCTURED_INPUT_SCHEMA_VERSION
    request_id: str = Field(min_length=8, max_length=128)
    task_id: str = Field(min_length=8, max_length=128)
    thread_id: str = Field(min_length=8, max_length=128)
    owner_binding_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    tenant_binding_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    source_edition: SourceEdition
    domain: ModelHarnessDomain
    control_plane_selection_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    current_request: dict[str, object]
    session_context: dict[str, object] = Field(default_factory=dict)
    memory_record_ids: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def _validate_bindings_and_context(self) -> HarnessInputEnvelope:
        for digest in (
            self.owner_binding_sha256,
            self.tenant_binding_sha256,
            self.control_plane_selection_sha256,
        ):
            if not _SHA256_PATTERN.fullmatch(digest):
                raise ValueError("control-plane bindings must be lowercase SHA-256 digests")
        context_bytes = len(
            json.dumps(
                {
                    "current_request": self.current_request,
                    "session_context": self.session_context,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        )
        if context_bytes > 65_536:
            raise ValueError("structured Harness input exceeds 65536 bytes")
        return self


class HarnessOutputEnvelope(_StrictModel):
    """Structured model/Harness result with no implicit execution authority."""

    schema_version: Literal["dronedream.model-harness-output.v1"] = STRUCTURED_OUTPUT_SCHEMA_VERSION
    request_id: str = Field(min_length=8, max_length=128)
    task_id: str = Field(min_length=8, max_length=128)
    domain: ModelHarnessDomain
    control_plane_selection_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    input_envelope_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: HarnessResultStatus
    lifecycle_stage: HarnessLifecycleStage = "proposal"
    structured_result: dict[str, object]
    model_call_count: int = Field(ge=0)
    repair_cycle_count: int = Field(ge=0)
    tool_receipt_ids: tuple[str, ...] = Field(default=(), max_length=128)
    validation_receipt_ids: tuple[str, ...] = Field(default=(), max_length=128)
    evidence_receipt_ids: tuple[str, ...] = Field(default=(), max_length=128)
    memory_candidate_ids: tuple[str, ...] = Field(default=(), max_length=32)
    execution_authority_enforcement: Literal["not_integrated"] = "not_integrated"
    grants_execution_authority: Literal[False] = False
    physical_action_performed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_control_plane_binding(self) -> HarnessOutputEnvelope:
        if not all(
            _SHA256_PATTERN.fullmatch(digest)
            for digest in (
                self.control_plane_selection_sha256,
                self.input_envelope_sha256,
            )
        ):
            raise ValueError("control-plane binding must be a lowercase SHA-256 digest")
        if self.lifecycle_stage == "compile_only" and (
            self.model_call_count != 0 or self.tool_receipt_ids
        ):
            raise ValueError("compile-only output cannot claim model or tool execution")
        if self.lifecycle_stage == "refused" and self.status != "blocked":
            raise ValueError("refused output must have blocked status")
        if self.lifecycle_stage == "execute" and (
            self.status != "closed" or not self.evidence_receipt_ids
        ):
            raise ValueError("execute output requires closed status and evidence receipts")
        return self


_CANONICAL_SCHEMA_MODELS: Final[tuple[tuple[str, str, type[_StrictModel]], ...]] = (
    (
        "managed-plugin-manifest.v1.schema.json",
        "urn:dronedream:schema:model-harness:managed-plugin-manifest:v1",
        ManagedPluginManifest,
    ),
    (
        "control-plane-receipt.v1.schema.json",
        "urn:dronedream:schema:model-harness:control-plane-receipt:v1",
        HarnessControlPlaneReceipt,
    ),
    (
        "harness-input.v1.schema.json",
        "urn:dronedream:schema:model-harness:input:v1",
        HarnessInputEnvelope,
    ),
    (
        "harness-output.v1.schema.json",
        "urn:dronedream:schema:model-harness:output:v1",
        HarnessOutputEnvelope,
    ),
)


def canonical_contract_json_schemas() -> dict[str, dict[str, object]]:
    """Generate the public schemas bound exactly to the runtime Pydantic models."""

    schemas: dict[str, dict[str, object]] = {}
    for filename, schema_id, model in _CANONICAL_SCHEMA_MODELS:
        schema = dict(model.model_json_schema(mode="validation"))
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = schema_id
        schemas[filename] = schema
    return schemas


def harness_input_sha256(input_envelope: HarnessInputEnvelope) -> str:
    """Bind the exact validated structured input without echoing it in output."""

    canonical = json.dumps(
        input_envelope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_output_against_control_plane(
    receipt: HarnessControlPlaneReceipt,
    output: HarnessOutputEnvelope,
    *,
    input_envelope: HarnessInputEnvelope | None = None,
) -> None:
    """Enforce domain, loop budget, and evidence boundaries after model work."""

    if output.domain != receipt.domain:
        raise ValueError("Harness output domain does not match its control-plane receipt")
    if output.control_plane_selection_sha256 != receipt.selection_sha256:
        raise ValueError("Harness output is not bound to its control-plane selection")
    if output.model_call_count > receipt.effective_maximum_model_calls:
        raise ValueError("Harness output exceeds the effective model-call budget")
    if output.repair_cycle_count > receipt.effective_maximum_repair_cycles:
        raise ValueError("Harness output exceeds the effective repair-cycle budget")
    if input_envelope is not None:
        if input_envelope.control_plane_selection_sha256 != receipt.selection_sha256:
            raise ValueError("Harness input is not bound to its control-plane selection")
        if input_envelope.domain != receipt.domain:
            raise ValueError("Harness input domain does not match its control-plane receipt")
        if output.request_id != input_envelope.request_id:
            raise ValueError("Harness output request does not match its input envelope")
        if output.task_id != input_envelope.task_id:
            raise ValueError("Harness output task does not match its input envelope")
        if output.input_envelope_sha256 != harness_input_sha256(input_envelope):
            raise ValueError("Harness output is not bound to its validated input envelope")
    if output.status in {"validated_proposal", "closed"} and not output.validation_receipt_ids:
        raise ValueError("validated Harness output requires a product-owned validation receipt")
    if output.status == "closed" and not output.evidence_receipt_ids:
        raise ValueError("closed Harness output requires an evidence receipt")


def domain_policy(domain: ModelHarnessDomain) -> HarnessDomainPolicy:
    """Return the authoritative policy for one responsibility domain."""

    try:
        return DOMAIN_POLICIES[domain]
    except KeyError as exc:  # pragma: no cover - typing catches normal callers
        raise ValueError("unsupported Model + Harness domain") from exc


def _product_managed_default(
    capability: PluginCapability,
    *,
    manifest_root: Path | None = None,
) -> PluginSelection:
    """Load and verify the checked-in implementation manifest for a required slot."""

    root = manifest_root or _MANAGED_PLUGIN_MANIFEST_ROOT
    path = root / f"{capability}.manifest.json"
    try:
        raw_manifest = path.read_bytes()
        payload = json.loads(raw_manifest)
        manifest = ManagedPluginManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid product-managed plugin manifest for {capability}") from exc
    canonical_manifest = (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    if raw_manifest != canonical_manifest:
        raise ValueError(f"product-managed plugin manifest for {capability} is not canonical")

    expected_plugin_id = f"dronedream.managed.{capability.replace('_', '-')}"
    if manifest.slot != capability or manifest.plugin_id != expected_plugin_id:
        raise ValueError(f"product-managed plugin identity mismatch for {capability}")
    expected_source_path = f"backend/{manifest.implementation.module.replace('.', '/')}.py"
    if manifest.implementation.source_path != expected_source_path:
        raise ValueError(f"product-managed plugin source path mismatch for {capability}")
    source_path = _REPOSITORY_ROOT / expected_source_path
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"product-managed plugin source is missing for {capability}") from exc
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if source_sha256 != manifest.implementation.source_sha256:
        raise ValueError(f"product-managed plugin source digest mismatch for {capability}")
    try:
        source_tree = ast.parse(source_bytes, filename=str(source_path))
    except SyntaxError as exc:  # pragma: no cover - the application would not import either
        raise ValueError(f"product-managed plugin source is invalid for {capability}") from exc
    entrypoints = {
        node.name
        for node in source_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if manifest.implementation.entrypoint not in entrypoints:
        raise ValueError(f"product-managed plugin entrypoint is missing for {capability}")

    content_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    return PluginSelection(
        slot=capability,
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        content_sha256=content_sha256,
        trust=manifest.trust,
        source="product_managed_default",
        selected_by="product_managed",
    )


def compile_control_plane_receipt(
    domain: ModelHarnessDomain,
    selections: tuple[PluginSelection, ...] = (),
    *,
    selection_authority: PluginSelectionAuthority | None = None,
    effective_maximum_model_calls: int | None = None,
    effective_maximum_repair_cycles: int | None = None,
    managed_plugin_manifest_root: Path | None = None,
) -> HarnessControlPlaneReceipt:
    """Validate plugin choices without surrendering fixed-kernel authority."""

    policy = domain_policy(domain)
    if selections and selection_authority is None:
        raise ValueError("explicit plugin selections require a declared selection authority")
    acting_authority: PluginSelectionAuthority = selection_authority or "product_managed"
    slot_by_capability = {slot.capability: slot for slot in policy.plugin_slots}
    grouped: dict[PluginCapability, list[PluginSelection]] = {}
    normalized_selections: list[PluginSelection] = []
    for selection in selections:
        if selection.source != "explicit":
            raise ValueError("product-managed default selections are issued only by the product")
        slot = slot_by_capability.get(selection.slot)
        if slot is None:
            raise ValueError(f"plugin capability {selection.slot!r} is not allowed for {domain}")
        if selection.trust not in slot.allowed_trust:
            raise ValueError(
                f"plugin trust {selection.trust!r} is not allowed for {selection.slot}"
            )
        if acting_authority != "product_managed" and acting_authority != slot.selection_authority:
            raise ValueError(
                f"plugin slot {selection.slot!r} is not selectable by {acting_authority}"
            )
        normalized = selection.model_copy(update={"selected_by": acting_authority})
        normalized_selections.append(normalized)
        grouped.setdefault(selection.slot, []).append(normalized)

    effective: list[PluginSelection] = list(normalized_selections)
    for slot in policy.plugin_slots:
        selected = grouped.get(slot.capability, [])
        if slot.cardinality == "one" and len(selected) > 1:
            raise ValueError(f"plugin capability {slot.capability!r} accepts only one selection")
        if slot.required and not selected:
            effective.append(
                _product_managed_default(
                    slot.capability,
                    manifest_root=managed_plugin_manifest_root,
                )
            )

    selected_model_calls = (
        policy.maximum_model_calls
        if effective_maximum_model_calls is None
        else effective_maximum_model_calls
    )
    selected_repair_cycles = (
        policy.maximum_repair_cycles
        if effective_maximum_repair_cycles is None
        else effective_maximum_repair_cycles
    )
    if selected_model_calls < 1 or selected_model_calls > policy.maximum_model_calls:
        raise ValueError("effective model-call cap must be within the immutable hard cap")
    if selected_repair_cycles < 0 or selected_repair_cycles > policy.maximum_repair_cycles:
        raise ValueError("effective repair-cycle cap must be within the immutable hard cap")

    ordered = tuple(
        sorted(
            effective,
            key=lambda item: (item.slot, item.plugin_id, item.version),
        )
    )
    canonical = {
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "structured_input_schema_version": STRUCTURED_INPUT_SCHEMA_VERSION,
        "structured_output_schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "domain": domain,
        "loop_kind": policy.loop_kind,
        "hard_maximum_model_calls": policy.maximum_model_calls,
        "hard_maximum_repair_cycles": policy.maximum_repair_cycles,
        "effective_maximum_model_calls": selected_model_calls,
        "effective_maximum_repair_cycles": selected_repair_cycles,
        "fixed_kernel_responsibilities": FIXED_KERNEL_RESPONSIBILITIES,
        "readable_memory_domains": policy.readable_memory_domains,
        "writable_memory_domain": policy.writable_memory_domain,
        "memory_retrieval_policy_version": MEMORY_RETRIEVAL_POLICY_VERSION,
        "learning_promotion_policy_version": LEARNING_PROMOTION_POLICY_VERSION,
        "semantic_memory_authority": "advisory_only",
        "online_policy_updates_allowed": False,
        "execution_authority_enforcement": "not_integrated",
        "grants_execution_authority": False,
        "plugin_selection_effect": "contract_only",
        "plugin_runtime_receipt_ids": (),
        "selected_plugins": [item.model_dump(mode="json") for item in ordered],
    }
    selection_sha256 = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return HarnessControlPlaneReceipt(
        domain=domain,
        loop_kind=policy.loop_kind,
        hard_maximum_model_calls=policy.maximum_model_calls,
        hard_maximum_repair_cycles=policy.maximum_repair_cycles,
        effective_maximum_model_calls=selected_model_calls,
        effective_maximum_repair_cycles=selected_repair_cycles,
        fixed_kernel_responsibilities=FIXED_KERNEL_RESPONSIBILITIES,
        readable_memory_domains=policy.readable_memory_domains,
        writable_memory_domain=policy.writable_memory_domain,
        selected_plugins=ordered,
        selection_sha256=selection_sha256,
    )


def canonical_domain_policy_contract() -> dict[str, object]:
    """Return the cross-runtime policy contract for all Harness tasks.

    Python remains the authoring implementation for the typed domain and
    plugin policies.  The exported JSON value is the language-neutral contract
    consumed by the Supabase planner and checked by both Python and Deno tests.
    """

    domains: dict[str, object] = {}
    for domain in MODEL_HARNESS_DOMAIN_VALUES:
        policy = domain_policy(domain)
        domains[domain] = {
            "loop_kind": policy.loop_kind,
            "hard_maximum_model_calls": policy.maximum_model_calls,
            "hard_maximum_repair_cycles": policy.maximum_repair_cycles,
            "readable_memory_domains": list(policy.readable_memory_domains),
            "writable_memory_domain": policy.writable_memory_domain,
            "plugin_slots": [
                {
                    "capability": slot.capability,
                    "cardinality": slot.cardinality,
                    "required": slot.required,
                    "hot_swappable": slot.hot_swappable,
                    "swap_boundary": slot.swap_boundary,
                    "allowed_trust": list(slot.allowed_trust),
                    "failure_mode": slot.failure_mode,
                    "selection_authority": slot.selection_authority,
                    "exposure": slot.exposure,
                }
                for slot in policy.plugin_slots
            ],
        }

    tasks: dict[str, object] = {}
    for task_type, domain in TASK_MODEL_HARNESS_DOMAINS.items():
        effective_model_calls, effective_repair_cycles = MANAGED_ASSISTANT_EFFECTIVE_LIMITS[
            task_type
        ]
        policy = domain_policy(domain)
        if effective_model_calls > policy.maximum_model_calls:
            raise RuntimeError("managed assistant model-call budget exceeds hard policy")
        if effective_repair_cycles > policy.maximum_repair_cycles:
            raise RuntimeError("managed assistant repair budget exceeds hard policy")
        tasks[task_type] = {
            "domain": domain,
            "managed_assistant": {
                "effective_maximum_model_calls": effective_model_calls,
                "effective_maximum_repair_cycles": effective_repair_cycles,
            },
        }

    return {
        "schema_version": DOMAIN_POLICY_CONTRACT_SCHEMA_VERSION,
        "control_plane_schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "structured_input_schema_version": STRUCTURED_INPUT_SCHEMA_VERSION,
        "structured_output_schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "memory_retrieval_policy_version": MEMORY_RETRIEVAL_POLICY_VERSION,
        "learning_promotion_policy_version": LEARNING_PROMOTION_POLICY_VERSION,
        "semantic_memory_authority": "advisory_only",
        "online_policy_updates_allowed": False,
        "execution_authority_enforcement": "not_integrated",
        "grants_execution_authority": False,
        "plugin_selection_effect": "contract_only",
        "plugin_runtime_receipt_ids": [],
        "fixed_kernel_responsibilities": list(FIXED_KERNEL_RESPONSIBILITIES),
        "memory_namespaces": list(MEMORY_DOMAIN_VALUES),
        "tasks": tasks,
        "domains": domains,
    }


def control_plane_catalog() -> dict[str, object]:
    """Return a JSON-ready catalog used by all five editions and the UI."""

    domains: dict[str, object] = {}
    for domain in MODEL_HARNESS_DOMAIN_VALUES:
        policy = domain_policy(domain)
        default_receipt = compile_control_plane_receipt(domain)
        domains[domain] = {
            "loop_kind": policy.loop_kind,
            "hard_maximum_model_calls": policy.maximum_model_calls,
            "hard_maximum_repair_cycles": policy.maximum_repair_cycles,
            "default_effective_maximum_model_calls": (
                default_receipt.effective_maximum_model_calls
            ),
            "default_effective_maximum_repair_cycles": (
                default_receipt.effective_maximum_repair_cycles
            ),
            "readable_memory_domains": policy.readable_memory_domains,
            "writable_memory_domain": policy.writable_memory_domain,
            "default_selected_plugins": [
                selection.model_dump(mode="json") for selection in default_receipt.selected_plugins
            ],
            "plugin_slots": [
                {
                    "capability": slot.capability,
                    "cardinality": slot.cardinality,
                    "required": slot.required,
                    "hot_swappable": slot.hot_swappable,
                    "swap_boundary": slot.swap_boundary,
                    "allowed_trust": slot.allowed_trust,
                    "failure_mode": slot.failure_mode,
                    "selection_authority": slot.selection_authority,
                    "exposure": slot.exposure,
                }
                for slot in policy.plugin_slots
            ],
        }
    return {
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "structured_input_schema_version": STRUCTURED_INPUT_SCHEMA_VERSION,
        "structured_output_schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "fixed_kernel_responsibilities": FIXED_KERNEL_RESPONSIBILITIES,
        "memory_retrieval_policy": {
            "version": MEMORY_RETRIEVAL_POLICY_VERSION,
            "primary_store": "structured_account_and_domain_state",
            "semantic_retrieval": "secondary_advisory",
            "required_filters": ("owner", "tenant", "domain", "status", "ttl"),
            "maximum_records": 12,
            "maximum_context_tokens": 2_000,
            "may_supply_execution_authority": False,
        },
        "learning_promotion_policy": {
            "version": LEARNING_PROMOTION_POLICY_VERSION,
            "online_policy_updates_allowed": False,
            "eligible_training_data": "verified_simulation_or_hardware_receipts",
            "eligible_targets": ("ranking", "routing", "trigger_thresholds"),
            "promotion_gates": (
                "offline_evaluation",
                "holdout_regression",
                "deterministic_safety_validation",
                "signed_promotion_receipt",
            ),
        },
        "plugin_lifecycle_policy": {
            "dependency_missing": "dispose_dependents",
            "dependency_restored": "revalidate_then_reload",
            "resource_cleanup": "registered_disposer_required",
            "failure_isolation": "per_plugin_group",
            "in_flight_mutation": "honor_slot_swap_boundary",
            "unsigned_production_plugins_allowed": False,
        },
        "execution_authority": {
            "integration_status": "not_integrated",
            "receipt_grants_authority": False,
            "output_grants_authority": False,
        },
        "plugin_selection_effect": "contract_only",
        "domains": domains,
    }


__all__ = [
    "CONTROL_PLANE_SCHEMA_VERSION",
    "DOMAIN_POLICY_CONTRACT_SCHEMA_VERSION",
    "DOMAIN_POLICIES",
    "HarnessControlPlaneReceipt",
    "HarnessDomainPolicy",
    "HarnessInputEnvelope",
    "HarnessLifecycleStage",
    "HarnessOutputEnvelope",
    "LEARNING_PROMOTION_POLICY_VERSION",
    "MANAGED_ASSISTANT_EFFECTIVE_LIMITS",
    "MANAGED_PLUGIN_MANIFEST_SCHEMA_VERSION",
    "MEMORY_RETRIEVAL_POLICY_VERSION",
    "ManagedPluginManifest",
    "PluginCapability",
    "PluginExposure",
    "PluginSelection",
    "PluginSelectionAuthority",
    "PluginSelectionSource",
    "PluginSlotPolicy",
    "PluginSwapBoundary",
    "STRUCTURED_INPUT_SCHEMA_VERSION",
    "STRUCTURED_OUTPUT_SCHEMA_VERSION",
    "canonical_contract_json_schemas",
    "canonical_domain_policy_contract",
    "compile_control_plane_receipt",
    "control_plane_catalog",
    "domain_policy",
    "harness_input_sha256",
    "validate_output_against_control_plane",
]
