"""Provenance tests for historical and current online routing freezes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration.harness_evaluation import (
    grade_routing_prediction_artifact,
    load_archived_routing_prediction_artifact,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
)

BACKEND_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
CORPUS = Path(__file__).parent / "fixtures" / "harness_routing_eval_v1.jsonl"
EVIDENCE_2_7_PROMPT_1_5 = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-routing-gpt-4.1-2025-04-14-evidence-2.7-20260728.json"
)
EVIDENCE_2_7_PROMPT_1_5_RERUN = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-routing-gpt-4.1-2025-04-14-evidence-2.7-prompt-1.5-rerun-20260728.json"
)
EVIDENCE_2_7_PROMPT_1_6 = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-routing-gpt-4.1-2025-04-14-evidence-2.7-prompt-1.6-20260728.json"
)
EVIDENCE_2_8_PROMPT_1_7 = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-routing-gpt-4.1-2025-04-14-evidence-2.8-prompt-1.7-20260728.json"
)
EVIDENCE_2_8_PROMPT_1_7_MANIFEST = (
    BACKEND_ROOT
    / "evaluation_artifacts"
    / "harness-routing-gpt-4.1-2025-04-14-evidence-2.8-prompt-1.7-20260728.manifest.json"
)
EVALUATOR_SCRIPT = BACKEND_ROOT / "scripts" / "evaluate_harness_router.py"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_current_online_provider_freeze_and_manifest_are_exactly_bound() -> None:
    cases = load_routing_eval_cases(CORPUS)
    artifact = load_routing_prediction_artifact(EVIDENCE_2_8_PROMPT_1_7, cases)
    report = grade_routing_prediction_artifact(artifact, cases)

    assert hashlib.sha256(EVIDENCE_2_8_PROMPT_1_7.read_bytes()).hexdigest() == (
        "d2359e0540aa284cd84262ec4c378369bc3fbab856d8384c3eff56738ef225c4"
    )
    assert artifact.evidence_schema_version == "2.8"
    assert artifact.prompt_template_version == "1.7"
    assert artifact.tool_registry_version == "2.1"
    assert artifact.generation_config.model_dump(mode="json") == {
        "response_format": "json_schema",
        "seed": 20260728,
        "temperature": 0.0,
        "top_p": 1.0,
    }
    assert report.predictions.passed_count == 23
    assert report.predictions.pass_rate == pytest.approx(23 / 24)
    assert report.predictions.category_results["tight_budget"] == {
        "case_count": 3,
        "passed_count": 2,
        "pass_rate": pytest.approx(2 / 3),
    }
    assert report.qualification.qualified is True
    assert report.qualification.failed_requirements == ()

    artifact_text = EVIDENCE_2_8_PROMPT_1_7.read_text(encoding="utf-8").lower()
    assert "openai_api_key" not in artifact_text
    assert "harness_routing_api_key" not in artifact_text
    assert "request_id" not in artifact_text

    manifest = json.loads(EVIDENCE_2_8_PROMPT_1_7_MANIFEST.read_text(encoding="utf-8"))
    unsigned_manifest = dict(manifest)
    declared_manifest_sha256 = unsigned_manifest.pop("manifest_sha256")
    assert _canonical_sha256(unsigned_manifest) == declared_manifest_sha256 == (
        "3ab3830ecf798b3e12845e249a07cde36add0ddcb34b727806f30eb34af4ed37"
    )
    assert manifest["artifact"]["bytes"] == EVIDENCE_2_8_PROMPT_1_7.stat().st_size
    assert manifest["artifact"]["sha256"] == hashlib.sha256(
        EVIDENCE_2_8_PROMPT_1_7.read_bytes()
    ).hexdigest()
    assert manifest["campaign"]["source_commit"] == (
        "aeffaae01a8106f74ff811b39ec26d9d2203d1f6"
    )
    assert manifest["campaign"]["provider_calls"] == len(cases) == 24
    assert manifest["result"]["passed_count"] == 23
    assert manifest["result"]["qualified"] is True
    assert manifest["result"]["failed_cases"] == [
        {
            "acceptable_tools": ["multi_fidelity_mobo", "optimizer_portfolio"],
            "case_id": "tight_budget_expensive_matrix",
            "category": "tight_budget",
            "selected_tool": "turbo",
        }
    ]
    assert manifest["credential_handling"] == {
        "api_key_persisted": False,
        "api_key_printed": False,
        "api_key_source": "process-local environment alias",
        "provider_request_ids_persisted": False,
        "secret_values_in_artifact": False,
    }


def test_archived_prompt_1_6_provider_freeze_remains_exactly_bound() -> None:
    cases = load_routing_eval_cases(CORPUS)

    artifact = load_archived_routing_prediction_artifact(
        EVIDENCE_2_7_PROMPT_1_6,
        cases,
        evidence_schema_version="2.7",
        prompt_template_version="1.6",
        prompt_suite_sha256=(
            "93ca5fdafe123741821f47296e3e8b23cb5f9d68ff9d78bbf2c10af83642bd77"
        ),
    )
    report = grade_routing_prediction_artifact(artifact, cases)

    assert hashlib.sha256(EVIDENCE_2_7_PROMPT_1_6.read_bytes()).hexdigest() == (
        "2cd125346b10bc914c90d889ef43db97714dbbce9f20bbe47b5e0365e39c76e4"
    )
    assert artifact.evidence_schema_version == "2.7"
    assert artifact.prompt_template_version == "1.6"
    assert artifact.corpus_sha256 == (
        "98b94ae1e32f3df7f5d119cefebe0f949fea5f17c537f8688c7d4c05b1d92f89"
    )
    assert artifact.prompt_suite_sha256 == (
        "93ca5fdafe123741821f47296e3e8b23cb5f9d68ff9d78bbf2c10af83642bd77"
    )
    assert report.predictions.passed_count == 24
    assert report.predictions.pass_rate == 1.0
    assert report.qualification.qualified is True
    assert report.qualification.failed_requirements == ()
    assert all(
        row["case_count"] == 3 and row["passed_count"] == 3
        for row in report.predictions.category_results.values()
    )


def test_prompt_1_5_provider_runs_remain_preserved_as_non_current_evidence() -> None:
    cases = load_routing_eval_cases(CORPUS)
    expected = {
        EVIDENCE_2_7_PROMPT_1_5: (
            "fddf588a74ce675cd521172a841a6f5daefe1fe5b5b2c6834979c54df6b73acf"
        ),
        EVIDENCE_2_7_PROMPT_1_5_RERUN: (
            "9e3c198664e79097c6fef540b0d775fc009f148288e8051f3b5be759b1987571"
        ),
    }

    for artifact_path, expected_sha256 in expected.items():
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert payload["evidence_schema_version"] == "2.7"
        assert payload["prompt_template_version"] == "1.5"
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == expected_sha256
        with pytest.raises(ValueError, match="invalid Harness routing prediction artifact"):
            load_routing_prediction_artifact(artifact_path, cases)


def test_evaluator_cli_binds_worktree_backend_from_repository_root() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(EVALUATOR_SCRIPT),
            "--predictions",
            str(EVIDENCE_2_7_PROMPT_1_6),
            "--allow-archived-evidence-2-7-prompt-1-6",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert Path(report["backend_root"]) == BACKEND_ROOT.resolve()
    assert report["evidence_schema_version"] == "2.8"
    assert report["tool_registry_version"] == "2.1"
    assert report["prompt_template_version"] == "1.7"
    assert report["grade"]["passed_count"] == 24
    assert report["comparison"]["qualification"]["qualified"] is True
    assert report["prediction_provenance"]["contract_current"] is False
    assert report["prediction_provenance"]["qualification_scope"] == (
        "archived_evidence_2_7_prompt_1_6"
    )
    assert report["prediction_provenance"]["evidence_schema_version"] == "2.7"
    assert report["prediction_provenance"]["prompt_template_version"] == "1.6"
    assert report["prediction_provenance"]["prompt_suite_sha256"] == (
        "93ca5fdafe123741821f47296e3e8b23cb5f9d68ff9d78bbf2c10af83642bd77"
    )


def test_evaluator_cli_accepts_the_current_online_provider_freeze() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(EVALUATOR_SCRIPT),
            "--predictions",
            str(EVIDENCE_2_8_PROMPT_1_7),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert Path(report["backend_root"]) == BACKEND_ROOT.resolve()
    assert report["evidence_schema_version"] == "2.8"
    assert report["tool_registry_version"] == "2.1"
    assert report["prompt_template_version"] == "1.7"
    assert report["grade"]["passed_count"] == 23
    assert report["grade"]["pass_rate"] == pytest.approx(23 / 24)
    assert report["comparison"]["qualification"]["qualified"] is True
    assert report["prediction_provenance"]["contract_current"] is True
    assert report["prediction_provenance"]["qualification_scope"] == "current_contract"
