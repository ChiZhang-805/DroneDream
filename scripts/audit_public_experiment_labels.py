#!/usr/bin/env python3
"""Reject internal experiment sequence labels from public repository text."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PUBLIC_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".sdf",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
EXPERIMENT_SEQUENCE_LABEL = re.compile(
    r"(?i)(?<![a-z0-9])r[0-9]{1,3}(?![a-z0-9])"
)
VISIBLE_REVISION_LABEL = re.compile(r"R\{[^}\n]*revision")

# These files bind literal names owned by third parties or installer-language
# register syntax. Their numeric tokens are not DroneDream experiment labels.
EXTERNAL_LITERAL_FILES = {
    "backend/app/benchmarking/method_inventory.py",
    "backend/app/benchmarking/pycma_reference_contract.py",
    "desktop/scripts/verify-installer-removal-wait.ps1",
    "desktop/scripts/verify-nsis-template.ps1",
    "frontend/src/features/settings/modelProviderCatalog.ts",
}


def _repository_files(repository: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return [
        repository / Path(item.decode("utf-8"))
        for item in completed.stdout.split(b"\0")
        if item
    ]


def find_public_experiment_labels(repository: Path) -> list[str]:
    violations: list[str] = []
    for path in _repository_files(repository):
        relative = path.relative_to(repository).as_posix()
        if (
            relative in EXTERNAL_LITERAL_FILES
            or path.suffix.lower() not in PUBLIC_TEXT_SUFFIXES
            or not path.is_file()
        ):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if EXPERIMENT_SEQUENCE_LABEL.search(line) or VISIBLE_REVISION_LABEL.search(line):
                violations.append(f"{relative}:{line_number}")
    return violations


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    violations = find_public_experiment_labels(repository)
    if not violations:
        print("PUBLIC_EXPERIMENT_LABEL_AUDIT status=passed")
        return 0
    print("PUBLIC_EXPERIMENT_LABEL_AUDIT status=failed")
    for violation in violations:
        print(violation)
    return 1


if __name__ == "__main__":
    sys.exit(main())
