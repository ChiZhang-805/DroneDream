"""Capability discovery API tests."""

from __future__ import annotations


def test_capabilities_reports_safe_defaults(client, monkeypatch) -> None:
    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    monkeypatch.delenv("REAL_SIMULATOR_COMMAND", raising=False)
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["simulators"]["authoritative"] is False
    assert data["optimizers"]["authoritative"] is False
    assert data["optimizers"]["configuration_scope"] == "api_process"
    assert data["simulators"]["items"]["mock"] == {
        "selectable": True,
        "configured": True,
        "ready": True,
        "status": "available",
        "reason": None,
        "physical_fidelity": False,
        "purpose": "deterministic_synthetic_workflow_validation",
        "catalog_parameter_effects": "synthetic_normalized_landscape_v1",
        "supported_scenarios": [
            "nominal",
            "noise_perturbed",
            "wind_perturbed",
            "combined_perturbed",
            "turbulence",
            "gps_dropout",
            "payload_changed",
            "battery_degraded",
            "actuator_delay",
            "custom",
        ],
    }
    real_cli = data["simulators"]["items"]["real_cli"]
    assert real_cli["selectable"] is True
    assert real_cli["configured"] is False
    assert real_cli["ready"] is False
    assert real_cli["status"] == "not_configured"
    assert real_cli["max_concurrency_per_host_without_instance_allocator"] == 1
    assert real_cli["instance_allocation"] == "operator_managed"
    assert real_cli["bundled_runner_advanced_effects"] == []
    assert real_cli["unverified_effect_passthrough_opt_in"] is True
    assert data["optimizers"]["items"]["gpt"]["ready"] is False
    serialized = response.text
    assert "REAL_SIMULATOR_COMMAND is not configured" in serialized
    assert "APP_SECRET_KEY" not in serialized


def test_capabilities_treats_blank_secret_key_as_unconfigured(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "   ")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    data = client.get("/api/v1/capabilities").json()["data"]

    assert data["optimizers"]["items"]["gpt"]["ready"] is False
    assert (
        data["optimizers"]["items"]["gpt"]["status"]
        == "server_secret_not_configured"
    )


def test_capabilities_honors_global_override_and_configuration(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_cli")
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python runner.py")
    monkeypatch.setenv("REAL_SIMULATOR_WORKDIR", str(tmp_path))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-material")

    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["simulators"]["worker_override"] == "real_cli"
    assert data["simulators"]["items"]["mock"]["ready"] is False
    assert data["simulators"]["items"]["mock"]["status"] == "overridden"
    assert data["simulators"]["items"]["real_cli"]["ready"] is True
    assert data["optimizers"]["items"]["gpt"]["ready"] is True
    assert "python runner.py" not in response.text
    assert "test-secret-material" not in response.text


def test_capabilities_rejects_invalid_real_cli_workdir_without_running_it(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python runner.py")
    monkeypatch.setenv("REAL_SIMULATOR_WORKDIR", str(tmp_path / "missing"))

    data = client.get("/api/v1/capabilities").json()["data"]

    real_cli = data["simulators"]["items"]["real_cli"]
    assert real_cli["configured"] is False
    assert real_cli["ready"] is False
    assert real_cli["status"] == "invalid_workdir"


def test_capabilities_surfaces_invalid_worker_override(client, monkeypatch) -> None:
    monkeypatch.setenv("SIMULATOR_BACKEND", "typo_backend")
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python runner.py")

    data = client.get("/api/v1/capabilities").json()["data"]

    simulators = data["simulators"]
    assert simulators["worker_override_supported"] is False
    assert simulators["items"]["mock"]["status"] == "invalid_override"
    assert simulators["items"]["real_cli"]["status"] == "invalid_override"
    assert simulators["items"]["mock"]["ready"] is False
    assert simulators["items"]["real_cli"]["ready"] is False
