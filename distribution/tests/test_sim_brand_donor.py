from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INTAKE_PATH = ROOT / "distribution" / "sim" / "brand" / "donor-intake.v1.json"
SCHEMA_PATH = (
    ROOT / "distribution" / "sim" / "brand" / "canonical-donor-manifest.schema.json"
)
APPROVED_SCHEMA_PATH = (
    ROOT / "distribution" / "sim" / "brand" / "approved-edition-assets.schema.json"
)
APPROVED_MANIFEST_PATH = (
    ROOT / "distribution" / "sim" / "brand" / "approved-edition-assets.v1.json"
)
RECONCILIATION_PATH = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "canonical-reconciliation-candidate.v1.json"
)
SYNC_AUDIT_PATH = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "canonical-sync-conflict-audit.v1.json"
)
ADOPTION_PATH = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "canonical-donor-adoption-receipt.v1.json"
)
TOOL_PATH = ROOT / "distribution" / "sim" / "tools" / "sim_brand_donor.py"

SPEC = importlib.util.spec_from_file_location("sim_brand_donor", TOOL_PATH)
assert SPEC and SPEC.loader
sim_brand = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sim_brand
SPEC.loader.exec_module(sim_brand)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SimBrandDonorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.intake = sim_brand.validate_donor_intake(load_json(INTAKE_PATH), repo_root=ROOT)

    def manifest(self) -> tuple[dict[str, Any], dict[str, bytes]]:
        payloads: dict[str, bytes] = {}
        assets = []
        for role, (mime_type, pixel_size) in sim_brand.ASSET_REQUIREMENTS.items():
            if mime_type == "image/svg+xml":
                payload = f'<svg xmlns="http://www.w3.org/2000/svg"><title>{role}</title></svg>'.encode()
                suffix = ".svg"
            elif mime_type == "image/png":
                payload = b"\x89PNG\r\n\x1a\n" + role.encode()
                suffix = ".png"
            else:
                payload = b"\x00\x00\x01\x00" + role.encode()
                suffix = ".ico"
            if role == "master-mark-svg":
                asset_path = f"brand/canonical/master/{role}{suffix}"
            else:
                asset_path = f"brand/canonical/sim/{role}{suffix}"
            payloads[asset_path] = payload
            assets.append(
                {
                    "role": role,
                    "path": asset_path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                    "mimeType": mime_type,
                    "width": pixel_size,
                    "height": pixel_size,
                }
            )
        master = assets[0]
        return (
            {
                "schemaVersion": 1,
                "kind": "dronedream-canonical-brand-donor-manifest",
                "manifestVersion": "1.0.0",
                "editionId": "sim",
                "source": {
                    "branch": "codex/software",
                    "donorCommit": "1" * 40,
                    "evidenceCommit": "2" * 40,
                    "commonCoreCommit": "1" * 40,
                    "commonCoreHash": "a" * 64,
                    "commonCorePaths": list(sim_brand.COMMON_CORE_PATHS),
                    "approvedConceptHandoffSha256": sim_brand.CONCEPT_HANDOFF_SHA256,
                },
                "identity": deepcopy(sim_brand.SIM_IDENTITY),
                "palette": deepcopy(sim_brand.SIM_PALETTE),
                "assets": assets,
                "preservation": {
                    "sourceMasterPath": master["path"],
                    "sourceMasterSha256": master["sha256"],
                    "originalWingShapePreserved": True,
                    "whiteFlightPathPreserved": True,
                    "masterWordmarkPreserved": True,
                    "masterRedrawn": False,
                },
                "review": {
                    "status": "reviewed-canonical",
                    "releaseUseAuthorized": True,
                    "conceptOnly": False,
                    "approvalReference": "chief-control-reviewed-donor",
                },
            },
            payloads,
        )

    def validate(
        self,
        manifest: object,
        payloads: dict[str, bytes],
        *,
        observed_hash: str = "a" * 64,
        ancestry_result: bool = True,
    ) -> dict[str, Any]:
        return sim_brand.validate_canonical_donor_manifest(
            manifest,
            intake=self.intake,
            repo_root=ROOT,
            asset_reader=lambda _root, _commit, asset_path: payloads[asset_path],
            common_core_hash_observer=lambda _root, _commit, _paths: observed_hash,
            ancestry_observer=lambda _root, _ancestor, _descendant: ancestry_result,
        )

    def test_schema_and_pending_intake_are_closed(self) -> None:
        schema = load_json(SCHEMA_PATH)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["editionId"]["const"], "sim")
        self.assertEqual(schema["properties"]["assets"]["minItems"], 8)
        self.assertEqual(
            schema["$defs"]["asset"]["properties"]["role"]["enum"],
            list(sim_brand.ASSET_REQUIREMENTS),
        )
        self.assertEqual(self.intake["state"], "awaiting-canonical-donor")
        self.assertTrue(all(value is False for value in self.intake["nonClaims"].values()))

    def test_valid_manifest_binds_source_common_core_and_assets(self) -> None:
        manifest, payloads = self.manifest()
        validated = self.validate(manifest, payloads)
        self.assertEqual(validated["identity"]["displayName"], "DroneDream · SIM")
        self.assertEqual(len(validated["assets"]), 8)

    def test_rejects_common_core_hash_or_commit_drift(self) -> None:
        manifest, payloads = self.manifest()
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "commonCoreHash"):
            self.validate(manifest, payloads, observed_hash="b" * 64)

        invalid = deepcopy(manifest)
        invalid["source"]["commonCoreCommit"] = "3" * 40
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "source/commonCore"):
            self.validate(invalid, payloads)

    def test_rejects_unproven_ancestry(self) -> None:
        manifest, payloads = self.manifest()
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "minimum commonCore"):
            self.validate(manifest, payloads, ancestry_result=False)

    def test_rejects_asset_role_sha_bytes_or_dimensions_drift(self) -> None:
        manifest, payloads = self.manifest()
        invalid = deepcopy(manifest)
        invalid["assets"] = invalid["assets"][:-1]
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "inventory"):
            self.validate(invalid, payloads)

        invalid = deepcopy(manifest)
        invalid["assets"][3]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "bytes or SHA-256"):
            self.validate(invalid, payloads)

        invalid = deepcopy(manifest)
        invalid["assets"][3]["width"] = 31
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "dimensions"):
            self.validate(invalid, payloads)

    def test_rejects_palette_preservation_or_review_overclaim(self) -> None:
        manifest, payloads = self.manifest()
        invalid = deepcopy(manifest)
        invalid["palette"]["middle"] = "#000000"
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "palette"):
            self.validate(invalid, payloads)

        invalid = deepcopy(manifest)
        invalid["preservation"]["masterRedrawn"] = True
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "preservation"):
            self.validate(invalid, payloads)

        invalid = deepcopy(manifest)
        invalid["review"]["conceptOnly"] = True
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "review"):
            self.validate(invalid, payloads)

    def test_approved_edition_assets_are_exact_authorized_source_bytes(self) -> None:
        schema = load_json(APPROVED_SCHEMA_PATH)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["assets"]["minItems"], 2)
        manifest = sim_brand.validate_approved_edition_assets(
            load_json(APPROVED_MANIFEST_PATH),
            repo_root=ROOT,
            require_source_assets=True,
        )
        self.assertEqual(
            manifest["authorization"]["status"],
            "chief-control-approved-byte-for-byte",
        )
        self.assertEqual(
            [asset["role"] for asset in manifest["assets"]],
            ["sim-mark-png", "sim-dot-lockup-png"],
        )
        self.assertTrue(manifest["integrationState"]["assetBytesVendored"])
        self.assertTrue(manifest["integrationState"]["applicationSourceWired"])
        self.assertFalse(manifest["integrationState"]["canonicalUniversalDonorIntegrated"])

    def test_approved_edition_assets_reject_provenance_or_common_core_drift(self) -> None:
        invalid = load_json(APPROVED_MANIFEST_PATH)
        invalid["assets"][0]["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "provenance drifted"):
            sim_brand.validate_approved_edition_assets(invalid, repo_root=ROOT)

        invalid = load_json(APPROVED_MANIFEST_PATH)
        invalid["commonCoreBinding"]["commonCoreCommit"] = "0" * 40
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "commonCore binding"):
            sim_brand.validate_approved_edition_assets(invalid, repo_root=ROOT)

        invalid = load_json(APPROVED_MANIFEST_PATH)
        invalid["integrationState"]["applicationSourceWired"] = False
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "integration state"):
            sim_brand.validate_approved_edition_assets(invalid, repo_root=ROOT)

    def test_approved_edition_assets_reject_execution_or_release_overclaim(self) -> None:
        for key in (
            "windowsIcoGenerated",
            "browserAcceptanceExecuted",
            "installerBuilt",
            "canonicalUniversalDonorIntegrated",
            "promotionReady",
        ):
            with self.subTest(key=key):
                invalid = load_json(APPROVED_MANIFEST_PATH)
                invalid["integrationState"][key] = True
                with self.assertRaisesRegex(
                    sim_brand.SimBrandDonorError, "integration state overclaims"
                ):
                    sim_brand.validate_approved_edition_assets(invalid, repo_root=ROOT)

    def test_canonical_candidate_reconciles_hashes_without_adoption(self) -> None:
        candidate = sim_brand.validate_canonical_reconciliation_candidate(
            load_json(RECONCILIATION_PATH), repo_root=ROOT
        )
        self.assertEqual(
            candidate["state"],
            "observed-not-adopted-awaiting-authoritative-handoff",
        )
        self.assertFalse(candidate["observedSource"]["authoritativeHandoffReceived"])
        self.assertIsNone(candidate["observedSource"]["sourceEvidenceHead"])
        self.assertTrue(
            all(value is False for value in candidate["adoptionGates"].values())
        )
        ico = next(
            item
            for item in candidate["generatedCandidates"]
            if item["role"] == "sim-windows-ico"
        )
        self.assertEqual(
            ico["sha256"],
            "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c",
        )
        self.assertFalse(candidate["adoptionGates"]["releaseAssetClaimed"])

    def test_canonical_candidate_rejects_ref_core_or_exact_byte_drift(self) -> None:
        invalid = load_json(RECONCILIATION_PATH)
        invalid["canonicalRefs"]["assetManifest"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "assetManifest SHA-256"):
            sim_brand.validate_canonical_reconciliation_candidate(invalid, repo_root=ROOT)

        invalid = load_json(RECONCILIATION_PATH)
        invalid["commonCoreCandidate"]["hash"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "commonCoreHash"):
            sim_brand.validate_canonical_reconciliation_candidate(invalid, repo_root=ROOT)

        invalid = load_json(RECONCILIATION_PATH)
        invalid["exactByteReconciliation"]["assets"][0]["canonicalSha256"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "metadata drifted"):
            sim_brand.validate_canonical_reconciliation_candidate(invalid, repo_root=ROOT)

    def test_canonical_candidate_rejects_handoff_or_release_overclaim(self) -> None:
        invalid = load_json(RECONCILIATION_PATH)
        invalid["observedSource"]["authoritativeHandoffReceived"] = True
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "overclaims adoption"):
            sim_brand.validate_canonical_reconciliation_candidate(invalid, repo_root=ROOT)

    def test_canonical_adoption_binds_donor_core_and_nine_frame_ico(self) -> None:
        adoption = sim_brand.validate_canonical_donor_adoption_receipt(
            load_json(ADOPTION_PATH), repo_root=ROOT
        )
        self.assertEqual(
            adoption["source"]["brandDonorCommit"],
            "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
        )
        self.assertEqual(
            adoption["source"]["commonCoreCommit"],
            "e374d3f8d96b1265fcdb06864208b676566e94d9",
        )
        self.assertFalse(adoption["source"]["commonCoreUpdated"])
        ico = next(
            item
            for item in adoption["assetBindings"]
            if item["role"] == "sim-windows-ico"
        )
        self.assertEqual(ico["bytes"], 54431)
        self.assertEqual(ico["frameSizesPx"], [16, 20, 24, 32, 40, 48, 64, 128, 256])
        self.assertFalse(adoption["nonClaims"]["releaseAsset"])

    def test_canonical_adoption_rejects_core_asset_or_semantic_drift(self) -> None:
        invalid = deepcopy(load_json(ADOPTION_PATH))
        invalid["source"]["commonCoreUpdated"] = True
        with self.assertRaisesRegex(
            sim_brand.SimBrandDonorError, "donor and commonCore classification"
        ):
            sim_brand.validate_canonical_donor_adoption_receipt(invalid, repo_root=ROOT)

        invalid = deepcopy(load_json(ADOPTION_PATH))
        invalid["assetBindings"][2]["frameSizesPx"] = [256]
        with self.assertRaisesRegex(
            sim_brand.SimBrandDonorError, "asset metadata"
        ):
            sim_brand.validate_canonical_donor_adoption_receipt(invalid, repo_root=ROOT)

        invalid = deepcopy(load_json(ADOPTION_PATH))
        invalid["semanticSync"]["editionRadioPresent"] = True
        with self.assertRaisesRegex(
            sim_brand.SimBrandDonorError, "semantic boundary"
        ):
            sim_brand.validate_canonical_donor_adoption_receipt(invalid, repo_root=ROOT)

        invalid = deepcopy(load_json(ADOPTION_PATH))
        invalid["nonClaims"]["releaseAsset"] = True
        with self.assertRaisesRegex(
            sim_brand.SimBrandDonorError, "overclaims readiness"
        ):
            sim_brand.validate_canonical_donor_adoption_receipt(invalid, repo_root=ROOT)

        invalid = load_json(RECONCILIATION_PATH)
        invalid["adoptionGates"]["releaseAssetClaimed"] = True
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "must remain false"):
            sim_brand.validate_canonical_reconciliation_candidate(invalid, repo_root=ROOT)

    def test_sync_audit_recomputes_paths_blobs_and_patches_without_merge(self) -> None:
        audit = sim_brand.validate_canonical_sync_conflict_audit(
            load_json(SYNC_AUDIT_PATH), repo_root=ROOT
        )
        self.assertEqual(
            (
                audit["pathObservation"]["simChangedPathCount"],
                audit["pathObservation"]["donorChangedPathCount"],
                audit["pathObservation"]["overlapPathCount"],
            ),
            (39, 104, 2),
        )
        self.assertEqual(
            audit["conflictResolution"][0]["evidence"]["simPatch"]["sha256"],
            "d073563b082578e52ba1ccafd393be4dfe5746576cc6a3a11087768834333533",
        )
        self.assertTrue(all(value is False for value in audit["execution"].values()))

    def test_sync_audit_rejects_path_blob_or_patch_drift(self) -> None:
        invalid = load_json(SYNC_AUDIT_PATH)
        invalid["pathObservation"]["simChangedPathCount"] = 40
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "statistics drifted"):
            sim_brand.validate_canonical_sync_conflict_audit(invalid, repo_root=ROOT)

        invalid = load_json(SYNC_AUDIT_PATH)
        invalid["conflictResolution"][0]["evidence"]["baseBlob"] = "0" * 40
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "blob or patch evidence"):
            sim_brand.validate_canonical_sync_conflict_audit(invalid, repo_root=ROOT)

        invalid = load_json(SYNC_AUDIT_PATH)
        invalid["conflictResolution"][1]["evidence"]["donorPatch"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "blob or patch evidence"):
            sim_brand.validate_canonical_sync_conflict_audit(invalid, repo_root=ROOT)

    def test_sync_audit_rejects_semantic_or_execution_overclaim(self) -> None:
        invalid = load_json(SYNC_AUDIT_PATH)
        invalid["conflictResolution"][0]["eligibleFromDonorAfterHandoff"] = [
            "canonical-brand-lockup-component"
        ]
        with self.assertRaisesRegex(sim_brand.SimBrandDonorError, "semantic resolution"):
            sim_brand.validate_canonical_sync_conflict_audit(invalid, repo_root=ROOT)

        for key in (
            "mergeExecuted",
            "commonCoreBaselineUpdated",
            "icoCopied",
            "releaseAssetClaimed",
        ):
            with self.subTest(key=key):
                invalid = load_json(SYNC_AUDIT_PATH)
                invalid["execution"][key] = True
                with self.assertRaisesRegex(
                    sim_brand.SimBrandDonorError, "must remain false"
                ):
                    sim_brand.validate_canonical_sync_conflict_audit(
                        invalid, repo_root=ROOT
                    )


if __name__ == "__main__":
    unittest.main()
