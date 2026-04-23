"""Select the :class:`SimulatorAdapter` implementation at runtime.

Adapter choice is driven by the ``SIMULATOR_BACKEND`` environment variable
(default ``mock``). The worker calls :func:`get_simulator_adapter` once per
trial, so operators can switch backends without code changes.

Supported values:

* ``mock`` → :class:`MockSimulatorAdapter` (default; MVP)
* ``real_stub`` → :class:`RealSimulatorAdapterStub` (placeholder that always
  returns ``ADAPTER_UNAVAILABLE``)
* ``real_cli`` → :class:`RealCliSimulatorAdapter` (Phase 8; subprocess
  adapter driven by ``REAL_SIMULATOR_COMMAND`` and the JSON file protocol
  documented in ``docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md``)

Phase 8 note: the ``SIMULATOR_BACKEND`` env var, when set, still overrides
every job's ``simulator_backend`` column. Leave it unset to let per-job UI
selection take effect.
"""

from __future__ import annotations

import os

from app.simulator.base import SimulatorAdapter
from app.simulator.mock import MockSimulatorAdapter
from app.simulator.real_cli import RealCliSimulatorAdapter
from app.simulator.real_stub import RealSimulatorAdapterStub

DEFAULT_BACKEND = "mock"

_REGISTRY: dict[str, type[SimulatorAdapter]] = {
    "mock": MockSimulatorAdapter,
    "real_stub": RealSimulatorAdapterStub,
    "real_cli": RealCliSimulatorAdapter,
}


class UnknownSimulatorBackendError(ValueError):
    """Raised when ``SIMULATOR_BACKEND`` is set to an unsupported value."""


def get_simulator_adapter(name: str | None = None) -> SimulatorAdapter:
    """Instantiate the adapter named ``name``.

    If ``name`` is ``None``, the ``SIMULATOR_BACKEND`` env var is used. Unknown
    names raise :class:`UnknownSimulatorBackendError` so mis-configurations
    surface at worker startup rather than silently running the wrong backend.
    """

    resolved = (name or os.environ.get("SIMULATOR_BACKEND") or DEFAULT_BACKEND).strip().lower()
    try:
        adapter_cls = _REGISTRY[resolved]
    except KeyError as exc:  # pragma: no cover — defensive
        supported = ", ".join(sorted(_REGISTRY))
        raise UnknownSimulatorBackendError(
            f"Unknown SIMULATOR_BACKEND={resolved!r}. Supported: {supported}."
        ) from exc
    return adapter_cls()


__all__ = ["DEFAULT_BACKEND", "UnknownSimulatorBackendError", "get_simulator_adapter"]
