"""Content-addressed proof of deterministic final Candidate selection."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.optimization.outcome_contract import selection_order_key

WINNER_SELECTION_EVIDENCE_SCHEMA = "dronedream.winner-selection-evidence/v1"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonnegativeFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonnegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SelectionOrder = tuple[
    Literal[0, 1],
    Literal[0, 1],
    NonnegativeFloat,
    Rate,
    FiniteFloat,
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class WinnerCandidateInputV1(_FrozenModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    generation_index: NonnegativeInt
    is_baseline: StrictBool
    eligible: StrictBool
    candidate_outcome_evidence_id: Sha256Id
    candidate_report_evidence_id: Sha256Id
    selection_order_key: SelectionOrder | None


class WinnerCandidateDecisionV1(WinnerCandidateInputV1):
    rank: PositiveInt | None


class WinnerSelectionEvidenceV1(_FrozenModel):
    schema_id: Literal["dronedream.winner-selection-evidence/v1"] = (
        "dronedream.winner-selection-evidence/v1"
    )
    evidence_id: Sha256Id
    outcome_contract_id: Sha256Id
    selection_policy_schema_version: Literal["1.0"] = "1.0"
    candidate_set_policy: Literal[
        "all_aggregated_candidates_with_bound_report_evidence"
    ] = "all_aggregated_candidates_with_bound_report_evidence"
    stable_tiebreak_policy: Literal[
        "optimizer_before_baseline_then_generation_then_candidate_id"
    ] = "optimizer_before_baseline_then_generation_then_candidate_id"
    baseline_candidate_id: str = Field(min_length=1, max_length=128)
    winner_candidate_id: str = Field(min_length=1, max_length=128)
    winner_candidate_report_evidence_id: Sha256Id
    candidate_count: PositiveInt
    eligible_candidate_count: PositiveInt
    candidates: tuple[WinnerCandidateDecisionV1, ...]


class WinnerSelectionEvidenceError(ValueError):
    """Raised when the final winner cannot be proven from current evidence."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _candidate_order(
    candidate: WinnerCandidateInputV1 | WinnerCandidateDecisionV1,
) -> tuple[int, int, float, float, float, int, int, str]:
    order = candidate.selection_order_key
    if order is None:
        raise WinnerSelectionEvidenceError(
            "eligible winner evidence Candidate lacks a finite selection key"
        )
    return (
        int(order[0]),
        int(order[1]),
        float(order[2]),
        float(order[3]),
        float(order[4]),
        0 if not candidate.is_baseline else 1,
        int(candidate.generation_index),
        candidate.candidate_id,
    )


def compile_winner_selection_evidence(
    *,
    outcome_contract_id: str,
    baseline_candidate_id: str,
    winner_candidate_id: str,
    candidates: Sequence[Mapping[str, Any] | WinnerCandidateInputV1],
) -> WinnerSelectionEvidenceV1:
    """Compile the complete aggregated Candidate universe and final ranking."""

    try:
        parsed = [
            (
                item
                if isinstance(item, WinnerCandidateInputV1)
                else WinnerCandidateInputV1.model_validate(item)
            )
            for item in candidates
        ]
    except ValidationError as exc:
        raise WinnerSelectionEvidenceError(
            "winner evidence contains an invalid Candidate input: "
            f"{exc.errors(include_url=False)}"
        ) from exc
    if not parsed:
        raise WinnerSelectionEvidenceError(
            "winner evidence requires at least one Candidate"
        )
    candidate_ids = [item.candidate_id for item in parsed]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise WinnerSelectionEvidenceError(
            "winner evidence Candidate IDs must be unique"
        )
    baselines = [item for item in parsed if item.is_baseline]
    if (
        len(baselines) != 1
        or baselines[0].candidate_id != baseline_candidate_id
    ):
        raise WinnerSelectionEvidenceError(
            "winner evidence must bind exactly one declared baseline"
        )
    eligible = sorted(
        (item for item in parsed if item.eligible),
        key=_candidate_order,
    )
    if not eligible:
        raise WinnerSelectionEvidenceError(
            "winner evidence requires at least one eligible Candidate"
        )
    if eligible[0].candidate_id != winner_candidate_id:
        raise WinnerSelectionEvidenceError(
            "declared winner does not match Selection Key 1.0 ordering"
        )
    rank_by_id = {
        item.candidate_id: rank
        for rank, item in enumerate(eligible, start=1)
    }
    decisions = tuple(
        WinnerCandidateDecisionV1(
            **item.model_dump(mode="python"),
            rank=rank_by_id.get(item.candidate_id),
        )
        for item in sorted(parsed, key=lambda row: row.candidate_id)
    )
    winner = eligible[0]
    payload = {
        "schema_id": WINNER_SELECTION_EVIDENCE_SCHEMA,
        "outcome_contract_id": outcome_contract_id,
        "selection_policy_schema_version": "1.0",
        "candidate_set_policy": (
            "all_aggregated_candidates_with_bound_report_evidence"
        ),
        "stable_tiebreak_policy": (
            "optimizer_before_baseline_then_generation_then_candidate_id"
        ),
        "baseline_candidate_id": baseline_candidate_id,
        "winner_candidate_id": winner_candidate_id,
        "winner_candidate_report_evidence_id": (
            winner.candidate_report_evidence_id
        ),
        "candidate_count": len(decisions),
        "eligible_candidate_count": len(eligible),
        "candidates": [
            item.model_dump(mode="json") for item in decisions
        ],
    }
    return WinnerSelectionEvidenceV1.model_validate(
        {
            "evidence_id": _sha256_id(payload),
            **payload,
        }
    )


