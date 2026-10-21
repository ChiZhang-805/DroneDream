"""Fail-closed verification for composite benchmark execution inventories.

Desktop, Runtime Base, Engine Pack, PX4, and Gazebo are independently built
components and therefore do not need to share one Git commit.  They do need to
match their individually frozen identities and the compatibility contract
declared by the verified Runtime Base and Engine Pack manifests.

This module is deliberately pure: it performs no filesystem, WSL, desktop,
provider, simulator, or network I/O.  Trusted platform adapters must first
derive :class:`CompositeExecutionObservationV1` from exact bytes and their
cryptographic/content-addressed verification receipts.  A successful result is
still evidence only and never authorizes execution by itself.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import (
    CompositeExecutionInventoryV1,
    ExecutionComponentV1,
    GitCommit,
    Identifier,
    Sha256Hex,
    canonical_sha256,
)

COMPOSITE_EXECUTION_VERIFICATION_SCHEMA_ID: Final[
    Literal["dronedream.composite-execution-verification/v1"]
] = "dronedream.composite-execution-verification/v1"
COMPOSITE_EXECUTION_OBSERVATION_SCHEMA_ID: Final[
    Literal["dronedream.composite-execution-observation/v1"]
] = "dronedream.composite-execution-observation/v1"
COMPOSITE_EXECUTION_VERIFICATION_POLICY_VERSION: Final[
    Literal["composite-compatibility-v1"]
] = "composite-compatibility-v1"

RuntimeBuildId: TypeAlias = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    ),
]
PackId: TypeAlias = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VerifiedExecutionComponentObservationV1(_StrictFrozen):
    """Identity derived by a trusted adapter from exact component bytes."""

    schema_id: Literal["dronedream.verified-execution-component/v1"] = (
        "dronedream.verified-execution-component/v1"
    )
    component: ExecutionComponentV1
    verification_method: Literal[
        "signed-release-manifest",
        "trusted-embedded-manifest",
        "source-pinned-by-runtime-manifest",
    ]
    manifest_bytes_sha256: Sha256Hex
    artifact_bytes_sha256: Sha256Hex | None = None
    integrity_verified: Literal[True] = True
    authenticity_verified: Literal[True] = True
    verification_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def _bind_exact_bytes(self) -> VerifiedExecutionComponentObservationV1:
        if self.manifest_bytes_sha256 != self.component.manifest_sha256:
            raise ValueError(
                "observed manifest bytes do not match the component manifest hash"
            )
        if self.artifact_bytes_sha256 != self.component.artifact_sha256:
            raise ValueError(
                "observed artifact bytes do not match the component artifact hash"
            )
        if (
            self.verification_method == "source-pinned-by-runtime-manifest"
            and self.component.source_commit is None
        ):
            raise ValueError(
                "source-pinned components require a source commit in the inventory"
            )
        return self


class RuntimeBaseCompatibilityObservationV1(_StrictFrozen):
    component_observation: VerifiedExecutionComponentObservationV1
    runtime_product_id: Literal["DroneDreamRuntime"] = "DroneDreamRuntime"
    runtime_build_id: RuntimeBuildId
    runtime_source_commit: GitCommit
    runtime_version: Annotated[str, Field(min_length=1, max_length=128)]
    python_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+$")]
    dependency_lock_sha256: Sha256Hex
    px4_version: Annotated[str, Field(min_length=1, max_length=128)]
    px4_commit: GitCommit
    gazebo_version: Annotated[str, Field(min_length=1, max_length=128)]
    smoke_promoted: Literal[True] = True


class EnginePackCompatibilityObservationV1(_StrictFrozen):
    component_observation: VerifiedExecutionComponentObservationV1
    pack_id: PackId
    engine_source_commit: GitCommit
    engine_api_version: Literal[1] = 1
    required_runtime_product_id: Literal["DroneDreamRuntime"] = "DroneDreamRuntime"
    required_runtime_version: Annotated[str, Field(min_length=1, max_length=128)]
    required_python_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+$")]
    required_dependency_lock_sha256: Sha256Hex
    required_px4_commit: GitCommit
    required_gazebo_version: Annotated[str, Field(min_length=1, max_length=128)]


class DesktopCompatibilityObservationV1(_StrictFrozen):
    component_observation: VerifiedExecutionComponentObservationV1
    supported_runtime_product_id: Literal["DroneDreamRuntime"] = "DroneDreamRuntime"
    expected_engine_api_version: Literal[1] = 1


class CompositeExecutionObservationV1(_StrictFrozen):
    """Trusted, sanitized observations used to verify one frozen inventory."""

    schema_id: Literal["dronedream.composite-execution-observation/v1"] = (
        COMPOSITE_EXECUTION_OBSERVATION_SCHEMA_ID
    )
    repository_subject_commit: GitCommit
    evaluator_subject_commit: GitCommit
    campaign_coordinator_subject_commit: GitCommit
    evidence_head_commit: GitCommit | None = None
    desktop: DesktopCompatibilityObservationV1 | None = None
    runtime_base: RuntimeBaseCompatibilityObservationV1
    engine_pack: EnginePackCompatibilityObservationV1
    px4: VerifiedExecutionComponentObservationV1
    gazebo: VerifiedExecutionComponentObservationV1
    prompt_registry_sha256: Sha256Hex
    response_schema_sha256: Sha256Hex
    tool_registry_sha256: Sha256Hex
    model_matrix_sha256: Sha256Hex
    machine_profile_sha256: Sha256Hex
    concurrency_profile_sha256: Sha256Hex
    observation_adapter_receipt_sha256: Sha256Hex


class CompositeExecutionVerificationReceiptV1(_StrictFrozen):
    schema_id: Literal["dronedream.composite-execution-verification/v1"] = (
        COMPOSITE_EXECUTION_VERIFICATION_SCHEMA_ID
    )
    policy_version: Literal["composite-compatibility-v1"] = (
        COMPOSITE_EXECUTION_VERIFICATION_POLICY_VERSION
    )
    status: Literal["verified", "denied"]
    compatible: bool
    execution_authorized: Literal[False] = False
    components_may_use_distinct_source_commits: Literal[True] = True
    inventory_sha256: Sha256Hex
    observation_sha256: Sha256Hex
    compatibility_summary_sha256: Sha256Hex
    verification_contract_sha256: Sha256Hex
    verified_component_ids: tuple[Identifier, ...]
    reason_codes: tuple[Identifier, ...]

    @model_validator(mode="after")
    def _validate_result_semantics(self) -> CompositeExecutionVerificationReceiptV1:
        if self.status == "verified":
            if not self.compatible or self.reason_codes:
                raise ValueError("verified receipt cannot contain denial reasons")
            if not self.verified_component_ids:
                raise ValueError("verified receipt must identify verified components")
        elif self.compatible or not self.reason_codes or self.verified_component_ids:
            raise ValueError(
                "denied receipt must contain reasons and no verified component claim"
            )
        return self


_VERIFICATION_CONTRACT: Final[dict[str, object]] = {
    "schema_id": COMPOSITE_EXECUTION_VERIFICATION_SCHEMA_ID,
    "policy_version": COMPOSITE_EXECUTION_VERIFICATION_POLICY_VERSION,
    "component_identity": "exact-inventory-match",
    "source_policy": "independent-commits-allowed",
    "compatibility_edges": [
        "desktop-engine-api",
        "desktop-runtime-product",
        "runtime-engine-product-version-python-lock",
        "runtime-engine-px4",
        "runtime-engine-gazebo",
        "runtime-px4-component",
        "runtime-gazebo-component",
    ],
    "execution_authorized": False,
}
COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256: Final[str] = canonical_sha256(
    _VERIFICATION_CONTRACT
)


def _append_reason(reasons: list[str], code: str, condition: bool) -> None:
    if condition and code not in reasons:
        reasons.append(code)


def _component_mismatch(
    expected: ExecutionComponentV1,
    observed: VerifiedExecutionComponentObservationV1,
) -> bool:
    return expected.model_dump(mode="json") != observed.component.model_dump(mode="json")


def _compatibility_summary(
    observation: CompositeExecutionObservationV1,
) -> dict[str, object]:
    return {
        "desktop_expected_engine_api_version": (
            observation.desktop.expected_engine_api_version
            if observation.desktop is not None
            else None
        ),
        "runtime_product_id": observation.runtime_base.runtime_product_id,
        "runtime_build_id": observation.runtime_base.runtime_build_id,
        "runtime_version": observation.runtime_base.runtime_version,
        "runtime_source_commit": observation.runtime_base.runtime_source_commit,
        "python_version": observation.runtime_base.python_version,
        "dependency_lock_sha256": observation.runtime_base.dependency_lock_sha256,
        "px4_version": observation.runtime_base.px4_version,
        "px4_commit": observation.runtime_base.px4_commit,
        "gazebo_version": observation.runtime_base.gazebo_version,
        "engine_pack_id": observation.engine_pack.pack_id,
        "engine_api_version": observation.engine_pack.engine_api_version,
        "engine_source_commit": observation.engine_pack.engine_source_commit,
        "required_runtime_product_id": (
            observation.engine_pack.required_runtime_product_id
        ),
        "required_runtime_version": observation.engine_pack.required_runtime_version,
        "required_python_version": observation.engine_pack.required_python_version,
        "required_dependency_lock_sha256": (
            observation.engine_pack.required_dependency_lock_sha256
        ),
        "required_px4_commit": observation.engine_pack.required_px4_commit,
        "required_gazebo_version": observation.engine_pack.required_gazebo_version,
    }


def verify_composite_execution_inventory(
    inventory: CompositeExecutionInventoryV1,
    observation: CompositeExecutionObservationV1,
) -> CompositeExecutionVerificationReceiptV1:
    """Return deterministic compatibility evidence; never authorize execution."""

    reasons: list[str] = []
    _append_reason(
        reasons,
        "repository-subject-mismatch",
        inventory.repository_subject_commit != observation.repository_subject_commit,
    )
    _append_reason(
        reasons,
        "evaluator-subject-mismatch",
        inventory.evaluator_subject_commit != observation.evaluator_subject_commit,
    )
    _append_reason(
        reasons,
        "coordinator-subject-mismatch",
        inventory.campaign_coordinator_subject_commit
        != observation.campaign_coordinator_subject_commit,
    )
    _append_reason(
        reasons,
        "evidence-head-mismatch",
        inventory.evidence_head_commit != observation.evidence_head_commit,
    )

    if inventory.desktop is None or observation.desktop is None:
        _append_reason(
            reasons,
            "desktop-presence-mismatch",
            (inventory.desktop is None) != (observation.desktop is None),
        )
    else:
        _append_reason(
            reasons,
            "desktop-identity-mismatch",
            _component_mismatch(
                inventory.desktop, observation.desktop.component_observation
            ),
        )

    for component_label, expected_component, observed_component in (
        (
            "runtime-base",
            inventory.runtime_base,
            observation.runtime_base.component_observation,
        ),
        (
            "engine-pack",
            inventory.engine_pack,
            observation.engine_pack.component_observation,
        ),
        ("px4", inventory.px4, observation.px4),
        ("gazebo", inventory.gazebo, observation.gazebo),
    ):
        _append_reason(
            reasons,
            f"{component_label}-identity-mismatch",
            _component_mismatch(expected_component, observed_component),
        )

    for registry_label, expected_hash, observed_hash in (
        (
            "prompt-registry",
            inventory.prompt_registry_sha256,
            observation.prompt_registry_sha256,
        ),
        (
            "response-schema",
            inventory.response_schema_sha256,
            observation.response_schema_sha256,
        ),
        ("tool-registry", inventory.tool_registry_sha256, observation.tool_registry_sha256),
        ("model-matrix", inventory.model_matrix_sha256, observation.model_matrix_sha256),
        (
            "machine-profile",
            inventory.machine_profile_sha256,
            observation.machine_profile_sha256,
        ),
        (
            "concurrency-profile",
            inventory.concurrency_profile_sha256,
            observation.concurrency_profile_sha256,
        ),
    ):
        _append_reason(
            reasons,
            f"{registry_label}-mismatch",
            expected_hash != observed_hash,
        )

    runtime = observation.runtime_base
    engine = observation.engine_pack
    _append_reason(
        reasons,
        "runtime-source-internal-mismatch",
        runtime.component_observation.component.source_commit
        != runtime.runtime_source_commit,
    )
    _append_reason(
        reasons,
        "runtime-version-internal-mismatch",
        runtime.component_observation.component.version != runtime.runtime_version,
    )
    _append_reason(
        reasons,
        "engine-source-internal-mismatch",
        engine.component_observation.component.source_commit
        != engine.engine_source_commit,
    )
    _append_reason(
        reasons,
        "engine-runtime-product-mismatch",
        engine.required_runtime_product_id != runtime.runtime_product_id,
    )
    _append_reason(
        reasons,
        "engine-runtime-version-mismatch",
        engine.required_runtime_version != runtime.runtime_version,
    )
    _append_reason(
        reasons,
        "engine-python-version-mismatch",
        engine.required_python_version != runtime.python_version,
    )
    _append_reason(
        reasons,
        "engine-dependency-lock-mismatch",
        engine.required_dependency_lock_sha256 != runtime.dependency_lock_sha256,
    )
    _append_reason(
        reasons,
        "runtime-px4-component-mismatch",
        runtime.px4_commit != observation.px4.component.source_commit
        or runtime.px4_version != observation.px4.component.version,
    )
    _append_reason(
        reasons,
        "engine-px4-mismatch",
        engine.required_px4_commit != runtime.px4_commit,
    )
    _append_reason(
        reasons,
        "runtime-gazebo-component-mismatch",
        runtime.gazebo_version != observation.gazebo.component.version,
    )
    _append_reason(
        reasons,
        "engine-gazebo-mismatch",
        engine.required_gazebo_version != runtime.gazebo_version,
    )
    if observation.desktop is not None:
        _append_reason(
            reasons,
            "desktop-engine-api-mismatch",
            observation.desktop.expected_engine_api_version != engine.engine_api_version,
        )
        _append_reason(
            reasons,
            "desktop-runtime-product-mismatch",
            observation.desktop.supported_runtime_product_id
            != runtime.runtime_product_id,
        )

    status: Literal["verified", "denied"] = "denied" if reasons else "verified"
    component_ids: tuple[str, ...] = ()
    if status == "verified":
        component_ids = tuple(
            item.component_id
            for item in (
                *([inventory.desktop] if inventory.desktop is not None else []),
                inventory.runtime_base,
                inventory.engine_pack,
                inventory.px4,
                inventory.gazebo,
            )
        )
    return CompositeExecutionVerificationReceiptV1(
        status=status,
        compatible=status == "verified",
        inventory_sha256=canonical_sha256(inventory),
        observation_sha256=canonical_sha256(observation),
        compatibility_summary_sha256=canonical_sha256(
            _compatibility_summary(observation)
        ),
        verification_contract_sha256=(
            COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256
        ),
        verified_component_ids=component_ids,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "COMPOSITE_EXECUTION_OBSERVATION_SCHEMA_ID",
    "COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256",
    "COMPOSITE_EXECUTION_VERIFICATION_POLICY_VERSION",
    "COMPOSITE_EXECUTION_VERIFICATION_SCHEMA_ID",
    "CompositeExecutionObservationV1",
    "CompositeExecutionVerificationReceiptV1",
    "DesktopCompatibilityObservationV1",
    "EnginePackCompatibilityObservationV1",
    "RuntimeBaseCompatibilityObservationV1",
    "VerifiedExecutionComponentObservationV1",
    "verify_composite_execution_inventory",
]
