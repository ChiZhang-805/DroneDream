from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_agent_core_stage_carries_qualified_default_assets_into_the_installer() -> None:
    script = (ROOT / "desktop" / "scripts" / "stage-agent-core.ps1").read_text(encoding="utf-8-sig")
    for fragment in (
        '"default-assets\\index.json"',
        '"default-assets\\school-map.ddpkg"',
        '"default-assets\\my-drone.ddpkg"',
        '"runtime\\local-policy\\catalog.json"',
        "defaultAssetIndexSha256",
        "Implicit checkout fallbacks are not allowed",
        "retired embedded autonomy-core snapshot is not a release input",
        "Copy-VerifiedManifestFile",
        "failed post-copy verification",
        "may reference only current DDPKG packages",
        "local expert catalog is not the current single-package contract",
        "local expert catalog scope and receipt kind disagree",
        "localPolicyCatalogSha256",
    ):
        assert fragment in script

    assert "SpecialFolder]::MyDocuments" not in script
    assert '"Codex\\DroneDream-Flight-Agent-Core"' not in script
    assert '"default-assets\\school-map.zip"' not in script
    assert '"default-assets\\my-drone.zip"' not in script
    assert 'Copy-Item -LiteralPath (Join-Path $sourceResources $name)' not in script

    for edition in ("universal", "sim", "lab", "field", "autonomy"):
        config = json.loads(
            (ROOT / "desktop" / "src-tauri" / f"tauri.{edition}.conf.json").read_text(
                encoding="utf-8"
            )
        )
        resources = config["bundle"]["resources"]
        assert resources["agent-core-resources/default-assets"] == ("agent-core/default-assets")


def test_five_edition_build_forwards_one_explicit_agent_core_repository() -> None:
    script = (
        ROOT / "desktop" / "scripts" / "build-five-edition-installers.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "[string]$AgentCoreRepository" in script
    assert "-AgentCoreRepository $AgentCoreRepository" in script


def test_retired_embedded_autonomy_core_is_absent() -> None:
    assert not (ROOT / "autonomy-core").exists()


def test_quality_gate_cannot_validate_the_retired_embedded_core_as_product_code() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality-gate.yml").read_text(
        encoding="utf-8"
    )

    assert "working-directory: autonomy-core" not in workflow
    assert "cache-dependency-path: autonomy-core/pyproject.toml" not in workflow
    assert "find autonomy-core/scripts" not in workflow
