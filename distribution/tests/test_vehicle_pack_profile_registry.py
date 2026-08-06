from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module(
    "distribution_contract_vehicle_profile_registry_tests",
    DISTRIBUTION / "tools/distribution_contract.py",
)
PROFILE_REGISTRY_PATH = DISTRIBUTION / "vehicle-packs/registry.sim-only.v1.json"
SOURCE_REGISTRY_PATH = DISTRIBUTION / "vehicle-packs/registry.v1.json"
PACK_PATH = DISTRIBUTION / "vehicle-packs/px4-gazebo-x500-reference.v1.json"
PACK_RELATIVE = PACK_PATH.relative_to(ROOT).as_posix()


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def validated_pack() -> dict[str, object]:
    upstream = contract.validate_upstream_source_inventory(
        load(DISTRIBUTION / "upstream-sources.v1.json")
    )
    capability_path = DISTRIBUTION / "capabilities/core-capabilities.v1.json"
    return contract.validate_vehicle_pack_manifest(
        load(PACK_PATH),
        upstream_inventory=upstream,
        capability_policy_sha256=contract.sha256_file(capability_path),
    )


def validate(document: dict[str, object]) -> dict[str, object]:
    return contract.validate_vehicle_pack_registry(
        document,
        vehicle_packs_by_path={PACK_RELATIVE: validated_pack()},
        vehicle_pack_manifest_sha256={PACK_RELATIVE: contract.sha256_file(PACK_PATH)},
        source_registry_document=load(SOURCE_REGISTRY_PATH),
        source_registry_sha256=contract.sha256_file(SOURCE_REGISTRY_PATH),
    )


def test_profile_registry_is_an_exact_source_bound_x500_projection() -> None:
    registry = load(PROFILE_REGISTRY_PATH)
    assert validate(registry) == registry
    assert registry["profileId"] == "sim-only"
    policy = registry["policy"]
    assert isinstance(policy, dict)
    assert policy["hardwareMetadataAllowed"] is False
    assert policy["allowedPackIds"] == ["px4-gazebo-x500-reference"]


def test_profile_registry_rejects_source_hash_or_projection_drift() -> None:
    registry = load(PROFILE_REGISTRY_PATH)
    bad_hash = deepcopy(registry)
    source = bad_hash["sourceRegistry"]
    assert isinstance(source, dict)
    source["sha256"] = "0" * 64
    with pytest.raises(contract.DistributionContractError, match="source registry hash drifted"):
        validate(bad_hash)

    changed_projection = deepcopy(registry)
    packs = changed_projection["packs"]
    assert isinstance(packs, list) and isinstance(packs[0], dict)
    packs[0]["goldenCandidate"] = False
    with pytest.raises(contract.DistributionContractError, match="projection drifted"):
        validate(changed_projection)


def test_profile_registry_rejects_extra_or_hardware_vehicle_metadata() -> None:
    registry = load(PROFILE_REGISTRY_PATH)
    with pytest.raises(
        contract.DistributionContractError,
        match="exactly the X500 reference manifest",
    ):
        contract.validate_vehicle_pack_registry(
            registry,
            vehicle_packs_by_path={
                PACK_RELATIVE: validated_pack(),
                "distribution/vehicle-packs/unexpected.v1.json": validated_pack(),
            },
            vehicle_pack_manifest_sha256={
                PACK_RELATIVE: contract.sha256_file(PACK_PATH),
                "distribution/vehicle-packs/unexpected.v1.json": "0" * 64,
            },
        )

    hardware_pack = deepcopy(validated_pack())
    components = hardware_pack["components"]
    assert isinstance(components, dict) and isinstance(components["hardware"], dict)
    components["hardware"]["status"] = "planned"
    with pytest.raises(contract.DistributionContractError, match="physical hardware metadata"):
        contract.validate_vehicle_pack_registry(
            registry,
            vehicle_packs_by_path={PACK_RELATIVE: hardware_pack},
            vehicle_pack_manifest_sha256={PACK_RELATIVE: contract.sha256_file(PACK_PATH)},
        )


def test_profile_registry_rejects_unknown_fields() -> None:
    registry = load(PROFILE_REGISTRY_PATH)
    registry["unexpected"] = True
    with pytest.raises(contract.DistributionContractError, match="fields are invalid"):
        validate(registry)
