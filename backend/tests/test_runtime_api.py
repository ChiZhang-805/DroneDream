from __future__ import annotations


def test_runtime_defaults_to_dry_run(client, monkeypatch):
    monkeypatch.delenv("SIMULATOR_BACKEND", raising=False)
    monkeypatch.delenv("PX4_GAZEBO_DRY_RUN", raising=False)
    monkeypatch.delenv("PX4_GAZEBO_LAUNCH_COMMAND", raising=False)
    monkeypatch.delenv("PX4_AUTOPILOT_DIR", raising=False)
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python scripts/simulators/px4_gazebo_runner.py")
    resp = client.get("/api/v1/runtime")
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["simulator_backend_env_override"] is None
    assert payload["px4_gazebo_dry_run"] is True
    assert payload["mode_label"] == "real_cli dry-run"
    assert payload["mode_warning"] == "No external PX4/Gazebo process is launched."


def test_runtime_real_mode_flags_incomplete(client, monkeypatch):
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_cli")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "false")
    monkeypatch.setenv("PX4_GAZEBO_HEADLESS", "true")
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "python scripts/simulators/px4_gazebo_runner.py")
    monkeypatch.delenv("PX4_GAZEBO_LAUNCH_COMMAND", raising=False)
    monkeypatch.delenv("PX4_AUTOPILOT_DIR", raising=False)
    resp = client.get("/api/v1/runtime")
    payload = resp.json()["data"]
    assert payload["mode_label"] == "real_cli PX4/Gazebo real mode"
    assert payload["mode_warning"] == "PX4/Gazebo real mode is incomplete."
    assert payload["px4_gazebo_launch_command_configured"] is False
    assert payload["px4_autopilot_dir_configured"] is False

