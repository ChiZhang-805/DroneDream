"""Placeholder adapter for the future PX4/Gazebo integration.

This exists so the selection surface is real and testable — picking
``SIMULATOR_BACKEND=real_stub`` at deploy time must fail loudly rather than
silently falling back to the mock. Phase 4 explicitly does *not* integrate
a real simulator.
"""

from __future__ import annotations

from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialResult,
)


class RealSimulatorAdapterStub(SimulatorAdapter):
    """Stub backend for future PX4/Gazebo integration.

    Two behaviours are exposed so callers can choose between a hard failure
    (``run_trial`` raising) and a soft failure (``run_trial`` returning a
    structured unavailable result). The default is the soft failure so the
    worker never crashes when an operator mis-configures the backend; the
    trial is simply marked ``FAILED`` with a clear ``ADAPTER_UNAVAILABLE``
    code and the job manager decides whether the whole job should fail.
    """

    backend_name = "real_stub"

    #: When True, ``run_trial`` raises ``NotImplementedError``. Primarily for
    #: tests that want to assert the stub is wired through the adapter
    #: selection logic.
    raise_on_run: bool = False

    def run_trial(self, ctx: TrialContext) -> TrialResult:  # noqa: D401 — docstring inherited
        if self.raise_on_run:
            raise NotImplementedError(
                "RealSimulatorAdapterStub is not implemented; PX4/Gazebo "
                "integration arrives in a later phase."
            )
        return TrialResult(
            success=False,
            backend=self.backend_name,
            failure=TrialFailure(
                code=FAILURE_ADAPTER_UNAVAILABLE,
                reason=(
                    "Real simulator backend is not available in the MVP. "
                    "Set SIMULATOR_BACKEND=mock or install a real adapter."
                ),
            ),
            log_excerpt=f"[real_stub] scenario={ctx.scenario_type} UNAVAILABLE",
        )


__all__ = ["RealSimulatorAdapterStub"]
