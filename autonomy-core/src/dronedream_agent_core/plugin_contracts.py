"""Versioned contracts shared by plugin packages, the app, and mission evidence."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PluginAuthority = Literal["read", "plan", "simulate", "control", "actuate"]
PluginRuntimeKind = Literal[
    "builtin-python",
    "mcp-stdio",
    "ros2-node",
    "model-provider",
    "ui-declarative",
]
PluginCapabilityKind = Literal[
    "tool",
    "model-provider",
    "runtime-adapter",
    "map-importer",
    "vehicle-importer",
    "planner",
    "perception",
    "payload",
    "voice",
    "data-service",
    "evidence",
    "ui-panel",
    "workflow-policy",
    "harness-profile",
    "workflow-topology",
    "harness-node",
    "harness-scheduler",
    "retry-policy",
    "timeout-policy",
    "budget-policy",
    "fallback-policy",
    "circuit-breaker",
    "cache-policy",
    "event-bus",
    "observer",
    "input-channel",
    "attachment-decoder",
    "locale-policy",
    "entity-resolver",
    "domain-pack",
    "action-pack",
    "model-policy",
    "provider-discovery",
    "model-router",
    "consensus-policy",
    "multimodal-preprocessor",
    "token-meter",
    "prompt-pack",
    "context-strategy",
    "context-enricher",
    "context-store",
    "context-retriever",
    "context-summarizer",
    "retention-policy",
    "structured-decoder",
    "task-decomposer",
    "plan-scorer",
    "plan-optimizer",
    "plan-validator",
    "tool-router",
    "tool-middleware",
    "tool-execution-policy",
    "result-fusion",
    "checkpoint-policy",
    "anomaly-detector",
    "runtime-replanner",
    "scenario-generator",
    "fault-injector",
    "evaluator",
    "evidence-exporter",
    "notification",
    "credential-source",
    "qualification-check",
    "simulator-adapter",
    "physics-model",
    "sensor-model",
    "environment-model",
    "clock-policy",
    "monte-carlo-policy",
    "runtime-amendment",
    "telemetry-adapter",
    "state-estimator",
    "localization",
    "controller",
    "payload-driver",
    "transport",
    "trust-provider",
    "runtime-watchdog",
]
PLUGIN_MCP_CAPABILITY_KINDS = frozenset(
    {
        "tool",
        "planner",
        "perception",
        "payload",
        "map-importer",
        "vehicle-importer",
        "data-service",
        "evidence",
        "context-enricher",
        "context-store",
        "context-retriever",
        "context-summarizer",
        "retention-policy",
        "plan-scorer",
        "plan-validator",
        "anomaly-detector",
        "scenario-generator",
        "fault-injector",
        "evaluator",
        "evidence-exporter",
        "notification",
        "workflow-policy",
        "harness-profile",
        "workflow-topology",
        "harness-node",
        "harness-scheduler",
        "retry-policy",
        "timeout-policy",
        "budget-policy",
        "fallback-policy",
        "circuit-breaker",
        "cache-policy",
        "event-bus",
        "observer",
        "input-channel",
        "attachment-decoder",
        "locale-policy",
        "entity-resolver",
        "domain-pack",
        "action-pack",
        "model-policy",
        "provider-discovery",
        "model-router",
        "consensus-policy",
        "multimodal-preprocessor",
        "token-meter",
        "prompt-pack",
        "context-strategy",
        "structured-decoder",
        "task-decomposer",
        "plan-optimizer",
        "tool-router",
        "tool-middleware",
        "tool-execution-policy",
        "result-fusion",
        "checkpoint-policy",
        "runtime-replanner",
        "credential-source",
        "qualification-check",
        "simulator-adapter",
        "physics-model",
        "sensor-model",
        "environment-model",
        "clock-policy",
        "monte-carlo-policy",
        "runtime-amendment",
        "telemetry-adapter",
        "state-estimator",
        "localization",
        "controller",
        "payload-driver",
        "transport",
        "trust-provider",
        "runtime-watchdog",
    }
)
PLUGIN_EXTENSION_HOOKS = frozenset(
    {
        "resolve_profile",
        "resolve_topology",
        "resolve_schedule",
        "resolve_retry",
        "resolve_timeout",
        "resolve_budget",
        "resolve_fallback",
        "resolve_cache",
        "run_harness_node",
        "observe_harness",
        "decode_attachment",
        "ingest_input",
        "resolve_entity",
        "resolve_locale",
        "resolve_domain",
        "declare_actions",
        "enrich_request",
        "normalize_intent",
        "select_port",
        "route_model",
        "discover_models",
        "select_consensus",
        "preprocess_multimodal",
        "measure_tokens",
        "augment_prompt",
        "validate_output",
        "compact_context",
        "enrich_context",
        "resolve_context_store",
        "retrieve_context",
        "summarize_context",
        "resolve_retention",
        "transform_task_graph",
        "optimize_semantic_plan",
        "optimize_track",
        "contribute_planning",
        "validate_planning",
        "score_plan",
        "validate_plan",
        "recommend_tools",
        "before_tool_call",
        "after_tool_call",
        "resolve_tool_execution",
        "fuse_results",
        "build_checkpoints",
        "evaluate_checkpoint",
        "select_anchor",
        "plan_coverage",
        "resolve_target_feed",
        "classify_amendment",
        "apply_amendment",
        "generate_campaign",
        "describe_fault",
        "evaluate_preflight",
        "evaluate_runtime",
        "export_evidence",
        "render_plan_notification",
        "import_asset",
        "qualify_asset",
        "describe_simulator",
        "describe_physics",
        "describe_sensor",
        "describe_environment",
        "resolve_clock",
        "resolve_monte_carlo",
        "normalize_telemetry",
        "estimate_state",
        "localize",
        "control_policy",
        "payload_command",
        "transport_message",
        "verify_trust",
        "resolve_watchdog",
    }
)
PluginPermission = Literal[
    "asset.read",
    "attachment.read",
    "asset.write-staging",
    "mission.read",
    "mission.write-output",
    "network.model-gateway",
    "network.external",
    "network.local-device",
    "process.spawn",
    "ros.read",
    "ros.write",
    "simulator.control",
    "vehicle.actuate",
    "ui.panel",
    "context.read",
    "context.write-summary",
    "telemetry.read",
    "evidence.write",
    "configuration.read",
    "credential.reference",
]
PluginLifecycleState = Literal[
    "discovered",
    "staged",
    "installed",
    "starting",
    "healthy",
    "draining",
    "disabled",
    "failed",
    "quarantined",
    "uninstalled",
]
PluginActivationMode = Literal["single", "multiple", "pipeline"]
PluginFailureMode = Literal["fail-closed", "isolate", "advisory"]
PluginSwapPolicy = Literal[
    "anytime",
    "next-mission",
    "safe-hold",
    "restart",
    "certified-update",
]
PluginScope = Literal["general", "mission", "runtime", "interface"]
PluginGovernanceOperation = Literal[
    "import",
    "enable",
    "promote",
    "trust-local-package",
]

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]{2,119}$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PluginModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PluginDependency(PluginModel):
    plugin_id: str
    version: str = Field(default="*")
    optional: bool = False

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid plugin dependency id")
        return value

    @field_validator("version")
    @classmethod
    def validate_requirement(cls, value: str) -> str:
        candidate = (
            value[2:] if value.startswith(">=") else value[1:] if value.startswith("^") else value
        )
        if value != "*" and _SEMVER.fullmatch(candidate) is None:
            raise ValueError("dependency version must be *, exact semver, >=semver, or ^semver")
        return value


class PluginRuntime(PluginModel):
    kind: PluginRuntimeKind
    entrypoint: str | None = Field(default=None, max_length=300)
    command: list[str] = Field(default_factory=list, max_length=32)
    protocol_version: str = Field(default="dronedream.plugin.v1", max_length=80)
    startup_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    call_timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)

    @model_validator(mode="after")
    def validate_runtime(self) -> PluginRuntime:
        if self.kind == "builtin-python" and not self.entrypoint:
            raise ValueError("builtin-python runtime requires entrypoint")
        if self.kind in {"mcp-stdio", "ros2-node"} and not self.command:
            raise ValueError(f"{self.kind} runtime requires command")
        if self.kind in {"model-provider", "ui-declarative"} and (self.entrypoint or self.command):
            raise ValueError(f"{self.kind} runtime may not execute code")
        for item in self.command:
            if not item or len(item) > 300 or "\x00" in item:
                raise ValueError("invalid runtime command")
        return self


class PluginResourcePolicy(PluginModel):
    """Fail-closed resource envelope applied to executable plugin runtimes."""

    memory_limit_mb: int = Field(default=256, ge=32, le=4_096)
    cpu_time_limit_seconds: int = Field(default=120, ge=1, le=3_600)
    process_limit: int = Field(default=4, ge=1, le=64)
    maximum_message_bytes: int = Field(default=2 * 1024 * 1024, ge=4_096, le=16 * 1024 * 1024)
    allowed_network_hosts: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("allowed_network_hosts")
    @classmethod
    def validate_hosts(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate network host")
        for value in values:
            if (
                not value
                or len(value) > 253
                or "://" in value
                or "/" in value
                or "\\" in value
                or "\x00" in value
            ):
                raise ValueError("invalid network host")
        return values


class PluginSignature(PluginModel):
    algorithm: Literal["ed25519"] = "ed25519"
    publisher_key_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    signed_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_base64: str = Field(min_length=80, max_length=128)
    signed_at: datetime


class PluginProvenance(PluginModel):
    source_uri: str | None = Field(default=None, max_length=1_024)
    source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,64}$")
    build_system: str | None = Field(default=None, max_length=120)
    build_timestamp: datetime | None = None
    sbom_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    update_ring: Literal["stable", "preview", "canary", "pinned"] = "stable"


class PluginCapability(PluginModel):
    capability_id: str
    kind: PluginCapabilityKind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    authority: PluginAuthority = "read"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[PluginPermission] | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid capability id")
        return value

    @model_validator(mode="after")
    def validate_schemas(self) -> PluginCapability:
        if self.required_permissions is not None and len(self.required_permissions) != len(
            set(self.required_permissions)
        ):
            raise ValueError("duplicate capability permission")
        tool_kinds = {
            "tool",
            "planner",
            "perception",
            "payload",
            "data-service",
            "evidence",
            "context-enricher",
            "plan-scorer",
            "plan-validator",
            "anomaly-detector",
            "scenario-generator",
            "fault-injector",
            "evaluator",
            "evidence-exporter",
            "notification",
        }
        if self.kind in tool_kinds and (not self.input_schema or not self.output_schema):
            raise ValueError(f"{self.kind} capability requires input and output schemas")
        for schema in (self.input_schema, self.output_schema):
            if not schema:
                continue
            try:
                jsonschema.validators.validator_for(schema).check_schema(schema)
            except jsonschema.SchemaError as error:
                raise ValueError("capability contains an invalid JSON schema") from error
        return self


class PluginPlacement(PluginModel):
    """Stable UI and activation slot occupied by a plugin implementation."""

    category_id: str = "general"
    category_label: str = "通用"
    slot_id: str = "general.extensions"
    slot_label: str = "通用能力"
    activation_mode: PluginActivationMode = "multiple"
    scope: PluginScope = "general"
    failure_mode: PluginFailureMode = "isolate"
    swap_policy: PluginSwapPolicy = "next-mission"
    category_order: int = Field(default=900, ge=0, le=10_000)
    slot_order: int = Field(default=900, ge=0, le=10_000)
    plugin_order: int = Field(default=900, ge=0, le=10_000)
    pipeline_order: int = Field(default=500, ge=0, le=10_000)
    runs_after: list[str] = Field(default_factory=list, max_length=32)
    runs_before: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("category_id", "slot_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid plugin placement identifier")
        return value

    @field_validator("runs_after", "runs_before")
    @classmethod
    def validate_ordering_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate plugin ordering reference")
        if any(_IDENTIFIER.fullmatch(value) is None for value in values):
            raise ValueError("invalid plugin ordering reference")
        return values

    @model_validator(mode="after")
    def validate_pipeline_options(self) -> PluginPlacement:
        if self.activation_mode != "pipeline" and (self.runs_after or self.runs_before):
            raise ValueError("ordering references require pipeline activation mode")
        if self.activation_mode == "single" and self.failure_mode == "advisory":
            raise ValueError("single implementation cannot use advisory failure mode")
        return self


class PluginManifest(PluginModel):
    schema_version: Literal["dronedream.plugin-manifest.v1"] = "dronedream.plugin-manifest.v1"
    plugin_id: str
    name: str = Field(min_length=1, max_length=120)
    version: str
    description: str = Field(min_length=1, max_length=1_000)
    publisher: str = Field(min_length=1, max_length=120)
    api_version: Literal["1.0"] = "1.0"
    minimum_app_version: str = "0.1.0"
    runtime: PluginRuntime
    resource_policy: PluginResourcePolicy = Field(default_factory=PluginResourcePolicy)
    capabilities: list[PluginCapability] = Field(min_length=1, max_length=64)
    permissions: list[PluginPermission] = Field(default_factory=list, max_length=32)
    dependencies: list[PluginDependency] = Field(default_factory=list, max_length=32)
    conflicts: list[str] = Field(default_factory=list, max_length=32)
    file_sha256: dict[str, str] = Field(default_factory=dict, max_length=2_000)
    default_enabled: bool = False
    removable: bool = True
    disable_allowed: bool = True
    placement: PluginPlacement = Field(default_factory=PluginPlacement)
    configuration_schema: dict[str, Any] = Field(default_factory=dict)
    provenance: PluginProvenance = Field(default_factory=PluginProvenance)
    signature: PluginSignature | None = None

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid plugin id")
        return value

    @field_validator("version", "minimum_app_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("version must be semantic versioning")
        return value

    @field_validator("file_sha256")
    @classmethod
    def validate_files(cls, value: dict[str, str]) -> dict[str, str]:
        for path, digest in value.items():
            candidate = path.replace("\\", "/")
            if (
                not candidate
                or candidate.startswith("/")
                or candidate.startswith("../")
                or "/../" in candidate
                or candidate.endswith("/..")
                or _SHA256.fullmatch(digest) is None
            ):
                raise ValueError("invalid plugin file integrity entry")
        return value

    @model_validator(mode="after")
    def validate_unique_members(self) -> PluginManifest:
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("duplicate capability id")
        dependency_ids = [item.plugin_id for item in self.dependencies]
        if self.plugin_id in dependency_ids:
            raise ValueError("plugin cannot depend on itself")
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("duplicate dependency id")
        if self.plugin_id in self.conflicts:
            raise ValueError("plugin cannot conflict with itself")
        if len(self.conflicts) != len(set(self.conflicts)):
            raise ValueError("duplicate conflict id")
        if any(_IDENTIFIER.fullmatch(value) is None for value in self.conflicts):
            raise ValueError("invalid conflict id")
        if set(dependency_ids).intersection(self.conflicts):
            raise ValueError("plugin cannot both depend on and conflict with another plugin")
        if self.plugin_id in self.placement.runs_after + self.placement.runs_before:
            raise ValueError("plugin cannot order itself")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("duplicate permission")
        authorities = {item.authority for item in self.capabilities}
        if "actuate" in authorities and "vehicle.actuate" not in self.permissions:
            raise ValueError("actuate capability requires vehicle.actuate permission")
        for capability in self.capabilities:
            undeclared = set(capability.required_permissions or []) - set(self.permissions)
            if undeclared:
                raise ValueError("capability permission must be declared by its plugin")
        if self.runtime.kind in {"mcp-stdio", "ros2-node"} and "process.spawn" not in (
            self.permissions
        ):
            raise ValueError("executable plugin requires process.spawn permission")
        kinds = {item.kind for item in self.capabilities}
        if "ui-panel" in kinds and "ui.panel" not in self.permissions:
            raise ValueError("ui-panel capability requires ui.panel permission")
        if "model-provider" in kinds and "network.model-gateway" not in self.permissions:
            raise ValueError("model-provider capability requires network.model-gateway permission")
        if self.resource_policy.allowed_network_hosts and not {
            "network.external",
            "network.local-device",
        }.intersection(self.permissions):
            raise ValueError("network host allowlist requires a network permission")
        if {"network.external", "network.local-device"}.intersection(
            self.permissions
        ) and not self.resource_policy.allowed_network_hosts:
            raise ValueError("network permission requires an explicit host allowlist")
        if self.configuration_schema:
            try:
                jsonschema.validators.validator_for(self.configuration_schema).check_schema(
                    self.configuration_schema
                )
            except jsonschema.SchemaError as error:
                raise ValueError("invalid plugin configuration schema") from error
        return self


class PluginGovernancePolicy(PluginModel):
    """Organization-controlled ceiling applied above every plugin lifecycle action."""

    schema_version: Literal["dronedream.plugin-governance-policy.v1"] = (
        "dronedream.plugin-governance-policy.v1"
    )
    policy_id: str = Field(default="personal-default", pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    mode: Literal["personal", "managed"] = "personal"
    allowed_plugin_ids: list[str] = Field(default_factory=list, max_length=512)
    allowed_publishers: list[str] = Field(default_factory=list, max_length=256)
    denied_permissions: list[PluginPermission] = Field(default_factory=list, max_length=32)
    allowed_update_rings: list[Literal["stable", "preview", "canary", "pinned"]] = Field(
        default_factory=lambda: ["stable", "preview", "canary", "pinned"], max_length=4
    )
    require_verified_signatures: bool = False
    allow_local_approval: bool = True
    maximum_external_plugins: int = Field(default=128, ge=0, le=2_000)

    @field_validator(
        "allowed_plugin_ids",
        "allowed_publishers",
        "denied_permissions",
        "allowed_update_rings",
    )
    @classmethod
    def validate_unique_governance_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate governance policy value")
        return values

    @field_validator("allowed_plugin_ids")
    @classmethod
    def validate_allowed_plugin_ids(cls, values: list[str]) -> list[str]:
        if any(_IDENTIFIER.fullmatch(value) is None for value in values):
            raise ValueError("invalid governance plugin id")
        return values


class PluginGovernanceDecision(PluginModel):
    schema_version: Literal["dronedream.plugin-governance-decision.v1"] = (
        "dronedream.plugin-governance-decision.v1"
    )
    decision_id: str = Field(pattern=r"^plugin-policy-[0-9a-f]{24}$")
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    operation: PluginGovernanceOperation
    plugin_id: str
    version: str
    accepted: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_status: Literal["verified", "local-approved", "unverified", "revoked"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("plugin_id")
    @classmethod
    def validate_governed_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid governed plugin id")
        return value


class PluginUsageEvent(PluginModel):
    schema_version: Literal["dronedream.plugin-usage-event.v1"] = "dronedream.plugin-usage-event.v1"
    invocation_id: str = Field(pattern=r"^plugin-call-[0-9a-f]{24}$")
    plugin_id: str
    plugin_version: str
    capability_id: str
    slot_id: str
    invocation_kind: Literal["tool", "hook"]
    outcome: Literal["success", "error"]
    duration_ms: float = Field(ge=0.0)
    input_bytes: int = Field(default=0, ge=0)
    output_bytes: int = Field(default=0, ge=0)
    issue_code: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("plugin_id", "capability_id", "slot_id")
    @classmethod
    def validate_usage_identifiers(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid plugin usage identifier")
        return value


class PluginMarketplaceSource(PluginModel):
    schema_version: Literal["dronedream.plugin-marketplace-source.v1"] = (
        "dronedream.plugin-marketplace-source.v1"
    )
    source_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    name: str = Field(min_length=1, max_length=120)
    index_url: str = Field(min_length=9, max_length=1_024)
    enabled: bool = True

    @field_validator("index_url")
    @classmethod
    def validate_marketplace_url(cls, value: str) -> str:
        if not value.startswith("https://") or "\x00" in value:
            raise ValueError("marketplace source must use HTTPS")
        return value


class PluginMarketplaceEntry(PluginModel):
    plugin_id: str
    version: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1_000)
    publisher: str = Field(min_length=1, max_length=120)
    archive_url: str = Field(min_length=9, max_length=1_024)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    category_id: str = Field(default="general", pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    update_ring: Literal["stable", "preview", "canary", "pinned"] = "stable"

    @field_validator("plugin_id")
    @classmethod
    def validate_marketplace_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid marketplace plugin id")
        return value

    @field_validator("version")
    @classmethod
    def validate_marketplace_version(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("invalid marketplace plugin version")
        return value

    @field_validator("archive_url")
    @classmethod
    def validate_marketplace_archive_url(cls, value: str) -> str:
        if not value.startswith("https://") or "\x00" in value:
            raise ValueError("marketplace archive must use HTTPS")
        return value


class PluginMarketplaceIndex(PluginModel):
    schema_version: Literal["dronedream.plugin-marketplace-index.v1"] = (
        "dronedream.plugin-marketplace-index.v1"
    )
    generated_at: datetime
    entries: list[PluginMarketplaceEntry] = Field(default_factory=list, max_length=5_000)

    @model_validator(mode="after")
    def validate_unique_marketplace_coordinates(self) -> PluginMarketplaceIndex:
        coordinates = [(item.plugin_id, item.version) for item in self.entries]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("duplicate marketplace plugin coordinate")
        return self


class PluginHookReceipt(PluginModel):
    """Hash-bound evidence for a non-tool Harness extension invocation."""

    schema_version: Literal["dronedream.plugin-hook-receipt.v1"] = (
        "dronedream.plugin-hook-receipt.v1"
    )
    invocation_id: str = Field(pattern=r"^hook-[0-9a-f]{24}$")
    plugin_id: str
    plugin_version: str
    plugin_package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_id: str
    slot_id: str
    hook: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,95}$")
    outcome: Literal["accepted", "skipped", "failed"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    created_at: datetime

    @field_validator("plugin_id", "capability_id", "slot_id")
    @classmethod
    def validate_hook_identifier(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid plugin hook identifier")
        return value


class CapabilityBrokerReceipt(PluginModel):
    """Sanitized evidence for a core-mediated plugin I/O operation."""

    schema_version: Literal["dronedream.capability-broker-receipt.v1"] = (
        "dronedream.capability-broker-receipt.v1"
    )
    plugin_id: str
    operation: Literal[
        "filesystem.read",
        "filesystem.write",
        "network.request",
        "credential.inject",
        "process.spawn",
    ]
    outcome: Literal["accepted", "denied", "failed"]
    resource_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(default=0, ge=0)
    issue_codes: list[str] = Field(default_factory=list, max_length=16)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("plugin_id")
    @classmethod
    def validate_broker_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid broker plugin id")
        return value


class PluginSnapshotEntry(PluginModel):
    plugin_id: str
    version: str
    package_sha256: str
    manifest_sha256: str
    configuration_sha256: str = Field(default="0" * 64)
    configuration: dict[str, Any] = Field(default_factory=dict)
    capability_ids: list[str] = Field(min_length=1, max_length=64)
    manifest: PluginManifest | None = None
    bundle_root: str | None = Field(default=None, max_length=1_024)

    @field_validator("bundle_root")
    @classmethod
    def validate_bundle_root(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("invalid snapshot bundle root")
        return value

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid snapshot plugin id")
        return value

    @field_validator("package_sha256", "manifest_sha256", "configuration_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("invalid snapshot hash")
        return value


class PluginSnapshot(PluginModel):
    schema_version: Literal["dronedream.plugin-snapshot.v1"] = "dronedream.plugin-snapshot.v1"
    snapshot_id: str = Field(pattern=r"^plugin-snapshot-[0-9a-f]{24}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plugins: list[PluginSnapshotEntry]
    created_at: datetime


class PluginLifecycleReceipt(PluginModel):
    schema_version: Literal["dronedream.plugin-lifecycle-receipt.v1"] = (
        "dronedream.plugin-lifecycle-receipt.v1"
    )
    receipt_id: str = Field(pattern=r"^plugin-event-[0-9a-f]{24}$")
    plugin_id: str
    version: str
    operation: Literal[
        "install",
        "enable",
        "disable",
        "healthcheck",
        "update",
        "activate",
        "rollback",
        "uninstall",
        "quarantine",
        "trust-local-package",
        "revoke-package",
    ]
    previous_state: PluginLifecycleState | None = None
    current_state: PluginLifecycleState
    accepted: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
