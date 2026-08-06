import hashlib
import json
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop/"
    "yellow-build-attempt-7-e3b427e-application.v1.json"
)


def _load() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


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
