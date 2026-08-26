"""Execute a prepared mission in real Gazebo/PX4 with the ROS plugin host active."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.runtime_interrupt import submit_runtime_message


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if len(drive) != 1:
        raise ValueError(f"path cannot be mapped to WSL: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"


def _secret_lines(provider: str, model: str, api_key: str) -> str:
    settings = {
        "deepseek": ("DEEPSEEK", "https://api.deepseek.com"),
        "kimi": ("KIMI", "https://api.moonshot.ai/v1"),
        "openai": ("OPENAI", "https://api.openai.com/v1"),
    }
    prefix, base_url = settings[provider]
    values = {
        f"{prefix}_API_KEY": api_key,
        f"{prefix}_BASE_URL": base_url,
        f"{prefix}_MODEL": model,
    }
    if provider == "openai":
        values["OPENAI_API_STYLE"] = "chat-completions"
    return "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _inject_runtime_message(
    *,
    run_root: Path,
    message_text: str,
    phase: str = "TRACK",
    timeout_seconds: float = 240.0,
) -> None:
    """Wait for a real execution phase, then enqueue one exact UTF-8 user message."""

    phase_path = run_root / "simulation" / "runtime-phase.json"
    control_dir = run_root / "simulation" / "runtime-control"
    evidence_path = run_root / "runtime-message-injection.json"
    started = time.monotonic()
    last_phase: str | None = None
    try:
        while time.monotonic() - started < timeout_seconds:
            if phase_path.is_file():
                try:
                    phase_payload = json.loads(phase_path.read_text(encoding="utf-8"))
                    last_phase = str(phase_payload.get("phase", ""))
                except (OSError, json.JSONDecodeError):
                    last_phase = None
                if last_phase == phase and (control_dir / "session.json").is_file():
                    message = submit_runtime_message(
                        control_dir=control_dir,
                        text=message_text,
                    )
                    _atomic_json(
                        evidence_path,
                        {
                            "status": "submitted",
                            "target_phase": phase,
                            "observed_phase": last_phase,
                            "message_id": message.message_id,
                            "message_sha256": sha256_json(message),
                            "text_sha256": hashlib.sha256(message_text.encode("utf-8")).hexdigest(),
                            "utf8_round_trip": (
                                message_text.encode("utf-8").decode("utf-8") == message_text
                            ),
                            "elapsed_seconds": time.monotonic() - started,
                        },
                    )
                    return
            time.sleep(0.1)
        raise TimeoutError(
            f"runtime did not reach {phase!r} before injection timeout; last phase={last_phase!r}"
        )
    except Exception as exc:
        _atomic_json(
            evidence_path,
            {
                "status": "failed",
                "target_phase": phase,
                "last_phase": last_phase,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": time.monotonic() - started,
            },
        )


def _summarize(
    run_root: Path,
    *,
    contract_id: str,
    provider: str,
    model: str,
    watchdog_deadline_ms: int,
    watchdog_startup_deadline_ms: int,
) -> dict[str, object]:
    simulation_root = run_root / "simulation"
    workflow_path = simulation_root / "workflow-result.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    plugin_log = (run_root / "plugin-host.log").read_text(encoding="utf-8", errors="replace")
    if workflow.get("status") != "verified":
        raise RuntimeError("runtime workflow did not reach verified status")
    if "activated plugin runtime.safe-hold" not in plugin_log:
        raise RuntimeError("ROS safe-hold capability was not activated")
    if "forced fail-closed" in plugin_log or "plugin configure failed" in plugin_log:
        raise RuntimeError("ROS native capability host entered its fail-closed path")
    runtime_evidence = workflow["runtime_evidence"]
    measurements = runtime_evidence["measurements"]
    checkpoints = workflow.get("checkpoint_decisions", [])
    injection_path = run_root / "runtime-message-injection.json"
    runtime_message: dict[str, Any] | None = None
    if injection_path.is_file():
        runtime_message = json.loads(injection_path.read_text(encoding="utf-8"))
        if runtime_message.get("status") != "submitted":
            raise RuntimeError(f"runtime message injection failed: {runtime_message}")
        message_id = str(runtime_message["message_id"])
        control_root = simulation_root / "runtime-control"
        required_message_evidence = {
            # The coordinator atomically moves a claimed inbox item into the
            # processed ledger after the decision is finalized.  Requiring the
            # transient claimed path would reject the successful terminal state.
            "processed": control_root / "processed" / f"{message_id}.json",
            "detected": control_root / "detected" / f"{message_id}.json",
            "acknowledgement": control_root / "acks" / f"{message_id}.json",
            "decision": control_root / "decisions" / f"{message_id}.json",
        }
        missing_runtime_evidence = [
            name for name, path in required_message_evidence.items() if not path.is_file()
        ]
        if missing_runtime_evidence:
            raise RuntimeError(
                "runtime message lacks closed-loop evidence: " + ", ".join(missing_runtime_evidence)
            )
        adoption_candidates = (
            control_root / "adoptions" / f"{message_id}.json",
            control_root / "command-results" / f"{message_id}.json",
            control_root / "takeover-adoptions" / f"{message_id}.json",
        )
        if not any(path.is_file() for path in adoption_candidates):
            raise RuntimeError("runtime message was decided but never adopted by the executor")
        runtime_message["closed_loop_evidence"] = True
    summary = {
        "schema_version": "dronedream.pluginized-runtime-acceptance.v1",
        "status": workflow["status"],
        "contract_id": contract_id,
        "provider": provider,
        "model": model,
        "plugin_host": "runtime.safe-hold",
        "plugin_host_activated": True,
        "ros_domain_id": 74,
        "rmw_implementation": "rmw_cyclonedds_cpp",
        "watchdog_deadline_ms": watchdog_deadline_ms,
        "watchdog_startup_deadline_ms": watchdog_startup_deadline_ms,
        "plugin_host_log_sha256": hashlib.sha256(
            (run_root / "plugin-host.log").read_bytes()
        ).hexdigest(),
        "workflow_sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
        "executor_return_code": measurements["executor_return_code"],
        "landing_state": measurements["landing_state"],
        "pose_sample_count": measurements["pose_sample_count"],
        "ros_observation_rows": measurements["ros_observation_rows"],
        "minimum_goal_distance_m": measurements["minimum_goal_distance_m"],
        "checkpoint_calls": len(checkpoints),
        "checkpoints_authorized": all(
            bool(item.get("continue_authorized")) for item in checkpoints
        ),
        "completion_accepted": bool(workflow["completion_assessment"]["accepted"]),
        "runtime_message": runtime_message,
    }
    (run_root / "runtime-acceptance-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def run(
    planning_root: Path,
    run_root: Path,
    resource_root: Path,
    *,
    provider: str,
    model: str,
    runtime_message_file: Path | None = None,
) -> dict[str, object]:
    prepared_path = planning_root / "plan" / "prepared-mission.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    contract_id = str(prepared["contract"]["contract_id"])
    simulation_contract = prepared.get("simulation_capabilities")
    if not isinstance(simulation_contract, dict):
        raise RuntimeError("prepared mission has no simulation capability contract")
    simulator_contract = simulation_contract.get("simulator")
    native_contract = simulation_contract.get("native_runtime")
    if not isinstance(simulator_contract, dict) or simulator_contract.get("engine") != (
        "gazebo-harmonic"
    ):
        raise RuntimeError("prepared mission does not select the Gazebo Harmonic adapter")
    if not isinstance(native_contract, dict):
        raise RuntimeError("prepared mission has no native runtime contract")
    transport_contract = native_contract.get("transport")
    watchdog_contract = native_contract.get("watchdog")
    if (
        not isinstance(transport_contract, dict)
        or transport_contract.get("implementation") != "px4-uxrce-dds"
    ):
        raise RuntimeError("prepared mission does not select the PX4 uXRCE-DDS transport")
    if not isinstance(watchdog_contract, dict):
        raise RuntimeError("prepared mission has no native watchdog contract")
    watchdog_deadline_ms = int(watchdog_contract.get("deadline_ms", 250))
    watchdog_startup_deadline_ms = int(watchdog_contract.get("startup_deadline_ms", 10_000))
    if not 20 <= watchdog_deadline_ms <= 1_000:
        raise RuntimeError("prepared mission watchdog deadline is outside the safe range")
    if (
        not 1_000 <= watchdog_startup_deadline_ms <= 60_000
        or watchdog_startup_deadline_ms < watchdog_deadline_ms
    ):
        raise RuntimeError("prepared mission watchdog startup deadline is outside the safe range")
    if run_root.exists():
        if (run_root / "simulation" / "workflow-result.json").is_file():
            return _summarize(
                run_root,
                contract_id=contract_id,
                provider=provider,
                model=model,
                watchdog_deadline_ms=watchdog_deadline_ms,
                watchdog_startup_deadline_ms=watchdog_startup_deadline_ms,
            )
        raise FileExistsError(f"run directory already exists: {run_root}")
    key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "kimi": "KIMI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"{key_env} is not configured")
    runtime_message_text: str | None = None
    if runtime_message_file is not None:
        runtime_message_text = runtime_message_file.read_text(encoding="utf-8").strip()
        if not runtime_message_text:
            raise ValueError("runtime message file is empty")

    map_root = planning_root / "app-store" / "assets" / "map" / "dronedream.school-map.v1"
    vehicle_root = planning_root / "app-store" / "assets" / "vehicle" / "dronedream.my-drone.v1"
    runtime = resource_root / "runtime"
    required = (
        prepared_path,
        map_root / "gazebo" / "world.sdf",
        map_root / "gazebo" / "semantic.json",
        map_root / "navigation-graph.json",
        vehicle_root / "gazebo" / "model.sdf",
        vehicle_root / "vehicle.json",
        vehicle_root / "controller_params.json",
        runtime / "px4_offboard_track_executor.py",
        runtime / "px4_checkpoint_executor.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"acceptance inputs are missing: {missing}")

    run_root.mkdir(parents=True)
    simulation_root = run_root / "simulation"
    secret_path = run_root / f".model-session-{uuid4().hex}.env"
    secret_path.write_text(_secret_lines(provider, model, api_key), encoding="utf-8", newline="\n")
    run_wsl = shlex.quote(_wsl_path(run_root))
    secret_wsl = shlex.quote(_wsl_path(secret_path))
    command = [
        "execute-prepared-mission",
        "--prepared",
        _wsl_path(prepared_path),
        "--confirm-contract-id",
        contract_id,
        "--completion-provider",
        provider,
        "--run-dir",
        _wsl_path(simulation_root),
        "--world-sdf",
        _wsl_path(map_root / "gazebo" / "world.sdf"),
        "--semantic",
        _wsl_path(map_root / "gazebo" / "semantic.json"),
        "--map-graph",
        _wsl_path(map_root / "navigation-graph.json"),
        "--vehicle-sdf",
        _wsl_path(vehicle_root / "gazebo" / "model.sdf"),
        "--vehicle-metadata",
        _wsl_path(vehicle_root / "vehicle.json"),
        "--controller-params",
        _wsl_path(vehicle_root / "controller_params.json"),
        "--px4-root",
        "/opt/PX4-Autopilot",
        "--executor",
        _wsl_path(runtime / "px4_offboard_track_executor.py"),
        "--context-db",
        _wsl_path(run_root / "mission-context.sqlite3"),
        "--checkpoint-provider",
        provider,
        "--checkpoint-executor",
        _wsl_path(runtime / "px4_checkpoint_executor.py"),
        "--runtime-interrupt-provider",
        provider,
        "--runtime-hold-timeout-seconds",
        "12",
        "--runtime-replan-hold-seconds",
        "30",
    ]
    command_text = " ".join(shlex.quote(value) for value in command)
    script = (
        "set -eo pipefail\n"
        "source /opt/ros/jazzy/setup.bash\n"
        'root="$HOME/.local/share/dronedream-autonomy/v0.1.0"\n'
        'source "$root/ros_ws/install/setup.bash"\n'
        "set -u\n"
        "export ROS_DOMAIN_ID=74 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp "
        "ROS2_DISABLE_DAEMON=1\n"
        'export CYCLONEDDS_URI=\'<CycloneDDS><Domain Id="any"><General>'
        '<Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces>'
        "<AllowMulticast>false</AllowMulticast></General><Discovery>"
        "<ParticipantIndex>auto</ParticipantIndex><Peers>"
        '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>\'\n'
        f"source {secret_wsl}\n"
        f"rm -f {secret_wsl}\n"
        "ros2 run dronedream_agent_plugin_api capability_host "
        "--ros-args "
        f"-p contract_id:={shlex.quote(contract_id)} "
        f"-p watchdog_deadline_ms:={watchdog_deadline_ms} "
        f"-p watchdog_startup_deadline_ms:={watchdog_startup_deadline_ms} "
        f">{run_wsl}/plugin-host.log 2>&1 &\n"
        "plugin_host_pid=$!\n"
        "trap 'kill $plugin_host_pid 2>/dev/null || true; "
        "wait $plugin_host_pid 2>/dev/null || true' EXIT\n"
        f'"$root/venv/bin/dronedream-agent" {command_text} '
        '--ros-workspace "$root/ros_ws"\n'
    )
    injection_thread: threading.Thread | None = None
    if runtime_message_text is not None:
        injection_thread = threading.Thread(
            target=_inject_runtime_message,
            kwargs={"run_root": run_root, "message_text": runtime_message_text},
            name="runtime-message-injector",
            daemon=True,
        )
        injection_thread.start()
    try:
        result = subprocess.run(
            ["wsl.exe", "-d", "DroneDreamRuntime", "--", "bash", "-s", "--"],
            input=script.encode("utf-8"),
            check=False,
            timeout=2_400,
        )
    finally:
        secret_path.unlink(missing_ok=True)
        if injection_thread is not None:
            injection_thread.join(timeout=5.0)
    if result.returncode != 0:
        raise RuntimeError(f"pluginized runtime failed with exit code {result.returncode}")

    return _summarize(
        run_root,
        contract_id=contract_id,
        provider=provider,
        model=model,
        watchdog_deadline_ms=watchdog_deadline_ms,
        watchdog_startup_deadline_ms=watchdog_startup_deadline_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("planning_root", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("resource_root", type=Path)
    parser.add_argument("--provider", choices=("deepseek", "kimi", "openai"), default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument(
        "--runtime-message-file",
        type=Path,
        help="UTF-8 natural-language message injected after the real runtime reaches TRACK",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.planning_root,
                args.run_root,
                args.resource_root,
                provider=args.provider,
                model=args.model,
                runtime_message_file=args.runtime_message_file,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
