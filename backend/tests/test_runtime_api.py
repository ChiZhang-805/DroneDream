from __future__ import annotations


def test_runtime_defaults_to_strict_real_mode(client, monkeypatch):
    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    monkeypatch.setenv("HOSTED_REAL_CLI_REQUIRES_PX4", "true")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "false")
    monkeypatch.setenv("PX4_GAZEBO_HEADLESS", "false")
    monkeypatch.setenv("PX4_GAZEBO_LAUNCH_COMMAND", "launch")
    monkeypatch.setenv("PX4_AUTOPILOT_DIR", "/opt/PX4-Autopilot")
    monkeypatch.setenv("PX4_AUTOPILOT_HOST_DIR", "/tmp")
    monkeypatch.setenv("VNC_PASSWORD", "secret")
    monkeypatch.setenv("VITE_GAZEBO_VIEWER_URL", "http://localhost:8080/gazebo/")
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python scripts/simulators/px4_gazebo_runner.py")
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["mode_label"] == "real_cli PX4/Gazebo real mode"
    assert payload["hosted_real_cli_requires_px4"] is True
    assert payload["real_mode_config_complete"] is True


def test_runtime_incomplete_in_strict_mode(client, monkeypatch):
    monkeypatch.setenv("HOSTED_REAL_CLI_REQUIRES_PX4", "true")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "true")
    monkeypatch.delenv("PX4_GAZEBO_LAUNCH_COMMAND", raising=False)
    monkeypatch.delenv("PX4_AUTOPILOT_DIR", raising=False)
    monkeypatch.delenv("VNC_PASSWORD", raising=False)
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["mode_label"] == "real_cli configuration incomplete"
    assert "PX4_GAZEBO_DRY_RUN must be false" in payload["mode_warning"]


def test_runtime_mock_dev_label_when_not_strict(client, monkeypatch):
    monkeypatch.setenv("HOSTED_REAL_CLI_REQUIRES_PX4", "false")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "true")
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["mode_label"] == "mock/dev"


def test_runtime_strict_mode_requires_vnc_password(client, monkeypatch):
    monkeypatch.setenv("HOSTED_REAL_CLI_REQUIRES_PX4", "true")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "false")
    monkeypatch.setenv("PX4_GAZEBO_HEADLESS", "false")
    monkeypatch.setenv("PX4_GAZEBO_LAUNCH_COMMAND", "launch")
    monkeypatch.setenv("PX4_AUTOPILOT_DIR", "/opt/PX4-Autopilot")
    monkeypatch.delenv("VNC_PASSWORD", raising=False)
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["real_mode_config_complete"] is False
    assert "VNC_PASSWORD is required" in payload["mode_warning"]


def test_runtime_strict_mode_missing_viewer_is_advisory(client, monkeypatch):
    monkeypatch.setenv("HOSTED_REAL_CLI_REQUIRES_PX4", "true")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "false")
    monkeypatch.setenv("PX4_GAZEBO_HEADLESS", "false")
    monkeypatch.setenv("PX4_GAZEBO_LAUNCH_COMMAND", "launch")
    monkeypatch.setenv("PX4_AUTOPILOT_DIR", "/opt/PX4-Autopilot")
    monkeypatch.setenv("VNC_PASSWORD", "secret")
    monkeypatch.delenv("VITE_GAZEBO_VIEWER_URL", raising=False)
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["real_mode_config_complete"] is True
    assert payload["gazebo_viewer_url_configured"] is False
    assert payload["mode_warning"] is None
    assert payload["mode_advisory"] is not None
