from __future__ import annotations

"""Verify the exact DroneDream · LAB EXE handoff consumed by Website."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT
    / "distribution"
    / "editions"
    / "lab"
    / "website-exact-exe-handoff.awaiting.v1.json"
)
SCHEMA_PATH = (
    ROOT
    / "distribution"
    / "schemas"
    / "lab-website-exact-exe-handoff.schema.json"
)

WEBSITE_SOURCE_COMMIT = "afdcdee5b60883290c9d1cc0c036141920066659"
WEBSITE_EVIDENCE_COMMIT = "1a82e36b362c95983473c4a0d0d967d8c7415f92"
COMMON_CORE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9"
COMMON_CORE_HASH = "b2a1d8479dd06616430e8eea9ec720f831ccaec5f5408032bc85eb3d9a0825e9"
FILE_NAME = "DroneDream-Lab-1.0.0.exe"
VERSION = "1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VALIDATION_STATES = {"not-run", "passed", "failed", "blocked", "not-applicable"}
FOREIGN_OR_PREVIEW_MARKERS = (
    "preview",
    "dronedream-sim",
    "dronedream-field",
    "dronedream-universal",
    "/sim/",
    "/field/",
    "/universal/",
)


class LabWebsiteHandoffError(ValueError):
    """Raised when a Website handoff can overstate Lab release readiness."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabWebsiteHandoffError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LabWebsiteHandoffError(f"{path} must contain a JSON object")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabWebsiteHandoffError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise LabWebsiteHandoffError(
            f"{label} fields drifted: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise LabWebsiteHandoffError(f"{label} must be a lowercase SHA-256")
    return value


