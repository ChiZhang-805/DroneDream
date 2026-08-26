from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import Settings, get_settings
from app.db import get_db

_DEFAULT_USER_EMAIL = "default@drone-dream.local"
_DEFAULT_USER_NAME = "Default User"
_LOCAL_IDENTITY_PROVIDER = "urn:dronedream:local"


class OIDCConfigurationError(RuntimeError):
    """Raised when oidc_jwt mode cannot initialize its verifier."""


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    # Bound work performed by JWT parsing/key selection and avoid retaining an
    # arbitrarily large attacker-controlled header in exception chains.
    if not token or len(token) > 16_384:
        return None
    return token


def _get_or_create_user(db: Session, *, email: str, display_name: str | None = None) -> models.User:
    existing = db.scalars(
        select(models.User)
        .where(
            models.User.identity_provider == _LOCAL_IDENTITY_PROVIDER,
            models.User.external_subject == email,
        )
        .limit(1)
    ).first()
    if existing is None:
        # Compatibility for databases created before local identities had an
        # explicit provider. Never adopt an OIDC identity merely because its
        # optional email claim happens to match a demo-token email.
        existing = db.scalars(
            select(models.User)
            .where(
                models.User.email == email,
                models.User.identity_provider.is_(None),
                models.User.external_subject.is_(None),
            )
            .limit(1)
        ).first()
    if existing is not None:
        return existing

    user = models.User(
        email=email,
        display_name=display_name or email,
        identity_provider=_LOCAL_IDENTITY_PROVIDER,
        external_subject=email,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent API replicas can provision the same demo/local identity
        # at the same time. Resolve the unique-constraint winner instead of
        # binding subsequent requests to different duplicate user rows.
        db.rollback()
        winner = db.scalars(
            select(models.User)
            .where(
                models.User.identity_provider == _LOCAL_IDENTITY_PROVIDER,
                models.User.external_subject == email,
            )
            .limit(1)
        ).first()
        if winner is None:
            raise
        return winner
    db.refresh(user)
    return user


def _get_or_create_oidc_user(
    db: Session,
    *,
    issuer: str,
    subject: str,
    email: str | None,
    display_name: str | None,
) -> models.User:
    existing = db.scalars(
        select(models.User)
        .where(
            models.User.identity_provider == issuer,
            models.User.external_subject == subject,
        )
        .limit(1)
    ).first()
    if existing is not None:
        changed = False
        if email and existing.email != email:
            existing.email = email
            changed = True
        if display_name and existing.display_name != display_name:
            existing.display_name = display_name
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)
        return existing

    user = models.User(
        email=email,
        display_name=display_name or email or subject,
        identity_provider=issuer,
        external_subject=subject,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # A second API replica may provision the same subject concurrently.
        db.rollback()
        winner = db.scalars(
            select(models.User)
            .where(
                models.User.identity_provider == issuer,
                models.User.external_subject == subject,
            )
            .limit(1)
        ).first()
        if winner is None:
            raise
        return winner
    db.refresh(user)
    return user


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str, timeout_seconds: int, maximum_bytes: int) -> Any:
    parsed_url = urlsplit(jwks_url)
    try:
        _ = parsed_url.port
    except ValueError as exc:
        raise OIDCConfigurationError("OIDC JWKS URL contains an invalid port") from exc
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
        or parsed_url.fragment
    ):
        raise OIDCConfigurationError("OIDC JWKS URL must be an absolute HTTP(S) URL")
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise OIDCConfigurationError(
            "PyJWT is not installed; install the backend authentication dependencies"
        ) from exc

    class _BoundedPyJWKClient(jwt.PyJWKClient):
        def fetch_data(self) -> Any:
            jwk_set: Any = None
            try:
                request = url_request.Request(  # noqa: S310 - validated HTTP(S) URL above.
                    url=self.uri,
                    headers=self.headers,
                )
                with url_request.urlopen(  # noqa: S310 - validated HTTP(S) URL above.
                    request,
                    timeout=self.timeout,
                    context=self.ssl_context,
                ) as response:
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None:
                        try:
                            parsed_length = int(declared_length)
                        except ValueError as exc:
                            raise jwt.exceptions.PyJWKClientConnectionError(
                                "JWKS endpoint returned an invalid Content-Length"
                            ) from exc
                        if parsed_length < 0 or parsed_length > maximum_bytes:
                            raise jwt.exceptions.PyJWKClientConnectionError(
                                "JWKS endpoint response exceeds the configured size limit"
                            )
                    raw = response.read(maximum_bytes + 1)
                    if len(raw) > maximum_bytes:
                        raise jwt.exceptions.PyJWKClientConnectionError(
                            "JWKS endpoint response exceeds the configured size limit"
                        )
                    jwk_set = json.loads(raw)
            except jwt.exceptions.PyJWKClientConnectionError:
                raise
            except (url_error.URLError, TimeoutError) as exc:
                raise jwt.exceptions.PyJWKClientConnectionError(
                    f'Failed to fetch JWKS data: "{exc}"'
                ) from exc
            else:
                return jwk_set
            finally:
                if self.jwk_set_cache is not None:
                    self.jwk_set_cache.put(jwk_set)

    return _BoundedPyJWKClient(
        jwks_url,
        cache_keys=True,
        timeout=timeout_seconds,
    )


