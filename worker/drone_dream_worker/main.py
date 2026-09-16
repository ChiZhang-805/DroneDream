"""DroneDream worker entrypoint.

Thin wrapper around :func:`app.orchestration.runner.run_forever`. The worker
process polls the database for QUEUED jobs and PENDING trials, dispatches
baseline + optimizer candidates, executes each trial through the configured
:class:`app.simulator.base.SimulatorAdapter` (deterministic mock by default),
aggregates per-candidate metrics into a ``JobReport``, and drives the job
state machine to a terminal state. The orchestration logic itself lives in
``app.orchestration`` (the backend package), which this worker imports after
installing the backend editable into its venv.
"""

from __future__ import annotations

import logging
import sys

from app.orchestration.runner import run_forever

from drone_dream_worker import __version__
from drone_dream_worker.config import get_settings

logger = logging.getLogger("drone_dream.worker")


def run(max_iterations: int | None = None) -> int:
    """Run the shared job/trial state machine, returning its terminal exit code.

    The backend runner owns database access, claims and simulator selection.
    This entrypoint only configures process logging and polling; it must not
    log credentials embedded in a configured database connection URL.
    """

    settings = get_settings()
    logging.basicConfig(
        level=settings.worker_log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # DATABASE_URL may include a password or credential-bearing query string.
    # Startup diagnostics do not need it, even in development/test runs.
    logger.info(
        "drone-dream-worker %s starting (poll_interval=%.2fs)",
        __version__,
        settings.worker_poll_interval_seconds,
    )
    exit_code: int = run_forever(
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        max_iterations=max_iterations,
    )
    return exit_code


def main() -> None:
    """Expose the worker outcome as the process exit status for its supervisor."""
    sys.exit(run())


if __name__ == "__main__":
    main()
