from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.orchestration.harness_handoff_closure import (
    build_harness_handoff_closure,
    export_harness_handoff_closure,
    verify_harness_handoff_closure,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_AT = "2026-07-29T12:00:00Z"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_closure_indexes_all_gaps_without_upgrading_claims() -> None:
    closure = build_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        subject_commit=_head(),
        generated_at=GENERATED_AT,
    )

    assert [item["gap_id"] for item in closure["closures"]] == [
        "6.1",
        "6.2",
        "6.3",
        "6.4",
        "6.5",
        "6.6",
    ]
    assert closure["closures"][0]["facts"]["passed"] == 23
    assert closure["closures"][0]["facts"]["total"] == 24
    assert closure["closures"][1]["facts"]["general_causal_benefit_claim_permitted"] is False
    assert closure["closures"][2]["facts"]["multi_tool_generations"] == 3
    assert closure["closures"][3]["facts"]["cases_passed"] == 10
    assert closure["closures"][4]["facts"]["verified_effect_categories"] == 9
    assert closure["closures"][4]["facts"]["all_effects_performance_successful"] is False
    assert closure["closures"][5]["facts"]["v10_release_ready"] is False
    assert closure["closures"][5]["facts"]["quality_aggregate_workflow_conclusion"] == "failure"
    assert closure["summary"]["technical_report_release_ready"] is False
    assert closure["online_policy"]["openai_api_key_read"] is False


def test_export_and_verify_are_exact_byte_stable(tmp_path: Path) -> None:
    output = tmp_path / "handoff-closure.json"
    checksum = tmp_path / "handoff-closure.json.sha256"
    exported = export_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        subject_commit=_head(),
        generated_at=GENERATED_AT,
        output_path=output,
        checksum_path=checksum,
    )

    verified = verify_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        output_path=output,
        checksum_path=checksum,
    )

    assert verified == exported
    assert json.loads(output.read_text(encoding="utf-8")) == exported
    assert checksum.read_text(encoding="ascii").endswith("  handoff-closure.json\n")


def test_verifier_rejects_output_tamper(tmp_path: Path) -> None:
    output = tmp_path / "handoff-closure.json"
    checksum = tmp_path / "handoff-closure.json.sha256"
    export_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        subject_commit=_head(),
        generated_at=GENERATED_AT,
        output_path=output,
        checksum_path=checksum,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["summary"]["technical_report_release_ready"] = True
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exact recomputation"):
        verify_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            output_path=output,
            checksum_path=checksum,
        )


def test_export_refuses_to_replace_an_existing_freeze(tmp_path: Path) -> None:
    output = tmp_path / "handoff-closure.json"
    checksum = tmp_path / "handoff-closure.json.sha256"
    export_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        subject_commit=_head(),
        generated_at=GENERATED_AT,
        output_path=output,
        checksum_path=checksum,
    )
    frozen_output = output.read_bytes()
    frozen_checksum = checksum.read_bytes()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        export_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            subject_commit=_head(),
            generated_at=GENERATED_AT,
            output_path=output,
            checksum_path=checksum,
        )

    assert output.read_bytes() == frozen_output
    assert checksum.read_bytes() == frozen_checksum


def test_verifier_rejects_checksum_tamper(tmp_path: Path) -> None:
    output = tmp_path / "handoff-closure.json"
    checksum = tmp_path / "handoff-closure.json.sha256"
    export_harness_handoff_closure(
        repository_root=REPOSITORY_ROOT,
        subject_commit=_head(),
        generated_at=GENERATED_AT,
        output_path=output,
        checksum_path=checksum,
    )
    checksum.write_text(f"{'0' * 64}  handoff-closure.json\n", encoding="ascii")

    with pytest.raises(ValueError, match="checksum file"):
        verify_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            output_path=output,
            checksum_path=checksum,
        )


@pytest.mark.parametrize(
    ("subject_commit", "generated_at", "message"),
    [
        ("deadbeef", GENERATED_AT, "full lowercase Git commit"),
        ("0" * 40, "2026-07-29T12:00:00+00:00", "ending in Z"),
    ],
)
def test_export_requires_full_commit_and_utc_timestamp(
    subject_commit: str,
    generated_at: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            subject_commit=subject_commit,
            generated_at=generated_at,
        )
