"""Durable accounting for every actual provider network request.

Logical cognitive turns and billable HTTP requests are not interchangeable.
This module commits one safe receipt immediately before each network send,
then appends a terminal outcome without persisting credentials, provider
request identifiers, raw prompts, raw chat, or raw responses.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas

PROVIDER_REQUEST_ATTEMPT_SCHEMA = (
    "dronedream.provider-network-request-attempt/v1"
)
PROVIDER_REQUEST_OUTCOME_SCHEMA = (
    "dronedream.provider-network-request-outcome/v1"
)
PROVIDER_RETRY_POLICY_VERSION = "explicit-network-attempts-v1"
MAX_PROVIDER_NETWORK_REQUESTS_PER_TURN = 8
MAX_PROVIDER_NETWORK_REQUESTS_PER_JOB = 256

RequestKind = Literal["primary", "retry", "compatibility_fallback"]
RequestOutcomeStatus = Literal["succeeded", "failed", "indeterminate"]

_HEX = frozenset("0123456789abcdef")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SENSITIVE_PRICE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "password",
        "provider_request_id",
        "request_id",
        "secret",
    }
)
_REQUEST_KINDS = frozenset({"primary", "retry", "compatibility_fallback"})


class ProviderRequestBlocked(RuntimeError):
    """Actual provider I/O was rejected before a network send."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderRequestPending(ProviderRequestBlocked):
    def __init__(self) -> None:
        super().__init__(
            "provider_request_outcome_pending",
            "An attempted provider request has no terminal outcome and cannot be replayed.",
        )


@dataclass(frozen=True)
class ProviderRequestAttempt:
    receipt_id: str
    cognitive_turn_receipt_id: str
    request_index: int


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class BoundProviderRequestAccountant:
    """Bind safe request accounting to one Job cognitive turn."""

    def __init__(
        self,
        db: Session,
        job: models.Job,
        *,
        cognitive_turn_receipt_id: str,
        provider: str,
        region: str | None = None,
    ) -> None:
        self._db = db
        self._job = job
        self._cognitive_turn_receipt_id = cognitive_turn_receipt_id
        self._provider = provider
        self._region = region

    def begin(
        self,
        *,
        request_kind: RequestKind,
        model_snapshot: str,
        api_surface: str,
        base_url: str,
        temperature: float | None,
        top_p: float | None,
        provider_seed: int | None,
        response_schema_sha256: str,
        prompt_sha256: str,
        request_body: Mapping[str, Any],
        price_snapshot: schemas.ProviderPriceSnapshot,
    ) -> ProviderRequestAttempt:
        turn = _turn_receipt(
            self._db,
            self._job,
            self._cognitive_turn_receipt_id,
        )
        existing_count = self._db.scalar(
            select(func.count(models.ProviderNetworkRequestReceipt.id)).where(
                models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
                == turn.id
            )
        )
        return begin_provider_network_request(
            self._db,
            self._job,
            cognitive_turn_receipt_id=turn.id,
            request_index=int(existing_count or 0) + 1,
            request_kind=request_kind,
            provider=self._provider,
            model_snapshot=model_snapshot,
            api_surface=api_surface,
            base_url=base_url,
            region=self._region,
            temperature=temperature,
            top_p=top_p,
            provider_seed=provider_seed,
            response_schema_sha256=response_schema_sha256,
            prompt_sha256=prompt_sha256,
            tool_outputs_sha256=turn.tool_outputs_sha256,
            request_body=request_body,
            price_snapshot=price_snapshot,
        )

    def succeed(
        self,
        attempt: ProviderRequestAttempt,
        *,
        response_content: str | bytes,
        usage: ProviderUsage,
        latency_ms: int,
    ) -> None:
        finish_provider_network_request(
            self._db,
            self._job,
            attempt,
            status="succeeded",
            response_content=response_content,
            usage=usage,
            latency_ms=latency_ms,
        )

    def fail(
        self,
        attempt: ProviderRequestAttempt,
        *,
        latency_ms: int,
        error_code: str,
    ) -> None:
        finish_provider_network_request(
            self._db,
            self._job,
            attempt,
            status="failed",
            latency_ms=latency_ms,
            error_code=error_code,
        )


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_sha256(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in _HEX for char in normalized):
        raise ProviderRequestBlocked(
            "provider_request_hash_invalid",
            f"{field} is not a SHA-256 digest.",
        )
    return normalized


