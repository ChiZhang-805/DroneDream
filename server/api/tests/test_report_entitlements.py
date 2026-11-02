from __future__ import annotations

import json
from typing import Any, cast
from urllib.request import Request

import pytest

from app.config import Settings
from app.services import report_entitlements


class _SnapshotResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _SnapshotResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


@pytest.mark.parametrize("plan_id", ["free", "plus", "pro"])
def test_report_export_tier_comes_from_authenticated_gateway_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    plan_id: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> _SnapshotResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _SnapshotResponse({"data": {"plan": {"id": plan_id}}})

    monkeypatch.setattr(report_entitlements, "urlopen", fake_urlopen)
    tier = report_entitlements.resolve_report_export_tier(
        authorization_header="Bearer signed-user-jwt",
        settings=Settings(
            model_gateway_base_url=("https://example.supabase.co/functions/v1/model-gateway"),
            llm_request_timeout_seconds=30,
        ),
    )

    assert tier == plan_id
    assert captured == {
        "url": "https://example.supabase.co/functions/v1/model-gateway/usage",
        "authorization": "Bearer signed-user-jwt",
        "timeout": 5.0,
    }


@pytest.mark.parametrize(
    "authorization,payload",
    [
        (None, {"data": {"plan": {"id": "pro"}}}),
        ("Pro", {"data": {"plan": {"id": "pro"}}}),
        ("Bearer signed-user-jwt", {"data": {"plan": {"id": "enterprise"}}}),
        ("Bearer signed-user-jwt", {"plan": {"id": "pro"}}),
    ],
)
def test_report_export_tier_fails_closed_to_free(
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
    payload: object,
) -> None:
    monkeypatch.setattr(
        report_entitlements,
        "urlopen",
        lambda *args, **kwargs: _SnapshotResponse(payload),
    )

    assert (
        report_entitlements.resolve_report_export_tier(
            authorization_header=authorization,
            settings=Settings(
                model_gateway_base_url=("https://example.supabase.co/functions/v1/model-gateway")
            ),
        )
        == "free"
    )


def test_report_export_tier_fails_closed_when_gateway_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise TimeoutError("gateway unavailable")

    monkeypatch.setattr(report_entitlements, "urlopen", unavailable)

    assert (
        report_entitlements.resolve_report_export_tier(
            authorization_header="Bearer signed-user-jwt",
            settings=Settings(
                model_gateway_base_url=("https://example.supabase.co/functions/v1/model-gateway")
            ),
        )
        == "free"
    )


def test_entitlement_transport_refuses_redirects() -> None:
    handler = report_entitlements._NoRedirectHandler()
    redirected = cast(Any, handler).redirect_request(
        Request("https://identity.example.test/usage"),
        None,
        302,
        "Found",
        {},
        "https://attacker.example.test/capture",
    )

    assert redirected is None


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.invalid/functions/v1/model-gateway",
        "file:///tmp/model-gateway",
        "https://user:password@example.invalid/functions/v1/model-gateway",
        "https://example.invalid/functions/v1/model-gateway?redirect=file:///tmp",
        "https:///functions/v1/model-gateway",
    ],
)
def test_report_export_tier_rejects_non_https_or_ambiguous_gateway_urls(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    def unexpected_urlopen(*args: object, **kwargs: object) -> object:
        raise AssertionError("invalid gateway URL must not reach urlopen")

    monkeypatch.setattr(report_entitlements, "urlopen", unexpected_urlopen)

    with pytest.raises(
        ValueError,
        match="MODEL_GATEWAY_BASE_URL must be a credential-free absolute HTTPS URL",
    ):
        Settings(model_gateway_base_url=base_url)

    bypassed_settings = Settings.model_construct(
        model_gateway_base_url=base_url,
        llm_request_timeout_seconds=30,
    )
    assert (
        report_entitlements.resolve_report_export_tier(
            authorization_header="Bearer signed-user-jwt",
            settings=bypassed_settings,
        )
        == "free"
    )
