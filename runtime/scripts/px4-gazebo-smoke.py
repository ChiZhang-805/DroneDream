#!/usr/bin/env python3
"""Run one real headless PX4/Gazebo session and verify parameter round-trip."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import subprocess
from pathlib import Path

from mavsdk import System

PX4_ROOT = Path("/opt/PX4-Autopilot")
SMOKE_ROOT = Path("/var/lib/dronedream/runtime-smoke")


async def _round_trip() -> dict[str, float | str]:
    drone = System()
    await drone.connect(system_address="udp://:14540")

    async def wait_connected() -> None:
        async for state in drone.core.connection_state():
            if state.is_connected:
                return

    await asyncio.wait_for(wait_connected(), timeout=150)
    parameter = "MPC_XY_P"
    original = float(await asyncio.wait_for(drone.param.get_param_float(parameter), timeout=30))
    if not math.isfinite(original) or not 0.0 <= original <= 2.0:
        raise RuntimeError(
            f"PX4 returned unsafe original {parameter} value before smoke write: {original!r}"
        )
    written = min(2.0, max(0.0, original + 0.05 if original <= 1.95 else original - 0.05))
    if math.isclose(original, written, rel_tol=0.0, abs_tol=1e-6):
        raise RuntimeError("could not choose a distinct in-range PX4 smoke value")
    write_attempted = False
    try:
        write_attempted = True
        await asyncio.wait_for(drone.param.set_param_float(parameter, written), timeout=30)
        read_back = float(
            await asyncio.wait_for(drone.param.get_param_float(parameter), timeout=30)
        )
    finally:
        if write_attempted:
            await asyncio.wait_for(
                asyncio.shield(drone.param.set_param_float(parameter, original)),
                timeout=30,
            )
    if not all(math.isfinite(value) for value in (original, written, read_back)):
        raise RuntimeError("PX4 returned a non-finite parameter value")
    if abs(written - read_back) > 1e-4:
        raise RuntimeError(f"PX4 parameter round-trip mismatch: {written} != {read_back}")
    return {
        "parameter": parameter,
        "original": original,
        "written": written,
        "readBack": read_back,
    }


def main() -> int:
    SMOKE_ROOT.mkdir(parents=True, exist_ok=True)
    marker = SMOKE_ROOT / "parameter-readback.json"
    marker.unlink(missing_ok=True)
    log_path = SMOKE_ROOT / "px4-gazebo.log"
    env = os.environ.copy()
    env.update({"HEADLESS": "1", "PX4_GZ_MODEL": "x500"})
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - executable and argv are fixed.
            ["make", "px4_sitl", "gz_x500"],  # noqa: S607 - fixed build command.
            cwd=PX4_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            payload = asyncio.run(asyncio.wait_for(_round_trip(), timeout=300))
            if process.poll() is not None:
                raise RuntimeError(f"PX4/Gazebo exited early with {process.returncode}")
            subprocess.run(
                ["pgrep", "-f", "gz sim"],  # noqa: S607 - fixed process probe.
                check=True,
                capture_output=True,
                timeout=10,
            )
            marker.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
