"""Composable route-candidate generators and deterministic multi-objective ranking."""

from __future__ import annotations

from collections.abc import Callable

from dronedream_agent_core.contracts import (
    GraphRoute,
    RouteAlternativeDecision,
    RouteAlternativeSet,
    RouteQuery,
)
from dronedream_agent_core.navigation import (
    clearance_first_route,
    energy_efficient_route,
    stability_first_route,
)
from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.tools import ToolPlugin


def _candidate_definition(
    *,
    plugin_id: str,
    name: str,
    description: str,
    order: int,
    planner: Callable,
) -> PluginDefinition:
    def tools(environment: ToolEnvironment) -> list[ToolPlugin]:
        return [
            ToolPlugin(
                tool_id=f"{plugin_id}.candidate",
                version="1.0.0",
                authority="plan",
                input_type=RouteQuery,
                output_type=GraphRoute,
                handler=lambda query: planner(environment.map_graph, query),
            )
        ]

    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id=plugin_id,
            name=name,
            version="1.0.0",
            description=description,
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definitions"
            ),
            capabilities=[
                PluginCapability(
                    capability_id=f"{plugin_id}.candidate",
                    kind="plan-optimizer",
                    name=name,
                    description=description,
                    authority="plan",
                    input_schema=RouteQuery.model_json_schema(),
                    output_schema=GraphRoute.model_json_schema(),
                    metadata={"produces_alternative": True},
                )
            ],
            permissions=["asset.read", "mission.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.route-candidates",
                slot_label="候选路线生成器",
                activation_mode="multiple",
                scope="mission",
                failure_mode="isolate",
                category_order=40,
                slot_order=14,
                plugin_order=order,
            ),
        ),
        tool_factory=tools,
    )


def _ranker_tools(environment: ToolEnvironment) -> list[ToolPlugin]:
    configuration = dict(environment.plugin_configuration or {})

    def rank(value: RouteAlternativeSet) -> RouteAlternativeDecision:
        candidates = value.candidates
        feasible = [candidate for candidate in candidates if candidate.feasible]
        if not feasible:
            raise ValueError("ROUTE_ALTERNATIVE_NO_FEASIBLE_CANDIDATE")
        weights = {
            "distance_m": float(
                configuration.get(
                    "distance_weight", value.objective_weights.get("distance_m", 0.20)
                )
            ),
            "minimum_clearance_m": float(
                configuration.get(
                    "clearance_weight",
                    value.objective_weights.get("minimum_clearance_m", 0.46),
                )
            ),
            "energy_proxy": float(
                configuration.get(
                    "energy_weight", value.objective_weights.get("energy_proxy", 0.14)
                )
            ),
            "transition_count": float(
                configuration.get(
                    "stability_weight",
                    value.objective_weights.get("transition_count", 0.10),
                )
            ),
            "qualification_penalty": float(
                configuration.get(
                    "qualification_weight",
                    value.objective_weights.get("qualification_penalty", 0.10),
                )
            ),
        }
        if sum(weights.values()) <= 0:
            raise ValueError("ROUTE_ALTERNATIVE_WEIGHTS_INVALID")
        values_by_metric = {
            metric: [candidate.objectives[metric] for candidate in feasible] for metric in weights
        }

        def normalized(candidate, metric: str) -> float:
            values = values_by_metric[metric]
            low, high = min(values), max(values)
            if high == low:
                return 1.0
            raw = candidate.objectives[metric]
            if metric == "minimum_clearance_m":
                return (raw - low) / (high - low)
            return (high - raw) / (high - low)

        scores = {
            candidate.alternative_id: round(
                sum(weights[metric] * normalized(candidate, metric) for metric in weights),
                8,
            )
            for candidate in feasible
        }
        ranked = sorted(scores, key=lambda item: (-scores[item], item))
        selected = next(item for item in feasible if item.alternative_id == ranked[0])
        rejected = {
            candidate.alternative_id: candidate.issue_codes
            for candidate in candidates
            if not candidate.feasible
        }
        return RouteAlternativeDecision(
            selected_alternative_id=selected.alternative_id,
            ranked_alternative_ids=ranked,
            normalized_scores=scores,
            selection_reasons=[
                "所有硬约束均已通过",
                (
                    "按距离、连续净空、能耗代理与转向/航段稳定性进行归一化加权，"
                    f"综合得分 {scores[selected.alternative_id]:.4f}"
                ),
                f"选中策略 {selected.strategy_tool_id}",
            ],
            rejected_alternatives=rejected,
        )

    return [
        ToolPlugin(
            tool_id="planning.multi-objective-ranker.rank",
            version="1.0.0",
            authority="plan",
            input_type=RouteAlternativeSet,
            output_type=RouteAlternativeDecision,
            handler=rank,
        )
    ]


def _ranker_definition() -> PluginDefinition:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            name: {"type": "number", "minimum": 0, "maximum": 1}
            for name in (
                "distance_weight",
                "clearance_weight",
                "energy_weight",
                "stability_weight",
                "qualification_weight",
            )
        },
    }
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="planning.multi-objective-ranker",
            name="多目标路线排序",
            version="1.0.0",
            description="在硬约束通过后对距离、净空、能耗与稳定性进行归一化排序。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definitions"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="planning.multi-objective-ranker.rank",
                    kind="plan-optimizer",
                    name="多目标路线排序",
                    description="从结构化候选路线中选择具有证据的可行解。",
                    authority="plan",
                    input_schema=RouteAlternativeSet.model_json_schema(),
                    output_schema=RouteAlternativeDecision.model_json_schema(),
                    metadata={"deterministic": True, "normalization": "min-max"},
                )
            ],
            permissions=["mission.read"],
            default_enabled=True,
            removable=False,
            disable_allowed=False,
            placement=PluginPlacement(
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.alternative-ranker",
                slot_label="候选路线排序器",
                activation_mode="single",
                scope="mission",
                failure_mode="fail-closed",
                category_order=40,
                slot_order=16,
                plugin_order=10,
            ),
            configuration_schema=schema,
        ),
        tool_factory=_ranker_tools,
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [
        _candidate_definition(
            plugin_id="planning.candidate-clearance",
            name="净空候选路线",
            description="生成偏好宽裕净空与飞行验证边的候选路线。",
            order=10,
            planner=clearance_first_route,
        ),
        _candidate_definition(
            plugin_id="planning.candidate-energy",
            name="能耗候选路线",
            description="生成降低距离、爬升与加速度代理的候选路线。",
            order=20,
            planner=energy_efficient_route,
        ),
        _candidate_definition(
            plugin_id="planning.candidate-stability",
            name="稳定候选路线",
            description="生成偏好验证边、较少过渡与温和速度的候选路线。",
            order=30,
            planner=stability_first_route,
        ),
        _ranker_definition(),
    ]
