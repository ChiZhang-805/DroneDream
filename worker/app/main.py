"""DroneDream worker entrypoint.

Phase 0 scope: log startup, idle on a polling loop, and log a clean shutdown
on SIGINT/SIGTERM. Trial execution is intentionally NOT implemented here.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType

from app import __version__
from app.config import get_settings

logger = logging.getLogger("drone_dream.worker")


class WorkerStopped(BaseException):
    """Internal sentinel raised from signal handlers to break the main loop."""


def _install_signal_handlers() -> None:
    def _handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("received signal %s, shutting down", signal.Signals(signum).name)
        raise WorkerStopped

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def run(max_iterations: int | None = None) -> int:
    """Run the worker loop.

    Args:
        max_iterations: Stop after this many polling iterations (used by tests).
            ``None`` means run until a shutdown signal arrives.

    Returns:
        Process exit code.
    """

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

    _install_signal_handlers()

    iterations = 0
    try:
        while True:
            # Phase 0: no work to do. Future phases will poll the DB queue here.
            iterations += 1
            logger.debug("worker idle tick #%d", iterations)
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(settings.worker_poll_interval_seconds)
    except WorkerStopped:
        pass
    finally:
        logger.info("drone-dream-worker stopped cleanly after %d ticks", iterations)

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
