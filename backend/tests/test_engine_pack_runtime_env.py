from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "desktop"
    / "src-tauri"
    / "scripts"
    / "reconcile_engine_pack_runtime_env.py"
)
SPEC = importlib.util.spec_from_file_location("dronedream_runtime_env_reconciler", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
reconciler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reconciler
SPEC.loader.exec_module(reconciler)


def _environment_text(*, legacy: bool) -> str:
    values = reconciler._LEGACY if legacy else reconciler._EXPECTED
    return "".join(
        (
            "# preserved operator configuration\n",
            "APP_SECRET_KEY=must-not-appear-in-receipts\n",
            f"REAL_SIMULATOR_COMMAND={values['REAL_SIMULATOR_COMMAND']}\n",
            f"PX4_GAZEBO_WORKDIR={values['PX4_GAZEBO_WORKDIR']}\n",
            f"PX4_GAZEBO_LAUNCH_COMMAND={values['PX4_GAZEBO_LAUNCH_COMMAND']}\n",
            f"PX4_OFFBOARD_EXECUTOR_COMMAND={values['PX4_OFFBOARD_EXECUTOR_COMMAND']}\n",
            "UNRELATED_SETTING=preserved\n",
        )
    )


def _stub_active_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reconciler,
        "_verify_active_root",
        lambda _path: {"packId": f"sha256:{'a' * 64}", "sourceCommit": "b" * 40},
    )


def _service_text(service_name: str, *, legacy: bool, custom_line: str = "") -> str:
    spec = reconciler._SERVICE_SPECS[service_name]
    transitions = {
        directive: values[0 if legacy else 1]
        for directive, values in spec["transitions"].items()
    }
    pythonpath = "" if legacy else f"{spec['pythonpath']}\n"
    return "".join(
        (
            "[Unit]\nDescription=test unit\n[Service]\n",
            f"{transitions['WorkingDirectory=']}\n",
            pythonpath,
            (
                f"{transitions['ExecStartPre=']}\n"
                if "ExecStartPre=" in transitions
                else ""
            ),
            "ExecStart=/usr/bin/true\n",
            custom_line,
        )
    )


def test_runtime_env_reconciler_reports_legacy_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    original = _environment_text(legacy=True)
    environment.write_text(original, encoding="utf-8")

    receipt = reconciler.reconcile(environment, tmp_path / "current", apply=False)

    assert receipt["status"] == "legacy"
    assert receipt["changed"] is False
    assert receipt["updatedKeys"] == sorted(reconciler._EXPECTED)
    assert environment.read_text(encoding="utf-8") == original
    assert "must-not-appear" not in str(receipt)


def test_runtime_env_reconciler_atomically_updates_only_managed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    environment.write_text(_environment_text(legacy=True), encoding="utf-8")
    environment.chmod(0o640)

    receipt = reconciler.reconcile(environment, tmp_path / "current", apply=True)

    updated = environment.read_text(encoding="utf-8")
    assert receipt["status"] == "reconciled"
    assert receipt["changed"] is True
    assert receipt["updatedKeys"] == sorted(reconciler._EXPECTED)
    assert "/opt/dronedream/source" not in updated
    assert "APP_SECRET_KEY=must-not-appear-in-receipts" in updated
    assert "UNRELATED_SETTING=preserved" in updated
    if os.name == "posix":
        assert stat.S_IMODE(environment.stat().st_mode) == 0o640
    assert "must-not-appear" not in str(receipt)


def test_runtime_env_reconciler_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    environment.write_text(_environment_text(legacy=False), encoding="utf-8")

    receipt = reconciler.reconcile(environment, tmp_path / "current", apply=True)

    assert receipt["status"] == "current"
    assert receipt["changed"] is False
    assert receipt["updatedKeys"] == []


