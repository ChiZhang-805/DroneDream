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
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.optimization.experimental_types import ExperimentalOptimizerStrategy
from app.orchestration.events import record_event
from app.orchestration.llm_parameter_proposer import (
    OpenAIClientLike,
    OpenAIJsonClient,
    load_job_api_key,
)
from app.parameters import get_parameter

logger = logging.getLogger("drone_dream.orchestration.decision_harness")

HarnessToolId = Literal[
    "cma_es",
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
]
HarnessDispatchStrategy = HarnessToolId
HarnessDecisionSource = Literal["model", "deterministic_fallback"]

_DEFAULT_MODEL = "gpt-4.1"
_FALLBACK_TOOL: HarnessToolId = "optimizer_portfolio"
_MAX_EVIDENCE_CANDIDATES = 8
_MAX_RATIONALE_LENGTH = 400
_ALLOWED_SOURCE_TYPES = frozenset({"baseline", "optimizer", "llm_optimizer"})
_ALLOWED_OBJECTIVE_PROFILES = frozenset({"stable", "fast", "smooth", "robust", "custom"})
_ALLOWED_TRACK_TYPES = frozenset({"circle", "u_turn", "lemniscate", "custom"})

HARNESS_TOOL_REGISTRY: dict[HarnessToolId, str] = {
    "cma_es": "Single-candidate dependency-free evolutionary search.",
    "constrained_mobo": "Constraint-aware multi-objective Bayesian search.",
    "multi_fidelity_mobo": "Bayesian search that may screen at reduced fidelity.",
    "turbo": "Trust-region Bayesian search around promising local evidence.",
    "saasbo": "Sparse-axis Bayesian search for higher-dimensional spaces.",
    "surrogate_cma_es": "Evolutionary search assisted by a fitted surrogate.",
    "bipop_cma_es": "Restarting evolutionary search with alternating populations.",
    "optimizer_portfolio": "Deterministic portfolio that allocates budget across engines.",
}

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


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_json(value: object, *, depth: int = 0) -> object | None:
    """Return bounded numeric/boolean JSON suitable for an evidence prompt."""

    if depth > 8:
        return None
    if value is None or isinstance(value, bool):
        return value
    numeric = _finite(value)
    if numeric is not None:
        return numeric
    if isinstance(value, list):
        return [_safe_json(item, depth=depth + 1) for item in value[:64]]
    # Aggregate values in the model contract are scalar or numeric arrays.
    # Reject mappings rather than forwarding attacker-controlled JSON keys.
    if isinstance(value, dict):
        return None
    return None


def _candidate_evidence(candidate: models.CandidateParameterSet) -> dict[str, Any]:
    aggregate = (
        candidate.aggregated_metric_json
        if isinstance(candidate.aggregated_metric_json, dict)
        else {}
    )
    allowed_metrics = {
        key: _safe_json(aggregate.get(key))
        for key in (
            "rmse",
            "max_error",
            "max_error_worst",
            "completion_time",
            "pass_rate",
            "aggregated_score",
            "feasible",
            "total_constraint_violation",
        )
        if key in aggregate
    }
    return {
        "generation": candidate.generation_index,
        "source_type": (
            candidate.source_type
            if candidate.source_type in _ALLOWED_SOURCE_TYPES
            else "unknown"
        ),
        "is_baseline": candidate.is_baseline,
        "aggregated_score": _finite(candidate.aggregated_score),
        "metrics": allowed_metrics,
        "trial_count": max(0, int(candidate.trial_count or 0)),
        "completed_trial_count": max(0, int(candidate.completed_trial_count or 0)),
        "failed_trial_count": max(0, int(candidate.failed_trial_count or 0)),
    }


