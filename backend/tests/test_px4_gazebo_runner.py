from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.simulator.base import FAILURE_ADAPTER_UNAVAILABLE, FAILURE_TIMEOUT, JobConfig, TrialContext
from app.simulator.real_cli import RealCliSimulatorAdapter

RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "px4_gazebo_runner.py"


def _trial_input(
    tmp_path: Path,
    *,
    vehicle_profile: dict[str, object] | None = None,
    seed: int = 42,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "trial_id": "trial-1",
        "job_id": "job-1",
        "candidate_id": "cand-1",
        "seed": seed,
        "attempt_count": 1,
        "execution_identity": {
            "trial_id": "trial-1",
            "job_id": "job-1",
            "candidate_id": "cand-1",
            "seed": seed,
            "attempt_count": 1,
        },
        "scenario_type": "nominal",
        "scenario_config": {},
        "job_config": {
            "track_type": "circle",
            "start_point": {"x": 0.0, "y": 0.0},
            "altitude_m": 3.0,
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
            "objective_profile": "robust",
        },
        "parameters": {
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": 5.0,
            "accel_limit": 4.0,
            "disturbance_rejection": 0.5,
        },
        "output_path": str(tmp_path / "trial_result.json"),
    }
    if vehicle_profile is not None:
        payload["vehicle_profile"] = vehicle_profile
        payload["job_config"]["vehicle_profile"] = vehicle_profile
    p = tmp_path / "trial_input.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _run_runner(
    tmp_path: Path,
    *,
    env_overrides: dict[str, str],
    vehicle_profile: dict[str, object] | None = None,
    seed: int = 42,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    input_path = _trial_input(tmp_path, vehicle_profile=vehicle_profile, seed=seed)
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert output_path.exists(), proc.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    return proc, payload


def _write_launcher_with_payloads(
    path: Path,
    telemetry_payload: dict[str, object],
    *,
    offboard_timing_payload: dict[str, object] | None = None,
) -> Path:
    script = [
        "import json, pathlib, sys",
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])",
        f"telemetry.write_text({json.dumps(json.dumps(telemetry_payload))}, encoding='utf-8')",
    ]
    if offboard_timing_payload is not None:
        script.extend(
            [
                "run_dir = telemetry.parent",
                (
                    "(run_dir / 'offboard_timing.json').write_text("
                    f"{json.dumps(json.dumps(offboard_timing_payload))}, encoding='utf-8')"
                ),
            ]
        )
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path


def _track_following_telemetry() -> dict[str, object]:
    samples: list[dict[str, object]] = []
    t = 0.0
    for _ in range(20):
        samples.append(
            {
                "t": round(t, 2),
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "mode": "takeoff",
                "crashed": False,
            }
        )
        t += 0.1
    for i in range(10):
        samples.append(
            {
                "t": round(t, 2),
                "x": 0.5 * i,
                "y": 0.0,
                "z": 3.0,
                "mode": "transition",
                "crashed": False,
            }
        )
        t += 0.1
    for i in range(180):
        theta = 2.0 * 3.141592653589793 * (i / 179)
        samples.append(
            {
                "t": round(t, 2),
                "x": 5.0 * math.cos(theta),
                "y": 5.0 * math.sin(theta),
                "z": 3.0,
                "mode": "offboard",
                "crashed": False,
            }
        )
        t += 0.1
    for _ in range(10):
        samples.append(
            {
                "t": round(t, 2),
                "x": 5.0,
                "y": 0.0,
                "z": 0.0,
                "mode": "land",
                "crashed": False,
            }
        )
        t += 0.1
    return {"samples": samples, "meta": {"source": "test_fixture"}}


def _find_sample_time(samples: list[dict[str, object]], idx: int) -> float:
    value = samples[idx]["t"]
    assert isinstance(value, (int, float))
    return float(value)


def _run_custom_track_case(
    tmp_path: Path,
    *,
    reference_track: list[dict[str, float]],
    telemetry_samples: list[dict[str, object]],
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    input_path = _trial_input(tmp_path)
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    input_payload["job_config"]["track_type"] = "custom"
    input_payload["job_config"]["reference_track"] = reference_track
    input_path.write_text(json.dumps(input_payload), encoding="utf-8")
    launcher = _write_launcher_with_payloads(
        tmp_path / "custom_track_launcher.py",
        {"samples": telemetry_samples},
    )
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(
        {
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f'"{sys.executable}" "{launcher}" --telemetry {{telemetry_json}}'
            ),
            **(env_overrides or {}),
        }
    )
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert output_path.is_file(), proc.stderr
    return proc, json.loads(output_path.read_text(encoding="utf-8"))


def test_px4_runner_requires_cli_args():
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--input" in proc.stderr


