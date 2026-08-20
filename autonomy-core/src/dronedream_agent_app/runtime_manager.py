"""Fail-closed bridge from the Windows desktop app to DroneDreamRuntime WSL2."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from dronedream_agent_core.contracts import (
    PreparedMission,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeOperatorControlCommand,
    RuntimeOperatorTakeoverGrant,
    RuntimeUserMessage,
    Vector3,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.plugin_contracts import PluginSnapshot
from dronedream_agent_core.runtime_interrupt import submit_runtime_message

from .custom_models import ModelConnection
from .mission_service import _validate_gateway
from .plugin_manager import PluginManager, PluginManagerError
from .storage import AppStore


class RuntimeBridgeError(RuntimeError):
    """The real ROS/Gazebo/PX4 runtime is missing or rejected a launch."""


@dataclass
class ActiveRun:
    run_dir: Path
    process: subprocess.Popen[str]


@dataclass
class ActiveTakeoverGrant:
    message_id: str
    execution_id: str
    token_sha256: str
    grant_sha256: str
    expires_at: datetime
    next_sequence: int = 1


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive or len(drive) != 1:
        raise RuntimeBridgeError("WINDOWS_PATH_CANNOT_MAP_TO_WSL")
    relative = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{relative}"


class RuntimeManager:
    distribution = "DroneDreamRuntime"
    runtime_home = "$HOME/.local/share/dronedream-autonomy/v0.1.0"

    def __init__(
        self, store: AppStore, resource_root: Path | None, plugin_manager: PluginManager
    ) -> None:
        self.store = store
        self.resource_root = resource_root
        self.plugin_manager = plugin_manager
        self._lock = threading.RLock()
        self._active_runs: dict[str, ActiveRun] = {}
        self._takeover_grants: dict[str, ActiveTakeoverGrant] = {}
        self._setup_thread: threading.Thread | None = None
        self._setup_snapshot: dict[str, object] = {
            "schema_version": "dronedream.autonomy.runtime-setup.v1",
            "operation_id": None,
            "phase": "idle",
            "progress": 0,
            "active": False,
            "error": None,
            "failed_phase": None,
            "started_at": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        if hasattr(value, "model_dump_json"):
            rendered = value.model_dump_json(indent=2)
        else:
            rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        temporary.write_text(rendered + "\n", encoding="utf-8")
        temporary.replace(path)

    def _bash(self, script: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["wsl.exe", "-d", self.distribution, "--", "bash", "-s", "--"],
                check=False,
                capture_output=True,
                input=script,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise RuntimeBridgeError("DRONEDREAM_RUNTIME_UNAVAILABLE") from error

    def _resources_ready(self) -> bool:
        if self.resource_root is None:
            return False
        runtime = self.resource_root / "runtime"
        required = (
            runtime / "requirements-linux.txt",
            runtime / "px4_offboard_track_executor.py",
            runtime / "px4_checkpoint_executor.py",
            runtime / "ros_ws" / "src",
            runtime / "wheels",
        )
        if any(not value.exists() for value in required):
            return False
        manifest_path = runtime / "runtime-manifest.json"
        if not manifest_path.is_file() or not any((runtime / "wheels").glob("*.whl")):
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            if not isinstance(files, list) or not files:
                return False
            root = runtime.resolve()
            for item in files:
                if not isinstance(item, dict):
                    return False
                path = (runtime / str(item["path"])).resolve()
                if root not in path.parents or not path.is_file():
                    return False
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != item["sha256"]:
                    return False
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return True

    def _runtime_manifest_sha256(self) -> str:
        if self.resource_root is None:
            raise RuntimeBridgeError("RUNTIME_RESOURCES_MISSING")
        manifest_path = self.resource_root / "runtime" / "runtime-manifest.json"
        if not manifest_path.is_file():
            raise RuntimeBridgeError("RUNTIME_RESOURCES_MISSING")
        return hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    def status(self) -> dict[str, object]:
        resources_ready = self._resources_ready()
        try:
            base_probe = self._bash(
                "set -e; source /opt/ros/jazzy/setup.bash; set -u; "
                "command -v ros2 >/dev/null; command -v gz >/dev/null; "
                "test -x /opt/PX4-Autopilot/build/px4_sitl_default/bin/px4",
                timeout=15,
            )
        except RuntimeBridgeError:
            base_probe = None
        runtime_available = bool(base_probe and base_probe.returncode == 0)
        provisioned = False
        if runtime_available:
            manifest_sha256 = self._runtime_manifest_sha256() if resources_ready else "missing"
            provision_probe = self._bash(
                f"set -e; test -x {self.runtime_home}/venv/bin/dronedream-agent; "
                f"test -f {self.runtime_home}/ros_ws/install/setup.bash; "
                f'test "$(cat {self.runtime_home}/.runtime-manifest-sha256)" = '
                f"{shlex.quote(manifest_sha256)}; "
                f"set +u; source {self.runtime_home}/ros_ws/install/setup.bash; set -u; "
                "ros2 run dronedream_agent_plugin_api plugin_probe | "
                "grep -q PLUGIN_PROBE_READY; "
                "ros2 run dronedream_agent_plugin_api capability_host --self-test | "
                "grep -q PLUGIN_LIFECYCLE_READY; "
                f"{self.runtime_home}/venv/bin/python -c "
                "'import openai,pydantic,mavsdk'",
                timeout=15,
            )
            provisioned = provision_probe.returncode == 0
        issue = None
        if not resources_ready:
            issue = "RUNTIME_RESOURCES_MISSING"
        elif not runtime_available:
            issue = "DRONEDREAM_RUNTIME_UNAVAILABLE"
        elif not provisioned:
            issue = "RUNTIME_PROVISION_REQUIRED"
        return {
            "distribution": self.distribution,
            "runtime_available": runtime_available,
            "resources_ready": resources_ready,
            "provisioned": provisioned,
            "issue": issue,
        }

    def _set_setup_progress(
        self,
        phase: str,
        progress: int,
        *,
        active: bool = True,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._setup_snapshot.update(
                {
                    "phase": phase,
                    "progress": max(0, min(100, progress)),
                    "active": active,
                    "error": error,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )

    def setup_progress(self) -> dict[str, object]:
        with self._lock:
            return dict(self._setup_snapshot)

    def start_setup(self) -> dict[str, object]:
        """Start a single evidence-driven Runtime installation or update.

        Every reported percentage is tied to a completed command.  A failed
        command leaves the snapshot at its exact phase instead of allowing a
        timer to continue toward 100 percent.
        """

        with self._lock:
            if self._setup_thread is not None and self._setup_thread.is_alive():
                return dict(self._setup_snapshot)
            operation_id = f"runtime-setup-{uuid4().hex}"
            now = datetime.now(UTC).isoformat()
            self._setup_snapshot = {
                "schema_version": "dronedream.autonomy.runtime-setup.v1",
                "operation_id": operation_id,
                "phase": "queued",
                "progress": 0,
                "active": True,
                "error": None,
                "failed_phase": None,
                "started_at": now,
                "updated_at": now,
            }

            def worker() -> None:
                try:
                    self._perform_provision(self._set_setup_progress)
                except RuntimeBridgeError as error:
                    current = self.setup_progress()
                    self._set_setup_progress(
                        "failed",
                        int(current["progress"]),
                        active=False,
                        error=str(error),
                    )
                    with self._lock:
                        self._setup_snapshot["failed_phase"] = current["phase"]
                except Exception as error:  # pragma: no cover - defensive boundary
                    current = self.setup_progress()
                    self._set_setup_progress(
                        "failed",
                        int(current["progress"]),
                        active=False,
                        error=f"RUNTIME_SETUP_INTERNAL:{type(error).__name__}",
                    )
                    with self._lock:
                        self._setup_snapshot["failed_phase"] = current["phase"]

            self._setup_thread = threading.Thread(
                target=worker,
                name="dronedream-runtime-setup",
                daemon=True,
            )
            self._setup_thread.start()
            return dict(self._setup_snapshot)

    def _perform_provision(self, report=None) -> dict[str, object]:
        def checkpoint(phase: str, progress: int) -> None:
            if report is not None:
                report(phase, progress)

        checkpoint("validatingResources", 5)
        if self.resource_root is None:
            raise RuntimeBridgeError("RUNTIME_RESOURCES_MISSING")
        runtime_resources = self.resource_root / "runtime"
        wheels = runtime_resources / "wheels"
        requirements = runtime_resources / "requirements-linux.txt"
        ros_source = runtime_resources / "ros_ws" / "src"
        if not wheels.is_dir() or not requirements.is_file() or not ros_source.is_dir():
            raise RuntimeBridgeError("RUNTIME_RESOURCES_MISSING")
        checkpoint("checkingBaseRuntime", 12)
        current = self.status()
        if not current["runtime_available"]:
            raise RuntimeBridgeError(str(current["issue"]))
        wheels_wsl = shlex.quote(_wsl_path(wheels))
        requirements_wsl = shlex.quote(_wsl_path(requirements))
        ros_source_wsl = shlex.quote(_wsl_path(ros_source))
        manifest_sha256 = self._runtime_manifest_sha256()
        root = f"root={self.runtime_home}; "
        steps = (
            (
                "preparingEnvironment",
                25,
                root
                + 'mkdir -p "$root" "$root/ros_ws"; '
                + 'if [ ! -x "$root/venv/bin/python" ]; then '
                + 'python3 -m venv --system-site-packages "$root/venv"; fi',
                90,
                None,
            ),
            (
                "installingCore",
                42,
                root
                + '"$root/venv/bin/pip" install --no-index --no-deps --force-reinstall '
                + f"--find-links {wheels_wsl} dronedream-flight-agent-core",
                180,
                None,
            ),
            (
                "installingDependencies",
                58,
                root
                + '"$root/venv/bin/pip" install --no-index --force-reinstall '
                + f"--find-links {wheels_wsl} -r {requirements_wsl}",
                300,
                None,
            ),
            (
                "buildingRosWorkspace",
                76,
                root
                + 'colcon --log-base "$root/ros_ws/log" build '
                + f"--base-paths {ros_source_wsl} "
                + '--build-base "$root/ros_ws/build" '
                + '--install-base "$root/ros_ws/install"',
                600,
                None,
            ),
            (
                "runningHealthChecks",
                92,
                root
                + 'set +u; source "$root/ros_ws/install/setup.bash"; set -u; '
                + "ros2 run dronedream_agent_plugin_api plugin_probe | "
                + "grep -q PLUGIN_PROBE_READY; "
                + "ros2 run dronedream_agent_plugin_api capability_host --self-test | "
                + "grep -q PLUGIN_LIFECYCLE_READY; "
                + '"$root/venv/bin/python" -c '
                + "\"import openai,pydantic,mavsdk; print('AUTONOMY_RUNTIME_READY')\"; "
                + '"$root/venv/bin/dronedream-agent" --help >/dev/null',
                120,
                "AUTONOMY_RUNTIME_READY",
            ),
            (
                "recordingReceipt",
                98,
                root
                + f"printf '%s\\n' {shlex.quote(manifest_sha256)} > "
                + '"$root/.runtime-manifest-sha256"',
                30,
                None,
            ),
        )
        for phase, progress, body, timeout, required_output in steps:
            checkpoint(phase, progress)
            result = self._bash(
                f"set -eo pipefail; source /opt/ros/jazzy/setup.bash; set -u; {body}",
                timeout=timeout,
            )
            if result.returncode != 0 or (
                required_output is not None and required_output not in result.stdout
            ):
                detail = (result.stderr or result.stdout)[-1_000:]
                raise RuntimeBridgeError(f"RUNTIME_PROVISION_FAILED:{phase}:{detail}")
        verified = self.status()
        if not verified["provisioned"]:
            raise RuntimeBridgeError("RUNTIME_PROVISION_VERIFICATION_FAILED")
        checkpoint("completed", 100)
        if report is not None:
            report("completed", 100, active=False)
        return verified

    def provision(self) -> dict[str, object]:
        return self._perform_provision()

    @staticmethod
    def _secret_lines(
        provider: str, model_id: str, grant: str, gateway: str, api_style: str = "chat-completions"
    ) -> str:
        prefix = re.sub(r"[^A-Z0-9]+", "_", provider.upper()).strip("_") or "CUSTOM"
        values = {
            f"{prefix}_API_KEY": grant,
            f"{prefix}_BASE_URL": gateway,
            f"{prefix}_MODEL": model_id,
        }
        if api_style:
            values[f"{prefix}_API_STYLE"] = api_style
        return "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())

    @classmethod
    def _write_secret_session(
        cls,
        path: Path,
        *,
        provider: str,
        model_id: str,
        grant: str,
        gateway: str,
        api_style: str = "chat-completions",
    ) -> None:
        path.write_text(
            cls._secret_lines(provider, model_id, grant, gateway, api_style),
            encoding="utf-8",
            newline="\n",
        )

    def execute(
        self,
        *,
        thread_id: str,
        connection: ModelConnection | None = None,
        model_id: str | None = None,
        model_grant: str | None = None,
        gateway_base_url: str | None = None,
    ) -> dict[str, object]:
        if connection is None:
            if not model_id or not model_grant or not gateway_base_url:
                raise RuntimeBridgeError("MODEL_CONNECTION_REQUIRED")
            provider, _plugin_id, capability_id = self.plugin_manager.model_binding_for_model(
                model_id
            )
            connection = ModelConnection(
                selection_id=model_id,
                provider=provider,
                model_id=model_id,
                api_key=model_grant,
                base_url=_validate_gateway(gateway_base_url),
                api_style="chat-completions",
                capability_id=capability_id,
                source="default",
            )
        if not self.status()["provisioned"]:
            raise RuntimeBridgeError("RUNTIME_PROVISION_REQUIRED")
        if self.resource_root is None:
            raise RuntimeBridgeError("RUNTIME_RESOURCES_MISSING")
        thread = self.store.get_thread(thread_id)
        if thread["state"] != "awaiting_confirmation":
            raise RuntimeBridgeError("TASK_NOT_AWAITING_CONFIRMATION")
        if connection.selection_id != thread["selected_model"]:
            raise RuntimeBridgeError("EXECUTION_MODEL_MISMATCH")
        with self._lock:
            if thread_id in self._active_runs:
                raise RuntimeBridgeError("TASK_ALREADY_EXECUTING")
        plan = self.store.latest_plan(thread_id)
        map_asset = self.store.get_asset(str(thread["selected_map_id"]), "map")
        vehicle_asset = self.store.get_asset(str(thread["selected_vehicle_id"]), "vehicle")
        if map_asset["status"] != "qualified" or vehicle_asset["status"] != "qualified":
            raise RuntimeBridgeError("EXECUTION_ASSET_NOT_QUALIFIED")
        provider = connection.provider
        provider_capability_id = connection.capability_id
        gateway = connection.base_url
        snapshot_record = self.store.latest_plugin_snapshot(thread_id)
        snapshot = PluginSnapshot.model_validate(snapshot_record["snapshot"])
        try:
            _runtime_entry, _runtime_manifest, runtime_capability = (
                self.plugin_manager.capability_for_slot(snapshot, "simulation.runtime-adapter")
            )
            _interrupt_entry, _interrupt_manifest, interrupt_capability = (
                self.plugin_manager.capability_for_slot(snapshot, "safety.interruption-policy")
            )
        except PluginManagerError as error:
            raise RuntimeBridgeError(str(error)) from error
        required_capabilities = {
            runtime_capability.capability_id,
            interrupt_capability.capability_id,
            provider_capability_id,
        }
        try:
            self.plugin_manager.assert_snapshot_active(snapshot, required_capabilities)
        except (KeyError, PluginManagerError) as error:
            raise RuntimeBridgeError(str(error)) from error
        map_manifest = map_asset["manifest"]
        vehicle_manifest = vehicle_asset["manifest"]
        if not isinstance(map_manifest, dict) or not isinstance(vehicle_manifest, dict):
            raise RuntimeBridgeError("EXECUTION_ASSET_MANIFEST_INVALID")
        map_files = map_manifest.get("files")
        vehicle_files = vehicle_manifest.get("files")
        if not isinstance(map_files, dict) or not isinstance(vehicle_files, dict):
            raise RuntimeBridgeError("EXECUTION_ASSET_FILES_INVALID")
        execution_id = f"execution-{uuid4().hex}"
        execution_root = self.store.missions_root / thread_id / execution_id
        execution_root.mkdir(parents=True, exist_ok=False)
        run_dir = execution_root / "simulation"
        map_root = Path(str(map_asset["bundle_root"]))
        vehicle_root = Path(str(vehicle_asset["bundle_root"]))
        prepared = Path(str(plan["output_dir"])) / "prepared-mission.json"
        world = map_root / str(map_files["world_sdf"])
        semantic = map_root / str(map_files["semantic"])
        map_graph = map_root / str(map_files["graph"])
        vehicle = vehicle_root / str(vehicle_files["vehicle_sdf"])
        controller = vehicle_root / str(vehicle_files["controller_params"])
        vehicle_metadata = vehicle_root / str(vehicle_files["vehicle_metadata"])
        required = (
            prepared,
            world,
            semantic,
            map_graph,
            vehicle,
            controller,
            vehicle_metadata,
        )
        if any(not path.is_file() for path in required):
            raise RuntimeBridgeError("EXECUTION_ARTIFACT_MISSING")
        try:
            prepared_mission = PreparedMission.model_validate_json(
                prepared.read_text(encoding="utf-8")
            )
            simulation_contract = prepared_mission.simulation_capabilities
            simulator_contract = simulation_contract.get("simulator", {})
            native_contract = simulation_contract.get("native_runtime", {})
            transport_contract = (
                native_contract.get("transport", {}) if isinstance(native_contract, dict) else {}
            )
            watchdog_contract = (
                native_contract.get("watchdog", {}) if isinstance(native_contract, dict) else {}
            )
        except (OSError, TypeError, ValueError) as error:
            raise RuntimeBridgeError("EXECUTION_PLUGIN_CONTRACT_INVALID") from error
        if not isinstance(simulator_contract, dict) or simulator_contract.get("engine") != (
            "gazebo-harmonic"
        ):
            raise RuntimeBridgeError("SIMULATOR_ADAPTER_NOT_EXECUTABLE")
        if (
            not isinstance(transport_contract, dict)
            or transport_contract.get("implementation") != "px4-uxrce-dds"
        ):
            raise RuntimeBridgeError("FLIGHT_TRANSPORT_NOT_EXECUTABLE")
        if not isinstance(watchdog_contract, dict):
            raise RuntimeBridgeError("RUNTIME_WATCHDOG_CONTRACT_INVALID")
        try:
            watchdog_deadline_ms = int(watchdog_contract.get("deadline_ms", 250))
            watchdog_startup_deadline_ms = int(watchdog_contract.get("startup_deadline_ms", 10_000))
        except (TypeError, ValueError) as error:
            raise RuntimeBridgeError("RUNTIME_WATCHDOG_CONTRACT_INVALID") from error
        if watchdog_deadline_ms < 20 or watchdog_deadline_ms > 1_000:
            raise RuntimeBridgeError("RUNTIME_WATCHDOG_CONTRACT_INVALID")
        if (
            not 1_000 <= watchdog_startup_deadline_ms <= 60_000
            or watchdog_startup_deadline_ms < watchdog_deadline_ms
        ):
            raise RuntimeBridgeError("RUNTIME_WATCHDOG_CONTRACT_INVALID")
        secret_path = execution_root / f".model-session-{uuid4().hex}.env"
        self._write_secret_session(
            secret_path,
            provider=provider,
            model_id=connection.model_id,
            grant=connection.api_key,
            gateway=gateway,
            api_style=connection.api_style,
        )
        runtime_metadata = runtime_capability.metadata
        interrupt_metadata = interrupt_capability.metadata
        runtime = self.resource_root / "runtime"
        executor = runtime / str(runtime_metadata.get("executor", ""))
        checkpoint_executor = runtime / str(runtime_metadata.get("checkpoint_executor", ""))
        runtime_distribution = str(runtime_metadata.get("distribution", self.distribution))
        ros_setup = str(runtime_metadata.get("ros_setup", "/opt/ros/jazzy/setup.bash"))
        px4_root = str(runtime_metadata.get("px4_root", "/opt/PX4-Autopilot"))
        runtime_cli = str(runtime_metadata.get("runtime_cli", "execute-prepared-mission"))
        capability_host = str(
            runtime_metadata.get(
                "capability_host", "ros2 run dronedream_agent_plugin_api capability_host"
            )
        )
        try:
            ros_domain_id = int(runtime_metadata.get("ros_domain_id", 74))
        except (TypeError, ValueError) as error:
            raise RuntimeBridgeError("RUNTIME_ROS_DOMAIN_INVALID") from error
        if ros_domain_id < 0 or ros_domain_id > 232:
            raise RuntimeBridgeError("RUNTIME_ROS_DOMAIN_INVALID")
        hold_timeout = float(interrupt_metadata.get("hold_timeout_seconds", 12.0))
        replan_hold = float(interrupt_metadata.get("replan_hold_seconds", 30.0))
        if not executor.is_file() or not checkpoint_executor.is_file():
            raise RuntimeBridgeError("RUNTIME_ADAPTER_RESOURCE_MISSING")
        context_db = self.store.root / "mission-context.sqlite3"
        contract_id = str(plan["contract_id"])
        command = [
            runtime_cli,
            "--prepared",
            _wsl_path(prepared),
            "--confirm-contract-id",
            contract_id,
            "--completion-provider",
            provider,
            "--run-dir",
            _wsl_path(run_dir),
            "--world-sdf",
            _wsl_path(world),
            "--semantic",
            _wsl_path(semantic),
            "--map-graph",
            _wsl_path(map_graph),
            "--vehicle-sdf",
            _wsl_path(vehicle),
            "--vehicle-metadata",
            _wsl_path(vehicle_metadata),
            "--controller-params",
            _wsl_path(controller),
            "--px4-root",
            px4_root,
            "--executor",
            _wsl_path(executor),
            "--context-db",
            _wsl_path(context_db),
            "--checkpoint-provider",
            provider,
            "--checkpoint-executor",
            _wsl_path(checkpoint_executor),
            "--runtime-interrupt-provider",
            provider,
            "--runtime-hold-timeout-seconds",
            f"{hold_timeout:g}",
            "--runtime-replan-hold-seconds",
            f"{replan_hold:g}",
        ]
        command_text = " ".join(shlex.quote(value) for value in command)
        secret_wsl = shlex.quote(_wsl_path(secret_path))
        script = (
            f"set -eo pipefail; source {shlex.quote(ros_setup)}; "
            f'root={self.runtime_home}; source "$root/ros_ws/install/setup.bash"; set -u; '
            f"export ROS_DOMAIN_ID={ros_domain_id} RMW_IMPLEMENTATION=rmw_cyclonedds_cpp "
            "ROS2_DISABLE_DAEMON=1; "
            'export CYCLONEDDS_URI=\'<CycloneDDS><Domain Id="any"><General>'
            '<Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces>'
            "<AllowMulticast>false</AllowMulticast></General><Discovery>"
            "<ParticipantIndex>auto</ParticipantIndex><Peers>"
            '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>\'; '
            f"source {secret_wsl}; rm -f {secret_wsl}; "
            f"{capability_host} --ros-args "
            f"-p contract_id:={shlex.quote(contract_id)} "
            f"-p watchdog_deadline_ms:={watchdog_deadline_ms} "
            f"-p watchdog_startup_deadline_ms:={watchdog_startup_deadline_ms} & "
            "plugin_host_pid=$!; "
            "trap 'kill $plugin_host_pid 2>/dev/null || true; "
            "wait $plugin_host_pid 2>/dev/null || true' EXIT; "
            f'"$root/venv/bin/dronedream-agent" {command_text} '
            '--ros-workspace "$root/ros_ws"'
        )
        stdout = (execution_root / "desktop-runtime.stdout.log").open("w", encoding="utf-8")
        stderr = (execution_root / "desktop-runtime.stderr.log").open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                ["wsl.exe", "-d", runtime_distribution, "--", "bash", "-s", "--"],
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
            assert process.stdin is not None
            process.stdin.write(script)
            process.stdin.close()
        except BaseException:
            stdout.close()
            stderr.close()
            secret_path.unlink(missing_ok=True)
            raise
        with self._lock:
            self._active_runs[thread_id] = ActiveRun(run_dir=run_dir, process=process)
        self.store.set_thread_state(thread_id, "executing")

        def monitor() -> None:
            return_code = process.wait()
            secret_path.unlink(missing_ok=True)
            stdout.close()
            stderr.close()
            with self._lock:
                self._active_runs.pop(thread_id, None)
                self._takeover_grants.pop(thread_id, None)
            result_path = run_dir / "workflow-result.json"
            final_state = "failed"
            if return_code == 0 and result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if result.get("status") == "verified":
                    final_state = "completed"
            self.store.set_thread_state(thread_id, final_state)
            english = self.store.get_settings().get("locale") == "en-US"
            self.store.append_message(
                thread_id,
                role="assistant",
                kind="status" if final_state == "completed" else "error",
                content=(
                    "Simulation completed"
                    if english and final_state == "completed"
                    else "Simulation did not pass acceptance"
                    if english
                    else "仿真任务已完成"
                    if final_state == "completed"
                    else "仿真任务未通过验收"
                ),
                metadata={
                    "execution_id": execution_id,
                    "return_code": return_code,
                    "run_dir": str(run_dir),
                    "execution_root": str(execution_root),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

        threading.Thread(target=monitor, daemon=True).start()
        return {
            "execution_id": execution_id,
            "state": "executing",
            "run_dir": str(run_dir),
            "execution_root": str(execution_root),
        }

    def submit_message(self, thread_id: str, text: str) -> dict[str, object]:
        with self._lock:
            active = self._active_runs.get(thread_id)
        if active is None:
            raise RuntimeBridgeError("TASK_NOT_EXECUTING")
        try:
            snapshot = PluginSnapshot.model_validate(
                self.store.latest_plugin_snapshot(thread_id)["snapshot"]
            )
            _entry, _manifest, capability = self.plugin_manager.capability_for_slot(
                snapshot, "safety.interruption-policy"
            )
        except (KeyError, ValueError, PluginManagerError) as error:
            raise RuntimeBridgeError("INTERRUPTION_POLICY_UNAVAILABLE") from error
        policy = str(capability.metadata.get("policy", "safe-hold-before-classification"))
        immediate_action = str(capability.metadata.get("immediate_action", "safe_hold"))
        message = submit_runtime_message(control_dir=active.run_dir / "runtime-control", text=text)
        self.store.set_thread_state(thread_id, "holding")
        self.store.append_message(
            thread_id,
            role="user",
            kind="status",
            content=text,
            metadata={
                "message_id": message.message_id,
                "interrupt_policy": policy,
                "interrupt_plugin_capability": capability.capability_id,
            },
        )
        return {
            "accepted": True,
            "message_id": message.message_id,
            "immediate_action": immediate_action,
        }

    def issue_takeover_grant(
        self,
        thread_id: str,
        *,
        message_id: str,
        operator_id: str,
        duration_seconds: int,
    ) -> dict[str, object]:
        with self._lock:
            active = self._active_runs.get(thread_id)
        if active is None:
            raise RuntimeBridgeError("TASK_NOT_EXECUTING")
        control_dir = active.run_dir / "runtime-control"
        session_path = control_dir / "session.json"
        message_path = next(
            (
                control_dir / folder / f"{message_id}.json"
                for folder in ("processed", "claimed", "inbox")
                if (control_dir / folder / f"{message_id}.json").is_file()
            ),
            None,
        )
        acknowledgement_path = control_dir / "acks" / f"{message_id}.json"
        decision_path = control_dir / "decisions" / f"{message_id}.json"
        if (
            message_path is None
            or not session_path.is_file()
            or not acknowledgement_path.is_file()
            or not decision_path.is_file()
        ):
            raise RuntimeBridgeError("TAKEOVER_STABLE_HOLD_NOT_READY")
        message = RuntimeUserMessage.model_validate_json(message_path.read_text(encoding="utf-8"))
        acknowledgement = RuntimeHoldAcknowledgement.model_validate_json(
            acknowledgement_path.read_text(encoding="utf-8")
        )
        decision = RuntimeInterruptionDecision.model_validate_json(
            decision_path.read_text(encoding="utf-8")
        )
        gates = {
            "message_action_is_takeover": (
                decision.classification.requested_action == "operator_takeover"
            ),
            "executor_is_holding": decision.authorized_action == "hold",
            "message_hash_matches": decision.message_sha256 == sha256_json(message),
            "hold_hash_matches": decision.hold_ack_sha256 == sha256_json(acknowledgement),
            "hold_gates_passed": all(acknowledgement.deterministic_gates.values()),
            "execution_matches": message.execution_id == acknowledgement.execution_id,
        }
        if not all(gates.values()):
            failed = ",".join(name for name, accepted in gates.items() if not accepted)
            raise RuntimeBridgeError(f"TAKEOVER_GRANT_REJECTED:{failed}")
        raw_token = secrets.token_urlsafe(48)
        token_sha256 = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.now(UTC)
        grant = RuntimeOperatorTakeoverGrant(
            message_id=message.message_id,
            execution_id=message.execution_id,
            operator_id=operator_id,
            message_sha256=sha256_json(message),
            hold_ack_sha256=sha256_json(acknowledgement),
            decision_sha256=sha256_json(decision),
            grant_token_sha256=token_sha256,
            maximum_horizontal_speed_mps=1.5,
            maximum_vertical_speed_mps=1.0,
            maximum_yaw_rate_dps=90.0,
            deterministic_gates=gates,
            issued_at=now,
            expires_at=now + timedelta(seconds=duration_seconds),
        )
        grant_sha256 = sha256_json(grant)
        self._atomic_json(control_dir / "takeover-grants" / f"{message_id}.json", grant)
        with self._lock:
            self._takeover_grants[thread_id] = ActiveTakeoverGrant(
                message_id=message_id,
                execution_id=message.execution_id,
                token_sha256=token_sha256,
                grant_sha256=grant_sha256,
                expires_at=grant.expires_at,
            )
        return {
            "accepted": True,
            "message_id": message_id,
            "grant_token": raw_token,
            "expires_at": grant.expires_at.isoformat(),
            "maximum_horizontal_speed_mps": grant.maximum_horizontal_speed_mps,
            "maximum_vertical_speed_mps": grant.maximum_vertical_speed_mps,
            "maximum_yaw_rate_dps": grant.maximum_yaw_rate_dps,
        }

    def submit_operator_control(
        self,
        thread_id: str,
        *,
        message_id: str,
        grant_token: str,
        action: str,
        north_mps: float,
        east_mps: float,
        down_mps: float,
        yaw_rate_dps: float,
        duration_seconds: float,
    ) -> dict[str, object]:
        with self._lock:
            active = self._active_runs.get(thread_id)
            grant_state = self._takeover_grants.get(thread_id)
        if active is None or grant_state is None:
            raise RuntimeBridgeError("TAKEOVER_GRANT_NOT_ACTIVE")
        supplied_hash = hashlib.sha256(grant_token.encode()).hexdigest()
        if not hmac.compare_digest(supplied_hash, grant_state.token_sha256):
            raise RuntimeBridgeError("TAKEOVER_GRANT_TOKEN_INVALID")
        if message_id != grant_state.message_id or datetime.now(UTC) >= grant_state.expires_at:
            raise RuntimeBridgeError("TAKEOVER_GRANT_EXPIRED_OR_MISMATCHED")
        horizontal = (north_mps**2 + east_mps**2) ** 0.5
        if horizontal > 1.5 or abs(down_mps) > 1.0 or abs(yaw_rate_dps) > 90.0:
            raise RuntimeBridgeError("TAKEOVER_COMMAND_OUTSIDE_GRANT_ENVELOPE")
        with self._lock:
            sequence = grant_state.next_sequence
            grant_state.next_sequence += 1
        command = RuntimeOperatorControlCommand(
            message_id=message_id,
            execution_id=grant_state.execution_id,
            grant_sha256=grant_state.grant_sha256,
            sequence=sequence,
            action=action,
            velocity_ned_mps=Vector3(x=north_mps, y=east_mps, z=down_mps),
            yaw_rate_dps=yaw_rate_dps,
            duration_seconds=duration_seconds,
            issued_at=datetime.now(UTC),
        )
        self._atomic_json(
            active.run_dir / "runtime-control" / "operator-commands" / f"{sequence:08d}.json",
            command,
        )
        return {"accepted": True, "sequence": sequence, "action": action}

    def prepare_plugin_disable(self, plugin_id: str, swap_policy: str) -> list[str]:
        """Enforce the manifest swap policy against exact active-task snapshots."""

        with self._lock:
            active_thread_ids = list(self._active_runs)
        affected: list[tuple[str, PluginSnapshot]] = []
        for thread_id in active_thread_ids:
            try:
                record = self.store.latest_plugin_snapshot(thread_id)
                snapshot = PluginSnapshot.model_validate(record["snapshot"])
            except (KeyError, ValueError):
                raise RuntimeBridgeError("ACTIVE_TASK_PLUGIN_SNAPSHOT_INVALID") from None
            if plugin_id not in {item.plugin_id for item in snapshot.plugins}:
                continue
            affected.append((thread_id, snapshot))
        if not affected or swap_policy in {"anytime", "next-mission"}:
            return []
        if swap_policy in {"restart", "certified-update"}:
            raise RuntimeBridgeError(
                f"PLUGIN_SWAP_REQUIRES_IDLE:{swap_policy}:"
                + ",".join(thread_id for thread_id, _snapshot in affected)
            )
        if swap_policy != "safe-hold":
            raise RuntimeBridgeError(f"PLUGIN_SWAP_POLICY_UNSUPPORTED:{swap_policy}")
        held: list[str] = []
        for thread_id, _snapshot in affected:
            result = self.submit_message(
                thread_id,
                f"系统正在停用插件 {plugin_id}，请立即进入安全悬停并等待能力变更。",
            )
            acknowledgement_path = (
                self._active_runs[thread_id].run_dir
                / "runtime-control"
                / "acks"
                / f"{result['message_id']}.json"
            )
            deadline = time.monotonic() + 15.0
            while not acknowledgement_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not acknowledgement_path.is_file():
                raise RuntimeBridgeError("PLUGIN_DRAIN_HOLD_ACK_TIMEOUT")
            acknowledgement = RuntimeHoldAcknowledgement.model_validate_json(
                acknowledgement_path.read_text(encoding="utf-8")
            )
            if not acknowledgement.side_effects_inhibited or not all(
                acknowledgement.deterministic_gates.values()
            ):
                raise RuntimeBridgeError("PLUGIN_DRAIN_HOLD_ACK_REJECTED")
            held.append(thread_id)
        return held

    def shutdown(self) -> None:
        with self._lock:
            active = list(self._active_runs.items())
        for thread_id, _run in active:
            try:
                self.submit_message(thread_id, "应用正在关闭，请立即进入安全悬停并降落")
            except (KeyError, RuntimeError):
                continue
        deadline = time.monotonic() + 5.0
        for _thread_id, run in active:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                run.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                run.process.terminate()
