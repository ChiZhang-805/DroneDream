from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


@pytest.fixture()
def provider_db(tmp_path: Path) -> Iterator[SimpleNamespace]:
    from app import models, schemas
    from app.db import Base, _build_engine

    engine = _build_engine(f"sqlite:///{tmp_path / 'provider-accounting.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for statement in (
            """
            CREATE TRIGGER trg_provider_network_request_receipts_no_update
            BEFORE UPDATE ON provider_network_request_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'provider network request receipts are append-only'
                );
            END
            """,
            """
            CREATE TRIGGER trg_provider_network_request_receipts_no_delete
            BEFORE DELETE ON provider_network_request_receipts
            WHEN NOT EXISTS (
                SELECT 1 FROM harness_cognitive_turn_delete_authorizations
                WHERE receipt_id = OLD.cognitive_turn_receipt_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'provider network request receipts are append-only'
                );
            END
            """,
            """
            CREATE TRIGGER trg_provider_network_request_outcomes_no_update
            BEFORE UPDATE ON provider_network_request_outcomes
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'provider network request outcomes are append-only'
                );
            END
            """,
            """
            CREATE TRIGGER trg_provider_network_request_outcomes_no_delete
            BEFORE DELETE ON provider_network_request_outcomes
            WHEN NOT EXISTS (
                SELECT 1
                FROM harness_cognitive_turn_delete_authorizations AS authorization
                JOIN provider_network_request_receipts AS receipt
                  ON receipt.cognitive_turn_receipt_id = authorization.receipt_id
                WHERE receipt.id = OLD.request_receipt_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'provider network request outcomes are append-only'
                );
            END
            """,
        ):
            connection.execute(text(statement))
    try:
        yield SimpleNamespace(engine=engine, models=models, schemas=schemas)
    finally:
        engine.dispose()


def _create_job_and_turn(
    db: Session,
    provider_db: SimpleNamespace,
    *,
    request_cap: int = 8,
    max_retries: int = 1,
) -> tuple[Any, Any]:
    models = provider_db.models
    job = models.Job(
        track_type="circle",
        altitude_m=3.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        status="RUNNING",
        simulator_backend_requested="mock",
        optimizer_strategy="llm_harness",
        max_iterations=2,
        max_total_trials=64,
        provider_turn_cap=8,
        provider_request_cap=request_cap,
        provider_max_retries=max_retries,
        openai_model="gpt-4.1-2025-04-14",
    )
    db.add(job)
    db.flush()
    turn = models.HarnessCognitiveTurnReceipt(
        job_id=job.id,
        receipt_schema="dronedream.harness-cognitive-turn-attempt/v1",
        generation_index=1,
        turn_index=1,
        turn_role="plan",
        trigger_policy_version="adaptive-trigger-v1",
        trigger_reasons_json=["test"],
        source_commit="1" * 40,
        model_snapshot="gpt-4.1-2025-04-14",
        prompt_sha256="a" * 64,
        evidence_sha256="b" * 64,
        schema_sha256="c" * 64,
        tool_outputs_sha256="d" * 64,
    )
    db.add(turn)
    db.commit()
    db.refresh(job)
    db.refresh(turn)
    return job, turn


