"""Zero-provider, zero-PX4 structural fairness matrix for benchmark adapters.

The matrix runs deterministic fixture responses and a cheap numeric landscape.
It proves common information, proposal/evaluator interoperability, and equal
simulator-candidate budgets.  It is an engineering gate only and cannot support
claims about flight quality, real models, or method rankings.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import (
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    BenchmarkProposalContextV1,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.benchmarking.llm_arm_contracts import BenchmarkLLMTurnRequestV1
from app.benchmarking.llm_fixture_runtime import (
    BenchmarkLLMFixtureExecutionError,
    execute_offline_llm_arm,
)
from app.benchmarking.numeric_landscapes import DeterministicConstrainedLandscapeV1
from app.benchmarking.registry import create_benchmark_adapter, require_registered_adapter
from app.optimization.domain import ParameterDomain, SearchSpace

OFFLINE_MATRIX_SCHEMA_ID: Final = "dronedream.benchmark-offline-matrix/v1"
OFFLINE_MATRIX_FIXTURE_ID: Final = "deterministic-closed-response-fixture-v1"
BenchmarkOfflineStatus = Literal["passed", "failed", "unsafe"]
_OfflineStatusCount = Annotated[int, Field(ge=0, le=128)]


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkOfflineArmResultV1(_FrozenStrict):
    adapter_id: Annotated[str, Field(min_length=1, max_length=128)]
    requested_generations: Annotated[int, Field(ge=1, le=128)]
    proposals_dispatched: Annotated[int, Field(ge=0, le=128)]
    simulator_evaluations_attempted: Annotated[int, Field(ge=0, le=128)]
    simulator_evaluations_completed: Annotated[int, Field(ge=0, le=128)]
    provider_turns_attempted: Annotated[int, Field(ge=0, le=512)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=512)]
    status_counts: dict[BenchmarkOfflineStatus, _OfflineStatusCount]
    failure_codes: tuple[str, ...] = Field(default=(), max_length=128)
    final_history_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def _validate_counts(self) -> BenchmarkOfflineArmResultV1:
        if self.simulator_evaluations_completed > self.simulator_evaluations_attempted:
            raise ValueError("completed simulator evaluations cannot exceed attempted")
        if self.proposals_dispatched != self.simulator_evaluations_attempted:
            raise ValueError("every dispatched numeric proposal must enter the shared evaluator")
        if self.provider_turns_succeeded > self.provider_turns_attempted:
            raise ValueError("provider successes cannot exceed attempts")
        if self.proposals_dispatched > self.requested_generations:
            raise ValueError("dispatched proposals cannot exceed requested generations")
        if sum(self.status_counts.values()) != self.simulator_evaluations_completed:
            raise ValueError("status counts must equal completed simulator evaluations")
        return self


class BenchmarkOfflineMatrixV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-offline-matrix/v1"] = (
        "dronedream.benchmark-offline-matrix/v1"
    )
    fixture_id: Literal["deterministic-closed-response-fixture-v1"] = (
        "deterministic-closed-response-fixture-v1"
    )
    landscape_id: Literal["dronedream.constrained-numeric-landscape/v1"] = (
        "dronedream.constrained-numeric-landscape/v1"
    )
    requested_generations_per_arm: Annotated[int, Field(ge=1, le=128)]
    shared_observation_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    shared_parameter_domain_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    results: tuple[BenchmarkOfflineArmResultV1, ...] = Field(min_length=1, max_length=64)
    structural_fairness_passed: bool
    evidence_scope: Literal["engineering-only-no-provider-no-px4"] = (
        "engineering-only-no-provider-no-px4"
    )

    @model_validator(mode="after")
    def _validate_unique_arms(self) -> BenchmarkOfflineMatrixV1:
        adapter_ids = [result.adapter_id for result in self.results]
        if len(adapter_ids) != len(set(adapter_ids)):
            raise ValueError("offline matrix adapter IDs must be unique")
        expected = self.requested_generations_per_arm
        if any(result.requested_generations != expected for result in self.results):
            raise ValueError("per-arm requested generations differ from the matrix contract")
        computed = all(
            result.simulator_evaluations_attempted == expected
            and result.simulator_evaluations_completed == expected
            and not result.failure_codes
            for result in self.results
        )
        if computed != self.structural_fairness_passed:
            raise ValueError("offline matrix fairness flag disagrees with per-arm accounting")
        return self


@dataclass(slots=True)
class DeterministicClosedResponseFixtureV1:
    """Schema-driven fixture provider with no model, credential, or network access."""

    fixture_only: bool = True
    requests: list[BenchmarkLLMTurnRequestV1] = field(default_factory=list)

    @staticmethod
    def _tool_outputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
        outputs = payload.get("tool_outputs")
        return outputs if isinstance(outputs, list) else []

    @staticmethod
    def _proposal_parameters(
        request: BenchmarkLLMTurnRequestV1, payload: dict[str, Any]
    ) -> dict[str, float | int]:
        properties = request.response_schema["properties"]["parameters"]["properties"]
        observation = payload.get("observation")
        raw_domains = observation.get("parameter_domain") if isinstance(observation, dict) else None
        if not isinstance(raw_domains, list):
            raise ValueError("fixture request is missing the frozen parameter domain")
        domains: dict[str, ParameterDomain] = {}
        for item in raw_domains:
            if not isinstance(item, dict):
                raise ValueError("fixture parameter domain entries must be objects")
            domain = ParameterDomain(
                name=item["name"],
                baseline=item["baseline"],
                minimum=item["minimum"],
                maximum=item["maximum"],
                step=item.get("step"),
                scale=item.get("scale", "linear"),
                value_type=item.get("value_type", "float"),
                choices=tuple(item.get("choices", ())),
                enabled=item.get("enabled", True),
                locked=item.get("locked", False),
            )
            if domain.name in domains:
                raise ValueError("fixture parameter domain names must be unique")
            domains[domain.name] = domain
        if set(domains) != set(properties):
            raise ValueError("fixture response schema and frozen parameter domain differ")
        result: dict[str, float | int] = {}
        for dimension, name in enumerate(sorted(properties)):
            schema = properties[name]
            fraction = 0.15 + 0.7 * (
                ((request.generation_index + 1) * (dimension + 2) * 0.318309886) % 1.0
            )
            value = domains[name].from_unit(fraction)
            result[name] = int(value) if schema["type"] == "integer" else value
        return result

    def complete(self, request: BenchmarkLLMTurnRequestV1) -> str:
        self.requests.append(request)
        payload = json.loads(request.user)
        tool_outputs = self._tool_outputs(payload)
        response: dict[str, Any]
        if request.turn_role in {"direct_proposal", "llambo_proposal"}:
            response = {
                "schema_version": "1.0",
                "decision": "propose",
                "parameters": self._proposal_parameters(request, payload),
            }
        elif request.turn_role == "react_action":
            proposals = [item for item in tool_outputs if "proposal_ref" in item]
            if proposals:
                response = {
                    "schema_version": "1.0",
                    "decision": "dispatch",
                    "tool_adapter_ids": [],
                    "selected_proposal_ref": proposals[0]["proposal_ref"],
                }
            else:
                response = {
                    "schema_version": "1.0",
                    "decision": "act",
                    "tool_adapter_ids": ["random_search/v1"],
                    "selected_proposal_ref": None,
                }
        elif request.turn_role == "plan":
            response = {
                "schema_version": "1.0",
                "decision": "act",
                "tool_adapter_ids": ["random_search/v1"],
            }
        elif request.turn_role == "revision":
            proposals = [item for item in tool_outputs if "proposal_ref" in item]
            response = {
                "schema_version": "1.0",
                "decision": "dispatch",
                "selected_proposal_ref": proposals[0]["proposal_ref"],
            }
        elif request.turn_role == "diagnosis":
            proposals = [item for item in tool_outputs if "proposal_ref" in item]
            response = {
                "schema_version": "1.0",
                "decision": "keep",
                "selected_proposal_ref": proposals[0]["proposal_ref"],
            }
        else:
            selected = next(
                item["selected_proposal_ref"]
                for item in reversed(tool_outputs)
                if "selected_proposal_ref" in item
            )
            response = {
                "schema_version": "1.0",
                "decision": "approve",
                "selected_proposal_ref": selected,
            }
        return json.dumps(response, sort_keys=True, separators=(",", ":"))


def _identity_neutral_observation_payload(observation: BenchmarkObservationV2) -> dict[str, Any]:
    payload = observation.model_dump(mode="json", exclude_none=False)
    for key in ("benchmark_arm_id", "campaign_id", "run_id"):
        payload.pop(key, None)
    return payload


def _arm_observation(
    base: BenchmarkObservationV2,
    *,
    adapter_id: str,
    generation_index: int,
    history: list[BenchmarkHistoryItemV2],
    requested_generations: int,
) -> BenchmarkObservationV2:
    payload = base.model_dump(mode="json", exclude_none=False)
    payload.update(
        {
            "benchmark_arm_id": adapter_id.replace("/", "-"),
            "campaign_id": "offline-matrix",
            "run_id": f"offline-{adapter_id.replace('/', '-')}",
            "generation_index": generation_index,
            "next_dispatch_ordinal": len(history) + 1,
            "history": [item.model_dump(mode="json") for item in history],
            "simulator_budget_remaining": requested_generations - len(history),
        }
    )
    return BenchmarkObservationV2.model_validate(payload)


def _history_from_evaluation(
    proposal: BenchmarkProposalV1,
    *,
    adapter_id: str,
    generation_index: int,
    dispatch_ordinal: int,
    status: BenchmarkOfflineStatus,
    metric_summary: dict[str, float | int | bool | None],
    failure_code: str | None,
) -> BenchmarkHistoryItemV2:
    def metric_float(name: str) -> float:
        value = metric_summary.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"numeric landscape metric {name} is missing or non-numeric")
        return float(value)

    tracking_error = metric_float("tracking_error")
    constraints = {
        "high_authority_violation": metric_float("high_authority_violation"),
        "low_authority_violation": metric_float("low_authority_violation"),
    }
    if status == "passed":
        outcome = BenchmarkOptimizerOutcomeV1(
            role="objective",
            loss=tracking_error,
            objectives={"tracking_error": tracking_error},
            objective_directions={"tracking_error": "minimize"},
            constraint_violations=constraints,
            feasible=True,
            failure_rate=0.0,
            completed=True,
        )
    else:
        outcome = BenchmarkOptimizerOutcomeV1(
            role="constraint_only",
            loss=None,
            objectives={},
            objective_directions={},
            constraint_violations=constraints,
            feasible=False,
            failure_rate=1.0,
            completed=True,
        )
    return BenchmarkHistoryItemV2(
        candidate_ref=proposal.candidate_ref,
        generation_index=generation_index,
        dispatch_ordinal=dispatch_ordinal,
        parameters=dict(proposal.parameters),
        screening_status=status,
        proposal_context=BenchmarkProposalContextV1(
            proposal_adapter_id=adapter_id,
            reason_code=proposal.reason_code,
            proposal_receipt_sha256=canonical_sha256(proposal.proposal_receipt),
            optimizer_strategy=adapter_id,
            optimizer_metadata={},
        ),
        outcome=outcome,
        failure_code=failure_code,
    )


def run_offline_structural_matrix(
    base_observation: BenchmarkObservationV2,
    *,
    adapter_ids: tuple[str, ...],
    requested_generations: int,
    search_space: SearchSpace,
) -> BenchmarkOfflineMatrixV1:
    """Run equal numeric-evaluation budgets across implemented and fixture LLM arms."""

    if not 1 <= requested_generations <= 128:
        raise ValueError("requested_generations must be in [1, 128]")
    if not adapter_ids or len(adapter_ids) != len(set(adapter_ids)):
        raise ValueError("offline matrix requires unique adapter IDs")
    if canonical_sha256(base_observation.parameter_domain) != canonical_sha256(
        [
            {
                "name": domain.name,
                "baseline": domain.baseline,
                "minimum": domain.minimum,
                "maximum": domain.maximum,
                "step": domain.step,
                "scale": domain.scale,
                "value_type": domain.value_type,
                "choices": list(domain.choices),
                "enabled": domain.enabled,
                "locked": domain.locked,
            }
            for domain in search_space.domains
        ]
    ):
        raise ValueError("numeric landscape search space differs from the shared observation")

    landscape = DeterministicConstrainedLandscapeV1(search_space)
    shared_view = _identity_neutral_observation_payload(base_observation)
    results: list[BenchmarkOfflineArmResultV1] = []
    for adapter_id in adapter_ids:
        descriptor = require_registered_adapter(adapter_id)
        history: list[BenchmarkHistoryItemV2] = []
        provider_turns_attempted = 0
        provider_turns_succeeded = 0
        proposals_dispatched = 0
        evaluations_completed = 0
        statuses: Counter[BenchmarkOfflineStatus] = Counter()
        failures: list[str] = []
        fixture = DeterministicClosedResponseFixtureV1()
        previous_family_state: dict[str, tuple[int, int]] = {}
        for generation_index in range(requested_generations):
            observation = _arm_observation(
                base_observation,
                adapter_id=adapter_id,
                generation_index=generation_index,
                history=history,
                requested_generations=requested_generations,
            )
            try:
                if descriptor.family == "traditional":
                    proposal = create_benchmark_adapter(adapter_id).propose(observation)
                else:
                    execution = execute_offline_llm_arm(
                        adapter_id,
                        observation,
                        provider=fixture,
                        previous_family_state=previous_family_state,
                    )
                    provider_turns_attempted += execution.provider_turns_attempted
                    provider_turns_succeeded += execution.provider_turns_succeeded
                    if execution.proposal is None:
                        failures.append("fixture-llm-abandoned")
                        break
                    if execution.trigger_decision is not None:
                        previous_family_state = dict(execution.trigger_decision.next_family_state)
                    proposal = execution.proposal
                proposals_dispatched += 1
                evaluation = landscape.evaluate(proposal)
                if evaluation.status not in {"passed", "failed", "unsafe"}:
                    raise ValueError("numeric landscape returned an unsupported terminal status")
                evaluations_completed += 1
                statuses[evaluation.status] += 1
                history.append(
                    _history_from_evaluation(
                        proposal,
                        adapter_id=adapter_id,
                        generation_index=generation_index,
                        dispatch_ordinal=len(history) + 1,
                        status=evaluation.status,
                        metric_summary=evaluation.metric_summary,
                        failure_code=evaluation.failure_code,
                    )
                )
            except BenchmarkLLMFixtureExecutionError as exc:
                attempted = exc.safe_receipt["provider_turns_attempted"]
                succeeded = exc.safe_receipt["provider_turns_succeeded"]
                if not isinstance(attempted, int) or not isinstance(succeeded, int):
                    raise RuntimeError(
                        "fixture failure receipt has invalid turn counters"
                    ) from None
                provider_turns_attempted += attempted
                provider_turns_succeeded += succeeded
                failures.append(exc.code)
                break
            except Exception:  # noqa: BLE001 - matrix records failure without hiding denominator.
                failures.append("offline-arm-execution-failed")
                break
        results.append(
            BenchmarkOfflineArmResultV1(
                adapter_id=adapter_id,
                requested_generations=requested_generations,
                proposals_dispatched=proposals_dispatched,
                simulator_evaluations_attempted=proposals_dispatched,
                simulator_evaluations_completed=evaluations_completed,
                provider_turns_attempted=provider_turns_attempted,
                provider_turns_succeeded=provider_turns_succeeded,
                status_counts=dict(sorted(statuses.items())),
                failure_codes=tuple(failures),
                final_history_sha256=canonical_sha256(
                    [item.model_dump(mode="json") for item in history]
                ),
            )
        )
    fairness_passed = all(
        result.simulator_evaluations_attempted == requested_generations
        and result.simulator_evaluations_completed == requested_generations
        and not result.failure_codes
        for result in results
    )
    return BenchmarkOfflineMatrixV1(
        requested_generations_per_arm=requested_generations,
        shared_observation_sha256=canonical_sha256(shared_view),
        shared_parameter_domain_sha256=canonical_sha256(base_observation.parameter_domain),
        results=tuple(results),
        structural_fairness_passed=fairness_passed,
    )


__all__ = [
    "OFFLINE_MATRIX_FIXTURE_ID",
    "OFFLINE_MATRIX_SCHEMA_ID",
    "BenchmarkOfflineArmResultV1",
    "BenchmarkOfflineMatrixV1",
    "BenchmarkOfflineStatus",
    "DeterministicClosedResponseFixtureV1",
    "run_offline_structural_matrix",
]
