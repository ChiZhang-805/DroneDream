"""Independent boundary corpus for production Harness tool eligibility.

These hand-authored cases are capability-contract regressions, not measured
router quality or simulator performance.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.optimization.scenarios import ScenarioRun
from app.orchestration.harness_context import (
    HARNESS_TOOL_DEFINITIONS,
    HarnessToolId,
    eligible_harness_tools,
)
from app.orchestration.harness_evaluation import (
    HarnessEvalToolHistory,
    HarnessRoutingEvalCase,
    HarnessRoutingStimulus,
    compile_routing_eval_snapshot,
)
from app.orchestration.job_manager import _effective_fidelity_mapping

CORPUS = (
    Path(__file__).parent
    / "fixtures"
    / "harness_tool_eligibility_boundaries_v1.jsonl"
)


def test_tool_eligibility_boundary_corpus_matches_execution_capabilities() -> None:
    seen_ids: set[str] = set()
    case_count = 0
    for line_number, raw_line in enumerate(
        CORPUS.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        case_id = payload["case_id"]
        assert case_id not in seen_ids, f"duplicate case at line {line_number}"
        seen_ids.add(case_id)
        stimulus = HarnessRoutingStimulus.model_validate(payload["stimulus"])
        required = tuple(payload["required_tools"])
        forbidden = tuple(payload["forbidden_tools"])
        assert set(required) <= set(HARNESS_TOOL_DEFINITIONS)
        assert set(forbidden) <= set(HARNESS_TOOL_DEFINITIONS)
        assert not set(required) & set(forbidden)
        snapshot = compile_routing_eval_snapshot(
            HarnessRoutingEvalCase(
                case_id=case_id,
                category="tight_budget",
                stimulus=stimulus,
                acceptable_tools=("cma_es",),
                rationale=payload["rationale"],
            )
        )

        eligible = set(eligible_harness_tools(snapshot))

        assert set(required) <= eligible, case_id
        assert not (set(forbidden) & eligible), case_id
        case_count += 1

    assert case_count == 6


def test_single_seed_scenario_count_never_implies_multi_fidelity() -> None:
    """Exercise the exact boundary across budget, dimension, and history."""

    for parameter_count in (4, 12, 48):
        for remaining_full_candidates in (1, 2, 8):
            stimulus = HarnessRoutingStimulus(
                parameter_count=parameter_count,
                current_generation=4,
                max_iterations=8,
                remaining_trials=4 * remaining_full_candidates,
                trials_per_candidate=4,
                training_case_count=4,
                training_replicate_count=4,
                scored_candidate_count=20,
                feasible_candidate_count=6,
                observed_failure_rate=0.6,
                tool_history=(
                    HarnessEvalToolHistory(
                        tool_id="multi_fidelity_mobo",
                        candidate_count=5,
                        feasible_candidate_count=1,
                        best_score=0.9,
                        failed_trial_count=8,
                        last_generation=4,
                    ),
                ),
            )
            case = HarnessRoutingEvalCase(
                case_id=(
                    f"single_seed_d{parameter_count}_"
                    f"b{remaining_full_candidates}"
                ),
                category="failure_recovery",
                stimulus=stimulus,
                acceptable_tools=("optimizer_portfolio",),
                rationale="Capability-boundary regression only.",
            )

            eligible = set(
                eligible_harness_tools(compile_routing_eval_snapshot(case))
            )

            assert "multi_fidelity_mobo" not in eligible
            assert "optimizer_portfolio" in eligible
            if parameter_count >= 12:
                assert "saasbo" in eligible


def test_replicated_scenario_matrix_exposes_multi_fidelity_at_boundary() -> None:
    required_tool: HarnessToolId = "multi_fidelity_mobo"
    for training_case_count, training_replicate_count in (
        (1, 2),
        (4, 5),
        (4, 8),
    ):
        stimulus = HarnessRoutingStimulus(
            parameter_count=6,
            training_case_count=training_case_count,
            training_replicate_count=training_replicate_count,
            trials_per_candidate=training_replicate_count,
            remaining_trials=training_replicate_count,
            scored_candidate_count=8,
            feasible_candidate_count=4,
        )
        case = HarnessRoutingEvalCase(
            case_id=f"replicated_{training_case_count}_{training_replicate_count}",
            category="tight_budget",
            stimulus=stimulus,
            acceptable_tools=(required_tool,),
            rationale="Capability-boundary regression only.",
        )

        assert required_tool in eligible_harness_tools(
            compile_routing_eval_snapshot(case)
        )


def test_router_multi_fidelity_gate_matches_dispatch_fidelity_mapping() -> None:
    single_seed_runs = [
        ScenarioRun(
            case_id=f"case-{index}",
            scenario_type="nominal",
            seed=index,
            weight=1.0,
            holdout=False,
            config={},
        )
        for index in range(4)
    ]
    replicated_runs = [
        ScenarioRun(
            case_id=f"case-{case_index}",
            scenario_type="nominal",
            seed=seed,
            weight=1.0,
            holdout=False,
            config={},
        )
        for case_index in range(4)
        for seed in (1, 2)
    ]

    single_seed_mapping = _effective_fidelity_mapping(
        single_seed_runs,
        full_trials_per_candidate=4,
    )
    replicated_mapping = _effective_fidelity_mapping(
        replicated_runs,
        full_trials_per_candidate=8,
    )

    assert all(effective == 1.0 for _requested, effective in single_seed_mapping)
    assert any(effective < 1.0 for _requested, effective in replicated_mapping)
