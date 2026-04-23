"""GPT-backed candidate parameter proposer (Phase 8).

Given the job configuration, acceptance criteria, baseline parameters, and a
summary of prior candidate attempts, this module calls OpenAI's
``chat.completions`` API with a ``response_format={"type": "json_schema"}``
structured-output constraint and returns a list of validated
:class:`LlmProposal` objects that the job manager can persist as
:class:`CandidateParameterSet` rows and dispatch as trials.

The OpenAI API key is fetched from the job's :class:`JobSecret` row and
never returned to callers or included in any persisted payload.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app import models
from app import secrets as job_secrets
from app.orchestration import constants
from app.orchestration.acceptance import AcceptanceCriteria
from app.orchestration.events import record_event

logger = logging.getLogger("drone_dream.orchestration.llm")

_PARAMETER_KEYS: tuple[str, ...] = tuple(constants.PARAMETER_SAFE_RANGES.keys())
_DEFAULT_MODEL = "gpt-4.1"
# Phase 8 product alignment: the GPT loop is "one tune → one simulation
# round". The proposer is now expected to emit exactly one candidate per
# generation so the acceptance evaluator has a single, clean unit to judge.
# A single proposal can still be evaluated over multiple seeds/scenarios
# via ``trials_per_candidate``.
_MAX_PROPOSALS = 1
_MIN_PROPOSALS = 1
# Maximum number of per-trial "feedback" rows we inline into the GPT prompt
# for the most recent generation so the model can reason about which
# scenarios caused failure without receiving unbounded telemetry.
_MAX_TRIAL_FEEDBACK_ROWS = 8
_MAX_FEEDBACK_TEXT = 400


# --- Public data classes -------------------------------------------------


@dataclass(frozen=True)
class LlmProposal:
    """One validated, safe-ranged candidate proposal returned to the caller."""

    label: str
    rationale: str
    parameters: dict[str, float]


@dataclass
class LlmProposerResult:
    """Outcome of one proposer call."""

    proposals: list[LlmProposal] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    model: str | None = None


# --- OpenAI client abstraction ------------------------------------------


class OpenAIClientLike(Protocol):
    """Narrow protocol satisfied by the real ``openai.OpenAI`` client and tests."""

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        ...


class _DefaultOpenAIClient:
    """Adapter over the official ``openai`` Python SDK.

    Uses ``client.chat.completions.create`` with
    ``response_format={"type": "json_schema", ...}`` to get structured JSON
    output that matches :data:`_STRICT_SCHEMA`. If a future switch to the
    newer Responses API is desired, only this class needs to change.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover — install instructs user
            raise RuntimeError(
                "The 'openai' package is not installed; install it to use "
                "optimizer_strategy=gpt (pip install openai)."
            ) from exc

        client = OpenAI(api_key=self._api_key)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "drone_dream_candidate_proposals",
                "schema": _PROPOSAL_SCHEMA,
                "strict": True,
            },
        }
        chat = client.chat.completions.create(  # type: ignore[call-overload]
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_format,
        )
        content = chat.choices[0].message.content or "{}"
        try:
            return json.loads(content)  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI returned non-JSON content: {exc}") from exc


# --- JSON schema used for structured outputs ---------------------------

_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["proposals"],
    "properties": {
        "proposals": {
            "type": "array",
            "minItems": _MIN_PROPOSALS,
            "maxItems": _MAX_PROPOSALS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "rationale", "parameters"],
                "properties": {
                    "label": {"type": "string", "minLength": 1, "maxLength": 80},
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 400},
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(_PARAMETER_KEYS),
                        "properties": {key: {"type": "number"} for key in _PARAMETER_KEYS},
                    },
                },
            },
        }
    },
}


# --- Helpers -----------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _sanitize(parameters: dict[str, Any]) -> dict[str, float] | None:
    cleaned: dict[str, float] = {}
    for key in _PARAMETER_KEYS:
        raw = parameters.get(key)
        if raw is None:
            return None
        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            return None
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        lo, hi = constants.PARAMETER_SAFE_RANGES[key]
        cleaned[key] = round(_clamp(numeric, lo, hi), 6)
    return cleaned


def _load_api_key(db: Session, job: models.Job) -> str | None:
    secret = next(
        (
            s
            for s in sorted(job.secrets, key=lambda s: s.created_at, reverse=True)
            if s.provider == "openai" and s.deleted_at is None and s.encrypted_api_key
        ),
        None,
    )
    if secret is None:
        return None
    try:
        return job_secrets.decrypt_secret(secret.encrypted_api_key)
    except job_secrets.SecretStoreError:
        logger.exception("failed to decrypt job secret for job %s", job.id)
        return None


