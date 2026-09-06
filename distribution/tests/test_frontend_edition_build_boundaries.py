from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "frontend" / "scripts" / "verify-edition-build-boundaries.mjs"
COMMON_CHUNKS = (
    "AutonomyPlatform",
    "Dashboard",
    "FixedScenarios",
    "History",
    "NewJobRoute",
)
VALID_EDITION_CHUNKS = {
    "universal": (
        "ExperimentAssistant",
        "LabSetup",
        "LabHardwareWorkspace",
        "LabValidationWorkspace",
        "FieldApp",
        "UniversalFieldApp",
    ),
    "sim": ("ExperimentAssistant",),
    "lab": (
        "ExperimentAssistant",
        "LabSetup",
        "LabHardwareWorkspace",
        "LabValidationWorkspace",
    ),
    "field": ("ExperimentAssistant", "UniversalFieldApp"),
    "autonomy": (),
}


def _write_dist(root: Path, chunks: tuple[str, ...]) -> None:
    (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    for chunk in (*COMMON_CHUNKS, *chunks):
        (root / f"{chunk}-contract.js").write_text("", encoding="utf-8")


def _verify(edition: str, dist: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(SCRIPT), "--edition", edition, "--dist", str(dist.resolve())],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("edition", tuple(VALID_EDITION_CHUNKS))
def test_current_edition_boundaries_accept_only_current_chunks(
    tmp_path: Path,
    edition: str,
) -> None:
    _write_dist(tmp_path, VALID_EDITION_CHUNKS[edition])

    result = _verify(edition, tmp_path)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["edition"] == edition
    assert receipt["builtInVehicleStudioAbsent"] is True
    assert receipt["result"] == "pass"


@pytest.mark.parametrize("edition", tuple(VALID_EDITION_CHUNKS))
def test_retired_vehicle_studio_is_forbidden_in_every_edition(
    tmp_path: Path,
    edition: str,
) -> None:
    _write_dist(tmp_path, (*VALID_EDITION_CHUNKS[edition], "VehicleStudio"))

    result = _verify(edition, tmp_path)

    assert result.returncode != 0
    assert f"{edition} contains foreign VehicleStudio code" in result.stderr


@pytest.mark.parametrize("foreign_chunk", ("ExperimentAssistant", "UniversalFieldApp"))
def test_autonomy_rejects_routes_folded_into_the_current_agent_workspace(
    tmp_path: Path,
    foreign_chunk: str,
) -> None:
    _write_dist(tmp_path, (foreign_chunk,))

    result = _verify("autonomy", tmp_path)

    assert result.returncode != 0
    assert f"autonomy contains foreign {foreign_chunk} code" in result.stderr


@pytest.mark.parametrize(
    ("edition", "missing_chunk"),
    (
        ("universal", "LabSetup"),
        ("lab", "LabHardwareWorkspace"),
        ("field", "UniversalFieldApp"),
        ("sim", "ExperimentAssistant"),
    ),
)
def test_edition_specific_required_chunks_fail_closed(
    tmp_path: Path,
    edition: str,
    missing_chunk: str,
) -> None:
    chunks = tuple(chunk for chunk in VALID_EDITION_CHUNKS[edition] if chunk != missing_chunk)
    _write_dist(tmp_path, chunks)

    result = _verify(edition, tmp_path)

    assert result.returncode != 0
    assert f"{edition} is missing its {missing_chunk} chunk" in result.stderr
