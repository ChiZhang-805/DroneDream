import hashlib
import json
import subprocess
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop/"
    "yellow-build-attempt-9-e17dd04-application.v1.json"
)
PRODUCT_SOURCE = "e17dd040189836abbeefbd6c175010331f1dc030"


def _load() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def _source_bytes(path: str) -> bytes:
    return subprocess.run(
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
    ).stdout


def test_attempt9_binds_new_exact_source_and_consumed_attempt8() -> None:
    application = _load()
    source = application["sourceSeparation"]
    predecessor = application["predecessorAttempt"]

    assert source["productSourceCommit"] == PRODUCT_SOURCE
    assert source["productSourceTree"] == "42d2f14365dca22018fffeb21b5f9caa24f699d0"
    assert source["requiredCheckoutMode"] == "detached-exact"
    assert source["expectedSourceCommitArgument"] == PRODUCT_SOURCE
    assert source["applicationEvidenceIsProductSource"] is False
    assert predecessor["globalBuildAttemptOrdinal"] == 8
    assert predecessor["sameAttemptMayBeReused"] is False
    assert predecessor["artifactCreated"] is False


def test_attempt9_build_inputs_match_exact_source_bytes() -> None:
    for file_ref in _load()["buildInputs"].values():
        source = _source_bytes(file_ref["path"])
        assert len(source) == file_ref["bytes"]
        assert hashlib.sha256(source).hexdigest() == file_ref["sha256"]


def test_attempt9_command_requires_exact_source_and_new_owned_root() -> None:
    application = _load()
    invocation = application["exactInvocation"]
    surface = application["ownedBuildSurface"]
    root = PureWindowsPath(surface["outputRoot"])

    assert root.parent == PureWindowsPath(surface["ownedBase"])
    assert root.name == "lab-final-e17dd04-attempt9"
    assert PureWindowsPath(surface["fixedArtifactPath"]).parent == root
    assert "-ExpectedSourceCommit" in invocation["arguments"]
    expected_index = invocation["arguments"].index("-ExpectedSourceCommit") + 1
    assert invocation["arguments"][expected_index] == PRODUCT_SOURCE
    assert invocation["requiredProcessEnvironment"]["CARGO_BUILD_JOBS"] == "2"
    assert surface["outputRootObservedAbsentAtFreeze"] is True
    assert surface["outputRootCreated"] is False


def test_attempt9_keeps_authority_and_execution_fail_closed() -> None:
    application = _load()

    assert application["buildIdentity"]["validatedVehiclePackCount"] == 0
    assert application["buildIdentity"]["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert application["safetyAuthority"]["requiredDecisionLayers"] == [
        "native",
        "backend",
        "runtime",
    ]
    assert application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"] is False
    assert application["authorization"]["newExactChiefControlStartSignalRequired"] is True
    assert application["attemptAccounting"]["globalBuildAttemptOrdinal"] == 9
    assert application["attemptAccounting"]["maximumBuildInvocations"] == 1
    assert application["attemptAccounting"]["automaticRetryAllowed"] is False
    assert all(value == 0 for value in application["executedCounts"].values())
    assert application["nonClaims"]["artifactCreated"] is False
