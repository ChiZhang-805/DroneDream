from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.benchmarking.method_inventory import (
    BENCHMARK_METHOD_INVENTORY,
    BENCHMARK_METHOD_INVENTORY_SHA256,
    BenchmarkMethodInventoryEntryV1,
    BenchmarkMethodSourceV1,
    require_execution_ready_method,
)
from app.benchmarking.registry import BENCHMARK_ADAPTER_REGISTRY


def test_method_inventory_is_complete_and_matches_registry_provenance() -> None:
    assert set(BENCHMARK_METHOD_INVENTORY) == set(BENCHMARK_ADAPTER_REGISTRY)
    assert len(BENCHMARK_METHOD_INVENTORY_SHA256) == 64
    for adapter_id, descriptor in BENCHMARK_ADAPTER_REGISTRY.items():
        inventory = BENCHMARK_METHOD_INVENTORY[adapter_id]
        assert inventory.adapter_id == adapter_id
        assert inventory.implementation_label == descriptor.implementation_label
        assert inventory.method_classification == descriptor.method_classification
        assert (inventory.execution_readiness == "ready") == (
            descriptor.availability == "implemented"
        )


@pytest.mark.parametrize(
    "adapter_id",
    (
        "random_search/v1",
        "seeded_halton/v1",
        "true_lhs/v1",
        "repo_constrained_mobo/v1",
        "optimizer_portfolio/v1",
        "repo_turbo_inspired/v1",
        "repo_bipop_cma_inspired/v1",
        "repo_surrogate_cma/v1",
        "llm_direct/v1",
        "llm_react/v1",
        "llambo_uav/v1",
        "dronedream_fixed_two_turn/v1",
        "dronedream_adaptive_1_4/v1",
    ),
)
def test_only_reviewed_project_adapters_are_execution_ready(adapter_id: str) -> None:
    entry = require_execution_ready_method(adapter_id)
    assert entry.execution_readiness == "ready"
    assert entry.blocker_codes == ()
    assert all(source.license_status == "inherited_project" for source in entry.sources)
    if adapter_id in {
        "llm_direct/v1",
        "llm_react/v1",
        "llambo_uav/v1",
        "dronedream_fixed_two_turn/v1",
        "dronedream_adaptive_1_4/v1",
    }:
        assert entry.environment_boundary == "provider_contract"


@pytest.mark.parametrize(
    ("adapter_id", "version", "license_spdx"),
    (
        ("bipop_cma_es/v1", "4.4.4", "BSD-3-Clause"),
        ("optuna_tpe/v1", "4.9.0", "MIT"),
        ("reference_turbo/v1", "0.17.0", "MIT"),
        ("reference_scbo/v1", "0.17.0", "MIT"),
    ),
)
def test_external_references_are_pinned_candidates_but_fail_closed_until_locked(
    adapter_id: str,
    version: str,
    license_spdx: str,
) -> None:
    entry = BENCHMARK_METHOD_INVENTORY[adapter_id]
    assert entry.environment_boundary == "isolated_benchmark"
    assert entry.execution_readiness == "blocked"
    assert "isolated_environment_missing" in entry.blocker_codes
    if adapter_id in {"bipop_cma_es/v1", "optuna_tpe/v1"}:
        assert "source_archive_hash_pending" not in entry.blocker_codes
        package_sources = [
            source for source in entry.sources if source.source_kind == "python_package"
        ]
        assert package_sources
        assert all(source.distribution_sha256 for source in package_sources)
    else:
        assert "source_archive_hash_pending" in entry.blocker_codes
    assert any(source.version_candidate == version for source in entry.sources)
    assert any(source.license_spdx == license_spdx for source in entry.sources)
    with pytest.raises(ValueError, match="benchmark method is blocked"):
        require_execution_ready_method(adapter_id)


def test_hebo_cannot_execute_while_root_license_and_compatibility_are_unverified() -> None:
    entry = BENCHMARK_METHOD_INVENTORY["hebo/v1"]
    assert entry.execution_readiness == "blocked"
    assert "license_unverified" in entry.blocker_codes
    assert "compatibility_unverified" in entry.blocker_codes
    assert "version_unresolved" in entry.blocker_codes
    assert entry.sources[0].license_status == "unverified"
    assert entry.sources[0].license_spdx is None


def test_reference_and_product_inspired_turbo_bipop_are_distinct_methods() -> None:
    assert BENCHMARK_METHOD_INVENTORY["reference_turbo/v1"].method_classification == (
        "standard_reference"
    )
    assert BENCHMARK_METHOD_INVENTORY["repo_turbo_inspired/v1"].method_classification == (
        "product_inspired"
    )
    assert BENCHMARK_METHOD_INVENTORY["bipop_cma_es/v1"].implementation_label.startswith("pycma-")
    assert BENCHMARK_METHOD_INVENTORY["repo_bipop_cma_inspired/v1"].implementation_label.startswith(
        "numpy-"
    )
    assert BENCHMARK_METHOD_INVENTORY["repo_turbo_inspired/v1"].execution_readiness == "ready"
    assert BENCHMARK_METHOD_INVENTORY["repo_bipop_cma_inspired/v1"].execution_readiness == "ready"


def test_seeded_halton_is_not_relabelled_as_true_lhs() -> None:
    halton = BENCHMARK_METHOD_INVENTORY["seeded_halton/v1"]
    lhs = BENCHMARK_METHOD_INVENTORY["true_lhs/v1"]
    assert halton.execution_readiness == "ready"
    assert "halton" in halton.implementation_label
    assert lhs.execution_readiness == "ready"
    assert "lhs" in lhs.implementation_label
    assert lhs.implementation_label != halton.implementation_label


def test_unverified_license_requires_a_fail_closed_blocker() -> None:
    source = BenchmarkMethodSourceV1(
        source_id="unknown-source",
        source_kind="upstream_repository",
        locator="https://example.invalid/source",
        license_status="unverified",
    )
    with pytest.raises(ValidationError, match="license_unverified"):
        BenchmarkMethodInventoryEntryV1(
            adapter_id="unknown/v1",
            method_classification="standard_reference",
            implementation_label="unknown",
            execution_readiness="blocked",
            environment_boundary="isolated_benchmark",
            sources=(source,),
            blocker_codes=("adapter_not_implemented",),
        )


def test_verified_license_requires_spdx_and_source_locator() -> None:
    with pytest.raises(ValidationError, match="SPDX"):
        BenchmarkMethodSourceV1(
            source_id="invalid-verified-source",
            source_kind="upstream_repository",
            locator="https://example.invalid/source",
            license_status="verified",
        )


def test_distribution_filename_and_hash_must_be_bound_together() -> None:
    with pytest.raises(ValidationError, match="declared together"):
        BenchmarkMethodSourceV1(
            source_id="incomplete-package-lock",
            source_kind="python_package",
            locator="https://example.invalid/package.whl",
            version_candidate="1.0.0",
            dependency_name="package",
            distribution_filename="package-1.0.0-py3-none-any.whl",
            license_status="verified",
            license_spdx="MIT",
            license_locator="https://example.invalid/LICENSE",
        )


def test_distribution_lock_is_rejected_for_non_package_sources() -> None:
    with pytest.raises(ValidationError, match="only Python-package"):
        BenchmarkMethodSourceV1(
            source_id="invalid-repository-archive",
            source_kind="upstream_repository",
            locator="https://example.invalid/source",
            distribution_filename="source.tar.gz",
            distribution_sha256="0" * 64,
            license_status="verified",
            license_spdx="MIT",
            license_locator="https://example.invalid/LICENSE",
        )
