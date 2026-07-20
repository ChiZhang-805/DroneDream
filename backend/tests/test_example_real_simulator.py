from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "example_real_simulator.py"
)
SPEC = importlib.util.spec_from_file_location("example_real_simulator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
simulator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(simulator)


def _valid_payload() -> dict[str, object]:
    return {
        "trial_id": "trial-1",
        "parameters": {"kp_xy": 1.0, "kd_xy": 0.2, "ki_xy": 0.05},
        "job_config": {"altitude_m": 3.0, "sensor_noise_level": "medium"},
        "scenario_type": "nominal",
        "scenario_config": {},
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("parameters", [], "parameters"),
        ("job_config", [], "job_config"),
        ("scenario_config", [], "scenario_config"),
        ("scenario_type", 1, "scenario_type"),
    ],
)
def test_compute_metrics_rejects_malformed_objects(field: str, value: object, message: str) -> None:
    payload = _valid_payload()
    payload[field] = value
    with pytest.raises(simulator.ExampleSimulatorError, match=message):
        simulator._compute_metrics(payload)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "not-a-number"])
def test_compute_metrics_rejects_nonfinite_controller_values(value: object) -> None:
    payload = _valid_payload()
    payload["parameters"] = {"kp_xy": value}
    with pytest.raises(simulator.ExampleSimulatorError, match="finite number"):
        simulator._compute_metrics(payload)


def test_injected_sleep_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _valid_payload()
    payload["scenario_config"] = {
        "inject_failure": "sleep",
        "sleep_seconds": simulator._MAX_INJECTED_SLEEP_SECONDS + 1,
    }
    monkeypatch.setattr(simulator.time, "sleep", lambda _seconds: None)
    with pytest.raises(simulator.ExampleSimulatorError, match="sleep_seconds"):
        simulator._compute_metrics(payload)


def test_main_rejects_non_object_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--input", str(input_path), "--output", str(output_path)],
    )
    assert simulator.main() == 2
    assert not output_path.exists()
    assert "JSON object" in capsys.readouterr().err


def test_main_writes_complete_result_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "run" / "output.json"
    input_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--input", str(input_path), "--output", str(output_path)],
    )
    assert simulator.main() == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["metrics"]["rmse"] > 0
    assert list(output_path.parent.glob("*.partial")) == []
