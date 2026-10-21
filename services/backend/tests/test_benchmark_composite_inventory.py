from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.benchmarking.composite_inventory import (
    COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256,
    CompositeExecutionObservationV1,
    verify_composite_execution_inventory,
)
from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256

_REPO = "1" * 40
_EVALUATOR = "2" * 40
_COORDINATOR = "3" * 40
_DESKTOP_SOURCE = "4" * 40
_RUNTIME_SOURCE = "5" * 40
_ENGINE_SOURCE = "6" * 40
_PX4_SOURCE = "7" * 40
_SHA = {
    name: f"{index:064x}"
    for index, name in enumerate(
        (
            "desktop_manifest",
            "desktop_artifact",
            "runtime_manifest",
            "runtime_artifact",
            "engine_manifest",
            "engine_artifact",
            "px4_manifest",
            "gazebo_manifest",
            "prompt",
            "schema",
            "tool",
            "model",
            "machine",
            "concurrency",
            "adapter_receipt",
            "desktop_receipt",
            "runtime_receipt",
            "engine_receipt",
            "px4_receipt",
            "gazebo_receipt",
            "dependency_lock",
        ),
        start=1,
    )
}


def _component(
    component_id: str,
    version: str,
    source_commit: str | None,
    manifest_sha256: str,
    artifact_sha256: str | None,
) -> dict[str, object]:
    return {
        "component_id": component_id,
        "version": version,
        "source_commit": source_commit,
        "manifest_sha256": manifest_sha256,
        "artifact_sha256": artifact_sha256,
    }


def _inventory_payload(*, with_desktop: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository_subject_commit": _REPO,
        "evaluator_subject_commit": _EVALUATOR,
        "campaign_coordinator_subject_commit": _COORDINATOR,
        "desktop": (
            _component(
                "desktop",
                "1.0.0",
                _DESKTOP_SOURCE,
                _SHA["desktop_manifest"],
                _SHA["desktop_artifact"],
            )
            if with_desktop
            else None
        ),
        "runtime_base": _component(
            "runtime-base",
            "0.1.0",
            _RUNTIME_SOURCE,
            _SHA["runtime_manifest"],
            _SHA["runtime_artifact"],
        ),
        "engine_pack": _component(
            "engine-pack",
            "engine-pack-v1",
            _ENGINE_SOURCE,
            _SHA["engine_manifest"],
            _SHA["engine_artifact"],
        ),
        "px4": _component(
            "px4",
            "v1.16.0",
            _PX4_SOURCE,
            _SHA["px4_manifest"],
            None,
        ),
        "gazebo": _component(
            "gazebo",
            "harmonic@1.0.0-1~noble",
            None,
            _SHA["gazebo_manifest"],
            None,
        ),
        "prompt_registry_sha256": _SHA["prompt"],
        "response_schema_sha256": _SHA["schema"],
        "tool_registry_sha256": _SHA["tool"],
        "model_matrix_sha256": _SHA["model"],
        "machine_profile_sha256": _SHA["machine"],
        "concurrency_profile_sha256": _SHA["concurrency"],
    }
    return payload


def _verified_component(
    component: dict[str, object],
    *,
    method: str,
    receipt_sha256: str,
) -> dict[str, object]:
    return {
        "component": component,
        "verification_method": method,
        "manifest_bytes_sha256": component["manifest_sha256"],
        "artifact_bytes_sha256": component["artifact_sha256"],
        "integrity_verified": True,
        "authenticity_verified": True,
        "verification_receipt_sha256": receipt_sha256,
    }


def _observation_payload(*, with_desktop: bool = True) -> dict[str, object]:
    inventory = _inventory_payload(with_desktop=with_desktop)
    runtime_component = inventory["runtime_base"]
    engine_component = inventory["engine_pack"]
    px4_component = inventory["px4"]
    gazebo_component = inventory["gazebo"]
    assert isinstance(runtime_component, dict)
    assert isinstance(engine_component, dict)
    assert isinstance(px4_component, dict)
    assert isinstance(gazebo_component, dict)
    desktop = inventory["desktop"]
    return {
        "repository_subject_commit": _REPO,
        "evaluator_subject_commit": _EVALUATOR,
        "campaign_coordinator_subject_commit": _COORDINATOR,
        "desktop": (
            {
                "component_observation": _verified_component(
                    desktop,
                    method="signed-release-manifest",
                    receipt_sha256=_SHA["desktop_receipt"],
                ),
                "supported_runtime_product_id": "DroneDreamRuntime",
                "expected_engine_api_version": 1,
            }
            if isinstance(desktop, dict)
            else None
        ),
        "runtime_base": {
            "component_observation": _verified_component(
                runtime_component,
                method="signed-release-manifest",
                receipt_sha256=_SHA["runtime_receipt"],
            ),
            "runtime_product_id": "DroneDreamRuntime",
            "runtime_build_id": "12345678-1234-5678-9abc-1234567890ab",
            "runtime_source_commit": _RUNTIME_SOURCE,
            "runtime_version": "0.1.0",
            "python_version": "3.12",
            "dependency_lock_sha256": _SHA["dependency_lock"],
            "px4_version": "v1.16.0",
            "px4_commit": _PX4_SOURCE,
            "gazebo_version": "harmonic@1.0.0-1~noble",
            "smoke_promoted": True,
        },
        "engine_pack": {
            "component_observation": _verified_component(
                engine_component,
                method="trusted-embedded-manifest",
                receipt_sha256=_SHA["engine_receipt"],
            ),
            "pack_id": "sha256:" + "a" * 64,
            "engine_source_commit": _ENGINE_SOURCE,
            "engine_api_version": 1,
            "required_runtime_product_id": "DroneDreamRuntime",
            "required_runtime_version": "0.1.0",
            "required_python_version": "3.12",
            "required_dependency_lock_sha256": _SHA["dependency_lock"],
            "required_px4_commit": _PX4_SOURCE,
            "required_gazebo_version": "harmonic@1.0.0-1~noble",
        },
        "px4": _verified_component(
            px4_component,
            method="source-pinned-by-runtime-manifest",
            receipt_sha256=_SHA["px4_receipt"],
        ),
        "gazebo": _verified_component(
            gazebo_component,
            method="signed-release-manifest",
            receipt_sha256=_SHA["gazebo_receipt"],
        ),
        "prompt_registry_sha256": _SHA["prompt"],
        "response_schema_sha256": _SHA["schema"],
        "tool_registry_sha256": _SHA["tool"],
        "model_matrix_sha256": _SHA["model"],
        "machine_profile_sha256": _SHA["machine"],
        "concurrency_profile_sha256": _SHA["concurrency"],
        "observation_adapter_receipt_sha256": _SHA["adapter_receipt"],
    }


