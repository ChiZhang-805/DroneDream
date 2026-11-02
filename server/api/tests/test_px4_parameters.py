from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.parameters import ParameterValueValidationError
from app.simulator import px4_parameters as px4_parameter_module
from app.simulator.px4_parameters import (
    APPLIED_EVIDENCE_NAME,
    BEFORE_EVIDENCE_NAME,
    REQUESTED_EVIDENCE_NAME,
    ParameterApplicationError,
    ParameterReadbackError,
    apply_and_verify_parameters,
    build_px4_parameter_environment,
    connect_mavsdk_parameter_client,
    verify_environment_parameters,
    verify_environment_parameters_with_mavsdk,
    write_simulated_parameter_evidence,
)


class FakeParameterClient:
    def __init__(
        self, values: dict[str, int | float], *, corrupt_readback: str | None = None
    ) -> None:
        self.values = values.copy()
        self.corrupt_readback = corrupt_readback
        self.set_calls: list[tuple[str, int | float, str]] = []

    async def get_parameter(self, name: str, value_type: str) -> int | float:
        value = self.values[name]
        if self.corrupt_readback == name and self.set_calls:
            return float(value) + 0.2
        return value

    async def set_parameter(self, name: str, value: int | float, value_type: str) -> None:
        self.values[name] = value
        self.set_calls.append((name, value, value_type))


def test_mavsdk_client_close_is_idempotent_after_stop_failure() -> None:
    class _Owner:
        stop_calls = 0

        def _stop_mavsdk_server(self) -> None:
            self.stop_calls += 1
            raise RuntimeError("stop failed")

    owner = _Owner()
    client = px4_parameter_module.MavsdkParameterClient(object(), owner=owner)

    with pytest.raises(RuntimeError, match="stop failed"):
        client.close()
    client.close()

    assert owner.stop_calls == 1


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_environment_builder_uses_real_px4_names_and_stable_values() -> None:
    result = build_px4_parameter_environment({"MPC_XY_P": 1.0, "MC_ROLLRATE_D": 0.003})
    assert result == {
        "PX4_PARAM_MPC_XY_P": "1",
        "PX4_PARAM_MC_ROLLRATE_D": "0.003",
    }


def test_environment_builder_supports_reboot_parameters_at_process_start() -> None:
    assert build_px4_parameter_environment({"IMU_GYRO_CUTOFF": 40.0}) == {
        "PX4_PARAM_IMU_GYRO_CUTOFF": "40"
    }


def test_environment_builder_enforces_safe_bounds_by_default() -> None:
    with pytest.raises(ParameterValueValidationError):
        build_px4_parameter_environment({"MPC_XY_VEL_I_ACC": 5.0})

    result = build_px4_parameter_environment({"MPC_XY_VEL_I_ACC": 5.0}, enforce_safe_bounds=False)
    assert result["PX4_PARAM_MPC_XY_VEL_I_ACC"] == "5"


def test_mavsdk_style_client_transaction_writes_before_requested_applied(tmp_path: Path) -> None:
    client = FakeParameterClient({"MPC_XY_P": 0.95, "MPC_XY_VEL_P_ACC": 1.8})
    result = asyncio.run(
        apply_and_verify_parameters(
            {"MPC_XY_P": 1.1, "MPC_XY_VEL_P_ACC": 2.0},
            client,
            tmp_path,
            context={"trial_id": "trial-1"},
        )
    )

    assert result.verified is True
    assert result.before == {"MPC_XY_P": 0.95, "MPC_XY_VEL_P_ACC": 1.8}
    assert result.applied == {"MPC_XY_P": 1.1, "MPC_XY_VEL_P_ACC": 2.0}
    assert [call[0] for call in client.set_calls] == ["MPC_XY_P", "MPC_XY_VEL_P_ACC"]
    assert _read(tmp_path / REQUESTED_EVIDENCE_NAME)["values"] == result.requested
    assert _read(tmp_path / BEFORE_EVIDENCE_NAME)["values"] == result.before
    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["values"] == result.applied
    assert applied["verification"] == {"mismatches": {}, "verified": True}
    assert applied["context"]["trial_id"] == "trial-1"


def test_live_transaction_rejects_reboot_parameter_before_contacting_px4(
    tmp_path: Path,
) -> None:
    client = FakeParameterClient({"IMU_GYRO_CUTOFF": 40.0})

    with pytest.raises(ParameterApplicationError, match="Start a fresh SITL process"):
        asyncio.run(
            apply_and_verify_parameters(
                {"IMU_GYRO_CUTOFF": 45.0},
                client,
                tmp_path,
            )
        )

    assert client.set_calls == []
    assert _read(tmp_path / REQUESTED_EVIDENCE_NAME)["values"] == {"IMU_GYRO_CUTOFF": 45.0}
    assert _read(tmp_path / BEFORE_EVIDENCE_NAME)["status"] == "error"
    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["status"] == "error"
    assert "reboot-required" in applied["verification"]["error"]


