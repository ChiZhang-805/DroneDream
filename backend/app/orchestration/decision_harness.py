"""Bounded LLM tool selection for iterative DroneDream optimization.

The model receives a compact, read-only evidence packet and may choose exactly
one optimizer from a closed registry. It never receives a callable tool,
database handle, shell, simulator, filesystem, or credential. The selected
tool is validated locally and then executed by the deterministic orchestration
layer in a separate step.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.optimization.experimental_types import ExperimentalOptimizerStrategy
from app.orchestration.cognitive_budget import (
    CognitiveTurnBlocked,
    CognitiveTurnPending,
    begin_cognitive_turn,
    empty_tool_outputs_sha256,
    finish_cognitive_turn,
    recover_existing_cognitive_turn,
    sha256_json,
)
from app.orchestration.events import record_event
from app.orchestration.experience_memory import (
    materialize_verified_terminal_job_experiences,
    retrieve_cross_job_memory,
)
from app.orchestration.harness_budget_planner import (
    HARNESS_BUDGET_POLICY_VERSION,
    HARNESS_BUDGET_PROMPT_VERSION,
    HARNESS_PLAN_REVISION_PROMPT_VERSION,
    HarnessBudgetOpportunity,
    HarnessCompiledGenerationPlan,
    HarnessGenerationPlan,
    HarnessPlanUncertainty,
    HarnessPlanValidation,
    HarnessProposalSummary,
    HarnessRevisionValidation,
    HarnessStopRecommendation,
    HarnessToolAllocation,
    build_budget_plan_messages,
    build_plan_revision_messages,
    compile_generation_plan,
    deterministic_fallback_plan,
    deterministic_revision_fallback,
    generation_plan_schema,
    plan_revision_schema,
    validate_generation_plan,
    validate_plan_revision,
)
from app.orchestration.harness_context import (
    HARNESS_DECISION_TRACE_SCHEMA_VERSION,
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_REGISTRY,
    HARNESS_TOOL_REGISTRY_VERSION,
    HarnessBatchPolicy,
    HarnessEvidenceSnapshot,
    HarnessGenerationPlanMemory,
    HarnessPlanPhase,
    HarnessToolCallExecutionMemory,
    HarnessToolId,
    build_harness_evidence,
    provider_tool_manifest,
    selectable_harness_tools,
)
from app.orchestration.llm_parameter_proposer import (
    OpenAIClientLike,
    OpenAIJsonClient,
    bind_provider_request_accounting,
    load_job_api_key,
)
from app.orchestration.provider_request_accounting import (
    provider_request_outcome_pending,
)

logger = logging.getLogger("drone_dream.orchestration.decision_harness")

HarnessDispatchStrategy: TypeAlias = HarnessToolId
HarnessDecisionSource = Literal["model", "deterministic_fallback"]

_DEFAULT_MODEL = "gpt-4.1"
HARNESS_FALLBACK_TOOL: HarnessToolId = "optimizer_portfolio"
_MAX_RATIONALE_LENGTH = 400
_DECISION_MEMORY_LOOKBACK_GENERATIONS = 32
_DECISION_MEMORY_RESULT_SCAN_LIMIT = 512
_DECISION_MEMORY_COMPANION_SCAN_LIMIT = 4096
_GENERATION_PLAN_RESULT_SCAN_LIMIT = 512
_GENERATION_PLAN_COMPANION_SCAN_LIMIT = 4096
_CROSS_JOB_SOURCE_SCAN_LIMIT = 12


def _decision_schema(
    allowed_tools: tuple[HarnessToolId, ...],
) -> dict[str, Any]:
    if not allowed_tools:
        raise ValueError("Harness decision schema requires an allowed tool")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision"],
        "properties": {
            "decision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tool_id", "rationale"],
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": list(allowed_tools),
                    },
                    "rationale": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _MAX_RATIONALE_LENGTH,
                    },
                },
            }
        },
    }


def decision_schema_for_snapshot(
    snapshot: HarnessEvidenceSnapshot,
) -> dict[str, Any]:
    """Return the exact closed response schema for one evidence snapshot."""

    return _decision_schema(selectable_harness_tools(snapshot))


@dataclass(frozen=True)
class HarnessDecision:
    """One locally validated optimizer-tool decision."""

    decision_id: str
    generation: int
    tool_id: HarnessDispatchStrategy
    rationale: str
    source: HarnessDecisionSource
    model: str | None
    evidence_sha256: str
    prompt_sha256: str | None = None
    fallback_reason: str | None = None
    plan_phase: HarnessPlanPhase = "balanced"
    batch_policy: HarnessBatchPolicy = "balanced"
    evidence_schema_version: str = HARNESS_EVIDENCE_SCHEMA_VERSION
    tool_registry_version: str = HARNESS_TOOL_REGISTRY_VERSION
    prompt_template_version: str = HARNESS_PROMPT_TEMPLATE_VERSION


@dataclass(frozen=True)
class HarnessBudgetPlanDecision:
    """One accepted multi-tool plan or an explicitly attributed fallback."""

    decision_id: str
    generation: int
    compiled_plan: HarnessCompiledGenerationPlan | None
    stop_reason: str | None
    source: HarnessDecisionSource
    model: str | None
    evidence_sha256: str
    prompt_sha256: str | None = None
    fallback_reason: str | None = None
    validation: HarnessPlanValidation | None = None
    budget_policy_version: str = HARNESS_BUDGET_POLICY_VERSION
    plan_prompt_version: str = HARNESS_BUDGET_PROMPT_VERSION
    evidence_schema_version: str = HARNESS_EVIDENCE_SCHEMA_VERSION
    tool_registry_version: str = HARNESS_TOOL_REGISTRY_VERSION


@dataclass(frozen=True)
class HarnessPlanRevisionDecision:
    """The sole bounded post-tool selection turn for one compiled plan."""

    revision_id: str
    decision_id: str
    selected_proposal_refs: tuple[str, ...]
    abandoned: bool
    source: HarnessDecisionSource
    model: str | None
    prompt_sha256: str | None
    fallback_reason: str | None
    validation: HarnessRevisionValidation
    revision_prompt_version: str = HARNESS_PLAN_REVISION_PROMPT_VERSION


@dataclass(frozen=True)
class HarnessDecisionTraceVerification:
    """Self-consistency result for one persisted, provider-safe decision trace."""

    valid: bool
    failures: tuple[str, ...]
    evidence_sha256: str | None = None
    tool_manifest_sha256: str | None = None
    prompt_sha256: str | None = None


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_response(
    raw: object,
    *,
    allowed_tools: tuple[HarnessToolId, ...],
) -> tuple[HarnessToolId, str] | None:
    if not isinstance(raw, dict) or set(raw) != {"decision"}:
        return None
    decision = raw.get("decision")
    if not isinstance(decision, dict) or set(decision) != {"tool_id", "rationale"}:
        return None
    tool_id = decision.get("tool_id")
    rationale = decision.get("rationale")
    if tool_id not in allowed_tools:
        return None
    if not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= _MAX_RATIONALE_LENGTH:
        return None
    return tool_id, rationale.strip()


def validate_harness_decision_response(
    raw: object,
    snapshot: HarnessEvidenceSnapshot,
) -> tuple[HarnessToolId, str] | None:
    """Validate a provider response against the snapshot-specific tool gate."""

    return _validate_response(
        raw,
        allowed_tools=selectable_harness_tools(snapshot),
    )


def build_decision_messages(
    evidence_snapshot: HarnessEvidenceSnapshot,
    *,
    tool_manifest: dict[str, object] | None = None,
) -> tuple[str, str]:
    """Build the exact production model messages from a closed snapshot.

    Keeping this function pure lets the routing evaluation suite exercise the
    same prompt and tool manifest used by live orchestration.
    """

    system = (
        "You are DroneDream's bounded optimization planner. Select exactly one "
        "optimizer tool from the supplied closed, versioned registry for the next "
        "generation. Compare remaining budget, parameter dimension, training-case "
        "heterogeneity, replicate cost, weight concentration, safe perturbation "
        "magnitudes, feasibility, optimizer-learning failure rate, improvement "
        "trend, stagnation, same-Job prior tool outcomes, and compatible cross-Job "
        "structured observations. Validation counts describe "
        "cost only; never infer hidden validation types, conditions, or results. "
        "Treat same-Job and cross-Job observed decision outcomes as bounded "
        "associations, not causal rewards, transfer guarantees, or child-tool "
        "credit. The deterministic receding-horizon plan "
        "sets the current phase and batch policy; select a tool compatible with "
        "that phase because the plan will be recomputed after the cohort result. "
        "Every provider-visible aggregated score uses DroneDream's deterministic "
        "lower-is-better loss convention: smaller finite baseline, best, cohort, "
        "incumbent, Candidate, and tool-history scores are better. Never describe "
        "a smaller aggregate score as worse. Do not compare raw metric values "
        "unless their direction is explicitly supplied. "
        "Use only the supplied evidence. You cannot run tools, change "
        "constraints, modify budgets, access credentials, or invent additional "
        "tool IDs. Return only JSON that conforms to the required schema."
    )
    user_payload = {
        "tool_manifest": (
            provider_tool_manifest(selectable_harness_tools(evidence_snapshot))
            if tool_manifest is None
            else tool_manifest
        ),
        "score_semantics": {
            "name": "dronedream_aggregated_loss",
            "direction": "minimize",
            "lower_is_better": True,
            "applies_to": [
                "search.baseline_score",
                "search.best_score",
                "search.best_score_by_generation[].best_score",
                "tool_history[].best_score",
                "decision_memory[].observed_outcome.incumbent_score_before",
                "decision_memory[].observed_outcome.cohort_best_score",
                "decision_memory[].observed_outcome.incumbent_score_after",
                "cross_job_memory.experiences[].observed_outcome.incumbent_score_before",
                "cross_job_memory.experiences[].observed_outcome.cohort_best_score",
                "cross_job_memory.experiences[].observed_outcome.incumbent_score_after",
                "candidates[].aggregated_score",
            ],
            "raw_metric_policy": "do_not_compare_without_explicit_direction",
        },
        "evidence": evidence_snapshot.model_dump(mode="json", exclude_none=True),
        "instructions": (
            "Choose one tool for the next bounded generation. Prefer measured "
            "progress and budget efficiency. Account for the anonymous training "
            "case profiles and job-wide simulation conditions without guessing "
            "anything about sealed validation cases. Reflect on verified prior "
            "cohort results when present, but do not infer causality from "
            "observational improvement. Cross-Job experience is restricted to "
            "the same authenticated owner and exact structural task family; use "
            "scenario_similarity only as a retrieval rank, never as a physical "
            "fidelity or transfer guarantee. Treat every listed aggregate score as a "
            "minimized loss, so a smaller finite value is better. Respect the "
            "supplied one-generation "
            "planning phase and batch policy; do not invent a later open-loop "
            "schedule. Use the deterministic portfolio when "
            "specialization is not supported by the evidence, and explain the "
            "numeric evidence behind the choice briefly in rationale."
        ),
    }
    return system, _canonical_json(user_payload)


def verify_harness_decision_trace(
    payload: object,
) -> HarnessDecisionTraceVerification:
    """Rebuild and verify a current-version decision-start trace.

    This proves internal reproducibility and detects accidental corruption. It
    is not a signature and does not make the mutable JobEvent table tamper-proof.
    """

    if not isinstance(payload, dict):
        return HarnessDecisionTraceVerification(
            valid=False,
            failures=("invalid_payload",),
        )
    failures: list[str] = []
    if payload.get("trace_schema_version") != HARNESS_DECISION_TRACE_SCHEMA_VERSION:
        failures.append("unsupported_trace_schema_version")
    if payload.get("prompt_template_version") != HARNESS_PROMPT_TEMPLATE_VERSION:
        failures.append("unsupported_prompt_template_version")

    snapshot: HarnessEvidenceSnapshot | None = None
    raw_snapshot = payload.get("evidence_snapshot")
    try:
        snapshot = HarnessEvidenceSnapshot.model_validate(raw_snapshot)
    except ValueError:
        failures.append("invalid_evidence_snapshot")
    computed_evidence_sha256: str | None = None
    if snapshot is not None:
        computed_evidence_sha256 = _sha256_text(
            _canonical_json(snapshot.model_dump(mode="json", exclude_none=True))
        )
        if payload.get("evidence_schema_version") != snapshot.schema_version:
            failures.append("evidence_schema_version_mismatch")
        if payload.get("evidence_sha256") != computed_evidence_sha256:
            failures.append("evidence_sha256_mismatch")
    expected_allowed_tools = selectable_harness_tools(snapshot) if snapshot is not None else None

    raw_manifest = payload.get("tool_manifest")
    manifest: dict[str, object] | None = raw_manifest if isinstance(raw_manifest, dict) else None
    if manifest is None:
        failures.append("invalid_tool_manifest")
    computed_manifest_sha256: str | None = None
    if manifest is not None:
        try:
            computed_manifest_sha256 = _sha256_text(_canonical_json(manifest))
        except (TypeError, ValueError):
            failures.append("invalid_tool_manifest")
            manifest = None
        else:
            if payload.get("tool_manifest_sha256") != computed_manifest_sha256:
                failures.append("tool_manifest_sha256_mismatch")
            expected_manifest = (
                provider_tool_manifest(expected_allowed_tools)
                if expected_allowed_tools is not None
                else None
            )
            if expected_manifest is None or manifest != expected_manifest:
                failures.append("tool_manifest_version_mismatch")
    if payload.get("tool_registry_version") != HARNESS_TOOL_REGISTRY_VERSION:
        failures.append("tool_registry_version_mismatch")
    if expected_allowed_tools is None or payload.get("allowed_tools") != list(
        expected_allowed_tools
    ):
        failures.append("allowed_tools_mismatch")

    computed_prompt_sha256: str | None = None
    if snapshot is not None and manifest is not None:
        system, user = build_decision_messages(
            snapshot,
            tool_manifest=manifest,
        )
        computed_prompt_sha256 = _sha256_text(f"{system}\n{user}")
        if payload.get("prompt_sha256") != computed_prompt_sha256:
            failures.append("prompt_sha256_mismatch")

    return HarnessDecisionTraceVerification(
        valid=not failures,
        failures=tuple(failures),
        evidence_sha256=computed_evidence_sha256,
        tool_manifest_sha256=computed_manifest_sha256,
        prompt_sha256=computed_prompt_sha256,
    )


def _verified_started_decision_id(event: models.JobEvent) -> str | None:
    if event.event_type != "harness_decision_started" or not isinstance(event.payload_json, dict):
        return None
    decision_id = event.payload_json.get("decision_id")
    if not isinstance(decision_id, str):
        return None
    verification = verify_harness_decision_trace(event.payload_json)
    return decision_id.lower() if verification.valid else None


def _event_decision_id(event: models.JobEvent) -> str | None:
    if not isinstance(event.payload_json, dict):
        return None
    decision_id = event.payload_json.get("decision_id")
    if (
        not isinstance(decision_id, str)
        or len(decision_id) != 32
        or any(char not in "0123456789abcdefABCDEF" for char in decision_id)
    ):
        return None
    return decision_id.lower()


def _event_generation(event: models.JobEvent) -> int | None:
    """Return an exact positive integer generation from an untrusted event.

    JobEvent payloads are intentionally schema-flexible.  Filtering with a
    database-side JSON integer cast is therefore unsafe on PostgreSQL because
    one historical string value can make the whole query raise.  Keep the SQL
    query type-agnostic and validate the bounded result window in Python.
    """

    if not isinstance(event.payload_json, dict):
        return None
    generation = event.payload_json.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int):
        return None
    return generation if generation >= 1 else None


def _recent_harness_decision_events(
    db: Session,
    job: models.Job,
) -> list[models.JobEvent]:
    """Load bounded companions for recent execution-result decision IDs.

    A bounded newest-first result scan avoids an O(generations^2) replay of
    historical started traces.  Generation filtering happens in Python because
    JobEvent JSON is untrusted and a PostgreSQL JSON-to-integer cast would let
    one malformed historical value break every future routing decision.  The
    second query still fetches every companion and duplicate for the selected
    IDs so provenance validation can fail closed rather than trusting event
    adjacency.
    """

    upper_generation = max(0, int(job.current_generation or 0)) + 1
    lower_generation = max(
        1,
        upper_generation - _DECISION_MEMORY_LOOKBACK_GENERATIONS,
    )
    scanned_results = list(
        db.scalars(
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job.id,
                models.JobEvent.event_type == "harness_tool_execution_result",
            )
            .order_by(
                models.JobEvent.created_at.desc(),
                models.JobEvent.id.desc(),
            )
            .limit(_DECISION_MEMORY_RESULT_SCAN_LIMIT + 1)
        )
    )
    if len(scanned_results) > _DECISION_MEMORY_RESULT_SCAN_LIMIT:
        return []
    recent_results = [
        event
        for event in scanned_results
        if (
            (event_generation := _event_generation(event)) is not None
            and lower_generation <= event_generation <= upper_generation
        )
    ]
    decision_ids = tuple(
        dict.fromkeys(
            decision_id
            for event in recent_results
            if (decision_id := _event_decision_id(event)) is not None
        )
    )
    if not decision_ids:
        return []

    decision_id_json = models.JobEvent.payload_json["decision_id"].as_string()
    companions = list(
        db.scalars(
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job.id,
                models.JobEvent.event_type.in_(
                    (
                        "harness_decision_started",
                        "harness_decision_rejected",
                        "harness_decision_accepted",
                        "harness_decision_fallback",
                        "harness_tool_execution_result",
                    )
                ),
                decision_id_json.in_(decision_ids),
            )
            .order_by(
                models.JobEvent.created_at.asc(),
                models.JobEvent.id.asc(),
            )
            .limit(_DECISION_MEMORY_COMPANION_SCAN_LIMIT + 1)
        )
    )
    if len(companions) > _DECISION_MEMORY_COMPANION_SCAN_LIMIT:
        return []
    return companions


def _recent_harness_multi_tool_events(
    db: Session,
    job: models.Job,
) -> list[models.JobEvent]:
    """Load a bounded, duplicate-preserving multi-tool provenance window."""

    upper_generation = max(0, int(job.current_generation or 0)) + 1
    lower_generation = max(
        1,
        upper_generation - _DECISION_MEMORY_LOOKBACK_GENERATIONS,
    )
    scanned_results = list(
        db.scalars(
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job.id,
                models.JobEvent.event_type == "harness_multi_tool_execution_result",
            )
            .order_by(
                models.JobEvent.created_at.desc(),
                models.JobEvent.id.desc(),
            )
            .limit(_GENERATION_PLAN_RESULT_SCAN_LIMIT + 1)
        )
    )
    if len(scanned_results) > _GENERATION_PLAN_RESULT_SCAN_LIMIT:
        return []
    recent_results = [
        event
        for event in scanned_results
        if (
            (event_generation := _event_generation(event)) is not None
            and lower_generation <= event_generation <= upper_generation
        )
    ]
    decision_ids = tuple(
        dict.fromkeys(
            decision_id
            for event in recent_results
            if (decision_id := _event_decision_id(event)) is not None
        )
    )
    if not decision_ids:
        return []
    decision_id_json = models.JobEvent.payload_json["decision_id"].as_string()
    companions = list(
        db.scalars(
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job.id,
                models.JobEvent.event_type.in_(
                    (
                        "harness_budget_plan_started",
                        "harness_budget_plan_accepted",
                        "harness_budget_plan_fallback",
                        "harness_budget_plan_stop_accepted",
                        "harness_plan_revision_started",
                        "harness_plan_revision_accepted",
                        "harness_plan_revision_fallback",
                        "harness_cognitive_review_result",
                        "harness_multi_tool_execution_result",
                    )
                ),
                decision_id_json.in_(decision_ids),
            )
            .order_by(
                models.JobEvent.created_at.asc(),
                models.JobEvent.id.asc(),
            )
            .limit(_GENERATION_PLAN_COMPANION_SCAN_LIMIT + 1)
        )
    )
    if len(companions) > _GENERATION_PLAN_COMPANION_SCAN_LIMIT:
        return []
    return companions


def _strict_hex(value: object, *, length: int) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(char not in "0123456789abcdefABCDEF" for char in value)
    ):
        return None
    return value.lower()


def _bounded_number(
    value: object,
    *,
    maximum: float = 600_000.0,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > maximum:
        return None
    return number


def _multi_plan_binding(
    payload: dict[str, object],
) -> tuple[str, int, str, str | None] | None:
    decision_id = _strict_hex(payload.get("decision_id"), length=32)
    generation = payload.get("generation")
    evidence_sha256 = _strict_hex(payload.get("evidence_sha256"), length=64)
    raw_prompt_sha256 = payload.get("prompt_sha256")
    prompt_sha256 = (
        None
        if raw_prompt_sha256 is None
        else _strict_hex(raw_prompt_sha256, length=64)
    )
    if (
        decision_id is None
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
        or evidence_sha256 is None
        or (raw_prompt_sha256 is not None and prompt_sha256 is None)
        or payload.get("evidence_schema_version") != HARNESS_EVIDENCE_SCHEMA_VERSION
        or payload.get("tool_registry_version") != HARNESS_TOOL_REGISTRY_VERSION
        or payload.get("budget_policy_version") != HARNESS_BUDGET_POLICY_VERSION
        or payload.get("plan_prompt_version") != HARNESS_BUDGET_PROMPT_VERSION
    ):
        return None
    return decision_id, generation, evidence_sha256, prompt_sha256


def _validated_compiled_plan(
    *,
    raw_plan: object,
    raw_opportunity: object,
) -> HarnessCompiledGenerationPlan | None:
    """Recompile a persisted plan and require exact canonical-byte semantics."""

    try:
        opportunity = HarnessBudgetOpportunity.model_validate_json(
            _canonical_json(raw_opportunity)
        )
        compiled = HarnessCompiledGenerationPlan.model_validate_json(
            _canonical_json(raw_plan)
        )
        plan = HarnessGenerationPlan(
            schema_version="1.0",
            decision="continue",
            generation_goal=compiled.generation_goal,
            tool_calls=tuple(
                HarnessToolAllocation(
                    tool_id=call.tool_id,
                    allocation=call.allocation,
                    fidelity_mode=call.fidelity_mode,
                    focus=call.focus,
                )
                for call in compiled.calls
            ),
            stop=HarnessStopRecommendation(
                recommended=False,
                reason_code=None,
            ),
            uncertainty=HarnessPlanUncertainty(
                level="low",
                missing_evidence=(),
            ),
        )
        expected = compile_generation_plan(plan, opportunity)
    except (TypeError, ValueError):
        return None
    return compiled if expected == compiled else None


def _revision_binding(
    payload: dict[str, object],
) -> tuple[str, str, int, str, str | None] | None:
    decision_id = _strict_hex(payload.get("decision_id"), length=32)
    revision_id = _strict_hex(payload.get("revision_id"), length=32)
    generation = payload.get("generation")
    plan_sha256 = _strict_hex(payload.get("compiled_plan_sha256"), length=64)
    raw_prompt_sha256 = payload.get("prompt_sha256")
    prompt_sha256 = (
        None
        if raw_prompt_sha256 is None
        else _strict_hex(raw_prompt_sha256, length=64)
    )
    if (
        decision_id is None
        or revision_id is None
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
        or plan_sha256 is None
        or (raw_prompt_sha256 is not None and prompt_sha256 is None)
        or payload.get("revision_prompt_version")
        != HARNESS_PLAN_REVISION_PROMPT_VERSION
    ):
        return None
    return decision_id, revision_id, generation, plan_sha256, prompt_sha256


def _selected_refs(payload: dict[str, object]) -> tuple[str, ...] | None:
    raw = payload.get("selected_proposal_refs")
    if not isinstance(raw, list) or any(
        not isinstance(item, str)
        or len(item) > 32
        or not item.startswith("proposal_")
        for item in raw
    ):
        return None
    refs = tuple(raw)
    return refs if len(refs) == len(set(refs)) else None


def _event_order_key(event: models.JobEvent) -> tuple[datetime, str]:
    created_at = event.created_at
    if not isinstance(created_at, datetime):
        created_at = datetime.min.replace(tzinfo=timezone.utc)
    elif created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at, event.id if isinstance(event.id, str) else ""


def _event_happened_after(
    left: models.JobEvent,
    right: models.JobEvent,
) -> bool:
    """Compare persisted event time without inventing order from random IDs.

    SQLite assigns one timestamp to multiple events flushed in the same
    transaction. Event IDs still make sorting deterministic, but they are
    random identities and cannot prove that one tied event happened later.
    """

    return _event_order_key(left)[0] > _event_order_key(right)[0]


def _generation_plan_history(
    events: list[models.JobEvent],
    *,
    current_generation: int,
) -> tuple[HarnessGenerationPlanMemory, ...]:
    """Compile only complete multi-tool event chains into provider evidence."""

    ordered = sorted(events, key=_event_order_key)
    by_decision: dict[str, list[models.JobEvent]] = {}
    for event in ordered:
        decision_id = _event_decision_id(event)
        if decision_id is not None:
            by_decision.setdefault(decision_id, []).append(event)

    verified: list[tuple[models.JobEvent, HarnessGenerationPlanMemory]] = []
    for decision_id, decision_events in by_decision.items():
        by_type: dict[str, list[models.JobEvent]] = {}
        for event in decision_events:
            by_type.setdefault(event.event_type, []).append(event)
        results = by_type.get("harness_multi_tool_execution_result", [])
        decisions = [
            event
            for event_type in (
                "harness_budget_plan_accepted",
                "harness_budget_plan_fallback",
                "harness_budget_plan_stop_accepted",
            )
            for event in by_type.get(event_type, [])
        ]
        if len(results) != 1 or len(decisions) != 1:
            continue
        result_event = results[0]
        decision_event = decisions[0]
        if not isinstance(result_event.payload_json, dict) or not isinstance(
            decision_event.payload_json,
            dict,
        ):
            continue
        result_payload = dict(result_event.payload_json)
        decision_payload = dict(decision_event.payload_json)
        result_binding = _multi_plan_binding(result_payload)
        decision_binding = _multi_plan_binding(decision_payload)
        if (
            result_binding is None
            or decision_binding is None
            or result_binding != decision_binding
            or result_binding[0] != decision_id
            or result_binding[1] > max(0, current_generation) + 1
            or _event_happened_after(decision_event, result_event)
        ):
            continue
        _, generation, _, prompt_sha256 = result_binding
        decision_source = result_payload.get("decision_source")
        status = result_payload.get("status")
        starts = by_type.get("harness_budget_plan_started", [])

        if decision_event.event_type == "harness_budget_plan_stop_accepted":
            if (
                decision_source != "model"
                or decision_payload.get("source") != "model"
                or status != "stop_accepted"
                or len(starts) != 1
                or prompt_sha256 is None
                or result_payload.get("provider_call_count") != 1
            ):
                continue
            start = starts[0]
            if not isinstance(start.payload_json, dict):
                continue
            if (
                _multi_plan_binding(dict(start.payload_json)) != result_binding
                or _event_happened_after(start, decision_event)
            ):
                continue
            plan_wall = _bounded_number(result_payload.get("plan_decision_wall_ms"))
            if plan_wall is None:
                continue
            verified.append(
                (
                    result_event,
                    HarnessGenerationPlanMemory(
                        generation=generation,
                        decision_source="model",
                        revision_source="not_applicable",
                        status="stop_accepted",
                        planned_candidates=0,
                        usable_proposal_count=0,
                        dispatched_candidates=0,
                        dispatched_trials=0,
                        projected_trial_upper_bound=0,
                        projected_critical_path_latency_budget_ms=0,
                        projected_cpu_budget_ms=0,
                        plan_decision_wall_ms=plan_wall,
                        revision_wall_ms=0.0,
                        tool_execution_wall_ms=0.0,
                        actual_tool_cpu_ms=0.0,
                        provider_call_count=1,
                        tool_calls=(),
                    ),
                )
            )
            continue

        if status not in {"dispatched", "search_space_exhausted"}:
            continue
        if decision_event.event_type == "harness_budget_plan_accepted":
            if (
                decision_source != "model"
                or decision_payload.get("source") != "model"
                or result_payload.get("fallback_reason") is not None
                or len(starts) != 1
                or prompt_sha256 is None
            ):
                continue
            start = starts[0]
            if not isinstance(start.payload_json, dict):
                continue
            start_payload = dict(start.payload_json)
            if (
                _multi_plan_binding(start_payload) != result_binding
                or _event_happened_after(start, decision_event)
            ):
                continue
            raw_opportunity = start_payload.get("opportunity")
            raw_plan = decision_payload.get("compiled_plan")
            typed_source: Literal["model", "deterministic_fallback"] = "model"
        else:
            if (
                decision_source != "deterministic_fallback"
                or decision_payload.get("source") != "deterministic_fallback"
                or not isinstance(decision_payload.get("reason"), str)
                or result_payload.get("fallback_reason")
                != decision_payload.get("reason")
                or len(starts) > 1
            ):
                continue
            raw_opportunity = decision_payload.get("opportunity")
            raw_plan = decision_payload.get("compiled_plan")
            typed_source = "deterministic_fallback"
            if starts:
                start = starts[0]
                if not isinstance(start.payload_json, dict) or (
                    _multi_plan_binding(dict(start.payload_json)) != result_binding
                    or _event_happened_after(start, decision_event)
                ):
                    continue

        compiled = _validated_compiled_plan(
            raw_plan=raw_plan,
            raw_opportunity=raw_opportunity,
        )
        if (
            compiled is None
            or compiled.generation != generation
            or result_payload.get("plan_sha256") != compiled.plan_sha256
            or result_payload.get("planned_candidates")
            != compiled.projected_candidate_count
            or result_payload.get("projected_trial_upper_bound")
            != compiled.projected_trial_upper_bound
            or result_payload.get("projected_critical_path_latency_budget_ms")
            != compiled.projected_critical_path_latency_budget_ms
            or result_payload.get("projected_cpu_budget_ms")
            != compiled.projected_cpu_budget_ms
        ):
            continue

        revision_id = _strict_hex(result_payload.get("revision_id"), length=32)
        if revision_id is None:
            continue
        revision_decisions = [
            event
            for event_type in (
                "harness_plan_revision_accepted",
                "harness_plan_revision_fallback",
            )
            for event in by_type.get(event_type, [])
            if isinstance(event.payload_json, dict)
            and event.payload_json.get("revision_id") == revision_id
        ]
        revision_starts = [
            event
            for event in by_type.get("harness_plan_revision_started", [])
            if isinstance(event.payload_json, dict)
            and event.payload_json.get("revision_id") == revision_id
        ]
        if len(revision_decisions) != 1:
            continue
        revision_event = revision_decisions[0]
        revision_payload_json = revision_event.payload_json
        if not isinstance(revision_payload_json, dict):
            continue
        revision_payload = dict(revision_payload_json)
        revision_binding = _revision_binding(revision_payload)
        expected_revision_binding = (
            decision_id,
            revision_id,
            generation,
            compiled.plan_sha256,
            revision_binding[4] if revision_binding is not None else None,
        )
        if (
            revision_binding is None
            or revision_binding != expected_revision_binding
            or _event_happened_after(decision_event, revision_event)
            or _event_happened_after(revision_event, result_event)
        ):
            continue
        revision_refs = _selected_refs(revision_payload)
        result_refs = _selected_refs(result_payload)
        if revision_refs is None or result_refs is None:
            continue
        review_events = by_type.get("harness_cognitive_review_result", [])
        if review_events:
            if len(review_events) != 1:
                continue
            review_event = review_events[0]
            review_payload_json = review_event.payload_json
            if not isinstance(review_payload_json, dict):
                continue
            review_payload = dict(review_payload_json)
            review_input_refs = review_payload.get("input_selected_proposal_refs")
            review_available_refs = review_payload.get("available_proposal_refs")
            review_result_refs = _selected_refs(review_payload)
            if (
                review_payload.get("decision_id") != decision_id
                or review_payload.get("revision_id") != revision_id
                or review_payload.get("generation") != generation
                or not isinstance(review_input_refs, list)
                or tuple(review_input_refs) != revision_refs
                or not isinstance(review_available_refs, list)
                or len(set(review_available_refs)) != len(review_available_refs)
                or any(not isinstance(ref, str) for ref in review_available_refs)
                or review_result_refs != result_refs
                or not set(result_refs).issubset(review_available_refs)
                or review_payload.get("holdout_outcomes_visible") is not False
                or _event_happened_after(revision_event, review_event)
                or _event_happened_after(review_event, result_event)
            ):
                continue
        elif revision_refs != result_refs:
            continue
        revision_source = result_payload.get("revision_source")
        if revision_event.event_type == "harness_plan_revision_accepted":
            if (
                revision_source != "model"
                or revision_payload.get("source") != "model"
                or result_payload.get("revision_fallback_reason") is not None
                or len(revision_starts) != 1
                or revision_binding[4] is None
            ):
                continue
            revision_start = revision_starts[0]
            if not isinstance(revision_start.payload_json, dict) or (
                _revision_binding(dict(revision_start.payload_json))
                != revision_binding
                or _event_happened_after(revision_start, revision_event)
            ):
                continue
            typed_revision_source: Literal["model", "deterministic_fallback"] = "model"
        else:
            if (
                revision_source != "deterministic_fallback"
                or not isinstance(revision_payload.get("reason"), str)
                or result_payload.get("revision_fallback_reason")
                != revision_payload.get("reason")
                or len(revision_starts) > 1
            ):
                continue
            if revision_starts:
                revision_start = revision_starts[0]
                if not isinstance(revision_start.payload_json, dict) or (
                    _revision_binding(dict(revision_start.payload_json))
                    != revision_binding
                    or _event_happened_after(revision_start, revision_event)
                ):
                    continue
            typed_revision_source = "deterministic_fallback"

        raw_tool_calls = result_payload.get("tool_calls")
        if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) != len(
            compiled.calls
        ):
            continue
        tool_memories: list[HarnessToolCallExecutionMemory] = []
        tool_rows_valid = True
        for raw_call, compiled_call in zip(raw_tool_calls, compiled.calls, strict=True):
            if not isinstance(raw_call, dict) or any(
                (
                    raw_call.get("call_id") != compiled_call.call_id,
                    raw_call.get("tool_id") != compiled_call.tool_id,
                    raw_call.get("allocation") != compiled_call.allocation,
                    raw_call.get("parallel_safe") != compiled_call.parallel_safe,
                    raw_call.get("latency_budget_ms")
                    != compiled_call.latency_budget_ms,
                    raw_call.get("cpu_budget_ms") != compiled_call.cpu_budget_ms,
                )
            ):
                tool_rows_valid = False
                break
            raw_status = raw_call.get("status")
            raw_proposal_count = raw_call.get("proposal_count")
            elapsed_ms = _bounded_number(raw_call.get("elapsed_ms"))
            cpu_ms = _bounded_number(raw_call.get("cpu_ms"))
            if (
                raw_status
                not in {"completed", "tool_error", "cost_budget_exceeded"}
                or isinstance(raw_proposal_count, bool)
                or not isinstance(raw_proposal_count, int)
                or elapsed_ms is None
                or cpu_ms is None
            ):
                tool_rows_valid = False
                break
            try:
                tool_memories.append(
                    HarnessToolCallExecutionMemory(
                        tool_id=compiled_call.tool_id,
                        allocation=compiled_call.allocation,
                        parallel_safe=compiled_call.parallel_safe,
                        status=cast(
                            Literal[
                                "completed",
                                "tool_error",
                                "cost_budget_exceeded",
                            ],
                            raw_status,
                        ),
                        proposal_count=raw_proposal_count,
                        elapsed_ms=elapsed_ms,
                        cpu_ms=cpu_ms,
                        latency_budget_ms=compiled_call.latency_budget_ms,
                        cpu_budget_ms=compiled_call.cpu_budget_ms,
                    )
                )
            except (TypeError, ValueError):
                tool_rows_valid = False
                break
        if not tool_rows_valid:
            continue

        plan_wall = _bounded_number(result_payload.get("plan_decision_wall_ms"))
        revision_wall = _bounded_number(result_payload.get("revision_wall_ms"))
        tool_wall = _bounded_number(result_payload.get("tool_execution_wall_ms"))
        actual_cpu = _bounded_number(result_payload.get("actual_tool_cpu_ms"))
        provider_calls = result_payload.get("provider_call_count")
        provider_successes = result_payload.get("provider_success_count")
        usable = result_payload.get("usable_proposal_count")
        dispatched_candidates = result_payload.get("dispatched_candidates")
        dispatched_trials = result_payload.get("dispatched_trials")
        if (
            plan_wall is None
            or revision_wall is None
            or tool_wall is None
            or actual_cpu is None
            or isinstance(provider_calls, bool)
            or not isinstance(provider_calls, int)
            or not 0 <= provider_calls <= 4
            or (
                provider_successes is not None
                and (
                    isinstance(provider_successes, bool)
                    or not isinstance(provider_successes, int)
                    or not 0 <= provider_successes <= provider_calls
                )
            )
            or isinstance(usable, bool)
            or not isinstance(usable, int)
            or usable < 0
            or isinstance(dispatched_candidates, bool)
            or not isinstance(dispatched_candidates, int)
            or dispatched_candidates < 0
            or isinstance(dispatched_trials, bool)
            or not isinstance(dispatched_trials, int)
            or dispatched_trials < 0
            or abs(actual_cpu - sum(item.cpu_ms for item in tool_memories)) > 0.01
            or (
                tool_memories
                and tool_wall + 0.01 < max(item.elapsed_ms for item in tool_memories)
            )
            or (status == "dispatched" and len(result_refs) != dispatched_candidates)
            or (status == "search_space_exhausted" and result_refs)
        ):
            continue
        try:
            memory = HarnessGenerationPlanMemory(
                generation=generation,
                decision_source=typed_source,
                revision_source=typed_revision_source,
                status=status,
                planned_candidates=compiled.projected_candidate_count,
                usable_proposal_count=usable,
                dispatched_candidates=dispatched_candidates,
                dispatched_trials=dispatched_trials,
                projected_trial_upper_bound=compiled.projected_trial_upper_bound,
                projected_critical_path_latency_budget_ms=(
                    compiled.projected_critical_path_latency_budget_ms
                ),
                projected_cpu_budget_ms=compiled.projected_cpu_budget_ms,
                plan_decision_wall_ms=plan_wall,
                revision_wall_ms=revision_wall,
                tool_execution_wall_ms=tool_wall,
                actual_tool_cpu_ms=actual_cpu,
                provider_call_count=provider_calls,
                tool_calls=tuple(tool_memories),
            )
        except (TypeError, ValueError):
            continue
        verified.append((result_event, memory))

    counts: dict[int, int] = {}
    for _, item in verified:
        counts[item.generation] = counts.get(item.generation, 0) + 1
    return tuple(
        item
        for _, item in sorted(
            verified,
            key=lambda pair: _event_order_key(pair[0]),
        )
        if counts[item.generation] == 1
    )


def _compile_cross_job_memory(
    db: Session,
    *,
    current_job: models.Job,
    current_snapshot: HarnessEvidenceSnapshot,
) -> HarnessEvidenceSnapshot:
    """Lazily materialize bounded terminal history, then retrieve it safely."""

    if not isinstance(current_job.user_id, str) or not current_job.user_id:
        return current_snapshot
    source_jobs = list(
        db.scalars(
            select(models.Job)
            .where(
                models.Job.user_id == current_job.user_id,
                models.Job.id != current_job.id,
                models.Job.status.in_(("COMPLETED", "FAILED", "CANCELLED")),
            )
            .order_by(models.Job.updated_at.desc(), models.Job.id.desc())
            .limit(_CROSS_JOB_SOURCE_SCAN_LIMIT)
        )
    )
    for source_job in source_jobs:
        source_events = _recent_harness_decision_events(db, source_job)
        verified_started = frozenset(
            verified_id
            for event in source_events
            if (verified_id := _verified_started_decision_id(event)) is not None
        )
        source_snapshot, _ = build_harness_evidence(
            source_job,
            execution_events=source_events,
            verified_started_decision_ids=verified_started,
        )
        materialize_verified_terminal_job_experiences(
            db,
            source_job=source_job,
            snapshot=source_snapshot,
        )
    db.flush()
    cross_job_memory = retrieve_cross_job_memory(
        db,
        current_job=current_job,
        current_snapshot=current_snapshot,
    )
    return current_snapshot.model_copy(
        update={"cross_job_memory": cross_job_memory}
    )


def _fallback(
    db: Session,
    job: models.Job,
    *,
    snapshot: HarnessEvidenceSnapshot,
    decision_id: str,
    generation: int,
    reason: str,
    evidence_sha256: str,
    model: str | None,
    prompt_sha256: str | None = None,
    error_type: str | None = None,
) -> HarnessDecision:
    rejected_payload: dict[str, Any] = {
        "decision_id": decision_id,
        "generation": generation,
        "reason": reason,
        "model": model,
        "evidence_sha256": evidence_sha256,
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
    }
    if prompt_sha256 is not None:
        rejected_payload["prompt_sha256"] = prompt_sha256
    if error_type:
        rejected_payload["error_type"] = error_type[:128]
    record_event(db, job.id, "harness_decision_rejected", rejected_payload)
    record_event(
        db,
        job.id,
        "harness_decision_fallback",
        {
            "decision_id": decision_id,
            "generation": generation,
            "reason": reason,
            "tool_id": HARNESS_FALLBACK_TOOL,
            "plan_phase": snapshot.plan.phase,
            "batch_policy": snapshot.plan.batch_policy,
            "evidence_sha256": evidence_sha256,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
            **({"prompt_sha256": prompt_sha256} if prompt_sha256 is not None else {}),
        },
    )
    return HarnessDecision(
        decision_id=decision_id,
        generation=generation,
        tool_id=HARNESS_FALLBACK_TOOL,
        rationale=(
            "The model decision was unavailable or invalid, so the bounded "
            "deterministic optimizer portfolio was selected."
        ),
        source="deterministic_fallback",
        model=model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        fallback_reason=reason,
        plan_phase=snapshot.plan.phase,
        batch_policy=snapshot.plan.batch_policy,
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
        prompt_template_version=HARNESS_PROMPT_TEMPLATE_VERSION,
    )


def _budget_plan_fallback(
    db: Session,
    job: models.Job,
    *,
    decision_id: str,
    generation: int,
    opportunity: HarnessBudgetOpportunity,
    reason: str,
    evidence_sha256: str,
    model: str | None,
    prompt_sha256: str | None = None,
    validation: HarnessPlanValidation | None = None,
    error_type: str | None = None,
) -> HarnessBudgetPlanDecision:
    compiled = deterministic_fallback_plan(opportunity)
    payload: dict[str, Any] = {
        "decision_id": decision_id,
        "generation": generation,
        "reason": reason,
        "model": model,
        "source": "deterministic_fallback",
        "opportunity": opportunity.model_dump(mode="json"),
        "compiled_plan": compiled.model_dump(mode="json"),
        "compiled_plan_sha256": compiled.plan_sha256,
        "projected_candidate_count": compiled.projected_candidate_count,
        "projected_trial_upper_bound": compiled.projected_trial_upper_bound,
        "projected_critical_path_latency_budget_ms": (
            compiled.projected_critical_path_latency_budget_ms
        ),
        "projected_cpu_budget_ms": compiled.projected_cpu_budget_ms,
        "evidence_sha256": evidence_sha256,
        "budget_policy_version": HARNESS_BUDGET_POLICY_VERSION,
        "plan_prompt_version": HARNESS_BUDGET_PROMPT_VERSION,
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
    }
    if prompt_sha256 is not None:
        payload["prompt_sha256"] = prompt_sha256
    if validation is not None:
        payload["validation"] = validation.model_dump(mode="json")
    if error_type is not None:
        payload["error_type"] = error_type[:128]
    record_event(db, job.id, "harness_budget_plan_fallback", payload)
    return HarnessBudgetPlanDecision(
        decision_id=decision_id,
        generation=generation,
        compiled_plan=compiled,
        stop_reason=None,
        source="deterministic_fallback",
        model=model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        fallback_reason=reason,
        validation=validation,
    )


def select_optimizer_budget_plan(
    db: Session,
    job: models.Job,
    *,
    opportunity: HarnessBudgetOpportunity,
    client: OpenAIClientLike | None = None,
) -> HarnessBudgetPlanDecision:
    """Select, validate, and compile one multi-tool plan without executing it."""

    decision_id = uuid.uuid4().hex
    generation = job.current_generation + 1
    if opportunity.generation != generation:
        raise ValueError("budget opportunity generation does not match the Job")
    evidence_snapshot, has_scored_evidence = current_harness_evidence_snapshot(
        db,
        job,
    )
    evidence = evidence_snapshot.model_dump(mode="json", exclude_none=True)
    evidence_sha256 = _sha256_text(_canonical_json(evidence))
    provider = job.llm_provider or "openai"
    configured_model = job.openai_model
    chosen_model = configured_model or _DEFAULT_MODEL
    opportunity_tools = tuple(item.tool_id for item in opportunity.tool_budgets)
    selectable_tools = selectable_harness_tools(evidence_snapshot)
    if any(tool_id not in selectable_tools for tool_id in opportunity_tools):
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="opportunity_contract_mismatch",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )
    if configured_model is None and provider != "openai":
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="missing_model",
            evidence_sha256=evidence_sha256,
            model=None,
        )
    if not has_scored_evidence:
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="insufficient_evidence",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )

    tool_manifest = provider_tool_manifest(opportunity_tools)
    system, user = build_budget_plan_messages(
        evidence_snapshot=evidence,
        opportunity=opportunity,
        tool_manifest=tool_manifest,
    )
    settings = get_settings()
    if len(user.encode("utf-8")) > settings.llm_max_prompt_bytes:
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="prompt_too_large",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )
    prompt_sha256 = _sha256_text(f"{system}\n{user}")
    plan_schema = generation_plan_schema(opportunity)
    recovered_turn = recover_existing_cognitive_turn(
        db,
        job,
        generation_index=generation,
        turn_index=1,
    )
    if recovered_turn == "pending":
        raise CognitiveTurnPending()
    if recovered_turn == "consumed":
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="cognitive_turn_consumed_without_replayable_result",
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
        )
    effective_client = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            return _budget_plan_fallback(
                db,
                job,
                decision_id=decision_id,
                generation=generation,
                opportunity=opportunity,
                reason="missing_api_key",
                evidence_sha256=evidence_sha256,
                prompt_sha256=prompt_sha256,
                model=chosen_model,
            )
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=plan_schema,
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=job.provider_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )

    record_event(
        db,
        job.id,
        "harness_budget_plan_started",
        {
            "decision_id": decision_id,
            "generation": generation,
            "model": chosen_model,
            "provider": provider,
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "opportunity": opportunity.model_dump(mode="json"),
            "budget_policy_version": HARNESS_BUDGET_POLICY_VERSION,
            "plan_prompt_version": HARNESS_BUDGET_PROMPT_VERSION,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
    )
    attempt = begin_cognitive_turn(
        db,
        job,
        generation_index=generation,
        turn_index=1,
        turn_role="plan",
        trigger_reasons=("default_plan",),
        model_snapshot=chosen_model,
        prompt_sha256=prompt_sha256,
        evidence_sha256=evidence_sha256,
        schema_sha256=sha256_json(plan_schema),
        tool_outputs_sha256=empty_tool_outputs_sha256(),
    )
    effective_client = bind_provider_request_accounting(
        effective_client,
        db,
        job,
        cognitive_turn_receipt_id=attempt.receipt_id,
    )
    try:
        raw = effective_client.generate(
            model=chosen_model,
            system=system,
            user=user,
        )
    except Exception as exc:
        if provider_request_outcome_pending(
            db,
            cognitive_turn_receipt_id=attempt.receipt_id,
        ):
            raise CognitiveTurnPending() from exc
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="client_error",
        )
        logger.warning(
            "harness budget plan call failed for job %s (error_type=%s)",
            job.id,
            type(exc).__name__,
        )
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="client_error",
            error_type=type(exc).__name__,
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
        )

    plan, validation = validate_generation_plan(raw, opportunity)
    if plan is None:
        rejection_code = next(
            (rule.code for rule in validation.rule_results if not rule.passed),
            "invalid_plan",
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            response=raw,
            error_code=rejection_code,
        )
        return _budget_plan_fallback(
            db,
            job,
            decision_id=decision_id,
            generation=generation,
            opportunity=opportunity,
            reason="invalid_plan",
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
            validation=validation,
        )
    if (
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response=raw,
        )
        == "source_drift"
    ):
        raise CognitiveTurnBlocked(
            "source_drift",
            "Software source changed while the provider turn was in flight.",
        )
    if plan.decision == "stop":
        stop_reason = plan.stop.reason_code
        if stop_reason is None:
            raise RuntimeError("accepted stop plan is missing its reason")
        record_event(
            db,
            job.id,
            "harness_budget_plan_stop_accepted",
            {
                "decision_id": decision_id,
                "generation": generation,
                "model": chosen_model,
                "source": "model",
                "stop_reason": stop_reason,
                "evidence_sha256": evidence_sha256,
                "prompt_sha256": prompt_sha256,
                "validation": validation.model_dump(mode="json"),
                "budget_policy_version": HARNESS_BUDGET_POLICY_VERSION,
                "plan_prompt_version": HARNESS_BUDGET_PROMPT_VERSION,
                "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
                "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            },
        )
        return HarnessBudgetPlanDecision(
            decision_id=decision_id,
            generation=generation,
            compiled_plan=None,
            stop_reason=stop_reason,
            source="model",
            model=chosen_model,
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            validation=validation,
        )

    compiled = compile_generation_plan(plan, opportunity)
    record_event(
        db,
        job.id,
        "harness_budget_plan_accepted",
        {
            "decision_id": decision_id,
            "generation": generation,
            "model": chosen_model,
            "source": "model",
            "compiled_plan": compiled.model_dump(mode="json"),
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "validation": validation.model_dump(mode="json"),
            "budget_policy_version": HARNESS_BUDGET_POLICY_VERSION,
            "plan_prompt_version": HARNESS_BUDGET_PROMPT_VERSION,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
    )
    return HarnessBudgetPlanDecision(
        decision_id=decision_id,
        generation=generation,
        compiled_plan=compiled,
        stop_reason=None,
        source="model",
        model=chosen_model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        validation=validation,
    )


def current_harness_evidence_snapshot(
    db: Session,
    job: models.Job,
) -> tuple[HarnessEvidenceSnapshot, bool]:
    """Build the current provider-safe snapshot without holdout outcomes."""

    recent_decision_events = _recent_harness_decision_events(db, job)
    recent_multi_tool_events = _recent_harness_multi_tool_events(db, job)
    verified_started_decision_ids = frozenset(
        verified_id
        for event in recent_decision_events
        if (verified_id := _verified_started_decision_id(event)) is not None
    )
    snapshot, has_scored_evidence = build_harness_evidence(
        job,
        execution_events=recent_decision_events,
        verified_started_decision_ids=verified_started_decision_ids,
        generation_plan_history=_generation_plan_history(
            recent_multi_tool_events,
            current_generation=max(0, int(job.current_generation or 0)),
        ),
    )
    return (
        _compile_cross_job_memory(
            db,
            current_job=job,
            current_snapshot=snapshot,
        ),
        has_scored_evidence,
    )


def _revision_fallback(
    db: Session,
    job: models.Job,
    *,
    decision_id: str,
    revision_id: str,
    generation: int,
    compiled_plan_sha256: str,
    proposals: tuple[HarnessProposalSummary, ...],
    maximum_dispatch_candidates: int,
    reason: str,
    model: str | None,
    prompt_sha256: str | None = None,
    error_type: str | None = None,
) -> HarnessPlanRevisionDecision:
    validation = deterministic_revision_fallback(
        proposals,
        maximum_dispatch_candidates=maximum_dispatch_candidates,
        rejection_code=reason,
    )
    payload: dict[str, Any] = {
        "decision_id": decision_id,
        "revision_id": revision_id,
        "generation": generation,
        "compiled_plan_sha256": compiled_plan_sha256,
        "reason": reason,
        "source": "deterministic_fallback",
        "model": model,
        "selected_proposal_refs": list(validation.selected_proposal_refs),
        "revision_prompt_version": HARNESS_PLAN_REVISION_PROMPT_VERSION,
    }
    if prompt_sha256 is not None:
        payload["prompt_sha256"] = prompt_sha256
    if error_type is not None:
        payload["error_type"] = error_type[:128]
    record_event(db, job.id, "harness_plan_revision_fallback", payload)
    return HarnessPlanRevisionDecision(
        revision_id=revision_id,
        decision_id=decision_id,
        selected_proposal_refs=validation.selected_proposal_refs,
        abandoned=False,
        source="deterministic_fallback",
        model=model,
        prompt_sha256=prompt_sha256,
        fallback_reason=reason,
        validation=validation,
    )


def select_plan_revision(
    db: Session,
    job: models.Job,
    *,
    plan_decision: HarnessBudgetPlanDecision,
    proposals: tuple[HarnessProposalSummary, ...],
    maximum_dispatch_candidates: int,
    client: OpenAIClientLike | None = None,
    allow_abandon: bool = False,
) -> HarnessPlanRevisionDecision:
    """Run at most one provider turn after pure proposal tools return."""

    revision_id = uuid.uuid4().hex
    compiled = plan_decision.compiled_plan
    if compiled is None:
        raise ValueError("a plan revision requires a compiled continue plan")
    if compiled.generation != job.current_generation + 1:
        raise ValueError("compiled plan generation drifted before revision")
    if not proposals:
        return _revision_fallback(
            db,
            job,
            decision_id=plan_decision.decision_id,
            revision_id=revision_id,
            generation=compiled.generation,
            compiled_plan_sha256=compiled.plan_sha256,
            proposals=proposals,
            maximum_dispatch_candidates=maximum_dispatch_candidates,
            reason="no_usable_proposals",
            model=plan_decision.model,
        )
    system, user = build_plan_revision_messages(
        compiled_plan=compiled,
        proposals=proposals,
        maximum_dispatch_candidates=maximum_dispatch_candidates,
    )
    settings = get_settings()
    if len(user.encode("utf-8")) > settings.llm_max_prompt_bytes:
        return _revision_fallback(
            db,
            job,
            decision_id=plan_decision.decision_id,
            revision_id=revision_id,
            generation=compiled.generation,
            compiled_plan_sha256=compiled.plan_sha256,
            proposals=proposals,
            maximum_dispatch_candidates=maximum_dispatch_candidates,
            reason="prompt_too_large",
            model=plan_decision.model,
        )
    prompt_sha256 = _sha256_text(f"{system}\n{user}")
    revision_schema = plan_revision_schema(
        proposals,
        maximum_dispatch_candidates=maximum_dispatch_candidates,
    )
    revision_evidence = {
        "compiled_plan": compiled.model_dump(mode="json"),
        "proposals": [proposal.model_dump(mode="json") for proposal in proposals],
        "maximum_dispatch_candidates": maximum_dispatch_candidates,
    }
    recovered_turn = recover_existing_cognitive_turn(
        db,
        job,
        generation_index=compiled.generation,
        turn_index=2,
    )
    if recovered_turn == "pending":
        raise CognitiveTurnPending()
    if recovered_turn == "consumed":
        return _revision_fallback(
            db,
            job,
            decision_id=plan_decision.decision_id,
            revision_id=revision_id,
            generation=compiled.generation,
            compiled_plan_sha256=compiled.plan_sha256,
            proposals=proposals,
            maximum_dispatch_candidates=maximum_dispatch_candidates,
            reason="cognitive_turn_consumed_without_replayable_result",
            prompt_sha256=prompt_sha256,
            model=plan_decision.model,
        )
    effective_client = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            return _revision_fallback(
                db,
                job,
                decision_id=plan_decision.decision_id,
                revision_id=revision_id,
                generation=compiled.generation,
                compiled_plan_sha256=compiled.plan_sha256,
                proposals=proposals,
                maximum_dispatch_candidates=maximum_dispatch_candidates,
                reason="missing_api_key",
                prompt_sha256=prompt_sha256,
                model=plan_decision.model,
            )
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=revision_schema,
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=job.provider_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )
    record_event(
        db,
        job.id,
        "harness_plan_revision_started",
        {
            "decision_id": plan_decision.decision_id,
            "revision_id": revision_id,
            "generation": compiled.generation,
            "model": plan_decision.model,
            "prompt_sha256": prompt_sha256,
            "compiled_plan_sha256": compiled.plan_sha256,
            "proposal_count": len(proposals),
            "maximum_dispatch_candidates": maximum_dispatch_candidates,
            "revision_prompt_version": HARNESS_PLAN_REVISION_PROMPT_VERSION,
        },
    )
    attempt = begin_cognitive_turn(
        db,
        job,
        generation_index=compiled.generation,
        turn_index=2,
        turn_role="revision",
        trigger_reasons=("post_tool_revision",),
        model_snapshot=plan_decision.model or _DEFAULT_MODEL,
        prompt_sha256=prompt_sha256,
        evidence_sha256=sha256_json(revision_evidence),
        schema_sha256=sha256_json(revision_schema),
        tool_outputs_sha256=sha256_json(
            [proposal.model_dump(mode="json") for proposal in proposals]
        ),
    )
    effective_client = bind_provider_request_accounting(
        effective_client,
        db,
        job,
        cognitive_turn_receipt_id=attempt.receipt_id,
    )
    try:
        raw = effective_client.generate(
            model=plan_decision.model or _DEFAULT_MODEL,
            system=system,
            user=user,
        )
    except Exception as exc:
        if provider_request_outcome_pending(
            db,
            cognitive_turn_receipt_id=attempt.receipt_id,
        ):
            raise CognitiveTurnPending() from exc
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="client_error",
        )
        logger.warning(
            "harness plan revision call failed for job %s (error_type=%s)",
            job.id,
            type(exc).__name__,
        )
        return _revision_fallback(
            db,
            job,
            decision_id=plan_decision.decision_id,
            revision_id=revision_id,
            generation=compiled.generation,
            compiled_plan_sha256=compiled.plan_sha256,
            proposals=proposals,
            maximum_dispatch_candidates=maximum_dispatch_candidates,
            reason="client_error",
            prompt_sha256=prompt_sha256,
            model=plan_decision.model,
            error_type=type(exc).__name__,
        )
    revision, validation = validate_plan_revision(
        raw,
        proposals=proposals,
        maximum_dispatch_candidates=maximum_dispatch_candidates,
        allow_abandon=allow_abandon,
    )
    if revision is None:
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            response=raw,
            error_code=validation.rejection_code or "invalid_revision",
        )
        return _revision_fallback(
            db,
            job,
            decision_id=plan_decision.decision_id,
            revision_id=revision_id,
            generation=compiled.generation,
            compiled_plan_sha256=compiled.plan_sha256,
            proposals=proposals,
            maximum_dispatch_candidates=maximum_dispatch_candidates,
            reason=validation.rejection_code or "invalid_revision",
            prompt_sha256=prompt_sha256,
            model=plan_decision.model,
        )
    if (
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response=raw,
        )
        == "source_drift"
    ):
        raise CognitiveTurnBlocked(
            "source_drift",
            "Software source changed while the provider turn was in flight.",
        )
    record_event(
        db,
        job.id,
        "harness_plan_revision_accepted",
        {
            "decision_id": plan_decision.decision_id,
            "revision_id": revision_id,
            "generation": compiled.generation,
            "model": plan_decision.model,
            "source": "model",
            "prompt_sha256": prompt_sha256,
            "compiled_plan_sha256": compiled.plan_sha256,
            "decision": revision.decision,
            "selected_proposal_refs": list(revision.selected_proposal_refs),
            "revision_prompt_version": HARNESS_PLAN_REVISION_PROMPT_VERSION,
        },
    )
    return HarnessPlanRevisionDecision(
        revision_id=revision_id,
        decision_id=plan_decision.decision_id,
        selected_proposal_refs=revision.selected_proposal_refs,
        abandoned=revision.decision == "abandon",
        source="model",
        model=plan_decision.model,
        prompt_sha256=prompt_sha256,
        fallback_reason=None,
        validation=validation,
    )


def select_optimizer_tool(
    db: Session,
    job: models.Job,
    *,
    client: OpenAIClientLike | None = None,
) -> HarnessDecision:
    """Choose one allowlisted optimizer using compact read-only evidence.

    Any provider, schema, credential, or evidence failure fails closed to the
    deterministic optimizer portfolio and records that fallback explicitly.
    """

    # One opaque identifier binds the provider trace or deterministic fallback
    # to the later execution receipt. It is created before any provider call so
    # every fail-closed path can be paired without trusting event adjacency.
    decision_id = uuid.uuid4().hex
    generation = job.current_generation + 1
    recent_decision_events = _recent_harness_decision_events(db, job)
    recent_multi_tool_events = _recent_harness_multi_tool_events(db, job)
    verified_started_decision_ids = frozenset(
        verified_id
        for event in recent_decision_events
        if (verified_id := _verified_started_decision_id(event)) is not None
    )
    evidence_snapshot, has_scored_evidence = build_harness_evidence(
        job,
        execution_events=recent_decision_events,
        verified_started_decision_ids=verified_started_decision_ids,
        generation_plan_history=_generation_plan_history(
            recent_multi_tool_events,
            current_generation=max(0, int(job.current_generation or 0)),
        ),
    )
    evidence_snapshot = _compile_cross_job_memory(
        db,
        current_job=job,
        current_snapshot=evidence_snapshot,
    )
    evidence = evidence_snapshot.model_dump(mode="json", exclude_none=True)
    evidence_json = _canonical_json(evidence)
    evidence_sha256 = _sha256_text(evidence_json)
    provider = job.llm_provider or "openai"
    configured_model = job.openai_model
    if configured_model is None and provider != "openai":
        return _fallback(
            db,
            job,
            snapshot=evidence_snapshot,
            decision_id=decision_id,
            generation=generation,
            reason="missing_model",
            evidence_sha256=evidence_sha256,
            model=None,
        )
    chosen_model = configured_model or _DEFAULT_MODEL
    if not has_scored_evidence:
        return _fallback(
            db,
            job,
            snapshot=evidence_snapshot,
            decision_id=decision_id,
            generation=generation,
            reason="insufficient_evidence",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )

    allowed_tools = selectable_harness_tools(evidence_snapshot)
    tool_manifest = provider_tool_manifest(allowed_tools)
    system, user = build_decision_messages(
        evidence_snapshot,
        tool_manifest=tool_manifest,
    )
    settings = get_settings()
    if len(user.encode("utf-8")) > settings.llm_max_prompt_bytes:
        return _fallback(
            db,
            job,
            snapshot=evidence_snapshot,
            decision_id=decision_id,
            generation=generation,
            reason="prompt_too_large",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )
    prompt_sha256 = _sha256_text(f"{system}\n{user}")
    tool_manifest_sha256 = _sha256_text(_canonical_json(tool_manifest))
    effective_client = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            return _fallback(
                db,
                job,
                snapshot=evidence_snapshot,
                decision_id=decision_id,
                generation=generation,
                reason="missing_api_key",
                evidence_sha256=evidence_sha256,
                prompt_sha256=prompt_sha256,
                model=chosen_model,
            )
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=decision_schema_for_snapshot(evidence_snapshot),
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=job.provider_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )

    record_event(
        db,
        job.id,
        "harness_decision_started",
        {
            "decision_id": decision_id,
            "generation": generation,
            "model": chosen_model,
            "provider": provider,
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "allowed_tools": list(allowed_tools),
            "trace_schema_version": HARNESS_DECISION_TRACE_SCHEMA_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "evidence_snapshot": evidence,
            "tool_manifest": tool_manifest,
            "tool_manifest_sha256": tool_manifest_sha256,
        },
    )
    try:
        raw = effective_client.generate(model=chosen_model, system=system, user=user)
    except Exception as exc:
        logger.warning(
            "harness decision call failed for job %s (error_type=%s)",
            job.id,
            type(exc).__name__,
        )
        return _fallback(
            db,
            job,
            snapshot=evidence_snapshot,
            decision_id=decision_id,
            generation=generation,
            reason="client_error",
            error_type=type(exc).__name__,
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
        )

    validated = validate_harness_decision_response(raw, evidence_snapshot)
    if validated is None:
        return _fallback(
            db,
            job,
            snapshot=evidence_snapshot,
            decision_id=decision_id,
            generation=generation,
            reason="invalid_response",
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
        )
    tool_id, rationale = validated
    record_event(
        db,
        job.id,
        "harness_decision_accepted",
        {
            "decision_id": decision_id,
            "generation": generation,
            "tool_id": tool_id,
            "rationale": rationale,
            "plan_phase": evidence_snapshot.plan.phase,
            "batch_policy": evidence_snapshot.plan.batch_policy,
            "model": chosen_model,
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        },
    )
    return HarnessDecision(
        decision_id=decision_id,
        generation=generation,
        tool_id=tool_id,
        rationale=rationale,
        source="model",
        model=chosen_model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        plan_phase=evidence_snapshot.plan.phase,
        batch_policy=evidence_snapshot.plan.batch_policy,
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
        prompt_template_version=HARNESS_PROMPT_TEMPLATE_VERSION,
    )


def is_experimental_harness_tool(
    tool_id: HarnessDispatchStrategy,
) -> bool:
    return tool_id != "cma_es"


def as_experimental_strategy(
    tool_id: HarnessDispatchStrategy,
) -> ExperimentalOptimizerStrategy:
    if tool_id == "cma_es":
        raise ValueError("cma_es is not an ExperimentalOptimizerStrategy")
    return tool_id


__all__ = [
    "HARNESS_DECISION_TRACE_SCHEMA_VERSION",
    "HARNESS_FALLBACK_TOOL",
    "HARNESS_PROMPT_TEMPLATE_VERSION",
    "HARNESS_TOOL_REGISTRY",
    "HarnessBudgetPlanDecision",
    "HarnessDecision",
    "HarnessDecisionTraceVerification",
    "HarnessDispatchStrategy",
    "HarnessPlanRevisionDecision",
    "as_experimental_strategy",
    "build_decision_messages",
    "decision_schema_for_snapshot",
    "is_experimental_harness_tool",
    "select_optimizer_budget_plan",
    "select_optimizer_tool",
    "select_plan_revision",
    "validate_harness_decision_response",
    "verify_harness_decision_trace",
]
