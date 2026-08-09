from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
APPLICATION = LIFECYCLE / "final-b3c5f909-app-only-application.v1.json"
PLAN = LIFECYCLE / "final-b3c5f909-app-only-plan.v1.json"
TARGET = LIFECYCLE / "final-b3c5f909-app-only-target-receipt.v1.json"
RUNNER = LIFECYCLE / "run-lab-final-app-only-lifecycle.ps1"
INSPECTOR = LIFECYCLE / "inspect-lab-e3b427e-live-webview2.mjs"
CLASSIFIER = LIFECYCLE / "lab-request-origin-diagnostics.mjs"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf_sha(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_lifecycle_contract_binds_new_exact_artifact_and_tools() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    target = _load(TARGET)

    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        "b3c5f90948f206472e3e12504d8205cb563ac9dc"
    )
    assert application["artifact"]["sha256"] == (
        "cf3ce9dd592995f90c9c0ed7dad014bfb74108a39d066194c8f315a012111811"
    )
    assert application["artifact"]["bytes"] == 12468471
    assert application["artifact"]["sha256"] == plan["artifact"]["sha256"]
    assert application["artifact"]["sha256"] == target["artifact"]["sha256"]
    assert application["plan"]["sha256"] == _sha(PLAN)
    assert application["targetReceipt"]["sha256"] == _sha(TARGET)
    assert application["executionTools"]["adapter"]["lfNormalizedSha256"] == (
        "7d704aa296f9165875fadff45b0e500c69b747035d34611fa94a46cbf3794756"
    )
    for key, path in (
        ("liveInspector", INSPECTOR),
        ("requestDiagnosticsClassifier", CLASSIFIER),
    ):
        assert application["executionTools"][key]["lfNormalizedSha256"] == _lf_sha(path)


def test_lifecycle_contract_is_owned_one_shot_and_fail_closed() -> None:
    application = _load(APPLICATION)
    counts = application["segments"]["a"]["exactCounts"]

    assert application["attempt"] == {
        "segmentAOrdinal": 1,
        "maximumExecutionInvocations": 1,
        "automaticRetryMaximum": 0,
        "priorAttemptResult": "none-new-product-source",
    }
    assert application["ownedIsolation"]["runId"] == (
        "lab-final-b3c5f909-segment-a-1"
    )
    assert counts == _load(PLAN)["exactCounts"]
    assert counts == _load(TARGET)["requiredExactCounts"]
    for name in (
        "browserLaunches",
        "oauthBoundaryChecks",
        "providerTokenExchanges",
        "accountReads",
        "artifactBuilds",
        "runtimeStartsOrMigrations",
        "px4Starts",
        "gazeboStarts",
        "hardwareActions",
        "uploadsOrDeployments",
    ):
        assert counts[name] == 0
    assert application["safety"]["validatedVehiclePackCount"] == 0
    assert application["safety"]["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert application["liveAssertions"]["themePalette"] == [
        "#A7E84A",
        "#20C77A",
        "#087E69",
    ]
    assert application["liveAssertions"]["themeSettingsAndThreeDGrantHardwareAuthority"] is False
