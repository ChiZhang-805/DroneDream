from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_pages_workflow_keeps_only_the_latest_successful_deployment() -> None:
    workflow = read(".github/workflows/pages.yml")
    for fragment in (
        "Verify Pages deployment retention",
        "node --test apps/website/scripts/prune-github-pages-deployments.test.mjs",
        "Retain website and Actions history",
        "needs: deploy",
        "deployments: write",
        "DRONEDREAM_DEPLOYMENT_ENVIRONMENT: github-pages",
        "node apps/website/scripts/prune-github-pages-deployments.mjs",
    ):
        assert fragment in workflow
    assert workflow.index("needs: deploy") < workflow.index(
        "node apps/website/scripts/prune-github-pages-deployments.mjs"
    )


def test_all_four_workflows_retain_only_four_repository_runs() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert [path.name for path in workflows] == [
        "pages.yml",
        "quality-gate.yml",
        "release-software.yml",
        "runtime-release.yml",
    ]
    for workflow in workflows:
        assert "retain-workflow-runs.sh" in workflow.read_text(encoding="utf-8")

    retention = read(".github/scripts/retain-workflow-runs.sh")
    assert "readonly keep_count=4" in retention
    assert 'if [[ "$status" == "completed" ]]' in retention
    assert "actions/runs/${run_id}" in retention


def test_release_publisher_requires_release_and_tag_set_equality() -> None:
    publisher = read("apps/desktop/scripts/publish-five-edition-release.ps1")
    for fragment in (
        "Assert-ExactStringSet",
        "GitHub Release inventory",
        "GitHub Tag inventory",
        "the canonical public set must contain exactly eight entries",
        "git/matching-refs/tags",
        "$channelTags + $keepCombined + $keepRuntime",
        "GitHub permanent branch inventory",
        "repos/$Repository/branches?per_page=100",
    ):
        assert fragment in publisher
    assert publisher.index('"release", "delete"') < publisher.index(
        'Assert-ExactStringSet -Label "GitHub Release inventory"'
    )
    assert publisher.count("Copy-Item -LiteralPath") == 4
    assert publisher.count("-WhatIf:$false") == 5


def test_public_policy_defines_the_exact_eight_entry_topology() -> None:
    policy = " ".join(read("release/desktop/RELEASE_POLICY.md").split())
    for statement in (
        "Release names and remote Tag names must be the same set",
        "exactly eight entries",
        "Exactly one permanent branch",
        "two five-edition builds",
        "five updater channels",
        "one Runtime release",
        "Remote `archive/*`",
        "exactly its newest successful Deployment",
    ):
        assert statement in policy


def test_website_routes_retention_to_the_canonical_policy() -> None:
    readme = read("apps/website/README.md")
    assert "retains only the newest successful" in readme
    assert "../../release/desktop/RELEASE_POLICY.md" in readme