def _verify(
    inventory_payload: dict[str, object],
    observation_payload: dict[str, object],
):
    return verify_composite_execution_inventory(
        CompositeExecutionInventoryV1.model_validate(inventory_payload),
        CompositeExecutionObservationV1.model_validate(observation_payload),
    )


def test_verifies_compatible_components_from_distinct_source_commits() -> None:
    inventory_payload = _inventory_payload()
    observation_payload = _observation_payload()

    receipt = _verify(inventory_payload, observation_payload)

    assert receipt.status == "verified"
    assert receipt.compatible is True
    assert receipt.execution_authorized is False
    assert receipt.components_may_use_distinct_source_commits is True
    assert receipt.reason_codes == ()
    assert receipt.verified_component_ids == (
        "desktop",
        "runtime-base",
        "engine-pack",
        "px4",
        "gazebo",
    )
    assert receipt.inventory_sha256 == canonical_sha256(
        CompositeExecutionInventoryV1.model_validate(inventory_payload)
    )
    assert (
        receipt.verification_contract_sha256
        == COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256
    )
    assert len(
        {
            _REPO,
            _EVALUATOR,
            _COORDINATOR,
            _DESKTOP_SOURCE,
            _RUNTIME_SOURCE,
            _ENGINE_SOURCE,
            _PX4_SOURCE,
        }
    ) == 7


@pytest.mark.parametrize(
    ("path", "replacement", "reason"),
    (
        (("repository_subject_commit",), "9" * 40, "repository-subject-mismatch"),
        (("prompt_registry_sha256",), "f" * 64, "prompt-registry-mismatch"),
        (("runtime_base", "runtime_version"), "0.2.0", "runtime-version-internal-mismatch"),
        (
            ("engine_pack", "required_python_version"),
            "3.11",
            "engine-python-version-mismatch",
        ),
        (("engine_pack", "required_px4_commit"), "8" * 40, "engine-px4-mismatch"),
        (
            ("engine_pack", "required_gazebo_version"),
            "harmonic@different",
            "engine-gazebo-mismatch",
        ),
        (
            ("desktop", "component_observation", "component", "version"),
            "1.0.1",
            "desktop-identity-mismatch",
        ),
    ),
)
def test_denies_identity_registry_and_compatibility_drift(
    path: tuple[str, ...], replacement: object, reason: str
) -> None:
    inventory_payload = _inventory_payload()
    observation_payload = _observation_payload()
    cursor: dict[str, object] = observation_payload
    for key in path[:-1]:
        value = cursor[key]
        assert isinstance(value, dict)
        cursor = value
    cursor[path[-1]] = replacement

    receipt = _verify(inventory_payload, observation_payload)

    assert receipt.status == "denied"
    assert receipt.compatible is False
    assert receipt.execution_authorized is False
    assert reason in receipt.reason_codes
    assert receipt.verified_component_ids == ()


def test_denies_desktop_presence_drift_but_allows_declared_headless_inventory() -> None:
    with_desktop = _verify(_inventory_payload(), _observation_payload(with_desktop=False))
    assert with_desktop.status == "denied"
    assert "desktop-presence-mismatch" in with_desktop.reason_codes

    headless = _verify(
        _inventory_payload(with_desktop=False),
        _observation_payload(with_desktop=False),
    )
    assert headless.status == "verified"
    assert headless.verified_component_ids == (
        "runtime-base",
        "engine-pack",
        "px4",
        "gazebo",
    )


def test_component_observation_rejects_manifest_and_artifact_byte_drift() -> None:
    observation_payload = _observation_payload()
    tampered_manifest = deepcopy(observation_payload)
    tampered_manifest["runtime_base"]["component_observation"][
        "manifest_bytes_sha256"
    ] = "f" * 64
    with pytest.raises(ValidationError, match="observed manifest bytes"):
        CompositeExecutionObservationV1.model_validate(tampered_manifest)

    tampered_artifact = deepcopy(observation_payload)
    tampered_artifact["engine_pack"]["component_observation"][
        "artifact_bytes_sha256"
    ] = "e" * 64
    with pytest.raises(ValidationError, match="observed artifact bytes"):
        CompositeExecutionObservationV1.model_validate(tampered_artifact)


def test_unknown_schema_fields_and_unpinned_source_fail_closed() -> None:
    unknown = _observation_payload()
    unknown["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CompositeExecutionObservationV1.model_validate(unknown)

    unpinned = _observation_payload()
    unpinned["px4"]["component"]["source_commit"] = None
    with pytest.raises(ValidationError, match="source-pinned components require"):
        CompositeExecutionObservationV1.model_validate(unpinned)
