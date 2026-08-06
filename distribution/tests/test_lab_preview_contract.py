from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB_EDITION = ROOT / "distribution" / "editions" / "lab.v1.json"
VEHICLE_PACK_REGISTRY = ROOT / "distribution" / "vehicle-packs" / "registry.v1.json"
LAB_UI_ADAPTER = ROOT / "frontend" / "src" / "lab" / "vehicle-pack-adapter.v1.json"
LAB_UI_RECEIPT = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-ui-1.0.0-19f6185.functional-prebrand.json"
)
READINESS_RECEIPT = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-yellow-readiness-1.0.0-8654d44.brand-linker-blocked.json"
)
WEBSITE_HANDOFF_READINESS_RECEIPT = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-yellow-readiness-1.0.0-d3adbcc.website-handoff-linker-blocked.json"
)
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import lab_preinstall_acceptance as lab_preinstall  # noqa: E402
import lab_yellow_readiness_audit as lab_readiness  # noqa: E402
import verify_lab_preview_artifact as lab_artifact  # noqa: E402
import verify_lab_preview_contract as lab_preview  # noqa: E402


def fake_gnullvm_toolchain(*blockers: str) -> dict[str, object]:
    ready = not blockers
    return {
        "selectedToolchain": "gnullvm" if ready else None,
        "selectionPolicy": "strict-pinned-gnullvm",
        "strictPinnedToolchainReady": ready,
        "candidates": {
            "gnullvm": {
                "requiresMsvcLinkExe": False,
                "strictlyPinnedReady": ready,
                "llvmRoot": "fixture/llvm-mingw-20260616-ucrt-x86_64",
                "blockers": list(blockers),
            },
            "msvc": {
                "requiredLinker": "link.exe",
                "linkerAvailable": False,
                "linkerPath": None,
                "ready": False,
            },
        },
        "environment": {
            "expectedCargoTargetDir": "fixture/lab-cargo-target",
            "cargoTargetIsRepositoryTarget": False,
        },
        "tauriInvoked": False,
        "nsisInvoked": False,
    }