def _registered_parameter_names(job: models.Job) -> list[str]:
    parameter_space = (
        job.parameter_space_json
        if isinstance(job.parameter_space_json, list)
        else []
    )
    vehicle_profile = (
        job.vehicle_profile_json
        if isinstance(job.vehicle_profile_json, dict)
        else {}
    )
    context = {
        key: value
        for key, value in {
            "px4_version": vehicle_profile.get("px4_version"),
            "vehicle_type": vehicle_profile.get("vehicle_type"),
            "airframe": vehicle_profile.get("airframe"),
        }.items()
        if isinstance(value, str)
    }
    result: list[str] = []
    for item in parameter_space:
        if (
            not isinstance(item, dict)
            or item.get("enabled", True) is not True
            or item.get("locked", False) is True
            or not isinstance(item.get("name"), str)
        ):
            continue
        try:
            parameter = get_parameter(item["name"], **context)
        except ValueError:
            parameter = None
        if parameter is not None:
            result.append(parameter.name)
    return result


def _build_evidence(job: models.Job) -> tuple[dict[str, Any], bool]:
    candidates = sorted(
        list(job.candidates),
        key=lambda item: (
            item.is_baseline,
            item.generation_index,
            item.created_at,
            item.id,
        ),
        reverse=True,
    )
    selected: dict[str, models.CandidateParameterSet] = {}
    for candidate in candidates:
        if candidate.is_baseline:
            selected[candidate.id] = candidate
    def score_order(item: models.CandidateParameterSet) -> tuple[bool, float, int]:
        score = _finite(item.aggregated_score)
        return (
            score is None,
            float("inf") if score is None else score,
            item.generation_index,
        )

    for candidate in sorted(candidates, key=score_order):
        if len(selected) >= _MAX_EVIDENCE_CANDIDATES:
            break
        selected[candidate.id] = candidate

    compact_candidates = [_candidate_evidence(item) for item in selected.values()]
    has_scored_evidence = any(
        item["aggregated_score"] is not None or bool(item["metrics"])
        for item in compact_candidates
    )
    enabled_parameter_names = _registered_parameter_names(job)
    evidence: dict[str, Any] = {
        "job": {
            "current_generation": job.current_generation,
            "max_iterations": job.max_iterations,
            "used_trials": job.progress_total_trials,
            "max_total_trials": job.max_total_trials,
            "objective_profile": (
                job.objective_profile
                if job.objective_profile in _ALLOWED_OBJECTIVE_PROFILES
                else "unknown"
            ),
            "track_type": (
                job.track_type if job.track_type in _ALLOWED_TRACK_TYPES else "unknown"
            ),
            "parameter_count": len(enabled_parameter_names),
            "parameter_names": enabled_parameter_names[:64],
        },
        "candidates": compact_candidates,
        "candidate_history_total": len(candidates),
        "candidate_history_included": len(compact_candidates),
    }
    return evidence, has_scored_evidence


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
    if (
        not isinstance(rationale, str)
        or not 1 <= len(rationale.strip()) <= _MAX_RATIONALE_LENGTH
    ):
        return None
    return tool_id, rationale.strip()


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

    evidence, has_scored_evidence = _build_evidence(job)
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

    system = (
        "You are DroneDream's bounded optimization planner. Select exactly one "
        "optimizer tool from the supplied closed registry for the next generation. "
        "Use only the supplied evidence. You cannot run tools, change constraints, "
        "modify budgets, access credentials, or invent additional tool IDs. Return "
        "only JSON that conforms to the required schema."
    )
    user_payload = {
        "tool_registry": HARNESS_TOOL_REGISTRY,
        "evidence": evidence,
        "instructions": (
            "Choose one tool for the next bounded generation. Prefer verified "
            "progress and budget efficiency; explain the evidence-based choice "
            "briefly in rationale."
        ),
    }
    user = _canonical_json(user_payload)
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
        },
    )
    return HarnessDecision(
        tool_id=tool_id,
        rationale=rationale,
        source="model",
        model=chosen_model,
        evidence_sha256=evidence_sha256,
        prompt_sha256=prompt_sha256,
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
    "is_experimental_harness_tool",
    "select_optimizer_tool",
]
