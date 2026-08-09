from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/lab/desktop"
    / "yellow-build-attempt-12-7b9ac35-application.v1.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_application_binds_exact_source_attempt_and_output() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))

    assert application["productSource"] == {
        "branch": "codex/software-lab",
        "commit": "7b9ac353b157ab0a7d03da54c1156e23f81d7cdf",
        "tree": "082f9eeb16927b5853b449ece6f69c062c8273e6",
        "requiresHeadEqualsUpstream": True,
        "requiresCleanWorktree": True,
    }
    assert application["attempt"]["maximumBuildInvocations"] == 1
    assert application["attempt"]["automaticRetryMaximum"] == 0
    assert application["paths"]["outputRoot"].endswith(
        "/lab-final-7b9ac353-attempt12"
    )
    assert "-ExpectedSourceCommit 7b9ac353b157ab0a7d03da54c1156e23f81d7cdf" in (
        application["command"]
    )


def test_application_binds_canonical_lab_icon_and_centered_lockup() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    brand = application["brandContract"]

    for key in ("canonicalWindowsIcon", "canonicalMark", "centeredSeparatorLockup"):
        asset = brand[key]
        path = ROOT / asset["path"]
        assert path.stat().st_size == asset["bytes"]
        assert _sha(path) == asset["sha256"]
    assert brand["shortcutIconSource"] == "$INSTDIR/${MAINBINARYNAME}.exe"
    assert brand["sharedLegacyIconResourceMayBackShortcut"] is False
    assert brand["presentationOnly"] is True
    assert brand["grantsHardwareAuthority"] is False


def test_application_requires_disposable_user_and_hardware_deny() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    requirements = application["postBuildRequirements"]

    assert requirements["requiresDisposableWindowsUserWithoutCanonicalLabIdentity"] is True
    assert requirements["hardwareAuthorityDecision"] == "deny"
    assert "overwrite-current-zju20-lab-install" in application["forbidden"]
    assert "automatic-retry" in application["forbidden"]
