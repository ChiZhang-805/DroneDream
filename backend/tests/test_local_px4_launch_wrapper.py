from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.simulator import scenario_effects
from app.simulator.scenario_effects import (
    EVIDENCE_ARTIFACT_NAME,
    build_scenario_effect_request,
    compile_bundled_sdf_profile,
    compile_bundled_steady_wind,
    validate_scenario_effect_evidence,
)

WRAPPER = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "local_px4_launch_wrapper.py"
)
RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "px4_gazebo_runner.py"
WRAPPER_SPEC = importlib.util.spec_from_file_location("local_px4_launch_wrapper", WRAPPER)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
wrapper = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(wrapper)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_wrapper_prefers_checkout_backend_over_stale_installed_app(tmp_path: Path) -> None:
    fake_site = tmp_path / "fake_site"
    fake_simulator = fake_site / "app" / "simulator"
    fake_simulator.mkdir(parents=True)
    (fake_site / "app" / "__init__.py").write_text("", encoding="utf-8")
    (fake_simulator / "__init__.py").write_text("", encoding="utf-8")

    probe = "\n".join(
        [
            "import importlib.util",
            "from pathlib import Path",
            f"wrapper_path = Path({str(WRAPPER)!r})",
            "spec = importlib.util.spec_from_file_location('wrapper_probe', wrapper_path)",
            "assert spec is not None and spec.loader is not None",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "print(Path(module._load_scenario_effect_engine().__file__).resolve())",
        ]
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_site)
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    expected = Path(__file__).resolve().parents[1] / "app" / "simulator" / "scenario_effects.py"
    assert Path(proc.stdout.strip()).resolve() == expected.resolve()


def _make_args(tmp_path: Path) -> list[str]:
    run_dir = tmp_path / "run"
    input_path = _write_json(tmp_path / "trial_input.json", {"trial_id": "t"})
    params = _write_json(tmp_path / "params.json", {"kp_xy": 1.0})
    track = _write_json(tmp_path / "track.json", {"points": [{"x": 0.0, "y": 0.0, "z": 3.0}]})
    telemetry = run_dir / "telemetry.json"
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    return [
        "--run-dir",
        str(run_dir),
        "--input",
        str(input_path),
        "--params",
        str(params),
        "--track",
        str(track),
        "--telemetry",
        str(telemetry),
        "--stdout-log",
        str(stdout_log),
        "--stderr-log",
        str(stderr_log),
        "--vehicle",
        "x500",
        "--world",
        "default",
        "--headless",
        "true",
    ]


def _set_headless_arg(args: list[str], value: str) -> list[str]:
    updated = list(args)
    headless_idx = updated.index("--headless")
    updated[headless_idx + 1] = value
    return updated


def _basic_telemetry() -> dict:
    return {
        "samples": [
            {
                "t": 0.0,
                "x": 0.0,
                "y": 0.0,
                "z": 3.0,
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw": 0.0,
                "armed": True,
                "mode": "offboard",
                "crashed": False,
            }
        ]
    }


