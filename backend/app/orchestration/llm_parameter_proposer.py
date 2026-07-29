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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app import models, schemas
from app import secrets as job_secrets
from app.config import get_settings
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.outcome_taxonomy import (
    classify_trial_outcome,
    is_optimizer_learning_failure,
    is_optimizer_learning_outcome,
)
from app.optimization.scenarios import resolve_scenario_case
from app.orchestration import constants
from app.orchestration.acceptance import AcceptanceCriteria
from app.orchestration.events import record_event
from app.orchestration.parameter_constraints import validator_for_job
from app.orchestration.provider_feedback import compile_candidate_feedback
from app.parameters import (
    SUPPORTED_PX4_VERSIONS,
    SUPPORTED_TRIAL_METRICS,
    SUPPORTED_VEHICLE_TYPES,
    classify_airframe,
)
from app.simulator.base import (
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
)

logger = logging.getLogger("drone_dream.orchestration.llm")

_LEGACY_PARAMETER_KEYS: tuple[str, ...] = tuple(constants.PARAMETER_SAFE_RANGES.keys())
_DEFAULT_MODEL = "gpt-4.1"
_MAX_PROPOSALS = 1
_MIN_PROPOSALS = 1
_MAX_RESPONSE_NODES = 10_000
_MAX_RESPONSE_DEPTH = 16
_MAX_PROMPT_CANDIDATES = 8
LLM_PROPOSER_PROMPT_SCHEMA_VERSION = "2.3"
_PROMPT_AGGREGATE_KEYS = (
    "rmse",
    "max_error",
    "max_error_worst",
    "overshoot_count",
    "completion_time",
    "aggregated_score",
    "scalar_loss",
    "feasible",
    "total_constraint_violation",
    "optimizer_learning_failure_rate",
)
_SAFE_SCENARIO_CONFIG_KEYS = frozenset(
    {
        "wind_mps",
        "dropout_rate",
        "mass_payload_kg",
        "delay_ms",
        "intensity",
    }
)
_SAFE_OPTIMIZER_FAILURE_CODES = frozenset(
    {
        FAILURE_TIMEOUT,
        FAILURE_SIMULATION,
        FAILURE_UNSTABLE,
    }
)
_SAFE_OBJECTIVE_METRICS = frozenset(
    {
        *SUPPORTED_TRIAL_METRICS,
        "completion_rate",
        "failed_trial_rate",
        "failure_rate",
        "pass_rate",
    }
)
_INVALID_PROMPT_VALUE = object()


def _is_unsupported_response_format_error(exc: Exception) -> bool:
    """Conservatively recognize provider rejection of response_format.

    Authentication, rate limits, timeouts, and 5xx failures must never trigger
    a second billable request merely because a custom base URL is in use.
    """

    if getattr(exc, "status_code", None) != 400:
        return False
    message = str(exc).lower()
    return "response_format" in message and any(
        marker in message for marker in ("unsupported", "not supported", "unknown", "unrecognized")
    )


def _reject_nonfinite_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value!r}")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_nonnegative_int(value: Any, *, default: int = 0) -> int:
    numeric = _finite_number(value)
    if numeric is None or numeric < 0 or not numeric.is_integer():
        return default
    return int(numeric)


def _safe_prompt_value(value: Any, *, depth: int = 0) -> Any:
    """Copy bounded JSON data while dropping non-finite or exotic values."""

    if depth > 12:
        return _INVALID_PROMPT_VALUE
    if value is None or isinstance(value, str | bool):
        return value
    numeric = _finite_number(value)
    if numeric is not None:
        return value
    if isinstance(value, list):
        copied = []
        for item in value[:1_000]:
            safe_item = _safe_prompt_value(item, depth=depth + 1)
            if safe_item is not _INVALID_PROMPT_VALUE:
                copied.append(safe_item)
        return copied
    if isinstance(value, dict):
        copied_dict: dict[str, Any] = {}
        for key, item in list(value.items())[:1_000]:
            if not isinstance(key, str):
                continue
            safe_item = _safe_prompt_value(item, depth=depth + 1)
            if safe_item is not _INVALID_PROMPT_VALUE:
                copied_dict[key] = safe_item
        return copied_dict
    return _INVALID_PROMPT_VALUE


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

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]: ...


