from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scripts import evaluate_harness_component_ablations as component
from scripts import evaluate_harness_cross_job_memory as cross_job
from scripts import evaluate_harness_fallback_contract_campaign as fallback
from scripts import evaluate_harness_outcome_campaign as outcome
from scripts import evaluate_harness_reflection_outcome_stress as outcome_stress
from scripts import evaluate_harness_reflection_triggers as reflection_triggers

_CASES: tuple[tuple[str, ModuleType, str, tuple[str, ...], bool], ...] = (
    (
        "component",
        component,
        "write_harness_component_ablation_files",
        (
            "build_harness_component_ablation_artifact",
            "build_harness_component_ablation_manifest",
        ),
        True,
    ),
    (
        "cross_job",
        cross_job,
        "write_harness_cross_job_memory_files",
        (
            "build_harness_cross_job_memory_artifact",
            "build_harness_cross_job_memory_manifest",
        ),
        True,
    ),
    (
        "fallback",
        fallback,
        "write_harness_fallback_contract_files",
        ("build_harness_fallback_contract_campaign",),
        False,
    ),
    (
        "outcome",
        outcome,
        "write_harness_outcome_campaign_files",
        ("build_harness_outcome_campaign",),
        False,
    ),
    (
        "outcome_stress",
        outcome_stress,
        "write_harness_reflection_outcome_stress_files",
        (
            "build_harness_reflection_outcome_stress_artifact",
            "build_harness_reflection_outcome_stress_manifest",
        ),
        True,
    ),
    (
        "reflection_triggers",
        reflection_triggers,
        "write_harness_reflection_trigger_files",
        (
            "build_harness_reflection_trigger_artifact",
            "build_harness_reflection_trigger_manifest",
        ),
        True,
    ),
)


@pytest.mark.parametrize(
    ("case_name", "module", "writer_name", "builder_names", "has_manifest"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_explicit_empty_evidence_is_rejected_instead_of_rebuilt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    module: ModuleType,
    writer_name: str,
    builder_names: tuple[str, ...],
    has_manifest: bool,
) -> None:
    def unexpected_default() -> Any:
        pytest.fail(f"{case_name} silently replaced explicit evidence with a default build")

    for builder_name in builder_names:
        monkeypatch.setattr(module, builder_name, unexpected_default)

    kwargs: dict[str, Any] = {
        "json_path": tmp_path / f"{case_name}.json",
        "csv_path": tmp_path / f"{case_name}.csv",
        "sha256_path": tmp_path / f"{case_name}.sha256",
        "artifact": {},
    }
    if has_manifest:
        kwargs["manifest_path"] = tmp_path / f"{case_name}.manifest.json"
        kwargs["manifest"] = {}

    with pytest.raises(ValueError):
        getattr(module, writer_name)(**kwargs)

    assert list(tmp_path.iterdir()) == []
