from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_pages_workflow_keeps_only_the_latest_successful_deployment() -> None:
    workflow = read(".github/workflows/pages.yml")
    for fragment in (
        "Verify Pages deployment retention",
        "node --test website/scripts/prune-github-pages-deployments.test.mjs",
        "Retain latest Pages deployment",
        "needs: deploy",
        "deployments: write",
        "DRONEDREAM_DEPLOYMENT_ENVIRONMENT: github-pages",
        "node website/scripts/prune-github-pages-deployments.mjs",
    ):
        assert fragment in workflow
    assert workflow.index("needs: deploy") < workflow.index(
        "node website/scripts/prune-github-pages-deployments.mjs"
    )


def test_release_publisher_requires_release_and_tag_set_equality() -> None:
    publisher = read("desktop/scripts/publish-five-edition-release.ps1")
    for fragment in (
        "Assert-ExactStringSet",
        "GitHub Release inventory",
        "GitHub Tag inventory",
        "git/matching-refs/tags",
        "$channelTags + $keepCombined + $keepRuntime",
    ):
        assert fragment in publisher
    assert publisher.index('"release", "delete"') < publisher.index(
        'Assert-ExactStringSet -Label "GitHub Release inventory"'
    )
    assert publisher.count("Copy-Item -LiteralPath") == 4
    assert publisher.count("-WhatIf:$false") == 5


def test_public_policy_defines_the_exact_eight_entry_topology() -> None:
    policy = " ".join(read("distribution/desktop/RELEASE_POLICY.md").split())
    for statement in (
        "Release names and remote Tag names must be the same set",
        "exactly eight entries",
        "two five-edition builds",
        "five updater channels",
        "one Runtime release",
        "Remote `archive/*`",
        "exactly its newest successful Deployment",
    ):
        assert statement in policy


def test_website_routes_retention_to_the_canonical_policy() -> None:
    readme = read("website/README.md")
    assert "retains only the newest successful" in readme
    assert "../distribution/desktop/RELEASE_POLICY.md" in readme
