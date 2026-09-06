#!/usr/bin/env python3
"""Exercise School Map collision geometry in a real Gazebo server.

The canonical mission proves that the qualified route is collision free.  This
acceptance runner proves the opposite side of the safety contract: deliberately
driven vehicle-sized probes must make physical contact with a wall, a tree trunk,
a tree crown, and a training-ring collision in Gazebo. The same swept paths must
also be rejected by DroneDream's runtime clearance gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.autonomy.school_map_artifact import (  # noqa: E402
    export_school_map_gazebo_artifact,
    school_map_runtime_collision_primitives,
)
from app.autonomy.school_map_mission_validation import (  # noqa: E402
    sample_polyline,
    validate_route_clearance,
)

WORLD_NAME = "school_map_world"
VEHICLE_PROBE_RADIUS_M = 0.38
VEHICLE_PROBE_MASS_KG = 2.1643076923076925
SWEEP_INTERVAL_M = 0.02


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "wall",
        "start": (-49.8, 14.95, 1.91),
        "end": (-52.0, 14.95, 1.91),
        "force": (-24.0, 0.0, 0.0),
        "expected_collision_token": "classroom-1-1-left-wall-collision",
        "expected_primitive_token": "classroom-1-1-left-wall",
    },
    {
        "id": "tree",
        "start": (-46.8, -11.6, 1.15),
        "end": (-49.2, -11.6, 1.15),
        "force": (-24.0, 0.0, 0.0),
        "expected_collision_token": "campus-tree-1-trunk-collision",
        "expected_primitive_token": "campus-tree-1-trunk",
    },
    {
        "id": "tree-crown",
        "start": (-45.4, -11.6825, 3.749),
        "end": (-49.0, -11.6825, 3.749),
        "force": (-24.0, 0.0, 0.0),
        "expected_collision_token": "campus-tree-1-conservative-crown-envelope-collision",
        "expected_primitive_token": "campus-tree-1-conservative-crown-envelope",
    },
    {
        "id": "training-ring",
        "start": (-5.0, -15.2, 2.40),
        "end": (-5.0, -17.4, 2.40),
        "force": (0.0, -24.0, 0.0),
        "expected_collision_token": "school-training-gate-1-collision-segment-",
        "expected_primitive_token": "school-training-gate-1-collision-segment-",
    },
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run physical wall/tree/training-ring collision acceptance in Gazebo"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser.parse_args()


def _prepare_empty_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)


def _inject_collision_plugins(source: Path, destination: Path) -> None:
    tree = ElementTree.parse(source)  # noqa: S314 - exact qualified School Map SDF input.
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError("School Map physics SDF has no world")
    # Adding any world plugin suppresses Gazebo's default server plugin set, so
    # include the three standard systems explicitly before the two systems used
    # by this acceptance run.
    plugins = (
        ("gz-sim-physics-system", "gz::sim::systems::Physics"),
        ("gz-sim-user-commands-system", "gz::sim::systems::UserCommands"),
        ("gz-sim-scene-broadcaster-system", "gz::sim::systems::SceneBroadcaster"),
        ("gz-sim-contact-system", "gz::sim::systems::Contact"),
        ("gz-sim-apply-link-wrench-system", "gz::sim::systems::ApplyLinkWrench"),
    )
    existing = {plugin.get("name") for plugin in world.findall("plugin")}
    for filename, name in plugins:
        if name not in existing:
            ElementTree.SubElement(world, "plugin", {"filename": filename, "name": name})
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def _probe_sdf(name: str, topic: str, start: tuple[float, float, float]) -> str:
    x, y, z = start
    inertia = 2.0 * VEHICLE_PROBE_MASS_KG * VEHICLE_PROBE_RADIUS_M**2 / 5.0
    return f"""<?xml version='1.0'?>
