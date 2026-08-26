from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from dronedream_agent_core.contracts import (
    PreparedMission,
    Px4GazeboRunEvidence,
    RuntimeCheckpointRequest,
)
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _telemetry_integrity(*, request: RuntimeCheckpointRequest, **_: Any) -> dict[str, object]:
    vectors = (
        request.observed_position_ned_m,
        request.observed_velocity_ned_mps,
        request.commanded_position_ned_m,
    )
    values = [component for vector in vectors for component in (vector.x, vector.y, vector.z)]
    values.extend([request.position_error_m, request.speed_mps, request.battery_percent])
    finite = all(math.isfinite(value) for value in values)
    deterministic = all(request.deterministic_gates.values())
    accepted = finite and deterministic
    return {
        "detector": "telemetry-integrity",
        "accepted": accepted,
        "gates": {
            "all_values_finite": finite,
            "executor_deterministic_gates_passed": deterministic,
        },
        "issue_codes": [] if accepted else ["RUNTIME_TELEMETRY_INTEGRITY_REJECTED"],
    }


def _tracking_stability(
    *,
    request: RuntimeCheckpointRequest,
    configuration: dict[str, object] | None = None,
    **_: Any,
) -> dict[str, object]:
    configured = configuration or {}
    maximum_error = float(configured.get("maximum_position_error_m", 1.5))
    maximum_speed = float(configured.get("maximum_checkpoint_speed_mps", 3.0))
    gates = {
        "position_error_within_policy": request.position_error_m <= maximum_error,
        "checkpoint_speed_within_policy": request.speed_mps <= maximum_speed,
    }
    accepted = all(gates.values())
    return {
        "detector": "tracking-stability",
        "accepted": accepted,
        "gates": gates,
        "observed_position_error_m": request.position_error_m,
        "observed_speed_mps": request.speed_mps,
        "issue_codes": [] if accepted else ["RUNTIME_TRACKING_STABILITY_REJECTED"],
    }


def _battery_reserve(
    *,
    request: RuntimeCheckpointRequest,
    configuration: dict[str, object] | None = None,
    **_: Any,
) -> dict[str, object]:
    threshold = float((configuration or {}).get("minimum_battery_percent", 20.0))
    accepted = request.battery_percent >= threshold
    return {
        "detector": "battery-reserve",
        "accepted": accepted,
        "battery_percent": request.battery_percent,
        "minimum_battery_percent": threshold,
        "issue_codes": [] if accepted else ["RUNTIME_BATTERY_RESERVE_LOW"],
    }


def _runtime_gate_integrity(*, runtime: Px4GazeboRunEvidence, **_: Any) -> dict[str, object]:
    gates = runtime.gates.model_dump()
    accepted = runtime.status == "verified" and all(gates.values())
    return {
        "evaluation": "runtime-gate-integrity",
        "accepted": accepted,
        "runtime_status": runtime.status,
        "gates": gates,
        "issue_codes": [] if accepted else ["RUNTIME_GATE_INTEGRITY_REJECTED"],
    }


def _artifact_binding(*, binding_gates: dict[str, bool], **_: Any) -> dict[str, object]:
    accepted = all(binding_gates.values())
    return {
        "evaluation": "artifact-binding",
        "accepted": accepted,
        "gates": dict(binding_gates),
        "issue_codes": [] if accepted else ["RUNTIME_ARTIFACT_BINDING_REJECTED"],
    }


def _atomic_text(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _export_summary(
    *,
    run_dir: Path,
    prepared: PreparedMission,
    runtime: Px4GazeboRunEvidence,
    binding_gates: dict[str, bool],
    plugin_evaluations: list[dict[str, object]],
    **_: Any,
) -> dict[str, object]:
    destination = run_dir / "plugin-evidence" / "mission-summary.json"
    payload = {
        "schema_version": "dronedream.plugin-mission-summary.v1",
        "contract_id": prepared.contract.contract_id,
        "world": runtime.world,
        "vehicle": runtime.vehicle,
        "runtime_status": runtime.status,
        "binding_gates": binding_gates,
        "plugin_evaluations": plugin_evaluations,
    }
    _atomic_text(
        destination,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {"accepted": True, "exporter": "mission-summary-json", "path": str(destination)}


def _export_metrics_csv(
    *,
    run_dir: Path,
    runtime: Px4GazeboRunEvidence,
    binding_gates: dict[str, bool],
    **_: Any,
) -> dict[str, object]:
    destination = run_dir / "plugin-evidence" / "runtime-metrics.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, object]] = [
        (f"gate.{name}", value) for name, value in sorted(binding_gates.items())
    ]
    rows.extend(
        (f"measurement.{name}", value)
        for name, value in sorted(runtime.measurements.model_dump(mode="json").items())
        if isinstance(value, (str, int, float, bool)) or value is None
    )
    temporary = destination.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)
    temporary.replace(destination)
    return {
        "accepted": True,
        "exporter": "runtime-metrics-csv",
        "path": str(destination),
        "row_count": len(rows),
    }


