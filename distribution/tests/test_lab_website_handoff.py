from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_website_handoff as handoff  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LabWebsiteHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifact = self.root / handoff.FILE_NAME
        self.artifact.write_bytes(b"MZ\x00\x00DroneDream LAB exact fake fixture")
        self.source_commit = "a" * 40
        artifact_sha = sha256(self.artifact)
        artifact_bytes = self.artifact.stat().st_size

        self.receipt = self.root / f"{handoff.FILE_NAME}.receipt.json"
        self.receipt.write_text(
            json.dumps(
                {
                    "kind": "dronedream-lab-preview-artifact-receipt",
                    "testOnly": False,
                    "sourceCommit": self.source_commit,
                    "commonCoreCommit": handoff.COMMON_CORE_COMMIT,
                    "commonCoreHash": handoff.COMMON_CORE_HASH,
                    "artifact": {
                        "fileName": handoff.FILE_NAME,
                        "bytes": artifact_bytes,
                        "sha256": artifact_sha,
                        "authenticode": {
                            "expected": "not-signed",
                            "observedStatus": "NotSigned",
                        },
                        "tauriUpdaterSignature": "not-issued",
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.manifest = self.root / f"{handoff.FILE_NAME}.manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "kind": "dronedream-lab-release-manifest",
                    "editionId": "lab",
                    "productVersion": handoff.VERSION,
                    "productSourceCommit": self.source_commit,
                    "artifact": {
                        "fileName": handoff.FILE_NAME,
                        "bytes": artifact_bytes,
                        "sha256": artifact_sha,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        family = "https://downloads.example.test/releases/lab-v1.0.0/"
        self.ready = {
            "schemaVersion": 1,
            "kind": "dronedream-lab-website-exact-exe-handoff",
            "handoffVersion": "1.0.0",
            "state": "release-ready",
            "receiver": {
                "websiteSourceCommit": handoff.WEBSITE_SOURCE_COMMIT,
                "websiteEvidenceCommit": handoff.WEBSITE_EVIDENCE_COMMIT,
                "mode": "read-only-receiver",
                "rebuildAllowed": False,
                "renameAllowed": False,
            },
            "edition": {
                "editionId": "lab",
                "displayName": "DroneDream · LAB",
                "version": "1.0.0",
                "fileName": handoff.FILE_NAME,
            },
            "productSource": {
                "branch": "codex/software-lab",
                "commit": self.source_commit,
                "clean": True,
                "commonCoreCommit": handoff.COMMON_CORE_COMMIT,
                "commonCoreHash": handoff.COMMON_CORE_HASH,
            },
            "artifact": {
                "absolutePath": str(self.artifact.resolve()),
                "fileName": handoff.FILE_NAME,
                "version": "1.0.0",
                "bytes": artifact_bytes,
                "sha256": artifact_sha,
                "authenticode": {
                    "signatureState": "NotSigned",
                    "subject": None,
                    "timestamp": None,
                },
                "updaterSignature": {
                    "state": "not-issued",
                    "absolutePath": None,
                    "bytes": None,
                    "sha256": None,
                },
            },
            "receipt": {
                "absolutePath": str(self.receipt.resolve()),
                "sha256": sha256(self.receipt),
            },
            "manifest": {
                "absolutePath": str(self.manifest.resolve()),
                "sha256": sha256(self.manifest),
            },
            "build": {
                "attemptCount": 1,
                "successfulArtifactCount": 1,
                "uniqueExe": True,
            },
            "validation": {
                "freshInstall": "passed",
                "overlayInstall": "passed",
                "uninstall": "passed",
                "shortcuts": "passed",
                "webView2": "passed",
                "localization": {"en": "passed", "zhCN": "passed"},
                "boundaryNotes": ["Offline fake fixture only."],
            },
            "publication": {
                "urlFamily": family,
                "releaseTag": "lab-v1.0.0",
                "downloadUrl": f"{family}{handoff.FILE_NAME}",
                "checksumUrl": f"{family}{handoff.FILE_NAME}.sha256",
                "receiptUrl": f"{family}{handoff.FILE_NAME}.receipt.json",
                "manifestUrl": f"{family}{handoff.FILE_NAME}.manifest.json",
                "signatureUrl": None,
            },
            "crossEditionValidation": {
                "comparedEditions": [
                    {
                        "editionId": "universal",
                        "artifactSha256": "1" * 64,
                        "downloadUrl": "https://downloads.example.test/releases/universal-v1.0.0/DroneDream-1.0.0.exe",
                        "releaseTag": "universal-v1.0.0",
                    },
                    {
                        "editionId": "sim",
                        "artifactSha256": "2" * 64,
                        "downloadUrl": "https://downloads.example.test/releases/sim-v1.0.0/DroneDream-Sim-1.0.0.exe",
                        "releaseTag": "sim-v1.0.0",
                    },
                    {
                        "editionId": "field",
                        "artifactSha256": "3" * 64,
                        "downloadUrl": "https://downloads.example.test/releases/field-v1.0.0/DroneDream-Field-1.0.0.exe",
                        "releaseTag": "field-v1.0.0",
                    },
                ],
                "distinctArtifactSha256": True,
                "distinctDownloadUrl": True,
                "distinctReleaseTag": True,
            },
            "releaseReady": True,
            "releaseConclusion": "release-ready",
            "blockers": [],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_awaiting_contract_is_machine_readable_but_not_release_ready(self) -> None:
        awaiting = handoff._load_json(handoff.CONTRACT_PATH)
        validated = handoff.validate_handoff(
            awaiting, verify_files=False, require_release_ready=False
        )
        self.assertEqual(validated["state"], "awaiting-exact-handoff")
        self.assertFalse(validated["releaseReady"])
        self.assertEqual(validated["edition"]["fileName"], handoff.FILE_NAME)
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "not release-ready"):
            handoff.validate_handoff(awaiting, verify_files=False)

    def test_release_ready_fixture_binds_exact_files_and_url_family(self) -> None:
        validated = handoff.validate_handoff(self.ready)
        self.assertTrue(validated["releaseReady"])
        self.assertEqual(validated["artifact"]["sha256"], sha256(self.artifact))

    def test_rejects_renamed_or_byte_drifted_artifact(self) -> None:
        renamed = copy.deepcopy(self.ready)
        renamed["artifact"]["absolutePath"] = str((self.root / "renamed.exe").resolve())
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "renamed or substituted"):
            handoff.validate_handoff(renamed, verify_files=False)

        drifted = copy.deepcopy(self.ready)
        drifted["artifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "bytes do not match"):
            handoff.validate_handoff(drifted)

    def test_rejects_preview_or_cross_edition_publication(self) -> None:
        preview = copy.deepcopy(self.ready)
        preview["publication"]["releaseTag"] = "lab-preview-v1.0.0"
        preview["publication"]["urlFamily"] = "https://downloads.example.test/releases/lab-preview-v1.0.0/"
        for key in ("downloadUrl", "checksumUrl", "receiptUrl", "manifestUrl"):
            preview["publication"][key] = preview["publication"][key].replace(
                "/lab-v1.0.0/", "/lab-preview-v1.0.0/"
            )
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "substitution"):
            handoff.validate_handoff(preview, verify_files=False)

    def test_rejects_incomplete_install_or_locale_boundary(self) -> None:
        incomplete = copy.deepcopy(self.ready)
        incomplete["validation"]["overlayInstall"] = "not-run"
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "every install and locale"):
            handoff.validate_handoff(incomplete, verify_files=False)

    def test_rejects_cross_edition_sha_url_or_tag_collision(self) -> None:
        duplicate = copy.deepcopy(self.ready)
        sibling = duplicate["crossEditionValidation"]["comparedEditions"][1]
        sibling["artifactSha256"] = duplicate["artifact"]["sha256"]
        sibling["downloadUrl"] = duplicate["publication"]["downloadUrl"]
        sibling["releaseTag"] = duplicate["publication"]["releaseTag"]
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "duplicated"):
            handoff.validate_handoff(duplicate, verify_files=False)

    def test_rejects_receiver_or_signature_claim_drift(self) -> None:
        receiver = copy.deepcopy(self.ready)
        receiver["receiver"]["websiteSourceCommit"] = "b" * 40
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "receiver identity"):
            handoff.validate_handoff(receiver, verify_files=False)

        signature = copy.deepcopy(self.ready)
        signature["artifact"]["updaterSignature"]["state"] = "issued"
        with self.assertRaisesRegex(handoff.LabWebsiteHandoffError, "absolute path"):
            handoff.validate_handoff(signature, verify_files=False)


if __name__ == "__main__":
    unittest.main()
