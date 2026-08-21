from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "distribution" / "repository" / "branch-topology.v1.json"
SCHEMA = ROOT / "distribution" / "schemas" / "public-branch-topology.schema.json"


EXPECTED = {
    "main": ("protected-integration", None),
    "codex/software": ("long-lived-product", "universal"),
    "codex/software-sim": ("long-lived-product", "sim"),
    "codex/software-lab": ("long-lived-product", "lab"),
    "codex/software-field": ("long-lived-product", "field"),
    "codex/software-agent": ("long-lived-product", "autonomy"),
    "codex/website": ("long-lived-delivery", "website"),
    "codex/technical-report": ("long-lived-delivery", "technical-report"),
}


def test_public_repository_has_one_exact_eight_branch_contract() -> None:
    topology = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert topology["schemaVersion"] == 1
    assert topology["kind"] == "dronedream-public-branch-topology"
    assert topology["requiredBranchCount"] == 8
    observed = {
        branch["name"]: (branch["role"], branch["productId"])
        for branch in topology["branches"]
    }
    assert observed == EXPECTED


def test_branch_policy_forbids_unsalvaged_deletion_and_force_push() -> None:
    policy = json.loads(TOPOLOGY.read_text(encoding="utf-8"))["policy"]
    assert policy == {
        "featureBranchesTemporary": True,
        "deleteFeatureBranchOnlyAfterMerged": True,
        "forcePushAllowed": False,
        "commonCoreChangesReturnToMain": True,
        "sharedProductChangesPropagateThroughPullRequests": True,
        "privateAutonomyDevelopmentMayRunInParallel": True,
    }
