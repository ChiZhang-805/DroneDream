from __future__ import annotations

from typing import Any

from dronedream_agent_core.harness_graph import HarnessNodeSpec, HarnessTopology
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _core_nodes(*, review_count: int, optional_advisors: bool) -> list[HarnessNodeSpec]:
    nodes = [
        HarnessNodeSpec(
            node_id="mission.request-ingest",
            node_kind="core",
            handler_id="core.request-ingest",
            required_inputs=["request"],
            output_key="request_context",
        ),
        HarnessNodeSpec(
            node_id="mission.context-prepare",
            node_kind="plugin",
            handler_id="core.context-prepare",
            depends_on=["mission.request-ingest"],
            required_inputs=["request_context"],
            output_key="context",
            cacheable=True,
        ),
        HarnessNodeSpec(
            node_id="mission.intent-parse",
            node_kind="core",
            handler_id="core.intent-parse",
            depends_on=["mission.context-prepare"],
            required_inputs=["context"],
            output_key="intent",
            retry_limit=2,
        ),
    ]
    reviews: list[str] = []
    for index in range(1, review_count + 1):
        node_id = f"mission.intent-review-{index}"
        reviews.append(node_id)
        nodes.append(
            HarnessNodeSpec(
                node_id=node_id,
                node_kind="core",
                handler_id="core.intent-review",
                depends_on=["mission.intent-parse"],
                required_inputs=["intent"],
                output_key=f"intent_review_{index}",
                retry_limit=1,
            )
        )
    nodes.extend(
        [
            HarnessNodeSpec(
                node_id="mission.intent-consensus",
                node_kind="barrier",
                handler_id="core.intent-consensus",
                depends_on=reviews,
                output_key="accepted_intent",
            ),
            HarnessNodeSpec(
                node_id="mission.contract-freeze",
                node_kind="barrier",
                handler_id="core.contract-freeze",
                depends_on=["mission.intent-consensus"],
                required_inputs=["accepted_intent"],
                output_key="contract",
            ),
        ]
    )
    task_dependencies = ["mission.contract-freeze"]
    if optional_advisors:
        nodes.append(
            HarnessNodeSpec(
                node_id="mission.tool-advice",
                node_kind="plugin",
                handler_id="core.tool-advice",
                depends_on=["mission.contract-freeze"],
                required_inputs=["contract"],
                output_key="tool_advice",
                failure_mode="isolate",
                retry_limit=1,
            )
        )
        task_dependencies.append("mission.tool-advice")
    nodes.extend(
        [
            HarnessNodeSpec(
                node_id="mission.task-decompose",
                node_kind="core",
                handler_id="core.task-decompose",
                depends_on=task_dependencies,
                required_inputs=["contract"],
                output_key="task_graph",
                retry_limit=2,
            ),
            HarnessNodeSpec(
                node_id="mission.semantic-plan",
                node_kind="core",
                handler_id="core.semantic-plan",
                depends_on=["mission.task-decompose"],
                required_inputs=["task_graph"],
                output_key="semantic_plan",
                retry_limit=3,
            ),
            HarnessNodeSpec(
                node_id="mission.route-resolve",
                node_kind="core",
                handler_id="core.route-resolve",
                depends_on=["mission.semantic-plan"],
                required_inputs=["semantic_plan"],
                output_key="route",
            ),
            HarnessNodeSpec(
                node_id="mission.clearance-gate",
                node_kind="barrier",
                handler_id="core.clearance-gate",
                depends_on=["mission.route-resolve"],
                required_inputs=["route"],
                output_key="clearance",
            ),
            HarnessNodeSpec(
                node_id="mission.track-export",
                node_kind="core",
                handler_id="core.track-export",
                depends_on=["mission.clearance-gate"],
                required_inputs=["clearance"],
                output_key="track",
            ),
            HarnessNodeSpec(
                node_id="mission.plan-evaluation",
                node_kind="plugin",
                handler_id="core.plan-evaluation",
                depends_on=["mission.track-export"],
                required_inputs=["track"],
                output_key="evaluation",
                failure_mode="isolate",
            ),
            HarnessNodeSpec(
                node_id="mission.plan-review",
                node_kind="core",
                handler_id="core.plan-review",
                depends_on=["mission.plan-evaluation"],
                required_inputs=["track"],
                output_key="plan_review",
                retry_limit=2,
            ),
            HarnessNodeSpec(
                node_id="mission.runtime-checkpoints",
                node_kind="core",
                handler_id="core.runtime-checkpoints",
                depends_on=["mission.plan-review"],
                required_inputs=["plan_review"],
                output_key="checkpoints",
            ),
            HarnessNodeSpec(
                node_id="mission.evidence-finalize",
                node_kind="barrier",
                handler_id="core.evidence-finalize",
                depends_on=["mission.runtime-checkpoints"],
                required_inputs=["checkpoints"],
                output_key="prepared_mission",
            ),
        ]
    )
    return nodes


