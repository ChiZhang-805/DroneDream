from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_public_repository_has_no_experiment_sequence_labels() -> None:
    repository = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(repository / "scripts" / "audit_public_experiment_labels.py")],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
