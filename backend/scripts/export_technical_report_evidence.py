"""Export provenance-bound evidence for the DroneDream technical report.

The exporter deliberately keeps evidence classes separate.  A development
routing corpus is not a simulator outcome, and the synthetic ten-scenario
campaign is never presented as physical PX4/Gazebo performance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_ablation import (  # noqa: E402
    load_harness_ablation_artifact,
)
from app.orchestration.harness_context import (  # noqa: E402
    HARNESS_TOOL_DEFINITIONS,
    HarnessToolId,
)
from app.orchestration.harness_evaluation import (  # noqa: E402
    build_routing_eval_report,
    load_routing_eval_cases,
)
from app.orchestration.harness_outcome_campaign import (  # noqa: E402
    load_harness_outcome_campaign,
)
from app.orchestration.harness_routing_holdout import (  # noqa: E402
    load_locked_routing_policy_holdout,
    load_locked_routing_policy_result,
)

REPORT_EVIDENCE_SCHEMA_VERSION = "dronedream.technical-report-evidence.v4"
ARCHIVED_ROUTING_CORPUS_SHA256 = (
    "4968b0a9639d59474c00402dcd261a241377bdb57a6273554f4d6ad0d1172625"
)
ARCHIVED_ROUTING_PROMPT_SUITE_SHA256 = (
    "d300d0516378974fb57be896b155ef1a537278594b03c0ecbdceff9ade26dc59"
)
DEFAULT_ROUTING_CORPUS = BACKEND_ROOT / "tests" / "fixtures" / "harness_routing_eval_v1.jsonl"
DEFAULT_ROUTING_PREDICTIONS = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-routing-gpt-4.1-2025-04-14.json"
)
DEFAULT_SIMULATION_COVERAGE = (
    BACKEND_ROOT / "evaluation_artifacts" / "simulation-coverage-mock-v2.json"
)
DEFAULT_HARNESS_ABLATIONS = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-contract-ablation-v1.json"
)
DEFAULT_HARNESS_OUTCOME_CAMPAIGN = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-fallback-outcome-campaign-v1.json"
)
DEFAULT_ROUTING_HOLDOUT_CORPUS = (
    BACKEND_ROOT / "tests" / "fixtures" / "harness_routing_policy_holdout_v1.jsonl"
)
DEFAULT_ROUTING_HOLDOUT_MANIFEST = (
    BACKEND_ROOT / "tests" / "fixtures" / "harness_routing_policy_holdout_v2.manifest.json"
)
DEFAULT_ROUTING_HOLDOUT_RESULT = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-routing-policy-holdout-v2.json"
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_finite_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _as_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def _load_archived_routing_predictions(
    path: Path,
    *,
    case_ids: set[str],
) -> tuple[dict[str, HarnessToolId], dict[str, Any]]:
    """Validate the historical 2.4/1.1 freeze without relabeling it current."""

    payload = _load_json_object(path)
    expected = {
        "schema_version": "1.0",
        "corpus_sha256": ARCHIVED_ROUTING_CORPUS_SHA256,
        "prompt_suite_sha256": ARCHIVED_ROUTING_PROMPT_SUITE_SHA256,
        "evidence_schema_version": "2.4",
        "tool_registry_version": "2.1",
        "prompt_template_version": "1.1",
    }
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            raise ValueError(f"archived routing artifact {key} does not match frozen contract")
    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, dict) or set(raw_predictions) != case_ids:
        raise ValueError("archived routing predictions must exactly cover the development corpus")
    predictions: dict[str, HarnessToolId] = {}
    for case_id, raw in raw_predictions.items():
        if not isinstance(raw, dict) or set(raw) != {"rationale", "selected_tool"}:
            raise ValueError("archived routing prediction has an invalid closed shape")
        tool_id = raw.get("selected_tool")
        rationale = raw.get("rationale")
        if tool_id not in HARNESS_TOOL_DEFINITIONS:
            raise ValueError("archived routing prediction selected an unknown tool")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("archived routing prediction requires a rationale")
        predictions[case_id] = cast(HarnessToolId, tool_id)
    return predictions, payload


def summarize_simulation_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and summarize the frozen mock campaign without upgrading its claim."""

    if payload.get("schema_version") != ("dronedream.simulation-coverage-campaign.v1"):
        raise ValueError("unexpected simulation coverage schema")
    if payload.get("physical_fidelity") is not False:
        raise ValueError("technical-report mock evidence must remain non-physical")
    if payload.get("simulator_backend") != "mock":
        raise ValueError("technical-report mock evidence must use backend=mock")

    scenario_types = payload.get("scenario_types")
    if (
        not isinstance(scenario_types, list)
        or not scenario_types
        or any(not isinstance(item, str) or not item for item in scenario_types)
        or len(set(scenario_types)) != len(scenario_types)
    ):
        raise ValueError("scenario_types must be unique non-empty strings")

    baseline = payload.get("baseline")
    selected = payload.get("selected")
    if not isinstance(baseline, dict) or not isinstance(selected, dict):
        raise ValueError("baseline and selected campaign summaries are required")
    baseline_by_scenario = baseline.get("holdout_by_scenario")
    selected_by_scenario = selected.get("holdout_by_scenario")
    if (
        not isinstance(baseline_by_scenario, dict)
        or not isinstance(selected_by_scenario, dict)
        or set(baseline_by_scenario) != set(scenario_types)
        or set(selected_by_scenario) != set(scenario_types)
    ):
        raise ValueError("holdout scenario mappings must exactly cover scenario_types")

    rows: list[dict[str, Any]] = []
    for scenario in scenario_types:
        baseline_loss = _as_finite_float(
            baseline_by_scenario[scenario],
            field=f"baseline.holdout_by_scenario.{scenario}",
        )
        selected_loss = _as_finite_float(
            selected_by_scenario[scenario],
            field=f"selected.holdout_by_scenario.{scenario}",
        )
        if baseline_loss <= 0:
            raise ValueError("baseline scenario losses must be positive")
        absolute_improvement = baseline_loss - selected_loss
        if absolute_improvement <= 0:
            raise ValueError(f"selected result did not improve scenario {scenario}")
        rows.append(
            {
                "scenario": scenario,
                "baseline_holdout_loss": baseline_loss,
                "selected_holdout_loss": selected_loss,
                "absolute_improvement": absolute_improvement,
                "relative_improvement_rate": absolute_improvement / baseline_loss,
            }
        )

    baseline_loss = _as_finite_float(
        baseline.get("holdout_loss"),
        field="baseline.holdout_loss",
    )
    selected_loss = _as_finite_float(
        selected.get("holdout_loss"),
        field="selected.holdout_loss",
    )
    if baseline_loss <= 0 or selected_loss >= baseline_loss:
        raise ValueError("aggregate holdout loss must improve over baseline")
    recomputed_improvement = (baseline_loss - selected_loss) / baseline_loss
    declared_improvement = _as_finite_float(
        payload.get("baseline_to_selected_improvement_rate"),
        field="baseline_to_selected_improvement_rate",
    )
    if not math.isclose(
        recomputed_improvement,
        declared_improvement,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("declared aggregate improvement does not recompute")
    if payload.get("all_scenarios_improved") is not True:
        raise ValueError("all_scenarios_improved must be true")

    candidate_budget = _as_positive_int(
        payload.get("candidate_budget"),
        field="candidate_budget",
    )
    evaluated_candidates = _as_positive_int(
        payload.get("evaluated_candidate_count"),
        field="evaluated_candidate_count",
    )
    if evaluated_candidates > candidate_budget:
        raise ValueError("evaluated candidates exceed the declared budget")

    return {
        "evidence_class": "synthetic_mock_campaign",
        "claim_boundary": (
            "Validates deterministic search, scenario aggregation, and holdout "
            "logic only; it is not PX4/Gazebo or real-flight performance."
        ),
        "physical_fidelity": False,
        "simulator_backend": "mock",
        "scenario_count": len(scenario_types),
        "candidate_budget": candidate_budget,
        "evaluated_candidate_count": evaluated_candidates,
        "exhaustive_oracle_candidate_count": _as_positive_int(
            payload.get("exhaustive_oracle_candidate_count"),
            field="exhaustive_oracle_candidate_count",
        ),
        "baseline_holdout_loss": baseline_loss,
        "selected_holdout_loss": selected_loss,
        "relative_improvement_rate": recomputed_improvement,
        "holdout_oracle_regret": _as_finite_float(
            payload.get("holdout_oracle_regret"),
            field="holdout_oracle_regret",
        ),
        "scenario_rows": rows,
    }


def build_report_evidence_bundle(
    *,
    routing_corpus_path: Path = DEFAULT_ROUTING_CORPUS,
    routing_predictions_path: Path = DEFAULT_ROUTING_PREDICTIONS,
    simulation_coverage_path: Path = DEFAULT_SIMULATION_COVERAGE,
    harness_ablations_path: Path = DEFAULT_HARNESS_ABLATIONS,
    harness_outcome_campaign_path: Path = DEFAULT_HARNESS_OUTCOME_CAMPAIGN,
    routing_holdout_corpus_path: Path = DEFAULT_ROUTING_HOLDOUT_CORPUS,
    routing_holdout_manifest_path: Path = DEFAULT_ROUTING_HOLDOUT_MANIFEST,
    routing_holdout_result_path: Path = DEFAULT_ROUTING_HOLDOUT_RESULT,
) -> dict[str, Any]:
    """Build a deterministic report bundle from verified repository artifacts."""

    cases = load_routing_eval_cases(routing_corpus_path)
    predictions, archived_artifact = _load_archived_routing_predictions(
        routing_predictions_path,
        case_ids={case.case_id for case in cases},
    )
    routing_report = build_routing_eval_report(cases, predictions)
    prediction_counts = Counter(predictions.values())

    routing = {
        "evidence_class": "development_routing_corpus",
        "claim_boundary": (
            "Measures acceptable optimizer-tool selection on a versioned "
            "development corpus; it is not a simulator outcome benchmark."
        ),
        "contract_current": False,
        "qualification_scope": "archived_evidence_2_4_prompt_1_1",
        "current_evidence_schema_version": "2.5",
        "current_prompt_template_version": "1.2",
        "model_snapshot": archived_artifact["model_snapshot"],
        "provider": archived_artifact["provider"],
        "case_count": routing_report.predictions.case_count,
        "passed_count": routing_report.predictions.passed_count,
        "pass_rate": routing_report.predictions.pass_rate,
        "category_rows": [
            {"category": category, **result}
            for category, result in sorted(routing_report.predictions.category_results.items())
        ],
        "tool_selection_rows": [
            {"tool": tool, "selected_count": count}
            for tool, count in sorted(prediction_counts.items())
        ],
        "uniform_random_expected_pass_rate": (
            routing_report.baselines.uniform_random_expected_pass_rate
        ),
        "best_constant_pass_rate": (routing_report.baselines.best_constant_pass_rate),
        "best_constant_tools": list(routing_report.baselines.best_constant_tools),
        "absolute_lift_over_uniform_random": (routing_report.absolute_lift_over_uniform_random),
        "absolute_lift_over_best_constant": (routing_report.absolute_lift_over_best_constant),
        "qualified": routing_report.qualification.qualified,
        "failed_requirements": list(routing_report.qualification.failed_requirements),
    }
    coverage_payload = _load_json_object(simulation_coverage_path)
    coverage = summarize_simulation_coverage(coverage_payload)
    ablation_artifact = load_harness_ablation_artifact(harness_ablations_path)
    harness_ablations = {
        "evidence_class": ablation_artifact["evidence_class"],
        "claim_boundary": ablation_artifact["claim_boundary"],
        "causal_claim_permitted": ablation_artifact["causal_claim_permitted"],
        "physical_fidelity": ablation_artifact["physical_fidelity"],
        "live_model_calls": ablation_artifact["live_model_calls"],
        "simulator_runs": ablation_artifact["simulator_runs"],
        "artifact_sha256": ablation_artifact["artifact_sha256"],
        "summary": ablation_artifact["summary"],
        "component_rows": ablation_artifact["component_rows"],
    }
    outcome_artifact = load_harness_outcome_campaign(
        harness_outcome_campaign_path
    )
    harness_outcome_rows: list[dict[str, Any]] = []
    for block in outcome_artifact["block_rows"]:
        direct_hash = next(
            arm["outcome_sha256"]
            for arm in block["arms"]
            if arm["arm"] == "direct_portfolio"
        )
        for arm in block["arms"]:
            outcome = arm["outcome"]
            budget = outcome["budget"]
            harness_outcome_rows.append(
                {
                    "block_id": block["block_id"],
                    "seed_block": block["seed_block"],
                    "arm": arm["arm"],
                    "provider_calls": arm["provider_calls"],
                    "network_calls": arm["network_calls"],
                    "candidate_count": budget["candidate_count"],
                    "trial_count": budget["trial_count"],
                    "dispatched_trials": budget["dispatched_trials"],
                    "winner_candidate_key": outcome["winner"]["candidate_key"],
                    "holdout_loss": outcome["holdout_loss"],
                    "failure_count": outcome["failure_count"],
                    "evidence_completeness_rate": outcome[
                        "evidence_completeness"
                    ]["completeness_rate"],
                    "exact_match_to_direct_portfolio": (
                        arm["outcome_sha256"] == direct_hash
                    ),
                }
            )
    harness_outcome_campaign = {
        "evidence_class": outcome_artifact["evidence_class"],
        "claim_label": outcome_artifact["claim_label"],
        "claim_boundary": outcome_artifact["claim_boundary"],
        "physical_fidelity": outcome_artifact["physical_fidelity"],
        "simulator_backend": outcome_artifact["simulator_backend"],
        "live_model_calls": outcome_artifact["live_model_calls"],
        "network_calls": outcome_artifact["network_calls"],
        "network_connect_guard_enforced": all(
            arm["network_connect_guard_enforced"] is True
            for block in outcome_artifact["block_rows"]
            for arm in block["arms"]
        ),
        "real_credentials_used": outcome_artifact["real_credentials_used"],
        "llm_superiority_claim_permitted": outcome_artifact[
            "llm_superiority_claim_permitted"
        ],
        "harness_causal_benefit_claim_permitted": outcome_artifact[
            "harness_causal_benefit_claim_permitted"
        ],
        "px4_or_flight_claim_permitted": outcome_artifact[
            "px4_or_flight_claim_permitted"
        ],
        "artifact_sha256": outcome_artifact["artifact_sha256"],
        "protocol": outcome_artifact["protocol"],
        "summary": outcome_artifact["summary"],
        "arm_rows": harness_outcome_rows,
    }
    holdout_bundle = load_locked_routing_policy_holdout(
        routing_holdout_corpus_path,
        routing_holdout_manifest_path,
        routing_corpus_path,
    )
    holdout_result = load_locked_routing_policy_result(
        routing_holdout_result_path,
        holdout_bundle,
    )
    holdout_category_counts: Counter[str] = Counter()
    holdout_category_passes: Counter[str] = Counter()
    for grade in holdout_result.grades:
        holdout_category_counts[grade.category] += 1
        holdout_category_passes[grade.category] += int(grade.passed)
    routing_policy_holdout = {
        "evidence_class": holdout_result.evidence_class,
        "claim_boundary": (
            "Measures exact production tool-eligibility sets on a separate, "
            "hash-locked deterministic policy corpus. It makes no LLM routing "
            "quality, simulator outcome, or permanent-blindness claim."
        ),
        "corpus_role": holdout_result.source_role,
        "case_count": holdout_result.case_count,
        "passed_count": holdout_result.passed_count,
        "pass_rate": holdout_result.pass_rate,
        "qualified": holdout_result.qualified,
        "online_calls": 0,
        "simulator_runs": 0,
        "feedback_writebacks": 0,
        "corpus_sha256": holdout_result.corpus_sha256,
        "manifest_sha256": holdout_result.manifest_sha256,
        "policy_input_suite_sha256": holdout_result.policy_input_suite_sha256,
        "development_corpus_sha256": holdout_result.development_corpus_sha256,
        "category_rows": [
            {
                "category": category,
                "case_count": holdout_category_counts[category],
                "passed_count": holdout_category_passes[category],
                "pass_rate": (
                    holdout_category_passes[category] / holdout_category_counts[category]
                ),
            }
            for category in sorted(holdout_category_counts)
        ],
    }
    sources = {
        "routing_corpus": {
            "path": routing_corpus_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(routing_corpus_path),
        },
        "routing_predictions": {
            "path": routing_predictions_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(routing_predictions_path),
        },
        "simulation_coverage": {
            "path": simulation_coverage_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(simulation_coverage_path),
        },
        "harness_ablations": {
            "path": harness_ablations_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(harness_ablations_path),
        },
        "harness_outcome_campaign": {
            "path": harness_outcome_campaign_path.relative_to(
                REPOSITORY_ROOT
            ).as_posix(),
            "sha256": _sha256_file(harness_outcome_campaign_path),
        },
        "routing_policy_holdout_corpus": {
            "path": routing_holdout_corpus_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(routing_holdout_corpus_path),
        },
        "routing_policy_holdout_manifest": {
            "path": routing_holdout_manifest_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(routing_holdout_manifest_path),
        },
        "routing_policy_holdout_result": {
            "path": routing_holdout_result_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": _sha256_file(routing_holdout_result_path),
        },
    }
    unsigned_bundle: dict[str, Any] = {
        "schema_version": REPORT_EVIDENCE_SCHEMA_VERSION,
        "sources": sources,
        "routing": routing,
        "simulation_coverage": coverage,
        "harness_ablations": harness_ablations,
        "harness_outcome_campaign": harness_outcome_campaign,
        "routing_policy_holdout": routing_policy_holdout,
    }
    return {
        **unsigned_bundle,
        "bundle_sha256": hashlib.sha256(
            _canonical_json(unsigned_bundle).encode("utf-8")
        ).hexdigest(),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report_evidence_bundle(
    bundle: dict[str, Any],
    *,
    output_path: Path,
    csv_directory: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if csv_directory is None:
        return
    routing = bundle["routing"]
    coverage = bundle["simulation_coverage"]
    harness_ablations = bundle["harness_ablations"]
    harness_outcome_campaign = bundle["harness_outcome_campaign"]
    routing_policy_holdout = bundle["routing_policy_holdout"]
    _write_csv(
        csv_directory / "routing_categories.csv",
        routing["category_rows"],
    )
    _write_csv(
        csv_directory / "routing_tool_selection.csv",
        routing["tool_selection_rows"],
    )
    _write_csv(
        csv_directory / "synthetic_scenario_holdout.csv",
        coverage["scenario_rows"],
    )
    _write_csv(
        csv_directory / "harness_contract_ablations.csv",
        harness_ablations["component_rows"],
    )
    _write_csv(
        csv_directory / "harness_fallback_outcomes.csv",
        harness_outcome_campaign["arm_rows"],
    )
    _write_csv(
        csv_directory / "routing_policy_holdout_categories.csv",
        routing_policy_holdout["category_rows"],
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSON evidence bundle.",
    )
    parser.add_argument(
        "--csv-directory",
        type=Path,
        help="Optional directory for chart-ready CSV tables.",
    )
    parser.add_argument(
        "--routing-corpus",
        type=Path,
        default=DEFAULT_ROUTING_CORPUS,
    )
    parser.add_argument(
        "--routing-predictions",
        type=Path,
        default=DEFAULT_ROUTING_PREDICTIONS,
    )
    parser.add_argument(
        "--simulation-coverage",
        type=Path,
        default=DEFAULT_SIMULATION_COVERAGE,
    )
    parser.add_argument(
        "--harness-ablations",
        type=Path,
        default=DEFAULT_HARNESS_ABLATIONS,
    )
    parser.add_argument(
        "--harness-outcome-campaign",
        type=Path,
        default=DEFAULT_HARNESS_OUTCOME_CAMPAIGN,
    )
    parser.add_argument(
        "--routing-holdout-corpus",
        type=Path,
        default=DEFAULT_ROUTING_HOLDOUT_CORPUS,
    )
    parser.add_argument(
        "--routing-holdout-manifest",
        type=Path,
        default=DEFAULT_ROUTING_HOLDOUT_MANIFEST,
    )
    parser.add_argument(
        "--routing-holdout-result",
        type=Path,
        default=DEFAULT_ROUTING_HOLDOUT_RESULT,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bundle = build_report_evidence_bundle(
        routing_corpus_path=args.routing_corpus.resolve(),
        routing_predictions_path=args.routing_predictions.resolve(),
        simulation_coverage_path=args.simulation_coverage.resolve(),
        harness_ablations_path=args.harness_ablations.resolve(),
        harness_outcome_campaign_path=args.harness_outcome_campaign.resolve(),
        routing_holdout_corpus_path=args.routing_holdout_corpus.resolve(),
        routing_holdout_manifest_path=args.routing_holdout_manifest.resolve(),
        routing_holdout_result_path=args.routing_holdout_result.resolve(),
    )
    write_report_evidence_bundle(
        bundle,
        output_path=args.output.resolve(),
        csv_directory=(args.csv_directory.resolve() if args.csv_directory is not None else None),
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "bundle_sha256": bundle["bundle_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
