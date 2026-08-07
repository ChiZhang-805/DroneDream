from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "distribution/editions/field/receipts/common-core-4933e21-ui-theme-sync-v1.json"
SUPERSESSION = ROOT / "distribution/editions/field/lifecycle/red-edc7aa1-superseded-by-ui-donor.v1.json"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_receipt_binds_exact_product_and_common_core_donor() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    product = receipt["productSource"]
    donor = receipt["commonCore"]["productDonor"]
    assert _git("rev-parse", f"{product['commit']}^{{tree}}") == product["tree"]
    assert receipt["donorPathReview"]["pathCount"] == 15
    for path in receipt["donorPathReview"]["exactSharedPaths"]:
        assert _git("rev-parse", f"{product['commit']}:{path}") == _git(
            "rev-parse", f"{donor}:{path}"
        )


def test_field_entry_reaches_shared_surface_without_palette_fork() -> None:
    main = (ROOT / "frontend/src/field/main.tsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend/src/field/FieldApp.tsx").read_text(encoding="utf-8")
    settings = (ROOT / "frontend/src/field/FieldSettingsDialog.tsx").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "frontend/src/field/field.css").read_text(encoding="utf-8").lower()
    assert "EditionThemeProvider" in main
    assert 'edition="field"' in main
    assert "FieldSettingsDialog" in app
    assert "EditionSettingsSurface" in settings
    assert 'consumerProfile="field-lightweight"' in settings
    assert 'import "../styles.css";' in main
    for duplicate in ("--field-yellow", "--field-coral", "--field-pink"):
        assert duplicate not in css
    for color in ("#ffc247", "#ff754b", "#d746a5", "#fff8ef", "#28140d"):
        assert color not in css


def test_ui_theme_remains_presentation_only_and_fail_closed() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["verification"]["edgeLayout"]["dialogAndPanelNoVerticalScroll"] is True
    assert receipt["verification"]["fieldBundle"]["threeSceneChunkAbsent"] is True
    assert receipt["authority"] == {
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
        "validatedPackCount": 0,
        "threeLayerQuorum": "missing",
        "hardwareActions": "deny",
    }
    assert receipt["buildGate"]["exeBuildStarted"] is False


def test_old_red_application_is_preserved_and_superseded() -> None:
    record = json.loads(SUPERSESSION.read_text(encoding="utf-8"))
    old = record["supersededApplication"]
    old_path = ROOT / old["path"]
    assert old_path.is_file()
    assert _sha256(old_path) == old["sha256"]
    assert old["executionStatus"] == "never-executed"
    assert record["gates"]["executeOldApplication"] is False
    assert record["gates"]["newExeBuildRequired"] is True
