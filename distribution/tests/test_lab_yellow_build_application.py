import hashlib
import json
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop/"
    "yellow-build-attempt-7-e3b427e-application.v1.json"
)
ATTEMPT_RECEIPT = (
    ROOT
    / "distribution/build-receipts/"
    "lab-preview-1.0.0-e3b427e-yellow-attempt7.exact-artifact.json"
)


def _load() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def _load_attempt_receipt() -> dict:
    return json.loads(ATTEMPT_RECEIPT.read_text(encoding="utf-8"))


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_application_binds_exact_product_source_and_single_attempt() -> None:
    application = _load()
    source = application["sourceSeparation"]
    attempt = application["attemptAccounting"]

    assert source["productSourceCommit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert source["productSourceTree"] == (
        "eec24c0f1d3d537c8f0da5ef1b015bd129c6d39a"
    )
    assert source["applicationEvidenceIsProductSource"] is False
    assert attempt["globalBuildAttemptOrdinal"] == 7
    assert attempt["sourceBuildAttemptOrdinal"] == 1
    assert attempt["maximumBuildInvocations"] == 1
    assert attempt["automaticRetryAllowed"] is False


def test_application_binds_current_lab_profile_payload_and_zero_pack_deny() -> None:
    application = _load()

    for file_ref in application["buildInputs"].values():
        assert _sha256(file_ref["path"]) == file_ref["sha256"]

    identity = application["buildIdentity"]
    assert identity["fileName"] == "DroneDream-Lab-1.0.0.exe"
    assert identity["displayName"] == "DroneDream · LAB"
    assert identity["compiledDesktopEditionId"] == "lab"
    assert identity["enginePackEditionProfile"] == "unified-sim-lab"
    assert identity["effectiveFrontendDist"] == "frontend/dist"
    assert identity["validatedVehiclePackCount"] == 0
    assert identity["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert application["uiAndBrandAcceptance"]["grantsHardwareAuthority"] is False
    assert application["safetyAuthority"]["requiredDecisionLayers"] == [
        "native",
        "backend",
        "runtime",
    ]


def test_application_uses_public_oauth_and_records_no_signing_secret() -> None:
    application = _load()
    oauth = application["publicOAuthRegistration"]
    signer = application["updaterSigningSource"]

    assert oauth["clientId"] == "0b9e7a8d-2c90-4b76-8842-511363f555bd"
    assert oauth["redirectUri"] == (
        "http://127.0.0.1:49212/desktop-auth/lab/callback"
    )
    assert oauth["clientType"] == "public"
    assert oauth["clientSecretRequired"] is False
    assert oauth["providerCallPerformed"] is False
    assert signer["privateKeyPath"] == (
        "C:/Users/zju20/.tauri/dronedream-updater.key"
    )
    assert signer["privateKeyContentRead"] is False
    assert signer["privateKeyCopied"] is False
    assert signer["expectedKeyId"] == "BA3FDCAF71CE2FF5"
    assert "privateKeySha256" not in signer


def test_application_output_root_and_command_are_exact_and_owned() -> None:
    application = _load()
    surface = application["ownedBuildSurface"]
    invocation = application["exactInvocation"]
    root = PureWindowsPath(surface["outputRoot"])
    owned_base = PureWindowsPath(surface["ownedBase"])
    artifact = PureWindowsPath(surface["fixedArtifactPath"])

    assert root.parent == owned_base
    assert root.name == "lab-final-e3b427e-attempt7"
    assert ".." not in root.parts
    assert artifact.parent == root
    assert artifact.name == "DroneDream-Lab-1.0.0.exe"
    assert surface["outputRootObservedAbsentAtFreeze"] is True
    assert surface["outputRootCreated"] is False
    assert invocation["executable"] == "powershell"
    assert invocation["arguments"] == [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "desktop/scripts/build-lab-preview.ps1",
        "-Build",
        "-Toolchain",
        "gnullvm",
        "-OutputRoot",
        surface["outputRoot"],
        "-CargoTargetDir",
        surface["cargoTargetDir"],
    ]
    assert invocation["requiredProcessEnvironment"]["CARGO_BUILD_JOBS"] == "2"


def test_application_authorizes_no_execution_and_preserves_history() -> None:
    application = _load()

    assert application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"] is False
    assert application["authorization"]["newExactChiefControlStartSignalRequired"] is True
    assert all(value == 0 for value in application["executedCounts"].values())
    assert application["nonClaims"]["buildStarted"] is False
    assert application["nonClaims"]["releaseReady"] is False
    assert application["historicalCandidatePreserved"]["sha256"] == (
        "b5969f2f287cf729450618e6d3a8232f426b1ac4cbe5c3662904d31bab215a48"
    )
    assert application["historicalCandidatePreserved"]["overwriteAllowed"] is False
    assert "historical-artifact-delete-overwrite-or-relabel" in application["forbiddenActions"]


def test_attempt_receipt_separates_product_source_from_build_evidence() -> None:
    receipt = _load_attempt_receipt()
    separation = receipt["sourceSeparation"]

    assert separation["productSource"]["commit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert separation["buildCheckout"]["commit"] == (
        "8885212d2702ae933c5e62fbb5a3c22d1bda8a2b"
    )
    assert separation["evidenceOnlyPathsAfterProductSource"] == [
        "distribution/editions/lab/desktop/"
        "yellow-build-attempt-7-e3b427e-application.v1.json",
        "distribution/tests/test_lab_yellow_build_application.py",
    ]
    assert separation["evidencePathsBundledAsProductPayload"] is False
    assert separation["applicationEvidenceIsProductSource"] is False


def test_attempt_receipt_freezes_unique_artifact_and_zero_retry() -> None:
    receipt = _load_attempt_receipt()

    assert receipt["attempt"]["buildInvocationCount"] == 1
    assert receipt["attempt"]["automaticRetryCount"] == 0
    assert receipt["artifact"]["fileName"] == "DroneDream-Lab-1.0.0.exe"
    assert receipt["artifact"]["uniqueAttemptArtifactCount"] == 1
    assert receipt["artifact"]["bytes"] == 12081900
    assert receipt["artifact"]["sha256"] == (
        "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
    )
    assert receipt["artifact"]["authenticodeStatus"] == "NotSigned"
    assert receipt["updaterSignature"]["state"] == "issued"
    assert receipt["updaterSignature"]["keyId"] == "BA3FDCAF71CE2FF5"
    assert receipt["updaterSignature"]["cryptographicArtifactVerification"] == {
        "state": "passed",
        "algorithm": "minisign-Ed25519-prehashed-blake2b",
        "publicKeySource": "desktop/src-tauri/tauri.conf.json",
        "publicKeyId": "BA3FDCAF71CE2FF5",
        "artifactSha256": (
            "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
        ),
        "privateKeyRead": False,
        "trustedCommentEnvelopeVerificationClaimed": False,
    }
    assert receipt["sideEffects"] == {
        "installerRun": False,
        "runtimeMigrationOrStart": False,
        "px4OrGazeboStarted": False,
        "oauthProviderCalled": False,
        "hardwareAccess": False,
        "releaseBranchCreated": False,
        "artifactUploaded": False,
        "deployed": False,
    }


def test_attempt_receipt_keeps_zero_pack_hardware_actions_denied() -> None:
    receipt = _load_attempt_receipt()

    assert receipt["safety"]["validatedVehiclePackCount"] == 0
    assert receipt["safety"]["workspaceOrThemeSwitchCountsAsAuthority"] is False
    assert receipt["safety"]["hardwareActionDecision"] == "deny"
    assert receipt["safety"]["requiredDecisionLayers"] == [
        "native",
        "backend",
        "runtime",
    ]
    assert receipt["releaseReady"] is False
