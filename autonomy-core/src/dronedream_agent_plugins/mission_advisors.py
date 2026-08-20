from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.tools import ToolPlugin


class AdvisoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_id: str
    goal: str = Field(min_length=1, max_length=500)
    constraints: list[str] = Field(default_factory=list, max_length=64)
    payload_action: str = Field(default="none", max_length=32)


class AdvisoryReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domain: str
    risk_flags: list[str] = Field(default_factory=list, max_length=32)
    required_checks: list[str] = Field(default_factory=list, max_length=32)
    acceptance_evidence: list[str] = Field(default_factory=list, max_length=32)


def _report(
    domain: str,
    *,
    checks: list[str],
    evidence: list[str],
    risk: Callable[[AdvisoryRequest], list[str]],
):
    def advise(request: AdvisoryRequest) -> AdvisoryReport:
        return AdvisoryReport(
            domain=domain,
            risk_flags=risk(request),
            required_checks=checks,
            acceptance_evidence=evidence,
        )

    return advise


def _definition(
    *,
    plugin_id: str,
    name: str,
    description: str,
    domain: str,
    checks: list[str],
    evidence: list[str],
    risk: Callable[[AdvisoryRequest], list[str]],
    recommended_when: dict[str, object],
    order: int,
) -> PluginDefinition:
    handler = _report(domain, checks=checks, evidence=evidence, risk=risk)

    def tools(_environment: ToolEnvironment) -> list[ToolPlugin]:
        return [
            ToolPlugin(
                tool_id=plugin_id,
                version="1.0.0",
                authority="plan",
                input_type=AdvisoryRequest,
                output_type=AdvisoryReport,
                handler=handler,
                routing_metadata={
                    "recommended_when": recommended_when,
                    "domains": [domain],
                },
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
                    capability_id=plugin_id,
                    kind="tool",
                    name=name,
                    description=description,
                    authority="plan",
                    input_schema=AdvisoryRequest.model_json_schema(),
                    output_schema=AdvisoryReport.model_json_schema(),
                    metadata={
                        "recommended_when": recommended_when,
                        "domains": [domain],
                    },
                )
            ],
            permissions=["mission.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="tools",
                category_label="工具与集成",
                slot_id="tools.mission-advisors",
                slot_label="任务专业顾问",
                activation_mode="multiple",
                scope="mission",
                failure_mode="advisory",
                category_order=50,
                slot_order=20,
                plugin_order=order,
            ),
        ),
        tool_factory=tools,
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [
        _definition(
            plugin_id="advisor.energy-reserve",
            name="能源余量顾问",
            description="为长距离、返程和载荷任务提出航程、余量与备降检查。",
            domain="energy",
            checks=["qualified-range", "return-reserve", "payload-energy-impact"],
            evidence=["predicted-energy", "remaining-battery", "reachable-landing-site"],
            risk=lambda request: [
                flag
                for flag, active in {
                    "payload-increases-energy": request.payload_action == "pickup",
                    "return-leg-required": "return" in request.goal.casefold(),
                }.items()
                if active
            ],
            recommended_when={"payload_action_in": ["pickup"]},
            order=10,
        ),
        _definition(
            plugin_id="advisor.communication-coverage",
            name="通信覆盖顾问",
            description="识别室内外切换、远距离和遮挡环境下的链路检查需求。",
            domain="communications",
            checks=["link-margin", "telemetry-heartbeat", "lost-link-policy"],
            evidence=["link-quality-trace", "heartbeat-continuity", "lost-link-recovery"],
            risk=lambda request: [
                "indoor-outdoor-transition"
                if any(value in request.goal for value in ("出门", "教学楼", "室内"))
                else "link-state-unknown"
            ],
            recommended_when={"constraints_any": ["communications", "室内外切换"]},
            order=20,
        ),
        _definition(
            plugin_id="advisor.emergency-landing",
            name="紧急降落顾问",
            description="要求任务全过程保持可达的安全悬停、返航和降落出口。",
            domain="landing",
            checks=["nearest-safe-hold", "reachable-landing-site", "abort-at-every-phase"],
            evidence=["landing-site-candidates", "reachability", "controlled-landing-proof"],
            risk=lambda _request: ["landing-options-must-remain-available"],
            recommended_when={"constraints_any": ["safety_priority", "安全优先"]},
            order=30,
        ),
        _definition(
            plugin_id="advisor.payload-custody",
            name="载荷交接顾问",
            description="为取件、样品和物品运输建立身份、抓取、质量和交付证据。",
            domain="payload",
            checks=["pickup-identity", "attachment-state", "mass-inertia-update", "delivery-proof"],
            evidence=["identity-observation", "attachment-confirmation", "payload-state-trace"],
            risk=lambda request: (
                ["payload-identity-and-attachment-required"]
                if request.payload_action == "pickup"
                else []
            ),
            recommended_when={"payload_action_in": ["pickup"]},
            order=40,
        ),
        _definition(
            plugin_id="advisor.privacy-noise",
            name="隐私与噪声顾问",
            description="为校园、办公和人群区域补充最小拍摄、避让与低噪声要求。",
            domain="privacy",
            checks=["minimum-necessary-capture", "people-avoidance", "quiet-zone-speed"],
            evidence=["capture-purpose", "redaction-policy", "quiet-zone-route"],
            risk=lambda request: [
                "people-or-office-context"
                if any(value in request.goal for value in ("办公室", "教学楼", "人"))
                else "privacy-context-unknown"
            ],
            recommended_when={"constraints_any": ["privacy", "noise", "隐私", "低噪声"]},
            order=50,
        ),
        _definition(
            plugin_id="advisor.inspection-coverage",
            name="巡检覆盖顾问",
            description="为设施、道路和区域巡检建立覆盖率、重叠度与异常复查要求。",
            domain="inspection",
            checks=["coverage-plan", "observation-overlap", "anomaly-revisit"],
            evidence=["coverage-map", "observation-index", "anomaly-review"],
            risk=lambda request: (
                ["coverage-must-be-measured"]
                if any(value in request.goal for value in ("巡检", "检查", "测绘"))
                else []
            ),
            recommended_when={"constraints_any": ["inspection", "巡检", "测绘"]},
            order=60,
        ),
        _definition(
            plugin_id="advisor.reproducibility",
            name="可复现实验顾问",
            description="为研发用户补充随机种子、版本、模型、工具和证据快照。",
            domain="reproducibility",
            checks=["seed", "asset-hashes", "plugin-snapshot", "model-receipts"],
            evidence=["run-manifest", "artifact-hashes", "evaluation-report"],
            risk=lambda _request: ["unrecorded-configuration-causes-nonreproducibility"],
            recommended_when={"constraints_any": ["reproducibility", "评测", "实验"]},
            order=70,
        ),
    ]