def test_wrapper_requires_required_args():
    proc = subprocess.run(
        [sys.executable, str(WRAPPER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--run-dir" in proc.stderr


def test_wrapper_site_dry_run_writes_valid_telemetry(tmp_path: Path):
    args = _make_args(tmp_path)
    args[args.index("--vehicle") + 1] = "gz_x500_depth"
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "true"
    # The legacy worker default must not override a per-job simulator model.
    env["PX4_MAKE_TARGET"] = "gz_x500"
    env.pop("PX4_FORCE_MAKE_TARGET", None)
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    telemetry = json.loads((tmp_path / "run" / "telemetry.json").read_text(encoding="utf-8"))
    assert "samples" in telemetry and len(telemetry["samples"]) == 1
    sample = telemetry["samples"][0]
    assert sample["z"] == 3.0
    assert sample["mode"] == "offboard"
    assert telemetry["meta"]["mode"] == "site_dry_run"
    assert (tmp_path / "run" / "controller_params.used.json").exists()
    assert (tmp_path / "run" / "reference_track.used.json").exists()
    assert (tmp_path / "run" / "launch_config.json").exists()
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["make_target"] == "gz_x500_depth"
    assert launch_config["GZ_PARTITION"] == wrapper._trial_gazebo_partition(tmp_path / "run")
    assert re.fullmatch(r"dronedream_[0-9a-f]{24}", launch_config["GZ_PARTITION"])
    assert launch_config["GZ_IP"] == "127.0.0.1"


def test_gazebo_transport_partition_is_stable_and_trial_isolated(tmp_path: Path) -> None:
    first = wrapper._trial_gazebo_partition(tmp_path / "trial-a")
    repeated = wrapper._trial_gazebo_partition(tmp_path / "trial-a")
    second = wrapper._trial_gazebo_partition(tmp_path / "trial-b")

    assert first == repeated
    assert first != second
    assert re.fullmatch(r"dronedream_[0-9a-f]{24}", first)


def test_make_target_can_be_explicitly_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PX4_MAKE_TARGET", "gz_x500")
    monkeypatch.setenv("PX4_FORCE_MAKE_TARGET", "true")
    assert wrapper._make_target_for_vehicle("gz_x500_depth") == "gz_x500"


def test_wrapper_site_dry_run_is_deterministic(tmp_path: Path):
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "true"

    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    proc_a = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(run_a)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    proc_b = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(run_b)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc_a.returncode == 0
    assert proc_b.returncode == 0
    telemetry_a = json.loads((run_a / "run" / "telemetry.json").read_text(encoding="utf-8"))
    telemetry_b = json.loads((run_b / "run" / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry_a == telemetry_b


def test_wrapper_site_dry_run_writes_px4_parameter_evidence(tmp_path: Path):
    args = _make_args(tmp_path)
    px4_parameters = _write_json(
        tmp_path / "px4_parameters.json",
        {"MPC_XY_P": 1.1, "MC_ROLLRATE_P": 0.16},
    )
    args.extend(["--px4-params", str(px4_parameters)])
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "true"
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    run_dir = tmp_path / "run"
    for filename in (
        "px4_parameters.requested.json",
        "px4_parameters.before.json",
        "px4_parameters.applied.json",
    ):
        evidence = json.loads((run_dir / filename).read_text(encoding="utf-8"))
        assert evidence["status"] == "simulated"
    launch_config = json.loads((run_dir / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["PX4_PARAMETER_TRANSPORT"] == "environment"
    assert launch_config["px4_parameter_names"] == ["MC_ROLLRATE_P", "MPC_XY_P"]


def test_wrapper_real_mode_requires_px4_autopilot_dir(tmp_path: Path):
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env.pop("PX4_AUTOPILOT_DIR", None)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "PX4_AUTOPILOT_DIR is required" in stderr_text


def _fake_dataset(name: str, data: dict[str, list[float] | list[int]]) -> SimpleNamespace:
    return SimpleNamespace(name=name, data=data)


def _fake_ulog_with_groundtruth_yaw() -> SimpleNamespace:
    return SimpleNamespace(
        data_list=[
            _fake_dataset(
                "vehicle_local_position",
                {
                    "timestamp": [1_000_000, 2_000_000],
                    "x": [1.0, 2.0],
                    "y": [3.0, 4.0],
                    "z": [-5.0, -6.0],
                    "vx": [0.2, 0.2],
                    "vy": [0.0, 0.2],
                    "vz": [-0.1, -0.2],
                },
            ),
            _fake_dataset(
                "vehicle_attitude_groundtruth",
                {
                    "q[0]": [1.0, math.cos(math.pi / 4)],
                    "q[1]": [0.0, 0.0],
                    "q[2]": [0.0, 0.0],
                    "q[3]": [0.0, math.sin(math.pi / 4)],
                },
            ),
            _fake_dataset(
                "vehicle_status",
                {
                    "arming_state": [2, 2],
                    "nav_state": [14, 14],
                },
            ),
            _fake_dataset(
                "failure_detector_status",
                {
                    "fd_motor": [0, 1],
                    "fd_roll": [0, 0],
                },
            ),
        ]
    )


def test_find_latest_ulog_recurses_and_selects_newest(tmp_path: Path):
    older = tmp_path / "2026-04-23" / "08_51_47.ulg"
    newer = tmp_path / "2026-04-24" / "08_53_27.ulg"
    older.parent.mkdir(parents=True, exist_ok=True)
    newer.parent.mkdir(parents=True, exist_ok=True)
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    latest = wrapper.find_latest_ulog(tmp_path)
    assert latest == newer


def test_find_latest_ulog_with_snapshot_rejects_unchanged_history(tmp_path: Path):
    historical = tmp_path / "2026-04-23" / "08_51_47.ulg"
    historical.parent.mkdir(parents=True)
    historical.write_text("old", encoding="utf-8")
    before = wrapper.snapshot_ulogs(tmp_path)

    with pytest.raises(FileNotFoundError, match="No new or changed ULog"):
        wrapper.find_latest_ulog(tmp_path, before=before)


def test_find_latest_ulog_with_snapshot_accepts_changed_or_new_file(tmp_path: Path):
    changed = tmp_path / "changed.ulg"
    changed.write_text("old", encoding="utf-8")
    before = wrapper.snapshot_ulogs(tmp_path)
    changed.write_text("new-and-larger", encoding="utf-8")
    os.utime(changed, (1_900_000_000, 1_900_000_000))

    assert wrapper.find_latest_ulog(tmp_path, before=before) == changed


def test_retain_ulog_snapshot_is_bounded_and_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.ulg"
    source.write_bytes(b"immutable ULog evidence")
    run_dir = tmp_path / "run"

    retained = wrapper.retain_ulog_snapshot(source, run_dir)

    assert retained == run_dir / wrapper.RETAINED_ULOG_NAME
    assert retained.read_bytes() == b"immutable ULog evidence"
    source.write_bytes(b"changed after snapshot")
    assert retained.read_bytes() == b"immutable ULog evidence"

    oversized = tmp_path / "oversized.ulg"
    oversized.write_bytes(b"12345")
    monkeypatch.setattr(wrapper, "MAX_ULOG_BYTES", 4)
    with pytest.raises(ValueError, match="safety limit"):
        wrapper.retain_ulog_snapshot(oversized, run_dir)
    assert retained.read_bytes() == b"immutable ULog evidence"


def test_retain_ulog_snapshot_rejects_symlink_source(tmp_path: Path) -> None:
    target = tmp_path / "target.ulg"
    target.write_bytes(b"target bytes")
    source = tmp_path / "source.ulg"
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    with pytest.raises(ValueError, match="regular, non-symlink"):
        wrapper.retain_ulog_snapshot(source, tmp_path / "run")


def test_ulog_to_telemetry_json_writes_schema_with_attitude_groundtruth_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    fake_ulog = _fake_ulog_with_groundtruth_yaw()

    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = fake_ulog.data_list

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    output_path = tmp_path / "telemetry.json"
    ulog_path = tmp_path / "sample.ulg"
    ulog_path.write_bytes(b"test ULog fixture")
    wrapper.ulog_to_telemetry_json(
        ulog_path,
        output_path,
        vehicle="x500",
        world="default",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["meta"]["source"] == "ulog"
    assert payload["meta"]["vehicle"] == "x500"
    assert payload["meta"]["origin_source_sha256"].startswith("sha256:")
    assert len(payload["meta"]["origin_source_sha256"]) == 71
    assert payload["meta"]["origin_source_byte_count"] == len(b"test ULog fixture")
    assert payload["meta"]["origin_coordinate_frame"] == "PX4_LOCAL_NED"
    assert payload["meta"]["origin_extraction_revision"] == ("pyulog-vehicle-local-position-1.1")
    assert payload["meta"]["origin_timestamp_duplicate_count"] == 0
    assert payload["samples"][0]["t"] == 0.0
    assert payload["samples"][0]["z"] == 5.0
    assert payload["samples"][0]["vz"] == 0.1
    assert payload["samples"][0]["yaw"] == pytest.approx(0.0)
    assert payload["samples"][1]["yaw"] == pytest.approx(math.pi / 2)
    assert payload["samples"][0]["mode"] == "14"
    assert payload["samples"][1]["crashed"] is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (np.int8(0), False),
        (np.uint8(1), True),
        (np.float32(0.0), False),
        (np.float64(1.0), True),
    ],
)
def test_bool_from_value_accepts_exact_numpy_boolean_encodings(
    value: object,
    expected: bool,
) -> None:
    assert wrapper._bool_from_value(value) is expected


@pytest.mark.parametrize("value", [np.int8(2), np.float32(0.5)])
def test_bool_from_value_rejects_non_boolean_numpy_numbers(value: object) -> None:
    with pytest.raises(ValueError, match="invalid boolean telemetry value"):
        wrapper._bool_from_value(value)


def test_ulog_to_telemetry_json_fails_when_vehicle_local_position_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = [_fake_dataset("vehicle_status", {"nav_state": [1]})]

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    ulog_path = tmp_path / "sample.ulg"
    ulog_path.write_bytes(b"test ULog fixture")
    with pytest.raises(ValueError, match="vehicle_local_position"):
        wrapper.ulog_to_telemetry_json(
            ulog_path,
            tmp_path / "telemetry.json",
            "x500",
            "default",
        )


def test_ulog_conversion_downsamples_evenly_and_preserves_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_ulog = _fake_ulog_with_groundtruth_yaw()
    local_position = fake_ulog.data_list[0]
    local_position.data = {
        "timestamp": [index * 1_000_000 for index in range(6)],
        "x": [float(index) for index in range(6)],
        "y": [0.0] * 6,
        "z": [-3.0] * 6,
        "vx": [1.0] * 6,
        "vy": [0.0] * 6,
        "vz": [0.0] * 6,
    }

    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = fake_ulog.data_list

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    monkeypatch.setattr(wrapper, "MAX_TELEMETRY_SAMPLES", 3)
    ulog_path = tmp_path / "sample.ulg"
    ulog_path.write_bytes(b"test ULog fixture")
    output_path = tmp_path / "telemetry.json"

    wrapper.ulog_to_telemetry_json(ulog_path, output_path, "x500", "default")

    samples = json.loads(output_path.read_text(encoding="utf-8"))["samples"]
    assert [sample["x"] for sample in samples] == [0.0, 2.0, 5.0]
    assert [sample["t"] for sample in samples] == [0.0, 2.0, 5.0]


def test_ulog_conversion_collapses_exact_duplicate_timestamp_and_retains_last_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_ulog = _fake_ulog_with_groundtruth_yaw()
    local_position = fake_ulog.data_list[0]
    local_position.data = {
        "timestamp": [1_000_000, 2_000_000, 2_000_000, 3_000_000],
        "x": [0.0, 1.0, 2.0, 3.0],
        "y": [0.0] * 4,
        "z": [-3.0] * 4,
        "vx": [1.0] * 4,
        "vy": [0.0] * 4,
        "vz": [0.0] * 4,
    }

    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = fake_ulog.data_list

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    ulog_path = tmp_path / "sample.ulg"
    ulog_path.write_bytes(b"test ULog fixture")
    output_path = tmp_path / "telemetry.json"

    wrapper.ulog_to_telemetry_json(ulog_path, output_path, "x500", "default")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [sample["t"] for sample in payload["samples"]] == [0.0, 1.0, 2.0]
    assert [sample["x"] for sample in payload["samples"]] == [0.0, 2.0, 3.0]
    assert payload["meta"]["origin_timestamp_duplicate_count"] == 1
    assert payload["meta"]["origin_timestamp_duplicate_policy"] == (
        "retain_last_exact_microsecond_sample"
    )


def test_ulog_conversion_rejects_timestamp_that_moves_backwards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_ulog = _fake_ulog_with_groundtruth_yaw()
    local_position = fake_ulog.data_list[0]
    local_position.data = {
        "timestamp": [1_000_000, 3_000_000, 2_000_000],
        "x": [0.0, 1.0, 2.0],
        "y": [0.0] * 3,
        "z": [-3.0] * 3,
        "vx": [1.0] * 3,
        "vy": [0.0] * 3,
        "vz": [0.0] * 3,
    }

    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = fake_ulog.data_list

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    ulog_path = tmp_path / "sample.ulg"
    ulog_path.write_bytes(b"test ULog fixture")

    with pytest.raises(ValueError, match="timestamp moved backwards at sample 2"):
        wrapper.ulog_to_telemetry_json(
            ulog_path,
            tmp_path / "telemetry.json",
            "x500",
            "default",
        )


def _obstacle_effect() -> dict[str, object]:
    return {
        "effect_id": "obstacles",
        "source": "advanced_scenario_config.obstacles",
        "requested_value": [
            {
                "type": "box",
                "x": 1.0,
                "y": 2.0,
                "z": 0.5,
                "size_x": 1.0,
                "size_y": 2.0,
                "size_z": 1.0,
            }
        ],
        "launcher_input": {},
        "mechanism": "gazebo_entity_factory",
        "capability": {"status": "available", "reason": "test"},
    }


def _wind_request() -> dict[str, object]:
    return build_scenario_effect_request(
        execution_identity={
            "trial_id": "t",
            "job_id": "j",
            "candidate_id": "c",
            "seed": 42,
            "attempt_count": 1,
        },
        scenario_type="nominal",
        scenario_config={"wind_mps": 2.0},
        job_config={
            "wind": {"north": 1.0, "east": 0.5, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )


def _minimal_px4_gazebo_tree(tmp_path: Path, *, world: str = "default") -> Path:
    px4_root = tmp_path / "PX4-Autopilot"
    model_dir = px4_root / "Tools" / "simulation" / "gz" / "models" / "x500_base"
    vehicle_model_dir = px4_root / "Tools" / "simulation" / "gz" / "models" / "x500"
    world_dir = px4_root / "Tools" / "simulation" / "gz" / "worlds"
    build_root = px4_root / "build" / "px4_sitl_default"
    rootfs = build_root / "rootfs"
    executable = build_root / "bin" / "px4"
    plugins = build_root / "src" / "modules" / "simulation" / "gz_plugins"
    server_config = px4_root / "src" / "modules" / "simulation" / "gz_bridge" / "server.config"
    model_dir.mkdir(parents=True)
    vehicle_model_dir.mkdir(parents=True)
    world_dir.mkdir(parents=True)
    rootfs.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    plugins.mkdir(parents=True)
    server_config.parent.mkdir(parents=True)
    (rootfs / "gz_env.sh").write_text("original", encoding="utf-8")
    (rootfs / "parameters.bson").write_text("stale", encoding="utf-8")
    (rootfs / "dataman").write_text("stale", encoding="utf-8")
    (rootfs / "log").mkdir()
    (rootfs / "log" / "stale.ulg").write_text("stale", encoding="utf-8")
    executable.write_text("px4", encoding="utf-8")
    server_config.write_text(
        """
<server_config>
  <plugins>
    <plugin entity_name="*" entity_type="world"
            filename="gz-sim-physics-system"
            name="gz::sim::systems::Physics"/>
    <plugin entity_name="*" entity_type="world"
            filename="gz-sim-user-commands-system"
            name="gz::sim::systems::UserCommands"/>
    <plugin entity_name="*" entity_type="world"
            filename="gz-sim-scene-broadcaster-system"
            name="gz::sim::systems::SceneBroadcaster"/>
  </plugins>
</server_config>
""".strip(),
        encoding="utf-8",
    )
    (model_dir / "model.sdf").write_text(
        """
<sdf version="1.9">
  <model name="x500_base">
    <link name="base_link">
      <inertial>
        <mass>2</mass>
        <inertia>
          <ixx>0.02</ixx><ixy>0</ixy><ixz>0</ixz>
          <iyy>0.02</iyy><iyz>0</iyz><izz>0.04</izz>
        </inertia>
      </inertial>
      <sensor name="air_pressure_sensor" type="air_pressure">
        <air_pressure>
          <pressure><noise type="gaussian"><stddev>3</stddev></noise></pressure>
        </air_pressure>
      </sensor>
      <sensor name="imu_sensor" type="imu">
        <imu>
          <angular_velocity>
            <x><noise type="gaussian"><stddev>0.001</stddev></noise></x>
            <y><noise type="gaussian"><stddev>0.001</stddev></noise></y>
            <z><noise type="gaussian"><stddev>0.001</stddev></noise></z>
          </angular_velocity>
          <linear_acceleration>
            <x><noise type="gaussian"><stddev>0.01</stddev></noise></x>
            <y><noise type="gaussian"><stddev>0.01</stddev></noise></y>
            <z><noise type="gaussian"><stddev>0.02</stddev></noise></z>
          </linear_acceleration>
        </imu>
      </sensor>
      <sensor name="navsat_sensor" type="navsat"><navsat /></sensor>
      <visual name="rotor">
        <geometry><box><size>1 1 1</size></box></geometry>
        <material>
          <script>
            <name>Gazebo/DarkGrey</name>
            <uri>file://media/materials/scripts/gazebo.material</uri>
          </script>
        </material>
      </visual>
    </link>
  </model>
</sdf>
""".strip(),
        encoding="utf-8",
    )
    (model_dir / "model.config").write_text("<model/>", encoding="utf-8")
    (vehicle_model_dir / "model.sdf").write_text(
        """
<sdf version="1.9">
  <model name="x500">
    <include><uri>model://x500_base</uri></include>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <jointName>rotor_0_joint</jointName><motorNumber>0</motorNumber><maxRotVelocity>1000</maxRotVelocity><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <jointName>rotor_1_joint</jointName><motorNumber>1</motorNumber><maxRotVelocity>1000</maxRotVelocity><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <jointName>rotor_2_joint</jointName><motorNumber>2</motorNumber><maxRotVelocity>1000</maxRotVelocity><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <jointName>rotor_3_joint</jointName><motorNumber>3</motorNumber><maxRotVelocity>1000</maxRotVelocity><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
  </model>
</sdf>
""".strip(),
        encoding="utf-8",
    )
    (vehicle_model_dir / "model.config").write_text("<model/>", encoding="utf-8")
    (world_dir / f"{world}.sdf").write_text(
        f"""
<sdf version="1.9">
  <world name="{world}">
    <gravity>0 0 -9.8</gravity>
  </world>
</sdf>
""".strip(),
        encoding="utf-8",
    )
    return px4_root


def _overlay_stub(request: dict[str, object], tmp_path: Path) -> dict[str, object]:
    compiled = compile_bundled_steady_wind(request)
    assert compiled is not None
    world_sdf = tmp_path / "world.sdf"
    model_sdf = tmp_path / "model.sdf"
    trial_rootfs = tmp_path / "px4_rootfs"
    trial_rootfs.mkdir(exist_ok=True)
    trial_gz_env = trial_rootfs / "gz_env.sh"
    world_sdf.write_text("<sdf/>", encoding="utf-8")
    model_sdf.write_text("<sdf/>", encoding="utf-8")
    trial_gz_env.write_text("export PX4_GZ_WORLDS=/trial", encoding="utf-8")
    return {
        "compiled_wind": compiled,
        "model_sdf_path": str(model_sdf),
        "model_sdf_sha256": "a" * 64,
        "sanitized_classic_material_scripts": 1,
        "world_sdf_path": str(world_sdf),
        "world_sdf_sha256": "b" * 64,
        "wind_enabled_link": "x500_base/base_link",
        "wind_effects_plugin": {
            "filename": wrapper.WIND_EFFECTS_PLUGIN_FILENAME,
            "name": wrapper.WIND_EFFECTS_PLUGIN_NAME,
        },
        "materialized_px4_system_plugins": [
            {
                "filename": "gz-sim-physics-system",
                "name": "gz::sim::systems::Physics",
            }
        ],
        "px4_server_config_path": str(tmp_path / "server.config"),
        "px4_server_config_sha256": "d" * 64,
        "px4_vehicle_model_instance": "x500_0",
        "px4_trial_rootfs_path": str(trial_rootfs),
        "px4_trial_gz_env_path": str(trial_gz_env),
        "px4_trial_gz_env_sha256": "c" * 64,
    }


def test_sdf_profile_mutators_round_trip_generated_runtime_sdf(tmp_path: Path) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "t", "seed": 42},
        scenario_type="actuator_delay",
        scenario_config={"delay_ms": 80.0},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "high",
        },
        advanced_config={
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 4.0,
                "direction_deg": 90.0,
                "period_s": 8.0,
            },
            "sensor_degradation": {
                "gps_noise_m": 2.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.5,
            },
            "battery": {"mass_payload_kg": 1.2},
        },
    )
    profile = compile_bundled_sdf_profile(request)
    assert profile is not None
    model_root = ET.fromstring(
        """
<sdf version="1.9">
  <model name="x500_base">
    <link name="base_link">
      <inertial>
        <mass>2</mass>
        <inertia>
          <ixx>0.02</ixx><ixy>0</ixy><ixz>0</ixz>
          <iyy>0.02</iyy><iyz>0</iyz><izz>0.04</izz>
        </inertia>
      </inertial>
      <sensor name="air_pressure_sensor" type="air_pressure">
        <air_pressure>
          <pressure><noise type="gaussian"><stddev>3</stddev></noise></pressure>
        </air_pressure>
      </sensor>
      <sensor name="imu_sensor" type="imu">
        <imu>
          <angular_velocity>
            <x><noise type="gaussian"><stddev>0.001</stddev></noise></x>
            <y><noise type="gaussian"><stddev>0.001</stddev></noise></y>
            <z><noise type="gaussian"><stddev>0.001</stddev></noise></z>
          </angular_velocity>
          <linear_acceleration>
            <x><noise type="gaussian"><stddev>0.01</stddev></noise></x>
            <y><noise type="gaussian"><stddev>0.01</stddev></noise></y>
            <z><noise type="gaussian"><stddev>0.02</stddev></noise></z>
          </linear_acceleration>
        </imu>
      </sensor>
      <sensor name="navsat_sensor" type="navsat"><navsat /></sensor>
    </link>
  </model>
</sdf>
""".strip()
    )
    base_link = model_root.find("./model/link")
    assert base_link is not None
    applied = {
        "sensor_noise": wrapper._apply_sensor_noise_sdf(
            base_link,
            profile["sensor_noise"],
        ),
        "payload": wrapper._apply_payload_sdf(
            base_link,
            profile["payload"],
        ),
    }
    navsat = base_link.find("./sensor[@name='navsat_sensor']/navsat/position_sensing")
    assert navsat is not None
    assert float(navsat.findtext("./horizontal/noise/stddev", default="nan")) == 2.0
    assert float(navsat.findtext("./vertical/noise/stddev", default="nan")) == 2.0
    vehicle_root = ET.fromstring(
        """
<sdf version="1.9">
  <model name="x500">
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <motorNumber>0</motorNumber><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <motorNumber>1</motorNumber><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <motorNumber>2</motorNumber><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
    <plugin filename="motor" name="gz::sim::systems::MulticopterMotorModel">
      <motorNumber>3</motorNumber><timeConstantUp>0.0125</timeConstantUp><timeConstantDown>0.025</timeConstantDown>
    </plugin>
  </model>
</sdf>
""".strip()
    )
    applied["actuator_dynamics"] = wrapper._apply_actuator_dynamics_sdf(
        vehicle_root,
        profile["actuator_dynamics"],
    )

    runtime_root = ET.Element("sdf", {"version": "1.9"})
    world = ET.SubElement(runtime_root, "world", {"name": "default"})
    wind_plugin = ET.SubElement(
        world,
        "plugin",
        {
            "filename": wrapper.WIND_EFFECTS_PLUGIN_FILENAME,
            "name": wrapper.WIND_EFFECTS_PLUGIN_NAME,
        },
    )
    applied["wind_gust"] = wrapper._configure_wind_effects_plugin(
        wind_plugin,
        profile["wind_gust"],
    )
    assert applied["wind_gust"]["time_for_rise_s"] == 1.0
    runtime_model = ET.SubElement(world, "model", {"name": "x500_0"})
    runtime_model.append(copy.deepcopy(base_link))
    source_vehicle = vehicle_root.find("./model")
    assert source_vehicle is not None
    for plugin in source_vehicle.findall("plugin"):
        runtime_model.append(copy.deepcopy(plugin))

    generated = ET.tostring(runtime_root, encoding="unicode")
    observation = wrapper._runtime_sdf_profile_observation(
        generated,
        generated_path=tmp_path / "generated_world.sdf",
        expected_vehicle_model="x500_0",
        applied_sdf_profile=applied,
        require_wind_mode=False,
    )

    assert observation["verified_profile_sections"] == [
        "sensor_noise",
        "payload",
        "actuator_dynamics",
        "wind_gust",
    ]
    assert observation["sdf_sha256"] == wrapper._sha256_hex(tmp_path / "generated_world.sdf")
    runtime_observation = {
        "source": "/world/default/generate_world_sdf",
        "kind": "artifact",
        "value": observation,
        "sha256": scenario_effects.scenario_effect_value_sha256(observation),
    }
    effects = []
    for effect in request["effects"]:
        effects.append(
            {
                "effect_id": effect["effect_id"],
                "mechanism": effect["mechanism"],
                "status": "applied",
                "capability": {
                    "status": "available",
                    "reason": "verified test profile",
                },
                "evidence": {
                    "requested_value_sha256": (
                        scenario_effects.scenario_effect_value_sha256(effect["requested_value"])
                    ),
                    "compiled_sdf_profile": profile,
                    "verification": {
                        "status": "verified",
                        "method": "trial_local_sdf_and_generated_world_sdf",
                        "observations": [runtime_observation],
                    },
                },
            }
        )
    payload = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=effects,
    )
    assert validate_scenario_effect_evidence(request, payload)["verification_status"] == (
        "verified_applied"
    )


def test_obstacle_sdf_and_entity_factory_ack_are_verifiable(tmp_path: Path, monkeypatch) -> None:
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout="/world/default/create\n/world/default/remove\n",
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="data: true\n", stderr=""),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(wrapper, "_gazebo_cli", lambda: "/usr/bin/gz")
    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    record = wrapper._apply_obstacle_effect(
        _obstacle_effect(),
        run_dir=tmp_path,
        world="default",
    )

    assert record["status"] == "applied"
    entity = record["evidence"]["created_entities"][0]
    assert entity["response_data"] is True
    assert len(entity["sdf_sha256"]) == 64
    sdf = Path(entity["sdf_path"])
    assert sdf.is_file()
    assert "<static>true</static>" in sdf.read_text(encoding="utf-8")
    assert commands[1][commands[1].index("-s") + 1] == "/world/default/create"
    assert "gz.msgs.EntityFactory" in commands[1]
    assert "gz.msgs.Boolean" in commands[1]


def test_preflight_allows_static_and_flight_timed_effects_together() -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "t"},
        scenario_type="nominal",
        scenario_config={},
        job_config={
            "wind": {"north": 1.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "obstacles": [_obstacle_effect()["requested_value"][0]],
            "sensor_degradation": {"dropout_rate": 0.2},
        },
    )

    assert wrapper._preflight_scenario_effects(request, site_dry_run=False) is None


def test_preflight_allows_bundled_wind_and_obstacles_together() -> None:
    request = _wind_request()
    request_with_obstacle = build_scenario_effect_request(
        execution_identity=request["execution_identity"],
        scenario_type="nominal",
        scenario_config={"wind_mps": 2.0},
        job_config={
            "wind": {"north": 1.0, "east": 0.5, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={"obstacles": [_obstacle_effect()["requested_value"][0]]},
    )

    assert wrapper._preflight_scenario_effects(request_with_obstacle, site_dry_run=False) is None


def test_trusted_local_xml_rejects_path_escape_and_entity_declarations(
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    escaped = tmp_path / "escaped.sdf"
    escaped.write_text("<sdf/>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside its trusted local root"):
        wrapper._parse_trusted_local_xml(
            escaped,
            trusted_root=trusted_root,
            context="test XML",
        )

    malicious = trusted_root / "malicious.sdf"
    malicious.write_text(
        '<!DOCTYPE sdf [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><sdf>&xxe;</sdf>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="forbidden DTD or entity declaration"):
        wrapper._parse_trusted_local_xml(
            malicious,
            trusted_root=trusted_root,
            context="test XML",
        )


def test_bounded_xml_text_rejects_oversize_and_entity_declarations() -> None:
    with pytest.raises(RuntimeError, match="exceeds the XML evidence limit"):
        wrapper._parse_bounded_xml_text(
            "<sdf/>",
            byte_limit=1,
            context="generated XML",
        )

    with pytest.raises(RuntimeError, match="forbidden DTD or entity declaration"):
        wrapper._parse_bounded_xml_text(
            '<!ENTITY payload "untrusted"><sdf/>',
            byte_limit=1024,
            context="generated XML",
        )


def test_steady_wind_overlay_is_trial_local_and_prepended_to_gazebo_paths(
    tmp_path: Path,
) -> None:
    request = _wind_request()
    px4_root = _minimal_px4_gazebo_tree(tmp_path)
    launch_env = {"GZ_SIM_RESOURCE_PATH": "/existing"}

    overlay = wrapper._prepare_steady_wind_overlay(
        request,
        scenario_effects,
        run_dir=tmp_path / "run",
        autopilot_dir=str(px4_root),
        simulator_model="gz_x500",
        world="default",
        launch_env=launch_env,
    )

    assert overlay is not None
    model_tree = wrapper.ET.parse(overlay["model_sdf_path"])
    assert (
        model_tree.findtext("./model[@name='x500_base']/link[@name='base_link']/enable_wind")
        == "true"
    )
    assert model_tree.find(".//material/script") is None
    assert model_tree.findtext(".//material/ambient") == "0.2 0.2 0.2 1"
    assert overlay["sanitized_classic_material_scripts"] == 1
    world_tree = wrapper.ET.parse(overlay["world_sdf_path"])
    plugin = world_tree.find(
        f"./world[@name='default']/plugin[@name='{wrapper.WIND_EFFECTS_PLUGIN_NAME}']"
    )
    assert plugin is not None
    assert plugin.get("filename") == wrapper.WIND_EFFECTS_PLUGIN_FILENAME
    physics_plugin = world_tree.find(
        "./world[@name='default']/plugin[@name='gz::sim::systems::Physics']"
    )
    user_commands_plugin = world_tree.find(
        "./world[@name='default']/plugin[@name='gz::sim::systems::UserCommands']"
    )
    scene_broadcaster_plugin = world_tree.find(
        "./world[@name='default']/plugin[@name='gz::sim::systems::SceneBroadcaster']"
    )
    assert physics_plugin is not None
    assert user_commands_plugin is not None
    assert scene_broadcaster_plugin is not None
    assert physics_plugin.get("entity_name") is None
    assert physics_plugin.get("entity_type") is None
    assert len(overlay["materialized_px4_system_plugins"]) == 3
    assert len(overlay["px4_server_config_sha256"]) == 64
    assert world_tree.findtext("./world[@name='default']/wind/linear_velocity")
    resource_paths = launch_env["GZ_SIM_RESOURCE_PATH"].split(os.pathsep)
    assert Path(resource_paths[0]).parts[-2:] == ("scenario_runtime", "models")
    assert Path(resource_paths[1]).parts[-2:] == ("scenario_runtime", "worlds")
    assert resource_paths[2] == "/existing"
    trial_rootfs = Path(overlay["px4_trial_rootfs_path"])
    assert (trial_rootfs / "gz_env.sh").is_file()
    assert not (trial_rootfs / "parameters.bson").exists()
    assert not (trial_rootfs / "dataman").exists()
    assert not (trial_rootfs / "log").exists()
    trial_env = (trial_rootfs / "gz_env.sh").read_text(encoding="utf-8")
    trial_worlds = str(tmp_path / "run" / "scenario_runtime" / "worlds")
    trial_models = str(tmp_path / "run" / "scenario_runtime" / "models")
    assert trial_worlds in trial_env
    assert f"export PX4_GZ_MODELS={shlex.quote(trial_models)}" in trial_env
    assert Path(overlay["vehicle_model_sdf_path"]).is_file()


def test_advanced_sdf_overlay_binds_trial_local_top_level_model(tmp_path: Path) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "advanced-overlay", "seed": 42},
        scenario_type="actuator_delay",
        scenario_config={"delay_ms": 80.0},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "high",
        },
        advanced_config={
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 4.0,
                "direction_deg": 90.0,
                "period_s": 8.0,
            },
            "sensor_degradation": {
                "gps_noise_m": 2.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.5,
            },
            "battery": {"mass_payload_kg": 1.2},
        },
    )
    px4_root = _minimal_px4_gazebo_tree(tmp_path)
    overlay = wrapper._prepare_steady_wind_overlay(
        request,
        scenario_effects,
        run_dir=tmp_path / "run",
        autopilot_dir=str(px4_root),
        simulator_model="x500",
        world="default",
        launch_env={},
    )

    assert overlay is not None
    vehicle_path = Path(overlay["vehicle_model_sdf_path"])
    assert vehicle_path.parts[-3:] == ("models", "x500", "model.sdf")
    vehicle_tree = ET.parse(vehicle_path)
    motor_plugins = vehicle_tree.findall(
        "./model[@name='x500']/plugin[@name='gz::sim::systems::MulticopterMotorModel']"
    )
    assert len(motor_plugins) == 4
    for plugin in motor_plugins:
        assert plugin.findtext("timeConstantUp") == "0.080000000000000002"
        assert plugin.findtext("timeConstantDown") == "0.080000000000000002"
    trial_env = Path(overlay["px4_trial_gz_env_path"]).read_text(encoding="utf-8")
    expected_models = shlex.quote(str(vehicle_path.parents[1]))
    assert f"export PX4_GZ_MODELS={expected_models}" in trial_env


def test_steady_wind_overlay_accepts_exact_collinear_gust_superposition(
    tmp_path: Path,
) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "collinear-gust", "seed": 42},
        scenario_type="wind_perturbed",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 2.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 4.0,
                "direction_deg": 90.0,
                "period_s": 12.0,
            }
        },
    )
    px4_root = _minimal_px4_gazebo_tree(tmp_path)

    overlay = wrapper._prepare_steady_wind_overlay(
        request,
        scenario_effects,
        run_dir=tmp_path / "run",
        autopilot_dir=str(px4_root),
        simulator_model="x500",
        world="default",
        launch_env={},
    )

    assert overlay is not None
    gust = overlay["compiled_sdf_profile"]["wind_gust"]
    assert gust["mean_linear_velocity_mps"] == {"x": 4.0, "y": 0.0, "z": 0.0}
    assert gust["horizontal_magnitude_sine_amplitude_percent"] == 0.5
    assert gust["range_mps"] == [2.0, 6.0]
    world_tree = ET.parse(overlay["world_sdf_path"])
    plugin = world_tree.find(
        "./world[@name='default']/plugin[@name='gz::sim::systems::WindEffects']"
    )
    assert plugin is not None
    assert (
        float(plugin.findtext("./horizontal/magnitude/sin/amplitude_percent", default="nan")) == 0.5
    )


