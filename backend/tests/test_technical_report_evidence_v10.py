from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.orchestration import technical_report_evidence_v10 as evidence_v10_module
from app.orchestration.technical_report_evidence_v10 import (
    MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_technical_report_evidence_v10,
    export_technical_report_evidence_v10,
    verify_technical_report_evidence_v10,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "97492448c36bef240e468a0cd53c3ba198cb6aae"
GENERATED_AT = "2026-07-29T00:00:00Z"


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    return (
        tmp_path / "evidence-v10.json",
        tmp_path / "evidence-v10.manifest.json",
        tmp_path / "evidence-v10.sha256",
        tmp_path / "csv-v10",
    )


def _export(tmp_path: Path) -> tuple[dict[str, object], tuple[Path, Path, Path, Path]]:
    output, manifest, checksums, csv_directory = _paths(tmp_path)
    bundle = export_technical_report_evidence_v10(
        repository_root=REPOSITORY_ROOT,
        output_path=output,
        manifest_path=manifest,
        checksum_path=checksums,
        csv_directory=csv_directory,
        source_commit=SOURCE_COMMIT,
        generated_at=GENERATED_AT,
    )
    return bundle, (output, manifest, checksums, csv_directory)


def test_source_verification_fails_closed_on_git_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise evidence_v10_module.subprocess.TimeoutExpired(
            cmd=["git", "rev-parse"],
            timeout=30,
        )

    monkeypatch.setattr(evidence_v10_module.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out after 30 seconds"):
        evidence_v10_module._verify_source_commit(REPOSITORY_ROOT, SOURCE_COMMIT)


def test_v10_recomputes_all_evidence_classes_without_upgrading_claims() -> None:
    bundle, csv_rows = build_technical_report_evidence_v10(
        repository_root=REPOSITORY_ROOT,
        source_commit=SOURCE_COMMIT,
        generated_at=GENERATED_AT,
    )

    assert bundle["schema_version"] == SCHEMA_VERSION
    assert bundle["source_commit"] == SOURCE_COMMIT
    assert bundle["generated_at"] == GENERATED_AT
    assert bundle["routing"]["case_count"] == 24
    assert bundle["routing"]["passed_count"] == 23
    assert bundle["routing"]["qualified"] is True
    assert bundle["routing"]["contract_current"] is False
    assert bundle["routing"]["artifact_contract"]["evidence_schema_version"] == "2.8"
    assert bundle["routing"]["current_contract"]["evidence_schema_version"] == "2.9"
    assert bundle["harness_multi_tool_budget"]["summary"]["block_count"] == 3
    assert bundle["harness_multi_tool_budget"]["summary"]["configured_budget_parity_count"] == 3
    assert bundle["harness_multi_tool_budget"]["runtime"]["network_calls"] == 0
    assert bundle["advanced_physics"]["summary"]["verified_category_count"] == 9
    assert (
        bundle["advanced_physics"]["summary"]["categories_with_all_retained_performance_success"]
        == 5
    )
    assert bundle["release_readiness"]["release_ready"] is False
    assert (
        bundle["release_readiness"]["online_provider_refresh_requires_separate_user_approval"]
        is True
    )
    assert "harness_component_outcome_ablation" in bundle["sources"]
    assert bundle["source_lineage"] == {
        "evidence_v9_source_commit": "c1222c9215e01a56351f6588af0d2b8694bca831",
        "evidence_v9_freeze_commit": "8102ffecb37b1f1b0e25c80d6b02db05325ca986",
        "online_routing_source_commit": "aeffaae01a8106f74ff811b39ec26d9d2203d1f6",
        "online_routing_freeze_commit": "ef00362927475b2fc411a4d82084bbbae8846582",
        "multi_tool_budget_source_commit": "136a1e3293efa6e53f3648e21fa8f7c6b5158d6f",
        "multi_tool_budget_freeze_commit": "15603c6f3c1e421dc20802ed0b8dfcfaf7ac49e8",
        "advanced_physics_subject_commit": ("f1e8fa855ebe95bf5ce208d62da7a3a46bba6228"),
        "advanced_physics_freeze_commit": ("83982f37899f8054e24a749af8e6469fedf48e8d"),
    }
    assert bundle["sources"]["routing_predictions"]["snapshot_commit"] == (
        "ef00362927475b2fc411a4d82084bbbae8846582"
    )
    assert len(csv_rows["online_routing_cases"]) == 24
    assert len(csv_rows["multi_tool_budget_blocks"]) == 3
    assert len(csv_rows["advanced_physics_coverage"]) == 9
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    expected_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert bundle["bundle_sha256"] == expected_hash


def test_v10_export_and_exact_byte_verification(tmp_path: Path) -> None:
    bundle, (output, manifest, checksums, csv_directory) = _export(tmp_path)

    verified = verify_technical_report_evidence_v10(
        repository_root=REPOSITORY_ROOT,
        output_path=output,
        manifest_path=manifest,
        checksum_path=checksums,
        csv_directory=csv_directory,
    )

    assert verified == bundle
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert (
        manifest_payload["bundle"]["file_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    )
    assert set(manifest_payload["csv_exports"]) == {
        "advanced_physics_coverage.csv",
        "multi_tool_budget_blocks.csv",
        "online_routing_cases.csv",
    }
    assert checksums.read_text(encoding="ascii").splitlines() == [
        f"{hashlib.sha256(output.read_bytes()).hexdigest()}  evidence-v10.json",
        (f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  evidence-v10.manifest.json"),
        *[
            (f"{hashlib.sha256(path.read_bytes()).hexdigest()}  csv-v10/{path.name}")
            for path in sorted(csv_directory.glob("*.csv"))
        ],
    ]


def test_v10_export_refuses_to_overwrite_an_existing_freeze(tmp_path: Path) -> None:
    _, paths = _export(tmp_path)
    output, manifest, checksums, csv_directory = paths
    originals = {
        path: path.read_bytes()
        for path in (
            output,
            manifest,
            checksums,
            *sorted(csv_directory.glob("*.csv")),
        )
    }

    with pytest.raises(ValueError, match="refusing to overwrite frozen evidence"):
        _export(tmp_path)

    assert {path: path.read_bytes() for path in originals} == originals


def test_v10_export_rolls_back_its_files_without_removing_a_raced_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, manifest, checksums, csv_directory = _paths(tmp_path)
    original_write = evidence_v10_module._write_new_bytes
    calls = 0

    def inject_race(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"concurrent publisher")
        original_write(path, payload)

    monkeypatch.setattr(evidence_v10_module, "_write_new_bytes", inject_race)
    with pytest.raises(ValueError, match="refusing to overwrite frozen evidence"):
        export_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            output_path=output,
            manifest_path=manifest,
            checksum_path=checksums,
            csv_directory=csv_directory,
            source_commit=SOURCE_COMMIT,
            generated_at=GENERATED_AT,
        )

    assert not output.exists()
    assert manifest.read_bytes() == b"concurrent publisher"
    assert not checksums.exists()
    assert not csv_directory.exists()


@pytest.mark.parametrize(
    "target_name",
    [
        "evidence-v10.json",
        "evidence-v10.manifest.json",
        "evidence-v10.sha256",
        "online_routing_cases.csv",
    ],
)
def test_v10_verifier_rejects_output_tamper(
    tmp_path: Path,
    target_name: str,
) -> None:
    _, (output, manifest, checksums, csv_directory) = _export(tmp_path)
    targets = {
        output.name: output,
        manifest.name: manifest,
        checksums.name: checksums,
        "online_routing_cases.csv": csv_directory / "online_routing_cases.csv",
    }
    target = targets[target_name]
    target.write_bytes(target.read_bytes() + b"tamper")

    with pytest.raises(ValueError):
        verify_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            output_path=output,
            manifest_path=manifest,
            checksum_path=checksums,
            csv_directory=csv_directory,
        )


def test_v10_requires_full_commit_and_utc_timestamp() -> None:
    with pytest.raises(ValueError, match="full lowercase Git commit"):
        build_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            source_commit="short",
            generated_at=GENERATED_AT,
        )
    with pytest.raises(ValueError, match="explicit UTC timestamp"):
        build_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            source_commit=SOURCE_COMMIT,
            generated_at="2026-07-29",
        )
    with pytest.raises(ValueError, match="does not resolve"):
        build_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            source_commit="0" * 40,
            generated_at=GENERATED_AT,
        )
    with pytest.raises(ValueError, match="does not contain freeze commit"):
        build_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            source_commit="8102ffecb37b1f1b0e25c80d6b02db05325ca986",
            generated_at=GENERATED_AT,
        )