<sdf version='1.9'>
  <model name='{name}'>
    <pose>{x} {y} {z} 0 0 0</pose>
    <link name='body'>
      <gravity>false</gravity>
      <inertial>
        <mass>{VEHICLE_PROBE_MASS_KG}</mass>
        <inertia>
          <ixx>{inertia}</ixx><iyy>{inertia}</iyy><izz>{inertia}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>
        </inertia>
      </inertial>
      <collision name='vehicle-envelope-collision'>
        <geometry><sphere><radius>{VEHICLE_PROBE_RADIUS_M}</radius></sphere></geometry>
      </collision>
      <sensor name='vehicle-envelope-contact' type='contact'>
        <contact>
          <collision>vehicle-envelope-collision</collision>
          <topic>{topic}</topic>
        </contact>
        <always_on>true</always_on>
        <update_rate>250</update_rate>
      </sensor>
    </link>
  </model>
</sdf>
"""


def _run(
    args: list[str],
    *,
    env: dict[str, str],
    timeout: float = 10.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - resolved Gazebo executable with fixed argv.
        args,
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _wait_for_world(gz: str, env: dict[str, str], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = _run([gz, "topic", "-l"], env=env, timeout=5.0, check=False)
        if result.returncode == 0 and "/clock" in result.stdout.splitlines():
            return
        time.sleep(0.25)
    raise TimeoutError("Gazebo did not expose /clock")


def _create_entity(
    gz: str, env: dict[str, str], *, name: str, sdf_filename: Path
) -> subprocess.CompletedProcess[str]:
    request = f'sdf_filename: "{sdf_filename}" name: "{name}" allow_renaming: false'
    result = _run(
        [
            gz,
            "service",
            "-s",
            f"/world/{WORLD_NAME}/create",
            "--reqtype",
            "gz.msgs.EntityFactory",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "5000",
            "--req",
            request,
        ],
        env=env,
        timeout=10.0,
    )
    if "data: true" not in result.stdout:
        raise RuntimeError(f"Gazebo rejected probe {name}: {result.stdout} {result.stderr}")
    return result


def _remove_entity(gz: str, env: dict[str, str], name: str) -> None:
    _run(
        [
            gz,
            "service",
            "-s",
            f"/world/{WORLD_NAME}/remove",
            "--reqtype",
            "gz.msgs.Entity",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "5000",
            "--req",
            f'name: "{name}" type: MODEL',
        ],
        env=env,
        timeout=10.0,
        check=False,
    )


def _publish_wrench(
    gz: str,
    env: dict[str, str],
    name: str,
    force: tuple[float, float, float],
) -> None:
    x, y, z = force
    message = f'entity: {{name: "{name}" type: MODEL}} wrench: {{force: {{x: {x} y: {y} z: {z}}}}}'
    _run(
        [
            gz,
            "topic",
            "-t",
            f"/world/{WORLD_NAME}/wrench/persistent",
            "-m",
            "gz.msgs.EntityWrench",
            "-p",
            message,
        ],
        env=env,
        timeout=5.0,
    )


def _clear_wrench(gz: str, env: dict[str, str], name: str) -> None:
    _run(
        [
            gz,
            "topic",
            "-t",
            f"/world/{WORLD_NAME}/wrench/clear",
            "-m",
            "gz.msgs.Entity",
            "-p",
            f'name: "{name}" type: MODEL',
        ],
        env=env,
        timeout=5.0,
        check=False,
    )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=8.0)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5.0)


def _runtime_rejection(scenario: dict[str, Any]) -> dict[str, Any]:
    samples = sample_polyline(
        [scenario["start"], scenario["end"]],
        interval_m=SWEEP_INTERVAL_M,
    )
    result = validate_route_clearance(
        samples,
        school_map_runtime_collision_primitives(),
        penetration_tolerance_m=0.0005,
    )
    accepted = result.collision_count == 0
    reported_names = sorted({collision[1] for collision in result.collisions})
    expected = str(scenario["expected_primitive_token"])
    return {
        "accepted": accepted,
        "collision_count": result.collision_count,
        "minimum_clearance_m": result.minimum_clearance_m,
        "reported_collision_names": reported_names,
        "expected_primitive_detected": any(expected in name for name in reported_names),
        "status": "failed" if not accepted else "verified",
        "failure_class": "crash_collision" if not accepted else None,
    }


def main() -> int:
    args = _parse_args()
    run_dir = args.run_dir.resolve()
    _prepare_empty_directory(run_dir)
    map_dir = run_dir / "school-map"
    export_school_map_gazebo_artifact(map_dir)
    collision_world = run_dir / "collision-world.sdf"
    _inject_collision_plugins(map_dir / "world.physics.sdf", collision_world)

    gz = shutil.which("gz")
    if gz is None:
        raise FileNotFoundError("gz executable was not found")
    env = os.environ.copy()
    partition = f"dronedream_collision_acceptance_{os.getpid()}_{int(time.time())}"
    state_root = run_dir / "runtime-state"
    for child in ("cache", "config", "data"):
        (state_root / child).mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "GZ_PARTITION": partition,
            "GZ_SIM_RESOURCE_PATH": str(map_dir),
            "XDG_CACHE_HOME": str(state_root / "cache"),
            "XDG_CONFIG_HOME": str(state_root / "config"),
            "XDG_DATA_HOME": str(state_root / "data"),
        }
    )

    gazebo_log_path = run_dir / "gazebo.log"
    results: list[dict[str, Any]] = []
    with gazebo_log_path.open("w", encoding="utf-8") as gazebo_log:
        gazebo = subprocess.Popen(  # noqa: S603 - resolved Gazebo executable with fixed argv.
            [gz, "sim", "-r", "-s", "-v", "2", str(collision_world)],
            env=env,
            stdout=gazebo_log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            _wait_for_world(gz, env, args.timeout_seconds)
            for scenario in SCENARIOS:
                scenario_id = str(scenario["id"])
                name = f"collision_probe_{scenario_id.replace('-', '_')}"
                topic = f"/dronedream/collision/{scenario_id}"
                probe_path = run_dir / f"{name}.sdf"
                probe_path.write_text(_probe_sdf(name, topic, scenario["start"]), encoding="utf-8")
                _create_entity(gz, env, name=name, sdf_filename=probe_path)
                listener = subprocess.Popen(  # noqa: S603 - resolved Gazebo executable with fixed argv.
                    [gz, "topic", "-e", "-n", "1", "-t", topic],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    time.sleep(0.5)
                    _publish_wrench(gz, env, name, scenario["force"])
                    contact_stdout, contact_stderr = listener.communicate(
                        timeout=args.timeout_seconds
                    )
                except subprocess.TimeoutExpired:
                    _terminate_process_group(listener)
                    contact_stdout, contact_stderr = listener.communicate()
                finally:
                    _clear_wrench(gz, env, name)
                    _remove_entity(gz, env, name)

                contact_path = run_dir / f"{scenario_id}-contact.txt"
                contact_path.write_text(contact_stdout, encoding="utf-8")
                expected_collision = str(scenario["expected_collision_token"])
                physical_contact = expected_collision in contact_stdout
                runtime_rejection = _runtime_rejection(scenario)
                result = {
                    "id": scenario_id,
                    "physical_contact_observed": physical_contact,
                    "expected_collision_token": expected_collision,
                    "contact_topic": topic,
                    "contact_evidence": contact_path.name,
                    "contact_stderr": contact_stderr,
                    "runtime_rejection": runtime_rejection,
                    "acceptance_passed": (
                        physical_contact
                        and runtime_rejection["status"] == "failed"
                        and runtime_rejection["expected_primitive_detected"] is True
                    ),
                }
                results.append(result)
        finally:
            _terminate_process_group(gazebo)

    payload = {
        "schema_version": "dronedream.school-map-collision-acceptance.v1",
        "status": (
            "verified"
            if results and all(item["acceptance_passed"] for item in results)
            else "failed"
        ),
        "world": WORLD_NAME,
        "partition": partition,
        "vehicle_probe_radius_m": VEHICLE_PROBE_RADIUS_M,
        "vehicle_probe_mass_kg": VEHICLE_PROBE_MASS_KG,
        "scenarios": results,
    }
    (run_dir / "collision_acceptance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
