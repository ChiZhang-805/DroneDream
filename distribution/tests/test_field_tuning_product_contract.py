from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "distribution/editions/field/field-tuning-contract.v1.json"
MANIFEST = ROOT / "distribution/editions/field.v1.json"
TAURI_CONFIG = ROOT / "desktop/src-tauri/tauri.field.conf.json"
LIB_SOURCE = ROOT / "desktop/src-tauri/src/lib.rs"
DEVICE_SOURCE = ROOT / "desktop/src-tauri/src/field_device.rs"
TUNING_SOURCE = ROOT / "desktop/src-tauri/src/field_tuning.rs"


def test_field_tuning_contract_is_real_device_only_and_authority_is_native() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["editionId"] == "field"
    assert contract["executionDomain"] == "real-hardware"
    assert contract["simulationAllowed"] is False
    assert contract["model"]["directHardwareAuthority"] is False
    assert contract["authority"]["frontendGrantsAuthority"] is False
    assert contract["authority"]["modelGrantsAuthority"] is False
    assert contract["authority"]["zeroValidatedPackDecision"] == "deny"
    assert contract["harness"]["failClosed"] is True
    assert contract["harness"]["candidateWritesAreTransactional"] is True
    assert contract["harness"]["independentHoldoutRequired"] is True
    assert contract["harness"]["phases"] == [
        "snapshot",
        "candidate-validation",
        "operator-confirmation",
        "controlled-trial",
        "telemetry-capture",
        "scoring",
        "failure-classification",
        "reflection",
        "qualification",
        "independent-holdout",
        "publish-or-rollback",
    ]


def test_field_manifest_exposes_independent_tuning_without_simulation() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert "tuning" not in manifest
    assert CONTRACT.is_file()
    assert "simulation.execute" in manifest["capabilities"]["forbidden"]
    assert "hardware.parameter.write" in manifest["capabilities"]["enabledOrConditioned"]


def test_field_native_handler_contains_no_runtime_or_simulator_commands() -> None:
    source = LIB_SOURCE.read_text(encoding="utf-8")
    field_handler_match = re.search(
        r"#\[cfg\(dronedream_field\)\]\s+let builder = builder\.invoke_handler"
        r"\(tauri::generate_handler!\[(.*?)\]\);",
        source,
        flags=re.DOTALL,
    )
    assert field_handler_match is not None
    field_handler = field_handler_match.group(1)

    for required in (
        "discover_field_devices",
        "get_field_tuning_status",
        "run_field_tuning_demo",
        "prepare_field_hardware_tuning",
    ):
        assert required in source

    for forbidden in (
        "probe_runtime_status",
        "start_runtime",
        "start_runtime_install",
        "install_embedded_engine_pack",
        "desktop_api_request",
    ):
        assert forbidden not in field_handler


def test_device_observation_never_opens_or_writes_serial_ports() -> None:
    source = DEVICE_SOURCE.read_text(encoding="utf-8")

    assert "RegOpenKeyExW" in source
    assert "RegEnumValueW" in source
    assert "KEY_QUERY_VALUE" in source
    assert "KEY_READ" not in source
    assert "registry_value_name_sha256" in source
    for forbidden in (
        "CreateFileW",
        "WriteFile",
        "ReadFile",
        "SetCommState",
        "EscapeCommFunction",
        "serialport::",
    ):
        assert forbidden not in source
    assert "port_open_attempts: 0" in source
    assert "write_attempts: 0" in source
    assert "hardware_authority: false" in source


def test_tuning_commands_are_fixture_or_plan_only_and_config_has_no_sim_payload() -> None:
    tuning = TUNING_SOURCE.read_text(encoding="utf-8")
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))

    assert 'execution_mode: "fixture-only-no-device-io"' in tuning
    assert "hardware_actions_performed: Vec::new()" in tuning
    assert "can_execute: false" in tuning
    assert "hardware_authority: false" in tuning
    resources = "\n".join(config["bundle"]["resources"]).lower()
    for forbidden in ("px4", "gazebo", "sitl", "hitl", "simulator", "runtime/"):
        assert forbidden not in resources