class LabPreviewContractTests(unittest.TestCase):
    def test_lab_preview_profile_is_unsigned_source_bound_and_fail_closed(self) -> None:
        result = lab_preview.verify_lab_preview_contract()
        self.assertEqual(result["artifactFileName"], "DroneDream-Lab-1.0.0.exe")
        self.assertEqual(result["profile"], "distribution/build-profiles/lab-preview.v1.json")
        profile = json.loads(
            (ROOT / result["profile"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            profile["commonCore"]["productSourceHash"],
            lab_artifact.common_core_hash(
                profile["commonCore"]["productSourceCommit"]
            ),
        )
        self.assertEqual(profile["signaturePolicy"]["authenticode"], "not-signed")
        self.assertEqual(profile["signaturePolicy"]["tauriUpdaterSignature"], "required")
        self.assertEqual(profile["signaturePolicy"]["updaterKeyId"], "BA3FDCAF71CE2FF5")

    def test_lab_build_separates_internal_product_and_unicode_display_names(self) -> None:
        script = (ROOT / "desktop/scripts/build-lab-preview.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Get-Content -LiteralPath $tauriOverlayPath -Raw -Encoding UTF8",
            script,
        )
        self.assertIn("$tauriProductName = [string]$tauriOverlay.productName", script)
        self.assertIn(
            "$tauriDisplayName = [string]$tauriOverlay.app.windows[0].title",
            script,
        )
        self.assertIn("displayName = $tauriDisplayName", script)
        self.assertLess(
            script.index("if (-not $Build)"),
            script.index("Test-Path -LiteralPath $env:TAURI_SIGNING_PRIVATE_KEY_PATH"),
        )
        self.assertNotIn('"DroneDream · LAB"', script)

    def test_lab_build_writes_python_compatible_receipt_bytes(self) -> None:
        script = (ROOT / "desktop/scripts/build-lab-preview.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '$coreListing.Replace("`r`n", "`n").Replace("`r", "`n").Trim()',
            script,
        )
        self.assertIn("[IO.File]::WriteAllText($receiptPath, $receiptJson, $utf8NoBom)", script)
        self.assertNotIn(
            "$receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8",
            script,
        )
        self.assertIn(
            "distribution\\schemas\\lab-website-exact-exe-handoff.schema.json",
            script,
        )
        self.assertNotIn("website-exact-exe-handoff.awaiting.v1.json", script)
        self.assertIn('representation = "relative-to-receipt-parent"', script)
        self.assertIn("path = $artifactName", script)
        self.assertIn('path = "${artifactName}.sig"', script)
        self.assertNotIn('$artifactPath.Replace($repoRoot', script)
        self.assertIn("edition-owned build-attempts root", script)

    def test_shared_llvm_build_uses_ordered_cli_config_overlays(self) -> None:
        script = (ROOT / "desktop/scripts/build-windows-llvm.ps1").read_text(
            encoding="utf-8"
        )
        edition_index = script.index("--config $additionalConfig")
        llvm_index = script.index("--config $llvmBundleConfig", edition_index)
        self.assertLess(edition_index, llvm_index)
        self.assertNotIn("$env:TAURI_CONFIG", script)

    def test_fake_lab_artifact_receipt_binds_workspace_module_and_artifact_contracts(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        validated = lab_artifact.validate_receipt(receipt)
        self.assertTrue(validated["testOnly"])
        self.assertEqual(validated["safety"]["hardwareActionDecision"], "deny")
        self.assertFalse(validated["safety"]["uiSwitchCountsAsAuthority"])
        self.assertEqual(
            validated["workspaces"]["hardwareLab"]["deniedHardwareActions"],
            [
                "hardware.parameter.write",
                "hardware.arm",
                "hardware.flight",
                "hardware.hitl.execute",
            ],
        )

    def test_lab_artifact_receipt_rejects_ui_authority_and_hardware_actions(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["workspaces"]["hardwareLab"]["allowedActions"].append("hardware.arm")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "hardware actions"):
            lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["safety"]["uiSwitchCountsAsAuthority"] = True
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "authority"):
            lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["brand"]["grantsHardwareAuthority"] = True
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "visual brand"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_updater_signature_identity_drift(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["artifact"]["tauriUpdaterSignature"]["keyId"] = "PRODUCTION-NAMING-KEY"
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "updater signature"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_brand_asset_drift(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["brand"]["installerIcon"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "installerIcon"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_website_handoff_contract_drift(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["websiteHandoffContract"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "websiteHandoffContract"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_field_or_universal_bootstrapper_mixing(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["moduleGraph"]["gatedHardwareAdapter"].append("runtime-base-field-lightweight")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "Field-only"):
            lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["moduleGraph"]["simulationPayload"].append("universal-bootstrapper")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "Universal bootstrapper"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_notice_drift_and_missing_real_artifact(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["licenseNotice"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "licenseNotice"):
            lab_artifact.validate_receipt(receipt)

        common_core_commit = lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["commonCoreCommit"] = common_core_commit
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(common_core_commit)
        receipt["testOnly"] = False
        with tempfile.TemporaryDirectory() as artifact_root, self.assertRaisesRegex(
            lab_artifact.LabPreviewArtifactError,
            "artifact file is missing",
        ):
            lab_artifact.validate_receipt(
                receipt,
                artifact_root=Path(artifact_root),
            )

    def test_real_lab_artifact_receipt_resolves_inside_external_owned_root(self) -> None:
        common_core_commit = lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["commonCoreCommit"] = common_core_commit
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(common_core_commit)
        receipt["testOnly"] = False
        with tempfile.TemporaryDirectory() as artifact_root:
            root = Path(artifact_root)
            artifact = root / receipt["artifact"]["path"]
            signature = root / receipt["artifact"]["tauriUpdaterSignature"]["path"]
            artifact.write_bytes(b"fake-lab-installer")
            signature.write_bytes(b"fake-updater-signature")
            receipt["artifact"]["bytes"] = artifact.stat().st_size
            receipt["artifact"]["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            receipt["artifact"]["tauriUpdaterSignature"]["sha256"] = hashlib.sha256(
                signature.read_bytes()
            ).hexdigest()
            validated = lab_artifact.validate_receipt(receipt, artifact_root=root)
            self.assertEqual(validated["artifactRoot"]["ownership"], "edition-owned-output-root")
            preinstall = lab_preinstall.evaluate_preinstall(receipt, artifact_root=root)
            self.assertIsNotNone(preinstall["receipt"])
            self.assertEqual(preinstall["receipt"]["artifactFileName"], "DroneDream-Lab-1.0.0.exe")
            self.assertEqual(preinstall["decision"], "blocked")

    def test_lab_artifact_receipt_rejects_external_root_traversal_forms(self) -> None:
        unsafe_paths = (
            "../outside.exe",
            "subdir/../../outside.exe",
            "C:/outside.exe",
            "C:outside.exe",
            "//server/share/outside.exe",
            "\\\\server\\share\\outside.exe",
            "DroneDream-Lab-1.0.0.exe:stream",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe):
                receipt = lab_artifact.fake_lab_preview_receipt()
                receipt["artifact"]["path"] = unsafe
                with self.assertRaisesRegex(
                    lab_artifact.LabPreviewArtifactError,
                    "artifact.path",
                ):
                    lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["artifact"]["tauriUpdaterSignature"]["path"] = "../outside.sig"
        with self.assertRaisesRegex(
            lab_artifact.LabPreviewArtifactError,
            "tauriUpdaterSignature.path",
        ):
            lab_artifact.validate_receipt(receipt)

    def test_real_lab_artifact_receipt_rejects_relative_or_unc_root(self) -> None:
        common_core_commit = lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["commonCoreCommit"] = common_core_commit
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(common_core_commit)
        receipt["testOnly"] = False
        with self.assertRaisesRegex(
            lab_artifact.LabPreviewArtifactError,
            "absolute local path",
        ):
            lab_artifact.validate_receipt(receipt, artifact_root=Path("relative-root"))
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "UNC"):
            lab_artifact.validate_receipt(
                receipt,
                artifact_root=Path("//server/share/lab-output"),
            )

    def test_lab_artifact_receipt_rejects_sim_preview_evidence_as_product_source(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["testOnly"] = False
        receipt["commonCoreCommit"] = lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(
            lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT,
        )
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "product source"):
            lab_artifact.validate_receipt(receipt, verify_artifact_file=False)

    def test_lab_artifact_receipt_schema_is_closed_and_versioned(self) -> None:
        schema = lab_artifact._load_json(lab_artifact.SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["kind"]["const"],
            "dronedream-lab-preview-artifact-receipt",
        )
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
        self.assertEqual(schema["properties"]["receiptVersion"]["const"], "1.1.0")
        self.assertIn("artifactRoot", schema["required"])

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["schemaVersion"] = 1
        receipt["receiptVersion"] = "1.0.0"
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "unsupported"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_manifest_has_independent_chinese_copy(self) -> None:
        manifest = json.loads(LAB_EDITION.read_text(encoding="utf-8"))
        self.assertEqual(manifest["displayName"]["en"], "DroneDream · LAB")
        self.assertEqual(manifest["displayName"]["zh-CN"], "DroneDream · LAB")
        self.assertEqual(
            manifest["description"]["zh-CN"],
            "统一提供仿真、HITL 与真机实验，"
            "但所有真机能力都必须通过 native、Runtime 与后端三层安全门。",
        )
        self.assertNotEqual(manifest["description"]["zh-CN"], manifest["description"]["en"])

    def test_lab_ui_vehicle_adapter_matches_authoritative_registry(self) -> None:
        registry = json.loads(VEHICLE_PACK_REGISTRY.read_text(encoding="utf-8"))
        adapter = json.loads(LAB_UI_ADAPTER.read_text(encoding="utf-8"))
        self.assertEqual(adapter["kind"], "dronedream-lab-vehicle-pack-ui-adapter")
        self.assertEqual(adapter["source"]["registryVersion"], registry["registryVersion"])
        self.assertEqual(adapter["source"]["auditDate"], registry["auditDate"])
        self.assertEqual(adapter["policy"]["validatedPackCount"], 0)
        self.assertFalse(adapter["policy"]["frontendIsAuthority"])
        self.assertEqual(adapter["policy"]["zeroValidatedPackDecision"], "deny")

        registry_packs = {entry["packId"]: entry for entry in registry["packs"]}
        adapter_packs = {entry["packId"]: entry for entry in adapter["packs"]}
        self.assertEqual(set(adapter_packs), set(registry_packs))
        self.assertEqual(len(adapter_packs), 8)
        for pack_id, registry_entry in registry_packs.items():
            manifest_path = ROOT / registry_entry["manifestPath"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            adapted = adapter_packs[pack_id]
            self.assertEqual(adapted["manifestPath"], registry_entry["manifestPath"])
            self.assertEqual(adapted["manifestSha256"], registry_entry["manifestSha256"])
            self.assertEqual(adapted["displayName"], manifest["displayName"])
            self.assertEqual(adapted["validationStatus"], manifest["validationStatus"])
            self.assertEqual(adapted["validationTier"], manifest["validationTier"])
            self.assertEqual(adapted["supportedEditions"], manifest["supportedEditions"])
            self.assertEqual(adapted["autopilotFamily"], manifest["autopilot"]["family"])
            expected_controllers = [
                {
                    "vendor": controller["vendor"],
                    "model": controller["model"],
                    "status": controller["status"],
                }
                for controller in manifest["controllers"]
            ]
            self.assertEqual(adapted["controllers"], expected_controllers)
            self.assertEqual(
                adapted["firmwareVersions"],
                manifest["autopilot"]["supportedFirmwareVersions"],
            )

    def test_lab_functional_ui_receipt_does_not_overstate_brand_or_hardware(self) -> None:
        receipt = json.loads(LAB_UI_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "functional-prebrand")
        self.assertEqual(receipt["source"]["commit"], "19f61854631319b475eec8649d59f205a41432cc")
        self.assertEqual(
            receipt["commonCore"]["productSourceCommit"],
            lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT,
        )
        self.assertEqual(
            receipt["commonCore"]["commonCoreHash"],
            lab_artifact.common_core_hash(lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT),
        )
        self.assertEqual(receipt["visualVerification"]["screenshotCount"], 24)
        report_path = ROOT / receipt["visualVerification"]["report"]["path"]
        report_bytes = report_path.read_bytes()
        self.assertEqual(len(report_bytes), receipt["visualVerification"]["report"]["bytes"])
        self.assertEqual(
            hashlib.sha256(report_bytes).hexdigest(),
            receipt["visualVerification"]["report"]["sha256"],
        )
        report = json.loads(report_bytes.decode("utf-8"))
        self.assertEqual(report["sourceCommit"], receipt["source"]["commit"])
        self.assertEqual(len(report["screenshots"]), 24)
        self.assertFalse(receipt["visualVerification"]["brandAcceptance"])
        self.assertEqual(
            receipt["brand"]["status"],
            "blocked-awaiting-canonical-universal-donor",
        )
        self.assertEqual(receipt["brand"]["requiredName"], "DroneDream · LAB")
        self.assertEqual(
            receipt["brand"]["requiredPalette"],
            ["#A7E84A", "#20C77A", "#087E69"],
        )
        self.assertIsNone(receipt["brand"]["canonicalDonorCommit"])
        self.assertFalse(receipt["installerStructure"]["editionBrandApplied"])
        self.assertEqual(receipt["safety"]["validatedVehiclePackCount"], 0)
        self.assertFalse(receipt["safety"]["frontendIsAuthority"])
        self.assertEqual(receipt["safety"]["hardwareActionDecision"], "deny")
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))

    def test_lab_preinstall_acceptance_is_read_only_and_blocked_without_real_receipt(self) -> None:
        result = lab_preinstall.evaluate_preinstall()
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("No Lab artifact receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

        result = lab_preinstall.evaluate_preinstall(lab_artifact.fake_lab_preview_receipt())
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("Only a fake test fixture receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

    def test_lab_yellow_readiness_audit_is_read_only_and_requestable(self) -> None:
        result = lab_readiness.evaluate_readiness(
            require_clean=False,
            toolchain_state=fake_gnullvm_toolchain(),
        )
        self.assertEqual(result["kind"], "dronedream-lab-yellow-readiness-audit")
        self.assertTrue(result["yellowBuildRequest"]["requestable"])
        self.assertEqual(
            result["yellowBuildRequest"]["requestBlockers"],
            result["safetyAndOAuthSourceReadiness"]["blockers"],
        )
        self.assertTrue(result["safetyAndOAuthSourceReadiness"]["sourceReady"])
        self.assertFalse(
            result["safetyAndOAuthSourceReadiness"]["oauth"][
                "providerExecutionEvidenceCollected"
            ]
        )
        self.assertEqual(
            result["commonCore"]["productSourceCommit"],
            lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT,
        )
        self.assertEqual(
            result["commonCore"]["excludedSimPreviewEvidenceCommit"],
            lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT,
        )
        self.assertFalse(result["commonCore"]["observedOriginHeadIsProductSource"])
        self.assertTrue(result["publicSupabaseClientConfigSource"]["sourceUsesVitePublicEnv"])
        self.assertTrue(result["publicSupabaseClientConfigSource"]["desktopVerifierRejectsServiceRole"])
        self.assertFalse(result["publicSupabaseClientConfigSource"]["actualEnvironmentRead"])
        self.assertEqual(result["vehiclePacks"]["validatedPackCount"], 0)
        self.assertEqual(result["safety"]["hardwareActionDecisionAtZeroValidatedPacks"], "deny")
        self.assertFalse(result["postBuildAcceptance"]["installableNow"])
        self.assertTrue(result["brand"]["readyForYellowBuild"])
        self.assertFalse(result["brand"]["grantsHardwareAuthority"])
        self.assertEqual(
            result["websiteExactExeHandoff"]["state"],
            "exact-artifact",
        )
        self.assertFalse(result["websiteExactExeHandoff"]["releaseReady"])
        self.assertEqual(result["toolchain"]["selectedToolchain"], "gnullvm")
        self.assertFalse(
            result["toolchain"]["candidates"]["gnullvm"]["requiresMsvcLinkExe"]
        )
        self.assertFalse(
            result["toolchain"]["candidates"]["msvc"]["linkerAvailable"]
        )
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

    def test_lab_yellow_readiness_blocks_when_pinned_gnullvm_bytes_drift(self) -> None:
        result = lab_readiness.evaluate_readiness(
            require_clean=False,
            toolchain_state=fake_gnullvm_toolchain(
                "one or more pinned LLVM-MinGW tool bytes drifted"
            ),
        )
        self.assertFalse(result["yellowBuildRequest"]["requestable"])
        self.assertIn(
            "strict pinned gnullvm: one or more pinned LLVM-MinGW tool bytes drifted",
            result["yellowBuildRequest"]["requestBlockers"],
        )
        self.assertFalse(result["toolchain"]["tauriInvoked"])
        self.assertFalse(result["toolchain"]["nsisInvoked"])

    def test_lab_yellow_readiness_blocks_when_cached_nsis_is_missing(self) -> None:
        result = lab_readiness.evaluate_readiness(
            require_clean=False,
            toolchain_state=fake_gnullvm_toolchain(
                "pinned cached NSIS executable is unavailable or drifted"
            ),
        )
        self.assertFalse(result["yellowBuildRequest"]["requestable"])
        self.assertIn(
            "strict pinned gnullvm: pinned cached NSIS executable is unavailable or drifted",
            result["yellowBuildRequest"]["requestBlockers"],
        )

    @unittest.skipUnless(sys.platform == "win32", "real toolchain probe is Windows-only")
    def test_real_toolchain_probe_is_green_read_only(self) -> None:
        toolchain = lab_readiness._toolchain_state()
        self.assertFalse(toolchain["tauriInvoked"])
        self.assertFalse(toolchain["nsisInvoked"])
        self.assertFalse(
            toolchain["candidates"]["gnullvm"]["requiresMsvcLinkExe"]
        )
        self.assertIsInstance(toolchain["candidates"]["gnullvm"]["blockers"], list)

    def test_real_readiness_receipt_preserves_the_linker_blocker(self) -> None:
        receipt = json.loads(READINESS_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "blocked-before-yellow-request")
        self.assertEqual(
            receipt["source"]["commit"],
            "8654d441b8759e66984285a0914e051f4ca1a8e2",
        )
        self.assertTrue(receipt["brand"]["readyForYellowBuild"])
        self.assertFalse(receipt["brand"]["grantsHardwareAuthority"])
        self.assertEqual(receipt["toolchain"]["requiredLinker"], "link.exe")
        self.assertFalse(receipt["toolchain"]["linkerAvailable"])
        self.assertFalse(receipt["yellowBuildRequest"]["requestable"])
        self.assertEqual(
            receipt["yellowBuildRequest"]["requestBlockers"],
            ["required Rust host linker is unavailable: link.exe"],
        )
        self.assertFalse(receipt["postBuildAcceptance"]["installableNow"])
        self.assertFalse(receipt["postBuildAcceptance"]["executableExists"])
        self.assertEqual(receipt["postBuildAcceptance"]["validatedVehiclePackCount"], 0)
        self.assertEqual(receipt["postBuildAcceptance"]["hardwareActionDecision"], "deny")
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))

    def test_website_handoff_readiness_receipt_preserves_awaiting_state(self) -> None:
        receipt = json.loads(
            WEBSITE_HANDOFF_READINESS_RECEIPT.read_text(encoding="utf-8")
        )
        self.assertEqual(
            receipt["source"]["head"],
            "d3adbcce59ba08113599b6ac6d772cb32394c30d",
        )
        self.assertEqual(
            receipt["websiteExactExeHandoff"]["receiverSourceCommit"],
            "afdcdee5b60883290c9d1cc0c036141920066659",
        )
        self.assertEqual(
            receipt["websiteExactExeHandoff"]["receiverEvidenceCommit"],
            "1a82e36b362c95983473c4a0d0d967d8c7415f92",
        )
        self.assertEqual(
            receipt["websiteExactExeHandoff"]["fileName"],
            "DroneDream-Lab-1.0.0.exe",
        )
        self.assertEqual(
            receipt["websiteExactExeHandoff"]["state"],
            "awaiting-exact-handoff",
        )
        self.assertFalse(receipt["websiteExactExeHandoff"]["releaseReady"])
        self.assertEqual(
            receipt["yellowBuildRequest"]["requestBlockers"],
            ["required Rust host linker is unavailable: link.exe"],
        )
        self.assertFalse(receipt["toolchain"]["tauriInvoked"])
        self.assertFalse(receipt["toolchain"]["nsisInvoked"])
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))


if __name__ == "__main__":
    unittest.main()
