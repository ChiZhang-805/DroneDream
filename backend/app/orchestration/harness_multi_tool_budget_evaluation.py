"""Equal-budget offline evaluation for the live multi-tool Harness dispatcher.

The evaluation runs production Job/Candidate/Trial orchestration on the
deterministic MockSimulatorAdapter. A scripted local planner exercises the same
closed schemas as the provider path but performs no provider or network call.
The direct optimizer portfolio and scripted Harness receive identical configured
generation and Trial ceilings. Realized work and local wall/CPU measurements are
reported rather than normalized away.

This is dispatcher, provenance, and accounting evidence. It is not evidence of
LLM quality, optimizer superiority, PX4/Gazebo fidelity, real-flight performance,
or causal benefit from the Harness.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.orchestration import aggregation, job_manager, trial_executor
from app.orchestration.decision_harness import (
    _generation_plan_history,
    _recent_harness_multi_tool_events,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.harness_outcome_campaign import (
    HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
    HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
    _isolated_session_factory,
    _job_request,
    _network_connect_guard,
    _normalize_outcome,
)
from app.services import jobs as job_services
from app.simulator.mock import MockSimulatorAdapter

HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION = (
    "dronedream.harness-multi-tool-budget-evaluation/v1"
)
HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION = (
    "dronedream.harness-multi-tool-budget-evaluation-manifest/v1"
)
HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY = (
    "Equal configured Trial and generation ceilings on MockSimulatorAdapter. "
    "The scripted local planner exercises production closed schemas, multi-tool "
    "execution, revision, provenance, and cost accounting with zero provider "
    "and network calls. Results do not establish LLM quality, optimizer "
    "superiority, physical fidelity, real-flight performance, or causal Harness "
    "benefit."
)
HARNESS_MULTI_TOOL_BUDGET_EVAL_SEED_BLOCKS = (7100, 8200, 9300)
HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS = (
    "direct_portfolio",
    "scripted_multi_tool",
)

_TERMINAL_JOBS = {"COMPLETED", "FAILED", "CANCELLED"}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class _ScriptedMultiToolClient:
    """Schema-valid local policy used only to exercise the dispatcher."""

    def __init__(self) -> None:
        self.calls = 0
        self.plan_calls = 0
        self.revision_calls = 0

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        del model, system
        self.calls += 1
        payload = json.loads(user)
        if "budget_opportunity" in payload:
            self.plan_calls += 1
            opportunity = payload["budget_opportunity"]
            tool_budgets = opportunity["tool_budgets"]
            capacity = int(opportunity["discretionary_candidates"])
            if not isinstance(tool_budgets, list) or not tool_budgets:
                raise ValueError("scripted planner received no eligible tool budget")
            selected = (
                tool_budgets[:2]
                if len(tool_budgets) >= 2 and capacity >= 2
                else tool_budgets[:1]
            )
            remaining = capacity
            calls: list[dict[str, object]] = []
            for index, budget in enumerate(selected):
                slots_left = len(selected) - index
                allocation = min(
                    int(budget["maximum_allocation"]),
                    max(1, remaining // slots_left),
                )
                calls.append(
                    {
                        "tool_id": budget["tool_id"],
                        "allocation": allocation,
                        "fidelity_mode": "force_full",
                        "focus": ["diversity", "verification"][: 1 + int(index == 0)],
                    }
                )
                remaining -= allocation
            return {
                "schema_version": "1.0",
                "decision": "continue",
                "generation_goal": (
                    "Exercise every currently selected proposal tool under the "
                    "server-issued candidate and Trial ceilings."
                ),
                "tool_calls": calls,
                "stop": {"recommended": False, "reason_code": None},
                "uncertainty": {
                    "level": "medium",
                    "missing_evidence": ["tool_cost_history"],
                },
            }
        if "proposals" in payload:
            self.revision_calls += 1
            proposals = payload["proposals"]
            maximum = int(payload["maximum_dispatch_candidates"])
            if not isinstance(proposals, list) or not proposals:
                raise ValueError("scripted revision received no proposal")
            return {
                "schema_version": "1.0",
                "decision": "dispatch",
                "selected_proposal_refs": [
                    item["proposal_ref"] for item in proposals[:maximum]
                ],
                "rationale": (
                    "Dispatch all locally validated proposals up to the immutable "
                    "server capacity."
                ),
            }
        raise ValueError("scripted client received an unknown prompt contract")


def _drive_job(
    factory: Any,
    *,
    job_id: str,
    client: _ScriptedMultiToolClient | None,
) -> dict[str, object]:
    previous_client = aggregation._llm_client_override
    aggregation.set_llm_client_override(client)
    adapter = MockSimulatorAdapter()
    try:
        with factory() as db:
            if job_manager.start_queued_jobs(db, limit=1) != [job_id]:
                raise RuntimeError("evaluation Job did not enter RUNNING")
        for _step in range(HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS + 24):
            with factory() as db:
                trial_id = trial_executor.claim_and_run_one_pending_trial(
                    db,
                    "multi-tool-budget-evaluation-worker",
                    adapter=adapter,
                )
            if trial_id is not None:
                continue
            with factory() as db:
                aggregation.finalize_ready_jobs(db, limit=1)
            with factory() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    raise RuntimeError("evaluation Job disappeared")
                if job.status in _TERMINAL_JOBS:
                    return _normalize_outcome(db, job_id)
        raise RuntimeError("evaluation Job exceeded bounded orchestration steps")
    finally:
        aggregation.set_llm_client_override(previous_client)


def _plan_trace(db: Session, job: models.Job) -> dict[str, object]:
    events = _recent_harness_multi_tool_events(db, job)
    history = _generation_plan_history(
        events,
        current_generation=max(0, int(job.current_generation or 0)),
    )
    result_count = sum(
        event.event_type == "harness_multi_tool_execution_result"
        for event in events
    )
    if len(history) != result_count:
        raise ValueError("multi-tool evaluation contains an unverified result chain")
    rows = [item.model_dump(mode="json") for item in history]
    return {
        "verified_generation_count": len(rows),
        "multi_tool_generation_count": sum(
            len(row["tool_calls"]) >= 2 for row in rows
        ),
        "provider_visible_history": rows,
        "accounting": {
            "provider_call_count": sum(row["provider_call_count"] for row in rows),
            "plan_decision_wall_ms": round(
                sum(row["plan_decision_wall_ms"] for row in rows),
                3,
            ),
            "revision_wall_ms": round(
                sum(row["revision_wall_ms"] for row in rows),
                3,
            ),
            "tool_execution_wall_ms": round(
                sum(row["tool_execution_wall_ms"] for row in rows),
                3,
            ),
            "actual_tool_cpu_ms": round(
                sum(row["actual_tool_cpu_ms"] for row in rows),
                3,
            ),
            "planned_candidates": sum(row["planned_candidates"] for row in rows),
            "dispatched_candidates": sum(
                row["dispatched_candidates"] for row in rows
            ),
            "dispatched_trials": sum(row["dispatched_trials"] for row in rows),
        },
    }


def _run_arm(seed_block: int, arm: str) -> dict[str, Any]:
    if arm not in HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS:
        raise ValueError(f"unknown evaluation arm: {arm}")
    client = _ScriptedMultiToolClient() if arm == "scripted_multi_tool" else None
    with (
        _network_connect_guard() as network_measurement,
        _isolated_session_factory() as factory,
    ):
        with factory() as db:
            user = models.User(
                email=f"multi-tool-budget-{seed_block}@dronedream.invalid",
                display_name="Multi-tool budget evaluation",
            )
            db.add(user)
            db.flush()
            request = _job_request(seed_block, arm=arm)
            job = job_services._create_job_from_config(
                db,
                user=user,
                req=request,
            )
            job_id = job.id
            db.commit()
        outcome = _drive_job(factory, job_id=job_id, client=client)
        with factory() as db:
            loaded_job = db.get(models.Job, job_id)
            if loaded_job is None:
                raise RuntimeError("evaluation Job disappeared")
            trace = (
                _plan_trace(db, loaded_job)
                if arm == "scripted_multi_tool"
                else {
                    "verified_generation_count": 0,
                    "multi_tool_generation_count": 0,
                    "provider_visible_history": [],
                    "accounting": {
                        "provider_call_count": 0,
                        "plan_decision_wall_ms": 0.0,
                        "revision_wall_ms": 0.0,
                        "tool_execution_wall_ms": 0.0,
                        "actual_tool_cpu_ms": 0.0,
                        "planned_candidates": 0,
                        "dispatched_candidates": 0,
                        "dispatched_trials": 0,
                    },
                }
            )
    if network_measurement.attempt_count:
        raise ValueError("multi-tool evaluation attempted a network connection")
    budget = outcome["budget"]
    if not isinstance(budget, dict):
        raise ValueError("evaluation outcome has no budget projection")
    return {
        "arm": arm,
        "configured_max_iterations": budget["configured_max_iterations"],
        "configured_max_total_trials": budget["configured_max_total_trials"],
        "realized_dispatched_trials": budget["dispatched_trials"],
        "realized_completed_trials": budget["completed_trials"],
        "realized_candidate_count": budget["candidate_count"],
        "terminal_status": outcome["terminal_status"],
        "optimization_outcome": outcome["optimization_outcome"],
        "holdout_loss": outcome["holdout_loss"],
        "failure_count": outcome["failure_count"],
        "evidence_completeness": outcome["evidence_completeness"],
        "real_provider_calls": 0,
        "scripted_decision_calls": 0 if client is None else client.calls,
        "scripted_plan_calls": 0 if client is None else client.plan_calls,
        "scripted_revision_calls": 0 if client is None else client.revision_calls,
        "network_calls": network_measurement.attempt_count,
        "real_credentials_used": False,
        "plan_trace": trace,
        "outcome_sha256": _sha256(outcome),
    }


def build_harness_multi_tool_budget_evaluation(
    *,
    source_commit: str,
    generated_at: str,
    seed_blocks: Iterable[int] = HARNESS_MULTI_TOOL_BUDGET_EVAL_SEED_BLOCKS,
) -> dict[str, object]:
    """Run matched arms and return a self-hashed measurement artifact."""

    if len(source_commit) != 40 or any(
        char not in "0123456789abcdef" for char in source_commit
    ):
        raise ValueError("source_commit must be a lowercase 40-character Git SHA")
    blocks = tuple(seed_blocks)
    if not blocks or len(set(blocks)) != len(blocks):
        raise ValueError("evaluation seed blocks must be non-empty and unique")
    block_rows: list[dict[str, Any]] = []
    for block_index, seed_block in enumerate(blocks, start=1):
        arms = [_run_arm(seed_block, arm) for arm in HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS]
        direct, scripted = arms
        configured_budget_equal = (
            direct["configured_max_iterations"]
            == scripted["configured_max_iterations"]
            == HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS
            and direct["configured_max_total_trials"]
            == scripted["configured_max_total_trials"]
            == HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS
        )
        if not configured_budget_equal:
            raise ValueError("evaluation arms did not receive the same configured budget")
        block_rows.append(
            {
                "block_id": block_index,
                "seed_block": seed_block,
                "configured_budget_equal": configured_budget_equal,
                "realized_trial_delta_scripted_minus_direct": (
                    int(scripted["realized_dispatched_trials"])
                    - int(direct["realized_dispatched_trials"])
                ),
                "arms": arms,
            }
        )
    scripted_rows = [
        row["arms"][1]
        for row in block_rows
        if isinstance(row.get("arms"), list)
    ]
    multi_tool_generation_count = sum(
        int(row["plan_trace"]["multi_tool_generation_count"])
        for row in scripted_rows
    )
    if multi_tool_generation_count < len(block_rows):
        raise ValueError("scripted arm did not exercise multi-tool execution in every block")
    unsigned: dict[str, object] = {
        "schema_version": HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_commit": source_commit,
        "claim_boundary": HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
        "evidence_class": "synthetic_mock_equal_budget_dispatcher_evaluation",
        "physical_fidelity": False,
        "llm_quality_claim_permitted": False,
        "optimizer_superiority_claim_permitted": False,
        "causal_harness_benefit_claim_permitted": False,
        "real_provider_calls": 0,
        "network_calls": 0,
        "real_credentials_used": False,
        "contracts": {
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
        "configured_budget": {
            "max_iterations": HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
            "max_total_trials": HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
        },
        "seed_blocks": list(blocks),
        "block_rows": block_rows,
        "summary": {
            "block_count": len(block_rows),
            "arm_run_count": len(block_rows) * len(HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS),
            "configured_budget_parity_count": sum(
                row["configured_budget_equal"] is True for row in block_rows
            ),
            "scripted_verified_generation_count": sum(
                int(row["plan_trace"]["verified_generation_count"])
                for row in scripted_rows
            ),
            "scripted_multi_tool_generation_count": multi_tool_generation_count,
            "scripted_decision_call_count": sum(
                int(row["scripted_decision_calls"]) for row in scripted_rows
            ),
            "scripted_accounted_provider_call_count": sum(
                int(row["plan_trace"]["accounting"]["provider_call_count"])
                for row in scripted_rows
            ),
            "scripted_plan_decision_wall_ms": round(
                sum(
                    float(row["plan_trace"]["accounting"]["plan_decision_wall_ms"])
                    for row in scripted_rows
                ),
                3,
            ),
            "scripted_revision_wall_ms": round(
                sum(
                    float(row["plan_trace"]["accounting"]["revision_wall_ms"])
                    for row in scripted_rows
                ),
                3,
            ),
            "scripted_tool_execution_wall_ms": round(
                sum(
                    float(row["plan_trace"]["accounting"]["tool_execution_wall_ms"])
                    for row in scripted_rows
                ),
                3,
            ),
            "scripted_actual_tool_cpu_ms": round(
                sum(
                    float(row["plan_trace"]["accounting"]["actual_tool_cpu_ms"])
                    for row in scripted_rows
                ),
                3,
            ),
        },
    }
    return {**unsigned, "artifact_sha256": _sha256(unsigned)}


def build_harness_multi_tool_budget_manifest(
    *,
    source_commit: str,
    generated_at: str,
    artifact: dict[str, object],
) -> dict[str, object]:
    """Bind the measured artifact to exact code, policy, and claim scope."""

    unsigned: dict[str, object] = {
        "schema_version": HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_commit": source_commit,
        "artifact_schema_version": HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION,
        "artifact_sha256": artifact["artifact_sha256"],
        "claim_boundary": HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
        "seed_blocks": list(HARNESS_MULTI_TOOL_BUDGET_EVAL_SEED_BLOCKS),
        "arms": list(HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS),
        "configured_budget": {
            "max_iterations": HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
            "max_total_trials": HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
        },
        "contracts": {
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        },
        "runtime": {
            "simulator_backend": "mock",
            "real_provider_calls": 0,
            "network_calls": 0,
            "real_credentials_used": False,
        },
    }
    return {**unsigned, "manifest_sha256": _sha256(unsigned)}


__all__ = [
    "HARNESS_MULTI_TOOL_BUDGET_EVAL_ARMS",
    "HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY",
    "HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION",
    "HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION",
    "HARNESS_MULTI_TOOL_BUDGET_EVAL_SEED_BLOCKS",
    "build_harness_multi_tool_budget_evaluation",
    "build_harness_multi_tool_budget_manifest",
]
