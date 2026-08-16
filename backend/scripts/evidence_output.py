"""Fail-closed helpers for publishing immutable evidence file groups."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from pathlib import Path


def write_new_evidence_files(
    outputs: Iterable[tuple[Path, bytes]],
    *,
    label: str,
) -> None:
    """Exclusively create every output without replacing an existing freeze."""

    resolved = [(path.resolve(), payload) for path, payload in outputs]
    paths = [path for path, _payload in resolved]
    if not resolved:
        raise ValueError(f"{label} has no output files")
    if len(set(paths)) != len(paths):
        raise ValueError(f"{label} output paths must be distinct")
    existing = [path for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite frozen {label}: "
            + ", ".join(str(path) for path in existing)
        )

    created: list[Path] = []
    try:
        for path, payload in resolved:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                created.append(path)
                handle.write(payload)
    except Exception:
        # These paths were created exclusively by this call. Roll back only
        # those new files so a failed group publication cannot look complete.
        for path in reversed(created):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        raise
