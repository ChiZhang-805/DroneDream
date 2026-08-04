"""Bounded T3 diagnosis and T4 safety review over existing proposals only.

These optional provider turns are deterministic-policy gated.  They may narrow
or abandon an existing proposal set, but they cannot create parameters, tools,
or budget.  Final holdout outcomes are deliberately absent from every prompt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.orchestration.cognitive_budget import (
    CognitiveTriggerEvaluation,
    CognitiveTurnAttempt,
    CognitiveTurnBlocked,
    CognitiveTurnPending,
    begin_cognitive_turn,
    finish_cognitive_turn,
    recover_existing_cognitive_turn,
    sha256_json,
    sha256_text,
)
from app.orchestration.harness_budget_planner import HarnessProposalSummary
from app.orchestration.llm_parameter_proposer import (
    OpenAIClientLike,
    OpenAIJsonClient,
    bind_provider_request_accounting,
    load_job_api_key,
)
from app.orchestration.provider_request_accounting import (
    provider_request_outcome_pending,
)

COGNITIVE_REVIEW_PROMPT_VERSION = "adaptive-cognitive-review-v1"
_DEFAULT_MODEL = "gpt-4.1"


@dataclass(frozen=True)
class AdaptiveCognitiveReviewResult:
    selected_proposal_refs: tuple[str, ...]
    diagnosis_decision: str | None = None
    critic_decision: str | None = None
    fail_closed_reason: str | None = None

    @property
    def abandoned(self) -> bool:
        return not self.selected_proposal_refs


def _closed_schema(
    *,
    role: Literal["diagnosis", "critic"],
    allowed_refs: Sequence[str],
    trigger_reasons: Sequence[str],
) -> dict[str, Any]:
    if role == "diagnosis":
        decision_values = ["keep", "replace", "abandon"]
        selection_field = "selected_proposal_refs"
        reason_field = "diagnosis_codes"
    else:
        decision_values = ["approve", "restrict", "veto"]
        selection_field = "approved_proposal_refs"
        reason_field = "risk_codes"
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "decision", selection_field, reason_field],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": decision_values},
            selection_field: {
                "type": "array",
                "items": {"type": "string", "enum": list(allowed_refs)},
                "uniqueItems": True,
                "maxItems": len(allowed_refs),
            },
            reason_field: {
                "type": "array",
                "items": {"type": "string", "enum": list(trigger_reasons)},
                "uniqueItems": True,
                "minItems": 1,
                "maxItems": len(trigger_reasons),
            },
        },
    }


def _review_messages(
    *,
    role: Literal["diagnosis", "critic"],
    trigger: CognitiveTriggerEvaluation,
    current_refs: Sequence[str],
    proposal_details: Mapping[str, Mapping[str, object]],
    hard_bounds: Sequence[Mapping[str, object]],
) -> tuple[str, str, dict[str, Any]]:
    permissions = (
        "T3 may keep, replace with existing proposal refs, or abandon. "
        "It cannot create parameters, tools, or budget."
        if role == "diagnosis"
        else "T4 may approve, choose a strict subset, or veto. "
        "It cannot add a proposal or expand any value or budget."
    )
    system = (
        "You are a bounded DroneDream generation-boundary reviewer. "
        f"{permissions} PX4 remains the high-rate flight controller. "
        "Final holdout outcomes, credentials, raw chat, and hidden prompts are unavailable. "
        "Return only JSON matching the supplied closed schema."
    )
    payload = {
        "schema_id": "dronedream.adaptive-cognitive-review-input/v1",
        "prompt_version": COGNITIVE_REVIEW_PROMPT_VERSION,
        "role": role,
        "trigger_policy_version": trigger.policy_version,
        "trigger_reasons": list(
            trigger.diagnosis_reasons if role == "diagnosis" else trigger.critic_reasons
        ),
        "trigger_evidence": trigger.evidence,
        "current_proposal_refs": list(current_refs),
        "proposal_details": [dict(proposal_details[ref]) for ref in sorted(proposal_details)],
        "hard_bounds": [dict(item) for item in hard_bounds],
        "holdout_outcomes_visible": False,
    }
    from app.orchestration.cognitive_budget import canonical_json

    return system, canonical_json(payload), payload


def _validate_diagnosis(
    raw: object,
    *,
    current_refs: tuple[str, ...],
    available_refs: frozenset[str],
    trigger_reasons: frozenset[str],
) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "decision",
        "selected_proposal_refs",
        "diagnosis_codes",
    }:
        return None
    if raw.get("schema_version") != "1.0":
        return None
    decision = raw.get("decision")
    selected_raw = raw.get("selected_proposal_refs")
    codes_raw = raw.get("diagnosis_codes")
    if not isinstance(selected_raw, list) or not isinstance(codes_raw, list):
        return None
    if any(not isinstance(item, str) for item in selected_raw + codes_raw):
        return None
    selected = tuple(selected_raw)
    if len(set(selected)) != len(selected) or not set(selected).issubset(available_refs):
        return None
    if (
        not codes_raw
        or len(set(codes_raw)) != len(codes_raw)
        or not set(codes_raw).issubset(trigger_reasons)
    ):
        return None
    if decision == "keep" and selected == current_refs:
        return decision, selected
    if decision == "replace" and selected and selected != current_refs:
        return decision, selected
    if decision == "abandon" and not selected:
        return decision, selected
    return None


def _validate_critic(
    raw: object,
    *,
    current_refs: tuple[str, ...],
    trigger_reasons: frozenset[str],
) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "decision",
        "approved_proposal_refs",
        "risk_codes",
    }:
        return None
    if raw.get("schema_version") != "1.0":
        return None
    selected_raw = raw.get("approved_proposal_refs")
    codes_raw = raw.get("risk_codes")
    if not isinstance(selected_raw, list) or not isinstance(codes_raw, list):
        return None
    if any(not isinstance(item, str) for item in selected_raw + codes_raw):
        return None
    selected = tuple(selected_raw)
    current_set = frozenset(current_refs)
    if len(set(selected)) != len(selected) or not set(selected).issubset(current_set):
        return None
    if (
        not codes_raw
        or len(set(codes_raw)) != len(codes_raw)
        or not set(codes_raw).issubset(trigger_reasons)
    ):
        return None
    decision = raw.get("decision")
    if decision == "approve" and selected == current_refs:
        return decision, selected
    if decision == "restrict" and selected and set(selected) < current_set:
        return decision, selected
    if decision == "veto" and not selected:
        return decision, selected
    return None


def _run_review_turn(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    role: Literal["diagnosis", "critic"],
    trigger_reasons: tuple[str, ...],
    available_refs: tuple[str, ...],
    current_refs: tuple[str, ...],
    proposal_details: Mapping[str, Mapping[str, object]],
    hard_bounds: Sequence[Mapping[str, object]],
    trigger: CognitiveTriggerEvaluation,
    client: OpenAIClientLike | None,
) -> tuple[Mapping[str, Any] | None, CognitiveTurnAttempt | None, str | None]:
    schema = _closed_schema(
        role=role,
        allowed_refs=available_refs if role == "diagnosis" else current_refs,
        trigger_reasons=trigger_reasons,
    )
    system, user, evidence = _review_messages(
        role=role,
        trigger=trigger,
        current_refs=current_refs,
        proposal_details=proposal_details,
        hard_bounds=hard_bounds,
    )
    settings = get_settings()
    if len(user.encode("utf-8")) > settings.llm_max_prompt_bytes:
        return None, None, f"{role}_prompt_too_large"
    model = job.openai_model or _DEFAULT_MODEL
    turn_index = 3 if role == "diagnosis" else 4
    recovered_turn = recover_existing_cognitive_turn(
        db,
        job,
        generation_index=generation_index,
        turn_index=turn_index,
    )
    if recovered_turn == "pending":
        raise CognitiveTurnPending()
    if recovered_turn == "consumed":
        return None, None, f"{role}_turn_consumed_without_replayable_result"
    effective_client = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            return None, None, f"{role}_missing_api_key"
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=schema,
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=job.provider_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )
    attempt = begin_cognitive_turn(
        db,
        job,
        generation_index=generation_index,
        turn_index=turn_index,
        turn_role=role,
        trigger_reasons=trigger_reasons,
        model_snapshot=model,
        prompt_sha256=sha256_text(f"{system}\n{user}"),
        evidence_sha256=sha256_json(evidence),
        schema_sha256=sha256_json(schema),
        tool_outputs_sha256=sha256_json(
            [dict(proposal_details[ref]) for ref in sorted(proposal_details)]
        ),
    )
    effective_client = bind_provider_request_accounting(
        effective_client,
        db,
        job,
        cognitive_turn_receipt_id=attempt.receipt_id,
    )
    try:
        raw = effective_client.generate(model=model, system=system, user=user)
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
            error_code=f"{role}_provider_failed",
        )
        return None, None, f"{role}_provider_failed"
    if not isinstance(raw, Mapping):
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            error_code=f"{role}_invalid_schema",
        )
        return None, None, f"{role}_invalid_schema"
    return raw, attempt, None


def run_adaptive_cognitive_review(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    trigger: CognitiveTriggerEvaluation,
    proposals: Sequence[HarnessProposalSummary],
    selected_proposal_refs: Sequence[str],
    proposal_details: Mapping[str, Mapping[str, object]],
    hard_bounds: Sequence[Mapping[str, object]],
    client: OpenAIClientLike | None = None,
) -> AdaptiveCognitiveReviewResult:
    """Apply deterministic-gated T3/T4 reviews without expanding proposals."""

    available_refs = tuple(item.proposal_ref for item in proposals)
    current_refs = tuple(selected_proposal_refs)
    if not current_refs:
        return AdaptiveCognitiveReviewResult(selected_proposal_refs=())
    if not set(current_refs).issubset(available_refs):
        raise CognitiveTurnBlocked(
            "unknown_proposal_reference",
            "Revision selected a proposal outside the current generation.",
        )

    diagnosis_decision: str | None = None
    if trigger.diagnosis_required:
        raw, attempt, error = _run_review_turn(
            db,
            job,
            generation_index=generation_index,
            role="diagnosis",
            trigger_reasons=trigger.diagnosis_reasons,
            available_refs=available_refs,
            current_refs=current_refs,
            proposal_details=proposal_details,
            hard_bounds=hard_bounds,
            trigger=trigger,
            client=client,
        )
        if raw is None:
            return AdaptiveCognitiveReviewResult(
                selected_proposal_refs=(),
                fail_closed_reason=error,
            )
        validated = _validate_diagnosis(
            raw,
            current_refs=current_refs,
            available_refs=frozenset(available_refs),
            trigger_reasons=frozenset(trigger.diagnosis_reasons),
        )
        if attempt is None:
            raise CognitiveTurnBlocked("turn_receipt_missing", "Diagnosis receipt is missing.")
        if validated is None:
            finish_cognitive_turn(
                db,
                job,
                attempt,
                status="invalid_schema",
                response=raw,
                error_code="diagnosis_invalid_schema",
            )
            return AdaptiveCognitiveReviewResult(
                selected_proposal_refs=(),
                fail_closed_reason="diagnosis_invalid_schema",
            )
        if (
            finish_cognitive_turn(db, job, attempt, status="succeeded", response=raw)
            == "source_drift"
        ):
            raise CognitiveTurnBlocked("source_drift", "Source changed during diagnosis.")
        diagnosis_decision, current_refs = validated
        if not current_refs:
            return AdaptiveCognitiveReviewResult(
                selected_proposal_refs=(),
                diagnosis_decision=diagnosis_decision,
            )

    critic_decision: str | None = None
    if trigger.critic_required:
        raw, attempt, error = _run_review_turn(
            db,
            job,
            generation_index=generation_index,
            role="critic",
            trigger_reasons=trigger.critic_reasons,
            available_refs=available_refs,
            current_refs=current_refs,
            proposal_details=proposal_details,
            hard_bounds=hard_bounds,
            trigger=trigger,
            client=client,
        )
        if raw is None:
            return AdaptiveCognitiveReviewResult(
                selected_proposal_refs=(),
                diagnosis_decision=diagnosis_decision,
                fail_closed_reason=error,
            )
        validated = _validate_critic(
            raw,
            current_refs=current_refs,
            trigger_reasons=frozenset(trigger.critic_reasons),
        )
        if attempt is None:
            raise CognitiveTurnBlocked("turn_receipt_missing", "Critic receipt is missing.")
        if validated is None:
            finish_cognitive_turn(
                db,
                job,
                attempt,
                status="invalid_schema",
                response=raw,
                error_code="critic_invalid_schema",
            )
            return AdaptiveCognitiveReviewResult(
                selected_proposal_refs=(),
                diagnosis_decision=diagnosis_decision,
                fail_closed_reason="critic_invalid_schema",
            )
        if (
            finish_cognitive_turn(db, job, attempt, status="succeeded", response=raw)
            == "source_drift"
        ):
            raise CognitiveTurnBlocked("source_drift", "Source changed during critic review.")
        critic_decision, current_refs = validated

    return AdaptiveCognitiveReviewResult(
        selected_proposal_refs=current_refs,
        diagnosis_decision=diagnosis_decision,
        critic_decision=critic_decision,
    )


__all__ = [
    "COGNITIVE_REVIEW_PROMPT_VERSION",
    "AdaptiveCognitiveReviewResult",
    "run_adaptive_cognitive_review",
]
