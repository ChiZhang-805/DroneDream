from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from scripts.evidence_output import write_new_evidence_files


def test_evidence_group_is_created_without_replacing_bytes(tmp_path: Path) -> None:
    first = tmp_path / "freeze.json"
    second = tmp_path / "freeze.sha256"
    write_new_evidence_files(
        ((first, b"frozen\n"), (second, b"digest\n")),
        label="test evidence",
    )

    assert first.read_bytes() == b"frozen\n"
    assert second.read_bytes() == b"digest\n"
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_new_evidence_files(
            ((first, b"replacement\n"), (tmp_path / "third", b"new\n")),
            label="test evidence",
        )
    assert first.read_bytes() == b"frozen\n"
    assert not (tmp_path / "third").exists()


def test_evidence_group_rejects_duplicate_destinations(tmp_path: Path) -> None:
    path = tmp_path / "duplicate"
    with pytest.raises(ValueError, match="distinct"):
        write_new_evidence_files(
            ((path, b"first"), (path, b"second")),
            label="test evidence",
        )
    assert not path.exists()


def test_evidence_group_removes_only_files_created_before_a_write_failure(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    with pytest.raises(TypeError):
        write_new_evidence_files(
            (
                (first, b"complete\n"),
                (second, cast(bytes, object())),
            ),
            label="test evidence",
        )

    assert not first.exists()
    assert not second.exists()
