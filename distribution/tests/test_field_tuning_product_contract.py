from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "distribution/editions/field/field-tuning-contract.v1.json"
LAB_MANIFEST = ROOT / "distribution/editions/lab.v1.json"
LAB_CONFIG = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
LIB_SOURCE = ROOT / "desktop/src-tauri/src/lib.rs"
DOMAIN_SOURCE = ROOT / "desktop/src-tauri/src/hardware_domain.rs"
DEVICE_SOURCE = ROOT / "desktop/src-tauri/src/field_device.rs"
TUNING_SOURCE = ROOT / "desktop/src-tauri/src/field_tuning.rs"
RECOVERY_SOURCE = ROOT / "desktop/src-tauri/src/field_recovery.rs"
PREFLIGHT_SOURCE = ROOT / "desktop/src-tauri/src/field_preflight.rs"


def test_donor_tuning_contract_is_real_device_only_and_non_authoritative() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["editionId"] == "field"
    assert contract["executionDomain"] == "real-hardware"
    assert contract["simulationAllowed"] is False
    assert contract["model"]["directHardwareAuthority"] is False
    assert contract["authority"]["frontendGrantsAuthority"] is False
    assert contract["authority"]["zeroValidatedPackDecision"] == "deny"
    assert contract["harness"]["failClosed"] is True
    assert contract["harness"]["independentHoldoutRequired"] is True
    assert contract["harness"]["preQuorumBudgets"] == {
        "hardwareTrials": 0,
        "parameterWrites": 0,
        "providerRequests": 0,
    }


def test_lab_keeps_simulation_and_embeds_the_gated_hardware_domain() -> None:
    manifest = json.loads(LAB_MANIFEST.read_text(encoding="utf-8"))
    config = json.loads(LAB_CONFIG.read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]
    assert manifest["editionId"] == "lab"
    assert "simulation.execute" in manifest["capabilities"]["enabledOrConditioned"]
    assert "hardware.parameter.write" in manifest["capabilities"]["enabledOrConditioned"]
    assert "../../distribution/editions/field/adapters/THIRD_PARTY_NOTICES.md" in resources
    assert "../../distribution/editions/field/adapters/catalog.v1.json" in resources
    assert "../../distribution/editions/field/adapters/packages" in resources
    assert "../../distribution/editions/field/field-tuning-contract.v1.json" in resources
    assert "tauri.field.conf.json" not in json.dumps(config)


def test_native_handler_registers_runtime_and_hardware_domain_commands() -> None:
    source = LIB_SOURCE.read_text(encoding="utf-8")
    handler = re.search(
        r"#\[cfg\(dronedream_lab\)\]\s+let builder = builder\.invoke_handler"
        r"\(tauri::generate_handler!\[(.*?)\]\);",
        source,
        flags=re.DOTALL,
    )
    assert handler is not None
    commands = handler.group(1)
    for required in (
        "probe_runtime_status",
        "start_runtime",
        "discover_field_devices",
        "get_field_tuning_status",
        "run_field_harness_job",
        "prepare_field_hardware_tuning",
        "create_field_parameter_snapshot",
        "prepare_field_parameter_rollback",
        "prepare_field_preflight",
        "evaluate_lab_calibration_cycle",
    ):
        assert required in commands


def test_hardware_domain_identity_is_exact_and_fail_closed() -> None:
    source = DOMAIN_SOURCE.read_text(encoding="utf-8")
    assert '("lab", "unified-sim-lab")' in source
    assert '("field", "field-lightweight")' in source
    assert "Hardware-domain commands are unavailable in this edition" in source
    assert "require_available()?" in TUNING_SOURCE.read_text(encoding="utf-8")
    assert "require_available()?" in RECOVERY_SOURCE.read_text(encoding="utf-8")


def test_device_discovery_is_registry_only_and_never_opens_transport() -> None:
    source = DEVICE_SOURCE.read_text(encoding="utf-8")
    assert "RegOpenKeyExW" in source
    assert "RegEnumValueW" in source
    assert "KEY_QUERY_VALUE" in source
    for forbidden in ("CreateFileW", "WriteFile", "ReadFile", "SetCommState", "serialport::"):
        assert forbidden not in source
    assert "port_open_attempts: 0" in source
    assert "write_attempts: 0" in source
    assert "hardware_authority: false" in source


def test_tuning_recovery_and_preflight_never_execute_hardware() -> None:
    tuning = TUNING_SOURCE.read_text(encoding="utf-8")
    recovery = RECOVERY_SOURCE.read_text(encoding="utf-8")
    preflight = PREFLIGHT_SOURCE.read_text(encoding="utf-8")
    for required in (
        'execution_mode: "fixture-only-no-device-io"',
        "can_execute: false",
        "hardware_authority: false",
        '"parameterWriteBudget": 0',
        '"providerRequests": 0',
        "native_hardware_validated_pack_count",
        "native_safety_catalog_snapshot",
    ):
        assert required in tuning
    for required in (
        'kind: "dronedream-field-parameter-snapshot"',
        'kind: "dronedream-field-rollback-plan"',
        "can_execute: false",
        "hardware_write_attempts: 0",
        "hardware_authority: false",
    ):
        assert required in recovery
    for required in (
        '("parameter-write", "deny")',
        '("arm", "deny")',
        '("flight", "deny")',
        "can_execute: false",
        "hardware_authority: false",
    ):
        assert required in preflight
    combined = tuning + recovery + preflight
    for forbidden in ("WriteFile", "SetCommState", "PARAM_SET", "COMMAND_LONG"):
        assert forbidden not in combined