def _trim(text: str | None, limit: int = _MAX_FEEDBACK_TEXT) -> str | None:
    if text is None:
        return None
    clean = text.strip()
    if not clean:
        return None
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _trial_feedback_row(trial: models.Trial) -> dict[str, Any]:
    """Compact per-trial feedback block for the proposer prompt.

    We deliberately do NOT include raw telemetry blobs — only the signals the
    model needs to understand which scenarios caused a failure: scenario,
    pass_flag, key error metrics, failure code + reason, and a bounded log
    excerpt.
    """

    metric = trial.metric
    return {
        "trial_id": trial.id,
        "scenario_type": trial.scenario_type,
        "status": trial.status,
        "pass_flag": (metric.pass_flag if metric is not None else None),
        "rmse": (metric.rmse if metric is not None else None),
        "max_error": (metric.max_error if metric is not None else None),
        "completion_time": (metric.completion_time if metric is not None else None),
        "final_error": (metric.final_error if metric is not None else None),
        "failure_code": trial.failure_code,
        "failure_reason": _trim(trial.failure_reason),
        "log_excerpt": _trim(trial.log_excerpt),
    }


def _candidate_feedback_block(
    candidate: models.CandidateParameterSet,
    *,
    include_trial_rows: bool,
) -> dict[str, Any]:
    """Structured per-candidate feedback exposed to the proposer.

    Includes aggregate pass/completion rates, the raw parameter set, and —
    for the most recent generation only — the compact per-trial rows so the
    model can reason about which scenario(s) caused failure.
    """

    trial_count = max(0, candidate.trial_count or 0)
    completed = candidate.completed_trial_count or 0
    metrics = candidate.aggregated_metric_json or {}
    passing = int(metrics.get("passing_trial_count") or 0)
    denom = trial_count or 1
    block: dict[str, Any] = {
        "candidate_id": candidate.id,
        "label": candidate.label,
        "source_type": candidate.source_type,
        "generation_index": candidate.generation_index,
        "is_baseline": bool(candidate.is_baseline),
        "parameters": dict(candidate.parameter_json or {}),
        "aggregated_metrics": candidate.aggregated_metric_json,
        "aggregated_score": candidate.aggregated_score,
        "trial_count": trial_count,
        "completed_trial_count": completed,
        "failed_trial_count": candidate.failed_trial_count,
        "passing_trial_count": passing,
        "pass_rate": round(passing / denom, 4) if trial_count else 0.0,
        "completion_rate": round(completed / denom, 4) if trial_count else 0.0,
    }
    if include_trial_rows:
        trials = sorted(
            list(candidate.trials),
            key=lambda t: (t.scenario_type or "", t.seed or 0),
        )[:_MAX_TRIAL_FEEDBACK_ROWS]
        block["trials"] = [_trial_feedback_row(t) for t in trials]
    return block


def _build_prompt(
    job: models.Job,
    criteria: AcceptanceCriteria,
    candidates: list[models.CandidateParameterSet],
) -> tuple[str, str]:
    system = (
        "You are an expert drone-control tuning assistant. Your job is to "
        "propose ONE next candidate PID + velocity/acceptance limit + "
        "disturbance rejection parameter set that is likely to improve "
        "simulator metrics under the given scenarios. You must return only "
        "structured JSON conforming to the provided schema — no free-form "
        "text. You will see per-trial feedback for the latest generation "
        "(scenario, pass_flag, errors, failure codes). Use it to diagnose "
        "which scenario(s) failed and adjust accordingly."
    )
    safe_ranges = {key: list(value) for key, value in constants.PARAMETER_SAFE_RANGES.items()}

    sorted_candidates = sorted(
        candidates,
        key=lambda c: (c.generation_index, 0 if c.is_baseline else 1),
    )
    latest_generation = (
        max((c.generation_index for c in sorted_candidates), default=0)
    )
    baseline_block: dict[str, Any] | None = None
    latest_blocks: list[dict[str, Any]] = []
    history_blocks: list[dict[str, Any]] = []
    for cand in sorted_candidates:
        include_trials = cand.is_baseline or cand.generation_index == latest_generation
        block = _candidate_feedback_block(cand, include_trial_rows=include_trials)
        if cand.is_baseline:
            baseline_block = block
        elif cand.generation_index == latest_generation:
            latest_blocks.append(block)
        else:
            # Previous generations: keep aggregates only, drop per-trial rows
            history_blocks.append(
                _candidate_feedback_block(cand, include_trial_rows=False)
            )

    user_payload = {
        "objective_profile": job.objective_profile,
        "simulator_backend": job.simulator_backend_requested,
        "track_type": job.track_type,
        "altitude_m": job.altitude_m,
        "wind": {
            "north": job.wind_north,
            "east": job.wind_east,
            "south": job.wind_south,
            "west": job.wind_west,
        },
        "sensor_noise_level": job.sensor_noise_level,
        "acceptance_criteria": {
            "target_rmse": criteria.target_rmse,
            "target_max_error": criteria.target_max_error,
            "min_pass_rate": criteria.min_pass_rate,
        },
        "parameter_safe_ranges": safe_ranges,
        "baseline_parameters": dict(constants.BASELINE_PARAMETERS),
        "baseline_feedback": baseline_block,
        "latest_generation_feedback": latest_blocks,
        "previous_generation_history": history_blocks,
        "current_generation": job.current_generation,
        "max_iterations": job.max_iterations,
        "instructions": (
            "Propose exactly ONE next candidate parameter set. Every numeric "
            "value must lie strictly inside the safe range; include all "
            "required keys and no others. Analyze latest_generation_feedback "
            "and baseline_feedback to identify which scenario(s) failed and "
            "adjust your parameters accordingly. Be explicit about the "
            "rationale in 1–3 sentences."
        ),
    }
    return system, json.dumps(user_payload, sort_keys=True, indent=2, default=str)


