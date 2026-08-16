from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.simulator.advanced_physics_closure_evidence import (
    EVIDENCE_SOURCES,
    MANIFEST_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    export_advanced_physics_closure,
    verify_advanced_physics_closure,
)
from app.simulator.scenario_effects import bundled_launcher_capabilities

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SUBJECT_COMMIT = "a" * 40
GENERATED_AT = "2026-07-28T23:30:00Z"
PHYSICS_EVIDENCE_AVAILABLE = all(
    (REPOSITORY_ROOT / relative).is_file()
    for source in EVIDENCE_SOURCES
    for relative in (
        [source.receipt_path]
        if source.manifest_path is None
        else [source.receipt_path, source.manifest_path]
    )
)

pytestmark = pytest.mark.skipif(
    not PHYSICS_EVIDENCE_AVAILABLE,
    reason="requires frozen technical-report physics evidence assets",
)


def _copy_evidence_sources(destination: Path) -> None:
    for source in EVIDENCE_SOURCES:
        paths = [source.receipt_path]
        if source.manifest_path is not None:
            paths.append(source.manifest_path)
        for relative in paths:
            source_path = REPOSITORY_ROOT / relative
            destination_path = destination / relative
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)


def test_export_and_verify_complete_physics_closure(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    manifest, receipt = export_advanced_physics_closure(
        repository_root=REPOSITORY_ROOT,
        output_root=output,
        subject_commit=SUBJECT_COMMIT,
        generated_at=GENERATED_AT,
    )

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert manifest["remaining_runtime_extensions"] == []
    assert manifest["summary"] == {
        "capability_category_count": 9,
        "verified_category_count": 9,
        "source_receipt_count": 4,
        "source_manifest_count": 2,
        "categories_with_all_retained_performance_success": 5,
        "all_runtime_effect_categories_verified": True,
        "all_effects_performance_successful": False,
        "real_aircraft_claim_permitted": False,
    }
    assert receipt["result"] == {
        "status": "complete_for_bundled_runtime_effect_contract",
        "verified_categories": 9,
        "remaining_runtime_extensions": 0,
        "all_effects_performance_successful": False,
        "real_aircraft_claim_permitted": False,
    }

    verified_manifest, verified_receipt = verify_advanced_physics_closure(
        repository_root=REPOSITORY_ROOT,
        evidence_root=output,
    )
    assert verified_manifest == manifest
    assert verified_receipt == receipt


def test_export_never_replaces_an_existing_closure(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "advanced-physics-closure-v2.manifest.json"
    sentinel.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(ValueError, match="absent or empty"):
        export_advanced_physics_closure(
            repository_root=REPOSITORY_ROOT,
            output_root=output,
            subject_commit=SUBJECT_COMMIT,
            generated_at=GENERATED_AT,
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"


def test_verify_rejects_changed_manifest_bytes(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    export_advanced_physics_closure(
        repository_root=REPOSITORY_ROOT,
        output_root=output,
        subject_commit=SUBJECT_COMMIT,
        generated_at=GENERATED_AT,
    )
    manifest_path = output / "advanced-physics-closure-v2.manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["summary"]["verified_category_count"] = 8
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="internal manifest hash drifted"):
        verify_advanced_physics_closure(
            repository_root=REPOSITORY_ROOT,
            evidence_root=output,
        )


def test_export_rejects_changed_source_receipt(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_evidence_sources(repository)
    receipt_path = repository / EVIDENCE_SOURCES[-1].receipt_path
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["effect_result"]["gazebo_joint_state"]["hard_stop_verified"] = False
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hard actuator-failure evidence drifted"):
        export_advanced_physics_closure(
            repository_root=repository,
            output_root=tmp_path / "bundle",
            subject_commit=SUBJECT_COMMIT,
            generated_at=GENERATED_AT,
        )


def test_export_rejects_source_receipt_internal_hash_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_evidence_sources(repository)
    receipt_path = repository / EVIDENCE_SOURCES[0].receipt_path
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["result"]["passed"] = 5
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="internal receipt hash drifted"):
        export_advanced_physics_closure(
            repository_root=repository,
            output_root=tmp_path / "bundle",
            subject_commit=SUBJECT_COMMIT,
            generated_at=GENERATED_AT,
        )


def test_export_rejects_open_runtime_extension(tmp_path: Path) -> None:
    capabilities = bundled_launcher_capabilities()
    capabilities["requires_runtime_extension"] = ["unverified effect"]

    with pytest.raises(ValueError, match="Runtime extensions remain open"):
        export_advanced_physics_closure(
            repository_root=REPOSITORY_ROOT,
            output_root=tmp_path / "bundle",
            subject_commit=SUBJECT_COMMIT,
            generated_at=GENERATED_AT,
            capabilities=capabilities,
        )


def test_cli_exports_checks_and_verifies_from_repository_root(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    script = REPOSITORY_ROOT / "backend/scripts/export_advanced_physics_closure.py"
    common = [
        sys.executable,
        str(script),
        "export",
        "--repository-root",
        str(REPOSITORY_ROOT),
        "--output-root",
        str(output),
        "--subject-commit",
        SUBJECT_COMMIT,
        "--generated-at",
        GENERATED_AT,
    ]
    exported = subprocess.run(
        common,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["verified_categories"] == 9

    checked = subprocess.run(
        [*common, "--check"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["mode"] == "check"

    verified = subprocess.run(
        [
            sys.executable,
            str(script),
            "verify",
            "--repository-root",
            str(REPOSITORY_ROOT),
            "--evidence-root",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["mode"] == "verify"
