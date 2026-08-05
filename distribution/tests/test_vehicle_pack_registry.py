from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
INVENTORY_PATH = DISTRIBUTION / "upstream-sources.v1.json"
PACK_DIRECTORY = DISTRIBUTION / "vehicle-packs"
REGISTRY_PATH = PACK_DIRECTORY / "registry.v1.json"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "vehicle-pack-registry.schema.json"
JCS_VERIFIER = DISTRIBUTION / "tools" / "verify_vehicle_pack_jcs.mjs"
PACK_PATHS = sorted(
    path for path in PACK_DIRECTORY.glob("*.json") if not path.name.startswith("registry.")
)

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract_vehicle_pack_registry",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


class VehiclePackRegistryTests(unittest.TestCase):
    registry: ClassVar[dict[str, Any]]
    packs_by_path: ClassVar[dict[str, dict[str, Any]]]
    manifest_shas: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        packs_by_id = distribution_contract.load_vehicle_pack_manifests(
            PACK_PATHS,
            upstream_inventory_path=INVENTORY_PATH,
            capability_policy_path=POLICY_PATH,
        )
        cls.packs_by_path = {}
        cls.manifest_shas = {}
        for path in PACK_PATHS:
            document = json.loads(path.read_text(encoding="utf-8"))
            relative_path = path.relative_to(ROOT).as_posix()
            cls.packs_by_path[relative_path] = packs_by_id[document["packId"]]
            cls.manifest_shas[relative_path] = distribution_contract.sha256_file(path)
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def validate(self, document: object) -> dict[str, Any]:
        return distribution_contract.validate_vehicle_pack_registry(
            document,
            vehicle_packs_by_path=self.packs_by_path,
            vehicle_pack_manifest_sha256=self.manifest_shas,
        )

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(
            schema["properties"]["kind"]["const"],
            "dronedream-vehicle-pack-registry",
        )

    def test_registry_loads_exact_initial_pack_set_without_validated_claims(self) -> None:
        loaded = distribution_contract.load_vehicle_pack_registry(
            REGISTRY_PATH,
            vehicle_pack_paths=PACK_PATHS,
            upstream_inventory_path=INVENTORY_PATH,
            capability_policy_path=POLICY_PATH,
            repository_root=ROOT,
        )
        statuses = [entry["currentValidationStatus"] for entry in loaded["packs"]]
        self.assertEqual(len(loaded["packs"]), 8)
        self.assertEqual(statuses.count("validated"), 0)
        self.assertEqual(statuses.count("contract-only"), 5)
        self.assertEqual(statuses.count("planned"), 3)
        self.assertEqual(
            sum(bool(entry["goldenCandidate"]) for entry in loaded["packs"]),
            3,
        )

    def test_jcs_verifier_accepts_shared_vector_and_every_pack_payload(self) -> None:
        result = subprocess.run(
            ["node", str(JCS_VERIFIER), *(str(path) for path in PACK_PATHS)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_jcs_verifier_rejects_tampered_payload(self) -> None:
        tampered = json.loads(PACK_PATHS[0].read_text(encoding="utf-8"))
        tampered["manufacturer"] = "tampered"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            result = subprocess.run(
                ["node", str(JCS_VERIFIER), str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("payload SHA-256 mismatch", result.stderr)

    def test_registry_rejects_manifest_byte_hash_drift(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][0]["manifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "drifted from file bytes",
        ):
            self.validate(invalid)

    def test_registry_rejects_validation_upgrade_not_present_in_manifest(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][0]["currentValidationStatus"] = "validated"
        invalid["packs"][0]["currentValidationTier"] = "sim-validated"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "currentValidationStatus drifted",
        ):
            self.validate(invalid)

    def test_registry_rejects_support_region_drift(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][1]["supportRegions"] = ["cn", "global"]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "supportRegions drifted",
        ):
            self.validate(invalid)

    def test_registry_rejects_path_traversal(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][0]["manifestPath"] = "distribution/vehicle-packs/../outside.json"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "manifestPath is unsafe",
        ):
            self.validate(invalid)

    def test_registry_rejects_mutable_evidence_after_audit_date(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][0]["availabilityEvidence"][0]["observedDate"] = "2026-08-06"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "must not follow registry auditDate",
        ):
            self.validate(invalid)

    def test_registry_rejects_credential_or_query_in_evidence_url(self) -> None:
        for url in (
            "https://user@example.com/vehicle",
            "https://example.com/vehicle?stock=true",
        ):
            with self.subTest(url=url):
                invalid = deepcopy(self.registry)
                invalid["packs"][0]["availabilityEvidence"][0]["url"] = url
                with self.assertRaisesRegex(
                    distribution_contract.DistributionContractError,
                    "credential-free HTTPS URL",
                ):
                    self.validate(invalid)

    def test_registry_rejects_wrong_golden_candidate_count(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][0]["goldenCandidate"] = False
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "golden candidate count drifted",
        ):
            self.validate(invalid)

    def test_registry_rejects_planned_pack_as_golden_candidate(self) -> None:
        invalid = deepcopy(self.registry)
        invalid["packs"][3]["goldenCandidate"] = False
        invalid["packs"][5]["goldenCandidate"] = True
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "cannot be a golden candidate",
        ):
            self.validate(invalid)

    def test_registry_must_exactly_cover_independently_supplied_manifests(self) -> None:
        omitted_path = next(iter(self.packs_by_path))
        packs = dict(self.packs_by_path)
        shas = dict(self.manifest_shas)
        del packs[omitted_path]
        del shas[omitted_path]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "not independently supplied|exactly cover",
        ):
            distribution_contract.validate_vehicle_pack_registry(
                deepcopy(self.registry),
                vehicle_packs_by_path=packs,
                vehicle_pack_manifest_sha256=shas,
            )


if __name__ == "__main__":
    unittest.main()
