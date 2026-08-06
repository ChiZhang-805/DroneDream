from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/field/build/yellow-e92ae21-application.v1.json"
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_application_binds_exact_product_source_and_single_attempt() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    source = application["source"]
    artifact = application["artifact"]
    assert _git("rev-parse", f"{source['productCommit']}^{{tree}}") == source["productTree"]
    assert source["productCommit"] == "e92ae21bd68b00d0959ad70f3860b2f7d1addbbd"
    for key in (
        "frontendBuildInvocationMaximum",
        "tauriInvocationMaximum",
        "cargoBuildCountMaximum",
        "nsisInvocationMaximum",
        "freshBuildAttemptMaximum",
    ):
        assert artifact[key] == 1
    assert application["greenVerification"]["tauriCargoNsisInvoked"] is False


def test_application_paths_are_new_owned_namespaces() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    paths = application["ownedPaths"]
    assert paths["sourceRoot"].endswith("ddfe92")
    assert paths["cargoTarget"].endswith("field-cargo-target\\e92ae21")
    assert "field-yellow-build-e92ae21-ui-theme-frontenddist" in paths["runRoot"]
    assert paths["sourceRootExistsAtPreparation"] is False
    assert paths["cargoTargetExistsAtPreparation"] is False
    assert paths["runRootExistsAtPreparation"] is False
    assert paths["reuseHistoricalSourceTargetOrOutputAllowed"] is False


def test_public_configuration_and_hardware_boundaries_are_fail_closed() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    public = application["publicConfiguration"]
    safety = application["safety"]
    assert public["oauthClientId"] == "3140bbe2-5f0e-4699-8a9b-295d4030f853"
    assert public["oauthCallback"] == (
        "http://127.0.0.1:49213/desktop-auth/field/callback"
    )
    assert public["oauthClientSecretPresent"] is False
    assert public["updaterPrivateKeyReadDuringGreen"] is False
    assert public["updaterMatchingPublicKeyId"] == "BA3FDCAF71CE2FF5"
    assert safety["validatedHardwarePackCount"] == 0
    assert safety["hardwareDecision"] == "deny"
    assert safety["frontendIsAuthority"] is False
    assert safety["installationAllowed"] is False
    assert safety["deviceOrHardwareAllowed"] is False


def test_application_integrity_and_no_historical_relabel() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    assert _canonical_sha(application) == application["integrity"]["canonicalSha256"]
    assert all("no-relabel" in item["state"] for item in application["historicalArtifacts"])
    assert application["failurePolicy"]["afterTauriInvocationRetryAllowed"] is False
    assert application["exactCommands"]["commandFilesCreatedOnlyAfterStartSignal"] is True
