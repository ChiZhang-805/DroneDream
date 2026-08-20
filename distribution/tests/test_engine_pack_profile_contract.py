from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/tools/engine_pack_profile_contract.py"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module("engine_pack_profile_contract_tests", CONTRACT_PATH)


def test_sim_profile_is_versioned_source_bound_and_complete() -> None:
    profile = contract.load_profile(ROOT)
    contract.verify_profile_files(ROOT, profile, active_payload=False)
    binding = contract.profile_manifest_binding(profile, ROOT)
    assert binding == {
        "profileId": "sim-only",
        "profileVersion": "1.0.0",
        "profileManifestPath": contract.PROFILE_PATH,
        "profileManifestSha256": contract.sha256_file(ROOT / contract.PROFILE_PATH),
        "includesLargeSimulator": True,
        "excludedSourcePaths": ["backend/app/distribution_safety.py"],
    }


def test_sim_profile_rejects_unknown_fields_and_mapping_hash_drift() -> None:
    profile = contract.load_profile(ROOT)
    unknown = deepcopy(profile)
    unknown["unexpected"] = True
    with pytest.raises(contract.EnginePackProfileError, match="fields do not match"):
        contract.validate_profile(unknown)

    drifted = deepcopy(profile)
    drifted["sourceMappings"][0]["sourceSha256"] = "0" * 64
    contract.validate_profile(drifted)
    with pytest.raises(contract.EnginePackProfileError, match="source mapping drifted"):
        contract.verify_profile_files(ROOT, drifted, active_payload=False)


def test_sim_profile_payload_inventory_rejects_hardware_or_missing_simulator() -> None:
    profile = contract.load_profile(ROOT)
    files = sorted(
        {
            *profile["directPayloadPaths"],
            *(mapping["payloadPath"] for mapping in profile["sourceMappings"]),
            "backend/app/simulator/base.py",
            "scripts/simulators/px4_gazebo_runner.py",
        }
    )
    contract.validate_payload_paths(profile, files)

    with pytest.raises(contract.EnginePackProfileError, match="forbidden file"):
        contract.validate_payload_paths(
            profile,
            sorted({*files, "distribution/editions/lab.v1.json"}),
        )
    without_launcher = [path for path in files if not path.startswith("scripts/simulators/")]
    with pytest.raises(contract.EnginePackProfileError, match="launcher support"):
        contract.validate_payload_paths(profile, without_launcher)


def test_profile_json_bytes_are_frozen_and_schema_is_closed() -> None:
    profile_path = ROOT / contract.PROFILE_PATH
    raw = profile_path.read_bytes()
    profile = json.loads(raw)
    assert set(profile) == contract.PROFILE_KEYS
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert contract.sha256_file(profile_path) == (
        "4a6438a9650378a7f55e985131a8e52c13bc4e3e1ac952060486b5dc2a503fd7"
    )
