from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
INVENTORY_PATH = DISTRIBUTION / "upstream-sources.v1.json"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "upstream-source-inventory.schema.json"
PINS_PATH = ROOT / "runtime" / "pins.env"
PYTHON_LOCK_PATH = ROOT / "runtime" / "locks" / "python-requirements.lock"

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in PINS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            pins[key] = value
    return pins


def _python_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in PYTHON_LOCK_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            versions[name.lower()] = version
    return versions


class UpstreamSourceInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = _load_json(SCHEMA_PATH)
        cls.inventory = _load_json(INVENTORY_PATH)
        cls.sources = {
            source["id"]: source for source in cls.inventory["sources"]  # type: ignore[index]
        }

    def test_inventory_validates_against_versioned_schema(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(self.schema["properties"]["schemaVersion"]["const"], 1)
        self.assertFalse(self.schema["additionalProperties"])
        self.assertIs(
            distribution_contract.validate_upstream_source_inventory(self.inventory),
            self.inventory,
        )

    def test_ids_are_unique(self) -> None:
        ids = [source["id"] for source in self.inventory["sources"]]  # type: ignore[index]
        self.assertEqual(len(ids), len(set(ids)))

    def test_runtime_source_entries_match_reviewed_pins(self) -> None:
        pins = _load_pins()
        python = _python_versions()
        self.assertEqual(
            self.sources["ubuntu-noble-base"]["pin"]["value"],  # type: ignore[index]
            pins["UBUNTU_BASE_IMAGE"],
        )
        self.assertEqual(
            self.sources["px4-autopilot"]["pin"]["value"],  # type: ignore[index]
            pins["PX4_VERSION"],
        )
        self.assertEqual(
            self.sources["px4-autopilot"]["pin"]["commit"],  # type: ignore[index]
            pins["PX4_GIT_COMMIT"],
        )
        self.assertEqual(
            self.sources["gazebo-harmonic"]["pin"]["value"],  # type: ignore[index]
            f'{pins["GAZEBO_METAPACKAGE"]}={pins["GAZEBO_METAPACKAGE_VERSION"]}',
        )
        self.assertEqual(
            self.sources["valkey"]["pin"]["commit"],  # type: ignore[index]
            pins["VALKEY_GIT_COMMIT"],
        )
        self.assertEqual(
            self.sources["mavsdk-python"]["pin"]["value"],  # type: ignore[index]
            pins["MAVSDK_VERSION"],
        )
        self.assertEqual(python["mavsdk"], pins["MAVSDK_VERSION"])
        self.assertEqual(
            self.sources["pyulog"]["pin"]["value"],  # type: ignore[index]
            f'v{pins["PYULOG_VERSION"]}',
        )
        self.assertEqual(python["pyulog"], pins["PYULOG_VERSION"])

    def test_pinned_px4_models_are_the_runtime_submodule_not_latest(self) -> None:
        source = self.sources["px4-gazebo-models"]
        self.assertEqual(
            source["pin"]["commit"],  # type: ignore[index]
            "e05f4312d3f28aa621157610584a4870406cb6d3",
        )
        self.assertIn("PX4-Autopilot@6ea353", source["pin"]["authority"])  # type: ignore[index]

    def test_planned_autopilots_are_not_distributed_or_validated(self) -> None:
        for source_id in ("ardupilot", "ardupilot-gazebo", "crazyflie-firmware"):
            source = self.sources[source_id]
            self.assertEqual(source["integrationStatus"], "planned")
            self.assertEqual(source["integrationMode"], "contract-only")
            self.assertEqual(source["distributionMode"], "not-distributed")
            self.assertNotEqual(source["validationTier"], "integrated-contract")

    def test_qgroundcontrol_remains_an_external_boundary(self) -> None:
        source = self.sources["qgroundcontrol"]
        self.assertEqual(source["integrationMode"], "external-launch-only")
        self.assertEqual(source["distributionMode"], "not-distributed")
        self.assertEqual(source["copiedIntoRepository"], False)
        self.assertEqual(
            set(source["declaredLicenses"]),
            {"Apache-2.0", "GPL-3.0-only"},
        )

    def test_noassertion_entries_are_explicitly_blocked_on_legal_review(self) -> None:
        noassertion = [
            source
            for source in self.sources.values()
            if source["licenseConclusion"] == "NOASSERTION"
        ]
        self.assertGreaterEqual(len(noassertion), 1)
        for source in noassertion:
            self.assertEqual(source["validationTier"], "legal-review-required")
            self.assertTrue(source["declaredLicenses"])

    def test_immutable_evidence_urls_carry_no_credentials_or_mutable_refs(self) -> None:
        immutable_raw = re.compile(
            r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/"
        )
        for source in self.sources.values():
            repository = urlsplit(source["officialRepository"])
            self.assertEqual(repository.scheme, "https")
            self.assertIsNone(repository.username)
            self.assertIsNone(repository.password)
            for evidence in source["licenseEvidence"]:
                parsed = urlsplit(evidence["url"])
                self.assertEqual(parsed.scheme, "https")
                self.assertIsNone(parsed.username)
                self.assertIsNone(parsed.password)
                if "raw.githubusercontent.com" in parsed.netloc:
                    self.assertRegex(evidence["url"], immutable_raw)
                    self.assertRegex(evidence["sha256"], r"^[0-9a-f]{64}$")

    def test_inventory_never_claims_source_was_copied_into_repository(self) -> None:
        self.assertTrue(
            all(source["copiedIntoRepository"] is False for source in self.sources.values())
        )

    def test_validator_rejects_duplicate_ids(self) -> None:
        invalid = deepcopy(self.inventory)
        invalid["sources"][1]["id"] = invalid["sources"][0]["id"]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "duplicate source id",
        ):
            distribution_contract.validate_upstream_source_inventory(invalid)

    def test_validator_rejects_mutable_raw_license_evidence(self) -> None:
        invalid = deepcopy(self.inventory)
        invalid["sources"][1]["licenseEvidence"][0]["url"] = (
            "https://raw.githubusercontent.com/PX4/PX4-Autopilot/main/LICENSE"
        )
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "full commit",
        ):
            distribution_contract.validate_upstream_source_inventory(invalid)

    def test_validator_rejects_bundled_contract_only_dependency(self) -> None:
        invalid = deepcopy(self.inventory)
        source = next(
            source for source in invalid["sources"] if source["id"] == "ardupilot"
        )
        source["distributionMode"] = "runtime-bundled"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "cannot be bundled",
        ):
            distribution_contract.validate_upstream_source_inventory(invalid)

    def test_validator_rejects_unreviewed_noassertion(self) -> None:
        invalid = deepcopy(self.inventory)
        source = next(
            source
            for source in invalid["sources"]
            if source["id"] == "crazyflie-firmware"
        )
        source["validationTier"] = "contract-only"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "requires declared licenses and legal review",
        ):
            distribution_contract.validate_upstream_source_inventory(invalid)

    def test_validator_rejects_unknown_fields(self) -> None:
        invalid = deepcopy(self.inventory)
        invalid["sources"][0]["validated"] = True
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "unsupported validated",
        ):
            distribution_contract.validate_upstream_source_inventory(invalid)


if __name__ == "__main__":
    unittest.main()
