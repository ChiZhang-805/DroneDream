from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "frontend" / "src" / "features" / "distribution" / "catalog.v1.json"
REGISTRY_PATH = ROOT / "distribution" / "vehicle-packs" / "registry.v1.json"
EDITION_PATHS = {
    edition_id: ROOT / "distribution" / "editions" / f"{edition_id}.v1.json"
    for edition_id in ("sim", "lab", "field")
}


class DistributionCatalogParityError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise DistributionCatalogParityError(f"{label} drifted from frozen distribution source")


def validate_frontend_catalog_parity(catalog: dict[str, Any]) -> None:
    require_equal(catalog.get("schemaVersion"), 1, "catalog schemaVersion")
    require_equal(
        catalog.get("kind"),
        "dronedream-frontend-distribution-catalog",
        "catalog kind",
    )
    require_equal(catalog.get("productDisplayVersion"), "1.0.0", "product display version")

    edition_bindings = catalog["sourceBindings"]["editionManifests"]
    frontend_editions = {edition["editionId"]: edition for edition in catalog["editions"]}
    require_equal(set(frontend_editions), set(EDITION_PATHS), "edition coverage")
    require_equal(set(edition_bindings), set(EDITION_PATHS), "edition binding coverage")

    for edition_id, edition_path in EDITION_PATHS.items():
        relative_path = edition_path.relative_to(ROOT).as_posix()
        require_equal(edition_bindings[edition_id]["path"], relative_path, f"{edition_id} path")
        require_equal(
            edition_bindings[edition_id]["sha256"],
            sha256_file(edition_path),
            f"{edition_id} manifest SHA-256",
        )
        source = load_json(edition_path)
        frontend = frontend_editions[edition_id]
        expected = {
            "editionVersion": source["editionVersion"],
            "displayName": source["displayName"],
            "implementationStatus": source["implementationStatus"],
            "validationTier": source["validationTier"],
            "artifactBaseName": source["artifactBaseName"],
            "requiredModules": source["modules"]["required"],
            "optionalModules": source["modules"]["optional"],
            "forbiddenModules": source["modules"]["forbidden"],
            "includesLargeSimulator": source["runtimeProfile"]["includesLargeSimulator"],
        }
        for field, expected_value in expected.items():
            require_equal(frontend[field], expected_value, f"{edition_id}.{field}")
        if frontend["downloadEstimateState"] == "verified":
            if not isinstance(frontend["downloadEstimateBytes"], int):
                raise DistributionCatalogParityError(
                    f"{edition_id} verified download estimate has no integer byte count"
                )
        elif frontend["downloadEstimateBytes"] is not None:
            raise DistributionCatalogParityError(
                f"{edition_id} unverified download estimate must remain null"
            )

    registry_binding = catalog["sourceBindings"]["vehiclePackRegistry"]
    require_equal(
        registry_binding["path"],
        REGISTRY_PATH.relative_to(ROOT).as_posix(),
        "Vehicle Pack registry path",
    )
    require_equal(
        registry_binding["sha256"],
        sha256_file(REGISTRY_PATH),
        "Vehicle Pack registry SHA-256",
    )
    registry = load_json(REGISTRY_PATH)
    registry_entries = {entry["packId"]: entry for entry in registry["packs"]}
    frontend_packs = {pack["packId"]: pack for pack in catalog["vehiclePacks"]}
    require_equal(set(frontend_packs), set(registry_entries), "Vehicle Pack coverage")

    for pack_id, entry in registry_entries.items():
        manifest_path = ROOT / entry["manifestPath"]
        manifest = load_json(manifest_path)
        frontend = frontend_packs[pack_id]
        require_equal(
            entry["manifestSha256"],
            sha256_file(manifest_path),
            f"{pack_id} registry SHA",
        )
        expected = {
            "packVersion": manifest["packVersion"],
            "displayName": manifest["displayName"],
            "manufacturer": manifest["manufacturer"],
            "vehicleClass": manifest["vehicleClass"],
            "supportRegions": manifest["availabilityRegions"],
            "supportedEditions": manifest["supportedEditions"],
            "validationStatus": manifest["validationStatus"],
            "validationTier": manifest["validationTier"],
            "autopilotFamily": manifest["autopilot"]["family"],
            "adapterStatus": manifest["autopilot"]["adapterStatus"],
            "controllers": manifest["controllers"],
            "segments": entry["segments"],
            "goldenCandidate": entry["goldenCandidate"],
            "productAvailability": entry["productAvailability"],
            "manifestSha256": entry["manifestSha256"],
        }
        for field, expected_value in expected.items():
            require_equal(frontend[field], expected_value, f"{pack_id}.{field}")

    statuses = [pack["validationStatus"] for pack in frontend_packs.values()]
    require_equal(statuses.count("validated"), 0, "validated Vehicle Pack count")
    require_equal(statuses.count("contract-only"), 5, "contract-only Vehicle Pack count")
    require_equal(statuses.count("planned"), 3, "planned Vehicle Pack count")
    require_equal(
        sum(bool(pack["goldenCandidate"]) for pack in frontend_packs.values()),
        3,
        "golden candidate count",
    )


class FrontendDistributionCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_json(CATALOG_PATH)

    def test_catalog_is_byte_bound_to_edition_and_vehicle_pack_sources(self) -> None:
        validate_frontend_catalog_parity(self.catalog)

    def test_catalog_rejects_source_hash_drift(self) -> None:
        invalid = deepcopy(self.catalog)
        invalid["sourceBindings"]["vehiclePackRegistry"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(DistributionCatalogParityError, "registry SHA-256"):
            validate_frontend_catalog_parity(invalid)

    def test_catalog_rejects_unearned_validation_upgrade(self) -> None:
        invalid = deepcopy(self.catalog)
        invalid["vehiclePacks"][0]["validationStatus"] = "validated"
        invalid["vehiclePacks"][0]["validationTier"] = "sim-validated"
        with self.assertRaisesRegex(DistributionCatalogParityError, "validationStatus"):
            validate_frontend_catalog_parity(invalid)

    def test_catalog_rejects_verified_size_without_integer_bytes(self) -> None:
        invalid = deepcopy(self.catalog)
        invalid["editions"][0]["downloadEstimateState"] = "verified"
        with self.assertRaisesRegex(DistributionCatalogParityError, "integer byte count"):
            validate_frontend_catalog_parity(invalid)


if __name__ == "__main__":
    unittest.main()
