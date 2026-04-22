"""DroneDream worker entrypoint.

Phase 3 scope: poll the database for QUEUED jobs and PENDING trials, run
deterministic mock trials, roll baseline metrics up into the candidate,
produce a READY JobReport, and drive the job state machine to a terminal
state. The actual orchestration logic lives in ``app.orchestration`` (the
backend package), which this worker imports after installing the backend
editable into its venv.
"""

from __future__ import annotations

import logging
import sys

from app.orchestration.runner import run_forever

from drone_dream_worker import __version__
from drone_dream_worker.config import get_settings

logger = logging.getLogger("drone_dream.worker")


def run(max_iterations: int | None = None) -> int:
    """Launch the worker loop. Used by both ``main()`` and tests."""

    settings = get_settings()
    logging.basicConfig(
        level=settings.worker_log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "drone-dream-worker %s starting (poll_interval=%.2fs, database=%s)",
        __version__,
        settings.worker_poll_interval_seconds,
        settings.database_url,
    )
    exit_code: int = run_forever(
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        max_iterations=max_iterations,
    )
    return exit_code


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
