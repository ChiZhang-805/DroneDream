"""Worker polling loop.

The worker process calls :func:`run_forever`, which repeatedly:

1. Claims any newly-QUEUED jobs and dispatches their baseline trials.
2. Runs at most one PENDING trial per iteration (deterministic mock work).
3. Finalizes any RUNNING/AGGREGATING jobs whose trials are all terminal.

Each step uses its own short-lived SQLAlchemy session so API traffic is never
blocked waiting for a worker transaction. The loop is intentionally simple —
Phase 5 will add an optimizer step between (1) and (3).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from types import FrameType

from app.db import SessionLocal
from app.orchestration.aggregation import finalize_ready_jobs
from app.orchestration.job_manager import start_queued_jobs
from app.orchestration.trial_executor import claim_and_run_one_pending_trial

logger = logging.getLogger("drone_dream.orchestration.runner")


class WorkerStopped(BaseException):
    """Internal sentinel raised from signal handlers to break the main loop."""


def _install_signal_handlers() -> None:
    def _handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("received signal %s, shutting down", signal.Signals(signum).name)
        raise WorkerStopped

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def tick(worker_id: str) -> dict[str, object]:
    """Run a single iteration of the worker loop.

    Exposed for tests so they can drive the orchestration deterministically
    without sleeping. Returns a small summary dict.
    """

    with SessionLocal() as db:
        started = start_queued_jobs(db)

    with SessionLocal() as db:
        trial_id = claim_and_run_one_pending_trial(db, worker_id)

    with SessionLocal() as db:
        finalized = finalize_ready_jobs(db)

    return {"started": started, "trial_id": trial_id, "finalized": finalized}


def run_forever(
    *,
    poll_interval_seconds: float = 1.0,
    max_iterations: int | None = None,
    worker_id: str | None = None,
) -> int:
    """Drive the polling loop until a stop signal or ``max_iterations``.

    Returns the intended process exit code.
    """

    wid = worker_id or _default_worker_id()
    _install_signal_handlers()
    logger.info("worker %s starting (poll_interval=%.2fs)", wid, poll_interval_seconds)

    iterations = 0
    try:
        while True:
            summary = tick(wid)
            iterations += 1
            did_work = bool(summary["started"] or summary["trial_id"] or summary["finalized"])
            if not did_work:
                logger.debug("worker idle tick #%d", iterations)
            if max_iterations is not None and iterations >= max_iterations:
                break
            # If we actually did work, loop again immediately to drain the queue.
            if not did_work:
                time.sleep(poll_interval_seconds)
    except WorkerStopped:
        pass
    finally:
        logger.info("worker %s stopped after %d ticks", wid, iterations)
    return 0
