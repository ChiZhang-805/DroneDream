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
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.optimization.experimental_types import ExperimentalOptimizerStrategy
from app.orchestration.events import record_event
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_REGISTRY,
    HARNESS_TOOL_REGISTRY_VERSION,
    MAX_DECISION_MEMORY_ITEMS,
    HarnessEvidenceSnapshot,
    HarnessToolId,
    build_harness_evidence,
    provider_tool_manifest,
)
from app.orchestration.llm_parameter_proposer import (
    OpenAIClientLike,
    OpenAIJsonClient,
    load_job_api_key,
)

logger = logging.getLogger("drone_dream.orchestration.decision_harness")

HarnessDispatchStrategy = HarnessToolId
HarnessDecisionSource = Literal["model", "deterministic_fallback"]

_DEFAULT_MODEL = "gpt-4.1"
_FALLBACK_TOOL: HarnessToolId = "optimizer_portfolio"
_MAX_RATIONALE_LENGTH = 400

_DECISION_SCHEMA: dict[str, Any] = {
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
                    "enum": list(HARNESS_TOOL_REGISTRY),
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


@dataclass(frozen=True)
class HarnessDecision:
    """One locally validated optimizer-tool decision."""

    tool_id: HarnessDispatchStrategy
    rationale: str
    source: HarnessDecisionSource
    model: str | None
    evidence_sha256: str
    prompt_sha256: str | None = None
    fallback_reason: str | None = None
    evidence_schema_version: str = HARNESS_EVIDENCE_SCHEMA_VERSION
    tool_registry_version: str = HARNESS_TOOL_REGISTRY_VERSION


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


def _validate_response(raw: object) -> tuple[HarnessToolId, str] | None:
    if not isinstance(raw, dict) or set(raw) != {"decision"}:
        return None
    decision = raw.get("decision")
    if not isinstance(decision, dict) or set(decision) != {"tool_id", "rationale"}:
        return None
    tool_id = decision.get("tool_id")
    rationale = decision.get("rationale")
    if tool_id not in HARNESS_TOOL_REGISTRY:
        return None
    if not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= _MAX_RATIONALE_LENGTH:
        return None
    return tool_id, rationale.strip()


def build_decision_messages(
    evidence_snapshot: HarnessEvidenceSnapshot,
) -> tuple[str, str]:
    """Build the exact production model messages from a closed snapshot.

    Keeping this function pure lets the routing evaluation suite exercise the
    same prompt and tool manifest used by live orchestration.
    """

    system = (
        "You are DroneDream's bounded optimization planner. Select exactly one "
        "optimizer tool from the supplied closed, versioned registry for the next "
        "generation. Compare remaining budget, parameter dimension, scenario cost, "
        "feasibility, failure rate, improvement trend, stagnation, and prior tool "
        "outcomes. Use only the supplied evidence. You cannot run tools, change "
        "constraints, modify budgets, access credentials, or invent additional "
        "tool IDs. Return only JSON that conforms to the required schema."
    )
    user_payload = {
        "tool_manifest": provider_tool_manifest(),
        "evidence": evidence_snapshot.model_dump(mode="json", exclude_none=True),
        "instructions": (
            "Choose one tool for the next bounded generation. Prefer measured "
            "progress and budget efficiency, use the deterministic portfolio when "
            "specialization is not supported by the evidence, and explain the "
            "numeric evidence behind the choice briefly in rationale."
        ),
    }
    return system, _canonical_json(user_payload)


def _fallback(
    db: Session,
    job: models.Job,
    *,
    reason: str,
    evidence_sha256: str,
    model: str | None,
    prompt_sha256: str | None = None,
    error_type: str | None = None,
) -> HarnessDecision:
    rejected_payload: dict[str, Any] = {
        "reason": reason,
        "model": model,
        "evidence_sha256": evidence_sha256,
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
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
            "reason": reason,
            "tool_id": _FALLBACK_TOOL,
            "evidence_sha256": evidence_sha256,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
    )
    return HarnessDecision(
        tool_id=_FALLBACK_TOOL,
        rationale=(
            "The model decision was unavailable or invalid, so the bounded "
            "deterministic optimizer portfolio was selected."
        ),
        source="deterministic_fallback",
        model=model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        fallback_reason=reason,
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
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

    recent_execution_events = list(
        reversed(
            list(
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
                    .limit(MAX_DECISION_MEMORY_ITEMS)
                )
            )
        )
    )
    evidence_snapshot, has_scored_evidence = build_harness_evidence(
        job,
        execution_events=recent_execution_events,
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
            reason="missing_model",
            evidence_sha256=evidence_sha256,
            model=None,
        )
    chosen_model = configured_model or _DEFAULT_MODEL
    if not has_scored_evidence:
        return _fallback(
            db,
            job,
            reason="insufficient_evidence",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )

    system, user = build_decision_messages(evidence_snapshot)
    settings = get_settings()
    if len(user.encode("utf-8")) > settings.llm_max_prompt_bytes:
        return _fallback(
            db,
            job,
            reason="prompt_too_large",
            evidence_sha256=evidence_sha256,
            model=chosen_model,
        )
    prompt_sha256 = _sha256_text(f"{system}\n{user}")
    effective_client = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            return _fallback(
                db,
                job,
                reason="missing_api_key",
                evidence_sha256=evidence_sha256,
                prompt_sha256=prompt_sha256,
                model=chosen_model,
            )
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=_DECISION_SCHEMA,
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )

    record_event(
        db,
        job.id,
        "harness_decision_started",
        {
            "generation": job.current_generation + 1,
            "model": chosen_model,
            "provider": provider,
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "allowed_tools": list(HARNESS_TOOL_REGISTRY),
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
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
            reason="client_error",
            error_type=type(exc).__name__,
            evidence_sha256=evidence_sha256,
            prompt_sha256=prompt_sha256,
            model=chosen_model,
        )

    validated = _validate_response(raw)
    if validated is None:
        return _fallback(
            db,
            job,
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
            "generation": job.current_generation + 1,
            "tool_id": tool_id,
            "rationale": rationale,
            "model": chosen_model,
            "evidence_sha256": evidence_sha256,
            "prompt_sha256": prompt_sha256,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
    )
    return HarnessDecision(
        tool_id=tool_id,
        rationale=rationale,
        source="model",
        model=chosen_model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
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
    "HARNESS_TOOL_REGISTRY",
    "HarnessDecision",
    "HarnessDispatchStrategy",
    "as_experimental_strategy",
    "build_decision_messages",
    "is_experimental_harness_tool",
    "select_optimizer_tool",
]