def test_readback_mismatch_is_fatal_but_preserves_evidence(tmp_path: Path) -> None:
    client = FakeParameterClient({"MPC_XY_P": 0.95}, corrupt_readback="MPC_XY_P")

    with pytest.raises(ParameterReadbackError):
        asyncio.run(
            apply_and_verify_parameters(
                {"MPC_XY_P": 1.1},
                client,
                tmp_path,
            )
        )

    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["status"] == "mismatch"
    assert applied["verification"]["verified"] is False
    assert "MPC_XY_P" in applied["verification"]["mismatches"]
    # The fake transport corrupts every post-write readback, so the original
    # value is restored in storage but cannot honestly be marked as verified.
    assert applied["verification"]["rollback_succeeded"] is False
    assert "MPC_XY_P" in applied["verification"]["rollback_errors"]
    assert client.values["MPC_XY_P"] == 0.95


def test_partial_live_parameter_write_rolls_back_previous_values(tmp_path: Path) -> None:
    class FailingClient(FakeParameterClient):
        async def set_parameter(self, name: str, value: int | float, value_type: str) -> None:
            if name == "MPC_XY_VEL_P_ACC" and value == 2.0:
                raise RuntimeError("transport dropped")
            await super().set_parameter(name, value, value_type)

    client = FailingClient({"MPC_XY_P": 0.95, "MPC_XY_VEL_P_ACC": 1.8})
    with pytest.raises(ParameterApplicationError, match="transport dropped"):
        asyncio.run(
            apply_and_verify_parameters(
                {"MPC_XY_P": 1.1, "MPC_XY_VEL_P_ACC": 2.0},
                client,
                tmp_path,
            )
        )
    assert client.values == {"MPC_XY_P": 0.95, "MPC_XY_VEL_P_ACC": 1.8}
    verification = _read(tmp_path / APPLIED_EVIDENCE_NAME)["verification"]
    assert verification["rollback_attempted"] is True
    assert verification["rollback_succeeded"] is True


def test_mavsdk_connection_timeout_stops_embedded_server(monkeypatch) -> None:
    class _Core:
        async def connection_state(self):
            while True:
                yield type("State", (), {"is_connected": False})()
                await asyncio.sleep(1)

    class _System:
        latest: _System | None = None

        def __init__(self) -> None:
            self.core = _Core()
            self.param = object()
            self.stopped = False
            _System.latest = self

        async def connect(self, *, system_address: str) -> None:
            assert system_address == "udp://:14540"

        def _stop_mavsdk_server(self) -> None:
            self.stopped = True

    mavsdk = ModuleType("mavsdk")
    mavsdk.System = _System  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mavsdk", mavsdk)

    with pytest.raises(ParameterApplicationError, match="timed out"):
        asyncio.run(
            connect_mavsdk_parameter_client(
                "udp://:14540",
                timeout_seconds=0.01,
            )
        )
    assert _System.latest is not None
    assert _System.latest.stopped is True


def test_mavsdk_connection_cancellation_stops_embedded_server_and_propagates(
    monkeypatch,
) -> None:
    class _Core:
        async def connection_state(self):
            raise asyncio.CancelledError
            yield  # pragma: no cover - makes this an async generator.

    class _System:
        latest: _System | None = None

        def __init__(self) -> None:
            self.core = _Core()
            self.param = object()
            self.stopped = False
            _System.latest = self

        async def connect(self, *, system_address: str) -> None:
            assert system_address == "udp://:14540"

        def _stop_mavsdk_server(self) -> None:
            self.stopped = True

    mavsdk = ModuleType("mavsdk")
    mavsdk.System = _System  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mavsdk", mavsdk)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            connect_mavsdk_parameter_client(
                "udp://:14540",
                timeout_seconds=1.0,
            )
        )
    assert _System.latest is not None
    assert _System.latest.stopped is True


def test_mavsdk_connect_failure_stops_embedded_server_and_propagates(monkeypatch) -> None:
    class _System:
        latest: _System | None = None

        def __init__(self) -> None:
            self.core = object()
            self.param = object()
            self.stopped = False
            _System.latest = self

        async def connect(self, *, system_address: str) -> None:
            assert system_address == "udp://:14540"
            raise RuntimeError("embedded transport failed")

        def _stop_mavsdk_server(self) -> None:
            self.stopped = True

    mavsdk = ModuleType("mavsdk")
    mavsdk.System = _System  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mavsdk", mavsdk)

    with pytest.raises(RuntimeError, match="embedded transport failed"):
        asyncio.run(
            connect_mavsdk_parameter_client(
                "udp://:14540",
                timeout_seconds=1.0,
            )
        )
    assert _System.latest is not None
    assert _System.latest.stopped is True


def test_environment_transport_readback_does_not_set_again(tmp_path: Path) -> None:
    client = FakeParameterClient({"MPC_XY_P": 1.1})
    result = asyncio.run(
        verify_environment_parameters(
            {"MPC_XY_P": 1.1},
            client,
            tmp_path,
            previous_environment={"PX4_PARAM_MPC_XY_P": "0.95"},
        )
    )
    assert result.verified is True
    assert result.before == {"MPC_XY_P": "0.95"}
    assert client.set_calls == []
    assert _read(tmp_path / BEFORE_EVIDENCE_NAME)["kind"] == "before_environment_override"