def test_actuator_failure_sdf_and_joint_state_prove_one_hard_stopped_motor(
    tmp_path: Path,
) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "actuator-failure", "seed": 42},
        scenario_type="actuator_failure",
        scenario_config={
            "motor_number": 2,
            "failure_mode": "stuck_stopped_at_launch",
        },
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    profile = compile_bundled_sdf_profile(request)
    assert profile is not None
    px4_root = _minimal_px4_gazebo_tree(tmp_path)
    overlay = wrapper._prepare_steady_wind_overlay(
        request,
        scenario_effects,
        run_dir=tmp_path / "run",
        autopilot_dir=str(px4_root),
        simulator_model="x500",
        world="default",
        launch_env={},
    )

    assert overlay is not None
    applied = overlay["applied_sdf_profile"]
    failure = applied["actuator_failure"]
    assert failure["target_motor_number"] == 2
    assert failure["failure_mode"] == "stuck_stopped_at_launch"
    vehicle_tree = ET.parse(Path(overlay["vehicle_model_sdf_path"]))
    source_vehicle = vehicle_tree.find("./model[@name='x500']")
    assert source_vehicle is not None
    motor_maxima = {
        int(plugin.findtext("motorNumber", default="-1")): float(
            plugin.findtext("maxRotVelocity", default="nan")
        )
        for plugin in source_vehicle.findall(
            "./plugin[@name='gz::sim::systems::MulticopterMotorModel']"
        )
    }
    assert motor_maxima == {0: 1000.0, 1: 1000.0, 2: 0.0, 3: 1000.0}
    publisher = source_vehicle.find("./plugin[@name='gz::sim::systems::JointStatePublisher']")
    assert publisher is not None
    assert publisher.findtext("topic") == profile["actuator_failure"]["joint_state_topic"]
    assert [item.text for item in publisher.findall("joint_name")] == [
        "rotor_0_joint",
        "rotor_1_joint",
        "rotor_2_joint",
        "rotor_3_joint",
    ]

    base_tree = ET.parse(Path(overlay["model_sdf_path"]))
    base_link = base_tree.find("./model[@name='x500_base']/link[@name='base_link']")
    assert base_link is not None
    runtime_root = ET.Element("sdf", {"version": "1.9"})
    world = ET.SubElement(runtime_root, "world", {"name": "default"})
    runtime_model = ET.SubElement(world, "model", {"name": "x500_0"})
    runtime_model.append(copy.deepcopy(base_link))
    for plugin in source_vehicle.findall("plugin"):
        runtime_model.append(copy.deepcopy(plugin))
    runtime_observation = wrapper._runtime_sdf_profile_observation(
        ET.tostring(runtime_root, encoding="unicode"),
        generated_path=tmp_path / "generated_actuator_failure.sdf",
        expected_vehicle_model="x500_0",
        applied_sdf_profile=applied,
        require_wind_mode=False,
    )
    assert runtime_observation["verified_profile_sections"] == ["actuator_failure"]

    raw_path = tmp_path / "run" / "actuator_failure_joint_state.log"
    raw_path.write_text(
        """
name: "x500_0"
joint { name: "rotor_0_joint" axis1 { velocity: 62.5 } }
joint { name: "rotor_1_joint" axis1 { velocity: -61.25 } }
joint { name: "rotor_2_joint" axis1 { velocity: 0 } }
joint { name: "rotor_3_joint" axis1 { velocity: -63.75 } }
joint { name: "rotor_0_joint" axis1 { velocity: 70 } }
joint { name: "rotor_1_joint" axis1 { velocity: -69 } }
joint { name: "rotor_2_joint" axis1 { velocity: 0 } }
joint { name: "rotor_3_joint" axis1 { velocity: -68 } }
""".strip(),
        encoding="utf-8",
    )
    joint_observation = wrapper._parse_actuator_failure_joint_state(
        raw_path.read_text(encoding="utf-8"),
        profile["actuator_failure"],
        raw_path=raw_path,
    )
    assert joint_observation["target_max_abs_velocity_rad_s"] == 0.0
    assert joint_observation["healthy_motion_verified"] is True

    effect = request["effects"][0]
    runtime_sdf_item = {
        "source": "/world/default/generate_world_sdf",
        "kind": "artifact",
        "value": runtime_observation,
        "sha256": scenario_effects.scenario_effect_value_sha256(runtime_observation),
    }
    record = wrapper._scenario_effect_record(
        effect,
        status="applied",
        capability_status="available",
        reason="test",
        evidence={
            "requested_value_sha256": (
                scenario_effects.scenario_effect_value_sha256(effect["requested_value"])
            ),
            "compiled_sdf_profile": profile,
            "verification": {
                "status": "verified",
                "method": "trial_local_sdf_and_generated_world_sdf",
                "observations": [runtime_sdf_item],
            },
        },
    )
    wrapper._augment_actuator_failure_record(
        record,
        joint_observation,
        scenario_effects,
        topic=profile["actuator_failure"]["joint_state_topic"],
    )
    evidence = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=[record],
    )
    assert (
        validate_scenario_effect_evidence(request, evidence)["verification_status"]
        == "verified_applied"
    )


