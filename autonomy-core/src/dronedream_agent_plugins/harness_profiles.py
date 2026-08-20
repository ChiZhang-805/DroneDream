from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _harness_policy_bundle(profile_id: str) -> list[str]:
    topology = "harness.topology-balanced"
    scheduler = "harness.scheduler-parallel-ready"
    retry = "harness.retry-bounded-exponential"
    timeout = "harness.timeout-adaptive"
    budget = "harness.budget-balanced"
    if profile_id in {
        "harness.profile-evaluation-lab",
        "harness.profile-field-readiness",
    }:
        topology = "harness.topology-committee"
    if profile_id == "harness.profile-evaluation-lab":
        scheduler = "harness.scheduler-sequential"
    if profile_id == "harness.profile-emergency-response":
        topology = "harness.topology-rapid-safe"
        timeout = "harness.timeout-low-latency"
        retry = "harness.retry-immediate-once"
    if profile_id == "harness.profile-plugin-developer":
        scheduler = "harness.scheduler-sequential"
    if profile_id == "harness.profile-privacy-sensitive":
        budget = "harness.budget-cost-capped"
    return [
        topology,
        scheduler,
        retry,
        timeout,
        budget,
        "harness.fallback-safe-degrade",
        "harness.cache-mission-hash",
        "harness.event-bus-in-process",
        "harness.observer-execution-ledger",
    ]


def _recommendations(profile_id: str, plugins: list[str]) -> list[str]:
    return list(dict.fromkeys([*plugins, *_harness_policy_bundle(profile_id)]))


def _profile(
    profile_id: str,
    *,
    priorities: list[str],
    required_evidence: list[str],
    operating_style: str,
    recommended_plugins: list[str],
):
    def resolve(**_: Any) -> dict[str, object]:
        return {
            "profile_id": profile_id,
            "priorities": priorities,
            "required_evidence": required_evidence,
            "operating_style": operating_style,
            "recommended_plugins": recommended_plugins,
            "may_relax_core_safety": False,
        }

    return resolve