def _normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ProviderRequestBlocked(
            "provider_base_url_invalid",
            "Provider base URL must be an absolute HTTP(S) URL.",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderRequestBlocked(
            "provider_base_url_unsafe",
            "Provider base URL cannot contain credentials, query, or fragment.",
        )
    host = parsed.hostname.lower()
    if parsed.scheme != "https" and host not in _LOOPBACK_HOSTS:
        raise ProviderRequestBlocked(
            "provider_base_url_insecure",
            "Provider credentials may only be sent to HTTPS or loopback.",
        )
    rendered_host = f"[{host}]" if ":" in host else host
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProviderRequestBlocked(
            "provider_base_url_invalid",
            "Provider base URL has an invalid port.",
        ) from exc
    netloc = rendered_host if port is None else f"{rendered_host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _validate_safe_tree(value: object, *, path: str = "price_snapshot") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ProviderRequestBlocked(
            "provider_price_snapshot_invalid",
            f"{path} contains a non-finite number.",
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_safe_tree(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in _SENSITIVE_PRICE_KEYS:
                raise ProviderRequestBlocked(
                    "provider_price_snapshot_sensitive",
                    "Price snapshot contains a prohibited key.",
                )
            _validate_safe_tree(item, path=f"{path}.{key}")
        return
    raise ProviderRequestBlocked(
        "provider_price_snapshot_invalid",
        f"{path} contains an unsupported value.",
    )


def _validate_request_body_tree(value: object, *, path: str = "request_body") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ProviderRequestBlocked(
            "provider_request_body_invalid",
            f"{path} contains a non-finite number.",
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_request_body_tree(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in _SENSITIVE_PRICE_KEYS:
                raise ProviderRequestBlocked(
                    "provider_request_body_sensitive",
                    "Request body contains a prohibited credential-bearing key.",
                )
            _validate_request_body_tree(item, path=f"{path}.{key}")
        return
    raise ProviderRequestBlocked(
        "provider_request_body_invalid",
        f"{path} contains an unsupported value.",
    )


def _bounded_label(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ProviderRequestBlocked(
            "provider_request_metadata_invalid",
            f"{field} is empty, too long, or contains control characters.",
        )
    return normalized


def unavailable_price_snapshot() -> schemas.ProviderPriceSnapshot:
    return schemas.ProviderPriceSnapshot(
        schema_version="dronedream.provider-price-snapshot/v1",
        source="unavailable",
    )


def _price_payload(
    snapshot: schemas.ProviderPriceSnapshot,
) -> tuple[dict[str, Any], str]:
    payload = snapshot.model_dump(mode="json")
    _validate_safe_tree(payload)
    encoded = canonical_json(payload)
    return payload, sha256_text(encoded)


def _turn_receipt(
    db: Session,
    job: models.Job,
    cognitive_turn_receipt_id: str,
) -> models.HarnessCognitiveTurnReceipt:
    turn = db.get(models.HarnessCognitiveTurnReceipt, cognitive_turn_receipt_id)
    if turn is None or turn.job_id != job.id:
        raise ProviderRequestBlocked(
            "cognitive_turn_receipt_missing",
            "Provider request is not bound to this Job cognitive turn.",
        )
    if turn.outcome is not None:
        raise ProviderRequestBlocked(
            "cognitive_turn_already_finalized",
            "A finalized cognitive turn cannot send another provider request.",
        )
    return turn


def begin_provider_network_request(
    db: Session,
    job: models.Job,
    *,
    cognitive_turn_receipt_id: str,
    request_index: int,
    request_kind: RequestKind,
    provider: str,
    model_snapshot: str,
    api_surface: str,
    base_url: str,
    region: str | None,
    temperature: float | None,
    top_p: float | None,
    provider_seed: int | None,
    response_schema_sha256: str,
    prompt_sha256: str,
    tool_outputs_sha256: str,
    request_body: Mapping[str, Any],
    price_snapshot: schemas.ProviderPriceSnapshot,
) -> ProviderRequestAttempt:
    """Atomically consume one Job request slot and commit before network I/O."""

    turn = _turn_receipt(db, job, cognitive_turn_receipt_id)
    if not 1 <= request_index <= MAX_PROVIDER_NETWORK_REQUESTS_PER_TURN:
        raise ProviderRequestBlocked(
            "provider_request_index_invalid",
            "Per-turn provider request index is outside the absolute cap.",
        )
    if request_kind not in _REQUEST_KINDS:
        raise ProviderRequestBlocked(
            "provider_request_kind_invalid",
            "Provider request kind is not recognized.",
        )
    normalized_provider = _bounded_label(provider, field="provider", maximum=64)
    normalized_api_surface = _bounded_label(
        api_surface,
        field="api_surface",
        maximum=64,
    )
    normalized_region = (
        _bounded_label(region, field="region", maximum=64)
        if region is not None and region.strip()
        else None
    )
    if temperature is not None and (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(float(temperature))
        or not 0 <= float(temperature) <= 2
    ):
        raise ProviderRequestBlocked(
            "provider_temperature_invalid",
            "Provider temperature is outside the supported finite range.",
        )
    if top_p is not None and (
        isinstance(top_p, bool)
        or not isinstance(top_p, (int, float))
        or not math.isfinite(float(top_p))
        or not 0 < float(top_p) <= 1
    ):
        raise ProviderRequestBlocked(
            "provider_top_p_invalid",
            "Provider top_p is outside the supported finite range.",
        )
    if provider_seed is not None and (
        isinstance(provider_seed, bool) or not isinstance(provider_seed, int)
    ):
        raise ProviderRequestBlocked(
            "provider_seed_invalid",
            "Provider seed must be an integer when supplied.",
        )
    if model_snapshot != turn.model_snapshot:
        raise ProviderRequestBlocked(
            "provider_model_drift",
            "Network request model differs from the frozen cognitive turn.",
        )
    schema_hash = _strict_sha256(
        response_schema_sha256,
        field="response_schema_sha256",
    )
    prompt_hash = _strict_sha256(prompt_sha256, field="prompt_sha256")
    tool_hash = _strict_sha256(
        tool_outputs_sha256,
        field="tool_outputs_sha256",
    )
    if (
        schema_hash != turn.schema_sha256
        or prompt_hash != turn.prompt_sha256
        or tool_hash != turn.tool_outputs_sha256
    ):
        raise ProviderRequestBlocked(
            "provider_request_contract_drift",
            "Network request hashes differ from the frozen cognitive turn.",
        )
    normalized_url = _normalize_base_url(base_url)
    _validate_request_body_tree(request_body)
    try:
        request_json = canonical_json(dict(request_body))
    except (TypeError, ValueError) as exc:
        raise ProviderRequestBlocked(
            "provider_request_body_invalid",
            "Provider request body cannot be encoded as canonical JSON.",
        ) from exc
    request_body_hash = sha256_text(request_json)
    price_payload, price_hash = _price_payload(price_snapshot)

    existing = list(
        db.scalars(
            select(models.ProviderNetworkRequestReceipt)
            .where(
                models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
                == turn.id
            )
            .order_by(models.ProviderNetworkRequestReceipt.request_index)
        )
    )
    if request_index != len(existing) + 1:
        raise ProviderRequestBlocked(
            "provider_request_sequence_invalid",
            "Provider request indexes must be contiguous and server-observed.",
        )
    if any(item.outcome is None for item in existing):
        raise ProviderRequestPending()
    if request_index == 1 and request_kind != "primary":
        raise ProviderRequestBlocked(
            "provider_request_kind_invalid",
            "The first actual request must be primary.",
        )
    if request_index > 1:
        previous = existing[-1]
        if request_kind == "primary":
            raise ProviderRequestBlocked(
                "provider_request_kind_invalid",
                "Only the first actual request may be primary.",
            )
        if previous.outcome is None:  # pragma: no cover - guarded above
            raise ProviderRequestPending()
        if previous.outcome.status != "failed":
            raise ProviderRequestBlocked(
                "provider_request_retry_not_allowed",
                "Only a failed actual request may authorize another request.",
            )
        if request_kind == "retry":
            retry_count = sum(item.request_kind == "retry" for item in existing)
            if retry_count >= job.provider_max_retries:
                raise ProviderRequestBlocked(
                    "provider_retry_cap_exhausted",
                    "The Job explicit provider retry cap is exhausted.",
                )
            if request_body_hash != previous.request_body_sha256:
                raise ProviderRequestBlocked(
                    "provider_retry_body_drift",
                    "A retry must preserve the exact request body.",
                )
        elif request_kind == "compatibility_fallback":
            if any(
                item.request_kind == "compatibility_fallback" for item in existing
            ):
                raise ProviderRequestBlocked(
                    "provider_fallback_already_consumed",
                    "Only one compatibility fallback is allowed per cognitive turn.",
                )
            if previous.outcome.error_code != "unsupported_response_format":
                raise ProviderRequestBlocked(
                    "provider_fallback_not_authorized",
                    "Compatibility fallback requires an explicit unsupported-format failure.",
                )
            if request_body_hash == previous.request_body_sha256:
                raise ProviderRequestBlocked(
                    "provider_fallback_body_unchanged",
                    "Compatibility fallback must remove the unsupported request feature.",
                )

    absolute_cap = min(
        MAX_PROVIDER_NETWORK_REQUESTS_PER_JOB,
        max(0, int(job.provider_request_cap)),
    )
    claimed = db.execute(
        update(models.Job)
        .where(
            models.Job.id == job.id,
            models.Job.provider_requests_attempted < absolute_cap,
        )
        .values(
            provider_requests_attempted=(
                models.Job.provider_requests_attempted + 1
            )
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(claimed, "rowcount", None) != 1:
        raise ProviderRequestBlocked(
            "provider_request_cap_exhausted",
            "Job actual provider-request cap is exhausted.",
        )
    receipt = models.ProviderNetworkRequestReceipt(
        cognitive_turn_receipt_id=turn.id,
        receipt_schema=PROVIDER_REQUEST_ATTEMPT_SCHEMA,
        request_index=request_index,
        request_kind=request_kind,
        retry_policy_version=PROVIDER_RETRY_POLICY_VERSION,
        provider=normalized_provider,
        model_snapshot=model_snapshot,
        api_surface=normalized_api_surface,
        base_url_normalized=normalized_url,
        base_url_sha256=sha256_text(normalized_url),
        region=normalized_region,
        temperature=None if temperature is None else float(temperature),
        top_p=None if top_p is None else float(top_p),
        provider_seed=provider_seed,
        response_schema_sha256=schema_hash,
        prompt_sha256=prompt_hash,
        tool_outputs_sha256=tool_hash,
        request_body_sha256=request_body_hash,
        input_utf8_bytes=len(request_json.encode("utf-8")),
        price_snapshot_json=price_payload,
        price_snapshot_sha256=price_hash,
    )
    db.add(receipt)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ProviderRequestBlocked(
            "provider_request_concurrency_conflict",
            "Concurrent provider request accounting collided before network I/O.",
        ) from exc
    db.refresh(job)
    db.refresh(receipt)
    return ProviderRequestAttempt(
        receipt_id=receipt.id,
        cognitive_turn_receipt_id=turn.id,
        request_index=request_index,
    )


def _usage_value(value: int | None, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderRequestBlocked(
            "provider_usage_invalid",
            f"{field} must be a non-negative integer when supplied.",
        )
    return value


def _provider_cost(
    receipt: models.ProviderNetworkRequestReceipt,
    usage: ProviderUsage,
) -> int | None:
    # JSON persistence intentionally turns datetimes into ISO strings. Parse
    # that trusted, schema-bounded representation without relaxing the public
    # request model itself.
    snapshot = schemas.ProviderPriceSnapshot.model_validate(
        receipt.price_snapshot_json,
        strict=False,
    )
    if snapshot.source != "preregistered":
        return None
    input_tokens = _usage_value(usage.input_tokens, field="input_tokens")
    output_tokens = _usage_value(usage.output_tokens, field="output_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    input_rate = snapshot.input_microusd_per_million_tokens
    output_rate = snapshot.output_microusd_per_million_tokens
    if input_rate is None or output_rate is None:  # pragma: no cover - schema guards
        return None
    numerator = input_tokens * input_rate + output_tokens * output_rate
    return (numerator + 999_999) // 1_000_000


def finish_provider_network_request(
    db: Session,
    job: models.Job,
    attempt: ProviderRequestAttempt,
    *,
    status: RequestOutcomeStatus,
    response_content: str | bytes | None = None,
    usage: ProviderUsage | None = None,
    latency_ms: int,
    error_code: str | None = None,
) -> RequestOutcomeStatus:
    """Append one terminal transport outcome and update Job counters."""

    receipt = db.get(models.ProviderNetworkRequestReceipt, attempt.receipt_id)
    if receipt is None or receipt.cognitive_turn_receipt_id != attempt.cognitive_turn_receipt_id:
        raise ProviderRequestBlocked(
            "provider_request_receipt_missing",
            "Provider request receipt is missing or mismatched.",
        )
    turn = db.get(models.HarnessCognitiveTurnReceipt, receipt.cognitive_turn_receipt_id)
    if turn is None or turn.job_id != job.id:
        raise ProviderRequestBlocked(
            "provider_request_job_mismatch",
            "Provider request receipt belongs to another Job.",
        )
    if receipt.outcome is not None:
        raise ProviderRequestBlocked(
            "provider_request_outcome_exists",
            "Provider request outcome is append-only.",
        )
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, int) or latency_ms < 0:
        raise ProviderRequestBlocked(
            "provider_latency_invalid",
            "Provider latency must be a non-negative integer millisecond count.",
        )
    if status == "succeeded" and response_content is None:
        raise ProviderRequestBlocked(
            "provider_response_missing",
            "A succeeded provider request requires response bytes.",
        )
    response_bytes = (
        response_content.encode("utf-8")
        if isinstance(response_content, str)
        else response_content or b""
    )
    supplied_usage = usage or ProviderUsage()
    input_tokens = _usage_value(supplied_usage.input_tokens, field="input_tokens")
    output_tokens = _usage_value(supplied_usage.output_tokens, field="output_tokens")
    total_tokens = _usage_value(supplied_usage.total_tokens, field="total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if (
        total_tokens is not None
        and input_tokens is not None
        and output_tokens is not None
        and total_tokens < input_tokens + output_tokens
    ):
        raise ProviderRequestBlocked(
            "provider_usage_invalid",
            "total_tokens cannot be smaller than input plus output tokens.",
        )
    outcome = models.ProviderNetworkRequestOutcome(
        request_receipt_id=receipt.id,
        outcome_schema=PROVIDER_REQUEST_OUTCOME_SCHEMA,
        status=status,
        response_sha256=(
            hashlib.sha256(response_bytes).hexdigest()
            if response_content is not None
            else None
        ),
        output_utf8_bytes=len(response_bytes),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_cost_microusd=_provider_cost(receipt, supplied_usage),
        latency_ms=latency_ms,
        error_code=error_code[:64] if error_code else None,
    )
    db.add(outcome)
    if status == "succeeded":
        updated = db.execute(
            update(models.Job)
            .where(
                models.Job.id == job.id,
                models.Job.provider_requests_succeeded
                < models.Job.provider_requests_attempted,
            )
            .values(
                provider_requests_succeeded=(
                    models.Job.provider_requests_succeeded + 1
                )
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", None) != 1:
            raise ProviderRequestBlocked(
                "provider_request_accounting_invalid",
                "Succeeded request accounting would exceed attempts.",
            )
    db.commit()
    db.refresh(job)
    return status


def recover_abandoned_provider_requests(
    db: Session,
    job: models.Job,
    *,
    cognitive_turn_receipt_id: str,
    request_timeout_seconds: float,
    now: datetime | None = None,
) -> int:
    """Seal stale no-outcome requests as indeterminate without replay."""

    if not math.isfinite(request_timeout_seconds) or request_timeout_seconds <= 0:
        raise ProviderRequestBlocked(
            "provider_timeout_invalid",
            "Provider timeout must be a positive finite number.",
        )
    _turn_receipt(db, job, cognitive_turn_receipt_id)
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        observed_now = observed_now.replace(tzinfo=timezone.utc)
    deadline_delta = timedelta(seconds=request_timeout_seconds + 60)
    pending = list(
        db.scalars(
            select(models.ProviderNetworkRequestReceipt)
            .where(
                models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
                == cognitive_turn_receipt_id,
                ~models.ProviderNetworkRequestReceipt.outcome.has(),
            )
            .order_by(models.ProviderNetworkRequestReceipt.request_index)
        )
    )
    sealed = 0
    for receipt in pending:
        attempted_at = receipt.attempted_at
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        if observed_now.astimezone(timezone.utc) < (
            attempted_at.astimezone(timezone.utc) + deadline_delta
        ):
            continue
        finish_provider_network_request(
            db,
            job,
            ProviderRequestAttempt(
                receipt_id=receipt.id,
                cognitive_turn_receipt_id=cognitive_turn_receipt_id,
                request_index=receipt.request_index,
            ),
            status="indeterminate",
            latency_ms=max(
                0,
                int(
                    (
                        observed_now.astimezone(timezone.utc)
                        - attempted_at.astimezone(timezone.utc)
                    ).total_seconds()
                    * 1000
                ),
            ),
            error_code="provider_outcome_indeterminate",
        )
        sealed += 1
    return sealed


def provider_request_counts_for_turn(
    db: Session,
    *,
    cognitive_turn_receipt_id: str,
) -> tuple[int, int]:
    attempted = db.scalar(
        select(func.count(models.ProviderNetworkRequestReceipt.id)).where(
            models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
            == cognitive_turn_receipt_id
        )
    )
    succeeded = db.scalar(
        select(func.count(models.ProviderNetworkRequestOutcome.id))
        .join(models.ProviderNetworkRequestReceipt)
        .where(
            models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
            == cognitive_turn_receipt_id,
            models.ProviderNetworkRequestOutcome.status == "succeeded",
        )
    )
    return int(attempted or 0), int(succeeded or 0)


def provider_request_outcome_pending(
    db: Session,
    *,
    cognitive_turn_receipt_id: str,
) -> bool:
    pending = db.scalar(
        select(models.ProviderNetworkRequestReceipt.id).where(
            models.ProviderNetworkRequestReceipt.cognitive_turn_receipt_id
            == cognitive_turn_receipt_id,
            ~models.ProviderNetworkRequestReceipt.outcome.has(),
        )
    )
    return pending is not None


__all__ = [
    "MAX_PROVIDER_NETWORK_REQUESTS_PER_JOB",
    "MAX_PROVIDER_NETWORK_REQUESTS_PER_TURN",
    "PROVIDER_REQUEST_ATTEMPT_SCHEMA",
    "PROVIDER_REQUEST_OUTCOME_SCHEMA",
    "PROVIDER_RETRY_POLICY_VERSION",
    "BoundProviderRequestAccountant",
    "ProviderRequestAttempt",
    "ProviderRequestBlocked",
    "ProviderRequestPending",
    "ProviderUsage",
    "RequestKind",
    "begin_provider_network_request",
    "finish_provider_network_request",
    "provider_request_counts_for_turn",
    "provider_request_outcome_pending",
    "recover_abandoned_provider_requests",
    "unavailable_price_snapshot",
]
