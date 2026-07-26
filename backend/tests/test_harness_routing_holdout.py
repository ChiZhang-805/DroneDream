"""Isolation and reproducibility tests for the locked routing-policy holdout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestration.harness_evaluation import (
    HarnessRoutingGenerationConfig,
    assert_routing_result_flow,
    load_routing_eval_cases,
)
from app.orchestration.harness_routing_campaign import (
    run_harness_routing_campaign,
)
from app.orchestration.harness_routing_holdout import (
    evaluate_locked_routing_policy_holdout,
    load_locked_routing_policy_holdout,
    load_locked_routing_policy_result,
    write_locked_routing_policy_result,
)

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "harness_routing_policy_holdout_v1.jsonl"
MANIFEST = FIXTURES / "harness_routing_policy_holdout_v1.manifest.json"
DEVELOPMENT = FIXTURES / "harness_routing_eval_v1.jsonl"
RESULT = (
    Path(__file__).parents[1] / "evaluation_artifacts" / "harness-routing-policy-holdout-v1.json"
)


class _ForbiddenClient:
    def generate(self, *, model: str, system: str, user: str) -> dict[str, object]:
        raise AssertionError(f"locked holdout must not call provider: {model=} {system=} {user=}")


def test_locked_holdout_is_hash_bound_and_disjoint_from_development() -> None:
    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)
    development = load_routing_eval_cases(DEVELOPMENT)

    assert bundle.manifest.corpus_role == "locked_holdout"
    assert bundle.manifest.evidence_class == "deterministic_router_policy_holdout"
    assert bundle.manifest.result_policy == "artifact_only_no_writeback"
    assert len(bundle.cases) == 16
    assert len(development) == 24
    assert not ({case.case_id for case in bundle.cases} & {case.case_id for case in development})


def test_locked_holdout_exactly_matches_current_eligibility_policy() -> None:
    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)

    result = evaluate_locked_routing_policy_holdout(bundle)

    assert result.evidence_class == "deterministic_router_policy_holdout"
    assert result.case_count == 16
    assert result.passed_count == 16
    assert result.pass_rate == 1.0
    assert result.qualified is True
    assert all(grade.passed for grade in result.grades)


def test_committed_holdout_result_reproduces_without_online_calls() -> None:
    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)

    result = load_locked_routing_policy_result(RESULT, bundle)

    assert result.qualified is True
    assert result.result_destination == "evaluation_artifact"


@pytest.mark.parametrize(
    "destination",
    ["development_evidence", "router_training", "runtime_feedback"],
)
def test_locked_holdout_rejects_every_adaptive_writeback(
    destination: str,
    tmp_path: Path,
) -> None:
    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)
    result = evaluate_locked_routing_policy_holdout(bundle)

    with pytest.raises(ValueError, match="evaluation-only"):
        assert_routing_result_flow("locked_holdout", destination)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="evaluation-only"):
        write_locked_routing_policy_result(
            tmp_path / "forbidden.json",
            result,
            destination=destination,  # type: ignore[arg-type]
        )
    assert not (tmp_path / "forbidden.json").exists()


def test_provider_campaign_rejects_locked_holdout_before_client_call() -> None:
    development_cases = load_routing_eval_cases(DEVELOPMENT)

    with pytest.raises(ValueError, match="evaluation-only"):
        run_harness_routing_campaign(
            development_cases[:1],
            provider="offline-test",
            model_snapshot="never-called",
            generation_config=HarnessRoutingGenerationConfig(),
            client_factory=lambda _schema: _ForbiddenClient(),
            source_role="locked_holdout",
        )


def test_holdout_cannot_be_loaded_as_development_examples() -> None:
    with pytest.raises(ValueError, match="invalid Harness routing case"):
        load_routing_eval_cases(CORPUS)


def test_manifest_and_result_tampering_fail_closed(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["corpus_sha256"] = "0" * 64
    mutated_manifest = tmp_path / MANIFEST.name
    mutated_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="corpus_sha256"):
        load_locked_routing_policy_holdout(CORPUS, mutated_manifest, DEVELOPMENT)

    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)
    artifact = json.loads(RESULT.read_text(encoding="utf-8"))
    artifact["grades"][0]["passed"] = False
    mutated_result = tmp_path / RESULT.name
    mutated_result.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid locked"):
        load_locked_routing_policy_result(mutated_result, bundle)


def test_result_writer_is_create_only(tmp_path: Path) -> None:
    bundle = load_locked_routing_policy_holdout(CORPUS, MANIFEST, DEVELOPMENT)
    result = evaluate_locked_routing_policy_holdout(bundle)
    output = tmp_path / "result.json"
    output.write_text("keep-existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_locked_routing_policy_result(output, result)

    assert output.read_text(encoding="utf-8") == "keep-existing"
