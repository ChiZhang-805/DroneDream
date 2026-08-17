from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/desktop-installer.yml"
RESOLVER = ROOT / "desktop/scripts/resolve-desktop-edition-release.ps1"
SOURCE_POLICY = ROOT / "desktop/scripts/verify-release-source-policy.mjs"
FAMILY_CONTRACT = ROOT / "distribution/desktop/edition-runtime-update-families.v1.json"


def _powershell() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"


def _run_resolver(
    tag: str, output: Path, validation_edition: str = "universal"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RESOLVER),
            "-ReleaseTag",
            tag,
            "-ValidationEditionId",
            validation_edition,
            "-GitHubOutputPath",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _outputs(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line
    )


def test_workflow_has_four_isolated_release_and_update_channels() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for edition in ("universal", "sim", "lab", "field"):
        assert f'"desktop-{edition}-v*-build-*"' in workflow
    for fragment in (
        "resolve-desktop-edition-release.ps1",
        '-ValidationEditionId "${{ inputs.edition || \'universal\' }}"',
        '"DRONEDREAM_RELEASE_SOURCE_COMMIT=$env:GITHUB_SHA"',
        '"DRONEDREAM_RELEASE_BUILD_NUMBER=$($contract.buildNumber)"',
        "--edition-config \"${{ steps.release.outputs.config_path }}\"",
        "Prepare edition release artifact",
        "desktop/release-dist/*",
        "needs.windows-nsis.outputs.is_release == 'true'",
        "desktop-stable-channel-${{ needs.windows-nsis.outputs.edition_id }}",
        "cancel-in-progress: false",
        "release already exists and will never be overwritten; verified canonical assets will be reused",
        '(cd "$existing_dir" && sha256sum --check',
        'cp "$existing_dir"/* dist/',
        '-EditionId "${{ steps.release.outputs.edition_id }}"',
        "Advance edition stable channel",
        "stable channel build must increase",
        "candidate_name=",
        "rollback_stable_metadata",
        "failed to restore previous stable metadata asset",
        "https://uploads.github.com/repos/",
        "stable channel already contains identical build",
        '--data-binary "@$source_file"',
        "Verify stable channel publication",
        '"unregistered-$($contract.editionId)-validation-client"',
    ):
        assert fragment in workflow
    assert 'startsWith(github.ref, \'refs/tags/desktop-v\')' not in workflow
    assert "bundle/nsis/latest.json" not in workflow
    assert "--clobber" not in workflow
    assert workflow.index("if (( incoming_build < existing_build ))") < workflow.index(
        "candidate_json=",
    )
    assert workflow.index("if (( incoming_build == existing_build ))") < workflow.index(
        "candidate_json=",
    )
    assert workflow.index("final_replaced=true") < workflow.index(
        '-f sha="$GITHUB_SHA"',
    )


def test_tauri_commands_convert_repo_root_config_for_npm_prefix() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("-replace '^desktop/', ''") == 2


def test_release_source_inventory_uses_edition_product_identity() -> None:
    policy = SOURCE_POLICY.read_text(encoding="utf-8")
    assert 'process.argv.indexOf("--edition-config")' in policy
    assert "editionConfig?.productName ?? tauriConfig.productName" in policy
    assert "edition Tauri config version must match" in policy


@pytest.mark.parametrize("edition", ["universal", "sim", "lab", "field"])
def test_resolver_accepts_only_the_current_version_and_commit_count(
    edition: str, tmp_path: Path
) -> None:
    contract = json.loads(FAMILY_CONTRACT.read_text(encoding="utf-8"))
    family = next(item for item in contract["editions"] if item["editionId"] == edition)
    build_number = subprocess.check_output(
        ["git", "rev-list", "--count", "HEAD"], cwd=ROOT, text=True
    ).strip()
    version = contract["productDisplayVersion"]
    tag = f"desktop-{edition}-v{version}-build-{build_number}"
    output = tmp_path / f"{edition}.txt"
    result = _run_resolver(tag, output)
    assert result.returncode == 0, result.stderr
    values = _outputs(output)
    assert values["is_release"] == "true"
    assert values["edition_id"] == edition
    assert values["product_name"] == family["installerProductName"]
    assert values["public_installer"] == family["publicArtifactFileName"]
    assert values["metadata_file"] == family["updaterMetadataFileName"]
    assert values["channel_tag"] == family["updaterChannelTag"]
    assert values["release_tag"] == tag


@pytest.mark.parametrize(
    "tag",
    [
        "desktop-v1.0.0",
        "desktop-sim-v9.9.9-build-1",
        "desktop-field-v1.0.0-build-0",
        "desktop-unknown-v1.0.0-build-1",
    ],
)
def test_resolver_rejects_ambiguous_or_stale_release_tags(
    tag: str, tmp_path: Path
) -> None:
    result = _run_resolver(tag, tmp_path / "invalid.txt")
    assert result.returncode != 0


@pytest.mark.parametrize("edition", ["universal", "sim", "lab", "field"])
def test_manual_validation_resolves_a_real_unsigned_edition(
    edition: str, tmp_path: Path,
) -> None:
    output = tmp_path / "validation.txt"
    result = _run_resolver("", output, edition)
    assert result.returncode == 0, result.stderr
    values = _outputs(output)
    assert values["is_release"] == "false"
    assert values["edition_id"] == edition
    assert values["config_path"] == f"desktop/src-tauri/tauri.{edition}.conf.json"