def _decode_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise OIDCConfigurationError(
            "PyJWT is not installed; install the backend authentication dependencies"
        ) from exc
    if not settings.oidc_jwks_url or not settings.oidc_issuer:
        raise OIDCConfigurationError("OIDC verifier settings are incomplete")
    signing_key = _jwks_client(
        settings.oidc_jwks_url,
        settings.oidc_jwks_timeout_seconds,
        settings.oidc_jwks_max_bytes,
    ).get_signing_key_from_jwt(token)
    audience: str | list[str]
    if len(settings.oidc_audience_list) == 1:
        audience = settings.oidc_audience_list[0]
    else:
        audience = settings.oidc_audience_list
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=settings.oidc_algorithm_list,
        audience=audience,
        issuer=settings.oidc_issuer,
        leeway=settings.oidc_clock_skew_seconds,
        options={"require": ["exp", "iss", "sub", "aud"]},
    )
    if not isinstance(claims, dict):  # pragma: no cover - PyJWT contract guard
        raise ValueError("OIDC token payload must be an object")
    return claims


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> models.User:
    settings = get_settings()
    if settings.auth_mode == "disabled":
        return _get_or_create_user(db, email=_DEFAULT_USER_EMAIL, display_name=_DEFAULT_USER_NAME)

    if settings.auth_mode not in {"demo_token", "oidc_jwt"}:
        raise HTTPException(
            status_code=500,
            detail={"code": "CONFIGURATION_ERROR", "message": "Unsupported AUTH_MODE."},
        )

    token = _extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        raise _unauthorized("Missing bearer token.")

    if settings.auth_mode == "oidc_jwt":
        try:
            claims = _decode_oidc_token(token, settings)
        except OIDCConfigurationError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "CONFIGURATION_ERROR", "message": str(exc)},
            ) from exc
        except Exception as exc:
            raise _unauthorized("Invalid or expired bearer token.") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise _unauthorized("Bearer token has no valid subject.")
        issuer = settings.oidc_issuer or ""
        if len(issuer) > 255:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "CONFIGURATION_ERROR",
                    "message": "OIDC_ISSUER exceeds the supported 255 characters.",
                },
            )
        email_claim = claims.get(settings.oidc_email_claim)
        name_claim = claims.get(settings.oidc_name_claim)
        email = (
            email_claim.strip()[:255]
            if isinstance(email_claim, str) and email_claim.strip()
            else None
        )
        display_name = (
            name_claim.strip()[:255] if isinstance(name_claim, str) and name_claim.strip() else None
        )
        return _get_or_create_oidc_user(
            db,
            issuer=issuer,
            subject=subject.strip(),
            email=email,
            display_name=display_name,
        )

    email = settings.demo_auth_token_map.get(token)
    if email is None:
        raise _unauthorized("Invalid bearer token.")

    return _get_or_create_user(db, email=email, display_name=email)
