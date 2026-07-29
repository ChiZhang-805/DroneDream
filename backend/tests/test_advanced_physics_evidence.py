from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.simulator.advanced_physics_evidence import (
    ATTEMPT_SPECS,
    CLAIM_BOUNDARY,
    export_advanced_physics_evidence,
    verify_advanced_physics_evidence,
)
from app.simulator.scenario_effects import scenario_effect_request_sha256

SUBJECT_COMMIT = "1" * 40
EXPORTER_COMMIT = "2" * 40
PX4_COMMIT = "6ea3539157ca358c70a515878b77077af7d4611d"
GENERATED_AT = "2026-07-28T20:30:00Z"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _identity(directory: str, attempt: int) -> dict[str, Any]:
    return {
        "attempt_count": attempt,
        "candidate_id": "baseline-mpc-xy-p-0.95",
        "job_id": "advanced-physics-real-px4-26b957e",
        "seed": 42001,
        "trial_id": f"trial-{directory}",
    }


def _effect_request(
    *,
    identity: dict[str, Any],
    effects: tuple[str, ...],
) -> dict[str, Any]:
    request = {
        "schema_version": "dronedream.scenario_effect_request.v1",
        "execution_identity": identity,
        "effects": [
            {
                "effect_id": effect,
                "capability": {"status": "available", "reason": "fixture"},
                "mechanism": "fixture",
            }
            for effect in effects
        ],
    }
    request["request_sha256"] = scenario_effect_request_sha256(request)
    return request


def _effect_evidence(
    *,
    identity: dict[str, Any],
    effects: tuple[str, ...],
    request_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.scenario_effect_evidence.v1",
        "execution_identity": identity,
        "request_sha256": request_sha256,
        "effects": [
            {
                "effect_id": effect,
                "status": "applied",
                "capability": {"status": "available", "reason": "fixture"},
                "mechanism": "fixture",
                "evidence": {"verification": {"status": "verified"}},
            }
            for effect in effects
        ],
    }


def _runtime_manifest(
    *,
    identity: dict[str, Any],
    effects: tuple[str, ...],
    request_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.simulator_runtime_manifest.v1",
        "execution_identity": identity,
        "px4_version": "v1.16",
        "firmware_identity": {
            "status": "verified",
            "observed_source": "git_head",
            "observed_commit": PX4_COMMIT,
            "requested_commit": PX4_COMMIT,
        },
        "scenario_effect_contract": {
            "verification_status": "verified_applied",
            "request_sha256": request_sha256,
            "requested_effects": list(effects),
            "applied_effects": list(effects),
            "unsupported_effects": [],
            "failed_effects": [],
            "pending_effects": [],
        },
        "scenario_effect_request": {
            "request_sha256": request_sha256,
            "schema_version": "dronedream.scenario_effect_request.v1",
        },
        "scenario_effect_evidence": {
            "required": True,
            "verification_status": "verified_applied",
            "schema_version": "dronedream.scenario_effect_evidence.v1",
        },
    }


def _result(
    *,
    identity: dict[str, Any],
    success: bool,
) -> dict[str, Any]:
    if not success:
        return {
            "schema_version": "dronedream.trial_result.v2",
            "execution_identity": identity,
            "success": False,
            "failure": {
                "code": "SIMULATION_FAILED",
                "reason": "lower-level launcher exited with code 1",
            },
            "log_excerpt": "lower-level launcher exited with code 1",
        }
    return {
        "schema_version": "dronedream.trial_result.v2",
        "execution_identity": identity,
        "success": True,
        "metrics": {
            "rmse": 0.37,
            "max_error": 1.49,
            "completion_time": 20.9,
            "score": 2.17,
            "pass_flag": True,
            "raw_metric_json": {
                "evaluation_track_coverage": 0.95,
            },
        },
    }


def _execution_window(directory: str) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.advanced-physics-execution-window/v1",
        "subject_commit": SUBJECT_COMMIT,
        "source_preflight": "windows_git_head_and_tracked_diff",
        "runtime_user": "dronedream",
        "run_name": directory,
        "started_at": "2026-07-28T20:19:54Z",
        "ended_at": "2026-07-28T20:21:16Z",
        "duration_seconds": 82,
        "runner_exit_code": 0,
        "preexisting_process_count": 0,
        "residual_process_count": 0,
    }


