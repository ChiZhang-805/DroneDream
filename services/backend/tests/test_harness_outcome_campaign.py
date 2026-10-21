from __future__ import annotations

import csv
import hashlib
import json
import socket
from pathlib import Path
from typing import Any, cast

import pytest

from app.orchestration.harness_fallback_contract_campaign import (
    HARNESS_FALLBACK_CONTRACT_ARMS,
    HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY,
    HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM,
    build_harness_fallback_contract_campaign,
    verify_harness_fallback_contract_campaign,
)
from app.orchestration.harness_outcome_campaign import (
    HARNESS_OUTCOME_CAMPAIGN_ARMS,
    HARNESS_OUTCOME_CAMPAIGN_CLAIM_BOUNDARY,
    HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS,
    SyntheticNetworkConnectBlocked,
    _drive_job,
    _network_connect_guard,
    load_harness_outcome_campaign,
    verify_harness_outcome_campaign,
)
from app.schemas import JobCreateRequest
from scripts.evaluate_harness_fallback_contract_campaign import (
    write_harness_fallback_contract_files,
)
from scripts.evaluate_harness_outcome_campaign import (
    write_harness_outcome_campaign_files,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
JSON_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-outcome-campaign-v1.json"
CSV_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-outcome-campaign-v1.csv"
SHA256_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-outcome-campaign-v1.sha256"
CURRENT_JSON_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-contract-campaign-v3.json"
CURRENT_CSV_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-contract-campaign-v3.csv"
CURRENT_SHA256_ARTIFACT = ARTIFACT_ROOT / "harness-fallback-contract-campaign-v3.sha256"


def test_committed_campaign_is_strictly_equivalent_and_claim_bounded() -> None:
    artifact = load_harness_outcome_campaign(JSON_ARTIFACT)

    assert artifact["claim_label"] == "SYNTHETIC_MOCK"
    assert artifact["physical_fidelity"] is False
    assert artifact["simulator_backend"] == "mock"
    assert artifact["live_model_calls"] is False
    assert artifact["network_calls"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["llm_superiority_claim_permitted"] is False
    assert artifact["harness_causal_benefit_claim_permitted"] is False
    assert artifact["px4_or_flight_claim_permitted"] is False
    assert artifact["summary"] == {
        "seed_block_count": 5,
        "arm_run_count": 15,
        "total_persisted_trials": 579,
        "fallback_comparison_count": 10,
        "exact_outcome_match_count": 10,
        "all_fallback_outcomes_match_direct_portfolio": True,
        "all_evidence_complete": True,
    }
    assert [row["seed_block"] for row in artifact["block_rows"]] == list(
        HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS
    )
    for block in artifact["block_rows"]:
        assert [arm["arm"] for arm in block["arms"]] == list(HARNESS_OUTCOME_CAMPAIGN_ARMS)
        assert len({arm["outcome_sha256"] for arm in block["arms"]}) == 1
        assert all(
            arm["outcome"]["evidence_completeness"]["completeness_rate"] == 1.0
            for arm in block["arms"]
        )


def test_current_fallback_campaign_matches_current_production_contracts() -> None:
    current = verify_harness_fallback_contract_campaign(
        json.loads(CURRENT_JSON_ARTIFACT.read_text(encoding="utf-8"))
    )
    assert current == build_harness_fallback_contract_campaign()
    assert current["claim_boundary"] == HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY
    assert current["methodology"]["reference_arm"] == (HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM)
    assert tuple(current["methodology"]["arms"]) == HARNESS_FALLBACK_CONTRACT_ARMS
    assert current["summary"] == {
        "seed_block_count": 5,
        "arm_run_count": 15,
        "total_persisted_trials": 474,
        "fallback_comparison_count": 10,
        "exact_outcome_match_count": 10,
        "all_fallback_outcomes_match_deterministic_baseline": True,
        "all_evidence_complete": True,
    }
    assert current["methodology"]["nondeterministic_fields_excluded"] == [
        "database_primary_keys",
        "timestamps",
        "worker_ids",
        "filesystem_paths",
        "evidence_ids",
        "harness_decision_ids",
        "harness_revision_ids",
        "harness_call_ids",
        "wall_and_cpu_timings",
    ]

    def contains_evidence_id(value: object) -> bool:
        if isinstance(value, dict):
            return "evidence_id" in value or any(
                contains_evidence_id(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(contains_evidence_id(item) for item in value)
        return False

    assert not contains_evidence_id(current["block_rows"])


def test_current_fallback_verifier_rejects_missing_tool_execution_trace() -> None:
    artifact = json.loads(CURRENT_JSON_ARTIFACT.read_text(encoding="utf-8"))
    execution = artifact["block_rows"][0]["arms"][0]["fallback_trace"][
        "generation_rows"
    ][0]["execution"]
    assert execution["tool_calls"]
    execution["tool_calls"] = []
    unsigned = {
        key: value for key, value in artifact.items() if key != "artifact_sha256"
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="declared current fallback contract"):
        verify_harness_fallback_contract_campaign(artifact)


def test_campaign_guard_blocks_and_counts_network_connects() -> None:
    with (
        _network_connect_guard() as measurement,
        pytest.raises(SyntheticNetworkConnectBlocked),
    ):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)

    assert measurement.attempt_count == 1


def test_campaign_client_override_is_not_a_production_api_field() -> None:
    assert "llm_client_override" not in JobCreateRequest.model_fields
    assert "client" not in JobCreateRequest.model_fields


@pytest.mark.parametrize("max_steps", [0, -1, True])
def test_campaign_driver_rejects_invalid_explicit_step_limit(
    max_steps: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="campaign orchestration step limit must be positive",
    ):
        _drive_job(
            cast(Any, None),
            job_id="not-started",
            client=None,
            max_steps=max_steps,
        )


def test_campaign_rejects_claim_upgrade_or_outcome_tamper() -> None:
    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["physical_fidelity"] = True
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="claim boundary"):
        verify_harness_outcome_campaign(artifact)

    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["claim_boundary"] = "This proves general real-flight superiority."
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert artifact["claim_boundary"] != HARNESS_OUTCOME_CAMPAIGN_CLAIM_BOUNDARY
    with pytest.raises(ValueError, match="claim boundary"):
        verify_harness_outcome_campaign(artifact)

    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["block_rows"][0]["arms"][1]["outcome"]["failure_count"] = 1
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_outcome_campaign(artifact)


def test_campaign_files_and_check_mode_are_reproducible(tmp_path: Path) -> None:
    artifact = load_harness_outcome_campaign(JSON_ARTIFACT)
    json_path = tmp_path / JSON_ARTIFACT.name
    csv_path = tmp_path / CSV_ARTIFACT.name
    sha256_path = tmp_path / SHA256_ARTIFACT.name

    first = write_harness_outcome_campaign_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
        artifact=artifact,
    )
    second = write_harness_outcome_campaign_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
        check=True,
        artifact=artifact,
    )

    assert first == second
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 15
    assert all(row["exact_match_to_direct_portfolio"] == "True" for row in rows)
    assert SHA256_ARTIFACT.read_text(encoding="ascii").splitlines() == [
        f"{hashlib.sha256(JSON_ARTIFACT.read_bytes()).hexdigest()}  {JSON_ARTIFACT.name}",
        f"{hashlib.sha256(CSV_ARTIFACT.read_bytes()).hexdigest()}  {CSV_ARTIFACT.name}",
    ]


def test_current_campaign_files_and_check_mode_are_reproducible(
    tmp_path: Path,
) -> None:
    artifact = verify_harness_fallback_contract_campaign(
        json.loads(CURRENT_JSON_ARTIFACT.read_text(encoding="utf-8"))
    )
    json_path = tmp_path / CURRENT_JSON_ARTIFACT.name
    csv_path = tmp_path / CURRENT_CSV_ARTIFACT.name
    sha256_path = tmp_path / CURRENT_SHA256_ARTIFACT.name

    first = write_harness_fallback_contract_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
        artifact=artifact,
    )
    second = write_harness_fallback_contract_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
        check=True,
        artifact=artifact,
    )

    assert first == second
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 15
    assert all(row["exact_match_to_deterministic_baseline"] == "True" for row in rows)