def test_environment_transport_reconciles_live_airframe_override(tmp_path: Path) -> None:
    client = FakeParameterClient({"MPC_THR_HOVER": 0.6})
    result = asyncio.run(
        verify_environment_parameters(
            {"MPC_THR_HOVER": 0.5},
            client,
            tmp_path,
            previous_environment={"PX4_PARAM_MPC_THR_HOVER": "0.5"},
            reconcile_live_mismatches=True,
        )
    )

    assert result.verified is True
    assert result.applied == {"MPC_THR_HOVER": pytest.approx(0.5)}
    assert client.set_calls == [("MPC_THR_HOVER", 0.5, "float")]
    verification = _read(tmp_path / APPLIED_EVIDENCE_NAME)["verification"]
    assert verification["initial_readback"] == {"MPC_THR_HOVER": 0.6}
    mismatch = verification["initial_mismatches"]["MPC_THR_HOVER"]
    assert mismatch["requested"] == 0.5
    assert mismatch["applied"] == 0.6
    assert mismatch["absolute_tolerance"] == pytest.approx(0.001)
    assert verification["reconciliation_transport"] == "mavsdk"
    assert verification["reconciled_parameters"] == ["MPC_THR_HOVER"]


def test_environment_transport_never_reconciles_reboot_parameter_live(tmp_path: Path) -> None:
    client = FakeParameterClient({"IMU_GYRO_CUTOFF": 40.0})

    with pytest.raises(ParameterReadbackError, match="IMU_GYRO_CUTOFF"):
        asyncio.run(
            verify_environment_parameters(
                {"IMU_GYRO_CUTOFF": 45.0},
                client,
                tmp_path,
                reconcile_live_mismatches=True,
            )
        )

    assert client.set_calls == []
    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["status"] == "mismatch"
    assert applied["verification"]["reconciled_parameters"] == []


@pytest.mark.parametrize(
    ("name", "requested", "unsafe_readback"),
    (
        ("MPC_XY_P", 1.0, float("nan")),
        ("MPC_XY_P", 1.0, True),
        ("MC_AIRMODE", 1, 1.5),
    ),
)
def test_environment_transport_rejects_invalid_px4_readback_values(
    tmp_path: Path,
    name: str,
    requested: int | float,
    unsafe_readback: object,
) -> None:
    class UnsafeReadbackClient(FakeParameterClient):
        async def get_parameter(self, name: str, value_type: str) -> int | float:
            del name, value_type
            return unsafe_readback  # type: ignore[return-value]

    client = UnsafeReadbackClient({name: requested})

    with pytest.raises(ParameterApplicationError, match="invalid PX4 parameter readback"):
        asyncio.run(
            verify_environment_parameters(
                {name: requested},
                client,
                tmp_path,
            )
        )

    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["status"] == "error"
    assert applied["values"] == {}
    assert applied["verification"]["verified"] is False


def test_reboot_parameter_is_verified_after_startup_environment_injection(
    tmp_path: Path,
) -> None:
    client = FakeParameterClient({"IMU_GYRO_CUTOFF": 45.0})
    result = asyncio.run(
        verify_environment_parameters(
            {"IMU_GYRO_CUTOFF": 45.0},
            client,
            tmp_path,
            previous_environment={"PX4_PARAM_IMU_GYRO_CUTOFF": "40"},
        )
    )

    assert result.verified is True
    assert result.applied == {"IMU_GYRO_CUTOFF": 45.0}
    assert client.set_calls == []


def test_site_dry_run_evidence_is_explicitly_marked_simulated(tmp_path: Path) -> None:
    result = write_simulated_parameter_evidence({"MPC_XY_P": 1.0}, tmp_path)
    assert result.verified is True
    for filename in (
        REQUESTED_EVIDENCE_NAME,
        BEFORE_EVIDENCE_NAME,
        APPLIED_EVIDENCE_NAME,
    ):
        assert _read(tmp_path / filename)["status"] == "simulated"
    assert _read(tmp_path / APPLIED_EVIDENCE_NAME)["verification"]["simulated"] is True


def test_connection_failure_still_writes_complete_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_connection(*_args, **_kwargs):
        raise ParameterApplicationError("connection unavailable")

    monkeypatch.setattr(
        px4_parameter_module,
        "connect_mavsdk_parameter_client",
        fail_connection,
    )

    with pytest.raises(ParameterApplicationError, match="connection unavailable"):
        asyncio.run(
            verify_environment_parameters_with_mavsdk(
                {"MPC_XY_P": 1.0},
                tmp_path,
                connection="udp://:14540",
            )
        )

    assert _read(tmp_path / REQUESTED_EVIDENCE_NAME)["values"] == {"MPC_XY_P": 1.0}
    assert (tmp_path / BEFORE_EVIDENCE_NAME).is_file()
    applied = _read(tmp_path / APPLIED_EVIDENCE_NAME)
    assert applied["status"] == "error"
    assert applied["verification"]["verified"] is False
    assert applied["verification"]["stage"] == "connection"