def _export_track_geojson(
    *, run_dir: Path, prepared: PreparedMission, **_: Any
) -> dict[str, object]:
    destination = run_dir / "plugin-evidence" / "planned-track.geojson"
    coordinates = [
        [point.east_m, point.north_m, point.up_m]
        for point in prepared.px4_track.source_world_points
    ]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "contract_id": prepared.contract.contract_id,
                    "coordinate_frame": "Gazebo ENU",
                    "point_count": len(coordinates),
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        ],
    }
    _atomic_text(
        destination,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "accepted": True,
        "exporter": "planned-track-geojson",
        "path": str(destination),
        "point_count": len(coordinates),
    }


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    anomaly_plugins = [
        (
            "runtime.anomaly-telemetry",
            "遥测完整性检测",
            "拒绝非有限数值或执行器确定性门失败的检查点。",
            _telemetry_integrity,
            {},
        ),
        (
            "runtime.anomaly-tracking",
            "跟踪稳定性检测",
            "按可配置位置误差与检查点速度限制决定是否继续。",
            _tracking_stability,
            {
                "type": "object",
                "properties": {
                    "maximum_position_error_m": {
                        "type": "number",
                        "minimum": 0.05,
                        "maximum": 20,
                    },
                    "maximum_checkpoint_speed_mps": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 20,
                    },
                },
                "additionalProperties": False,
            },
        ),
        (
            "runtime.anomaly-battery",
            "电量余量检测",
            "在每个运行检查点实施可配置最低电量门。",
            _battery_reserve,
            {
                "type": "object",
                "properties": {
                    "minimum_battery_percent": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 80,
                    }
                },
                "additionalProperties": False,
            },
        ),
    ]
    for index, (plugin_id, name, description, handler, schema) in enumerate(
        anomaly_plugins, start=1
    ):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.detect",
                capability_kind="anomaly-detector",
                capability_name=name,
                capability_description=description,
                category_id="runtime",
                category_label="运行与接管",
                slot_id="runtime.anomaly-detectors",
                slot_label="运行异常检测器",
                activation_mode="multiple",
                category_order=70,
                slot_order=30,
                plugin_order=index * 10,
                hooks={"evaluate_checkpoint": handler},
                default_enabled=True,
                failure_mode="fail-closed",
                swap_policy="safe-hold",
                configuration_schema=schema,
                permissions=["mission.read", "telemetry.read", "configuration.read"],
            )
        )
    runtime_gates = [
        (
            "evaluation.runtime-gates",
            "运行门完整性",
            "验收 PX4/Gazebo 运行状态与全部原生运行门。",
            _runtime_gate_integrity,
        ),
        (
            "evaluation.artifact-binding",
            "工件绑定完整性",
            "验收运行文件、任务合同、地图和无人机哈希绑定。",
            _artifact_binding,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(runtime_gates, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.evaluate",
                capability_kind="evaluator",
                capability_name=name,
                capability_description=description,
                category_id="evaluation",
                category_label="证据与评测",
                slot_id="evaluation.runtime-gates",
                slot_label="运行验收门",
                activation_mode="multiple",
                category_order=90,
                slot_order=20,
                plugin_order=index * 10,
                hooks={"evaluate_runtime": handler},
                default_enabled=True,
                failure_mode="fail-closed",
                swap_policy="next-mission",
                permissions=["mission.read", "telemetry.read"],
            )
        )
    exporters = [
        (
            "evidence.summary-json",
            "任务摘要 JSON",
            "导出合同、运行门和插件评测的机器可读摘要。",
            _export_summary,
        ),
        (
            "evidence.metrics-csv",
            "运行指标 CSV",
            "导出运行测量与绑定门，便于数据分析和批量评测。",
            _export_metrics_csv,
        ),
        (
            "evidence.track-geojson",
            "航迹 GeoJSON",
            "导出 Gazebo ENU 三维计划航迹，便于巡检、测绘和外部 GIS 审查。",
            _export_track_geojson,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(exporters, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.export",
                capability_kind="evidence-exporter",
                capability_name=name,
                capability_description=description,
                category_id="evaluation",
                category_label="证据与评测",
                slot_id="evidence.exporters",
                slot_label="证据导出器",
                activation_mode="multiple",
                category_order=90,
                slot_order=30,
                plugin_order=index * 10,
                hooks={"export_evidence": handler},
                default_enabled=plugin_id != "evidence.track-geojson",
                failure_mode="isolate",
                swap_policy="next-mission",
                permissions=["mission.read", "telemetry.read", "evidence.write"],
            )
        )
    return definitions
