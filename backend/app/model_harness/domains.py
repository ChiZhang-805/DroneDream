"""Canonical responsibility and long-term-memory domains for Model + Harness.

Edition is product-routing metadata, not a durable memory partition.  A single
authenticated account therefore reuses verified structured experience across
editions when, and only when, the underlying Harness responsibility is the
same.  Raw conversations remain task-instance data and are never admitted by
the long-term-memory policy in this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal, NamedTuple, cast

EditionId = Literal["universal", "sim", "lab", "field", "autonomy"]
ModelHarnessDomain = Literal[
    "optimization.control_tuning",
    "autonomy.mission",
    "asset.qualification",
    "experiment.simulation",
    "workflow.cross_edition",
    "validation.hardware",
    "calibration.system",
    "transfer.sim_to_real",
    "transfer.real_to_sim",
    "operations.field",
]
MemoryDomain = Literal[
    "account.shared",
    "optimization.control_tuning",
    "autonomy.mission",
    "asset.qualification",
    "experiment.simulation",
    "workflow.cross_edition",
    "validation.hardware",
    "calibration.system",
    "transfer.sim_to_real",
    "transfer.real_to_sim",
    "operations.field",
]
MemoryPrecedenceLayer = Literal[
    "current_request",
    "session",
    "domain_memory",
    "account_defaults",
]
MemoryLifecycleStatus = Literal["candidate", "consolidated", "revoked", "expired"]
MemorySource = Literal[
    "current_request",
    "session",
    "domain_memory",
    "account_defaults",
    "verified_job_outcome",
]
FixedKernelResponsibility = Literal[
    "identity_and_tenant_boundary",
    "structured_io_validation",
    "safety_policy",
    "budget_enforcement",
    "acceptance_and_evidence",
    "memory_governance",
    "plugin_trust_and_lifecycle",
]
PluginSeam = Literal[
    "model_provider",
    "intent_extractor",
    "context_enricher",
    "prompt_pack",
    "tool_provider",
    "planner",
    "optimizer",
    "critic",
    "validator",
    "memory_extractor",
    "memory_consolidator",
    "memory_retriever",
    "semantic_retriever",
    "simulator_adapter",
    "asset_adapter",
    "telemetry_adapter",
    "recovery_strategy",
    "evidence_exporter",
    "notification_adapter",
]

DOMAIN_SCHEMA_VERSION: Final = "dronedream.model-harness-domains.v1"
ACCOUNT_SHARED_MEMORY_DOMAIN: Final[MemoryDomain] = "account.shared"
OPTIMIZATION_CONTROL_TUNING_DOMAIN: Final[ModelHarnessDomain] = "optimization.control_tuning"
EXPERIMENT_SIMULATION_DOMAIN: Final[ModelHarnessDomain] = "experiment.simulation"
LONG_TERM_MEMORY_AUTHORITY: Final = "advisory_only"
RAW_CONVERSATION_RETENTION: Final = "task_instance_only"
MAX_LONG_TERM_MEMORY_BYTES: Final = 32_768
MAX_LONG_TERM_MEMORY_STRING_BYTES: Final = 4_000
MAX_LONG_TERM_MEMORY_ITEMS: Final = 512
MEMORY_PRECEDENCE: Final[tuple[MemoryPrecedenceLayer, ...]] = (
    "current_request",
    "session",
    "domain_memory",
    "account_defaults",
)
FIXED_KERNEL_RESPONSIBILITIES: Final[tuple[FixedKernelResponsibility, ...]] = (
    "identity_and_tenant_boundary",
    "structured_io_validation",
    "safety_policy",
    "budget_enforcement",
    "acceptance_and_evidence",
    "memory_governance",
    "plugin_trust_and_lifecycle",
)
PLUGIN_SEAMS: Final[tuple[PluginSeam, ...]] = (
    "model_provider",
    "intent_extractor",
    "context_enricher",
    "prompt_pack",
    "tool_provider",
    "planner",
    "optimizer",
    "critic",
    "validator",
    "memory_extractor",
    "memory_consolidator",
    "memory_retriever",
    "semantic_retriever",
    "simulator_adapter",
    "asset_adapter",
    "telemetry_adapter",
    "recovery_strategy",
    "evidence_exporter",
    "notification_adapter",
)

MODEL_HARNESS_DOMAIN_VALUES: Final[tuple[ModelHarnessDomain, ...]] = (
    "optimization.control_tuning",
    "autonomy.mission",
    "asset.qualification",
    "experiment.simulation",
    "workflow.cross_edition",
    "validation.hardware",
    "calibration.system",
    "transfer.sim_to_real",
    "transfer.real_to_sim",
    "operations.field",
)
MEMORY_DOMAIN_VALUES: Final[tuple[MemoryDomain, ...]] = (
    ACCOUNT_SHARED_MEMORY_DOMAIN,
    *MODEL_HARNESS_DOMAIN_VALUES,
)

TASK_MODEL_HARNESS_DOMAINS: Final[dict[str, ModelHarnessDomain]] = {
    "control_tuning": "optimization.control_tuning",
    "mission_autonomy": "autonomy.mission",
    "asset_import_qualification": "asset.qualification",
    "simulation_experiment": "experiment.simulation",
    "cross_edition_workflow": "workflow.cross_edition",
    "hardware_validation": "validation.hardware",
    "calibration": "calibration.system",
    "sim_to_real": "transfer.sim_to_real",
    "real_to_sim": "transfer.real_to_sim",
    "field_task": "operations.field",
}

_EDITIONS: Final[frozenset[str]] = frozenset({"universal", "sim", "lab", "field", "autonomy"})
_LEGACY_SAFETY_PREFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"safety_constraints", "abort_preference", "rollback_preference"}
)
_FORBIDDEN_LONG_TERM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "raw_chat_history",
        "raw_conversation_history",
        "conversation",
        "conversation_summary",
        "messages",
        "user_message",
        "assistant_message",
        "tool_output",
    }
)
_AUTHORITY_SUBJECT_PARTS: Final[frozenset[str]] = frozenset(
    {
        "operator",
        "plan",
        "execution",
        "arm",
        "arming",
        "write",
        "flight",
    }
)
_AUTHORITY_MARKER_PARTS: Final[frozenset[str]] = frozenset(
    {
        "approval",
        "authorization",
        "authority",
        "authorized",
        "confirmation",
        "grant",
    }
)
_FORBIDDEN_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "auth_token",
        "authorization_token",
        "credential",
        "credentials",
        "one_time_token",
        "refresh_token",
        "secret",
    }
)
_FORBIDDEN_LONG_TERM_TEXT: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?:^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{4,}", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{10,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"忽略(?:之前|以上|先前|此前)(?:的)?(?:指令|说明|要求)"),
    re.compile(r"系统提示词|开发者消息"),
    re.compile(r"(?:^|\n)\s*(?:system|developer|assistant|tool|user)\s*:", re.IGNORECASE),
    re.compile(r"<\|(?:system|developer|assistant|tool|user)\|>", re.IGNORECASE),
    re.compile(r"\[(?:system|developer|assistant|tool)\]", re.IGNORECASE),
)


class DomainBinding(NamedTuple):
    """One task's canonical Harness and structured-memory partition."""

    model_harness_domain: ModelHarnessDomain
    memory_domain: MemoryDomain


