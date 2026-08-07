import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "distribution/editions/field/adapters/catalog.v1.json"
PACKAGE_ROOT = ROOT / "distribution/editions/field/adapters/packages"


class FieldAdapterCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_catalog_is_field_only_unique_and_non_authoritative(self) -> None:
        self.assertEqual(self.catalog["schemaVersion"], 1)
        self.assertEqual(self.catalog["kind"], "dronedream-field-adapter-catalog")
        self.assertEqual(self.catalog["editionId"], "field")
        self.assertFalse(self.catalog["hardwareAuthority"])
        entries = self.catalog["entries"]
        self.assertEqual(len(entries), 8)
        identifiers = [entry["adapterId"] for entry in entries]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item) for item in identifiers))
        for entry in entries:
            safety = entry["safety"]
            self.assertFalse(safety["installationGrantsAuthority"])
            self.assertFalse(safety["discoveryGrantsAuthority"])
            self.assertTrue(safety["requiresValidatedVehiclePackForWrites"])
            self.assertTrue(safety["requiresNativeBackendRuntimeOperatorQuorum"])

    def test_managed_packages_are_exact_data_only_and_fail_closed(self) -> None:
        installable = [entry for entry in self.catalog["entries"] if entry["installable"]]
        self.assertEqual(
            {entry["adapterId"] for entry in installable},
            {"mavlink-common-v2", "mavlink-px4-v2", "mavlink-ardupilotmega-v2"},
        )
        for entry in installable:
            path = PACKAGE_ROOT / f"{entry['adapterId']}.adapter.json"
            payload = path.read_bytes()
            package = json.loads(payload.decode("utf-8"))
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["packageSha256"])
            self.assertEqual(package["adapterId"], entry["adapterId"])
            self.assertEqual(package["editionId"], "field")
            self.assertFalse(package["safety"]["executableCode"])
            self.assertEqual(package["safety"]["zeroValidatedPackDecision"], "deny")
            for action in ("parameterWrite", "arm", "flight", "autonomousTuning"):
                self.assertEqual(package["capabilities"][action], "quorum-required")

    def test_vendor_restricted_entries_cannot_be_installed_or_impersonated(self) -> None:
        restricted = [entry for entry in self.catalog["entries"] if not entry["installable"]]
        self.assertEqual(len(restricted), 5)
        for entry in restricted:
            self.assertIsNone(entry["packageSha256"])
            self.assertNotEqual(entry["deliveryMode"], "embedded-managed")
            self.assertNotEqual(entry["implementationStatus"], "available")

    def test_native_parser_has_only_bounded_read_only_serial_transport(self) -> None:
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        mavlink_line = next(line for line in manifest.splitlines() if line.startswith("mavlink ="))
        serial_line = next(line for line in manifest.splitlines() if line.startswith("serialport ="))
        self.assertIn('version = "=0.17.1"', mavlink_line)
        self.assertIn('"common"', mavlink_line)
        self.assertIn('"ardupilotmega"', mavlink_line)
        self.assertNotRegex(mavlink_line, r"direct-serial|transport-|\btcp\b|\budp\b")
        self.assertIn('version = "=4.9.0"', serial_line)
        self.assertIn("default-features = false", serial_line)

        source = (ROOT / "desktop/src-tauri/src/field_adapters.rs").read_text(encoding="utf-8")
        self.assertIn("read_any_msg", source)
        self.assertIn("probe_field_mavlink_telemetry", source)
        self.assertIn("serialport::new", source)
        self.assertIn("device_open_attempts: 0", source)
        self.assertIn("device_open_attempts: 1", source)
        self.assertIn("hardware_write_attempts: 0", source)
        self.assertIn("parameter_read_attempts: 0", source)
        self.assertIn("arm_attempts: 0", source)
        self.assertIn("flight_attempts: 0", source)
        self.assertNotRegex(source, r"TcpStream|UdpSocket|gazebo|sitl|hitl")

    def test_field_bundle_carries_adapter_notice_and_ui_stays_non_authoritative(self) -> None:
        config = json.loads(
            (ROOT / "desktop/src-tauri/tauri.field.conf.json").read_text(encoding="utf-8")
        )
        resources = config["bundle"]["resources"]
        self.assertIn(
            "../../distribution/editions/field/adapters/THIRD_PARTY_NOTICES.md",
            resources,
        )
        notice = (ROOT / "distribution/editions/field/adapters/THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("mavlink 0.17.1", notice)
        self.assertIn("serialport 4.9.0", notice)
        self.assertIn("MIT License", notice)
        self.assertIn("Apache License 2.0", notice)
        self.assertIn("Mozilla Public License 2.0", notice)

        ui = (ROOT / "frontend/src/field/FieldAdapterCenter.tsx").read_text(encoding="utf-8")
        expected_catalog_hash = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
        self.assertIn(expected_catalog_hash, ui)
        self.assertIn('data-authority="false"', ui)
        self.assertIn('data-executable-extension-loading="false"', ui)
        self.assertIn("Vehicle Pack validation", ui)


if __name__ == "__main__":
    unittest.main()