def test_px4_runner_returns_adapter_unavailable_when_command_missing(tmp_path: Path):
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": "",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == FAILURE_ADAPTER_UNAVAILABLE


def test_px4_runner_dry_run_is_deterministic(tmp_path: Path):
    proc1, result1 = _run_runner(tmp_path / "r1", env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    proc2, result2 = _run_runner(tmp_path / "r2", env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    proc3, result3 = _run_runner(
        tmp_path / "r3",
        env_overrides={"PX4_GAZEBO_DRY_RUN": "true"},
        seed=43,
    )
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    assert proc3.returncode == 0
    assert result1["success"] is True
    assert result2["success"] is True
    assert result1["metrics"] == result2["metrics"]
    assert result1["metrics"] != result3["metrics"]
    assert result1["schema_version"] == "dronedream.trial_result.v2"
    assert result1["execution_identity"]["trial_id"] == "trial-1"


def test_px4_runner_timeout_maps_to_timeout(tmp_path: Path):
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(
        "import time\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {sleeper} --input {{trial_input}} --telemetry {{telemetry_json}}"
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_TIMEOUT_SECONDS": "1",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == FAILURE_TIMEOUT


def test_px4_runner_scales_one_x_timeout_for_slow_simulation(tmp_path: Path) -> None:
    launcher = _write_launcher_with_payloads(
        tmp_path / "slow_launcher.py",
        _track_following_telemetry(),
    )
    launcher.write_text(
        "import time\ntime.sleep(1.2)\n" + launcher.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_TIMEOUT_SECONDS": "1",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f'"{sys.executable}" "{launcher}" --telemetry {{telemetry_json}}'
            ),
        },
        vehicle_profile={"simulation_speed_factor": 0.5},
    )

    assert proc.returncode == 0
    assert result["success"] is True, result
    launch_config = json.loads((tmp_path / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["timeout_base_1x_seconds"] == 1
    assert launch_config["timeout_effective_seconds"] == 2.0


def test_px4_runner_verifies_requested_firmware_against_git_head(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required for firmware identity test")
    checkout = tmp_path / "PX4-Autopilot"
    checkout.mkdir()
    subprocess.run([git, "init", "-q", str(checkout)], check=True, capture_output=True)
    subprocess.run(
        [git, "-C", str(checkout), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git, "-C", str(checkout), "config", "user.name", "DroneDream Test"],
        check=True,
        capture_output=True,
    )
    (checkout / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run([git, "-C", str(checkout), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        [git, "-C", str(checkout), "commit", "-q", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        [git, "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    verified_dir = tmp_path / "verified"
    proc, result = _run_runner(
        verified_dir,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "true",
            "PX4_AUTOPILOT_DIR": str(checkout),
            "PX4_FIRMWARE_COMMIT_OBSERVED": "",
        },
        vehicle_profile={"firmware_commit": head[:8]},
    )

    assert proc.returncode == 0
    assert result["success"] is True, result
    launch_config = json.loads((verified_dir / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["firmware_identity"] == {
        "requested_commit": head[:8],
        "observed_commit": head,
        "observed_source": "git_head",
        "px4_autopilot_dir": str(checkout.resolve()),
        "status": "verified",
        "error": None,
    }
    runtime_manifest = json.loads(
        (verified_dir / "simulator_runtime_manifest.json").read_text(encoding="utf-8")
    )
    assert runtime_manifest["firmware_identity"]["observed_commit"] == head

    mismatch_dir = tmp_path / "mismatch"
    proc, result = _run_runner(
        mismatch_dir,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "true",
            "PX4_AUTOPILOT_DIR": str(checkout),
            "PX4_FIRMWARE_COMMIT_OBSERVED": "",
        },
        vehicle_profile={"firmware_commit": "0" * 7},
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "does not match observed HEAD" in result["failure"]["reason"]
    mismatch_config = json.loads((mismatch_dir / "launch_config.json").read_text(encoding="utf-8"))
    assert mismatch_config["firmware_identity"]["status"] == "mismatch"


def test_px4_runner_malformed_telemetry_maps_to_simulation_failed(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "telemetry.write_text('{bad json', encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
    proc, result = _run_runner(
        tmp_path,
        env_overrides={"PX4_GAZEBO_DRY_RUN": "false", "PX4_GAZEBO_LAUNCH_COMMAND": command},
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == "SIMULATION_FAILED"


def test_px4_runner_parses_false_telemetry_strings_without_truthiness_bug(
    tmp_path: Path,
) -> None:
    launcher = _write_launcher_with_payloads(
        tmp_path / "boolean_telemetry.py",
        {
            "samples": [
                {"t": 0.0, "x": 0.0, "y": 0.0, "z": 3.0, "crashed": "false"},
                {"t": 0.1, "x": 0.1, "y": 0.0, "z": 3.0, "crashed": "0"},
            ]
        },
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f'"{sys.executable}" "{launcher}" --telemetry {{telemetry_json}}'
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True, result
    assert result["metrics"]["crash_flag"] is False


def test_px4_runner_rejects_non_monotonic_telemetry_timestamps(tmp_path: Path) -> None:
    launcher = _write_launcher_with_payloads(
        tmp_path / "non_monotonic.py",
        {
            "samples": [
                {"t": 0.1, "x": 0.0, "y": 0.0, "z": 3.0},
                {"t": 0.1, "x": 0.1, "y": 0.0, "z": 3.0},
            ]
        },
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f'"{sys.executable}" "{launcher}" --telemetry {{telemetry_json}}'
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "timestamp must be strictly increasing" in result["failure"]["reason"]


def test_px4_runner_writes_expected_artifacts_in_dry_run(tmp_path: Path):
    proc, result = _run_runner(tmp_path, env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    assert proc.returncode == 0
    assert result["success"] is True, result
    for name in (
        "controller_params.json",
        "scenario_config.json",
        "reference_track.json",
        "telemetry.json",
        "trajectory.json",
        "stdout.log",
        "stderr.log",
        "runner.log",
        "trial_result.json",
    ):
        assert (tmp_path / name).exists(), name


def test_px4_runner_extracts_real_candidate_parameters_and_writes_evidence(
    tmp_path: Path,
):
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["parameters"]["MPC_XY_P"] = 1.1
    payload["parameters"]["MC_ROLLRATE_P"] = 0.16
    payload["parameters"]["IMU_GYRO_CUTOFF"] = 40.0
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "true"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    requested = json.loads((tmp_path / "px4_parameters.requested.json").read_text(encoding="utf-8"))
    applied = json.loads((tmp_path / "px4_parameters.applied.json").read_text(encoding="utf-8"))
    assert requested["values"] == {
        "IMU_GYRO_CUTOFF": 40.0,
        "MC_ROLLRATE_P": 0.16,
        "MPC_XY_P": 1.1,
    }
    assert applied["verification"]["verified"] is True
    artifact_names = {Path(item["storage_path"]).name for item in result["artifacts"]}
    assert {
        "px4_parameters.requested.json",
        "px4_parameters.before.json",
        "px4_parameters.applied.json",
    }.issubset(artifact_names)


def test_px4_runner_rejects_real_parameter_outside_safe_bounds(tmp_path: Path):
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["parameters"]["MPC_XY_VEL_I_ACC"] = 5.0
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "true"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["failure"]["code"] == "SIMULATION_FAILED"
    assert "OUTSIDE_SAFE_BOUNDS" in result["failure"]["reason"]


def test_px4_runner_prefers_trial_input_reference_track_even_when_track_type_not_custom(
    tmp_path: Path,
):
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["job_config"]["track_type"] = "circle"
    payload["job_config"]["reference_track"] = [
        {"x": 0.0, "y": 0.0, "z": 3.0},
        {"x": 2.0, "y": 1.0, "z": 3.0},
        {"x": 4.0, "y": 1.0, "z": 3.0},
    ]
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "true"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert output_path.exists(), proc.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert proc.returncode == 0
    assert result["success"] is True
    track_payload = json.loads((tmp_path / "reference_track.json").read_text(encoding="utf-8"))
    assert track_payload["reference_track"] == payload["job_config"]["reference_track"]
    assert track_payload["points"] == payload["job_config"]["reference_track"]


def test_px4_runner_template_substitutes_env_tokens(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    args_dump = tmp_path / "argv.json"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1]).write_text("
        '\'{"samples": [{"t": 0.0, "x": 0.0, "y": 0.0, "z": 3.0}]}\''
        ", encoding='utf-8')\n"
        f"pathlib.Path({str(args_dump)!r}).write_text(json.dumps(sys.argv), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        f"{sys.executable} {launcher} "
        "--vehicle {vehicle} --world {world} --headless {headless} --extra {extra_args} "
        "--params {params_json} --track {track_json} --telemetry {telemetry_json}"
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
            "PX4_GAZEBO_VEHICLE": "x500_test",
            "PX4_GAZEBO_WORLD": "warehouse",
            "PX4_GAZEBO_HEADLESS": "false",
            "PX4_GAZEBO_EXTRA_ARGS": "--speed 2 --foo bar",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    argv = json.loads(args_dump.read_text(encoding="utf-8"))
    assert "--vehicle" in argv and "x500_test" in argv
    assert "--world" in argv and "warehouse" in argv
    assert "--headless" in argv and "false" in argv
    assert "--extra" in argv
    extra_idx = argv.index("--extra")
    assert argv[extra_idx + 1 : extra_idx + 5] == ["--speed", "2", "--foo", "bar"]


def test_px4_runner_uses_per_job_vehicle_profile_instead_of_worker_defaults(
    tmp_path: Path,
):
    launcher = tmp_path / "profile_launcher.py"
    args_dump = tmp_path / "profile_argv.json"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1]).write_text("
        '\'{"samples": [{"t": 0.0, "x": 0.0, "y": 0.0, "z": 3.0}]}\','
        " encoding='utf-8')\n"
        f"pathlib.Path({str(args_dump)!r}).write_text(json.dumps(sys.argv), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        f"{sys.executable} {launcher} --vehicle {{vehicle}} --airframe {{airframe}} "
        "--model {simulator_model} --world {world} --version {px4_version} "
        "--telemetry {telemetry_json}"
    )
    profile = {
        "px4_version": "v1.16",
        "vehicle_type": "multicopter",
        "airframe": "quad_x",
        "simulator_model": "gz_x500_depth",
        "world": "warehouse",
    }
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
            "PX4_GAZEBO_VEHICLE": "worker_default",
            "PX4_GAZEBO_WORLD": "worker_default",
        },
        vehicle_profile=profile,
    )
    assert proc.returncode == 0
    assert result["success"] is True
    argv = json.loads(args_dump.read_text(encoding="utf-8"))
    assert argv[argv.index("--vehicle") + 1] == "gz_x500_depth"
    assert argv[argv.index("--airframe") + 1] == "quad_x"
    assert argv[argv.index("--model") + 1] == "gz_x500_depth"
    assert argv[argv.index("--world") + 1] == "warehouse"
    assert argv[argv.index("--version") + 1] == "v1.16"
    launch_config = json.loads((tmp_path / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["simulator_model"] == "gz_x500_depth"
    assert launch_config["airframe"] == "quad_x"


def test_px4_runner_preserves_spaced_paths_and_exports_runtime_context(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "workspace with spaces"
    run_dir.mkdir()
    launcher = run_dir / "context launcher.py"
    context_dump = run_dir / "context.json"
    launcher.write_text(
        "import json, os, pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "telemetry.write_text(json.dumps({'samples': "
        "[{'t': 0, 'x': 0, 'y': 0, 'z': 3}]}), encoding='utf-8')\n"
        "context = {'argv': sys.argv, 'speed': os.environ.get('PX4_SIM_SPEED_FACTOR'), "
        "'seed': os.environ.get('PX4_TRIAL_SEED'), "
        "'instance': os.environ.get('PX4_INSTANCE'), "
        "'scenario': os.environ.get('PX4_TRIAL_SCENARIO_CONFIG_PATH')}\n"
        f"pathlib.Path({str(context_dump)!r}).write_text(json.dumps(context), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        f'{{px4_executable}} "{launcher}" --telemetry {{telemetry_json}} '
        "--scenario {scenario_config_json} --instance {instance_id} "
        "--speed {simulation_speed_factor}"
    )
    proc, result = _run_runner(
        run_dir,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
            "DRONEDREAM_PX4_EXECUTABLE": sys.executable,
        },
        vehicle_profile={
            "headless": False,
            "instance_id": 7,
            "simulation_speed_factor": 2.5,
        },
    )

    assert proc.returncode == 0
    assert result["success"] is True, result
    context = json.loads(context_dump.read_text(encoding="utf-8"))
    argv = context["argv"]
    telemetry_arg = Path(argv[argv.index("--telemetry") + 1])
    scenario_arg = Path(argv[argv.index("--scenario") + 1])
    assert telemetry_arg == run_dir / "telemetry.json"
    assert scenario_arg == run_dir / "scenario_config.json"
    assert context["speed"] == "2.5"
    assert context["seed"] == "42"
    assert context["instance"] == "7"
    assert Path(context["scenario"]) == scenario_arg
    launch_config = json.loads((run_dir / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["headless"] is False
    assert launch_config["simulation_speed_factor"] == 2.5
    assert launch_config["instance_id"] == 7


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_px4_runner_rejects_nonpositive_timeout(tmp_path: Path, timeout: str) -> None:
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "true",
            "PX4_GAZEBO_TIMEOUT_SECONDS": timeout,
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "must be greater than zero" in result["failure"]["reason"]


def test_px4_runner_rejects_speed_factor_below_timeout_scaling_contract(
    tmp_path: Path,
) -> None:
    proc, result = _run_runner(
        tmp_path,
        env_overrides={"PX4_GAZEBO_DRY_RUN": "true"},
        vehicle_profile={"simulation_speed_factor": 0.01},
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "must be finite and in [0.1, 100]" in result["failure"]["reason"]


def test_px4_runner_fails_fast_for_unapplied_advanced_scenario_effects(
    tmp_path: Path,
) -> None:
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["advanced_scenario_config"] = {
        "wind_gusts": {"enabled": True, "magnitude_mps": 2.0},
        "obstacles": [{"type": "cylinder", "x": 1.0, "y": 2.0, "z": 1.0}],
        "sensor_degradation": {"dropout_rate": 0.1},
        "battery": {"initial_percent": 80.0},
    }
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "true"
    env.pop("PX4_GAZEBO_ALLOW_UNVERIFIED_ADVANCED_EFFECTS", None)

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["failure"]["code"] == "UNSUPPORTED_SCENARIO_EFFECT"
    launch_config = json.loads((tmp_path / "launch_config.json").read_text(encoding="utf-8"))
    unsupported = launch_config["scenario_effect_contract"]["unsupported_effects"]
    assert unsupported == [
        "battery.initial_percent",
        "obstacles",
        "sensor_degradation.dropout_rate",
        "wind_gusts",
    ]


def test_unverified_advanced_effect_passthrough_can_run_but_never_pass(
    tmp_path: Path,
) -> None:
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["advanced_scenario_config"] = {"sensor_degradation": {"gps_noise_m": 1.0}}
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(
        {
            "PX4_GAZEBO_DRY_RUN": "true",
            "PX4_GAZEBO_ALLOW_UNVERIFIED_ADVANCED_EFFECTS": "true",
        }
    )

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["metrics"]["pass_flag"] is False
    summary = result["metrics"]["raw_metric_json"]["advanced_scenario_summary"]
    assert summary["applied_effects"] == []
    assert summary["unsupported_effects"] == ["sensor_degradation.gps_noise_m"]
    assert summary["verification_status"] == "unverified_passthrough"


def test_real_runner_fails_closed_for_unapplied_scenario_suite_effect(
    tmp_path: Path,
) -> None:
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["scenario_type"] = "wind_perturbed"
    payload["scenario_config"] = {"wind_mps": 4.0}
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    sentinel = tmp_path / "launcher-ran"
    launcher = tmp_path / "must_not_run.py"
    launcher.write_text(
        f"import pathlib\npathlib.Path({str(sentinel)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(
        {
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": f'"{sys.executable}" "{launcher}"',
        }
    )

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert proc.returncode == 0
    assert result["failure"]["code"] == "UNSUPPORTED_SCENARIO_EFFECT"
    assert not sentinel.exists()
    contract = json.loads((tmp_path / "launch_config.json").read_text(encoding="utf-8"))[
        "scenario_effect_contract"
    ]
    assert contract["unsupported_effects"] == [
        "scenario_config.wind_mps",
        "scenario_type.wind_perturbed",
    ]


def test_px4_runner_rejects_unsafe_vehicle_profile_tokens(tmp_path: Path):
    proc, result = _run_runner(
        tmp_path,
        env_overrides={"PX4_GAZEBO_DRY_RUN": "true"},
        vehicle_profile={
            "px4_version": "v1.16",
            "airframe": "x500; touch owned",
            "simulator_model": "gz_x500",
            "world": "default",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "vehicle_profile.airframe" in str(result["failure"]["reason"])


def test_px4_runner_rejects_unsupported_or_malformed_px4_version(tmp_path: Path):
    proc, result = _run_runner(
        tmp_path,
        env_overrides={"PX4_GAZEBO_DRY_RUN": "true"},
        vehicle_profile={
            "px4_version": "v1.16 --unexpected",
            "airframe": "x500",
            "simulator_model": "gz_x500",
            "world": "default",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert "vehicle_profile.px4_version" in str(result["failure"]["reason"])


def test_px4_runner_independently_rejects_false_readback_evidence(tmp_path: Path):
    input_path = _trial_input(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["parameters"]["MPC_XY_P"] = 1.1
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    launcher = tmp_path / "false_evidence_launcher.py"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "run_dir = telemetry.parent\n"
        "telemetry.write_text(json.dumps({'samples': [{"
        "'t': 0.0, 'x': 0.0, 'y': 0.0, 'z': 3.0}]}), encoding='utf-8')\n"
        "(run_dir / 'px4_parameters.requested.json').write_text(json.dumps({"
        "'px4_version': 'main', 'values': {'MPC_XY_P': 1.1}}), encoding='utf-8')\n"
        "(run_dir / 'px4_parameters.before.json').write_text(json.dumps({"
        "'px4_version': 'main', 'values': {'MPC_XY_P': 0.95}}), encoding='utf-8')\n"
        "(run_dir / 'px4_parameters.applied.json').write_text(json.dumps({"
        "'px4_version': 'main', 'values': {'MPC_XY_P': 0.7}, "
        "'verification': {'verified': True, 'mismatches': {}}}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "false"
    env["PX4_GAZEBO_LAUNCH_COMMAND"] = f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is False
    assert "does not match request for MPC_XY_P" in result["failure"]["reason"]


def test_px4_runner_treats_nonzero_launcher_exit_as_failure(tmp_path: Path):
    launcher = tmp_path / "nonzero_launcher.py"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "telemetry.write_text(json.dumps({'samples': [{"
        "'t': 0.0, 'x': 0.0, 'y': 0.0, 'z': 3.0}]}), encoding='utf-8')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == "SIMULATION_FAILED"
    assert "exited with code 7" in result["failure"]["reason"]


def test_px4_runner_trajectory_artifact_type_is_json(tmp_path: Path):
    proc, result = _run_runner(tmp_path, env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    assert proc.returncode == 0
    assert result["success"] is True
    trajectory = next(
        a for a in result["artifacts"] if Path(a["storage_path"]).name == "trajectory.json"
    )
    assert trajectory["artifact_type"] == "trajectory_json"
    assert trajectory["display_name"] == "Trajectory Samples"
    assert trajectory["mime_type"] == "application/json"


def test_px4_runner_collects_track_marker_logs_when_present(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "run_dir = telemetry.parent\n"
        "telemetry.write_text("
        '\'{"samples": [{"t": 0.0, "x": 0.0, "y": 0.0, "z": 3.0}]}\''
        ", encoding='utf-8')\n"
        "(run_dir / 'track_marker_stdout.log').write_text('marker ok\\n', encoding='utf-8')\n"
        "(run_dir / 'track_marker_stderr.log').write_text('', encoding='utf-8')\n",
        encoding="utf-8",
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    artifact_types = {artifact["artifact_type"] for artifact in result["artifacts"]}
    assert "gazebo_track_marker_stdout_log" in artifact_types
    assert "gazebo_track_marker_stderr_log" in artifact_types


def test_evaluation_window_ignores_takeoff_transition_and_landing(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_PASS_RMSE": "1.5",
            "PX4_GAZEBO_PASS_MAX_ERROR": "3.0",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["raw_metric_json"]["full_log_max_error"] > 4.5
    assert result["metrics"]["rmse"] < 0.2
    assert result["metrics"]["pass_flag"] is True


def test_track_coverage_is_invariant_to_reference_waypoint_density(tmp_path: Path) -> None:
    telemetry = [
        {
            "t": index * 0.1,
            "x": index / 10,
            "y": 0.0,
            "z": 3.0,
            "crashed": False,
        }
        for index in range(101)
    ]
    sparse_reference = [
        {"x": 0.0, "y": 0.0, "z": 3.0},
        {"x": 10.0, "y": 0.0, "z": 3.0},
    ]
    dense_reference = [{"x": index / 100, "y": 0.0, "z": 3.0} for index in range(1_001)]

    sparse_proc, sparse = _run_custom_track_case(
        tmp_path / "sparse",
        reference_track=sparse_reference,
        telemetry_samples=telemetry,
    )
    dense_proc, dense = _run_custom_track_case(
        tmp_path / "dense",
        reference_track=dense_reference,
        telemetry_samples=telemetry,
    )

    assert sparse_proc.returncode == 0
    assert dense_proc.returncode == 0
    assert sparse["success"] is True, sparse
    assert dense["success"] is True, dense
    sparse_raw = sparse["metrics"]["raw_metric_json"]
    dense_raw = dense["metrics"]["raw_metric_json"]
    assert sparse_raw["evaluation_track_coverage"] == pytest.approx(1.0, abs=1e-6)
    assert dense_raw["evaluation_track_coverage"] == pytest.approx(1.0, abs=1e-6)
    assert sparse["metrics"]["rmse"] == pytest.approx(dense["metrics"]["rmse"], abs=1e-6)
    assert sparse["metrics"]["overshoot_count"] == 0
    assert dense["metrics"]["overshoot_count"] == 0
    assert dense_raw["coverage_basis"] == "union_of_traversed_polyline_arc_length"


def test_track_progress_rejects_reverse_and_backtracking_flights(tmp_path: Path) -> None:
    reference = [
        {"x": 0.0, "y": 0.0, "z": 3.0},
        {"x": 10.0, "y": 0.0, "z": 3.0},
    ]
    reverse = [
        {"t": index * 0.1, "x": 10.0 - index / 10, "y": 0.0, "z": 3.0} for index in range(101)
    ]
    backtracking_positions = [index / 10 for index in range(51)]
    backtracking_positions += [5.0 - index / 10 for index in range(1, 31)]
    backtracking_positions += [2.0 + index / 10 for index in range(1, 81)]
    backtracking = [
        {"t": index * 0.1, "x": x, "y": 0.0, "z": 3.0}
        for index, x in enumerate(backtracking_positions)
    ]

    _, reverse_result = _run_custom_track_case(
        tmp_path / "reverse",
        reference_track=reference,
        telemetry_samples=reverse,
    )
    _, backtracking_result = _run_custom_track_case(
        tmp_path / "backtracking",
        reference_track=reference,
        telemetry_samples=backtracking,
    )

    reverse_raw = reverse_result["metrics"]["raw_metric_json"]
    assert reverse_raw["evaluation_track_coverage"] == 0.0
    assert reverse_raw["evaluation_direction_valid"] is False
    assert reverse_result["metrics"]["pass_flag"] is False
    backtracking_raw = backtracking_result["metrics"]["raw_metric_json"]
    assert backtracking_raw["evaluation_track_coverage"] == pytest.approx(1.0, abs=1e-6)
    assert backtracking_raw["evaluation_backward_distance_m"] > 2.9
    assert backtracking_raw["evaluation_progress_contract_ok"] is False
    assert backtracking_result["metrics"]["pass_flag"] is False


def test_track_progress_rejects_large_jump_and_unreached_endpoint(tmp_path: Path) -> None:
    reference = [
        {"x": 0.0, "y": 0.0, "z": 3.0},
        {"x": 10.0, "y": 0.0, "z": 3.0},
    ]
    jump = [
        {"t": index * 10.0, "x": x, "y": 0.0, "z": 3.0}
        for index, x in enumerate([0.0, 0.0, 10.0, 10.0, 10.0])
    ]
    incomplete = [{"t": index * 0.1, "x": index / 10, "y": 0.0, "z": 3.0} for index in range(96)]

    _, jump_result = _run_custom_track_case(
        tmp_path / "jump",
        reference_track=reference,
        telemetry_samples=jump,
    )
    _, incomplete_result = _run_custom_track_case(
        tmp_path / "incomplete",
        reference_track=reference,
        telemetry_samples=incomplete,
    )

    jump_raw = jump_result["metrics"]["raw_metric_json"]
    assert jump_raw["evaluation_progress_discontinuity_count"] == 1
    assert jump_raw["evaluation_track_coverage"] == 0.0
    assert jump_result["metrics"]["pass_flag"] is False
    incomplete_raw = incomplete_result["metrics"]["raw_metric_json"]
    assert incomplete_raw["evaluation_track_coverage"] > 0.9
    assert incomplete_raw["evaluation_endpoint_reached"] is False
    assert incomplete_result["metrics"]["pass_flag"] is False


def test_custom_track_uses_three_dimensional_projection_and_reference_altitude(
    tmp_path: Path,
) -> None:
    reference = [{"x": index / 10, "y": 0.0, "z": 5.0 - (index / 25)} for index in range(101)]
    correct = [
        {
            "t": index * 0.1,
            "x": point["x"],
            "y": point["y"],
            "z": point["z"],
            "crashed": False,
        }
        for index, point in enumerate(reference)
    ]
    altitude_offset = [dict(sample, z=float(sample["z"]) + 1.0) for sample in correct]

    correct_proc, correct_result = _run_custom_track_case(
        tmp_path / "correct",
        reference_track=reference,
        telemetry_samples=correct,
    )
    offset_proc, offset_result = _run_custom_track_case(
        tmp_path / "offset",
        reference_track=reference,
        telemetry_samples=altitude_offset,
        env_overrides={"PX4_GAZEBO_PASS_RMSE": "2.0", "PX4_GAZEBO_PASS_MAX_ERROR": "2.0"},
    )

    assert correct_proc.returncode == 0
    assert offset_proc.returncode == 0
    assert correct_result["success"] is True, correct_result
    assert offset_result["success"] is True, offset_result
    assert correct_result["metrics"]["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert offset_result["metrics"]["rmse"] > 0.8
    correct_raw = correct_result["metrics"]["raw_metric_json"]
    assert correct_raw["evaluation_track_coverage"] == pytest.approx(1.0, abs=1e-6)
    # A legitimate descending custom track must not be trimmed as a landing
    # merely because later points are below the first point's altitude.
    assert correct_raw["evaluation_sample_count"] == len(correct)
    assert correct_raw["evaluation_max_error_sample"]["reference_z"] == pytest.approx(
        correct_raw["evaluation_max_error_sample"]["z"], abs=1e-6
    )
    assert correct_raw["track_projection"] == "ordered_local_3d_segment_projection"


@pytest.mark.parametrize("limit_kind", ["bytes", "samples"])
def test_px4_runner_rejects_oversized_telemetry_contract(
    tmp_path: Path,
    limit_kind: str,
) -> None:
    input_path = _trial_input(tmp_path)
    launcher = tmp_path / "oversized_telemetry.py"
    if limit_kind == "bytes":
        body = (
            f"with telemetry.open('wb') as stream:\n    stream.truncate({16 * 1024 * 1024 + 1})\n"
        )
        expected = "byte contract limit"
    else:
        body = (
            "samples = ["
            "{'t': i, 'x': 0.0, 'y': 0.0, 'z': 3.0} for i in range(50001)]\n"
            "telemetry.write_text(json.dumps({'samples': samples}), encoding='utf-8')\n"
        )
        expected = "sample contract limit"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n" + body,
        encoding="utf-8",
    )
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(
        {
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f'"{sys.executable}" "{launcher}" --telemetry {{telemetry_json}}'
            ),
        }
    )

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is False
    assert expected in result["failure"]["reason"]


def test_preflight_and_post_track_ground_samples_do_not_trigger_crash(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is False
    assert result["metrics"]["raw_metric_json"]["crash_reason"] == "none"


def test_crash_inside_evaluation_window_sets_crash_flag(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for idx in range(80, 90):
        samples[idx]["crashed"] = True
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is True
    assert result["metrics"]["raw_metric_json"]["crash_reason"] == "telemetry_crashed_flag"
    assert result["metrics"]["pass_flag"] is False


def test_altitude_collapse_inside_evaluation_window_sets_crash(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for idx in range(120, 130):
        samples[idx]["z"] = 1.0
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES": "5",
            "PX4_GAZEBO_EVAL_ALTITUDE_FRACTION": "0.3",
            "PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION": "0.5",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is True
    assert (
        result["metrics"]["raw_metric_json"]["crash_reason"]
        == "altitude_collapse_in_evaluation_window"
    )


def test_offboard_timing_window_source_is_used_when_present(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    launcher = _write_launcher_with_payloads(
        tmp_path / "launcher.py",
        telemetry,
        offboard_timing_payload={
            "track_start_t": _find_sample_time(samples, 10),
            "track_end_t": _find_sample_time(samples, 210),
            "time_base": "executor_relative_seconds",
        },
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_window_source"] == "offboard_timing_refined"
    assert raw["evaluation_window_raw_source"] == "offboard_timing"
    assert raw["evaluation_start_t"] > raw["raw_track_start_t"]
    assert raw["evaluation_trimmed_takeoff_samples"] > 0
    assert raw["crash_reason"] == "none"
    assert result["metrics"]["crash_flag"] is False
    assert raw["evaluation_sample_count"] < raw["total_sample_count"]
    assert result["metrics"]["max_error"] < 3.5


def test_telemetry_derived_window_source_used_when_timing_missing(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_window_source"] == "telemetry_derived_refined"
    for key in (
        "evaluation_window_source",
        "evaluation_window_raw_source",
        "raw_track_start_t",
        "raw_track_end_t",
        "evaluation_start_t",
        "evaluation_end_t",
        "evaluation_sample_count",
        "total_sample_count",
        "evaluation_start_reason",
        "evaluation_trimmed_takeoff_samples",
        "evaluation_trimmed_landing_samples",
        "evaluation_min_z",
        "evaluation_max_z",
        "evaluation_max_error_sample",
        "crash_reason",
    ):
        assert key in raw


def test_entry_requires_consecutive_samples(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for i in range(20, 40):
        samples[i]["z"] = 0.0
    samples[30]["x"] = 5.0
    samples[30]["y"] = 0.0
    samples[30]["z"] = 3.0
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES": "5",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_start_t"] > float(samples[30]["t"])


def _ctx() -> TrialContext:
    return TrialContext(
        trial_id="trial-1",
        job_id="job-1",
        candidate_id="cand-1",
        seed=42,
        scenario_type="nominal",
        scenario_config={},
        parameters={
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": 5.0,
            "accel_limit": 4.0,
            "disturbance_rejection": 0.5,
        },
        job_config=JobConfig(
            track_type="circle",
            start_point_x=0.0,
            start_point_y=0.0,
            altitude_m=3.0,
            wind_north=0.0,
            wind_east=0.0,
            wind_south=0.0,
            wind_west=0.0,
            sensor_noise_level="medium",
            objective_profile="robust",
        ),
    )


def test_real_cli_integration_with_px4_runner_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{RUNNER}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "true")
    adapter = RealCliSimulatorAdapter()

    result = adapter.run_trial(_ctx())

    assert result.success is True, result.failure
    assert result.metrics is not None
    assert result.metrics.raw_metric_json.get("mode") == "dry_run"
    run_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1"
    assert (run_dir / "telemetry.json").exists()
    assert (run_dir / "trajectory.json").exists()
    assert {a.artifact_type for a in result.artifacts} >= {
        "telemetry_json",
        "trajectory_json",
        "worker_log",
    }
