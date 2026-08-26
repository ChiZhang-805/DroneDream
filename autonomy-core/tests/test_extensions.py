from __future__ import annotations

from dronedream_agent_core.extensions import (
    ExtensionExecutionError,
    ExtensionPlugin,
    ExtensionRegistry,
)


def _plugin(
    plugin_id: str,
    *,
    mode: str = "pipeline",
    failure: str = "isolate",
    order: int = 500,
    runs_after: tuple[str, ...] = (),
    runs_before: tuple[str, ...] = (),
    handler=lambda **kwargs: kwargs.get("value"),
) -> ExtensionPlugin:
    return ExtensionPlugin(
        plugin_id=plugin_id,
        version="1.0.0",
        package_sha256="a" * 64,
        capability_id=f"{plugin_id}.capability",
        slot_id="harness.test-pipeline",
        activation_mode=mode,  # type: ignore[arg-type]
        failure_mode=failure,  # type: ignore[arg-type]
        swap_policy="next-mission",
        pipeline_order=order,
        runs_after=runs_after,
        runs_before=runs_before,
        hooks={"transform": handler},
    )


def test_pipeline_is_ordered_and_hash_bound() -> None:
    registry = ExtensionRegistry()
    registry.register(
        _plugin(
            "pipeline.second",
            order=10,
            runs_after=("pipeline.first",),
            handler=lambda *, value: value + ["second"],
        )
    )
    registry.register(
        _plugin(
            "pipeline.first",
            order=900,
            handler=lambda *, value: value + ["first"],
        )
    )

    output, receipts = registry.invoke_pipeline("harness.test-pipeline", "transform", [])

    assert output == ["first", "second"]
    assert [receipt.plugin_id for receipt in receipts] == [
        "pipeline.first",
        "pipeline.second",
    ]
    assert all(receipt.outcome == "accepted" for receipt in receipts)
    assert all(len(receipt.input_sha256) == 64 for receipt in receipts)


def test_isolated_pipeline_failure_does_not_corrupt_value() -> None:
    registry = ExtensionRegistry()

    def broken(*, value: list[str]) -> list[str]:
        raise RuntimeError(value)

    registry.register(_plugin("pipeline.broken", order=10, handler=broken))
    registry.register(
        _plugin(
            "pipeline.healthy",
            order=20,
            handler=lambda *, value: value + ["healthy"],
        )
    )

    output, receipts = registry.invoke_pipeline("harness.test-pipeline", "transform", ["original"])

    assert output == ["original", "healthy"]
    assert [receipt.outcome for receipt in receipts] == ["failed", "accepted"]


def test_fail_closed_extension_stops_dispatch() -> None:
    registry = ExtensionRegistry()

    def broken(*, value: object) -> object:
        raise RuntimeError(value)

    registry.register(_plugin("pipeline.guard", failure="fail-closed", handler=broken))

    try:
        registry.invoke_pipeline("harness.test-pipeline", "transform", {})
    except ExtensionExecutionError as error:
        assert error.receipt.plugin_id == "pipeline.guard"
        assert error.receipt.outcome == "failed"
    else:
        raise AssertionError("fail-closed extension did not stop the pipeline")


def test_pipeline_cycle_is_rejected() -> None:
    registry = ExtensionRegistry()
    registry.register(_plugin("pipeline.a", runs_after=("pipeline.b",)))
    try:
        registry.register(_plugin("pipeline.b", runs_after=("pipeline.a",)))
    except ValueError as error:
        assert "cycle" in str(error)
    else:
        raise AssertionError("pipeline cycle was accepted")


def test_plugin_suite_can_register_multiple_hook_capabilities() -> None:
    registry = ExtensionRegistry()
    for capability_id, hook_name in (
        ("suite.risk", "risk"),
        ("suite.energy", "energy"),
    ):
        registry.register(
            ExtensionPlugin(
                plugin_id="suite.inspection",
                version="1.0.0",
                package_sha256="b" * 64,
                capability_id=capability_id,
                slot_id="harness.suite-advisors",
                activation_mode="multiple",
                failure_mode="isolate",
                swap_policy="next-mission",
                pipeline_order=100,
                runs_after=(),
                runs_before=(),
                hooks={hook_name: lambda **kwargs: kwargs["mission"]},
            )
        )

    risk, risk_receipts = registry.invoke_multiple(
        "harness.suite-advisors", "risk", mission="inspect"
    )
    energy, energy_receipts = registry.invoke_multiple(
        "harness.suite-advisors", "energy", mission="inspect"
    )

    assert risk == ["inspect"]
    assert energy == ["inspect"]
    assert risk_receipts[0].capability_id == "suite.risk"
    assert energy_receipts[0].capability_id == "suite.energy"