@pytest.mark.parametrize(
    ("target_velocity", "healthy_velocity", "message"),
    [
        (0.1, 10.0, "failed rotor exceeded"),
        (0.0, 0.5, "healthy rotors did not all exceed"),
    ],
)
def test_actuator_failure_joint_state_fails_closed(
    tmp_path: Path,
    target_velocity: float,
    healthy_velocity: float,
    message: str,
) -> None:
    profile = {
        "failure_mode": "stuck_stopped_at_launch",
        "failure_start": "launch",
        "target_motor_number": 0,
        "target_joint_name": "rotor_0_joint",
        "max_failed_motor_abs_velocity_rad_s": 0.05,
        "min_healthy_motor_abs_velocity_rad_s": 1.0,
    }
    raw_path = tmp_path / "joint_state.log"
    raw_path.write_text(
        "\n".join(
            [
                f'joint {{ name: "rotor_0_joint" axis1 {{ velocity: {target_velocity} }} }}',
                f'joint {{ name: "rotor_1_joint" axis1 {{ velocity: {healthy_velocity} }} }}',
                f'joint {{ name: "rotor_2_joint" axis1 {{ velocity: {healthy_velocity} }} }}',
                f'joint {{ name: "rotor_3_joint" axis1 {{ velocity: {healthy_velocity} }} }}',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match=message):
        wrapper._parse_actuator_failure_joint_state(
            raw_path.read_text(encoding="utf-8"),
            profile,
            raw_path=raw_path,
        )


def test_trial_wind_world_launches_from_clean_rootfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial_rootfs = tmp_path / "scenario_runtime" / "px4_rootfs"
    executable = tmp_path / "PX4-Autopilot" / "build" / "px4_sitl_default" / "bin" / "px4"
    trial_rootfs.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.write_text("px4", encoding="utf-8")
    launch_env: dict[str, str] = {}
    monkeypatch.delenv("PX4_LAUNCH_COMMAND_TEMPLATE", raising=False)

    command = wrapper._wrap_launch_command_for_trial_world(
        "cd /opt/PX4-Autopilot; HEADLESS=1 make px4_sitl gz_x500",
        {
            "px4_trial_rootfs_path": str(trial_rootfs),
            "px4_executable_path": str(executable),
            "px4_sim_model": "gz_x500",
        },
        launch_env=launch_env,
        headless=True,
    )

    assert "PX4_GZ_STANDALONE" not in launch_env
    assert launch_env["GZ_IP"] == "127.0.0.1"
    assert str(trial_rootfs.resolve()) in command
    assert "HEADLESS=1" in command
    assert "PX4_SIM_MODEL=gz_x500" in command
    assert str(executable.resolve()) in command
    quoted_rootfs = shlex.quote(str(trial_rootfs.resolve()))
    assert f"-d -w {quoted_rootfs} {quoted_rootfs}" in command
    assert "make px4_sitl" not in command


def test_trial_wind_world_refuses_unverifiable_custom_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_sdf = tmp_path / "default.sdf"
    world_sdf.write_text("<sdf version='1.9'/>", encoding="utf-8")
    monkeypatch.setenv("PX4_LAUNCH_COMMAND_TEMPLATE", "custom-launch")

    with pytest.raises(
        wrapper.ScenarioEffectUnsupportedError,
        match="custom PX4_LAUNCH_COMMAND_TEMPLATE",
    ):
        wrapper._wrap_launch_command_for_trial_world(
            "custom-launch",
            {"world_sdf_path": str(world_sdf)},
            launch_env={},
            headless=True,
        )


def test_steady_wind_application_requires_readback_and_runtime_sdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _wind_request()
    compiled = compile_bundled_steady_wind(request)
    assert compiled is not None
    generated_sdf = """
<sdf version="1.9">
  <world name="default">
    <model name="x500_0">
      <link name="base_link"><enable_wind>true</enable_wind></link>
    </model>
  </world>
</sdf>
""".strip()
    world_before_vehicle_spawn = '<sdf version="1.9"><world name="default"></world></sdf>'
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout=("/world/default/wind_info\n/world/default/generate_world_sdf\n"),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=("linear_velocity {\n  x: 0\n  y: 0\n  z: 0\n}\nenable_wind: true\n"),
            stderr="",
        ),
        SimpleNamespace(
            returncode=0,
            stdout=f"data: {json.dumps(world_before_vehicle_spawn)}\n",
            stderr="",
        ),
        SimpleNamespace(
            returncode=0,
            stdout=f"data: {json.dumps(generated_sdf)}\n",
            stderr="",
        ),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(wrapper, "_gazebo_cli", lambda: "/usr/bin/gz")
    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(wrapper.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("PX4_GAZEBO_WIND_READBACK_ATTEMPTS", "1")
    monkeypatch.setenv("PX4_GAZEBO_RUNTIME_SDF_ATTEMPTS", "2")

    records = wrapper._apply_steady_wind_effects(
        request,
        scenario_effects,
        _overlay_stub(request, tmp_path),
        run_dir=tmp_path / "run",
        world="default",
    )

    assert set(records) == {"job_config.wind", "scenario_config.wind_mps"}
    assert all(record["_activation_pending"] is True for record in records.values())
    runtime_records: dict[str, dict] = {}
    for effect in request["effects"]:
        effect_id = effect["effect_id"]
        runtime_records[effect_id] = {
            "effect_id": effect_id,
            "mechanism": effect["mechanism"],
            "status": "applied",
            "capability": {"status": "available", "reason": "post-hover wind verified"},
            "evidence": {
                "requested_value_sha256": scenario_effects.scenario_effect_value_sha256(
                    effect["requested_value"]
                ),
                "compiled_runtime_profile": scenario_effects.compile_bundled_runtime_profile(
                    request
                ),
                "verification": {
                    "status": "verified",
                    "method": "gazebo_wind_topic_after_stable_hover_and_exact_readback",
                    "observations": [
                        {
                            "source": "/world/default/wind_info",
                            "kind": "readback",
                            "value": {
                                "linear_velocity_mps": compiled["linear_velocity_mps"],
                                "enable_wind": True,
                            },
                        },
                        {
                            "source": "/world/default/wind",
                            "kind": "acknowledgement",
                            "value": {
                                "phase": "after_stable_hover_before_track_entry",
                                "activation_t_s": 1.25,
                            },
                        },
                    ],
                },
            },
        }
    merged = wrapper._merge_staged_wind_effect_records(
        scenario_effects,
        records,
        runtime_records,
    )
    payload = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=[merged[effect["effect_id"]] for effect in request["effects"]],
    )
    normalized = validate_scenario_effect_evidence(request, payload)
    assert normalized["verification_status"] == "verified_applied"
    assert (tmp_path / "run" / "scenario_runtime" / "generated_world.sdf").is_file()
    assert (tmp_path / "run" / "scenario_runtime" / "generated_world.last_attempt.sdf").is_file()
    assert commands[1][1:3] == ["topic", "-t"]
    assert "gz.msgs.Empty" in commands[2]
    assert "gz.msgs.SdfGeneratorConfig" in commands[3]
    assert "expand_include_tags" in commands[3][-1]
    assert "gz.msgs.SdfGeneratorConfig" in commands[4]


def test_steady_wind_application_rejects_mismatched_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _wind_request()
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout="/world/default/wind_info\n/world/default/generate_world_sdf\n",
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=("linear_velocity { x: 99 y: 0 z: 0 }\nenable_wind: true\n"),
            stderr="",
        ),
    ]

    monkeypatch.setattr(wrapper, "_gazebo_cli", lambda: "/usr/bin/gz")
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *_args, **_kwargs: responses.pop(0))
    monkeypatch.setenv("PX4_GAZEBO_WIND_READBACK_ATTEMPTS", "1")

    with pytest.raises(RuntimeError, match="never proved the zero-wind takeoff profile"):
        wrapper._apply_steady_wind_effects(
            request,
            scenario_effects,
            _overlay_stub(request, tmp_path),
            run_dir=tmp_path / "run",
            world="default",
        )