def _build_source(root: Path) -> Path:
    for index, spec in enumerate(ATTEMPT_SPECS, start=1):
        directory = root / spec.directory
        directory.mkdir(parents=True)
        identity = _identity(spec.directory, index)
        _write_json(directory / "trial-input.json", {"execution_identity": identity})
        if spec.role == "file_backed_preflight_failure":
            _write_json(
                directory / "trial-result.json",
                {
                    "schema_version": "dronedream.trial_result.v2",
                    "execution_identity": identity,
                    "success": False,
                    "failure": {
                        "code": "SIMULATION_FAILED",
                        "reason": (
                            "fatal: detected dubious ownership; configure "
                            "safe.directory before retry"
                        ),
                    },
                },
            )
            (directory / "runner.log").write_text(
                "dubious ownership safe.directory\n",
                encoding="utf-8",
            )
            continue

        request = _effect_request(
            identity=identity,
            effects=spec.expected_effects,
        )
        request_sha = str(request["request_sha256"])
        _write_json(
            directory / "scenario_effects.request.json",
            request,
        )
        _write_json(
            directory / "scenario_effects.applied.json",
            _effect_evidence(
                identity=identity,
                effects=spec.expected_effects,
                request_sha256=request_sha,
            ),
        )
        _write_json(
            directory / "simulator_runtime_manifest.json",
            _runtime_manifest(
                identity=identity,
                effects=spec.expected_effects,
                request_sha256=request_sha,
            ),
        )
        _write_json(
            directory / "trial-result.json",
            _result(identity=identity, success=spec.expected_success),
        )
        _write_json(directory / "launch_config.json", {"fixture": True})
        _write_json(directory / "scenario_config.json", {"fixture": True})
        (directory / "runner.log").write_text("fixture\n", encoding="utf-8")
        (directory / "stdout.log").write_text("fixture stdout\n", encoding="utf-8")
        stderr = (
            "fixture stderr\n"
            if spec.expected_success
            else "PX4 readiness timeout after 30.0s\n"
        )
        (directory / "stderr.log").write_text(stderr, encoding="utf-8")
        sdf = directory / "scenario_runtime" / "generated_world.sdf"
        sdf.parent.mkdir(parents=True)
        sdf.write_text("<sdf version='1.10'/>\n", encoding="utf-8")
        omitted = directory / "scenario_runtime" / "px4_rootfs" / "params.json"
        omitted.parent.mkdir(parents=True)
        omitted.write_text("{}\n", encoding="utf-8")
        if spec.authoritative:
            _write_json(
                directory / "execution-window.json",
                _execution_window(spec.directory),
            )
            (directory / "execution-window.log").write_text(
                "START_UTC=fixture\n",
                encoding="utf-8",
            )
        if spec.role == "authoritative_success":
            (directory / "px4_source.ulg").write_bytes(b"fixture-ulog" * 100)
            _write_json(directory / "telemetry.json", {"samples": [1, 2, 3]})
    return root


def _export(source: Path, output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return export_advanced_physics_evidence(
        source_root=source,
        output_root=output,
        subject_commit=SUBJECT_COMMIT,
        exporter_commit=EXPORTER_COMMIT,
        generated_at=GENERATED_AT,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_export_is_deterministic_and_verifies_every_raw_byte(tmp_path: Path) -> None:
    source = _build_source(tmp_path / "source")
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest, receipt = _export(source, first)
    _export(source, second)
    verified_manifest, verified_receipt = verify_advanced_physics_evidence(
        evidence_root=first,
        source_root=source,
    )

    assert _files(first) == _files(second)
    assert verified_manifest == manifest
    assert verified_receipt == receipt
    assert manifest["claim_boundary"] == CLAIM_BOUNDARY
    assert manifest["summary"]["attempt_count"] == 6
    assert manifest["summary"]["successful_flight_count"] == 3
    assert manifest["summary"]["passing_flight_count"] == 3
    assert manifest["summary"]["gps_readiness_boundary_count"] == 2
    assert manifest["summary"]["file_backed_preflight_failure_count"] == 1
    assert receipt["result"]["status"] == "passed"

    ulog = (
        first
        / "attempts"
        / "success-five-effects-attempt-4"
        / "px4_source.ulg.gz"
    )
    raw = ulog.read_bytes()
    assert int.from_bytes(raw[4:8], "little") == 0


def test_verifier_rejects_retained_tampering(tmp_path: Path) -> None:
    source = _build_source(tmp_path / "source")
    output = tmp_path / "bundle"
    _export(source, output)
    retained = (
        output
        / "attempts"
        / "success-five-effects-attempt-4"
        / "trial-result.json"
    )
    retained.write_bytes(retained.read_bytes() + b" ")

    with pytest.raises(ValueError, match="retained evidence drifted"):
        verify_advanced_physics_evidence(evidence_root=output)


def test_raw_verifier_rejects_omitted_source_tampering(tmp_path: Path) -> None:
    source = _build_source(tmp_path / "source")
    output = tmp_path / "bundle"
    _export(source, output)
    omitted = (
        source
        / "success-five-effects-attempt-4"
        / "scenario_runtime"
        / "px4_rootfs"
        / "params.json"
    )
    omitted.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="raw source no longer matches"):
        verify_advanced_physics_evidence(
            evidence_root=output,
            source_root=source,
        )


def test_export_rejects_boundary_without_readiness_timeout(tmp_path: Path) -> None:
    source = _build_source(tmp_path / "source")
    stderr = (
        source
        / "gps-readiness-boundary-attempt-2"
        / "stderr.log"
    )
    stderr.write_text("generic failure\n", encoding="utf-8")

    with pytest.raises(ValueError, match="readiness boundary drifted"):
        _export(source, tmp_path / "bundle")


def test_export_rejects_unverified_effect(tmp_path: Path) -> None:
    source = _build_source(tmp_path / "source")
    path = (
        source
        / "success-five-effects-attempt-4"
        / "scenario_effects.applied.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["effects"][0]["evidence"]["verification"]["status"] = "unverified"
    _write_json(path, evidence)

    with pytest.raises(ValueError, match="effect is not verified applied"):
        _export(source, tmp_path / "bundle")


def test_export_rejects_request_hash_that_only_matches_cross_file_references(
    tmp_path: Path,
) -> None:
    source = _build_source(tmp_path / "source")
    directory = source / "success-five-effects-attempt-4"
    forged_hash = "f" * 64
    request_path = directory / "scenario_effects.request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["request_sha256"] = forged_hash
    _write_json(request_path, request)

    evidence_path = directory / "scenario_effects.applied.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["request_sha256"] = forged_hash
    _write_json(evidence_path, evidence)

    runtime_path = directory / "simulator_runtime_manifest.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["scenario_effect_contract"]["request_sha256"] = forged_hash
    runtime["scenario_effect_request"]["request_sha256"] = forged_hash
    _write_json(runtime_path, runtime)

    with pytest.raises(ValueError, match="request hash does not recompute"):
        _export(source, tmp_path / "bundle")