def test_runtime_reconciler_moves_api_and_worker_services_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    environment.write_text(_environment_text(legacy=False), encoding="utf-8")
    api_service = tmp_path / "dronedream-api.service"
    worker_service = tmp_path / "dronedream-worker.service"
    api_service.write_text(
        _service_text("dronedream-api.service", legacy=True),
        encoding="utf-8",
    )
    worker_service.write_text(
        _service_text("dronedream-worker.service", legacy=True),
        encoding="utf-8",
    )
    api_service.chmod(0o644)
    worker_service.chmod(0o640)

    dry_run = reconciler.reconcile(
        environment,
        tmp_path / "current",
        apply=False,
        api_service=api_service,
        worker_service=worker_service,
    )
    assert dry_run["status"] == "legacy"
    assert dry_run["changed"] is False
    assert dry_run["updatedKeys"] == []
    assert dry_run["updatedServices"] == [
        "dronedream-api.service",
        "dronedream-worker.service",
    ]
    assert "/opt/dronedream/source" in api_service.read_text(encoding="utf-8")

    receipt = reconciler.reconcile(
        environment,
        tmp_path / "current",
        apply=True,
        api_service=api_service,
        worker_service=worker_service,
    )
    assert receipt["status"] == "reconciled"
    assert receipt["updatedServices"] == dry_run["updatedServices"]
    for service_name, service_path in (
        ("dronedream-api.service", api_service),
        ("dronedream-worker.service", worker_service),
    ):
        updated = service_path.read_text(encoding="utf-8")
        assert "/opt/dronedream/source" not in updated
        assert reconciler._SERVICE_SPECS[service_name]["pythonpath"] in updated
    if os.name == "posix":
        assert stat.S_IMODE(api_service.stat().st_mode) == 0o644
        assert stat.S_IMODE(worker_service.stat().st_mode) == 0o640

    current = reconciler.reconcile(
        environment,
        tmp_path / "current",
        apply=True,
        api_service=api_service,
        worker_service=worker_service,
    )
    assert current["status"] == "current"
    assert current["changed"] is False
    assert current["updatedServices"] == []


def test_runtime_reconciler_rejects_custom_or_duplicate_service_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    environment.write_text(_environment_text(legacy=False), encoding="utf-8")
    api_service = tmp_path / "dronedream-api.service"
    worker_service = tmp_path / "dronedream-worker.service"
    worker_service.write_text(
        _service_text("dronedream-worker.service", legacy=True),
        encoding="utf-8",
    )

    api_service.write_text(
        _service_text("dronedream-api.service", legacy=True).replace(
            "WorkingDirectory=/opt/dronedream/source/backend",
            "WorkingDirectory=/operator/custom",
        ),
        encoding="utf-8",
    )
    with pytest.raises(reconciler.ReconcileError, match="custom managed WorkingDirectory"):
        reconciler.reconcile(
            environment,
            tmp_path / "current",
            apply=True,
            api_service=api_service,
            worker_service=worker_service,
        )

    api_service.write_text(
        _service_text(
            "dronedream-api.service",
            legacy=False,
            custom_line=(
                f"{reconciler._SERVICE_SPECS['dronedream-api.service']['pythonpath']}\n"
            ),
        ),
        encoding="utf-8",
    )
    with pytest.raises(reconciler.ReconcileError, match="duplicate managed PYTHONPATH"):
        reconciler.reconcile(
            environment,
            tmp_path / "current",
            apply=True,
            api_service=api_service,
            worker_service=worker_service,
        )


def test_runtime_env_reconciler_matches_fresh_runtime_template() -> None:
    template = (
        Path(__file__).resolve().parents[2] / "runtime" / "config" / "runtime.env.default"
    ).read_text(encoding="utf-8")
    values = {}
    for raw in template.splitlines():
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key] = value

    assert {key: values[key] for key in reconciler._EXPECTED} == reconciler._EXPECTED


def test_runtime_env_reconciler_rejects_custom_or_duplicate_managed_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_root(monkeypatch)
    environment = tmp_path / "runtime.env"
    custom = _environment_text(legacy=True).replace(
        f"PX4_GAZEBO_WORKDIR={reconciler._LEGACY['PX4_GAZEBO_WORKDIR']}",
        "PX4_GAZEBO_WORKDIR=/operator/custom",
    )
    environment.write_text(custom, encoding="utf-8")
    with pytest.raises(reconciler.ReconcileError, match="custom value"):
        reconciler.reconcile(environment, tmp_path / "current", apply=True)

    duplicate = _environment_text(legacy=True) + (
        f"PX4_GAZEBO_WORKDIR={reconciler._LEGACY['PX4_GAZEBO_WORKDIR']}\n"
    )
    environment.write_text(duplicate, encoding="utf-8")
    with pytest.raises(reconciler.ReconcileError, match="duplicate"):
        reconciler.reconcile(environment, tmp_path / "current", apply=True)
