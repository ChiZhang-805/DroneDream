from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from dronedream_agent_core.asset_qualification import qualify_staged_asset

ASSET_ROOT = Path(__file__).parents[1] / "assets" / "default"


def _stage(tmp_path: Path, archive_name: str) -> tuple[dict[str, object], dict[str, Path]]:
    with zipfile.ZipFile(ASSET_ROOT / archive_name) as archive:
        archive.extractall(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    resolved = {key: tmp_path / value for key, value in manifest["files"].items()}
    return manifest, resolved


@pytest.mark.parametrize(
    ("archive_name", "kind", "expected_checks"),
    [
        (
            "school-map.zip",
            "map",
            {
                "source-receipt",
                "runtime-evidence",
                "package-export-integrity",
                "map-format-frame-semantic",
                "map-seam-intersection",
                "map-material-physics",
                "map-navigability-clearance",
                "map-export",
            },
        ),
        (
            "my-drone.zip",
            "vehicle",
            {
                "source-receipt",
                "runtime-evidence",
                "package-export-integrity",
                "vehicle-cad-urdf-sdf-format",
                "vehicle-mass-inertia",
                "vehicle-motor-propeller",
                "vehicle-battery-sensors",
                "vehicle-controller",
                "vehicle-payload",
                "vehicle-flight-envelope",
            },
        ),
    ],
)
def test_default_assets_pass_every_independent_check(
    tmp_path: Path,
    archive_name: str,
    kind: str,
    expected_checks: set[str],
) -> None:
    manifest, resolved = _stage(tmp_path, archive_name)

    receipts = qualify_staged_asset(
        staging=tmp_path,
        kind=kind,  # type: ignore[arg-type]
        manifest=manifest,
        resolved=resolved,
    )

    assert {receipt.check_type for receipt in receipts} == expected_checks
    assert all(receipt.accepted for receipt in receipts)
    assert all(receipt.input_sha256 != receipt.output_sha256 for receipt in receipts)


def test_map_numeric_gap_and_material_loss_are_rejected(tmp_path: Path) -> None:
    manifest, resolved = _stage(tmp_path, "school-map.zip")
    graph = json.loads(resolved["graph"].read_text(encoding="utf-8"))
    graph["edges"][0]["distance_m"] += 0.5
    resolved["graph"].write_text(json.dumps(graph), encoding="utf-8")
    semantic = json.loads(resolved["semantic"].read_text(encoding="utf-8"))
    semantic["physical_material_contract"]["semantic_material_ids"].pop("terrain")
    resolved["semantic"].write_text(json.dumps(semantic), encoding="utf-8")

    receipts = qualify_staged_asset(
        staging=tmp_path,
        kind="map",
        manifest=manifest,
        resolved=resolved,
    )
    failures = {
        receipt.check_type: receipt.issue_codes for receipt in receipts if not receipt.accepted
    }

    assert "MAP_ROUTE_NUMERIC_GAP" in failures["map-seam-intersection"]
    assert "MAP_PRIMITIVE_MATERIAL_UNRESOLVED" in failures["map-material-physics"]
    assert "ASSET_DECLARED_EXPORT_HASH_MISMATCH" in failures["package-export-integrity"]
    assert "MAP_EXPORT_HASH_MISMATCH" in failures["map-export"]


def test_vehicle_control_sensor_payload_and_physics_tampering_are_rejected(
    tmp_path: Path,
) -> None:
    manifest, resolved = _stage(tmp_path, "my-drone.zip")
    manifest["physical_material_contract"]["mass_and_inertia_from_source_model"] = False
    manifest["physical_material_contract"]["rotor_dynamics_from_source_model"] = False
    vehicle = json.loads(resolved["vehicle_metadata"].read_text(encoding="utf-8"))
    vehicle["sensors"] = ["camera"]
    resolved["vehicle_metadata"].write_text(json.dumps(vehicle), encoding="utf-8")
    controller = json.loads(resolved["controller_params"].read_text(encoding="utf-8"))
    controller["vel_limit"] = 10.0
    resolved["controller_params"].write_text(json.dumps(controller), encoding="utf-8")
    payload = resolved["payload_sdf"].read_text(encoding="utf-8")
    resolved["payload_sdf"].write_text(
        payload.replace("<mass>0.1</mass>", "<mass>0.2</mass>"), encoding="utf-8"
    )

    receipts = qualify_staged_asset(
        staging=tmp_path,
        kind="vehicle",
        manifest=manifest,
        resolved=resolved,
    )
    failures = {
        receipt.check_type: receipt.issue_codes for receipt in receipts if not receipt.accepted
    }

    assert "VEHICLE_INERTIA_UNVERIFIED" in failures["vehicle-mass-inertia"]
    assert "VEHICLE_ROTOR_DYNAMICS_UNVERIFIED" in failures["vehicle-motor-propeller"]
    assert "VEHICLE_SENSOR_SUITE_INCOMPLETE" in failures["vehicle-battery-sensors"]
    assert "VEHICLE_CONTROLLER_SPEED_EXCEEDS_ENVELOPE" in failures["vehicle-controller"]
    assert "VEHICLE_PAYLOAD_MASS_MISMATCH" in failures["vehicle-payload"]
    assert "ASSET_DECLARED_EXPORT_HASH_MISMATCH" in failures["package-export-integrity"]