@dataclass(frozen=True)
class MemoryLifecycle:
    """Auditable candidate-to-consolidated metadata for durable memory."""

    source: MemorySource
    evidence_count: int
    confidence: float
    recency_at: datetime
    ttl_days: int
    status: MemoryLifecycleStatus

    def __post_init__(self) -> None:
        if self.evidence_count < 1:
            raise ValueError("memory lifecycle requires at least one evidence item")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("memory lifecycle confidence must be between zero and one")
        if self.ttl_days < 1:
            raise ValueError("memory lifecycle TTL must be positive")


def consolidated_verified_outcome_lifecycle(
    *,
    evidence_count: int,
    recency_at: datetime,
    ttl_days: int,
) -> MemoryLifecycle:
    """Build the only lifecycle admitted by optimization experience memory."""

    return MemoryLifecycle(
        source="verified_job_outcome",
        evidence_count=evidence_count,
        # Confidence describes receipt verification, not causal effectiveness.
        confidence=1.0,
        recency_at=recency_at,
        ttl_days=ttl_days,
        status="consolidated",
    )


def resolve_task_domains(
    task_type: str,
    *,
    source_edition: str | None = None,
) -> DomainBinding:
    """Resolve domains from responsibility, never from edition.

    ``source_edition`` remains accepted so edition-scoped legacy callers do not
    need a flag day.  It is validated as provenance metadata and deliberately
    does not participate in the returned durable partition.
    """

    if source_edition is not None and source_edition not in _EDITIONS:
        raise ValueError("unsupported source edition")
    try:
        model_domain = TASK_MODEL_HARNESS_DOMAINS[task_type]
    except KeyError as exc:
        raise ValueError("unsupported Model + Harness task type") from exc
    return DomainBinding(
        model_harness_domain=model_domain,
        memory_domain=cast(MemoryDomain, model_domain),
    )


def model_harness_memory_domain(domain: ModelHarnessDomain) -> MemoryDomain:
    """Return the durable memory partition for one Harness responsibility."""

    if domain not in MODEL_HARNESS_DOMAIN_VALUES:
        raise ValueError("unsupported Model + Harness domain")
    return cast(MemoryDomain, domain)


