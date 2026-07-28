from __future__ import annotations

import hashlib
import json

from app.orchestration.harness_multi_tool_budget_evaluation import (
    HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
    build_harness_multi_tool_budget_evaluation,
    build_harness_multi_tool_budget_manifest,
)
from scripts.evaluate_harness_multi_tool_budget import _payloads


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


def test_equal_budget_multi_tool_evaluation_exercises_verified_live_dispatch() -> None:
    source_commit = "a" * 40
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
    assert artifact["summary"]["scripted_decision_call_count"] == artifact[
        "summary"
    ]["scripted_accounted_provider_call_count"]
    block = artifact["block_rows"][0]
    assert block["configured_budget_equal"] is True
    direct, scripted = block["arms"]
    assert direct["configured_max_total_trials"] == scripted[
        "configured_max_total_trials"
    ]
    assert direct["configured_max_iterations"] == scripted[
        "configured_max_iterations"
    ]
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


def test_multi_tool_evaluation_manifest_and_rendered_files_bind_artifact() -> None:
    source_commit = "b" * 40
    generated_at = "2026-07-28T18:01:00Z"
    artifact = {
        "artifact_sha256": "c" * 64,
        "block_rows": [],
    }
    manifest = build_harness_multi_tool_budget_manifest(
        source_commit=source_commit,
        generated_at=generated_at,
        artifact=artifact,
    )

    assert manifest["source_commit"] == source_commit
    assert manifest["generated_at"] == generated_at
    assert manifest["artifact_sha256"] == "c" * 64
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
