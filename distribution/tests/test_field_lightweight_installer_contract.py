from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / "desktop/src-tauri/nsis/edition-identity.nsh"
RUNTIME_MODE = ROOT / "desktop/src-tauri/nsis/runtime-mode.nsh"
LANGUAGES = ROOT / "desktop/src-tauri/nsis/installer-languages.nsh"
FIELD_CONFIG = ROOT / "desktop/src-tauri/tauri.field.conf.json"


def test_only_field_disables_the_runtime_mode_installer_page() -> None:
    source = IDENTITY.read_text(encoding="utf-8")
    policies = dict(
        re.findall(
            r'!?(?:else )?if "\$\{PRODUCTNAME\}" == "(DroneDream-[^"]+)"'
            r'.*?!define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "([01])"',
            source,
            flags=re.DOTALL,
        )
    )

    assert policies == {
        "DroneDream-Universal": "1",
        "DroneDream-Sim": "1",
        "DroneDream-Lab": "1",
        "DroneDream-Field": "0",
    }


def test_runtime_page_and_ui_implementation_are_compile_time_gated() -> None:
    source = RUNTIME_MODE.read_text(encoding="utf-8")
    guard = '!if "${DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED}" == "1"'
    assert source.count(guard) == 2
    assert source.index(guard) < source.index(
        "Page custom DroneDreamRuntimeModePageCreate DroneDreamRuntimeModePageLeave"
    )
    implementation_guard = source.index(guard, source.index(guard) + 1)
    assert implementation_guard < source.index("Function DroneDreamRunPlanner")
    assert source.index("Function DroneDreamRuntimeModePageLeave") < source.index(
        "!endif", implementation_guard
    )


def test_field_compile_branch_excludes_simulator_and_runtime_choice_copy() -> None:
    source = LANGUAGES.read_text(encoding="utf-8")
    guard = '!if "${DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED}" == "1"'
    start = source.index(guard)
    end = source.index("!endif", start)
    guarded = source[start:end]
    for forbidden in (
        "PX4/Gazebo",
        "Install everything (recommended)",
        "Choose a Runtime drive",
        "Runtime setup starts in DroneDream",
        "Retry detection",
    ):
        assert forbidden in guarded
        assert forbidden not in source[:start] + source[end:]


def test_field_bundle_resources_contain_no_runtime_or_simulator_payload() -> None:
    config = json.loads(FIELD_CONFIG.read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]
    normalized = "\n".join(resources).lower()
    for forbidden in ("px4", "gazebo", "sitl", "hitl", "simulator", "runtime/"):
        assert forbidden not in normalized
    assert config["productName"] == "DroneDream-Field"
    assert config["identifier"] == "io.dronedream.desktop.field"
