from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.archive_experiment_evidence import (
    EvidenceArchiveError,
    archive_experiment_evidence,
    verify_experiment_evidence_archive,
)


def _source(root: Path, name: str = "source") -> Path:
    source = root / name
    (source / "logs").mkdir(parents=True)
    (source / "logs" / "trial-1.json").write_text(
        json.dumps({"status": "FAILED", "reason": "px4_timeout"}),
        encoding="utf-8",
    )
    (source / "metrics.csv").write_text("trial,rmse\n1,0.42\n", encoding="utf-8")
    return source


def _archive(root: Path, source: Path, name: str, *, delete: bool = False) -> dict[str, object]:
    return archive_experiment_evidence(
        source=source,
        archive_path=root / f"{name}.zip",
        receipt_path=root / f"{name}.receipt.json",
        source_label="failed-px4-timeout-case",
        terminal_status="failed",
        delete_source_after_verify=delete,
    )


def test_archive_is_deterministic_and_preserves_failed_outcomes(tmp_path: Path) -> None:
    first_source = _source(tmp_path, "first")
    second_source = _source(tmp_path, "second")

    first = _archive(tmp_path, first_source, "first-archive")
    second = _archive(tmp_path, second_source, "second-archive")

    assert first["archive_sha256"] == second["archive_sha256"]
    assert first["terminal_status"] == "failed"
    manifest = verify_experiment_evidence_archive(tmp_path / "first-archive.zip")
    assert manifest["terminal_status"] == "failed"
    assert manifest["outcome_filtering_applied"] is False
    assert {row["path"] for row in manifest["files"]} == {
        "logs/trial-1.json",
        "metrics.csv",
    }


def test_explicit_delete_happens_only_after_verified_archive(tmp_path: Path) -> None:
    source = _source(tmp_path)
    receipt = _archive(tmp_path, source, "verified", delete=True)

    assert receipt["verification"] == "passed"
    assert receipt["delete_source_after_verify_performed"] is True
    assert source.is_dir()
    assert list(source.iterdir()) == []
    verify_experiment_evidence_archive(tmp_path / "verified.zip")


@pytest.mark.parametrize(
    ("relative", "payload"),
    [
        (".env", "OPENAI_API_KEY=not-a-real-test-secret-value"),
        ("credentials.json", "{}"),
        ("safe.log", "password=unredacted-example-value"),
        ("safe.log", "sk-example000000000000000000000000"),
    ],
)
def test_credentials_fail_closed_without_creating_outputs(
    tmp_path: Path,
    relative: str,
    payload: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / relative).write_text(payload, encoding="utf-8")

    with pytest.raises(EvidenceArchiveError):
        _archive(tmp_path, source, "blocked")
    assert not (tmp_path / "blocked.zip").exists()
    assert not (tmp_path / "blocked.receipt.json").exists()


def test_archive_and_receipt_must_be_outside_source(tmp_path: Path) -> None:
    source = _source(tmp_path)

    with pytest.raises(EvidenceArchiveError, match="outside"):
        archive_experiment_evidence(
            source=source,
            archive_path=source / "archive.zip",
            receipt_path=tmp_path / "receipt.json",
            source_label="case",
            terminal_status="mixed",
        )


def test_existing_outputs_are_never_overwritten(tmp_path: Path) -> None:
    source = _source(tmp_path)
    archive = tmp_path / "existing.zip"
    archive.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        archive_experiment_evidence(
            source=source,
            archive_path=archive,
            receipt_path=tmp_path / "receipt.json",
            source_label="case",
            terminal_status="success",
        )
    assert archive.read_bytes() == b"keep"


def test_tampered_archive_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _archive(tmp_path, source, "tampered")
    archive_path = tmp_path / "tampered.zip"

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr("unexpected.txt", "tamper")
    with pytest.raises(EvidenceArchiveError, match="entries"):
        verify_experiment_evidence_archive(archive_path)