def verify_winner_selection_evidence(
    value: object,
) -> WinnerSelectionEvidenceV1 | None:
    """Verify schema, content hash, complete ranks, and deterministic winner."""

    try:
        evidence = WinnerSelectionEvidenceV1.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    if evidence_id != _sha256_id(payload):
        return None
    candidates = list(evidence.candidates)
    candidate_ids = [item.candidate_id for item in candidates]
    if (
        candidate_ids != sorted(candidate_ids)
        or len(set(candidate_ids)) != evidence.candidate_count
        or len(candidate_ids) != evidence.candidate_count
    ):
        return None
    baselines = [item for item in candidates if item.is_baseline]
    if (
        len(baselines) != 1
        or baselines[0].candidate_id != evidence.baseline_candidate_id
    ):
        return None
    eligible_candidates = [
        item for item in candidates if item.eligible
    ]
    if any(
        item.selection_order_key is None
        for item in eligible_candidates
    ):
        return None
    eligible = sorted(eligible_candidates, key=_candidate_order)
    if len(eligible) != evidence.eligible_candidate_count or not eligible:
        return None
    for rank, item in enumerate(eligible, start=1):
        if item.rank != rank:
            return None
    if any(item.rank is not None for item in candidates if not item.eligible):
        return None
    winner = eligible[0]
    if (
        winner.candidate_id != evidence.winner_candidate_id
        or winner.candidate_report_evidence_id
        != evidence.winner_candidate_report_evidence_id
    ):
        return None
    return evidence


def winner_evidence_matches_current_candidates(
    value: object,
    *,
    candidates: Sequence[object],
    outcome_projections: Mapping[str, Mapping[str, Any]],
    report_projections: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Bind a verified envelope back to current Candidate rows and projections."""

    evidence = verify_winner_selection_evidence(value)
    if evidence is None:
        return False
    current_by_id: dict[str, object] = {}
    for candidate in candidates:
        candidate_id = getattr(candidate, "id", None)
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in current_by_id
        ):
            return False
        current_by_id[candidate_id] = candidate
    evidence_by_id = {
        item.candidate_id: item for item in evidence.candidates
    }
    if set(current_by_id) != set(evidence_by_id):
        return False
    for candidate_id, candidate in current_by_id.items():
        decision = evidence_by_id[candidate_id]
        outcome = outcome_projections.get(candidate_id)
        report = report_projections.get(candidate_id)
        if outcome is None or report is None:
            return False
        current_order = selection_order_key(
            getattr(candidate, "aggregated_metric_json", None),
            getattr(candidate, "aggregated_score", None),
        )
        finite_current_order = (
            tuple(current_order)
            if all(
                math.isfinite(float(order_value))
                for order_value in current_order
            )
            else None
        )
        if (
            finite_current_order != decision.selection_order_key
            or report.get("candidate_outcome_evidence_id")
            != decision.candidate_outcome_evidence_id
            or report.get("candidate_report_evidence_id")
            != decision.candidate_report_evidence_id
            or getattr(candidate, "generation_index", None)
            != decision.generation_index
            or getattr(candidate, "is_baseline", None)
            != decision.is_baseline
            or (getattr(candidate, "rank_in_job", None) is not None)
            != decision.eligible
            or getattr(candidate, "rank_in_job", None) != decision.rank
            or bool(getattr(candidate, "is_best", False))
            != (candidate_id == evidence.winner_candidate_id)
        ):
            return False
    return True


__all__ = [
    "WINNER_SELECTION_EVIDENCE_SCHEMA",
    "WinnerCandidateDecisionV1",
    "WinnerCandidateInputV1",
    "WinnerSelectionEvidenceError",
    "WinnerSelectionEvidenceV1",
    "compile_winner_selection_evidence",
    "verify_winner_selection_evidence",
    "winner_evidence_matches_current_candidates",
]