def _price(provider_db: SimpleNamespace, *, available: bool = False) -> Any:
    if not available:
        return provider_db.schemas.ProviderPriceSnapshot(
            schema_version="dronedream.provider-price-snapshot/v1",
            source="unavailable",
        )
    return provider_db.schemas.ProviderPriceSnapshot(
        schema_version="dronedream.provider-price-snapshot/v1",
        source="preregistered",
        input_microusd_per_million_tokens=2_000_000,
        output_microusd_per_million_tokens=8_000_000,
        effective_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def _begin(
    module: Any,
    db: Session,
    provider_db: SimpleNamespace,
    job: Any,
    turn: Any,
    *,
    index: int,
    kind: Literal["primary", "retry", "compatibility_fallback"],
    body: dict[str, Any] | None = None,
) -> Any:
    return module.begin_provider_network_request(
        db,
        job,
        cognitive_turn_receipt_id=turn.id,
        request_index=index,
        request_kind=kind,
        provider="openai",
        model_snapshot=turn.model_snapshot,
        api_surface="chat_completions",
        base_url="https://api.openai.com/v1/",
        region=None,
        temperature=0,
        top_p=1,
        provider_seed=20260804,
        response_schema_sha256=turn.schema_sha256,
        prompt_sha256=turn.prompt_sha256,
        tool_outputs_sha256=turn.tool_outputs_sha256,
        request_body=body
        or {
            "model": turn.model_snapshot,
            "messages": ["hashed-before-persistence"],
            "response_format": "json_schema",
        },
        price_snapshot=_price(provider_db, available=True),
    )


def test_request_is_committed_before_io_and_success_is_separate(
    provider_db: SimpleNamespace,
) -> None:
    from app.orchestration import provider_request_accounting as accounting

    with Session(provider_db.engine) as db:
        job, turn = _create_job_and_turn(db, provider_db)
        attempt = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=1,
            kind="primary",
        )
        assert job.provider_requests_attempted == 1
        assert job.provider_requests_succeeded == 0
        receipt = db.get(provider_db.models.ProviderNetworkRequestReceipt, attempt.receipt_id)
        assert receipt is not None
        assert receipt.outcome is None
        assert receipt.base_url_normalized == "https://api.openai.com/v1"
        assert "messages" not in receipt.__dict__
        assert "api_key" not in str(receipt.__dict__).lower()

        status = accounting.finish_provider_network_request(
            db,
            job,
            attempt,
            status="succeeded",
            response_content='{"ok":true}',
            usage=accounting.ProviderUsage(
                input_tokens=100,
                output_tokens=10,
                total_tokens=110,
            ),
            latency_ms=321,
        )
        assert status == "succeeded"
        assert job.provider_requests_attempted == 1
        assert job.provider_requests_succeeded == 1
        db.refresh(receipt)
        assert receipt.outcome is not None
        assert receipt.outcome.provider_cost_microusd == 280
        assert receipt.outcome.output_utf8_bytes == len(b'{"ok":true}')
        assert accounting.provider_request_counts_for_turn(
            db,
            cognitive_turn_receipt_id=turn.id,
        ) == (1, 1)

        with pytest.raises(DBAPIError):
            db.execute(
                text(
                    "UPDATE provider_network_request_receipts "
                    "SET provider='changed' WHERE id=:receipt_id"
                ),
                {"receipt_id": receipt.id},
            )
            db.commit()
        db.rollback()


def test_retry_and_compatibility_fallback_are_explicit_and_bounded(
    provider_db: SimpleNamespace,
) -> None:
    from app.orchestration import provider_request_accounting as accounting

    with Session(provider_db.engine) as db:
        job, turn = _create_job_and_turn(db, provider_db, max_retries=1)
        body = {"messages": ["same"], "response_format": "json_schema"}
        first = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=1,
            kind="primary",
            body=body,
        )
        accounting.finish_provider_network_request(
            db,
            job,
            first,
            status="failed",
            latency_ms=20,
            error_code="transport_error",
        )
        retry = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=2,
            kind="retry",
            body=body,
        )
        accounting.finish_provider_network_request(
            db,
            job,
            retry,
            status="failed",
            latency_ms=25,
            error_code="unsupported_response_format",
        )
        fallback = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=3,
            kind="compatibility_fallback",
            body={"messages": ["same"]},
        )
        accounting.finish_provider_network_request(
            db,
            job,
            fallback,
            status="succeeded",
            response_content="{}",
            latency_ms=30,
        )
        assert job.provider_requests_attempted == 3
        assert job.provider_requests_succeeded == 1
        assert [item.request_kind for item in turn.network_requests] == [
            "primary",
            "retry",
            "compatibility_fallback",
        ]
        with pytest.raises(accounting.ProviderRequestBlocked) as after_success:
            _begin(
                accounting,
                db,
                provider_db,
                job,
                turn,
                index=4,
                kind="retry",
                body={"messages": ["same"]},
            )
        assert after_success.value.code == "provider_request_retry_not_allowed"