def validate_long_term_memory_payload(
    payload: object,
    *,
    legacy_scope: str | None = None,
) -> None:
    """Reject raw conversation or execution authority in durable memory.

    The historical ``safety_approvals`` scope is interpreted narrowly: it may
    retain only safety constraints and abort/rollback preferences.  Its name
    never turns stored data into an operator approval or execution grant.
    """

    if legacy_scope == "safety_approvals":
        if not isinstance(payload, Mapping):
            raise ValueError("legacy safety preferences must be a structured object")
        unsupported = set(payload) - _LEGACY_SAFETY_PREFERENCE_KEYS
        if unsupported:
            raise ValueError(
                "legacy safety memory permits only constraints and abort/rollback preferences"
            )
    elif legacy_scope is not None:
        raise ValueError("unsupported legacy memory scope")

    total_bytes = 0
    item_count = 0

    def account_bytes(value: str) -> None:
        nonlocal total_bytes
        encoded_size = len(value.encode("utf-8"))
        if encoded_size > MAX_LONG_TERM_MEMORY_STRING_BYTES:
            raise ValueError("long-term memory string exceeds the bounded size")
        total_bytes += encoded_size
        if total_bytes > MAX_LONG_TERM_MEMORY_BYTES:
            raise ValueError("long-term memory payload exceeds the bounded size")

    def visit(value: object, *, depth: int = 0) -> None:
        nonlocal item_count
        if depth > 12:
            raise ValueError("long-term memory nesting exceeds the bounded depth")
        item_count += 1
        if item_count > MAX_LONG_TERM_MEMORY_ITEMS:
            raise ValueError("long-term memory payload exceeds the bounded item count")
        if isinstance(value, Mapping):
            if len(value) > 128:
                raise ValueError("long-term memory object exceeds the bounded item count")
            for raw_key, child in value.items():
                if not isinstance(raw_key, str):
                    raise ValueError("long-term memory keys must be strings")
                account_bytes(raw_key)
                normalized = raw_key.strip().lower().replace("-", "_")
                key_parts = frozenset(part for part in re.split(r"[._]+", normalized) if part)
                # ``parameter_write_authorized`` is covered by write +
                # authorized, while ordinary telemetry such as
                # flight_duration, arm_geometry, token_budget, and write_rate
                # remains valid long-term evidence.
                authority_bearing = bool(
                    key_parts & _AUTHORITY_SUBJECT_PARTS and key_parts & _AUTHORITY_MARKER_PARTS
                )
                if (
                    normalized in _FORBIDDEN_LONG_TERM_KEYS
                    or normalized in _FORBIDDEN_SECRET_KEYS
                    or authority_bearing
                ):
                    raise ValueError(
                        "long-term memory cannot contain conversation data or execution authority"
                    )
                visit(child, depth=depth + 1)
            return
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            if len(value) > 256:
                raise ValueError("long-term memory sequence exceeds the bounded item count")
            for child in value:
                visit(child, depth=depth + 1)
            return
        if isinstance(value, str):
            account_bytes(value)
            if any(pattern.search(value) for pattern in _FORBIDDEN_LONG_TERM_TEXT):
                raise ValueError("long-term memory contains secret or prompt-injection text")
            return
        if isinstance(value, bytes | bytearray):
            raise ValueError("long-term memory cannot contain opaque bytes")
        if isinstance(value, datetime | date):
            account_bytes(value.isoformat())
            return
        if value is None or isinstance(value, bool | int | float):
            account_bytes(str(value))
            return
        raise ValueError("long-term memory contains an unsupported value type")

    visit(payload)


__all__ = [
    "ACCOUNT_SHARED_MEMORY_DOMAIN",
    "DOMAIN_SCHEMA_VERSION",
    "DomainBinding",
    "EditionId",
    "EXPERIMENT_SIMULATION_DOMAIN",
    "FIXED_KERNEL_RESPONSIBILITIES",
    "FixedKernelResponsibility",
    "LONG_TERM_MEMORY_AUTHORITY",
    "MAX_LONG_TERM_MEMORY_BYTES",
    "MAX_LONG_TERM_MEMORY_ITEMS",
    "MAX_LONG_TERM_MEMORY_STRING_BYTES",
    "MEMORY_PRECEDENCE",
    "MEMORY_DOMAIN_VALUES",
    "MemoryLifecycle",
    "MemoryLifecycleStatus",
    "MemoryPrecedenceLayer",
    "MemorySource",
    "MODEL_HARNESS_DOMAIN_VALUES",
    "MemoryDomain",
    "ModelHarnessDomain",
    "OPTIMIZATION_CONTROL_TUNING_DOMAIN",
    "PLUGIN_SEAMS",
    "PluginSeam",
    "RAW_CONVERSATION_RETENTION",
    "TASK_MODEL_HARNESS_DOMAINS",
    "consolidated_verified_outcome_lifecycle",
    "model_harness_memory_domain",
    "resolve_task_domains",
    "validate_long_term_memory_payload",
]
