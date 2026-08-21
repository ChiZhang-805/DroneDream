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
    "ExperimentAssistant",
    "FixedScenarios",
    "History",
    "NewJobRoute",
)


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


@pytest.mark.parametrize("edition", ["universal", "autonomy"])
def test_vehicle_studio_is_required_in_its_two_host_editions(
    tmp_path: Path,
    edition: str,
) -> None:
    required = (
        "LabSetup",
        "LabHardwareWorkspace",
        "LabValidationWorkspace",
        "FieldApp",
        "UniversalFieldApp",
        "VehicleStudio",
    ) if edition == "universal" else ("UniversalFieldApp", "VehicleStudio")
    _write_dist(tmp_path, required)

    result = _verify(edition, tmp_path)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["vehicleStudioHosts"] == ["universal", "autonomy"]
    assert receipt["vehicleStudioBoundarySatisfied"] is True


@pytest.mark.parametrize("edition", ["universal", "autonomy"])
def test_vehicle_studio_host_build_fails_when_chunk_is_missing(
    tmp_path: Path,
    edition: str,
) -> None:
    required = (
        "LabSetup",
        "LabHardwareWorkspace",
        "LabValidationWorkspace",
        "FieldApp",
        "UniversalFieldApp",
    ) if edition == "universal" else ("UniversalFieldApp",)
    _write_dist(tmp_path, required)

    result = _verify(edition, tmp_path)

    assert result.returncode != 0
    assert f"{edition} is missing its VehicleStudio chunk" in result.stderr


@pytest.mark.parametrize(
    ("edition", "required"),
    [
        ("sim", ()),
        ("lab", ("LabSetup", "LabHardwareWorkspace", "LabValidationWorkspace")),
        ("field", ("UniversalFieldApp",)),
    ],
)
def test_vehicle_studio_is_forbidden_in_non_host_editions(
    tmp_path: Path,
    edition: str,
    required: tuple[str, ...],
) -> None:
    _write_dist(tmp_path, (*required, "VehicleStudio"))

    result = _verify(edition, tmp_path)

    assert result.returncode != 0
    assert f"{edition} contains foreign VehicleStudio code" in result.stderr
