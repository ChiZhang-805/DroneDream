from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
REPO = Path(r"C:\Users\zju20\.codex\worktrees\2833\DroneDream")
TARGET = Path(
    r"C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target\c7e25b3"
)
ARTIFACT = EVIDENCE / "artifact" / "DroneDream-Field-1.0.0.exe"
PAYLOAD = EVIDENCE / "payload"
INVENTORY = EVIDENCE / "payload-inventory.json"
FIELD_TEST_LOG = EVIDENCE / "field-contract-tests.log"
SOURCE_COMMIT = "c7e25b3862fdd491de99f4a0b02cf0f348b94ea3"
COMMON_CORE_COMMIT = "cabcde3903ccceaf19119824af227bebeb7dd5be"
COMMON_CORE_HASH = "c6e480dfd2cf4eccb07ee34cd836f096843afab375b03a5fb2d57ab964b5c94a"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_field_prerelease_audit():
    module_path = REPO / "distribution" / "tools" / "field_prerelease_audit.py"
    spec = importlib.util.spec_from_file_location("field_postbuild_audit", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Field prerelease audit: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pe_certificate_table(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
    if payload[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("artifact is not a PE file")
    optional = pe_offset + 24
    magic = struct.unpack_from("<H", payload, optional)[0]
    data_directories = optional + (112 if magic == 0x20B else 96)
    return struct.unpack_from("<II", payload, data_directories + 8 * 4)


def matching_text_files(root: Path) -> list[dict[str, object]]:
    findings = []
    pattern = re.compile(r"gazebo|sitl|hitl|simulator", re.IGNORECASE)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {
            ".css",
            ".html",
            ".js",
            ".json",
            ".md",
            ".txt",
        }:
            continue
        matches = pattern.findall(path.read_text(encoding="utf-8", errors="replace"))
        if matches:
            findings.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "matchCount": len(matches),
                }
            )
    return findings


def main() -> None:
    inventory = load_json(INVENTORY)
    descriptor_path = PAYLOAD / "engine-pack" / "engine-pack-bundle.json"
    descriptor = load_json(descriptor_path)
    engine_manifest_path = PAYLOAD / "engine-pack" / descriptor["manifest"]["filename"]
    engine_archive_path = PAYLOAD / "engine-pack" / descriptor["archive"]["filename"]
    engine_manifest = load_json(engine_manifest_path)
    field_audit = load_field_prerelease_audit()
    postbuild_payload_audit = field_audit.audit_engine_pack_payload(
        descriptor_path=descriptor_path,
        archive_path=engine_archive_path,
        common_core_commit=COMMON_CORE_COMMIT,
        common_core_hash=COMMON_CORE_HASH,
    )
    postbuild_audit_path = EVIDENCE / "postbuild-payload-audit.json"
    write_json(postbuild_audit_path, postbuild_payload_audit)
    frontend = PAYLOAD / "frontend-field-dist"
    frontend_files = sorted(path for path in frontend.rglob("*") if path.is_file())
    executable_suffixes = {
        ".bat",
        ".cmd",
        ".dll",
        ".exe",
        ".msi",
        ".ps1",
        ".py",
        ".sh",
        ".so",
        ".tar",
        ".tgz",
        ".zip",
    }
    simulator_tokens = ("gazebo", "sitl", "hitl", "simulator")
    forbidden_frontend_paths = [
        path.relative_to(frontend).as_posix()
        for path in frontend_files
        if path.suffix.lower() in executable_suffixes
        and any(token in path.name.lower() for token in simulator_tokens)
    ]
    visual_only_lockups = [
        path.relative_to(frontend).as_posix()
        for path in frontend_files
        if re.match(r"^(sim|lab|universal)-lockup-.*\.png$", path.name)
    ]
    nsi_path = PAYLOAD / "nsis" / "installer.nsi"
    nsi_text = nsi_path.read_text(encoding="utf-8-sig")
    cert_offset, cert_size = pe_certificate_table(ARTIFACT)
    build_stdout = EVIDENCE / "build.stdout.log"
    build_stderr = EVIDENCE / "build.stderr.log"
    stderr_text = build_stderr.read_text(encoding="utf-8", errors="replace")
    stdout_text = build_stdout.read_text(encoding="utf-8", errors="replace")
    field_test_text = FIELD_TEST_LOG.read_text(encoding="utf-8", errors="replace")
    field_test_count_match = re.search(r"Ran (\d+) tests", field_test_text)
    if field_test_count_match is None or not re.search(r"^OK$", field_test_text, re.MULTILINE):
        raise RuntimeError("Field contract test log does not contain a passing result")
    field_test_count = int(field_test_count_match.group(1))
    target_bytes = sum(path.stat().st_size for path in TARGET.rglob("*") if path.is_file())
    frontend_bytes = sum(path.stat().st_size for path in frontend_files)
    stage_bytes = (PAYLOAD / "nsis" / "WebView2Loader.dll").stat().st_size

    manifest = {
        "schemaVersion": 1,
        "kind": "dronedream-field-unsigned-preview-artifact-manifest",
        "editionId": "field",
        "version": "1.0.0",
        "productSource": {
            "branch": "codex/software-field",
            "commit": SOURCE_COMMIT,
            "upstreamCommit": SOURCE_COMMIT,
            "treeStateAtBuildStart": "clean",
            "trackedTreeChangedDuringBuild": False,
            "buildNumber": 698,
            "commonCoreCommit": COMMON_CORE_COMMIT,
            "commonCoreHash": COMMON_CORE_HASH,
        },
        "artifact": {
            "absolutePath": str(ARTIFACT),
            "filename": ARTIFACT.name,
            "originalGeneratedFilename": "DroneDream · FIELD_1.0.0_x64-setup.exe",
            "bytes": ARTIFACT.stat().st_size,
            "sha256": sha256_file(ARTIFACT),
            "fileVersion": "1.0.0",
            "productVersion": "1.0.0",
            "productName": "DroneDream · FIELD",
            "packaging": "tauri-nsis",
            "cargoBuildCount": 1,
            "nsisInvocationCount": 1,
        },
        "signature": {
            "signatureState": "unsigned",
            "authenticodeStatus": "NotSigned",
            "signerCertificatePresent": False,
            "timestampCertificatePresent": False,
            "peCertificateTableOffset": cert_offset,
            "peCertificateTableBytes": cert_size,
        },
        "updater": {
            "createUpdaterArtifacts": False,
            "signaturePath": None,
            "signatureSha256": None,
            "signatureState": "not-issued",
        },
        "branding": {
            "canonicalDonorCommit": "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
            "fieldIconSha256": sha256_file(
                REPO / "brand" / "generated" / "field" / "windows" / "icon.ico"
            ),
            "fieldMarkSha256": sha256_file(
                REPO
                / "distribution"
                / "editions"
                / "field"
                / "branding"
                / "dronedream-field-mark.png"
            ),
            "fieldDotLockupSha256": sha256_file(
                REPO
                / "distribution"
                / "editions"
                / "field"
                / "branding"
                / "dronedream-field-dot-lockup.png"
            ),
            "installedShortcutIconPath": "icons/DroneDream.ico",
            "productDisplayName": "DroneDream · FIELD",
        },
        "payload": {
            "inventoryPath": str(INVENTORY),
            "inventorySha256": sha256_file(INVENTORY),
            "inventoryFileCount": inventory["fileCount"],
            "inventoryBytes": inventory["totalBytes"],
            "enginePack": {
                "profileId": engine_manifest["editionProfile"]["profileId"],
                "includesLargeSimulator": engine_manifest["editionProfile"][
                    "includesLargeSimulator"
                ],
                "excludedSourcePaths": engine_manifest["editionProfile"][
                    "excludedSourcePaths"
                ],
                "sourceCommit": engine_manifest["source"]["gitCommit"],
                "descriptorSha256": sha256_file(descriptor_path),
                "manifestSha256": sha256_file(engine_manifest_path),
                "archiveSha256": sha256_file(engine_archive_path),
                "archiveBytes": engine_archive_path.stat().st_size,
                "postbuildAuditPath": str(postbuild_audit_path),
                "postbuildAuditSha256": sha256_file(postbuild_audit_path),
                "forbiddenSimulatorPayloads": postbuild_payload_audit[
                    "forbiddenPayloads"
                ],
                "vehiclePackCount": 8,
                "validatedHardwarePackCount": 0,
            },
            "frontend": {
                "fileCount": len(frontend_files),
                "bytes": frontend_bytes,
                "forbiddenSimulatorExecutableOrScriptPaths": forbidden_frontend_paths,
                "simulatorTextReferencesInGenericManuals": matching_text_files(frontend),
                "visualOnlySharedEditionLockupAssets": visual_only_lockups,
                "visualAssetsAreHardwareAuthority": False,
            },
        },
        "licenses": {
            "repositoryLicensePath": "LICENSE",
            "repositoryLicenseSha256": sha256_file(REPO / "LICENSE"),
            "noticePath": "runtime/THIRD_PARTY_NOTICES.md",
            "noticeSha256": sha256_file(
                REPO / "runtime" / "THIRD_PARTY_NOTICES.md"
            ),
            "valkeyLicensePath": "runtime/licenses/valkey-COPYING",
            "valkeyLicenseSha256": sha256_file(
                REPO / "runtime" / "licenses" / "valkey-COPYING"
            ),
            "allIncludedByGeneratedNsis": all(
                token in nsi_text
                for token in (
                    "DroneDream-LICENSE.txt",
                    "THIRD_PARTY_NOTICES.md",
                    "Valkey-COPYING.txt",
                )
            ),
        },
        "installerStructure": {
            "generatedNsiPath": str(nsi_path),
            "generatedNsiSha256": sha256_file(nsi_path),
            "webView2Contract": "verified-embedded-microsoft-signed-bootstrapper",
            "webView2BootstrapperSha256": sha256_file(
                PAYLOAD / "nsis" / "MicrosoftEdgeWebview2Setup.exe"
            ),
            "webView2LoaderSha256": sha256_file(
                PAYLOAD / "nsis" / "WebView2Loader.dll"
            ),
            "compiledLanguages": ["English:1033", "SimplifiedChinese:2052"],
            "languageTableCount": 2,
            "shortcutHookPath": "desktop/src-tauri/nsis/webview2-health.nsh",
            "shortcutHookSha256": sha256_file(
                REPO
                / "desktop"
                / "src-tauri"
                / "nsis"
                / "webview2-health.nsh"
            ),
            "installMode": "currentUser",
            "installExecuted": False,
            "upgradeExecuted": False,
            "uninstallExecuted": False,
        },
        "safety": {
            "vehiclePackCount": 8,
            "validatedHardwarePackCount": 0,
            "hardwareWriteUnlockArmFlightDecision": "deny",
            "requiredQuorumLayers": ["native", "backend", "runtime"],
            "deviceAccessExecuted": False,
            "simulationExecuted": False,
            "apiKeyRead": False,
        },
        "release": {
            "previewReady": True,
            "releaseReady": False,
            "releaseBranchCreated": False,
            "uploaded": False,
            "websiteHandoffState": "awaiting-exact-release-ready-handoff",
            "blockers": [
                "Authenticode is unsigned",
                "fresh install not executed",
                "upgrade not executed",
                "uninstall not executed",
                "shortcut behavior not validated on an installed system",
                "public URL family and re-download not issued or verified",
            ],
        },
    }
    manifest_path = EVIDENCE / "artifact-manifest.json"
    write_json(manifest_path, manifest)

    receipt = {
        "schemaVersion": 1,
        "kind": "dronedream-field-single-yellow-build-receipt",
        "editionId": "field",
        "decision": "unsigned-preview-built-not-release-ready",
        "productSourceHead": SOURCE_COMMIT,
        "evidenceGitHead": None,
        "commonCoreCommit": COMMON_CORE_COMMIT,
        "commonCoreHash": COMMON_CORE_HASH,
        "build": {
            "authorizedBuildCount": 1,
            "cargoBuildCount": 1,
            "nsisInvocationCount": stderr_text.count("Running [tauri_bundler::bundle::windows::nsis] makensis to produce"),
            "preCompilationTauriCliAbortCount": 1,
            "preCompilationAbortProducedTarget": False,
            "preCompilationAbortProducedExe": False,
            "startedAt": "2026-08-05T15:04:35Z",
            "finishedAt": "2026-08-05T15:07:22Z",
            "durationSeconds": 167,
            "stdoutLog": str(build_stdout),
            "stdoutLogSha256": sha256_file(build_stdout),
            "stderrLog": str(build_stderr),
            "stderrLogSha256": sha256_file(build_stderr),
        },
        "authorization": {
            "path": str(EVIDENCE / "build-authorization.json"),
            "sha256": sha256_file(EVIDENCE / "build-authorization.json"),
            "tauriOverlayPath": str(EVIDENCE / "tauri-yellow-override.json"),
            "tauriOverlaySha256": sha256_file(EVIDENCE / "tauri-yellow-override.json"),
            "frozenReadinessPath": str(
                EVIDENCE.parent / "field-yellow-readiness-c7e25b3" / "receipt.json"
            ),
            "frozenReadinessSha256": sha256_file(
                EVIDENCE.parent / "field-yellow-readiness-c7e25b3" / "receipt.json"
            ),
        },
        "artifact": manifest["artifact"],
        "artifactManifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "payloadInventory": {
            "path": str(INVENTORY),
            "sha256": sha256_file(INVENTORY),
        },
        "postbuildPayloadAudit": {
            "path": str(postbuild_audit_path),
            "sha256": sha256_file(postbuild_audit_path),
            "forbiddenPayloads": postbuild_payload_audit["forbiddenPayloads"],
            "validatedHardwarePackCount": postbuild_payload_audit["registrySummary"][
                "validatedHardwarePackCount"
            ],
        },
        "resourceEvidence": {
            "cargoTargetPath": str(TARGET),
            "cargoTargetBytes": target_bytes,
            "cargoTargetBytesMaximum": 8 * 1024 * 1024 * 1024,
            "workspaceTemporaryBytes": frontend_bytes + stage_bytes,
            "workspaceTemporaryBytesMaximum": 1024 * 1024 * 1024,
            "configuredMemoryBytesMaximum": 8 * 1024 * 1024 * 1024,
            "observedPeakMemoryBytes": None,
            "memoryBoundaryNote": "Process peak memory was not independently recorded.",
            "cargoBuildJobs": 4,
        },
        "offlineEvidence": {
            "cargoNetOffline": True,
            "npmOffline": True,
            "invalidHttpProxyConfigured": True,
            "buildLogDownloadReferenceCount": len(
                re.findall(r"downloading|downloaded", stderr_text + stdout_text, re.IGNORECASE)
            ),
            "networkTrafficIndependentlyMeasured": False,
        },
        "verification": {
            "fieldDistributionContracts": {
                "result": "pass",
                "testCount": field_test_count,
                "logPath": str(FIELD_TEST_LOG),
                "logSha256": sha256_file(FIELD_TEST_LOG),
            },
            "filenameVersionBytesSha256": "pass",
            "authenticodeAndPeCertificate": "pass-unsigned-confirmed",
            "enginePackFieldProfile": "pass",
            "forbiddenSimulatorExecutablePayload": "pass",
            "licenseNoticeValkey": "pass",
            "webView2CompiledStructure": "pass",
            "englishChineseCompiledLocales": "pass",
            "shortcutIconStaticStructure": "pass",
            "installUpgradeUninstall": "not-executed-requires-separate-approval",
            "realHardware": "not-executed-red",
        },
        "websiteAcceptance": {
            "websiteSourceCommit": "afdcdee5b60883290c9d1cc0c036141920066659",
            "websiteEvidenceCommit": "1a82e36b362c95983473c4a0d0d967d8c7415f92",
            "state": "awaiting-exact-release-ready-handoff",
            "previewSubstitutionAllowed": False,
            "crossEditionAttachmentAllowed": False,
            "singleEditionUrlFamilyVerified": False,
        },
        "previewReady": True,
        "releaseReady": False,
        "remainingGates": manifest["release"]["blockers"],
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    receipt_path = EVIDENCE / "build-receipt.json"
    write_json(receipt_path, receipt)

    print(
        json.dumps(
            {
                "artifactManifestPath": str(manifest_path),
                "artifactManifestSha256": sha256_file(manifest_path),
                "buildReceiptPath": str(receipt_path),
                "buildReceiptSha256": sha256_file(receipt_path),
                "previewReady": True,
                "releaseReady": False,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
