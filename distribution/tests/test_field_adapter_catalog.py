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
        self.assertEqual(len(entries), 11)
        identifiers = [entry["adapterId"] for entry in entries]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(
            all(
                re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item)
                for item in identifiers
            )
        )
        for entry in entries:
            safety = entry["safety"]
            self.assertFalse(safety["installationGrantsAuthority"])
            self.assertFalse(safety["discoveryGrantsAuthority"])
            self.assertTrue(safety["requiresValidatedVehiclePackForWrites"])
            self.assertTrue(safety["requiresNativeBackendRuntimeOperatorQuorum"])
        by_id = {entry["adapterId"]: entry for entry in entries}
        self.assertEqual(by_id["dronecan-v1"]["supportedTransports"], ["can", "udp"])
        self.assertNotIn("usb-network", by_id["dronecan-v1"]["supportedTransports"])
        schema = json.loads(
            (ROOT / "distribution/schemas/field-adapter-catalog.schema.json").read_text(
                encoding="utf-8"
            )
        )
        transport_enum = schema["$defs"]["entry"]["properties"]["supportedTransports"][
            "items"
        ]["enum"]
        self.assertEqual(
            transport_enum,
            [
                "serial",
                "can",
                "usb-network",
                "udp",
                "tcp",
                "remote-controller",
                "cloud",
                "radio",
            ],
        )

    def test_managed_packages_are_exact_data_only_and_fail_closed(self) -> None:
        installable = [entry for entry in self.catalog["entries"] if entry["installable"]]
        self.assertEqual(
            {entry["adapterId"] for entry in installable},
            {
                "mavlink-common-v2",
                "mavlink-px4-v2",
                "mavlink-ardupilotmega-v2",
                "crazyflie-crtp",
                "betaflight-msp-v1",
                "dronecan-v1",
                "tello-state-v2",
            },
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
                self.assertIn(
                    package["capabilities"][action],
                    {"quorum-required", "unavailable"},
                )
        tello = json.loads(
            (PACKAGE_ROOT / "tello-state-v2.adapter.json").read_text(encoding="utf-8")
        )
        for action in (
            "parameterRead",
            "parameterWrite",
            "arm",
            "flight",
            "autonomousTuning",
        ):
            self.assertEqual(tello["capabilities"][action], "unavailable")

    def test_vendor_restricted_entries_cannot_be_installed_or_impersonated(self) -> None:
        restricted = [entry for entry in self.catalog["entries"] if not entry["installable"]]
        self.assertEqual(len(restricted), 4)
        for entry in restricted:
            self.assertIsNone(entry["packageSha256"])
            self.assertNotEqual(entry["deliveryMode"], "embedded-managed")
            self.assertNotEqual(entry["implementationStatus"], "available")

    def test_native_parser_has_only_bounded_read_only_serial_transport(self) -> None:
        manifest = (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        mavlink_line = next(line for line in manifest.splitlines() if line.startswith("mavlink ="))
        serial_line = next(
            line for line in manifest.splitlines() if line.startswith("serialport =")
        )
        msp_line = next(
            line for line in manifest.splitlines()
            if line.startswith("multiwii_serial_protocol =")
        )
        dronecan_line = next(
            line for line in manifest.splitlines() if line.startswith("dronecan =")
        )
        self.assertIn('version = "=0.18.0"', mavlink_line)
        self.assertIn('"dialect-common"', mavlink_line)
        self.assertIn('"dialect-ardupilotmega"', mavlink_line)
        self.assertNotRegex(mavlink_line, r"direct-serial|transport-|\btcp\b|\budp\b")
        self.assertIn('version = "=4.9.0"', serial_line)
        self.assertIn("default-features = false", serial_line)
        self.assertIn('version = "=0.1.1"', msp_line)
        self.assertIn("default-features = false", msp_line)
        self.assertIn('version = "=0.1.0"', dronecan_line)
        self.assertIn("default-features = false", dronecan_line)

        source = (ROOT / "desktop/src-tauri/src/field_adapters.rs").read_text(encoding="utf-8")
        self.assertIn("read_any_msg", source)
        self.assertIn("probe_field_mavlink_telemetry", source)
        self.assertIn("serialport::new", source)
        self.assertIn("inspect_field_protocol_frame", source)
        self.assertIn("multiwii_serial_protocol::MspParser", source)
        self.assertIn("dronecan::Id::new", source)
        self.assertIn("inspect_tello_state", source)
        self.assertIn("device_open_attempts: 0", source)
        self.assertIn("device_open_attempts: 1", source)
        self.assertIn("hardware_write_attempts: 0", source)
        self.assertIn("parameter_read_attempts: 0", source)
        self.assertIn("arm_attempts: 0", source)
        self.assertIn("flight_attempts: 0", source)
        self.assertNotRegex(source, r"TcpStream|UdpSocket|gazebo|sitl|hitl")

    def test_shared_source_carries_adapter_notice_and_ui_stays_non_authoritative(self) -> None:
        notice_path = ROOT / "distribution/editions/field/adapters/THIRD_PARTY_NOTICES.md"
        self.assertTrue(notice_path.is_file())
        notice = notice_path.read_text(encoding="utf-8")
        self.assertIn("mavlink 0.18.0", notice)
        self.assertIn("serialport 4.9.0", notice)
        self.assertIn("MultiWii Serial Protocol parser 0.1.1", notice)
        self.assertIn("DroneCAN parser 0.1.0", notice)
        self.assertIn("Bitcraze Crazy RealTime Protocol", notice)
        self.assertIn("Ryze Tello SDK 2.0 State", notice)
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
