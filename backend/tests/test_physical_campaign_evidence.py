from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from app.simulator import physical_campaign_evidence
from app.simulator.physical_campaign_evidence import build_runtime_observation
from scripts.observe_px4_runtime import write_new_runtime_observation

_PX4_COMMIT = "6ea3539157ca358c70a515878b77077af7d4611d"
_OBSERVER_COMMIT = "a" * 40
_RUNTIME_ID = "5e15a7a5-f943-5c38-a284-1bdcc9cd528f"
_COMMAND_NAMES = (
    "px4_git_head",
    "gazebo_sim_version",
    "python_version",
    "mavsdk_version",
    "pyulog_version",
    "ubuntu_release",
    "gazebo_harmonic_package",
    "kernel",
)


def _command_rows() -> list[dict[str, Any]]:
    rows = []
    for name in _COMMAND_NAMES:
        stdout = f"{name}-stdout"
        stderr = ""
        rows.append(
            {
                "name": name,
                "argv": ["wsl.exe", "-d", "DroneDreamRuntime", "--", name],
                "exit_code": 0,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            }
        )
    return rows


def _observation(*, commands: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return build_runtime_observation(
        runtime_id=_RUNTIME_ID,
        observer_commit=_OBSERVER_COMMIT,
        observed_at="2026-07-28T15:00:00Z",
        wsl_distribution="DroneDreamRuntime",
        px4_commit=_PX4_COMMIT,
        gazebo_sim_version="8.14.0",
        gazebo_harmonic_package="1.0.0-1~noble",
        python_version="3.12.3",
        mavsdk_version="3.15.3",
        pyulog_version="1.2.3",
        ubuntu_version="24.04",
        kernel="Linux test 6.6.0 x86_64 GNU/Linux",
        commands=commands or _command_rows(),
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_runtime_observation_writer_never_replaces_a_freeze(tmp_path: Path) -> None:
    output = tmp_path / "runtime-observation.json"
    payload = _observation()

    write_new_runtime_observation(output, payload)
    original = output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        write_new_runtime_observation(output, payload)

    assert output.read_bytes() == original


def _identity(*, attempt: int) -> dict[str, Any]:
    return {
        "trial_id": f"failure-{attempt}",
        "job_id": "failure-history",
        "candidate_id": "baseline-mpc-xy-p-0.95",
        "seed": 41001,
        "attempt_count": attempt,
    }


def test_runtime_observation_is_deterministic_and_content_addressed() -> None:
    first = _observation()
    second = _observation()

    assert first == second
    unsigned = dict(first)
    declared = unsigned.pop("observation_sha256")
    assert (
        declared
        == hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert first["network_calls"] == 0
    assert first["real_credentials_used"] is False


def test_runtime_observation_rejects_failed_command() -> None:
    commands = _command_rows()
    commands[3]["exit_code"] = 1

    with pytest.raises(ValueError, match="command evidence"):
        _observation(commands=commands)


def test_runtime_release_fixture_binds_campaign_firmware() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (repository_root / "runtime" / "tests" / "fixtures" / "runtime-release.json").read_text(
            encoding="utf-8"
        )
    )

    summary = physical_campaign_evidence._validate_runtime_release_manifest(
        payload,
        expected_firmware_commit=_PX4_COMMIT,
    )

    assert summary["runtime_id"] == _RUNTIME_ID
    assert summary["gazebo_release"] == "harmonic"
    assert summary["px4_commit"] == _PX4_COMMIT


def test_pre_dispatch_failure_attempt_one_may_omit_result_identity(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "probe-nominal"
    identity = _identity(attempt=1)
    _write_json(trial / "trial_input.json", {"execution_identity": identity})
    _write_json(
        trial / "trial_result.json",
        {
            "success": False,
            "failure": {
                "code": "SIMULATION_FAILED",
                "reason": "sensor_noise_level must be one of: low, medium, high",
            },
        },
    )

    summary = physical_campaign_evidence._validate_failure_trial(
        trial,
        expected_source_commit="b" * 40,
    )

    assert summary["attempt_count"] == 1
    assert summary["result_identity_present"] is False
    assert summary["failure_code"] == "SIMULATION_FAILED"


def test_later_failure_may_not_omit_result_identity(tmp_path: Path) -> None:
    trial = tmp_path / "probe-nominal-attempt-2"
    identity = _identity(attempt=2)
    _write_json(trial / "trial_input.json", {"execution_identity": identity})
    _write_json(
        trial / "trial_result.json",
        {
            "success": False,
            "failure": {"code": "SIMULATION_FAILED", "reason": "expected failure"},
        },
    )

    with pytest.raises(ValueError, match="only for pre-dispatch attempt 1"):
        physical_campaign_evidence._validate_failure_trial(
            trial,
            expected_source_commit="b" * 40,
        )


def test_inventory_uses_posix_sort_order_and_deterministic_ulog_gzip(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    (source / "scenario_runtime" / "px4_rootfs" / "etc" / "init.d").mkdir(parents=True)
    (source / "scenario_runtime" / "px4_rootfs" / "etc" / "init.d-posix").mkdir(parents=True)
    (source / "scenario_runtime" / "px4_rootfs" / "etc" / "init.d" / "rcS").write_text(
        "rcS",
        encoding="utf-8",
    )
    (source / "scenario_runtime" / "px4_rootfs" / "etc" / "init.d-posix" / "airframe").write_text(
        "airframe", encoding="utf-8"
    )
    ulog = b"ULog" * 100
    (source / "px4_source.ulg").write_bytes(ulog)

    first, _ = physical_campaign_evidence._inventory_and_retain(
        source,
        output_root=first_output,
        retained_prefix=PurePosixPath("trial"),
        failure=False,
    )
    second, _ = physical_campaign_evidence._inventory_and_retain(
        source,
        output_root=second_output,
        retained_prefix=PurePosixPath("trial"),
        failure=False,
    )

    paths = [row["source_path"] for row in first]
    assert paths == sorted(paths)
    assert first == second
    first_gzip = first_output / "trial" / "px4_source.ulg.gz"
    second_gzip = second_output / "trial" / "px4_source.ulg.gz"
    assert first_gzip.read_bytes() == second_gzip.read_bytes()
    assert gzip.decompress(first_gzip.read_bytes()) == ulog


def test_attempt_four_reprocessing_remains_a_diagnostic_contract() -> None:
    ulog = b"diagnostic ULog"
    ulog_sha = hashlib.sha256(ulog).hexdigest()
    sample = {
        "t": 0.0,
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
        "yaw": 0.0,
        "armed": False,
        "mode": "4",
        "crashed": False,
    }
    payload = {
        "meta": {
            "origin_source_sha256": f"sha256:{ulog_sha}",
            "origin_source_byte_count": len(ulog),
            "source": "ulog",
            "simulator": "px4_gazebo",
            "origin_coordinate_frame": "PX4_LOCAL_NED",
            "origin_extraction_revision": "pyulog-vehicle-local-position-1.0",
        },
        "samples": [sample, {**sample, "t": 0.008, "armed": True}],
    }

    summary = physical_campaign_evidence._validate_reprocessed_failure_telemetry(
        payload,
        ulog_sha256=ulog_sha,
        ulog_bytes=len(ulog),
    )

    assert summary["sample_count"] == 2
    assert summary["evidence_role"] == "post-fix-parser-diagnostic-not-success-trial"