class OpenAIJsonClient:
    """Strict JSON adapter over the official ``openai`` Python SDK.

    Uses ``client.chat.completions.create`` with
    ``response_format={"type": "json_schema", ...}`` to get structured JSON
    output that matches the caller-provided schema. Both the direct GPT
    parameter proposer and the bounded tool-decision harness use this adapter;
    it has no simulator, shell, database, or filesystem authority.
    """

    def __init__(
        self,
        api_key: str,
        *,
        proposal_schema: dict[str, Any],
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        max_response_bytes: int = 1_000_000,
        temperature: float | None = None,
        top_p: float | None = None,
        seed: int | None = None,
    ) -> None:
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0.0 <= float(temperature) <= 2.0
        ):
            raise ValueError("temperature must be a finite number between 0 and 2")
        if top_p is not None and (
            isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not math.isfinite(float(top_p))
            or not 0.0 < float(top_p) <= 1.0
        ):
            raise ValueError("top_p must be a finite number greater than 0 and at most 1")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ValueError("seed must be an integer")
        self._api_key = api_key
        self._proposal_schema = proposal_schema
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._temperature = None if temperature is None else float(temperature)
        self._top_p = None if top_p is None else float(top_p)
        self._seed = seed

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover — install instructs user
            raise RuntimeError(
                "The 'openai' package is not installed; install it to use "
                "optimizer_strategy=gpt (pip install openai)."
            ) from exc

        client_kwargs: dict[str, Any] = {
            "api_key": self._api_key,
            "timeout": self._timeout_seconds,
            "max_retries": self._max_retries,
        }
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = OpenAI(**client_kwargs)
        messages: Any = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if self._base_url:
            response_format: Any = {"type": "json_object"}
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "drone_dream_candidate_proposals",
                    "schema": self._proposal_schema,
                    "strict": True,
                },
            }

        def create_completion(*, include_response_format: bool) -> Any:
            arguments: dict[str, Any] = {
                "model": model,
                "messages": messages,
                # The managed gateway uses this key to make SDK network retries
                # non-billable duplicates. A deliberate response-format
                # fallback gets a new key because it is a distinct request.
                "extra_headers": {
                    "Idempotency-Key": f"dd-{uuid.uuid4()}",
                },
            }
            for name, value in (
                ("temperature", self._temperature),
                ("top_p", self._top_p),
                ("seed", self._seed),
            ):
                if value is not None:
                    arguments[name] = value
            if include_response_format:
                arguments["response_format"] = response_format
            return client.chat.completions.create(**arguments)

        try:
            chat = create_completion(include_response_format=True)
        except Exception as exc:
            if not self._base_url or not _is_unsupported_response_format_error(exc):
                raise
            # Some OpenAI-compatible providers accept chat completions but not
            # response_format. The prompt and local validator remain strict.
            chat = create_completion(include_response_format=False)
        content = chat.choices[0].message.content or "{}"
        if len(content.encode("utf-8")) > self._max_response_bytes:
            raise RuntimeError(f"LLM response exceeds {self._max_response_bytes} byte limit")
        try:
            return json.loads(  # type: ignore[no-any-return]
                content,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"OpenAI returned non-JSON content: {exc}") from exc


# --- JSON schema used for structured outputs ---------------------------


def _proposal_schema(search_space: SearchSpace) -> dict[str, Any]:
    parameter_properties: dict[str, Any] = {}
    for domain in search_space.domains:
        definition: dict[str, Any] = {
            "type": "integer" if domain.value_type != "float" else "number",
            "minimum": domain.minimum,
            "maximum": domain.maximum,
        }
        if domain.choices:
            definition["enum"] = list(domain.choices)
        parameter_properties[domain.name] = definition
    parameter_keys = [domain.name for domain in search_space.domains]
    return {
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
                        "rationale": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 400,
                        },
                        "parameters": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": parameter_keys,
                            "properties": parameter_properties,
                        },
                    },
                },
            }
        },
    }


# --- Helpers -----------------------------------------------------------


