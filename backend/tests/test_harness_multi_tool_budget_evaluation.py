from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration import harness_multi_tool_budget_evaluation as evaluation_module
from app.orchestration.harness_multi_tool_budget_evaluation import (
    HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
    build_harness_multi_tool_budget_evaluation,
    build_harness_multi_tool_budget_manifest,
)
from scripts.evaluate_harness_multi_tool_budget import (
    _payloads,
    _semantic_projection,
    _validate_timing_accounting,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
EVALUATOR = BACKEND_ROOT / "scripts" / "evaluate_harness_multi_tool_budget.py"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(payload: dict[str, object], field: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def test_provenance_verification_fails_closed_on_git_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired(cmd=["git", "rev-parse"], timeout=30)

    monkeypatch.setattr(evaluation_module.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out after 30 seconds"):
        evaluation_module._verify_provenance(
            "0" * 40,
            "2026-07-29T00:00:00Z",
        )


def test_equal_budget_multi_tool_evaluation_exercises_verified_live_dispatch() -> None:
    source_commit = _head()
    generated_at = "2026-07-28T18:00:00Z"
    artifact = build_harness_multi_tool_budget_evaluation(
        source_commit=source_commit,
        generated_at=generated_at,
        seed_blocks=(7100,),
    )

    assert artifact["source_commit"] == source_commit
    assert artifact["generated_at"] == generated_at
    assert artifact["claim_boundary"] == HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY
    assert artifact["real_provider_calls"] == 0
    assert artifact["network_calls"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["physical_fidelity"] is False
    assert artifact["llm_quality_claim_permitted"] is False
    assert artifact["optimizer_superiority_claim_permitted"] is False
    assert artifact["causal_harness_benefit_claim_permitted"] is False
    assert artifact["contracts"]["evidence_schema_version"] == "2.9"
    assert artifact["summary"]["block_count"] == 1
    assert artifact["summary"]["configured_budget_parity_count"] == 1
    assert artifact["summary"]["scripted_multi_tool_generation_count"] >= 1
    assert (
        artifact["summary"]["scripted_decision_call_count"]
        == artifact["summary"]["scripted_accounted_provider_call_count"]
    )
    block = artifact["block_rows"][0]
    assert block["configured_budget_equal"] is True
    direct, scripted = block["arms"]
    assert direct["configured_max_total_trials"] == scripted["configured_max_total_trials"]
    assert direct["configured_max_iterations"] == scripted["configured_max_iterations"]
    assert direct["real_provider_calls"] == scripted["real_provider_calls"] == 0
    assert direct["network_calls"] == scripted["network_calls"] == 0
    assert scripted["plan_trace"]["verified_generation_count"] >= 2
    assert scripted["plan_trace"]["multi_tool_generation_count"] >= 1
    assert all(
        "decision_id" not in json.dumps(row, sort_keys=True)
        and "revision_id" not in json.dumps(row, sort_keys=True)
        and "call_id" not in json.dumps(row, sort_keys=True)
        and "proposal_ref" not in json.dumps(row, sort_keys=True)
        for row in scripted["plan_trace"]["provider_visible_history"]
    )
    assert artifact["artifact_sha256"] == _sha256(artifact, "artifact_sha256")
    _validate_timing_accounting(artifact)


def test_semantic_reexecution_ignores_only_validated_clock_observations() -> None:
    source_commit = _head()
    generated_at = "2026-07-28T18:00:00Z"
    first = build_harness_multi_tool_budget_evaluation(
        source_commit=source_commit,
        generated_at=generated_at,
        seed_blocks=(7200,),
    )
    second = build_harness_multi_tool_budget_evaluation(
        source_commit=source_commit,
        generated_at=generated_at,
        seed_blocks=(7200,),
    )

    _validate_timing_accounting(first)
    _validate_timing_accounting(second)
    assert _semantic_projection(first) == _semantic_projection(second)

    tampered = copy.deepcopy(first)
    tampered["block_rows"][0]["arms"][1]["holdout_loss"] += 1.0
    assert _semantic_projection(first) != _semantic_projection(tampered)

    invalid_accounting = copy.deepcopy(first)
    invalid_accounting["summary"]["scripted_plan_decision_wall_ms"] += 1.0
    with pytest.raises(ValueError, match="does not match block accounting"):
        _validate_timing_accounting(invalid_accounting)


def test_multi_tool_evaluation_manifest_and_rendered_files_bind_artifact() -> None:
    source_commit = _head()
    generated_at = "2026-07-28T18:01:00Z"
    artifact = {
        "schema_version": "dronedream.harness-multi-tool-budget-evaluation/v1",
        "source_commit": source_commit,
        "generated_at": generated_at,
        "claim_boundary": HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
        "seed_blocks": [7100],
        "configured_budget": {
            "max_iterations": 2,
            "max_total_trials": 40,
        },
        "contracts": {
            "evidence_schema_version": "2.9",
            "tool_registry_version": "2.1",
        },
        "physical_fidelity": False,
        "real_provider_calls": 0,
        "network_calls": 0,
        "real_credentials_used": False,
        "block_rows": [],
    }
    artifact["artifact_sha256"] = _sha256(artifact, "artifact_sha256")
    manifest = build_harness_multi_tool_budget_manifest(
        source_commit=source_commit,
        generated_at=generated_at,
        artifact=artifact,
    )

    assert manifest["source_commit"] == source_commit
    assert manifest["generated_at"] == generated_at
    assert manifest["artifact_sha256"] == artifact["artifact_sha256"]
    assert manifest["seed_blocks"] == [7100]
    assert manifest["runtime"] == {
        "simulator_backend": "mock",
        "real_provider_calls": 0,
        "network_calls": 0,
        "real_credentials_used": False,
    }
    assert manifest["manifest_sha256"] == _sha256(manifest, "manifest_sha256")
    # A minimal row-less artifact is sufficient to exercise canonical file
    # rendering here; semantic run validation belongs to the campaign test.
    rendered = _payloads(artifact, manifest)
    assert set(rendered) == {
        "harness-multi-tool-budget-evaluation-v1.json",
        "harness-multi-tool-budget-evaluation-v1.csv",
        "harness-multi-tool-budget-evaluation-v1.manifest.json",
        "harness-multi-tool-budget-evaluation-v1.sha256",
    }

    with pytest.raises(ValueError, match="artifact provenance"):
        build_harness_multi_tool_budget_manifest(
            source_commit="0" * 40,
            generated_at=generated_at,
            artifact=artifact,
        )


def test_multi_tool_evaluator_binds_backend_when_launched_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, str(EVALUATOR), "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "--source-commit" in result.stdout
    assert "--generated-at" in result.stdout