def _require_absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise LabWebsiteHandoffError(f"{label} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() and not PureWindowsPath(value).is_absolute():
        raise LabWebsiteHandoffError(f"{label} must be an absolute path")
    return path


def _verify_file_ref(
    value: Any,
    label: str,
    *,
    verify_files: bool,
) -> tuple[Path, str]:
    reference = _exact_keys(value, {"absolutePath", "sha256"}, label)
    path = _require_absolute_path(reference["absolutePath"], f"{label}.absolutePath")
    digest = _require_sha256(reference["sha256"], f"{label}.sha256")
    if verify_files:
        if not path.is_file():
            raise LabWebsiteHandoffError(f"{label} file is missing")
        if _sha256_file(path) != digest:
            raise LabWebsiteHandoffError(f"{label} bytes do not match its SHA-256")
    return path, digest


def _validate_receiver(value: Any) -> None:
    receiver = _exact_keys(
        value,
        {
            "websiteSourceCommit",
            "websiteEvidenceCommit",
            "mode",
            "rebuildAllowed",
            "renameAllowed",
        },
        "receiver",
    )
    if (
        receiver["websiteSourceCommit"] != WEBSITE_SOURCE_COMMIT
        or receiver["websiteEvidenceCommit"] != WEBSITE_EVIDENCE_COMMIT
        or receiver["mode"] != "read-only-receiver"
        or receiver["rebuildAllowed"] is not False
        or receiver["renameAllowed"] is not False
    ):
        raise LabWebsiteHandoffError("Website receiver identity or read-only policy drifted")


def _validate_edition(value: Any) -> None:
    edition = _exact_keys(
        value, {"editionId", "displayName", "version", "fileName"}, "edition"
    )
    if edition != {
        "editionId": "lab",
        "displayName": "DroneDream · LAB",
        "version": VERSION,
        "fileName": FILE_NAME,
    }:
        raise LabWebsiteHandoffError("Lab edition identity or fixed filename drifted")


def _validate_product_source(value: Any, *, exact_artifact: bool) -> dict[str, Any]:
    source = _exact_keys(
        value,
        {"branch", "commit", "clean", "commonCoreCommit", "commonCoreHash"},
        "productSource",
    )
    if (
        source["branch"] != "codex/software-lab"
        or source["commonCoreCommit"] != COMMON_CORE_COMMIT
        or source["commonCoreHash"] != COMMON_CORE_HASH
    ):
        raise LabWebsiteHandoffError("Lab product source or common-core binding drifted")
    if exact_artifact:
        if not isinstance(source["commit"], str) or not COMMIT_RE.fullmatch(source["commit"]):
            raise LabWebsiteHandoffError("productSource.commit must be an exact full commit")
        if source["clean"] is not True:
            raise LabWebsiteHandoffError("productSource.clean must be true")
    elif source["commit"] is not None or source["clean"] is not None:
        raise LabWebsiteHandoffError("awaiting handoff cannot claim an exact product source")
    return source


def _validate_artifact(
    value: Any,
    *,
    exact_artifact: bool,
    verify_files: bool,
) -> tuple[dict[str, Any], Path | None]:
    artifact = _exact_keys(
        value,
        {
            "absolutePath",
            "fileName",
            "version",
            "bytes",
            "sha256",
            "authenticode",
            "updaterSignature",
        },
        "artifact",
    )
    if artifact["fileName"] != FILE_NAME or artifact["version"] != VERSION:
        raise LabWebsiteHandoffError("artifact filename or version drifted")
    authenticode = _exact_keys(
        artifact["authenticode"],
        {"signatureState", "subject", "timestamp"},
        "artifact.authenticode",
    )
    updater = _exact_keys(
        artifact["updaterSignature"],
        {"state", "absolutePath", "bytes", "sha256"},
        "artifact.updaterSignature",
    )
    if not exact_artifact:
        awaiting_values = (
            artifact["absolutePath"],
            artifact["bytes"],
            artifact["sha256"],
            authenticode["subject"],
            authenticode["timestamp"],
            updater["absolutePath"],
            updater["bytes"],
            updater["sha256"],
        )
        if any(item is not None for item in awaiting_values):
            raise LabWebsiteHandoffError("awaiting handoff cannot claim artifact bytes")
        if authenticode["signatureState"] != "awaiting" or updater["state"] != "awaiting":
            raise LabWebsiteHandoffError("awaiting handoff signature states drifted")
        return artifact, None

    path = _require_absolute_path(artifact["absolutePath"], "artifact.absolutePath")
    if path.name != FILE_NAME:
        raise LabWebsiteHandoffError("artifact absolute path was renamed or substituted")
    if not isinstance(artifact["bytes"], int) or isinstance(artifact["bytes"], bool) or artifact["bytes"] < 1:
        raise LabWebsiteHandoffError("artifact.bytes must be positive")
    _require_sha256(artifact["sha256"], "artifact.sha256")
    if authenticode["signatureState"] not in {"NotSigned", "Valid", "Invalid"}:
        raise LabWebsiteHandoffError("artifact Authenticode signatureState is unsupported")
    if authenticode["signatureState"] == "NotSigned" and (
        authenticode["subject"] is not None or authenticode["timestamp"] is not None
    ):
        raise LabWebsiteHandoffError("NotSigned artifact cannot claim signer metadata")
    if authenticode["signatureState"] == "Valid" and not authenticode["subject"]:
        raise LabWebsiteHandoffError("Valid Authenticode must name the signer subject")
    if verify_files:
        if not path.is_file():
            raise LabWebsiteHandoffError("artifact file is missing")
        if path.read_bytes()[:2] != b"MZ":
            raise LabWebsiteHandoffError("artifact is not a Windows PE file")
        if path.stat().st_size != artifact["bytes"] or _sha256_file(path) != artifact["sha256"]:
            raise LabWebsiteHandoffError("artifact bytes do not match the handoff")

    if updater["state"] == "not-issued":
        if any(updater[key] is not None for key in ("absolutePath", "bytes", "sha256")):
            raise LabWebsiteHandoffError("not-issued updater signature cannot claim a file")
    elif updater["state"] == "issued":
        signature_path = _require_absolute_path(
            updater["absolutePath"], "artifact.updaterSignature.absolutePath"
        )
        if signature_path.name != f"{FILE_NAME}.sig":
            raise LabWebsiteHandoffError("updater signature filename drifted")
        if not isinstance(updater["bytes"], int) or updater["bytes"] < 1:
            raise LabWebsiteHandoffError("updater signature bytes must be positive")
        _require_sha256(updater["sha256"], "artifact.updaterSignature.sha256")
        if verify_files:
            if not signature_path.is_file():
                raise LabWebsiteHandoffError("updater signature file is missing")
            if (
                signature_path.stat().st_size != updater["bytes"]
                or _sha256_file(signature_path) != updater["sha256"]
            ):
                raise LabWebsiteHandoffError("updater signature bytes drifted")
    else:
        raise LabWebsiteHandoffError("exact artifact updater signature state is unsupported")
    return artifact, path


def _validate_receipt_identity(
    path: Path,
    source: dict[str, Any],
    artifact: dict[str, Any],
) -> None:
    receipt = _load_json(path)
    receipt_artifact = receipt.get("artifact")
    if (
        receipt.get("kind") != "dronedream-lab-preview-artifact-receipt"
        or receipt.get("testOnly") is not False
        or receipt.get("sourceCommit") != source["commit"]
        or receipt.get("commonCoreCommit") != COMMON_CORE_COMMIT
        or receipt.get("commonCoreHash") != COMMON_CORE_HASH
        or not isinstance(receipt_artifact, dict)
        or receipt_artifact.get("fileName") != FILE_NAME
        or receipt_artifact.get("bytes") != artifact["bytes"]
        or receipt_artifact.get("sha256") != artifact["sha256"]
    ):
        raise LabWebsiteHandoffError("artifact receipt identity does not match the handoff")


def _validate_manifest_identity(
    path: Path,
    source: dict[str, Any],
    artifact: dict[str, Any],
) -> None:
    manifest = _load_json(path)
    manifest_artifact = manifest.get("artifact")
    if (
        manifest.get("kind") != "dronedream-lab-release-manifest"
        or manifest.get("editionId") != "lab"
        or manifest.get("productVersion") != VERSION
        or manifest.get("productSourceCommit") != source["commit"]
        or not isinstance(manifest_artifact, dict)
        or manifest_artifact.get("fileName") != FILE_NAME
        or manifest_artifact.get("bytes") != artifact["bytes"]
        or manifest_artifact.get("sha256") != artifact["sha256"]
    ):
        raise LabWebsiteHandoffError("release manifest identity does not match the handoff")


def _validate_build(value: Any, *, exact_artifact: bool) -> dict[str, Any]:
    build = _exact_keys(
        value, {"attemptCount", "successfulArtifactCount", "uniqueExe"}, "build"
    )
    if not exact_artifact:
        if any(build[key] is not None for key in build):
            raise LabWebsiteHandoffError("awaiting handoff cannot claim build counts")
        return build
    if (
        not isinstance(build["attemptCount"], int)
        or build["attemptCount"] < 1
        or build["successfulArtifactCount"] != 1
        or build["uniqueExe"] is not True
    ):
        raise LabWebsiteHandoffError("build count must bind one unique successful EXE")
    return build


def _validate_validation(value: Any, *, release_ready: bool) -> dict[str, Any]:
    validation = _exact_keys(
        value,
        {
            "freshInstall",
            "overlayInstall",
            "uninstall",
            "shortcuts",
            "webView2",
            "localization",
            "boundaryNotes",
        },
        "validation",
    )
    localization = _exact_keys(validation["localization"], {"en", "zhCN"}, "validation.localization")
    states = [
        validation["freshInstall"],
        validation["overlayInstall"],
        validation["uninstall"],
        validation["shortcuts"],
        validation["webView2"],
        localization["en"],
        localization["zhCN"],
    ]
    if any(state not in VALIDATION_STATES for state in states):
        raise LabWebsiteHandoffError("validation boundary state is unsupported")
    notes = validation["boundaryNotes"]
    if not isinstance(notes, list) or any(not isinstance(note, str) or not note for note in notes):
        raise LabWebsiteHandoffError("validation.boundaryNotes must be a string array")
    if release_ready and any(state != "passed" for state in states):
        raise LabWebsiteHandoffError("release-ready requires every install and locale boundary to pass")
    return validation


def _parse_https_url(value: Any, label: str) -> tuple[str, str, str]:
    if not isinstance(value, str):
        raise LabWebsiteHandoffError(f"{label} must be an HTTPS URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path or parsed.query or parsed.fragment:
        raise LabWebsiteHandoffError(f"{label} must be a stable HTTPS URL without query or fragment")
    return parsed.scheme, parsed.netloc.lower(), unquote(parsed.path)


def _validate_publication(value: Any, artifact: dict[str, Any], *, release_ready: bool) -> dict[str, Any]:
    publication = _exact_keys(
        value,
        {
            "urlFamily",
            "releaseTag",
            "downloadUrl",
            "checksumUrl",
            "receiptUrl",
            "manifestUrl",
            "signatureUrl",
        },
        "publication",
    )
    if not release_ready:
        return publication
    required = (
        "urlFamily",
        "releaseTag",
        "downloadUrl",
        "checksumUrl",
        "receiptUrl",
        "manifestUrl",
    )
    if any(not publication[key] for key in required):
        raise LabWebsiteHandoffError("release-ready publication URLs are incomplete")
    release_tag = publication["releaseTag"]
    if not isinstance(release_tag, str) or "lab" not in release_tag.lower():
        raise LabWebsiteHandoffError("Lab release tag must be edition-specific")
    values_to_scan = [release_tag, *(publication[key] for key in required if key != "releaseTag")]
    lowered = "\n".join(str(value).lower() for value in values_to_scan)
    if any(marker in lowered for marker in FOREIGN_OR_PREVIEW_MARKERS):
        raise LabWebsiteHandoffError("publication contains preview or cross-Edition substitution")

    family_scheme, family_host, family_path = _parse_https_url(publication["urlFamily"], "publication.urlFamily")
    if not family_path.endswith("/"):
        raise LabWebsiteHandoffError("publication.urlFamily must end with a slash")
    if family_path.rstrip("/").split("/")[-1] != release_tag:
        raise LabWebsiteHandoffError("publication release tag and URL family drifted")
    expected_names = {
        "downloadUrl": FILE_NAME,
        "checksumUrl": f"{FILE_NAME}.sha256",
        "receiptUrl": f"{FILE_NAME}.receipt.json",
        "manifestUrl": f"{FILE_NAME}.manifest.json",
    }
    for key, expected_name in expected_names.items():
        scheme, host, path = _parse_https_url(publication[key], f"publication.{key}")
        parent, _, name = path.rpartition("/")
        if (
            scheme != family_scheme
            or host != family_host
            or f"{parent}/" != family_path
            or name != expected_name
        ):
            raise LabWebsiteHandoffError("publication URLs are not one exact Lab URL family")
    signature_url = publication["signatureUrl"]
    if artifact["updaterSignature"]["state"] == "issued":
        scheme, host, path = _parse_https_url(signature_url, "publication.signatureUrl")
        parent, _, name = path.rpartition("/")
        if (
            scheme != family_scheme
            or host != family_host
            or f"{parent}/" != family_path
            or name != f"{FILE_NAME}.sig"
        ):
            raise LabWebsiteHandoffError("updater signature URL left the Lab URL family")
    elif signature_url is not None:
        raise LabWebsiteHandoffError("not-issued updater signature cannot claim a URL")
    return publication


def _validate_cross_edition(
    value: Any,
    artifact: dict[str, Any],
    publication: dict[str, Any],
    *,
    release_ready: bool,
) -> None:
    cross = _exact_keys(
        value,
        {
            "comparedEditions",
            "distinctArtifactSha256",
            "distinctDownloadUrl",
            "distinctReleaseTag",
        },
        "crossEditionValidation",
    )
    siblings = cross["comparedEditions"]
    if not isinstance(siblings, list) or len(siblings) != 3:
        raise LabWebsiteHandoffError("cross-Edition inventory must contain three siblings")
    expected_ids = ["universal", "sim", "field"]
    for sibling, expected_id in zip(siblings, expected_ids, strict=True):
        item = _exact_keys(
            sibling,
            {"editionId", "artifactSha256", "downloadUrl", "releaseTag"},
            f"crossEditionValidation.{expected_id}",
        )
        if item["editionId"] != expected_id:
            raise LabWebsiteHandoffError("cross-Edition inventory order or identity drifted")
    if not release_ready:
        return
    hashes = [artifact["sha256"]]
    urls = [publication["downloadUrl"]]
    tags = [publication["releaseTag"]]
    for sibling in siblings:
        hashes.append(_require_sha256(sibling["artifactSha256"], "sibling artifactSha256"))
        _parse_https_url(sibling["downloadUrl"], "sibling downloadUrl")
        if not isinstance(sibling["releaseTag"], str) or not sibling["releaseTag"]:
            raise LabWebsiteHandoffError("sibling releaseTag is missing")
        urls.append(sibling["downloadUrl"])
        tags.append(sibling["releaseTag"])
    actual_distinct = (
        len(set(hashes)) == 4,
        len(set(urls)) == 4,
        len(set(tags)) == 4,
    )
    claimed_distinct = (
        cross["distinctArtifactSha256"] is True,
        cross["distinctDownloadUrl"] is True,
        cross["distinctReleaseTag"] is True,
    )
    if not all(actual_distinct) or claimed_distinct != (True, True, True):
        raise LabWebsiteHandoffError("cross-Edition SHA, URL, or tag is duplicated")


def validate_handoff(
    handoff: Any,
    *,
    verify_files: bool = True,
    require_release_ready: bool = True,
) -> dict[str, Any]:
    document = _exact_keys(
        handoff,
        {
            "schemaVersion",
            "kind",
            "handoffVersion",
            "state",
            "receiver",
            "edition",
            "productSource",
            "artifact",
            "receipt",
            "manifest",
            "build",
            "validation",
            "publication",
            "crossEditionValidation",
            "releaseReady",
            "releaseConclusion",
            "blockers",
        },
        "Lab Website handoff",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-lab-website-exact-exe-handoff"
        or document["handoffVersion"] != VERSION
        or document["state"] not in {"awaiting-exact-handoff", "exact-artifact", "release-ready"}
    ):
        raise LabWebsiteHandoffError("Lab Website handoff identity is unsupported")
    _validate_receiver(document["receiver"])
    _validate_edition(document["edition"])
    exact_artifact = document["state"] != "awaiting-exact-handoff"
    release_ready = document["state"] == "release-ready"
    source = _validate_product_source(document["productSource"], exact_artifact=exact_artifact)
    artifact, _ = _validate_artifact(
        document["artifact"], exact_artifact=exact_artifact, verify_files=verify_files
    )
    _validate_build(document["build"], exact_artifact=exact_artifact)
    _validate_validation(document["validation"], release_ready=release_ready)

    if exact_artifact:
        receipt_path, _ = _verify_file_ref(document["receipt"], "receipt", verify_files=verify_files)
        manifest_path, _ = _verify_file_ref(document["manifest"], "manifest", verify_files=verify_files)
        if verify_files:
            _validate_receipt_identity(receipt_path, source, artifact)
            _validate_manifest_identity(manifest_path, source, artifact)
    else:
        for label in ("receipt", "manifest"):
            reference = _exact_keys(document[label], {"absolutePath", "sha256"}, label)
            if reference["absolutePath"] is not None or reference["sha256"] is not None:
                raise LabWebsiteHandoffError("awaiting handoff cannot claim receipt or manifest")

    publication = _validate_publication(document["publication"], artifact, release_ready=release_ready)
    _validate_cross_edition(
        document["crossEditionValidation"], artifact, publication, release_ready=release_ready
    )
    blockers = document["blockers"]
    if not isinstance(blockers, list) or any(not isinstance(item, str) or not item for item in blockers):
        raise LabWebsiteHandoffError("blockers must be a string array")
    if release_ready:
        if (
            document["releaseReady"] is not True
            or document["releaseConclusion"] != "release-ready"
            or blockers
            or artifact["authenticode"]["signatureState"] == "Invalid"
        ):
            raise LabWebsiteHandoffError("release-ready conclusion is not supported by evidence")
    elif (
        document["releaseReady"] is not False
        or document["releaseConclusion"] not in {"awaiting-exact-handoff", "exact-artifact-not-release-ready"}
        or not blockers
    ):
        raise LabWebsiteHandoffError("non-release handoff must remain explicitly blocked")
    if require_release_ready and not release_ready:
        raise LabWebsiteHandoffError("Website handoff is not release-ready")
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, nargs="?", default=CONTRACT_PATH)
    parser.add_argument("--allow-awaiting", action="store_true")
    parser.add_argument("--skip-files", action="store_true", help="contract tests only")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_handoff(
            _load_json(args.handoff.resolve()),
            verify_files=not args.skip_files,
            require_release_ready=not args.allow_awaiting,
        )
    except LabWebsiteHandoffError as exc:
        print(f"Lab Website handoff rejected: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "editionId": result["edition"]["editionId"],
                "fileName": result["edition"]["fileName"],
                "state": result["state"],
                "releaseReady": result["releaseReady"],
                "receiverSource": result["receiver"]["websiteSourceCommit"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
