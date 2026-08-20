from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution/tools/desktop_runtime_update_families.py"
CONTRACT_PATH = ROOT / "distribution/desktop/edition-runtime-update-families.v1.json"
SCHEMA_PATH = ROOT / "distribution/schemas/desktop-edition-runtime-update-families.schema.json"

SPEC = importlib.util.spec_from_file_location("desktop_runtime_update_families", TOOL_PATH)
assert SPEC and SPEC.loader
contract_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract_tool
SPEC.loader.exec_module(contract_tool)


def _document() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_schema_and_contract_are_closed_versioned_inputs() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["editions"]["minItems"] == 5
    for name in ("sharedRuntimeBase", "updaterPolicy"):
        nested = schema["properties"][name]
        assert nested["additionalProperties"] is False
        assert set(nested["required"]) == set(nested["properties"])
        assert set(_document()[name]) == set(nested["properties"])
    assert contract_tool.load_contract(ROOT)["contractVersion"] == "1.0.0"
    edition_schema = schema["properties"]["editions"]["items"]["properties"]
    assert "Autonomy" in edition_schema["installerProductName"]["pattern"]
    assert "Autonomy" in edition_schema["publicArtifactFileName"]["pattern"]
    assert "Autonomy" in edition_schema["tauriBundleInstallerFileName"]["pattern"]


def test_shared_runtime_has_one_global_owner_and_one_global_operation_lease() -> None:
    shared = contract_tool.load_contract(ROOT)["sharedRuntimeBase"]
    assert shared["managerNamespace"] == "io.dronedream.runtime-base-manager"
    assert shared["legacyCompatibilityLeaseRequired"] is True
    assert shared["legacyCompatibilityLeaseRelativePath"] == (
        "io.dronedream.desktop/runtime-operation-v1.lock"
    )
    assert shared["editionOperationsMayUseIndependentLocks"] is False
    assert shared["editionUninstallMayRemoveRuntime"] is False


def test_diagnostics_state_metadata_and_release_families_are_unique() -> None:
    editions = contract_tool.load_contract(ROOT)["editions"]
    for field in (
        "localRuntimeStateNamespace",
        "diagnosticsRelativePath",
        "updaterMetadataFileName",
        "updaterMetadataUrl",
        "updaterReleaseTagPrefix",
        "publicArtifactFileName",
    ):
        values = [edition[field] for edition in editions]
        assert len(values) == len(set(values)), field


@pytest.mark.parametrize(
    "field",
    [
        "diagnosticsRelativePath",
        "updaterMetadataFileName",
        "updaterMetadataUrl",
        "updaterReleaseTagPrefix",
    ],
)
def test_cross_edition_collision_fails_closed(field: str) -> None:
    document = _document()
    document["editions"][1][field] = document["editions"][0][field]
    with pytest.raises(contract_tool.DesktopRuntimeUpdateFamilyError, match="collide"):
        contract_tool.validate_contract(document)


def test_runtime_profile_and_artifact_cross_binding_fails_closed() -> None:
    document = deepcopy(_document())
    document["editions"][1]["runtimeProfileId"] = "unified-sim-lab"
    with pytest.raises(contract_tool.DesktopRuntimeUpdateFamilyError, match="runtimeProfileId"):
        contract_tool.validate_contract(document)
    document = deepcopy(_document())
    document["editions"][2]["publicArtifactFileName"] = "DroneDream-Field-1.0.0.exe"
    with pytest.raises(contract_tool.DesktopRuntimeUpdateFamilyError):
        contract_tool.validate_contract(document)


def test_unknown_fields_and_independent_runtime_locks_fail_closed() -> None:
    document = _document()
    document["unexpected"] = True
    with pytest.raises(contract_tool.DesktopRuntimeUpdateFamilyError, match="fields drifted"):
        contract_tool.validate_contract(document)
    document = _document()
    document["sharedRuntimeBase"]["editionOperationsMayUseIndependentLocks"] = True
    with pytest.raises(contract_tool.DesktopRuntimeUpdateFamilyError, match="ownership drifted"):
        contract_tool.validate_contract(document)
