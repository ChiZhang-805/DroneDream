from __future__ import annotations

import hashlib
import io
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.runtime_manager import RuntimeBridgeError, RuntimeManager
from dronedream_agent_app.storage import AppStore


def _runtime_resources(root: Path) -> Path:
    runtime = root / "runtime"
    (runtime / "wheels").mkdir(parents=True)
    (runtime / "ros_ws" / "src").mkdir(parents=True)
    files = {
        "requirements-linux.txt": b"pydantic==2.13.4\n",
        "px4_offboard_track_executor.py": b"# executor\n",
        "px4_checkpoint_executor.py": b"# checkpoint\n",
        "wheels/dependency.whl": b"wheel",
    }
    entries = []
    for relative, content in files.items():
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    (runtime / "runtime-manifest.json").write_text(
        json.dumps({"schema_version": "1.0.0", "files": entries}), encoding="utf-8"
    )
    return root


def _manager(store_root: Path, resource_root: Path) -> RuntimeManager:
    store = AppStore(store_root)
    return RuntimeManager(store, resource_root, PluginManager(store))


def test_runtime_status_distinguishes_base_stack_from_provisioning(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "store", _runtime_resources(tmp_path / "res"))
    results = iter(
        (
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 1, "", ""),
        )
    )
    monkeypatch.setattr(manager, "_bash", lambda _script, timeout: next(results))

    status = manager.status()

    assert status == {
        "distribution": "DroneDreamRuntime",
        "runtime_available": True,
        "resources_ready": True,
        "provisioned": False,
        "issue": "RUNTIME_PROVISION_REQUIRED",
    }


def test_runtime_status_fails_closed_when_wsl_is_missing(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "store", _runtime_resources(tmp_path / "res"))

    def unavailable(_script: str, *, timeout: float):
        raise RuntimeBridgeError("DRONEDREAM_RUNTIME_UNAVAILABLE")

    monkeypatch.setattr(manager, "_bash", unavailable)

    status = manager.status()

    assert status["runtime_available"] is False
    assert status["provisioned"] is False
    assert status["issue"] == "DRONEDREAM_RUNTIME_UNAVAILABLE"


def test_runtime_resource_hash_tampering_is_rejected(tmp_path):
    resources = _runtime_resources(tmp_path / "res")
    manager = _manager(tmp_path / "store", resources)
    (resources / "runtime" / "px4_checkpoint_executor.py").write_text(
        "# changed\n", encoding="utf-8"
    )

    assert manager._resources_ready() is False


def test_runtime_setup_reports_only_completed_evidence_checkpoints(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "store", _runtime_resources(tmp_path / "res"))
    monkeypatch.setattr(
        "dronedream_agent_app.runtime_manager._wsl_path",
        lambda path: path.resolve().as_posix(),
    )
    monkeypatch.setattr(
        manager,
        "status",
        lambda: {
            "distribution": "DroneDreamRuntime",
            "runtime_available": True,
            "resources_ready": True,
            "provisioned": True,
            "issue": None,
        },
    )

    def successful_step(script: str, *, timeout: float):
        del timeout
        output = "AUTONOMY_RUNTIME_READY\n" if "AUTONOMY_RUNTIME_READY" in script else ""
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr(manager, "_bash", successful_step)

    started = manager.start_setup()
    assert started["phase"] == "queued"
    assert started["progress"] == 0
    deadline = time.monotonic() + 2
    while manager.setup_progress()["active"] and time.monotonic() < deadline:
        time.sleep(0.01)

    completed = manager.setup_progress()
    assert completed["phase"] == "completed"
    assert completed["progress"] == 100
    assert completed["active"] is False
    assert completed["error"] is None


