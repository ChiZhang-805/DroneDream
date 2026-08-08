import hashlib
import json
import subprocess
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop/"
    "yellow-build-attempt-8-2d00662-application.v1.json"
)
PRODUCT_SOURCE = "2d0066227b99eb572d8ca24a666bece75bcb44a7"


def _load() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def _git_checkout_file_bytes(path: str) -> bytes:
    result = subprocess.run(
        [
            "git",
            "cat-file",
            "--filters",
            f"--path={path}",
            f"{PRODUCT_SOURCE}:{path}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def test_application_binds_exact_source_donors_and_single_attempt() -> None:
    application = _load()
    source = application["sourceSeparation"]
    donors = application["commonCoreAndDonors"]
    attempt = application["attemptAccounting"]

    assert source == {
        "productSourceCommit": PRODUCT_SOURCE,
        "productSourceTree": "f41543034055ce51214ec7cdff2aac9aa7d9180a",
        "branch": "codex/software-lab",
        "upstreamExactAtFreeze": True,
        "cleanAtFreeze": True,
        "applicationEvidenceIsProductSource": False,
        "sourceMustBeCheckedOutExactAndClean": True,
    }
    assert donors["simProductSource"] == (
        "ef70567fe4c34f261fc9f16defb6e98e95f337dc"
    )
    assert donors["fieldProductSource"] == (
        "2f8fa28564dab7b1ff264c853705535373cb9068"
    )
    assert donors["fieldAuthWireContractSource"] == (
        "1129b561a187edf9ddb3214f3e8c993be31f281b"
    )
    assert donors["sharedCoreForkCreated"] is False
    assert attempt["globalBuildAttemptOrdinal"] == 8
    assert attempt["sourceBuildAttemptOrdinal"] == 1
    assert attempt["maximumBuildInvocations"] == 1
    assert attempt["automaticRetryAllowed"] is False


def test_application_build_inputs_are_exact_product_source_bytes() -> None:
    application = _load()

    for file_ref in application["buildInputs"].values():
        source_bytes = _git_checkout_file_bytes(file_ref["path"])
        assert len(source_bytes) == file_ref["bytes"]
        assert hashlib.sha256(source_bytes).hexdigest() == file_ref["sha256"]


def test_application_binds_full_lab_identity_and_bidirectional_capability() -> None:
    application = _load()
    identity = application["buildIdentity"]
    capability = application["productCapability"]

    assert identity["fileName"] == "DroneDream-Lab-1.0.0.exe"
    assert identity["displayName"] == "DroneDream · LAB"
    assert identity["compiledDesktopEditionId"] == "lab"
    assert identity["enginePackEditionProfile"] == "unified-sim-lab"
    assert capability["simulationModelHarness"] == "integrated"
    assert capability["fieldRecordedEvidenceHarness"] == "integrated"
    assert capability["managedReadOnlyHardwareAdapters"] == "integrated"
    assert capability["metricNormalizationReceiptRequired"] is True
    assert capability["independentHoldoutRequired"] is True
    assert capability["simpleSimPlusFieldUnionClaimed"] is False


def test_application_keeps_hardware_and_credential_boundaries_closed() -> None:
    application = _load()
    authority = application["safetyAuthority"]
    oauth = application["publicOAuthRegistration"]
    signer = application["updaterSigningSource"]

    assert authority["validatedVehiclePackCount"] == 0
    assert authority["workspaceThemeModelOrReceiptCountsAsAuthority"] is False
    assert authority["requiredDecisionLayers"] == ["native", "backend", "runtime"]
    assert application["buildIdentity"]["hardwareWriteArmHitlFlightDecision"] == (
        "deny"
    )
    assert application["uiAndBrandAcceptance"]["grantsHardwareAuthority"] is False
    assert oauth["clientSecretRequired"] is False
    assert oauth["providerCallPerformed"] is False
    assert signer["privateKeyContentRead"] is False
    assert signer["privateKeyCopied"] is False
    assert "privateKeySha256" not in signer


def test_application_uses_new_owned_root_and_exact_command() -> None:
    application = _load()
    surface = application["ownedBuildSurface"]
    invocation = application["exactInvocation"]
    root = PureWindowsPath(surface["outputRoot"])
    owned_base = PureWindowsPath(surface["ownedBase"])
    artifact = PureWindowsPath(surface["fixedArtifactPath"])

    assert root.parent == owned_base
    assert root.name == "lab-final-2d00662-attempt8"
    assert ".." not in root.parts
    assert artifact.parent == root
    assert artifact.name == "DroneDream-Lab-1.0.0.exe"
    assert surface["outputRootObservedAbsentAtFreeze"] is True
    assert surface["outputRootCreated"] is False
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


def test_application_is_plan_only_and_preserves_previous_artifact() -> None:
    application = _load()

    assert application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"] is False
    assert application["authorization"]["newExactChiefControlStartSignalRequired"] is True
    assert all(value == 0 for value in application["executedCounts"].values())
    assert application["nonClaims"]["buildStarted"] is False
    assert application["nonClaims"]["releaseReady"] is False
    assert application["historicalArtifactPreservation"]["previousArtifactSha256"] == (
        "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
    )
    assert application["historicalArtifactPreservation"]["overwriteAllowed"] is False
    assert "build-before-exact-start-signal" in application["forbiddenActions"]
    assert "historical-artifact-delete-overwrite-or-relabel" in application["forbiddenActions"]
