"""Verify model planner bindings against the owner-scoped orchestration store."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import quote, urlsplit, urlunsplit

from app.autonomy.models import AutonomyCompileRequest
from app.config import Settings, get_settings


class PlannerArtifactVerificationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class VerifiedPlannerArtifactReceipt:
    owner_subject: str
    run_id: str
    provider: str
    model: str
    artifact_sha256: str


class _NoRedirect(url_request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: url_request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _orchestrator_url(settings: Settings) -> str:
    explicit = settings.assistant_orchestrator_url.strip().rstrip("/")
    if explicit:
        parsed = urlsplit(explicit)
    else:
        issuer_text = (settings.oidc_issuer or "").strip().rstrip("/")
        issuer_url = urlsplit(issuer_text)
        if (
            issuer_url.scheme != "https"
            or not issuer_url.hostname
            or issuer_url.username
            or issuer_url.password
            or issuer_url.query
            or issuer_url.fragment
            or issuer_url.path.rstrip("/") != "/auth/v1"
        ):
            raise PlannerArtifactVerificationError(
                "AUTONOMY_PLANNER_VERIFIER_NOT_CONFIGURED",
                "The trusted assistant orchestrator endpoint is not configured.",
                503,
            )
        parsed = issuer_url._replace(path="/functions/v1/assistant-orchestrator")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_VERIFIER_NOT_CONFIGURED",
            "The trusted assistant orchestrator endpoint is invalid.",
            503,
        )
    trusted_issuer = urlsplit((settings.oidc_issuer or "").strip().rstrip("/"))
    if trusted_issuer.hostname and (
        parsed.scheme != trusted_issuer.scheme or parsed.netloc != trusted_issuer.netloc
    ):
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_VERIFIER_ORIGIN_MISMATCH",
            "The assistant orchestrator does not share the trusted identity origin.",
            503,
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _read_bounded_response(response: Any, maximum_bytes: int) -> dict[str, Any]:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise PlannerArtifactVerificationError(
                "AUTONOMY_PLANNER_RECEIPT_INVALID",
                "The assistant run returned an invalid response length.",
                502,
            ) from exc
        if declared_bytes < 0 or declared_bytes > maximum_bytes:
            raise PlannerArtifactVerificationError(
                "AUTONOMY_PLANNER_RECEIPT_TOO_LARGE",
                "The assistant run response exceeded the verification limit.",
                502,
            )
    raw = response.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_RECEIPT_TOO_LARGE",
            "The assistant run response exceeded the verification limit.",
            502,
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_RECEIPT_INVALID",
            "The assistant run did not return a valid JSON receipt.",
            502,
        ) from exc
    if not isinstance(value, dict):
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_RECEIPT_INVALID",
            "The assistant run receipt is not an object.",
            502,
        )
    return value


def _fetch_run(
    run_id: str,
    authorization: str,
    settings: Settings,
) -> dict[str, Any]:
    url = f"{_orchestrator_url(settings)}/runs/{quote(run_id, safe='')}"
    request = url_request.Request(  # noqa: S310 - URL is pinned to trusted OIDC HTTPS.
        url,
        method="GET",
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
        },
    )
    opener = url_request.build_opener(_NoRedirect())
    try:
        with opener.open(  # noqa: S310 - URL is restricted to the trusted OIDC origin.
            request,
            timeout=settings.assistant_orchestrator_timeout_seconds,
        ) as response:
            return _read_bounded_response(
                response,
                settings.assistant_orchestrator_max_response_bytes,
            )
    except url_error.HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise PlannerArtifactVerificationError(
                "AUTONOMY_PLANNER_ARTIFACT_NOT_ISSUED",
                "No owner-scoped server-issued planner artifact matched this run.",
                403,
            ) from exc
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_VERIFIER_UNAVAILABLE",
            "The assistant planner receipt service is temporarily unavailable.",
            503,
        ) from exc
    except (url_error.URLError, TimeoutError, OSError) as exc:
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_VERIFIER_UNAVAILABLE",
            "The assistant planner receipt service is temporarily unavailable.",
            503,
        ) from exc


def validate_planner_artifact_response(
    request: AutonomyCompileRequest,
    expected_subject: str,
    envelope: dict[str, Any],
) -> None:
    planner = request.asset_context.planner_binding if request.asset_context else None
    run = envelope.get("data")
    result = run.get("result_json") if isinstance(run, dict) else None
    artifact = result.get("artifact_payload") if isinstance(result, dict) else None
    expected_artifact = {
        "schema_version": "dronedream.autonomy.planner-response.v1",
        "status": "draft",
        "goal": planner.goal if planner else None,
        "asset_bindings": {
            "aircraft_id": planner.aircraft_id if planner else None,
            "aircraft_version": planner.aircraft_version if planner else None,
            "map_id": planner.map_id if planner else None,
            "map_version": planner.map_version if planner else None,
            "context_sha256": planner.context_sha256 if planner else None,
        },
        "task_graph": planner.task_graph.model_dump(mode="json") if planner else None,
    }
    artifact_subset = (
        {
            "schema_version": artifact.get("schema_version"),
            "status": artifact.get("status"),
            "goal": artifact.get("goal"),
            "asset_bindings": artifact.get("asset_bindings"),
            "task_graph": artifact.get("task_graph"),
        }
        if isinstance(artifact, dict)
        else None
    )
    if (
        planner is None
        or not isinstance(run, dict)
        or not isinstance(result, dict)
        or run.get("run_id") != planner.run_id
        or run.get("owner_user_id") != expected_subject
        or run.get("edition") != request.edition
        or run.get("provider") != planner.provider
        or run.get("model") != planner.model
        or run.get("state") != "completed"
        or run.get("stage") != "completed"
        or result.get("run_id") != planner.run_id
        or result.get("artifact_kind") != "autonomy_mission_plan"
        or result.get("artifact_sha256") != planner.artifact_sha256
        or artifact_subset != expected_artifact
    ):
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_ARTIFACT_MISMATCH",
            "The planner binding does not match the owner-scoped server-issued artifact.",
            403,
        )


async def verify_planner_artifact_binding(
    request: AutonomyCompileRequest,
    authorization: str | None,
    expected_subject: str | None,
) -> VerifiedPlannerArtifactReceipt:
    authorization_parts = authorization.split(" ", 1) if authorization else []
    bearer_token = authorization_parts[1].strip() if len(authorization_parts) == 2 else ""
    if (
        authorization is None
        or len(authorization) > 16_384
        or any(ord(character) < 32 for character in authorization)
        or len(authorization_parts) != 2
        or authorization_parts[0].casefold() != "bearer"
        or not bearer_token
        or expected_subject is None
        or not expected_subject.strip()
    ):
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_IDENTITY_REQUIRED",
            "An authenticated owner identity is required to verify the planner artifact.",
            403,
        )
    planner = request.asset_context.planner_binding if request.asset_context else None
    if planner is None:
        raise PlannerArtifactVerificationError(
            "AUTONOMY_PLANNER_ARTIFACT_MISMATCH",
            "The simulation request has no model planner binding to verify.",
            403,
        )
    settings = get_settings()
    envelope = await asyncio.to_thread(
        _fetch_run,
        planner.run_id,
        f"Bearer {bearer_token}",
        settings,
    )
    validate_planner_artifact_response(request, expected_subject.strip(), envelope)
    return VerifiedPlannerArtifactReceipt(
        owner_subject=expected_subject.strip(),
        run_id=planner.run_id,
        provider=planner.provider,
        model=planner.model,
        artifact_sha256=planner.artifact_sha256,
    )


__all__ = [
    "PlannerArtifactVerificationError",
    "VerifiedPlannerArtifactReceipt",
    "validate_planner_artifact_response",
    "verify_planner_artifact_binding",
]
