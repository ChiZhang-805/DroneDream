"""Simulator adapter layer (Phase 4).

All trial-level simulation work goes through :class:`SimulatorAdapter`. The
worker never hardcodes simulator logic; it asks :func:`get_simulator_adapter`
for the concrete backend (mock by default, real stub for future PX4/Gazebo).

Public surface:

* :class:`SimulatorAdapter` — abstract interface.
* :class:`TrialContext` — all inputs to one trial.
* :class:`TrialResult`, :class:`TrialMetricsPayload`,
  :class:`ArtifactMetadata`, :class:`TrialFailure` — adapter return shapes.
* :class:`MockSimulatorAdapter` — deterministic MVP backend.
* :class:`RealSimulatorAdapterStub` — placeholder for future integration.
* :func:`get_simulator_adapter` — env-var controlled factory.
"""

from __future__ import annotations

from app.simulator.base import (
    ArtifactMetadata,
    JobConfig,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialMetricsPayload,
    TrialResult,
)
from app.simulator.factory import get_simulator_adapter
from app.simulator.mock import MockSimulatorAdapter
from app.simulator.real_stub import RealSimulatorAdapterStub

__all__ = [
    "ArtifactMetadata",
    "JobConfig",
    "MockSimulatorAdapter",
    "RealSimulatorAdapterStub",
    "SimulatorAdapter",
    "TrialContext",
    "TrialFailure",
    "TrialMetricsPayload",
    "TrialResult",
    "get_simulator_adapter",
]
