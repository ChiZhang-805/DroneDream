"""Select the :class:`SimulatorAdapter` implementation at runtime.

Adapter choice is driven by the ``SIMULATOR_BACKEND`` environment variable
(default ``real_cli``). The worker calls :func:`get_simulator_adapter` once per
trial, so operators can switch backends without code changes.

Product runtime value:

* ``real_cli`` → :class:`RealCliSimulatorAdapter` (subprocess
  adapter driven by ``REAL_SIMULATOR_COMMAND`` and the JSON file protocol
  documented in ``docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md``)

``mock`` and ``real_stub`` remain registered only for isolated regression
tests. They are deliberately rejected outside ``APP_ENV=test`` so neither a
synthetic physics landscape nor a guaranteed-to-fail stub can be selected by
an operator-facing product.

The ``SIMULATOR_BACKEND`` env var, when set, overrides every job's
``simulator_backend`` column. Leave it unset to let per-job UI selection take
effect.
"""

from __future__ import annotations

import os

from app.config import get_settings
from app.simulator.base import SimulatorAdapter
from app.simulator.mock import MockSimulatorAdapter
from app.simulator.real_cli import RealCliSimulatorAdapter
from app.simulator.real_stub import RealSimulatorAdapterStub

DEFAULT_BACKEND = "real_cli"

_PUBLIC_REGISTRY: dict[str, type[SimulatorAdapter]] = {
    "real_cli": RealCliSimulatorAdapter,
}
_TEST_ONLY_REGISTRY: dict[str, type[SimulatorAdapter]] = {
    "mock": MockSimulatorAdapter,
    "real_stub": RealSimulatorAdapterStub,
}
_REGISTRY = {**_PUBLIC_REGISTRY, **_TEST_ONLY_REGISTRY}


class UnknownSimulatorBackendError(ValueError):
    """Raised when ``SIMULATOR_BACKEND`` is set to an unsupported value."""


def get_simulator_adapter(name: str | None = None) -> SimulatorAdapter:
    """Instantiate the adapter named ``name``.

    If ``name`` is ``None``, the ``SIMULATOR_BACKEND`` env var is used. Unknown
    names raise :class:`UnknownSimulatorBackendError` so mis-configurations
    surface at worker startup rather than silently running the wrong backend.
    """

    resolved = (name or os.environ.get("SIMULATOR_BACKEND") or DEFAULT_BACKEND).strip().lower()
    if resolved in _TEST_ONLY_REGISTRY:
        app_env = get_settings().app_env.strip().lower()
        if app_env not in {"test", "testing"}:
            supported = ", ".join(sorted(_PUBLIC_REGISTRY))
            raise UnknownSimulatorBackendError(
                f"SIMULATOR_BACKEND={resolved!r} is test-only and cannot be used "
                f"when APP_ENV={app_env!r}. Supported runtime backends: {supported}."
            )
    try:
        adapter_cls = _REGISTRY[resolved]
    except KeyError as exc:  # pragma: no cover – defensive
        supported = ", ".join(sorted(_PUBLIC_REGISTRY))
        raise UnknownSimulatorBackendError(
            f"Unknown SIMULATOR_BACKEND={resolved!r}. Supported: {supported}."
        ) from exc
    return adapter_cls()


__all__ = ["DEFAULT_BACKEND", "UnknownSimulatorBackendError", "get_simulator_adapter"]