def test_pending_wind_activation_is_not_reported_as_applied_after_earlier_failure() -> None:
    request = _wind_request()
    preliminary = {
        effect["effect_id"]: {
            "effect_id": effect["effect_id"],
            "mechanism": effect["mechanism"],
            "status": "applied",
            "capability": {"status": "available", "reason": "zero-wind preflight"},
            "_activation_pending": True,
        }
        for effect in request["effects"]
    }

    records = wrapper._scenario_effect_failure_records(
        request,
        applied_by_id=preliminary,
        failing_ids=set(),
        reason="another effect failed before takeoff",
        unsupported=False,
    )

    assert all(record["status"] == "skipped" for record in records)
    assert all("_activation_pending" not in record for record in records)


def test_pre_executor_validation_accepts_staged_wind_prerequisite_records() -> None:
    request = _wind_request()
    staged_ids = {effect["effect_id"] for effect in request["effects"]}

    wrapper._validate_pre_executor_effect_records(
        scenario_effects,
        {effect_id: {"_activation_pending": True} for effect_id in staged_ids},
        expected_preflight_ids=set(),
        runtime_effect_ids=staged_ids,
    )


def test_pre_executor_validation_reports_unexpected_records() -> None:
    with pytest.raises(RuntimeError, match=r"unexpected=unrelated\.effect"):
        wrapper._validate_pre_executor_effect_records(
            scenario_effects,
            {"unrelated.effect": {}},
            expected_preflight_ids=set(),
            runtime_effect_ids=set(),
        )