def _resolve(topology: HarnessTopology):
    def resolve(**_: Any) -> dict[str, object]:
        return topology.model_dump(mode="json")

    return resolve


def _definition(
    *,
    plugin_id: str,
    name: str,
    description: str,
    topology: HarnessTopology,
    order: int,
    enabled: bool,
) -> PluginDefinition:
    return hook_plugin(
        module_name=__name__,
        plugin_id=plugin_id,
        name=name,
        description=description,
        capability_id=f"{plugin_id}.resolve",
        capability_kind="workflow-topology",
        capability_name=name,
        capability_description=description,
        category_id="harness",
        category_label="Harness 与智能体",
        slot_id="harness.workflow-topology",
        slot_label="工作流拓扑",
        activation_mode="single",
        category_order=10,
        slot_order=20,
        plugin_order=order,
        hooks={"resolve_topology": _resolve(topology)},
        default_enabled=enabled,
        failure_mode="fail-closed",
        swap_policy="next-mission",
        metadata={
            "topology_id": topology.topology_id,
            "node_count": len(topology.nodes),
            "maximum_parallelism": topology.maximum_parallelism,
            "protected_barriers": [
                item.node_id for item in topology.nodes if item.node_kind == "barrier"
            ],
        },
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [
        _definition(
            plugin_id="harness.topology-balanced",
            name="均衡闭环拓扑",
            description="完整执行意图、合同、任务、路线、净空、轨迹、审查和证据门。",
            topology=HarnessTopology(
                topology_id="topology.balanced-closed-loop",
                name="Balanced closed loop",
                nodes=_core_nodes(review_count=1, optional_advisors=True),
                maximum_parallelism=4,
                metadata={"review_strategy": "single-specialist"},
            ),
            order=10,
            enabled=True,
        ),
        _definition(
            plugin_id="harness.topology-committee",
            name="委员会并行审查拓扑",
            description="并行执行三次独立意图审查，并在合同冻结前形成一致结论。",
            topology=HarnessTopology(
                topology_id="topology.committee-closed-loop",
                name="Committee closed loop",
                nodes=_core_nodes(review_count=3, optional_advisors=True),
                maximum_parallelism=6,
                metadata={"review_strategy": "three-way-consensus"},
            ),
            order=20,
            enabled=False,
        ),
        _definition(
            plugin_id="harness.topology-rapid-safe",
            name="快速安全拓扑",
            description="省略非关键顾问阶段，但保留合同、净空、计划审查和证据安全门。",
            topology=HarnessTopology(
                topology_id="topology.rapid-safe",
                name="Rapid safe closed loop",
                nodes=_core_nodes(review_count=1, optional_advisors=False),
                maximum_parallelism=3,
                metadata={"review_strategy": "latency-bounded"},
            ),
            order=30,
            enabled=False,
        ),
    ]
