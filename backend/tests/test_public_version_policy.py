from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_public_repository_has_no_internal_experiment_or_component_version_labels() -> None:
    repository = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(repository / "scripts" / "audit_public_experiment_labels.py")],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_current_frontend_cannot_restore_retired_routes_or_job_downgrades() -> None:
    repository = Path(__file__).resolve().parents[2]
    router = (repository / "frontend/src/router.tsx").read_text(encoding="utf-8")
    autonomy = (repository / "frontend/src/pages/AutonomyPlatform.tsx").read_text(
        encoding="utf-8"
    )
    new_job = (repository / "frontend/src/pages/NewJob.tsx").read_text(
        encoding="utf-8"
    )

    for retired_route in ("autonomy/mission", "autonomy/evidence", "vehicle-studio"):
        assert retired_route not in router
    assert "AutonomyMissionRedirect" not in autonomy
    assert "export function AutonomyMission" not in autonomy
    assert "function legacyRequest(" not in new_job
    assert "createJob(legacyRequest(" not in new_job
