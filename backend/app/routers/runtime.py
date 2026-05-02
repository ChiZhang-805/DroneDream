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
    hosted_real_cli_requires_px4 = _env_bool("HOSTED_REAL_CLI_REQUIRES_PX4", True)
    px4_gazebo_dry_run = _env_bool("PX4_GAZEBO_DRY_RUN", False)
    px4_gazebo_headless = _env_bool("PX4_GAZEBO_HEADLESS", False)
    px4_gazebo_launch_command = _normalized_or_none("PX4_GAZEBO_LAUNCH_COMMAND")
    px4_autopilot_dir = _normalized_or_none("PX4_AUTOPILOT_DIR")
    px4_autopilot_host_dir = _normalized_or_none("PX4_AUTOPILOT_HOST_DIR")
    px4_make_target = _normalized_or_none("PX4_MAKE_TARGET")
    gazebo_viewer_url_configured = _normalized_or_none("VITE_GAZEBO_VIEWER_URL") is not None
    vnc_configured = _normalized_or_none("VNC_PASSWORD") is not None

    launch_configured = px4_gazebo_launch_command is not None
    autopilot_dir_configured = px4_autopilot_dir is not None
    autopilot_host_dir_configured = px4_autopilot_host_dir is not None

    hard_missing = []
    if hosted_real_cli_requires_px4:
        if px4_gazebo_dry_run:
            hard_missing.append("PX4_GAZEBO_DRY_RUN must be false")
        if not launch_configured:
            hard_missing.append("PX4_GAZEBO_LAUNCH_COMMAND is required")
        if not autopilot_dir_configured:
            hard_missing.append("PX4_AUTOPILOT_DIR is required")
        if px4_gazebo_headless:
            hard_missing.append("PX4_GAZEBO_HEADLESS must be false")
        if not vnc_configured:
            hard_missing.append("VNC_PASSWORD is required")
    mode_advisory = None
    if hosted_real_cli_requires_px4 and (not gazebo_viewer_url_configured):
        mode_advisory = "Gazebo viewer URL is not configured; real simulation can run but web iframe will not be embedded."

    real_mode_config_complete = len(hard_missing) == 0 and launch_configured and autopilot_dir_configured and (not px4_gazebo_dry_run)

    if hosted_real_cli_requires_px4 and hard_missing:
        mode_label = "real_cli configuration incomplete"
        mode_warning = "; ".join(hard_missing)
    elif real_mode_config_complete:
        mode_label = "real_cli PX4/Gazebo real mode"
        mode_warning = None
    else:
        mode_label = "mock/dev"
        mode_warning = None

    return ok({
        "simulator_backend_env_override": simulator_backend_env_override,
        "real_simulator_command": real_simulator_command,
        "hosted_real_cli_requires_px4": hosted_real_cli_requires_px4,
        "gazebo_viewer_url_configured": gazebo_viewer_url_configured,
        "vnc_configured": vnc_configured,
        "px4_gazebo_dry_run": px4_gazebo_dry_run,
        "px4_gazebo_headless": px4_gazebo_headless,
        "px4_gazebo_launch_command_configured": launch_configured,
        "px4_autopilot_dir_configured": autopilot_dir_configured,
        "px4_autopilot_host_dir_configured": autopilot_host_dir_configured,
        "real_mode_config_complete": real_mode_config_complete,
        "px4_make_target": px4_make_target,
        "mode_label": mode_label,
        "mode_warning": mode_warning,
        "mode_advisory": mode_advisory,
        "runtime_source_note": (
            "Runtime values are read from backend/shared deployment environment "
            "(for example deploy/hosted-b/.env), not from live probes of every worker process."
        ),
    })
