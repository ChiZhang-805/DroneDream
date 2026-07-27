"""Trusted subscription resolution for downloadable experiment reports."""

from __future__ import annotations

import json
from typing import Literal
from urllib.request import Request, urlopen

from app.config import Settings, get_settings

ReportExportTier = Literal["free", "plus", "pro"]
_MAX_SNAPSHOT_BYTES = 65_536
_MAX_AUTHORIZATION_BYTES = 16_384


def _verified_plan_id(payload: object) -> ReportExportTier | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    plan = data.get("plan")
    if not isinstance(plan, dict):
        return None
    plan_id = plan.get("id")
    if plan_id == "free":
        return "free"
    if plan_id == "plus":
        return "plus"
    if plan_id == "pro":
        return "pro"
    return None


def resolve_report_export_tier(
    *,
    authorization_header: str | None,
    settings: Settings | None = None,
) -> ReportExportTier:
    """Resolve a report tier through the authenticated model-gateway snapshot.

    The caller cannot supply a tier. The Supabase Edge Function verifies the
    bearer token and reads the active entitlement through its service-role
    database connection. Any missing configuration, invalid response, timeout,
    or unavailable entitlement fails closed to the watermarked Free export.
    """

    current = settings or get_settings()
    base_url = current.model_gateway_base_url.strip().rstrip("/")
    authorization = (authorization_header or "").strip()
    if (
        not base_url
        or not authorization.startswith("Bearer ")
        or len(authorization.encode("utf-8")) > _MAX_AUTHORIZATION_BYTES
    ):
        return "free"

    request = Request(
        f"{base_url}/usage",
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": authorization,
            "User-Agent": "DroneDream-Report-Entitlement/1.0",
        },
    )
    try:
        with urlopen(
            request,
            timeout=min(current.llm_request_timeout_seconds, 5.0),
        ) as response:
            body = response.read(_MAX_SNAPSHOT_BYTES + 1)
            if len(body) > _MAX_SNAPSHOT_BYTES:
                return "free"
            payload = json.loads(body.decode("utf-8"))
    except Exception:
        return "free"

    return _verified_plan_id(payload) or "free"


__all__ = ["ReportExportTier", "resolve_report_export_tier"]
