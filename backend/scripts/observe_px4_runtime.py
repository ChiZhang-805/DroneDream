"""Freeze a read-only identity observation of the DroneDreamRuntime WSL distro."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.simulator.physical_campaign_evidence import (  # noqa: E402
    build_runtime_observation,
)

_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "px4_git_head",
        (
            "git",
            "-c",
            "safe.directory=/opt/PX4-Autopilot",
            "-C",
            "/opt/PX4-Autopilot",
            "rev-parse",
            "HEAD",
        ),
    ),
    ("gazebo_sim_version", ("gz", "sim", "--version")),
    ("python_version", ("/opt/dronedream/venv/bin/python3", "--version")),
    (
        "mavsdk_version",
        (
            "/opt/dronedream/venv/bin/python3",
            "-c",
            "import importlib.metadata as m; print(m.version('mavsdk'))",
        ),
    ),
    (
        "pyulog_version",
        (
            "/opt/dronedream/venv/bin/python3",
            "-c",
            "import importlib.metadata as m; print(m.version('pyulog'))",
        ),
    ),
    ("ubuntu_release", ("cat", "/etc/os-release")),
    ("gazebo_harmonic_package", ("dpkg-query", "-W", "gz-harmonic")),
    # Exclude the host name: kernel/release/architecture are relevant evidence,
    # while a local machine name is neither required nor appropriate to freeze.
    ("kernel", ("uname", "-srmo")),
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_wsl(*, distribution: str, name: str, argv: tuple[str, ...]) -> dict[str, Any]:
    command = ["wsl.exe", "-d", distribution, "--", *argv]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot observe Runtime command {name}: {exc}") from exc
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    record = {
        "name": name,
        "argv": command,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
    }
    if completed.returncode != 0:
        raise ValueError(
            f"Runtime observation command {name} failed with "
            f"{completed.returncode}: {stderr}"
        )
    return record


def _command_stdout(records: list[dict[str, Any]], name: str) -> str:
    matches = [str(record["stdout"]) for record in records if record["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"Runtime observation command result is missing: {name}")
    return matches[0]


def _parse_os_release(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in value.splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        result[key] = raw.strip().strip('"')
    return result


def _load_runtime_release(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Runtime release manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Runtime release manifest must contain an object")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-release",
        type=Path,
        required=True,
        help="Frozen Runtime release manifest that names the build and PX4 commit.",
    )
    parser.add_argument("--observer-commit", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--distribution", default="DroneDreamRuntime")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Runtime observation output already exists: {output}")
    release = _load_runtime_release(args.runtime_release.resolve())
    runtime = release.get("runtime")
    source = release.get("source")
    if not isinstance(runtime, dict) or not isinstance(source, dict):
        raise ValueError("Runtime release manifest lacks runtime/source identity")
    runtime_id = runtime.get("buildId")
    px4_commit = source.get("px4Commit")
    if not isinstance(runtime_id, str) or not isinstance(px4_commit, str):
        raise ValueError("Runtime release manifest lacks buildId/PX4 commit")

    records = [
        _run_wsl(distribution=args.distribution, name=name, argv=argv)
        for name, argv in _COMMANDS
    ]
    observed_px4 = _command_stdout(records, "px4_git_head")
    if observed_px4 != px4_commit:
        raise ValueError("observed PX4 commit does not match Runtime release manifest")
    gazebo_output = _command_stdout(records, "gazebo_sim_version")
    gazebo_match = re.search(r"Gazebo Sim, version ([0-9.]+)", gazebo_output)
    if gazebo_match is None:
        raise ValueError("cannot parse Gazebo Sim version")
    python_output = _command_stdout(records, "python_version")
    python_match = re.fullmatch(r"Python ([0-9.]+)", python_output)
    if python_match is None:
        raise ValueError("cannot parse Runtime Python version")
    package_output = _command_stdout(records, "gazebo_harmonic_package")
    package_parts = package_output.split()
    if len(package_parts) != 2 or package_parts[0] != "gz-harmonic":
        raise ValueError("cannot parse gz-harmonic package version")
    os_release = _parse_os_release(_command_stdout(records, "ubuntu_release"))

    payload = build_runtime_observation(
        runtime_id=runtime_id,
        observer_commit=args.observer_commit,
        observed_at=args.observed_at,
        wsl_distribution=args.distribution,
        px4_commit=observed_px4,
        gazebo_sim_version=gazebo_match.group(1),
        gazebo_harmonic_package=package_parts[1],
        python_version=python_match.group(1),
        mavsdk_version=_command_stdout(records, "mavsdk_version"),
        pyulog_version=_command_stdout(records, "pyulog_version"),
        ubuntu_version=os_release.get("VERSION_ID", ""),
        kernel=_command_stdout(records, "kernel"),
        commands=records,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "observation_sha256": payload["observation_sha256"],
                "runtime_id": payload["runtime_id"],
                "px4_commit": payload["px4_commit"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