# --- Public API --------------------------------------------------------


def propose_candidates(
    db: Session,
    job: models.Job,
    criteria: AcceptanceCriteria,
    *,
    client: OpenAIClientLike | None = None,
    model: str | None = None,
) -> LlmProposerResult:
    """Call the proposer and return at least one validated proposal.

    Records ``llm_proposal_*`` :class:`JobEvent` rows. On failure the returned
    :class:`LlmProposerResult` has ``error`` set and ``proposals`` empty.
    """

    chosen_model = (
        model
        or job.openai_model
        or job_secrets_env_model()
        or _DEFAULT_MODEL
    )

    effective_client: OpenAIClientLike | None = client
    if effective_client is None:
        api_key = _load_api_key(db, job)
        if api_key is None:
            record_event(
                db,
                job.id,
                "llm_proposal_failed",
                {"reason": "missing_api_key", "model": chosen_model},
            )
            return LlmProposerResult(error="missing_api_key", model=chosen_model)
        effective_client = _DefaultOpenAIClient(api_key)

    record_event(
        db,
        job.id,
        "llm_proposal_started",
        {"generation": job.current_generation + 1, "model": chosen_model},
    )

    try:
        system, user = _build_prompt(job, criteria, list(job.candidates))
        raw = effective_client.generate(model=chosen_model, system=system, user=user)
    except Exception as exc:  # OpenAI client failure, network, etc.
        logger.exception("LLM proposer call failed for job %s", job.id)
        record_event(
            db,
            job.id,
            "llm_proposal_failed",
            {"reason": "client_error", "message": str(exc)[:500], "model": chosen_model},
        )
        return LlmProposerResult(error=str(exc), model=chosen_model)

    proposals = _validate_response(raw)
    if not proposals:
        record_event(
            db,
            job.id,
            "llm_proposal_failed",
            {"reason": "invalid_response", "model": chosen_model},
        )
        return LlmProposerResult(error="invalid_response", raw_response=raw, model=chosen_model)

    record_event(
        db,
        job.id,
        "llm_proposal_completed",
        {
            "model": chosen_model,
            "proposal_count": len(proposals),
            "labels": [p.label for p in proposals],
        },
    )
    return LlmProposerResult(proposals=proposals, raw_response=raw, model=chosen_model)


def _validate_response(raw: dict[str, Any] | None) -> list[LlmProposal]:
    if not isinstance(raw, dict):
        return []
    proposals_raw = raw.get("proposals")
    if not isinstance(proposals_raw, list) or not proposals_raw:
        return []
    out: list[LlmProposal] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for item in proposals_raw[:_MAX_PROPOSALS]:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        rationale = item.get("rationale")
        parameters = item.get("parameters")
        if not isinstance(label, str) or not isinstance(rationale, str):
            continue
        if not isinstance(parameters, dict):
            continue
        cleaned = _sanitize(parameters)
        if cleaned is None:
            continue
        fingerprint = tuple(sorted(cleaned.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(
            LlmProposal(
                label=label.strip()[:80] or "llm_candidate",
                rationale=rationale.strip()[:400],
                parameters=cleaned,
            )
        )
    return out


def job_secrets_env_model() -> str | None:
    import os

    value = os.environ.get("OPENAI_MODEL")
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "LlmProposal",
    "LlmProposerResult",
    "OpenAIClientLike",
    "propose_candidates",
]
