from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "receipts"
    / "common-core-6f25-engine-pack-sync-v1.json"
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _load_module(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_synced_paths_and_dependencies_are_exact_to_current_common_core() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    source = receipt["productSource"]
    common = receipt["commonCore"]
    assert _git("rev-parse", f'{source["commit"]}^{{tree}}') == source["tree"]
    assert _git("rev-parse", f'{common["commit"]}^{{tree}}') == common["tree"]
    assert _git("merge-base", "--is-ancestor", source["commit"], "HEAD") == ""
    for record in [*receipt["paths"], *receipt["desktopContractDependencies"]]:
        path = record["path"]
        assert _git("rev-parse", f'{source["commit"]}:{path}') == record["gitBlob"]
        assert _git("rev-parse", f'{common["commit"]}:{path}') == record["gitBlob"]
        assert _sha256(path) == record["sha256"]


def test_all_historical_backflow_groups_now_match_universal() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    acceptance = _load_module(
        "distribution/tools/field_common_core_sync_acceptance.py",
        "field_engine_pack_sync_acceptance",
    )
    source = receipt["productSource"]["commit"]
    common = receipt["commonCore"]["commit"]
    assert len(acceptance.BACKFLOW_GROUPS) == receipt["acceptance"]["backflowGroupCount"]
    for paths in acceptance.BACKFLOW_GROUPS.values():
        for path in paths:
            assert _git("rev-parse", f"{source}:{path}") == _git(
                "rev-parse", f"{common}:{path}"
            )
    assert receipt["acceptance"]["backflowPathDriftCount"] == 0
    assert receipt["acceptance"]["commonCoreBackflowPending"] is False


def test_field_lightweight_payload_excludes_unified_contracts_and_simulator() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    engine_pack = _load_module(
        "engine-pack/tools/engine_pack.py",
        "field_engine_pack_sync_tool",
    )
    files = engine_pack.production_files(
        ROOT,
        edition_profile=engine_pack.FIELD_EDITION_PROFILE,
    )
    paths = {path for path, _source in files}
    assert len(paths) == receipt["fieldPayload"]["observedPathCount"]
    assert not paths.intersection(engine_pack.UNIFIED_DESKTOP_CONTRACT_PATHS)
    assert not any(
        path.startswith(("scripts/simulators/", "backend/app/simulator/"))
        for path in paths
    )
    assert receipt["fieldPayload"]["runtimeProfileId"] == "field-lightweight"
    assert receipt["fieldPayload"]["includesLargeSimulator"] is False


def test_zero_pack_and_execution_gates_remain_fail_closed() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    registry = json.loads(
        (ROOT / "distribution/vehicle-packs/registry.v1.json").read_text(encoding="utf-8")
    )
    validated = [
        pack
        for pack in registry["packs"]
        if pack["currentValidationTier"] == "validated"
    ]
    assert validated == []
    assert receipt["safety"]["validatedHardwarePackCount"] == 0
    assert receipt["safety"]["threeLayerQuorum"] == "missing"
    for key in (
        "buildPerformed",
        "installPerformed",
        "runtimeMigrationPerformed",
        "providerUsed",
        "deviceTouched",
        "hardwareActionsAllowed",
        "simulationAllowed",
        "releaseBranchCreated",
        "deploymentPerformed",
    ):
        assert receipt["safety"][key] is False
    assert receipt["releaseState"]["releaseReady"] is False
    assert receipt["releaseState"]["websiteReady"] is False
    assert receipt["releaseState"]["supersededPreviewMayBePromoted"] is False