def _search_space_for_job(job: models.Job) -> SearchSpace:
    if job.parameter_space_json:
        selections = [
            schemas.ParameterSelection(**item)
            for item in job.parameter_space_json
            if item.get("enabled", True)
        ]
        if selections:
            return SearchSpace.from_schema(
                selections,
                candidate_validator=validator_for_job(job),
            )
    return SearchSpace(
        [
            ParameterDomain(
                name=key,
                baseline=constants.BASELINE_PARAMETERS[key],
                minimum=bounds[0],
                maximum=bounds[1],
            )
            for key, bounds in constants.PARAMETER_SAFE_RANGES.items()
        ]
    )


def _sanitize(parameters: dict[str, Any], search_space: SearchSpace) -> dict[str, float] | None:
    parameter_keys = {domain.name for domain in search_space.domains}
    if set(parameters) != parameter_keys:
        return None
    numeric_parameters: dict[str, float] = {}
    for key, raw in parameters.items():
        numeric = _finite_number(raw)
        if numeric is None:
            return None
        numeric_parameters[key] = numeric
    try:
        return search_space.project(numeric_parameters)
    except ValueError:
        return None


def _is_safe_response_tree(value: Any) -> bool:
    remaining = _MAX_RESPONSE_NODES

    def visit(node: Any, depth: int) -> bool:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > _MAX_RESPONSE_DEPTH:
            return False
        if node is None or isinstance(node, str | bool):
            return True
        if isinstance(node, int | float):
            return not isinstance(node, bool) and math.isfinite(float(node))
        if isinstance(node, list):
            return all(visit(item, depth + 1) for item in node)
        if isinstance(node, dict):
            return all(
                isinstance(key, str) and visit(item, depth + 1) for key, item in node.items()
            )
        return False

    return visit(value, 0)


