from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MAVSDK = types.ModuleType("mavsdk")
MAVSDK.System = object
with mock.patch.dict(sys.modules, {"mavsdk": MAVSDK}):
    SPEC = importlib.util.spec_from_file_location(
        "px4_gazebo_smoke", ROOT / "runtime" / "scripts" / "px4-gazebo-smoke.py"
    )
    assert SPEC and SPEC.loader
    smoke = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(smoke)


class _ConnectionState:
    is_connected = True


class _Core:
    async def connection_state(self):
        yield _ConnectionState()


class _Parameters:
    def __init__(self, reads: list[float]) -> None:
        self.reads = iter(reads)
        self.writes: list[tuple[str, float]] = []

    async def get_param_float(self, _name: str) -> float:
        return next(self.reads)

    async def set_param_float(self, name: str, value: float) -> None:
        self.writes.append((name, value))


class _System:
    def __init__(self, reads: list[float]) -> None:
        self.core = _Core()
        self.param = _Parameters(reads)

    async def connect(self, *, system_address: str) -> None:
        if system_address != "udpin://0.0.0.0:14540":
            raise AssertionError(system_address)


class Px4GazeboSmokeTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_check_requires_restore_evidence(self) -> None:
        runtime_check = (ROOT / "runtime" / "scripts" / "runtime-check.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('float(payload["restored"])', runtime_check)
        self.assertIn("PX4 parameter restore mismatch", runtime_check)

    async def test_round_trip_confirms_original_value_was_restored(self) -> None:
        system = _System([1.0, 1.05, 1.0])
        with mock.patch.object(smoke, "System", return_value=system):
            payload = await smoke._round_trip()

        self.assertEqual(payload["restored"], 1.0)
        self.assertEqual(system.param.writes, [("MPC_XY_P", 1.05), ("MPC_XY_P", 1.0)])

    async def test_round_trip_fails_if_original_value_did_not_restore(self) -> None:
        system = _System([1.0, 1.05, 1.05])
        with (
            mock.patch.object(smoke, "System", return_value=system),
            self.assertRaisesRegex(RuntimeError, "restore"),
        ):
            await smoke._round_trip()


if __name__ == "__main__":
    unittest.main()
