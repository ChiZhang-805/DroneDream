"""Frozen evaluation checks for the cross-Job memory safety contract."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration.harness_cross_job_memory_evaluation import (
    HARNESS_CROSS_JOB_EVAL_CASES,
    build_harness_cross_job_memory_artifact,
    build_harness_cross_job_memory_manifest,
    verify_harness_cross_job_memory_artifact,
    verify_harness_cross_job_memory_manifest,
)
from scripts.evaluate_harness_cross_job_memory import (
    write_harness_cross_job_memory_files,
)

ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
STEM = "harness-cross-job-memory-contract-v1"
JSON_ARTIFACT = ROOT / f"{STEM}.json"
CSV_ARTIFACT = ROOT / f"{STEM}.csv"
MANIFEST_ARTIFACT = ROOT / f"{STEM}.manifest.json"
SHA256_ARTIFACT = ROOT / f"{STEM}.sha256"
SCRIPT = ROOT.parent / "scripts" / "evaluate_harness_cross_job_memory.py"
REPOSITORY_ROOT = ROOT.parents[1]


def _load_manifest() -> dict[str, object]:
    return verify_harness_cross_job_memory_manifest(
        json.loads(MANIFEST_ARTIFACT.read_text(encoding="utf-8"))
    )


def _load_artifact() -> dict[str, object]:
    return verify_harness_cross_job_memory_artifact(
        json.loads(JSON_ARTIFACT.read_text(encoding="utf-8")),
        manifest=_load_manifest(),
    )


def test_cross_job_memory_artifact_is_complete_and_claim_bounded() -> None:
    artifact = _load_artifact()
    assert artifact["summary"] == {
        "case_count": 10,
        "passed_count": 10,
        "failed_count": 0,
        "retrieval_positive_count": 2,
        "retrieval_negative_count": 8,
        "provider_identifier_leak_count": 0,
        "provider_calls": 0,
        "network_calls": 0,
        "simulator_runs": 0,
    }
    rows = artifact["case_rows"]
    assert [row["case_id"] for row in rows] == list(HARNESS_CROSS_JOB_EVAL_CASES)
    assert all(row["passed"] is True for row in rows)
    assert rows[0]["scenario_similarity"] == 1.0
    assert 0.0 < rows[1]["scenario_similarity"] < 1.0
    assert all(
        row["prompt_binding_changed"]
        is (row["retrieved_experience_count"] > 0)
        for row in rows
    )
    assert "no claim of optimizer-quality benefit" in artifact["claim_boundary"]


def test_cross_job_memory_artifact_matches_current_contract_and_bytes(
    tmp_path: Path,
) -> None:
    assert _load_manifest() == build_harness_cross_job_memory_manifest()
    assert _load_artifact() == build_harness_cross_job_memory_artifact()
    result = write_harness_cross_job_memory_files(
        json_path=tmp_path / JSON_ARTIFACT.name,
        csv_path=tmp_path / CSV_ARTIFACT.name,
        manifest_path=tmp_path / MANIFEST_ARTIFACT.name,
        sha256_path=tmp_path / SHA256_ARTIFACT.name,
    )
    assert result["summary"]["passed_count"] == 10
    assert (tmp_path / JSON_ARTIFACT.name).read_bytes() == JSON_ARTIFACT.read_bytes()
    assert (tmp_path / CSV_ARTIFACT.name).read_bytes() == CSV_ARTIFACT.read_bytes()
    assert (
        (tmp_path / MANIFEST_ARTIFACT.name).read_bytes()
        == MANIFEST_ARTIFACT.read_bytes()
    )
    assert (
        (tmp_path / SHA256_ARTIFACT.name).read_bytes()
        == SHA256_ARTIFACT.read_bytes()
    )
    with (tmp_path / CSV_ARTIFACT.name).open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    write_harness_cross_job_memory_files(
        json_path=tmp_path / JSON_ARTIFACT.name,
        csv_path=tmp_path / CSV_ARTIFACT.name,
        manifest_path=tmp_path / MANIFEST_ARTIFACT.name,
        sha256_path=tmp_path / SHA256_ARTIFACT.name,
        check=True,
    )


def test_cross_job_memory_artifact_rejects_hash_tamper() -> None:
    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["case_rows"][0]["retrieved_experience_count"] = 0
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_cross_job_memory_artifact(
            artifact,
            manifest=_load_manifest(),
        )
    manifest = json.loads(MANIFEST_ARTIFACT.read_text(encoding="utf-8"))
    manifest["contracts"]["retention_days"] = 1
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_cross_job_memory_manifest(manifest)


def test_cross_job_memory_checksum_manifest_matches_files() -> None:
    expected = SHA256_ARTIFACT.read_text(encoding="ascii").splitlines()
    assert expected == [
        f"{hashlib.sha256(JSON_ARTIFACT.read_bytes()).hexdigest()}  {JSON_ARTIFACT.name}",
        f"{hashlib.sha256(CSV_ARTIFACT.read_bytes()).hexdigest()}  {CSV_ARTIFACT.name}",
        (
            f"{hashlib.sha256(MANIFEST_ARTIFACT.read_bytes()).hexdigest()}  "
            f"{MANIFEST_ARTIFACT.name}"
        ),
    ]


def test_cross_job_memory_check_cli_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["passed_count"] == 10