def plugin_definitions() -> list[PluginDefinition]:
    managed_plugins = [
        "prompt.payload-custody",
        "prompt.operator-concise",
        "validation.energy-reserve",
        "notification.planning-metrics",
        "notification.operator-checklist",
        "planning.corner-speed-envelope",
        "evidence.track-geojson",
        "harness.topology-balanced",
        "harness.topology-committee",
        "harness.topology-rapid-safe",
        "harness.scheduler-parallel-ready",
        "harness.scheduler-sequential",
        "harness.retry-bounded-exponential",
        "harness.retry-immediate-once",
        "harness.timeout-adaptive",
        "harness.timeout-low-latency",
        "harness.budget-balanced",
        "harness.budget-cost-capped",
        "harness.fallback-safe-degrade",
        "harness.cache-mission-hash",
        "harness.event-bus-in-process",
        "harness.observer-execution-ledger",
    ]
    values = [
        (
            "harness.profile-balanced",
            "均衡自主",
            "默认方案，在安全、规划质量、模型成本和响应时间之间保持平衡。",
            ["safety", "reliability", "latency", "cost"],
            ["route-clearance", "runtime-checkpoints", "completion-assessment"],
            "balanced",
            [
                "workflow.balanced",
                "models.role-specialist",
                "context.structured-window",
                "tools.router-hybrid",
                "runtime.checkpoint-every-segment",
                "runtime.replan-nearest-anchor",
                "navigation.shortest-route",
                "safety.route-clearance",
                "px4.export-track",
                "simulation.campaign-acceptance",
            ],
            True,
        ),
        (
            "harness.profile-indoor-guardian",
            "室内守护",
            "面向走廊、楼梯、门洞和狭窄空间，提高净空、稳定性与检查密度。",
            ["clearance", "stability", "localization", "safe-hold"],
            ["continuous-clearance", "segment-checkpoints", "pose-stability"],
            "indoor-conservative",
            [
                "workflow.deliberate",
                "models.role-adversarial",
                "context.event-ledger",
                "tools.router-safety-first",
                "runtime.checkpoint-every-segment",
                "runtime.replan-verified-anchor",
                "navigation.clearance-first-route",
                "safety.conservative-route-clearance",
                "px4.stability-track",
                "simulation.campaign-stress",
                "planning.corner-speed-envelope",
                "prompt.operator-concise",
                "validation.energy-reserve",
                "notification.operator-checklist",
            ],
            False,
        ),
        (
            "harness.profile-payload-delivery",
            "载荷取送",
            "面向外卖、样品和轻型载荷任务，强化身份确认、载荷状态和返程验证。",
            ["payload-integrity", "identity", "stability", "return"],
            ["pickup-identity", "payload-attached", "return-complete"],
            "payload-custody",
            [
                "workflow.deliberate",
                "models.role-adversarial",
                "context.structured-window",
                "tools.router-safety-first",
                "runtime.checkpoint-every-segment",
                "runtime.replan-verified-anchor",
                "navigation.stability-first-route",
                "safety.conservative-route-clearance",
                "px4.stability-track",
                "simulation.campaign-stress",
                "planning.corner-speed-envelope",
                "prompt.payload-custody",
                "validation.energy-reserve",
                "notification.operator-checklist",
            ],
            False,
        ),
        (
            "harness.profile-evaluation-lab",
            "评测实验室",
            "面向研发与回归测试，优先获得可复现的模型、工具、故障和证据记录。",
            ["reproducibility", "coverage", "diagnostics", "evidence"],
            ["seed", "model-receipts", "tool-receipts", "evaluation-report"],
            "evaluation",
            [
                "workflow.committee-review",
                "models.role-adversarial",
                "context.event-ledger",
                "tools.router-hybrid",
                "runtime.checkpoint-every-segment",
                "runtime.replan-nearest-anchor",
                "navigation.shortest-route",
                "safety.route-clearance",
                "px4.export-track",
                "simulation.campaign-stress",
                "validation.energy-reserve",
                "notification.planning-metrics",
                "evidence.track-geojson",
            ],
            False,
        ),
        (
            "harness.profile-field-readiness",
            "真机准备",
            "面向未来真机迁移审查，增加通信、降落点、能源和硬件边界要求，但不授予真机控制权。",
            ["energy", "communications", "landing-options", "hardware-boundaries"],
            ["energy-reserve", "link-margin", "landing-options", "sim-only-proof"],
            "field-readiness-review",
            [
                "workflow.committee-review",
                "models.role-adversarial",
                "context.event-ledger",
                "tools.router-safety-first",
                "runtime.checkpoint-every-segment",
                "runtime.replan-verified-anchor",
                "navigation.energy-efficient-route",
                "safety.conservative-route-clearance",
                "px4.stability-track",
                "simulation.campaign-stress",
                "prompt.operator-concise",
                "validation.energy-reserve",
                "notification.planning-metrics",
                "notification.operator-checklist",
            ],
            False,
        ),
        (
            "harness.profile-infrastructure-inspection",
            "设施巡检",
            "面向桥梁、楼宇、管线和电力设施巡检，强化稳定成像、覆盖率和证据完整性。",
            ["inspection-coverage", "stable-observation", "clearance", "evidence"],
            ["coverage-report", "stable-viewpoints", "route-clearance", "media-binding"],
            "inspection-evidence",
            [
                "workflow.deliberate",
                "models.role-specialist",
                "context.event-ledger",
                "tools.router-safety-first",
                "runtime.checkpoint-every-segment",
                "runtime.replan-verified-anchor",
                "navigation.stability-first-route",
                "safety.conservative-route-clearance",
                "px4.stability-track",
                "simulation.campaign-acceptance",
                "planning.corner-speed-envelope",
                "validation.energy-reserve",
                "notification.planning-metrics",
                "evidence.track-geojson",
            ],
            False,
        ),
        (
            "harness.profile-area-survey",
            "区域测绘",
            "面向农田、园区和大范围测绘，兼顾覆盖率、能源、通信和可复现航线。",
            ["coverage", "energy", "communications", "reproducibility"],
            ["coverage-report", "energy-reserve", "link-margin", "track-receipt"],
            "area-survey",
            [
                "workflow.balanced",
                "models.role-specialist",
                "context.structured-window",
                "tools.router-hybrid",
                "runtime.checkpoint-mission-boundaries",
                "runtime.replan-nearest-anchor",
                "navigation.energy-efficient-route",
                "safety.route-clearance",
                "px4.export-track",
                "simulation.campaign-acceptance",
                "validation.energy-reserve",
                "notification.planning-metrics",
                "evidence.track-geojson",
            ],
            False,
        ),
        (
            "harness.profile-emergency-response",
            "应急响应",
            "面向时间敏感但仍需安全门禁的任务，缩短规划路径并保持高频检查与安全悬停。",
            ["latency", "clearance", "communications", "safe-hold"],
            ["route-clearance", "link-margin", "segment-checkpoints", "abort-options"],
            "rapid-safe-response",
            [
                "workflow.fast-preview",
                "models.role-specialist",
                "context.structured-window",
                "tools.router-safety-first",
                "runtime.checkpoint-every-segment",
                "runtime.replan-verified-anchor",
                "navigation.clearance-first-route",
                "safety.conservative-route-clearance",
                "px4.stability-track",
                "simulation.campaign-stress",
                "planning.corner-speed-envelope",
                "prompt.operator-concise",
                "validation.energy-reserve",
                "notification.operator-checklist",
            ],
            False,
        ),
        (
            "harness.profile-plugin-developer",
            "插件开发",
            "面向插件作者和集成工程师，强化结构契约、调用收据、隔离和可复现验证。",
            ["schema-contracts", "failure-isolation", "receipts", "reproducibility"],
            ["plugin-snapshot", "hook-receipts", "tool-receipts", "quarantine-proof"],
            "plugin-integration",
            [
                "workflow.fast-preview",
                "models.role-adversarial",
                "context.event-ledger",
                "tools.router-hybrid",
                "runtime.checkpoint-every-segment",
                "runtime.replan-nearest-anchor",
                "navigation.shortest-route",
                "safety.route-clearance",
                "px4.export-track",
                "simulation.campaign-stress",
                "notification.planning-metrics",
                "evidence.track-geojson",
            ],
            False,
        ),
        (
            "harness.profile-privacy-sensitive",
            "隐私敏感任务",
            "面向校园、医疗和人员密集区域，强化最小化采集、审计上下文和边界约束。",
            ["privacy", "auditability", "minimum-collection", "safety"],
            ["privacy-boundary", "event-ledger", "route-clearance", "artifact-binding"],
            "privacy-first",
            [
                "workflow.deliberate",
                "models.role-specialist",
                "context.event-ledger",
                "tools.router-hybrid",
                "runtime.checkpoint-every-segment",
                "runtime.replan-nearest-anchor",
                "navigation.shortest-route",
                "safety.route-clearance",
                "px4.export-track",
                "simulation.campaign-acceptance",
                "notification.operator-checklist",
            ],
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.resolve",
            capability_kind="harness-profile",
            capability_name=name,
            capability_description=description,
            category_id="harness",
            category_label="Harness 与智能体",
            slot_id="harness.profile",
            slot_label="任务 Harness 方案",
            activation_mode="single",
            category_order=10,
            slot_order=10,
            plugin_order=index * 10,
            hooks={
                "resolve_profile": _profile(
                    plugin_id,
                    priorities=priorities,
                    required_evidence=evidence,
                    operating_style=style,
                    recommended_plugins=_recommendations(plugin_id, recommended_plugins),
                )
            },
            metadata={
                "recommended_plugins": _recommendations(plugin_id, recommended_plugins),
                "managed_plugins": managed_plugins,
                "atomic_profile": True,
            },
            default_enabled=enabled,
            failure_mode="fail-closed",
            swap_policy="next-mission",
        )
        for index, (
            plugin_id,
            name,
            description,
            priorities,
            evidence,
            style,
            recommended_plugins,
            enabled,
        ) in enumerate(values, start=1)
    ]
