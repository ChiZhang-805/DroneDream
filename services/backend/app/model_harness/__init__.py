"""Canonical Model + Harness policy, control-plane and runtime boundaries.

``domains`` owns the ten responsibility domains and memory policy.
``control_plane`` compiles immutable budgets and plugin selections.
``runtime`` distinguishes callable, delegated and fail-closed operations.
"""

__all__ = ["control_plane", "domains", "runtime"]
