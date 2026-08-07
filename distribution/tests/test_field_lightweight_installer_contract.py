from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / "desktop/src-tauri/nsis/edition-identity.nsh"
RUNTIME_MODE = ROOT / "desktop/src-tauri/nsis/runtime-mode.nsh"
LANGUAGES = ROOT / "desktop/src-tauri/nsis/installer-languages.nsh"
FIELD_CONFIG = ROOT / "desktop/src-tauri/tauri.field.conf.json"
LOCALE_VERIFIER = ROOT / "desktop/scripts/verify-installer-locales.ps1"
POWERSHELL = Path(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)

ALWAYS_PRESENT_LOCALE_NAMES = ("DD_ShortcutConflict",)
RUNTIME_MODE_LOCALE_NAMES = (
    "DD_ModeHeader",
    "DD_InstallButton",
    "DD_RetryDetection",
    "DD_PlannerFailureDetails",
    "DD_SelectedDriveProbeFailed",
)


def _locale_lines(names: tuple[str, ...]) -> str:
    return "\n".join(
        f'LangString: "{name}" {language} fixture'
        for name in names
        for language in (1033, 2052)
    )


def _run_locale_verifier(
    tmp_path: Path,
    product_name: str,
    names: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    generated_nsi = tmp_path / "installer.nsi"
    generated_nsi.write_text(
        f'!define PRODUCTNAME "{product_name}"\n',
        encoding="utf-8",
    )
    fake_makensis = tmp_path / "fake-makensis.cmd"
    output = _locale_lines(names)
    fake_makensis.write_text(
        "@echo off\r\n"
        + "\r\n".join(f"echo {line}" for line in output.splitlines())
        + "\r\nexit /b 0\r\n",
        encoding="ascii",
    )
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LOCALE_VERIFIER),
            "-GeneratedNsi",
            str(generated_nsi),
            "-MakeNsis",
            str(fake_makensis),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


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


def test_field_locale_verifier_requires_runtime_strings_to_be_absent(
    tmp_path: Path,
) -> None:
    result = _run_locale_verifier(
        tmp_path,
        "DroneDream-Field",
        ALWAYS_PRESENT_LOCALE_NAMES,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtimeModePageEnabled=False" in result.stdout


def test_field_locale_verifier_rejects_runtime_strings(tmp_path: Path) -> None:
    result = _run_locale_verifier(
        tmp_path,
        "DroneDream-Field",
        ALWAYS_PRESENT_LOCALE_NAMES + RUNTIME_MODE_LOCALE_NAMES,
    )
    assert result.returncode != 0
    assert "DD_ModeHeader must compile exactly 0 time(s)" in result.stderr


@pytest.mark.parametrize(
    "product_name",
    ("DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab"),
)
def test_runtime_editions_require_bilingual_runtime_strings(
    tmp_path: Path,
    product_name: str,
) -> None:
    result = _run_locale_verifier(
        tmp_path,
        product_name,
        ALWAYS_PRESENT_LOCALE_NAMES + RUNTIME_MODE_LOCALE_NAMES,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtimeModePageEnabled=True" in result.stdout


def test_locale_verifier_rejects_unknown_product_identity(tmp_path: Path) -> None:
    result = _run_locale_verifier(
        tmp_path,
        "DroneDream-Unknown",
        ALWAYS_PRESENT_LOCALE_NAMES,
    )
    assert result.returncode != 0
    assert "Unknown DroneDream installer PRODUCTNAME" in result.stderr
