from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "receipts"
    / "common-core-coexistence-sync-v1.json"
)


def sha256_git_file(commit: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def validate_receipt(receipt: dict[str, object]) -> None:
    if receipt.get("kind") != "dronedream-field-common-core-coexistence-sync-receipt":
        raise ValueError("receipt kind drifted")
    donor = receipt["donorPathVerification"]
    if donor["pathCount"] != 8 or donor["allGitBlobsExact"] is not True:
        raise ValueError("donor path gate drifted")
    for record in donor["paths"]:
        if git("rev-parse", f'{donor["donorCommit"]}:{record["path"]}') != record["gitBlob"]:
            raise ValueError("donor blob drifted")
        source_commit = receipt["source"]["fieldProductCommit"]
        if git("rev-parse", f'{source_commit}:{record["path"]}') != record["gitBlob"]:
            raise ValueError("integrated blob drifted")
        if sha256_git_file(source_commit, record["path"]) != record["sha256"]:
            raise ValueError("integrated file identity drifted")
    if receipt["safety"] != {
        "validatedHardwarePackCount": 0,
        "buildAllowed": False,
        "installAllowed": False,
        "deviceEnumerationAllowed": False,
        "hardwareActionsAllowed": False,
        "simulationAllowed": False,
        "releaseBranchAllowed": False,
        "websiteHandoffAllowed": False,
    }:
        raise ValueError("safety boundary drifted")


class FieldCommonCoreCoexistenceSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    def test_receipt_binds_exact_donor_paths_and_field_overlay(self) -> None:
        validate_receipt(self.receipt)
        source_commit = self.receipt["source"]["fieldProductCommit"]
        self.assertEqual(
            sha256_git_file(source_commit, self.receipt["fieldOverlay"]["path"]),
            self.receipt["fieldOverlay"]["sha256"],
        )
        self.assertEqual(
            sha256_git_file(
                source_commit,
                "distribution/desktop/edition-coexistence.v1.json",
            ),
            self.receipt["fieldOverlay"]["commonCoexistenceContractSha256"],
        )
        self.assertEqual(self.receipt["fieldOverlay"]["installerProductName"], "DroneDream-Field")
        self.assertEqual(self.receipt["fieldOverlay"]["displayName"], "DroneDream · FIELD")
        self.assertEqual(self.receipt["excludedEvidenceCommit"]["consumed"], False)

    def test_integration_commits_are_ancestors_without_release_claims(self) -> None:
        for donor in self.receipt["canonicalDonors"]:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "merge-base",
                    "--is-ancestor",
                    donor["fieldIntegrationCommit"],
                    "HEAD",
                ],
                check=False,
            )
            self.assertEqual(completed.returncode, 0, donor)
        self.assertEqual(self.receipt["frozenArtifact"]["status"], "superseded-preview")
        self.assertFalse(self.receipt["frozenArtifact"]["releaseReady"])
        self.assertFalse(self.receipt["frozenArtifact"]["websiteReady"])
        self.assertIn(
            "field.auth.awaiting-exact-universal-donor",
            self.receipt["remainingGates"],
        )

    def test_donor_or_safety_drift_is_rejected(self) -> None:
        drifted = deepcopy(self.receipt)
        drifted["safety"]["buildAllowed"] = True
        with self.assertRaisesRegex(ValueError, "safety boundary drifted"):
            validate_receipt(drifted)
        drifted = deepcopy(self.receipt)
        drifted["donorPathVerification"]["paths"][0]["gitBlob"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "donor blob drifted"):
            validate_receipt(drifted)


if __name__ == "__main__":
    unittest.main()
