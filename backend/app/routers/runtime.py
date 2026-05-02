"""Runtime configuration visibility routes under /api/v1."""

from __future__ import annotations

import os

from fastapi import APIRouter

from app.response import ok

router = APIRouter(tags=["runtime"])


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalized_or_none(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


@router.get("/runtime")
def runtime_state() -> dict[str, object]:
    simulator_backend_env_override = _normalized_or_none("SIMULATOR_BACKEND")
    real_simulator_command = os.environ.get("REAL_SIMULATOR_COMMAND", "")
    px4_gazebo_dry_run = _env_bool("PX4_GAZEBO_DRY_RUN", True)
    px4_gazebo_headless = _env_bool("PX4_GAZEBO_HEADLESS", True)
    px4_gazebo_launch_command = _normalized_or_none("PX4_GAZEBO_LAUNCH_COMMAND")
    px4_autopilot_dir = _normalized_or_none("PX4_AUTOPILOT_DIR")
    px4_make_target = _normalized_or_none("PX4_MAKE_TARGET")
    launch_configured = px4_gazebo_launch_command is not None
    autopilot_configured = px4_autopilot_dir is not None
    real_mode_incomplete = (not px4_gazebo_dry_run) and (
        (not launch_configured) or (not autopilot_configured)
    )

    mode_label = (
        "real_cli dry-run" if px4_gazebo_dry_run else "real_cli PX4/Gazebo real mode"
    )
    mode_warning = (
        "No external PX4/Gazebo process is launched."
        if px4_gazebo_dry_run
        else ("PX4/Gazebo real mode is incomplete." if real_mode_incomplete else None)
    )
    return ok(
        {
            "simulator_backend_env_override": simulator_backend_env_override,
            "real_simulator_command": real_simulator_command,
            "px4_gazebo_dry_run": px4_gazebo_dry_run,
            "px4_gazebo_headless": px4_gazebo_headless,
            "px4_gazebo_launch_command_configured": launch_configured,
            "px4_autopilot_dir_configured": autopilot_configured,
            "px4_make_target": px4_make_target,
            "mode_label": mode_label,
            "mode_warning": mode_warning,
        }
    )
