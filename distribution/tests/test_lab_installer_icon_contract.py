from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
CANONICAL_ICON = ROOT / "brand/generated/lab/windows/icon.ico"
EXPECTED_ICON_SHA256 = (
    "67b5747de298ffcf64d062294829306bd9b66df4ee52cfa8a8e3498cb94d5fa1"
)


def _validate_icon_contract(config: dict) -> tuple[Path, Path]:
    nsis = config.get("bundle", {}).get("windows", {}).get("nsis", {})
    expected = "../../brand/generated/lab/windows/icon.ico"
    if nsis.get("installerIcon") != expected:
        raise ValueError("LAB NSIS installerIcon must use the canonical LAB ICO")
    if nsis.get("uninstallerIcon") != expected:
        raise ValueError("LAB NSIS uninstallerIcon must use the canonical LAB ICO")
    return tuple((CONFIG.parent / nsis[key]).resolve() for key in (
        "installerIcon",
        "uninstallerIcon",
    ))


def test_lab_nsis_icons_bind_canonical_green_asset() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    installer_icon, uninstaller_icon = _validate_icon_contract(config)

    assert installer_icon == CANONICAL_ICON
    assert uninstaller_icon == CANONICAL_ICON
    assert CANONICAL_ICON.stat().st_size == 55959
    assert hashlib.sha256(CANONICAL_ICON.read_bytes()).hexdigest() == (
        EXPECTED_ICON_SHA256
    )


@pytest.mark.parametrize("missing_key", ["installerIcon", "uninstallerIcon"])
def test_lab_nsis_icon_contract_rejects_missing_surface(missing_key: str) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    del config["bundle"]["windows"]["nsis"][missing_key]

    with pytest.raises(ValueError, match=missing_key):
        _validate_icon_contract(config)
