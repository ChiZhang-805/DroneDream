"""Job orchestration primitives.

This package contains the Phase 3 async execution surface: job manager,
trial dispatcher, trial executor (mock), minimal aggregation, and a polling
runner loop that the worker process drives. It is deliberately imported by
the worker entrypoint (which installs the backend editable) so that job
and trial state machines live in a single authoritative place.
"""

from __future__ import annotations

__all__: list[str] = []
