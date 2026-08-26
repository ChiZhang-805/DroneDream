#!/usr/bin/env python3
"""Atomically move legacy Runtime execution paths onto the active Engine Pack."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import stat
import tempfile
from pathlib import Path

_MAX_ENV_BYTES = 1024 * 1024
_ACTIVE_ROOT = Path("/opt/dronedream/engine/current")
_ENVIRONMENT = Path("/etc/dronedream/runtime.env")
_LEGACY_ROOT = "/opt/dronedream/source"
_ENGINE_ROOT = "/opt/dronedream/engine/current"

_EXPECTED = {
    "REAL_SIMULATOR_COMMAND": (
        '"/opt/dronedream/venv/bin/python '
        '/opt/dronedream/engine/current/scripts/simulators/px4_gazebo_runner.py"'
    ),
    "PX4_GAZEBO_WORKDIR": _ENGINE_ROOT,
    "PX4_GAZEBO_LAUNCH_COMMAND": (
        '"/opt/dronedream/venv/bin/python '
        "/opt/dronedream/engine/current/scripts/simulators/local_px4_launch_wrapper.py "
        "--run-dir {run_dir} --input {trial_input} --params {params_json} "
        "--px4-params {px4_params_json} --track {track_json} "
        "--telemetry {telemetry_json} --stdout-log {stdout_log} "
        "--stderr-log {stderr_log} --vehicle {vehicle} --airframe {airframe} "
        "--simulator-model {simulator_model} --world {world} "
        '--px4-version {px4_version} --headless {headless}"'
    ),
    "PX4_OFFBOARD_EXECUTOR_COMMAND": (
        '"/opt/dronedream/venv/bin/python '
        '/opt/dronedream/engine/current/scripts/simulators/px4_offboard_track_executor.py"'
    ),
}
_LEGACY = {key: value.replace(_ENGINE_ROOT, _LEGACY_ROOT) for key, value in _EXPECTED.items()}
_REQUIRED_ACTIVE_FILES = (
    "engine-pack-manifest.json",
    "scripts/simulators/px4_gazebo_runner.py",
    "scripts/simulators/local_px4_launch_wrapper.py",
    "scripts/simulators/px4_offboard_track_executor.py",
)


class ReconcileError(RuntimeError):
    """The installed Runtime is not safe to reconcile automatically."""


def _regular_file_bytes(path: Path, *, label: str, max_bytes: int) -> tuple[os.stat_result, bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReconcileError(f"{label} could not be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ReconcileError(f"{label} must be a regular, non-symlink file")
    if metadata.st_size > max_bytes:
        raise ReconcileError(f"{label} exceeds the bounded size limit")
    try:
        with path.open("rb") as stream:
            payload = stream.read(max_bytes + 1)
    except OSError as exc:
        raise ReconcileError(f"{label} could not be read") from exc
    if len(payload) > max_bytes:
        raise ReconcileError(f"{label} exceeds the bounded size limit")
    return metadata, payload


def _verify_active_root(active_root: Path) -> dict[str, str]:
    if not active_root.is_symlink():
        raise ReconcileError("Engine Pack active root is not a symbolic link")
    try:
        release = active_root.resolve(strict=True)
        releases_root = (active_root.parent / "releases").resolve(strict=True)
    except OSError as exc:
        raise ReconcileError("Engine Pack active root could not be resolved") from exc
    if release.parent != releases_root or len(release.name) != 64:
        raise ReconcileError("Engine Pack active root points outside the managed release directory")
    try:
        int(release.name, 16)
    except ValueError as exc:
        raise ReconcileError("Engine Pack active release ID is invalid") from exc
    for relative in _REQUIRED_ACTIVE_FILES:
        candidate = active_root / relative
        try:
            metadata = candidate.stat()
        except OSError as exc:
            raise ReconcileError(f"active Engine Pack is missing {relative}") from exc
        if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ReconcileError(f"active Engine Pack file is unsafe: {relative}")
    _, manifest_bytes = _regular_file_bytes(
        active_root / "engine-pack-manifest.json",
        label="Engine Pack manifest",
        max_bytes=8 * 1024 * 1024,
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReconcileError("Engine Pack manifest is invalid JSON") from exc
    expected_pack_id = f"sha256:{release.name}"
    if not isinstance(manifest, dict) or manifest.get("packId") != expected_pack_id:
        raise ReconcileError("Engine Pack active release does not match its manifest packId")
    source = manifest.get("source")
    source_commit = source.get("gitCommit") if isinstance(source, dict) else None
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise ReconcileError("Engine Pack manifest source commit is invalid")
    return {"packId": expected_pack_id, "sourceCommit": source_commit}


def _parse_environment(payload: bytes) -> tuple[list[str], dict[str, tuple[int, str]]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise ReconcileError("Runtime environment is not UTF-8") from exc
    lines = text.splitlines(keepends=True)
    targets: dict[str, tuple[int, str]] = {}
    for index, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key not in _EXPECTED:
            continue
        if key in targets:
            raise ReconcileError(f"Runtime environment contains duplicate {key}")
        targets[key] = (index, value)
    missing = sorted(set(_EXPECTED) - set(targets))
    if missing:
        raise ReconcileError("Runtime environment is missing managed execution path keys")
    for key, (_, value) in targets.items():
        if value not in {_EXPECTED[key], _LEGACY[key]}:
            raise ReconcileError(f"Runtime environment has a custom value for {key}")
    return lines, targets


def _atomic_replace(path: Path, payload: bytes, metadata: os.stat_result) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if hasattr(os, "chown"):
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def reconcile(environment: Path, active_root: Path, *, apply: bool) -> dict[str, object]:
    active = _verify_active_root(active_root)
    metadata, payload = _regular_file_bytes(
        environment,
        label="Runtime environment",
        max_bytes=_MAX_ENV_BYTES,
    )
    lines, targets = _parse_environment(payload)
    legacy_keys = sorted(key for key, (_, value) in targets.items() if value == _LEGACY[key])
    if not legacy_keys:
        return {
            "schemaVersion": 1,
            "status": "current",
            "changed": False,
            "updatedKeys": [],
            **active,
        }
    if not apply:
        return {
            "schemaVersion": 1,
            "status": "legacy",
            "changed": False,
            "updatedKeys": legacy_keys,
            **active,
        }
    for key in legacy_keys:
        index, _ = targets[key]
        newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
        lines[index] = f"{key}={_EXPECTED[key]}{newline}"
    updated = "".join(lines).encode("utf-8")
    _atomic_replace(environment, updated, metadata)
    _, verified_payload = _regular_file_bytes(
        environment,
        label="reconciled Runtime environment",
        max_bytes=_MAX_ENV_BYTES,
    )
    _, verified_targets = _parse_environment(verified_payload)
    if any(value != _EXPECTED[key] for key, (_, value) in verified_targets.items()):
        raise ReconcileError("Runtime environment reconciliation did not persist exact paths")
    return {
        "schemaVersion": 1,
        "status": "reconciled",
        "changed": True,
        "updatedKeys": legacy_keys,
        **active,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, default=_ENVIRONMENT)
    parser.add_argument("--active-root", type=Path, default=_ACTIVE_ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        receipt = reconcile(args.environment, args.active_root, apply=args.apply)
    except ReconcileError as exc:
        parser.exit(2, f"Runtime execution path reconciliation failed: {exc}\n")
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
