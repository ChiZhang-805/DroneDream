#!/usr/bin/env python3
"""Install a verified Engine Pack into a versioned Runtime Base slot."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

DEFAULT_ENGINE_ROOT = Path("/opt/dronedream/engine")
DEFAULT_RUNTIME_MANIFEST = Path("/opt/dronedream/runtime-manifest.json")
DEFAULT_STATE_PATH = Path("/var/lib/dronedream/engine-pack-state.json")
DEFAULT_DATABASE = Path("/var/lib/dronedream/dronedream.db")
ENGINE_SERVICES = ("dronedream-worker.service", "dronedream-api.service")
HEALTH_URL = "http://127.0.0.1:8000/health/ready"
ACTIVE_JOB_STATUSES = ("QUEUED", "RUNNING", "AGGREGATING", "FINALIZING")
SYSTEMCTL = Path("/usr/bin/systemctl")
ALEMBIC = Path("/opt/dronedream/venv/bin/alembic")


class EnginePackInstallError(RuntimeError):
    """Raised when activation cannot be completed without losing safety."""


def load_engine_pack_tool() -> ModuleType:
    candidates = (
        Path("/usr/lib/dronedream/engine_pack.py"),
        Path(__file__).resolve().parents[2] / "engine-pack" / "tools" / "engine_pack.py",
    )
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("dronedream_engine_pack_tool", path)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    raise EnginePackInstallError("Engine Pack verification tool is unavailable")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EnginePackInstallError(f"unable to read JSON contract: {path}") from error
    if not isinstance(value, dict):
        raise EnginePackInstallError(f"JSON contract is not an object: {path}")
    return value


def assert_runtime_compatible(pack: dict[str, Any], runtime: dict[str, Any]) -> None:
    compatibility = pack.get("runtimeCompatibility")
    details = runtime.get("componentDetails")
    locks = runtime.get("locks")
    if (
        not isinstance(compatibility, dict)
        or not isinstance(details, dict)
        or not isinstance(locks, dict)
    ):
        raise EnginePackInstallError("Runtime compatibility metadata is incomplete")
    px4 = details.get("px4")
    gazebo = details.get("gazebo")
    python = details.get("python")
    if (
        not isinstance(px4, dict)
        or not isinstance(gazebo, dict)
        or not isinstance(python, dict)
    ):
        raise EnginePackInstallError("Runtime component details are incomplete")
    observed = {
        "runtimeId": runtime.get("runtimeId"),
        "runtimeVersion": runtime.get("version"),
        "pythonVersion": python.get("version"),
        "px4Commit": px4.get("commit"),
        "gazeboVersion": f"{gazebo.get('release')}@{gazebo.get('packageVersion')}",
        "dependencyLockSha256": locks.get("pythonRequirementsSha256"),
    }
    mismatches = [
        key for key, expected in compatibility.items() if observed.get(key) != expected
    ]
    if mismatches:
        raise EnginePackInstallError(
            "Engine Pack requires a different Runtime Base: " + ", ".join(sorted(mismatches))
        )


def release_name(pack_id: str) -> str:
    prefix = "sha256:"
    if not pack_id.startswith(prefix) or len(pack_id) != len(prefix) + 64:
        raise EnginePackInstallError("Engine Pack ID is invalid")
    return pack_id[len(prefix) :]


def safe_extract(archive_path: Path, destination: Path, records: list[dict[str, Any]]) -> None:
    expected = {record["path"] for record in records}
    with tarfile.open(archive_path, mode="r:gz") as archive:
        payload_members: dict[str, tarfile.TarInfo] = {}
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise EnginePackInstallError("Engine Pack archive contains an unsafe member")
            if member.name.startswith("payload/"):
                inner = member.name.removeprefix("payload/")
                if inner in payload_members:
                    raise EnginePackInstallError("Engine Pack archive contains a duplicate payload")
                payload_members[inner] = member
        if set(payload_members) != expected:
            raise EnginePackInstallError("Engine Pack payload does not match its verified manifest")
        for relative in sorted(payload_members):
            target = destination / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(payload_members[relative])
            if source is None:
                raise EnginePackInstallError(f"Engine Pack payload cannot be read: {relative}")
            with target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def replace_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve(strict=True) == target.resolve(strict=True):
        return
    temporary = link.with_name(f".{link.name}.{uuid.uuid4().hex}.tmp")
    temporary.symlink_to(target)
    os.replace(temporary, link)


def current_release(current: Path) -> Path | None:
    if not current.is_symlink():
        return None
    try:
        target = current.resolve(strict=True)
        releases = (current.parent / "releases").resolve(strict=True)
    except OSError as error:
        raise EnginePackInstallError("Engine Pack current release link is invalid") from error
    if target.parent != releases or len(target.name) != 64:
        raise EnginePackInstallError(
            "Engine Pack current release points outside the managed release directory"
        )
    try:
        int(target.name, 16)
    except ValueError as error:
        raise EnginePackInstallError("Engine Pack current release ID is invalid") from error
    return target


def verify_release_directory(
    tool: ModuleType,
    release: Path,
    manifest: dict[str, Any],
    manifest_bytes: bytes,
) -> None:
    manifest_path = release / "engine-pack-manifest.json"
    try:
        if manifest_path.is_symlink() or manifest_path.read_bytes() != manifest_bytes:
            raise EnginePackInstallError("Engine Pack release manifest was modified")
        for record in manifest["files"]:
            path = release / Path(*PurePosixPath(record["path"]).parts)
            if path.is_symlink() or not path.is_file():
                raise EnginePackInstallError(
                    f"Engine Pack release file is missing or unsafe: {record['path']}"
                )
            if (
                path.stat().st_size != record["sizeBytes"]
                or tool.sha256_file(path) != record["sha256"]
            ):
                raise EnginePackInstallError(
                    f"Engine Pack release file failed verification: {record['path']}"
                )
    except OSError as error:
        raise EnginePackInstallError("Engine Pack release directory cannot be verified") from error


def ensure_no_active_experiments(database: Path) -> None:
    """Fail closed before replacing code used by a queued or running experiment."""

    if not database.is_file():
        return
    try:
        connection = sqlite3.connect(
            f"file:{database}?mode=ro",
            uri=True,
            timeout=5,
        )
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            active_jobs = 0
            active_trials = 0
            if "jobs" in tables:
                active_jobs = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE status IN (?, ?, ?, ?)",
                        ACTIVE_JOB_STATUSES,
                    ).fetchone()[0]
                )
            if "trials" in tables:
                active_trials = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM trials WHERE status = ?",
                        ("RUNNING",),
                    ).fetchone()[0]
                )
        finally:
            connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        raise EnginePackInstallError(
            "Engine Pack update could not verify that all experiments are idle"
        ) from error
    if active_jobs or active_trials:
        raise EnginePackInstallError(
            "Engine Pack update is waiting for active experiments to finish "
            f"({active_jobs} jobs, {active_trials} trials)"
        )


def run_systemctl(action: str, services: tuple[str, ...]) -> None:
    if action not in {"start", "stop"}:
        raise EnginePackInstallError("unsupported systemctl action")
    if not services or any(service not in ENGINE_SERVICES for service in services):
        raise EnginePackInstallError("unsupported Engine Pack service")
    if not SYSTEMCTL.is_file():
        raise EnginePackInstallError("systemctl is unavailable")
    result = subprocess.run(  # noqa: S603 - fixed executable and allowlisted arguments.
        [str(SYSTEMCTL), action, *services],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise EnginePackInstallError(f"systemctl {action} failed: {detail[:1000]}")


def backup_sqlite(database: Path, backup_root: Path) -> Path | None:
    if not database.is_file():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"dronedream-{int(time.time())}-{uuid.uuid4().hex}.db"
    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backup.chmod(0o600)
    return backup


def restore_sqlite(backup: Path | None, database: Path) -> None:
    if backup is None:
        return
    temporary = database.with_name(f".{database.name}.{uuid.uuid4().hex}.restore")
    shutil.copyfile(backup, temporary)
    temporary.chmod(0o600)
    os.replace(temporary, database)


def migrate_database(release: Path) -> None:
    if not ALEMBIC.is_file():
        raise EnginePackInstallError("Engine Pack migration tool is unavailable")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = f"{release / 'backend'}:{release / 'worker'}"
    result = subprocess.run(  # noqa: S603 - fixed executable and verified release paths.
        [
            str(ALEMBIC),
            "-c",
            str(release / "backend" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=release / "backend",
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise EnginePackInstallError(
            f"Engine Pack database migration failed: {result.stderr[-1000:]}"
        )


def wait_healthy(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed loopback HTTP endpoint.
                HEALTH_URL,
                timeout=3,
            ) as response:
                payload = json.loads(response.read(65_537))
                if response.status == 200 and payload.get("success") is True:
                    return
                last_error = f"unexpected health payload ({response.status})"
        except Exception as error:  # bounded retry converts the final failure below
            last_error = str(error)
        time.sleep(2)
    raise EnginePackInstallError(f"Engine Pack health check failed: {last_error}")


def install_pack(
    *,
    descriptor_path: Path,
    archive_path: Path,
    runtime_manifest_path: Path,
    engine_root: Path,
    state_path: Path,
    manage_services: bool,
) -> dict[str, Any]:
    tool = load_engine_pack_tool()
    descriptor, manifest = tool.verified_bundle(descriptor_path, archive_path)
    runtime = load_json(runtime_manifest_path)
    assert_runtime_compatible(manifest, runtime)
    release_id = release_name(manifest["packId"])
    releases = engine_root / "releases"
    staging_root = engine_root / "staging"
    current = engine_root / "current"
    releases.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    target = releases / release_id
    previous = current_release(current)
    manifest_bytes = (
        descriptor_path.parent / descriptor["manifest"]["filename"]
    ).read_bytes()
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise EnginePackInstallError(
            "Engine Pack release target is not a managed ordinary directory"
        )
    if not target.exists():
        staging = Path(tempfile.mkdtemp(prefix=f"{release_id}.", dir=staging_root))
        try:
            safe_extract(archive_path, staging, manifest["files"])
            (staging / "engine-pack-manifest.json").write_bytes(manifest_bytes)
            directories = (path for path in staging.rglob("*") if path.is_dir())
            for directory in sorted(directories, reverse=True):
                directory.chmod(0o755)
            staging.chmod(0o755)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    verify_release_directory(tool, target, manifest, manifest_bytes)
    backup = None
    api_stop_attempted = False
    worker_stop_attempted = False
    switched = False
    if manage_services:
        ensure_no_active_experiments(DEFAULT_DATABASE)
    try:
        if manage_services:
            # Close the API intake first, then check again so a job queued in
            # the preflight race window cannot be interrupted by this update.
            api_stop_attempted = True
            run_systemctl("stop", ("dronedream-api.service",))
            ensure_no_active_experiments(DEFAULT_DATABASE)
            worker_stop_attempted = True
            run_systemctl("stop", ("dronedream-worker.service",))
            backup = backup_sqlite(DEFAULT_DATABASE, state_path.parent / "engine-pack-backups")
        replace_symlink(current, target)
        switched = True
        if manage_services:
            migrate_database(target)
            run_systemctl("start", tuple(reversed(ENGINE_SERVICES)))
            wait_healthy()
        activated_at = (
            dt.datetime.now(dt.timezone.utc)
            if manage_services
            else dt.datetime.fromtimestamp(
                manifest["source"]["sourceDateEpoch"],
                tz=dt.timezone.utc,
            )
        )
        receipt = {
            "schemaVersion": 1,
            "currentPackId": manifest["packId"],
            "previousPackId": f"sha256:{previous.name}" if previous is not None else None,
            "sourceCommit": manifest["source"]["gitCommit"],
            "archiveSha256": descriptor["archive"]["sha256"],
            "activatedAt": activated_at.isoformat(),
            "runtimeId": runtime["runtimeId"],
            "runtimeVersion": runtime["version"],
        }
        atomic_write_json(state_path, receipt)
        return receipt
    except Exception:
        if manage_services and worker_stop_attempted:
            with contextlib.suppress(EnginePackInstallError):
                run_systemctl("stop", ENGINE_SERVICES)
        if switched:
            if previous is not None:
                replace_symlink(current, previous)
            elif current.is_symlink():
                current.unlink()
        if manage_services and worker_stop_attempted:
            restore_sqlite(backup, DEFAULT_DATABASE)
        if manage_services and api_stop_attempted and (previous is not None or not switched):
            run_systemctl("start", tuple(reversed(ENGINE_SERVICES)))
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--engine-root", type=Path, default=DEFAULT_ENGINE_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--no-services", action="store_true")
    parser.add_argument("--check-idle", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_idle:
            if args.descriptor is not None or args.archive is not None or args.no_services:
                raise EnginePackInstallError("idle check does not accept installation arguments")
            ensure_no_active_experiments(DEFAULT_DATABASE)
            print(json.dumps({"idle": True}, sort_keys=True))
            return 0
        if args.descriptor is None or args.archive is None:
            raise EnginePackInstallError("descriptor and archive are required for installation")
        receipt = install_pack(
            descriptor_path=args.descriptor.resolve(),
            archive_path=args.archive.resolve(),
            runtime_manifest_path=args.runtime_manifest.resolve(),
            engine_root=args.engine_root.resolve(),
            state_path=args.state_path.resolve(),
            manage_services=not args.no_services,
        )
    except (EnginePackInstallError, OSError, ValueError, tarfile.TarError) as error:
        print(f"engine pack install error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