def test_cap_hash_drift_and_pending_attempt_fail_before_io(
    provider_db: SimpleNamespace,
) -> None:
    from app.orchestration import provider_request_accounting as accounting

    with Session(provider_db.engine) as db:
        job, turn = _create_job_and_turn(db, provider_db, request_cap=1)
        with pytest.raises(accounting.ProviderRequestBlocked) as drift:
            accounting.begin_provider_network_request(
                db,
                job,
                cognitive_turn_receipt_id=turn.id,
                request_index=1,
                request_kind="primary",
                provider="openai",
                model_snapshot=turn.model_snapshot,
                api_surface="chat_completions",
                base_url="https://api.openai.com/v1",
                region=None,
                temperature=0,
                top_p=1,
                provider_seed=None,
                response_schema_sha256="e" * 64,
                prompt_sha256=turn.prompt_sha256,
                tool_outputs_sha256=turn.tool_outputs_sha256,
                request_body={"safe": True},
                price_snapshot=_price(provider_db),
            )
        assert drift.value.code == "provider_request_contract_drift"
        assert job.provider_requests_attempted == 0

        with pytest.raises(accounting.ProviderRequestBlocked) as sensitive:
            accounting.begin_provider_network_request(
                db,
                job,
                cognitive_turn_receipt_id=turn.id,
                request_index=1,
                request_kind="primary",
                provider="openai",
                model_snapshot=turn.model_snapshot,
                api_surface="chat_completions",
                base_url="https://api.openai.com/v1",
                region=None,
                temperature=0,
                top_p=1,
                provider_seed=None,
                response_schema_sha256=turn.schema_sha256,
                prompt_sha256=turn.prompt_sha256,
                tool_outputs_sha256=turn.tool_outputs_sha256,
                request_body={"api_key": "must-never-be-persisted"},
                price_snapshot=_price(provider_db),
            )
        assert sensitive.value.code == "provider_request_body_sensitive"
        assert job.provider_requests_attempted == 0

        first = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=1,
            kind="primary",
        )
        with pytest.raises(accounting.ProviderRequestPending):
            _begin(
                accounting,
                db,
                provider_db,
                job,
                turn,
                index=2,
                kind="retry",
            )
        accounting.finish_provider_network_request(
            db,
            job,
            first,
            status="failed",
            latency_ms=10,
            error_code="transport_error",
        )
        with pytest.raises(accounting.ProviderRequestBlocked) as exhausted:
            _begin(
                accounting,
                db,
                provider_db,
                job,
                turn,
                index=2,
                kind="retry",
            )
        assert exhausted.value.code == "provider_request_cap_exhausted"
        db.rollback()


def test_stale_attempt_becomes_indeterminate_and_is_never_replayed(
    provider_db: SimpleNamespace,
) -> None:
    from app.orchestration import provider_request_accounting as accounting

    with Session(provider_db.engine) as db:
        job, turn = _create_job_and_turn(db, provider_db)
        attempt = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=1,
            kind="primary",
        )
        receipt = db.get(provider_db.models.ProviderNetworkRequestReceipt, attempt.receipt_id)
        assert receipt is not None
        attempted_at = receipt.attempted_at
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        assert (
            accounting.recover_abandoned_provider_requests(
                db,
                job,
                cognitive_turn_receipt_id=turn.id,
                request_timeout_seconds=10,
                now=attempted_at + timedelta(seconds=69),
            )
            == 0
        )
        assert (
            accounting.recover_abandoned_provider_requests(
                db,
                job,
                cognitive_turn_receipt_id=turn.id,
                request_timeout_seconds=10,
                now=attempted_at + timedelta(seconds=71),
            )
            == 1
        )
        db.refresh(receipt)
        assert receipt.outcome is not None
        assert receipt.outcome.status == "indeterminate"
        with pytest.raises(accounting.ProviderRequestBlocked) as no_replay:
            _begin(
                accounting,
                db,
                provider_db,
                job,
                turn,
                index=2,
                kind="retry",
            )
        assert no_replay.value.code == "provider_request_retry_not_allowed"


def test_authorized_job_delete_cascades_request_receipts(
    provider_db: SimpleNamespace,
) -> None:
    from app.orchestration import provider_request_accounting as accounting

    with Session(provider_db.engine) as db:
        job, turn = _create_job_and_turn(db, provider_db)
        job_id = job.id
        attempt = _begin(
            accounting,
            db,
            provider_db,
            job,
            turn,
            index=1,
            kind="primary",
        )
        accounting.finish_provider_network_request(
            db,
            job,
            attempt,
            status="failed",
            latency_ms=1,
            error_code="test_failure",
        )
        db.add(
            provider_db.models.HarnessCognitiveTurnDeleteAuthorization(
                receipt_id=turn.id,
                reason="job_delete",
            )
        )
        db.flush()
        db.delete(job)
        db.commit()
        assert db.get(provider_db.models.Job, job_id) is None
        assert (
            db.scalar(
                text("SELECT count(*) FROM provider_network_request_receipts")
            )
            == 0
        )