def test_runtime_setup_stops_at_failed_base_runtime_check(tmp_path, monkeypatch):
    manager = _manager(tmp_path / "store", _runtime_resources(tmp_path / "res"))
    monkeypatch.setattr(
        manager,
        "status",
        lambda: {
            "distribution": "DroneDreamRuntime",
            "runtime_available": False,
            "resources_ready": True,
            "provisioned": False,
            "issue": "DRONEDREAM_RUNTIME_UNAVAILABLE",
        },
    )

    manager.start_setup()
    deadline = time.monotonic() + 2
    while manager.setup_progress()["active"] and time.monotonic() < deadline:
        time.sleep(0.01)

    failed = manager.setup_progress()
    assert failed["phase"] == "failed"
    assert failed["progress"] == 12
    assert failed["active"] is False
    assert failed["error"] == "DRONEDREAM_RUNTIME_UNAVAILABLE"
    assert failed["failed_phase"] == "checkingBaseRuntime"


def test_runtime_secret_session_uses_wsl_safe_lf_newlines(tmp_path):
    path = tmp_path / "session.env"

    RuntimeManager._write_secret_session(
        path,
        provider="deepseek",
        model_id="deepseek-v4-flash",
        grant="private-value",
        gateway="https://api.deepseek.com",
    )

    payload = path.read_bytes()
    assert b"\r" not in payload
    assert payload.endswith(b"\n")
    assert b"private-value" in payload


def test_execute_keeps_supervisor_files_outside_empty_simulation_run(tmp_path, monkeypatch):
    store = AppStore(tmp_path / "store")
    repository = Path(__file__).resolve().parents[1]
    store.seed_bundled_assets(repository / "assets" / "default")
    plugins = PluginManager(store)
    thread = store.create_thread("runtime layout", "gpt-5.4")
    thread_id = str(thread["thread_id"])
    store.patch_thread(
        thread_id,
        {
            "selected_map_id": "dronedream.school-map.v1",
            "selected_vehicle_id": "dronedream.my-drone.v1",
        },
    )
    plan_root = tmp_path / "plan"
    plan_root.mkdir()
    (plan_root / "prepared-mission.json").write_text("{}\n", encoding="utf-8")
    store.append_message(
        thread_id,
        role="assistant",
        kind="plan",
        content="prepared",
        metadata={"output_dir": str(plan_root), "contract_id": "mission-layout"},
    )
    snapshot = plugins.snapshot(thread_id=thread_id)
    assert store.latest_plugin_snapshot(thread_id)["snapshot_id"] == snapshot.snapshot_id
    store.set_thread_state(thread_id, "awaiting_confirmation")
    resources = _runtime_resources(tmp_path / "resources")
    manager = RuntimeManager(store, resources, plugins)
    monkeypatch.setattr(
        "dronedream_agent_app.runtime_manager._wsl_path",
        lambda path: path.resolve().as_posix(),
    )
    monkeypatch.setattr(manager, "status", lambda: {"provisioned": True})
    monkeypatch.setattr(
        "dronedream_agent_app.runtime_manager.PreparedMission.model_validate_json",
        lambda _payload: SimpleNamespace(
            simulation_capabilities={
                "simulator": {"engine": "gazebo-harmonic"},
                "native_runtime": {
                    "transport": {"implementation": "px4-uxrce-dds"},
                    "watchdog": {
                        "deadline_ms": 250,
                        "startup_deadline_ms": 10_000,
                    },
                },
            }
        ),
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()

        def wait(self) -> int:
            time.sleep(0.05)
            return 1

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())

    launched = manager.execute(
        thread_id=thread_id,
        model_id="gpt-5.4",
        model_grant="private-value",
        gateway_base_url="https://example.supabase.co/functions/v1/model-gateway",
    )

    execution_root = Path(str(launched["execution_root"]))
    simulation_root = Path(str(launched["run_dir"]))
    assert simulation_root == execution_root / "simulation"
    assert execution_root.is_dir()
    assert not simulation_root.exists()
    assert (execution_root / "desktop-runtime.stdout.log").is_file()
    assert (execution_root / "desktop-runtime.stderr.log").is_file()