def load_job_api_key(db: Session, job: models.Job) -> str | None:
    now = datetime.now(timezone.utc)
    expired_count = 0
    for stored_secret in job.secrets:
        expires_at = stored_secret.expires_at
        if expires_at is None:
            continue
        # SQLite may round-trip timezone-aware columns as naive datetimes.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now and stored_secret.deleted_at is None:
            stored_secret.deleted_at = now
            stored_secret.encrypted_api_key = ""
            expired_count += 1
    if expired_count:
        record_event(
            db,
            job.id,
            "job_secrets_purged",
            {"reason": "secret_expired", "count": expired_count},
        )
        # Flush before returning so another code path in this transaction
        # cannot accidentally reuse an expired credential.
        db.flush()
    expected_secret_provider = (
        "dronedream_gateway" if job.llm_provider == "dronedream" else "openai"
    )
    secret = next(
        (
            s
            for s in sorted(job.secrets, key=lambda s: s.created_at, reverse=True)
            if (
                s.provider == expected_secret_provider
                and s.deleted_at is None
                and s.encrypted_api_key
            )
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


# Compatibility alias retained for the focused secret-expiry regression test.
_load_api_key = load_job_api_key


def _compile_vehicle_profile(job: models.Job) -> dict[str, Any]:
    profile = schemas.VehicleProfileConfig(**(job.vehicle_profile_json or {}))
    try:
        airframe_family = classify_airframe(profile.airframe)
    except ValueError:
        airframe_family = "custom_multicopter"
    return {
        "px4_version": (
            profile.px4_version
            if profile.px4_version in SUPPORTED_PX4_VERSIONS
            else "custom_px4_version"
        ),
        "firmware_commit": profile.firmware_commit,
        "vehicle_type": (
            profile.vehicle_type
            if profile.vehicle_type in SUPPORTED_VEHICLE_TYPES
            else "custom_vehicle_type"
        ),
        "airframe_family": airframe_family,
        "simulator_model_kind": (
            "gazebo_px4" if profile.simulator_model.startswith("gz_") else "custom"
        ),
        "world_kind": "default" if profile.world == "default" else "custom",
        "headless": profile.headless,
        "simulation_speed_factor": profile.simulation_speed_factor,
        "instance_id": profile.instance_id,
    }


def _compile_objective_contract(job: models.Job) -> dict[str, Any]:
    config = schemas.ObjectiveConfig(**(job.objective_config_json or {}))
    objectives = [
        {
            "metric": (
                objective.metric
                if objective.metric in _SAFE_OBJECTIVE_METRICS
                else f"custom_objective_{index + 1}"
            ),
            "direction": objective.direction,
            "weight": objective.weight,
            "normalization": objective.normalization,
            "target": objective.target,
        }
        for index, objective in enumerate(config.objectives)
    ]
    constraints = [
        {
            "metric": (
                constraint.metric
                if constraint.metric in _SAFE_OBJECTIVE_METRICS
                else f"custom_constraint_{index + 1}"
            ),
            "operator": constraint.operator,
            "threshold": constraint.threshold,
            "hard": constraint.hard,
            "penalty": constraint.penalty,
        }
        for index, constraint in enumerate(config.constraints)
    ]
    return {
        "objectives": objectives,
        "constraints": constraints,
        "robust_aggregation": config.robust_aggregation,
        "cvar_alpha": config.cvar_alpha,
        "percentile": config.percentile,
    }


def _compile_scenario_contract(
    job: models.Job,
    *,
    compact: bool = False,
) -> dict[str, Any]:
    suite = schemas.ScenarioSuiteConfig(**(job.scenario_suite_json or {}))
    training_cases = [case for case in suite.cases if case.enabled and not case.holdout]
    holdout_cases = [case for case in suite.cases if case.enabled and case.holdout]
    training_aliases = {
        case.id: f"training_case_{index + 1}" for index, case in enumerate(training_cases)
    }
    training_type_counts: dict[str, int] = {}
    for case in training_cases:
        training_type_counts[case.scenario_type] = (
            training_type_counts.get(case.scenario_type, 0) + 1
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "common_random_numbers": suite.common_random_numbers,
        "training_case_count": len(training_cases),
        "training_replicate_count": sum(len(case.seeds) for case in training_cases),
        "training_type_counts": dict(sorted(training_type_counts.items())),
        "holdout_case_count": len(holdout_cases),
        "holdout_replicate_count": sum(len(case.seeds) for case in holdout_cases),
    }
    if compact:
        return payload
    payload["training_cases"] = [
        {
            "case_alias": training_aliases[case.id],
            "scenario_type": case.scenario_type,
            "seed_count": len(case.seeds),
            "weight": case.weight,
            "config": {
                key: numeric
                for key in sorted(_SAFE_SCENARIO_CONFIG_KEYS)
                if (numeric := _finite_number(case.config.get(key))) is not None
            },
        }
        for case in training_cases
    ]
    return payload


def _build_prompt(
    job: models.Job,
    criteria: AcceptanceCriteria,
    candidates: list[models.CandidateParameterSet],
    search_space: SearchSpace,
) -> tuple[str, str, dict[str, Any]]:
    scenario_suite = schemas.ScenarioSuiteConfig(**(job.scenario_suite_json or {}))
    training_cases = [case for case in scenario_suite.cases if case.enabled and not case.holdout]
    training_case_aliases = {
        case.id: f"training_case_{index + 1}" for index, case in enumerate(training_cases)
    }
    system = (
        "You are an expert drone-control tuning assistant. Your job is to "
        "propose only the user-selected PX4 control parameters that improve "
        "simulator metrics under the configured scenario matrix and constraints. "
        "Treat each scenario case alias as a distinct experimental condition; "
        "never merge cases solely because they share a scenario_type. "
        "You must return only structured JSON conforming to the "
        "provided schema — no free-form text."
    )
    parameter_domains = {
        domain.name: {
            "minimum": domain.minimum,
            "maximum": domain.maximum,
            "baseline": domain.baseline,
            "step": domain.step,
            "scale": domain.scale,
            "value_type": domain.value_type,
            "choices": list(domain.choices),
            "locked": domain.locked,
        }
        for domain in search_space.domains
    }
    feedback_by_id = {
        candidate.id: compile_candidate_feedback(
            candidate,
            scenario_suite=scenario_suite,
        )
        for candidate in candidates
    }

    selected_history: dict[str, models.CandidateParameterSet] = {}
    for candidate in candidates:
        if candidate.is_baseline:
            selected_history[candidate.id] = candidate
    for candidate in sorted(
        (item for item in candidates if feedback_by_id[item.id].score is not None),
        key=lambda item: (
            (
                feedback_by_id[item.id].score
                if feedback_by_id[item.id].score is not None
                else float("inf")
            ),
            item.generation_index,
        ),
    )[:2]:
        selected_history[candidate.id] = candidate
    for candidate in sorted(
        candidates,
        key=lambda item: (item.generation_index, item.created_at, item.id),
        reverse=True,
    ):
        if len(selected_history) >= _MAX_PROMPT_CANDIDATES:
            break
        selected_history[candidate.id] = candidate

    prior: list[dict[str, Any]] = []
    domain_names = {domain.name for domain in search_space.domains}
    for cand in sorted(
        selected_history.values(),
        key=lambda c: (c.generation_index, not c.is_baseline, c.id),
    ):
        feedback = feedback_by_id[cand.id]
        agg = feedback.aggregate
        trial_count = 0
        completed_trial_count = 0
        failed_trial_count = 0
        passing_trial_count = 0
        scenario_feedback: dict[str, dict[str, Any]] = {}
        trusted_trials = (
            sorted(
                cand.trials,
                key=lambda trial: (
                    trial.scenario_type,
                    trial.seed,
                    trial.id,
                ),
            )
            if feedback.usable
            else ()
        )
        for trial in trusted_trials:
            resolution = resolve_scenario_case(
                scenario_suite,
                scenario_type=trial.scenario_type,
                scenario_config=trial.scenario_config_json,
                seed=trial.seed,
            )
            if not resolution.matched or resolution.case is None or resolution.case.holdout:
                continue
            scenario_case = resolution.case
            case_alias = training_case_aliases.get(scenario_case.id)
            if case_alias is None:
                continue
            metric = trial.metric
            rmse = _finite_number(metric.rmse) if metric is not None else None
            max_error = _finite_number(metric.max_error) if metric is not None else None
            completion_time = _finite_number(metric.completion_time) if metric is not None else None
            usable_metric = (
                trial.status == "COMPLETED"
                and metric is not None
                and rmse is not None
                and max_error is not None
                and completion_time is not None
            )
            outcome_class = classify_trial_outcome(
                status=trial.status,
                failure_code=trial.failure_code,
                usable_metric=usable_metric,
            )
            if not is_optimizer_learning_outcome(outcome_class):
                continue
            trial_count += 1
            bucket = scenario_feedback.setdefault(
                scenario_case.id,
                {
                    "case_alias": case_alias,
                    "scenario_type": scenario_case.scenario_type,
                    "weight": scenario_case.weight,
                    "configured_seed_count": len(scenario_case.seeds),
                    "config": {
                        key: numeric
                        for key in sorted(_SAFE_SCENARIO_CONFIG_KEYS)
                        if (numeric := _finite_number(scenario_case.config.get(key))) is not None
                    },
                    "trial_count": 0,
                    "completed_count": 0,
                    "passing_count": 0,
                    "rmse_sum": 0.0,
                    "max_error_sum": 0.0,
                    "completion_time_sum": 0.0,
                    "failure_codes": {},
                },
            )
            bucket["trial_count"] += 1
            if outcome_class == "success" and metric is not None:
                if rmse is None or max_error is None or completion_time is None:
                    raise RuntimeError(
                        "successful optimizer-learning outcome lost its usable metrics"
                    )
                completed_trial_count += 1
                passing_trial_count += int(metric.pass_flag)
                bucket["completed_count"] += 1
                bucket["passing_count"] += int(metric.pass_flag)
                bucket["rmse_sum"] += rmse
                bucket["max_error_sum"] += max_error
                bucket["completion_time_sum"] += completion_time
            elif is_optimizer_learning_failure(outcome_class):
                failed_trial_count += 1
                codes = bucket["failure_codes"]
                failure_code = (
                    trial.failure_code
                    if trial.failure_code in _SAFE_OPTIMIZER_FAILURE_CODES
                    else "OTHER"
                )
                codes[failure_code] = int(codes.get(failure_code, 0)) + 1
        compact_feedback: list[dict[str, Any]] = []
        for scenario_case in training_cases:
            case_bucket = scenario_feedback.get(scenario_case.id)
            if case_bucket is None:
                continue
            completed_count = int(case_bucket.pop("completed_count"))
            rmse_sum = float(case_bucket.pop("rmse_sum"))
            max_error_sum = float(case_bucket.pop("max_error_sum"))
            completion_sum = float(case_bucket.pop("completion_time_sum"))
            case_bucket["failure_codes"] = dict(sorted(case_bucket["failure_codes"].items()))
            case_bucket["completed_count"] = completed_count
            case_bucket["mean_rmse"] = (
                round(rmse_sum / completed_count, 6) if completed_count else None
            )
            case_bucket["mean_max_error"] = (
                round(max_error_sum / completed_count, 6) if completed_count else None
            )
            case_bucket["mean_completion_time"] = (
                round(completion_sum / completed_count, 6) if completed_count else None
            )
            compact_feedback.append(case_bucket)
        completion_rate = completed_trial_count / trial_count if trial_count > 0 else 0.0
        prompt_aggregate: dict[str, Any] = {}
        for key in _PROMPT_AGGREGATE_KEYS:
            if key not in agg:
                continue
            safe_value = _safe_prompt_value(agg[key])
            if safe_value is not _INVALID_PROMPT_VALUE:
                prompt_aggregate[key] = safe_value
        prompt_aggregate.update(
            {
                "trial_count": trial_count,
                "completed_trial_count": completed_trial_count,
                "failed_trial_count": failed_trial_count,
                "passing_trial_count": passing_trial_count,
                "optimizer_learning_failure_rate": (
                    round(failed_trial_count / trial_count, 8) if trial_count > 0 else 0.0
                ),
            }
        )
        prior.append(
            {
                "generation_index": cand.generation_index,
                "source_type": (
                    cand.source_type
                    if cand.source_type in {"baseline", "optimizer", "llm_optimizer"}
                    else "unknown"
                ),
                "feedback_status": feedback.feedback_status,
                "parameters": {
                    key: value
                    for key, value in (cand.parameter_json or {}).items()
                    if key in domain_names and _finite_number(value) is not None
                },
                "aggregated_metrics": prompt_aggregate,
                "aggregated_score": feedback.score,
                "pass_rate": (
                    round((passing_trial_count / trial_count), 4) if trial_count > 0 else 0.0
                ),
                "completion_rate": round(completion_rate, 4),
                "passing_trial_count": passing_trial_count,
                "trial_count": trial_count,
                "scenario_feedback": compact_feedback,
                "is_baseline": cand.is_baseline,
            }
        )

    user_payload = {
        "prompt_schema_version": LLM_PROPOSER_PROMPT_SCHEMA_VERSION,
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
        "vehicle_profile": _compile_vehicle_profile(job),
        "parameter_catalog_version": job.parameter_catalog_version,
        "parameter_domains": parameter_domains,
        "baseline_parameters": search_space.baseline(),
        "objective_config": _compile_objective_contract(job),
        "scenario_suite": _compile_scenario_contract(job),
        "previous_candidates": prior,
        "current_generation": job.current_generation,
        "max_iterations": job.max_iterations,
        "instructions": (
            "Propose exactly 1 next-generation candidate parameter set. "
            "The proposal must include all required keys and "
            "every numeric value must lie inside its declared domain. Keep locked "
            "parameters at baseline and honor step/enum values. Do not "
            "include any other keys. Be explicit about the rationale."
        ),
    }
    settings = get_settings()
    scenario_suite_compacted = False

    def serialize() -> str:
        return json.dumps(
            user_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    encoded = serialize()
    while len(encoded.encode("utf-8")) > settings.llm_max_prompt_bytes:
        removable_index = next(
            (index for index, item in enumerate(prior) if not bool(item.get("is_baseline"))),
            None,
        )
        if removable_index is None:
            break
        prior.pop(removable_index)
        encoded = serialize()
    if len(encoded.encode("utf-8")) > settings.llm_max_prompt_bytes:
        user_payload["scenario_suite"] = _compile_scenario_contract(
            job,
            compact=True,
        )
        scenario_suite_compacted = True
        encoded = serialize()
    prompt_bytes = len(encoded.encode("utf-8"))
    if prompt_bytes > settings.llm_max_prompt_bytes:
        raise RuntimeError(
            f"LLM prompt exceeds {settings.llm_max_prompt_bytes} byte limit after safe compaction"
        )
    prompt_metadata = {
        "history_total": len(candidates),
        "history_included": len(prior),
        "history_omitted": len(candidates) - len(prior),
        "scenario_suite_compacted": scenario_suite_compacted,
        "prompt_bytes": prompt_bytes,
    }
    user_payload["prompt_compaction"] = prompt_metadata
    encoded = serialize()
    if len(encoded.encode("utf-8")) > settings.llm_max_prompt_bytes:
        raise RuntimeError("LLM prompt metadata exceeded configured byte limit")
    prompt_metadata["prompt_bytes"] = len(encoded.encode("utf-8"))
    return system, serialize(), prompt_metadata


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

    provider = job.llm_provider or "openai"
    configured_model = model or job.openai_model or job_secrets_env_model()
    if configured_model is None and provider != "openai":
        record_event(
            db,
            job.id,
            "llm_proposal_failed",
            {"reason": "missing_model", "provider": provider},
        )
        return LlmProposerResult(error="missing_model")
    chosen_model = configured_model or _DEFAULT_MODEL
    search_space = _search_space_for_job(job)

    effective_client: OpenAIClientLike | None = client
    if effective_client is None:
        api_key = load_job_api_key(db, job)
        if api_key is None:
            record_event(
                db,
                job.id,
                "llm_proposal_failed",
                {"reason": "missing_api_key", "model": chosen_model},
            )
            return LlmProposerResult(error="missing_api_key", model=chosen_model)
        settings = get_settings()
        effective_client = OpenAIJsonClient(
            api_key,
            proposal_schema=_proposal_schema(search_space),
            base_url=job.llm_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_response_bytes=settings.llm_max_response_bytes,
        )

    record_event(
        db,
        job.id,
        "llm_proposal_started",
        {
            "generation": job.current_generation + 1,
            "model": chosen_model,
            "provider": provider,
            "parameter_count": len(search_space.domains),
        },
    )

    try:
        system, user, prompt_metadata = _build_prompt(
            job, criteria, list(job.candidates), search_space
        )
        if prompt_metadata["history_omitted"] or prompt_metadata["scenario_suite_compacted"]:
            record_event(db, job.id, "llm_prompt_compacted", prompt_metadata)
        raw = effective_client.generate(model=chosen_model, system=system, user=user)
    except Exception as exc:  # OpenAI client failure, network, etc.
        error_type = type(exc).__name__
        logger.warning(
            "LLM proposer call failed for job %s (error_type=%s)",
            job.id,
            error_type,
        )
        record_event(
            db,
            job.id,
            "llm_proposal_failed",
            {
                "reason": "client_error",
                "error_type": error_type[:128],
                "model": chosen_model,
            },
        )
        return LlmProposerResult(error="client_error", model=chosen_model)

    proposals = _validate_response(raw, search_space)
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
    persisted_response = {
        "proposals": [
            {
                "label": proposal.label,
                "rationale": proposal.rationale,
                "parameters": dict(proposal.parameters),
            }
            for proposal in proposals
        ]
    }
    return LlmProposerResult(
        proposals=proposals,
        raw_response=persisted_response,
        model=chosen_model,
    )


def _validate_response(raw: dict[str, Any] | None, search_space: SearchSpace) -> list[LlmProposal]:
    if not isinstance(raw, dict) or set(raw) != {"proposals"} or not _is_safe_response_tree(raw):
        return []
    proposals_raw = raw.get("proposals")
    if (
        not isinstance(proposals_raw, list)
        or not _MIN_PROPOSALS <= len(proposals_raw) <= _MAX_PROPOSALS
    ):
        return []
    out: list[LlmProposal] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for item in proposals_raw:
        if not isinstance(item, dict):
            continue
        if set(item) != {"label", "rationale", "parameters"}:
            continue
        label = item.get("label")
        rationale = item.get("rationale")
        parameters = item.get("parameters")
        if (
            not isinstance(label, str)
            or not isinstance(rationale, str)
            or not 1 <= len(label.strip()) <= 80
            or not 1 <= len(rationale.strip()) <= 400
        ):
            continue
        if not isinstance(parameters, dict):
            continue
        cleaned = _sanitize(parameters, search_space)
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
    "LLM_PROPOSER_PROMPT_SCHEMA_VERSION",
    "LlmProposal",
    "LlmProposerResult",
    "OpenAIJsonClient",
    "OpenAIClientLike",
    "load_job_api_key",
    "propose_candidates",
]
