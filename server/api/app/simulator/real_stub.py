"""Internal test adapter that always reports the simulator as unavailable.

The adapter preserves regression coverage for failure handling without
pretending to be a real PX4/Gazebo implementation. The runtime factory rejects
``real_stub`` outside ``APP_ENV=test`` and the public API schema never exposes
it as a selectable backend.
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
    """Test backend for exercising structured adapter-unavailable failures.

    Two behaviours are exposed so callers can choose between a hard failure
    (``run_trial`` raising) and a soft failure (``run_trial`` returning a
    structured unavailable result). The default is the soft failure so the
    worker records a structured ``ADAPTER_UNAVAILABLE`` result instead of
    crashing. Production and development callers cannot select this adapter
    through the factory.
    """

    backend_name = "real_stub"

    #: When True, ``run_trial`` raises ``NotImplementedError``. Primarily for
    #: tests that want to assert the stub is wired through the adapter
    #: selection logic.
    raise_on_run: bool = False

    def run_trial(self, ctx: TrialContext) -> TrialResult:  # noqa: D401 — docstring inherited
        if self.raise_on_run:
            raise NotImplementedError(
                "RealSimulatorAdapterStub is an internal failure-path test adapter "
                "and cannot execute PX4/Gazebo."
            )
        return TrialResult(
            success=False,
            backend=self.backend_name,
            failure=TrialFailure(
                code=FAILURE_ADAPTER_UNAVAILABLE,
                reason=(
                    "The internal real_stub test adapter cannot run a simulation. "
                    "Use mock for workflow tests or configure real_cli for PX4/Gazebo."
                ),
            ),
            log_excerpt=f"[real_stub] scenario={ctx.scenario_type} UNAVAILABLE",
        )


__all__ = ["RealSimulatorAdapterStub"]