def test_site_dry_run_writes_explicit_unphysical_effect_evidence(
    tmp_path: Path,
) -> None:
    args = _make_args(tmp_path)
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "t"},
        scenario_type="nominal",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "obstacles": [_obstacle_effect()["requested_value"][0]],
        },
    )
    request_path = tmp_path / "effect-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    evidence_path = tmp_path / "run" / EVIDENCE_ARTIFACT_NAME
    env = os.environ.copy()
    env.update(
        {
            "PX4_SITE_DRY_RUN": "true",
            "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH": str(request_path),
            "PX4_TRIAL_SCENARIO_EFFECT_EVIDENCE_PATH": str(evidence_path),
        }
    )

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    normalized = validate_scenario_effect_evidence(request, payload)
    assert normalized["unsupported_effects"] == ["obstacles"]
    assert "fixture telemetry" in payload["effects"][0]["reason"]


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_wrapper_rejects_non_finite_environment_numbers(raw: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        wrapper._parse_float(raw, default=1.0)


def test_track_marker_timeout_is_bounded_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = SimpleNamespace(run_dir=run_dir, stdout_log=run_dir / "stdout.log")
    stderr_log = run_dir / "stderr.log"
    monkeypatch.setattr(wrapper, "_build_track_marker_command", lambda _args: "marker")

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("marker", 1, output="partial", stderr="late")

    monkeypatch.setattr(wrapper.subprocess, "run", timeout)
    monkeypatch.setenv("PX4_GAZEBO_TRACK_MARKER_PROCESS_TIMEOUT_SECONDS", "1")

    assert wrapper._run_track_marker(args, stderr_log) == 124
    assert (run_dir / "track_marker_stdout.log").read_text() == "partial"
    assert "timed out" in stderr_log.read_text()


def test_offboard_timeout_is_bounded_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = SimpleNamespace(run_dir=run_dir, stdout_log=run_dir / "stdout.log")
    stderr_log = run_dir / "stderr.log"
    monkeypatch.setattr(wrapper, "_build_offboard_executor_argv", lambda _args: ["offboard"])

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("offboard", 30)

    monkeypatch.setattr(wrapper.subprocess, "run", timeout)
    monkeypatch.setenv("PX4_OFFBOARD_PROCESS_TIMEOUT_SECONDS", "30")

    assert wrapper._run_offboard_executor(args, stderr_log) == 124
    assert "timed out" in stderr_log.read_text()


@pytest.mark.parametrize(
    ("configured_ip", "expected_ip"),
    [(None, "127.0.0.1"), ("127.0.0.2", "127.0.0.2")],
)
def test_offboard_executor_shares_gazebo_transport_interface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_ip: str | None,
    expected_ip: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = SimpleNamespace(run_dir=run_dir, stdout_log=run_dir / "stdout.log")
    stderr_log = run_dir / "stderr.log"
    monkeypatch.setattr(wrapper, "_build_offboard_executor_argv", lambda _args: ["offboard"])
    monkeypatch.setenv("GZ_PARTITION", "dronedream_test_partition")
    if configured_ip is None:
        monkeypatch.delenv("GZ_IP", raising=False)
    else:
        monkeypatch.setenv("GZ_IP", configured_ip)
    captured_env: dict[str, str] = {}

    def complete(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(["offboard"], 0, stdout="", stderr="")

    monkeypatch.setattr(wrapper.subprocess, "run", complete)

    assert wrapper._run_offboard_executor(args, stderr_log) == 0
    assert captured_env["GZ_IP"] == expected_ip
    assert captured_env["GZ_PARTITION"] == "dronedream_test_partition"


def test_json_and_normalized_telemetry_limits_fail_before_unbounded_processing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b" " * 32 + b"}")
    monkeypatch.setattr(wrapper, "MAX_JSON_BYTES", 16)
    with pytest.raises(ValueError, match="exceeds"):
        wrapper._json_load(oversized)

    monkeypatch.setattr(wrapper, "MAX_TELEMETRY_SAMPLES", 1)
    payload = _basic_telemetry()
    payload["samples"].append(dict(payload["samples"][0], t=1.0))
    with pytest.raises(ValueError, match="sample contract limit"):
        wrapper._normalize_telemetry_payload(payload)


def test_wrapper_real_mode_ulog_uses_px4_ulog_path(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("print('ok')\n", encoding="utf-8")
    ulog_path = tmp_path / "specific.ulg"
    ulog_path.write_text("placeholder", encoding="utf-8")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_TELEMETRY_MODE"] = "ulog"
    env["PX4_ULOG_PATH"] = str(ulog_path)
    env["PYTHONPATH"] = str(tmp_path)
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"

    fake_pyulog = tmp_path / "pyulog.py"
    fake_pyulog.write_text(
        "class DS:\n"
        "    def __init__(self, name, data):\n"
        "        self.name=name\n"
        "        self.data=data\n"
        "class ULog:\n"
        "    def __init__(self, _path):\n"
        "        self.data_list=[\n"
        "            DS('vehicle_local_position', {\n"
        "                'timestamp':[1000000], 'x':[0.0], 'y':[0.0],\n"
        "                'z':[-3.0], 'vx':[0.0], 'vy':[0.0], 'vz':[0.0]\n"
        "            }),\n"
        "            DS('vehicle_attitude_groundtruth', {\n"
        "                'q[0]':[1.0], 'q[1]':[0.0], 'q[2]':[0.0], 'q[3]':[0.0]\n"
        "            })\n"
        "        ]\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    telemetry = json.loads((tmp_path / "run" / "telemetry.json").read_text(encoding="utf-8"))
    retained_ulog = tmp_path / "run" / wrapper.RETAINED_ULOG_NAME
    assert retained_ulog.read_bytes() == b"placeholder"
    assert telemetry["meta"]["ulog_path"] == str(retained_ulog)


def test_wrapper_real_mode_ulog_missing_log_fails_with_clear_message(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("print('ok')\n", encoding="utf-8")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_TELEMETRY_MODE"] = "ulog"
    ulog_root = tmp_path / "ulog_root"
    historical = ulog_root / "old" / "historical.ulg"
    historical.parent.mkdir(parents=True)
    historical.write_text("stale", encoding="utf-8")
    env["PX4_ULOG_ROOT"] = str(ulog_root)
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "No new or changed ULog files were produced by this PX4 run" in stderr_text


def test_px4_runner_can_call_local_wrapper_in_site_dry_run(tmp_path: Path):
    trial_input = {
        "trial_id": "trial-1",
        "job_id": "job-1",
        "candidate_id": "cand-1",
        "seed": 1,
        "scenario_type": "nominal",
        "scenario_config": {},
        "vehicle_profile": {
            "px4_version": "v1.17",
            "vehicle_type": "multicopter",
            "airframe": "quad_x",
            "simulator_model": "gz_x500_depth",
            "world": "warehouse",
        },
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
    input_path = _write_json(tmp_path / "trial_input.json", trial_input)
    output_path = tmp_path / "trial_result.json"

    launch_command = (
        f"{sys.executable} {WRAPPER} "
        "--run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} "
        "--telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} "
        "--vehicle {vehicle} --world {world} --headless {headless}"
    )

    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "false"
    env["PX4_GAZEBO_LAUNCH_COMMAND"] = launch_command
    env["PX4_SITE_DRY_RUN"] = "true"

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
    assert result["metrics"]["raw_metric_json"]["mode"] == "real"
    launch_config = json.loads((tmp_path / "launch_config.json").read_text(encoding="utf-8"))
    assert launch_config["airframe"] == "quad_x"
    assert launch_config["simulator_model"] == "gz_x500_depth"
    assert launch_config["world"] == "warehouse"
    assert launch_config["px4_version"] == "v1.17"
    assert launch_config["make_target"] == "gz_x500_depth"


def test_wrapper_real_mode_without_offboard_executor_preserves_behavior(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\nprint('launched')\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "telemetry.json").exists()


def test_wrapper_routes_profile_tokens_and_world_to_real_launcher(tmp_path: Path):
    profile_dump = tmp_path / "profile.json"
    launcher = tmp_path / "profile_launcher.py"
    launcher.write_text(
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(profile_dump)!r}).write_text(json.dumps(dict("
        "argv=sys.argv, world_env=os.environ.get('PX4_GZ_WORLD'))), encoding='utf-8')\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _make_args(tmp_path)
    args[args.index("--vehicle") + 1] = "gz_x500_depth"
    args[args.index("--world") + 1] = "warehouse"
    args.extend(
        [
            "--airframe",
            "quad_x",
            "--simulator-model",
            "gz_x500_depth",
            "--px4-version",
            "v1.17",
        ]
    )
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = (
        f"{sys.executable} {launcher} --airframe {{airframe}} "
        "--model {simulator_model} --version {px4_version} --world {world}"
    )
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_MAKE_TARGET"] = "gz_x500"
    env.pop("PX4_FORCE_MAKE_TARGET", None)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    profile = json.loads(profile_dump.read_text(encoding="utf-8"))
    assert profile["world_env"] == "warehouse"
    argv = profile["argv"]
    assert argv[argv.index("--airframe") + 1] == "quad_x"
    assert argv[argv.index("--model") + 1] == "gz_x500_depth"
    assert argv[argv.index("--version") + 1] == "v1.17"
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["make_target"] == "gz_x500_depth"
    assert launch_config["px4_version"] == "v1.17"


def test_wrapper_offboard_executor_invoked_while_px4_running(tmp_path: Path):
    pid_file = tmp_path / "px4.pid"
    marker_file = tmp_path / "run" / "executor_ok.txt"
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib,time,os\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    executor_script = tmp_path / "executor.py"
    executor_script.write_text(
        "import os,sys,pathlib,time\n"
        f"pid_path=pathlib.Path({str(pid_file)!r})\n"
        "for _ in range(50):\n"
        "    if pid_path.exists():\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "if not pid_path.exists():\n"
        "    sys.exit(4)\n"
        "pid=int(pid_path.read_text(encoding='utf-8').strip())\n"
        "if os.name == 'nt':\n"
        "    import ctypes\n"
        "    handle=ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)\n"
        "    alive=bool(handle)\n"
        "    if handle:\n"
        "        ctypes.windll.kernel32.CloseHandle(handle)\n"
        "else:\n"
        "    alive=True\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "    except OSError:\n"
        "        alive=False\n"
        "marker=pathlib.Path(sys.argv[sys.argv.index('--log')+1]).with_name('executor_ok.txt')\n"
        "marker.write_text('alive' if alive else 'dead', encoding='utf-8')\n"
        "log_path = pathlib.Path(sys.argv[sys.argv.index('--log')+1])\n"
        "log_path.write_text('executor ran\\n', encoding='utf-8')\n"
        "sys.exit(0 if alive else 3)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "true"
    env["PX4_OFFBOARD_EXECUTOR_COMMAND"] = f"{sys.executable} {executor_script}"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert marker_file.read_text(encoding="utf-8") == "alive"
    assert (tmp_path / "run" / "offboard_executor.log").exists()


def test_wrapper_windows_cleanup_timeout_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"killed": False}

    def timeout_taskkill(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd="taskkill",
            timeout=wrapper.WINDOWS_PROCESS_TREE_TERMINATION_TIMEOUT_SECONDS,
        )

    fake_proc = SimpleNamespace(
        pid=12345,
        poll=lambda: None,
        kill=lambda: state.__setitem__("killed", True),
        wait=lambda timeout: None,
    )
    stderr_log = tmp_path / "stderr.log"
    monkeypatch.setattr(wrapper.os, "name", "nt")
    monkeypatch.setattr(wrapper.subprocess, "run", timeout_taskkill)

    wrapper._terminate_process_group(
        fake_proc,
        stderr_log,
        label="PX4",
    )

    assert state["killed"] is True
    assert "Timed out terminating PX4 process tree" in stderr_log.read_text(encoding="utf-8")


def test_wrapper_offboard_executor_failure_exits_non_zero(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\nprint('launched')\ntime.sleep(30)\n", encoding="utf-8")
    bad_executor = tmp_path / "bad_executor.py"
    bad_executor.write_text(
        "import sys\nprint('boom', file=sys.stderr)\nsys.exit(9)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "true"
    env["PX4_OFFBOARD_EXECUTOR_COMMAND"] = f"{sys.executable} {bad_executor}"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "offboard executor failed" in stderr_text


def test_failed_runtime_effect_records_remain_valid_launcher_evidence(tmp_path: Path) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "trial-runtime-failure"},
        scenario_type="nominal",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "battery": {"initial_percent": 75.0, "voltage_sag": True},
        },
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    reason = "takeoff did not reach a continuously stable hover"
    records = [
        wrapper._scenario_effect_record(
            effect,
            status="failed",
            capability_status="available",
            reason=reason,
        )
        for effect in request["effects"]
    ]
    (tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME).write_text(
        json.dumps(
            {
                "schema_version": "dronedream.scenario_runtime_effects.v1",
                "request_sha256": request["request_sha256"],
                "compiled_runtime_profile": profile,
                "status": "failed",
                "error": reason,
                "records": records,
            }
        ),
        encoding="utf-8",
    )

    loaded = wrapper._load_runtime_effect_records(
        scenario_effects,
        request,
        run_dir=tmp_path,
    )
    payload = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="local_px4_launch_wrapper",
        world="default",
        effects=[loaded[effect["effect_id"]] for effect in request["effects"]],
    )
    normalized = validate_scenario_effect_evidence(request, payload)
    assert normalized["verification_status"] == "failed"
    assert normalized["failed_effects"] == [
        "battery.initial_percent",
        "battery.voltage_sag",
    ]


def test_skipped_runtime_effect_records_preserve_pre_activation_failure(
    tmp_path: Path,
) -> None:
    request = build_scenario_effect_request(
        execution_identity={"trial_id": "trial-runtime-pre-activation-failure"},
        scenario_type="nominal",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "battery": {"initial_percent": 75.0, "voltage_sag": True},
        },
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    reason = "flight terminated before battery activation: takeoff stability timeout"
    records = [
        wrapper._scenario_effect_record(
            effect,
            status="skipped",
            capability_status="available",
            reason=reason,
        )
        for effect in request["effects"]
    ]
    (tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME).write_text(
        json.dumps(
            {
                "schema_version": "dronedream.scenario_runtime_effects.v1",
                "request_sha256": request["request_sha256"],
                "compiled_runtime_profile": profile,
                "attempted_sections": [],
                "status": "failed",
                "error": "TimeoutError: takeoff stability timeout",
                "records": records,
            }
        ),
        encoding="utf-8",
    )

    loaded = wrapper._load_runtime_effect_records(
        scenario_effects,
        request,
        run_dir=tmp_path,
    )
    payload = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="local_px4_launch_wrapper",
        world="default",
        effects=[loaded[effect["effect_id"]] for effect in request["effects"]],
    )
    normalized = validate_scenario_effect_evidence(request, payload)
    assert normalized["verification_status"] == "failed"
    assert normalized["failed_effects"] == []
    assert normalized["unsupported_effects"] == []
    assert normalized["skipped_effects"] == [
        "battery.initial_percent",
        "battery.voltage_sag",
    ]


def test_wrapper_headless_true_does_not_launch_gui_client(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.4)\n", encoding="utf-8")
    gui_marker = tmp_path / "run" / "gui_invoked.txt"
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        f"import pathlib\npathlib.Path({str(gui_marker)!r}).write_text('yes', encoding='utf-8')\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "true")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} {gui_script}"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert not gui_marker.exists()
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "Track marker not launched: headless=true" in wrapper_stdout


def test_wrapper_non_headless_launches_gui_client_and_writes_logs_and_launch_config(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        "import pathlib,time\n"
        "run_dir=pathlib.Path(__file__).resolve().parent / 'run'\n"
        "(run_dir / 'gui_started.txt').write_text('started', encoding='utf-8')\n"
        "print('gui-stdout-line')\n"
        "print('gui-stderr-line', file=__import__('sys').stderr)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "0.2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "gui_stdout.log").exists()
    assert (tmp_path / "run" / "gui_stderr.log").exists()
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["gui_client_enabled"] is True
    assert launch_config["gui_command"] == f"{sys.executable} {gui_script}"
    assert "gui_stdout_log" in launch_config["paths"]
    assert "gui_stderr_log" in launch_config["paths"]


def test_wrapper_gui_failure_is_non_fatal_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.4)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = "command_that_does_not_exist_12345"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "gui_stderr.log").exists()


def test_wrapper_terminates_gui_process_on_exit(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        "import time\nprint('gui-started')\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "0.2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "GUI client launch command" in wrapper_stdout
    assert "Sent SIGTERM to GUI process group" in wrapper_stderr


def test_wrapper_non_headless_track_marker_disabled_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "false"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "Track marker not launched" in wrapper_stdout
    assert "PX4_GAZEBO_DRAW_TRACK_MARKER=false" in wrapper_stdout
    assert not (tmp_path / "run" / "track_marker_stdout.log").exists()


def test_wrapper_non_headless_track_marker_runs_and_writes_logs(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    marker = tmp_path / "marker.py"
    marker.write_text("print('marker-ok')\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} {marker}"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "track_marker_stdout.log").exists()
    assert (tmp_path / "run" / "track_marker_stderr.log").exists()
    marker_stdout = (tmp_path / "run" / "track_marker_stdout.log").read_text(encoding="utf-8")
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "marker-ok" in marker_stdout
    assert "Track marker command" in wrapper_stdout
    assert "Track marker exit code: 0" in wrapper_stdout
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["track_marker_enabled"] is True
    assert launch_config["track_marker_command"] == f"{sys.executable} {marker}"
    assert launch_config["track_marker_require"] is False
    assert "track_marker_stdout_log" in launch_config["paths"]
    assert "track_marker_stderr_log" in launch_config["paths"]


def test_wrapper_track_marker_failure_non_fatal_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f'{sys.executable} -c "import sys; sys.exit(9)"'

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "WARNING: track marker failed" in wrapper_stderr


def test_wrapper_track_marker_failure_fatal_when_required(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_REQUIRE_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f'{sys.executable} -c "import sys; sys.exit(6)"'

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "PX4_GAZEBO_REQUIRE_TRACK_MARKER=true" in wrapper_stderr
