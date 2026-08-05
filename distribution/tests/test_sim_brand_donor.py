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


if __name__ == "__main__":
    unittest.main()
