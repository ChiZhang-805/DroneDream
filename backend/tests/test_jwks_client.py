from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import jwt
import pytest

from app import auth


class _FakeResponse:
    def __init__(self, body: bytes, *, content_length: str | None = None) -> None:
        self.body = body
        self.headers = {} if content_length is None else {"Content-Length": content_length}
        self.read_sizes: list[int] = []

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.body[:size]


@pytest.fixture(autouse=True)
def _clear_jwks_client_cache() -> Iterator[None]:
    auth._jwks_client.cache_clear()
    yield
    auth._jwks_client.cache_clear()


def test_jwks_client_uses_configured_timeout_and_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"keys": []}).encode("utf-8")
    response = _FakeResponse(body, content_length=str(len(body)))
    observed: dict[str, Any] = {}

    def fake_urlopen(
        request: Any,
        *,
        timeout: int,
        context: Any,
    ) -> _FakeResponse:
        observed.update(url=request.full_url, timeout=timeout, context=context)
        return response

    monkeypatch.setattr("app.auth.url_request.urlopen", fake_urlopen)

    client = auth._jwks_client("https://identity.example.test/jwks.json", 2, 64)

    assert client.fetch_data() == {"keys": []}
    assert observed == {
        "url": "https://identity.example.test/jwks.json",
        "timeout": 2,
        "context": None,
    }
    assert response.read_sizes == [65]


@pytest.mark.parametrize("declared_length", ["65", "-1", "not-a-number"])
def test_jwks_client_rejects_invalid_declared_response_size(
    monkeypatch: pytest.MonkeyPatch,
    declared_length: str,
) -> None:
    response = _FakeResponse(b'{"keys":[]}', content_length=declared_length)
    monkeypatch.setattr(
        "app.auth.url_request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    client = auth._jwks_client("https://identity.example.test/jwks.json", 5, 64)

    with pytest.raises(jwt.exceptions.PyJWKClientConnectionError):
        client.fetch_data()
    assert response.read_sizes == []


def test_jwks_client_rejects_chunked_response_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(b"x" * 65)
    monkeypatch.setattr(
        "app.auth.url_request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    client = auth._jwks_client("https://identity.example.test/jwks.json", 5, 64)

    with pytest.raises(
        jwt.exceptions.PyJWKClientConnectionError,
        match="exceeds the configured size limit",
    ):
        client.fetch_data()
    assert response.read_sizes == [65]


@pytest.mark.parametrize(
    "jwks_url",
    [
        "file:///tmp/jwks.json",
        "https://user:password@identity.example.test/jwks.json",
        "https://identity.example.test/jwks.json#fragment",
        "https://identity.example.test:invalid/jwks.json",
    ],
)
def test_jwks_client_rejects_unsafe_urls(jwks_url: str) -> None:
    with pytest.raises(auth.OIDCConfigurationError, match="OIDC JWKS URL"):
        auth._jwks_client(jwks_url, 5, 64)
